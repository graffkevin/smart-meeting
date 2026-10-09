"""Home: state of the first-run installs, recording a meeting, importing a file."""

from collections.abc import Callable
from pathlib import Path

from gi.repository import Adw, Gio, Gtk

from smart_meeting_gtk.state import AppState, error_text
from smart_meeting_gtk.widgets import LANGUAGES, TagEditor, banner, clear, label


def language_dropdown(selected: str) -> Gtk.DropDown:
    dropdown = Gtk.DropDown.new_from_strings([name for _, name in LANGUAGES])
    codes = [code for code, _ in LANGUAGES]
    dropdown.set_selected(codes.index(selected) if selected in codes else 0)
    return dropdown


def selected_language(dropdown: Gtk.DropDown) -> str:
    return LANGUAGES[dropdown.get_selected()][0]


class HomePage(Gtk.ScrolledWindow):
    def __init__(
        self, app: AppState, open_meeting: Callable[[int], None], open_settings: Callable[[], None]
    ):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.app, self.open_meeting, self.open_settings = app, open_meeting, open_settings
        clamp = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=20,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        holder = Adw.Clamp(maximum_size=720, child=clamp)
        self.set_child(holder)
        self._status = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._record = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.import_panel = ImportPanel(app, open_meeting)
        clamp.append(self._status)
        clamp.append(self._record)
        clamp.append(self.import_panel)
        self._form: RecordForm | None = None
        self._showing_form: bool | None = None
        app.on("health", self.refresh)
        app.on("settings", self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._refresh_status()
        active = self.app.active_meeting_id
        showing_form = active is None
        if showing_form != self._showing_form:
            self._showing_form = showing_form
            clear(self._record)
            if showing_form:
                self._form = RecordForm(self.app, self.open_meeting, self.open_settings)
                self._record.append(self._form)
            else:
                self._form = None
                self._record.append(self._in_progress(active))
        if self._form is not None:
            self._form.refresh_devices()
        self.import_panel.set_busy(active is not None)

    def _in_progress(self, meeting_id: int) -> Gtk.Widget:
        frame = Gtk.Frame()
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
            margin_top=20,
            margin_bottom=20,
            halign=Gtk.Align.CENTER,
        )
        box.append(label("● Enregistrement", "recording-label", xalign=0.5))
        box.append(label("Une réunion est en cours", "title-2", xalign=0.5))
        join = Gtk.Button(label="Reprendre la réunion", css_classes=["suggested-action", "pill"])
        join.connect("clicked", lambda _b: self.open_meeting(meeting_id))
        box.append(join)
        frame.set_child(box)
        return frame

    def _refresh_status(self) -> None:
        clear(self._status)
        app = self.app
        if app.unreachable:
            self._status.append(
                banner(
                    "Smart Meeting ne répond pas",
                    "Relancez l'application.",
                    "dialog-error-symbolic",
                    "error",
                )
            )
            return
        health = app.health
        if health is None:
            spinner = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            spinner.append(Gtk.Spinner(spinning=True))
            spinner.append(
                label(
                    "Démarrage de Smart Meeting… (la première fois, l'installation peut "
                    "prendre plusieurs minutes)",
                    wrap=True,
                )
            )
            self._status.append(spinner)
            return
        if health["whisper"] == "loading":
            self._status.append(
                banner(
                    "Préparation de la transcription",
                    "Chargement du modèle (jusqu'à 1,6 Go à télécharger au premier lancement)…",
                    "audio-input-microphone-symbolic",
                )
            )
        if health["whisper"] == "error":
            self._status.append(
                banner(
                    "La transcription ne fonctionne pas",
                    health.get("whisper_detail") or "",
                    "dialog-error-symbolic",
                    "error",
                )
            )
        setup = health.get("setup") or []
        if setup:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.append(label("Premier lancement : installation de l'IA locale", "heading"))
            for step in setup:
                if step.get("error"):
                    box.append(label(f"{step['label']} : échec. {step['error']}", "error"))
                    continue
                bar = Gtk.ProgressBar(show_text=True)
                if step.get("progress") is not None:
                    bar.set_fraction(step["progress"])
                    bar.set_text(f"{step['label']} : {int(step['progress'] * 100)} %")
                else:
                    bar.pulse()
                    bar.set_text(f"{step['label']}…")
                box.append(bar)
            box.append(
                label(
                    "Comptez 10 à 30 minutes selon votre connexion (environ 6 Go). Vous pouvez "
                    "déjà "
                    "enregistrer : le compte rendu sera disponible à la fin.",
                    "caption",
                    "dim-label",
                )
            )
            self._status.append(box)
        elif not health.get("ollama"):
            self._status.append(
                banner(
                    "L'IA locale ne répond pas",
                    "Le compte rendu automatique est indisponible.",
                    "dialog-warning-symbolic",
                    "warning",
                )
            )
        elif not health.get("ollama_model_available"):
            self._status.append(
                banner(
                    f"Le modèle d'IA {health.get('ollama_model')} est absent.",
                    "",
                    "dialog-warning-symbolic",
                    "warning",
                )
            )


