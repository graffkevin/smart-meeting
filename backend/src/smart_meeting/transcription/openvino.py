"""OpenVINO engine (openvino-genai): Whisper on Intel GPUs (integrated Iris Xe, Arc) and CPUs.

The GPU needs Intel's compute driver (intel-opencl-icd on Linux, included in the Windows
graphics driver); without it the CPU is used. Models come already converted from the OpenVINO
organization on Hugging Face, quantized to 8 bits.

Compared with faster-whisper: greedy decoding (no beam search), no probability for the detected
language nor "no speech" score per sentence, so the language of an utterance counts as sure once
it is long enough, and only the known phrases are filtered as hallucinations.
"""

import logging
from collections.abc import Callable

import numpy as np

from smart_meeting.transcription.base import (
    SAMPLE_RATE,
    TranscribedPiece,
    Transcriber,
    blocks,
    is_hallucination,
)
from smart_meeting.transcription.language import LanguageTracker

logger = logging.getLogger(__name__)

# The language of a long enough utterance is taken as detected for sure (no probability given)
DETECTED = 1.0


def repository(name: str) -> str:
    return name if "/" in name else f"OpenVINO/whisper-{name}-int8-ov"


def pick_device(devices: list[str], discrete: Callable[[str], bool], wanted: str) -> str:
    """GPU when there is one (a discrete card before the integrated one), else the CPU."""
    if wanted != "auto":
        return wanted.upper()
    gpus = [d for d in devices if d.startswith("GPU")]
    return next((d for d in gpus if discrete(d)), gpus[0] if gpus else "CPU")


def pieces(result, offset: float = 0.0) -> list[TranscribedPiece]:
    """Sentences of a result with timestamps, each with the words that start within it."""
    words = [(w.start_ts + offset, w.end_ts + offset, w.word) for w in (result.words or [])]
    found = []
    for chunk in result.chunks or []:
        if is_hallucination(chunk.text):
            continue
        start, end = chunk.start_ts + offset, chunk.end_ts + offset
        inside = [w for w in words if start - 0.01 <= w[0] < end]
        found.append(TranscribedPiece(start, end, chunk.text.strip(), inside))
    return found


class OpenVinoTranscriber(Transcriber):
    def load(self) -> None:
        import openvino as ov
        import openvino_genai
        from huggingface_hub import snapshot_download

        core = ov.Core()

        def discrete(device: str) -> bool:
            return str(core.get_property(device, "DEVICE_TYPE")).endswith("DISCRETE")

        device = pick_device(core.available_devices, discrete, self.settings.whisper_device)
        name = self.settings.whisper_model
        if name == "auto":
            # On CPU, small keeps up with live meetings
            name = "large-v3-turbo" if device.startswith("GPU") else "small"
        # Compiled models kept on disk: a GPU compiles them for a long time on the first load
        cache = self.settings.data_dir / "openvino-cache"

        def load_model(model_name: str):
            logger.info("Loading Whisper %s with OpenVINO on %s", repository(model_name), device)
            pipeline = openvino_genai.WhisperPipeline(
                snapshot_download(repository(model_name)),
                device,
                word_timestamps=True,
                CACHE_DIR=str(cache),
            )
            # Warm-up so the first utterance is not delayed (and driver errors surface now)
            pipeline.generate(np.zeros(SAMPLE_RATE, dtype=np.float32), language="<|fr|>")
            return pipeline

        self._pipeline = load_model(name)
        partial = self.settings.whisper_partial_model
        if partial == "auto":
            partial = "small" if device.startswith("GPU") and name != "small" else name
        if partial == "none":
            self._partial = None
        else:
            self._partial = self._pipeline if partial == name else load_model(partial)
        self.model_name = name
        self.device = device

    def _generate(self, pipeline, audio: np.ndarray, language: str | None, prompt: str, **options):
        if language:
            options["language"] = f"<|{language}|>"
        if prompt:
            options["initial_prompt"] = prompt
        return pipeline.generate(audio, task="transcribe", **options)

    def transcribe(
        self, audio: np.ndarray, tracker: LanguageTracker, previous_text: str = ""
    ) -> list[TranscribedPiece]:
        prompt = self._prompt(previous_text)
        if not tracker.automatic:
            result = self._generate(
                self._pipeline, audio, tracker.language, prompt, return_timestamps=True
            )
            return pieces(result)
        # Detected while transcribing; done again in the language the tracker keeps, if other
        result = self._generate(self._pipeline, audio, None, prompt, return_timestamps=True)
        detected = result.language.strip("<|>")
        language = tracker.observe(detected, DETECTED, len(audio) / SAMPLE_RATE)
        if language != detected:
            result = self._generate(self._pipeline, audio, language, prompt, return_timestamps=True)
        return pieces(result)

    def transcribe_partial(self, audio: np.ndarray, language: str, previous_text: str = "") -> str:
        if self._partial is None:
            return ""
        result = self._generate(self._partial, audio, language, self._prompt(previous_text))
        text = result.texts[0] if result.texts else ""
        return "" if is_hallucination(text) else text.strip()

    def transcribe_file(
        self,
        audio: np.ndarray,
        language: str | None,
        on_piece: Callable[[TranscribedPiece], bool],
    ) -> None:
        """Block by block: OpenVINO only returns a passage once fully decoded."""
        starts = list(blocks(audio))
        for start, end in zip(starts, [*starts[1:], len(audio)], strict=True):
            result = self._generate(
                self._pipeline,
                audio[start:end],
                language,
                self.settings.whisper_glossary,
                return_timestamps=True,
                word_timestamps=True,
            )
            # Detected on the first block, kept for the others
            language = language or result.language.strip("<|>")
            for piece in pieces(result, start / SAMPLE_RATE):
                if not on_piece(piece):
                    return
