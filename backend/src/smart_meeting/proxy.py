"""Proxy of the system for the downloads (models, Ollama), when none comes from the environment.

An app started from the Finder or the applications menu does not get the HTTPS_PROXY of a
terminal: behind a company proxy its downloads timed out (the transcription model of the macOS app
was never downloaded, the meeting waited for 12 minutes). The proxy is then taken from the system
settings: a manual one (macOS network settings, GNOME), or the one an automatic configuration
(PAC) file gives. The local server and Ollama are never reached through it.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.request

logger = logging.getLogger(__name__)

LOCAL = "localhost,127.0.0.1,::1"
ENV_NAMES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


def apply_system_proxy() -> str | None:
    """Set HTTPS_PROXY and HTTP_PROXY from the system settings unless already set; returns the
    proxy used, if any."""
    if any(os.environ.get(name) for name in ENV_NAMES):
        return None
    proxy = _manual_proxy() or _pac_proxy()
    if proxy:
        os.environ["HTTPS_PROXY"] = os.environ["HTTP_PROXY"] = proxy
        no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
        os.environ["NO_PROXY"] = f"{no_proxy},{LOCAL}" if no_proxy else LOCAL
        logger.info("Downloads through the proxy of the system settings: %s", proxy)
    return proxy


def _manual_proxy() -> str | None:
    # macOS: urllib reads the network settings (SystemConfiguration) when the environment has none
    if sys.platform == "darwin":
        proxies = urllib.request.getproxies()
        return proxies.get("https") or proxies.get("http")
    if _gsettings("org.gnome.system.proxy", "mode") == "manual":
        host = _gsettings("org.gnome.system.proxy.https", "host") or _gsettings(
            "org.gnome.system.proxy.http", "host"
        )
        port = _gsettings("org.gnome.system.proxy.https", "port") or _gsettings(
            "org.gnome.system.proxy.http", "port"
        )
        if host:
            return f"http://{host}:{port or 3128}"
    return None


def _pac_proxy() -> str | None:
    url = _pac_url()
    if not url:
        return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            return proxy_from_pac(response.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        logger.warning("Proxy auto-configuration unreadable: %s", url, exc_info=True)
        return None


def _pac_url() -> str | None:
    if sys.platform == "darwin" and shutil.which("scutil"):
        return pac_url_from_scutil(_run(["scutil", "--proxy"]))
    if _gsettings("org.gnome.system.proxy", "mode") == "auto":
        return _gsettings("org.gnome.system.proxy", "autoconfig-url") or None
    return None


def pac_url_from_scutil(output: str) -> str | None:
    """`scutil --proxy` prints `ProxyAutoConfigEnable : 1` and `ProxyAutoConfigURLString : url`,
    or `ProxyAutoDiscoveryEnable : 1` (WPAD: the script at the usual address of the network)."""
    if re.search(r"ProxyAutoConfigEnable\s*:\s*1", output):
        match = re.search(r"ProxyAutoConfigURLString\s*:\s*(\S+)", output)
        if match:
            return match.group(1)
    if re.search(r"ProxyAutoDiscoveryEnable\s*:\s*1", output):
        return "http://wpad/wpad.dat"
    return None


def proxy_from_pac(script: str) -> str | None:
    """The first proxy a PAC script names: what it gives for addresses outside the company. A
    script only sending everything DIRECT names none."""
    match = re.search(r"PROXY\s+([\w.-]+:\d+)", script)
    return f"http://{match.group(1)}" if match else None


def _gsettings(schema: str, key: str) -> str:
    if not shutil.which("gsettings"):
        return ""
    return _run(["gsettings", "get", schema, key]).strip().strip("'")


def _run(command: list[str]) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
