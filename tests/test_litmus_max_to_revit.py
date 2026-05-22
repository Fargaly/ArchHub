"""M5 litmus — end-to-end Max-mass → Revit-family chain (pure Python).

References:
  * AgDR-0012 (Direction X) — every wire is Speckle Operations.send/receive
  * AgDR-0016 — SHARE + ADAPTER categories, MAX→Revit-family example
  * AgDR-0017 — M2-Python Revit↔Speckle ops + annotation→C# generator

The founder's litmus from 2026-05-21: "using 3ds Max to model a mass
and wiring it to a Revit session should transfer as a native Revit
family with parameters."

This test EXERCISES the whole chain WITHOUT a live Max or Revit:

    [Max upstream value]                  (a mass dict — mocked)
        → adapter.max_to_revit_family     (annotates → revit_* keys)
        → SpeckleWire.send                (per-project SQLiteTransport)
        → speckle://local/<hash>          (the wire reference)
        → SpeckleWire.receive             (round-trip dict)
        → build_create_script             (annotation → C#)
        → assertions on the generated C#  (FamilyInstance creation)

If any link in the chain breaks — adapter drops an annotation,
SpeckleWire mangles the shape, the C# generator misclassifies — the
test surfaces it.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from connectors.revit_speckle_ops import (  # noqa: E402
    _classify_item,
    build_create_script,
    send_to_speckle,
)
from workflows.nodes.adapter import (  # noqa: E402
    _max_to_revit_family_executor,
)
from speckle_wire import SpeckleWire  # noqa: E402


# ---------------------------------------------------------------------------
# Mocks of host-side extractor outputs.


def _mock_max_mass(*, name="MyMass", origin=(0, 0, 0),
                    width=2000.0, depth=1500.0, height=3000.0,
                    notes="from max"):
    """The shape `max.list_objects` would return for one mass.
    A real Max extractor returns more — we only need the fields the
    adapter consumes."""
    return {
        "speckle_type": "Objects.BuiltElements.Element",
        "max_id": 12345,
        "name": name,
        "origin": list(origin),
        "max_bbox": {"w": width, "d": depth, "h": height},
        "max_notes": notes,
    }


# ---------------------------------------------------------------------------
# Litmus chain — assertions per stage + an end-to-end stage.


def test_litmus_max_mass_to_revit_family(tmp_path):
    """The full M5 chain from a Max mass dict to a native-creation
    C# script. Every stage asserted in order."""

    # ── Stage 1: Max upstream extraction (mocked) ────────────────
    mass = _mock_max_mass(name="WingMass",
                            origin=(5000, 3000, 0),
                            width=4000, depth=2500, height=12000,
                            notes="origin-x=5000 mm")
    # Sanity: Max-side data carries no revit_* annotations yet.
    assert "revit_target_category" not in mass
    assert "revit_family_name" not in mass

    # ── Stage 2: adapter.max_to_revit_family enriches ────────────
    adapted = _max_to_revit_family_executor(
        config={
            "target_category": "Mass",
            "family_name":     "ArchHub_WingFamily",
            "family_template": "Metric Mass.rft",
            "parameters":      {
                "Width":   4000,
                "Depth":   2500,
                "Height": 12000,
                "Notes":  "from-max-litmus",
            },
        },
        inputs={"value": mass},
        ctx=None,
    )
    # Adapter outputs `value` (the enriched item) + `status`.
    enriched = adapted["value"]
    assert enriched["revit_target_category"] == "Mass"
    assert enriched["revit_family_name"] == "ArchHub_WingFamily"
    assert enriched["revit_parameters"]["Width"] == 4000
    # The original Max-side fields survive the merge.
    assert enriched["max_id"] == 12345
    assert enriched["name"] == "WingMass"
    # Status reports the right shape for the adapter rail.
    assert adapted["status"]["ok"] is True
    assert adapted["status"]["count"] == 1
    assert adapted["status"]["family_name"] == "ArchHub_WingFamily"

    # ── Stage 3: revit.send_to_speckle (wraps + SpeckleWire) ─────
    sent = send_to_speckle(
        value=enriched,
        model_name="litmus-max-to-revit",
        project_dir=str(tmp_path),
    )
    assert sent.get("hash"), sent
    assert sent["url"].startswith("speckle://local/")
    assert sent["item_count"] == 1
    assert sent["mode"] == "disk"

    # ── Stage 4: SpeckleWire round-trip (the wire substrate) ─────
    # The receive-side adapter reads this back. We exercise the
    # round-trip explicitly so a wire-substrate bug surfaces here,
    # not behind the C# generator.
    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass
    # send_to_speckle wraps in `{revit_source, model_name, data, item_count}`.
    assert isinstance(payload, dict)
    assert payload.get("revit_source") is True
    assert payload.get("model_name") == "litmus-max-to-revit"
    received = payload.get("data")
    # The adapter annotations survived the round-trip.
    assert received["revit_target_category"] == "Mass"
    assert received["revit_family_name"] == "ArchHub_WingFamily"
    assert received["revit_parameters"]["Width"] == 4000

    # ── Stage 5: classify the received item ──────────────────────
    assert _classify_item(received) == "family"

    # ── Stage 6: build_create_script emits FamilyInstance C# ─────
    script = build_create_script([received])
    # The script must contain the family lookup + NewFamilyInstance.
    assert "ArchHub_WingFamily" in script
    assert "NewFamilyInstance" in script
    assert "FamilySymbol" in script
    # Every parameter from the map appears in the C# (`LookupParameter`).
    assert "Width" in script and "4000" in script
    assert "Depth" in script and "2500" in script
    assert "Height" in script and "12000" in script
    assert "Notes" in script and "from-max-litmus" in script
    # Per-item try/catch shape.
    assert "try {" in script
    assert "catch (Exception ex)" in script
    # The ctx.result block at the end.
    assert "ctx.result" in script
    assert "created_count" in script


