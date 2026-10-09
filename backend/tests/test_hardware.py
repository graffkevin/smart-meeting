from smart_meeting import provision
from smart_meeting.hardware import Hardware, parse_cpuinfo, parse_lspci

CPUINFO = """processor\t: 0
model name\t: 13th Gen Intel(R) Core(TM) i7-1365U
physical id\t: 0
core id\t: 0

processor\t: 1
model name\t: 13th Gen Intel(R) Core(TM) i7-1365U
physical id\t: 0
core id\t: 0

processor\t: 2
model name\t: 13th Gen Intel(R) Core(TM) i7-1365U
physical id\t: 0
core id\t: 4
"""

LSPCI = (
    '00:00.0 "Host bridge" "Intel Corporation" "Raptor Lake-P/U Host Bridge" -r01 "" ""\n'
    '00:02.0 "VGA compatible controller" "Intel Corporation" "Iris Xe Graphics"'
    ' -r04 "" ""\n'
    '01:00.0 "3D controller" "NVIDIA Corporation" "GA107M [GeForce RTX 3050 Mobile]" -ra1 "" ""\n'
)


def test_cpuinfo_counts_physical_cores_not_threads():
    assert parse_cpuinfo(CPUINFO) == ("13th Gen Intel(R) Core(TM) i7-1365U", 2)


def test_lspci_keeps_display_controllers_with_their_vendor():
    assert parse_lspci(LSPCI) == (
        ("intel", "Intel Corporation Iris Xe Graphics"),
        ("nvidia", "NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile]"),
    )


def test_intel_cpu_or_gpu_counts_as_intel():
    amd_cpu_arc_gpu = Hardware("AMD Ryzen 7", "amd", 8, False, (("intel", "Intel Arc A770"),))
    assert amd_cpu_arc_gpu.intel and amd_cpu_arc_gpu.intel_gpu == "Intel Arc A770"
    assert Hardware("Intel Core i5", "intel", 4, False).intel
    assert not Hardware("AMD Ryzen 7", "amd", 8, False, (("amd", "Radeon"),)).intel


def test_ollama_reaches_intel_gpus_through_vulkan(monkeypatch):
    monkeypatch.setattr(provision.sys, "platform", "linux")
    iris = Hardware("Intel Core i7", "intel", 4, False, (("intel", "Iris Xe"),))
    assert provision.ollama_tuning(iris)["OLLAMA_VULKAN"] == "1"
    # NVIDIA GPU next to it: CUDA, no Vulkan
    with_nvidia = Hardware("Intel Core i7", "intel", 4, True, (("intel", "Iris Xe"),))
    assert "OLLAMA_VULKAN" not in provision.ollama_tuning(with_nvidia)
    tuning = provision.ollama_tuning(Hardware("AMD Ryzen", "amd", 8, False))
    assert tuning == {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}
