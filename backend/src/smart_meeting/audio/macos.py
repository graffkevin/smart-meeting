"""macOS backend (13 Ventura or later).

- Microphone: PortAudio through sounddevice.
- What the user hears: ScreenCaptureKit system audio capture (all outputs, this app
  excluded). macOS asks once for the "Screen & System Audio Recording" permission, granted to
  the terminal running Smart Meeting; it must then be restarted.

Not tested on a real Mac yet.
"""

import asyncio
import logging
import subprocess
import threading

import numpy as np

from smart_meeting.audio.backend import OnAudio, PermissionNeeded
from smart_meeting.audio.threaded import ThreadedCapture
from smart_meeting.messages import tr
from smart_meeting.models import AudioDevice, AudioDevices, Source

logger = logging.getLogger(__name__)

SYSTEM_AUDIO = "system"
SCK_RATE = 48000


# Inputs that carry the sound of an application, not a voice: the call itself (Teams, Zoom, Webex
# install one), or routing tools. Taken as the microphone, everything the others say is
# transcribed twice.
VIRTUAL_INPUTS = (
    "microsoft teams audio", "zoomaudiodevice", "zoom audio", "webex", "blackhole",
    "soundflower", "loopback", "virtual",
)  # fmt: skip


def is_virtual(name: str) -> bool:
    return any(marker in name.lower() for marker in VIRTUAL_INPUTS)


def real_microphone(inputs: list[dict], default_index: int | None) -> dict | None:
    """The default input, unless it is virtual: then the built-in microphone, else the first real
    input (a headset)."""
    default = next((d for d in inputs if d["index"] == default_index), None)
    if default is not None and not is_virtual(default["name"]):
        return default
    real = [d for d in inputs if not is_virtual(d["name"])]
    built_in = [
        d for d in real if any(w in d["name"].lower() for w in ("macbook", "built-in", "intégré"))
    ]
    return (built_in or real or [default])[0]


class MicCapture(ThreadedCapture):
    def __init__(self, target: str | None, on_audio: OnAudio, sample_rate: int) -> None:
        super().__init__(target, on_audio, sample_rate)
        self._stream = None

    def _open(self) -> None:
        import sounddevice as sd

        device = (
            sd.query_devices(self.target, "input") if self.target else _automatic_microphone(sd)
        )
        rate = int(device["default_samplerate"])
        self._stream = sd.InputStream(
            device=device["index"],
            channels=1,
            samplerate=rate,
            dtype="float32",
            callback=lambda indata, frames, time, status: self._push(indata.copy(), rate),
        )
        self._stream.start()
        self.target = self.target or device["name"]

    def _close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


class SystemAudioCapture(ThreadedCapture):
    """ScreenCaptureKit stream with audio only (a tiny video size is still required)."""

    def __init__(self, on_audio: OnAudio, sample_rate: int) -> None:
        super().__init__(SYSTEM_AUDIO, on_audio, sample_rate)
        self._stream = None
        self._output = None

    def _open(self) -> None:
        import CoreMedia
        import ScreenCaptureKit as SCK

        content = _wait(SCK.SCShareableContent.getShareableContentWithCompletionHandler_)
        if not content.displays():
            raise PermissionNeeded(tr("macos_permission"))
        content_filter = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(
            content.displays()[0], []
        )
        config = SCK.SCStreamConfiguration.alloc().init()
        config.setCapturesAudio_(True)
        config.setExcludesCurrentProcessAudio_(True)
        config.setSampleRate_(SCK_RATE)
        config.setChannelCount_(1)
        config.setWidth_(2)
        config.setHeight_(2)
        config.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, 1))

        self._output = _make_output(lambda samples: self._push(samples, SCK_RATE))
        self._stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(
            content_filter, config, None
        )
        added = self._stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._output, SCK.SCStreamOutputTypeAudio, None, None
        )
        if not (added[0] if isinstance(added, tuple) else added):
            raise RuntimeError(tr("system_audio_failed"))
        _wait(self._stream.startCaptureWithCompletionHandler_, has_result=False)

    def _close(self) -> None:
        if self._stream is not None:
            _wait(self._stream.stopCaptureWithCompletionHandler_, has_result=False)


def _wait(method, has_result: bool = True, timeout: float = 10):
    """Call an Objective-C method taking a completion handler and wait for it."""
    done = threading.Event()
    outcome: dict = {}

    def handler(*args):
        outcome["args"] = args
        done.set()

    method(handler)
    if not done.wait(timeout):
        raise PermissionNeeded(f"{tr('macos_no_answer')} {tr('macos_permission')}")
    args = outcome["args"]
    error = args[-1]
    if error is not None:
        raise PermissionNeeded(f"{error.localizedDescription()} {tr('macos_permission')}")
    return args[0] if has_result else None


def _make_output(on_samples):
    """SCStreamOutput delegate converting audio sample buffers to numpy (mono float32)."""
    import CoreMedia
    import objc
    import ScreenCaptureKit as SCK
    from Foundation import NSObject

    class AudioOutput(NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]):
        def stream_didOutputSampleBuffer_ofType_(self, stream, sample_buffer, output_type):
            if output_type != SCK.SCStreamOutputTypeAudio:
                return
            block = CoreMedia.CMSampleBufferGetDataBuffer(sample_buffer)
            if block is None:
                return
            length = CoreMedia.CMBlockBufferGetDataLength(block)
            status, data = CoreMedia.CMBlockBufferCopyDataBytes(block, 0, length, None)
            if status == 0 and data:
                on_samples(np.frombuffer(bytes(data), dtype=np.float32))

    return AudioOutput.alloc().init()


# System Settings > Privacy & Security > Screen & System Audio Recording
PERMISSION_SETTINGS = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)


def _automatic_microphone(sd) -> dict:
    inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
    default_index = sd.query_devices(kind="input")["index"]
    return real_microphone(inputs, default_index) or sd.query_devices(kind="input")


class MacBackend:
    name = "macos"

    def open_permission_settings(self) -> None:
        """Open the settings where the user allows the capture of the system audio."""
        subprocess.Popen(["open", PERMISSION_SETTINGS])

    async def list_devices(self) -> AudioDevices:
        import sounddevice as sd

        devices = await asyncio.to_thread(sd.query_devices)
        default_in = (await asyncio.to_thread(sd.query_devices, kind="input"))["index"]
        sources = [
            AudioDevice(name=d["name"], description=d["name"], is_default=d["index"] == default_in)
            for d in devices
            if d["max_input_channels"] > 0
        ]
        # Automatic mode: the real microphone, the default input unless it is virtual
        inputs = [d for d in devices if d["max_input_channels"] > 0]
        chosen = real_microphone(inputs, default_in)
        default_name = chosen["name"] if chosen else None
        return AudioDevices(
            sources=sorted(sources, key=lambda d: not d.is_default),
            sinks=[
                AudioDevice(
                    name=SYSTEM_AUDIO,
                    description=tr("system_audio"),
                    is_default=True,
                )
            ],
            in_use_source=default_name,
            in_use_sink=SYSTEM_AUDIO,
        )

    async def resolve_in_use(
        self, fallback_to_defaults: bool = True
    ) -> tuple[str | None, str | None]:
        # System audio covers every output; the microphone is the default one.
        return (None, None) if not fallback_to_defaults else (None, SYSTEM_AUDIO)

    def create_capture(
        self, source: Source, target: str | None, on_audio: OnAudio, sample_rate: int
    ) -> ThreadedCapture:
        if source == "remote":
            return SystemAudioCapture(on_audio, sample_rate)
        return MicCapture(target, on_audio, sample_rate)
