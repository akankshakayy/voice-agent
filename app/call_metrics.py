"""Numbers about processed call recordings, for the recordings page: what each call cost (Sarvam's transcription
plus the LLM's tokens), how many words were captured, whether both voices (and both the RM and the CSP) were
found, and which words and phrases come up most. The word lists keep only words that matter for Eko's work
(app/domain_terms.py) and words people corrected as misheard: the vocabulary worth fine-tuning on.

Costs are estimates from published rates, set by env so they can follow price changes:
    SARVAM_INR_PER_HOUR=45        # Sarvam speech-to-text with speaker separation, per hour of audio (billed per second)
    USD_TO_INR=85
    LLM_PRICES_USD='{"claude-haiku-4-5": [1, 5]}'   # $ per million input / output tokens, by model name (prefix ok)
A model with no price set counts as free (Groq's and Gemini's free tiers) unless it is a Claude model, whose cost is
then shown as unknown rather than guessed.
"""
import json
import os
import re
from collections import Counter, defaultdict

from . import db, domain_terms, misheard

MASKS = re.compile(r"\[[A-Z]+\]")                         # [PHONE], [AADHAAR]… put in by recordings.mask
WORD = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)       # Latin, digits and Devanagari (with its vowel signs)

# Common Hindi / Hinglish / English words that say nothing about the call: left out of the top words
STOPWORDS = set("""
है हैं था थे थी हो होगा होगी होंगे हुआ हुई हुए रहा रही रहे कर करो करना करके करें किया की का के को में से पर ने
और या तो भी ही जी हाँ हां हम मैं मेरा मेरी मेरे आप आपका आपकी आपके आपको वो वह ये यह इस उस इसमें उसमें कि क्या कोई
कुछ एक तक लिए वाला वाली वाले अभी बस ना न नहीं मतलब अच्छा ठीक हम्म हाँजी तुम तू उन उनका इन जो जब तब फिर
haan han ha hai hain tha the thi ho hoga raha rahe rahi kar karo karna karke kiya ki ka ke ko me mein se par ne aur ya
to toh bhi hi ji jee hum main mera meri mere aap aapka aapki aapke aapko wo woh ye yeh is us ek kuch koi kya na nahi
nahin matlab accha acha theek thik ok okay hmm hm haa
the a an is are was were be to of and or in on for it this that i you we he she they me my your so do does did
yes no not but with at as hello hi sir madam ma'am mam please
""".split())


def words_of(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(MASKS.sub(" ", text or ""))]


def audio_seconds(rec: dict, lines: list[dict] | None = None) -> float:
    """The length Sarvam bills for: the file's own length, else the end of the last line."""
    if rec.get("duration_sec"):
        return float(rec["duration_sec"])
    return max((float(l.get("end") or 0) for l in lines or []), default=0.0)


# ---------------------------------------------------------------- cost
def _prices() -> dict:
    try:
        return json.loads(os.environ.get("LLM_PRICES_USD") or "{}")
    except ValueError:
        return {}


def llm_cost_inr(usage: dict) -> float | None:
    """{model: {"input", "output"}} -> rupees. None when a model's price isn't known (a Claude model with no price)."""
    prices, rate, total = _prices(), float(os.environ.get("USD_TO_INR", "85")), 0.0
    for model, u in (usage or {}).items():
        price = prices.get(model) or next((v for k, v in prices.items() if model.startswith(k)), None)
        if price is None:
            if model.startswith("claude"):
                return None
            continue                                         # free tier (Groq, Gemini)
        total += (u.get("input", 0) * price[0] + u.get("output", 0) * price[1]) / 1e6 * rate
    return total


def stt_cost_inr(audio_s: float) -> float:
    return audio_s / 3600 * float(os.environ.get("SARVAM_INR_PER_HOUR", "45"))


def _merge(*usages) -> dict:
    out = {}
    for u in usages:
        for model, v in (u or {}).items():
            m = out.setdefault(model, {"input": 0, "output": 0, "requests": 0})
            for k in m:
                m[k] += v.get(k, 0)
    return out


