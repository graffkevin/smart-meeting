"""A meeting: live recording, questions to the AI and its minutes; the transcript on the side."""

import time
from collections.abc import Callable
from datetime import datetime

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from smart_meeting_gtk.meeting_model import MeetingModel, duration
from smart_meeting_gtk.report import report_view
from smart_meeting_gtk.state import AppState
from smart_meeting_gtk.transcript import TranscriptPane
from smart_meeting_gtk.widgets import (
    STATUS_LABELS,
    EstimatedProgress,
    LevelMeter,
    TagEditor,
    ai_status,
    banner,
    chip,
    clear,
    confirm,
    copy_text,
    label,
    toast,
)

BIDIRECTIONAL = GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
QUICK_QUESTIONS = [
    ("Résumer", "view-list-symbolic", "Fais un résumé de la réunion jusqu'ici."),
    ("Mes actions", "object-select-symbolic", "Qu'est-ce que je dois faire ?"),
    ("Décisions", "emblem-ok-symbolic", "Quelles décisions ont été prises ?"),
]


class MeetingPage(Adw.NavigationPage):
    def __init__(self, app: AppState, model: MeetingModel, go_home: Callable[[], None]) -> None:
        super().__init__(title="Réunion")
        self.app, self.model, self.go_home = app, model, go_home
        model.reopen()

        self.header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle()
        self.header.set_title_widget(self.title_widget)
        self.stop_button = Gtk.Button(
            label="Arrêter l'enregistrement", css_classes=["destructive-action"]
        )
        self.stop_button.connect("clicked", lambda _b: self.ask_stop())
        self.menu_button = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Actions")
        self.transcript_toggle = Gtk.ToggleButton(
            icon_name="sidebar-show-right-symbolic",
            active=True,
            tooltip_text="Afficher ou masquer la transcription",
        )
        self.header.pack_end(self.transcript_toggle)
        self.header.pack_end(self.menu_button)
        self.header.pack_end(self.stop_button)

        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=20,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scrolled.set_child(Adw.Clamp(maximum_size=900, child=self.content))
        self.split = Adw.OverlaySplitView(
            sidebar_position=Gtk.PackType.END,
            show_sidebar=True,
            min_sidebar_width=300,
            max_sidebar_width=520,
            sidebar_width_fraction=0.4,
        )
        self.split.set_content(scrolled)
        self.split.set_sidebar(TranscriptPane(model))
        self.transcript_toggle.bind_property("active", self.split, "show-sidebar", BIDIRECTIONAL)
        toolbar = Adw.ToolbarView(content=self.split)
        toolbar.add_top_bar(self.header)
        self.set_child(toolbar)

        self._install_actions()
        self._live_widgets: dict = {}
        self._question_text = ""
        self._timer = GLib.timeout_add_seconds(1, self._tick)
        model.on(self._changed)
        app.on("health", self._update_live)
        self.connect("unrealize", self._closed)
        self.rebuild()
        model.reload()

    def _closed(self, _widget) -> None:
        GLib.source_remove(self._timer)
        self.model.off(self._changed)
        self.app.off("health", self._update_live)
        self.model.close()

    def _changed(self, what: str) -> None:
        if what in ("detail", "ask"):
            self.rebuild()
        elif what == "live":
            self._update_live()

    # Header and actions

    def _install_actions(self) -> None:
        group = Gio.SimpleActionGroup()
        for name, callback in (
            ("copy", self._copy_report),
            ("analyze", lambda: self.model.analyze()),
            ("delete-audio", lambda: self.model.delete_audio()),
            ("delete", self._ask_delete),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, c=callback: c())
            group.add_action(action)
        self.insert_action_group("meeting", group)

    def _menu(self, detail: dict) -> Gio.Menu:
        menu = Gio.Menu()
        if self.model.report:
            menu.append("Copier le compte rendu", "meeting.copy")
        if detail["segments"]:
            menu.append(
                "Régénérer le compte rendu"
                if detail.get("analysis")
                else "Générer le compte rendu",
                "meeting.analyze",
            )
        if detail.get("has_audio"):
            menu.append("Supprimer l'audio", "meeting.delete-audio")
        danger = Gio.Menu()
        danger.append("Supprimer la réunion…", "meeting.delete")
        menu.append_section(None, danger)
        return menu

    def _copy_report(self) -> None:
        if self.model.report:
            copy_text(self, self.model.report)
            toast(self, "Compte rendu copié")

    def _ask_delete(self) -> None:
        meeting = self.model.meeting
        if meeting is None:
            return

        def deleted(_result=None) -> None:
            self.app.forget(self.model.id)
            self.app.reload_history()
            self.go_home()

        confirm(
            self,
            "Supprimer cette réunion ?",
            f"« {meeting['title']} », sa transcription et son compte rendu seront définitivement "
            "supprimés.",
            "Supprimer",
            lambda: self.app.call(lambda: self.app.api.delete_meeting(self.model.id), deleted),
        )

    def ask_stop(self) -> None:
        """Stopping asks first: a key pressed by mistake must not end a meeting."""
        confirm(
            self,
            "Arrêter l'enregistrement ?",
            "La transcription se termine, puis l'IA rédige le compte rendu. L'enregistrement ne "
            "pourra "
            "pas reprendre dans cette réunion.",
            "Arrêter",
            self.model.stop,
        )

    # Content

    def rebuild(self) -> None:
        if "question" in self._live_widgets:
            self._question_text = self._live_widgets["question"].get_text()
        clear(self.content)
        self._live_widgets = {}
        model, detail = self.model, self.model.detail
        if detail is None:
            if model.load_error:
                self.content.append(
                    Adw.StatusPage(
                        icon_name="dialog-warning-symbolic",
                        title="Réunion introuvable",
                        description=model.load_error,
                    )
                )
            else:
                self.content.append(Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER))
            self.stop_button.set_visible(False)
            self.menu_button.set_visible(False)
            return
        meeting = detail["meeting"]
        status = meeting["status"]
        self.set_title(meeting["title"])
        self.title_widget.set_title(meeting["title"])
        started = datetime.fromisoformat(meeting["started_at"]).astimezone()
        self.title_widget.set_subtitle(started.strftime("%d/%m/%Y %H:%M"))
        self.stop_button.set_visible(status == "recording")
        self.stop_button.set_sensitive(not model.stopping)
        finished = status in ("transcribed", "done")
        self.menu_button.set_visible(finished)
        if finished:
            self.menu_button.set_menu_model(self._menu(detail))

        self.content.append(self._header(meeting))
        if status == "recording":
            self.content.append(self._live_panel(meeting, detail))
        if status == "transcribing":
            self._live_widgets["progress"] = Gtk.ProgressBar(show_text=True)
            self.content.append(self._live_widgets["progress"])
            self._update_live()
        if status == "analyzing":
            estimate = (detail.get("estimates") or {}).get("analysis_s") or 30
            started_at = model.loaded_at - (detail.get("analysis_elapsed_s") or 0)
            self.content.append(
                EstimatedProgress("L'IA locale rédige le compte rendu…", estimate, started_at)
            )
        for message in filter(None, (meeting.get("error"), model.action_error)):
            self.content.append(label(f"⚠ {message}", "warning"))
        if status == "transcribed" and not detail.get("analysis") and detail["segments"]:
            analyze = Gtk.Button(
                label="Générer le compte rendu",
                halign=Gtk.Align.START,
                css_classes=["suggested-action"],
            )
            analyze.connect("clicked", lambda _b: model.analyze())
            self.content.append(analyze)
        self.content.append(self._ask_panel(detail))
        if detail.get("analysis"):
            self.content.append(report_view(detail["analysis"]))
        if finished and detail.get("storage"):
            self.content.append(self._storage(detail["storage"]))

    def _header(self, meeting: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top = Gtk.Box(spacing=8)
        title = Gtk.EditableLabel(
            text=meeting["title"], hexpand=True, tooltip_text="Cliquez pour renommer"
        )
        title.add_css_class("title-1")
        title.connect("notify::editing", self._title_edited)
        top.append(title)
        if meeting.get("language") and meeting["language"] != "auto":
            top.append(chip(meeting["language"].upper(), "muted"))
        if meeting["status"] != "recording":
            top.append(
                chip(
                    STATUS_LABELS.get(meeting["status"], meeting["status"]),
                    "muted" if meeting["status"] != "done" else "",
                )
            )
        box.append(top)
        tags = TagEditor(self.model.set_tags)
        tags.set_tags(meeting.get("tags") or [])
        box.append(tags)
        if meeting.get("source_file"):
            box.append(label(f"Fichier : {meeting['source_file']}", "caption", "dim-label"))
        return box

    def _title_edited(self, editable: Gtk.EditableLabel, _param) -> None:
        if editable.get_editing():
            return
        title = editable.get_text().strip()
        meeting = self.model.meeting
        if title and meeting and title != meeting["title"]:
            self.app.call(
                lambda: self.app.api.rename(self.model.id, title),
                lambda _r: (self.app.reload_history(), self.model.reload()),
            )

    def _live_panel(self, meeting: dict, detail: dict) -> Gtk.Widget:
        frame = Gtk.Frame()
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        box.append(label("● Enregistrement", "recording-label", xalign=0.5))
        clock = label("", "timer", xalign=0.5, wrap=False)
        box.append(clock)
        levels = Gtk.Box(spacing=24)
        mic, remote = LevelMeter("Vous"), LevelMeter("Participants")
        levels.append(mic)
        levels.append(remote)
        box.append(levels)
        stop = Gtk.Button(halign=Gtk.Align.CENTER, css_classes=["destructive-action", "pill"])
        content = Gtk.Box(spacing=8, margin_start=12, margin_end=12)
        content.append(Gtk.Image(icon_name="media-playback-stop-symbolic"))
        content.append(Gtk.Label(label="Arrêter l'enregistrement"))
        stop.set_child(content)
        stop.set_sensitive(not self.model.stopping)
        stop.connect("clicked", lambda _b: self.ask_stop())
        box.append(stop)
        waiting = banner(
            "Préparation de la transcription",
            "Le modèle de transcription se télécharge (la première fois seulement). Tout ce qui "
            "se dit est enregistré et sera transcrit dès qu'il sera prêt : rien n'est perdu.",
            "folder-download-symbolic",
        )
        box.append(waiting)
        queue = label("", "caption", "dim-label", xalign=0.5)
        devices = label("", "caption", "dim-label", xalign=0.5)
        errors = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(queue)
        box.append(devices)
        box.append(errors)
        frame.set_child(box)
        started = datetime.fromisoformat(meeting["started_at"]).astimezone().timestamp()
        self._live_widgets.update(
            clock=clock,
            started=started,
            mic=mic,
            remote=remote,
            queue=queue,
            devices=devices,
            errors=errors,
            captured=detail.get("captured"),
            stop=stop,
            waiting=waiting,
        )
        self._tick()
        self._update_live()
        return frame

    def _tick(self) -> bool:
        clock = self._live_widgets.get("clock")
        if clock is not None:
            clock.set_text(duration(time.time() - self._live_widgets["started"]))
        return True

    def _update_live(self) -> None:
        model, widgets = self.model, self._live_widgets
        if "progress" in widgets and model.progress:
            done, total = model.progress
            bar = widgets["progress"]
            bar.set_fraction(done / max(total, 1) if total else 0)
            bar.set_text(
                f"Transcription du fichier · {duration(done)}"
                + (f" / {duration(total)}" if total else "")
            )
        if "mic" not in widgets:
            return
        levels = model.levels or {}
        widgets["mic"].set_db(levels.get("mic", -60))
        widgets["remote"].set_db(levels.get("remote", -60))
        widgets["stop"].set_sensitive(not model.stopping)
        widgets["waiting"].set_visible((self.app.health or {}).get("whisper") == "loading")
        self.stop_button.set_sensitive(not model.stopping)
        queue = model.queue
        widgets["queue"].set_text(f"{queue} phrase(s) en attente de transcription" if queue else "")
        captured = model.devices or widgets["captured"] or {}
        widgets["devices"].set_text(
            f"Micro : {self._device(captured.get('mic'))} · "
            f"Son : {self._device(captured.get('remote'))}"
        )
        clear(widgets["errors"])
        if (captured.get("mic") or {}).get("error"):
            widgets["errors"].append(
                label(f"Votre micro n'est pas capté : {captured['mic']['error']}", "warning")
            )
        if (captured.get("remote") or {}).get("error"):
            widgets["errors"].append(
                label(
                    f"Le son des participants n'est pas capté : {captured['remote']['error']}",
                    "warning",
                )
            )

    def _device(self, source: dict | None) -> str:
        if not source or not source.get("device"):
            return "par défaut"
        devices = self.app.devices or {}
        known = devices.get("sources", []) + devices.get("sinks", [])
        description = self.app.describe(source["device"], known) or source["device"]
        return f"{description} (auto)" if source.get("auto") else description

    def _ask_panel(self, detail: dict) -> Gtk.Widget:
        model = self.model
        frame = Gtk.Frame()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("panel")
        empty = not detail["segments"]
        unavailable = empty or self.app.ai_state[0] != "ready" or model.pending_question is not None
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Image(icon_name="dialog-question-symbolic"))
        head.append(label("Interroger la réunion", "heading"))
        head.append(Gtk.Box(hexpand=True))
        head.append(ai_status(self.app.ai_state, (self.app.health or {}).get("ollama_model")))
        box.append(head)
        box.append(
            label(
                "Les questions deviendront possibles dès les premières phrases transcrites."
                if empty
                else "Posez une question : l'IA locale répond à partir de la transcription, même "
                "pendant la réunion.",
                "dim-label",
            )
        )
        quick = Gtk.Box(spacing=8)
        for text, icon, question in QUICK_QUESTIONS:
            button = Gtk.Button(sensitive=not unavailable)
            content = Gtk.Box(spacing=6)
            content.append(Gtk.Image(icon_name=icon))
            content.append(Gtk.Label(label=text))
            button.set_child(content)
            button.connect("clicked", lambda _b, q=question: model.ask(q))
            quick.append(button)
        box.append(quick)

        row = Gtk.Box(spacing=8)
        entry = Gtk.Entry(
            placeholder_text="Ex. : Qu'a-t-on décidé pour l'hébergement ?",
            hexpand=True,
            sensitive=not empty,
            text=self._question_text,
        )
        ask = Gtk.Button(label="Demander", css_classes=["suggested-action"])

        def submit(*_args) -> None:
            text = entry.get_text()
            if text.strip() and not unavailable:
                self._question_text = ""
                entry.set_text("")
                model.ask(text)

        entry.connect("activate", submit)
        ask.connect("clicked", submit)
        ask.set_sensitive(not unavailable)
        row.append(entry)
        if self.app.recent_questions and not empty:
            recent = Gio.Menu()
            for index, question in enumerate(self.app.recent_questions[:10]):
                recent.append(question[:80], f"recent.pick({index})")
            group = Gio.SimpleActionGroup()
            pick = Gio.SimpleAction.new("pick", GLib.VariantType.new("i"))
            pick.connect(
                "activate",
                lambda _a, value: entry.set_text(self.app.recent_questions[value.get_int32()]),
            )
            group.add_action(pick)
            menu = Gtk.MenuButton(
                icon_name="document-open-recent-symbolic",
                menu_model=recent,
                tooltip_text="Questions récentes",
            )
            menu.insert_action_group("recent", group)
            row.append(menu)
        row.append(ask)
        box.append(row)
        self._live_widgets["question"] = entry

        for answer in detail.get("questions") or []:
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            item.add_css_class("answer")
            item.append(label(answer["question"], "heading"))
            text = label(answer["answer"])
            text.set_selectable(True)
            item.append(text)
            box.append(item)
        if model.pending_question is not None:
            question, started = model.pending_question
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            item.add_css_class("answer")
            item.append(label(question, "heading"))
            estimate = (detail.get("estimates") or {}).get("ask_s") or 30
            item.append(EstimatedProgress("L'IA locale réfléchit…", estimate, started))
            box.append(item)
        if model.ask_error:
            box.append(label(f"Pas de réponse : {model.ask_error}", "warning"))
        frame.set_child(box)
        return frame

    def _storage(self, storage: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for title, path in (
            ("Enregistrée dans", storage.get("database")),
            ("Audio dans", storage.get("audio")),
        ):
            if not path:
                continue
            row = Gtk.Box(spacing=6)
            row.append(label(title, "caption", "dim-label", wrap=False))
            text = label(path, "caption", "monospace", wrap=False)
            text.set_selectable(True)
            text.set_ellipsize(2)  # MIDDLE
            row.append(text)
            show = Gtk.Button(label="Ouvrir le dossier", css_classes=["flat", "caption"])
            show.connect("clicked", lambda _b, p=path: self._open_folder(p))
            row.append(show)
            box.append(row)
        return box

    def _open_folder(self, path: str) -> None:
        file = Gio.File.new_for_path(path)
        Gtk.FileLauncher.new(file).open_containing_folder(self.get_root(), None, None)
