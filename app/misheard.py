"""What speech-to-text gets wrong on our calls, learned from transcripts people corrected (recordings.save_edits).

A corrected line keeps what was heard ("heard") beside what was said ("text"). Comparing the two word by word
gives:
- word errors per recording (word error rate, shown on the recordings page), and
- the words misheard again and again ("डीएमटी" -> "DMT"). Those go into the prompts of the live agent, the call
  review and the summary, so the LLM reads past them. Not into Whisper's own hint: Whisper copies hint text
  into transcripts (see recordings.STT_PROMPT).

Pairs that carry a number of three or more digits are left out: they are values (amounts, IDs), not words.
"""
import json
import os
import re
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from . import db

MIN_COUNT = int(os.environ.get("MISHEARD_MIN_COUNT", "2"))   # seen this often before it goes into prompts
MAX_PAIR_WORDS = 3          # longer replacements are rewrites, not a misheard word
HINT_PAIRS = 25
_PUNCT = ".,?!।|\"'()[]{}:;-–—…“”‘’"
_cache: dict = {"at": 0.0, "pairs": None}


def tokens(text: str) -> list[str]:
    return [w for w in (t.strip(_PUNCT) for t in (text or "").split()) if w]


def _distance(a: list[str], b: list[str]) -> int:
    """Word-level Levenshtein distance (lines are short: a few dozen words)."""
    a, b = [w.lower() for w in a], [w.lower() for w in b]
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb)))
        prev = cur
    return prev[-1]


def word_errors(lines: list[dict], removed: list[dict]) -> tuple[int, int]:
    """(word errors, words actually said) for a checked transcript. A removed line was made up: all its words are
    errors. Lines are compared one by one, as their times tie the heard and corrected versions together."""
    errors, words = 0, 0
    for l in lines:
        said = tokens(l["text"])
        words += len(said)
        if "heard" in l:
            errors += _distance(tokens(l["heard"]), said)
    errors += sum(len(tokens(l.get("heard", l["text"]))) for l in removed)
    return errors, words


def _pairs_in(heard: str, said: str):
    h, s = tokens(heard), tokens(said)
    ops = SequenceMatcher(None, [w.lower() for w in h], [w.lower() for w in s], autojunk=False).get_opcodes()
    for op, i1, i2, j1, j2 in ops:
        if op != "replace" or i2 - i1 > MAX_PAIR_WORDS or j2 - j1 > MAX_PAIR_WORDS:
            continue
        a, b = " ".join(h[i1:i2]), " ".join(s[j1:j2])
        if re.search(r"\d{3}|\[", a + b):      # values (amounts, IDs) and masked numbers: not vocabulary
            continue
        yield a, b


def pairs(min_count: int = 1, limit: int = 200, rm_id: int | None = None) -> list[dict]:
    """Misheard words across every corrected transcript (or one RM's), most frequent first:
    [{"heard", "said", "count", "calls"}]. The commonest spelling of each side is shown."""
    counts, calls, spell_h, spell_s = Counter(), defaultdict(set), defaultdict(Counter), defaultdict(Counter)
    for r in db.q("SELECT id, transcript_json FROM recordings WHERE transcript_edited_at IS NOT NULL"
                  + (" AND rm_id=?" if rm_id else ""), (rm_id,) if rm_id else ()):
        for l in json.loads(r["transcript_json"] or "[]"):
            if "heard" not in l:
                continue
            for a, b in _pairs_in(l["heard"], l["text"]):
                key = (a.lower(), b.lower())
                counts[key] += 1
                calls[key].add(r["id"])
                spell_h[key][a] += 1
                spell_s[key][b] += 1
    out = [{"heard": spell_h[k].most_common(1)[0][0], "said": spell_s[k].most_common(1)[0][0], "count": n,
            "calls": len(calls[k])} for k, n in counts.items() if n >= min_count]
    return sorted(out, key=lambda p: (-p["count"], -p["calls"], p["heard"]))[:limit]


def hint() -> str:
    """One prompt paragraph of the commonest misheard words, or "" when there are none yet. Cached 10 minutes:
    the live agent calls this on every turn."""
    if _cache["pairs"] is None or time.time() - _cache["at"] > 600:
        try:
            _cache.update(pairs=pairs(MIN_COUNT, HINT_PAIRS), at=time.time())
        except Exception:
            return ""          # never let this break a call
    if not _cache["pairs"]:
        return ""
    return ("Speech-to-text often mishears these on our calls (heard -> meant): "
            + "; ".join(f'"{p["heard"]}" -> "{p["said"]}"' for p in _cache["pairs"])
            + ". Read the text with these in mind.")


def forget():
    """Drop the cached list (after a correction is saved, so the next prompt uses it)."""
    _cache["pairs"] = None
