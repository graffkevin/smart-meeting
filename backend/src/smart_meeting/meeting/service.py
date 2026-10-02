"""Meeting lifecycle: capture -> utterances -> transcription -> storage -> analysis.

Everything runs in the asyncio loop except Whisper, which runs in a single worker thread so
utterances from both sources are transcribed one at a time, in arrival order.
"""

import asyncio
import logging
import math
import shutil
import time
import wave
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np

from smart_meeting.audio.backend import AudioBackend, Capture, get_backend
from smart_meeting.audio.decode import decode_audio
from smart_meeting.audio.segmenter import Utterance, UtteranceSegmenter, silero_vad
from smart_meeting.config import Settings
from smart_meeting.db import Database, now_iso
from smart_meeting.llm.analysis import OllamaClient, format_transcript
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
from smart_meeting.transcription.language import LanguageTracker
from smart_meeting.transcription.whisper import TranscribedPiece, WhisperTranscriber

logger = logging.getLogger(__name__)

DEVICE_POLL_S = 2.0
# Provisional text of the sentence being spoken: refreshed at most this often, once it is this long.
PARTIAL_INTERVAL_S = 1.0
PARTIAL_MIN_S = 1.0
# A pause this long may end the sentence: its final transcription gets Whisper first.
PARTIAL_PAUSE_S = 0.2
# Time between two provisional texts, as a multiple of the last one's computing time (GPU load).
PARTIAL_LOAD_FACTOR = 1.5
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


@dataclass
class SourceStream:
    source: Source
    speaker: str
    # Automatic mode: follow the device applications use instead of a fixed one.
    auto: bool = False
    capture: Capture | None = None
    # Why this source could not be captured (the meeting goes on with the other one).
    error: str | None = None
    segmenter: UtteranceSegmenter | None = None
    # Meeting time (s) of the first sample received, to align both sources.
    offset_s: float | None = None
    wav: wave.Wave_write | None = None
    previous_text: str = ""
    language: LanguageTracker = field(default_factory=LanguageTracker)
    peak_rms: float = 0.0


