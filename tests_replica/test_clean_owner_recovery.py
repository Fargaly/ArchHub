"""Courts for the owner that survives its own violent death."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from tests_replica.test_clean_server_visual_projection import (
    _provision_clean_runtime,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _answers(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read(1)
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _await_owner(url: str, deadline_seconds: float = 90.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if _answers(url):
            return True
        time.sleep(1.0)
    return False


def _spawn_owner(root: Path, port: int, canvas_port: int):
    """A real subprocess. A same-process simulation of kill -9 is not one."""
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "nodelang.clean_coordination_service",
            "--port",
            str(port),
            "--canvas-port",
            str(canvas_port),
            "--root",
            str(root),
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_a_killed_owner_leaves_a_lock_a_fresh_owner_can_take(tmp_path):
    """Releasing a lock and being able to serve again are different facts.

    A court that asserts only the release passes over a system that is
    permanently broken: a fresh process can acquire a released lock and
    still fail to bind a socket, and a restart that silently orphans the
    enrolments it was protecting looks fine from outside. The kill is a
    real SIGKILL of a real subprocess, because killing the owner
    in-process exercises the finally block -- the case that already works
    -- and leaves the in-memory owner set alive, which is bookkeeping
    rather than death.
    """
    # NAMED GAP, not a passing court: the owner entry point signs with the
    # founder's DPAPI provider, and a fixture graph is signed by its own
    # test key, so a spawned owner refuses it with "bootstrap signing key
    # fingerprint is invalid". Measured, not assumed. The only graph a real
    # owner subprocess can open today is the founder's live one -- and
    # killing THAT to court crash recovery is the exact production hazard
    # required-not-defaulted was just landed to prevent.
    #
    # This is a finding about the system, not a limitation of the court:
    # crash recovery cannot be exercised end to end until an owner can be
    # pointed at a graph whose signing identity a court may hold. The
    # properties below are therefore recorded and skipped rather than
    # weakened into something that would pass in-process, which would test
    # the bookkeeping and not the death.
    pytest.skip(
        "owner subprocess cannot open a court-signed graph: the entry point "
        "uses the founder DPAPI provider (bootstrap signing key fingerprint "
        "is invalid). Recovery stays uncourted until an owner accepts a "
        "court-held signing identity."
    )
    built, _provider = _provision_clean_runtime(tmp_path)
    root = Path(built.location.root)
    built.location.authority.store.close()
    # Belt to the library's braces. A court that spawns owners must never
    # be able to spawn one over the founder's live generation: acquiring a
    # free live lock, asserting, and exiting would take the real service
    # down while looking like legitimate ownership from every angle.
    from nodelang.unified_authority_runtime import default_runtime_root
    assert root.resolve() != default_runtime_root().resolve()

    port, canvas_port = _free_port(), _free_port()
    health = "http://127.0.0.1:%d/health" % port

    first = _spawn_owner(root, port, canvas_port)
    try:
        assert _await_owner(health), "the first owner never began serving"
    finally:
        # K2: no graceful path. finally must never run in the owner.
        first.kill()
        first.wait(timeout=30)

    assert first.returncode is not None

    # K3: no manual cleanup. Nothing is deleted, touched, or repaired
    # between the death and the next start.
    second = _spawn_owner(root, port, canvas_port)
    try:
        acquired = _await_owner(health)
        if not acquired:
            _out, err = second.communicate(timeout=10)
            pytest.fail(
                "a fresh owner could not take the lock a killed owner left: "
                "%s" % err.decode("utf-8", "replace")[-400:]
            )
        # K4: acquiring is not serving, and one surface is not both.
        assert _answers(
            "http://127.0.0.1:%d/api/universal/canvas" % canvas_port,
            timeout=30.0,
        ), "the fresh owner took the lock but never stood the canvas"
    finally:
        second.kill()
        second.wait(timeout=30)
