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
    app.state.service = MeetingService(settings, Database(settings.db_path), EventHub())
    app.state.stop_when_unused = None
    with TestClient(app) as test_client:
        yield test_client


def add_transcribed_meeting(client) -> int:
    db = client.app.state.service.db
    meeting = db.create_meeting("Point JUNN", None, None, keep_audio=False)
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
