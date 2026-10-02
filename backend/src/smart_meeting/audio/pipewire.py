"""Linux backend: PipeWire."""

from smart_meeting.audio.backend import OnAudio
from smart_meeting.audio.pipewire_capture import PipeWireCapture
from smart_meeting.audio.pipewire_devices import list_devices, pw_dump, resolve_in_use
from smart_meeting.models import AudioDevices, Source


class PipeWireBackend:
    name = "pipewire"

    async def list_devices(self) -> AudioDevices:
        return await list_devices()

    async def resolve_in_use(
        self, fallback_to_defaults: bool = True
    ) -> tuple[str | None, str | None]:
        return resolve_in_use(await pw_dump(), fallback_to_defaults=fallback_to_defaults)

    def create_capture(
        self, source: Source, target: str | None, on_audio: OnAudio, sample_rate: int
    ) -> PipeWireCapture:
        return PipeWireCapture(
            name=source,
            target=target,
            # The "remote" source records the output's monitor: what the user hears.
            capture_sink=source == "remote",
            on_audio=on_audio,
            sample_rate=sample_rate,
        )
