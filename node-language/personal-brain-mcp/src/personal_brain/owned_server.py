"""Owned Speckle server readiness — brain-side status + flag.

Founder goal 2026-06-01: a community can converge through "my own server"
(no external SaaS account). The ACTUAL lifecycle (docker compose up/down,
compose-file management, /api/health polling) lives in
`app/speckle_server.py` and is driven by the desktop bridge — this module
does NOT duplicate it (ONE-SYSTEM-PLAN-BEFORE-BUILD). It is the thin,
daemon-side STATUS + GATE the brain needs so a `speckle` community transport
can be validated and the Docker-absent case flagged honestly to the user.

What it provides:
  * docker_available()  — same pure-stdlib check as app/speckle_server.py
                          (docker on PATH AND `docker info` daemon responds).
  * server_reachable()  — GET <url>/api/health; True iff a Speckle-shaped
                          server answers.
  * readiness(base_url) — combined report the community tooling surfaces:
                          {reachable, docker_available, can_start, code, ...}.

`code` mirrors app/speckle_server.start_local's vocabulary so the desktop
+ brain agree:
    "running"        — server already reachable; nothing to do
    "ready_to_start" — docker present + daemon up; start_local would work
    "docker_missing" — docker absent / daemon down → user must install +
                       start Docker Desktop (the one true boundary)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Optional


_DEFAULT_URL = "http://localhost:3000"


def docker_available() -> bool:
    """True iff a `docker` CLI is on PATH AND the daemon responds.

    Byte-for-byte the same gate as app/speckle_server.docker_available so
    the brain and the desktop never disagree about whether an owned server
    can start.
    """
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


def server_reachable(url: str = _DEFAULT_URL, *, timeout: float = 2.0) -> bool:
    """GET <url>/api/health (then /healthcheck, /) — True on any 2xx."""
    base = url.rstrip("/")
    for path in ("/api/health", "/healthcheck", "/"):
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=timeout) as r:
                if r.status < 400:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return False


def readiness(base_url: str = _DEFAULT_URL) -> dict:
    """Combined owned-server readiness report for the community tooling.

    Never starts anything — the desktop bridge owns the actual
    `app/speckle_server.start_local()` call. This is the truthful gate the
    brain surfaces so the founder sees exactly why a `speckle` community
    transport is or isn't live yet.
    """
    url = (base_url or _DEFAULT_URL).rstrip("/")
    reachable = server_reachable(url)
    if reachable:
        return {
            "base_url": url,
            "reachable": True,
            "docker_available": True,  # something is answering on the port
            "can_start": True,
            "code": "running",
            "message": f"Owned Speckle server reachable at {url}.",
        }
    has_docker = docker_available()
    if has_docker:
        return {
            "base_url": url,
            "reachable": False,
            "docker_available": True,
            "can_start": True,
            "code": "ready_to_start",
            "message": (
                f"Docker is up; owned Speckle server not yet running at {url}. "
                "Start it from the desktop (Settings -> Brain -> Start my "
                "Speckle server), which runs `docker compose up -d`."
            ),
        }
    return {
        "base_url": url,
        "reachable": False,
        "docker_available": False,
        "can_start": False,
        "code": "docker_missing",
        "message": (
            "Docker is not installed or its daemon is not running, so an "
            "owned Speckle server cannot start on this machine yet. Install "
            "Docker Desktop (https://www.docker.com/products/docker-desktop) "
            "and start it; then the community can converge through your own "
            "server. Until then, use transport_kind='cloud_relay' (your "
            "ArchHub account) or 'disk' (a shared folder) — both work today."
        ),
    }
