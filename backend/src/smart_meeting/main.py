import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# No telemetry from the Hugging Face hub (only used to download Whisper models once).
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from smart_meeting.api.routes import router  # noqa: E402
from smart_meeting.config import get_settings  # noqa: E402
from smart_meeting.db import Database  # noqa: E402
from smart_meeting.meeting.events import EventHub  # noqa: E402
from smart_meeting.meeting.service import MeetingService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db = Database(settings.db_path)
    db.fail_interrupted_meetings()
    service = MeetingService(settings, db, EventHub())
    app.state.service = service
    service.startup()
    yield
    await service.shutdown()


app = FastAPI(title="Smart Meeting", lifespan=lifespan)
app.include_router(router)

# Production-like mode: serve the built frontend from the same origin.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
