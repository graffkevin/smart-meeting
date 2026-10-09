# PyInstaller spec of the Windows app: one folder (`Smart Meeting/`) with Python, the server, the
# built web interface and the window (pywebview). Built by packaging/windows/build.sh.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 (defined by PyInstaller)
SOURCES = ROOT / "backend" / "src" / "smart_meeting"

datas = [
    (str(SOURCES / "llm" / "prompts"), "smart_meeting/llm/prompts"),
    (str(SOURCES / "starting.html"), "smart_meeting"),
    # Served by the server (smart_meeting/main.py finds it in the bundle)
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    # The installed version, for the update check
    *copy_metadata("smart-meeting"),
]
binaries = []
hiddenimports = (
    collect_submodules("smart_meeting")
    + collect_submodules("smart_meeting_win")
    + collect_submodules("uvicorn")
)
# Native libraries and data files (Silero VAD model, WASAPI capture, FFmpeg, WebView2 and .NET
# glue…) their hooks miss.
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers", "soxr",
                "pyaudiowpatch", "hf_xet", "webview", "clr_loader", "pythonnet"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(  # noqa: F821
    [str(Path(SPECPATH) / "app_entry.py")],  # noqa: F821
    pathex=[str(SOURCES.parent), str(ROOT / "windows")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Development tools, never imported by the app
    excludes=["pytest", "ruff", "tkinter", "torch"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Smart Meeting",
    console=False,  # a window app; the server writes to its log
    icon=str(ROOT / "build" / "windows" / "app.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Smart Meeting")  # noqa: F821
