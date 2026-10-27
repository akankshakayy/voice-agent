"""What speech-to-text gets wrong on our calls, learned from transcripts people corrected (recordings.save_edits).

A corrected line keeps what was heard ("heard") beside what was said ("text"). Comparing the two word by word
gives:
- word errors per recording (word error rate, shown on the recordings page), and
- the words misheard again and again ("डीएमटी" -> "DMT"). Those go into the prompts of the live agent, the call
  review and the summary, so the LLM reads past them. Not into Whisper's own hint: Whisper copies hint text
  into transcripts (see recordings.STT_PROMPT).

Pairs that carry a number of three or more digits are left out: they are values (amounts, IDs), not words.

What goes into prompts is text people typed, so a pair must earn its place: seen on MIN_CALLS calls, fixed by
MIN_PEOPLE different people, about the same number of words on both sides (a misheard word, not a rewrite), and
not blocked by admin or ops on the recordings page (misheard_blocked). One person can't put words into every
call's prompt on their own.
"""
import json
import os
import re
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from . import db

MIN_COUNT = int(os.environ.get("MISHEARD_MIN_COUNT", "2"))   # seen this often before it goes into prompts,
MIN_CALLS = int(os.environ.get("MISHEARD_MIN_CALLS", "2"))   # on this many calls,
MIN_PEOPLE = int(os.environ.get("MISHEARD_MIN_PEOPLE", "2"))  # fixed by this many people
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
        if re.search(r'["\\<>{}`]', a + b):     # can't be quoted safely in a prompt
            continue
        yield a, b


def _why_not(count: int, calls: int, people: int, heard: str, said: str, blocked: bool) -> str | None:
    """Why a pair is not given to the AI yet, or None when it is."""
    if blocked:
        return "blocked"
    if abs(len(heard.split()) - len(said.split())) > 1:
        return "a rewrite, not a misheard word"
    if count < MIN_COUNT or calls < MIN_CALLS:
        return f"needs {MIN_CALLS} calls"
    if people < MIN_PEOPLE:
        return f"needs fixing by {MIN_PEOPLE} people"
    return None


def pairs(min_count: int = 1, limit: int = 200, rm_id: int | None = None) -> list[dict]:
    """Misheard words across every corrected transcript (or one RM's), most frequent first:
    [{"heard", "said", "count", "calls", "people", "in_prompts", "why_not"}]. The commonest spelling of each
    side is shown. in_prompts is decided over every RM's calls, whatever rm_id narrows the list to."""
    counts, calls, people = Counter(), defaultdict(set), defaultdict(set)
    spell_h, spell_s = defaultdict(Counter), defaultdict(Counter)
    for r in db.q("SELECT id, rm_id, edited_by, transcript_json FROM recordings WHERE transcript_edited_at IS NOT NULL"):
        for l in json.loads(r["transcript_json"] or "[]"):
            if "heard" not in l:
                continue
            for a, b in _pairs_in(l["heard"], l["text"]):
                key = (a.lower(), b.lower())
                counts[key] += 1
                calls[key].add((r["id"], r["rm_id"]))
                people[key].add(l.get("fixed_by") or r["edited_by"])
                spell_h[key][a] += 1
                spell_s[key][b] += 1
    blocked = {(b["heard"], b["said"]) for b in db.q("SELECT heard, said FROM misheard_blocked")}
    out = []
    for k, n in counts.items():
        mine = [c for c in calls[k] if not rm_id or c[1] == rm_id]
        if n < min_count or not mine:
            continue
        p = {"heard": spell_h[k].most_common(1)[0][0], "said": spell_s[k].most_common(1)[0][0], "count": n,
             "calls": len(calls[k]), "people": len(people[k]), "blocked": k in blocked}
        p["why_not"] = _why_not(n, p["calls"], p["people"], *k, k in blocked)
        p["in_prompts"] = p["why_not"] is None
        out.append(p)
    return sorted(out, key=lambda p: (-p["count"], -p["calls"], p["heard"]))[:limit]


def set_blocked(heard: str, said: str, blocked: bool, actor: str):
    """Admin or ops keep a pair out of the prompts (or let it back in)."""
    key = (heard.strip().lower(), said.strip().lower())
    if blocked:
        db.x("INSERT OR REPLACE INTO misheard_blocked(heard, said, by, at) VALUES(?,?,?,?)", (*key, actor, time.time()))
    else:
        db.x("DELETE FROM misheard_blocked WHERE heard=? AND said=?", key)
    forget()


def hint() -> str:
    """One prompt paragraph of the commonest misheard words, or "" when there are none yet. Cached 10 minutes:
    the live agent calls this on every turn."""
    if _cache["pairs"] is None or time.time() - _cache["at"] > 600:
        try:
            _cache.update(pairs=[p for p in pairs(MIN_COUNT) if p["in_prompts"]][:HINT_PAIRS], at=time.time())
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
