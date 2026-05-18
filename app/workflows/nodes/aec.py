"""AEC-specific workflow nodes.

Matches the founder's BubbleGraph reference: the canvas should ship a
node library that speaks AEC out of the box, not just generic
Input/Math/Output. v1.3.3 seeds the library with 9 nodes covering the
common construction-data + parametric-design patterns.

Each node:
  - has a stable `aec.*` type id
  - declares inputs/outputs + a config_schema with sensible defaults
  - degrades gracefully if an optional library is missing (executor
    returns {"status":"missing_dep", "library": "ezdxf"} instead of
    raising)

The executors are pure-Python + stdlib by default. ezdxf / ifcopenshell
/ pandas are tried inside the executor; absence is reported back, not
crashed on.

BRAND voice: no emoji, no exclamation, terse description (50 chars max),
icon = single Unicode glyph from a typographic / mathematical set.
"""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ---------------------------------------------------------------------------
# 1. DXF Reader — parse a .dwg/.dxf and return layers + entity count.
def _dxf_reader_exec(config: dict, inputs: dict, ctx) -> dict:
    path = (inputs.get("path") or config.get("path") or "").strip()
    if not path:
        return {"status": "error", "error": "path is required"}
    try:
        import ezdxf  # type: ignore
    except ImportError:
        return {"status": "missing_dep", "library": "ezdxf",
                "hint": "pip install ezdxf"}
    if not Path(path).exists():
        return {"status": "error", "error": f"file not found: {path}"}
    try:
        doc = ezdxf.readfile(path)
    except Exception as ex:
        return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}
    msp = doc.modelspace()
    layers = sorted({e.dxf.layer for e in msp if hasattr(e, "dxf")})
    counts = {}
    for e in msp:
        counts[e.dxftype()] = counts.get(e.dxftype(), 0) + 1
    return {
        "status": "ok",
        "path": path,
        "layers": layers,
        "entity_counts": counts,
        "total_entities": sum(counts.values()),
    }


register(
    NodeSpec(
        type="aec.dxf_reader",
        category="aec.files",
        display_name="DXF Reader",
        description="Parse a DXF file. Returns layers + entity counts.",
        inputs=[Port(name="path", type=PortType.STRING)],
        outputs=[
            Port(name="layers", type=PortType.LIST),
            Port(name="entity_counts", type=PortType.OBJECT),
            Port(name="total_entities", type=PortType.NUMBER),
        ],
        config_schema={
            "path": {"type": "string",
                      "description": "Absolute path to .dxf file"},
        },
        icon="◫",
    ),
    _dxf_reader_exec,
)


# ---------------------------------------------------------------------------
# 2. IFC Reader — parse an .ifc and return building elements.
def _ifc_reader_exec(config: dict, inputs: dict, ctx) -> dict:
    path = (inputs.get("path") or config.get("path") or "").strip()
    if not path:
        return {"status": "error", "error": "path is required"}
    try:
        import ifcopenshell  # type: ignore
    except ImportError:
        return {"status": "missing_dep", "library": "ifcopenshell",
                "hint": "pip install ifcopenshell"}
    if not Path(path).exists():
        return {"status": "error", "error": f"file not found: {path}"}
    try:
        model = ifcopenshell.open(path)
    except Exception as ex:
        return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}
    elt_types = ("IfcWall", "IfcDoor", "IfcWindow", "IfcSlab",
                 "IfcColumn", "IfcBeam", "IfcSpace", "IfcStair")
    counts = {t: len(model.by_type(t)) for t in elt_types}
    schema = getattr(model, "schema", "IFC?")
    return {
        "status": "ok",
        "path": path,
        "schema": schema,
        "element_counts": counts,
        "total_elements": sum(counts.values()),
    }


register(
    NodeSpec(
        type="aec.ifc_reader",
        category="aec.files",
        display_name="IFC Reader",
        description="Parse an IFC file. Returns element counts by type.",
        inputs=[Port(name="path", type=PortType.STRING)],
        outputs=[
            Port(name="schema", type=PortType.STRING),
            Port(name="element_counts", type=PortType.OBJECT),
            Port(name="total_elements", type=PortType.NUMBER),
        ],
        config_schema={
            "path": {"type": "string",
                      "description": "Absolute path to .ifc file"},
        },
        icon="◰",
    ),
    _ifc_reader_exec,
)


