"""AutoCAD + 3ds Max send-to-Speckle parity (M5 prep).

Mirrors `revit.send_to_speckle` for the other two broker hosts. The
op delegates to the canonical `revit_speckle_ops.send_to_speckle`
with `source_host='autocad'` / `source_host='max'`, so the Speckle
commit carries `archhub_source: <host>` for receive-side
disambiguation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Force module loads so the ops register.
import connectors.autocad_connector  # noqa: F401, E402
import connectors.max_connector       # noqa: F401, E402


# ─── 1. ops appear with the right shape ──────────────────────────────


def test_acad_send_to_speckle_op_registered():
    from connectors.base import all_connectors
    acad = next(c for c in all_connectors() if c.host == "autocad")
    op = next((o for o in acad.ops()
                if o.op_id == "autocad.send_to_speckle"), None)
    assert op is not None
    # CON-02: writes a Speckle commit to disk (+ optional remote push) —
    # an outside-world side effect — so it is an ACTION, not a read, even
    # though it does NOT mutate AutoCAD. As an action it is approval-gated.
    assert op.kind == "action"
    assert op.destructive is True


def test_max_send_to_speckle_op_registered():
    from connectors.base import all_connectors
    mx = next(c for c in all_connectors() if c.host == "max")
    op = next((o for o in mx.ops()
                if o.op_id == "max.send_to_speckle"), None)
    assert op is not None
    # CON-02: writes a Speckle commit to disk (+ optional remote push) —
    # an outside-world side effect — so it is an ACTION, not a read, even
    # though it does NOT mutate 3ds Max. As an action it is approval-gated.
    assert op.kind == "action"
    assert op.destructive is True


# ─── 2. ops execute end-to-end through SpeckleWire ───────────────────


def test_acad_send_to_speckle_writes_via_speckle_wire(tmp_path,
                                                        monkeypatch):
    """Calling `autocad.send_to_speckle` ships the value through the
    canonical SpeckleWire and returns a `speckle://local/<hash>` URL."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))

    from connectors.base import run_op
    res = run_op("autocad.send_to_speckle",
                  value={"acad_layer": "A-WALL",
                         "points": [[0, 0, 0], [1000, 0, 0]]},
                  model_name="autocad-test")
    assert res.ok, res.error
    inner = res.value
    assert isinstance(inner, dict)
    assert inner["url"].startswith("speckle://local/")
    assert inner["item_count"] == 1
    assert inner["mode"] == "disk"


def test_max_send_to_speckle_writes_via_speckle_wire(tmp_path, monkeypatch):
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))

    from connectors.base import run_op
    res = run_op("max.send_to_speckle",
                  value={"max_id": 99, "max_name": "MyMass"},
                  model_name="max-test")
    assert res.ok, res.error
    inner = res.value
    assert inner["url"].startswith("speckle://local/")
    assert inner["item_count"] == 1


# ─── 3. archhub_source marker per-host ───────────────────────────────


def test_acad_send_marks_archhub_source(tmp_path, monkeypatch):
    """The Speckle commit carries `archhub_source: 'autocad'` so a
    cross-host receiver can disambiguate."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))

    from connectors.base import run_op
    res = run_op("autocad.send_to_speckle",
                  value={"foo": "bar"})
    assert res.ok
    hash_id = res.value["hash"]

    # Read back via SpeckleWire to inspect the wrapped payload.
    wire = speckle_wire.SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(hash_id)
    finally:
        try: wire.close()
        except Exception: pass

    assert payload.get("archhub_source") == "autocad"
    # No revit_source flag for AutoCAD sends.
    assert "revit_source" not in payload


def test_max_send_marks_archhub_source(tmp_path, monkeypatch):
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))

    from connectors.base import run_op
    res = run_op("max.send_to_speckle",
                  value={"x": 1})
    assert res.ok
    hash_id = res.value["hash"]

    wire = speckle_wire.SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(hash_id)
    finally:
        try: wire.close()
        except Exception: pass

    assert payload.get("archhub_source") == "max"
    assert "revit_source" not in payload


def test_revit_send_still_marks_revit_source_back_compat(tmp_path,
                                                            monkeypatch):
    """The back-compat `revit_source: True` flag stays on Revit
    commits so older receive paths don't break."""
    import speckle_wire
    monkeypatch.setattr(speckle_wire, "default_project_dir",
                         lambda: str(tmp_path))

    import connectors.revit_connector  # noqa: F401
    from connectors.base import run_op
    res = run_op("revit.send_to_speckle",
                  value={"x": 1})
    assert res.ok
    hash_id = res.value["hash"]

    wire = speckle_wire.SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(hash_id)
    finally:
        try: wire.close()
        except Exception: pass

    assert payload.get("archhub_source") == "revit"
    # Back-compat marker still present.
    assert payload.get("revit_source") is True


# ─── 4. LLM tool surface includes the new ops ────────────────────────


def test_tool_surface_includes_acad_and_max_send():
    """The tool-engine's connector-tool list must include the new ops
    with the `__` name shape."""
    from tool_engine import ToolEngine

    class _StubManager:
        entries: list = []
        def active_families(self) -> set: return set()

    engine = ToolEngine(manager=_StubManager())
    specs = engine._connector_tool_specs()
    names = {s["name"] for s in specs}
    assert "autocad__send_to_speckle" in names
    assert "max__send_to_speckle" in names
