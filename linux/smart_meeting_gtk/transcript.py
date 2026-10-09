"""Transcript as a conversation: my sentences on the right, the other participants on the left,
each speaker with their own color. Double-click a speaker to name them in the whole meeting
("Intervenant 2" -> "Paul"; a name already used merges both). While recording, the sentences
being spoken follow in italics until their final transcription."""

from gi.repository import Adw, GLib, Gtk

from smart_meeting_gtk.meeting_model import MeetingModel
from smart_meeting_gtk.widgets import clear, copy_text, label, prompt_text, toast

COLORS = 7


class TranscriptPane(Gtk.Box):
    def __init__(self, model: MeetingModel) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.model = model
        self.set_size_request(320, -1)
        header = Gtk.Box(spacing=6, margin_start=14, margin_end=8, margin_top=8, margin_bottom=8)
        header.append(label("Transcription", "heading"))
        header.append(Gtk.Box(hexpand=True))
        self.copy = Gtk.Button(
            icon_name="edit-copy-symbolic",
            tooltip_text="Copier toute la transcription",
            css_classes=["flat"],
        )
        self.copy.connect("clicked", self._copy)
        header.append(self.copy)
        self.append(header)
        self.append(Gtk.Separator())
        self._list = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_start=14,
            margin_end=14,
            margin_top=14,
            margin_bottom=14,
        )
        self._scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._scrolled.set_child(self._list)
        self.append(self._scrolled)
        self._shown: list = []  # ids of the sentences on screen, in order
        self._partials: list[Gtk.Widget] = []
        model.on(self._changed)
        self.connect("unrealize", lambda _w: model.off(self._changed))
        self.rebuild()

    def _changed(self, what: str) -> None:
        if what == "detail":
            self.rebuild()
        elif what == "segments":
            self._append_new()
        elif what == "partials":
            self._show_partials()

    @property
    def _live(self) -> bool:
        return self.model.status == "recording"

    def _speakers(self) -> list[str]:
        speakers: list[str] = []
        for segment in self.model.segments:
            name = segment.get("speaker")
            if name and name not in speakers:
                speakers.append(name)
        return speakers

    def rebuild(self) -> None:
        clear(self._list)
        self._shown, self._partials = [], []
        segments = self.model.segments
        self.copy.set_visible(bool(segments))
        if self.model.detail is None:  # not loaded yet: not "nothing said"
            if not self.model.load_error:
                self._list.append(
                    Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, margin_top=48)
                )
            return
        if not segments and not (self._live and self.model.partials):
            empty = Adw.StatusPage(
                icon_name="audio-input-microphone-symbolic",
                title="Smart Meeting écoute…" if self._live else "Aucune parole détectée.",
                description="Les phrases apparaîtront ici au fil de la réunion."
                if self._live
                else "",
            )
            empty.add_css_class("compact")
            self._list.append(empty)
            return
        self._append_new()

    def _append_new(self) -> None:
        segments = self.model.segments
        ids = [s.get("id") for s in segments]
        if ids[: len(self._shown)] != self._shown:
            # A sentence inserted before the last one shown (the other source was later), or one
            # removed (an echo): everything again
            clear(self._list)
            self._shown, self._partials = [], []
        elif not self._shown and segments:
            clear(self._list)  # the "listening" placeholder
        speakers = self._speakers()
        for partial in self._partials:
            self._list.remove(partial)
        self._partials = []
        for segment in segments[len(self._shown) :]:
            self._list.append(self._bubble(segment, speakers))
        self._shown = ids
        self.copy.set_visible(bool(segments))
        self._show_partials()
        if self._live:
            GLib.idle_add(self._scroll_to_end)

    def _show_partials(self) -> None:
        for partial in self._partials:
            self._list.remove(partial)
        self._partials = []
        if not self._live:
            return
        for partial in sorted(self.model.partials.values(), key=lambda p: p["start_s"]):
            widget = self._partial(partial)
            self._partials.append(widget)
            self._list.append(widget)
        GLib.idle_add(self._scroll_to_end)

    def _scroll_to_end(self) -> bool:
        adjustment = self._scrolled.get_vadjustment()
        adjustment.set_value(adjustment.get_upper())
        return False

    def _bubble(self, segment: dict, speakers: list[str]) -> Gtk.Widget:
        mine = segment["source"] == "mic"
        align = Gtk.Align.END if mine else Gtk.Align.START
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, halign=align)
        box.set_margin_start(36 if mine else 0)
        box.set_margin_end(0 if mine else 36)
        meta = Gtk.Box(spacing=6, halign=align)
        speaker = segment.get("speaker")
        if speaker:
            name = Gtk.Box(
                spacing=4,
                tooltip_text="Double-cliquez pour nommer cet intervenant dans toute la réunion",
            )
            dot = Gtk.Box(valign=Gtk.Align.CENTER)
            dot.add_css_class("dot")
            dot.add_css_class(
                f"speaker-{speakers.index(speaker) % COLORS if speaker in speakers else 0}"
            )
            name.append(dot)
            name.append(label(speaker, "caption", "heading", wrap=False))
            click = Gtk.GestureClick()
            click.connect(
                "pressed", lambda _g, count, _x, _y, s=speaker: count == 2 and self._rename(s)
            )
            name.add_controller(click)
            meta.append(name)
        meta.append(label(self.model.time(segment["start_s"]), "caption", "dim-label", wrap=False))
        box.append(meta)
        text = label(segment["text"])
        text.set_selectable(True)
        text.add_css_class("bubble")
        if mine:
            text.add_css_class("mine")
        box.append(text)
        return box

    def _partial(self, partial: dict) -> Gtk.Widget:
        mine = partial["source"] == "mic"
        align = Gtk.Align.END if mine else Gtk.Align.START
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, halign=align)
        box.append(
            label(
                f"{partial['speaker']} · {self.model.time(partial['start_s'])}",
                "caption",
                "dim-label",
                wrap=False,
            )
        )
        text = label(f"{partial['text']}…", "dim-label")
        text.add_css_class("bubble")
        text.add_css_class("partial")
        box.append(text)
        return box

    def _rename(self, speaker: str) -> None:
        prompt_text(
            self,
            "Nommer cet intervenant",
            "Dans toute la réunion. Un nom déjà utilisé fusionne les deux intervenants.",
            speaker,
            "Renommer",
            lambda name: self.model.rename_speaker(speaker, name),
        )

    def _copy(self, _button) -> None:
        copy_text(self, self.model.transcript_text)
        toast(self, "Transcription copiée")
