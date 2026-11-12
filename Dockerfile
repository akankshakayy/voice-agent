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

# Startup script: ensure database exists before starting app
RUN echo '#!/bin/bash\nset -e\necho "Preparing data directory..."\nmkdir -p /app/data/logs\necho "Checking database..."\nif [ ! -f /app/data/eko_agent.db ]; then\n  echo "Database not found at /app/data/eko_agent.db"\n  # Try to restore from backup locations\n  if [ -f /backup/eko_agent.db ]; then\n    echo "Restoring from /backup/eko_agent.db"\n    cp /backup/eko_agent.db /app/data/\n  elif [ -f /tmp/eko_agent.db ]; then\n    echo "Restoring from /tmp/eko_agent.db"\n    cp /tmp/eko_agent.db /app/data/\n  else\n    echo "WARNING: No database backup found - app will create a new one"\n  fi\nelse\n  echo "Database found at /app/data/eko_agent.db"\nfi\necho "Starting Eko RM Voice Agent..."\nexec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
