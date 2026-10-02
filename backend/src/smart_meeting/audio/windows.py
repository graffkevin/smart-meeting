"""Windows backend: WASAPI through PyAudioWPatch.

What the user hears is captured with WASAPI loopback on the output device: a digital copy of
what is sent to it, no driver or virtual device needed. Devices are identified by name since
PortAudio indexes change when devices are plugged in.

Not tested on a real Windows machine yet.
"""

import asyncio

import numpy as np

from smart_meeting.audio.backend import OnAudio
from smart_meeting.audio.threaded import ThreadedCapture
from smart_meeting.messages import tr
from smart_meeting.models import AudioDevice, AudioDevices, Source

FRAMES_PER_BUFFER = 1024


def _pyaudio():
    import pyaudiowpatch

    return pyaudiowpatch


def _wasapi_devices(pa) -> tuple[list[dict], dict, dict]:
    """(WASAPI devices, default input, default output)."""
    pyaudio = _pyaudio()
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    devices = [
        pa.get_device_info_by_index(i)
        for i in range(pa.get_device_count())
        if pa.get_device_info_by_index(i)["hostApi"] == wasapi["index"]
    ]
    default_in = pa.get_device_info_by_index(wasapi["defaultInputDevice"])
    default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    return devices, default_in, default_out


class WasapiCapture(ThreadedCapture):
    def __init__(self, source: Source, target: str | None, on_audio: OnAudio, sample_rate: int):
        super().__init__(target, on_audio, sample_rate)
        self.source = source
        self._pa = None
        self._stream = None

    def _find_device(self, devices: list[dict], default_in: dict, default_out: dict) -> dict:
        if self.source == "mic":
            wanted = self.target or default_in["name"]
            return next(
                d
                for d in devices
                if d["name"] == wanted and d["maxInputChannels"] > 0 and not d["isLoopbackDevice"]
            )
        # Loopback devices are named after their output device, e.g. "Speakers (...) [Loopback]".
        output = self.target or default_out["name"]
        return next(d for d in devices if d["isLoopbackDevice"] and d["name"].startswith(output))

    def _open(self) -> None:
        pyaudio = _pyaudio()
        self._pa = pyaudio.PyAudio()
        try:
            device = self._find_device(*_wasapi_devices(self._pa))
        except StopIteration:
            self._pa.terminate()
            raise RuntimeError(
                tr("device_not_found", device=self.target or tr("default_device"))
            ) from None
        channels = max(1, int(device["maxInputChannels"]))
        rate = int(device["defaultSampleRate"])

        def callback(in_data, frame_count, time_info, status):
            frames = np.frombuffer(in_data, dtype=np.float32).reshape(-1, channels)
            self._push(frames, rate)
            return None, pyaudio.paContinue

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=FRAMES_PER_BUFFER,
            stream_callback=callback,
        )
        self.target = self.target or device["name"]

    def _close(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa is not None:
            self._pa.terminate()


class WasapiBackend:
    name = "wasapi"

    def _snapshot(self) -> tuple[list[dict], dict, dict]:
        pa = _pyaudio().PyAudio()
        try:
            return _wasapi_devices(pa)
        finally:
            pa.terminate()

    async def list_devices(self) -> AudioDevices:
        devices, default_in, default_out = await asyncio.to_thread(self._snapshot)
        sources = [
            AudioDevice(
                name=d["name"], description=d["name"], is_default=d["name"] == default_in["name"]
            )
            for d in devices
            if d["maxInputChannels"] > 0 and not d["isLoopbackDevice"]
        ]
        sinks = [
            AudioDevice(
                name=d["name"], description=d["name"], is_default=d["name"] == default_out["name"]
            )
            for d in devices
            if d["maxOutputChannels"] > 0 and not d["isLoopbackDevice"]
        ]
        return AudioDevices(
            sources=sorted(sources, key=lambda d: not d.is_default),
            sinks=sorted(sinks, key=lambda d: not d.is_default),
            in_use_source=default_in["name"],
            in_use_sink=default_out["name"],
        )

    async def resolve_in_use(
        self, fallback_to_defaults: bool = True
    ) -> tuple[str | None, str | None]:
        # WASAPI does not tell which device an application uses: the defaults are the best
        # guess, resolved once when the meeting starts.
        if not fallback_to_defaults:
            return None, None
        _, default_in, default_out = await asyncio.to_thread(self._snapshot)
        return default_in["name"], default_out["name"]

    def create_capture(
        self, source: Source, target: str | None, on_audio: OnAudio, sample_rate: int
    ) -> WasapiCapture:
        return WasapiCapture(source, target, on_audio, sample_rate)
