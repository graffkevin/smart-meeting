"""Entry point of the server bundled in the desktop app (PyInstaller): the launcher, in app mode."""

import multiprocessing

from smart_meeting.launcher import run

if __name__ == "__main__":
    # Helper processes of multiprocessing (the semaphore tracker of tqdm's lock) start this same
    # executable: they must run their own code, not the server
    multiprocessing.freeze_support()
    run()
