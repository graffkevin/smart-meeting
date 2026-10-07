"""`smart-meeting` command: check the system, build the UI if needed, start the local server
and open the app. Same behavior on Linux, macOS and Windows."""

import argparse
import html
import logging
import os
import platform
import shutil
import signal
import socket
import string
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from pathlib import Path

import httpx

from smart_meeting.config import get_settings
from smart_meeting.messages import tr
from smart_meeting.preferences import PreferencesStore
from smart_meeting.watchdog import STALL_S, page_marker_path, pid_path, traces_path

logger = logging.getLogger("smart_meeting.launcher")

# A page left open retries every 2 s (PRESENCE_RETRY_MS in the frontend): enough to see it back.
RECONNECT_WAIT_S = 3


def _health(url: str) -> dict | None:
    try:
        return httpx.get(f"{url}api/health", timeout=1, trust_env=False).json()
    except (httpx.HTTPError, ValueError):
        return None


def _port_owner(url: str) -> str | None:
    """'smart-meeting' if our server answers at url, 'other' if something else does."""
    try:
        response = httpx.get(f"{url}api/health", timeout=1, trust_env=False)
    except httpx.HTTPError:
        return None
    try:
        is_ours = "whisper" in response.json() and "ollama_model" in response.json()
    except ValueError:
        is_ours = False
    return "smart-meeting" if is_ours else "other"


def bind_port(port: int) -> socket.socket | None:
    """The server's socket, bound before anything else starts: a second launch never gets past
    this point, so it cannot touch the meetings of the running server. None if the port is taken."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":  # on Windows this option would let two servers share the port
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        return None
    return sock


def _is_our_server(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    cmdline = Path(f"/proc/{pid}/cmdline")
    if not cmdline.exists():  # no /proc (macOS, Windows): trust the pid file
        return True
    return b"smart-meeting" in cmdline.read_bytes() or b"smart_meeting" in cmdline.read_bytes()


def replace_frozen_server(url: str, port: int) -> socket.socket | None:
    """Our port is taken but nothing answers: wait in case the server is only busy, then stop it
    (its meetings are kept, the one being recorded is closed with what was transcribed).
    None if it answers again meanwhile."""
    deadline = time.monotonic() + STALL_S + 5  # the frozen server writes its stacks first
    while time.monotonic() < deadline:
        if _port_owner(url) is not None:
            return None
        if sock := bind_port(port):
            return sock
        time.sleep(1)
    pid_file = pid_path(get_settings().data_dir)
    try:
        pid = int(pid_file.read_text())
    except (OSError, ValueError):
        pid = None
    if pid is None or not _is_our_server(pid):
        fail(tr("port_unresponsive", port=port))
    logger.warning(
        "Smart Meeting (pid %s) no longer responds: restarting it. Stacks in %s",
        pid, traces_path(get_settings().data_dir),
    )  # fmt: skip
    # SIGKILL: a frozen event loop never runs the SIGTERM handler. TerminateProcess on Windows.
    os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)
    for _ in range(50):
        if sock := bind_port(port):
            pid_file.unlink(missing_ok=True)
            return sock
        time.sleep(0.2)
    fail(tr("port_unresponsive", port=port))
    return None


def open_window(url: str) -> None:
    """Open the app as a new tab of the user's default browser (in its existing window)."""
    webbrowser.open_new_tab(url)


def open_unless_already_open(url: str, wait_s: float = 0) -> None:
    """Reuse an open page: pages poll the server every 2 s (and reload themselves when it comes
    back after a restart), so only open a tab when none shows up within `wait_s`."""
    deadline = time.monotonic() + wait_s
    while True:
        if (_health(url) or {}).get("ui_open"):
            logger.info("Smart Meeting is already open in the browser")
            return
        if time.monotonic() >= deadline:
            open_window(url)
            return
        time.sleep(0.5)


def write_starting_page(url: str, data_dir: Path) -> Path:
    """The page shown while the server starts, in the interface language: it goes to the app as
    soon as the server answers."""
    source = Path(__file__).parent / "starting.html"
    template = string.Template(source.read_text(encoding="utf-8"))
    page = data_dir / "starting.html"
    data_dir.mkdir(parents=True, exist_ok=True)
    page.write_text(
        template.safe_substitute(
            lang=get_settings().ui_language,
            url=url,
            title=html.escape(tr("starting_title")),
            detail=html.escape(tr("starting_detail")),
            slow=html.escape(tr("starting_slow")),
        ),
        encoding="utf-8",
    )
    return page


def check_system() -> None:
    """Fail early, with the fix, when the OS lacks something we cannot install ourselves."""
    if sys.platform.startswith("linux"):
        missing = [tool for tool in ("pw-record", "pw-dump") if not shutil.which(tool)]
        if missing:
            fail(tr("pipewire_missing"))
    elif sys.platform == "darwin":
        version = tuple(int(x) for x in (platform.mac_ver()[0] or "0").split(".")[:1])
        if version < (13,):
            fail(tr("macos_too_old"))


BUN_RELEASES = "https://github.com/oven-sh/bun/releases/latest/download"
# "baseline" builds run on every x86-64 CPU (the others need AVX2: "Illegal instruction").
BUN_VARIANTS = {
    ("linux", "x86_64"): "linux-x64-baseline",
    ("linux", "aarch64"): "linux-aarch64",
    ("darwin", "arm64"): "darwin-aarch64",
    ("darwin", "x86_64"): "darwin-x64-baseline",
    ("win32", "amd64"): "windows-x64-baseline",
}


