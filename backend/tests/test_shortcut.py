import subprocess
from pathlib import Path

from smart_meeting import shortcut

ROOT = Path(__file__).resolve().parents[2]


def test_linux_without_gtk_runs_the_browser_version(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(shortcut, "_gnome_app_available", lambda root: False)
    entry = shortcut._install_linux(ROOT).read_text()
    assert f"Exec=/bin/bash -lc '{ROOT}/smart-meeting'" in entry
    assert "@ROOT@" not in entry


def test_linux_with_gtk_installs_the_app_with_its_icon(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(shortcut, "_gnome_app_available", lambda root: True)
    old = tmp_path / ".local" / "share" / "applications" / "smart-meeting.desktop"
    old.parent.mkdir(parents=True)
    old.write_text("browser version")
    entry = shortcut._install_linux(ROOT)
    assert entry.name == "io.github.graffkevin.SmartMeeting.desktop"
    assert f"Exec={ROOT}/linux/smart-meeting-app" in entry.read_text()
    icon = (
        tmp_path / ".local/share/icons/hicolor/scalable/apps/io.github.graffkevin.SmartMeeting.svg"
    )
    assert icon.exists()
    assert not old.exists()  # no second "Smart Meeting" in the menu


def test_macos_app_runs_the_launcher_even_from_a_folder_with_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "mes projets" / "smart-meeting"
    root.mkdir(parents=True)
    (root / "smart-meeting").write_text("#!/bin/bash\necho lancé\n")
    (root / "smart-meeting").chmod(0o755)
    app = shortcut._install_macos(root)
    run = subprocess.run(
        [app / "Contents" / "MacOS" / "smart-meeting"], capture_output=True, text=True
    )
    assert run.stdout == "lancé\n"
    assert (
        "<key>CFBundleExecutable</key><string>smart-meeting</string>"
        in (app / "Contents" / "Info.plist").read_text()
    )