class RecordForm(Gtk.Frame):
    """The main call to action: name the meeting, check its language, start recording."""

    def __init__(
        self, app: AppState, open_meeting: Callable[[int], None], open_settings: Callable[[], None]
    ):
        super().__init__()
        self.app, self.open_meeting = app, open_meeting
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=20,
            margin_bottom=20,
            margin_start=20,
            margin_end=20,
        )
        box.append(label("Prêt pour votre prochaine réunion ?", "title-1", xalign=0.5))
        box.append(
            label(
                "Smart Meeting transcrit votre réunion en direct. Demandez-lui ce que vous voulez, "
                "pendant ou après : un résumé, vos actions, qui a dit quoi… et récupérez le compte "
                "rendu. Tout reste sur votre ordinateur.",
                "dim-label",
                xalign=0.5,
            )
        )

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.title = Gtk.Entry(placeholder_text="Ex. : Ma super réunion", hexpand=True)
        self.title.connect("activate", lambda _e: self._start())
        self.tags = TagEditor(lambda _tags: None)
        preferences = app.preferences or {}
        self.language = language_dropdown(preferences.get("language") or "auto")
        for row, (name, widget) in enumerate(
            (
                ("Nom de la réunion", self.title),
                ("Tags", self.tags),
                ("Langue parlée", self.language),
            )
        ):
            grid.attach(label(name, xalign=1.0, wrap=False), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        box.append(grid)

        self.start_button = Gtk.Button(
            halign=Gtk.Align.CENTER, css_classes=["destructive-action", "pill"]
        )
        self.start_button.set_child(self._start_label("Démarrer l'enregistrement"))
        self.start_button.connect("clicked", lambda _b: self._start())
        box.append(self.start_button)

        devices = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.devices = label("", "caption", "dim-label", wrap=True)
        change = Gtk.Button(label="Modifier", css_classes=["flat", "caption"])
        change.connect("clicked", lambda _b: open_settings())
        devices.append(self.devices)
        devices.append(change)
        box.append(devices)
        box.append(
            label(
                "Lancez ensuite votre visio (Teams, Meet, Zoom…) : Smart Meeting s'adapte.",
                "caption",
                "dim-label",
                xalign=0.5,
            )
        )
        box.append(
            label(
                "Rien de ce qui se dit n'est perdu : le son est enregistré sur votre ordinateur "
                "pendant "
                "la réunion, au cas où. Si la transcription décroche, elle reprend toute seule et "
                "rattrape ce qui manque, puis ce son est effacé (sauf si vous choisissez de le "
                "garder).",
                "caption",
                "dim-label",
                xalign=0.5,
            )
        )
        self.error = label("", "error")
        self.error.set_visible(False)
        box.append(self.error)
        self.set_child(box)
        self.refresh_devices()

    @staticmethod
    def _start_label(text: str) -> Gtk.Box:
        content = Gtk.Box(spacing=8, margin_start=12, margin_end=12)
        content.append(Gtk.Image(icon_name="media-record-symbolic"))
        content.append(Gtk.Label(label=text))
        return content

    def refresh_devices(self) -> None:
        app = self.app
        preferences, devices = app.preferences or {}, app.devices or {}
        mic = (
            app.describe(
                preferences.get("mic_device") or devices.get("in_use_source"),
                devices.get("sources", []),
            )
            or "aucun"
        )
        output = (
            app.describe(
                preferences.get("output_device") or devices.get("in_use_sink"),
                devices.get("sinks", []),
            )
            or "aucun"
        )
        self.devices.set_text(f"Micro : {mic} · Son des participants : {output}")
        self.start_button.set_sensitive(app.preferences is not None and app.health is not None)

    def _start(self) -> None:
        app = self.app
        if app.preferences is None:
            return
        preferences = app.preferences
        request = {
            "title": self.title.get_text(),
            "mic_device": preferences.get("mic_device"),
            "remote_device": preferences.get("output_device"),
            "keep_audio": preferences.get("keep_audio", False),
            "room": preferences.get("room", False),
            "language": selected_language(self.language),
            "tags": self.tags.tags,
        }
        self.start_button.set_sensitive(False)
        self.start_button.set_child(self._start_label("Démarrage…"))

        def started(meeting: dict) -> None:
            self.error.set_visible(False)
            app.reload_history()
            self.open_meeting(meeting["id"])

        def failed(error: Exception) -> None:
            self.start_button.set_sensitive(True)
            self.start_button.set_child(self._start_label("Démarrer l'enregistrement"))
            self.error.set_text(f"Impossible de démarrer : {error_text(error)}")
            self.error.set_visible(True)

        app.call(lambda: app.api.start_meeting(request), started, failed)


class ImportPanel(Gtk.Frame):
    """Transcribes a video or audio file: a replay, a webinar, a voice note."""

    def __init__(self, app: AppState, open_meeting: Callable[[int], None]):
        super().__init__()
        self.app, self.open_meeting = app, open_meeting
        self.file: Path | None = None
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=14,
            margin_bottom=14,
            margin_start=14,
            margin_end=14,
        )
        top = Gtk.Box(spacing=12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        texts.append(label("Vous avez déjà un enregistrement ?", "heading"))
        texts.append(
            label(
                "Replay de visio, webinaire, note vocale… Importez la vidéo ou le fichier audio, "
                "ou "
                "déposez-le sur la fenêtre : la transcription va plus vite que la lecture.",
                "dim-label",
            )
        )
        top.append(texts)
        self.choose = Gtk.Button(label="Choisir un fichier", valign=Gtk.Align.START)
        self.choose.connect("clicked", lambda _b: self.choose_file())
        top.append(self.choose)
        box.append(top)

        self.form = Gtk.Box(spacing=8)
        self.name = Gtk.Entry(placeholder_text="Nom", hexpand=True)
        self.language = language_dropdown("auto")
        self.send = Gtk.Button(css_classes=["suggested-action"])
        self.send.connect("clicked", lambda _b: self._send())
        self.form.append(self.name)
        self.form.append(self.language)
        self.form.append(self.send)
        self.form.set_visible(False)
        box.append(self.form)
        self.note = label("", "caption", "dim-label")
        self.note.set_visible(False)
        box.append(self.note)
        self.error = label("", "error")
        self.error.set_visible(False)
        box.append(self.error)
        self.set_child(box)

    def set_busy(self, busy: bool) -> None:
        self.choose.set_sensitive(not busy)
        self.send.set_sensitive(not busy)
        self.note.set_text("Disponible une fois la réunion en cours terminée." if busy else "")
        self.note.set_visible(busy)

    def choose_file(self) -> None:
        dialog = Gtk.FileDialog(title="Importer un enregistrement")
        media = Gtk.FileFilter(name="Audio et vidéo")
        media.add_mime_type("audio/*")
        media.add_mime_type("video/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(media)
        dialog.set_filters(filters)
        dialog.open(self.get_root(), None, self._chosen)

    def _chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except Exception:  # noqa: BLE001 (cancelled)
            return
        if file is not None and file.get_path():
            self.set_file(Path(file.get_path()))

    def set_file(self, path: Path) -> None:
        self.file = path
        self.name.set_text(path.stem)
        self.send.set_label(f"Transcrire « {path.name} »")
        self.choose.set_label("Choisir un autre fichier")
        self.form.set_visible(True)

    def _send(self) -> None:
        if self.file is None:
            return
        path, title, language = self.file, self.name.get_text(), selected_language(self.language)
        self.send.set_sensitive(False)
        self.send.set_label("Envoi…")

        def sent(meeting: dict) -> None:
            self.file = None
            self.form.set_visible(False)
            self.choose.set_label("Choisir un fichier")
            self.send.set_sensitive(True)
            self.error.set_visible(False)
            self.app.reload_history()
            self.open_meeting(meeting["id"])

        def failed(error: Exception) -> None:
            self.send.set_sensitive(True)
            self.send.set_label(f"Transcrire « {path.name} »")
            self.error.set_text(f"Import impossible : {error_text(error)}")
            self.error.set_visible(True)

        self.app.call(lambda: self.app.api.import_file(path, title, language), sent, failed)