def test_litmus_chain_handles_a_list_of_masses(tmp_path):
    """The chain must handle a list of mass inputs (Max often returns
    N masses; the adapter applies element-wise). Test pins:
      * adapter creates N annotated items
      * SpeckleWire ships the list as a list
      * build_create_script emits N FamilyInstance blocks
    """
    masses = [
        _mock_max_mass(name=f"Mass{i}", origin=(i * 1000, 0, 0))
        for i in range(3)
    ]
    adapted = _max_to_revit_family_executor(
        config={
            "target_category": "Mass",
            "family_name":     "BatchFamily",
            "parameters":      {},
        },
        inputs={"value": masses},
        ctx=None,
    )
    out = adapted["value"]
    assert isinstance(out, list) and len(out) == 3
    assert all(item["revit_target_category"] == "Mass" for item in out)

    sent = send_to_speckle(value=out, model_name="batch",
                             project_dir=str(tmp_path))
    assert sent["item_count"] == 3

    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass
    data = payload["data"]
    assert isinstance(data, list) and len(data) == 3

    script = build_create_script(data)
    # Three FamilyInstance creation blocks — count the per-item
    # Family.Name lookup (once per try-catch block) rather than the
    # bare `NewFamilyInstance` substring (which appears twice in
    # each block via the lvl ternary).
    assert script.count('Family.Name ==') == 3
    assert script.count("BatchFamily") >= 3
    # Verify per-item idx tagging — the C# `created.Add(new { idx = N`
    # appears once per item.
    for i in range(3):
        assert f"idx = {i}, kind = \"family\"" in script


def test_litmus_skips_when_no_adapter_annotation(tmp_path):
    """When a Max mass goes through WITHOUT the adapter (user
    forgot to wire the adapter in), the receive-side classifies
    it as `skip` — honest, no fake creation. Documents the
    failure mode."""
    bare_mass = _mock_max_mass(name="NoAdapterMass")
    sent = send_to_speckle(value=bare_mass, project_dir=str(tmp_path))

    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass

    received = payload["data"]
    # No annotation → classify as skip.
    assert _classify_item(received) == "skip"
    script = build_create_script([received])
    # Skipped index recorded.
    assert "skipped = new System.Collections.Generic.List<int> { 0 }" in script
    # No NewFamilyInstance call.
    assert "NewFamilyInstance" not in script


def test_litmus_cad_to_wall_chain(tmp_path):
    """Parallel chain: CAD polyline → adapter.cad_to_revit_wall →
    Speckle round-trip → Wall.Create C#. Documents that the same
    pattern works for the AutoCAD → Revit Wall path."""
    from workflows.nodes.adapter import _cad_to_revit_wall_executor

    polyline = {
        "speckle_type": "Objects.Geometry.Polyline",
        "acad_layer": "A-WALL",
        "revit_polyline": [[0, 0, 0], [5000, 0, 0], [5000, 4000, 0]],
    }
    adapted = _cad_to_revit_wall_executor(
        config={
            "level":      "Level 1",
            "wall_type":  "Generic - 200mm",
            "height":     3200,
            "top_offset": 0,
            "structural": False,
        },
        inputs={"value": polyline},
        ctx=None,
    )
    enriched = adapted["value"]
    assert enriched["revit_target_category"] == "Walls"
    assert enriched["revit_level"] == "Level 1"
    assert enriched["revit_wall_type"] == "Generic - 200mm"
    assert enriched["revit_height_mm"] == 3200

    sent = send_to_speckle(value=enriched, project_dir=str(tmp_path))
    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass
    received = payload["data"]

    assert _classify_item(received) == "wall"
    script = build_create_script([received])
    assert "Wall.Create(" in script
    assert "Generic - 200mm" in script
    assert "Level 1" in script
    # Height converted mm → ft (3200 / 304.8 ≈ 10.499).
    assert "10.49" in script


