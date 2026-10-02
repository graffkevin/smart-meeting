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
import zipfile
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
        fail(f"Bun n'est pas disponible pour {sys.platform} {platform.machine()}")
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
        fail(
            f"Téléchargement de Bun impossible ({exc}). Derrière un proxy, vérifiez HTTPS_PROXY ;"
            " sinon installez Bun à la main : https://bun.sh"
        )
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
        fail(f"Bun a été installé dans {local} mais ne démarre pas sur cette machine.")
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
            fail("Construction de l'interface impossible (voir les messages ci-dessus).")


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
    app.state.stop_when_unused = app.state.request_exit
    server.run()
