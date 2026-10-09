"""Smart Meeting for Windows: the app window on the local server.

The window shows the web interface in Edge WebView2 (through pywebview, part of Windows 10 and 11).
The server is the same executable started hidden (`--server`), and stops with the window: a
meeting being recorded is then stopped and its transcription finished. A server already answering
(the browser version, `smart-meeting.cmd`) is used as it is and left running.
"""

import ctypes
import html
import json
import subprocess
import sys
import threading
import time
import urllib.request

from smart_meeting.config import get_settings
from smart_meeting.launcher import write_starting_page
from smart_meeting.messages import tr
from smart_meeting.preferences import PreferencesStore

CREATE_NO_WINDOW = 0x08000000
MB_OKCANCEL, MB_ICONWARNING, IDOK = 0x1, 0x30, 1
# Long enough for the transcription of a meeting stopped by the closing of the window
STOP_TIMEOUT_S = 180
# Never through the proxy of the system: the server is on this computer
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(url: str, method: str = "GET", timeout: float = 2) -> dict | None:
    try:
        with _opener.open(urllib.request.Request(url, method=method), timeout=timeout) as reply:
            body = reply.read()
            return json.loads(body) if body else {}
    except (OSError, ValueError):
        return None


def _start_server(port: int) -> subprocess.Popen:
    # The same executable, without a window; its output goes to its log (data folder)
    return subprocess.Popen(
        [sys.executable, "--server", "--app", "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def _stop_server(url: str, process: subprocess.Popen) -> None:
    _request(url + "api/shutdown", method="POST", timeout=10)
    try:
        process.wait(timeout=STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> None:
    import webview

    settings = get_settings()
    PreferencesStore(settings)  # messages in the language chosen in the interface
    url = f"http://127.0.0.1:{settings.port}/"
    process = None if _request(url + "api/health") is not None else _start_server(settings.port)

    # The starting page waits for the server, then opens the interface
    window = webview.create_window(
        "Smart Meeting",
        write_starting_page(url, settings.data_dir).as_uri(),
        width=1280,
        height=840,
        min_size=(900, 600),
        text_select=True,
    )

    def watch_server() -> None:
        # Stopped before answering (a missing library, a port taken): say so, with the log
        while process is not None and process.poll() is None:
            if _request(url + "api/health") is not None:
                return
            time.sleep(1)
        if process is not None:
            message = tr("app_server_failed", log=settings.data_dir / "server.log")
            window.load_html(f"<p style='font-family: sans-serif'>{html.escape(message)}</p>")

    def closing() -> bool:
        """False keeps the window open (a meeting being recorded, and the user changed mind)."""
        health = _request(url + "api/health")
        if process is None or not health or health.get("active_meeting_id") is None:
            return True
        answer = ctypes.windll.user32.MessageBoxW(
            0, tr("app_quit_while_recording"), "Smart Meeting", MB_OKCANCEL | MB_ICONWARNING
        )
        return answer == IDOK

    window.events.closing += closing
    threading.Thread(target=watch_server, daemon=True).start()
    # The interface keeps its settings (language, layout) between launches
    webview.start(private_mode=False, storage_path=str(settings.data_dir / "webview"))
    if process is not None:
        _stop_server(url, process)
