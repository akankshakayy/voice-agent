FROM python:3.12-slim

WORKDIR /app
COPY . /app/

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user matching eko-deploy's enforced user
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/data/logs && \
    chown -R 10001:10001 /app && \
    chmod -R 755 /app

USER 10001

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
