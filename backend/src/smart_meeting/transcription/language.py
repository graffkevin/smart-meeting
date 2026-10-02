"""Sticky language choice for the automatic mode.

Whisper detects the language of each utterance, but a few English words in a French sentence
must not switch the transcription to English. Each audio source keeps a current language:

- an utterance confidently detected (long enough, high probability) is transcribed in its
  detected language, so that a long English passage is not "translated" into French;
- an uncertain one (short, mixed) is transcribed in the current language;
- the current language only changes after `switch_after` confident utterances in a row in
  another language.
"""

from dataclasses import dataclass

AUTO = "auto"


@dataclass
class LanguageTracker:
    fixed: str | None = None  # forced language; None: automatic
    fallback: str = "fr"  # before the first detection
    switch_after: int = 2
    min_probability: float = 0.8
    min_duration_s: float = 2.0
    current: str | None = None
    _candidate: str | None = None
    _streak: int = 0

    @classmethod
    def for_choice(cls, choice: str, fallback: str) -> "LanguageTracker":
        return cls(fixed=None if choice == AUTO else choice, fallback=fallback)

    @property
    def automatic(self) -> bool:
        return self.fixed is None

    @property
    def language(self) -> str:
        return self.fixed or self.current or self.fallback

    def observe(self, detected: str, probability: float, duration_s: float) -> str:
        """Record a detection; return the language to transcribe this utterance in."""
        if self.fixed:
            return self.fixed
        confident = probability >= self.min_probability and duration_s >= self.min_duration_s
        if self.current is None:
            # The first clear utterance sets the language of the source.
            if confident:
                self.current = detected
            return detected if confident else self.language
        if not confident:
            return self.current
        if detected == self.current:
            self._candidate, self._streak = None, 0
            return detected
        self._streak = self._streak + 1 if detected == self._candidate else 1
        self._candidate = detected
        if self._streak >= self.switch_after:
            self.current, self._candidate, self._streak = detected, None, 0
        return detected
