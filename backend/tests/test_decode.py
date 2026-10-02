import asyncio
import shutil
import subprocess

import numpy as np
import pytest

from smart_meeting.audio.decode import decode_audio, probe_duration

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def test_decodes_video_audio_track(tmp_path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.5",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=64x64:d=2.5",
            "-shortest",
            str(video),
        ],
        check=True,
    )

    async def run():
        chunks = []
        async with decode_audio(video, 16000) as stream:
            async for chunk in stream:
                chunks.append(chunk)
        return np.concatenate(chunks), await probe_duration(video)

    audio, duration = asyncio.run(run())
    assert abs(len(audio) / 16000 - 2.5) < 0.1
    assert audio.dtype == np.float32 and np.abs(audio).max() > 0.1
    assert abs(duration - 2.5) < 0.1


def test_rejects_non_media(tmp_path):
    bogus = tmp_path / "notes.txt"
    bogus.write_text("pas une vidéo")

    async def run():
        async with decode_audio(bogus, 16000) as stream:
            async for _ in stream:
                pass

    with pytest.raises(RuntimeError, match="Décodage impossible"):
        asyncio.run(run())
