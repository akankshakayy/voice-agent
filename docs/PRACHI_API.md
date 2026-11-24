# Recordings hand-off to Prachi's CRM

Every new **RM and DC** call recording is sent to Prachi's CRM webhook within seconds of upload. Only the call
details and an audio link are sent, never the transcript, so the hand-off does not wait for transcription.
Employee recordings are never sent. Agreed with Prachi on 2026-11-24.

Code: `app/recordings.py` (`send_to_prachi`, `prachi_loop`), audio route and test send in `app/main.py`.

## Switching it on

| Setting (eko-deploy secret) | Meaning |
|---|---|
| `PRACHI_RECORDING_SECRET` | Shared secret, sent as the `X-Recording-Secret` header. Also signs the audio links. |
| `PRACHI_SEND_FROM` | Switch-on date, e.g. `2026-11-25` (Indian time). **Unset = feed off.** Only recordings uploaded on or after it are sent. |
| `APP_BASE_URL` | Our public address, used to build the full audio link. |

```
eko-deploy secret set rm-voice-agent PRACHI_SEND_FROM --stdin    # then: eko-deploy restart rm-voice-agent
```

## What is sent

`POST https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings`, a JSON list of up to 50 records:

```json
[{
  "id": "1123",
  "rm_number": "9876543210",
  "other_number": "+91 87654 32109",
  "direction": "outbound",
  "started_at": "2026-11-25T10:30:00+05:30",
  "duration": 95,
  "audio_url": "https://indev.eko.in/rm-voice-agent/api/prachi/recordings/1123/audio?exp=…&sig=…"
}]
```

- **RM call:** `rm_number` (the RM) + `other_number` (the CSP). **DC call:** `dc_number` (the DC) + `other_number`
  (the SBI official). Exactly one of `rm_number` / `dc_number` is present; Prachi tells them apart by that.
- `id` is our recording id, unique across RM and DC. A test send uses `test_<id>`.
- `direction` is `inbound` / `outbound`, and is left out when the phone did not tell us.
- `started_at` always carries the `+05:30` offset.
- `audio_url` is a full link that works with a plain GET for one hour (signed with the shared secret;
  a wrong or expired signature gets 403). Prachi downloads the audio as soon as the record arrives.

## Prachi's reply and what we do

Prachi replies `202` with a result per record, which we store in `recordings.prachi_status` / `prachi_reason`:

| `prachi_status` | Meaning | Retried? |
|---|---|---|
| `queued` | Accepted; Prachi downloads the audio in the background | no |
| `duplicate` | Already stored by Prachi | no |
| `skipped` | A party is not in her CRM (`rm_not_in_crm`, `csp_not_in_crm`, `dc_not_in_crm`, `official_not_in_crm`, `too_short`) | no |
| `invalid` | Something is wrong with the record (reason says what) | only after a fix, by clearing `prachi_status` |
| `no_staff_number` | (ours) We have no phone number for the RM/DC, so it was never sent | no |
| `gave_up` | (ours) Not accepted within 24 hours | no |

- **Timeout, connection error or 5xx:** the record stays pending and is retried every 5 minutes, for up to 24 hours.
- **401 (wrong secret):** sending pauses until the app restarts with a corrected secret. Nothing is lost: the
  records stay pending (within the 24-hour window).

## Test send

An admin can send one recording to the live webhook as `test_<id>` and see Prachi's reply. It changes nothing on
our side:

```
POST /rm-voice-agent/api/prachi/test-send/<recording id>      (admin sign-in)
```

Prachi removes the test entry on her side afterwards.

## Checking it

```
eko-deploy logs rm-voice-agent --tail 500 | grep -i prachi
```

`Prachi hand-off: N sent, {'queued': …, 'skipped': …}` is logged for every batch.
