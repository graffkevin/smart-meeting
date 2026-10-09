"""Choice of the transcription engine from the hardware, with a fallback.

- Apple Silicon: MLX, on the GPU of the chip.
- NVIDIA GPU: faster-whisper on CUDA.
- Intel CPU or GPU (integrated Iris Xe, Arc): OpenVINO, Intel's engine, on the GPU when its
  driver is there, else on the CPU. Installed by the `intel` extra (the launcher adds it).
- Anything else: faster-whisper on the CPU.

An engine that is not installed is skipped; one that fails to load (missing driver, old GPU)
gives way to the next one, faster-whisper on CPU last.
"""

import importlib.util
import logging
from collections.abc import Callable

from smart_meeting.config import Settings
from smart_meeting.hardware import Hardware, detect_hardware
from smart_meeting.transcription.base import Transcriber

logger = logging.getLogger(__name__)

ENGINES = ("faster-whisper", "mlx", "openvino")
# Module that must be importable for each engine
MODULES = {"faster-whisper": "faster_whisper", "mlx": "mlx_whisper", "openvino": "openvino_genai"}


def _installed(engine: str) -> bool:
    return importlib.util.find_spec(MODULES[engine]) is not None


def engine_order(settings: Settings, hardware: Hardware) -> list[str]:
    """Engines to try, best first."""
    chosen = settings.whisper_engine
    if chosen != "auto":
        if chosen not in ENGINES:
            choices = ", ".join(ENGINES)
            raise ValueError(f"Unknown transcription engine: {chosen} (one of {choices})")
        order = [chosen]
    elif hardware.apple_silicon:
        order = ["mlx"]
    elif hardware.nvidia:
        order = []  # faster-whisper on CUDA, its own device detection
    elif hardware.intel:
        order = ["openvino"]
    else:
        order = []
    order.append("faster-whisper")
    return [engine for engine in dict.fromkeys(order) if _installed(engine)]


def _engine(name: str, settings: Settings) -> Transcriber:
    if name == "mlx":
        from smart_meeting.transcription.mlx import MlxTranscriber

        return MlxTranscriber(settings)
    if name == "openvino":
        from smart_meeting.transcription.openvino import OpenVinoTranscriber

        return OpenVinoTranscriber(settings)
    from smart_meeting.transcription.whisper import WhisperTranscriber

    return WhisperTranscriber(settings)


class AutoTranscriber:
    """The first engine of `engine_order` that loads; calls then go to it."""

    def __init__(
        self,
        settings: Settings,
        hardware: Callable[[], Hardware] = detect_hardware,
        factory: Callable[[str, Settings], Transcriber] = _engine,
    ) -> None:
        self.settings = settings
        self._hardware = hardware
        self._factory = factory
        self._engine: Transcriber | None = None
        self.engine: str | None = None

    def load(self) -> None:
        order = engine_order(self.settings, self._hardware())
        for name in order:
            engine = self._factory(name, self.settings)
            try:
                engine.load()
            except Exception:
                if name == order[-1]:
                    raise
                logger.warning(
                    "Transcription engine %s unavailable, trying the next one", name, exc_info=True
                )
                continue
            self._engine, self.engine = engine, name
            logger.info("Transcription engine: %s", name)
            return
        raise RuntimeError("No transcription engine installed")

    @property
    def model_name(self) -> str | None:
        return self._engine.model_name if self._engine else None

    @property
    def device(self) -> str | None:
        return f"{self.engine} {self._engine.device}" if self._engine else None

    def __getattr__(self, name: str):
        # transcribe, transcribe_partial, transcribe_file: only called once loaded
        if name.startswith("_") or self.__dict__.get("_engine") is None:
            raise AttributeError(name)
        return getattr(self._engine, name)


def create_transcriber(settings: Settings) -> AutoTranscriber:
    return AutoTranscriber(settings)
