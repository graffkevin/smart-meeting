"""`smart-meeting` command: start everything locally and open the app window."""

import argparse
import logging
import os
import shutil
import subprocess
import threading
import time
import webbrowser

import httpx

from smart_meeting.config import get_settings

logger = logging.getLogger("smart_meeting.launcher")

APP_MODE_BROWSERS = ["google-chrome", "chromium", "chromium-browser", "microsoft-edge"]


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


def run() -> None:
    parser = argparse.ArgumentParser(description="Local meeting transcription and analysis")
    parser.add_argument("--port", type=int, default=get_settings().port)
    parser.add_argument("--no-window", action="store_true", help="do not open the app window")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    url = f"http://127.0.0.1:{args.port}/"
    owner = _port_owner(url)
    if owner == "smart-meeting":
        logger.info("Already running: opening %s", url)
        if not args.no_window:
            open_window(url)
        return
    if owner == "other":
        raise SystemExit(
            f"Port {args.port} is used by another application. "
            "Choose another one with --port or SM_PORT."
        )

    from smart_meeting.main import FRONTEND_DIST

    if not FRONTEND_DIST.is_dir():
        raise SystemExit("Frontend not built: run ./smart-meeting (or `make build`).")

    def open_when_ready() -> None:
        for _ in range(100):
            if _port_owner(url) == "smart-meeting":
                open_window(url)
                return
            time.sleep(0.2)

    if not args.no_window:
        threading.Thread(target=open_when_ready, daemon=True).start()

    import uvicorn

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # Loopback only: the API exposes meeting content.
    uvicorn.run("smart_meeting.main:app", host="127.0.0.1", port=args.port)
