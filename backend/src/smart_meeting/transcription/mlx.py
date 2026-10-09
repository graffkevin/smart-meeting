"""MLX engine (mlx-whisper): Whisper on the GPU of Apple Silicon chips.

About 5 times faster than faster-whisper on their CPU, which lets the large-v3-turbo model run
live where the CPU only kept up with small. No beam search: greedy decoding, with the low
temperature retry of the other engines.
"""

import logging
from collections.abc import Callable

import numpy as np

from smart_meeting.transcription.base import (
    SAMPLE_RATE,
    TEMPERATURES,
    TranscribedPiece,
    Transcriber,
    blocks,
    is_hallucination,
)
from smart_meeting.transcription.language import LanguageTracker

logger = logging.getLogger(__name__)

# Model sizes and their MLX conversion on Hugging Face
REPOSITORIES = {
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


class MlxTranscriber(Transcriber):
    def load(self) -> None:
        import mlx.core as mx
        import mlx_whisper  # noqa: F401 (fails here when MLX has no GPU to run on)
        from mlx_whisper.transcribe import ModelHolder

        name = self.settings.whisper_model
        if name == "auto":
            name = "large-v3-turbo"
        self._repository = REPOSITORIES.get(name, name)
        logger.info("Loading Whisper %s with MLX", self._repository)
        # Kept by mlx-whisper between calls; also used here for the language detection
        self._dtype = mx.float16  # mlx-whisper's default
        self._model = ModelHolder.get_model(self._repository, self._dtype)
        # Warm-up so the first utterance is not delayed
        self._run(np.zeros(SAMPLE_RATE, dtype=np.float32), language="fr")
        self.model_name = name
        self.device = "gpu"

    def _run(self, audio: np.ndarray, **options) -> dict:
        import mlx_whisper

        return mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self._repository,
            temperature=options.pop("temperature", TEMPERATURES),
            condition_on_previous_text=False,
            verbose=None,
            **options,
        )

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim

        mel = log_mel_spectrogram(audio, n_mels=self._model.dims.n_mels, padding=N_SAMPLES)
        _, probabilities = self._model.detect_language(
            pad_or_trim(mel, N_FRAMES, axis=-2).astype(self._dtype)
        )
        language = max(probabilities, key=probabilities.get)
        return language, float(probabilities[language])

    def transcribe(
        self, audio: np.ndarray, tracker: LanguageTracker, previous_text: str = ""
    ) -> list[TranscribedPiece]:
        language = tracker.language
        if tracker.automatic:
            detected, probability = self.detect_language(audio)
            language = tracker.observe(detected, probability, len(audio) / SAMPLE_RATE)
        result = self._run(
            audio, language=language, initial_prompt=self._prompt(previous_text) or None
        )
        return [
            TranscribedPiece(s["start"], s["end"], s["text"].strip())
            for s in result["segments"]
            if not is_hallucination(s["text"], s["no_speech_prob"], s["avg_logprob"])
        ]

    def transcribe_partial(self, audio: np.ndarray, language: str, previous_text: str = "") -> str:
        result = self._run(
            audio,
            language=language,
            temperature=0.0,
            initial_prompt=self._prompt(previous_text) or None,
            without_timestamps=True,
        )
        return " ".join(
            s["text"].strip()
            for s in result["segments"]
            if not is_hallucination(s["text"], s["no_speech_prob"], s["avg_logprob"])
        )

    def transcribe_file(
        self,
        audio: np.ndarray,
        language: str | None,
        on_piece: Callable[[TranscribedPiece], bool],
    ) -> None:
        """Block by block: mlx-whisper only returns a passage once fully decoded."""
        starts = list(blocks(audio))
        for start, end in zip(starts, [*starts[1:], len(audio)], strict=True):
            if language is None:
                language, _ = self.detect_language(audio[start:end])
            result = self._run(
                audio[start:end],
                language=language,
                initial_prompt=self.settings.whisper_glossary or None,
                word_timestamps=True,
                # Skips what Whisper invents in long silences (it has no VAD of its own here)
                hallucination_silence_threshold=2.0,
            )
            offset = start / SAMPLE_RATE
            for s in result["segments"]:
                if is_hallucination(s["text"], s["no_speech_prob"], s["avg_logprob"]):
                    continue
                words = [
                    (w["start"] + offset, w["end"] + offset, w["word"]) for w in s.get("words", [])
                ]
                piece = TranscribedPiece(
                    s["start"] + offset, s["end"] + offset, s["text"].strip(), words
                )
                if not on_piece(piece):
                    return
