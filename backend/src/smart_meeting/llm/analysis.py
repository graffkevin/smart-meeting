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
- Une action n'est retenue que si quelqu'un s'engage ou est chargé explicitement de la faire.
- "owner" : uniquement une personne explicitement désignée ou qui s'engage elle-même \
("je vais…" prononcé par {user_name} => "{user_name}"). Sinon null.
- "deadline" : uniquement une échéance explicitement prononcée, recopiée telle quelle \
(ex. "vendredi", "fin octobre"). Sinon null.
- "quote" : recopie exactement le passage de la transcription qui mentionne l'action.
- Les décisions sont des choix actés pendant la réunion, pas des pistes évoquées.
- Listes vides si rien ne correspond. Rédige en français, de manière concise.
- Les interlocuteurs distants sont tous étiquetés "{remote_name}" : ne leur attribue \
pas de nom propre sauf s'ils se nomment explicitement."""

USER_PROMPT = """Titre de la réunion : {title}

Transcription (horodatage depuis le début de la réunion) :
{transcript}"""


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def format_transcript(segments: list[Segment]) -> str:
    return "\n".join(f"[{format_timestamp(s.start_s)}] {s.speaker}: {s.text}" for s in segments)


def analysis_schema() -> dict:
    schema = MeetingAnalysis.model_json_schema()
    action = schema["$defs"]["ActionItem"]
    action["properties"].pop("verified")
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
        verified = bool(action.quote) and _quote_found(action.quote, normalized)
        actions.append(
            action.model_copy(update={"owner": owner, "deadline": deadline, "verified": verified})
        )
    return analysis.model_copy(update={"actions": actions})


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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

    async def analyze(self, title: str, segments: list[Segment]) -> MeetingAnalysis:
        transcript = format_transcript(segments)
        system = SYSTEM_PROMPT.format(
            user_name=self.settings.user_name, remote_name=self.settings.remote_name
        )
        payload = {
            "model": self.settings.ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": USER_PROMPT.format(
                        title=title or "(sans titre)", transcript=transcript
                    ),
                },
            ],
            "format": analysis_schema(),
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.settings.ollama_num_ctx},
        }
        async with self._client(timeout=self.settings.ollama_timeout_s) as client:
            response = await client.post("/api/chat", json=payload)
        if response.is_error:
            try:
                detail = response.json()["error"]
            except (ValueError, KeyError):
                detail = response.text
            raise RuntimeError(f"Ollama ({response.status_code}) : {detail}")
        content = response.json()["message"]["content"]
        analysis = MeetingAnalysis.model_validate_json(content)
        return ground_analysis(analysis, transcript, self.settings.user_name)