def _bun_works(path: str) -> bool:
    try:
        return subprocess.run([path, "--version"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_bun(target: Path) -> None:
    """Download the official Bun build for this machine and unzip it in Python: no curl, no
    unzip, no AVX2 needed, and the download goes through the proxy of the environment."""
    platform_name = "linux" if sys.platform.startswith("linux") else sys.platform
    variant = BUN_VARIANTS.get((platform_name, platform.machine().lower()))
    if variant is None:
        fail(tr("bun_unavailable", system=f"{sys.platform} {platform.machine()}"))
    url = f"{BUN_RELEASES}/bun-{variant}.zip"
    logger.info("Installing Bun from %s", url)
    archive = target.parent / "bun-download.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            httpx.stream("GET", url, follow_redirects=True, timeout=120) as response,
            archive.open("wb") as out,
        ):
            response.raise_for_status()
            for chunk in response.iter_bytes():
                out.write(chunk)
        with zipfile.ZipFile(archive) as zipped:
            member = next(n for n in zipped.namelist() if n.rsplit("/", 1)[-1] == target.name)
            target.write_bytes(zipped.read(member))
    except (httpx.HTTPError, OSError, zipfile.BadZipFile, StopIteration) as exc:
        fail(tr("bun_download_failed", error=exc))
    finally:
        archive.unlink(missing_ok=True)
    target.chmod(0o755)


def ensure_bun() -> str:
    """Bun builds the interface; installed for the user (no admin rights) when missing or broken."""
    local = Path.home() / ".bun" / "bin" / ("bun.exe" if sys.platform == "win32" else "bun")
    for candidate in (shutil.which("bun"), str(local) if local.exists() else None):
        if candidate and _bun_works(candidate):
            return candidate
    install_bun(local)
    if not _bun_works(str(local)):
        fail(tr("bun_not_starting", path=local))
    return str(local)


def build_frontend_if_needed(frontend: Path) -> None:
    """Build the UI on first run and whenever its sources changed since the last build."""
    index = frontend / "dist" / "index.html"
    sources = [
        frontend / "package.json",
        frontend / "bun.lock",
        frontend / "index.html",
        *(frontend / "src").rglob("*"),
        *(frontend / "public").rglob("*"),
    ]
    if index.exists() and all(p.stat().st_mtime <= index.stat().st_mtime for p in sources):
        return
    bun = ensure_bun()
    # The package scripts call `bun` by name: a freshly installed one is not on the PATH yet.
    env = {**os.environ, "PATH": str(Path(bun).parent) + os.pathsep + os.environ.get("PATH", "")}
    logger.info("Building the interface…")
    for command in ([bun, "install", "--frozen-lockfile"], [bun, "run", "build"]):
        if subprocess.run(command, cwd=frontend, env=env).returncode != 0:
            fail(tr("build_failed"))


def fail(message: str) -> None:
    """Report an error visibly, even when started from a desktop shortcut without a terminal."""
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.run(["notify-send", "-i", "dialog-error", "Smart Meeting", message])
    raise SystemExit(f"Smart Meeting : {message}")


def run() -> None:
    parser = argparse.ArgumentParser(description="Local meeting transcription and analysis")
    parser.add_argument("--port", type=int, default=get_settings().port)
    parser.add_argument("--no-window", action="store_true", help="do not open the app window")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Messages in the language chosen in the interface (saved preferences)
    PreferencesStore(get_settings())

    url = f"http://127.0.0.1:{args.port}/"
    owner = _port_owner(url)
    if owner == "other":
        raise SystemExit(tr("port_taken", port=args.port))
    sock = None if owner else bind_port(args.port) or replace_frozen_server(url, args.port)
    if sock is None:
        logger.info("Already running at %s", url)
        # Asked for explicitly: show a page even if one is open, maybe hidden in another window.
        if not args.no_window:
            open_window(url)
        return

    from smart_meeting.main import FRONTEND_DIST

    data_dir = get_settings().data_dir
    page_left_open = page_marker_path(data_dir).exists()
    # No page to come back: show one at once, it waits for the server (the build can take a while).
    if not args.no_window and not page_left_open:
        open_window(write_starting_page(url, data_dir).as_uri())

    check_system()
    build_frontend_if_needed(FRONTEND_DIST.parent)

    def open_when_ready() -> None:
        for _ in range(100):
            if _port_owner(url) == "smart-meeting":
                open_unless_already_open(url, wait_s=RECONNECT_WAIT_S)
                return
            time.sleep(0.2)

    if not args.no_window and page_left_open:
        threading.Thread(target=open_when_ready, daemon=True).start()

    import uvicorn

    from smart_meeting.main import app

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # Loopback only: the API exposes meeting content.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port))
    # Quit button: on Windows a signal would kill the process without a graceful shutdown.
    app.state.request_exit = lambda: setattr(server, "should_exit", True)

    def stop_unused() -> None:
        # No page left: the next launch opens one at once instead of waiting for it.
        page_marker_path(data_dir).unlink(missing_ok=True)
        app.state.request_exit()

    app.state.stop_when_unused = stop_unused
    server.run(sockets=[sock])
