"""Settings (Ctrl+,): applied at once, for the next sentences and the next meetings."""

from gi.repository import Adw, GLib, Gtk

from smart_meeting_gtk.state import AppState
from smart_meeting_gtk.widgets import LANGUAGES, TagEditor

SAVE_DELAY_MS = 400


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, app: AppState) -> None:
        super().__init__(title="Paramètres", search_enabled=False)
        self.app = app
        self.draft = dict(app.preferences or {})
        self._timer = 0
        page = Adw.PreferencesPage()
        self.add(page)

        you = Adw.PreferencesGroup(
            description="Appliqués tout de suite, pour les prochaines phrases et les "
            "prochaines réunions."
        )
        name = Adw.EntryRow(title="Votre nom", text=self.draft.get("user_name") or "")
        name.connect("changed", lambda row: self._set("user_name", row.get_text()))
        you.add(name)
        name_help = Adw.ActionRow(
            subtitle="Vos phrases sont signées de ce nom, et l'IA sait que « je », c'est vous."
        )
        name_help.set_activatable(False)
        you.add(name_help)
        page.add(you)

        glossary = Adw.PreferencesGroup(
            title="Vocabulaire",
            description="Noms, sigles et termes techniques à bien reconnaître "
            "(Entrée après chaque mot).",
        )
        words = TagEditor(
            lambda tags: self._set("glossary", tags), placeholder="Ajouter un mot", vertical=True
        )
        words.set_tags(self.draft.get("glossary") or [])
        glossary.add(words)
        page.add(glossary)

        languages = Adw.PreferencesGroup(title="Langues")
        spoken = Adw.ComboRow(
            title="Langue parlée par défaut",
            subtitle="En automatique, la langue du début est gardée : quelques mots "
            "d'anglais ne la changent pas, un long passage, si.",
            model=Gtk.StringList.new([n for _, n in LANGUAGES]),
        )
        codes = [c for c, _ in LANGUAGES]
        current = self.draft.get("language") or "auto"
        spoken.set_selected(codes.index(current) if current in codes else 0)
        spoken.connect(
            "notify::selected", lambda row, _p: self._set("language", codes[row.get_selected()])
        )
        languages.add(spoken)
        answers = Adw.ComboRow(
            title="Langue des réponses et des comptes rendus",
            model=Gtk.StringList.new(["Français", "Anglais"]),
        )
        answers.set_selected(1 if self.draft.get("ui_language") == "en" else 0)
        answers.connect(
            "notify::selected",
            lambda row, _p: self._set("ui_language", "en" if row.get_selected() else "fr"),
        )
        languages.add(answers)
        page.add(languages)

        ai = Adw.PreferencesGroup(title="IA")
        model = Adw.ComboRow(
            title="Modèle d'IA",
            subtitle="Pour les questions et le compte rendu. Le modèle précis est plus long ; il "
            "est téléchargé la première fois.",
            model=Gtk.StringList.new(["Rapide (par défaut)", "Précis, plus lent"]),
        )
        model.set_selected(1 if self.draft.get("ai_mode") == "precise" else 0)
        model.connect(
            "notify::selected",
            lambda row, _p: self._set("ai_mode", "precise" if row.get_selected() else "fast"),
        )
        ai.add(model)
        page.add(ai)

        audio = Adw.PreferencesGroup(title="Audio")
        devices = app.devices or {}
        audio.add(
            self._device_row(
                "Micro",
                "Ce que vous dites.",
                "mic_device",
                devices.get("sources", []),
                devices.get("in_use_source"),
            )
        )
        audio.add(
            self._device_row(
                "Casque",
                "Ce que vous entendez : la voix des autres participants.",
                "output_device",
                devices.get("sinks", []),
                devices.get("in_use_sink"),
            )
        )
        room = Adw.SwitchRow(
            title="Réunion en salle",
            subtitle="Plusieurs personnes parlent dans mon micro : elles sont distinguées par "
            "leur voix, comme les participants à distance, au lieu d'être toutes « moi ».",
            active=bool(self.draft.get("room")),
        )
        room.connect("notify::active", lambda row, _p: self._set("room", row.get_active()))
        audio.add(room)
        keep = Adw.SwitchRow(
            title="Garder l'enregistrement audio",
            subtitle="Sinon, le son n'est gardé que pendant la réunion, au cas où, puis effacé "
            "une fois tout transcrit : seule la transcription est conservée.",
            active=bool(self.draft.get("keep_audio")),
        )
        keep.connect("notify::active", lambda row, _p: self._set("keep_audio", row.get_active()))
        audio.add(keep)
        page.add(audio)

    def _device_row(
        self, title: str, help_text: str, key: str, devices: list[dict], in_use: str | None
    ):
        automatic = self.app.describe(in_use, devices) or ""
        names = [None] + [d["name"] for d in devices]
        labels = [f"Automatique ({automatic})" if automatic else "Automatique"] + [
            d["description"] for d in devices
        ]
        row = Adw.ComboRow(title=title, subtitle=help_text, model=Gtk.StringList.new(labels))
        current = self.draft.get(key)
        row.set_selected(names.index(current) if current in names else 0)
        row.connect("notify::selected", lambda r, _p: self._set(key, names[r.get_selected()]))
        return row

    def _set(self, key: str, value) -> None:
        if self.draft.get(key) == value:
            return
        self.draft[key] = value
        if self._timer:
            GLib.source_remove(self._timer)

        def save() -> bool:
            self._timer = 0
            self.app.save_preferences(dict(self.draft))
            return False

        self._timer = GLib.timeout_add(SAVE_DELAY_MS, save)
