import asyncio
import contextlib
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import httpx
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

from smart_meeting.meeting.report import build_markdown
from smart_meeting.meeting.service import ConflictError, MeetingService, default_title
from smart_meeting.messages import tr
from smart_meeting.models import (
    AskAnswer,
    AskRequest,
    AudioDevices,
    Health,
    Meeting,
    MeetingDetail,
    MeetingListItem,
    MeetingStorage,
    Preferences,
    RenameSpeakerRequest,
    SetupStepInfo,
    StartMeetingRequest,
    TagCount,
    TagsRequest,
    UpdateInfo,
    UpdateMeetingRequest,
    UpdateResult,
)
from smart_meeting.update import UpdateError

router = APIRouter(prefix="/api")

# Suggestions of the question field
RECENT_QUESTIONS = 10


def service(request: Request) -> MeetingService:
    return request.app.state.service


def get_meeting_or_404(svc: MeetingService, meeting_id: int) -> Meeting:
    meeting = svc.db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, tr("meeting_not_found"))
    return meeting


@contextlib.contextmanager
def conflict_as_409():
    try:
        yield
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/update")
async def get_update(request: Request, refresh: bool = False) -> UpdateInfo:
    """The latest version published, and how this installation gets it."""
    return await service(request).updater.check(force=refresh)


@router.post("/update")
async def apply_update(request: Request) -> UpdateResult:
    """Install the latest version, then restart: the server by itself in the browser version,
    the desktop app restarts itself and its server."""
    svc = service(request)
    if svc.busy:
        raise HTTPException(409, tr("update_busy"))
    try:
        await svc.updater.apply()
    except UpdateError as exc:
        raise HTTPException(409, str(exc)) from exc
    restart = request.app.state.restart
    if restart is None:
        return UpdateResult(restart="app")
    asyncio.get_running_loop().call_later(0.5, restart)  # once this answer is sent
    return UpdateResult(restart="server")


@router.get("/health")
async def health(request: Request) -> Health:
    svc = service(request)
    models = await svc.ollama.available_models()
    wanted = svc.settings.ai_model
    return Health(
        whisper=svc.whisper_state,
        whisper_detail=svc.whisper_detail,
        ollama=models is not None,
        ollama_model=wanted,
        ollama_model_available=bool(models)
        and any(m == wanted or m == f"{wanted}:latest" for m in models),
        active_meeting_id=svc.active.meeting_id if svc.active else None,
        ui_open=svc.ui_connections > 0,
        setup=[
            SetupStepInfo(**vars(step)) for step in svc.provisioner.steps.values() if not step.done
        ],
    )


@router.post("/shutdown", status_code=202)
async def shutdown(request: Request, background: BackgroundTasks) -> None:
    """Quit button: finish the current recording's transcription, then stop the server
    (the launcher then stops the Ollama it started)."""
    await service(request).quit()
    # After the response is sent: graceful shutdown, like Ctrl+C.
    background.add_task(request.app.state.request_exit)


@router.post("/ai/restart", status_code=202)
async def restart_ai(request: Request) -> None:
    """Restart the local AI (Ollama), and install its model again if it is missing."""
    service(request).restart_ai()


@router.get("/preferences")
def get_preferences(request: Request) -> Preferences:
    return service(request).preferences.current


@router.put("/preferences")
async def update_preferences(request: Request, body: Preferences) -> Preferences:
    """Saved and applied at once: name and vocabulary for the next sentences, defaults for the next
    meeting, the AI model (downloaded if missing)."""
    return service(request).save_preferences(body)


@router.post("/audio/permission-settings", status_code=204)
def open_permission_settings(request: Request) -> None:
    """macOS: open the settings where the capture of the system audio is allowed."""
    audio = service(request).audio
    if not hasattr(audio, "open_permission_settings"):
        raise HTTPException(status_code=409, detail=tr("not_on_this_system"))
    audio.open_permission_settings()


@router.get("/audio/devices")
async def audio_devices(request: Request) -> AudioDevices:
    try:
        return await service(request).audio.list_devices()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, tr("audio_unavailable", error=exc)) from exc


@router.get("/meetings")
def list_meetings(request: Request, q: str = "") -> list[MeetingListItem]:
    """History, newest first; `q` searches titles, summaries and transcripts."""
    return service(request).db.list_meetings(q)


@router.post("/meetings", status_code=201)
async def start_meeting(request: Request, body: StartMeetingRequest) -> Meeting:
    with conflict_as_409():
        return await service(request).start(body)


