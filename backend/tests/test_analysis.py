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


def test_estimates_grow_with_the_transcript_and_learn_the_speed():
    from smart_meeting.config import Settings
    from smart_meeting.llm.analysis import OllamaClient

    client = OllamaClient(Settings())
    short, long = client.estimate_s(1_000, "ask"), client.estimate_s(50_000, "ask")
    assert long > short > 0
    assert client.estimate_s(1_000, "analysis") > short
    # A faster machine measured: estimates go down
    client._measure(
        {
            "prompt_eval_count": 4000,
            "prompt_eval_duration": 2e9,
            "eval_count": 300,
            "eval_duration": 5e9,
        }
    )
    assert client.estimate_s(50_000, "ask") < long


def test_prompts_come_from_markdown_files_that_the_user_can_replace(monkeypatch, tmp_path):
    from smart_meeting.llm import analysis

    default = analysis.prompt("ask_user")
    assert default.startswith("Titre de la réunion : {title}")  # header comment removed
    monkeypatch.setattr(analysis, "USER_PROMPTS_DIR", tmp_path)
    (tmp_path / "ask_user.md").write_text("<!-- mine -->\nQ : {question}", encoding="utf-8")
    assert analysis.prompt("ask_user") == "Q : {question}"


def long_meeting(minutes: int):
    from smart_meeting.models import Segment

    # About one sentence of 120 characters every 6 s, like a busy meeting
    return [
        Segment(source="remote", speaker="Intervenant 1", start_s=i * 6, end_s=i * 6 + 5,
                text=f"Phrase {i} " + "x" * 110)
        for i in range(minutes * 10)
    ]  # fmt: skip


def fake_client(monkeypatch, answers):
    from smart_meeting.config import Settings
    from smart_meeting.llm.analysis import OllamaClient

    client = OllamaClient(Settings(ollama_num_ctx=16384))
    calls = []

    async def chat(system, user, response_format=None):
        calls.append(user)
        return answers(user, response_format)

    monkeypatch.setattr(client, "_chat", chat)
    return client, calls


def test_split_transcript_keeps_old_parts_when_the_meeting_grows():
    from smart_meeting.llm.analysis import split_transcript

    before = split_transcript(long_meeting(60), 20000)
    after = split_transcript(long_meeting(90), 20000)
    assert len(before) > 1
    assert after[: len(before) - 1] == before[:-1]


def test_a_long_meeting_is_analyzed_part_by_part(monkeypatch):
    import asyncio
    import json

    def answers(user, response_format):
        if response_format is None:
            return "Résumé de toute la réunion."
        part = user.split("partie ")[1].split(" ")[0]
        action = {"task": "Rédiger la note", "owner": None, "deadline": None, "quote": "Phrase 1"}
        return json.dumps({
            "summary": f"Partie {part}.", "decisions": [f"Décision {part}", "Commune"],
            "actions": [action], "questions": [], "risks": [], "technical_topics": [],
        })  # fmt: skip

    client, calls = fake_client(monkeypatch, answers)
    analysis = asyncio.run(client.analyze("Point", long_meeting(180)))
    parts = len(calls) - 1  # then one summary call
    assert parts >= 4
    assert analysis.summary == "Résumé de toute la réunion."
    assert analysis.decisions[:2] == ["Décision 1", "Commune"]
    assert len(analysis.decisions) == parts + 1  # "Commune" only once
    assert len(analysis.actions) == 1
    assert "Partie 1." in calls[-1] and f"Partie {parts}." in calls[-1]


def test_questions_on_a_long_meeting_reuse_the_notes_of_old_parts(monkeypatch):
    import asyncio

    from smart_meeting.llm.analysis import NotesCache

    class Memory(NotesCache):
        def __init__(self):
            self.notes = {}

        def get(self, digest):
            return self.notes.get(digest)

        def put(self, digest, notes):
            self.notes[digest] = notes

    client, calls = fake_client(
        monkeypatch, lambda user, _: "- notes" if "Transcription de" in user else "Réponse"
    )
    cache = Memory()
    segments = long_meeting(120)
    assert client.missing_notes_chars("Point", segments, cache) > 0
    assert asyncio.run(client.ask("Point", segments, "Mes actions ?", cache)) == "Réponse"
    notes_calls = len(calls) - 1
    assert notes_calls >= 2
    assert "Notes sur les parties anciennes" in calls[-1]
    assert len(calls[-1]) < client.budget_chars("ask") + 2000
    assert client.missing_notes_chars("Point", segments, cache) == 0
    asyncio.run(client.ask("Point", segments, "Et les décisions ?", cache))
    assert len(calls) == notes_calls + 2  # no new notes
