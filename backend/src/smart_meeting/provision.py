"""First-run provisioning of Ollama and its model, without sudo, with progress for the UI.

- Ollama: an existing install (PATH, SM_OLLAMA_BIN, desktop app, system service) is used as
  is. Otherwise the official standalone build for the OS is extracted to a per-user directory
  (~/.local/opt/ollama on Linux).
- Ollama is started as a child process when it is not already running, and stopped with us.
- Model: when we manage Ollama, blobs are fetched from the Ollama registry by our own
  resumable downloader (`ollama pull` stalls behind some corporate proxies); with a system
  Ollama, `/api/pull` is used since its model directory is not ours.

Downloads use the environment proxy settings. They only fetch software and model weights:
no meeting data is involved.
"""

import asyncio
import ctypes
import hashlib
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import zstandard
from platformdirs import user_data_path

from smart_meeting.config import Settings

logger = logging.getLogger(__name__)

REGISTRY = "https://registry.ollama.ai"
MANIFEST_TYPE = "application/vnd.docker.distribution.manifest.v2+json"
LOCAL_OLLAMA_DIR = (
    Path.home() / ".local" / "opt" / "ollama"
    if sys.platform.startswith("linux")
    else user_data_path("smart-meeting", appauthor=False) / "ollama"
)
BINARY_NAME = "ollama.exe" if sys.platform == "win32" else "ollama"
# Desktop app installs, checked before downloading anything.
KNOWN_INSTALLS = [
    Path("/Applications/Ollama.app/Contents/Resources/ollama"),
    Path(os.environ.get("LOCALAPPDATA", "~")) / "Programs" / "Ollama" / "ollama.exe",
]
CHUNK = 1024 * 1024


@dataclass
class SetupStep:
    label: str
    progress: float | None = None  # 0..1, None when unknown
    error: str | None = None
    done: bool = False


def _die_with_parent() -> None:
    """Runs in the child: Linux kills it when its parent exits, even on SIGKILL."""
    pr_set_pdeathsig = 1
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(pr_set_pdeathsig, signal.SIGTERM)


def _download_url() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if sys.platform == "darwin":
        return "https://ollama.com/download/ollama-darwin.tgz"  # universal binary
    if not arch:
        raise RuntimeError(f"Architecture non prise en charge : {platform.machine()}")
    if sys.platform == "win32":
        return f"https://ollama.com/download/ollama-windows-{arch}.zip"
    return f"https://ollama.com/download/ollama-linux-{arch}.tar.zst"


def _extract(archive: Path, target: Path) -> None:
    """Extract a .tar.zst, .tgz or .zip archive (pure Python: no zstd/tar tools needed)."""
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(target)
    elif archive.name.endswith(".tar.zst"):
        with archive.open("rb") as raw:
            stream = zstandard.ZstdDecompressor().stream_reader(raw)
            with tarfile.open(fileobj=stream, mode="r|") as tar:
                tar.extractall(target, filter="data")
    else:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(target, filter="data")


def _download_client() -> httpx.AsyncClient:
    # trust_env=True: model and software downloads go through the configured proxy.
    return httpx.AsyncClient(timeout=httpx.Timeout(60, read=300), follow_redirects=True)


