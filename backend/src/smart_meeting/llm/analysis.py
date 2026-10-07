"""Meeting analysis with a local LLM served by Ollama.

Guardrails against invented content:
- JSON schema enforced by Ollama (structured outputs), temperature 0;
- the prompt requires null for anything not explicitly said;
- every action must quote the transcript; owners and deadlines that do not appear in the
  transcript are reset to null, and actions whose quote cannot be found are flagged.
"""

import hashlib
import json
import logging
import math
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

import httpx

from smart_meeting.config import CONFIG_FILE, Settings
from smart_meeting.db import Database
from smart_meeting.models import MeetingAnalysis, Segment

# Prompts: Markdown files next to this module, read at each call (edits apply without restart).
# A file of the same name in the user config folder replaces the default one.
PROMPTS_DIR = Path(__file__).parent / "prompts"
USER_PROMPTS_DIR = CONFIG_FILE.parent / "prompts"


def prompt(name: str) -> str:
    """Template `name` (e.g. "analysis_system"), without its leading HTML comment."""
    custom = USER_PROMPTS_DIR / f"{name}.md"
    text = (custom if custom.exists() else PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return re.sub(r"\A\s*<!--.*?-->\s*", "", text, flags=re.S).strip()


ANSWER_LANGUAGES = {"fr": "français", "en": "anglais (English)"}


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def format_transcript(segments: list[Segment]) -> str:
    return "\n".join(f"[{format_timestamp(s.start_s)}] {s.speaker}: {s.text}" for s in segments)


def analysis_schema() -> dict:
    schema = MeetingAnalysis.model_json_schema()
    action = schema["$defs"]["ActionItem"]
    action["properties"].pop("verified")
    # The model must always justify an action with a quote (never null).
    quote = action["properties"]["quote"]
    action["properties"]["quote"] = {"type": "string", "description": quote["description"]}
    action["required"] = ["task", "owner", "deadline", "quote"]
    return schema


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", text).strip()


def _quote_found(quote: str, normalized_transcript: str) -> bool:
    words = _normalize(quote).split()
    if not words:
        return False
    if " ".join(words) in normalized_transcript:
        return True
    # Tolerate light rewording: most of the quote's words must appear in the transcript.
    transcript_words = set(normalized_transcript.split())
    return sum(w in transcript_words for w in words) / len(words) >= 0.8


def ground_analysis(analysis: MeetingAnalysis, transcript: str, user_name: str) -> MeetingAnalysis:
    """Remove owners/deadlines that were not said, flag actions without a verifiable quote."""
    normalized = f" {_normalize(transcript)} "
    allowed_owners = {_normalize(user_name), "moi"}
    actions = []
    for action in analysis.actions:
        owner = action.owner
        if owner and _normalize(owner) not in allowed_owners:
            owner_words = _normalize(owner).split()
            if not any(f" {w} " in normalized for w in owner_words if len(w) > 2):
                owner = None
        deadline = action.deadline
        if deadline and f" {_normalize(deadline)} " not in normalized:
            deadline = None
        # Evidence: the quote, or a task copied verbatim from the transcript.
        verified = any(
            text and _quote_found(text, normalized) for text in (action.quote, action.task)
        )
        actions.append(
            action.model_copy(update={"owner": owner, "deadline": deadline, "verified": verified})
        )
    return analysis.model_copy(update={"actions": actions})


# Duration estimates of the local AI, refined after each call with the speeds Ollama reports.
CHARS_PER_TOKEN = 3.5  # French text
PROMPT_OVERHEAD_TOKENS = 600  # instructions and JSON schema
EXPECTED_OUTPUT_TOKENS = {"ask": 200, "analysis": 700, "notes": 300, "summary": 250}
# Room kept in the context for the answer, and margin on the characters-per-token ratio.
RESERVED_OUTPUT_TOKENS = {"ask": 1000, "analysis": 2000}
CONTEXT_MARGIN = 0.9
# Long meeting, questions: old parts become notes, the part in progress is read word for word.
# A part is this share of the context, which leaves room for the notes of about 3 hours.
NOTES_PART_SHARE = 0.6
LOAD_ESTIMATE_S = 4.0  # model loaded into memory before the first answer
SPEED_SMOOTHING = 0.5  # weight of the last measure in the running speeds


def split_transcript(segments: list[Segment], max_chars: int) -> list[list[Segment]]:
    """Consecutive parts of at most `max_chars` of transcript (whole sentences). The parts of a
    growing meeting stay the same: only the last one changes."""
    parts: list[list[Segment]] = [[]]
    size = 0
    for segment in segments:
        line = len(format_transcript([segment])) + 1
        if parts[-1] and size + line > max_chars:
            parts.append([])
            size = 0
        parts[-1].append(segment)
        size += line
    return parts


def _span(part: list[Segment]) -> dict[str, str]:
    return {"start": format_timestamp(part[0].start_s), "end": format_timestamp(part[-1].end_s)}


def _unique(items: list, key: Callable[[object], str]) -> list:
    seen: set[str] = set()
    kept = []
    for item in items:
        if (k := key(item)) not in seen:
            seen.add(k)
            kept.append(item)
    return kept


def merge_analyses(parts: list[MeetingAnalysis], summary: str) -> MeetingAnalysis:
    """The analyses of the parts of a long meeting as one, without repeated items."""
    lists = {
        name: _unique([i for p in parts for i in getattr(p, name)], _normalize)
        for name in ("decisions", "questions", "risks", "technical_topics")
    }
    actions = _unique(
        [a for p in parts for a in p.actions], lambda a: _normalize(f"{a.task} {a.owner or ''}")
    )
    return MeetingAnalysis(summary=summary, actions=actions, **lists)


class NotesCache:
    """Notes on the old parts of a meeting, kept between questions (by digest of the part).
    This one forgets them; the service keeps them in the database."""

    def get(self, digest: str) -> str | None:
        return None

    def put(self, digest: str, notes: str) -> None:
        pass


class MeetingNotes(NotesCache):
    def __init__(self, db: Database, meeting_id: int) -> None:
        self.db, self.meeting_id = db, meeting_id

    def get(self, digest: str) -> str | None:
        return self.db.get_note(self.meeting_id, digest)

    def put(self, digest: str, notes: str) -> None:
        self.db.save_note(self.meeting_id, digest, notes)


logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Tokens per second: measured on this computer, kept between launches (ai-speed.json);
        # the first time, a model mostly on the CPU (a 7B model does not fit in 4 GB of GPU).
        self.prompt_rate = 80.0
        self.eval_rate = 5.0
        self._speeds_path = settings.data_dir / "ai-speed.json"
        try:
            saved = json.loads(self._speeds_path.read_text(encoding="utf-8"))
            if saved.get("model") == settings.ollama_model:
                self.prompt_rate = float(saved["prompt_rate"])
                self.eval_rate = float(saved["eval_rate"])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def budget_chars(self, kind: str) -> int:
        """Transcript characters that fit in the context of the model, for this kind of call."""
        tokens = (
            self.settings.ollama_num_ctx - PROMPT_OVERHEAD_TOKENS - RESERVED_OUTPUT_TOKENS[kind]
        )
        return int(tokens * CHARS_PER_TOKEN * CONTEXT_MARGIN)

    def estimate_s(self, transcript_chars: int, kind: str, notes_chars: int = 0) -> float:
        """Expected duration of a question ("ask") or a report ("analysis"), in seconds. A long
        report is written part by part, then summed up; `notes_chars`: old parts of the meeting
        still to turn into notes before a question."""
        parts = 1
        output_tokens = EXPECTED_OUTPUT_TOKENS[kind]
        if kind == "analysis" and transcript_chars > self.budget_chars("analysis"):
            parts = math.ceil(transcript_chars / self.budget_chars("analysis"))
            output_tokens = parts * output_tokens + EXPECTED_OUTPUT_TOKENS["summary"]
        if notes_chars:
            notes = math.ceil(notes_chars / self.notes_part_chars())
            parts += notes
            output_tokens += notes * EXPECTED_OUTPUT_TOKENS["notes"]
        prompt_tokens = (transcript_chars + notes_chars) / CHARS_PER_TOKEN
        return (
            LOAD_ESTIMATE_S
            + (prompt_tokens + parts * PROMPT_OVERHEAD_TOKENS) / self.prompt_rate
            + output_tokens / self.eval_rate
        )

    def notes_part_chars(self) -> int:
        return int(self.budget_chars("ask") * NOTES_PART_SHARE)

    def _measure(self, metrics: dict) -> None:
        """Running speeds from the counters of an Ollama answer (durations in nanoseconds)."""
        for count, duration, attribute in (
            ("prompt_eval_count", "prompt_eval_duration", "prompt_rate"),
            ("eval_count", "eval_duration", "eval_rate"),
        ):
            tokens, nanoseconds = metrics.get(count), metrics.get(duration)
            if tokens and nanoseconds and tokens > 20:
                measured = tokens / (nanoseconds / 1e9)
                current = getattr(self, attribute)
                setattr(self, attribute, current + SPEED_SMOOTHING * (measured - current))
        speeds = {
            "model": self.settings.ollama_model,
            "prompt_rate": round(self.prompt_rate, 1),
            "eval_rate": round(self.eval_rate, 2),
        }
        try:
            self._speeds_path.parent.mkdir(parents=True, exist_ok=True)
            self._speeds_path.write_text(json.dumps(speeds), encoding="utf-8")
        except OSError:
            logger.warning("Could not save the AI speeds", exc_info=True)

    def _client(self, timeout: float) -> httpx.AsyncClient:
        # trust_env=False: never route transcripts through the HTTP proxy from the environment.
        return httpx.AsyncClient(
            base_url=self.settings.ollama_url, timeout=timeout, trust_env=False
        )

    async def available_models(self) -> list[str] | None:
        """Installed model names, or None if Ollama is unreachable."""
        try:
            async with self._client(timeout=3) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
        except httpx.HTTPError:
            return None
        return [m["name"] for m in response.json().get("models", [])]

    async def _chat(self, system: str, user: str, response_format: dict | None = None) -> str:
        payload = {
            "model": self.settings.ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.settings.ollama_num_ctx},
        }
        if response_format is not None:
            payload["format"] = response_format
        async with self._client(timeout=self.settings.ollama_timeout_s) as client:
            response = await client.post("/api/chat", json=payload)
        if response.is_error:
            try:
                detail = response.json()["error"]
            except (ValueError, KeyError):
                detail = response.text
            raise RuntimeError(f"Ollama ({response.status_code}) : {detail}")
        body = response.json()
        self._measure(body)
        return body["message"]["content"]

    def _names(self) -> dict[str, str]:
        return {
            "user_name": self.settings.user_name,
            "remote_name": self.settings.remote_name,
            # Answers and minutes in the interface language
            "answer_language": ANSWER_LANGUAGES.get(self.settings.ui_language, "français"),
        }

    async def analyze(self, title: str, segments: list[Segment]) -> MeetingAnalysis:
        """Minutes of the meeting. Longer than the context: each part is analyzed on its own, the
        lists are merged and the summaries of the parts summed up in one."""
        title = title or "(sans titre)"
        transcript = format_transcript(segments)
        system = prompt("analysis_system").format(**self._names())
        parts = split_transcript(segments, self.budget_chars("analysis"))
        if len(parts) == 1:
            user = prompt("analysis_user").format(title=title, transcript=transcript)
            content = await self._chat(system, user, response_format=analysis_schema())
            analysis = MeetingAnalysis.model_validate_json(content)
            return ground_analysis(analysis, transcript, self.settings.user_name)
        analyses = []
        for number, part in enumerate(parts, 1):
            user = prompt("analysis_part").format(
                title=title, part=number, parts=len(parts), transcript=format_transcript(part),
                **_span(part),
            )  # fmt: skip
            content = await self._chat(system, user, response_format=analysis_schema())
            analyses.append(MeetingAnalysis.model_validate_json(content))
        summaries = "\n\n".join(
            "{start} - {end} :\n".format(**_span(part)) + analysis.summary
            for part, analysis in zip(parts, analyses, strict=True)
        )
        summary = await self._chat(
            prompt("summary_system").format(**self._names()),
            prompt("summary_user").format(title=title, summaries=summaries),
        )
        merged = merge_analyses(analyses, summary.strip())
        return ground_analysis(merged, transcript, self.settings.user_name)

    def old_parts(self, segments: list[Segment]) -> tuple[list[list[Segment]], list[Segment]]:
        """A long meeting for a question: its old parts (read as notes), and the recent one."""
        if len(format_transcript(segments)) <= self.budget_chars("ask"):
            return [], segments
        *old, recent = split_transcript(segments, self.notes_part_chars())
        return old, recent

    def _notes_digest(self, title: str, part: list[Segment]) -> str:
        # A renamed speaker or an edited prompt changes the digest: the notes are written again.
        text = "\n".join((prompt("notes_system"), title, format_transcript(part)))
        return hashlib.sha256(text.encode()).hexdigest()

    def missing_notes_chars(self, title: str, segments: list[Segment], cache: NotesCache) -> int:
        """Transcript of the old parts not yet turned into notes (duration of the next question)."""
        old, _ = self.old_parts(segments)
        return sum(
            len(format_transcript(part))
            for part in old
            if cache.get(self._notes_digest(title, part)) is None
        )

    async def _notes(self, title: str, part: list[Segment], cache: NotesCache) -> str:
        digest = self._notes_digest(title, part)
        notes = cache.get(digest)
        if notes is None:
            notes = (
                await self._chat(
                    prompt("notes_system").format(**self._names()),
                    prompt("notes_user").format(
                        title=title, transcript=format_transcript(part), **_span(part)
                    ),
                )
            ).strip()
            cache.put(digest, notes)
        return notes

    async def ask(
        self, title: str, segments: list[Segment], question: str, cache: NotesCache | None = None
    ) -> str:
        """Answer a question about the meeting, from its transcript only (it may be in progress).
        Longer than the context: the old parts are given as notes, written once and kept."""
        title = title or "(sans titre)"
        old, recent = self.old_parts(segments)
        transcript = format_transcript(recent)
        if old:
            cache = cache or NotesCache()
            notes = [
                "### {start} - {end}\n".format(**_span(part))
                + await self._notes(title, part, cache)
                for part in old
            ]
            transcript = "\n\n".join(
                [
                    "Notes sur les parties anciennes de la réunion :",
                    *notes,
                    "Transcription mot à mot depuis {start} :".format(**_span(recent)),
                    transcript,
                ]
            )
        return (
            await self._chat(
                prompt("ask_system").format(**self._names()),
                prompt("ask_user").format(title=title, transcript=transcript, question=question),
            )
        ).strip()
