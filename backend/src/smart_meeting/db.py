"""SQLite persistence. Plain sqlite3: the schema is small and the access patterns simple."""

import json
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from smart_meeting.messages import tr
from smart_meeting.models import (
    AskAnswer,
    Meeting,
    MeetingAnalysis,
    MeetingListItem,
    MeetingStatus,
    Segment,
    TagCount,
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
    language      TEXT NOT NULL DEFAULT 'auto',
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
CREATE TABLE IF NOT EXISTS tags (
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    PRIMARY KEY (meeting_id, name)
);
CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    asked_at   TEXT NOT NULL
);
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
-- Notes of the local AI on the old parts of a long meeting, reused by the next questions
CREATE TABLE IF NOT EXISTS notes (
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    digest     TEXT NOT NULL,          -- of the part's transcript and of the notes prompt
    text       TEXT NOT NULL,
    PRIMARY KEY (meeting_id, digest)
);
"""


def fold(text: str | None) -> str:
    """Lowercase and strip accents, for search."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


TAG_SEPARATOR = "\x1f"
TAGS_COLUMN = (
    "(SELECT group_concat(t.name, char(31)) FROM tags t WHERE t.meeting_id = m.id) AS tags"
)
TAG_MAX_LENGTH = 40


def clean_tags(tags: list[str]) -> list[str]:
    """Trimmed, single-spaced, not empty, without case-insensitive duplicates (first kept)."""
    cleaned: dict[str, str] = {}
    for tag in tags:
        name = " ".join(tag.split())[:TAG_MAX_LENGTH]
        if name and fold(name) not in cleaned:
            cleaned[fold(name)] = name
    return list(cleaned.values())


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
        conn.create_function("fold", 1, fold, deterministic=True)
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
        language: str = "auto",
    ) -> Meeting:
        now = now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO meetings (title, status, started_at, mic_device, remote_device,"
                " keep_audio, source_file, language, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    status,
                    now,
                    mic_device,
                    remote_device,
                    keep_audio,
                    source_file,
                    language,
                    now,
                ),
            )
            meeting_id = cursor.lastrowid
        meeting = self.get_meeting(meeting_id)
        assert meeting is not None
        return meeting

    def get_meeting(self, meeting_id: int) -> Meeting | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT m.*, {TAGS_COLUMN} FROM meetings m WHERE m.id = ?", (meeting_id,)
            ).fetchone()
        return _meeting_from_row(row) if row else None

    def list_meetings(self, query: str = "") -> list[MeetingListItem]:
        """Meetings, newest first, optionally filtered by words found in the title, summary
        or transcript (case and accent insensitive, every word must match)."""
        sql = (
            f"SELECT m.*, {TAGS_COLUMN}, (SELECT COUNT(*) FROM actions a WHERE a.meeting_id = m.id)"
            " AS action_count FROM meetings m"
        )
        params: list[str] = []
        conditions = []
        match = "LIKE ? ESCAPE '\\'"
        for word in fold(query).split():
            conditions.append(
                f"(fold(m.title) {match} OR fold(m.summary) {match}"
                " OR EXISTS (SELECT 1 FROM segments s WHERE s.meeting_id = m.id"
                f" AND fold(s.text) {match})"
                " OR EXISTS (SELECT 1 FROM tags t WHERE t.meeting_id = m.id"
                f" AND fold(t.name) {match}))"
            )
            escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params += [f"%{escaped}%"] * 4
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY m.started_at DESC, m.id DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            MeetingListItem(**_meeting_from_row(row).model_dump(), action_count=row["action_count"])
            for row in rows
        ]

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

    # Questions to the local AI

    def add_question(self, meeting_id: int, question: str, answer: str) -> AskAnswer:
        asked_at = now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO questions (meeting_id, question, answer, asked_at)"
                " VALUES (?, ?, ?, ?)",
                (meeting_id, question, answer, asked_at),
            )
        return AskAnswer(id=cursor.lastrowid, question=question, answer=answer, asked_at=asked_at)

    def list_questions(self, meeting_id: int) -> list[AskAnswer]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE meeting_id = ? ORDER BY id", (meeting_id,)
            ).fetchall()
        return [
            AskAnswer(
                id=row["id"],
                question=row["question"],
                answer=row["answer"],
                asked_at=row["asked_at"],
            )
            for row in rows
        ]

    def recent_questions(self, limit: int) -> list[str]:
        """Questions asked lately, in any meeting, most recent first, without duplicates."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT question FROM questions GROUP BY question ORDER BY MAX(id) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row["question"] for row in rows]

    # Tags

    def set_tags(self, meeting_id: int, tags: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tags WHERE meeting_id = ?", (meeting_id,))
            conn.executemany(
                "INSERT INTO tags (meeting_id, name) VALUES (?, ?)",
                [(meeting_id, tag) for tag in clean_tags(tags)],
            )

    def list_tags(self) -> list[TagCount]:
        """Every tag in use, most used first (suggestions of the tag fields)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, COUNT(*) AS count FROM tags GROUP BY name ORDER BY count DESC, name"
            ).fetchall()
        return [TagCount(name=row["name"], count=row["count"]) for row in rows]

    def delete_meeting(self, meeting_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))

    def fail_interrupted_meetings(self, resumed: int | None = None) -> list[int]:
        """Meetings left in a running state by a crash or restart can never complete (except
        `resumed`, the one a restart for a frozen transcription goes on recording). Returns the
        meetings whose analysis was interrupted, to analyze again."""
        with self._connect() as conn:
            analyzing = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM meetings WHERE status = ?", (MeetingStatus.ANALYZING,)
                )
            ]
            conn.execute(
                "UPDATE meetings SET status = ?, error = ?, ended_at = COALESCE(ended_at, ?)"
                " WHERE status IN (?, ?) AND id IS NOT ?",
                (
                    MeetingStatus.ERROR,
                    tr("interrupted"),
                    now_iso(),
                    MeetingStatus.RECORDING,
                    MeetingStatus.TRANSCRIBING,
                    resumed,
                ),
            )
            conn.execute(
                "UPDATE meetings SET status = ? WHERE status = ?",
                (MeetingStatus.TRANSCRIBED, MeetingStatus.ANALYZING),
            )
        return analyzing

    # Notes on the old parts of long meetings

    def get_note(self, meeting_id: int, digest: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT text FROM notes WHERE meeting_id = ? AND digest = ?", (meeting_id, digest)
            ).fetchone()
        return row["text"] if row else None

    def save_note(self, meeting_id: int, digest: str, text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO notes (meeting_id, digest, text) VALUES (?, ?, ?)",
                (meeting_id, digest, text),
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

    def split_segment(self, segment_id: int, parts: list[Segment]) -> None:
        """Replace a segment by several (a sentence said by two speakers)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT meeting_id FROM segments WHERE id = ?", (segment_id,)
            ).fetchone()
            if not row:
                return
            conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
            conn.executemany(
                "INSERT INTO segments (meeting_id, source, speaker, start_s, end_s, text)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (row["meeting_id"], p.source, p.speaker, p.start_s, p.end_s, p.text)
                    for p in parts
                ],
            )

    def delete_segment(self, segment_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))

    def set_speakers(self, speakers: dict[int, str]) -> None:
        """Speaker of each segment (by id), once the voices are regrouped."""
        with self._connect() as conn:
            conn.executemany(
                "UPDATE segments SET speaker = ? WHERE id = ?",
                [(name, segment_id) for segment_id, name in speakers.items()],
            )

    def rename_speaker(self, meeting_id: int, old: str, new: str) -> None:
        """Everywhere in the meeting: its passages, the owners of its actions."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE segments SET speaker = ? WHERE meeting_id = ? AND speaker = ?",
                (new, meeting_id, old),
            )
            conn.execute(
                "UPDATE actions SET owner = ? WHERE meeting_id = ? AND owner = ?",
                (new, meeting_id, old),
            )
        analysis = self.get_analysis(meeting_id)
        if analysis:
            actions = [
                a.model_copy(update={"owner": new}) if a.owner == old else a
                for a in analysis.actions
            ]
            self.save_analysis(meeting_id, analysis.model_copy(update={"actions": actions}))

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
    if "language" not in columns:
        conn.execute("ALTER TABLE meetings ADD COLUMN language TEXT NOT NULL DEFAULT 'auto'")


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
        language=row["language"],
        tags=sorted(row["tags"].split(TAG_SEPARATOR), key=fold)
        if "tags" in row.keys() and row["tags"]
        else [],
        created_at=row["created_at"],
    )
