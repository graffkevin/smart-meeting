import io
import tarfile
import zipfile

import pytest
import zstandard

from smart_meeting import provision


def make_tar(path, compress):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("bin/ollama")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"exec"))
    path.write_bytes(compress(buffer.getvalue()))


@pytest.mark.parametrize("name", ["o.tar.zst", "o.tgz", "o.zip"])
def test_extract_supported_archives(tmp_path, name):
    archive = tmp_path / name
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("bin/ollama", b"exec")
    elif name.endswith(".tar.zst"):
        make_tar(archive, zstandard.ZstdCompressor().compress)
    else:
        import gzip

        make_tar(archive, gzip.compress)
    provision._extract(archive, tmp_path / "out")
    assert (tmp_path / "out" / "bin" / "ollama").read_bytes() == b"exec"


@pytest.mark.parametrize(
    ("platform_name", "machine", "expected"),
    [
        ("linux", "x86_64", "ollama-linux-amd64.tar.zst"),
        ("linux", "aarch64", "ollama-linux-arm64.tar.zst"),
        ("darwin", "arm64", "ollama-darwin.tgz"),
        ("win32", "AMD64", "ollama-windows-amd64.zip"),
    ],
)
def test_download_url_per_platform(monkeypatch, platform_name, machine, expected):
    monkeypatch.setattr(provision.sys, "platform", platform_name)
    monkeypatch.setattr(provision.platform, "machine", lambda: machine)
    assert provision._download_url().endswith(expected)


def test_ensure_running_restarts_a_stopped_ollama(tmp_path, monkeypatch):
    import asyncio

    from smart_meeting.config import Settings

    started = []
    provisioner = provision.OllamaProvisioner(Settings(data_dir=tmp_path))
    answers = iter([False])

    async def reachable():
        return next(answers, True)

    async def start(binary):
        started.append(binary)

    monkeypatch.setattr(provisioner, "_reachable", reachable)
    monkeypatch.setattr(provisioner, "_find_binary", lambda: "/opt/ollama")
    monkeypatch.setattr(provisioner, "_start", start)
    asyncio.run(provisioner.ensure_running())  # stopped: restarted
    asyncio.run(provisioner.ensure_running())  # answering: left alone
    assert started == ["/opt/ollama"]
