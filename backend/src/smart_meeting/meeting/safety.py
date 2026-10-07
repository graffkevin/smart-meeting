"""Nothing said is lost, even if the server freezes or crashes during a meeting.

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
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

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
    os.execv(sys.executable, [sys.executable, *args])
