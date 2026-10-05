"""Stack traces of a frozen server. When the event loop stops answering, every thread's Python
stack is appended to `hang-traces.log` in the data folder: no debugger or admin rights needed to
find out where it is stuck. On Linux and macOS, `kill -USR1 <pid>` writes them on demand."""

import asyncio
import faulthandler
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

STALL_S = 10.0  # the launcher waits longer before replacing a frozen server


def traces_path(data_dir: Path) -> Path:
    return data_dir / "hang-traces.log"


def pid_path(data_dir: Path) -> Path:
    return data_dir / "server.pid"


def start(loop: asyncio.AbstractEventLoop, data_dir: Path, stall_s: float = STALL_S) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    # Kept open for the life of the process: faulthandler writes to its file descriptor.
    traces = traces_path(data_dir).open("a", encoding="utf-8")
    if sys.platform != "win32":
        faulthandler.register(signal.SIGUSR1, file=traces, all_threads=True)
    last_beat = time.monotonic()

    def beat() -> None:
        nonlocal last_beat
        last_beat = time.monotonic()

    def watch() -> None:
        dumped = False  # once per freeze
        while not loop.is_closed():
            try:
                loop.call_soon_threadsafe(beat)
            except RuntimeError:  # loop closed meanwhile
                return
            time.sleep(1)
            stalled_s = time.monotonic() - last_beat
            if stalled_s < stall_s:
                dumped = False
            elif not dumped:
                dumped = True
                logger.error("Event loop frozen for %.0f s, stacks in %s", stalled_s, traces.name)
                traces.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()}:"
                             f" event loop frozen for {stalled_s:.0f} s ===\n")  # fmt: skip
                traces.flush()
                faulthandler.dump_traceback(file=traces, all_threads=True)
                traces.flush()

    threading.Thread(target=watch, name="loop-watchdog", daemon=True).start()
