"""Smart Meeting for Linux: a GNOME app (GTK 4, libadwaita) around the local server.

python3 -m smart_meeting_gtk        (from the linux/ folder; the .deb installs `smart-meeting-app`)
"""

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from smart_meeting_gtk.api import background  # noqa: E402
from smart_meeting_gtk.server import LOG_FILE, ROOT  # noqa: E402
from smart_meeting_gtk.state import AppState  # noqa: E402
from smart_meeting_gtk.widgets import confirm, install_css  # noqa: E402
from smart_meeting_gtk.window import MainWindow  # noqa: E402

APP_ID = "io.github.graffkevin.SmartMeeting"
VERSION = "0.2.3"


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.state = AppState()
        self.window: MainWindow | None = None
        self.quitting = False

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        install_css()
        Gtk.Window.set_default_icon_name(APP_ID)  # installed by the package
        for name, callback, accels in (
            ("new", lambda: self.window.show_home(), ["<Control>n"]),
            ("import", lambda: self.window.import_file(), ["<Control>o"]),
            ("stop", lambda: self.window.stop_recording(), ["<Control>period"]),
            ("settings", lambda: self.window.open_settings(), ["<Control>comma"]),
            ("log", self._open_log, []),
            ("about", self._about, []),
            ("quit", self.request_quit, ["<Control>q"]),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, c=callback: c())
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        self.state.on("report-ready", self._report_ready)
        self.state.start()

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MainWindow(self, self.state)
            self.window.connect("close-request", lambda _w: self.request_quit() or True)
        self.window.present()

    # Quitting: the meeting being recorded is stopped and its transcription finished first

    def request_quit(self) -> None:
        if self.quitting:
            return
        if self.state.active_meeting_id is not None and self.window is not None:
            confirm(
                self.window,
                "Quitter Smart Meeting ?",
                "Une réunion est en cours : elle sera arrêtée et sa transcription terminée. Le "
                "compte "
                "rendu pourra être généré plus tard.",
                "Quitter",
                self._quit,
            )
        else:
            self._quit()

    def _quit(self) -> None:
        self.quitting = True
        self.hold()
        if self.window is not None:
            self.window.set_visible(False)

        def stopped(_result=None) -> None:
            self.release()
            self.quit()

        background(self.state.server.stop, stopped, stopped)

    def restart(self) -> None:
        """After an update: the server stopped (even one this app did not start), then the
        app again, which starts the new server."""
        self.quitting = True
        self.hold()
        if self.window is not None:
            self.window.set_visible(False)

        def stopped(_result=None) -> None:
            launcher = ROOT / "linux" / "smart-meeting-app"
            os.execv(str(launcher), [str(launcher)])

        background(self.state.server.stop_any, stopped, stopped)

    # Menu

    def _open_log(self) -> None:
        file = Gio.File.new_for_path(str(LOG_FILE))
        Gtk.FileLauncher.new(file).open_containing_folder(self.window, None, None)

    def _about(self) -> None:
        about = Adw.AboutDialog(
            application_name="Smart Meeting",
            application_icon=APP_ID,
            version=VERSION,
            developer_name="Kevin Graff",
            license_type=Gtk.License.MIT_X11,
            website="https://github.com/graffkevin/smart-meeting",
            comments="Transcription et compte rendu de vos réunions, 100 % local : rien de ce "
            "qui se "
            "dit ne quitte votre ordinateur.",
        )
        about.present(self.window)

    def _report_ready(self) -> None:
        meeting = self.state.report_ready
        if meeting is None or (self.window is not None and self.window.is_active()):
            return
        notification = Gio.Notification.new("Compte rendu prêt")
        notification.set_body(meeting["title"])
        self.send_notification(f"report-{meeting['id']}", notification)


def main() -> int:
    GLib.set_application_name("Smart Meeting")
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
