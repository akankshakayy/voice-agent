FROM python:3.12-slim

WORKDIR /app
COPY . /app/

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user and data directories
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/data/logs && \
    chown -R 10001:10001 /app && \
    chmod -R 755 /app

USER 10001

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Persistent volumes for database and logs
VOLUME ["/app/data", "/data"]

# Startup script: initialize database location
RUN echo '#!/bin/bash\nset -e\necho "Setting up data directory..."\nmkdir -p /app/data/logs\necho "Checking database location..."\nDB_PATH="${DB_PATH:-/app/data/eko_agent.db}"\necho "Using database: $DB_PATH"\nif [ ! -f "$DB_PATH" ] && [ -f /data/eko_agent.db ]; then\n  echo "Copying database from /data mount..."\n  cp /data/eko_agent.db /app/data/ 2>/dev/null || echo "Could not copy from /data"\nfi\necho "Starting Eko RM Voice Agent..."\nexec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
