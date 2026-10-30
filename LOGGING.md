# Logging Guide

## Overview
The app uses Python's standard `logging` module with a centralized configuration that handles both file and console output with automatic rotation.

## Where Logs Go

### Development (local)
- **Console**: All logs printed to stdout (via `uvicorn` or direct script run)
- **Files**: `data/logs/eko.log` (created automatically)

### Production (server)
- **Console**: Captured by systemd/container (available via `journalctl` or container logs)
- **Files**: `/data/logs/eko.log` (persistent storage in mounted volume)

## Configuration

### Log Level
Set via `LOG_LEVEL` environment variable. Defaults to `INFO`.

```bash
# Debug: see everything
LOG_LEVEL=DEBUG uvicorn app.main:app

# Production default
LOG_LEVEL=INFO  # or omit (default)

# Quiet
LOG_LEVEL=WARNING
```

On the server, set in `/home/cat/.env`:
```
LOG_LEVEL=INFO
```

### File Rotation
- **Max file size**: 10MB per log file
- **Backups kept**: 5 (so `eko.log.1`, `eko.log.2`, etc.)
- **Total storage**: ~60MB max for logs

When `eko.log` reaches 10MB, it's renamed to `eko.log.1` and a fresh `eko.log` starts. Older backups rotate out.

### Log Directory
Logs are stored in `{DATA_DIR}/logs/` (default: `data/logs/`)

In production on the server, this is `/data/logs/` because `DATA_DIR` is set to `/data` (mounted volume).

## Viewing Logs

### Local development
```bash
# Real-time tail (like `tail -f`)
tail -f data/logs/eko.log

# View from start
cat data/logs/eko.log

# Last 50 lines
tail -50 data/logs/eko.log
```

### On the server
```bash
# Connect to the server
ssh root@indev.eko.in

# View logs
tail -f /data/logs/eko.log

# Or check systemd journal
journalctl -u rm-voice-agent -f  # (if running as a systemd service)
```

### Check log size
```bash
ls -lh /data/logs/
du -sh /data/logs/
```

## Logger Names

Each module has its own logger under the `eko` namespace:

- `eko` — main app (FastAPI, auth, routes)
- `eko.recordings` — recording processing
- `eko.diarize` — speaker diarization
- `eko.integrations` — webhook delivery
- `eko.mail` — email sending

Example: to set debug level only for recordings:
```python
logging.getLogger("eko.recordings").setLevel(logging.DEBUG)
```

## Usage in Code

### Basic logging
```python
from . import logging_config
log = logging_config.setup_logging("eko.mymodule")

# or (if already in main.py or a module that imports from main)
import logging
log = logging.getLogger("eko.mymodule")

# Use it
log.debug("Detailed info for debugging")
log.info("Normal operation")
log.warning("Something unexpected but handled")
log.error("An error occurred")
log.exception("An error occurred (with traceback)")
```

## Suppressing Verbose Third-Party Logs

The config already suppresses verbose output from:
- `urllib3` → WARNING
- `httpx` → WARNING  
- `asyncio` → WARNING

Add more in `logging_config.py` if needed.

## Troubleshooting

### "No logs appearing in data/logs/"
- Check that `data/` directory exists and is writable: `ls -la data/`
- Verify `LOG_LEVEL` is not `CRITICAL`
- Check console output — logs go to both files and console

### "Log file grows too fast"
- Reduce `LOG_LEVEL` to `WARNING` to log fewer messages
- Search for excessive `log.debug()` calls that should be `log.info()`
- Check for logs in tight loops (e.g., every API request if it's high volume)

### "Can't SSH to the server to check logs"
- Verify SSH credentials in `.env` (DEPLOY_SSH_KEY, DEPLOY_HOST)
- Check that you have permission to access indev.eko.in
- Use the deployment dashboard if available

## Files Modified
- `app/logging_config.py` — New centralized logging setup
- `app/main.py` — Uses `setup_logging("eko")` on startup
- `app/recordings.py` — CLI commands use `setup_logging()`
- `app/diarize.py` — CLI commands use `setup_logging()`
