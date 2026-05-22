# Cloud-daemon image. Runs `python -m agents.cloud_runner` 24/7 on Fly.io.
#
# Build:   docker build -f agents/Dockerfile -t archhub-agents .
# Run:     docker run --rm -e ANTHROPIC_API_KEY=... -v $PWD/data:/data archhub-agents
# Deploy:  fly deploy --config agents/fly.toml
#
# Build context: repo root (so we can COPY in the agents/ package).

# Multi-stage: separate build layer for pip install so the runtime image
# doesn't carry build toolchain artefacts. 3.13 (not 3.14) for stable
# pydantic-core wheels; FastAPI + uvicorn ship aarch64 + x86_64 wheels here.
FROM python:3.13-slim AS build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt ./requirements.txt
RUN pip install --prefix=/install -r requirements.txt


# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    ARCHHUB_AGENTS_BACKEND=anthropic \
    ARCHHUB_AGENTS_DATA_ROOT=/data/agents \
    ARCHHUB_AGENTS_CYCLE=60
# ENV=production omitted intentionally — agents config raises on
# missing ANTHROPIC_API_KEY when production is set. Promote after
# the key lands as a Fly secret.

WORKDIR /app

# Bring the pre-installed deps from the build stage.
COPY --from=build /install /usr/local

# Copy the agents package contents into /app/agents/. Build context
# is the agents/ directory (fly.toml lives there too).
COPY . /app/agents/

# Drop privileges. The Fly volume gets chowned to this user on first
# mount via the entrypoint shim below.
RUN useradd --create-home --shell /bin/bash agentuser \
 && mkdir -p /data/agents \
 && chown -R agentuser:agentuser /data/agents /app

USER agentuser

# Volume for persistent task state + outputs + heartbeat.
VOLUME ["/data"]

# Dashboard HTTP port (Fly may or may not expose this — see fly.toml).
EXPOSE 8080

# CMD — single process; cloud_runner spins up the dashboard on a
# thread itself, so we don't need a process manager.
CMD ["python", "-m", "agents.cloud_runner"]
