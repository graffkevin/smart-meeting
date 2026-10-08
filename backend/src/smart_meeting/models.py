from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["mic", "remote"]


class MeetingStatus(StrEnum):
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"  # capture stopped, draining the transcription queue
    TRANSCRIBED = "transcribed"  # transcript complete, no analysis yet
    ANALYZING = "analyzing"
    DONE = "done"
    ERROR = "error"


class Meeting(BaseModel):
    id: int
    title: str
    status: MeetingStatus
    started_at: str
    ended_at: str | None = None
    mic_device: str | None = None
    remote_device: str | None = None
    keep_audio: bool = False
    summary: str | None = None
    error: str | None = None
    source_file: str | None = None  # set for imported files
    language: str = "auto"  # transcription language: "auto" or a code (fr, en…)
    tags: list[str] = []
    created_at: str


class MeetingListItem(Meeting):
    action_count: int = 0


class Segment(BaseModel):
    id: int | None = None
    source: Source
    speaker: str | None = None
    start_s: float
    end_s: float
    text: str


# LLM output. Field descriptions are part of the JSON schema sent to Ollama.


class ActionItem(BaseModel):
    task: str = Field(description="Tâche à réaliser, formulée brièvement")
    owner: str | None = Field(
        description="Personne explicitement désignée comme responsable, sinon null"
    )
    deadline: str | None = Field(
        description="Échéance exactement telle que prononcée dans la transcription, sinon null"
    )
    quote: str | None = Field(
        description="Extrait exact de la transcription où l'action est mentionnée"
    )
    # Set by the backend, not the model: whether the quote was found in the transcript.
    verified: bool = False


class MeetingAnalysis(BaseModel):
    summary: str
    decisions: list[str]
    actions: list[ActionItem]
    questions: list[str]
    risks: list[str]
    technical_topics: list[str]


# API payloads


class AudioDevice(BaseModel):
    name: str  # PipeWire node.name, used as pw-record target
    description: str
    is_default: bool


class AudioDevices(BaseModel):
    sources: list[AudioDevice]  # microphones
    sinks: list[AudioDevice]  # outputs; their monitor is captured
    # What "automatic" mode would capture right now (devices used by applications).
    in_use_source: str | None = None
    in_use_sink: str | None = None


class StartMeetingRequest(BaseModel):
    title: str = ""
    # None means automatic: follow the devices applications are using, re-checked during
    # the meeting (e.g. a call starting after the recording, or a headset plugged in).
    mic_device: str | None = None
    remote_device: str | None = None
    keep_audio: bool = False
    # "auto": detected, sticky (a few foreign words do not switch it); or a code (fr, en…).
    language: str = "auto"
    tags: list[str] = Field(default=[], max_length=30)
    # Meeting room: several people around the microphone, told apart like the remote ones.
    room: bool = False


class RenameSpeakerRequest(BaseModel):
    """Every passage of `old` gets `new`; an existing name merges both speakers."""

    old: str = Field(min_length=1, max_length=80)
    new: str = Field(min_length=1, max_length=80)


class UpdateMeetingRequest(BaseModel):
    title: str


class Preferences(BaseModel):
    """Settings of the interface, applied without restart (see preferences.py)."""

    user_name: str = Field("Moi", max_length=80)  # label of my microphone, "I" for the AI
    glossary: list[str] = []  # vocabulary that helps the transcription (names, acronyms)
    language: str = "auto"  # default language of a new meeting
    mic_device: str | None = None  # None: automatic
    output_device: str | None = None  # None: automatic
    keep_audio: bool = False
    room: bool = False  # several people around the microphone
    ui_language: Literal["fr", "en"] = "fr"  # interface, AI answers and minutes


class TagsRequest(BaseModel):
    tags: list[str] = Field(max_length=30)


class TagCount(BaseModel):
    name: str
    count: int


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AskAnswer(BaseModel):
    """A question to the local AI about a meeting and its answer, kept with the meeting."""

    id: int | None = None
    question: str
    answer: str
    asked_at: str | None = None


class CapturedDevice(BaseModel):
    device: str | None
    auto: bool
    error: str | None = None  # capture failed for this source
    # The system blocks it until the user allows it: the interface opens the right settings
    permission_needed: bool = False


class AiEstimates(BaseModel):
    ask_s: float
    analysis_s: float


class MeetingStorage(BaseModel):
    """Where a meeting is kept on this computer."""

    database: str  # transcript, minutes, questions (SQLite)
    audio: str | None = None  # folder of its audio, when kept


class MeetingDetail(BaseModel):
    meeting: Meeting
    segments: list[Segment]
    analysis: MeetingAnalysis | None
    has_audio: bool
    # Devices being captured, while recording.
    captured: dict[Source, CapturedDevice] | None = None
    # Expected durations of the local AI on this transcript, in seconds (progress bars).
    estimates: AiEstimates | None = None
    # Seconds since the report started, while it is being written.
    analysis_elapsed_s: float | None = None
    # Questions asked to the local AI about this meeting, oldest first.
    questions: list["AskAnswer"] = []
    storage: MeetingStorage | None = None


class SetupStepInfo(BaseModel):
    label: str
    progress: float | None
    error: str | None
    done: bool


class Health(BaseModel):
    whisper: Literal["loading", "ready", "error"]
    whisper_detail: str | None
    ollama: bool
    ollama_model: str
    ollama_model_available: bool
    active_meeting_id: int | None
    ui_open: bool = False  # a browser page is currently open on the app
    # First-run installs and downloads still running or failed (Ollama, model).
    setup: list[SetupStepInfo] = []
