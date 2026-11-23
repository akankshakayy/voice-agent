"""Speech-to-text + speaker A/B test on real calls, scored against transcripts a person corrected on the live site.

Every engine runs on the same audio copies (data/stt_bench/audio/{id}.mp3); results stay in data/stt_bench/results/
and never touch the production database. Both engines' voices are named (RM / CSP / other) by the same Claude step,
so the comparison is about hearing and voice separation, not about the naming.

    python -m evals.stt_bench run sarvam whisper     # transcribe (cached per engine and call)
    python -m evals.stt_bench fetch                  # pull the corrected transcripts (needs SAHAYAK_SESSION in .env)
    python -m evals.stt_bench score                  # word error rate and wrong-speaker share per engine

Engines: sarvam (Saaras, transcript + voices in one), whisper (Groq whisper-large-v3 + local voice model),
production (what the live site shows now, saved before the test in data/stt_bench/whisper_before/).
"""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "data", "stt_bench")
SITE = "https://indev.eko.in/rm-voice-agent"
NAMER_MODEL = os.environ.get("BENCH_NAMER_MODEL", "claude-opus-5-5")

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))
os.environ["RECORDINGS_SPEAKERS"] = "2"          # read at import by diarize and per call by sarvam

from app import diarize, recordings, sarvam, stt  # noqa: E402

# The Whisper setup the live site used before Sarvam replaced it (kept here only so the A/B test can be re-run)
WHISPER_MODEL = os.environ.get("RECORDINGS_STT_MODEL", "whisper-large-v3")
WHISPER_LANG = "hi"
# A style-only hint: without one, Whisper writes English words in Devanagari with no punctuation
WHISPER_PROMPT = "हाँ जी, ठीक है। तो ये website का project है, उसमें docs folder है।"


def _compact(path: str) -> tuple[bytes, str]:
    """Any phone format -> 16 kHz mono Opus, so a long call stays under Whisper's 25 MB limit."""
    if not stt.ffmpeg():
        with open(path, "rb") as f:
            return f.read(), os.path.basename(path)
    out = subprocess.run([stt.ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000",
                          "-c:a", "libopus", "-b:a", "24k", "-f", "ogg", "pipe:1"], capture_output=True, timeout=600)
    if out.returncode != 0 or not out.stdout:
        raise ValueError(f"Couldn't read this audio file: {out.stderr.decode(errors='replace')[:200]}")
    return out.stdout, "call.ogg"


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def drop_leaks(segs: list[dict], words: list[dict], prompt: str | None) -> tuple[list[dict], list[dict]]:
    """Whisper sometimes repeats its hint over silence or noise: drop every segment that mostly repeats it."""
    if not prompt:
        return segs, words
    p = _norm(prompt)
    leaked = [s for s in segs if (n := _norm(s["text"])) and
              (SequenceMatcher(None, n, p).ratio() >= 0.6 or (len(n) >= 12 and n in p))]
    if not leaked:
        return segs, words
    inside = lambda w: any(s["start"] - 0.05 <= w["start"] < s["end"] + 0.05 for s in leaked)   # noqa: E731
    return [s for s in segs if s not in leaked], [w for w in words if not inside(w)]


def ids() -> list[int]:
    return json.load(open(os.path.join(BENCH, "selected.json")))


def out_path(engine: str, rid: int) -> str:
    return os.path.join(BENCH, "results", engine, f"{rid}.json")


# ---------------------------------------------------------------- engines: audio -> lines with voices
def lines_sarvam(path: str) -> tuple[list[dict], str]:
    return sarvam.transcribe(path), f"Sarvam {sarvam.MODEL} {sarvam.MODE}, 2 speakers"


def lines_whisper(path: str) -> tuple[list[dict], str]:
    audio, name = _compact(path)
    segs, words = stt.transcribe_detailed(audio, name, WHISPER_LANG, WHISPER_MODEL, words=True, prompt=WHISPER_PROMPT)
    segs, words = drop_leaks(segs, words, WHISPER_PROMPT)
    turns = diarize.diarize(path)
    lines = diarize.assign_words(diarize.punctuate(words, segs), turns) if turns and words else segs
    return recordings.split_sentences(lines), f"Whisper {WHISPER_MODEL} + local voices, 2 speakers"


ENGINES = {"sarvam": lines_sarvam, "whisper": lines_whisper}


# ---------------------------------------------------------------- naming the voices with Claude (CLI, user's login)
def name_speakers(lines: list[dict]) -> tuple[dict, str]:
    user = (recordings._review_input(lines) + "\n\nAnswer with one JSON object only, no other text, with the keys of "
            "the call_review tool: " + json.dumps(recordings.REVIEW_TOOL["parameters"]["properties"], ensure_ascii=False))
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")}
    for attempt in range(3):
        p = subprocess.run(["claude", "-p", "--model", NAMER_MODEL, "--output-format", "json", "--no-session-persistence",
                            "--system-prompt", recordings._review_prompt().replace("Use the call_review tool.", "")],
                           input=user, capture_output=True, text=True, timeout=600, env=env, cwd=BENCH)
        try:
            res = json.loads(p.stdout)
            text = res["result"]
            if res.get("is_error"):
                raise ValueError(text)
            return json.loads(text[text.index("{"):text.rindex("}") + 1]), NAMER_MODEL
        except (ValueError, KeyError) as e:
            err = f"{e} {p.stderr[-300:]}"
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Claude naming failed: {err}")


