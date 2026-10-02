from smart_meeting.db import Database
from smart_meeting.meeting.report import build_markdown
from smart_meeting.models import ActionItem, MeetingAnalysis, MeetingStatus, Segment


def test_meeting_roundtrip_and_report(tmp_path):
    db = Database(tmp_path / "test.db")
    meeting = db.create_meeting("Point projet JUNN", "mic", None, keep_audio=False)
    assert meeting.status == MeetingStatus.RECORDING
    db.add_segment(
        meeting.id,
        Segment(
            source="remote",
            speaker="Interlocuteur",
            start_s=4,
            end_s=8,
            text="Il faudrait intégrer le simulateur.",
        ),
    )
    db.add_segment(
        meeting.id, Segment(source="mic", speaker="Moi", start_s=1, end_s=3, text="Bonjour.")
    )
    assert [s.text for s in db.list_segments(meeting.id)] == [
        "Bonjour.",
        "Il faudrait intégrer le simulateur.",
    ]

    analysis = MeetingAnalysis(
        summary="Intégration du simulateur.",
        decisions=["Utiliser l'API"],
        actions=[
            ActionItem(
                task="Intégrer | le simulateur",
                owner="Moi",
                deadline=None,
                quote="intégrer",
                verified=True,
            )
        ],
        questions=[],
        risks=[],
        technical_topics=["OGC API Processes"],
    )
    db.save_analysis(meeting.id, analysis)
    db.update_meeting(meeting.id, status=MeetingStatus.DONE)
    assert db.get_analysis(meeting.id) == analysis
    assert db.get_meeting(meeting.id).summary == "Intégration du simulateur."

    markdown = build_markdown(db.get_meeting(meeting.id), db.list_segments(meeting.id), analysis)
    assert markdown.startswith("# Point projet JUNN")
    assert "| Intégrer \\| le simulateur | Moi | Non définie |" in markdown
    assert "Moi : Bonjour." in markdown

    db.delete_meeting(meeting.id)
    assert db.list_meetings() == [] and db.list_segments(meeting.id) == []


def test_interrupted_meetings_are_failed(tmp_path):
    db = Database(tmp_path / "test.db")
    meeting = db.create_meeting("x", None, None, keep_audio=False)
    db.fail_interrupted_meetings()
    assert db.get_meeting(meeting.id).status == MeetingStatus.ERROR


def test_imported_meeting_report_uses_file_positions(tmp_path):
    db = Database(tmp_path / "test.db")
    meeting = db.create_meeting(
        "Webinaire",
        None,
        None,
        keep_audio=False,
        status=MeetingStatus.TRANSCRIBING,
        source_file="webinaire.mp4",
    )
    db.add_segment(
        meeting.id,
        Segment(source="remote", speaker="Intervenant", start_s=3725, end_s=3730, text="Bonjour."),
    )
    markdown = build_markdown(db.get_meeting(meeting.id), db.list_segments(meeting.id), None)
    assert "fichier `webinaire.mp4`" in markdown
    assert "**01:02:05** Intervenant : Bonjour." in markdown


def test_migration_adds_source_file(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE meetings (id INTEGER PRIMARY KEY, title TEXT, status TEXT,"
        " started_at TEXT, ended_at TEXT, mic_device TEXT, remote_device TEXT,"
        " keep_audio INTEGER, transcript TEXT, summary TEXT, analysis_json TEXT,"
        " error TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()
    db = Database(path)
    assert (
        db.create_meeting("x", None, None, keep_audio=False, source_file="a.mp3").source_file
        == "a.mp3"
    )
