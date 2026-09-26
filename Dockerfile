# syntax=docker/dockerfile:1

# ---- builder: resolve dependencies into a venv -----------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime ---------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/data/app.db \
    LOCAL_STORAGE_DIR=/data/output \
    TEMP_DIR=/data/temp \
    DATA_DIR=/data \
    LOG_DIR=/data/logs

COPY --from=builder /opt/venv /opt/venv

# Run unprivileged; /data is the only writable path the app needs.
RUN useradd --create-home --uid 10001 docxy \
    && mkdir -p /data/output /data/temp /data/logs \
    && chown -R docxy:docxy /data

WORKDIR /app
COPY --chown=docxy:docxy app ./app
COPY --chown=docxy:docxy run.py ./

USER docxy
EXPOSE 8000
VOLUME ["/data"]

# SQLite lives on a single volume and the worker is in-process, so this image
# runs as one replica. Scale extraction with WORKER_COUNT, not more containers.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status==200 else 1)"

CMD ["python", "run.py"]
