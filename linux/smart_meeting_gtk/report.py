"""Minutes of a meeting: summary, actions, decisions, open questions, watch points, technical
topics."""

from gi.repository import Gtk

from smart_meeting_gtk.widgets import chip, label


def panel(title: str, icon: str | None = None) -> tuple[Gtk.Frame, Gtk.Box]:
    frame = Gtk.Frame()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.add_css_class("panel")
    head = Gtk.Box(spacing=8)
    if icon:
        head.append(Gtk.Image(icon_name=icon))
    head.append(label(title, "heading"))
    box.append(head)
    frame.set_child(box)
    return frame, box


def nothing() -> Gtk.Label:
    return label("Rien de particulier.", "dim-label")


def items(title: str, entries: list[str], icon: str, css: str) -> Gtk.Frame:
    frame, box = panel(title)
    if not entries:
        box.append(nothing())
    for entry in entries:
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Image(icon_name=icon, css_classes=[css], valign=Gtk.Align.START))
        text = label(entry)
        text.set_selectable(True)
        text.set_hexpand(True)
        row.append(text)
        box.append(row)
    return frame


def report_view(analysis: dict) -> Gtk.Box:
    view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

    frame, box = panel("Résumé", "format-justify-left-symbolic")
    summary = label(analysis.get("summary") or "")
    summary.set_selectable(True)
    summary.add_css_class("title-4")
    box.append(summary)
    view.append(frame)

    frame, box = panel("Actions", "object-select-symbolic")
    actions = analysis.get("actions") or []
    if not actions:
        box.append(nothing())
    else:
        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        for column, title in enumerate(("Action", "Qui", "Pour quand")):
            grid.attach(label(title, "caption", "heading", "dim-label", wrap=False), column, 0, 1, 1)
        for row, action in enumerate(actions, 1):
            task = Gtk.Box(spacing=6, hexpand=True)
            text = label(action["task"])
            text.set_selectable(True)
            task.append(text)
            if action.get("verified") is False:
                task.append(Gtk.Image(icon_name="dialog-warning-symbolic", css_classes=["warning"],
                                      tooltip_text="Introuvable mot pour mot dans la transcription : à vérifier"))  # fmt: skip
            grid.attach(task, 0, row, 1, 1)
            owner = chip(action["owner"]) if action.get("owner") else label("À définir", "caption", "dim-label")
            deadline = (chip(action["deadline"], "purple") if action.get("deadline")
                        else label("Non fixée", "caption", "dim-label"))  # fmt: skip
            for column, widget in ((1, owner), (2, deadline)):
                widget.set_halign(Gtk.Align.START)
                widget.set_valign(Gtk.Align.START)
                grid.attach(widget, column, row, 1, 1)
        box.append(grid)
    view.append(frame)

    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1,
                       max_children_per_line=2, column_spacing=16, row_spacing=16, homogeneous=True)  # fmt: skip
    flow.append(items("Décisions", analysis.get("decisions") or [], "emblem-ok-symbolic", "success"))
    flow.append(items("Questions en suspens", analysis.get("questions") or [], "dialog-question-symbolic", "accent"))
    flow.append(items("Points de vigilance", analysis.get("risks") or [], "dialog-warning-symbolic", "warning"))
    frame, box = panel("Sujets techniques")
    topics = analysis.get("technical_topics") or []
    if not topics:
        box.append(nothing())
    else:
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8)
        for topic in topics:
            chips.append(chip(topic, "muted"))
        box.append(chips)
    flow.append(frame)
    view.append(flow)
    return view
