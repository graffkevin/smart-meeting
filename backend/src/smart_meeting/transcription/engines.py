"""Choice of the transcription engine from the hardware, with a fallback.

- Apple Silicon: MLX, on the GPU of the chip.
- NVIDIA GPU: faster-whisper on CUDA.
- Anything else, Intel included: faster-whisper on the CPU. OpenVINO, Intel's engine, only when
  chosen (SM_WHISPER_ENGINE=openvino, installed by the `intel` extra the launcher adds): measured
  on an Intel UHD (TigerLake) it ran slower than real time on that GPU, so a meeting fell behind
  for good, and on the CPU it made more mistakes live than faster-whisper, which keeps up there.

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
    else:
        order = []  # faster-whisper, on CUDA with an NVIDIA GPU (its own device detection)
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

    def lighter(self) -> tuple[str, Settings] | None:
        """The next lighter setting when the live transcription falls behind: the small model on
        the same engine, then faster-whisper small on the CPU. None when already there."""
        if self._engine is None or self.engine is None:
            return None
        small = {"whisper_model": "small", "whisper_partial_model": "none"}
        if self._engine.model_name != "small":
            return self.engine, self.settings.model_copy(update=small)
        if self.engine != "faster-whisper":
            cpu = {**small, "whisper_engine": "faster-whisper", "whisper_device": "cpu"}
            return "faster-whisper", self.settings.model_copy(update=cpu)
        return None

    def lighten(self) -> str | None:
        """Load the next lighter setting and use it from now on; returns what now transcribes.
        Whisper thread only, like every call."""
        step = self.lighter()
        if step is None:
            return None
        name, settings = step
        engine = self._factory(name, settings)
        engine.load()
        self._engine, self.engine, self.settings = engine, name, settings
        logger.warning("Transcription lightened to %s %s", name, engine.model_name)
        return f"{self.model_name} ({self.device})"

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
