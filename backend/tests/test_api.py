"""API tests without Whisper: the service is built directly, Ollama points to a closed port."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from smart_meeting.api.routes import router
from smart_meeting.config import Settings
from smart_meeting.db import Database
from smart_meeting.meeting.events import EventHub
from smart_meeting.meeting.service import MeetingService
from smart_meeting.models import MeetingStatus, Segment


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, ollama_url="http://127.0.0.1:9")
    app = FastAPI()
    app.include_router(router)
    service = MeetingService(settings, Database(settings.db_path), EventHub())
    service.provisioner._find_binary = lambda: None  # no Ollama to start in tests
    app.state.service = service
    app.state.stop_when_unused = None
    with TestClient(app) as test_client:
        yield test_client


def add_transcribed_meeting(client) -> int:
    db = client.app.state.service.db
    meeting = db.create_meeting("Point Atlas", None, None, keep_audio=False)
    db.add_segment(
        meeting.id,
        Segment(source="mic", speaker="Moi", start_s=0, end_s=1, text="Je m'occupe de la note."),
    )
    db.update_meeting(meeting.id, status=MeetingStatus.TRANSCRIBED)
    return meeting.id


def test_analyze_reports_unreachable_ollama(client):
    meeting_id = add_transcribed_meeting(client)
    assert client.post(f"/api/meetings/{meeting_id}/analyze").status_code == 202
    for _ in range(50):
        meeting = client.get(f"/api/meetings/{meeting_id}").json()["meeting"]
        if meeting["error"]:
            break
        time.sleep(0.1)
    assert meeting["status"] == "transcribed"
    assert meeting["error"].startswith("Analyse impossible")


def test_history_search_report_and_delete(client):
    meeting_id = add_transcribed_meeting(client)
    assert [m["id"] for m in client.get("/api/meetings", params={"q": "note"}).json()] == [
        meeting_id
    ]
    assert client.get("/api/meetings", params={"q": "absent"}).json() == []
    assert (
        "Moi : Je m'occupe de la note." in client.get(f"/api/meetings/{meeting_id}/report.md").text
    )
    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 204
    assert client.get(f"/api/meetings/{meeting_id}").status_code == 404


def test_cannot_stop_a_meeting_that_is_not_recording(client):
    meeting_id = add_transcribed_meeting(client)
    assert client.post(f"/api/meetings/{meeting_id}/stop").status_code == 409


def test_health_reports_open_pages(client):
    assert client.get("/api/health").json()["ui_open"] is False
    with client.websocket_connect("/api/presence"):
        assert client.get("/api/health").json()["ui_open"] is True
    assert client.get("/api/health").json()["ui_open"] is False


def test_ask_answers_from_the_transcript(client):
    meeting_id = add_transcribed_meeting(client)
    service = client.app.state.service
    seen = {}

    async def fake_ask(title, segments, question, notes=None):
        seen.update(title=title, texts=[s.text for s in segments], question=question)
        return "Vous devez rédiger la note."

    service.ollama.ask = fake_ask
    answer = client.post(
        f"/api/meetings/{meeting_id}/ask", json={"question": " Que dois-je faire ? "}
    ).json()
    assert (answer["question"], answer["answer"]) == (
        "Que dois-je faire ?",
        "Vous devez rédiger la note.",
    )
    # Kept with the meeting, in its report, and offered as a suggestion
    kept = client.get(f"/api/meetings/{meeting_id}").json()["questions"]
    assert [q["question"] for q in kept] == ["Que dois-je faire ?"]
    assert "**Que dois-je faire ?**" in client.get(f"/api/meetings/{meeting_id}/report.md").text
    assert client.get("/api/questions/recent").json() == ["Que dois-je faire ?"]
    assert seen == {
        "title": "Point Atlas",
        "texts": ["Je m'occupe de la note."],
        "question": "Que dois-je faire ?",
    }


def test_ask_needs_something_transcribed(client):
    meeting = client.app.state.service.db.create_meeting("Vide", None, None, keep_audio=False)
    assert (
        client.post(f"/api/meetings/{meeting.id}/ask", json={"question": "Résumé ?"}).status_code
        == 409
    )
    assert client.post(f"/api/meetings/{meeting.id}/ask", json={"question": ""}).status_code == 422


def test_preferences_are_saved_and_applied(client, tmp_path):
    service = client.app.state.service
    assert client.get("/api/preferences").json()["user_name"] == "Moi"
    saved = client.put(
        "/api/preferences",
        json={
            "user_name": "Kevin",
            "glossary": ["Atlas", "Géolocalisation"],
            "language": "fr",
            "mic_device": None,
            "output_device": "casque",
            "keep_audio": False,
        },
    ).json()
    assert saved["output_device"] == "casque"
    assert service.settings.user_name == "Kevin"
    assert service.settings.whisper_glossary == "Atlas, Géolocalisation"
    assert (tmp_path / "preferences.json").exists()


def test_default_title_names_the_date():
    from datetime import datetime

    from smart_meeting.meeting.service import default_title

    assert default_title(datetime(2026, 10, 2, 14, 5)) == "Réunion du 2 octobre 2026 à 14h05"


def test_rename_to_nothing_uses_the_date(client):
    meeting_id = add_transcribed_meeting(client)
    title = client.patch(f"/api/meetings/{meeting_id}", json={"title": "  "}).json()["title"]
    assert title.startswith("Réunion du ")


def test_naming_a_speaker_renames_passages_and_action_owners(client):
    from smart_meeting.models import ActionItem, MeetingAnalysis

    db = client.app.state.service.db
    meeting = db.create_meeting("Point", None, None, keep_audio=False)
    for speaker, text in [("Intervenant 1", "Je fais la note."), ("Intervenant 2", "Merci.")]:
        db.add_segment(
            meeting.id, Segment(source="remote", speaker=speaker, start_s=0, end_s=1, text=text)
        )
    action = ActionItem(task="La note", owner="Intervenant 1", deadline=None, quote="la note")
    empty = {"summary": "", "decisions": [], "questions": [], "risks": [], "technical_topics": []}
    db.save_analysis(meeting.id, MeetingAnalysis(**empty, actions=[action]))

    body = {"old": "Intervenant 1", "new": "Paul"}
    assert client.put(f"/api/meetings/{meeting.id}/speakers", json=body).status_code == 204
    detail = client.get(f"/api/meetings/{meeting.id}").json()
    assert [s["speaker"] for s in detail["segments"]] == ["Paul", "Intervenant 2"]
    assert detail["analysis"]["actions"][0]["owner"] == "Paul"

    # Giving an existing name merges both speakers
    body = {"old": "Intervenant 2", "new": "Paul"}
    client.put(f"/api/meetings/{meeting.id}/speakers", json=body)
    detail = client.get(f"/api/meetings/{meeting.id}").json()
    assert {s["speaker"] for s in detail["segments"]} == {"Paul"}


def test_permission_settings_only_exist_where_the_system_needs_them(client):
    assert client.post("/api/audio/permission-settings").status_code == 409  # not macOS


def test_a_meeting_tells_where_it_is_kept(client):
    meeting_id = add_transcribed_meeting(client)
    storage = client.get(f"/api/meetings/{meeting_id}").json()["storage"]
    assert storage["database"].endswith("smart-meeting.db")
    assert storage["audio"] is None  # no audio kept
