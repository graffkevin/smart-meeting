"""Audio decoding of imported files with ffmpeg (any audio or video container)."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np

CHUNK_S = 1


async def probe_duration(path: Path) -> float | None:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await proc.communicate()
    try:
        return float(json.loads(stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        return None


@asynccontextmanager
async def decode_audio(path: Path, sample_rate: int) -> AsyncIterator[AsyncIterator[np.ndarray]]:
    """Yield an iterator of mono float32 chunks; the ffmpeg process is killed on exit."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    assert proc.stdout and proc.stderr

    async def chunks() -> AsyncIterator[np.ndarray]:
        chunk_bytes = sample_rate * CHUNK_S * 2
        while True:
            try:
                data = await proc.stdout.readexactly(chunk_bytes)
            except asyncio.IncompleteReadError as exc:
                data = exc.partial[: len(exc.partial) // 2 * 2]
                if data:
                    yield np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                break
            yield np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if await proc.wait() != 0:
            stderr = (await proc.stderr.read()).decode().strip()
            raise RuntimeError(
                f"Décodage impossible : {stderr.splitlines()[-1] if stderr else proc.returncode}"
            )

    try:
        yield chunks()
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
