#!/bin/sh
# Container entrypoint. eko-deploy runs the container with a read-only root filesystem;
# only /tmp and the declared volume (/app/data, see eko-deploy.toml) are writable.
set -e

: "${EKO_DB_PATH:=/app/data/eko_agent.db}"
: "${DATA_DIR:=$(dirname "$EKO_DB_PATH")}"
export EKO_DB_PATH DATA_DIR

mkdir -p "$DATA_DIR/logs"

# Seed the persistent database from the copy bundled in the image ONLY on first boot.
# Never overwrite an existing database: it holds live data.
if [ ! -e "$EKO_DB_PATH" ] && [ -f /app/eko_agent.db ]; then
  echo "No database at $EKO_DB_PATH - seeding from bundled /app/eko_agent.db"
  cp /app/eko_agent.db "$EKO_DB_PATH"
else
  echo "Using existing database at $EKO_DB_PATH"
fi

echo "Database: $EKO_DB_PATH | DATA_DIR: $DATA_DIR | DEV_MODE: ${DEV_MODE:-not set}"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"