# ---------------------------------------------------------------- one call
def for_call(rec: dict) -> dict:
    """Words, voices and who was found, tokens and cost for one processed recording (a row with transcript_json,
    stt_json, review_usage_json, summary_usage_json and duration_sec)."""
    lines = rec["transcript"] if "transcript" in rec else json.loads(rec.get("transcript_json") or "[]")
    stt = json.loads(rec.get("stt_json") or "null") or {}
    by_sarvam = str(stt.get("provider", "")).startswith("sarvam")
    review = json.loads(rec.get("review_usage_json") or "null")
    summary = json.loads(rec.get("summary_usage_json") or "null")
    usage = _merge(review, summary)
    tokens_in = sum(u["input"] for u in usage.values())
    tokens_out = sum(u["output"] for u in usage.values())
    audio_s = stt.get("audio_s") or audio_seconds(rec, lines)
    stt_cost = stt_cost_inr(audio_s) if by_sarvam else 0.0
    llm_cost = llm_cost_inr(usage)
    voices = {l["voice"] for l in lines if l.get("voice")}
    roles = {l.get("speaker") for l in lines}
    return {"words": sum(len(words_of(l.get("text"))) for l in lines), "lines": len(lines),
            "voices": len(voices), "rm_found": "rm" in roles, "csp_found": "csp" in roles,
            "audio_s": round(audio_s, 1), "stt": stt.get("stt"), "by_sarvam": by_sarvam,
            "tokens_recorded": review is not None or summary is not None,
            "tokens_in": tokens_in, "tokens_out": tokens_out, "tokens": tokens_in + tokens_out, "usage": usage,
            "stt_cost_inr": round(stt_cost, 2), "llm_cost_inr": None if llm_cost is None else round(llm_cost, 2),
            "cost_inr": None if llm_cost is None else round(stt_cost + llm_cost, 2)}


