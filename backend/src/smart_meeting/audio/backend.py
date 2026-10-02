"""OS-specific audio capture behind one interface.

Each backend captures two sources: the microphone ("mic") and what is played to the user
("remote"), and delivers mono float32 at 16 kHz to `on_audio`, on the event loop.

- Linux: PipeWire (`pw-record` on the output's monitor, `pw-dump` for devices).
- Windows: WASAPI loopback of the output device (PyAudioWPatch).
- macOS 13+: ScreenCaptureKit for system audio, PortAudio (sounddevice) for the microphone.
"""

import sys
from collections.abc import Callable
from typing import Protocol

import numpy as np

from smart_meeting.models import AudioDevices, Source

OnAudio = Callable[[np.ndarray], None]


class Capture(Protocol):
    target: str | None  # device being captured, None for the system default

    async def start(self) -> None: ...

    async def stop(self) -> None:
        """Stop and deliver every sample captured so far before returning."""
        ...


class AudioBackend(Protocol):
    name: str

    async def list_devices(self) -> AudioDevices: ...

    async def resolve_in_use(
        self, fallback_to_defaults: bool = True
    ) -> tuple[str | None, str | None]:
        """(microphone, output) currently used by applications, for the automatic mode.

        Without fallback, (None, None) means "nothing better known": capture is not switched.
        """
        ...

    def create_capture(
        self, source: Source, target: str | None, on_audio: OnAudio, sample_rate: int
    ) -> Capture: ...


def get_backend() -> AudioBackend:
    if sys.platform.startswith("linux"):
        from smart_meeting.audio.pipewire import PipeWireBackend

        return PipeWireBackend()
    if sys.platform == "win32":
        from smart_meeting.audio.windows import WasapiBackend

        return WasapiBackend()
    if sys.platform == "darwin":
        from smart_meeting.audio.macos import MacBackend

        return MacBackend()
    raise RuntimeError(f"Système non pris en charge : {sys.platform}")
