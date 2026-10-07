import subprocess
from pathlib import Path

from smart_meeting import shortcut

ROOT = Path(__file__).resolve().parents[2]


def test_linux_entry_runs_the_launcher_of_the_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    entry = shortcut._install_linux(ROOT).read_text()
    assert f"Exec=/bin/bash -lc '{ROOT}/smart-meeting'" in entry
    assert "@ROOT@" not in entry


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
