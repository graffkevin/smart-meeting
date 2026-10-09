"""The graphics card between Whisper and the AI: left to the AI outside meetings, taken back when a
meeting starts."""

import asyncio

from smart_meeting.config import Settings
from smart_meeting.db import Database
from smart_meeting.meeting.events import EventHub
from smart_meeting.meeting.service import MeetingService


class GpuTranscriber:
    def __init__(self, on_gpu=True):
        self.on_gpu = on_gpu
        self.loaded = True
        self.loads = 0
        self.model_name, self.device = "large-v3-turbo", "faster-whisper cuda/int8_float16"

    def load(self):
        self.loaded = True
        self.loads += 1

    def unload(self):
        self.loaded = False


class Ollama:
    """Models in memory, as /api/ps gives them."""

    def __init__(self, models):
        self.models = models
        self.unloaded = []

    async def loaded_models(self):
        return list(self.models)

    async def unload(self, name):
        self.unloaded.append(name)
        self.models = [m for m in self.models if m["name"] != name]


def service(tmp_path, transcriber, models) -> MeetingService:
    settings = Settings(data_dir=tmp_path, ollama_url="http://127.0.0.1:9")
    svc = MeetingService(settings, Database(settings.db_path), EventHub())
    svc.transcriber = transcriber
    ollama = Ollama(models)
    svc.ollama.loaded_models, svc.ollama.unload = ollama.loaded_models, ollama.unload
    svc.fake_ollama = ollama
    svc._whisper_ready.set()
    return svc


SPLIT = {"name": "qwen2.5:3b", "size": 2_600, "size_vram": 1_300}  # half on the card


def test_whisper_leaves_the_card_to_the_ai_then_comes_back(tmp_path):
    async def run():
        transcriber = GpuTranscriber()
        svc = service(tmp_path, transcriber, [SPLIT])
        await svc._gpu_for_ai()
        assert not transcriber.loaded and not svc._whisper_ready.is_set()
        # Loaded beside Whisper: unloaded, to come back on the whole card
        assert svc.fake_ollama.unloaded == ["qwen2.5:3b"]

        svc.fake_ollama.models = [{"name": "qwen2.5:3b", "size": 2_600, "size_vram": 2_600}]
        svc._need_whisper()  # a meeting starts
        await asyncio.wait_for(svc._whisper_ready.wait(), 5)
        assert transcriber.loaded and transcriber.loads == 1
        assert svc.fake_ollama.models == []  # the AI left the card first
        assert svc.whisper_state != "error"

    asyncio.run(run())


def test_whisper_stays_while_something_is_transcribed(tmp_path):
    async def run():
        transcriber = GpuTranscriber()
        svc = service(tmp_path, transcriber, [SPLIT])
        svc._whisper_users = 1  # the end of a meeting, a recovery
        await svc._gpu_for_ai()
        assert transcriber.loaded and svc._whisper_ready.is_set()
        assert svc.fake_ollama.unloaded == []

    asyncio.run(run())


def test_whisper_off_the_card_stays(tmp_path):
    async def run():
        transcriber = GpuTranscriber(on_gpu=False)  # processor, Apple chip: nothing to share
        svc = service(tmp_path, transcriber, [SPLIT])
        await svc._gpu_for_ai()
        assert transcriber.loaded
        svc._need_whisper()
        assert svc._whisper_reload is None

    asyncio.run(run())


def test_whisper_loads_once_the_ai_left_the_card(tmp_path):
    async def run():
        transcriber = GpuTranscriber()
        svc = service(tmp_path, transcriber, [SPLIT])

        def load():  # out of memory while the AI is on the card
            if svc.fake_ollama.models:
                raise RuntimeError("CUDA failed with error out of memory")
            transcriber.loads += 1

        transcriber.load = load
        svc._whisper_ready.clear()
        await svc._load_whisper()
        assert svc.whisper_state == "ready" and transcriber.loads == 1

    asyncio.run(run())
