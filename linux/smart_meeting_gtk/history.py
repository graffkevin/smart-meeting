"""History of the meetings in the sidebar: by day or by tag, searchable in titles, tags,
summaries and transcripts; a right click renames or deletes a meeting."""

from collections.abc import Callable
from datetime import date, datetime, timedelta

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from smart_meeting_gtk.meeting_model import duration
from smart_meeting_gtk.state import AppState
from smart_meeting_gtk.widgets import STATUS_LABELS, ai_status, clear, confirm, label, prompt_text

DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]  # fmt: skip


def started(meeting: dict) -> datetime:
    return datetime.fromisoformat(meeting["started_at"]).astimezone()


def day_label(day: date) -> str:
    today = date.today()
    if day == today:
        return "Aujourd'hui"
    if day == today - timedelta(days=1):
        return "Hier"
    text = f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def by_date(meetings: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[date, list[dict]] = {}
    for meeting in meetings:  # newest first already
        groups.setdefault(started(meeting).date(), []).append(meeting)
    return [(day_label(day), items) for day, items in groups.items()]


def by_tag(meetings: list[dict]) -> list[tuple[str, list[dict]]]:
    tags = sorted({t for m in meetings for t in m.get("tags") or []}, key=str.casefold)
    groups = [(f"{t} ({sum(t in (m.get('tags') or []) for m in meetings)})",
               [m for m in meetings if t in (m.get("tags") or [])]) for t in tags]  # fmt: skip
    untagged = [m for m in meetings if not m.get("tags")]
    if untagged:
        groups.append(("Sans tag", untagged))
    return groups


class HistorySidebar(Gtk.Box):
    def __init__(self, app: AppState, open_meeting: Callable[[int], None], go_home: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app, self.open_meeting, self.go_home = app, open_meeting, go_home
        self.selected: int | None = None

        search = Gtk.SearchEntry(placeholder_text="Un mot, un nom, un sujet…")
        search.connect("search-changed", lambda entry: app.set_search(entry.get_text()))
        switch = Gtk.Box(spacing=0, homogeneous=True, css_classes=["linked"])
        self._by_date_button = Gtk.ToggleButton(label="Par date", active=True)
        self._by_tag_button = Gtk.ToggleButton(label="Par tag", group=self._by_date_button)
        self._by_tag_button.connect("toggled", self._toggle_view)
        switch.append(self._by_date_button)
        switch.append(self._by_tag_button)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=10,
                      margin_end=10, margin_top=6, margin_bottom=6)  # fmt: skip
        new = Gtk.Button(label="Nouvelle réunion", css_classes=["suggested-action", "pill"])
        new.connect("clicked", lambda _b: self.go_home())
        top.append(new)
        top.append(search)
        top.append(switch)
        self.append(top)

        self._list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=6,
                             margin_end=6, margin_bottom=6)  # fmt: skip
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scrolled.set_child(self._list)
        self.append(scrolled)

        self._footer = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=6, margin_bottom=8)
        self.append(Gtk.Separator())
        self.append(self._footer)

        app.on("history", self.refresh)
        app.on("health", self._refresh_footer)
        self.refresh()
        self._refresh_footer()

    def _toggle_view(self, button: Gtk.ToggleButton) -> None:
        self.app.by_tag = button.get_active()
        self.refresh()

    def select(self, meeting_id: int | None) -> None:
        self.selected = meeting_id
        self.refresh()

    def refresh(self) -> None:
        clear(self._list)
        app = self.app
        if app.history_error:
            self._list.append(Adw.StatusPage(icon_name="dialog-warning-symbolic",
                                             title="Historique indisponible",
                                             description=app.history_error))  # fmt: skip
            return
        if not app.meetings:
            if app.health is not None:
                text = ("Vos réunions apparaîtront ici après votre premier enregistrement."
                        if not app.search else "Aucune réunion ne correspond.")  # fmt: skip
                page = Adw.StatusPage(icon_name="audio-input-microphone-symbolic",
                                      title="Aucune réunion", description=text)  # fmt: skip
                page.add_css_class("compact")
                self._list.append(page)
            return
        groups = by_tag(app.meetings) if app.by_tag else by_date(app.meetings)
        for title, meetings in groups:
            self._list.append(label(title, "heading", "dim-label", wrap=False))
            box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
            box.connect("row-activated", lambda _b, row: self.open_meeting(row.meeting_id))
            for meeting in meetings:
                row = self._row(meeting)
                box.append(row)
                if meeting["id"] == self.selected:
                    box.select_row(row)
            self._list.append(box)

    def _row(self, meeting: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.meeting_id = meeting["id"]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_start=10,
                      margin_end=10, margin_top=6, margin_bottom=6)  # fmt: skip
        title = Gtk.Box(spacing=6)
        recording = meeting["id"] == self.app.active_meeting_id
        if recording:
            title.append(Gtk.Image(icon_name="media-record-symbolic", css_classes=["error"]))
        name = label(meeting["title"], wrap=False)
        name.set_ellipsize(3)  # END
        title.append(name)
        box.append(title)
        details = [started(meeting).strftime("%H:%M")]
        if meeting.get("ended_at"):
            end = datetime.fromisoformat(meeting["ended_at"]).astimezone()
            details.append(duration((end - started(meeting)).total_seconds()))
        if not recording and meeting["status"] != "done":
            details.append(STATUS_LABELS.get(meeting["status"], meeting["status"]))
        count = meeting.get("action_count") or 0
        if count:
            details.append("1 action" if count == 1 else f"{count} actions")
        info = label(" · ".join(details), "caption", "dim-label", wrap=False)
        box.append(info)
        row.set_child(box)

        menu = Gio.Menu()
        menu.append("Renommer…", f"history.rename({meeting['id']})")
        menu.append("Supprimer…", f"history.delete({meeting['id']})")
        popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=False)
        popover.set_parent(row)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", lambda _g, _n, x, y: self._popup(popover, x, y))
        row.add_controller(click)
        return row

    @staticmethod
    def _popup(popover: Gtk.PopoverMenu, x: float, y: float) -> None:
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()

    def install_actions(self, window: Gtk.Window) -> None:
        group = Gio.SimpleActionGroup()
        rename = Gio.SimpleAction.new("rename", GLib.VariantType.new("i"))
        rename.connect("activate", lambda _a, value: self._rename(value.get_int32()))
        delete = Gio.SimpleAction.new("delete", GLib.VariantType.new("i"))
        delete.connect("activate", lambda _a, value: self._delete(value.get_int32()))
        group.add_action(rename)
        group.add_action(delete)
        window.insert_action_group("history", group)

    def _meeting(self, meeting_id: int) -> dict | None:
        return next((m for m in self.app.meetings if m["id"] == meeting_id), None)

    def _rename(self, meeting_id: int) -> None:
        meeting = self._meeting(meeting_id)
        if meeting is None:
            return

        def renamed(title: str) -> None:
            title = title.strip()
            if title:
                self.app.call(lambda: self.app.api.rename(meeting_id, title),
                              lambda _r: self._after_change(meeting_id))  # fmt: skip

        prompt_text(self, "Renommer la réunion", "", meeting["title"], "Renommer", renamed)

    def _delete(self, meeting_id: int) -> None:
        meeting = self._meeting(meeting_id)
        if meeting is None:
            return
        if meeting["status"] == "recording":
            return

        def deleted(_result=None) -> None:
            self.app.forget(meeting_id)
            if self.selected == meeting_id:
                self.go_home()
            self.app.reload_history()

        confirm(
            self,
            "Supprimer cette réunion ?",
            f"« {meeting['title']} », sa transcription et son compte rendu seront définitivement supprimés.",
            "Supprimer",
            lambda: self.app.call(lambda: self.app.api.delete_meeting(meeting_id), deleted),
        )

    def _after_change(self, meeting_id: int) -> None:
        self.app.reload_history()
        self.app.model(meeting_id).reload()

    def _refresh_footer(self) -> None:
        clear(self._footer)
        local = Gtk.Box(spacing=4, tooltip_text="Aucune donnée n'est envoyée ailleurs : le son, "
                        "la transcription, vos questions et les réponses de l'IA restent sur votre ordinateur.")  # fmt: skip
        local.append(Gtk.Image(icon_name="security-high-symbolic", css_classes=["success"]))
        local.append(label("100 % local", "caption", wrap=False))
        self._footer.append(local)
        self._footer.append(Gtk.Box(hexpand=True))
        health = self.app.health or {}
        self._footer.append(ai_status(self.app.ai_state, health.get("ollama_model")))
        if self.app.ai_restartable:
            restart = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Redémarrer l'IA locale",
                                 css_classes=["flat"])  # fmt: skip
            restart.connect("clicked", lambda _b: self.app.restart_ai())
            self._footer.append(restart)

