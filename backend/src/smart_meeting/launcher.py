"""`smart-meeting` command: check the system, build the UI if needed, start the local server
and open the app. Same behavior on Linux, macOS and Windows."""

import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx

from smart_meeting.config import get_settings

logger = logging.getLogger("smart_meeting.launcher")


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


def check_system() -> None:
    """Fail early, with the fix, when the OS lacks something we cannot install ourselves."""
    if sys.platform.startswith("linux"):
        missing = [tool for tool in ("pw-record", "pw-dump") if not shutil.which(tool)]
        if missing:
            fail(
                "PipeWire est requis (Ubuntu 22.10+). Installez-le : sudo apt install pipewire-bin"
            )
    elif sys.platform == "darwin":
        version = tuple(int(x) for x in (platform.mac_ver()[0] or "0").split(".")[:1])
        if version < (13,):
            fail("macOS 13 (Ventura) ou plus récent est requis pour capturer l'audio système.")


def build_frontend_if_needed(frontend: Path) -> None:
    """Build the UI on first run and whenever its sources changed since the last build."""
    index = frontend / "dist" / "index.html"
    sources = [frontend / "package.json", *(frontend / "src").rglob("*")]
    if index.exists() and all(p.stat().st_mtime <= index.stat().st_mtime for p in sources):
        return
    npm = shutil.which("npm")
    if not npm:
        fail(f"Node.js est requis pour construire l'interface : {NODE_HINTS.get(sys.platform, '')}")
    logger.info("Building the interface…")
    for command in ([npm, "ci", "--no-audit", "--no-fund"], [npm, "run", "build"]):
        if subprocess.run(command, cwd=frontend).returncode != 0:
            fail("Construction de l'interface impossible (voir les messages ci-dessus).")


NODE_HINTS = {
    "linux": "sudo apt install nodejs npm",
    "darwin": "brew install node (ou https://nodejs.org)",
    "win32": "winget install OpenJS.NodeJS.LTS (ou https://nodejs.org)",
}


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

    url = f"http://127.0.0.1:{args.port}/"
    owner = _port_owner(url)
    if owner == "smart-meeting":
        logger.info("Already running at %s", url)
        if not args.no_window:
            open_unless_already_open(url)
        return
    if owner == "other":
        raise SystemExit(
            f"Port {args.port} is used by another application. "
            "Choose another one with --port or SM_PORT."
        )

    from smart_meeting.main import FRONTEND_DIST

    check_system()
    build_frontend_if_needed(FRONTEND_DIST.parent)

    def open_when_ready() -> None:
        for _ in range(100):
            if _port_owner(url) == "smart-meeting":
                # Leave time for a page left open from a previous run to reconnect.
                open_unless_already_open(url, wait_s=5)
                return
            time.sleep(0.2)

    if not args.no_window:
        threading.Thread(target=open_when_ready, daemon=True).start()

    import uvicorn

    from smart_meeting.main import app

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # Loopback only: the API exposes meeting content.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port))
    # Quit button: on Windows a signal would kill the process without a graceful shutdown.
    app.state.request_exit = lambda: setattr(server, "should_exit", True)
    server.run()
