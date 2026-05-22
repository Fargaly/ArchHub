"""Cross-file test pollution guard — `session_io` isolation.

ROADMAP NEXT-30-DAYS pre-fix flake: `test_delete_session_removes_file`
in `test_new_bridge_slots.py` passed isolated but failed in full-suite
runs. Class of bug: a test collected earlier imports `session_io` and
leaves SESSIONS_DIR (or related module state) pointing at a stale path.

Fix: the autouse `_isolate_session_io_module_state` fixture in
`test_new_bridge_slots.py` re-stamps SESSIONS_DIR via monkeypatch on
every test, so cross-file pollution can't leak through. This test
file pins the fixture's contract + verifies it survives.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


def test_session_io_module_exposes_sessions_dir():
    """SESSIONS_DIR must be a module-level attribute — the autouse
    fixture in test_new_bridge_slots monkeypatches it directly."""
    import session_io
    assert hasattr(session_io, "SESSIONS_DIR")


def test_session_io_sessions_dir_is_path_like():
    """SESSIONS_DIR is a Path / str — the slot uses `/` operator on
    it. Type drift here would break delete/rename/fork slots."""
    import session_io
    val = session_io.SESSIONS_DIR
    assert val is not None
    # Path or str — both support `/` via __fspath__.
    assert isinstance(val, (Path, str)) or hasattr(val, "__fspath__")


def test_autouse_fixture_is_defined_in_test_new_bridge_slots():
    """Guard against accidental removal of the structural guard.
    The fixture lives in `tests/test_new_bridge_slots.py` with
    `autouse=True` so every test in that file resets SESSIONS_DIR
    before it runs."""
    src = (Path(__file__).resolve().parent /
           "test_new_bridge_slots.py").read_text(encoding="utf-8")
    assert "_isolate_session_io_module_state" in src
    assert "autouse=True" in src


def test_isolation_fixture_applies_to_every_test_in_module():
    """The fixture is autouse=True scoped to function (the default).
    That means it runs before EACH test in test_new_bridge_slots.py.
    Pin the contract."""
    src = (Path(__file__).resolve().parent /
           "test_new_bridge_slots.py").read_text(encoding="utf-8")
    # The autouse fixture is registered with @pytest.fixture(autouse=True).
    assert "@pytest.fixture(autouse=True)" in src


def test_isolation_fixture_uses_monkeypatch():
    """The fixture must use `monkeypatch.setattr` (not plain
    attribute assignment) so the reset is cleaned up automatically
    after each test."""
    src = (Path(__file__).resolve().parent /
           "test_new_bridge_slots.py").read_text(encoding="utf-8")
    assert "monkeypatch.setattr(_sio, " in src