@router.post("/meetings/import", status_code=201)
async def import_meeting(
    request: Request, file: UploadFile, title: str = Form(""), language: str = Form("auto")
) -> Meeting:
    """Upload an audio or video file to transcribe and analyze. It is deleted once decoded."""
    svc = service(request)
    filename = Path(file.filename or "fichier").name
    uploads = svc.settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    path = uploads / f"{uuid.uuid4().hex}{Path(filename).suffix}"
    with path.open("wb") as out:
        await asyncio.to_thread(shutil.copyfileobj, file.file, out, 1024 * 1024)
    try:
        with conflict_as_409():
            return await svc.import_file(title, path, filename, language)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise


@router.get("/meetings/{meeting_id}")
def get_meeting(request: Request, meeting_id: int) -> MeetingDetail:
    svc = service(request)
    meeting = get_meeting_or_404(svc, meeting_id)
    segments = svc.db.list_segments(meeting_id)
    has_audio = meeting.keep_audio and svc.audio_path(meeting_id).exists()
    return MeetingDetail(
        meeting=meeting,
        segments=segments,
        analysis=svc.db.get_analysis(meeting_id),
        # Safety tracks of a meeting being recorded are not "kept audio"
        has_audio=has_audio,
        captured=svc.captured_devices(meeting_id),
        estimates=svc.estimates(meeting, segments),
        analysis_elapsed_s=svc.analysis_elapsed_s(meeting_id),
        questions=svc.db.list_questions(meeting_id),
        storage=MeetingStorage(
            database=str(svc.settings.db_path),
            audio=str(svc.audio_path(meeting_id)) if has_audio else None,
        ),
    )


@router.patch("/meetings/{meeting_id}")
def update_meeting(request: Request, meeting_id: int, body: UpdateMeetingRequest) -> Meeting:
    svc = service(request)
    meeting = get_meeting_or_404(svc, meeting_id)
    started = datetime.fromisoformat(meeting.started_at).astimezone()
    title = body.title.strip() or default_title(started, svc.settings.ui_language)
    svc.db.update_meeting(meeting_id, title=title)
    return get_meeting_or_404(svc, meeting_id)


@router.put("/meetings/{meeting_id}/tags")
def set_meeting_tags(request: Request, meeting_id: int, body: TagsRequest) -> Meeting:
    """Replaces the tags of a meeting (used to group the history)."""
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    svc.db.set_tags(meeting_id, body.tags)
    return get_meeting_or_404(svc, meeting_id)


@router.put("/meetings/{meeting_id}/speakers", status_code=204)
def rename_speaker(request: Request, meeting_id: int, body: RenameSpeakerRequest) -> None:
    """Names a speaker ("Intervenant 2" -> "Paul") in the whole meeting, during or after it.
    Giving the name of another speaker merges both (a voice wrongly split in two)."""
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    svc.rename_speaker(meeting_id, body.old, body.new)


@router.get("/tags")
def list_tags(request: Request) -> list[TagCount]:
    """Every tag in use, most used first."""
    return service(request).db.list_tags()


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


@router.post("/meetings/{meeting_id}/ask")
async def ask_meeting(request: Request, meeting_id: int, body: AskRequest) -> AskAnswer:
    """A question about the meeting (\"what do I have to do?\"), answered from its transcript by the
    local AI, during or after the meeting. Kept with the meeting."""
    svc = service(request)
    get_meeting_or_404(svc, meeting_id)
    question = body.question.strip()
    with conflict_as_409():
        try:
            answer = await svc.ask(meeting_id, question)
        except httpx.TimeoutException as exc:
            raise HTTPException(503, tr("ai_too_slow").capitalize()) from exc
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(503, tr("ai_unreachable", error=exc)) from exc
    return svc.db.add_question(meeting_id, question, answer)


@router.get("/questions/recent")
def recent_questions(request: Request) -> list[str]:
    """Questions asked lately in any meeting: suggestions of the question field."""
    return service(request).db.recent_questions(RECENT_QUESTIONS)


@router.get("/meetings/{meeting_id}/report.md", response_class=PlainTextResponse)
def meeting_report(request: Request, meeting_id: int) -> str:
    svc = service(request)
    meeting = get_meeting_or_404(svc, meeting_id)
    return build_markdown(
        meeting,
        svc.db.list_segments(meeting_id),
        svc.db.get_analysis(meeting_id),
        svc.db.list_questions(meeting_id),
        svc.settings.ui_language,
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


@router.websocket("/presence")
async def presence(websocket: WebSocket) -> None:
    """Held open by every page. The launcher reuses an open page instead of opening a new one,
    and the app stops when the last page is closed (once nothing is running)."""
    svc: MeetingService = websocket.app.state.service
    await websocket.accept()
    svc.page_opened()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        svc.page_closed(websocket.app.state.stop_when_unused)


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
