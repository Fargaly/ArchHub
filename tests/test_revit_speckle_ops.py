"""M2-Python — Revit ↔ Speckle ops (AgDR-0017).

Tests pin:
  1. `_classify_item` — annotation → create-fn kind.
  2. `build_create_script` — pure annotation → C# generator output:
      * Wall annotation → `Wall.Create` C#
      * DirectShape annotation → `DirectShape.CreateElement` C#
      * Family annotation → `NewFamilyInstance` C#
      * Per-item try/catch + skipped list
  3. `send_to_speckle` — shape preservation through SpeckleWire
     (dict / list / scalar / None).
  4. `receive_from_speckle` — offline path surfaces typed error
     instead of fabricating a result.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from connectors.revit_speckle_ops import (  # noqa: E402
    _classify_item,
    build_create_script,
    send_to_speckle,
    receive_from_speckle,
)


# ─── 1. _classify_item ───────────────────────────────────────────────


def test_classify_wall_annotation():
    item = {"revit_target_category": "Walls",
            "revit_polyline": [[0, 0, 0], [1000, 0, 0]]}
    assert _classify_item(item) == "wall"


def test_classify_family_annotation():
    item = {"revit_target_category": "GenericModel",
            "revit_family_name": "MyMass"}
    assert _classify_item(item) == "family"


def test_classify_directshape_annotation():
    item = {"revit_directshape_category": "OST_GenericModel"}
    assert _classify_item(item) == "directshape"


def test_classify_builtin_category_fallback():
    item = {"revit_builtin_category": "OST_Walls"}
    assert _classify_item(item) == "directshape"


def test_classify_no_annotation_skips():
    assert _classify_item({}) == "skip"
    assert _classify_item({"foo": "bar"}) == "skip"
    assert _classify_item(None) == "skip"
    assert _classify_item("not a dict") == "skip"


def test_classify_walls_wins_over_family():
    """Explicit Walls target wins even if a family_name is also
    present — the user's intent was a wall, not a family."""
    item = {"revit_target_category": "Walls",
            "revit_family_name": "Whatever",
            "revit_polyline": [[0, 0, 0], [1, 0, 0]]}
    assert _classify_item(item) == "wall"


# ─── 2. build_create_script ──────────────────────────────────────────


def test_build_create_script_wall_emits_wall_create():
    items = [{
        "revit_target_category": "Walls",
        "revit_level": "Level 1",
        "revit_wall_type": "Generic - 200mm",
        "revit_height_mm": 3000,
        "revit_polyline": [[0, 0, 0], [5000, 0, 0]],
    }]
    script = build_create_script(items)
    assert "Wall.Create(" in script
    assert "Generic - 200mm" in script
    assert "Level 1" in script
    # Height converted mm → feet (3000 / 304.8 ≈ 9.8425...).
    assert "9.84" in script
    # Per-item try/catch.
    assert "try {" in script
    assert "catch (Exception ex)" in script


def test_build_create_script_directshape():
    items = [{
        "revit_directshape_category": "OST_GenericModel",
    }]
    script = build_create_script(items)
    assert "DirectShape.CreateElement" in script
    assert "OST_GenericModel" in script
    assert "BuiltInCategory" in script


def test_build_create_script_family_instance():
    items = [{
        "revit_family_name": "MyMass",
        "revit_target_category": "Mass",
        "revit_origin": [1000, 2000, 0],
        "revit_parameters": {"Width": 500, "Comments": "from-max"},
        "revit_level": "Level 2",
    }]
    script = build_create_script(items)
    assert "NewFamilyInstance" in script
    assert "MyMass" in script
    assert "Width" in script
    assert "500" in script
    assert "Comments" in script
    assert "from-max" in script
    assert "Level 2" in script


def test_build_create_script_per_item_try_catch():
    """Each item gets its own try/catch — one bad item must not
    prevent others from creating."""
    items = [
        {"revit_target_category": "Walls",
         "revit_polyline": [[0, 0, 0], [1, 0, 0]],
         "revit_level": "L1", "revit_wall_type": "WT", "revit_height_mm": 1000},
        {"revit_directshape_category": "OST_GenericModel"},
    ]
    script = build_create_script(items)
    # Two `try {` blocks, two `catch (Exception ex)` clauses.
    assert script.count("try {") >= 2
    assert script.count("catch (Exception ex)") >= 2


def test_build_create_script_tracks_skipped_indices():
    """Unannotated items show up in the `skipped` list at their
    original index — the receive caller can see which items the
    server didn't try to create."""
    items = [
        {"revit_target_category": "Walls",
         "revit_polyline": [[0, 0, 0], [1, 0, 0]],
         "revit_level": "L1", "revit_wall_type": "WT", "revit_height_mm": 1000},
        {"unrelated": "data"},  # skipped — index 1
        {"revit_directshape_category": "OST_GenericModel"},
    ]
    script = build_create_script(items)
    assert "skipped = new System.Collections.Generic.List<int> { 1 }" in script


