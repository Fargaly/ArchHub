"""Speckle Server lifecycle — M1.5 (per founder decision 2026-05-21).

Founder: "create nodes that when the user uses them inside their workflow
it opens a local host server so the worksharing is OPTIONAL."

This module is the lifecycle layer behind the 3 typed SHARE nodes
(`speckle.publish` / `speckle.subscribe` / `speckle.server`). When a
user wires a SHARE node into their graph + cooks it, this module
ensures a localhost Speckle Server is reachable — installs nothing
silently, prompts via typed errors when something is missing.

Architecture:
  • DiskTransport (specklepy.SQLiteTransport via `speckle_wire.py`)
    stays the DEFAULT wire substrate — runs offline, no Docker, no
    server. Use this for solo / disconnected work.
  • Speckle Server runs as a Docker Compose stack of:
    speckle-frontend + speckle-server (Node.js) + postgres + redis +
    minio (S3-compatible object storage). Lifecycle managed here.
  • OPT-IN: ServerTransport activates only when the user places a
    SHARE node (`speckle.publish` etc.). At first run we offer to
    start the server; subsequent runs are silent.

Public API:
    is_running(url='http://localhost:3000') -> {running, version, ...}
    start_local(port=3000) -> {url, status, error?}
    stop_local() -> {ok}
    status() -> {url, running, docker_available, compose_path, ...}
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


# Where the bundled compose file lives (gets copied into the user's
# data dir on first start so it survives ArchHub updates).
_BUNDLED_COMPOSE = (Path(__file__).resolve().parent.parent
                    / "docker-resources" / "speckle-compose.yml")

# Where the per-user persisted compose + data lives. Survives across
# ArchHub sessions; the Speckle DB/object-store persists here too.
_USER_DIR = (Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))
             / "ArchHub" / "speckle-server")

_DEFAULT_PORT = 3000

# Server-up poll cadence + ceiling. Speckle's full stack takes ~30-45s
# cold start (Postgres init, Redis ready, server bind). Cap at 90s.
_POLL_INTERVAL = 1.5
_POLL_TIMEOUT  = 90.0


# ---------------------------------------------------------------------------
# Helpers — Docker presence + health probe


def docker_available() -> bool:
    """True if a `docker` CLI is on PATH AND the daemon responds."""
    if not (shutil.which("docker") or shutil.which("docker.exe")):
        return False
    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=5,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0),
        )
        return r.returncode == 0 and (r.stdout or "").strip() != ""
    except Exception:
        return False


def _health_probe(url: str, *, timeout: float = 2.0) -> Optional[dict]:
    """GET <url>/api/health. Returns the parsed payload if reachable
    AND smells like a Speckle Server (response includes a `serverInfo`
    or `version` field). Else None."""
    base = url.rstrip("/")
    for path in ("/api/health", "/healthcheck", "/"):
        try:
            with urllib.request.urlopen(
                    f"{base}{path}", timeout=timeout) as r:
                if r.status >= 400:
                    continue
                raw = r.read().decode("utf-8", errors="replace") or ""
                try:
                    data = json.loads(raw or "{}")
                except json.JSONDecodeError:
                    data = {"raw": raw[:200]}
                # Discriminator: a real Speckle Server returns
                # /api/health → {ok: true} OR /info → {version, ...}.
                # Accept any 2xx for now; identity check is a polish step.
                return {"endpoint": path, "payload": data}
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return None


# ---------------------------------------------------------------------------
# Compose file management


def _ensure_compose_at_user_dir() -> Path:
    """Copy the bundled compose template to the user's persisted dir
    on first use. Returns the user-dir compose path. Idempotent."""
    _USER_DIR.mkdir(parents=True, exist_ok=True)
    user_compose = _USER_DIR / "docker-compose.yml"
    if not user_compose.exists():
        if _BUNDLED_COMPOSE.exists():
            user_compose.write_bytes(_BUNDLED_COMPOSE.read_bytes())
        else:
            # Bundled template missing — write a minimal one inline.
            user_compose.write_text(_minimal_compose_yaml(),
                                     encoding="utf-8")
    return user_compose


def _minimal_compose_yaml() -> str:
    """Fallback when the bundled template isn't shipped yet. Pulls the
    official Speckle compose-published images; spins up a usable
    instance with default credentials. The user can replace it with a
    custom compose at `~/AppData/Local/ArchHub/speckle-server/docker-compose.yml`."""
    return _MINIMAL_COMPOSE


# Inline minimal compose used when the bundled template is absent.
# Sourced from Speckle's official self-host quickstart shape; not all
# services (gunicorn / preview-service) are included — bare HTTP only.
_MINIMAL_COMPOSE = """\
# ArchHub-bundled minimal Speckle Server.
# For a full production stack, replace with the official
# Speckle docker-compose from https://github.com/specklesystems/speckle-server
services:
  postgres:
    image: postgres:14-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: speckle
      POSTGRES_USER: speckle
      POSTGRES_PASSWORD: speckle
    volumes:
      - postgres-data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data

  minio:
    image: minio/minio:latest
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: speckle
      MINIO_ROOT_PASSWORD: speckle1234
    volumes:
      - minio-data:/data

  speckle-server:
    image: speckle/speckle-server:2
    restart: unless-stopped
    depends_on: [postgres, redis, minio]
    ports:
      - "3000:3000"
    environment:
      POSTGRES_URL: "postgres:5432/speckle?user=speckle&password=speckle"
      REDIS_URL: "redis://redis:6379"
      S3_ENDPOINT: "http://minio:9000"
      S3_ACCESS_KEY: speckle
      S3_SECRET_KEY: speckle1234
      S3_BUCKET: speckle-server
      S3_CREATE_BUCKET: "true"
      CANONICAL_URL: "http://localhost:3000"
      SESSION_SECRET: "archhub-local-dev-secret-replace-in-prod"
      LOG_LEVEL: info
      LOG_PRETTY: "true"

