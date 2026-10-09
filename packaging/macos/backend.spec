# PyInstaller spec of the server bundled in the macOS app: one folder (`smart-meeting-backend/`)
# with Python and the dependencies, no web interface (the app has its own). Built by
# packaging/macos/build.sh.
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 (defined by PyInstaller)
SOURCES = ROOT / "backend" / "src" / "smart_meeting"

datas = [
    (str(SOURCES / "llm" / "prompts"), "smart_meeting/llm/prompts"),
    (str(SOURCES / "starting.html"), "smart_meeting"),
]
binaries = []
hiddenimports = collect_submodules("smart_meeting") + collect_submodules("uvicorn")
# Native libraries and data files (Silero VAD model, PortAudio, FFmpeg, Metal kernels of MLX,
# Whisper tokenizer…) their hooks miss.
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers", "soxr",
                "sounddevice", "_sounddevice_data", "hf_xet", "ScreenCaptureKit", "CoreMedia",
                "mlx", "mlx_whisper", "tiktoken", "tiktoken_ext"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
# MLX loads its Metal kernels from next to libmlx.dylib, which PyInstaller moves to the top folder
# (where mlx/core links it from): the kernels go there too, the copies in mlx/lib are dropped.
MLX_LIB = ("libmlx.dylib", "mlx.metallib")
datas = [d for d in datas if not (d[1] == "mlx/lib" and Path(d[0]).name in MLX_LIB)]
binaries = [b for b in binaries if not (b[1] == "mlx/lib" and Path(b[0]).name in MLX_LIB)]
MLX_DIR = Path(importlib.util.find_spec("mlx").submodule_search_locations[0])
datas.append((str(MLX_DIR / "lib" / "mlx.metallib"), "."))

a = Analysis(  # noqa: F821
    [str(Path(SPECPATH) / "backend_entry.py")],  # noqa: F821
    pathex=[str(SOURCES.parent)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Development tools, never imported by the server; PyTorch: model conversion of mlx-whisper
    excludes=["pytest", "ruff", "PyObjCTest", "tkinter", "torch"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="smart-meeting-backend",
    console=True,
    # Signed afterwards with the app's entitlements (packaging/macos/sign-backend.sh)
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="smart-meeting-backend")  # noqa: F821