def test_build_create_script_empty_items():
    """Zero items → a valid script that returns zero counts (no
    crash, no missing braces)."""
    script = build_create_script([])
    assert "ctx.result" in script
    assert "(no creatable items)" in script
    # Counts are emitted via the ctx.result block.
    assert "created_count" in script


def test_build_create_script_escapes_quotes_in_strings():
    """A C# string-literal escape: a level name like `Level "1"`
    must not break the script."""
    items = [{
        "revit_target_category": "Walls",
        "revit_level": 'Level "1"',
        "revit_wall_type": "WT", "revit_height_mm": 1000,
        "revit_polyline": [[0, 0, 0], [1, 0, 0]],
    }]
    script = build_create_script(items)
    # Should contain the escaped form, not raw double-quotes.
    assert 'Level \\"1\\"' in script


# ─── 3. send_to_speckle ──────────────────────────────────────────────


def test_send_to_speckle_dict_preserves_shape():
    """A dict value should round-trip its shape via SpeckleWire +
    return a hash + a `speckle://local/<hash>` URL."""
    with tempfile.TemporaryDirectory() as tmp:
        result = send_to_speckle(
            value={"key": "value", "n": 42},
            model_name="test",
            project_dir=tmp,
        )
        assert result.get("hash"), result
        assert result["url"].startswith("speckle://local/")
        assert result["item_count"] == 1
        assert result["mode"] == "disk"


def test_send_to_speckle_list_preserves_count():
    """A list of N items should report `item_count = N`."""
    with tempfile.TemporaryDirectory() as tmp:
        items = [{"i": i} for i in range(5)]
        result = send_to_speckle(value=items, project_dir=tmp)
        assert result["item_count"] == 5


def test_send_to_speckle_scalar_wraps_once():
    """A scalar input → `item_count = 1`."""
    with tempfile.TemporaryDirectory() as tmp:
        result = send_to_speckle(value=42, project_dir=tmp)
        assert result["item_count"] == 1


def test_send_to_speckle_none_value_zero_count():
    """`value=None` → `item_count = 0`. No crash."""
    with tempfile.TemporaryDirectory() as tmp:
        result = send_to_speckle(value=None, project_dir=tmp)
        assert result["item_count"] == 0
        assert result.get("hash"), result


# ─── 4. receive_from_speckle ─────────────────────────────────────────


def test_receive_from_speckle_missing_url():
    """Empty source_url → typed error, not a fake create count."""
    result = receive_from_speckle(source_url="")
    assert result["status"] == "error"
    assert "source_url" in result["error"].lower()


def test_receive_from_speckle_unknown_hash_returns_error():
    """A speckle://local/ URL pointing at an unknown hash → an
    SpeckleWire.receive error surfaces honestly (not a fake
    create count)."""
    with tempfile.TemporaryDirectory() as tmp:
        result = receive_from_speckle(
            source_url="speckle://local/deadbeefdeadbeefdeadbeefdeadbeef",
            project_dir=tmp)
        assert result["status"] == "error"
        assert "receive" in result["error"].lower() \
            or "not found" in result["error"].lower() \
            or "no object" in result["error"].lower()


def test_receive_from_speckle_remote_url_not_supported():
    """Per AgDR-0017 the MVP rejects remote URLs."""
    result = receive_from_speckle(
        source_url="https://app.speckle.systems/streams/X/objects/Y")
    assert result["status"] == "error"
    assert "remote" in result["error"].lower()


# ─── 5. end-to-end round-trip (send → receive's classification) ──────


def test_send_then_classify_round_trip(tmp_path):
    """Send a list of ADAPTER-annotated items → receive-side
    classify_item walks the data: every item gets the right kind
    (wall / family / directshape). Skips empty payloads."""
    items = [
        {"revit_target_category": "Walls",
         "revit_polyline": [[0, 0, 0], [1000, 0, 0]],
         "revit_level": "L1", "revit_wall_type": "WT",
         "revit_height_mm": 3000},
        {"revit_family_name": "Mass1",
         "revit_target_category": "Mass",
         "revit_origin": [0, 0, 0]},
    ]
    sent = send_to_speckle(value=items, project_dir=str(tmp_path))
    # Read back via SpeckleWire directly to confirm round-trip
    # preserves the annotation shape. Close after to release the
    # SQLite handle so the tempdir teardown can run on Windows.
    from speckle_wire import SpeckleWire
    wire = SpeckleWire(str(tmp_path))
    try:
        payload = wire.receive(sent["hash"])
    finally:
        try: wire.close()
        except Exception: pass
    data = payload.get("data") if isinstance(payload, dict) else payload
    assert isinstance(data, list)
    assert len(data) == 2
    assert _classify_item(data[0]) == "wall"
    assert _classify_item(data[1]) == "family"