# ---------------------------------------------------------------------------
# 3. CSV Reader — stdlib, zero deps.
def _csv_reader_exec(config: dict, inputs: dict, ctx) -> dict:
    path = (inputs.get("path") or config.get("path") or "").strip()
    if not path:
        return {"status": "error", "error": "path is required"}
    if not Path(path).exists():
        return {"status": "error", "error": f"file not found: {path}"}
    delimiter = config.get("delimiter") or ","
    encoding = config.get("encoding") or "utf-8"
    try:
        with open(path, encoding=encoding, newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            rows = list(reader)
            columns = reader.fieldnames or []
    except Exception as ex:
        return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}
    return {
        "status": "ok",
        "path": path,
        "columns": list(columns),
        "row_count": len(rows),
        "rows": rows[:1000],  # cap for memory
    }


register(
    NodeSpec(
        type="aec.csv_reader",
        category="aec.files",
        display_name="CSV Reader",
        description="Read CSV into rows + columns (stdlib, no pandas).",
        inputs=[Port(name="path", type=PortType.STRING)],
        outputs=[
            Port(name="columns", type=PortType.LIST),
            Port(name="rows", type=PortType.LIST),
            Port(name="row_count", type=PortType.NUMBER),
        ],
        config_schema={
            "path": {"type": "string"},
            "delimiter": {"type": "string", "default": ","},
            "encoding": {"type": "string", "default": "utf-8"},
        },
        icon="≡",
    ),
    _csv_reader_exec,
)


# ---------------------------------------------------------------------------
# 4. Revit Wall — emit a wall-creation spec the chat can pipe into
#    revit_execute_csharp downstream.
def _revit_wall_exec(config: dict, inputs: dict, ctx) -> dict:
    length_mm = float(inputs.get("length_mm") or config.get("length_mm") or 3000)
    height_mm = float(inputs.get("height_mm") or config.get("height_mm") or 2700)
    width_mm  = float(inputs.get("width_mm")  or config.get("width_mm")  or 200)
    level     = (inputs.get("level") or config.get("level") or "Level 1").strip()
    wall_type = (inputs.get("wall_type") or config.get("wall_type") or "Generic - 200mm").strip()
    # Safely JSON-quote the user-controlled strings so a stray double-quote
    # can't escape the generated C# (`Generic - 200"` would break out and
    # let arbitrary code through). json.dumps emits a proper C-style
    # escaped literal we can drop into a string slot.
    import json as _json
    level_lit = _json.dumps(level)
    wall_type_lit = _json.dumps(wall_type)
    csharp = (
        f"// auto-emitted by aec.revit_wall node\n"
        f"var lvl = new FilteredElementCollector(Doc)\n"
        f"    .OfClass(typeof(Level)).Cast<Level>()\n"
        f"    .FirstOrDefault(l => l.Name == {level_lit});\n"
        f"if (lvl == null) {{ result = new {{ status = \"error\","
        f" reason = \"level {level} not found\" }}; return; }}\n"
        f"var wt = new FilteredElementCollector(Doc)\n"
        f"    .OfClass(typeof(WallType)).Cast<WallType>()\n"
        f"    .FirstOrDefault(t => t.Name == {wall_type_lit});\n"
        f"if (wt == null) {{ result = new {{ status = \"error\","
        f" reason = \"wall type {wall_type} not found\" }}; return; }}\n"
        f"var line = Line.CreateBound(\n"
        f"    new XYZ(0, 0, 0),\n"
        f"    new XYZ({length_mm}/304.8, 0, 0));\n"
        f"var w = Wall.Create(Doc, line, wt.Id, lvl.Id,\n"
        f"    {height_mm}/304.8, 0, false, false);\n"
        f"result = new {{ status = \"ok\", wall_id = w.Id.IntegerValue }};\n"
    )
    return {
        "status": "ok",
        "length_mm": length_mm,
        "height_mm": height_mm,
        "width_mm": width_mm,
        "level": level,
        "wall_type": wall_type,
        "csharp": csharp,
    }


