"""Updates: the latest release published on GitHub, and how this installation gets it.

- a clone of the repository: `git pull`;
- the Linux package (/opt/smart-meeting): the new .deb, installed after the system asks for the
  password (pkexec);
- the macOS app, or anything else: the page of the release, to download it.

The check only reads the public list of releases: nothing about the meetings is sent. The update
itself needs the server to restart: the server does it in the browser version, the desktop app
restarts itself and its server.
"""

import asyncio
import hashlib
import importlib.metadata
import logging
import re
import shutil
import sys
import time
from pathlib import Path

import httpx

from smart_meeting.config import Settings
from smart_meeting.messages import tr
from smart_meeting.models import UpdateInfo

logger = logging.getLogger(__name__)

REPOSITORY = "graffkevin/smart-meeting"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
CHECK_EVERY_S = 6 * 3600
# The project: a clone, or /opt/smart-meeting once installed from the package
ROOT = Path(__file__).resolve().parents[3]
INSTALLED_ROOT = Path("/opt/smart-meeting")


def install_method(root: Path = ROOT) -> str:
    if getattr(sys, "frozen", False):  # macOS app: a new disk image
        return "download"
    if (root / ".git").exists() and shutil.which("git"):
        return "git"
    if root == INSTALLED_ROOT and shutil.which("pkexec") and shutil.which("apt-get"):
        return "deb"
    return "download"


def version_key(version: str) -> tuple[int, ...]:
    """'v0.2.10' -> (0, 2, 10): compared as numbers, not as text."""
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def current_version() -> str:
    try:
        return importlib.metadata.version("smart-meeting")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


class Updater:
    def __init__(self, settings: Settings, root: Path = ROOT) -> None:
        self.settings = settings
        self.root = root
        self.method = install_method(root)
        self.current = current_version()
        self.latest: dict | None = None  # the release, as GitHub describes it
        self.checked_at = -float("inf")
        self.updating = False
        self.error: str | None = None
        self._check_lock = asyncio.Lock()

    def info(self) -> UpdateInfo:
        release = self.latest or {}
        latest = (release.get("tag_name") or "").removeprefix("v") or None
        return UpdateInfo(
            current=self.current,
            latest=latest,
            available=latest is not None and version_key(latest) > version_key(self.current),
            method=self.method,
            url=release.get("html_url"),
            notes=release.get("body"),
            updating=self.updating,
            error=self.error,
        )

    async def check(self, force: bool = False) -> UpdateInfo:
        """The latest release, read again every few hours (or when asked)."""
        async with self._check_lock:
            if force or time.monotonic() - self.checked_at > CHECK_EVERY_S:
                try:
                    # trust_env: through the proxy of the system, like the other downloads
                    async with httpx.AsyncClient(timeout=15, trust_env=True) as client:
                        response = await client.get(
                            LATEST_URL, headers={"Accept": "application/vnd.github+json"}
                        )
                        response.raise_for_status()
                    self.latest = response.json()
                    self.checked_at = time.monotonic()
                except (httpx.HTTPError, ValueError) as exc:
                    # Offline, or GitHub unreachable: asked again at the next check
                    logger.info("Could not check for updates: %s", exc)
        return self.info()

    async def apply(self) -> None:
        """Install the latest release; the caller restarts afterwards."""
        if self.updating:
            raise UpdateError(tr("update_in_progress"))
        self.updating, self.error = True, None
        try:
            if self.method == "git":
                await self._run("git", "-C", str(self.root), "pull", "--ff-only")
            elif self.method == "deb":
                package = await self._download_package()
                # The system asks for the password of an administrator
                await self._run("pkexec", "apt-get", "install", "-y", str(package))
            else:
                raise UpdateError(tr("update_download"))
        except UpdateError as exc:
            self.error = str(exc)
            raise
        finally:
            self.updating = False
        logger.info("Updated to %s", self.info().latest)

    async def _download_package(self) -> Path:
        release = self.latest or {}
        asset = next(
            (a for a in release.get("assets", []) if a.get("name", "").endswith("_all.deb")), None
        )
        if asset is None:
            raise UpdateError(tr("update_no_package"))
        folder = self.settings.data_dir / "updates"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / asset["name"]
        digest = hashlib.sha256()
        try:
            async with (
                httpx.AsyncClient(timeout=60, trust_env=True, follow_redirects=True) as client,
                client.stream("GET", asset["browser_download_url"]) as response,
            ):
                response.raise_for_status()
                with path.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        file.write(chunk)
                        digest.update(chunk)
        except httpx.HTTPError as exc:
            raise UpdateError(tr("update_failed", error=str(exc))) from exc
        expected = (asset.get("digest") or "").removeprefix("sha256:")
        if expected and expected != digest.hexdigest():
            path.unlink(missing_ok=True)
            raise UpdateError(tr("update_failed", error="SHA-256"))
        return path

    async def _run(self, *command: str) -> None:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        output, _ = await process.communicate()
        if process.returncode in (126, 127) and command[0] == "pkexec":
            raise UpdateError(tr("update_cancelled"))
        if process.returncode != 0:
            text = output.decode(errors="replace").strip().splitlines()
            logger.warning("Update failed: %s", "\n".join(text[-20:]))
            raise UpdateError(tr("update_failed", error=text[-1] if text else process.returncode))


class UpdateError(Exception):
    pass
