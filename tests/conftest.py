"""Shared pytest configuration for the ArchHub desktop-app test suite.

Two jobs:
  1. Put `app/` on sys.path so tests can import the app modules.
  2. Isolate `secrets_store` for EVERY test — a throwaway per-test
     APP_DIR — so no test can ever write the developer's real
     %LOCALAPPDATA%/ArchHub/settings.json or secrets.dat.

Job 2 is the structural fix for the tool-policy pollution class.
Before this, only test_ai_behaviour.py isolated `secrets_store`; any
other test that touched `secrets_store.save_setting` or
`ai_behaviour.set_tool_policy` without its own monkeypatch silently
mutated the developer's real on-disk settings — the exact way the
`tool_policies` override store ended up polluted. Founder mandate
2026-05-18: tests must not touch real machine state, and the
guarantee must be structural, not per-test discipline.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))


@pytest.fixture(autouse=True)
def _isolate_secrets_store(tmp_path, monkeypatch):
    """Redirect `secrets_store` to a throwaway per-test directory so no
    test pollutes the real settings store. Autouse — every test in the
    suite gets it, with zero opt-in. A test that wants its own
    secrets_store path can still monkeypatch on top; this only
    guarantees the floor."""
    app_dir = tmp_path / "ArchHub"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    try:
        import secrets_store
    except Exception:
        # secrets_store not importable in this environment — nothing to
        # isolate. (Never fatal: a test that doesn't touch it is fine.)
        return
    monkeypatch.setattr(secrets_store, "APP_DIR", app_dir, raising=False)
    monkeypatch.setattr(secrets_store, "SECRETS_FILE",
                        app_dir / "secrets.dat", raising=False)
    monkeypatch.setattr(secrets_store, "SETTINGS_FILE",
                        app_dir / "settings.json", raising=False)
