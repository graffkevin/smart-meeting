from smart_meeting.llm.analysis import analysis_schema, ground_analysis
from smart_meeting.models import ActionItem, MeetingAnalysis
from smart_meeting.transcription.whisper import is_hallucination

TRANSCRIPT = """[00:00:04] Interlocuteur: Il faudrait intégrer le simulateur dans le démonstrateur.
[00:00:12] Moi: Je vais regarder comment exposer le script Python via l'API d'ici vendredi.
[00:00:20] Interlocuteur: Benoît s'occupe de la note d'architecture."""


def analysis(*actions: ActionItem) -> MeetingAnalysis:
    return MeetingAnalysis(
        summary="",
        decisions=[],
        actions=list(actions),
        questions=[],
        risks=[],
        technical_topics=[],
    )


def test_grounding_keeps_said_owner_and_deadline():
    result = ground_analysis(
        analysis(
            ActionItem(
                task="Exposer le script",
                owner="Moi",
                deadline="vendredi",
                quote="je vais regarder comment exposer le script Python via l'API",
            )
        ),
        TRANSCRIPT,
        "Moi",
    )
    action = result.actions[0]
    assert (action.owner, action.deadline, action.verified) == ("Moi", "vendredi", True)


def test_grounding_removes_invented_owner_and_deadline():
    result = ground_analysis(
        analysis(
            ActionItem(
                task="Intégrer le simulateur",
                owner="Kevin",
                deadline="15 octobre",
                quote="intégrer le simulateur dans le démonstrateur",
            ),
            ActionItem(
                task="Note d'archi", owner="Benoit", deadline=None, quote="Benoît rédige la note"
            ),
            ActionItem(
                task="Inventée",
                owner=None,
                deadline=None,
                quote="on livrera la v2 en décembre au client",
            ),
        ),
        TRANSCRIPT,
        "Moi",
    )
    first, second, third = result.actions
    assert (first.owner, first.deadline, first.verified) == (None, None, True)
    assert second.owner == "Benoit"  # accent-insensitive match
    assert third.verified is False


def test_schema_hides_backend_fields():
    action = analysis_schema()["$defs"]["ActionItem"]
    assert "verified" not in action["properties"]
    assert set(action["required"]) == {"task", "owner", "deadline", "quote"}
    assert action["properties"]["quote"]["type"] == "string"  # never null


def test_verbatim_task_counts_as_evidence():
    result = ground_analysis(
        analysis(
            ActionItem(
                task="Benoît s'occupe de la note d'architecture",
                owner="Benoît",
                deadline=None,
                quote=None,
            )
        ),
        TRANSCRIPT,
        "Moi",
    )
    assert result.actions[0].verified


def test_hallucination_filter():
    assert is_hallucination("Sous-titres réalisés par la communauté d'Amara.org", 0.1, -0.2)
    assert is_hallucination("  ", 0.0, 0.0)
    assert is_hallucination("Merci.", 0.9, -1.5)
    assert not is_hallucination("Merci.", 0.1, -0.3)
