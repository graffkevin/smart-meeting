from smart_meeting.transcription.language import LanguageTracker


def test_fixed_language_is_always_used():
    tracker = LanguageTracker.for_choice("fr", fallback="fr")
    assert not tracker.automatic
    assert tracker.observe("en", 0.99, 10) == "fr"


def test_english_words_in_french_do_not_switch():
    tracker = LanguageTracker.for_choice("auto", fallback="fr")
    assert tracker.observe("fr", 0.95, 4) == "fr"  # sets French
    assert tracker.observe("en", 0.6, 3) == "fr"  # mixed sentence: uncertain
    assert tracker.observe("en", 0.95, 1) == "fr"  # "OK, merge request": too short
    assert tracker.current == "fr"


def test_long_english_passage_is_transcribed_in_english_then_switches():
    tracker = LanguageTracker.for_choice("auto", fallback="fr")
    tracker.observe("fr", 0.95, 4)
    assert tracker.observe("en", 0.95, 5) == "en"  # not translated into French
    assert tracker.current == "fr"  # one utterance does not switch yet
    assert tracker.observe("en", 0.9, 5) == "en"
    assert tracker.current == "en"  # second in a row: switched
    assert tracker.observe("fr", 0.5, 1) == "en"  # uncertain: stays in English now


def test_interrupted_streak_does_not_switch():
    tracker = LanguageTracker.for_choice("auto", fallback="fr")
    tracker.observe("fr", 0.95, 4)
    tracker.observe("en", 0.95, 5)
    tracker.observe("fr", 0.95, 4)
    tracker.observe("en", 0.95, 5)
    assert tracker.current == "fr"


def test_fallback_until_a_clear_detection():
    tracker = LanguageTracker.for_choice("auto", fallback="fr")
    assert tracker.observe("de", 0.4, 1) == "fr"
    assert tracker.current is None
    assert tracker.observe("en", 0.9, 3) == "en"
    assert tracker.current == "en"
