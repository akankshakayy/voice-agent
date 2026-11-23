# Recordings: Sarvam-only transcription and call metrics

_Added 2026-11-23, after the speech-to-text A/B test ([STT_AB_TEST.md](STT_AB_TEST.md)) showed Sarvam beating Whisper._

## Transcription: Sarvam only
- Every RM/DC recording is transcribed by **Sarvam saaras:v4 (codemix)**, which also splits the speakers.
  The Whisper fallback and local voice model were removed from the recordings pipeline (`app/recordings.py`).
- `SARVAM_API_KEY` is **required**. Without it, new recordings stay *Waiting* and the run reports
  `SARVAM_API_KEY is not set`. It is in the `eko-deploy.toml` secrets list.
- `RECORDINGS_SPEAKERS` now defaults to **2** (RM + CSP), the setting that won the A/B test. Set `0` to let Sarvam guess.
- Old Whisper transcripts are re-sent to Sarvam only when a recording is processed again. Transcripts a person
  corrected or checked are never re-transcribed.
- The Whisper helpers live on in `evals/stt_bench.py`, so the A/B test can still be re-run.

## Call metrics (recordings page → "Call metrics" panel)
They follow the tab (RM / DC / Employee) and the RM, employee and date filters. RMs see only their own calls.
API: `GET /api/recordings/metrics?mode=rm&rm_id=&employee_id=&date_from=&date_to=` (epoch seconds), built in
`app/call_metrics.py`.

| Metric | How it is worked out |
|---|---|
| Cost per call | Sarvam: audio length × `SARVAM_INR_PER_HOUR` (default ₹45/h, the published rate with speaker separation). LLM: tokens × `LLM_PRICES_USD` × `USD_TO_INR`. Groq/Gemini free tier = ₹0; a Claude model with no price set shows as unknown. |
| Tokens per call | The LLM API's own usage numbers for the call review and the detailed summary (`review_usage_json`, `summary_usage_json`). Counted from this release on, so older calls have none. |
| Words per call | Words in the transcript (masked numbers like `[PHONE]` not counted), plus words per minute. |
| Both voices found | Calls where Sarvam found 2+ distinct voices; breakdown by 1 / 2 / 3+ / none. |
| RM and CSP both found | Calls where the AI review labelled at least one line RM and one line CSP. |
| Most used words / phrases | Word counts (and how many calls each appears in), 2–3 word phrases, words said 3+ times in one call, RM's and CSP's top words. Common filler words (है, जी, haan, ok, sir…) are left out. |

Opening a call shows its own **Call stats** in the details: words, voices, who was found, tokens (in/out), and cost.

## Tests
`tests/test_call_metrics.py`.
