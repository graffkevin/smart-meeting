"""Backend-independent capture logic, exercised with fakes (no audio hardware needed)."""

import asyncio

import numpy as np
import pytest

from smart_meeting.audio import threaded
from smart_meeting.audio.threaded import ThreadedCapture
from smart_meeting.config import Settings
from smart_meeting.db import Database
from smart_meeting.meeting.events import EventHub
from smart_meeting.meeting.service import ConflictError, MeetingService
from smart_meeting.models import AudioDevices, StartMeetingRequest


class FakeThreaded(ThreadedCapture):
    def _open(self):
        pass

    def _close(self):
        pass


def test_threaded_capture_resamples_to_mono_16k():
    received = []

    async def run():
        capture = FakeThreaded("dev", received.append, 16000)
        await capture.start()
        stereo = np.ones((48000, 2), dtype=np.float32) * 0.5  # 1 s at 48 kHz
        for block in np.split(stereo, 10):
            capture._push(block, 48000)
        await asyncio.sleep(0)
        await capture.stop()

    asyncio.run(run())
    audio = np.concatenate(received)
    assert abs(len(audio) - 16000) <= 32
    assert abs(float(audio[1000:-1000].mean()) - 0.5) < 0.01


def test_threaded_capture_fills_silent_gaps(monkeypatch):
    received = []
    clock = [100.0]
    monkeypatch.setattr(threaded.time, "monotonic", lambda: clock[0])

    async def run():
        capture = FakeThreaded("dev", received.append, 16000)
        await capture.start()
        clock[0] += 2.0  # loopback delivered nothing for 2 s
        capture._push(np.ones((1600, 1), dtype=np.float32), 16000)
        await asyncio.sleep(0)
        await capture.stop()

    asyncio.run(run())
    audio = np.concatenate(received)
    assert abs(len(audio) - 32000) <= 32  # 2 s of filled silence including the block


class FakeCapture:
    def __init__(self, target, fail):
        self.target = target
        self.fail = fail
        self.stopped = False

    async def start(self):
        if self.fail:
            raise RuntimeError("permission refusée")

    async def stop(self):
        self.stopped = True


class FakeBackend:
    name = "fake"

    def __init__(self, failing=()):
        self.failing = set(failing)

    async def list_devices(self):
        return AudioDevices(sources=[], sinks=[])

    async def resolve_in_use(self, fallback_to_defaults=True):
        return ("mic-dev", "out-dev") if fallback_to_defaults else (None, None)

    def create_capture(self, source, target, on_audio, sample_rate):
        return FakeCapture(target, source in self.failing)


def make_service(tmp_path, backend):
    settings = Settings(data_dir=tmp_path)
    return MeetingService(settings, Database(settings.db_path), EventHub(), audio=backend)


def test_meeting_continues_when_one_source_fails(tmp_path):
    async def run():
        svc = make_service(tmp_path, FakeBackend(failing={"remote"}))
        meeting = await svc.start(StartMeetingRequest(title="t"))
        captured = svc.captured_devices(meeting.id)
        await svc.stop(meeting.id)
        svc._whisper_ready.set()
        while svc.active:
            await asyncio.sleep(0.01)
        return captured

    captured = asyncio.run(run())
    assert captured["mic"].device == "mic-dev" and captured["mic"].error is None
    assert captured["remote"].error == "permission refusée"


def test_meeting_fails_when_no_source_works(tmp_path):
    async def run():
        svc = make_service(tmp_path, FakeBackend(failing={"mic", "remote"}))
        with pytest.raises(ConflictError, match="Aucune source audio"):
            await svc.start(StartMeetingRequest(title="t"))
        assert svc.active is None
        return svc.db.list_meetings()[0]

    meeting = asyncio.run(run())
    assert meeting.status == "error"
