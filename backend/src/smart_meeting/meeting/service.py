"""Meeting lifecycle: capture -> utterances -> transcription -> storage -> analysis.

Everything runs in the asyncio loop except Whisper, which runs in a single worker thread so
utterances from both sources are transcribed one at a time, in arrival order.
"""

import asyncio
import faulthandler
import itertools
import json
import logging
import math
import re
import shutil
import sys
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np

from smart_meeting.audio.backend import AudioBackend, Capture, PermissionNeeded, get_backend
from smart_meeting.audio.decode import decode_audio
from smart_meeting.audio.segmenter import Utterance, UtteranceSegmenter, silero_vad
from smart_meeting.config import Settings
from smart_meeting.db import Database, now_iso
from smart_meeting.llm.analysis import MeetingNotes, OllamaClient, format_transcript
from smart_meeting.meeting import echo, safety
from smart_meeting.meeting.events import EventHub
from smart_meeting.messages import tr
from smart_meeting.models import (
    AiEstimates,
    CapturedDevice,
    Meeting,
    MeetingStatus,
    Segment,
    Source,
    StartMeetingRequest,
)
from smart_meeting.preferences import PreferencesStore
from smart_meeting.provision import OllamaProvisioner
from smart_meeting.speakers import MeetingVoices, VoicePrinter, split_by_speaker
from smart_meeting.transcription.base import TranscribedPiece
from smart_meeting.transcription.engines import create_transcriber
from smart_meeting.transcription.language import LanguageTracker
from smart_meeting.watchdog import page_marker_path

logger = logging.getLogger(__name__)

DEVICE_POLL_S = 2.0
# Provisional text of the sentence being spoken: refreshed at most this often, once it is this long.
PARTIAL_INTERVAL_S = 1.0
PARTIAL_MIN_S = 1.0
# A pause this long may end the sentence: its final transcription gets Whisper first.
PARTIAL_PAUSE_S = 0.2
# Time between two provisional texts, as a multiple of the last one's computing time (GPU load).
PARTIAL_LOAD_FACTOR = 1.5
# Speech turns of an imported file, for telling its speakers apart: cut at shorter pauses than
# live sentences, and kept short enough to hold a single voice.
TURN_SILENCE_MS = 300
TURN_MAX_S = 10.0
# How often the progress of the transcription is checked during a meeting
PROGRESS_CHECK_S = 5.0
# Falling behind (seconds of speech waiting): the provisional text is turned off past
# PARTIALS_OFF_S; past LIGHTER_S, still growing over a minute, a lighter model takes over
# (at most once a minute).
KEEP_UP_CHECK_S = 10.0
PARTIALS_OFF_S = 30.0
LIGHTER_S = 90.0
LIGHTER_COOLDOWN_S = 60.0
# Without any open page for this long (time to reload a page), the app stops once idle.
UNUSED_GRACE_S = 10


class ConflictError(Exception):
    pass


