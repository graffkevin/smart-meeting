"""Streaming utterance segmentation with Silero VAD.

Instead of transcribing fixed chunks (which cut words, and need overlap and deduplication),
audio is cut at pauses: an utterance ends after `min_silence_ms` of silence, or is force-cut
at its quietest point once it reaches `max_utterance_s`. Each utterance is transcribed exactly
once, so there is nothing to deduplicate and sentences are rarely split.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

WINDOW = 512  # Silero VAD window at 16 kHz (32 ms)

VadFn = Callable[[np.ndarray], np.ndarray]


def silero_vad() -> VadFn:
    """Silero VAD bundled with faster-whisper: N*512 samples in, N speech probabilities out."""
    from faster_whisper.vad import get_vad_model

    model = get_vad_model()
    return lambda audio: np.asarray(model(audio)).reshape(-1)


@dataclass
class Utterance:
    start_sample: int  # absolute position in the source stream
    audio: np.ndarray

    def start_s(self, sample_rate: int) -> float:
        return self.start_sample / sample_rate

    def end_s(self, sample_rate: int) -> float:
        return (self.start_sample + len(self.audio)) / sample_rate


class UtteranceSegmenter:
    def __init__(
        self,
        vad: VadFn,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_silence_ms: int = 700,
        max_utterance_s: float = 20.0,
        pre_roll_ms: int = 300,
        post_roll_ms: int = 200,
        min_speech_ms: int = 250,
    ) -> None:
        self.vad = vad
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.neg_threshold = max(threshold - 0.15, 0.01)
        self.min_silence_windows = self._windows(min_silence_ms)
        self.max_windows = int(max_utterance_s * sample_rate) // WINDOW
        self.post_roll_windows = self._windows(post_roll_ms)
        self.min_speech_windows = self._windows(min_speech_ms)

        self._pending = np.zeros(0, dtype=np.float32)  # samples not yet forming a full window
        self._position = 0  # absolute index of the next window's first sample
        self._pre_roll: deque[np.ndarray] = deque(maxlen=self._windows(pre_roll_ms))
        self._windows_buf: list[np.ndarray] = []  # current utterance, one entry per window
        self._probs: list[float] = []
        self._start = 0
        self._silence_run = 0
        self._speech_count = 0

    def _windows(self, ms: int) -> int:
        return max(1, round(ms * self.sample_rate / 1000 / WINDOW))

    @property
    def in_speech(self) -> bool:
        return bool(self._windows_buf)

    def push(self, samples: np.ndarray) -> list[Utterance]:
        audio = np.concatenate([self._pending, samples.astype(np.float32, copy=False)])
        full = len(audio) // WINDOW * WINDOW
        self._pending = audio[full:]
        if not full:
            return []
        probs = self.vad(audio[:full])
        out: list[Utterance] = []
        for i, prob in enumerate(probs):
            window = audio[i * WINDOW : (i + 1) * WINDOW]
            utterance = self._process_window(window, float(prob))
            if utterance is not None:
                out.append(utterance)
            self._position += WINDOW
        return out

    def flush(self) -> list[Utterance]:
        """Emit whatever speech is buffered, e.g. when the meeting stops."""
        if self._pending.size and self.in_speech:
            self._windows_buf.append(self._pending)
            self._probs.append(0.0)
        self._pending = np.zeros(0, dtype=np.float32)
        utterance = self._emit(len(self._windows_buf))
        return [utterance] if utterance else []

    def _process_window(self, window: np.ndarray, prob: float) -> Utterance | None:
        if not self.in_speech:
            if prob >= self.threshold:
                self._start = self._position - len(self._pre_roll) * WINDOW
                self._windows_buf = [*self._pre_roll, window]
                self._probs = [0.0] * len(self._pre_roll) + [prob]
                self._pre_roll.clear()
                self._silence_run = 0
                self._speech_count = 1
            else:
                self._pre_roll.append(window)
            return None

        self._windows_buf.append(window)
        self._probs.append(prob)
        if prob < self.neg_threshold:
            self._silence_run += 1
        else:
            self._silence_run = 0
            if prob >= self.threshold:
                self._speech_count += 1

        if self._silence_run >= self.min_silence_windows:
            keep = len(self._windows_buf) - self._silence_run + self.post_roll_windows
            return self._emit(keep)
        if len(self._windows_buf) >= self.max_windows:
            return self._emit(self._quietest_cut())
        return None

    def _quietest_cut(self) -> int:
        """Cut point (window count) at the quietest window in the last third of the buffer."""
        search_from = len(self._probs) * 2 // 3
        tail = self._probs[search_from:]
        return search_from + int(np.argmin(tail)) + 1

    def _emit(self, keep: int) -> Utterance | None:
        """Emit the first `keep` windows; carry the rest over as the start of a new utterance."""
        if not self._windows_buf:
            return None
        emitted, rest = self._windows_buf[:keep], self._windows_buf[keep:]
        rest_probs = self._probs[keep:]
        utterance = None
        if self._speech_count >= self.min_speech_windows:
            utterance = Utterance(self._start, np.concatenate(emitted))
        emitted_samples = sum(len(w) for w in emitted)

        speech_left = sum(p >= self.threshold for p in rest_probs)
        if speech_left:
            # Forced cut in the middle of speech: the remainder is the next utterance.
            self._start += emitted_samples
            self._windows_buf, self._probs = rest, rest_probs
            self._speech_count = speech_left
            self._silence_run = 0
        else:
            self._windows_buf, self._probs = [], []
            self._speech_count = 0
            self._silence_run = 0
            self._pre_roll.extend(rest)
        return utterance
