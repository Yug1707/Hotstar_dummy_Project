# Build from the repo root:  docker build -f app/Dockerfile --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t streamlite .
FROM python:3.12-slim

ARG GIT_SHA=dev
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_VERSION=$GIT_SHA \
    WEB_CONCURRENCY=1 \
    WEB_DIR=/app/web

LABEL org.opencontainers.image.title="streamlite" \
      org.opencontainers.image.description="Hotstar Scale Lab - StreamLite API" \
      org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/*.py ./
COPY web/ ./web/
COPY scripts/calibrate.py ./scripts/calibrate.py

RUN useradd --uid 10001 --create-home app
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=2s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=1)"

# --workers 2 only if E1 shows GIL contention (plan §4.6); stats stay correct either way.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log --workers ${WEB_CONCURRENCY}"]
