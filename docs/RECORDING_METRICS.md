# Recordings: Sarvam-only transcription and call metrics

_Added 2026-11-23, after the speech-to-text A/B test ([STT_AB_TEST.md](STT_AB_TEST.md)) showed Sarvam beating Whisper._

## Transcription: Sarvam only
- Every RM/DC recording is transcribed by **Sarvam saaras:v4 (codemix)**, which also splits the speakers.
  The Whisper fallback and local voice model were removed from the recordings pipeline (`app/recordings.py`).
- `SARVAM_API_KEY` is **required**. Without it, new recordings stay *Waiting* and the run reports
  `SARVAM_API_KEY is not set`. It is in the `eko-deploy.toml` secrets list.
- `RECORDINGS_SPEAKERS` now defaults to **2** (RM + CSP), the setting that won the A/B test. Set `0` to let Sarvam guess.
- **Old recordings are redone by Sarvam automatically, in batches** (`backfill_batch` in `app/recordings.py`):
  10 recordings, then a 10-minute rest, newest calls first. New uploads always go first. Set
  `SARVAM_BACKFILL_BATCH` / `SARVAM_BACKFILL_PAUSE_S` to change the pace, or `SARVAM_BACKFILL=0` to stop it.
  - Covers RM/DC recordings that were done or failed under Whisper, if their audio is still on the server.
  - Skipped: calls a person corrected or checked (transcript, issue or summary), employee calls, DC calls outside the CSP list.
  - A redo gets a new review and summary, but is **not** sent to Prachi or the webhooks again.
  - A failed redo leaves the old transcript in place; after 3 failures that call is given up on.
  - Progress (calls left, minutes of audio, estimated Sarvam cost) shows under Call metrics, for admin/ops only.
- The Whisper helpers live on in `evals/stt_bench.py`, so the A/B test can still be re-run.

## Call metrics (recordings page → "Call metrics" panel)
They follow the tab (RM / DC / Employee) and the RM, employee and date filters. RMs see only their own calls.
API: `GET /api/recordings/metrics?mode=rm&rm_id=&employee_id=&date_from=&date_to=` (epoch seconds), built in
`app/call_metrics.py`.

| Metric | How it is worked out |
|---|---|
| Cost per call | Sarvam: audio length × `SARVAM_INR_PER_HOUR` (default ₹45/h, the published rate with speaker separation). LLM: tokens × `LLM_PRICES_USD` × `USD_TO_INR`. Groq/Gemini free tier = ₹0; a Claude model with no price set shows as unknown. |
| Tokens | Stored per call (`review_usage_json`, `summary_usage_json`) and shown in each call's stats. There is no page-level card, because cost already covers it. |
| Words per call | Words in the transcript (masked numbers like `[PHONE]` not counted), plus words per minute. |
| Both voices found | Calls where Sarvam found 2+ distinct voices; breakdown by 1 / 2 / 3+ / none. |
| RM and CSP both found | Calls where the AI review labelled at least one line RM and one line CSP. |
| Most used words / phrases | **Only domain words** (`app/domain_terms.py`: Eko business, money, banks and IDs, problems and actions, plus the issue keywords from `app/taxonomy.py`) and words people corrected as misheard. Each word shows its group, and "What the calls talk about" totals the groups. Phrases must contain a domain word. This is the vocabulary to use for fine-tuning. |

Opening a call shows its own **Call stats** in the details: words, voices, who was found, tokens (in/out), and cost.

## Tests
`tests/test_call_metrics.py`.

## Recordings list
The table of calls starts closed. Click "View all recordings" to open it and "Hide recordings" to close it. It
opens by itself when you search, pick a status, or press "Show the calls to check". The tabs and filters stay
visible because they also drive the metrics.
