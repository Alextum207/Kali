# Playwright's official image ships Chromium + all its native deps
# preinstalled for the exact playwright version pinned below — avoids a
# separate `playwright install --with-deps chromium` step and version drift
# between the pip package and the browser binary.
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

# WeasyPrint needs these as shared libs by name (Pango/GDK-Pixbuf/cairo) —
# Playwright's image has its own copies for browser rendering, but not
# necessarily the dev/shared-lib packages WeasyPrint's cffi bindings dlopen.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# DB/evidence go to /var/data, NOT ./data — ./data/consent_rules is baked
# into the image (read via DEFAULT_CONSENT_RULES_DIR, unrelated to these two
# env vars) and must not be hidden by Render's optional persistent disk
# mount (render.yaml mounts at /var/data — mounting over ./data instead
# would shadow consent_rules/ with the empty/persisted disk).
RUN mkdir -p /var/data/evidence
ENV DB_PATH=/var/data/monitor.db
ENV EVIDENCE_DIR=/var/data/evidence

EXPOSE 8000
# Shell form (not exec-form JSON array) so $PORT actually expands — Render
# assigns a dynamic port via this env var and routes its proxy there; a
# hardcoded --port 8000 works locally but causes 502 Bad Gateway on Render
# since its edge can't reach whatever port the container really bound to.
# ${PORT:-8000} falls back to 8000 for local `docker run` (no PORT set).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
