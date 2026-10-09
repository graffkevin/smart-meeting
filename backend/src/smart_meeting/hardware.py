"""What this machine can run the AI on, detected once at startup.

Cheap and without heavy imports: system files on Linux, sysctl on macOS, one PowerShell call on
Windows. Anything undetected counts as absent: the CPU engine then runs, as before.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

# PCI vendor ids
VENDORS = {"0x10de": "nvidia", "0x8086": "intel", "0x1002": "amd"}


@dataclass(frozen=True)
class Hardware:
    cpu: str  # model name
    cpu_vendor: str  # intel | amd | apple | other
    cores: int  # physical cores: compute threads worth using
    nvidia: bool  # usable NVIDIA GPU (driver answering)
    gpus: tuple[tuple[str, str], ...] = ()  # (vendor, name) of each GPU, integrated ones included

    @property
    def apple_silicon(self) -> bool:
        return self.cpu_vendor == "apple"

    @property
    def intel_gpu(self) -> str | None:
        return next((name for vendor, name in self.gpus if vendor == "intel"), None)

    @property
    def intel(self) -> bool:
        """Intel CPU or GPU: OpenVINO, Intel's engine, is made for them."""
        return self.cpu_vendor == "intel" or self.intel_gpu is not None

    def describe(self) -> str:
        gpus = ", ".join(name for _, name in self.gpus) or "no GPU"
        return f"{self.cpu} ({self.cores} cores), {gpus}"


def _run(*command: str, timeout: float = 5.0) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _vendor(name: str) -> str:
    lowered = name.lower()
    for vendor in ("intel", "amd", "nvidia", "apple"):
        if vendor in lowered:
            return vendor
    if "radeon" in lowered or "advanced micro devices" in lowered:
        return "amd"
    if "geforce" in lowered or "quadro" in lowered:
        return "nvidia"
    return "other"


def _nvidia() -> bool:
    return shutil.which("nvidia-smi") is not None and bool(_run("nvidia-smi", "-L").strip())


def parse_cpuinfo(text: str) -> tuple[str, int]:
    """Model name and physical cores (distinct physical id/core id pairs) of /proc/cpuinfo."""
    name, cores, physical = "", set(), "0"
    for line in text.splitlines():
        key, _, value = (part.strip() for part in line.partition(":"))
        if key == "model name" and not name:
            name = value
        elif key == "physical id":
            physical = value
        elif key == "core id":
            cores.add((physical, value))
    return name, len(cores)


def parse_lspci(text: str) -> tuple[tuple[str, str], ...]:
    """Display controllers of `lspci -mm` ("slot" "class" "vendor" "device" ...)."""
    gpus = []
    for line in text.splitlines():
        fields = re.findall(r'"([^"]*)"', line)
        if len(fields) >= 4 and re.search(r"VGA|3D|Display", fields[0]):
            gpus.append((_vendor(fields[1]), f"{fields[1]} {fields[2]}".strip()))
    return tuple(gpus)


def _linux_gpus() -> tuple[tuple[str, str], ...]:
    gpus = parse_lspci(_run("lspci", "-mm")) if shutil.which("lspci") else ()
    if gpus:
        return gpus
    # No lspci (minimal installs): vendor ids of the DRM devices, without model names
    found = []
    for vendor_file in sorted(Path("/sys/class/drm").glob("card[0-9]*/device/vendor")):
        vendor = VENDORS.get(vendor_file.read_text().strip())
        if vendor and (vendor, vendor.upper() + " GPU") not in found:
            found.append((vendor, vendor.upper() + " GPU"))
    return tuple(found)


def _detect_linux() -> Hardware:
    try:
        name, cores = parse_cpuinfo(Path("/proc/cpuinfo").read_text())
    except OSError:
        name, cores = "", 0
    return Hardware(
        cpu=name or platform.processor() or "CPU",
        cpu_vendor=_vendor(name),
        cores=cores or os.cpu_count() or 4,
        nvidia=_nvidia(),
        gpus=_linux_gpus(),
    )


def _detect_macos() -> Hardware:
    def sysctl(key: str) -> str:
        return _run("sysctl", "-n", key).strip()

    name = sysctl("machdep.cpu.brand_string") or platform.processor()
    apple = platform.machine() == "arm64"
    # Apple Silicon: performance cores only, the efficiency ones slow a shared computation down
    cores = sysctl("hw.perflevel0.physicalcpu") if apple else ""
    return Hardware(
        cpu=name,
        cpu_vendor="apple" if apple else _vendor(name),
        cores=int(cores or sysctl("hw.physicalcpu") or os.cpu_count() or 4),
        nvidia=False,
        gpus=(("apple", name),) if apple else (),
    )


def _detect_windows() -> Hardware:
    output = _run(
        "powershell",
        "-NoProfile",
        "-Command",
        "$c = Get-CimInstance Win32_Processor | Select-Object -First 1; "
        "'CPU|' + $c.Name + '|' + $c.NumberOfCores; "
        "Get-CimInstance Win32_VideoController | ForEach-Object { 'GPU|' + $_.Name }",
        timeout=15.0,
    )
    name, cores, gpus = "", 0, []
    for line in output.splitlines():
        kind, _, rest = line.strip().partition("|")
        if kind == "CPU":
            name, _, count = rest.rpartition("|")
            cores = int(count) if count.isdigit() else 0
        elif kind == "GPU" and rest:
            gpus.append((_vendor(rest), rest))
    # Without PowerShell: "Intel64 Family 6 Model 154 Stepping 3, GenuineIntel"
    name = name.strip() or os.environ.get("PROCESSOR_IDENTIFIER", "CPU")
    return Hardware(
        cpu=name,
        cpu_vendor="intel" if "GenuineIntel" in name else _vendor(name),
        cores=cores or max((os.cpu_count() or 8) // 2, 1),
        nvidia=_nvidia(),
        gpus=tuple(gpus),
    )


@cache
def detect_hardware() -> Hardware:
    if sys.platform == "darwin":
        hardware = _detect_macos()
    elif sys.platform == "win32":
        hardware = _detect_windows()
    else:
        hardware = _detect_linux()
    logger.info("Hardware: %s", hardware.describe())
    return hardware
