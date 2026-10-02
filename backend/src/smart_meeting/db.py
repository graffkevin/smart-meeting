"""SQLite persistence. Plain sqlite3: the schema is small and the access patterns simple."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from smart_meeting.models import (
    Meeting,
    MeetingAnalysis,
    MeetingStatus,
    Segment,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    mic_device    TEXT,
    remote_device TEXT,
    keep_audio    INTEGER NOT NULL DEFAULT 0,
    transcript    TEXT,
    summary       TEXT,
    analysis_json TEXT,
    error         TEXT,
    source_file   TEXT,                -- imported file name, NULL for live meetings
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,          -- 'mic' | 'remote'
    speaker    TEXT,
    start_s    REAL NOT NULL,          -- seconds since meeting start
    end_s      REAL NOT NULL,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_meeting ON segments(meeting_id, start_s);
CREATE TABLE IF NOT EXISTS decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    text       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    task       TEXT NOT NULL,
    owner      TEXT,
    deadline   TEXT,
    quote      TEXT,
    verified   INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _migrate(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # Meetings

    def create_meeting(
        self,
        title: str,
        mic_device: str | None,
        remote_device: str | None,
        keep_audio: bool,
        status: MeetingStatus = MeetingStatus.RECORDING,
        source_file: str | None = None,
    ) -> Meeting:
        now = now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO meetings (title, status, started_at, mic_device, remote_device,"
                " keep_audio, source_file, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, status, now, mic_device, remote_device, keep_audio, source_file, now),
            )
            meeting_id = cursor.lastrowid
        meeting = self.get_meeting(meeting_id)
        assert meeting is not None
        return meeting

    def get_meeting(self, meeting_id: int) -> Meeting | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return _meeting_from_row(row) if row else None

    def list_meetings(self) -> list[Meeting]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM meetings ORDER BY started_at DESC").fetchall()
        return [_meeting_from_row(row) for row in rows]

    def update_meeting(self, meeting_id: int, **fields: object) -> None:
        allowed = {"title", "status", "ended_at", "transcript", "summary", "error", "keep_audio"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Cannot update {unknown}")
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE meetings SET {assignments} WHERE id = ?", (*fields.values(), meeting_id)
            )

    def delete_meeting(self, meeting_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))

    def fail_interrupted_meetings(self) -> None:
        """Meetings left in a running state by a crash or restart can never complete."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE meetings SET status = ?, error = ?, ended_at = COALESCE(ended_at, ?)"
                " WHERE status IN (?, ?)",
                (
                    MeetingStatus.ERROR,
                    "Interrompue (redémarrage du serveur)",
                    now_iso(),
                    MeetingStatus.RECORDING,
                    MeetingStatus.TRANSCRIBING,
                ),
            )
            conn.execute(
                "UPDATE meetings SET status = ? WHERE status = ?",
                (MeetingStatus.TRANSCRIBED, MeetingStatus.ANALYZING),
            )

    # Segments

    def add_segment(self, meeting_id: int, segment: Segment) -> Segment:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO segments (meeting_id, source, speaker, start_s, end_s, text)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    meeting_id,
                    segment.source,
                    segment.speaker,
                    segment.start_s,
                    segment.end_s,
                    segment.text,
                ),
            )
        return segment.model_copy(update={"id": cursor.lastrowid})

    def list_segments(self, meeting_id: int) -> list[Segment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE meeting_id = ? ORDER BY start_s, id", (meeting_id,)
            ).fetchall()
        return [
            Segment(
                id=row["id"],
                source=row["source"],
                speaker=row["speaker"],
                start_s=row["start_s"],
                end_s=row["end_s"],
                text=row["text"],
            )
            for row in rows
        ]

    # Analysis

    def save_analysis(self, meeting_id: int, analysis: MeetingAnalysis) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM decisions WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM actions WHERE meeting_id = ?", (meeting_id,))
            conn.executemany(
                "INSERT INTO decisions (meeting_id, text) VALUES (?, ?)",
                [(meeting_id, decision) for decision in analysis.decisions],
            )
            conn.executemany(
                "INSERT INTO actions (meeting_id, task, owner, deadline, quote, verified)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (meeting_id, a.task, a.owner, a.deadline, a.quote, a.verified)
                    for a in analysis.actions
                ],
            )
            conn.execute(
                "UPDATE meetings SET summary = ?, analysis_json = ? WHERE id = ?",
                (analysis.summary, analysis.model_dump_json(), meeting_id),
            )

    def get_analysis(self, meeting_id: int) -> MeetingAnalysis | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT analysis_json FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
        if not row or not row["analysis_json"]:
            return None
        return MeetingAnalysis.model_validate(json.loads(row["analysis_json"]))


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by earlier versions."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(meetings)")}
    if "source_file" not in columns:
        conn.execute("ALTER TABLE meetings ADD COLUMN source_file TEXT")


def _meeting_from_row(row: sqlite3.Row) -> Meeting:
    return Meeting(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        mic_device=row["mic_device"],
        remote_device=row["remote_device"],
        keep_audio=bool(row["keep_audio"]),
        summary=row["summary"],
        error=row["error"],
        source_file=row["source_file"],
        created_at=row["created_at"],
    )
