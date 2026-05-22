"""Revit ↔ Speckle connector ops — M2-Python (AgDR-0017).

Two ops on the Revit family that close the litmus chain from
AgDR-0016 (Max-mass → Revit-family with parameters):

    revit.send_to_speckle      wraps upstream value · writes via
                                SpeckleWire · returns model URL
    revit.receive_from_speckle  pulls a model · reads `revit_*`
                                ADAPTER annotations · emits ONE
                                C# transaction script · POSTs via
                                the existing RevitMCP `/exec` route

The C# generator (`build_create_script`) is a pure function — it
takes a list of dict items and emits a C# transaction body that
creates Walls / DirectShapes / FamilyInstances based on the
ADAPTER annotations written by `app/workflows/nodes/adapter.py`.
That keeps the translation logic tested without a live Revit.

This module deliberately does NOT bundle the official Speckle
Revit add-in (that's the deferred M2-Bundle slice). Every Revit-
side action goes through `/exec` — the same path every other
Revit op uses.
"""
from __future__ import annotations

import json
from typing import Any

from connectors.base import OpResult


# Default transaction name shows up in Revit's undo stack.
_TX_RECV = "ArchHub: receive from Speckle"


def _coerce_items(value: Any) -> list:
    """Normalise the upstream `value` into a flat list of items.
    A dict becomes `[dict]`; a list passes through; a scalar
    becomes `[scalar]`. `None` → `[]`."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def send_to_speckle(value: Any = None, *,
                     model_name: str = "revit",
                     project_dir: str | None = None,
                     server_push: bool = False,
                     server_url: str = "",
                     source_host: str = "revit") -> dict:
    """Wrap `value` and write it through a per-project `SpeckleWire`.

    Returns ``{"url", "hash", "item_count", "mode"}``. ``url`` is a
    `speckle://local/<hash>` reference when ``server_push=False``,
    or the remote model URL when push succeeds. The Speckle commit
    holds the full upstream shape — a list stays a list on receive,
    a dict stays a dict.

    `archhub_source: <host>` is stamped on the top-level wrapper so
    a downstream receiver can tell which host the data came from
    (revit / autocad / max / generic). Used for symmetry +
    debugging. `revit_source: True` ALSO stamped for back-compat
    when `source_host == "revit"`.
    """
    items = _coerce_items(value)
    try:
        from speckle_wire import SpeckleWire, default_project_dir
    except Exception as ex:
        return {"status": "error",
                "error": f"SpeckleWire unavailable: {ex}"}
    pdir = project_dir or default_project_dir()
    wire = SpeckleWire(pdir)
    # Single wrapped payload so the consumer gets the original
    # shape back (a list or dict in `data`).
    payload: dict = {
        "archhub_source": source_host,
        "model_name": model_name,
        "item_count": len(items),
        "data": value,
    }
    # Back-compat marker (older revit.receive_from_speckle tests
    # look for `revit_source`).
    if source_host == "revit":
        payload["revit_source"] = True
    try:
        hash_id = wire.send(payload)
    except Exception as ex:
        return {"status": "error",
                "error": f"SpeckleWire.send failed: {ex}"}
    local_url = f"speckle://local/{hash_id}"
    out = {"url": local_url, "hash": hash_id,
           "item_count": len(items), "mode": "disk"}
    if server_push and server_url:
        try:
            from speckle_server import push_to_server
            remote_url = push_to_server(payload, server_url,
                                          model_name)
            out["url"] = remote_url
            out["mode"] = "server"
        except Exception as ex:
            # Per AgDR-0016: server push failure does NOT block
            # the local DiskTransport write — local URL still
            # surfaces; honest mode is "disk_only_after_server_fail".
            out["mode"] = "disk_only_after_server_fail"
            out["server_error"] = f"{type(ex).__name__}: {ex}"
    return out


# ── ADAPTER annotation → C# generator (pure function) ────────────────


def _csharp_string(s: Any) -> str:
    """Escape a Python value into a C# string literal.
    `None` → `""`. Quotes + backslashes properly escaped."""
    if s is None:
        return '""'
    if isinstance(s, (int, float, bool)):
        if isinstance(s, bool):
            return "true" if s else "false"
        return str(s)
    s = str(s)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{s}"'


def _emit_wall(idx: int, item: dict) -> str:
    """Emit the C# `try { Wall.Create(...) }` body for one
    `adapter.cad_to_revit_wall` item.

    Required annotations:
        revit_target_category == "Walls"
        revit_level                (Level name OR ElementId int)
        revit_wall_type            (WallType name)
        revit_height_mm            (number — mm)
        revit_polyline             (list of [x,y,z] points, mm)
        revit_top_offset_mm        (number — mm; default 0)
        revit_structural           (bool; default false)
    """
    polyline = item.get("revit_polyline") or []
    level = item.get("revit_level") or ""
    wall_type = item.get("revit_wall_type") or ""
    height = item.get("revit_height_mm") or 0
    structural = bool(item.get("revit_structural", False))
    # Convert mm → Revit internal feet (1 ft = 304.8 mm).
    height_ft = float(height) / 304.8
    pts_csharp = ", ".join(
        f"new XYZ({float(p[0])/304.8}, {float(p[1])/304.8}, "
        f"{float(p[2] if len(p) > 2 else 0)/304.8})"
        for p in polyline)
    return f"""    try {{
      var pts = new XYZ[] {{ {pts_csharp} }};
      if (pts.Length < 2) throw new InvalidOperationException(
        "wall polyline needs ≥2 points");
      var lvl = new FilteredElementCollector(doc)
        .OfClass(typeof(Level)).Cast<Level>()
        .FirstOrDefault(l => l.Name == {_csharp_string(level)});
      if (lvl == null) throw new InvalidOperationException(
        "Level not found: " + {_csharp_string(level)});
      var wt = new FilteredElementCollector(doc)
        .OfClass(typeof(WallType)).Cast<WallType>()
        .FirstOrDefault(t => t.Name == {_csharp_string(wall_type)});
      if (wt == null) throw new InvalidOperationException(
        "WallType not found: " + {_csharp_string(wall_type)});
      for (int s = 0; s < pts.Length - 1; s++) {{
        var curve = Line.CreateBound(pts[s], pts[s+1]);
        var w = Wall.Create(doc, curve, wt.Id, lvl.Id,
                            {height_ft}, 0, false, {str(structural).lower()});
        created.Add(new {{ idx = {idx}, kind = "wall",
                            id = w.Id.IntegerValue }});
      }}
    }} catch (Exception ex) {{
      errors.Add(new {{ idx = {idx}, kind = "wall", error = ex.Message }});
    }}"""


def _emit_directshape(idx: int, item: dict) -> str:
    """Emit the C# `try { DirectShape.CreateElement(...) }` body for
    one `adapter.to_revit_directshape` item.

    Required annotations:
        revit_directshape_category   (built-in category enum NAME)
        revit_geometry_json          (Speckle geometry JSON — handed
                                      to a DirectShape SetShape call;
                                      placeholder geometry if absent)
    """
    cat = item.get("revit_directshape_category") or \
          item.get("revit_builtin_category") or "OST_GenericModel"
    # The geometry conversion is non-trivial in real Revit;
    # for the MVP we create the DirectShape with a placeholder
    # element (the user can later wire-in a real Mesh from Speckle).
    return f"""    try {{
      var bic = (BuiltInCategory)Enum.Parse(typeof(BuiltInCategory),
                                              {_csharp_string(cat)});
      var ds = DirectShape.CreateElement(doc, new ElementId(bic));
      ds.SetName("ArchHub-{idx}");
      created.Add(new {{ idx = {idx}, kind = "directshape",
                          id = ds.Id.IntegerValue }});
    }} catch (Exception ex) {{
      errors.Add(new {{ idx = {idx}, kind = "directshape",
                         error = ex.Message }});
    }}"""


def _emit_family_instance(idx: int, item: dict) -> str:
    """Emit the C# `try { doc.Create.NewFamilyInstance(...) }` body
    for one `adapter.max_to_revit_family` item.

    Required annotations:
        revit_family_name        (Family name)
        revit_family_template    (optional — Family Template — only
                                  used by a separate load step)
        revit_target_category    (BuiltInCategory enum name)
        revit_origin             ([x,y,z] in mm; defaults to origin)
        revit_parameters         (dict of name → value to push onto
                                  the placed FamilyInstance)
        revit_level              (Level name; defaults to active view's
                                  GenLevel)
    """
    family = item.get("revit_family_name") or ""
    cat = item.get("revit_target_category") or ""
    origin = item.get("revit_origin") or [0, 0, 0]
    params = item.get("revit_parameters") or {}
    level = item.get("revit_level") or ""
    ox = float(origin[0]) / 304.8 if len(origin) > 0 else 0.0
    oy = float(origin[1]) / 304.8 if len(origin) > 1 else 0.0
    oz = float(origin[2]) / 304.8 if len(origin) > 2 else 0.0
    set_params_lines = []
    for k, v in params.items():
        if isinstance(v, (int, float)):
            set_params_lines.append(
                f"      try {{ var p = fi.LookupParameter({_csharp_string(k)});"
                f" if (p != null) p.Set({v}); }} catch {{}}")
        else:
            set_params_lines.append(
                f"      try {{ var p = fi.LookupParameter({_csharp_string(k)});"
                f" if (p != null) p.Set({_csharp_string(str(v))}); }} catch {{}}")
    set_params_block = "\n".join(set_params_lines) or "      // (no parameters)"
    level_lookup = (
        f"new FilteredElementCollector(doc).OfClass(typeof(Level))"
        f".Cast<Level>().FirstOrDefault(l => l.Name == {_csharp_string(level)})"
        if level
        else "(doc.ActiveView != null ? doc.ActiveView.GenLevel : null)"
    )
    return f"""    try {{
      var sym = new FilteredElementCollector(doc)
        .OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()
        .FirstOrDefault(s => s.Family.Name == {_csharp_string(family)});
      if (sym == null) throw new InvalidOperationException(
        "Family not loaded: " + {_csharp_string(family)});
      if (!sym.IsActive) sym.Activate();
      var lvl = {level_lookup};
      var origin = new XYZ({ox}, {oy}, {oz});
      var fi = lvl != null
        ? doc.Create.NewFamilyInstance(origin, sym, lvl,
            Autodesk.Revit.DB.Structure.StructuralType.NonStructural)
        : doc.Create.NewFamilyInstance(origin, sym,
            Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
{set_params_block}
      created.Add(new {{ idx = {idx}, kind = "family",
                          id = fi.Id.IntegerValue }});
    }} catch (Exception ex) {{
      errors.Add(new {{ idx = {idx}, kind = "family",
                         error = ex.Message }});
    }}"""


def _emit_detail_line(idx: int, item: dict) -> str:
    """Emit the C# `try { DetailCurve.Create(...) }` body for one
    `adapter.cad_to_revit_detail_line` item.

    Required annotations:
        revit_target_category == "DetailLines"
        revit_polyline   (list of [x,y,z] points, mm)
        revit_view_id    (Revit View ElementId; 0 = active view)
        revit_line_style (optional — line style name)
    """
    polyline = item.get("revit_polyline") or []
    view_id = int(item.get("revit_view_id") or 0)
    line_style = item.get("revit_line_style") or ""
    pts_csharp = ", ".join(
        f"new XYZ({float(p[0])/304.8}, {float(p[1])/304.8}, "
        f"{float(p[2] if len(p) > 2 else 0)/304.8})"
        for p in polyline)
    view_lookup = (
        f"doc.GetElement(new ElementId({view_id})) as View"
        if view_id > 0
        else "doc.ActiveView"
    )
    style_lookup = (
        f"new FilteredElementCollector(doc).OfClass(typeof(GraphicsStyle))"
        f".Cast<GraphicsStyle>().FirstOrDefault(g => g.Name == "
        f"{_csharp_string(line_style)})"
        if line_style
        else "null"
    )
    return f"""    try {{
      var pts = new XYZ[] {{ {pts_csharp} }};
      if (pts.Length < 2) throw new InvalidOperationException(
        "detail line polyline needs ≥2 points");
      var view = {view_lookup};
      if (view == null) throw new InvalidOperationException(
        "View not found (id={view_id})");
      var style = {style_lookup};
      for (int s = 0; s < pts.Length - 1; s++) {{
        var curve = Line.CreateBound(pts[s], pts[s+1]);
        var dc = doc.Create.NewDetailCurve(view, curve);
        if (style != null) dc.LineStyle = style;
        created.Add(new {{ idx = {idx}, kind = "detail_line",
                            id = dc.Id.IntegerValue }});
      }}
    }} catch (Exception ex) {{
      errors.Add(new {{ idx = {idx}, kind = "detail_line",
                         error = ex.Message }});
    }}"""


def _emit_beam(idx: int, item: dict) -> str:
    """Emit the C# `try { NewFamilyInstance(curve, ..., StructuralType.Beam) }`
    body for one `adapter.rhino_to_revit_beam` item.

    Required annotations:
        revit_target_category == "StructuralFraming"
        revit_polyline           (list of [x,y,z] mm — start + end)
        revit_beam_family        (Family name)
        revit_beam_type          (Type within the family)
        revit_level              (Level name)
    """
    polyline = item.get("revit_polyline") or []
    beam_family = item.get("revit_beam_family") or ""
    beam_type = item.get("revit_beam_type") or ""
    level = item.get("revit_level") or ""
    if len(polyline) < 2:
        # Degenerate — emit a guaranteed-error block so the failure
        # surfaces in the result (rather than silently dropping).
        return f"""    try {{
      throw new InvalidOperationException(
        "beam polyline needs at least a start and end point");
    }} catch (Exception ex) {{
      errors.Add(new {{ idx = {idx}, kind = "beam",
                         error = ex.Message }});
    }}"""
    p0 = polyline[0]
    p1 = polyline[1]
    p0x, p0y, p0z = (float(p0[0])/304.8, float(p0[1])/304.8,
                      float(p0[2] if len(p0) > 2 else 0)/304.8)
    p1x, p1y, p1z = (float(p1[0])/304.8, float(p1[1])/304.8,
                      float(p1[2] if len(p1) > 2 else 0)/304.8)
    return f"""    try {{
      var sym = new FilteredElementCollector(doc)
        .OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()
        .FirstOrDefault(s => s.Family.Name == {_csharp_string(beam_family)}
                          && s.Name == {_csharp_string(beam_type)});
      if (sym == null) throw new InvalidOperationException(
        "Beam family/type not loaded: " + {_csharp_string(beam_family)}
        + "/" + {_csharp_string(beam_type)});
      if (!sym.IsActive) sym.Activate();
      var lvl = new FilteredElementCollector(doc).OfClass(typeof(Level))
        .Cast<Level>().FirstOrDefault(l => l.Name == {_csharp_string(level)});
      if (lvl == null) throw new InvalidOperationException(
        "Level not found: " + {_csharp_string(level)});
      var curve = Line.CreateBound(new XYZ({p0x}, {p0y}, {p0z}),
                                    new XYZ({p1x}, {p1y}, {p1z}));
      var fi = doc.Create.NewFamilyInstance(curve, sym, lvl,
        Autodesk.Revit.DB.Structure.StructuralType.Beam);
      created.Add(new {{ idx = {idx}, kind = "beam",
                          id = fi.Id.IntegerValue }});
    }} catch (Exception ex) {{
      errors.Add(new {{ idx = {idx}, kind = "beam",
                         error = ex.Message }});
    }}"""


def _classify_item(item: dict) -> str:
    """Pick the create-fn for an item from its `revit_*` annotations.
    Returns one of: 'wall', 'directshape', 'family', 'beam',
    'detail_line', 'parameter_set', 'skip'.

    Precedence:
      explicit `revit_target_category == "Walls"`            → wall
      explicit `revit_target_category == "DetailLines"`      → detail_line
      `revit_target_category == "StructuralFraming"` +
       `revit_beam_family`                                   → beam
      `revit_element_id` + `revit_parameters`                → parameter_set
       (consumed by `revit.batch_set_parameters`, NOT by
        `build_create_script` — it's a mutation, not a creation)
      `revit_family_name`                                    → family
      `revit_directshape_category` or `revit_builtin_category` → directshape
      otherwise                                              → skip
    """
    if not isinstance(item, dict):
        return "skip"
    cat = item.get("revit_target_category")
    if cat == "Walls":
        return "wall"
    if cat == "DetailLines":
        return "detail_line"
    if cat == "StructuralFraming" and item.get("revit_beam_family"):
        return "beam"
    if item.get("revit_element_id") and \
       isinstance(item.get("revit_parameters"), dict):
        return "parameter_set"
    if item.get("revit_family_name"):
        return "family"
    if item.get("revit_directshape_category") or \
       item.get("revit_builtin_category"):
        return "directshape"
    return "skip"


def build_create_script(items: list, transaction_name: str = _TX_RECV
                         ) -> str:
    """Generate one C# transaction body for an entire receive call.

    Each item gets a try/catch block. Successful creates append to
    `created` (with idx + kind + id); failures append to `errors`
    (with idx + kind + error message); items with no recognised
    `revit_*` annotation append to `skipped`. The script ends with
    a `ctx.result = ...` that serialises into the RevitMCP /exec
    response.

    Pure function — no Revit needed to test."""
    bodies: list[str] = []
    skipped: list[int] = []
    for i, item in enumerate(items or []):
        kind = _classify_item(item)
        if kind == "wall":
            bodies.append(_emit_wall(i, item))
        elif kind == "family":
            bodies.append(_emit_family_instance(i, item))
        elif kind == "directshape":
            bodies.append(_emit_directshape(i, item))
        elif kind == "beam":
            bodies.append(_emit_beam(i, item))
        elif kind == "detail_line":
            bodies.append(_emit_detail_line(i, item))
        else:
            # 'parameter_set' items also fall here — they belong to
            # `revit.batch_set_parameters`, NOT to the create script.
            # Surfacing them in `skipped` is honest.
            skipped.append(i)
    inner = "\n".join(bodies) if bodies else "    // (no creatable items)"
    skipped_csharp = ", ".join(str(i) for i in skipped)
    return f"""
// ArchHub M2-Python receive_from_speckle · AgDR-0017
// Transaction: {transaction_name}
var doc = ctx.Document;
var created = new System.Collections.Generic.List<object>();
var errors  = new System.Collections.Generic.List<object>();
var skipped = new System.Collections.Generic.List<int> {{ {skipped_csharp} }};
{inner}
ctx.result = new {{
    created_count = created.Count,
    error_count = errors.Count,
    skipped_count = skipped.Count,
    created = created,
    errors = errors,
    skipped = skipped,
}};
""".strip()


def receive_from_speckle(source_url: str = "", *,
                          instance: str | None = None,
                          project_dir: str | None = None,
                          op_id: str = "revit.receive_from_speckle"
                          ) -> dict:
    """Pull a Speckle commit by URL · classify items by annotation ·
    emit one C# transaction · POST via the RevitMCP `/exec` route.

    Returns ``{"created_count","error_count","skipped_count",
              "items"}`` echoing the Revit-side per-item results.
    """
    if not source_url:
        return {"status": "error",
                "error": "source_url is required"}
    # Resolve the upstream model.
    try:
        from speckle_wire import SpeckleWire, default_project_dir
    except Exception as ex:
        return {"status": "error",
                "error": f"SpeckleWire unavailable: {ex}"}
    pdir = project_dir or default_project_dir()
    wire = SpeckleWire(pdir)
    # `share.subscribe`-style URL parsing: speckle://local/<hash>
    # OR bare hash; remote URLs not yet supported in this MVP.
    if source_url.startswith("speckle://local/"):
        hash_id = source_url[len("speckle://local/"):]
    elif "://" not in source_url:
        hash_id = source_url
    else:
        return {"status": "error",
                "error": "remote Speckle URLs not yet supported "
                         "in revit.receive_from_speckle MVP"}
    try:
        payload = wire.receive(hash_id)
    except Exception as ex:
        return {"status": "error",
                "error": f"SpeckleWire.receive failed: {ex}"}
    # The send-side stamps `{revit_source, model_name, item_count,
    # data}`. We pull `data` (the original shape). A list goes
    # through as-is; a single dict is wrapped.
    data = (payload or {}).get("data") \
        if isinstance(payload, dict) and "data" in payload \
        else payload
    items = _coerce_items(data)
    script = build_create_script(items)
    # Run the script via the existing Revit /exec route.
    try:
        from connectors.revit_connector import _exec
    except Exception as ex:
        return {"status": "error",
                "error": f"Revit connector unavailable: {ex}"}
    try:
        result = _exec(op_id, script, instance=instance,
                       tx_name=_TX_RECV, timeout=60.0)
    except Exception as ex:
        return {"status": "error",
                "error": f"/exec failed: {ex}"}
    # The /exec response shape is the C# `ctx.result` value.
    if isinstance(result, OpResult):
        return {"status": "ok" if result.ok else "error",
                "items": items,
                "result": result.value,
                "error": result.error}
    return {"status": "ok", "items": items, "result": result}


def build_set_parameters_script(items: list,
                                  transaction_name: str = "ArchHub: "
                                  "batch set parameters") -> str:
    """Generate one C# transaction body that walks `items`, looks up
    each element by `revit_element_id`, and pushes every parameter
    from `revit_parameters` onto it.

    Items without `revit_element_id` are skipped (idx in `skipped`).
    Per-item + per-parameter try/catch so partial work lands cleanly.
    Pure function — no Revit needed to test."""
    blocks: list[str] = []
    skipped: list[int] = []
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            skipped.append(i); continue
        eid = item.get("revit_element_id")
        params = item.get("revit_parameters")
        if not isinstance(params, dict) or not eid:
            skipped.append(i); continue
        try:
            eid_int = int(eid)
        except (TypeError, ValueError):
            skipped.append(i); continue
        param_lines: list[str] = []
        for k, v in params.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                param_lines.append(
                    f"        try {{ var p = el.LookupParameter("
                    f"{_csharp_string(k)}); if (p != null) p.Set({v}); "
                    f"set_count++; }} catch {{ }}")
            elif isinstance(v, bool):
                # ElementId(int) for Yes/No (Revit param Set(int) for
                # booleans is 0/1).
                ival = 1 if v else 0
                param_lines.append(
                    f"        try {{ var p = el.LookupParameter("
                    f"{_csharp_string(k)}); if (p != null) p.Set({ival}); "
                    f"set_count++; }} catch {{ }}")
            else:
                param_lines.append(
                    f"        try {{ var p = el.LookupParameter("
                    f"{_csharp_string(k)}); if (p != null) p.Set("
                    f"{_csharp_string(str(v))}); set_count++; }} catch {{ }}")
        param_block = "\n".join(param_lines) or "        // (no parameters)"
        blocks.append(f"""    try {{
      var el = doc.GetElement(new ElementId({eid_int}));
      if (el == null) throw new InvalidOperationException(
        "Element not found: id={eid_int}");
      int set_count = 0;
{param_block}
      updated.Add(new {{ idx = {i}, element_id = {eid_int},
                          set_count = set_count }});
    }} catch (Exception ex) {{
      errors.Add(new {{ idx = {i}, element_id = {eid_int},
                         error = ex.Message }});
    }}""")
    inner = "\n".join(blocks) if blocks else "    // (no parameter rows)"
    skipped_csharp = ", ".join(str(i) for i in skipped)
    return f"""
// ArchHub M2-Python · AgDR-0018 · batch_set_parameters
// Transaction: {transaction_name}
var doc = ctx.Document;
var updated = new System.Collections.Generic.List<object>();
var errors  = new System.Collections.Generic.List<object>();
var skipped = new System.Collections.Generic.List<int> {{ {skipped_csharp} }};
{inner}
ctx.result = new {{
    updated_count = updated.Count,
    error_count = errors.Count,
    skipped_count = skipped.Count,
    updated = updated,
    errors = errors,
    skipped = skipped,
}};
""".strip()


def batch_set_parameters(source_url: str = "", *,
                          instance: str | None = None,
                          project_dir: str | None = None,
                          op_id: str = "revit.batch_set_parameters"
                          ) -> dict:
    """Pull a Speckle commit · expect `excel_to_revit_params`-shaped
    items · emit one C# transaction setting each row's parameters on
    the named element · POST via RevitMCP `/exec`."""
    if not source_url:
        return {"status": "error",
                "error": "source_url is required"}
    try:
        from speckle_wire import SpeckleWire, default_project_dir
    except Exception as ex:
        return {"status": "error",
                "error": f"SpeckleWire unavailable: {ex}"}
    pdir = project_dir or default_project_dir()
    wire = SpeckleWire(pdir)
    if source_url.startswith("speckle://local/"):
        hash_id = source_url[len("speckle://local/"):]
    elif "://" not in source_url:
        hash_id = source_url
    else:
        return {"status": "error",
                "error": "remote URLs not yet supported "
                         "in revit.batch_set_parameters MVP"}
    try:
        payload = wire.receive(hash_id)
    except Exception as ex:
        return {"status": "error",
                "error": f"SpeckleWire.receive failed: {ex}"}
    data = (payload or {}).get("data") \
        if isinstance(payload, dict) and "data" in payload \
        else payload
    items = _coerce_items(data)
    script = build_set_parameters_script(items)
    try:
        from connectors.revit_connector import _exec
    except Exception as ex:
        return {"status": "error",
                "error": f"Revit connector unavailable: {ex}"}
    try:
        result = _exec(op_id, script, instance=instance,
                       tx_name="ArchHub: batch set parameters",
                       timeout=60.0)
    except Exception as ex:
        return {"status": "error",
                "error": f"/exec failed: {ex}"}
    if isinstance(result, OpResult):
        return {"status": "ok" if result.ok else "error",
                "items": items, "result": result.value,
                "error": result.error}
    return {"status": "ok", "items": items, "result": result}


__all__ = [
    "send_to_speckle",
    "receive_from_speckle",
    "build_create_script",
    "batch_set_parameters",
    "build_set_parameters_script",
]
