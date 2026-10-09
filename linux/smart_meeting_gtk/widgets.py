"""Small building blocks shared by the pages: chips, tag editor, level meters, banners, progress
estimated from the expected duration, confirmations and text prompts."""

import time
from collections.abc import Callable

from gi.repository import Adw, Gdk, GLib, Gtk

from smart_meeting_gtk.meeting_model import level

CSS = """
.chip { border-radius: 999px; padding: 1px 9px; background: alpha(@accent_bg_color, 0.15); }
.chip.purple { background: alpha(@purple_3, 0.25); }
.chip.muted { background: alpha(@view_fg_color, 0.08); }
.tag-chip { padding: 0 2px 0 9px; min-height: 0; }
.bubble { border-radius: 10px; padding: 7px 10px; background: alpha(@view_fg_color, 0.06); }
.bubble.mine { background: alpha(@accent_bg_color, 0.18); }
.bubble.partial { background: none; border: 1px dashed alpha(@view_fg_color, 0.25); font-style: italic; }
.banner-box { border-radius: 10px; padding: 12px; }
.banner-box.info { background: alpha(@accent_bg_color, 0.12); }
.banner-box.warning { background: alpha(@warning_bg_color, 0.15); }
.banner-box.error { background: alpha(@error_bg_color, 0.15); }
.timer { font-size: 34pt; font-weight: 600; font-feature-settings: "tnum"; }
.recording-label { color: @error_color; font-weight: bold; }
.dot { border-radius: 999px; min-width: 8px; min-height: 8px; }
.dot.ready { background: @success_color; }
.dot.warning { background: @warning_color; }
.dot.down { background: @error_color; }
.speaker-0 { background: @blue_3; } .speaker-1 { background: @purple_3; }
.speaker-2 { background: @green_4; } .speaker-3 { background: @orange_3; }
.speaker-4 { background: @red_2; } .speaker-5 { background: @brown_2; } .speaker-6 { background: @yellow_4; }
.panel { padding: 14px; }
.answer { border-radius: 8px; padding: 10px 12px; background: alpha(@view_fg_color, 0.05); }
"""

STATUS_LABELS = {
    "recording": "Enregistrement",
    "transcribing": "Transcription",
    "transcribed": "Transcrite",
    "analyzing": "Compte rendu en cours",
    "done": "Terminée",
    "error": "Erreur",
}
LANGUAGES = [
    ("auto", "Automatique"),
    ("fr", "Français"),
    ("en", "Anglais"),
    ("de", "Allemand"),
    ("es", "Espagnol"),
    ("it", "Italien"),
]


def install_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def label(text: str, *classes: str, wrap: bool = True, xalign: float = 0.0) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=False)
    widget.set_wrap_mode(2)  # Pango.WrapMode.WORD_CHAR
    for name in classes:
        widget.add_css_class(name)
    return widget


def chip(text: str, *classes: str) -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.add_css_class("chip")
    widget.add_css_class("caption")
    for name in classes:
        widget.add_css_class(name)
    return widget


def clear(box: Gtk.Box) -> None:
    while child := box.get_first_child():
        box.remove(child)


def copy_text(widget: Gtk.Widget, text: str) -> None:
    widget.get_clipboard().set(text)


def toast(widget: Gtk.Widget, text: str) -> None:
    overlay = widget.get_ancestor(Adw.ToastOverlay)
    if overlay is not None:
        overlay.add_toast(Adw.Toast(title=text, timeout=2))


def banner(title: str, detail: str = "", icon: str = "dialog-information-symbolic", kind: str = "info"):
    box = Gtk.Box(spacing=10)
    box.add_css_class("banner-box")
    box.add_css_class(kind)
    box.append(Gtk.Image(icon_name=icon, valign=Gtk.Align.START))
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    texts.append(label(title, "heading"))
    if detail:
        texts.append(label(detail, "dim-label"))
    box.append(texts)
    return box


def ai_status(state: tuple[str, str], model: str | None) -> Gtk.Box:
    tone, hint = state
    box = Gtk.Box(spacing=6, tooltip_text=hint, valign=Gtk.Align.CENTER)
    dot = Gtk.Box(valign=Gtk.Align.CENTER)
    dot.add_css_class("dot")
    dot.add_css_class(tone)
    box.append(dot)
    box.append(label(f"IA - {model}" if model else "IA", "caption", wrap=False))
    return box


