"""ADAPTER category engine nodes — cross-host native-type mapping.

Reference: founder demand 2026-05-21. "Wires should map data as per
native categories from an application to another." Example: 3ds Max mass
→ Revit native family with parameters · CAD A-WALL layer → Revit Wall.

Architecture:
  • Source host's Speckle connector (Revit / AutoCAD / Rhino / 3ds Max)
    extracts geometry as a Speckle `Base` with `speckle_type` (e.g.
    Objects.Geometry.Polyline, Objects.Geometry.Mesh).
  • Adapter nodes sit MID-WIRE and ANNOTATE the Base with
    target-host metadata: `revit_target_category` / `revit_family_name` /
    `revit_parameters` etc.
  • Receiving host's Speckle connector reads those annotations on the
    way in and creates the right native (Wall / FamilyInstance /
    DirectShape fallback).

The adapter doesn't TRANSFORM geometry — it ENRICHES the Base with
metadata. Speckle's connector ecosystem handles the actual host-side
conversion.

First two adapters this slice:
  • adapter.cad_to_revit_wall   — Polyline → Wall with level/type
  • adapter.to_revit_directshape — generic Speckle Base → DirectShape
                                    (fallback when no specific mapping)
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ---------------------------------------------------------------------------
# Helpers — annotation read/write
#
# Wires carry plain Python dicts via SpeckleWire's JSON wrap (slice M1.a).
# An adapter reads the dict (or Speckle Base), enriches with `revit_*`
# annotations, returns the enriched dict. Downstream Revit-receive
# connector reads `revit_*` to drive native creation.


def _enrich(value: Any, annotations: dict) -> dict:
    """Merge annotations into the source value. Accepts dict (from
    DiskTransport JSON-wrap) or Speckle Base (from host-extracted typed
    Base). Returns dict — receive-side adapters JSON.loads back.

    Source value's native fields take precedence over annotation keys
    of the same name — adapter annotations live under prefixed
    `revit_*` keys so collisions are explicit.
    """
    if isinstance(value, dict):
        merged = dict(value)
    elif value is None:
        merged = {}
    else:
        # Foreign Base / scalar / list — wrap as the `_source` field.
        merged = {"_source": value}
    merged.update(annotations)
    return merged


# ---------------------------------------------------------------------------
# adapter.cad_to_revit_wall
#
# Input  : value : dict / Base — must carry geometry (curve/polyline)
# Output : value : dict — same content + revit_* annotations
#
# Typical wiring:
#   [autocad.list_layer] (filter to A-WALL)
#     → wire (Polyline list)
#   [adapter.cad_to_revit_wall]
#     config: level="Level 1", wall_type="Generic - 200mm",
#             height=3000, top_offset=0
#     → wire (Polyline + revit annotations)
#   [revit.receive_from_speckle]
#     reads revit_target_category="Walls" + revit_wall_type + revit_level
#     creates Wall via Revit API at the polyline's footprint


def _cad_to_revit_wall_executor(config: dict, inputs: dict, ctx) -> dict:
    value = inputs.get("value")
    level = (config.get("level") or "Level 1").strip()
    wall_type = (config.get("wall_type") or "Generic - 200mm").strip()
    height_mm = float(config.get("height", 3000) or 3000)
    top_offset_mm = float(config.get("top_offset", 0) or 0)
    structural = bool(config.get("structural", False))

    annotations = {
        "revit_target_category": "Walls",
        "revit_wall_type":       wall_type,
        "revit_level":           level,
        "revit_height_mm":       height_mm,
        "revit_top_offset_mm":   top_offset_mm,
        "revit_structural":      structural,
        "_archhub_adapter":      "cad_to_revit_wall",
    }

    if isinstance(value, list):
        # List of polylines → annotate each. Receive-side iterates.
        out = []
        for item in value:
            out.append(_enrich(item, annotations))
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": "Walls",
                           "level": level, "wall_type": wall_type}}

    out = _enrich(value, annotations)
    return {"value": out,
            "status": {"ok": True, "count": 1,
                       "target_category": "Walls",
                       "level": level, "wall_type": wall_type}}


register(
    NodeSpec(
        type="adapter.cad_to_revit_wall",
        category="adapter",
        display_name="CAD → Revit Wall",
        description=(
            "Annotates CAD polyline(s) so the Revit receive-side creates "
            "native Wall(s). Configure level, wall type, height, and "
            "top-offset. Accepts a single polyline or a list."
        ),
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[
            Port(name="value",  type=PortType.ANY),
            Port(name="status", type=PortType.OBJECT),
        ],
        config_schema={
            "level":      {"type": "string", "default": "Level 1",
                            "description": "Revit level name."},
            "wall_type":  {"type": "string", "default": "Generic - 200mm",
                            "description": "Revit wall type name."},
            "height":     {"type": "number", "default": 3000,
                            "description": "Wall height in mm."},
            "top_offset": {"type": "number", "default": 0,
                            "description": "Top constraint offset in mm."},
            "structural": {"type": "boolean", "default": False,
                            "description": "Mark as structural wall."},
        },
        icon="◐",
    ),
    _cad_to_revit_wall_executor,
)


# ---------------------------------------------------------------------------
# adapter.to_revit_directshape
#
# Generic fallback adapter — annotates any Speckle Base to be created as
# Revit DirectShape under the chosen category. Lossy (no parametric type
# binding) but the universal escape hatch for "we don't have a specific
# adapter yet."


def _to_revit_directshape_executor(config: dict, inputs: dict, ctx) -> dict:
    value = inputs.get("value")
    target_category = (config.get("target_category") or "Generic Models").strip()
    category_name = (config.get("category_name") or "ArchHub Direct").strip()
    builtin_category = (config.get("builtin_category")
                         or "OST_GenericModel").strip()

    annotations = {
        "revit_target_category": "DirectShape",
        "revit_directshape_category": target_category,
        "revit_directshape_category_name": category_name,
        "revit_builtin_category": builtin_category,
        "_archhub_adapter":      "to_revit_directshape",
    }

    if isinstance(value, list):
        out = [_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": target_category}}
    return {"value": _enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": target_category}}


register(
    NodeSpec(
        type="adapter.to_revit_directshape",
        category="adapter",
        display_name="→ Revit DirectShape",
        description=(
            "Generic fallback: annotates any geometry to be created as "
            "Revit DirectShape under the chosen built-in category. "
            "Lossy (no parametric family binding) — use a specific adapter "
            "if one exists for your source/target combo."
        ),
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[
            Port(name="value",  type=PortType.ANY),
            Port(name="status", type=PortType.OBJECT),
        ],
        config_schema={
            "target_category":  {"type": "string", "default": "Generic Models"},
            "category_name":    {"type": "string", "default": "ArchHub Direct"},
            "builtin_category": {"type": "string",
                                  "default": "OST_GenericModel",
                                  "description": "Revit BuiltInCategory enum value."},
        },
        icon="◇",
    ),
    _to_revit_directshape_executor,
)


# ---------------------------------------------------------------------------
# adapter.max_to_revit_family
#
# Founder's example: 3ds Max mass → Revit native family with parameters.
# The Max mass arrives as a Speckle Mesh; this adapter annotates it so
# the Revit receive-side creates a FamilyInstance under the Mass category
# (or a configurable category), with the specified parameter bindings.


def _max_to_revit_family_executor(config: dict, inputs: dict, ctx) -> dict:
    value = inputs.get("value")
    target_category = (config.get("target_category") or "Mass").strip()
    family_name = (config.get("family_name") or "ArchHubMass").strip()
    family_template = (config.get("family_template")
                        or "Metric Mass.rft").strip()
    parameters = config.get("parameters") or {}

    annotations = {
        "revit_target_category": target_category,
        "revit_family_name":     family_name,
        "revit_family_template": family_template,
        "revit_parameters":      parameters if isinstance(parameters, dict) else {},
        "_archhub_adapter":      "max_to_revit_family",
    }

    if isinstance(value, list):
        out = [_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": target_category,
                           "family_name": family_name}}
    return {"value": _enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": target_category,
                       "family_name": family_name}}


register(
    NodeSpec(
        type="adapter.max_to_revit_family",
        category="adapter",
        display_name="3ds Max → Revit Family",
        description=(
            "Annotates a 3ds Max mass/mesh so the Revit receive-side "
            "creates a native FamilyInstance under the chosen category "
            "(default Mass), bound to a family template, with the "
            "specified parameter map."
        ),
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[
            Port(name="value",  type=PortType.ANY),
            Port(name="status", type=PortType.OBJECT),
        ],
        config_schema={
            "target_category":  {"type": "string", "default": "Mass",
                                  "description": "Revit category (Mass / Walls / Generic Models / …)."},
            "family_name":      {"type": "string", "default": "ArchHubMass"},
            "family_template":  {"type": "string", "default": "Metric Mass.rft",
                                  "description": "Revit family template (.rft) for new families."},
            "parameters":       {"type": "object", "default": {},
                                  "description": "Parameter map {revit_param_name: value_or_source_path}."},
        },
        icon="▣",
    ),
    _max_to_revit_family_executor,
)


# ---------------------------------------------------------------------------
# Batch 2 (AgDR-0018)
# ---------------------------------------------------------------------------

# adapter.cad_to_revit_detail_line
#
# Source: a polyline / curve from AutoCAD on an annotation layer
#         (e.g. A-ANNO-NOTE). View-specific — does NOT model.
# Output: same polyline + revit annotations targeting `DetailLines`.


def _cad_to_revit_detail_line_executor(config: dict, inputs: dict,
                                         ctx) -> dict:
    value = inputs.get("value")
    view_id = config.get("view_id", 0) or 0
    line_style = (config.get("line_style") or "Thin Lines").strip()

    annotations = {
        "revit_target_category": "DetailLines",
        "revit_view_id":         int(view_id) if view_id else 0,
        "revit_line_style":      line_style,
        "_archhub_adapter":      "cad_to_revit_detail_line",
    }

    if isinstance(value, list):
        out = [_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": "DetailLines",
                           "line_style": line_style}}
    return {"value": _enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": "DetailLines",
                       "line_style": line_style}}


register(
    NodeSpec(
        type="adapter.cad_to_revit_detail_line",
        category="adapter",
        display_name="CAD → Revit Detail Line",
        description=(
            "Annotates CAD polyline(s) so the Revit receive-side "
            "creates view-specific DetailCurve(s). Pick the target "
            "view (0 = active view) and the line style."
        ),
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[
            Port(name="value",  type=PortType.ANY),
            Port(name="status", type=PortType.OBJECT),
        ],
        config_schema={
            "view_id":    {"type": "number", "default": 0,
                            "description": "Target view ElementId; 0 = active view."},
            "line_style": {"type": "string", "default": "Thin Lines",
                            "description": "Revit line style name."},
        },
        icon="┄",
    ),
    _cad_to_revit_detail_line_executor,
)


# ---------------------------------------------------------------------------
# adapter.rhino_to_revit_beam
#
# Source: a Rhino curve (start/end pair). Output: annotated as
# Structural Framing FamilyInstance with the chosen beam family/type
# and level binding.


def _rhino_to_revit_beam_executor(config: dict, inputs: dict, ctx) -> dict:
    value = inputs.get("value")
    beam_family = (config.get("beam_family") or "W-Wide Flange").strip()
    beam_type = (config.get("beam_type") or "W12X26").strip()
    level = (config.get("level") or "Level 1").strip()

    annotations = {
        "revit_target_category": "StructuralFraming",
        "revit_beam_family":     beam_family,
        "revit_beam_type":       beam_type,
        "revit_level":           level,
        "revit_structural":      True,
        "_archhub_adapter":      "rhino_to_revit_beam",
    }

    if isinstance(value, list):
        out = [_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": "StructuralFraming",
                           "beam_family": beam_family,
                           "beam_type": beam_type, "level": level}}
    return {"value": _enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": "StructuralFraming",
                       "beam_family": beam_family,
                       "beam_type": beam_type, "level": level}}


register(
    NodeSpec(
        type="adapter.rhino_to_revit_beam",
        category="adapter",
        display_name="Rhino → Revit Beam",
        description=(
            "Annotates Rhino curve(s) so the Revit receive-side "
            "creates native StructuralFraming beams. Pick the beam "
            "family, type, and host level."
        ),
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[
            Port(name="value",  type=PortType.ANY),
            Port(name="status", type=PortType.OBJECT),
        ],
        config_schema={
            "beam_family": {"type": "string", "default": "W-Wide Flange",
                              "description": "Beam family name."},
            "beam_type":   {"type": "string", "default": "W12X26",
                              "description": "Beam type within the family."},
            "level":       {"type": "string", "default": "Level 1",
                              "description": "Host level name."},
        },
        icon="━",
    ),
    _rhino_to_revit_beam_executor,
)


# ---------------------------------------------------------------------------
# adapter.excel_to_revit_params
#
# Source: a list of row dicts (e.g. from `excel.read_range`). One column
# holds the target Revit ElementId; every other column becomes a
# parameter to push on that element.
#
# Output: list of `{revit_element_id, revit_parameters}` dicts —
# consumed by `revit.batch_set_parameters` downstream.


def _excel_to_revit_params_executor(config: dict, inputs: dict,
                                      ctx) -> dict:
    value = inputs.get("value")
    id_column = (config.get("element_id_column") or "ElementId").strip()
    ignore = set(
        c.strip() for c in (config.get("ignore_columns") or "").split(",")
        if c.strip())

    def _to_param_row(row: dict) -> dict:
        # Pull the element id (accepts int or string).
        eid_raw = row.get(id_column)
        try:
            eid = int(eid_raw)
        except (TypeError, ValueError):
            eid = 0
        params = {k: v for k, v in row.items()
                  if k != id_column and k not in ignore and v is not None}
        return {
            "revit_element_id":  eid,
            "revit_parameters":  params,
            "_archhub_adapter":  "excel_to_revit_params",
            "_source_row":       row,
        }

    rows = value if isinstance(value, list) else (
        [value] if isinstance(value, dict) else [])
    out = [_to_param_row(r) for r in rows if isinstance(r, dict)]
    return {"value": out,
            "status": {"ok": True, "count": len(out),
                       "element_id_column": id_column}}


register(
    NodeSpec(
        type="adapter.excel_to_revit_params",
        category="adapter",
        display_name="Excel → Revit Parameters",
        description=(
            "Folds each Excel row into a `{revit_element_id, "
            "revit_parameters}` annotation. Downstream `revit."
            "batch_set_parameters` walks the list and pushes each "
            "row's parameters onto the named element."
        ),
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[
            Port(name="value",  type=PortType.ANY),
            Port(name="status", type=PortType.OBJECT),
        ],
        config_schema={
            "element_id_column": {"type": "string", "default": "ElementId",
                                    "description": "Column whose value is the target ElementId."},
            "ignore_columns":    {"type": "string", "default": "",
                                    "description": "Comma-separated column names to skip (e.g. 'Notes,Date')."},
        },
        icon="▦",
    ),
    _excel_to_revit_params_executor,
)