# ---------------------------------------------------------------- all calls in view
def summary(mode: str = "rm", rm_id: int | None = None, employee_id: int | None = None,
            date_from: float | None = None, date_to: float | None = None, top: int = 30) -> dict:
    where, args = ["status='done'", "transcript_json IS NOT NULL", "transcript_json NOT IN ('', '[]')"], []
    if mode == "rm":
        where.append("COALESCE(mode, 'rm')='rm'")
    elif mode:
        where.append("mode=?")
        args.append(mode)
    for col, val in (("rm_id", rm_id), ("employee_id", employee_id)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    if date_from:
        where.append("COALESCE(started_at, uploaded_at) >= ?")
        args.append(date_from)
    if date_to:
        where.append("COALESCE(started_at, uploaded_at) <= ?")
        args.append(date_to)
    rows = db.q(f"""SELECT id, duration_sec, transcript_json, stt_json, review_usage_json, summary_usage_json, is_csp_call
                    FROM recordings WHERE {' AND '.join(where)}""", tuple(args))

    # Words people corrected as misheard are training data too, whatever their subject
    fixed = {w.lower(): "Corrected as misheard" for p in misheard.pairs(1, 500) for w in words_of(p["said"])
             if w not in STOPWORDS and len(w) > 1 and not w.isdigit()}
    group = lambda w: domain_terms.group_of(w, fixed)   # noqa: E731
    per = []
    words, phrases, word_calls = Counter(), Counter(), Counter()
    by_role = defaultdict(Counter)
    repeats = Counter()          # a word said 3+ times in one call: how many calls that happens in
    for r in rows:
        m = for_call(r)
        per.append(m)
        in_call = Counter()
        for l in json.loads(r["transcript_json"]):
            ws = [w for w in words_of(l.get("text")) if not w.isdigit()]
            keep = [w for w in ws if w not in STOPWORDS and len(w) > 1 and group(w)]
            words.update(keep)
            in_call.update(keep)
            by_role[l.get("speaker") or "unknown"].update(keep)
            for n in (2, 3):     # phrases: runs of words holding a domain word, not starting or ending in filler
                for i in range(len(ws) - n + 1):
                    gram = ws[i:i + n]
                    if gram[0] not in STOPWORDS and gram[-1] not in STOPWORDS and any(group(w) for w in gram):
                        phrases[" ".join(gram)] += 1
        word_calls.update(in_call.keys())
        repeats.update(w for w, c in in_call.items() if c >= 3)

    groups = Counter()
    for w, c in words.items():
        groups[group(w)] += c
    n = len(per)
    priced = [m for m in per if m["cost_inr"] is not None]
    with_tokens = [m for m in per if m["tokens_recorded"]]
    tot = lambda key, group=per: sum(m[key] or 0 for m in group)   # noqa: E731
    avg = lambda key, group: round(tot(key, group) / len(group), 2) if group else None   # noqa: E731
    word_rows = lambda counter: [{"word": w, "count": c, "calls": word_calls[w], "group": group(w)}   # noqa: E731
                                 for w, c in counter.most_common(top)]
    return {
        "calls": n,
        "csp_calls": sum(1 for r in rows if r["is_csp_call"]),
        "audio_min": round(tot("audio_s") / 60, 1),
        "by_sarvam": sum(1 for m in per if m["by_sarvam"]),
        "words": {"total": tot("words"), "avg": avg("words", per),
                  "per_min": round(tot("words") / (tot("audio_s") / 60), 1) if tot("audio_s") else None},
        "voices": {"two_or_more": sum(1 for m in per if m["voices"] >= 2), "one": sum(1 for m in per if m["voices"] == 1),
                   "three_or_more": sum(1 for m in per if m["voices"] >= 3), "none": sum(1 for m in per if m["voices"] == 0)},
        "roles": {"both": sum(1 for m in per if m["rm_found"] and m["csp_found"]),
                  "rm_only": sum(1 for m in per if m["rm_found"] and not m["csp_found"]),
                  "csp_only": sum(1 for m in per if m["csp_found"] and not m["rm_found"]),
                  "neither": sum(1 for m in per if not m["rm_found"] and not m["csp_found"])},
        "tokens": {"calls": len(with_tokens), "total": tot("tokens", with_tokens), "input": tot("tokens_in", with_tokens),
                   "output": tot("tokens_out", with_tokens), "avg": avg("tokens", with_tokens),
                   "by_model": _merge(*(m["usage"] for m in with_tokens))},
        "cost": {"calls": len(priced), "total_inr": round(tot("cost_inr", priced), 2), "avg_inr": avg("cost_inr", priced),
                 "stt_inr": round(tot("stt_cost_inr"), 2), "llm_inr": round(tot("llm_cost_inr", priced), 2),
                 "sarvam_inr_per_hour": float(os.environ.get("SARVAM_INR_PER_HOUR", "45"))},
        "top_words": word_rows(words),
        "top_phrases": [{"phrase": p, "count": c} for p, c in phrases.most_common(top) if c >= 2],
        "repeated_in_call": [{"word": w, "calls": c, "group": group(w)} for w, c in repeats.most_common(top)],
        "top_words_rm": [{"word": w, "count": c, "group": group(w)} for w, c in by_role["rm"].most_common(top)],
        "top_words_csp": [{"word": w, "count": c, "group": group(w)} for w, c in by_role["csp"].most_common(top)],
        # How big each list is in full (the lists above are cut to the top few): distinct entries and total uses
        "word_counts": {
            "top_words": {"distinct": len(words), "uses": sum(words.values())},
            "top_phrases": {"distinct": sum(1 for c in phrases.values() if c >= 2),
                            "uses": sum(c for c in phrases.values() if c >= 2)},
            "repeated_in_call": {"distinct": len(repeats), "uses": sum(repeats.values())},
            "top_words_rm": {"distinct": len(by_role["rm"]), "uses": sum(by_role["rm"].values())},
            "top_words_csp": {"distinct": len(by_role["csp"]), "uses": sum(by_role["csp"].values())},
        },
        "groups": [{"group": g, "count": c} for g, c in groups.most_common()],
    }
