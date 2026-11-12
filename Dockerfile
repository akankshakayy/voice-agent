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

# Startup script: handle database from host mount
RUN echo '#!/bin/bash\nset -e\necho "Preparing directories..."\nmkdir -p /app/data/logs\necho "Checking for mounted host database..."\nif [ -f /data/eko_agent.db ]; then\n  echo "Found database in /data mount (host volume)"\n  cp /data/eko_agent.db /app/data/\n  echo "Copied to /app/data/"\nelif [ ! -f /app/data/eko_agent.db ]; then\n  echo "WARNING: No database found - app will use in-memory or create new"\nelse\n  echo "Database already in /app/data"\nfi\necho "Starting Eko RM Voice Agent..."\nexec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