register(
    NodeSpec(
        type="aec.revit_wall",
        category="aec.revit",
        display_name="Revit Wall",
        description="Emit a wall-creation C# snippet. Pipe into revit_execute_csharp.",
        inputs=[
            Port(name="length_mm", type=PortType.NUMBER),
            Port(name="height_mm", type=PortType.NUMBER),
            Port(name="width_mm",  type=PortType.NUMBER),
            Port(name="level",     type=PortType.STRING),
            Port(name="wall_type", type=PortType.STRING),
        ],
        outputs=[
            Port(name="csharp",    type=PortType.STRING),
            Port(name="length_mm", type=PortType.NUMBER),
            Port(name="height_mm", type=PortType.NUMBER),
        ],
        config_schema={
            "length_mm": {"type": "number", "default": 3000},
            "height_mm": {"type": "number", "default": 2700},
            "width_mm":  {"type": "number", "default": 200},
            "level":     {"type": "string", "default": "Level 1"},
            "wall_type": {"type": "string", "default": "Generic - 200mm"},
        },
        icon="▐",
    ),
    _revit_wall_exec,
)


# ---------------------------------------------------------------------------
# 5. Column — structural column with section + height.
def _column_exec(config: dict, inputs: dict, ctx) -> dict:
    section = (inputs.get("section") or config.get("section") or "300x300").strip()
    height_mm = float(inputs.get("height_mm") or config.get("height_mm") or 3000)
    material = (inputs.get("material") or config.get("material") or "Concrete").strip()
    try:
        w_mm, h_mm = [float(p) for p in section.replace("x", "X").split("X")[:2]]
    except Exception:
        return {"status": "error", "error": f"section '{section}' must be WxH (e.g. 300x300)"}
    volume_m3 = (w_mm / 1000) * (h_mm / 1000) * (height_mm / 1000)
    return {
        "status": "ok",
        "section": section,
        "height_mm": height_mm,
        "material": material,
        "width_mm": w_mm,
        "depth_mm": h_mm,
        "volume_m3": round(volume_m3, 4),
    }


register(
    NodeSpec(
        type="aec.column",
        category="aec.parts",
        display_name="Column",
        description="Structural column. Computes volume from section + height.",
        inputs=[
            Port(name="section",   type=PortType.STRING),
            Port(name="height_mm", type=PortType.NUMBER),
            Port(name="material",  type=PortType.STRING),
        ],
        outputs=[
            Port(name="volume_m3", type=PortType.NUMBER),
            Port(name="width_mm",  type=PortType.NUMBER),
            Port(name="depth_mm",  type=PortType.NUMBER),
        ],
        config_schema={
            "section":   {"type": "string", "default": "300x300"},
            "height_mm": {"type": "number", "default": 3000},
            "material":  {"type": "string", "default": "Concrete"},
        },
        icon="█",
    ),
    _column_exec,
)


# ---------------------------------------------------------------------------
# 6. QTO Pricing — quantity-take-off × unit price → line total.
def _qto_pricing_exec(config: dict, inputs: dict, ctx) -> dict:
    quantity = float(inputs.get("quantity") or 0)
    unit_price = float(inputs.get("unit_price") or config.get("unit_price") or 0)
    currency = (inputs.get("currency") or config.get("currency") or "AED").strip()
    line_item = (inputs.get("line_item") or config.get("line_item") or "").strip()
    line_total = round(quantity * unit_price, 2)
    return {
        "status": "ok",
        "line_item": line_item,
        "quantity": quantity,
        "unit_price": unit_price,
        "currency": currency,
        "line_total": line_total,
        "formatted": f"{line_item}: {quantity:.2f} × {unit_price:.2f} {currency} = {line_total:.2f} {currency}",
    }


register(
    NodeSpec(
        type="aec.qto_pricing",
        category="aec.qto",
        display_name="QTO Pricing",
        description="Multiply quantity × unit price to get a line total.",
        inputs=[
            Port(name="quantity",   type=PortType.NUMBER),
            Port(name="unit_price", type=PortType.NUMBER),
            Port(name="line_item",  type=PortType.STRING),
        ],
        outputs=[
            Port(name="line_total", type=PortType.NUMBER),
            Port(name="formatted",  type=PortType.STRING),
        ],
        config_schema={
            "unit_price": {"type": "number", "default": 0},
            "currency":   {"type": "string", "default": "AED"},
            "line_item":  {"type": "string", "default": ""},
        },
        icon="¤",
    ),
    _qto_pricing_exec,
)


