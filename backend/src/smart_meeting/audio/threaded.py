"""Base for captures fed by an audio library callback thread (Windows, macOS)."""

import asyncio
import logging
import threading
import time

import numpy as np
import soxr

from smart_meeting.audio.backend import OnAudio

logger = logging.getLogger(__name__)

# Some sources deliver nothing while silent (WASAPI loopback when nothing plays). Gaps longer
# than this are filled with silence so timestamps keep matching the wall clock.
GAP_FILL_S = 0.2


class ThreadedCapture:
    """Subclasses implement `_open()` / `_close()` (blocking, run in a thread) and call
    `_push(frames, rate)` from the audio thread with float32 frames shaped (n, channels)."""

    def __init__(self, target: str | None, on_audio: OnAudio, sample_rate: int) -> None:
        self.target = target
        self.on_audio = on_audio
        self.sample_rate = sample_rate
        self._loop: asyncio.AbstractEventLoop | None = None
        self._resampler: soxr.ResampleStream | None = None
        self._rate: int | None = None
        self._started_at = 0.0
        self._received = 0  # frames at the native rate, including filled gaps
        self._lock = threading.Lock()

    def _open(self) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._started_at = time.monotonic()
        await asyncio.to_thread(self._open)

    async def stop(self) -> None:
        await asyncio.to_thread(self._close)
        with self._lock:
            if self._resampler is not None:
                tail = self._resampler.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
                self._resampler = None
                if tail.size:
                    self.on_audio(tail)

    def _push(self, frames: np.ndarray, rate: int) -> None:
        """Called from the audio thread."""
        mono = frames.mean(axis=1) if frames.ndim == 2 else frames
        mono = np.ascontiguousarray(mono, dtype=np.float32)
        with self._lock:
            if self._resampler is None or rate != self._rate:
                self._resampler = soxr.ResampleStream(rate, self.sample_rate, 1, dtype="float32")
                self._rate = rate
            expected = int((time.monotonic() - self._started_at) * rate)
            missing = expected - self._received - len(mono)
            if missing > GAP_FILL_S * rate:
                mono = np.concatenate([np.zeros(missing, dtype=np.float32), mono])
            self._received += len(mono)
            out = self._resampler.resample_chunk(mono)
        if out.size and self._loop is not None:
            self._loop.call_soon_threadsafe(self.on_audio, out)
