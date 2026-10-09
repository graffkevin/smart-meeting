"""Echo between the two sources: the microphone hearing what the others say (laptop speakers,
no headset, or a virtual input carrying the call). The same sentence, said at the same time,
is then transcribed twice: once as mine, once as theirs; only theirs is kept."""

import re
import unicodedata
from difflib import SequenceMatcher

# Two sentences closer than this in time can be the same one heard twice
WINDOW_S = 4.0
# Shorter sentences ("oui", "d'accord") are said by both sides for real
MIN_WORDS = 3
SIMILAR = 0.6


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"\w+", text)


def is_echo(a: str, b: str) -> bool:
    """Two transcriptions of the same speech (Whisper may differ a little on each copy)."""
    wa, wb = words(a), words(b)
    if min(len(wa), len(wb)) < MIN_WORDS:
        return False
    return SequenceMatcher(None, wa, wb, autojunk=False).ratio() >= SIMILAR


def at_same_time(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """The two (start, end) overlap, give or take WINDOW_S (the text decides then)."""
    return a[0] - WINDOW_S <= b[1] and b[0] - WINDOW_S <= a[1]
