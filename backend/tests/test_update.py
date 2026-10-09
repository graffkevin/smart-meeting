"""Updates: the latest release on GitHub, compared with this version, installed the way this
installation was made. GitHub is replaced by a mock transport."""

import asyncio
import functools
import hashlib

import httpx
import pytest

from smart_meeting import update
from smart_meeting.config import Settings

PACKAGE = b"deb package"


def release(tag="v9.0.0", digest=None):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/graffkevin/smart-meeting/releases/tag/{tag}",
        "body": "Nouveautés",
        "assets": [
            {
                "name": f"smart-meeting_{tag[1:]}_all.deb",
                "browser_download_url": "https://github.com/download/package.deb",
                "digest": digest or f"sha256:{hashlib.sha256(PACKAGE).hexdigest()}",
            }
        ],
    }


@pytest.fixture
def github(monkeypatch):
    """Answers of GitHub; returns the list of requested URLs."""
    state = {"release": release(), "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(str(request.url))
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json=state["release"])
        return httpx.Response(200, content=PACKAGE)

    client = functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(update.httpx, "AsyncClient", client)
    return state


def updater(tmp_path, method="git") -> update.Updater:
    u = update.Updater(Settings(data_dir=tmp_path), root=tmp_path)
    u.method, u.current = method, "0.2.2"
    return u


def test_versions_compare_as_numbers():
    assert update.version_key("v0.2.10") > update.version_key("0.2.9")
    assert update.version_key("0.3.0") > update.version_key("0.2.22")


def test_a_newer_release_is_offered(tmp_path, github):
    info = asyncio.run(updater(tmp_path).check())
    assert (info.current, info.latest, info.available) == ("0.2.2", "9.0.0", True)
    assert info.url.endswith("/v9.0.0")


def test_the_same_version_is_not_offered(tmp_path, github):
    github["release"] = release("v0.2.2")
    assert not asyncio.run(updater(tmp_path).check()).available


def test_offline_nothing_is_offered(tmp_path, monkeypatch):
    def offline(request):
        raise httpx.ConnectError("no network")

    client = functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(offline))
    monkeypatch.setattr(update.httpx, "AsyncClient", client)
    info = asyncio.run(updater(tmp_path).check())
    assert info.latest is None and not info.available


def test_a_clone_pulls(tmp_path, github):
    u = updater(tmp_path, "git")
    commands = []

    async def run(*command):
        commands.append(command)

    u._run = run
    asyncio.run(u.check())
    asyncio.run(u.apply())
    assert commands == [("git", "-C", str(tmp_path), "pull", "--ff-only")]


def test_the_package_is_downloaded_checked_and_installed(tmp_path, github):
    u = updater(tmp_path, "deb")
    commands = []

    async def run(*command):
        commands.append(command)

    u._run = run
    asyncio.run(u.check())
    asyncio.run(u.apply())
    package = tmp_path / "updates" / "smart-meeting_9.0.0_all.deb"
    assert package.read_bytes() == PACKAGE
    assert commands == [("pkexec", "apt-get", "install", "-y", str(package))]


def test_a_corrupted_package_is_not_installed(tmp_path, github):
    github["release"] = release(digest="sha256:" + "0" * 64)
    u = updater(tmp_path, "deb")
    u._run = None  # never reached
    asyncio.run(u.check())
    with pytest.raises(update.UpdateError, match="SHA-256"):
        asyncio.run(u.apply())
    assert not list((tmp_path / "updates").iterdir())
    assert u.info().error and not u.info().updating


def test_the_macos_app_is_downloaded_by_hand(tmp_path, github):
    u = updater(tmp_path, "download")
    asyncio.run(u.check())
    with pytest.raises(update.UpdateError):
        asyncio.run(u.apply())


def test_how_this_installation_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/usr/bin/{name}")
    (tmp_path / ".git").mkdir()
    assert update.install_method(tmp_path) == "git"
    assert update.install_method(update.INSTALLED_ROOT) == "deb"
    monkeypatch.setattr(update.sys, "frozen", True, raising=False)
    assert update.install_method(tmp_path) == "download"
