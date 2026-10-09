"""Entry point of the Windows app (PyInstaller): one executable for the window and its server.

Smart Meeting.exe              the app window, which starts the server below
Smart Meeting.exe --server …   the server (launcher arguments: --app, --port, --no-window)
Smart Meeting.exe --self-test  exit code 0 when the window's libraries load (CI)
"""

import multiprocessing
import sys

if __name__ == "__main__":
    # Helper processes of multiprocessing start this same executable: their own code first
    multiprocessing.freeze_support()
    if "--server" in sys.argv:
        sys.argv.remove("--server")
        from smart_meeting.config import get_settings

        # A windowed executable has no console: the output goes to the log of the data folder
        log_dir = get_settings().data_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(log_dir / "server.log", "a", encoding="utf-8", buffering=1)
        from smart_meeting.launcher import run

        run()
    elif "--self-test" in sys.argv:
        import webview.platforms.winforms  # noqa: F401 (WebView2 and .NET, through pythonnet)

        sys.exit(0)
    else:
        from smart_meeting_win.app import main

        main()
