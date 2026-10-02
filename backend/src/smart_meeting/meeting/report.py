from datetime import datetime, timedelta

from smart_meeting.llm.analysis import format_timestamp
from smart_meeting.models import AskAnswer, Meeting, MeetingAnalysis, Segment

# Texts of the Markdown report, in the interface language
LABELS = {
    "fr": {
        "untitled": "Réunion sans titre",
        "file": "fichier",
        "none": "_Aucun._",
        "summary": "Résumé",
        "decisions": "Décisions prises",
        "actions": "Actions",
        "table": "| Action | Responsable | Échéance |",
        "unverified": "⚠️ _(non retrouvée dans la transcription)_",
        "no_owner": "Non défini",
        "no_deadline": "Non définie",
        "topics": "Points techniques",
        "questions": "Questions ouvertes",
        "risks": "Risques",
        "asked": "Questions posées",
        "transcript": "Transcription",
        "date": "%d/%m/%Y %H:%M",
    },
    "en": {
        "untitled": "Untitled meeting",
        "file": "file",
        "none": "_None._",
        "summary": "Summary",
        "decisions": "Decisions",
        "actions": "Actions",
        "table": "| Action | Owner | Deadline |",
        "unverified": "⚠️ _(not found in the transcript)_",
        "no_owner": "Not set",
        "no_deadline": "Not set",
        "topics": "Technical topics",
        "questions": "Open questions",
        "risks": "Risks",
        "asked": "Questions asked",
        "transcript": "Transcript",
        "date": "%Y-%m-%d %H:%M",
    },
}


def _bullets(items: list[str], none: str) -> str:
    return "\n".join(f"- {item}" for item in items) if items else none


def _cell(value: str | None, default: str) -> str:
    return (value or default).replace("|", "\\|").replace("\n", " ")


def build_markdown(
    meeting: Meeting,
    segments: list[Segment],
    analysis: MeetingAnalysis | None,
    questions: list[AskAnswer] | None = None,
    language: str = "fr",
) -> str:
    text = LABELS.get(language, LABELS["fr"])
    none = text["none"]
    started = datetime.fromisoformat(meeting.started_at).astimezone()
    origin = f" · {text['file']} `{meeting.source_file}`" if meeting.source_file else ""
    lines = [
        f"# {meeting.title or text['untitled']}",
        "",
        f"_{started:{text['date']}}{origin}_",
        "",
    ]

    if analysis:
        lines += [f"## {text['summary']}", "", analysis.summary or none, ""]
        lines += [f"## {text['decisions']}", "", _bullets(analysis.decisions, none), ""]
        lines += [f"## {text['actions']}", ""]
        if analysis.actions:
            lines += [text["table"], "|---|---|---|"]
            for action in analysis.actions:
                task = _cell(action.task, "")
                if not action.verified:
                    task += f" {text['unverified']}"
                lines.append(
                    f"| {task} | {_cell(action.owner, text['no_owner'])}"
                    f" | {_cell(action.deadline, text['no_deadline'])} |"
                )
        else:
            lines.append(none)
        lines += [""]
        lines += [f"## {text['topics']}", "", _bullets(analysis.technical_topics, none), ""]
        lines += [f"## {text['questions']}", "", _bullets(analysis.questions, none), ""]
        lines += [f"## {text['risks']}", "", _bullets(analysis.risks, none), ""]

    if questions:
        lines += [f"## {text['asked']}", ""]
        for item in questions:
            lines += [f"**{item.question}**", "", item.answer, ""]

    lines += [f"## {text['transcript']}", ""]
    for segment in segments:
        if meeting.source_file:  # position in the file
            at = format_timestamp(segment.start_s)
        else:  # wall-clock time
            at = f"{started + timedelta(seconds=segment.start_s):%H:%M:%S}"
        lines.append(f"**{at}** {segment.speaker} : {segment.text}  ")
    return "\n".join(lines).rstrip() + "\n"
