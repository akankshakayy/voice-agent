# RM voiceprints: which voice in a call is the RM

Sarvam splits each recorded call into two voices (A and B) but cannot say who is who. Before this change, the AI
review guessed from the words. Now each RM has a **voiceprint**, a list of 192 numbers that describes their voice,
made once from a short sample. On every RM call, the voice that sounds like that RM is labelled RM.

## How to add or replace a voiceprint

1. Record 30–60 seconds of the RM talking alone: a WhatsApp voice note is fine; any audio format works.
2. Open **/admin → RM Voice Samples**, click **Upload sample** next to the RM and pick the file.
3. The server keeps only the voiceprint and deletes the audio. Samples under 20 seconds are refused; under 30 seconds
   are saved with a warning.

The first upload after a deploy takes about a minute: the server downloads the voice model (about 40 MB) once.

## How it decides

- For each voice in the call, its lines of 0.8 seconds or longer are joined and compared with the RM's voiceprint
  (cosine similarity, 3D-Speaker ERes2Net model via sherpa-onnx).
- The voice with the highest score is the RM if it beats the other voice by at least 0.08
  (`VOICEPRINT_MIN_MARGIN`). Otherwise the AI's guess is used.
- The AI review is told which voice is the RM, so the summary and the speaker labels agree.
- Only RM-mode calls are matched. DC calls, transcripts a person has corrected, and RMs without a voiceprint use the
  AI's guess as before. A failure in matching never fails the recording.
- Each recording's `timing_json.voiceprint` stores the scores, the margin, the chosen voice and whether the AI would
  have picked the same voice (`ai_agreed`), so the two can be compared on live calls.

## Test result (25 Nov 2026)

On the 20 A/B test calls (all Vandana's), with samples recorded as WhatsApp voice notes:

| | Right RM voice |
|---|---|
| Voiceprint | 20 of 20 |
| AI guess from the words | 19 of 20 (call 89: the AI picked the man who says "हाँ Madam, बोलिए") |

The smallest gap between the RM's voice and the other voice was 0.12, the median 0.31. Similarity between the three
RMs' own samples is 0.21–0.39, so the model tells them apart well. Shiwani's and Amuda's voiceprints are untested
until their phones upload calls.

## Privacy

A voiceprint is biometric personal data. The sample audio is not stored on the server; the voiceprint is stored in
`rms.voiceprint_json`. Each RM should agree to it. Admins can delete a voiceprint on the same page.