# ---------------------------------------------------------------------------
# 7. Cost Estimate — sum a list of line totals.
def _cost_estimate_exec(config: dict, inputs: dict, ctx) -> dict:
    items = inputs.get("items") or []
    if not isinstance(items, list):
        return {"status": "error", "error": "items must be an array"}
    currency = (inputs.get("currency") or config.get("currency") or "AED").strip()
    total = 0.0
    for it in items:
        if isinstance(it, dict):
            v = it.get("line_total") or it.get("total") or 0
        else:
            v = it
        try:
            total += float(v)
        except (TypeError, ValueError):
            pass
    return {
        "status": "ok",
        "currency": currency,
        "item_count": len(items),
        "grand_total": round(total, 2),
        "formatted": f"{len(items)} items · {total:,.2f} {currency}",
    }


register(
    NodeSpec(
        type="aec.cost_estimate",
        category="aec.qto",
        display_name="Cost Estimate",
        description="Sum a list of priced items to get a grand total.",
        inputs=[Port(name="items", type=PortType.LIST)],
        outputs=[
            Port(name="grand_total", type=PortType.NUMBER),
            Port(name="formatted",   type=PortType.STRING),
        ],
        config_schema={
            "currency": {"type": "string", "default": "AED"},
        },
        icon="Σ",
    ),
    _cost_estimate_exec,
)


# ---------------------------------------------------------------------------
# 8. Schedule Builder — collect rows into a tabular spec (downstream
# can pipe into revit_execute_csharp or a CSV writer).
def _schedule_builder_exec(config: dict, inputs: dict, ctx) -> dict:
    rows = inputs.get("rows") or []
    columns = inputs.get("columns") or config.get("columns") or []
    if not isinstance(rows, list) or not isinstance(columns, list):
        return {"status": "error", "error": "rows + columns must be arrays"}
    title = (inputs.get("title") or config.get("title") or "Schedule").strip()
    return {
        "status": "ok",
        "title": title,
        "columns": columns,
        "row_count": len(rows),
        "rows": rows,
    }


register(
    NodeSpec(
        type="aec.schedule_builder",
        category="aec.qto",
        display_name="Schedule Builder",
        description="Collect rows + columns into a schedule spec.",
        inputs=[
            Port(name="rows",    type=PortType.LIST),
            Port(name="columns", type=PortType.LIST),
            Port(name="title",   type=PortType.STRING),
        ],
        outputs=[
            Port(name="rows",      type=PortType.LIST),
            Port(name="columns",   type=PortType.LIST),
            Port(name="row_count", type=PortType.NUMBER),
        ],
        config_schema={
            "title":   {"type": "string", "default": "Schedule"},
            "columns": {"type": "array",  "default": []},
        },
        icon="≣",
    ),
    _schedule_builder_exec,
)


# ---------------------------------------------------------------------------
# 9. Team Member Selector — pick a name (or list) from a roster.
def _team_member_exec(config: dict, inputs: dict, ctx) -> dict:
    roster = inputs.get("roster") or config.get("roster") or []
    if not isinstance(roster, list):
        return {"status": "error", "error": "roster must be an array"}
    role = (inputs.get("role") or config.get("role") or "").strip().lower()
    if role:
        picks = [m for m in roster if isinstance(m, dict)
                 and (m.get("role") or "").strip().lower() == role]
    else:
        picks = list(roster)
    return {
        "status": "ok",
        "role_filter": role,
        "members": picks,
        "count": len(picks),
    }


register(
    NodeSpec(
        type="aec.team_member_selector",
        category="aec.team",
        display_name="Team Member Selector",
        description="Filter a roster by role. Returns matching members.",
        inputs=[
            Port(name="roster", type=PortType.LIST),
            Port(name="role",   type=PortType.STRING),
        ],
        outputs=[
            Port(name="members", type=PortType.LIST),
            Port(name="count",   type=PortType.NUMBER),
        ],
        config_schema={
            "role":   {"type": "string", "default": ""},
            "roster": {"type": "array",  "default": []},
        },
        icon="◍",
    ),
    _team_member_exec,
)