def apply_names(lines: list[dict], review: dict) -> list[dict]:
    """Same rule as production: a voice's role decides every line it speaks."""
    sp = [s if s in recordings.SPEAKERS else "unknown" for s in review.get("speakers") or []]
    sp = (sp + ["unknown"] * len(lines))[:len(lines)]
    roles = {v: r for v, r in (review.get("voice_roles") or {}).items() if r in recordings.SPEAKERS}
    return [{**l, "text": recordings.mask(l["text"]), "speaker": roles.get(l.get("voice"), s)} for l, s in zip(lines, sp)]


def run_one(engine: str, rid: int) -> str:
    out = out_path(engine, rid)
    if os.path.exists(out):
        return f"{engine} {rid}: cached"
    path = os.path.join(BENCH, "audio", f"{rid}.mp3")
    t0 = time.perf_counter()
    lines, label = ENGINES[engine](path)
    stt_s = time.perf_counter() - t0
    review, model = name_speakers([{**l, "text": recordings.mask(l["text"])} for l in lines]) if lines else ({}, None)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"id": rid, "engine": label, "stt_s": round(stt_s, 1), "namer": model, "raw_lines": lines,
               "transcript": apply_names(lines, review), "review": review}, open(out, "w"), ensure_ascii=False, indent=1)
    return f"{engine} {rid}: {len(lines)} lines, {stt_s:.0f}s"


def run(engines: list[str]):
    jobs = [(e, r) for e in engines for r in ids()]
    with ThreadPoolExecutor(4) as pool:
        futs = {pool.submit(run_one, e, r): (e, r) for e, r in jobs}
        for f, (e, r) in futs.items():
            try:
                print(f.result(), flush=True)
            except Exception as ex:
                print(f"{e} {r}: FAILED {ex}", flush=True)


# ---------------------------------------------------------------- ground truth and scoring
def fetch():
    import httpx
    cookie = os.environ.get("SAHAYAK_SESSION", "").strip().strip("'\"")
    os.makedirs(os.path.join(BENCH, "truth"), exist_ok=True)
    done = 0
    with httpx.Client(cookies={"eko_session": cookie}, timeout=60) as c:
        for rid in ids():
            r = c.get(f"{SITE}/api/recordings/{rid}")
            r.raise_for_status()
            d = r.json()
            if d.get("checked_at"):
                json.dump(d, open(os.path.join(BENCH, "truth", f"{rid}.json"), "w"), ensure_ascii=False, indent=1)
                done += 1
    print(f"{done} of {len(ids())} calls are checked")


_LOOSE = [(r"[.~^_]", ""), (r"(?<=[^aeiou])a$", ""), (r"aa", "a"), (r"ee|ii", "i"), (r"oo|uu", "u"), (r"ae", "e"),
          (r"w", "v"), (r"z", "j"), (r"ph", "f"), (r"q", "k"), (r"x", "ks"), (r"(?<=[bcdgjkpst])h", ""),
          (r"(?<=[aeiou])y(?=[aeiou])", ""), (r"n(?=[bcdgjkpst])", ""), (r"m$", ""), (r"(?<=[aeiou])n$", ""), (r"(.)\1+", r"\1")]


def loose(word: str) -> str:
    """One spelling for a word however it was written: "देखिए", "dekhiye" and "dekhie" all become "dekie".
    The person writes Hindi in English letters; the engines write Devanagari."""
    from indic_transliteration import sanscript
    w = sanscript.transliterate(word, sanscript.DEVANAGARI, sanscript.ITRANS) if re.search(r"[ऀ-ॿ]", word) else word
    w = w.lower()
    for rx, repl in _LOOSE:
        w = re.sub(rx, repl, w)
    return w or word


def _words(transcript: list[dict]) -> list[tuple[str, str]]:
    out = []
    for l in transcript:
        text = (l.get("text") or "").translate(recordings.DEVANAGARI_DIGITS).replace("₹", " ")
        out += [(w if w.startswith("[") else loose(w), l.get("speaker") or "unknown")
                for w in re.findall(r"\[[A-Z]+\]|[\wऀ-ॣ०-ॿ]+", text)]
    return out


