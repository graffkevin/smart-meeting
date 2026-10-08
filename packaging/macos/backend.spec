# PyInstaller spec of the server bundled in the macOS app: one folder (`smart-meeting-backend/`)
# with Python and the dependencies, no web interface (the app has its own). Built by
# packaging/macos/build.sh.
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
# Native libraries and data files (Silero VAD model, PortAudio, FFmpeg…) their hooks miss.
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers", "soxr",
                "sounddevice", "_sounddevice_data", "hf_xet", "ScreenCaptureKit", "CoreMedia"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(  # noqa: F821
    [str(Path(SPECPATH) / "backend_entry.py")],  # noqa: F821
    pathex=[str(SOURCES.parent)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Development tools, never imported by the server
    excludes=["pytest", "ruff", "PyObjCTest", "tkinter"],
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
