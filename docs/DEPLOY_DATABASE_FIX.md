# Fix: `/api/dcs` and `/api/allowed-numbers` returned HTTP 500 (Nov 18, 2026)

## Symptom
Admin panel empty; every DB query failed with `sqlite3.OperationalError: unable to open database file`
(`eko-deploy logs rm-voice-agent`).

## Root cause
- eko-deploy runs containers with a **read-only root filesystem** (only `/tmp` and declared volumes are writable).
- With no `eko-deploy.toml`, AutoPilot configured the project. It ignores `eko.yml`, so `EKO_DB_PATH`
  was never set and the old `start.sh` picked the bundled `/app/eko_agent.db`. SQLite (WAL mode) cannot
  open a database in a read-only directory.
- The Dockerfile's build-time copy into `/app/data` ran after `VOLUME`, so Docker discarded it.
- eko-deploy builds from the server folder `~/voice_agent`, so commits must be `git pull`ed there first.

## Fix
- `eko-deploy.toml`: port 8000, `health_path=/healthz`, user 10001, `DATA_DIR=/app/data` (`EKO_*` env names are reserved by the platform; `EKO_DB_PATH` comes from the Dockerfile ENV / `start.sh` default),
  a named persistent volume at `/app/data`, and the list of secrets.
- `start.sh`: seeds `/app/data/eko_agent.db` from the bundled copy **only if it doesn't exist**; never overwrites.
- `.dockerignore`: excludes `.env` and `data/` from the image.
- `app/db.py`: migrations ignore only `duplicate column name`; any other error is logged and re-raised.
- `app/main.py`: removed all temporary diagnostics, including the public `/api/debug/db-path`.

## Verified locally
Image run with `--read-only --tmpfs /tmp -v <volume>:/app/data`: first boot seeds, restart reuses the DB,
`/healthz` 200, `/api/dcs` 9 rows, `/api/allowed-numbers` 874 rows.

## Deploying
```
cd ~/voice_agent && git pull && git log --oneline -1
eko-deploy deploy rm-voice-agent --no-prompt
```
New secrets must also be added to `secrets = [...]` in `eko-deploy.toml`.

## Follow-up (r0157 → next release): volume already had an empty database
r0157 fixed the 500s, but the `data` volume already contained an `eko_agent.db` (origin unproven; most
likely left by an earlier release), so `start.sh` did not seed it and both endpoints returned 0 rows.

`app/bootstrap.py: seed_reference_data()` now runs at startup: for `dcs` and `allowed_numbers` only,
if the live table is **empty**, it copies the rows (IDs kept) from the bundled `/app/eko_agent.db`
(opened read-only, `immutable=1`). No other table is touched and existing rows are never overwritten;
on later starts it copies nothing. Tested locally against an existing empty DB with an unrelated row:
9 + 874 rows seeded, unrelated row kept, restart copied 0.

## Security fix: DC and allowed-number lists required no sign-in
`GET /api/dcs` and `GET /api/allowed-numbers` were in `PUBLIC_PATHS` (a workaround from Nov 13, when the
admin page did not yet send its cookie). Anyone with the URL could read all 874 real phone numbers.
The admin page already sends `credentials: "include"`, so the workaround is not needed: both are removed
from `PUBLIC_PATHS` and now use `Depends(allow("admin"))`, like `/api/employees`.
Tested: no sign-in → 401, admin → 200 (9 / 874), ops → 403.

## Cleanup (Nov 18)
- `DEV_MODE` removed from the server (secret unset, dropped from `eko-deploy.toml`). It only made requests from
  127.0.0.1 act as admin without sign-in (`app/main.py` `require_login`); use it for local dev only.
- `eko_agent.db` is no longer tracked in git (`*.db` ignored again). The live data is in the persistent `data`
  volume; the startup seed simply skips when no bundled DB exists. A copy was kept on the server in
  `~/voice_agent/data/eko_agent.bundled-20261118.db`. The file (real phone numbers) is still in git history.
- `eko.yml` deleted: eko-deploy never read it; `eko-deploy.toml` is the real config.
- SSH password removed from `deploy_data.sh` / `DEPLOYMENT_INSTRUCTIONS.md` (still in history: rotate it).

## Employee/DC delete + push to Mansi's AutoGMap (Nov 18)
- `DELETE /api/employees/{id}` and `DELETE /api/dcs/{id}` added (admin only); the admin page's Delete gave 405.
  Someone with recordings/uploader history is kept but marked inactive and their uploader tokens revoked.
- Employee recordings are PUSHED to AutoGMap (`POST AUTOGMAP_RECORDINGS_URL`, multipart: file, phone, direction
  in/out, duration_seconds, recording_id, started_at), only if the other number is on AutoGMap's applicant list
  (matched on the last 10 digits, sent in AutoGMap's own format). Rate-limited queue, retries 60/300/900 s.
- Removed `send_to_mansi_api` (sent only JSON with an internal file path to the same URL: duplicate, no audio).
- Recordings that arrive while AutoGMap is off or before the first numbers sync are `autogmap_status='waiting'`
  and are sent after the next successful sync (also re-sends `pending` ones lost in a restart).
- Pull endpoints (`/api/mansi/recordings`, `/api/autogmap/recordings/{id}/audio`) stay locked (sign-in / API key).
- Server secrets: `AUTOGMAP_*` set, but `AUTOGMAP_ENABLED=false` because AutoGMap answers 401 to the current key.
  To switch on once Mansi gives a valid key:
  `eko-deploy secret set rm-voice-agent AUTOGMAP_API_KEY --stdin`, same for `AUTOGMAP_ENABLED` (`true`), then deploy.
