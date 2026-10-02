import numpy as np

from smart_meeting.audio.segmenter import WINDOW, UtteranceSegmenter

SR = 16000


def energy_vad(audio: np.ndarray) -> np.ndarray:
    """Fake VAD: a window is speech when its amplitude is high."""
    return (np.abs(audio.reshape(-1, WINDOW)).mean(axis=1) > 0.1).astype(np.float32)


def tone(seconds: float) -> np.ndarray:
    return np.full(int(seconds * SR), 0.5, dtype=np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32)


def feed(segmenter: UtteranceSegmenter, audio: np.ndarray, block: int = 1600):
    out = []
    for i in range(0, len(audio), block):
        out += segmenter.push(audio[i : i + block])
    return out


def test_cuts_at_pauses():
    seg = UtteranceSegmenter(energy_vad, min_silence_ms=500)
    audio = np.concatenate([silence(1), tone(2), silence(1), tone(1.5), silence(1)])
    utterances = feed(seg, audio)
    assert len(utterances) == 2
    first, second = utterances
    # Pre-roll (300 ms) before speech onset at 1 s, post-roll after speech end at 3 s.
    assert 0.6 <= first.start_s(SR) <= 1.0
    assert 3.0 <= first.end_s(SR) <= 3.3
    assert 3.6 <= second.start_s(SR) <= 4.0
    assert seg.flush() == []


def test_short_pause_does_not_split():
    seg = UtteranceSegmenter(energy_vad, min_silence_ms=700)
    audio = np.concatenate([tone(1), silence(0.3), tone(1), silence(1)])
    assert len(feed(seg, audio)) == 1


def test_max_length_forces_contiguous_cut():
    seg = UtteranceSegmenter(energy_vad, max_utterance_s=5)
    utterances = feed(seg, tone(12)) + seg.flush()
    assert len(utterances) >= 3
    assert all(len(u.audio) <= 5 * SR for u in utterances)
    for previous, current in zip(utterances, utterances[1:], strict=False):
        assert previous.start_sample + len(previous.audio) == current.start_sample
    assert sum(len(u.audio) for u in utterances) == len(tone(12)) // WINDOW * WINDOW


def test_flush_emits_ongoing_speech_and_ignores_blips():
    seg = UtteranceSegmenter(energy_vad, min_speech_ms=250)
    feed(seg, np.concatenate([silence(1), tone(0.1), silence(2)]))  # too short: dropped
    assert seg.flush() == []
    feed(seg, tone(2))
    flushed = seg.flush()
    assert len(flushed) == 1 and flushed[0].start_s(SR) > 2.5
