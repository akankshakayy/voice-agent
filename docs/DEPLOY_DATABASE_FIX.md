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
