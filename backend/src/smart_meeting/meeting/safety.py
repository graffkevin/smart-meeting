"""Nothing said is lost, even if the server freezes or crashes during a meeting.

- The raw audio of each source is always written to disk while recording (a safety track, in
  meeting time). Once the meeting ends, any speech in it that has no transcribed sentence (a
  freeze, a restart, a crash) is transcribed and put in its place. The tracks are then deleted,
  unless the user keeps the audio.
- Every sentence waiting for Whisper is written to disk (`pending/<meeting>/`) and removed once
  transcribed: after a crash, the next start transcribes what was left.
- If the transcription stops progressing, the server restarts itself and resumes the same meeting
  (`resume.json`): recording goes on, and the sentences left waiting are transcribed first.
"""

import json
import logging
import os
import shutil
import sys
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Speech of a safety track is looked for where no sentence was transcribed for this long; a
# sentence covers this much more around it (Whisper's times are a bit shorter than the speech).
MIN_MISSING_S = 2.0
COVER_MARGIN_S = 1.0
WAV_HEADER_BYTES = 44  # the wave module writes the classic header

# A restart older than this is not resumed (the user may have stopped everything since).
RESUME_MAX_AGE_S = 600


@dataclass
class PendingSentence:
    source: str
    start_s: float  # meeting time of its first sample
    audio: np.ndarray
    path: Path


class PendingAudio:
    def __init__(self, data_dir: Path, sample_rate: int) -> None:
        self.root = data_dir / "pending"
        self.sample_rate = sample_rate

    def folder(self, meeting_id: int) -> Path:
        return self.root / str(meeting_id)

    def save(self, meeting_id: int, source: str, start_s: float, audio: np.ndarray) -> Path:
        folder = self.folder(meeting_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{source}-{round(start_s * 1000):010d}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        return path

    def load(self, meeting_id: int) -> list[PendingSentence]:
        """Sentences left untranscribed, in meeting time order."""
        sentences = []
        for path in self.folder(meeting_id).glob("*.wav"):
            try:
                source, millis = path.stem.rsplit("-", 1)
                with wave.open(str(path), "rb") as wav:
                    frames = wav.readframes(wav.getnframes())
            except (OSError, ValueError, EOFError, wave.Error):
                logger.warning("Unreadable pending sentence %s", path, exc_info=True)
                continue
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768
            sentences.append(PendingSentence(source, int(millis) / 1000, audio, path))
        return sorted(sentences, key=lambda s: s.start_s)

    def meetings(self) -> list[int]:
        if not self.root.exists():
            return []
        return sorted(int(p.name) for p in self.root.iterdir() if p.is_dir() and p.name.isdigit())

    def remove(self, meeting_id: int) -> None:
        shutil.rmtree(self.folder(meeting_id), ignore_errors=True)


def resume_path(data_dir: Path) -> Path:
    return data_dir / "resume.json"


def save_resume(data_dir: Path, meeting_id: int, request: dict) -> None:
    payload = {"meeting_id": meeting_id, "request": request, "at": time.time()}
    resume_path(data_dir).write_text(json.dumps(payload), encoding="utf-8")


def take_resume(data_dir: Path) -> dict | None:
    """The meeting to resume after a restart for a frozen transcription, read only once."""
    path = resume_path(data_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        path.unlink(missing_ok=True)
    if time.time() - float(payload.get("at", 0)) > RESUME_MAX_AGE_S:
        return None
    return payload


def restart_process() -> None:
    """Replace this process by a fresh one, same command (no new browser tab): stuck threads
    cannot be stopped otherwise."""
    args = list(sys.argv)
    if Path(args[0]).name.startswith("smart-meeting") and "--no-window" not in args:
        args.append("--no-window")
    logging.shutdown()
    # macOS app: sys.executable is the bundled server itself (argv[0]), not a Python interpreter
    os.execv(sys.executable, args if getattr(sys, "frozen", False) else [sys.executable, *args])


class SafetyTrack:
    """Raw audio of a source, sample i at meeting time `start_s + i / rate`: silence fills the
    time a device switch takes. The header is kept up to date and every write flushed, so a
    crash loses nothing that was received."""

    def __init__(self, folder: Path, source: str, start_s: float, sample_rate: int) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"{source}-{round(start_s * 1000):010d}.wav"
        self.start_s = start_s
        self.rate = sample_rate
        self.frames = 0
        self._wav = wave.open(str(self.path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    def write(self, samples: np.ndarray, at_s: float) -> None:
        gap = round((at_s - self.start_s) * self.rate) - self.frames
        if gap > self.rate // 20:  # more than 50 ms behind: a capture restart
            self._wav.writeframes(np.zeros(gap, np.int16).tobytes())
            self.frames += gap
        self._wav.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
        self.frames += len(samples)
        self._wav._file.flush()  # type: ignore[attr-defined]

    def close(self) -> None:
        self._wav.close()


def load_tracks(folder: Path, source: str) -> list[tuple[float, np.ndarray]]:
    """(meeting time of the first sample, audio) of the safety tracks of a source. Read without
    trusting the header: a track cut by a crash is read up to its last sample."""
    tracks = []
    for path in sorted(folder.glob(f"{source}-*.wav")):
        try:
            start_s = int(path.stem.rsplit("-", 1)[1]) / 1000
            data = path.read_bytes()[WAV_HEADER_BYTES:]
        except (OSError, ValueError, IndexError):
            continue
        audio = np.frombuffer(data[: len(data) // 2 * 2], np.int16).astype(np.float32) / 32768
        tracks.append((start_s, audio))
    return tracks


def missing_speech(
    tracks: list[tuple[float, np.ndarray]],
    sentences: list[tuple[float, float]],
    new_segmenter: Callable,
    rate: int,
) -> list[tuple[float, np.ndarray]]:
    """Speech of the tracks where no sentence was transcribed: (meeting time, audio) each."""
    covered = sorted((start - COVER_MARGIN_S, end + COVER_MARGIN_S) for start, end in sentences)
    found = []
    for track_start, audio in tracks:
        track_end = track_start + len(audio) / rate
        cursor = track_start
        for start, end in [*covered, (track_end, track_end)]:
            if start - cursor >= MIN_MISSING_S:
                first = int((cursor - track_start) * rate)
                piece = audio[first : int((min(start, track_end) - track_start) * rate)]
                segmenter = new_segmenter()
                utterances = [
                    u for i in range(0, len(piece), 30 * rate)
                    for u in segmenter.push(piece[i : i + 30 * rate])
                ] + segmenter.flush()  # fmt: skip
                found += [(cursor + u.start_s(rate), u.audio) for u in utterances]
            cursor = max(cursor, end)
            if cursor >= track_end:
                break
    return found
