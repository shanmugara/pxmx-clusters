# Build context must be the repo root:
#   docker build -f dashboard/Dockerfile -t pxmx-dashboard .
#
# ── Stage 1: build dependencies into an isolated venv ────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools needed by some Python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY dashboard/requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt gunicorn==22.*


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as a non-root user
RUN groupadd --gid 1000 app && \
    useradd  --uid 1000 --gid app --no-create-home app

# Copy the virtualenv from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Application code
COPY --chown=app:app dashboard/app.py           ./app.py
COPY --chown=app:app dashboard/gunicorn.conf.py ./gunicorn.conf.py
COPY --chown=app:app dashboard/templates/       ./templates/

# Embed the cluster template so /api/template returns pre-populated YAML.
# The app resolves this relative to app.py's parent: ../example-cluster.yaml
# which maps to /example-cluster.yaml inside the container.
COPY --chown=app:app example-cluster.yaml ./example-cluster.yaml

USER app

EXPOSE 5001

# Health check — matches the /healthz endpoint added to app.py
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/healthz')"

ENTRYPOINT ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
