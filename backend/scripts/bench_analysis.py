"""Speed and output of the meeting analysis for several Ollama models, on this machine.

    uv run python scripts/bench_analysis.py meeting.txt qwen2.5:7b qwen2.5:3b --out results/

The transcript has one sentence per line: "mm:ss|Speaker|text". Each model writes the minutes
of the meeting and answers the questions, through the same code as the app; the answers are saved
in --out for comparing their quality.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from smart_meeting.config import Settings
from smart_meeting.llm.analysis import OllamaClient
from smart_meeting.models import Segment

QUESTIONS = [
    "Quel est le budget total du salon, et comment le dépassement est-il financé ?",
    "Qui recontacte les clients touchés par l'incident, et avec quelle offre ?",
]


def load_transcript(path: Path) -> list[Segment]:
    lines = [line.split("|", 2) for line in path.read_text().splitlines() if line.strip()]
    starts = [int(m) * 60 + int(s) for m, s in (t.split(":") for t, _, _ in lines)]
    return [
        Segment(source="remote", speaker=speaker, start_s=start, end_s=end, text=text)
        for (_, speaker, text), start, end in zip(
            lines, starts, [*starts[1:], starts[-1] + 5], strict=True
        )
    ]


async def unload(settings: Settings, model: str) -> None:
    async with httpx.AsyncClient(base_url=settings.ollama_url, timeout=60) as client:
        await client.post("/api/generate", json={"model": model, "keep_alive": 0})


async def run(model: str, segments: list[Segment], out: Path) -> dict:
    settings = Settings(ollama_model=model)
    client = OllamaClient(settings)
    calls = []
    measure = client._measure

    def record(metrics: dict) -> None:
        calls.append({k: metrics.get(k) for k in (
            "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count",
            "eval_duration", "total_duration",
        )})  # fmt: skip
        measure(metrics)

    client._measure = record
    # Loaded once beforehand: the times below are the analysis itself
    await client._chat("Réponds OK.", "OK ?")
    calls.clear()

    started = time.perf_counter()
    analysis = await client.analyze("Réunion d'équipe hebdomadaire", segments)
    analysis_s = time.perf_counter() - started
    answers = []
    for question in QUESTIONS:
        started = time.perf_counter()
        answer = await client.ask("Réunion d'équipe hebdomadaire", segments, question)
        answers.append({"question": question, "answer": answer,
                        "seconds": round(time.perf_counter() - started, 1)})  # fmt: skip
    await unload(settings, model)

    first = calls[0]
    result = {
        "model": model,
        "analysis_s": round(analysis_s, 1),
        "ask_s": [a["seconds"] for a in answers],
        "prompt_tokens": first["prompt_eval_count"],
        "output_tokens": first["eval_count"],
        "read_rate": round(first["prompt_eval_count"] / (first["prompt_eval_duration"] / 1e9)),
        "write_rate": round(first["eval_count"] / (first["eval_duration"] / 1e9), 1),
    }
    name = model.replace(":", "_").replace("/", "_")
    (out / f"{name}.json").write_text(
        json.dumps(
            {**result, "analysis": analysis.model_dump(), "answers": answers},
            ensure_ascii=False,
            indent=2,
        )  # fmt: skip
    )
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("transcript", type=Path)
    parser.add_argument("models", nargs="+")
    parser.add_argument("--out", type=Path, default=Path("analysis-bench"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    segments = load_transcript(args.transcript)
    print(f"{'model':<18} {'minutes':>8} {'questions':>12} {'read':>9} {'write':>9} {'out tok':>8}")
    for model in args.models:
        r = await run(model, segments, args.out)
        questions = "/".join(f"{s:.0f}" for s in r["ask_s"])
        print(
            f"{r['model']:<18} {r['analysis_s']:>7.0f}s {questions:>11}s"
            f" {r['read_rate']:>6} t/s {r['write_rate']:>5} t/s {r['output_tokens']:>8}"
        )


if __name__ == "__main__":
    asyncio.run(main())
