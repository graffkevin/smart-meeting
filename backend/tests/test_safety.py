"""Nothing said is lost: sentences waiting for Whisper are on disk, a stuck transcription
restarts the server, which resumes the meeting; a crash leaves sentences transcribed later."""

import asyncio
import threading

import numpy as np
from test_audio_backends import FakeBackend, make_service

from smart_meeting.audio.segmenter import Utterance
from smart_meeting.meeting import safety
from smart_meeting.meeting import service as service_module
from smart_meeting.models import MeetingStatus, StartMeetingRequest
from smart_meeting.transcription.whisper import TranscribedPiece


class FakeWhisper:
    def __init__(self):
        self.release = threading.Event()
        self.release.set()

    def transcribe(self, audio, language, previous_text=""):
        self.release.wait(10)
        return [TranscribedPiece(0.0, len(audio) / 16000, "Bonjour")]

    def transcribe_partial(self, audio, language, previous_text=""):
        return ""


def ready_service(tmp_path):
    svc = make_service(tmp_path, FakeBackend())
    svc.transcriber = FakeWhisper()
    svc.voices_error = "off"  # no voice prints model in tests
    svc._whisper_ready.set()
    svc._voices_loaded.set()
    return svc


def one_second():
    return Utterance(16000, np.full(16000, 0.1, np.float32))  # starts 1 s after the source


async def wait_for(condition, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


def test_waiting_sentences_are_on_disk_until_transcribed(tmp_path):
    async def run():
        svc = ready_service(tmp_path)
        meeting = await svc.start(StartMeetingRequest(title="t"))
        recording = svc.active
        stream = recording.streams["remote"]
        stream.offset_s = 2.0
        svc.transcriber.release.clear()
        svc._enqueue(recording, stream, one_second())
        folder = svc.pending.folder(meeting.id)
        assert len(list(folder.glob("*.wav"))) == 1
        svc.transcriber.release.set()
        await wait_for(lambda: svc.db.list_segments(meeting.id))
        await wait_for(lambda: not list(folder.glob("*.wav")))
        segment = svc.db.list_segments(meeting.id)[0]
        await svc.stop(meeting.id)
        await wait_for(lambda: svc.active is None)
        return segment, folder

    segment, folder = asyncio.run(run())
    assert segment.start_s == 3.0  # offset of the source + start of the sentence
    assert not folder.exists()


def test_a_stuck_transcription_restarts_and_resumes_the_meeting(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module, "PROGRESS_CHECK_S", 0.05)
    restarts = []
    monkeypatch.setattr(safety, "restart_process", lambda: restarts.append(1))

    async def stuck():
        svc = ready_service(tmp_path)
        svc.settings.stall_restart_s = 0.2
        meeting = await svc.start(StartMeetingRequest(title="t", room=True, keep_audio=True))
        svc.transcriber.release.clear()  # Whisper never answers
        svc._enqueue(svc.active, svc.active.streams["mic"], one_second())
        await wait_for(lambda: restarts)
        svc.transcriber.release.set()
        return meeting.id

    meeting_id = asyncio.run(stuck())
    resume = safety.take_resume(tmp_path)
    assert resume["meeting_id"] == meeting_id and resume["request"]["room"] is True

    async def restarted():
        svc = ready_service(tmp_path)
        svc.db.fail_interrupted_meetings(resumed=meeting_id)
        await svc._recover(resume)
        assert svc.active.meeting_id == meeting_id  # recording goes on in the same meeting
        await wait_for(lambda: svc.db.list_segments(meeting_id))
        assert svc.db.get_meeting(meeting_id).status == MeetingStatus.RECORDING
        await svc.stop(meeting_id)
        await wait_for(lambda: svc.active is None)
        return svc

    svc = asyncio.run(restarted())
    assert [s.text for s in svc.db.list_segments(meeting_id)] == ["Bonjour"]
    assert (svc.audio_path(meeting_id) / "mic-2.wav").exists()  # audio before kept apart


def test_sentences_left_by_a_crash_are_transcribed_at_the_next_start(tmp_path):
    async def run():
        svc = ready_service(tmp_path)
        meeting = svc.db.create_meeting("t", None, None, keep_audio=False)
        svc.pending.save(meeting.id, "mic", 12.5, np.full(16000, 0.1, np.float32))
        svc.db.fail_interrupted_meetings()
        await svc._recover(None)
        return svc, meeting.id

    svc, meeting_id = asyncio.run(run())
    segments = svc.db.list_segments(meeting_id)
    assert [(s.speaker, s.start_s) for s in segments] == [("Moi", 12.5)]
    assert svc.db.get_meeting(meeting_id).status != MeetingStatus.ERROR  # complete again
    assert not svc.pending.folder(meeting_id).exists()
