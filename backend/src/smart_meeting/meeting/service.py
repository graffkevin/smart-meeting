"""Meeting lifecycle: capture -> utterances -> transcription -> storage -> analysis.

Everything runs in the asyncio loop except Whisper, which runs in a single worker thread so
utterances from both sources are transcribed one at a time, in arrival order.
"""

import asyncio
import logging
import math
import shutil
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

from smart_meeting.audio.backend import AudioBackend, Capture, get_backend
from smart_meeting.audio.decode import decode_audio, probe_duration
from smart_meeting.audio.segmenter import Utterance, UtteranceSegmenter, silero_vad
from smart_meeting.config import Settings
from smart_meeting.db import Database, now_iso
from smart_meeting.llm.analysis import OllamaClient, format_transcript
from smart_meeting.meeting.events import EventHub
from smart_meeting.models import (
    CapturedDevice,
    Meeting,
    MeetingStatus,
    Segment,
    Source,
    StartMeetingRequest,
)
from smart_meeting.provision import OllamaProvisioner
from smart_meeting.transcription.whisper import WhisperTranscriber

logger = logging.getLogger(__name__)

DEVICE_POLL_S = 2.0


class ConflictError(Exception):
    pass


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
        self._import_task: asyncio.Task[None] | None = None
        self._import_meeting_id: int | None = None

    # Lifecycle

    def startup(self) -> None:
        """Load Whisper and provision Ollama in the background: the UI is usable meanwhile
        and shows their progress."""
        self._spawn(self._load_whisper())
        self._spawn(self.provisioner.run())

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
            raise ConflictError("Une réunion est déjà en cours")
        if self.whisper_state == "error":
            raise ConflictError(f"Whisper indisponible : {self.whisper_detail}")

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
                raise ConflictError(f"Audio indisponible : {exc}") from exc

        meeting = self.db.create_meeting(
            request.title.strip() or "Réunion sans titre",
            request.mic_device,
            request.remote_device,
            request.keep_audio,
        )
        loop = asyncio.get_running_loop()
        recording = Recording(
            meeting_id=meeting.id,
            started=loop.time(),
            streams={
                "mic": SourceStream("mic", self.settings.user_name),
                "remote": SourceStream("remote", self.settings.remote_name),
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
            exc = RuntimeError(f"Aucune source audio capturée ({errors})")
            await self._abort(recording, exc)
            raise ConflictError(str(exc))
        recording.tasks = [
            asyncio.create_task(self._transcription_worker(recording), name="transcription"),
            asyncio.create_task(self._publish_levels(recording), name="levels"),
            asyncio.create_task(self._follow_devices(recording), name="devices"),
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

    async def _transcription_worker(self, recording: Recording) -> None:
        await self._whisper_ready.wait()
        while (item := await recording.queue.get()) is not None:
            source, offset_s, utterance = item
            stream = recording.streams[source]
            stream.previous_text = await self._transcribe_utterance(
                recording.meeting_id, source, stream.speaker, offset_s, utterance,
                stream.previous_text,
            )  # fmt: skip

    async def _transcribe_utterance(
        self,
        meeting_id: int,
        source: Source,
        speaker: str,
        offset_s: float,
        utterance: Utterance,
        previous_text: str,
    ) -> str:
        """Transcribe, store and publish one utterance. Returns the context for the next one."""
        sample_rate = self.settings.sample_rate
        try:
            pieces = await asyncio.get_running_loop().run_in_executor(
                self._executor, self.transcriber.transcribe, utterance.audio, previous_text
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
            raise ConflictError("Cette réunion n'est pas en cours d'enregistrement")
        if recording.stopping:
            raise ConflictError("Arrêt déjà en cours")
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

    async def import_file(self, title: str, path: Path, filename: str) -> Meeting:
        """Transcribe an audio/video file (decoded by ffmpeg), then analyze it like a meeting."""
        async with self._start_lock:
            if self.active:
                raise ConflictError("Une réunion est en cours d'enregistrement")
            if self._import_task:
                raise ConflictError("Un import est déjà en cours")
            if self.whisper_state == "error":
                raise ConflictError(f"Whisper indisponible : {self.whisper_detail}")
            meeting = self.db.create_meeting(
                title.strip() or Path(filename).stem,
                None,
                None,
                keep_audio=False,
                status=MeetingStatus.TRANSCRIBING,
                source_file=filename,
            )
            self._import_task = asyncio.create_task(self._run_import(meeting.id, path))
            self._import_meeting_id = meeting.id
        return meeting

    async def _run_import(self, meeting_id: int, path: Path) -> None:
        try:
            await self._transcribe_file(meeting_id, path)
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

    async def _transcribe_file(self, meeting_id: int, path: Path) -> None:
        await self._whisper_ready.wait()
        sample_rate = self.settings.sample_rate
        duration = await probe_duration(path)
        segmenter = self._new_segmenter()
        speaker = self.settings.import_speaker
        previous_text = ""
        received = 0
        async with decode_audio(path, sample_rate) as chunks:
            async for samples in chunks:
                received += len(samples)
                # ffmpeg is paused by the pipe while Whisper works: memory stays bounded.
                for utterance in segmenter.push(samples):
                    previous_text = await self._transcribe_utterance(
                        meeting_id, "remote", speaker, 0.0, utterance, previous_text
                    )
                self.hub.publish(
                    meeting_id,
                    {"type": "progress", "done_s": received / sample_rate, "total_s": duration},
                )
        if received == 0:
            raise RuntimeError("Aucune piste audio lisible dans ce fichier")
        for utterance in segmenter.flush():
            await self._transcribe_utterance(
                meeting_id, "remote", speaker, 0.0, utterance, previous_text
            )

    # Analysis

    async def analyze(self, meeting_id: int) -> None:
        meeting = self.db.get_meeting(meeting_id)
        segments = self.db.list_segments(meeting_id)
        if not meeting:
            return
        if not segments:
            self._set_status(
                meeting_id, MeetingStatus.TRANSCRIBED, error="Transcription vide : rien à analyser"
            )
            return
        self._set_status(meeting_id, MeetingStatus.ANALYZING, error=None)
        try:
            analysis = await self.ollama.analyze(meeting.title, segments)
        except Exception as exc:
            logger.exception("Analysis failed for meeting %s", meeting_id)
            detail = str(exc) or type(exc).__name__
            self._set_status(
                meeting_id, MeetingStatus.TRANSCRIBED, error=f"Analyse impossible : {detail}"
            )
            return
        self.db.save_analysis(meeting_id, analysis)
        self._set_status(meeting_id, MeetingStatus.DONE, error=None)

    def request_analysis(self, meeting_id: int) -> None:
        meeting = self.db.get_meeting(meeting_id)
        if not meeting:
            raise KeyError(meeting_id)
        if meeting.status not in (MeetingStatus.TRANSCRIBED, MeetingStatus.DONE):
            raise ConflictError(f"Analyse impossible dans l'état « {meeting.status} »")
        self._spawn(self.analyze(meeting_id))

    # Housekeeping

    def delete_audio(self, meeting_id: int) -> None:
        if self.active and self.active.meeting_id == meeting_id:
            raise ConflictError("Réunion en cours")
        shutil.rmtree(self.audio_path(meeting_id), ignore_errors=True)
        self.db.update_meeting(meeting_id, keep_audio=False)

    def delete_meeting(self, meeting_id: int) -> None:
        if self._import_task and self._import_meeting_id == meeting_id:
            self._import_task.cancel()
        self.delete_audio(meeting_id)
        self.db.delete_meeting(meeting_id)
