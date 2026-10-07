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


def test_regrouping_merges_a_split_voice_and_numbers_again():
    voices = MeetingVoices(label)
    spoken = []
    # Same person, 0.43 apart (under the live threshold, over the final one), then someone else
    for i, vector in enumerate([unit(1, 0), unit(1, 2.1), unit(0, 0, 1)]):
        spoken.append(voices.assign("remote", vector, 3))
        spoken[-1].segment_ids.append(i)
    assert [voices.name(s) for s in spoken] == [label(1), label(2), label(3)]
    voices.names[3] = "Paul"
    assert voices.regroup() == {0: label(1), 1: label(1), 2: "Paul"}


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
