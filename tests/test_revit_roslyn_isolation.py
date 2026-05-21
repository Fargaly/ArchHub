"""AgDR-0023 — RevitMCP Roslyn isolation Python-side support.

Tests pin:
  1. Broker logs ONE-TIME deprecation when /ping says
     `compiler: in_process_roslyn`.
  2. Broker stays silent when modern `compiler: subprocess_csc`
     OR when the field is absent (pre-AgDR-0023 RevitMCP).
  3. Revit connector translates `error_code: csc_missing` into a
     typed OpResult with the install-Build-Tools pointer.
  4. AgDR + RUN-REVIT.md docs exist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


# ─── 1. broker deprecation log ───────────────────────────────────────


@pytest.fixture
def fresh_broker(monkeypatch):
    """Force a clean `_LEGACY_COMPILER_WARNED` set so each test sees
    a deterministic one-time-warn behaviour."""
    import revit_broker
    monkeypatch.setattr(revit_broker, "_LEGACY_COMPILER_WARNED", set())
    return revit_broker


def test_broker_warns_once_on_legacy_compiler(fresh_broker, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="revit_broker")
    fresh_broker._warn_legacy_compiler_once(48884, "in_process_roslyn")
    assert any("in-process Roslyn" in r.message for r in caplog.records)
    # Second call → no extra log (one-shot).
    caplog.clear()
    fresh_broker._warn_legacy_compiler_once(48884, "in_process_roslyn")
    assert not any("in-process Roslyn" in r.message
                    for r in caplog.records)


def test_broker_silent_on_modern_compiler(fresh_broker, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="revit_broker")
    fresh_broker._warn_legacy_compiler_once(48884, "subprocess_csc")
    assert not caplog.records


def test_broker_silent_when_compiler_field_absent(fresh_broker, caplog):
    """Pre-AgDR-0023 RevitMCP builds have NO `compiler` field. The
    broker treats absent as 'unknown' — no warning. Back-compat."""
    import logging
    caplog.set_level(logging.WARNING, logger="revit_broker")
    fresh_broker._warn_legacy_compiler_once(48884, None)
    fresh_broker._warn_legacy_compiler_once(48884, "")
    assert not caplog.records


def test_broker_warns_per_port_separately(fresh_broker, caplog):
    """Each (port, compiler) pair fires its own one-time log."""
    import logging
    caplog.set_level(logging.WARNING, logger="revit_broker")
    fresh_broker._warn_legacy_compiler_once(48884, "in_process_roslyn")
    fresh_broker._warn_legacy_compiler_once(48885, "in_process_roslyn")
    # Two distinct ports, both warned.
    legacy_msgs = [r for r in caplog.records
                    if "in-process Roslyn" in r.message]
    assert len(legacy_msgs) == 2
    ports = [int(r.args[0]) for r in legacy_msgs]
    assert set(ports) == {48884, 48885}


# ─── 2. connector csc_missing typed error ────────────────────────────


def test_revit_exec_translates_csc_missing_to_typed_error(monkeypatch):
    """When `/exec` returns `status:error` + `error_code:csc_missing`,
    `_exec` surfaces a typed OpResult with a Build-Tools install
    pointer in the error message."""
    import connectors.revit_connector as rc

    # Stub the broker to look "alive" + return a csc_missing error.
    class _FakeSession:
        session_id = "sess-1"; pid = 1; family = "revit"
        port = 48884; doc_title = "demo"
    stub_session = _FakeSession()
    monkeypatch.setattr(rc, "revit_broker", types_with(
        pick_session=lambda prefer=None: stub_session,
        forward=lambda session, path, body, method, timeout: {
            "status": "error",
            "error_code": "csc_missing",
            "error": "csc.exe not found",
        },
    ))
    result = rc._exec("revit.test", code="...",)
    assert hasattr(result, "ok")
    assert result.ok is False
    assert "csc.exe" in result.error.lower()
    assert "build tools" in result.error.lower()
    # RUN-REVIT.md pointer in error so the UI can deep-link.
    assert "run-revit.md" in result.error.lower()


def test_revit_exec_passes_through_other_errors(monkeypatch):
    """Non-csc_missing errors keep the existing pass-through path."""
    import connectors.revit_connector as rc

    class _FakeSession:
        session_id = "sess-1"; pid = 1; family = "revit"
        port = 48884; doc_title = "demo"
    monkeypatch.setattr(rc, "revit_broker", types_with(
        pick_session=lambda prefer=None: _FakeSession(),
        forward=lambda session, path, body, method, timeout: {
            "status": "error",
            "error": "some other failure",
        },
    ))
    result = rc._exec("revit.test", code="...",)
    assert result.ok is False
    assert "some other failure" in result.error


# ─── 3. docs exist ───────────────────────────────────────────────────


def test_agdr_0023_exists():
    p = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
         / "AgDR-0023-revitmcp-roslyn-isolation.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "subprocess" in text.lower()
    assert "csc.exe" in text.lower()
    assert "Roslyn" in text


def test_run_revit_doc_exists():
    p = (Path(__file__).resolve().parents[1] / "docs" / "RUN-REVIT.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    # User-visible: install pointer + verify command.
    assert "Build Tools" in text
    assert "/ping" in text
    assert "ARCHHUB_CSC_PATH" in text
    # Reinforces the founder's "shouldn't disable other addins" stance.
    assert "symptom" in text.lower() or "coexist" in text.lower()


# ─── helpers ─────────────────────────────────────────────────────────


def types_with(**kwargs):
    """Build a SimpleNamespace-like object with arbitrary callables."""
    from types import SimpleNamespace
    return SimpleNamespace(**kwargs)
