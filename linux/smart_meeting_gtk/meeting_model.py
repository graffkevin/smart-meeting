"""A meeting on screen: its stored state (reloaded from the server) and its live state (audio
levels, capture devices, import progress, sentences being spoken) from its WebSocket."""

import json
import time
from collections.abc import Callable
from datetime import datetime

import gi

gi.require_version("Soup", "3.0")
from gi.repository import GLib, Soup  # noqa: E402

from smart_meeting_gtk.api import background  # noqa: E402

LIVE_STATUSES = ("recording", "transcribing", "analyzing")
# A final sentence replaces a provisional text that started at most this much later (seconds)
PARTIAL_TOLERANCE_S = 0.5
RECONNECT_S = 2


class MeetingModel:
    def __init__(self, meeting_id: int, app) -> None:
        self.id = meeting_id
        self.app = app
        self.detail: dict | None = None
        self.load_error: str | None = None
        self.report: str | None = None
        self.loaded_at = time.monotonic()
        # Live state, not stored
        self.levels: dict | None = None
        self.queue = 0
        self.devices: dict | None = None
        self.progress: tuple[float, float | None] | None = None
        self.partials: dict[str, dict] = {}
        self.stopping = False
        self.pending_question: tuple[str, float] | None = None
        self.ask_error: str | None = None
        self.action_error: str | None = None
        self._listeners: list[Callable[[str], None]] = []
        self._session = Soup.Session()
        self._socket: Soup.WebsocketConnection | None = None
        self._connecting = False
        self._loading = False
        self._closed = False

    # Subscriptions: callback(what) with what = "detail" | "live" | "partials" | "ask"

    def on(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def off(self, callback: Callable[[str], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _emit(self, what: str) -> None:
        for callback in list(self._listeners):
            callback(what)

    @property
    def meeting(self) -> dict | None:
        return self.detail["meeting"] if self.detail else None

    @property
    def segments(self) -> list[dict]:
        return self.detail["segments"] if self.detail else []

    @property
    def status(self) -> str | None:
        return self.meeting["status"] if self.meeting else None

    # Loading and live events

    def reload(self) -> None:
        if self._loading:
            return
        self._loading = True
        previous = self.status

        def loaded(result) -> None:
            self._loading = False
            detail, report = result
            self.detail, self.report, self.load_error = detail, report, None
            self.loaded_at = time.monotonic()
            if self.status in LIVE_STATUSES:
                self._connect()
            else:
                self._disconnect()
                self.partials = {}
            if previous == "analyzing" and self.status == "done":
                self.app.report_ready = self.meeting
                self.app.emit("report-ready")
            self._emit("detail")

        def failed(error: Exception) -> None:
            self._loading = False
            self.load_error = str(error)
            self._emit("detail")

        def load():
            detail = self.app.api.meeting(self.id)
            live = detail["meeting"]["status"] in LIVE_STATUSES
            return detail, None if live else self.app.api.report(self.id)

        background(load, loaded, failed)

    def _connect(self) -> None:
        if self._socket is not None or self._connecting or self._closed:
            return
        self._connecting = True
        message = Soup.Message.new("GET", self.app.api.events_url(self.id))
        self._session.websocket_connect_async(
            message, None, None, GLib.PRIORITY_DEFAULT, None, self._connected
        )

    def _connected(self, session: Soup.Session, result) -> None:
        self._connecting = False
        try:
            socket = session.websocket_connect_finish(result)
        except GLib.Error:
            self._retry()
            return
        if self._closed:
            socket.close(Soup.WebsocketCloseCode.GOING_AWAY, None)
            return
        self._socket = socket
        socket.connect("message", self._message)
        socket.connect("closed", lambda _socket: self._lost(socket))
        # Connected: reload once, for the sentences transcribed before the connection
        self.reload()

    def _lost(self, socket) -> None:
        if self._socket is socket:
            self._socket = None
            self._retry()

    def _retry(self) -> None:
        # Server restarting: connect again while the meeting is live
        if not self._closed:
            GLib.timeout_add_seconds(RECONNECT_S, lambda: self.reload() and False)

    def _message(self, _socket, _type, data: GLib.Bytes) -> None:
        try:
            event = json.loads(data.get_data().decode())
        except (ValueError, UnicodeDecodeError):
            return
        kind = event.get("type")
        if kind == "segment" and self.detail is not None:
            segment = event["segment"]
            if not any(s.get("id") == segment.get("id") for s in self.segments):
                self.segments.append(segment)
                self.segments.sort(key=lambda s: s["start_s"])
            partial = self.partials.get(segment["source"])
            if partial and segment["start_s"] >= partial["start_s"] - PARTIAL_TOLERANCE_S:
                del self.partials[segment["source"]]
            self._emit("segments")
        elif kind == "partial":
            self.partials[event["source"]] = event
            self._emit("partials")
        elif kind == "levels":
            self.levels, self.queue = event.get("levels"), event.get("queue", 0)
            self._emit("live")
        elif kind == "devices":
            self.devices = event.get("devices")
            self._emit("live")
        elif kind == "progress":
            self.progress = (event.get("done_s") or 0.0, event.get("total_s"))
            self._emit("live")
        elif kind == "status":
            self.reload()
            self.app.reload_history()
        elif kind == "speakers":
            self.reload()

    def _disconnect(self) -> None:
        if self._socket is not None:
            socket, self._socket = self._socket, None
            socket.close(Soup.WebsocketCloseCode.GOING_AWAY, None)

    def close(self) -> None:
        self._closed = True
        self._disconnect()

    def reopen(self) -> None:
        self._closed = False

    # Actions

    def stop(self) -> None:
        self.stopping = True
        self._emit("live")

        def finished(_result=None) -> None:
            self.stopping = False
            self.reload()
            self.app.reload_history()

        def failed(error: Exception) -> None:
            self.action_error = str(error)
            finished()

        background(lambda: self.app.api.stop_meeting(self.id), finished, failed)

    def analyze(self) -> None:
        def failed(error: Exception) -> None:
            self.action_error = str(error)
            self.reload()

        background(lambda: self.app.api.analyze(self.id), lambda _r: self.reload(), failed)

    def ask(self, question: str) -> None:
        question = question.strip()
        if not question or self.pending_question is not None:
            return
        self.pending_question, self.ask_error = (question, time.monotonic()), None
        self._emit("ask")

        def answered(_result) -> None:
            self.pending_question = None
            self.reload()
            self.app.reload_recent_questions()
            self._emit("ask")

        def failed(error: Exception) -> None:
            self.pending_question, self.ask_error = None, str(error)
            self._emit("ask")

        background(lambda: self.app.api.ask(self.id, question), answered, failed)

    def set_tags(self, tags: list[str]) -> None:
        def done(_result) -> None:
            self.reload()
            self.app.reload_history()

        background(lambda: self.app.api.set_tags(self.id, tags), done, lambda _e: None)

    def rename_speaker(self, old: str, new: str) -> None:
        new = new.strip()
        if not new or new == old:
            return
        background(
            lambda: self.app.api.rename_speaker(self.id, old, new),
            lambda _r: self.reload(),
            lambda _e: None,
        )

    def delete_audio(self) -> None:
        background(
            lambda: self.app.api.delete_audio(self.id), lambda _r: self.reload(), lambda _e: None
        )

    # Texts

    def time(self, offset: float) -> str:
        """Wall-clock time of a sentence of a live meeting, position in an imported file."""
        meeting = self.meeting
        if meeting is None:
            return ""
        if meeting.get("source_file"):
            return duration(offset)
        started = datetime.fromisoformat(meeting["started_at"]).astimezone()
        return datetime.fromtimestamp(started.timestamp() + offset).strftime("%H:%M:%S")

    @property
    def transcript_text(self) -> str:
        return "\n".join(
            f"[{self.time(s['start_s'])}] {s.get('speaker') or ''} : {s['text']}"
            for s in self.segments
        )


def duration(total: float) -> str:
    seconds = max(0, int(total))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def level(db: float) -> float:
    """Audio level in dBFS as 0…1, from -60 dBFS (silence) to 0 dBFS."""
    return min(1.0, max(0.0, (db + 60) / 60))
