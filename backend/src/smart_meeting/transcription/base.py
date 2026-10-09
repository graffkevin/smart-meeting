"""What the transcription engines (faster-whisper, MLX, OpenVINO) share."""

import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import numpy as np

from smart_meeting.config import Settings
from smart_meeting.transcription.language import LanguageTracker

SAMPLE_RATE = 16000

# Decoding temperatures. Whisper retries uncertain passages up to 1.0 by default: sampled text
# then often holds plausible but non-existent words. One low retry only.
TEMPERATURES = (0.0, 0.2)

# Phrases Whisper is known to produce on silence or noise (learnt from subtitled videos).
HALLUCINATIONS = [
    "sous-titres realises par la communaute d'amara.org",
    "sous-titrage st' 501",
    "sous-titrage societe radio-canada",
    "merci d'avoir regarde cette video",
    "abonnez-vous",
    "thanks for watching",
]


@dataclass
class TranscribedPiece:
    start_s: float  # relative to the utterance start
    end_s: float
    text: str
    # (start, end, word) of imported files: a sentence can then be split between two speakers
    words: list[tuple[float, float, str]] = field(default_factory=list)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip(" .!?…")


def is_hallucination(text: str, no_speech_prob: float = 0.0, avg_logprob: float = 0.0) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return True
    if any(phrase in normalized for phrase in HALLUCINATIONS):
        return True
    # Same heuristic as Whisper's own: likely silence and low confidence.
    return no_speech_prob > 0.6 and avg_logprob < -1.0


def blocks(audio: np.ndarray, block_s: float = 300.0, search_s: float = 10.0) -> Iterator[int]:
    """Start sample of each block of a long file, for engines that only return a passage once it
    is fully decoded: the import then progresses block by block. Each cut is placed at the
    quietest 100 ms of the last `search_s` seconds of the block, not in the middle of a word."""
    size, search, window = (int(s * SAMPLE_RATE) for s in (block_s, search_s, 0.1))
    start = 0
    while start < len(audio):
        yield start
        end = start + size
        if end >= len(audio):
            return
        region = audio[end - search : end].reshape(-1, window)
        energy = np.sqrt(np.mean(region**2, axis=1))
        start = end - search + int(np.argmin(energy)) * window


class Transcriber:
    """An engine. Not thread-safe: called from a single worker thread, `load` included."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_name: str | None = None
        self.device: str | None = None

    def load(self) -> None:
        raise NotImplementedError

    def transcribe(
        self, audio: np.ndarray, tracker: LanguageTracker, previous_text: str = ""
    ) -> list[TranscribedPiece]:
        """Transcribe an utterance; in automatic mode its language is detected first and the tracker
        decides (sticky language, see transcription/language.py)."""
        raise NotImplementedError

    def transcribe_partial(self, audio: np.ndarray, language: str, previous_text: str = "") -> str:
        """Fast provisional text of an utterance still being spoken: greedy decoding, no language
        detection. Only shown live, replaced by the final transcription."""
        raise NotImplementedError

    def transcribe_file(
        self,
        audio: np.ndarray,
        language: str | None,
        on_piece: Callable[[TranscribedPiece], bool],
    ) -> None:
        """Whole imported file. `language` None: detected once on the start of the file.
        `on_piece` receives the sentences in order, with times relative to the file; it returns
        False to stop."""
        raise NotImplementedError

    def _prompt(self, previous_text: str) -> str:
        """Vocabulary of the user, and the previous sentence only when enabled: an error in it tends
        to spread to the next sentences."""
        context = previous_text[-200:] if self.settings.whisper_previous_context else ""
        return " ".join(p for p in (self.settings.whisper_glossary, context) if p)
