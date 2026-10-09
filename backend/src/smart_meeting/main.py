import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path

# No telemetry from the Hugging Face hub (only used to download Whisper models once).
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from smart_meeting import watchdog  # noqa: E402
from smart_meeting.api.routes import router  # noqa: E402
from smart_meeting.config import get_settings  # noqa: E402
from smart_meeting.db import Database  # noqa: E402
from smart_meeting.meeting import safety  # noqa: E402
from smart_meeting.meeting.events import EventHub  # noqa: E402
from smart_meeting.meeting.service import MeetingService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    services: list[MeetingService] = []  # the watchdog starts before the service exists
    watchdog.start(
        asyncio.get_running_loop(),
        settings.data_dir,
        on_frozen=lambda: services and services[0].restart_if_recording(),
    )
    # Lets the launcher replace this server if it ever freezes.
    pid_file = watchdog.pid_path(settings.data_dir)
    pid_file.write_text(str(os.getpid()))
    db = Database(settings.db_path)
    # Restarted because the transcription froze: that meeting goes on
    resume = safety.take_resume(settings.data_dir)
    unfinished = db.fail_interrupted_meetings(resumed=resume["meeting_id"] if resume else None)
    service = MeetingService(settings, db, EventHub())
    services.append(service)
    app.state.service = service
    service.startup(resume, unfinished)
    yield
    await service.shutdown()
    pid_file.unlink(missing_ok=True)


# FastAPI's built-in OpenTelemetry instrumentation is fully disabled: nothing about meetings
# must ever be exported, even if OTEL_* variables happen to be set in the environment.
app = FastAPI(
    title="Smart Meeting",
    lifespan=lifespan,
    # Operation ids = route function names: readable names in the generated frontend client.
    generate_unique_id_function=lambda route: route.name,
    telemetry={"tracing": False, "metrics": False, "logs": False, "auto_configure": False},
)
app.include_router(router)
# Replaced by the launcher with a cross-platform uvicorn exit; SIGINT works under `uvicorn` (dev).
app.state.request_exit = lambda: os.kill(os.getpid(), signal.SIGINT)
# Set by the launcher only: in development, closing the page must not stop the server.
app.state.stop_when_unused = None
# Set by the launcher in the browser version: restart on the updated code (see update.py).
app.state.restart = None

# The built interface, from the same origin. Not checked at import: the launcher builds it after
# importing this module (first run, or sources changed).
app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True, check_dir=False), name="frontend")
