"""Pytest fixtures — isolate DB per test."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    # Force config to pick up the new path on the next module load.
    import config
    monkeypatch.setattr(config, "DATABASE_URL", str(db_path))
    # cloud-brain-unify (2026-05-31): the memory DAO + /v1/brain/sync now
    # share ONE per-user store (the replica fragments). Isolate that store
    # per-test too — repoint BOTH config.REPLICAS_ROOT and the module-level
    # brain_replica.DEFAULT_REPLICAS_ROOT at the same tmp dir so a test's
    # facts/fragments never leak into the dev box's cloud_backend/data/replicas
    # and the two APIs resolve to the identical brain.db file.
    # NB: do NOT pre-create the dir here. BrainReplica.open() lazily creates
    # <root>/<user_id> with parents=True, and several test modules define
    # their OWN `replicas_root` fixture that does a bare `mkdir()` on the
    # same tmp path — pre-creating it would make that bare mkdir collide.
    replicas_root = tmp_path / "replicas"
    monkeypatch.setattr(config, "REPLICAS_ROOT", str(replicas_root))
    import brain_replica
    monkeypatch.setattr(brain_replica, "DEFAULT_REPLICAS_ROOT", replicas_root)
    # Google id_token local-JWKS verification keeps a module-level signing-key
    # cache (google_auth._JWKS_CACHE). Reset it per test so a cached key — or a
    # post-failure cooldown — from one test never leaks into the next; this
    # keeps the tokeninfo-fallback tests and the local-verify tests mutually
    # isolated. setattr (not clear()) so monkeypatch auto-restores after.
    import google_auth
    monkeypatch.setattr(google_auth, "_JWKS_CACHE",
                        {"keys": {}, "exp": 0, "retry_after": 0, "last_refetch": 0})
    # ALWAYS run init_schema for the freshly-pathed DB.
    import db
    db.init_schema()
    yield
