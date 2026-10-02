"""Audio decoding of imported files with PyAV (bundled FFmpeg libraries: no system ffmpeg)."""

import asyncio
import itertools
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import av
import numpy as np

CHUNK_S = 1


def _probe_duration(path: Path) -> float | None:
    try:
        with av.open(str(path)) as container:
            return container.duration / av.time_base if container.duration else None
    except av.FFmpegError:
        return None


async def probe_duration(path: Path) -> float | None:
    return await asyncio.to_thread(_probe_duration, path)


@asynccontextmanager
async def decode_audio(path: Path, sample_rate: int) -> AsyncIterator[AsyncIterator[np.ndarray]]:
    """Yield an iterator of mono float32 chunks of about CHUNK_S seconds.

    Decoding runs in a thread; the bounded queue pauses it while the consumer (Whisper) works.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[np.ndarray | Exception | None] = asyncio.Queue(maxsize=4)
    stop = threading.Event()

    def put(item: np.ndarray | Exception | None) -> None:
        future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        while not stop.is_set():
            try:
                future.result(timeout=0.2)
                return
            except TimeoutError:
                continue
        future.cancel()

    def produce() -> None:
        try:
            with av.open(str(path)) as container:
                if not container.streams.audio:
                    raise RuntimeError("Aucune piste audio dans ce fichier")
                resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
                pending: list[np.ndarray] = []
                pending_size = 0
                frames = container.decode(container.streams.audio[0])
                # A final None flushes the resampler.
                for frame in itertools.chain(_iter_frames(frames, stop), [None]):
                    for out in resampler.resample(frame):
                        samples = out.to_ndarray().reshape(-1)
                        pending.append(samples)
                        pending_size += len(samples)
                    if pending and (pending_size >= sample_rate * CHUNK_S or frame is None):
                        chunk = np.concatenate(pending).astype(np.float32) / 32768.0
                        pending, pending_size = [], 0
                        put(chunk)
                    if stop.is_set():
                        return
            put(None)
        except av.FFmpegError as exc:
            put(RuntimeError(f"Décodage impossible : {exc}"))
        except Exception as exc:
            put(exc)

    async def chunks() -> AsyncIterator[np.ndarray]:
        while (item := await queue.get()) is not None:
            if isinstance(item, Exception):
                raise item
            yield item

    thread = threading.Thread(target=produce, name="decode", daemon=True)
    thread.start()
    try:
        yield chunks()
    finally:
        stop.set()
        await asyncio.to_thread(thread.join)


def _iter_frames(frames, stop: threading.Event):
    for frame in frames:
        if stop.is_set():
            return
        yield frame
