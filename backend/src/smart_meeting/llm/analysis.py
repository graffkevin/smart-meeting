"""Meeting analysis with a local LLM served by Ollama.

Guardrails against invented content:
- JSON schema enforced by Ollama (structured outputs), temperature 0;
- the prompt requires null for anything not explicitly said;
- every action must quote the transcript; owners and deadlines that do not appear in the
  transcript are reset to null, and actions whose quote cannot be found are flagged.
"""

import re
import unicodedata

import httpx

from smart_meeting.config import Settings
from smart_meeting.models import MeetingAnalysis, Segment

SYSTEM_PROMPT = """Tu es un assistant qui rédige le compte rendu d'une réunion professionnelle \
à partir de sa transcription automatique (qui peut contenir des erreurs de reconnaissance).

Règles impératives :
- N'utilise QUE des informations présentes dans la transcription. N'invente rien.
- Décision = choix acté ("on a décidé de…", "on part sur…", "c'est validé"). Une décision va \
dans "decisions", jamais dans "actions", même si elle implique du travail.
- Action = tâche qu'une personne s'engage à faire ou dont elle est chargée ("je vais…", \
"X s'en occupe", "peux-tu…"). Sans tâche à faire par quelqu'un, ce n'est pas une action.
- "owner" : uniquement une personne explicitement désignée ou qui s'engage elle-même \
("je vais…" prononcé par {user_name} => "{user_name}"). Sinon null.
- "deadline" : uniquement une échéance explicitement prononcée, recopiée telle quelle \
(ex. "vendredi", "fin octobre"). Sinon null.
- "quote" : recopie exactement le passage de la transcription qui mentionne l'action.
- Une piste seulement évoquée n'est ni une décision ni une action.
- Listes vides si rien ne correspond. Rédige en français, de manière concise.
- Les interlocuteurs distants sont tous étiquetés "{remote_name}" : ne leur attribue \
pas de nom propre sauf s'ils se nomment explicitement."""

USER_PROMPT = """Titre de la réunion : {title}

Transcription (horodatage depuis le début de la réunion) :
{transcript}"""


ASK_PROMPT = """Tu réponds aux questions sur une réunion professionnelle, à partir de sa \
transcription automatique (qui peut contenir des erreurs de reconnaissance, et peut être en cours).

Règles impératives :
- Réponds UNIQUEMENT avec ce que dit la transcription. Si l'information n'y est pas, dis-le \
simplement, sans inventer.
- La personne qui pose la question est {user_name} : ses propres phrases sont étiquetées \
"{user_name}". "je", "moi", "mes" désignent {user_name}.
- Les autres participants sont étiquetés "{remote_name}".
- Sois exhaustif : relis toute la transcription. Pour une question sur des tâches, actions ou \
décisions, liste CHACUNE d'elles, une par ligne commençant par "- ", même si elles sont dispersées.
- Termine chaque point par l'horodatage [hh:mm:ss] du passage sur lequel il s'appuie.
- Réponds en français, de façon concise, en t'adressant directement à {user_name} ("vous")."""

ASK_USER_PROMPT = """Titre de la réunion : {title}

Transcription :
{transcript}

Question : {question}"""


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
EXPECTED_OUTPUT_TOKENS = {"ask": 200, "analysis": 700}
LOAD_ESTIMATE_S = 4.0  # model loaded into memory before the first answer
SPEED_SMOOTHING = 0.5  # weight of the last measure in the running speeds


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Tokens per second, starting from a modest laptop GPU, then measured.
        self.prompt_rate = 400.0
        self.eval_rate = 12.0

    def estimate_s(self, transcript_chars: int, kind: str) -> float:
        """Expected duration of a question ("ask") or a report ("analysis"), in seconds."""
        prompt_tokens = transcript_chars / CHARS_PER_TOKEN + PROMPT_OVERHEAD_TOKENS
        return (
            LOAD_ESTIMATE_S
            + prompt_tokens / self.prompt_rate
            + EXPECTED_OUTPUT_TOKENS[kind] / self.eval_rate
        )

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
        return {"user_name": self.settings.user_name, "remote_name": self.settings.remote_name}

    async def analyze(self, title: str, segments: list[Segment]) -> MeetingAnalysis:
        transcript = format_transcript(segments)
        content = await self._chat(
            SYSTEM_PROMPT.format(**self._names()),
            USER_PROMPT.format(title=title or "(sans titre)", transcript=transcript),
            response_format=analysis_schema(),
        )
        analysis = MeetingAnalysis.model_validate_json(content)
        return ground_analysis(analysis, transcript, self.settings.user_name)

    async def ask(self, title: str, segments: list[Segment], question: str) -> str:
        """Answer a question about the meeting, from its transcript only (it may be in progress)."""
        return (
            await self._chat(
                ASK_PROMPT.format(**self._names()),
                ASK_USER_PROMPT.format(
                    title=title or "(sans titre)",
                    transcript=format_transcript(segments),
                    question=question,
                ),
            )
        ).strip()
