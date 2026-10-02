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
    created_at: str


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


class UpdateMeetingRequest(BaseModel):
    title: str


class CapturedDevice(BaseModel):
    device: str | None
    auto: bool


class MeetingDetail(BaseModel):
    meeting: Meeting
    segments: list[Segment]
    analysis: MeetingAnalysis | None
    has_audio: bool
    # Devices being captured, while recording.
    captured: dict[Source, CapturedDevice] | None = None


class Health(BaseModel):
    whisper: Literal["loading", "ready", "error"]
    whisper_detail: str | None
    ollama: bool
    ollama_model: str
    ollama_model_available: bool
    active_meeting_id: int | None
