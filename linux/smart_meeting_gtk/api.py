"""HTTP API of the local server, and the way to call it without freezing the window: requests run
in a worker thread, their result comes back on the GTK main loop."""

import json
import mimetypes
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path

from gi.repository import GLib

PORT = 8417
BASE_URL = f"http://127.0.0.1:{PORT}/"
# The AI can take minutes to answer on a computer without a large GPU
LONG_TIMEOUT_S = 1800


class ApiError(Exception):
    """A request the server refused (the message is the server's, in the interface language)."""


def background(
    work: Callable[[], object],
    done: Callable[[object], None] | None = None,
    failed: Callable[[Exception], None] | None = None,
) -> None:
    """Run `work` in a thread; `done(result)` or `failed(error)` then run on the main loop."""

    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 (any failure goes back to the window)
            if failed:
                GLib.idle_add(_once, failed, error)
            return
        if done:
            GLib.idle_add(_once, done, result)

    threading.Thread(target=run, daemon=True).start()


def _once(callback: Callable[[object], None], value: object) -> bool:
    callback(value)
    return False  # GLib: do not call again


class Api:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url
        # Never through a proxy: the server is on this computer
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(
        self,
        method: str,
        path: str,
        body: object = None,
        timeout: float = 15,
        raw: object = None,
        length: int | None = None,
        content_type: str = "application/json",
        text: bool = False,
    ):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", content_type)
        if length is not None:  # streamed body
            request.add_header("Content-Length", str(length))
        try:
            with self._opener.open(request, timeout=timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            raise ApiError(_detail(error)) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise ApiError("Smart Meeting ne répond pas") from error
        if text:
            return payload.decode()
        return json.loads(payload) if payload else None

    def events_url(self, meeting_id: int) -> str:
        return f"ws://127.0.0.1:{PORT}/api/meetings/{meeting_id}/ws"

    # Server

    def health(self) -> dict:
        return self._request("GET", "api/health", timeout=3)

    def shutdown(self) -> None:
        """Stops the server once the meeting being recorded is transcribed (can take a while)."""
        self._request("POST", "api/shutdown", timeout=LONG_TIMEOUT_S)

    def update(self, refresh: bool = False) -> dict:
        return self._request("GET", "api/update" + ("?refresh=true" if refresh else ""), timeout=30)

    def apply_update(self) -> dict:
        """Download and install the new version (the system asks for the password)."""
        return self._request("POST", "api/update", timeout=LONG_TIMEOUT_S)

    def restart_ai(self) -> None:
        self._request("POST", "api/ai/restart")

    # Settings

    def preferences(self) -> dict:
        return self._request("GET", "api/preferences")

    def save_preferences(self, preferences: dict) -> dict:
        return self._request("PUT", "api/preferences", preferences)

    def devices(self) -> dict:
        return self._request("GET", "api/audio/devices")

    def tags(self) -> list[dict]:
        return self._request("GET", "api/tags")

    def recent_questions(self) -> list[str]:
        return self._request("GET", "api/questions/recent")

    # Meetings

    def meetings(self, search: str = "") -> list[dict]:
        query = urllib.parse.urlencode({"q": search}) if search else ""
        return self._request("GET", "api/meetings" + (f"?{query}" if query else ""))

    def meeting(self, meeting_id: int) -> dict:
        return self._request("GET", f"api/meetings/{meeting_id}")

    def report(self, meeting_id: int) -> str:
        return self._request("GET", f"api/meetings/{meeting_id}/report.md", text=True)

    def start_meeting(self, request: dict) -> dict:
        return self._request("POST", "api/meetings", request, timeout=60)

    def stop_meeting(self, meeting_id: int) -> dict:
        return self._request("POST", f"api/meetings/{meeting_id}/stop", timeout=60)

    def analyze(self, meeting_id: int) -> None:
        self._request("POST", f"api/meetings/{meeting_id}/analyze")

    def ask(self, meeting_id: int, question: str) -> dict:
        path = f"api/meetings/{meeting_id}/ask"
        return self._request("POST", path, {"question": question}, timeout=LONG_TIMEOUT_S)

    def rename(self, meeting_id: int, title: str) -> dict:
        return self._request("PATCH", f"api/meetings/{meeting_id}", {"title": title})

    def set_tags(self, meeting_id: int, tags: list[str]) -> dict:
        return self._request("PUT", f"api/meetings/{meeting_id}/tags", {"tags": tags})

    def rename_speaker(self, meeting_id: int, old: str, new: str) -> None:
        self._request("PUT", f"api/meetings/{meeting_id}/speakers", {"old": old, "new": new})

    def delete_meeting(self, meeting_id: int) -> None:
        self._request("DELETE", f"api/meetings/{meeting_id}")

    def delete_audio(self, meeting_id: int) -> None:
        self._request("DELETE", f"api/meetings/{meeting_id}/audio")

    def import_file(self, path: Path, title: str, language: str) -> dict:
        boundary = uuid.uuid4().hex
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts = []
        for name, value in (("title", title), ("language", language)):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{path.name}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
        )
        head, tail = b"".join(parts), f"\r\n--{boundary}--\r\n".encode()

        def body():  # streamed: a video can weigh gigabytes
            yield head
            with path.open("rb") as file:
                while chunk := file.read(1024 * 1024):
                    yield chunk
            yield tail

        return self._request(
            "POST",
            "api/meetings/import",
            raw=body(),
            length=len(head) + path.stat().st_size + len(tail),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=600,
        )


def _detail(error: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(error.read()).get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # validation errors
        detail = "; ".join(str(item.get("msg", item)) for item in detail)
    return str(detail or f"Erreur du serveur ({error.code})")
