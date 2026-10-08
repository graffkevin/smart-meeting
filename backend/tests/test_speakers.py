import numpy as np

from smart_meeting.speakers import MeetingVoices, fbank


def unit(*values):
    vector = np.zeros(256, np.float32)
    vector[: len(values)] = values
    return vector / np.linalg.norm(vector)


ANNE, BRUNO = unit(1, 0), unit(0, 1)


def label(n):
    return f"Intervenant {n}"


def test_fbank_has_80_bands_every_10_ms():
    feats = fbank(np.random.default_rng(0).standard_normal(16000).astype(np.float32) * 0.1)
    assert feats.shape == (98, 80)
    assert np.allclose(feats.mean(axis=0), 0, atol=1e-3)


def test_voices_are_told_apart_and_short_utterances_never_start_one():
    voices = MeetingVoices(label)
    names = [
        voices.name(voices.assign("remote", vector, duration))
        for vector, duration in [(ANNE, 3), (BRUNO, 3), (unit(0.2, 1), 0.5), (ANNE, 2)]
    ]
    assert names == ["Intervenant 1", "Intervenant 2", "Intervenant 2", "Intervenant 1"]


def test_sources_never_share_a_voice():
    voices = MeetingVoices(label)
    assert voices.name(voices.assign("mic", ANNE, 3)) == "Intervenant 1"
    assert voices.name(voices.assign("remote", ANNE, 3)) == "Intervenant 2"


def test_a_new_voice_needs_a_long_and_clearly_different_sentence():
    voices = MeetingVoices(label)
    names = [
        voices.name(voices.assign("remote", vector, duration))
        for vector, duration in [
            (ANNE, 5),
            (unit(1, 0, 2.1), 5),  # 0.43 like Anne: still Anne (a call codec, a cold)
            (BRUNO, 1.5),  # unlike Anne, but too short to tell
            (BRUNO, 3),  # unlike Anne and long enough: someone else
        ]
    ]
    assert names == [label(1), label(1), label(1), label(2)]


def test_small_voices_join_the_main_one_unless_clearly_someone_else(tmp_path):
    voices = MeetingVoices(label)
    spoken = [voices.assign("remote", ANNE, 3) for _ in range(20)]  # Anne, 60 s
    spoken.append(voices.assign("remote", unit(1, 4), 3))  # 0.24 like Anne, 3 s: a laugh
    spoken.append(voices.assign("remote", unit(0.25, 1), 3))  # 0.24 like Anne, 3 s: an "ok"
    carla = unit(0, 0, 1)
    spoken += [voices.assign("remote", carla, 4) for _ in range(5)]  # 20 s, unlike Anne
    for number, utterance in enumerate(spoken):
        utterance.segment_ids.append(number)
    speakers = voices.regroup()
    assert set(speakers.values()) == {label(1), label(2)}  # Anne and Carla, nobody invented
    assert [speakers[n] for n in (20, 21, 22)] == [label(1), label(1), label(2)]


def test_numbers_skip_names_given_by_the_user():
    voices = MeetingVoices(label)
    first = voices.assign("remote", ANNE, 3)
    first.segment_ids.append(1)
    second = voices.assign("remote", BRUNO, 3)
    second.segment_ids.append(2)
    voices.rename(label(2), label(1))  # the user merged them by hand
    assert voices.regroup() == {1: label(1), 2: label(1)}


def test_a_sentence_is_split_where_the_speaker_changes():
    from smart_meeting.speakers import split_by_speaker

    words = [(i, i + 0.9, f" w{i}") for i in range(8)]
    turns = [(0, 4.5, "A"), (4.6, 9, "B")]
    assert split_by_speaker(words, turns) == [
        (0, 4.9, "w0 w1 w2 w3 w4", "A"),
        (5, 7.9, "w5 w6 w7", "B"),
    ]
    # Two words do not make a turn of their own
    assert [p[3] for p in split_by_speaker(words, [(0, 9, "A"), (2, 3.5, "B")])] == ["A"]
