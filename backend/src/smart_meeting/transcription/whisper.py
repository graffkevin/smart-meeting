import ctypes
import glob
import logging
import os
import re
import site
import sys
import unicodedata
from dataclasses import dataclass

import numpy as np

from smart_meeting.config import Settings

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
        logger.info("Loading Whisper %s on %s (%s)", name, device, compute_type)
        model = WhisperModel(name, device=device, compute_type=compute_type)
        # Warm-up so the first real utterance is not delayed (and CUDA errors surface now).
        list(model.transcribe(np.zeros(16000, dtype=np.float32), language="fr")[0])
        self._model = model
        self.model_name = name
        self.device = f"{device}/{compute_type}"

    def transcribe(self, audio: np.ndarray, previous_text: str = "") -> list[TranscribedPiece]:
        if self._model is None:
            raise RuntimeError("Whisper model is not loaded")
        prompt = " ".join(p for p in (self.settings.whisper_glossary, previous_text[-200:]) if p)
        segments, _ = self._model.transcribe(
            audio,
            language=self.settings.whisper_language,
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