def test_litmus_rhino_to_revit_beam_chain(tmp_path):
    """Batch 2 chain: Rhino curve → adapter.rhino_to_revit_beam →
    Speckle round-trip → NewFamilyInstance(StructuralType.Beam) C#."""
    from workflows.registry import get as registry_get

    _, beam_adapter = registry_get("adapter.rhino_to_revit_beam")
    curve = {
        "speckle_type": "Objects.Geometry.Curve",
        "rhino_id": "abc123",
        "revit_polyline": [[0, 0, 0], [6000, 0, 0]],
    }
    adapted = beam_adapter(
        {"beam_family": "W-Wide Flange",
         "beam_type": "W14X22",
         "level": "Level 2"},
        {"value": curve},
        None,
    )
    enriched = adapted["value"]
    assert enriched["revit_target_category"] == "StructuralFraming"
    assert enriched["revit_beam_family"] == "W-Wide Flange"
    assert enriched["revit_structural"] is True

    sent = send_to_speckle(value=enriched, project_dir=str(tmp_path))
    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass
    received = payload["data"]

    assert _classify_item(received) == "beam"
    script = build_create_script([received])
    assert "StructuralType.Beam" in script
    assert "W-Wide Flange" in script
    assert "W14X22" in script
    assert "Level 2" in script
    assert "Line.CreateBound" in script


def test_litmus_cad_to_detail_line_chain(tmp_path):
    """Batch 2 chain: CAD annotation polyline →
    adapter.cad_to_revit_detail_line → Speckle round-trip →
    DetailCurve.Create C#."""
    from workflows.registry import get as registry_get

    _, dl_adapter = registry_get("adapter.cad_to_revit_detail_line")
    polyline = {
        "speckle_type": "Objects.Geometry.Polyline",
        "acad_layer": "A-ANNO",
        "revit_polyline": [[0, 0, 0], [1000, 0, 0], [1000, 500, 0]],
    }
    adapted = dl_adapter(
        {"view_id": 0, "line_style": "Wide Lines"},
        {"value": polyline},
        None,
    )
    enriched = adapted["value"]
    assert enriched["revit_target_category"] == "DetailLines"
    assert enriched["revit_view_id"] == 0
    assert enriched["revit_line_style"] == "Wide Lines"

    sent = send_to_speckle(value=enriched, project_dir=str(tmp_path))
    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass
    received = payload["data"]

    assert _classify_item(received) == "detail_line"
    script = build_create_script([received])
    assert "NewDetailCurve" in script
    assert "doc.ActiveView" in script  # view_id=0 → active view
    assert "Wide Lines" in script


def test_litmus_excel_to_batch_params_chain(tmp_path):
    """Batch 2 chain: Excel rows → adapter.excel_to_revit_params →
    Speckle round-trip → build_set_parameters_script emits per-row
    LookupParameter().Set() calls. End-to-end pure-Python."""
    from workflows.registry import get as registry_get
    from connectors.revit_speckle_ops import (
        build_set_parameters_script)

    _, excel_adapter = registry_get("adapter.excel_to_revit_params")
    rows = [
        {"ElementId": 1001, "Width": 500, "Comments": "row-1"},
        {"ElementId": 1002, "Width": 700, "Comments": "row-2"},
    ]
    adapted = excel_adapter(
        {"element_id_column": "ElementId"},
        {"value": rows},
        None,
    )
    out = adapted["value"]
    assert len(out) == 2

    sent = send_to_speckle(value=out, project_dir=str(tmp_path))
    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass
    data = payload["data"]
    assert isinstance(data, list) and len(data) == 2
    assert all(_classify_item(item) == "parameter_set" for item in data)

    # The batch_set_parameters script (NOT build_create_script) drives
    # the receive — this is the M2-Batch-2 split.
    script = build_set_parameters_script(data)
    assert "GetElement(new ElementId(1001))" in script
    assert "GetElement(new ElementId(1002))" in script
    assert "LookupParameter(\"Width\")" in script
    assert "p.Set(500)" in script
    assert "p.Set(700)" in script
