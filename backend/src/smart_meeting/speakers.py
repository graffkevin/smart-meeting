"""Who is speaking, without names: one voice print per utterance, grouped by similarity.

The voice prints come from the WeSpeaker ResNet34-LM model (VoxCeleb, CC BY 4.0, the one behind
pyannote 3.1), run with ONNX Runtime on the CPU from Kaldi filterbanks computed here: no PyTorch.
Live, each utterance joins the closest known voice or starts a new one; once the meeting ends, all
of them are grouped again at once, which fixes most live mistakes (one person split in two).
"""

import itertools
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

MODEL_REPO = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
MODEL_FILE = "voxceleb_resnet34_LM.onnx"
SAMPLE_RATE = 16000

# Cosine similarity between voice prints. Live, a sentence starts a new voice only when it is
# long enough and unlike every known voice; at the end, voices closer than REGROUP are merged
# (one person split in two). Calibrated on real calls (a 2-person call gave 11 voices before) and
# on a 4-voice sample, kept apart.
NEW_VOICE = 0.35
MIN_NEW_VOICE_S = 2.0
REGROUP = 0.40
# A voice heard less than SMALL_VOICE_S in all joins the closest main voice if it looks like it
# at all (a laugh, an "ok", the codec of a call); under TINY_VOICE_S it always does.
SMALL_VOICE_S = 30.0
ABSORB = 0.20
TINY_VOICE_S = 10.0
# Shorter utterances give unreliable prints: they keep their voice at the end.
MIN_RELIABLE_S = 1.0


