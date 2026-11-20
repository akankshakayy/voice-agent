# Speech-to-text and speaker A/B test

Started 2026-11-20. Transcripts and speaker labels on recorded RM–CSP calls were not accurate enough, so we compare
engines on the **same** real calls, scored against transcripts a person corrected by hand.

## Engines compared

| Name in results | What it is |
|---|---|
| `production` | What the live site showed before the test: Groq Whisper large-v3, voices named by the Groq LLM |
| `whisper` | Groq Whisper large-v3 + local voice model (sherpa-onnx), fixed at 2 speakers, voices named by Claude |
| `sarvam` | Sarvam Saaras v4, `codemix` mode, transcript and voices in one step, fixed at 2 speakers, voices named by Claude |
| `elevenlabs` | Planned (ElevenLabs Scribe); not run yet, no key |

`sarvam` and `whisper` use the same Claude naming step (Claude Code CLI, Opus 5.5), so the comparison is about
hearing and voice separation, not about naming.

## Test set

20 of Vandana's calls (22 Oct – 6 Nov 2026), 28.6 minutes, all with complete audio, chosen across Whisper's
confidence (hard, medium and easy), Hindi and Hinglish:

89, 415, 431, 434, 454, 460, 501, 504, 509, 517, 521, 528, 536, 539, 540, 541, 558, 567, 571, 574

Open one at `https://indev.eko.in/rm-voice-agent/recordings#<number>`, or type the number in the search box.

## How the corrections are written

- Hindi is typed in **English letters** (keyboard limits), English words as normal ("account", "KYC").
- Every line gets its speaker (RM, CSP or other); a line where two people speak is split.
- Amounts as numbers ("900"). Press **checked** when the call is done.

Scoring converts the engines' Devanagari to English letters and folds spellings together ("देखिए", "dekhiye",
"dekhie" are the same word), so the difference in script is not counted as an error.

## Running it

```bash
python -m evals.stt_bench run sarvam whisper   # transcribe; cached per engine and call
python -m evals.stt_bench compare              # data/stt_bench/compare.html: all transcripts side by side + audio
python -m evals.stt_bench fetch                # pull checked transcripts (SAHAYAK_SESSION cookie in .env)
python -m evals.stt_bench score                # word errors, letter errors, wrong-speaker share per engine
```

Needs `SARVAM_API_KEY` and `GROQ_API_KEY` in `.env`, the `claude` CLI logged in, and `pip install indic-transliteration`
(test-only, not in requirements.txt). Audio copies and results stay in `data/stt_bench/` (git-ignored); nothing is
written to the live database.

Sarvam's plan allows only a few requests at once: run it one call at a time (4 at once hit HTTP 429).

## Results so far (before scoring against corrections)

| | Sarvam | Whisper + local voices |
|---|---|---|
| Time per call (median) | 9 s | 41 s |
| Calls where 2 voices were found | 20 / 20 | 9 / 20 |
| Calls with both RM and CSP labelled | 17 / 20 | 7 / 20 |
| Words captured, all 20 calls | 5,313 | 3,047 |

Example, call 434 (48 s): Whisper produced only "लोगों, आहां, बोलें।"; Sarvam produced the full conversation about
slab targets (SBY, APY, JBY counts). Word and speaker error rates are added here once corrections are in.

## Separate finding: most recordings are missing audio

In 294 of 442 processed RM recordings (67%) the audio file holds less than 80% of the call, usually 1–2 seconds of a
1–4 minute call (about 6.5 hours lost). The files were uploaded long after each call ended, so it is not an early
upload: the phone's recorder captured only the start. It improved from 4 Nov but was still 19 of 69 on 5 Nov. No
engine can fix this; it has to be fixed on the phone (dialer recording settings / Android version), and is the
bigger cause of "bad transcripts" on the site.

## Decided next steps

- Pick the engine from the scores, then switch production (`SARVAM_API_KEY` as a server secret if Sarvam wins).
- Fix the speaker count at 2 (`RECORDINGS_SPEAKERS=2`); allow up to 3 only if the corrections show 3-person calls
  are common.
- Save each RM's voice once and match against it, so "which voice is the RM" is measured, not guessed by the LLM.
- Remove `app/claude_stt.py`: Claude cannot transcribe audio, so it always fell back to Groq.
- Find why phone recordings are cut short.
