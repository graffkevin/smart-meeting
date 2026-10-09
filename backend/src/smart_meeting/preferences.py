"""User preferences set from the interface, kept in the data directory (preferences.json).

They override the matching settings at runtime (no restart, no config file to edit): the name of
the user (who "I" is for the AI), the vocabulary that helps the transcription, and the defaults of
a new meeting (language, devices, keeping the audio).
"""

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from smart_meeting.config import Settings
from smart_meeting.models import Preferences

logger = logging.getLogger(__name__)


class PreferencesStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path: Path = settings.data_dir / "preferences.json"
        self.current = self._load()
        self._apply()

    def _defaults(self) -> Preferences:
        glossary = [w.strip() for w in self.settings.whisper_glossary.split(",") if w.strip()]
        return Preferences(
            user_name=self.settings.user_name,
            glossary=glossary,
            language=self.settings.whisper_language,
        )

    def _load(self) -> Preferences:
        if not self.path.exists():
            return self._defaults()
        try:
            return Preferences.model_validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError):
            logger.warning("Unreadable %s: defaults used", self.path, exc_info=True)
            return self._defaults()

    def _apply(self) -> None:
        self.settings.user_name = self.current.user_name.strip() or "Moi"
        self.settings.whisper_glossary = ", ".join(self.current.glossary)
        self.settings.ui_language = self.current.ui_language
        self.settings.ai_mode = self.current.ai_mode

    def save(self, preferences: Preferences) -> Preferences:
        self.current = preferences
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(preferences.model_dump_json(indent=2), encoding="utf-8")
        self._apply()
        return preferences