class OllamaProvisioner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.steps: dict[str, SetupStep] = {}
        self._process: subprocess.Popen | None = None

    # Public

    async def run(self) -> None:
        """Make Ollama reachable with the configured model. Errors are reported in `steps`."""
        try:
            if not await self._reachable():
                binary = self._find_binary() or await self._install_binary()
                await self._start(binary)
            await self._ensure_model()
        except Exception as exc:
            logger.exception("Ollama provisioning failed")
            for step in self.steps.values():
                if not step.done and not step.error:
                    step.error = str(exc) or type(exc).__name__

    @property
    def busy(self) -> bool:
        return any(not step.done and not step.error for step in self.steps.values())

    async def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            await asyncio.to_thread(self._process.wait)

    # Binary

    def _find_binary(self) -> str | None:
        candidates = [
            self.settings.ollama_bin,
            shutil.which("ollama"),
            *map(str, KNOWN_INSTALLS),
            *map(str, sorted(LOCAL_OLLAMA_DIR.rglob(BINARY_NAME))),
        ]
        return next((c for c in candidates if c and Path(c).expanduser().is_file()), None)

    async def _install_binary(self) -> str:
        step = self.steps.setdefault("ollama", SetupStep("Installation d'Ollama"))
        url = _download_url()
        archive = LOCAL_OLLAMA_DIR.with_name("ollama-download-" + url.rsplit("/", 1)[1])
        archive.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading Ollama from %s", url)
        await self._download(url, archive, step)
        step.label, step.progress = "Installation d'Ollama (extraction)", None
        partial = LOCAL_OLLAMA_DIR.with_name("ollama.partial")
        shutil.rmtree(partial, ignore_errors=True)
        await asyncio.to_thread(_extract, archive, partial)
        archive.unlink(missing_ok=True)
        shutil.rmtree(LOCAL_OLLAMA_DIR, ignore_errors=True)
        partial.rename(LOCAL_OLLAMA_DIR)
        binary = self._find_binary()
        if not binary:
            raise RuntimeError(f"{BINARY_NAME} introuvable dans l'archive Ollama")
        if sys.platform != "win32":
            Path(binary).chmod(0o755)
        step.done = True
        return binary

    # Process

    async def _start(self, binary: str) -> None:
        log = self.settings.data_dir / "ollama.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Starting %s serve (log: %s)", binary, log)
        url = urlparse(self.settings.ollama_url)
        env = {**os.environ, "OLLAMA_HOST": f"{url.hostname}:{url.port or 11434}"}
        # Plain Popen: asyncio subprocesses depend on the event loop type on Windows.
        with log.open("ab") as output:
            self._process = subprocess.Popen(
                [binary, "serve"],
                stdout=output,
                stderr=subprocess.STDOUT,
                env=env,
                # Linux only; elsewhere Ollama is stopped by `stop()` on shutdown.
                preexec_fn=_die_with_parent if sys.platform.startswith("linux") else None,
            )
        for _ in range(100):
            if await self._reachable():
                return
            await asyncio.sleep(0.2)
        raise RuntimeError(f"Ollama ne démarre pas (voir {log})")

    async def _reachable(self) -> bool:
        return await self._models() is not None

    async def _models(self) -> list[str] | None:
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.ollama_url, timeout=3, trust_env=False
            ) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
        except httpx.HTTPError:
            return None
        return [m["name"] for m in response.json().get("models", [])]

    # Model

    async def _ensure_model(self) -> None:
        name = self.settings.ollama_model
        full_name = name if ":" in name else f"{name}:latest"
        if full_name in (await self._models() or []):
            return
        step = self.steps.setdefault("model", SetupStep(f"Téléchargement du modèle IA {name}"))
        if self._process:  # our Ollama: we own its model directory
            await self._download_model(name, step)
            if full_name not in (await self._models() or []):
                # Make the restarted server rescan its models.
                binary = self._find_binary()
                await self.stop()
                assert binary
                await self._start(binary)
        else:
            await self._pull_model(name, step)
        if full_name not in (await self._models() or []):
            raise RuntimeError(f"Modèle {name} introuvable après téléchargement")
        step.done = True

    async def _pull_model(self, name: str, step: SetupStep) -> None:
        async with (
            httpx.AsyncClient(
                base_url=self.settings.ollama_url, timeout=None, trust_env=False
            ) as client,
            client.stream("POST", "/api/pull", json={"model": name}) as response,
        ):
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if "error" in event:
                    raise RuntimeError(event["error"])
                if event.get("total"):
                    step.progress = event.get("completed", 0) / event["total"]

    async def _download_model(self, name: str, step: SetupStep) -> None:
        model, _, tag = name.partition(":")
        namespace, _, model = model.rpartition("/")
        repository = f"{namespace or 'library'}/{model}"
        tag = tag or "latest"
        models_dir = Path(os.environ.get("OLLAMA_MODELS", Path.home() / ".ollama" / "models"))
        async with _download_client() as client:
            response = await client.get(
                f"{REGISTRY}/v2/{repository}/manifests/{tag}", headers={"Accept": MANIFEST_TYPE}
            )
            response.raise_for_status()
            manifest = response.content
            layers = [response.json()["config"], *response.json()["layers"]]
            total = sum(layer["size"] for layer in layers)
            done = 0
            for layer in layers:
                digest = layer["digest"]
                blob = models_dir / "blobs" / digest.replace(":", "-")
                if not (blob.exists() and blob.stat().st_size == layer["size"]):
                    base = done

                    def report(received: int, base: int = base) -> None:
                        step.progress = (base + received) / total

                    await self._download(
                        f"{REGISTRY}/v2/{repository}/blobs/{digest}",
                        blob,
                        step,
                        client=client,
                        sha256=digest.removeprefix("sha256:"),
                        on_bytes=report,
                    )
                done += layer["size"]
                step.progress = done / total
        target = models_dir / "manifests" / "registry.ollama.ai" / repository / tag
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(manifest)

    # Download helper

    async def _download(
        self,
        url: str,
        path: Path,
        step: SetupStep,
        client: httpx.AsyncClient | None = None,
        sha256: str | None = None,
        on_bytes=None,
    ) -> None:
        """Resumable download to `path` (via `path.partial`), optionally checksum-verified."""
        partial = path.with_name(path.name + ".partial")
        partial.parent.mkdir(parents=True, exist_ok=True)
        owned_client = client is None
        client = client or _download_client()
        try:
            for attempt in range(5):
                offset = partial.stat().st_size if partial.exists() else 0
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                try:
                    async with client.stream("GET", url, headers=headers) as response:
                        if response.status_code == 416:  # already complete
                            break
                        response.raise_for_status()
                        if offset and response.status_code != 206:
                            offset = 0  # server ignored the range: restart
                        size = offset + int(response.headers.get("content-length", 0))
                        with partial.open("ab" if offset else "wb") as out:
                            received = offset
                            async for chunk in response.aiter_bytes(CHUNK):
                                out.write(chunk)
                                received += len(chunk)
                                if on_bytes:
                                    on_bytes(received)
                                elif size:
                                    step.progress = received / size
                    break
                except httpx.HTTPError as exc:
                    if attempt == 4:
                        raise
                    logger.warning("Download interrupted (%s), resuming", exc)
                    await asyncio.sleep(2)
        finally:
            if owned_client:
                await client.aclose()
        if sha256 and await asyncio.to_thread(_sha256, partial) != sha256:
            partial.unlink()
            raise RuntimeError(f"Somme de contrôle invalide pour {path.name}")
        partial.rename(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
