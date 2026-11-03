"""Speech-to-text using Claude CLI (local) with Groq fallback for robustness.

Claude provides more accurate transcription for Indian English and Hinglish.
Automatically falls back to Groq if Claude is unavailable.
"""
import json
import os
import subprocess
import base64
from typing import Optional

from . import stt as groq_stt

MODEL = "claude-3-5-sonnet-20241022"  # Default Claude model


def available() -> bool:
    """Check if Claude CLI is available and Groq is configured as fallback."""
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _transcribe_with_claude(audio: bytes, filename: str, lang: str = "hi-IN") -> Optional[str]:
    """Transcribe using Claude CLI via base64-encoded audio."""
    try:
        # Prepare audio data
        audio_b64 = base64.standard_b64encode(audio).decode()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp3"

        # Map extensions to media types
        media_types = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "flac": "audio/flac",
            "ogg": "audio/ogg",
            "m4a": "audio/mp4",
            "webm": "audio/webm",
        }
        media_type = media_types.get(ext, "audio/mpeg")

        # Build Claude prompt
        lang_name = "Hindi" if lang.startswith("hi") else "English"
        prompt = f"""Transcribe this {lang_name} audio from a customer support call about Eko (DMT, AePS, wallet, commission, KYC, refund, transaction ID, UTR).

Return ONLY valid JSON with no additional text:
{{"text": "full transcription"}}

If you cannot transcribe clearly, return {{"text": "", "error": "reason"}}"""

        # Use claude command with audio
        cmd = [
            "claude",
            "-m", MODEL,
            "--",
            prompt
        ]

        # Call Claude with audio as stdin
        result = subprocess.run(
            cmd,
            input=audio,
            capture_output=True,
            timeout=60,
            text=False
        )

        if result.returncode != 0:
            return None

        output = result.stdout.decode(errors="replace").strip()

        # Try to parse JSON response
        try:
            data = json.loads(output)
            return (data.get("text") or "").strip() if data.get("text") else None
        except json.JSONDecodeError:
            # Claude might return text with markdown formatting
            if "```json" in output:
                json_part = output.split("```json")[1].split("```")[0].strip()
                data = json.loads(json_part)
                return (data.get("text") or "").strip() if data.get("text") else None
            return None

    except Exception as e:
        print(f"Claude transcription error: {e}")
        return None


def transcribe(audio: bytes, filename: str, lang: str = "hi-IN") -> str:
    """Transcribe with Claude, fallback to Groq if needed."""
    if available():
        result = _transcribe_with_claude(audio, filename, lang)
        if result:
            return result

    # Fallback to Groq
    return groq_stt.transcribe(audio, filename, lang)


def transcribe_segments(audio: bytes, filename: str, lang: str = "hi", model: str | None = None) -> list[dict]:
    """Transcribe with timestamps. Claude doesn't support segments natively, so use Groq."""
    return groq_stt.transcribe_segments(audio, filename, lang, model)


def transcribe_detailed(audio: bytes, filename: str, lang: str = "hi", model: str | None = None,
                        words: bool = False, prompt: str | None = None) -> tuple[list[dict], list[dict]]:
    """Detailed transcription with word-level timing. Falls back to Groq for detailed analysis."""
    return groq_stt.transcribe_detailed(audio, filename, lang, model, words, prompt)