@dataclass
class Recording:
    meeting_id: int
    started: float  # loop.time() at start
    streams: dict[Source, SourceStream]
    # (source, meeting time of the source's first sample, utterance)
    queue: asyncio.Queue[tuple[Source, float, Utterance] | None] = field(
        default_factory=asyncio.Queue
    )
    # Serializes device switches with stop().
    device_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    stopping: bool = False


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
        self.transcriber = WhisperTranscriber(settings)
        self.ollama = OllamaClient(settings)
        self.provisioner = OllamaProvisioner(settings)
        self.whisper_state: Literal["loading", "ready", "error"] = "loading"
        self.whisper_detail: str | None = None
        self.active: Recording | None = None
        self._whisper_ready = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
        self._background: set[asyncio.Task[None]] = set()
        self._start_lock = asyncio.Lock()
        self._ask_lock = asyncio.Lock()
        self.ui_connections = 0  # open browser pages (presence WebSockets)
        self._analyses = 0
        self.analysis_started: dict[int, float] = {}  # meeting id -> monotonic start
        self._import_task: asyncio.Task[None] | None = None
        self._import_meeting_id: int | None = None

    # Lifecycle

    def startup(self) -> None:
        """Load Whisper and provision Ollama in the background: the UI is usable meanwhile
        and shows their progress."""
        self._spawn(self._load_whisper())
        self._spawn(self._provision())

    def restart_ai(self) -> None:
        """Restart button of the interface: stop the Ollama we started, then provision again
        (start it, download its model if missing). A system Ollama is left running."""
        self._spawn(self._restart_ai())

    async def _restart_ai(self) -> None:
        await self.provisioner.stop()
        await self.provisioner.run()

    async def _provision(self) -> None:
        await self.provisioner.run()
        await self.provisioner.watch()

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

    # Open pages

    def page_opened(self) -> None:
        self.ui_connections += 1

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

    async def _start(self, request: StartMeetingRequest) -> Meeting:
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

        meeting = self.db.create_meeting(
            request.title.strip() or default_title(language=self.settings.ui_language),
            request.mic_device,
            request.remote_device,
            request.keep_audio,
            language=request.language,
        )
        if request.tags:
            self.db.set_tags(meeting.id, request.tags)
        loop = asyncio.get_running_loop()
        recording = Recording(
            meeting_id=meeting.id,
            started=loop.time(),
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
        for stream in recording.streams.values():
            stream.auto = targets[stream.source] is None
            if stream.auto:
                targets[stream.source] = in_use[stream.source]
            stream.segmenter = self._new_segmenter()
            if request.keep_audio:
                stream.wav = self._open_wav(meeting.id, stream.source)
            stream.capture = self._new_capture(recording, stream, targets[stream.source])

        self.active = recording
        for stream in recording.streams.values():
            try:
                await stream.capture.start()
            except Exception as exc:
                logger.exception("Could not start %s capture", stream.source)
                stream.error = str(exc) or type(exc).__name__
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
                device=stream.capture.target, auto=stream.auto, error=stream.error
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
            stream.error = None
        except Exception as exc:
            logger.exception("Could not switch %s capture to %s", stream.source, target)
            stream.error = str(exc) or type(exc).__name__
        self._publish_devices(recording)

    def _open_wav(self, meeting_id: int, source: Source) -> wave.Wave_write:
        directory = self.audio_path(meeting_id)
        directory.mkdir(parents=True, exist_ok=True)
        wav = wave.open(str(directory / f"{source}.wav"), "wb")
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(self.settings.sample_rate)
        return wav

    async def _abort(self, recording: Recording, exc: Exception) -> None:
        for stream in recording.streams.values():
            if stream.capture:
                await stream.capture.stop()
            if stream.wav:
                stream.wav.close()
        self._set_status(recording.meeting_id, MeetingStatus.ERROR, error=str(exc))
        self.active = None

    def _on_audio(self, recording: Recording, stream: SourceStream, samples: np.ndarray) -> None:
        sample_rate = self.settings.sample_rate
        if stream.offset_s is None:
            elapsed = asyncio.get_running_loop().time() - recording.started
            stream.offset_s = max(0.0, elapsed - len(samples) / sample_rate)
        if stream.wav:
            stream.wav.writeframes((samples * 32767).astype(np.int16).tobytes())
        stream.peak_rms = max(stream.peak_rms, float(np.sqrt(np.mean(samples**2))))
        for utterance in stream.segmenter.push(samples):
            recording.queue.put_nowait((stream.source, stream.offset_s, utterance))

    def _flush(self, recording: Recording, stream: SourceStream) -> None:
        for utterance in stream.segmenter.flush():
            recording.queue.put_nowait((stream.source, stream.offset_s or 0.0, utterance))

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
                    text = await loop.run_in_executor(
                        self._executor,
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
                            "speaker": stream.speaker,
                            "start_s": round(
                                (stream.offset_s or 0.0) + ongoing.start_s(sample_rate), 2
                            ),
                            "text": text,
                        },
                    )

    async def _transcription_worker(self, recording: Recording) -> None:
        await self._whisper_ready.wait()
        while (item := await recording.queue.get()) is not None:
            source, offset_s, utterance = item
            stream = recording.streams[source]
            stream.previous_text = await self._transcribe_utterance(
                recording.meeting_id, source, stream.speaker, offset_s, utterance,
                stream.language, stream.previous_text,
            )  # fmt: skip

    async def _transcribe_utterance(
        self,
        meeting_id: int,
        source: Source,
        speaker: str,
        offset_s: float,
        utterance: Utterance,
        language: LanguageTracker,
        previous_text: str,
    ) -> str:
        """Transcribe, store and publish one utterance. Returns the context for the next one."""
        sample_rate = self.settings.sample_rate
        try:
            pieces = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                self.transcriber.transcribe,
                utterance.audio,
                language,
                previous_text,
            )
        except Exception:
            logger.exception("Transcription failed for a %s utterance", source)
            return previous_text
        base = offset_s + utterance.start_s(sample_rate)
        utterance_end = offset_s + utterance.end_s(sample_rate)
        for piece in pieces:
            segment = self.db.add_segment(
                meeting_id,
                Segment(
                    source=source,
                    speaker=speaker,
                    start_s=round(base + piece.start_s, 2),
                    end_s=round(min(base + piece.end_s, utterance_end), 2),
                    text=piece.text,
                ),
            )
            self.hub.publish(meeting_id, {"type": "segment", "segment": segment.model_dump()})
        return " ".join(p.text for p in pieces) if pieces else previous_text

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
            if stream.wav:
                stream.wav.close()
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
        transcript = format_transcript(self.db.list_segments(meeting_id))
        self._set_status(meeting_id, MeetingStatus.TRANSCRIBED, transcript=transcript)
        await self.analyze(meeting_id)

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

    # Analysis

    async def analyze(self, meeting_id: int) -> None:
        self._analyses += 1
        self.analysis_started[meeting_id] = time.monotonic()
        try:
            await self._analyze(meeting_id)
        finally:
            self._analyses -= 1
            self.analysis_started.pop(meeting_id, None)

    def estimates(self, segments: list[Segment]) -> AiEstimates:
        chars = len(format_transcript(segments))
        return AiEstimates(
            ask_s=round(self.ollama.estimate_s(chars, "ask"), 1),
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
            return await self.ollama.ask(meeting.title, segments, question)

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
        self.db.delete_meeting(meeting_id)
