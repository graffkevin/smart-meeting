"""`smart-meeting --install`: Smart Meeting among the applications of the system, to pin it to the
dock or the taskbar. Linux: an entry of the applications menu; macOS: `~/Applications/Smart
Meeting.app`; Windows: a Start menu shortcut. Each one runs the launcher of the repository."""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Smart Meeting"
LINUX_APP_ID = "io.github.graffkevin.SmartMeeting"


def install(root: Path) -> Path:
    """Create the shortcut for this system; returns where it is."""
    if sys.platform == "darwin":
        return _install_macos(root)
    if sys.platform == "win32":
        return _install_windows(root)
    return _install_linux(root)


def _install_linux(root: Path) -> Path:
    """The GNOME app (linux/) when GTK 4 and libadwaita are there: its own entry and icon, as the
    package installs them, in the user's folders (no admin rights). Else the browser version."""
    share = Path.home() / ".local" / "share"
    old = share / "applications" / "smart-meeting.desktop"  # browser version, earlier installs
    if _gnome_app_available(root):
        entry = share / "applications" / f"{LINUX_APP_ID}.desktop"
        icon = share / "icons" / "hicolor" / "scalable" / "apps" / f"{LINUX_APP_ID}.svg"
        for folder in (entry.parent, icon.parent):
            folder.mkdir(parents=True, exist_ok=True)
        template = (root / "packaging" / "linux" / f"{LINUX_APP_ID}.desktop").read_text("utf-8")
        launcher = shlex.quote(str(root / "linux" / "smart-meeting-app"))
        entry.write_text(template.replace("@EXEC@", launcher), encoding="utf-8")
        shutil.copyfile(root / "macos" / "app-icon.svg", icon)
        old.unlink(missing_ok=True)
        return entry
    template = (root / "packaging" / "smart-meeting.desktop").read_text(encoding="utf-8")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(template.replace("@ROOT@", str(root)), encoding="utf-8")
    return old


def _gnome_app_available(root: Path) -> bool:
    if not (root / "linux" / "smart-meeting-app").exists():
        return False
    check = "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')"
    try:  # the system Python: the app does not run in the server's environment
        return (
            subprocess.run(["/usr/bin/python3", "-c", check], capture_output=True).returncode == 0
        )
    except OSError:
        return False


def _install_macos(root: Path) -> Path:
    app = Path.home() / "Applications" / f"{APP_NAME}.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Info.plist").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>{APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>local.smart-meeting</string>
  <key>CFBundleExecutable</key><string>smart-meeting</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Transcrire votre micro pendant les réunions, sur votre ordinateur.</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    executable = contents / "MacOS" / "smart-meeting"
    # Login shell: gets PATH (uv) and the proxy settings from the user profile
    launcher = shlex.quote(str(root / "smart-meeting"))
    executable.write_text(f"#!/bin/bash\nexec /bin/bash -lc {shlex.quote(launcher)}\n")
    executable.chmod(0o755)
    return app


def _install_windows(root: Path) -> Path:
    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    link = programs / f"{APP_NAME}.lnk"
    launcher = root / "smart-meeting.cmd"
    # A shortcut to cmd.exe (not to the .cmd itself) can be pinned to the taskbar
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK); "
        "$s.TargetPath = $env:ComSpec; "
        '$s.Arguments = "/c `"$env:LAUNCHER`""; '
        "$s.WorkingDirectory = $env:ROOT; "
        "$s.WindowStyle = 7; "  # minimized: the app is the browser page
        "$s.Description = 'Transcription et compte rendu de réunions, 100 % local'; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        env={**os.environ, "LINK": str(link), "LAUNCHER": str(launcher), "ROOT": str(root)},
    )
    return link
