"""APP-05 regression: `acad` and `autocad` must resolve to one host.

The bug was not one misspelled call site. AutoCAD is registered as
`autocad` in the real connector/activation registries while legacy tools
and callers still use `acad`. These tests pin the shared lookup behavior
so either spelling reaches the same connector/host instead of reporting a
false miss.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def test_acad_alias_resolves_registered_autocad_connector():
    import connectors.autocad_connector  # noqa: F401
    from connectors.base import get

    canonical = get("autocad")
    alias = get("acad")

    assert canonical is not None
    assert alias is canonical
    assert alias.host == "autocad"


def test_acad_alias_resolves_activation_spec():
    from connectors.registry import resolve

    canonical = resolve("autocad")
    alias = resolve("acad")

    assert canonical is not None
    assert alias is canonical
    assert alias.family == "autocad"


def test_acad_alias_run_op_reaches_autocad_connector_not_false_miss():
    from connectors import autocad_connector
    from connectors.base import run_op

    broker = autocad_connector.acad_broker
    with patch.object(broker, "pick_session", return_value=None), \
            patch.object(broker, "is_any_alive", return_value=False):
        canonical = run_op("autocad.list_blocks", instance="")
        alias = run_op("acad.list_blocks", instance="")

    assert canonical.ok is False
    assert alias.ok is False
    assert "no connector for host" not in alias.error.lower()
    assert "autocad" in alias.error.lower()


def test_acad_alias_uses_autocad_broker_host_detector_path(monkeypatch):
    import host_detector

    monkeypatch.setattr(host_detector, "_tcp_open", lambda *a, **k: False)
    monkeypatch.setattr(host_detector, "_find_process", lambda names: None)

    status = host_detector._probe_broker("acad")

    assert status["status"] == "missing"
    assert status["detail"]["port"] == 48885
    assert "no broker port" not in status["note"].lower()
    assert "autocad" in status["note"].lower()
