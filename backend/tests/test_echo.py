import asyncio

import numpy as np
from test_safety import ready_service, wait_for

from smart_meeting.audio.segmenter import Utterance
from smart_meeting.meeting import echo
from smart_meeting.models import StartMeetingRequest


def test_two_transcriptions_of_the_same_speech_are_an_echo():
    assert echo.is_echo(
        "On garde la mise en production pour jeudi.", "on garde la mise en prod pour jeudi"
    )
    assert not echo.is_echo("On garde la mise en production pour jeudi.", "Je préfère lundi.")
    assert not echo.is_echo("Oui.", "Oui.")  # both sides do say "oui"


def test_echo_needs_the_same_moment():
    assert echo.at_same_time((10.0, 14.0), (11.2, 15.0))
    assert not echo.at_same_time((10.0, 14.0), (40.0, 44.0))


def transcribe(svc, source, start_s, text):
    svc.transcriber.text = text
    recording = svc.active
    return svc._transcribe_utterance(
        recording,
        recording.streams[source],
        start_s,
        Utterance(0, np.full(32000, 0.1, np.float32)),
    )


def run_meeting(tmp_path, steps):
    async def run():
        svc = ready_service(tmp_path)
        original = svc.transcriber.transcribe
        svc.transcriber.transcribe = lambda audio, language, previous="": [
            piece.__class__(piece.start_s, piece.end_s, svc.transcriber.text)
            for piece in original(audio, language, previous)
        ]
        meeting = await svc.start(StartMeetingRequest(title="t"))
        for source, start_s, text in steps:
            await transcribe(svc, source, start_s, text)
        await svc.stop(meeting.id)
        await wait_for(lambda: svc.active is None)
        return [(s.source, s.text) for s in svc.db.list_segments(meeting.id)]

    return asyncio.run(run())


def test_the_others_heard_by_my_microphone_are_kept_once(tmp_path):
    said = "On garde la mise en production pour jeudi."
    # Whichever copy is transcribed first, the others' one stays
    assert run_meeting(tmp_path / "a", [("remote", 10.0, said), ("mic", 10.3, said)]) == [
        ("remote", said)
    ]
    assert run_meeting(tmp_path / "b", [("mic", 10.3, said), ("remote", 10.0, said)]) == [
        ("remote", said)
    ]


def test_both_saying_yes_at_once_is_kept(tmp_path):
    assert len(run_meeting(tmp_path, [("remote", 10.0, "Oui."), ("mic", 10.2, "Oui.")])) == 2


def test_the_final_check_does_not_bring_an_echo_back(tmp_path):
    from test_safety import SegmentAll

    from smart_meeting.meeting import safety
    from smart_meeting.models import Segment

    said = "On garde la mise en production pour jeudi."

    async def run():
        svc = ready_service(tmp_path)
        svc._new_segmenter = SegmentAll
        svc.transcriber.text = said
        original = svc.transcriber.transcribe
        svc.transcriber.transcribe = lambda audio, language, previous="": [
            piece.__class__(piece.start_s, piece.end_s, said)
            for piece in original(audio, language, previous)
        ]
        meeting = await svc.start(StartMeetingRequest(title="t"))
        recording = svc.active
        # The others said it at 10 s; my microphone heard it (its copy was left out live)
        svc.db.add_segment(
            meeting.id, Segment(source="remote", speaker="I1", start_s=10, end_s=13, text=said)
        )
        track = safety.SafetyTrack(svc.audio_path(meeting.id), "mic", 0.0, 16000)
        audio = np.zeros(20 * 16000, np.float32)
        audio[10 * 16000 : 13 * 16000] = 0.5
        track.write(audio, 0.0)
        track.close()
        await svc._transcribe_missing(recording)
        sources = [s.source for s in svc.db.list_segments(meeting.id)]
        await svc.stop(meeting.id)
        await wait_for(lambda: svc.active is None)
        return sources

    assert asyncio.run(run()) == ["remote"]
