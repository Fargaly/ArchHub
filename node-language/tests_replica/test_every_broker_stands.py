"""Every program the founder works with stands in the connector catalogue with its
real state, and every broker engine answers honestly when its host is closed."""
from __future__ import annotations

import os

import pytest

from nodelang import host_brokers
from nodelang.pipeline_engines import PIPELINE_ENGINES, probe_connectors

EXPECTED = {"revit", "autocad", "speckle", "max", "rhino", "blender", "excel", "word", "powerpoint",
            "outlook", "notion", "dropbox", "revit-2024", "autocad-2025", "max-2025", "photoshop",
            "illustrator", "indesign", "teams", "lmstudio", "antigravity", "procore"}


def test_the_catalogue_names_every_program_with_a_truthful_state():
    rows = {r["id"]: r for r in probe_connectors()}
    missing = EXPECTED - set(rows)
    assert not missing, missing
    for row in rows.values():
        assert row["state"] in {"connected", "listening", "running", "installed", "needs-key", "absent", "reachable"}, row
        assert row["detail"], row


def test_every_broker_engine_is_registered():
    for name in ("max.exec", "rhino.exec", "blender.exec", "office.read", "outlook.inbox", "notion.search", "dropbox.list", "connector.rows"):
        assert name in PIPELINE_ENGINES, name


def test_closed_hosts_answer_with_the_honest_zero(monkeypatch):
    monkeypatch.setattr(host_brokers, "_port_open", lambda port, timeout=0.15: False)
    monkeypatch.setattr(host_brokers, "_com_alive", lambda prog_id: False)
    monkeypatch.setattr(host_brokers, "_notion_token", lambda: "")
    monkeypatch.setattr(host_brokers, "_dropbox_root", lambda: None)
    for engine, params in (("max.exec", {"code": "x"}), ("rhino.exec", {"code": "x"}), ("blender.exec", {"code": "x"}),
                           ("outlook.inbox", {}), ("notion.search", {"query": "x"}), ("dropbox.list", {})):
        out, label = host_brokers.ENGINES[engine](params, {})
        assert out["ok"] is False and out["out"] == [] and label, (engine, out, label)


def test_a_live_host_is_never_launched_by_a_probe(monkeypatch):
    """Probes only ask whether an application is already open (GetActiveObject)."""
    import inspect
    src = inspect.getsource(host_brokers)
    assert "GetActiveObject" in src and "Dispatch(" not in src


@pytest.mark.skipif(os.name != "nt", reason="COM lives on Windows")
def test_office_read_on_this_machine_is_honest():
    out, label = host_brokers.ENGINES["office.read"]({"operation": "excel.list_workbooks"}, {})
    assert label
    assert out.get("ok") is False or "workbooks" in out["out"]
