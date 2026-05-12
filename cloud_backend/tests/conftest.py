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
    # ALWAYS run init_schema for the freshly-pathed DB.
    import db
    db.init_schema()
    yield
