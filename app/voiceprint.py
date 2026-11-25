"""Which voice in a recorded call is the RM, from a sample of the RM's own voice (a voiceprint).

Sarvam splits a call into voices A and B but can't say who is who; the AI review guesses from the words. Each RM
records a short sample once (an admin uploads it on /admin); a speaker-embedding model turns it into 192 numbers
that describe the voice. Only those numbers are kept, never the sample audio. On every RM call the voice that
sounds most like the RM's voiceprint is the RM, when it is clearly closer than the other voice (MIN_MARGIN);
otherwise the AI's guess stands. Tested on the 20 A/B test calls: 20/20 right (the AI alone: 19/20).

Model: 3D-Speaker ERes2Net (sherpa-onnx release), about 40 MB, fetched into models_dir() on first use.
"""
import json
import logging
import os
import threading
import time
import urllib.request

from . import db
from .diarize import SAMPLE_RATE, _load, models_dir

log = logging.getLogger("eko.voiceprint")
MODEL_FILE = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{MODEL_FILE}"
MIN_MARGIN = float(os.environ.get("VOICEPRINT_MIN_MARGIN", "0.08"))   # smallest gap seen on the test calls: 0.12
MIN_SAMPLE_S = 20          # shorter samples give unreliable voiceprints
GOOD_SAMPLE_S = 30
MIN_LINE_S = 0.8           # lines shorter than this are mostly "हाँ" and overlap; used only if a voice has nothing longer
MIN_VOICE_S = 1.0
_lock = threading.Lock()
_extractor = None


def model_path() -> str:
    return os.path.join(models_dir(), MODEL_FILE)


def _ensure_model() -> str:
    path = model_path()
    if not os.path.exists(path):
        os.makedirs(models_dir(), exist_ok=True)
        log.info("Downloading the voiceprint model to %s", path)
        urllib.request.urlretrieve(MODEL_URL, path + ".part")
        os.replace(path + ".part", path)
    return path


def _embed(samples):
    """Samples -> unit-length voice vector. The model is loaded (and downloaded) on first use."""
    import numpy as np
    import sherpa_onnx
    global _extractor
    with _lock:
        if _extractor is None:
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=_ensure_model(), num_threads=2))
        s = _extractor.create_stream()
        s.accept_waveform(SAMPLE_RATE, samples)
        s.input_finished()
        v = np.array(_extractor.compute(s), dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def from_sample(path: str) -> dict:
    """A voice sample file (any format ffmpeg reads) -> a voiceprint to store. Raises ValueError if too short."""
    samples = _load(path)
    seconds = len(samples) / SAMPLE_RATE
    if seconds < MIN_SAMPLE_S:
        raise ValueError(f"The sample is {seconds:.0f} seconds long; at least {MIN_SAMPLE_S} seconds are needed")
    return {"model": MODEL_FILE, "vec": [round(float(x), 5) for x in _embed(samples)], "seconds": round(seconds, 1)}


def save(rm_id: int, print_: dict, by: str | None = None):
    db.x("UPDATE rms SET voiceprint_json=?, voiceprint_at=?, voiceprint_by=? WHERE id=?",
         (json.dumps(print_), time.time(), by, rm_id))


def remove(rm_id: int):
    db.x("UPDATE rms SET voiceprint_json=NULL, voiceprint_at=NULL, voiceprint_by=NULL WHERE id=?", (rm_id,))


def get(rm_id: int | None) -> dict | None:
    """The RM's stored voiceprint, if there is one made with the current model."""
    if not rm_id:
        return None
    row = db.q("SELECT voiceprint_json FROM rms WHERE id=?", (rm_id,), one=True)
    p = json.loads(row["voiceprint_json"]) if row and row.get("voiceprint_json") else None
    return p if p and p.get("model") == MODEL_FILE else None


def status() -> list[dict]:
    """Every RM with whether a voiceprint is stored (for the admin page). The numbers themselves aren't sent."""
    out = []
    for r in db.q("SELECT id, name, phone, source, voiceprint_json, voiceprint_at, voiceprint_by FROM rms ORDER BY name"):
        p = json.loads(r["voiceprint_json"]) if r.get("voiceprint_json") else None
        out.append({"id": r["id"], "name": r["name"], "phone": r["phone"], "source": r["source"],
                    "has_voiceprint": bool(p and p.get("model") == MODEL_FILE),
                    "seconds": p.get("seconds") if p else None, "at": r.get("voiceprint_at"), "by": r.get("voiceprint_by")})
    return out


def decide(scores: dict[str, float]) -> tuple[str | None, float]:
    """Voice -> similarity to the RM. Returns (the RM's voice, or None when it isn't clear, margin over the next)."""
    if len(scores) < 2:
        return None, 0.0
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    margin = round(ranked[0][1] - ranked[1][1], 3)
    return (ranked[0][0] if margin >= MIN_MARGIN else None), margin


def match(audio_path: str, lines: list[dict], rm_id: int | None) -> dict | None:
    """Which of the call's voices is the RM. lines: Sarvam's lines with start, end and voice.
    Returns {"rm_voice": "B" or None, "scores": {...}, "margin": 0.28, "model": ...}, or None without a voiceprint."""
    p = get(rm_id)
    if not p:
        return None
    import numpy as np
    audio = _load(audio_path)
    rm = np.array(p["vec"], dtype=np.float32)
    scores = {}
    for voice in sorted({l.get("voice") for l in lines if l.get("voice")}):
        mine = [l for l in lines if l.get("voice") == voice]
        longer = [l for l in mine if l["end"] - l["start"] >= MIN_LINE_S] or mine
        parts = [audio[int(l["start"] * SAMPLE_RATE):int(l["end"] * SAMPLE_RATE)] for l in longer]
        parts = [x for x in parts if len(x)]
        if parts and sum(len(x) for x in parts) >= MIN_VOICE_S * SAMPLE_RATE:
            scores[voice] = round(float(rm @ _embed(np.concatenate(parts))), 3)
    voice, margin = decide(scores)
    return {"rm_voice": voice, "scores": scores, "margin": margin, "model": MODEL_FILE, "min_margin": MIN_MARGIN}
