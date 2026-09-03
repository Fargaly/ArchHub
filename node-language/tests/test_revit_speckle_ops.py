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
    _coerce_mesh,
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
    """A DirectShape item carrying real geometry emits a DirectShape
    create under the chosen built-in category. (CON-01: a geometry-LESS
    item no longer emits a create — see
    test_directshape_without_geometry_is_an_honest_error_not_a_fake_create.)"""
    items = [{
        "revit_directshape_category": "OST_GenericModel",
        "revit_geometry_json": {
            "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            "faces": [[0, 1, 2]],
        },
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


# ─── 2b. CON-01 — DirectShape honesty (no empty-shell fabrication) ────
#
# Root cause fixed: `_emit_directshape` used to emit
# `DirectShape.CreateElement` + `SetName` with NO geometry, then push the
# element into `created` with an id — so a receive of a geometry-less item
# reported "1 created" for an EMPTY element (real result missing). The fix
# mirrors `revit_connector._tessellate_cs`: build real geometry via a
# TessellatedShapeBuilder + SetShape, report `created` ONLY when the build
# yields geometry objects, and otherwise delete the element + record an
# honest error — never a fabricated `created` row.


def _mesh_cube():
    """A unit cube as the canonical (vertices, faces) dict the receive
    side hands to a DirectShape item via `revit_geometry_json`."""
    verts = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
             [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]]
    faces = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4],
             [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return {"vertices": verts, "faces": faces}


def test_directshape_without_geometry_is_an_honest_error_not_a_fake_create():
    """CON-01: a DirectShape item with NO geometry must NOT emit a
    `created.Add(...)` — the old empty-shell success. It must instead
    surface an honest error block (refuse to create an empty element)."""
    items = [{"revit_directshape_category": "OST_GenericModel"}]  # no geometry
    script = build_create_script(items)
    # An honest refusal — no fabricated `created` row for this item.
    assert "created.Add" not in script
    assert "errors.Add" in script
    assert "no geometry" in script.lower()
    # And it explicitly does NOT just create + name an empty element.
    assert "DirectShape.CreateElement" not in script


def test_directshape_with_geometry_builds_real_shape_and_reports_counts():
    """CON-01: with real `(vertices, faces)` the script builds the shape
    with a TessellatedShapeBuilder + SetShape, and only reports it in
    `created` when the build yields geometry objects — carrying a
    verifiable vertex/face/geometry-object count (the real result)."""
    items = [{
        "revit_directshape_category": "OST_GenericModel",
        "revit_geometry_json": _mesh_cube(),
    }]
    script = build_create_script(items)
    # Real geometry path — these are the load-bearing C# tokens.
    assert "DirectShape.CreateElement" in script
    assert "TessellatedShapeBuilder" in script
    assert "SetShape(objs)" in script
    # `created` is gated on the build actually producing geometry.
    assert "geomCount > 0" in script
    assert "created.Add" in script
    # The created row carries a verifiable, non-empty result.
    assert "geometry_object_count" in script
    assert "vertex_count" in script
    # On an empty build, the element is deleted + an honest error recorded —
    # never a silent empty shell.
    assert "doc.Delete(ds.Id)" in script
    assert "produced no" in script.lower()


def test_directshape_geometry_as_json_string_is_parsed():
    """`revit_geometry_json` may arrive as a JSON STRING (the name says
    'json') — it must still parse to real geometry, not be treated as
    'no geometry' and fabricated as an empty shell."""
    import json as _json
    items = [{
        "revit_directshape_category": "OST_GenericModel",
        "revit_geometry_json": _json.dumps(_mesh_cube()),
    }]
    script = build_create_script(items)
    assert "TessellatedShapeBuilder" in script
    assert "SetShape(objs)" in script
    assert "no geometry" not in script.lower()


# --- _coerce_mesh unit coverage (the geometry normaliser) ---


def test_coerce_mesh_grouped_vertices_and_faces():
    v, f = _coerce_mesh(_mesh_cube())
    assert len(v) == 8 and all(len(p) == 3 for p in v)
    assert len(f) == 6 and all(len(face) >= 3 for face in f)


def test_coerce_mesh_flat_vertices_and_encoded_faces():
    """Speckle Mesh shape: flat vertex triplets + count-prefixed faces
    (triangle encoded as 0, quad as 1 in the 2.x convention)."""
    geo = {
        "vertices": [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0],  # 4 verts, flat
        "faces": [1, 0, 1, 2, 3],  # one quad (1 => 4 verts) over 0,1,2,3
    }
    v, f = _coerce_mesh(geo)
    assert len(v) == 4
    assert f == [[0, 1, 2, 3]]


def test_coerce_mesh_rejects_empty_and_bad_input():
    assert _coerce_mesh(None) == ([], [])
    assert _coerce_mesh("") == ([], [])
    assert _coerce_mesh("not json") == ([], [])
    assert _coerce_mesh({}) == ([], [])
    assert _coerce_mesh({"vertices": []}) == ([], [])
    # Vertices but no usable faces → no real mesh.
    assert _coerce_mesh({"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                         "faces": []}) == ([], [])
    # Face index out of range → rejected (no fabricated geometry).
    assert _coerce_mesh({"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                         "faces": [[0, 1, 9]]}) == ([], [])


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