def _edits(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def score_one(truth: list[dict], hyp: list[dict]) -> dict:
    ref, got = _words(truth), _words(hyp)
    rw, hw = [w for w, _ in ref], [w for w, _ in got]
    sm = SequenceMatcher(None, rw, hw, autojunk=False)
    pairs = [(ref[b.a + k][1], got[b.b + k][1]) for b in sm.get_matching_blocks() for k in range(b.size)]
    rc, hc = " ".join(rw), " ".join(hw)
    return {"words": len(rw), "errors": _edits(rw, hw), "chars": len(rc), "char_errors": _edits(list(rc), list(hc)),
            "matched": len(pairs), "speaker_wrong": sum(1 for a, b in pairs if a != b)}


def score():
    truths = {int(f[:-5]): json.load(open(os.path.join(BENCH, "truth", f)))
              for f in sorted(os.listdir(os.path.join(BENCH, "truth")))} if os.path.isdir(os.path.join(BENCH, "truth")) else {}
    if not truths:
        sys.exit("No checked transcripts yet: run `fetch` after calls are marked checked")
    engines = {"production": lambda rid: json.load(open(os.path.join(BENCH, "whisper_before", f"{rid}.json")))["transcript"]}
    for e in ENGINES:
        engines[e] = lambda rid, e=e: json.load(open(out_path(e, rid)))["transcript"] if os.path.exists(out_path(e, rid)) else None
    rows = {}
    for name, get in engines.items():
        per = {rid: score_one(t["transcript"], h) for rid, t in truths.items() if (h := get(rid)) is not None}
        tot = {k: sum(p[k] for p in per.values()) for k in ("words", "errors", "chars", "char_errors", "matched", "speaker_wrong")}
        rows[name] = {"calls": len(per), "wer": tot["errors"] / tot["words"] if tot["words"] else None,
                      "cer": tot["char_errors"] / tot["chars"] if tot["chars"] else None,
                      "speaker_wrong": tot["speaker_wrong"] / tot["matched"] if tot["matched"] else None, "per_call": per}
    print(f"{'engine':<12}{'calls':>6}{'word errors':>13}{'letter errors':>15}{'wrong speaker':>15}")
    for n, r in rows.items():
        f = lambda x: f"{100 * x:.1f}%" if x is not None else "-"   # noqa: E731
        print(f"{n:<12}{r['calls']:>6}{f(r['wer']):>13}{f(r['cer']):>15}{f(r['speaker_wrong']):>15}")
    json.dump(rows, open(os.path.join(BENCH, "scores.json"), "w"), indent=1)


def compare():
    """data/stt_bench/compare.html: every engine's transcript of each call side by side, with the call's audio.
    Opened from disk, so nothing is published."""
    import html
    cols = [("Live site now", lambda r: os.path.join(BENCH, "whisper_before", f"{r}.json"))]
    cols += [(n, lambda r, e=e: out_path(e, r)) for e, n in (("whisper", "Whisper + local voices"), ("sarvam", "Sarvam"))]
    calls = []
    for rid in ids():
        panes = []
        for name, path in cols:
            p = path(rid)
            rows = json.load(open(p))["transcript"] if os.path.exists(p) else []
            body = "".join(f'<div class="l {html.escape(l.get("speaker") or "unknown")}"><span class="t">'
                           f'{int(l["start"] // 60)}:{int(l["start"] % 60):02d}</span><b>{html.escape((l.get("speaker") or "?").upper())}</b> '
                           f'{html.escape(l["text"])}</div>' for l in rows) or '<div class="muted">No transcript</div>'
            panes.append(f'<section><h3>{name} <small>{len(rows)} lines, {sum(len(l["text"].split()) for l in rows)} words</small></h3>{body}</section>')
        calls.append(f'<article id="c{rid}"><h2>Recording #{rid} <a href="{SITE}/recordings#{rid}" target="_blank">open on site</a></h2>'
                     f'<audio controls preload="none" src="audio/{rid}.mp3"></audio><div class="grid">{"".join(panes)}</div></article>')
    nav = " ".join(f'<a href="#c{r}">#{r}</a>' for r in ids())
    page = f"""<!doctype html><meta charset="utf-8"><title>Transcript comparison</title><style>
body{{font:14px/1.5 system-ui,sans-serif;margin:0;padding:16px;background:#fafafa;color:#222}}
nav{{position:sticky;top:0;background:#fafafa;padding:8px 0;border-bottom:1px solid #ddd;z-index:1}} nav a{{margin-right:8px}}
article{{margin:24px 0}} audio{{width:100%;max-width:600px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}} @media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
section{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px}} h3{{margin:0 0 8px;font-size:15px}} small{{color:#888;font-weight:normal}}
.l{{padding:3px 6px;border-left:3px solid #ccc;margin:2px 0}} .rm{{border-color:#2b6cb0;background:#ebf4ff}} .csp{{border-color:#c05621;background:#fff5eb}}
.other{{border-color:#6b46c1}} .t{{color:#999;font-size:12px;margin-right:6px}} .muted{{color:#999}}
</style><h1>Transcript comparison</h1><p>Blue = RM, orange = CSP. Correct the live site from what you <b>hear</b>, not by copying any column.</p>
<nav>{nav}</nav>{"".join(calls)}"""
    out = os.path.join(BENCH, "compare.html")
    open(out, "w").write(page)
    print(out)


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["help"]
    {"run": lambda: run(rest or list(ENGINES)), "fetch": fetch, "score": score,
     "compare": compare}.get(cmd, lambda: print(__doc__))()