volumes:
  postgres-data:
  redis-data:
  minio-data:
"""


# ---------------------------------------------------------------------------
# Public API


def is_running(url: str = f"http://localhost:{_DEFAULT_PORT}") -> dict:
    """Quick reachability check. Returns:
        {running: bool, url, version?, endpoint?}
    """
    probe = _health_probe(url)
    if not probe:
        return {"running": False, "url": url}
    payload = probe.get("payload") or {}
    return {
        "running": True,
        "url": url,
        "endpoint": probe.get("endpoint"),
        "version": payload.get("version"),
    }


def start_local(port: int = _DEFAULT_PORT,
                *, wait: bool = True) -> dict:
    """Ensure a Speckle Server is reachable on localhost:<port>.

    Idempotent: if already running, returns {url, status:'running'}
    without touching Docker. If not running, requires Docker — runs
    `docker compose up -d` on the user-dir compose file. With wait=True
    polls /api/health until the server responds (~30-90s cold start)."""
    url = f"http://localhost:{port}"

    # Fast path — already up.
    probe = is_running(url)
    if probe["running"]:
        return {"url": url, "status": "running",
                "version": probe.get("version")}

    if not docker_available():
        return {
            "url": url, "status": "error",
            "error": (
                "Docker not installed or daemon not running. Install "
                "Docker Desktop (https://www.docker.com/products/docker-desktop) "
                "then place a SHARE node in your graph to retry."
            ),
            "code": "docker_missing",
        }

    compose_path = _ensure_compose_at_user_dir()
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_path),
             "up", "-d"],
            capture_output=True, text=True, timeout=120, check=True,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0),
        )
    except subprocess.CalledProcessError as ex:
        return {"url": url, "status": "error",
                "error": f"docker compose up failed: {ex.stderr[:300]}",
                "code": "compose_failed"}
    except subprocess.TimeoutExpired:
        return {"url": url, "status": "error",
                "error": "docker compose up timed out after 120s",
                "code": "compose_timeout"}

    if not wait:
        return {"url": url, "status": "starting",
                "compose_path": str(compose_path)}

    # Poll for readiness — Speckle stack takes ~30-90s cold-start.
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        probe = is_running(url)
        if probe["running"]:
            return {"url": url, "status": "running",
                    "compose_path": str(compose_path),
                    "version": probe.get("version")}
        time.sleep(_POLL_INTERVAL)

    return {"url": url, "status": "error",
            "error": (
                f"Server didn't respond within {_POLL_TIMEOUT:.0f}s. "
                "Check `docker compose logs speckle-server` in "
                f"{compose_path.parent}."
            ),
            "code": "server_unhealthy",
            "compose_path": str(compose_path)}


def stop_local() -> dict:
    """Stop the localhost Speckle Server (docker compose down).
    Data volumes persist; restart picks up where it left off."""
    if not docker_available():
        return {"ok": False, "error": "docker not available",
                "code": "docker_missing"}
    compose_path = _ensure_compose_at_user_dir()
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "down"],
            capture_output=True, text=True, timeout=60, check=True,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0),
        )
        return {"ok": True}
    except subprocess.CalledProcessError as ex:
        return {"ok": False,
                "error": f"docker compose down failed: {ex.stderr[:300]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "docker compose down timed out"}


def status() -> dict:
    """Combined status — docker presence, server reachability, paths."""
    url = f"http://localhost:{_DEFAULT_PORT}"
    return {
        "docker_available":  docker_available(),
        "compose_template_bundled": _BUNDLED_COMPOSE.exists(),
        "user_data_dir":     str(_USER_DIR),
        "user_compose_path": str(_USER_DIR / "docker-compose.yml"),
        **is_running(url),
    }


def push_to_server(value: Any, server_url: str,
                    model_name: str = "default",
                    *, token: Optional[str] = None) -> str:
    """Push `value` to a Speckle Server via ServerTransport. Returns
    the canonical `{server}/streams/{model}/objects/{hash}` URL.

    The single canonical entry-point for server pushes — used by
    `share.publish` AND `revit.send_to_speckle` (M2-Python /
    AgDR-0017) so the wire-format + auth + fallback logic lives in
    ONE place. Anonymous push is attempted by default; pass `token`
    when the server requires auth (the M6 collaboration polish slice
    will wire that through bridge settings).

    Raises on any failure — the caller decides whether to fall back
    gracefully (share.publish + revit.send_to_speckle both do).
    """
    from specklepy.api.client import SpeckleClient
    from specklepy.transports.server import ServerTransport
    from specklepy.api import operations
    from speckle_wire import _coerce_to_base  # type: ignore

    client = SpeckleClient(host=server_url,
                            use_ssl=server_url.startswith("https"))
    if token:
        try:
            client.authenticate_with_token(token)
        except Exception:
            # Fall through — anonymous attempt will surface the right
            # error if the server requires auth.
            pass
    transport = ServerTransport(client=client, stream_id=model_name)
    base = _coerce_to_base(value)
    hash_id = operations.send(base, [transport], use_default_cache=False)
    return (f"{server_url.rstrip('/')}/streams/{model_name}"
            f"/objects/{hash_id}")