def _mel_banks(num_bins: int = 80, n_fft: int = 512, low_hz: float = 20.0) -> np.ndarray:
    """Kaldi's triangular mel filters, (num_bins, n_fft // 2 + 1)."""

    def mel(hz):
        return 1127.0 * np.log(1.0 + np.asarray(hz) / 700.0)

    low, high = mel(low_hz), mel(SAMPLE_RATE / 2)
    delta = (high - low) / (num_bins + 1)
    bin_mel = mel(np.arange(n_fft // 2) * SAMPLE_RATE / n_fft)
    left = low + np.arange(num_bins)[:, None] * delta
    center, right = left + delta, left + 2 * delta
    up = (bin_mel - left) / (center - left)
    down = (right - bin_mel) / (right - center)
    banks = np.maximum(0.0, np.minimum(up, down))
    return np.pad(banks, ((0, 0), (0, 1))).astype(np.float32)  # Nyquist bin: no weight


_BANKS = _mel_banks()
_WINDOW = (0.54 - 0.46 * np.cos(2 * np.pi * np.arange(400) / 399)).astype(np.float32)


def fbank(audio: np.ndarray) -> np.ndarray:
    """80 log mel filterbanks every 10 ms over 25 ms frames, like torchaudio's Kaldi fbank used
    to train the model (16-bit scale, DC removed, pre-emphasis, Hamming window), mean removed."""
    samples = audio.astype(np.float32) * 32768
    count = 1 + (len(samples) - 400) // 160
    if count < 1:
        return np.zeros((0, 80), dtype=np.float32)
    index = np.arange(400)[None, :] + 160 * np.arange(count)[:, None]
    frames = samples[index]
    frames -= frames.mean(axis=1, keepdims=True)
    frames[:, 1:] -= 0.97 * frames[:, :-1]
    frames[:, 0] *= 0.03
    power = np.abs(np.fft.rfft(frames * _WINDOW, n=512)) ** 2
    feats = np.log(np.maximum(power @ _BANKS.T, np.finfo(np.float32).eps))
    return (feats - feats.mean(axis=0)).astype(np.float32)


class VoicePrinter:
    """Voice prints (unit vectors of 256 values) of 16 kHz mono audio."""

    def __init__(self) -> None:
        self._session = None

    def load(self) -> None:
        import onnxruntime
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(MODEL_REPO, MODEL_FILE)
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            path, options, providers=["CPUExecutionProvider"]
        )
        logger.info("Voice prints ready: %s", MODEL_REPO)

    @property
    def ready(self) -> bool:
        return self._session is not None

    def embed(self, audio: np.ndarray) -> np.ndarray | None:
        if self._session is None:
            return None
        feats = fbank(audio)
        if len(feats) < 20:  # under 0.2 s
            return None
        (vector,) = self._session.run(None, {"feats": feats[None]})[0]
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else None


@dataclass
class Voice:
    key: int
    total: np.ndarray  # sum of the prints, weighted by duration
    duration_s: float = 0.0

    @property
    def centroid(self) -> np.ndarray:
        return self.total / (np.linalg.norm(self.total) or 1.0)


@dataclass
class OnlineVoices:
    """Live grouping of one audio source: returns a voice number for each utterance."""

    voices: list[Voice] = field(default_factory=list)
    last: int | None = None

    def assign(
        self, voice_print: np.ndarray | None, duration_s: float, new_key: Callable[[], int]
    ) -> int:
        if voice_print is None:
            return self.last if self.last is not None else self._new(None, 0.0, new_key)
        best, score = None, -1.0
        for voice in self.voices:
            similarity = float(voice.centroid @ voice_print)
            if similarity > score:
                best, score = voice, similarity
        if best is not None and (score >= NEW_VOICE or duration_s < MIN_NEW_VOICE_S):
            best.total = best.total + voice_print * duration_s
            best.duration_s += duration_s
            self.last = best.key
            return best.key
        return self._new(voice_print, duration_s, new_key)

    def _new(
        self, voice_print: np.ndarray | None, duration_s: float, new_key: Callable[[], int]
    ) -> int:
        key = new_key()
        total = voice_print * duration_s if voice_print is not None else np.zeros(256, np.float32)
        self.voices.append(Voice(key, total, duration_s))
        self.last = key
        return key


def regroup(voices: list[Voice], spoken: list["Spoken"], threshold: float = REGROUP) -> None:
    """End of recording: merge voices that turned out to be the same person, then move each
    reliable utterance to its closest final voice (early ones were matched to immature voices)."""
    groups = {v.key: v.total.copy() for v in voices if v.duration_s > 0}
    weights = {v.key: v.duration_s for v in voices}
    merged = {v.key: v.key for v in voices}
    while len(groups) > 1:
        keys = list(groups)
        centroids = np.stack([groups[k] / (np.linalg.norm(groups[k]) or 1.0) for k in keys])
        similarity = centroids @ centroids.T
        np.fill_diagonal(similarity, -np.inf)
        a, b = np.unravel_index(int(np.argmax(similarity)), similarity.shape)
        if similarity[a, b] < threshold:
            break
        keep, drop = sorted((keys[a], keys[b]), key=lambda k: -weights[k])
        groups[keep] = groups[keep] + groups.pop(drop)
        weights[keep] += weights[drop]
        merged = {k: keep if v == drop else v for k, v in merged.items()}

    def centroid(key: int) -> np.ndarray:
        return groups[key] / (np.linalg.norm(groups[key]) or 1.0)

    main = [k for k in groups if weights[k] >= SMALL_VOICE_S]
    for small in [k for k in groups if weights[k] < SMALL_VOICE_S] if main else []:
        target = max(main, key=lambda k: float(centroid(k) @ centroid(small)))
        if weights[small] < TINY_VOICE_S or float(centroid(target) @ centroid(small)) >= ABSORB:
            groups[target] = groups[target] + groups.pop(small)
            weights[target] += weights[small]
            merged = {k: target if v == small else v for k, v in merged.items()}
    keys = list(groups)
    centroids = np.stack([groups[k] / (np.linalg.norm(groups[k]) or 1.0) for k in keys])
    for utterance in spoken:
        utterance.key = merged[utterance.key]
        if utterance.voice_print is not None and utterance.duration_s >= MIN_RELIABLE_S:
            utterance.key = keys[int(np.argmax(centroids @ utterance.voice_print))]


@dataclass
class Spoken:
    """One utterance of a source whose speakers are told apart, and the segments it gave."""

    source: str
    voice_print: np.ndarray | None
    duration_s: float
    key: int
    segment_ids: list[int] = field(default_factory=list)
    start_s: float = 0.0  # imported files: position of this speech turn
    end_s: float = 0.0


class MeetingVoices:
    """Speakers of one meeting: numbered "Speaker N" labels, live then regrouped at the end, and
    the names given to them. Voices of different sources are never merged."""

    def __init__(self, label: Callable[[int], str]) -> None:
        self.label = label
        self.names: dict[int, str] = {}
        self.spoken: list[Spoken] = []
        self._sources: dict[str, OnlineVoices] = {}
        self._keys = itertools.count(1)

    def assign(self, source: str, voice_print: np.ndarray | None, duration_s: float) -> Spoken:
        voices = self._sources.setdefault(source, OnlineVoices())
        key = voices.assign(voice_print, duration_s, lambda: next(self._keys))
        self.names.setdefault(key, self.label(key))
        utterance = Spoken(source, voice_print, duration_s, key)
        self.spoken.append(utterance)
        return utterance

    def name(self, utterance: Spoken) -> str:
        return self.names[utterance.key]

    def current(self, source: str) -> str | None:
        """Last speaker heard on a source (provisional text of the sentence being spoken)."""
        voices = self._sources.get(source)
        return self.names.get(voices.last) if voices and voices.last is not None else None

    def snapshot(self) -> dict:
        """Known voices and their names, to go on with the same labels after a restart."""
        return {
            "names": {str(k): v for k, v in self.names.items()},
            "next": max(self.names, default=0) + 1,
            "sources": {
                source: [[v.key, v.duration_s, v.total.tolist()] for v in voices.voices]
                for source, voices in self._sources.items()
            },
        }

    def restore(self, state: dict) -> None:
        self.names = {int(k): v for k, v in state["names"].items()}
        self._keys = itertools.count(int(state["next"]))
        for source, voices in state["sources"].items():
            self._sources[source] = OnlineVoices(
                [Voice(int(k), np.asarray(total, np.float32), float(d)) for k, d, total in voices]
            )

    def rename(self, old: str, new: str) -> None:
        self.names = {k: new if name == old else name for k, name in self.names.items()}

    def regroup(self) -> dict[int, str]:
        """Final grouping; unnamed voices are numbered again by first appearance.
        Returns the speaker of every segment."""
        for source, voices in self._sources.items():
            regroup(voices.voices, [s for s in self.spoken if s.source == source])
        given = {name for key, name in self.names.items() if name != self.label(key)}
        numbers = (n for n in itertools.count(1) if self.label(n) not in given)
        names: dict[int, str] = {}
        for utterance in self.spoken:
            if utterance.key not in names:
                name = self.names[utterance.key]
                names[utterance.key] = name if name in given else self.label(next(numbers))
        self.names = names
        return {i: names[s.key] for s in self.spoken for i in s.segment_ids}


# A run of fewer words than this does not make a sentence of its own: it stays with its neighbor
MIN_RUN_WORDS = 3


def split_by_speaker(
    words: list[tuple[float, float, str]], turns: list[tuple[float, float, str]]
) -> list[tuple[float, float, str, str]]:
    """Cut a sentence where the speaker changes: each word goes to the speech turn (start, end,
    speaker) around its middle, or the closest one. Returns (start, end, text, speaker) parts."""
    if not words or not turns:
        return []

    def speaker(start: float, end: float) -> str:
        middle = (start + end) / 2
        turn = min(turns, key=lambda t: 0.0 if t[0] <= middle <= t[1] else min(
            abs(middle - t[0]), abs(middle - t[1])
        ))  # fmt: skip
        return turn[2]

    runs: list[tuple[str, list]] = []  # consecutive words of one speaker
    for word in words:
        name = speaker(word[0], word[1])
        if runs and runs[-1][0] == name:
            runs[-1][1].append(word)
        else:
            runs.append((name, [word]))
    # A few words never stand alone: they join the previous run (the next one at the start)
    merged: list[tuple[str, list]] = []
    for name, run_words in runs:
        if merged and (len(run_words) < MIN_RUN_WORDS or merged[-1][0] == name):
            merged[-1][1].extend(run_words)
        elif merged and len(merged[-1][1]) < MIN_RUN_WORDS:
            merged[-1] = (name, merged[-1][1] + run_words)
        else:
            merged.append((name, list(run_words)))
    return [
        (run_words[0][0], run_words[-1][1], "".join(w[2] for w in run_words).strip(), name)
        for name, run_words in merged
    ]