MONTHS = {
    "fr": [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}  # fmt: skip


def default_title(at: datetime | None = None, language: str = "fr") -> str:
    """Title of a meeting started without a name: its date and local time."""
    at = at or datetime.now()
    if language == "en":
        month = MONTHS["en"][at.month - 1]
        return f"Meeting on {month} {at.day}, {at.year} at {at.hour}:{at.minute:02d}"
    month = MONTHS["fr"][at.month - 1]
    return f"Réunion du {at.day} {month} {at.year} à {at.hour}h{at.minute:02d}"


def speaker_label(number: int) -> str:
    return tr("speaker_label", n=number)


@dataclass
class SourceStream:
    source: Source
    speaker: str
    # Automatic mode: follow the device applications use instead of a fixed one.
    auto: bool = False
    capture: Capture | None = None
    # Why this source could not be captured (the meeting goes on with the other one), and
    # whether the system needs the user's permission for it
    error: str | None = None
    permission_needed: bool = False
    segmenter: UtteranceSegmenter | None = None
    # Meeting time (s) of the first sample received, to align both sources.
    offset_s: float | None = None
    # Raw audio on disk, in meeting time (see safety.py), and samples received since the
    # capture (re)started
    track: safety.SafetyTrack | None = None
    received: int = 0
    previous_text: str = ""
    language: LanguageTracker = field(default_factory=LanguageTracker)
    peak_rms: float = 0.0
    # Several people on this source: told apart by their voices (else all are `speaker`).
    diarize: bool = False


@dataclass
class Recording:
    meeting_id: int
    started: float  # loop.time() at start
    streams: dict[Source, SourceStream]
    # (source, meeting time of the source's first sample, utterance, its copy on disk)
    queue: asyncio.Queue[tuple[Source, float, Utterance, Path] | None] = field(
        default_factory=asyncio.Queue
    )
    # Serializes device switches with stop().
    device_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    stopping: bool = False
    # Last sentences stored, to drop the echo of one source in the other (see echo.py):
    # (source, start, end, text, segment id)
    recent: deque = field(default_factory=lambda: deque(maxlen=40))
    # Seconds of speech waiting for Whisper, and the provisional text turned off to catch up
    backlog_s: float = 0.0
    partials_off: bool = False
    voices: MeetingVoices = field(default_factory=lambda: MeetingVoices(speaker_label))
    request: StartMeetingRequest | None = None  # options, to resume after a restart


class MeetingService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        hub: EventHub,
        audio: AudioBackend | None = None,
    ) -> None:
        self.settings = settings
        self.preferences = PreferencesStore(settings)
        self.audio = audio or get_backend()
        self.db = db
        self.hub = hub
        self.transcriber = create_transcriber(settings)
        self.voice_printer = VoicePrinter()
        self.voices_error: str | None = None
        self.ollama = OllamaClient(settings)
        self.ollama.during_meeting = lambda: self.active is not None
        self.provisioner = OllamaProvisioner(settings)
        self.whisper_state: Literal["loading", "ready", "error"] = "loading"
        self.whisper_detail: str | None = None
        self.active: Recording | None = None
        self._whisper_ready = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
        # Voice prints in the Whisper thread, never alongside it: numpy matrix products from two
        # threads at once deadlocked OpenBLAS (a live meeting stopped being transcribed).
        self._voice_executor = self._executor
        self._background: set[asyncio.Task[None]] = set()
        self._start_lock = asyncio.Lock()
        self._ask_lock = asyncio.Lock()
        self.ui_connections = 0  # open browser pages (presence WebSockets)
        self._analyses = 0
        self.analysis_started: dict[int, float] = {}  # meeting id -> monotonic start
        self._import_task: asyncio.Task[None] | None = None
        self._import_meeting_id: int | None = None
        self.pending = safety.PendingAudio(settings.data_dir, settings.sample_rate)
        self._voices_loaded = asyncio.Event()
        self._provisioned = asyncio.Event()  # Ollama installed and started (or failed to)
        # Whisper thread computations not finished yet: number -> submitted at (monotonic)
        self._jobs: dict[int, float] = {}
        self._lightening = False  # a lighter model loading: not a stuck transcription
        self._job_numbers = itertools.count()

    # Lifecycle

    def startup(self, resume: dict | None = None, unfinished: list[int] | None = None) -> None:
        """Load Whisper and provision Ollama in the background: the UI is usable meanwhile
        and shows their progress. Then resume the meeting of a restart for a frozen
        transcription, transcribe the sentences a crash left untranscribed, and write again the
        minutes a restart interrupted (`unfinished`)."""
        self._spawn(self._load_whisper())
        self._spawn(self._load_voice_printer())
        self._spawn(self._provision())
        self._spawn(self._recover(resume))
        if unfinished:
            self._spawn(self._analyze_unfinished(unfinished))

    def restart_ai(self) -> None:
        """Restart button of the interface: stop the Ollama we started, then provision again
        (start it, download its model if missing). A system Ollama is left running."""
        self._spawn(self._restart_ai())

    async def _restart_ai(self) -> None:
        await self.provisioner.stop()
        await self.provisioner.run()

    async def _provision(self) -> None:
        try:
            await self.provisioner.run()
        finally:
            self._provisioned.set()
        await self.provisioner.watch()

    async def _analyze_unfinished(self, meeting_ids: list[int]) -> None:
        """Minutes interrupted by a restart, written again once Ollama is set up."""
        await self._provisioned.wait()
        for meeting_id in meeting_ids:
            logger.info("Writing again the minutes of meeting %s, interrupted", meeting_id)
            await self.analyze(meeting_id)

    async def _load_whisper(self) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(self._executor, self.transcriber.load)
        except Exception as exc:
            logger.exception("Whisper failed to load")
            self.whisper_state, self.whisper_detail = "error", str(exc)
            return
        self.whisper_state = "ready"
        self.whisper_detail = f"{self.transcriber.model_name} ({self.transcriber.device})"
        self._whisper_ready.set()
        logger.info("Whisper ready: %s", self.whisper_detail)

    async def _load_voice_printer(self) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(
                self._voice_executor, self.voice_printer.load
            )
        except Exception as exc:
            # Speakers are then not told apart: one label per source, as before.
            logger.warning("Voice prints unavailable", exc_info=True)
            self.voices_error = str(exc)
        finally:
            self._voices_loaded.set()

    async def _whisper_job(self, function: Callable, *args):
        """A computation of the Whisper thread during a meeting, watched by `_watch_progress`."""
        number = next(self._job_numbers)
        self._jobs[number] = time.monotonic()
        try:
            return await asyncio.get_running_loop().run_in_executor(self._executor, function, *args)
        finally:
            del self._jobs[number]

    async def _voice_print(self, audio: np.ndarray) -> np.ndarray | None:
        try:
            return await self._whisper_job(self.voice_printer.embed, audio)
        except Exception:
            logger.warning("Voice print failed", exc_info=True)
            return None

    # Open pages

    def page_opened(self) -> None:
        self.ui_connections += 1
        page_marker_path(self.settings.data_dir).touch()

    def page_closed(self, on_unused: Callable[[], None] | None) -> None:
        """Last page closed: call `on_unused` (stop the app) once nothing is running."""
        self.ui_connections -= 1
        if self.ui_connections == 0 and on_unused:
            self._spawn(self._stop_when_unused(on_unused))

    @property
    def busy(self) -> bool:
        """Work that closing the page must not interrupt."""
        return bool(self.active or self._import_task or self._analyses or self.provisioner.busy)

    async def _stop_when_unused(self, on_unused: Callable[[], None]) -> None:
        await asyncio.sleep(UNUSED_GRACE_S)
        while self.ui_connections == 0:
            if not self.busy:
                logger.info("No page open and nothing running: stopping")
                on_unused()
                return
            await asyncio.sleep(5)

    async def quit(self) -> None:
        """Prepare a user-requested exit: stop the recording and let its transcription finish,
        so nothing said is lost. A pending analysis is interrupted and can be rerun later."""
        if self.active and not self.active.stopping:
            await self.stop(self.active.meeting_id)
        while self.active:
            await asyncio.sleep(0.2)

    async def shutdown(self) -> None:
        if self.active and not self.active.stopping:
            await self.stop(self.active.meeting_id)
        for task in [*self._background, self._import_task]:
            if task:
                task.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        await self.provisioner.stop()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def audio_path(self, meeting_id: int) -> Path:
        return self.settings.audio_dir / str(meeting_id)

    def _set_status(self, meeting_id: int, status: MeetingStatus, **fields: object) -> None:
        self.db.update_meeting(meeting_id, status=status, **fields)
        self.hub.publish(
            meeting_id, {"type": "status", "status": status, "error": fields.get("error")}
        )

    # Recording

    async def start(self, request: StartMeetingRequest) -> Meeting:
        async with self._start_lock:
            return await self._start(request)

    async def _start(
        self,
        request: StartMeetingRequest,
        resume: Meeting | None = None,
        backlog: list[safety.PendingSentence] | None = None,
    ) -> Meeting:
        """Start recording a new meeting, or go on with `resume` after a restart (its sentences
        left untranscribed, `backlog`, come first)."""
        if self.active:
            raise ConflictError(tr("meeting_in_progress"))
        if self.whisper_state == "error":
            raise ConflictError(tr("whisper_unavailable", detail=self.whisper_detail))

        targets: dict[Source, str | None] = {
            "mic": request.mic_device,
            "remote": request.remote_device,
        }
        in_use: dict[Source, str | None] = {}
        if None in targets.values():
            try:
                in_use = dict(
                    zip(("mic", "remote"), await self.audio.resolve_in_use(), strict=True)
                )
            except (OSError, RuntimeError) as exc:
                raise ConflictError(tr("audio_unavailable", error=exc)) from exc

        loop = asyncio.get_running_loop()
        if resume:
            meeting = resume
            started_at = datetime.fromisoformat(resume.started_at)
            elapsed_s = (datetime.now(started_at.tzinfo) - started_at).total_seconds()
        else:
            meeting = self.db.create_meeting(
                request.title.strip() or default_title(language=self.settings.ui_language),
                request.mic_device,
                request.remote_device,
                request.keep_audio,
                language=request.language,
            )
            if request.tags:
                self.db.set_tags(meeting.id, request.tags)
            elapsed_s = 0.0
        recording = Recording(
            meeting_id=meeting.id,
            started=loop.time() - elapsed_s,
            request=request,
            streams={
                # One language per source: I may speak French while the others speak English.
                "mic": SourceStream(
                    "mic", self.settings.user_name, language=self._tracker(request.language)
                ),
                "remote": SourceStream(
                    "remote", self.settings.remote_name, language=self._tracker(request.language)
                ),
            },
        )
        diarize = self.voices_error is None
        recording.streams["remote"].diarize = diarize
        recording.streams["mic"].diarize = diarize and request.room
        for stream in recording.streams.values():
            stream.auto = targets[stream.source] is None
            if stream.auto:
                targets[stream.source] = in_use[stream.source]
            stream.segmenter = self._new_segmenter()
            stream.capture = self._new_capture(recording, stream, targets[stream.source])

        voices_file = self.pending.folder(meeting.id) / "voices.json"
        if resume and voices_file.exists():
            try:
                recording.voices.restore(json.loads(voices_file.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("Could not restore the voices of meeting %s", meeting.id)
        for sentence in backlog or []:
            utterance = Utterance(0, sentence.audio)
            item = (sentence.source, sentence.start_s, utterance, sentence.path)
            recording.queue.put_nowait(item)  # type: ignore[arg-type]

        self.active = recording
        for stream in recording.streams.values():
            try:
                await stream.capture.start()
            except Exception as exc:
                logger.exception("Could not start %s capture", stream.source)
                stream.error = str(exc) or type(exc).__name__
                stream.permission_needed = isinstance(exc, PermissionNeeded)
        if all(stream.error for stream in recording.streams.values()):
            errors = " ; ".join(f"{s.source} : {s.error}" for s in recording.streams.values())
            exc = RuntimeError(tr("no_audio_source", errors=errors))
            await self._abort(recording, exc)
            raise ConflictError(str(exc))
        recording.tasks = [
            asyncio.create_task(self._transcription_worker(recording), name="transcription"),
            asyncio.create_task(self._publish_levels(recording), name="levels"),
            asyncio.create_task(self._follow_devices(recording), name="devices"),
            asyncio.create_task(self._publish_partials(recording), name="partials"),
            asyncio.create_task(self._watch_progress(recording), name="watch"),
            asyncio.create_task(self._keep_up(recording), name="keep-up"),
        ]
        self._publish_devices(recording)
        return meeting

    def _new_segmenter(self) -> UtteranceSegmenter:
        return UtteranceSegmenter(
            silero_vad(),
            sample_rate=self.settings.sample_rate,
            threshold=self.settings.vad_threshold,
            min_silence_ms=self.settings.vad_min_silence_ms,
            max_utterance_s=self.settings.vad_max_utterance_s,
        )

    def _new_capture(
        self, recording: Recording, stream: SourceStream, target: str | None
    ) -> Capture:
        return self.audio.create_capture(
            stream.source,
            target,
            lambda samples: self._on_audio(recording, stream, samples),
            self.settings.sample_rate,
        )

    def captured_devices(self, meeting_id: int) -> dict[Source, CapturedDevice] | None:
        recording = self.active
        if not recording or recording.meeting_id != meeting_id or recording.stopping:
            return None
        return {
            source: CapturedDevice(
                device=stream.capture.target,
                auto=stream.auto,
                error=stream.error,
                permission_needed=stream.permission_needed,
            )
            for source, stream in recording.streams.items()
        }

    def _publish_devices(self, recording: Recording) -> None:
        devices = self.captured_devices(recording.meeting_id) or {}
        self.hub.publish(
            recording.meeting_id,
            {"type": "devices", "devices": {k: v.model_dump() for k, v in devices.items()}},
        )

    async def _follow_devices(self, recording: Recording) -> None:
        """In automatic mode, switch capture when applications move to another device."""
        auto_streams = [s for s in recording.streams.values() if s.auto]
        while auto_streams and not recording.stopping:
            await asyncio.sleep(DEVICE_POLL_S)
            try:
                # No fallback: a call pausing must not send the capture back to the defaults.
                mic, sink = await self.audio.resolve_in_use(fallback_to_defaults=False)
            except (OSError, RuntimeError):
                logger.warning("Could not inspect audio devices", exc_info=True)
                continue
            for stream in auto_streams:
                target = mic if stream.source == "mic" else sink
                if target and target != stream.capture.target:
                    async with recording.device_lock:
                        if not recording.stopping:
                            await self._switch_device(recording, stream, target)

    async def _switch_device(self, recording: Recording, stream: SourceStream, target: str) -> None:
        logger.info("Switching %s capture to %s", stream.source, target)
        await stream.capture.stop()
        self._flush(recording, stream)
        # Fresh timeline for the new device: the offset is re-measured on its first sample.
        stream.segmenter = self._new_segmenter()
        stream.offset_s = None
        stream.capture = self._new_capture(recording, stream, target)
        try:
            await stream.capture.start()
            stream.error, stream.permission_needed = None, False
        except Exception as exc:
            logger.exception("Could not switch %s capture to %s", stream.source, target)
            stream.error = str(exc) or type(exc).__name__
            stream.permission_needed = isinstance(exc, PermissionNeeded)
        self._publish_devices(recording)

    async def _abort(self, recording: Recording, exc: Exception) -> None:
        for stream in recording.streams.values():
            if stream.capture:
                await stream.capture.stop()
            if stream.track:
                stream.track.close()
        self._set_status(recording.meeting_id, MeetingStatus.ERROR, error=str(exc))
        self.active = None

    def _on_audio(self, recording: Recording, stream: SourceStream, samples: np.ndarray) -> None:
        sample_rate = self.settings.sample_rate
        if stream.offset_s is None:
            elapsed = asyncio.get_running_loop().time() - recording.started
            stream.offset_s = max(0.0, elapsed - len(samples) / sample_rate)
            stream.received = 0
        at_s = stream.offset_s + stream.received / sample_rate
        stream.received += len(samples)
        if stream.track is None:
            folder = self.audio_path(recording.meeting_id)
            stream.track = safety.SafetyTrack(folder, stream.source, at_s, sample_rate)
        stream.track.write(samples, at_s)
        stream.peak_rms = max(stream.peak_rms, float(np.sqrt(np.mean(samples**2))))
        for utterance in stream.segmenter.push(samples):
            self._enqueue(recording, stream, utterance)

    def _flush(self, recording: Recording, stream: SourceStream) -> None:
        for utterance in stream.segmenter.flush():
            self._enqueue(recording, stream, utterance)

    def _enqueue(self, recording: Recording, stream: SourceStream, utterance: Utterance) -> None:
        """A sentence for Whisper, first written to disk: a crash or a restart cannot lose it."""
        offset_s = stream.offset_s or 0.0
        start_s = offset_s + utterance.start_s(self.settings.sample_rate)
        path = self.pending.save(recording.meeting_id, stream.source, start_s, utterance.audio)
        recording.backlog_s += len(utterance.audio) / self.settings.sample_rate
        # Kept on disk with its own timeline: it starts at its meeting time
        recording.queue.put_nowait((stream.source, start_s, Utterance(0, utterance.audio), path))

    async def _publish_levels(self, recording: Recording) -> None:
        while True:
            await asyncio.sleep(0.5)
            levels = {}
            for source, stream in recording.streams.items():
                rms, stream.peak_rms = stream.peak_rms, 0.0
                levels[source] = round(20 * math.log10(rms), 1) if rms > 1e-5 else -100.0
            self.hub.publish(
                recording.meeting_id,
                {"type": "levels", "levels": levels, "queue": recording.queue.qsize()},
            )

    async def _publish_partials(self, recording: Recording) -> None:
        """Live provisional text of the sentence being spoken, word after word. Final sentences
        come first: a provisional text is only computed while Whisper has nothing else to do."""
        await self._whisper_ready.wait()
        loop = asyncio.get_running_loop()
        sample_rate = self.settings.sample_rate
        shown: dict[Source, int] = {}  # source -> length of the audio last transcribed
        delay = PARTIAL_INTERVAL_S
        while not recording.stopping:
            await asyncio.sleep(delay)
            delay = PARTIAL_INTERVAL_S
            if recording.partials_off:  # Whisper behind: the final sentences come first
                continue
            for source, stream in recording.streams.items():
                ongoing = stream.segmenter.ongoing()
                if ongoing is None or len(ongoing.audio) < PARTIAL_MIN_S * sample_rate:
                    shown.pop(source, None)
                    continue
                if (
                    not recording.queue.empty()
                    or stream.segmenter.trailing_silence_s >= PARTIAL_PAUSE_S
                    or shown.get(source) == len(ongoing.audio)
                ):
                    continue
                shown[source] = len(ongoing.audio)
                started = loop.time()
                try:
                    text = await self._whisper_job(
                        self.transcriber.transcribe_partial,
                        ongoing.audio,
                        stream.language.language,
                        stream.previous_text,
                    )
                except Exception:
                    logger.exception("Provisional transcription failed")
                    continue
                delay = max(delay, (loop.time() - started) * PARTIAL_LOAD_FACTOR)
                if text:
                    self.hub.publish(
                        recording.meeting_id,
                        {
                            "type": "partial",
                            "source": source,
                            "speaker": recording.voices.current(source) or stream.speaker,
                            "start_s": round(
                                (stream.offset_s or 0.0) + ongoing.start_s(sample_rate), 2
                            ),
                            "text": text,
                        },
                    )

    async def _transcription_worker(self, recording: Recording) -> None:
        await self._whisper_ready.wait()
        while (item := await recording.queue.get()) is not None:
            source, offset_s, utterance, path = item
            await self._transcribe_utterance(
                recording, recording.streams[source], offset_s, utterance
            )
            path.unlink(missing_ok=True)
            seconds = len(utterance.audio) / self.settings.sample_rate
            recording.backlog_s = max(0.0, recording.backlog_s - seconds)

    async def _keep_up(self, recording: Recording) -> None:
        """A transcription slower than speech (a weak GPU, a busy computer) would fall behind for
        good: first stop the provisional text, then switch to a lighter model."""
        loop = asyncio.get_running_loop()
        history: deque[float] = deque(maxlen=round(LIGHTER_COOLDOWN_S / KEEP_UP_CHECK_S) + 1)
        changed = -math.inf
        while not recording.stopping:
            await asyncio.sleep(KEEP_UP_CHECK_S)
            if not self._whisper_ready.is_set():
                continue
            backlog = recording.backlog_s
            history.append(backlog)
            if backlog > PARTIALS_OFF_S and not recording.partials_off:
                recording.partials_off = True
                logger.warning("Transcription %.0f s behind: provisional text off", backlog)
            growing = len(history) == history.maxlen and backlog > history[0]
            now = time.monotonic()
            if backlog < LIGHTER_S or not growing or now - changed < LIGHTER_COOLDOWN_S:
                continue
            changed = now
            history.clear()
            lighten = getattr(self.transcriber, "lighten", None)
            if lighten is None:
                continue
            self._lightening = True
            try:
                detail = await loop.run_in_executor(self._executor, lighten)
            except Exception:
                logger.exception("Could not switch to a lighter transcription")
                detail = None
            finally:
                self._lightening = False
            if detail:
                self.whisper_detail = detail
                logger.warning("Transcription %.0f s behind: now %s", backlog, detail)

    async def _watch_progress(self, recording: Recording) -> None:
        """A Whisper computation that never ends (a stuck library) would silently stop the
        transcription: restart the server, which resumes this meeting."""
        while not recording.stopping:
            await asyncio.sleep(PROGRESS_CHECK_S)
            started = min(self._jobs.values(), default=None)
            if self._lightening:  # loading a lighter model: computations wait for it
                continue
            if started is None or time.monotonic() - started < self.settings.stall_restart_s:
                continue
            logger.error(
                "Transcription stuck for %.0f s (%s sentences waiting): restarting",
                time.monotonic() - started, recording.queue.qsize(),
            )  # fmt: skip
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            self._prepare_resume(recording)
            safety.restart_process()

    def restart_if_recording(self) -> None:
        """Watchdog thread, event loop frozen: restart and resume the meeting being recorded.
        Its sentences waiting for Whisper are already on disk; the one being spoken is lost."""
        recording = self.active
        if recording is None or recording.stopping:
            return
        request = (recording.request or StartMeetingRequest()).model_dump()
        safety.save_resume(self.settings.data_dir, recording.meeting_id, request)
        safety.restart_process()

    def _prepare_resume(self, recording: Recording) -> None:
        folder = self.pending.folder(recording.meeting_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "voices.json").write_text(json.dumps(recording.voices.snapshot()))
        # The sentence being spoken is kept too
        for stream in recording.streams.values():
            self._flush(recording, stream)
            if stream.track:
                stream.track.close()
        request = (recording.request or StartMeetingRequest()).model_dump()
        safety.save_resume(self.settings.data_dir, recording.meeting_id, request)

    async def _recover(self, resume: dict | None) -> None:
        """After a restart: go on recording the resumed meeting, then transcribe what other
        meetings left untranscribed (a crash)."""
        resumed = None
        if resume:  # at once, Whisper loading meanwhile: the capture gap stays short
            meeting = self.db.get_meeting(int(resume["meeting_id"]))
            if meeting and meeting.status == MeetingStatus.RECORDING:
                request = StartMeetingRequest.model_validate(resume["request"])
                logger.info("Resuming meeting %s after a restart", meeting.id)
                async with self._start_lock:
                    try:
                        await self._start(request, meeting, self.pending.load(meeting.id))
                        resumed = meeting.id
                    except Exception:
                        logger.exception("Could not resume meeting %s", meeting.id)
                        self._set_status(meeting.id, MeetingStatus.ERROR, error=tr("interrupted"))
        await self._whisper_ready.wait()
        await self._voices_loaded.wait()
        audio_dirs = self.settings.audio_dir.glob("*") if self.settings.audio_dir.exists() else []
        candidates = {
            *self.pending.meetings(),
            *(int(d.name) for d in audio_dirs if d.name.isdigit()),
        }
        for meeting_id in sorted(candidates - {resumed}):
            meeting = self.db.get_meeting(meeting_id)
            if meeting is None:
                self.pending.remove(meeting_id)
            elif meeting_id in self.pending.meetings() or (
                meeting.status == MeetingStatus.ERROR and meeting.error == tr("interrupted")
            ):
                await self._complete_interrupted(meeting_id)

    async def _complete_interrupted(self, meeting_id: int) -> None:
        """A meeting interrupted by a crash: its sentences left waiting, then the speech of its
        safety tracks that was never transcribed."""
        sentences = self.pending.load(meeting_id)
        logger.info("Completing meeting %s (%s sentences left)", meeting_id, len(sentences))
        # Their voices are not known: numbered after the speakers already in the meeting
        label = re.compile(re.escape(speaker_label(0)).replace("0", r"(\d+)"))
        known = [label.fullmatch(s.speaker or "") for s in self.db.list_segments(meeting_id)]
        first = max((int(m.group(1)) for m in known if m), default=0)
        recording = Recording(
            meeting_id=meeting_id,
            started=0.0,
            voices=MeetingVoices(lambda n: speaker_label(n + first)),
            streams={
                "mic": SourceStream("mic", self.settings.user_name),
                "remote": SourceStream(
                    "remote", self.settings.remote_name, diarize=self.voices_error is None
                ),
            },
        )
        for sentence in sentences:
            stream = recording.streams.get(sentence.source)  # type: ignore[call-overload]
            if stream:
                await self._transcribe_utterance(
                    recording, stream, sentence.start_s, Utterance(0, sentence.audio)
                )
            sentence.path.unlink(missing_ok=True)
        await self._transcribe_missing(recording)
        self._store_speakers(meeting_id, recording.voices)
        self.pending.remove(meeting_id)
        self._drop_tracks(meeting_id)
        # Complete again: the minutes are written with everything that was said
        transcript = format_transcript(self.db.list_segments(meeting_id))
        self._set_status(meeting_id, MeetingStatus.TRANSCRIBED, transcript=transcript, error=None)
        self._spawn(self.analyze(meeting_id))

    async def _transcribe_missing(self, recording: Recording) -> None:
        """Last check of a meeting: speech of the safety tracks with no transcribed sentence
        (lost to a freeze, a restart or a crash) is transcribed and put in its place."""
        loop = asyncio.get_running_loop()
        folder = self.audio_path(recording.meeting_id)
        segments = self.db.list_segments(recording.meeting_id)
        # Every sentence, to recognize the echo of the others that was left out of the microphone
        recording.recent = deque((s.source, s.start_s, s.end_s, s.text, s.id) for s in segments)
        found = 0
        for source, stream in recording.streams.items():
            sentences = [(s.start_s, s.end_s) for s in segments if s.source == source]
            tracks = safety.load_tracks(folder, source)
            if not tracks:
                continue
            missing = await loop.run_in_executor(
                self._executor, safety.missing_speech, tracks, sentences, self._new_segmenter,
                self.settings.sample_rate,
            )  # fmt: skip
            for start_s, audio in missing:
                await self._transcribe_utterance(recording, stream, start_s, Utterance(0, audio))
            found += len(missing)
        if found:
            logger.warning("Meeting %s: %s passages missing from the transcript recovered",
                           recording.meeting_id, found)  # fmt: skip

    def _drop_tracks(self, meeting_id: int) -> None:
        """The safety tracks are only kept when the user keeps the audio."""
        meeting = self.db.get_meeting(meeting_id)
        if meeting and not meeting.keep_audio:
            shutil.rmtree(self.audio_path(meeting_id), ignore_errors=True)

    async def _transcribe_utterance(
        self, recording: Recording, stream: SourceStream, offset_s: float, utterance: Utterance
    ) -> None:
        """Transcribe, store and publish one utterance, with who said it."""
        sample_rate = self.settings.sample_rate
        meeting_id, source = recording.meeting_id, stream.source
        voice_print = (
            asyncio.ensure_future(self._voice_print(utterance.audio)) if stream.diarize else None
        )
        try:
            pieces = await self._whisper_job(
                self.transcriber.transcribe,
                utterance.audio,
                stream.language,
                stream.previous_text,
            )
        except Exception:
            logger.exception("Transcription failed for a %s utterance", source)
            pieces = []
        speaker, spoken = stream.speaker, None
        if voice_print is not None:
            vector = await voice_print
            if pieces:
                duration_s = len(utterance.audio) / sample_rate
                spoken = recording.voices.assign(source, vector, duration_s)
                speaker = recording.voices.name(spoken)
        base = offset_s + utterance.start_s(sample_rate)
        utterance_end = offset_s + utterance.end_s(sample_rate)
        for piece in pieces:
            start_s = round(base + piece.start_s, 2)
            end_s = round(min(base + piece.end_s, utterance_end), 2)
            if self._drop_echo(recording, source, start_s, end_s, piece.text):
                continue
            segment = self.db.add_segment(
                meeting_id,
                Segment(
                    source=source, speaker=speaker, start_s=start_s, end_s=end_s, text=piece.text
                ),
            )
            recording.recent.append((source, start_s, end_s, piece.text, segment.id))
            if spoken is not None and segment.id is not None:
                spoken.segment_ids.append(segment.id)
            self.hub.publish(meeting_id, {"type": "segment", "segment": segment.model_dump()})
        if pieces:
            stream.previous_text = " ".join(p.text for p in pieces)

    def _drop_echo(
        self, recording: Recording, source: Source, start_s: float, end_s: float, text: str
    ) -> bool:
        """The same sentence heard by both sources at the same time: the others' copy is kept.
        True when this one (from the microphone) is the echo; a microphone copy stored before
        is removed when the others' arrives."""
        for other in list(recording.recent):
            other_source, other_start, other_end, other_text, other_id = other
            if other_source == source or not echo.at_same_time(
                (start_s, end_s), (other_start, other_end)
            ):
                continue
            if not echo.is_echo(text, other_text):
                continue
            if source == "mic":
                logger.info("Echo of the others in the microphone dropped: %s", text)
                return True
            logger.info("Echo of the others in the microphone removed: %s", other_text)
            recording.recent.remove(other)
            if other_id is not None:
                self.db.delete_segment(other_id)
                self.hub.publish(recording.meeting_id, {"type": "speakers"})  # reload
        return False

    async def stop(self, meeting_id: int) -> Meeting:
        recording = self.active
        if not recording or recording.meeting_id != meeting_id:
            raise ConflictError(tr("not_recording"))
        if recording.stopping:
            raise ConflictError(tr("already_stopping"))
        recording.stopping = True
        self._set_status(meeting_id, MeetingStatus.TRANSCRIBING, ended_at=now_iso())
        async with recording.device_lock:
            # pw-record flushes what it has; the segmenters then emit any pending speech.
            await asyncio.gather(*(s.capture.stop() for s in recording.streams.values()))
        for stream in recording.streams.values():
            self._flush(recording, stream)
            if stream.track:
                stream.track.close()
        recording.queue.put_nowait(None)
        self._spawn(self._finish(recording))
        meeting = self.db.get_meeting(meeting_id)
        assert meeting is not None
        return meeting

    async def _finish(self, recording: Recording) -> None:
        worker, *helpers = recording.tasks
        for task in helpers:
            task.cancel()
        try:
            await worker  # drain the transcription backlog
        finally:
            self.active = None
        meeting_id = recording.meeting_id
        await self._transcribe_missing(recording)
        self.pending.remove(meeting_id)  # everything is transcribed
        self._drop_tracks(meeting_id)
        self._store_speakers(meeting_id, recording.voices)
        transcript = format_transcript(self.db.list_segments(meeting_id))
        self._set_status(meeting_id, MeetingStatus.TRANSCRIBED, transcript=transcript)
        await self.analyze(meeting_id)

    def _store_speakers(self, meeting_id: int, voices: MeetingVoices) -> None:
        """Final speakers, after regrouping the voices: the pages reload the transcript."""
        if not voices.spoken:
            return
        self.db.set_speakers(voices.regroup())
        self.hub.publish(meeting_id, {"type": "speakers"})

    def rename_speaker(self, meeting_id: int, old: str, new: str) -> None:
        """Name a speaker ("Speaker 2" -> "Paul"); an existing name merges both."""
        new = new.strip()
        self.db.rename_speaker(meeting_id, old, new)
        recording = self.active
        if recording and recording.meeting_id == meeting_id:
            recording.voices.rename(old, new)
            for stream in recording.streams.values():
                if stream.speaker == old:
                    stream.speaker = new
        meeting = self.db.get_meeting(meeting_id)
        if meeting and meeting.status not in (MeetingStatus.RECORDING, MeetingStatus.TRANSCRIBING):
            # Full text kept for the search
            transcript = format_transcript(self.db.list_segments(meeting_id))
            self.db.update_meeting(meeting_id, transcript=transcript)
        self.hub.publish(meeting_id, {"type": "speakers"})

    # File import

    def _tracker(self, choice: str) -> LanguageTracker:
        return LanguageTracker.for_choice(choice, fallback=self.settings.whisper_fallback_language)

    async def import_file(
        self, title: str, path: Path, filename: str, language: str = "auto"
    ) -> Meeting:
        """Transcribe an audio/video file (decoded by PyAV), then analyze it like a meeting."""
        async with self._start_lock:
            if self.active:
                raise ConflictError(tr("recording_in_progress"))
            if self._import_task:
                raise ConflictError(tr("import_in_progress"))
            if self.whisper_state == "error":
                raise ConflictError(tr("whisper_unavailable", detail=self.whisper_detail))
            meeting = self.db.create_meeting(
                title.strip() or Path(filename).stem,
                None,
                None,
                keep_audio=False,
                status=MeetingStatus.TRANSCRIBING,
                source_file=filename,
                language=language,
            )
            self._import_task = asyncio.create_task(
                self._run_import(meeting.id, path, self._tracker(language))
            )
            self._import_meeting_id = meeting.id
        return meeting

    async def _run_import(self, meeting_id: int, path: Path, language: LanguageTracker) -> None:
        try:
            await self._transcribe_file(meeting_id, path, language)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Import failed for meeting %s", meeting_id)
            self._set_status(meeting_id, MeetingStatus.ERROR, error=str(exc), ended_at=now_iso())
            return
        finally:
            path.unlink(missing_ok=True)  # the upload is never kept
            self._import_task, self._import_meeting_id = None, None
        transcript = format_transcript(self.db.list_segments(meeting_id))
        self._set_status(
            meeting_id, MeetingStatus.TRANSCRIBED, transcript=transcript, ended_at=now_iso()
        )
        await self.analyze(meeting_id)

    async def _transcribe_file(
        self, meeting_id: int, path: Path, language: LanguageTracker
    ) -> None:
        """Decode the whole file, then transcribe it in batches (several passages at once, the
        language detected once unless chosen): several times faster than sentence by sentence.
        Sentences are stored and published as they come; deleting the meeting stops it."""
        await self._whisper_ready.wait()
        loop = asyncio.get_running_loop()
        sample_rate = self.settings.sample_rate
        chunks: list[np.ndarray] = []
        async with decode_audio(path, sample_rate) as decoded:
            async for samples in decoded:
                chunks.append(samples)
        if not chunks:
            raise RuntimeError(tr("no_readable_audio"))
        audio = np.concatenate(chunks)
        duration = len(audio) / sample_rate
        self.hub.publish(meeting_id, {"type": "progress", "done_s": 0.0, "total_s": duration})
        speaker = self.settings.import_speaker
        stored: list[tuple[int, TranscribedPiece]] = []

        def store(piece: TranscribedPiece) -> None:
            segment = self.db.add_segment(
                meeting_id,
                Segment(
                    source="remote",
                    speaker=speaker,
                    start_s=round(piece.start_s, 2),
                    end_s=round(piece.end_s, 2),
                    text=piece.text,
                ),
            )
            if segment.id is not None:
                stored.append((segment.id, piece))
            self.hub.publish(meeting_id, {"type": "segment", "segment": segment.model_dump()})
            self.hub.publish(
                meeting_id, {"type": "progress", "done_s": piece.end_s, "total_s": duration}
            )

        def on_piece(piece: TranscribedPiece) -> bool:
            # Whisper thread: storing and publishing happen on the event loop
            if self._import_meeting_id != meeting_id:
                return False  # meeting deleted, import cancelled
            loop.call_soon_threadsafe(store, piece)
            return True

        await loop.run_in_executor(
            self._executor,
            self.transcriber.transcribe_file,
            audio,
            None if language.automatic else language.language,
            on_piece,
        )
        # Let the last sentences queued by the thread be stored before finishing
        await asyncio.sleep(0)
        if self.voices_error is None and self._import_meeting_id == meeting_id:
            await self._tell_speakers_apart(meeting_id, audio, stored)

    async def _tell_speakers_apart(
        self, meeting_id: int, audio: np.ndarray, stored: list[tuple[int, TranscribedPiece]]
    ) -> None:
        """Imported file, a single mixed track: speech turns cut at short pauses, one voice print
        each, grouped like a live meeting; then each sentence goes to the turns its words fall in,
        split in two where the speaker changes mid-sentence."""
        turns = await asyncio.get_running_loop().run_in_executor(
            self._voice_executor, self._speech_turns, audio
        )
        voices = MeetingVoices(speaker_label)
        spoken = []
        for start_s, end_s, voice_print in turns:
            spoken.append(voices.assign("remote", voice_print, end_s - start_s))
            spoken[-1].start_s, spoken[-1].end_s = start_s, end_s
        voices.regroup()
        named = [(s.start_s, s.end_s, voices.name(s)) for s in spoken]
        speakers: dict[int, str] = {}
        for segment_id, piece in stored:
            words = piece.words or [(piece.start_s, piece.end_s, piece.text)]
            parts = split_by_speaker(words, named)
            if len(parts) == 1:
                speakers[segment_id] = parts[0][3]
            elif parts:
                self.db.split_segment(
                    segment_id,
                    [
                        Segment(source="remote", speaker=name, text=text,
                                start_s=round(start, 2), end_s=round(end, 2))
                        for start, end, text, name in parts
                    ],
                )  # fmt: skip
        self.db.set_speakers(speakers)
        self.hub.publish(meeting_id, {"type": "speakers"})

    def _speech_turns(self, audio: np.ndarray) -> list[tuple[float, float, np.ndarray | None]]:
        """Voices thread: (start, end, voice print) of each stretch of speech between pauses."""
        rate = self.settings.sample_rate
        segmenter = UtteranceSegmenter(
            silero_vad(), sample_rate=rate, threshold=self.settings.vad_threshold,
            min_silence_ms=TURN_SILENCE_MS, max_utterance_s=TURN_MAX_S,
        )  # fmt: skip
        utterances = [
            u
            for i in range(0, len(audio), 30 * rate)
            for u in segmenter.push(audio[i : i + 30 * rate])
        ]
        utterances += segmenter.flush()
        return [
            (u.start_s(rate), u.end_s(rate), self.voice_printer.embed(u.audio)) for u in utterances
        ]

    # Analysis

    async def analyze(self, meeting_id: int) -> None:
        self._analyses += 1
        self.analysis_started[meeting_id] = time.monotonic()
        try:
            await self._analyze(meeting_id)
        finally:
            self._analyses -= 1
            self.analysis_started.pop(meeting_id, None)

    def estimates(self, meeting: Meeting, segments: list[Segment]) -> AiEstimates:
        chars = len(format_transcript(segments))
        # A long meeting: the old parts not yet turned into notes make the next question longer
        notes = MeetingNotes(self.db, meeting.id)
        missing = self.ollama.missing_notes_chars(meeting.title, segments, notes)
        # During the meeting, the model kept loaded only reads what was said since the last question
        new_chars = max(0, chars - self.ollama.cached_chars) if self.active else chars
        return AiEstimates(
            ask_s=round(self.ollama.estimate_s(new_chars, "ask", notes_chars=missing), 1),
            analysis_s=round(self.ollama.estimate_s(chars, "analysis"), 1),
        )

    def analysis_elapsed_s(self, meeting_id: int) -> float | None:
        started = self.analysis_started.get(meeting_id)
        return None if started is None else round(time.monotonic() - started, 1)

    async def _analyze(self, meeting_id: int) -> None:
        meeting = self.db.get_meeting(meeting_id)
        segments = self.db.list_segments(meeting_id)
        if not meeting:
            return
        if not segments:
            self._set_status(meeting_id, MeetingStatus.TRANSCRIBED, error=tr("empty_transcript"))
            return
        self._set_status(meeting_id, MeetingStatus.ANALYZING, error=None)
        try:
            await self.provisioner.ensure_running()
            analysis = await self.ollama.analyze(meeting.title, segments)
        except Exception as exc:
            logger.exception("Analysis failed for meeting %s", meeting_id)
            detail = str(exc) or type(exc).__name__
            self._set_status(
                meeting_id, MeetingStatus.TRANSCRIBED, error=tr("analysis_failed", error=detail)
            )
            return
        self.db.save_analysis(meeting_id, analysis)
        self._set_status(meeting_id, MeetingStatus.DONE, error=None)

    async def ask(self, meeting_id: int, question: str) -> str:
        """Answer a question about a meeting, finished or still recording, from its transcript."""
        meeting = self.db.get_meeting(meeting_id)
        if not meeting:
            raise KeyError(meeting_id)
        segments = self.db.list_segments(meeting_id)
        if not segments:
            raise ConflictError(tr("nothing_transcribed"))
        await self.provisioner.ensure_running()
        # One question at a time: the local AI shares the GPU with the live transcription.
        async with self._ask_lock:
            notes = MeetingNotes(self.db, meeting_id)
            return await self.ollama.ask(meeting.title, segments, question, notes)

    def request_analysis(self, meeting_id: int) -> None:
        meeting = self.db.get_meeting(meeting_id)
        if not meeting:
            raise KeyError(meeting_id)
        if meeting.status not in (MeetingStatus.TRANSCRIBED, MeetingStatus.DONE):
            raise ConflictError(tr("analysis_not_possible", status=meeting.status))
        self._spawn(self.analyze(meeting_id))

    # Housekeeping

    def delete_audio(self, meeting_id: int) -> None:
        if self.active and self.active.meeting_id == meeting_id:
            raise ConflictError(tr("meeting_busy"))
        shutil.rmtree(self.audio_path(meeting_id), ignore_errors=True)
        self.db.update_meeting(meeting_id, keep_audio=False)

    def delete_meeting(self, meeting_id: int) -> None:
        if self._import_task and self._import_meeting_id == meeting_id:
            self._import_task.cancel()
        self.delete_audio(meeting_id)
        self.pending.remove(meeting_id)
        self.db.delete_meeting(meeting_id)
