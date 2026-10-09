"""Main window: the history in the sidebar, the home page or a meeting on the right. A file
dropped on the window is offered for import."""

from pathlib import Path

from gi.repository import Adw, Gdk, Gio, Gtk

from smart_meeting_gtk.history import HistorySidebar
from smart_meeting_gtk.home import HomePage
from smart_meeting_gtk.meeting_page import MeetingPage
from smart_meeting_gtk.settings import SettingsDialog
from smart_meeting_gtk.state import AppState


def primary_menu() -> Gio.Menu:
    menu = Gio.Menu()
    main = Gio.Menu()
    main.append("Nouvelle réunion", "app.new")
    main.append("Importer un enregistrement…", "app.import")
    menu.append_section(None, main)
    other = Gio.Menu()
    other.append("Paramètres", "app.settings")
    other.append("Journal du serveur", "app.log")
    other.append("À propos de Smart Meeting", "app.about")
    menu.append_section(None, other)
    quit_section = Gio.Menu()
    quit_section.append("Quitter", "app.quit")
    menu.append_section(None, quit_section)
    return menu


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, app: AppState) -> None:
        super().__init__(application=application, title="Smart Meeting", default_width=1280,
                         default_height=820)  # fmt: skip
        self.set_size_request(760, 520)
        self.app = app
        self.meeting_page: MeetingPage | None = None

        self.sidebar = HistorySidebar(app, self.open_meeting, self.show_home)
        self.sidebar.install_actions(self)
        sidebar_header = Adw.HeaderBar()
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=primary_menu(),
                              tooltip_text="Menu principal", primary=True)  # fmt: skip
        sidebar_header.pack_end(menu)
        sidebar_view = Adw.ToolbarView(content=self.sidebar)
        sidebar_view.add_top_bar(sidebar_header)
        self.split = Adw.NavigationSplitView(min_sidebar_width=260, max_sidebar_width=380,
                                             sidebar_width_fraction=0.26)  # fmt: skip
        self.split.set_sidebar(Adw.NavigationPage(title="Smart Meeting", child=sidebar_view))

        self.home = HomePage(app, self.open_meeting, self.open_settings)
        home_view = Adw.ToolbarView(content=self.home)
        home_view.add_top_bar(Adw.HeaderBar())
        self.home_page = Adw.NavigationPage(title="Smart Meeting", child=home_view, tag="home")
        self.split.set_content(self.home_page)

        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._dropped)
        self.add_controller(drop)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 700sp"))
        breakpoint.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint)

    def show_home(self) -> None:
        self.meeting_page = None
        self.sidebar.select(None)
        self.split.set_content(self.home_page)
        self.split.set_show_content(True)

    def open_meeting(self, meeting_id: int) -> None:
        if self.meeting_page is not None and self.meeting_page.model.id == meeting_id:
            self.split.set_show_content(True)
            return
        self.meeting_page = MeetingPage(self.app, self.app.model(meeting_id), self.show_home)
        self.split.set_content(self.meeting_page)
        self.split.set_show_content(True)
        self.sidebar.select(meeting_id)

    def open_settings(self) -> None:
        if self.app.preferences is None:
            return
        SettingsDialog(self.app).present(self)

    def import_file(self) -> None:
        self.show_home()
        self.home.import_panel.choose_file()

    def stop_recording(self) -> None:
        meeting_id = self.app.active_meeting_id
        if meeting_id is None:
            return
        self.open_meeting(meeting_id)
        if self.meeting_page is not None:
            self.meeting_page.ask_stop()

    def _dropped(self, _target, files, _x, _y) -> bool:
        paths = [Path(f.get_path()) for f in files.get_files() if f.get_path()]
        if not paths:
            return False
        self.show_home()
        self.home.import_panel.set_file(paths[0])
        return True

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))
