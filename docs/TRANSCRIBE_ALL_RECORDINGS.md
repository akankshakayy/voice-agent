# Every RM call with audio is transcribed (2026-11-19)

## Before
`process_one` marked a recording "done" without transcribing it when:
- the other number was not in the CSP calling sheet ("Calling number not in CSP list")
- it was shorter than 2 seconds
- it came from an employee phone, or was a legacy DC call

`POST /api/recordings/cleanup` was in `PUBLIC_PATHS` (no sign-in needed) and deleted every
non-CSP and under-2-second recording.

## Now
- Every RM-mode recording whose audio file exists is transcribed and reviewed, whatever its length or number.
- Employee recordings are unchanged: not transcribed, audio pushed to AutoGMap.
- DC recordings are unchanged: transcribed only when the number is in the CSP list; legacy DC calls are not.
- A recording whose audio file is missing is marked `failed` with "Audio file is missing on the server"
  instead of retrying ffmpeg three times.
- At startup, `recordings.requeue_untranscribed()` puts back in the queue every RM recording that has audio but
  no transcript (skipped by the old rules, or given up on after 3 failures).
- `POST /api/recordings/cleanup` is admin-only and deletes nothing: it runs the same re-queue.
  CLI: `python -m app.recordings cleanup`.

## Note
The backlog is transcribed on Groq Whisper. If the free-tier limit is hit, the queue pauses and resumes
30 minutes later on its own.
