"""`smart-meeting` command: start everything locally and open the app window."""

import argparse
import ctypes
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

import httpx

from smart_meeting.config import get_settings

logger = logging.getLogger("smart_meeting.launcher")

APP_MODE_BROWSERS = ["google-chrome", "chromium", "chromium-browser", "microsoft-edge"]


def _reachable(url: str) -> bool:
    try:
        return httpx.get(url, timeout=1, trust_env=False).is_success
    except httpx.HTTPError:
        return False


def open_window(url: str) -> None:
    """A dedicated app window when a Chromium-based browser exists, else a browser tab."""
    for browser in APP_MODE_BROWSERS:
        if path := shutil.which(browser):
            subprocess.Popen(
                [path, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return
    if path := shutil.which("firefox"):
        subprocess.Popen(
            [path, "--new-window", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return
    webbrowser.open_new(url)


def _die_with_parent() -> None:
    """Runs in the child: Linux kills it when the launcher exits, even on SIGKILL."""
    pr_set_pdeathsig = 1
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(pr_set_pdeathsig, signal.SIGTERM)


def start_ollama_if_needed() -> subprocess.Popen | None:
    """Start `ollama serve` when it is installed but not running (no system service)."""
    settings = get_settings()
    if _reachable(f"{settings.ollama_url}/api/version"):
        return None
    binary = settings.ollama_bin or shutil.which("ollama")
    if not binary or not Path(binary).exists():
        logger.warning("Ollama not found: AI analysis will be unavailable")
        return None
    log = settings.data_dir / "ollama.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Starting %s serve (log: %s)", binary, log)
    with log.open("ab") as output:
        return subprocess.Popen(
            [binary, "serve"],
            stdout=output,
            stderr=subprocess.STDOUT,
            preexec_fn=_die_with_parent,
        )


def run() -> None:
    parser = argparse.ArgumentParser(description="Local meeting transcription and analysis")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-window", action="store_true", help="do not open the app window")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    url = f"http://127.0.0.1:{args.port}/"
    if _reachable(f"{url}api/health"):
        logger.info("Already running: opening %s", url)
        if not args.no_window:
            open_window(url)
        return

    from smart_meeting.main import FRONTEND_DIST

    if not FRONTEND_DIST.is_dir():
        raise SystemExit("Frontend not built: run `make build` at the repository root.")

    ollama = start_ollama_if_needed()

    def open_when_ready() -> None:
        for _ in range(100):
            if _reachable(f"{url}api/health"):
                open_window(url)
                return
            time.sleep(0.2)

    if not args.no_window:
        threading.Thread(target=open_when_ready, daemon=True).start()

    import uvicorn

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        # Loopback only: the API exposes meeting content.
        uvicorn.run("smart_meeting.main:app", host="127.0.0.1", port=args.port)
    finally:
        if ollama:
            ollama.terminate()
