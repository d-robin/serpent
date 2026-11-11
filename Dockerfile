# --- build Snake Charmer ---------------------------------------------------
FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
# vite writes to ../src/serpent/ui_dist
RUN mkdir -p /src/serpent && npm run build

# --- runtime ---------------------------------------------------------------
FROM python:3.15-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERPENT_HOME=/data \
    DB_PATH=/data/serpent.db

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
COPY --from=ui /src/serpent/ui_dist ./src/serpent/ui_dist
RUN pip install --no-cache-dir . \
 && useradd --system --uid 10001 --home /data serpent \
 && mkdir -p /data && chown serpent /data

USER serpent
VOLUME ["/data"]
EXPOSE 8971

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8971/healthz', timeout=4).status==200 else 1)"

CMD ["uvicorn", "serpent.main:app", "--host", "0.0.0.0", "--port", "8971", "--no-access-log"]
