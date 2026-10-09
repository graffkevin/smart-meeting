"""State of the whole app: the server, its status, the history, the settings, the open meetings.
Everything is read and changed on the GTK main loop; views subscribe to the parts they show."""

from collections import defaultdict
from collections.abc import Callable

from gi.repository import GLib

from smart_meeting_gtk.api import Api, ApiError, background
from smart_meeting_gtk.server import ServerProcess

HEALTH_POLL_S = 2
UPDATE_POLL_S = 30 * 60
SEARCH_DELAY_MS = 250


class AppState:
    def __init__(self) -> None:
        self.api = Api()
        self.server = ServerProcess(self.api)
        self.health: dict | None = None
        self.unreachable = False  # stopped answering after having answered
        self.meetings: list[dict] = []
        self.history_error: str | None = None
        self.tags: list[dict] = []
        self.preferences: dict | None = None
        self.devices: dict | None = None
        self.recent_questions: list[str] = []
        self.search = ""
        self.by_tag = False
        self._listeners: dict[str, list[Callable[[], None]]] = defaultdict(list)
        self._reload_needed = True
        self._search_timer = 0
        self._models: dict[int, object] = {}
        self.report_ready: dict | None = None  # meeting whose minutes were just written
        self.update: dict | None = None  # latest version published, see check_update

    # Subscriptions: "health", "history", "settings", "questions", "update"

    def on(self, topic: str, callback: Callable[[], None]) -> None:
        self._listeners[topic].append(callback)

    def off(self, topic: str, callback: Callable[[], None]) -> None:
        if callback in self._listeners[topic]:
            self._listeners[topic].remove(callback)

    def emit(self, topic: str) -> None:
        for callback in list(self._listeners[topic]):
            callback()

    # Server

    def start(self) -> None:
        background(self.server.start, lambda _: self._poll(), lambda _: self._poll())
        GLib.timeout_add_seconds(HEALTH_POLL_S, self._poll)
        GLib.timeout_add_seconds(UPDATE_POLL_S, self.check_update)

    def check_update(self) -> bool:
        """The server reads the latest release on GitHub every few hours."""

        def answered(update: dict) -> None:
            self.update = update
            self.emit("update")

        background(self.api.update, answered, lambda _error: None)
        return True

    def _poll(self) -> bool:
        def answered(health: dict) -> None:
            previous = (self.health or {}).get("active_meeting_id")
            self.health, self.unreachable = health, False
            if self._reload_needed:
                self._reload_needed = False
                self.reload_all()
                self.check_update()
            elif previous != health.get("active_meeting_id"):
                self.reload_history()
            self.emit("health")

        def failed(_error: Exception) -> None:
            # Starting: the first answer can take a few seconds, it is not a failure yet
            self.unreachable = self.health is not None
            self._reload_needed = True
            self.emit("health")

        background(self.api.health, answered, failed)
        return True

    @property
    def active_meeting_id(self) -> int | None:
        return (self.health or {}).get("active_meeting_id")

    # History and settings

    def reload_all(self) -> None:
        self.reload_history()
        self.reload_settings()

    def reload_history(self) -> None:
        search = self.search

        def loaded(result) -> None:
            meetings, tags = result
            if search != self.search:
                return  # an older search
            self.meetings, self.tags, self.history_error = meetings, tags, None
            self.emit("history")

        def failed(error: Exception) -> None:
            self.history_error = str(error)
            self.emit("history")

        background(lambda: (self.api.meetings(search), self.api.tags()), loaded, failed)

    def set_search(self, text: str) -> None:
        self.search = text
        if self._search_timer:
            GLib.source_remove(self._search_timer)

        def run() -> bool:
            self._search_timer = 0
            self.reload_history()
            return False

        self._search_timer = GLib.timeout_add(SEARCH_DELAY_MS, run)

    def reload_settings(self) -> None:
        def loaded(result) -> None:
            self.preferences, self.devices, self.recent_questions = result
            self.emit("settings")
            self.emit("questions")

        background(
            lambda: (self.api.preferences(), self.api.devices(), self.api.recent_questions()),
            loaded,
            lambda _error: None,
        )

    def reload_recent_questions(self) -> None:
        def loaded(questions: list[str]) -> None:
            self.recent_questions = questions
            self.emit("questions")

        background(self.api.recent_questions, loaded, lambda _error: None)

    def save_preferences(self, preferences: dict) -> None:
        self.preferences = preferences

        def saved(result: dict) -> None:
            self.preferences = result
            self.emit("settings")

        background(lambda: self.api.save_preferences(preferences), saved, lambda _error: None)

    # AI state: ("ready" | "warning" | "down", explanation)

    @property
    def installing(self) -> bool:
        setup = (self.health or {}).get("setup") or []
        return any(not step["done"] and not step.get("error") for step in setup)

    @property
    def ai_state(self) -> tuple[str, str]:
        health = self.health
        if health is None or self.unreachable:
            return "down", "Smart Meeting ne répond pas"
        model = health.get("ollama_model", "")
        if not health.get("ollama"):
            if self.installing:
                return "warning", "Installation de l'IA locale en cours"
            return "down", "L'IA locale ne répond pas : relancement automatique en cours"
        if health.get("ollama_model_available"):
            return "ready", f"IA locale prête : {model}"
        return "warning", f"L'IA locale répond, mais le modèle {model} est absent"

    @property
    def ai_restartable(self) -> bool:
        return (
            self.health is not None
            and not self.unreachable
            and self.ai_state[0] != "ready"
            and not self.installing
        )

    def restart_ai(self) -> None:
        background(self.api.restart_ai, None, lambda _error: None)

    # Meetings

    def model(self, meeting_id: int):
        from smart_meeting_gtk.meeting_model import MeetingModel

        if meeting_id not in self._models:
            self._models[meeting_id] = MeetingModel(meeting_id, self)
        return self._models[meeting_id]

    def forget(self, meeting_id: int) -> None:
        model = self._models.pop(meeting_id, None)
        if model is not None:
            model.close()

    def describe(self, name: str | None, devices: list[dict]) -> str | None:
        if name is None:
            return None
        return next((d["description"] for d in devices if d["name"] == name), name)

    def call(
        self,
        work: Callable[[], object],
        done: Callable[[object], None] | None = None,
        failed: Callable[[Exception], None] | None = None,
    ) -> None:
        """An action on the server, its error shown by `failed` (or ignored)."""
        background(work, done, failed or (lambda _error: None))


def error_text(error: Exception) -> str:
    return str(error) if isinstance(error, ApiError) else f"{type(error).__name__}: {error}"