class TagEditor(Gtk.Box):
    """Tags as removable chips, a new one typed then Enter."""

    def __init__(self, on_change: Callable[[list[str]], None], placeholder: str = "Ajouter un tag"):
        super().__init__(spacing=6)
        self.tags: list[str] = []
        self._on_change = on_change
        self._flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=4)
        self._flow.set_max_children_per_line(20)
        self._entry = Gtk.Entry(placeholder_text=placeholder, hexpand=True)
        self._entry.connect("activate", self._add)
        self.append(self._flow)
        self.append(self._entry)

    def set_tags(self, tags: list[str]) -> None:
        self.tags = list(tags)
        self._flow.remove_all()
        for tag in self.tags:
            button = Gtk.Button(tooltip_text=f"Retirer « {tag} »")
            content = Gtk.Box(spacing=2)
            content.append(Gtk.Label(label=tag))
            content.append(Gtk.Image(icon_name="window-close-symbolic", pixel_size=12))
            button.set_child(content)
            button.add_css_class("chip")
            button.add_css_class("tag-chip")
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, t=tag: self._remove(t))
            self._flow.append(button)
        self._flow.set_visible(bool(self.tags))

    def _add(self, entry: Gtk.Entry) -> None:
        tag = " ".join(entry.get_text().split())
        entry.set_text("")
        if tag and tag.lower() not in (t.lower() for t in self.tags):
            self.set_tags([*self.tags, tag])
            self._on_change(self.tags)

    def _remove(self, tag: str) -> None:
        self.set_tags([t for t in self.tags if t != tag])
        self._on_change(self.tags)


class LevelMeter(Gtk.Box):
    def __init__(self, title: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.append(label(title, "caption", "dim-label"))
        self.bar = Gtk.LevelBar(min_value=0, max_value=1)
        self.bar.remove_offset_value("low")
        self.bar.remove_offset_value("high")
        self.bar.remove_offset_value("full")
        self.append(self.bar)

    def set_db(self, db: float) -> None:
        self.bar.set_value(level(db))


class EstimatedProgress(Gtk.Box):
    """A bar moving with the time spent over the expected duration (never quite full)."""

    def __init__(self, text: str, estimate_s: float, started: float) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.append(label(text))
        self.bar = Gtk.ProgressBar(show_text=True)
        self.append(self.bar)
        self._estimate, self._started = max(estimate_s, 1.0), started
        self._tick()
        self._timer = GLib.timeout_add(500, self._tick)
        self.connect("unrealize", lambda _w: GLib.source_remove(self._timer))

    def _tick(self) -> bool:
        elapsed = time.monotonic() - self._started
        self.bar.set_fraction(min(0.95, elapsed / self._estimate))
        left = self._estimate - elapsed
        self.bar.set_text(f"encore ~{_minutes(left)}" if left > 0 else "presque terminé…")
        return True


def _minutes(seconds: float) -> str:
    return f"{int(seconds)} s" if seconds < 60 else f"{round(seconds / 60)} min"


def confirm(
    parent: Gtk.Widget,
    heading: str,
    body: str,
    confirm_label: str,
    on_confirm: Callable[[], None],
    destructive: bool = True,
) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Annuler")
    dialog.add_response("confirm", confirm_label)
    dialog.set_response_appearance(
        "confirm",
        Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED,
    )
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, response: response == "confirm" and on_confirm())
    dialog.present(parent)


def prompt_text(
    parent: Gtk.Widget,
    heading: str,
    body: str,
    initial: str,
    confirm_label: str,
    on_confirm: Callable[[str], None],
) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    entry = Gtk.Entry(text=initial, activates_default=True)
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Annuler")
    dialog.add_response("confirm", confirm_label)
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("confirm")
    dialog.set_close_response("cancel")
    dialog.connect(
        "response",
        lambda _d, response: response == "confirm" and on_confirm(entry.get_text()),
    )
    dialog.present(parent)
    entry.grab_focus()
