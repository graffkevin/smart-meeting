"""The local server, started with the app and stopped when it quits. A server already answering
(`./smart-meeting --no-window`, the browser version) is used as it is and left running."""

import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from smart_meeting_gtk.api import Api, ApiError

# The project: next to this package (a clone, or /opt/smart-meeting once installed)
ROOT = Path(os.environ.get("SMART_MEETING_ROOT", Path(__file__).resolve().parents[2]))
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "smart-meeting"
LOG_FILE = STATE / "server.log"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "smart-meeting"


class ServerProcess:
    def __init__(self, api: Api) -> None:
        self.api = api
        self.process: subprocess.Popen | None = None

    def answers(self) -> bool:
        try:
            self.api.health()
        except ApiError:
            return False
        return True

    def start(self) -> None:
        """Start the server unless one answers (worker thread: the check takes a moment)."""
        if self.answers():
            return
        launcher = ROOT / "smart-meeting"
        env = dict(os.environ)
        if not os.access(ROOT / "backend", os.W_OK):
            # Installed read-only (/opt): the Python environment goes to the user's folder
            env["UV_PROJECT_ENVIRONMENT"] = str(DATA / "venv")
        STATE.mkdir(parents=True, exist_ok=True)
        log = LOG_FILE.open("ab")
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} Smart Meeting ===\n".encode())
        log.flush()
        # Login shell: PATH (uv) and the proxy settings of the user's profile, as in a terminal
        command = f"exec {_quote(launcher)} --app"
        self.process = subprocess.Popen(
            ["/bin/bash", "-lc", command],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def stop(self, timeout: float = 120) -> None:
        """Gracefully: the meeting being recorded is stopped and its transcription finished.
        Only the server this app started; blocks, call it from a worker thread."""
        process = self.process
        if process is None or process.poll() is not None:
            return
        done = threading.Event()

        def shutdown() -> None:
            try:
                self.api.shutdown()
            except ApiError:
                pass
            done.set()

        threading.Thread(target=shutdown, daemon=True).start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)

    def stop_any(self, timeout: float = 120) -> None:
        """Before restarting on a new version: also a server this app did not start, so that
        the new one takes its place. Blocks, call it from a worker thread."""
        if self.running:
            self.stop(timeout)
            return
        try:
            self.api.shutdown()
        except ApiError:
            return
        deadline = time.monotonic() + timeout
        while self.answers() and time.monotonic() < deadline:
            time.sleep(0.5)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "'\\''") + "'"


def uv_available() -> bool:
    return shutil.which("uv") is not None or (Path.home() / ".local" / "bin" / "uv").exists()
