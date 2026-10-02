from datetime import datetime, timedelta

from smart_meeting.llm.analysis import format_timestamp
from smart_meeting.models import AskAnswer, Meeting, MeetingAnalysis, Segment


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "_Aucun._"


def _cell(value: str | None, default: str) -> str:
    return (value or default).replace("|", "\\|").replace("\n", " ")


def build_markdown(
    meeting: Meeting,
    segments: list[Segment],
    analysis: MeetingAnalysis | None,
    questions: list[AskAnswer] | None = None,
) -> str:
    started = datetime.fromisoformat(meeting.started_at).astimezone()
    origin = f" · fichier `{meeting.source_file}`" if meeting.source_file else ""
    lines = [
        f"# {meeting.title or 'Réunion sans titre'}",
        "",
        f"_{started:%d/%m/%Y %H:%M}{origin}_",
        "",
    ]

    if analysis:
        lines += ["## Résumé", "", analysis.summary or "_Aucun._", ""]
        lines += ["## Décisions prises", "", _bullets(analysis.decisions), ""]
        lines += ["## Actions", ""]
        if analysis.actions:
            lines += ["| Action | Responsable | Échéance |", "|---|---|---|"]
            for action in analysis.actions:
                task = _cell(action.task, "")
                if not action.verified:
                    task += " ⚠️ _(non retrouvée dans la transcription)_"
                lines.append(
                    f"| {task} | {_cell(action.owner, 'Non défini')}"
                    f" | {_cell(action.deadline, 'Non définie')} |"
                )
        else:
            lines.append("_Aucune._")
        lines += [""]
        lines += ["## Points techniques", "", _bullets(analysis.technical_topics), ""]
        lines += ["## Questions ouvertes", "", _bullets(analysis.questions), ""]
        lines += ["## Risques", "", _bullets(analysis.risks), ""]

    if questions:
        lines += ["## Questions posées", ""]
        for item in questions:
            lines += [f"**{item.question}**", "", item.answer, ""]

    lines += ["## Transcription", ""]
    for segment in segments:
        if meeting.source_file:  # position in the file
            at = format_timestamp(segment.start_s)
        else:  # wall-clock time
            at = f"{started + timedelta(seconds=segment.start_s):%H:%M:%S}"
        lines.append(f"**{at}** {segment.speaker} : {segment.text}  ")
    return "\n".join(lines).rstrip() + "\n"
