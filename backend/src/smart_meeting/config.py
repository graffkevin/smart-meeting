from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from platformdirs import user_config_path, user_data_path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
APP_NAME = "smart-meeting"
# Linux: ~/.config/smart-meeting/config.env ; macOS: ~/Library/Application Support/... ;
# Windows: %LOCALAPPDATA%\smart-meeting\...
CONFIG_FILE = user_config_path(APP_NAME, appauthor=False) / "config.env"


class Settings(BaseSettings):
    """Application settings, overridable with SM_* environment variables or a .env file."""

    model_config = SettingsConfigDict(
        env_prefix="SM_",
        # User config, then a local .env for development (later files win).
        env_file=(CONFIG_FILE, ".env"),
        extra="ignore",
    )

    data_dir: Path = user_data_path(APP_NAME, appauthor=False)
    # Unusual default: 8000 is often taken by other FastAPI projects.
    port: int = 8417

    # Speaker labels. Mic and remote audio are captured separately, which gives
    # a free two-way diarization: "me" vs "the others".
    user_name: str = "Moi"
    # Language of the interface, of the AI answers and of the minutes (fr, en)
    ui_language: str = "fr"
    remote_name: str = "Interlocuteur"
    import_speaker: str = "Intervenant"  # imported files: a single mixed track

    # Audio
    sample_rate: int = 16000

    # Utterance segmentation (Silero VAD)
    vad_threshold: float = 0.5
    vad_min_silence_ms: int = 700
    vad_max_utterance_s: float = 20.0
    # A Whisper computation longer than this during a meeting means it is stuck: the server
    # restarts itself and resumes the meeting (a sentence takes a few seconds at most).
    stall_restart_s: float = 90.0

    # Whisper
    # auto: large-v3-turbo with an NVIDIA GPU, small on CPU (Mac, PC without GPU) to keep up
    # with live meetings.
    whisper_model: str = "auto"
    whisper_device: str = "auto"  # auto | cuda | cpu
    whisper_compute_type: str = "auto"  # auto | int8_float16 | int8 | float16 ...
    # Live provisional text (the sentence being spoken): auto = "small" next to a larger model on
    # GPU (fast drafts), the main model otherwise; "none" disables it.
    whisper_partial_model: str = "auto"
    # Transcription language offered by default: "auto" (sticky detection) or a code (fr, en…).
    whisper_language: str = "auto"
    # Automatic mode: language assumed until a first clear detection.
    whisper_fallback_language: str = "fr"
    whisper_beam_size: int = 5
    # Domain vocabulary fed to Whisper as prompt, helps with technical/English terms.
    whisper_glossary: str = ""
    # Also give Whisper the previous sentence: better continuity, but its errors spread.
    whisper_previous_context: bool = False

    # Ollama
    ollama_url: str = "http://127.0.0.1:11434"
    # Started by the launcher when Ollama is not already running (defaults to PATH lookup).
    ollama_bin: str | None = None
    ollama_model: str = "qwen2.5:7b"
    ollama_num_ctx: int = 16384
    ollama_timeout_s: float = 900.0
    # Safety net: transcripts must never leave the machine unless explicitly allowed.
    allow_remote_llm: bool = False

    @field_validator("data_dir")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "smart-meeting.db"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    def check_privacy(self) -> None:
        host = urlparse(self.ollama_url).hostname
        if host not in LOOPBACK_HOSTS and not self.allow_remote_llm:
            raise ValueError(
                f"SM_OLLAMA_URL points to {host!r}, which is not local. "
                "Set SM_ALLOW_REMOTE_LLM=true to allow sending transcripts there."
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check_privacy()
    return settings
