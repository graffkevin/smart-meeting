"""Speed and accuracy of the transcription on this machine.

    uv run python scripts/bench_transcription.py meeting.mp4 --reference script.txt

Settings come from the usual SM_* variables (SM_WHISPER_ENGINE, SM_WHISPER_MODEL…), so two
engines or models are compared by running the script twice. Live mode transcribes the audio cut
at its silences, as in a meeting; file mode is the import of a whole file.
"""

import argparse
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import av
import numpy as np

from smart_meeting.config import Settings
from smart_meeting.transcription.engines import create_transcriber
from smart_meeting.transcription.language import LanguageTracker

SAMPLE_RATE = 16000


def load_audio(path: Path) -> np.ndarray:
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32)


def utterances(audio: np.ndarray, max_s: float = 20.0) -> list[np.ndarray]:
    """Cut at silences of 0.4 s or more (30 ms frames below a fixed energy)."""
    frame = int(0.03 * SAMPLE_RATE)
    energy = np.sqrt(np.mean(audio[: len(audio) // frame * frame].reshape(-1, frame) ** 2, axis=1))
    silent = energy < 0.01
    pieces, start, quiet = [], None, 0
    for index, is_silent in enumerate(silent):
        if not is_silent:
            if start is None:
                start = index
            quiet = 0
        elif start is not None:
            quiet += 1
            too_long = (index - start) * 0.03 >= max_s
            if quiet * 0.03 >= 0.4 or too_long:
                pieces.append(audio[start * frame : (index + 1) * frame])
                start, quiet = None, 0
    if start is not None:
        pieces.append(audio[start * frame :])
    return [p for p in pieces if len(p) >= SAMPLE_RATE // 2]


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", text)


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        previous, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (r != h))
    return row[-1] / max(len(ref), 1)


def run(args: argparse.Namespace) -> None:
    reference = None
    if args.reference:
        # Lines of the generated test meeting are "voice|text"
        lines = args.reference.read_text().splitlines()
        reference = " ".join(line.split("|")[-1] for line in lines)

    audio = load_audio(args.audio)
    duration = len(audio) / SAMPLE_RATE
    transcriber = create_transcriber(Settings())
    started = time.perf_counter()
    transcriber.load()
    print(f"Engine   {transcriber.model_name} ({transcriber.device})")
    print(f"Audio    {duration:.1f} s")
    print(f"Loading  {time.perf_counter() - started:.1f} s")

    def report(name: str, seconds: float, text: str) -> None:
        line = f"{name:<8} {seconds:.1f} s, {duration / seconds:.1f}x real time"
        if reference:
            line += f", word error rate {word_error_rate(reference, text):.1%}"
        print(line)

    tracker = LanguageTracker.for_choice(args.language, fallback="fr")
    pieces = utterances(audio)
    started = time.perf_counter()
    texts = []
    for piece in pieces:
        transcriber.transcribe_partial(piece[: len(piece) // 2], tracker.language)
        texts.extend(p.text for p in transcriber.transcribe(piece, tracker))
    report("Live", time.perf_counter() - started, " ".join(texts))
    print(f"         {len(pieces)} utterances, each with a provisional text of its first half")

    if not args.skip_file:
        language = None if args.language == "auto" else args.language
        texts = []
        started = time.perf_counter()
        transcriber.transcribe_file(audio, language, lambda p: texts.append(p.text) or True)
        report("File", time.perf_counter() - started, " ".join(texts))
        if reference:
            print(f"\n{' '.join(texts)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("audio", type=Path)
    parser.add_argument("--reference", type=Path, help="spoken text, one line per sentence")
    parser.add_argument("--language", default="fr", help="'auto' to detect it")
    parser.add_argument("--skip-file", action="store_true", help="live mode only")
    args = parser.parse_args()
    # A worker thread, like the server's: some engines only work from the thread they loaded in
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(run, args).result()
    # Some native libraries crash while Python tears them down at exit
    os._exit(0)


if __name__ == "__main__":
    main()
