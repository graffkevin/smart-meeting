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


class SegmentAll:
    """Fake VAD: any loud enough piece is one sentence."""

    def push(self, audio):
        return [Utterance(0, audio)] if len(audio) and np.abs(audio).max() > 0.05 else []

    def flush(self):
        return []


class SegmentNothing:
    def push(self, audio):
        return []

    def flush(self):
        return []


def test_a_safety_track_is_in_meeting_time_and_readable_after_a_crash(tmp_path):
    track = safety.SafetyTrack(tmp_path, "mic", 10.0, 16000)
    track.write(np.full(16000, 0.5, np.float32), 10.0)
    track.write(np.full(16000, 0.5, np.float32), 13.0)  # capture restarted: 2 s of silence
    # not closed, like a crash
    [(start, audio)] = safety.load_tracks(tmp_path, "mic")
    assert start == 10.0 and len(audio) == 4 * 16000
    assert audio[16000 : 3 * 16000].max() == 0 and audio[-1] > 0.4


def test_missing_speech_is_only_where_nothing_was_transcribed():
    audio = np.zeros(60 * 16000, np.float32)
    audio[5 * 16000 : 8 * 16000] = 0.5  # transcribed
    audio[30 * 16000 : 33 * 16000] = 0.5  # lost
    found = safety.missing_speech([(100.0, audio)], [(105.0, 108.0)], SegmentAll, 16000)
    # The fake VAD gives the whole uncovered stretch after the sentence (and its margin)
    [(start, lost)] = found
    assert start == 109.0
    assert lost[(130 - 109) * 16000] == 0.5


def test_speech_lost_during_the_meeting_is_recovered_at_the_end(tmp_path):
    async def run():
        svc = ready_service(tmp_path)
        segmenter = {"cls": SegmentNothing}  # live: the sentence is lost
        svc._new_segmenter = lambda: segmenter["cls"]()
        meeting = await svc.start(StartMeetingRequest(title="t"))
        stream = svc.active.streams["mic"]
        for _ in range(30):  # 3 s of speech, in 100 ms blocks
            svc._on_audio(svc.active, stream, np.full(1600, 0.5, np.float32))
        segmenter["cls"] = SegmentAll  # the final check finds it
        await svc.stop(meeting.id)
        await wait_for(lambda: svc.active is None)
        await wait_for(lambda: svc.db.get_meeting(meeting.id).status != MeetingStatus.TRANSCRIBING)
        return svc, meeting.id

    svc, meeting_id = asyncio.run(run())
    assert [s.text for s in svc.db.list_segments(meeting_id)] == ["Bonjour"]
    assert not svc.audio_path(meeting_id).exists()  # tracks deleted: audio not kept


def test_minutes_interrupted_by_a_restart_are_written_again(tmp_path):
    async def run():
        svc = ready_service(tmp_path)
        meeting = svc.db.create_meeting("t", None, None, keep_audio=False)
        svc.db.update_meeting(meeting.id, status=MeetingStatus.ANALYZING)
        unfinished = svc.db.fail_interrupted_meetings()
        analyzed = []

        async def analyze(meeting_id):
            analyzed.append(meeting_id)

        svc.analyze = analyze
        svc._provisioned.set()
        await svc._analyze_unfinished(unfinished)
        return meeting.id, unfinished, analyzed

    meeting_id, unfinished, analyzed = asyncio.run(run())
    assert unfinished == [meeting_id] and analyzed == [meeting_id]
