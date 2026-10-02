import asyncio
import contextlib
import os
import shutil
import signal
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import PlainTextResponse

from smart_meeting.audio.devices import list_devices
from smart_meeting.meeting.report import build_markdown
from smart_meeting.meeting.service import ConflictError, MeetingService
from smart_meeting.models import (
    AudioDevices,
    Health,
    Meeting,
    MeetingDetail,
    MeetingListItem,
    SetupStepInfo,
    StartMeetingRequest,
    UpdateMeetingRequest,
)

router = APIRouter(prefix="/api")


def service(request: Request) -> MeetingService:
    return request.app.state.service


def get_meeting_or_404(svc: MeetingService, meeting_id: int) -> Meeting:
    meeting = svc.db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, "Réunion introuvable")
    return meeting


@contextlib.contextmanager
def conflict_as_409():
    try:
        yield
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/health")
async def health(request: Request) -> Health:
    svc = service(request)
    models = await svc.ollama.available_models()
    wanted = svc.settings.ollama_model
    return Health(
        whisper=svc.whisper_state,
        whisper_detail=svc.whisper_detail,
        ollama=models is not None,
        ollama_model=wanted,
        ollama_model_available=bool(models)
        and any(m == wanted or m == f"{wanted}:latest" for m in models),
        active_meeting_id=svc.active.meeting_id if svc.active else None,
        setup=[
            SetupStepInfo(**vars(step)) for step in svc.provisioner.steps.values() if not step.done
        ],
    )


@router.post("/shutdown", status_code=202)
async def shutdown(request: Request, background: BackgroundTasks) -> None:
    """Quit button: finish the current recording's transcription, then stop the server
    (the launcher then stops the Ollama it started)."""
    await service(request).quit()
    # After the response is sent: same graceful path as Ctrl+C.
    background.add_task(os.kill, os.getpid(), signal.SIGINT)


@router.get("/audio/devices")
async def audio_devices() -> AudioDevices:
    try:
        return await list_devices()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, f"PipeWire indisponible : {exc}") from exc


@router.get("/meetings")
def list_meetings(request: Request, q: str = "") -> list[MeetingListItem]:
    """History, newest first; `q` searches titles, summaries and transcripts."""
    return service(request).db.list_meetings(q)


@router.post("/meetings", status_code=201)
async def start_meeting(request: Request, body: StartMeetingRequest) -> Meeting:
    with conflict_as_409():
        return await service(request).start(body)


@router.post("/meetings/import", status_code=201)
async def import_meeting(request: Request, file: UploadFile, title: str = Form("")) -> Meeting:
    """Upload an audio or video file to transcribe and analyze. It is deleted once decoded."""
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "ffmpeg est requis pour importer un fichier")
    svc = service(request)
    filename = Path(file.filename or "fichier").name
    uploads = svc.settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    path = uploads / f"{uuid.uuid4().hex}{Path(filename).suffix}"
    with path.open("wb") as out:
        await asyncio.to_thread(shutil.copyfileobj, file.file, out, 1024 * 1024)
    try:
        with conflict_as_409():
            return await svc.import_file(title, path, filename)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise


@router.get("/meetings/{meeting_id}")
def get_meeting(request: Request, meeting_id: int) -> MeetingDetail:
    svc = service(request)
    meeting = get_meeting_or_404(svc, meeting_id)
    return MeetingDetail(
        meeting=meeting,
        segments=svc.db.list_segments(meeting_id),
        analysis=svc.db.get_analysis(meeting_id),
        has_audio=svc.audio_path(meeting_id).exists(),
        captured=svc.captured_devices(meeting_id),
    )


@router.patch("/meetings/{meeting_id}")
def update_meeting(request: Request, meeting_id: int, body: UpdateMeetingRequest) -> Meeting:
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    svc.db.update_meeting(meeting_id, title=body.title.strip() or "Réunion sans titre")
    return get_meeting_or_404(svc, meeting_id)


@router.post("/meetings/{meeting_id}/stop")
async def stop_meeting(request: Request, meeting_id: int) -> Meeting:
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    with conflict_as_409():
        return await svc.stop(meeting_id)


@router.post("/meetings/{meeting_id}/analyze", status_code=202)
async def analyze_meeting(request: Request, meeting_id: int) -> None:
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    with conflict_as_409():
        svc.request_analysis(meeting_id)


@router.get("/meetings/{meeting_id}/report.md", response_class=PlainTextResponse)
def meeting_report(request: Request, meeting_id: int) -> str:
    svc = service(request)
    meeting = get_meeting_or_404(svc, meeting_id)
    return build_markdown(
        meeting, svc.db.list_segments(meeting_id), svc.db.get_analysis(meeting_id)
    )


@router.delete("/meetings/{meeting_id}/audio", status_code=204)
def delete_audio(request: Request, meeting_id: int) -> None:
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    with conflict_as_409():
        svc.delete_audio(meeting_id)


@router.delete("/meetings/{meeting_id}", status_code=204)
async def delete_meeting(request: Request, meeting_id: int) -> None:
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    with conflict_as_409():
        svc.delete_meeting(meeting_id)


@router.websocket("/meetings/{meeting_id}/ws")
async def meeting_events(websocket: WebSocket, meeting_id: int) -> None:
    """Live events: `segment`, `status`, `levels`. Clients load existing state via GET first."""
    svc: MeetingService = websocket.app.state.service
    await websocket.accept()
    queue = svc.hub.subscribe(meeting_id)
    receiver = asyncio.create_task(websocket.receive_text())  # detects disconnection
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                getter.cancel()
                break
            await websocket.send_json(getter.result())
    except WebSocketDisconnect:
        pass
    finally:
        receiver.cancel()
        svc.hub.unsubscribe(meeting_id, queue)
