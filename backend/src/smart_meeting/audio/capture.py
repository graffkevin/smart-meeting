"""Audio capture through `pw-record` subprocesses.

One process per source, emitting raw mono s16le PCM at 16 kHz on stdout. PipeWire does the
resampling and downmix. Capturing a sink with `stream.capture.sink = true` records its monitor,
i.e. exactly what is played in the headset, without touching the routing of other apps.
"""

import asyncio
import logging
from collections.abc import Callable

import numpy as np

logger = logging.getLogger(__name__)

BLOCK_MS = 100


class PipeWireCapture:
    def __init__(
        self,
        name: str,
        target: str | None,
        capture_sink: bool,
        on_audio: Callable[[np.ndarray], None],
        sample_rate: int = 16000,
    ) -> None:
        self.name = name
        self.target = target
        self.capture_sink = capture_sink
        self.on_audio = on_audio
        self.sample_rate = sample_rate
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stopping = False

    def command(self) -> list[str]:
        props = [f'node.name = "smart-meeting-{self.name}"']
        if self.capture_sink:
            props.append("stream.capture.sink = true")
        cmd = [
            "pw-record",
            "--rate", str(self.sample_rate),
            "--channels", "1",
            "--format", "s16",
            "--latency", "50ms",
            "--properties", "{ " + " ".join(props) + " }",
        ]  # fmt: skip
        if self.target:
            cmd += ["--target", self.target]
        return [*cmd, "-"]

    async def start(self) -> None:
        cmd = self.command()
        logger.info("Starting capture %s: %s", self.name, " ".join(cmd))
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        self._reader = asyncio.create_task(self._read_loop(), name=f"capture-{self.name}")

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        block_bytes = self.sample_rate * BLOCK_MS // 1000 * 2
        while True:
            try:
                data = await self._proc.stdout.readexactly(block_bytes)
            except asyncio.IncompleteReadError as exc:
                data = exc.partial[: len(exc.partial) // 2 * 2]
                if data:
                    self._emit(data)
                break
            self._emit(data)
        await self._proc.wait()
        if self._proc.returncode != 0 and not self._stopping:
            stderr = await self._proc.stderr.read() if self._proc.stderr else b""
            logger.error(
                "pw-record %s exited with %s: %s",
                self.name,
                self._proc.returncode,
                stderr.decode().strip(),
            )

    def _emit(self, data: bytes) -> None:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            self.on_audio(samples)
        except Exception:
            logger.exception("Audio callback failed for %s", self.name)

    async def stop(self) -> None:
        """Stop pw-record and wait until every captured sample has been delivered."""
        self._stopping = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
        if self._reader:
            await self._reader
