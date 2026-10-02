import ctypes
import glob
import logging
import os
import re
import site
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from smart_meeting.config import Settings
from smart_meeting.transcription.language import LanguageTracker

logger = logging.getLogger(__name__)

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


def preload_cuda_libraries() -> None:
    """Make pip-installed CUDA 12 libraries (the `cuda` extra) visible to CTranslate2."""
    if sys.platform == "win32":
        # Windows: DLLs live in nvidia/*/bin and are found through the DLL search path.
        for base in site.getsitepackages():
            for directory in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
                os.add_dll_directory(directory)
                os.environ["PATH"] = directory + os.pathsep + os.environ["PATH"]
        return
    patterns = [
        "nvidia/cublas/lib/libcublasLt.so.12",
        "nvidia/cublas/lib/libcublas.so.12",
        "nvidia/cudnn/lib/libcudnn*.so.9",
    ]
    for base in site.getsitepackages():
        for pattern in patterns:
            for path in sorted(glob.glob(os.path.join(base, pattern))):
                try:
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                except OSError as exc:
                    logger.warning("Could not preload %s: %s", path, exc)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip(" .!?…")


def is_hallucination(text: str, no_speech_prob: float, avg_logprob: float) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return True
    if any(phrase in normalized for phrase in HALLUCINATIONS):
        return True
    # Same heuristic as Whisper's own: likely silence and low confidence.
    return no_speech_prob > 0.6 and avg_logprob < -1.0


class WhisperTranscriber:
    """faster-whisper wrapper. Not thread-safe: call from a single worker thread."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._partial_model = None  # fast model for the live provisional text
        self._batched = None  # batched pipeline over the main model, for imported files
        self.batch_size = 4
        self.model_name: str | None = None
        self.device: str | None = None

    def load(self) -> None:
        import ctranslate2

        device = self.settings.whisper_device
        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        if device == "cuda":
            preload_cuda_libraries()
        compute_type = self.settings.whisper_compute_type
        if compute_type == "auto":
            compute_type = "int8_float16" if device == "cuda" else "int8"

        from faster_whisper import WhisperModel

        name = self.settings.whisper_model
        if name == "auto":
            name = "large-v3-turbo" if device == "cuda" else "small"

        def load_model(model_name: str):
            logger.info("Loading Whisper %s on %s (%s)", model_name, device, compute_type)
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            # Warm-up so the first utterance is not delayed (and CUDA errors surface now).
            list(model.transcribe(np.zeros(16000, dtype=np.float32), language="fr")[0])
            return model

        self._model = load_model(name)
        partial = self.settings.whisper_partial_model
        if partial == "auto":
            partial = "small" if device == "cuda" and name != "small" else name
        if partial == "none":
            self._partial_model = None
        else:
            self._partial_model = self._model if partial == name else load_model(partial)
        self.model_name = name
        self.device = f"{device}/{compute_type}"
        # Passages decoded at once for imported files (halved when the GPU runs out of memory)
        self.batch_size = 4

    def transcribe(
        self, audio: np.ndarray, tracker: LanguageTracker, previous_text: str = ""
    ) -> list[TranscribedPiece]:
        """Transcribe an utterance; in automatic mode its language is detected first and the tracker
        decides (sticky language, see transcription/language.py)."""
        if self._model is None:
            raise RuntimeError("Whisper model is not loaded")
        language = tracker.language
        if tracker.automatic:
            detected, probability, _ = self._model.detect_language(audio)
            language = tracker.observe(detected, probability, len(audio) / 16000)
        prompt = " ".join(p for p in (self.settings.whisper_glossary, previous_text[-200:]) if p)
        segments, _ = self._model.transcribe(
            audio,
            language=language,
            beam_size=self.settings.whisper_beam_size,
            initial_prompt=prompt or None,
            # Utterances are already cut by our own VAD and are shorter than 30 s.
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return [
            TranscribedPiece(s.start, s.end, s.text.strip())
            for s in segments
            if not is_hallucination(s.text, s.no_speech_prob, s.avg_logprob)
        ]

    def transcribe_file(
        self,
        audio: np.ndarray,
        language: str | None,
        on_piece: Callable[[TranscribedPiece], bool],
    ) -> None:
        """Whole imported file, several passages decoded at once (faster-whisper batched pipeline,
        its own VAD). `language` None: detected once on the start of the file. `on_piece` receives
        the sentences in order, with times relative to the file; it returns False to stop.

        Out of GPU memory, the batches are halved and the file resumed after the last sentence
        given; the working size is kept for the next files."""
        if self._model is None:
            raise RuntimeError("Whisper model is not loaded")
        from faster_whisper import BatchedInferencePipeline

        if self._batched is None:
            self._batched = BatchedInferencePipeline(model=self._model)
        state = {"last_end": -1.0}
        while True:
            try:
                segments, _ = self._batched.transcribe(
                    audio,
                    language=language,
                    beam_size=self.settings.whisper_beam_size,
                    batch_size=self.batch_size,
                    initial_prompt=self.settings.whisper_glossary or None,
                    without_timestamps=False,
                )
                for s in segments:
                    # Resumed after running out of memory: skip what was already given
                    if s.start < state["last_end"] or is_hallucination(
                        s.text, s.no_speech_prob, s.avg_logprob
                    ):
                        continue
                    state["last_end"] = s.end
                    if not on_piece(TranscribedPiece(s.start, s.end, s.text.strip())):
                        return
                return
            except RuntimeError as exc:
                if "out of memory" not in str(exc) or self.batch_size == 1:
                    raise
                self.batch_size //= 2
                logger.warning("Out of GPU memory: batches of %s passages", self.batch_size)

    def transcribe_partial(self, audio: np.ndarray, language: str, previous_text: str = "") -> str:
        """Fast provisional text of an utterance still being spoken: small model, greedy decoding,
        no language detection. Only shown live, replaced by the final transcription."""
        if self._partial_model is None:
            return ""
        prompt = " ".join(p for p in (self.settings.whisper_glossary, previous_text[-200:]) if p)
        segments, _ = self._partial_model.transcribe(
            audio,
            language=language,
            beam_size=1,
            initial_prompt=prompt or None,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(
            s.text.strip()
            for s in segments
            if not is_hallucination(s.text, s.no_speech_prob, s.avg_logprob)
        )
