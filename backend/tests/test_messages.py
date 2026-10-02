from smart_meeting.config import get_settings
from smart_meeting.messages import MESSAGES, tr


def test_every_message_is_translated():
    for key, texts in MESSAGES.items():
        assert set(texts) == {"fr", "en"}, key


def test_messages_follow_the_interface_language():
    settings = get_settings()
    try:
        settings.ui_language = "en"
        assert tr("meeting_not_found") == "Meeting not found"
        assert tr("device_not_found", device="X") == "Device not found: X"
        settings.ui_language = "fr"
        assert tr("meeting_not_found") == "Réunion introuvable"
    finally:
        settings.ui_language = "fr"
