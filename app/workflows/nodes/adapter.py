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

────────────────────────────────────────────────────────────────────────────
STEM-CELL REBUILD (wave 4) — every adapter below is now an `impl.kind=graph`
composition of EXISTING library cells (`data.passthrough` + `code.expression`
/ `code.python`), NOT a bespoke hand-written executor. The retired bespoke
`_*_executor` blobs are GONE; the live registration for each type id is the
graph executor, byte-identical to the bespoke it replaced over the full
declared output contract (`value` + `status`) on every adversarial input —
None / missing / non-list scalar / config-only (no input wire) / falsy-present
/ float / unicode — proven in `tests/test_rebuild_in_place_parity.py`.

The three patterns the bespoke adapters leant on, reproduced with the wave-4
normalization infra (no new mechanism — ONE-SYSTEM):

  • CONFIG-ONLY ENRICHMENT — the annotation values came from `config.get(x)`
    with no input wire. A subgraph only threads the facade node's *inputs*
    into the inner graph, never its *config*; so each annotation key is now a
    CONFIG-SOURCED inner seed (`inner_inputs` entry with `source: "config"` +
    `config_key: k`, seeded from the facade node's `config.get(k)` —
    app/workflows/subgraph.py, routed through `impl.kind=graph` by
    custom_nodes._graph_executor). The inner expression then reproduces the
    `(config.get(x) or default).strip()` / `float(... or ...)` / `bool(...)`
    coercion EXACTLY.

  • isinstance(value, list) SHAPE-BRANCHING — the bespoke annotated each item
    of a list, else the single value, and `status.count` = `len(out)` vs `1`.
    The inner `code.expression` reproduces the branch with
    `[enrich(it) for it in v] if isinstance(v, list) else enrich(v)`.

  • THE `_enrich` MERGE — `{**source, **annotations}` (annotation keys win, a
    dict source merges, None → `{}`, a scalar/list source → `{"_source": v}`).
    Inlined as `_ENRICH_FN` below, the literal of the retired `_enrich`.

adapter.excel_to_revit_params is the one row-FOLD (not an enrich): its bespoke
`try/except int()` + None-filtering comprehension is reproduced verbatim in a
`code.python` body (the sandbox now exposes the pure exception classes so the
literal `try/except` cooks identically — see nodes/code.py).
"""
from __future__ import annotations

from ..registry import register
from ..custom_nodes import _build_executor, _spec_from_dict


# ---------------------------------------------------------------------------
# `_enrich` as a stem-cell expression.
#
# The retired bespoke helper was:
#     if isinstance(value, dict):   merged = dict(value)
#     elif value is None:           merged = {}
#     else:                         merged = {"_source": value}
#     merged.update(annotations)    # annotation keys WIN on collision
#     return merged
# Inlined here as a lambda literal so every enrich adapter's inner graph wires
# the SAME merge — `{**source, **ann}` is exactly `dict(source)` then
# `.update(ann)` (annotation keys override), with the dict / None / scalar
# source-shaping the bespoke did. Pure, total, never raises.
_ENRICH_FN = (
    "(lambda v, ann: {**(v if isinstance(v, dict) else "
    "({} if v is None else {'_source': v})), **ann})"
)

# The list/scalar shape-branch: annotate each item of a list, else the single
# value — the bespoke's `if isinstance(value, list)` fork, byte-identical.
def _value_expr(enrich_fn: str = _ENRICH_FN) -> str:
    return (f"[{enrich_fn}(it, ann) for it in v] if isinstance(v, list) "
            f"else {enrich_fn}(v, ann)")


# ---------------------------------------------------------------------------
# Shared builder — an enrich adapter as an `impl.kind=graph` composition.
#
# Every enrich adapter (wall / directshape / max_family / detail_line / beam)
# has the SAME skeleton: a `value` passthrough fanning to the value-enrich +
# status cells, an annotation-builder cell fed by config-sourced seeds, and a
# status cell fed by `value` + (some of) the same config seeds. They differ
# ONLY in (a) the annotation expression, (b) the status expression, and (c)
# which config keys seed which cell. This builder captures the skeleton so the
# per-adapter spec is just those three differences — DRY without hiding logic.


def _register_enrich_adapter(*, type_id: str, category: str, display_name: str,
                             description: str, icon: str, config_schema: dict,
                             ann_expr: str, status_expr: str,
                             ann_seed_keys: list[str],
                             status_seed_keys: list[str]) -> dict:
    """Build + register an enrich adapter as a stem-cell graph composition.

    ann_expr      a Python expression over the `ann_seed_keys` inner ports →
                  the annotation dict (reproduces the bespoke's config coercion).
    status_expr   a Python expression over `v` (the value) + the
                  `status_seed_keys` inner ports → the `status` dict.
    ann_seed_keys / status_seed_keys
                  config keys to CONFIG-SOURCE-seed into the annotation / status
                  cell respectively (each `inner_port` is the bare key name; it
                  is seeded from the facade node's `config.get(key)`).

    Returns the spec dict (so the parity test can introspect it).
    """
    ann_ins = [{"id": k, "t": "any"} for k in ann_seed_keys]
    status_ins = ([{"id": "v", "t": "any"}]
                  + [{"id": k, "t": "any"} for k in status_seed_keys])

    inner_graph = {
        "nodes": [
            {"id": "vin", "type": "data.passthrough", "config": {},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "value", "t": "any"}]},
            {"id": "ann", "type": "code.expression",
             "config": {"expr": ann_expr},
             "ins":  ann_ins,
             "outs": [{"id": "value", "t": "any"}]},
            {"id": "gval", "type": "code.expression",
             "config": {"expr": _value_expr()},
             "ins":  [{"id": "v", "t": "any"}, {"id": "ann", "t": "any"}],
             "outs": [{"id": "value", "t": "any"}]},
            {"id": "gstatus", "type": "code.expression",
             "config": {"expr": status_expr},
             "ins":  status_ins,
             "outs": [{"id": "value", "t": "any"}]},
        ],
        "wires": [
            {"from": ["vin", "value"], "to": ["gval", "v"]},
            {"from": ["ann", "value"], "to": ["gval", "ann"]},
            {"from": ["vin", "value"], "to": ["gstatus", "v"]},
        ],
    }

    inner_inputs = [
        {"port": "value", "inner_node": "vin", "inner_port": "value",
         "type": "any"},
    ]
    # Config-sourced seeds → the annotation cell. Facade port ids are unique
    # (`<key>__ann`) so two cells reading the same config key never collide.
    for k in ann_seed_keys:
        inner_inputs.append({
            "port": f"{k}__ann", "inner_node": "ann", "inner_port": k,
            "source": "config", "config_key": k, "type": "any"})
    # Config-sourced seeds → the status cell.
    for k in status_seed_keys:
        inner_inputs.append({
            "port": f"{k}__status", "inner_node": "gstatus", "inner_port": k,
            "source": "config", "config_key": k, "type": "any"})

    inner_outputs = [
        {"port": "value", "inner_node": "gval", "inner_port": "value",
         "type": "any"},
        {"port": "status", "inner_node": "gstatus", "inner_port": "value",
         "type": "object"},
    ]

    spec = {
        "type": type_id,
        "category": category,
        "display_name": display_name,
        "description": description,
        "inputs": [{"name": "value", "type": "any"}],
        "outputs": [{"name": "value", "type": "any"},
                    {"name": "status", "type": "object"}],
        "config_schema": config_schema,
        "icon": icon,
        "impl": {
            "kind": "graph",
            "graph": inner_graph,
            "inner_inputs": inner_inputs,
            "inner_outputs": inner_outputs,
        },
    }
    node_spec = _spec_from_dict(spec)
    # The bespoke marked `value` required=True; `_spec_from_dict` defaults
    # required to False, so re-stamp it to keep the declared contract identical.
    for p in node_spec.inputs:
        if p.name == "value":
            p.required = True
    register(node_spec, _build_executor(spec, node_spec))
    return spec


# ---------------------------------------------------------------------------
# adapter.cad_to_revit_wall
#
# Bespoke:
#     level         = (config.get("level") or "Level 1").strip()
#     wall_type     = (config.get("wall_type") or "Generic - 200mm").strip()
#     height_mm     = float(config.get("height", 3000) or 3000)
#     top_offset_mm = float(config.get("top_offset", 0) or 0)
#     structural    = bool(config.get("structural", False))
# A config-sourced seed yields `config.get(k)` (None when absent), so
# `config.get("height", 3000)` is reproduced as `(height if height is not None
# else 3000)`, then `or 3000` exactly as the bespoke.
_WALL_ANN = (
    "{"
    "'revit_target_category': 'Walls', "
    "'revit_wall_type': (wall_type or 'Generic - 200mm').strip(), "
    "'revit_level': (level or 'Level 1').strip(), "
    "'revit_height_mm': float((height if height is not None else 3000) or 3000), "
    "'revit_top_offset_mm': float((top_offset if top_offset is not None else 0) or 0), "
    "'revit_structural': bool(structural), "
    "'_archhub_adapter': 'cad_to_revit_wall'"
    "}"
)
_WALL_STATUS = (
    "{'ok': True, 'count': len(v) if isinstance(v, list) else 1, "
    "'target_category': 'Walls', "
    "'level': (level or 'Level 1').strip(), "
    "'wall_type': (wall_type or 'Generic - 200mm').strip()}"
)

_WALL_SPEC = _register_enrich_adapter(
    type_id="adapter.cad_to_revit_wall",
    category="adapter",
    display_name="CAD → Revit Wall",
    description=(
        "Annotates CAD polyline(s) so the Revit receive-side creates "
        "native Wall(s). Configure level, wall type, height, and "
        "top-offset. Accepts a single polyline or a list."
    ),
    icon="◐",
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
    ann_expr=_WALL_ANN,
    status_expr=_WALL_STATUS,
    ann_seed_keys=["level", "wall_type", "height", "top_offset", "structural"],
    status_seed_keys=["level", "wall_type"],
)


# ---------------------------------------------------------------------------
# adapter.to_revit_directshape
#
# Bespoke:
#     target_category  = (config.get("target_category") or "Generic Models").strip()
#     category_name    = (config.get("category_name") or "ArchHub Direct").strip()
#     builtin_category = (config.get("builtin_category") or "OST_GenericModel").strip()
# status.target_category is the RESOLVED target_category (not the literal
# "DirectShape" that revit_target_category carries).
_DS_ANN = (
    "{"
    "'revit_target_category': 'DirectShape', "
    "'revit_directshape_category': (target_category or 'Generic Models').strip(), "
    "'revit_directshape_category_name': (category_name or 'ArchHub Direct').strip(), "
    "'revit_builtin_category': (builtin_category or 'OST_GenericModel').strip(), "
    "'_archhub_adapter': 'to_revit_directshape'"
    "}"
)
_DS_STATUS = (
    "{'ok': True, 'count': len(v) if isinstance(v, list) else 1, "
    "'target_category': (target_category or 'Generic Models').strip()}"
)

_DS_SPEC = _register_enrich_adapter(
    type_id="adapter.to_revit_directshape",
    category="adapter",
    display_name="→ Revit DirectShape",
    description=(
        "Generic fallback: annotates any geometry to be created as "
        "Revit DirectShape under the chosen built-in category. "
        "Lossy (no parametric family binding) — use a specific adapter "
        "if one exists for your source/target combo."
    ),
    icon="◇",
    config_schema={
        "target_category":  {"type": "string", "default": "Generic Models"},
        "category_name":    {"type": "string", "default": "ArchHub Direct"},
        "builtin_category": {"type": "string",
                              "default": "OST_GenericModel",
                              "description": "Revit BuiltInCategory enum value."},
    },
    ann_expr=_DS_ANN,
    status_expr=_DS_STATUS,
    ann_seed_keys=["target_category", "category_name", "builtin_category"],
    status_seed_keys=["target_category"],
)


# ---------------------------------------------------------------------------
# adapter.max_to_revit_family
#
# Bespoke:
#     target_category = (config.get("target_category") or "Mass").strip()
#     family_name     = (config.get("family_name") or "ArchHubMass").strip()
#     family_template = (config.get("family_template") or "Metric Mass.rft").strip()
#     parameters      = config.get("parameters") or {}
#     ... revit_parameters: parameters if isinstance(parameters, dict) else {}
# `parameters` is config-sourced; `config.get("parameters") or {}` then the
# isinstance-guard are reproduced verbatim in the expression.
_MAX_ANN = (
    "{"
    "'revit_target_category': (target_category or 'Mass').strip(), "
    "'revit_family_name': (family_name or 'ArchHubMass').strip(), "
    "'revit_family_template': (family_template or 'Metric Mass.rft').strip(), "
    "'revit_parameters': ((parameters or {}) "
    "if isinstance((parameters or {}), dict) else {}), "
    "'_archhub_adapter': 'max_to_revit_family'"
    "}"
)
_MAX_STATUS = (
    "{'ok': True, 'count': len(v) if isinstance(v, list) else 1, "
    "'target_category': (target_category or 'Mass').strip(), "
    "'family_name': (family_name or 'ArchHubMass').strip()}"
)

_MAX_SPEC = _register_enrich_adapter(
    type_id="adapter.max_to_revit_family",
    category="adapter",
    display_name="3ds Max → Revit Family",
    description=(
        "Annotates a 3ds Max mass/mesh so the Revit receive-side "
        "creates a native FamilyInstance under the chosen category "
        "(default Mass), bound to a family template, with the "
        "specified parameter map."
    ),
    icon="▣",
    config_schema={
        "target_category":  {"type": "string", "default": "Mass",
                              "description": "Revit category (Mass / Walls / Generic Models / …)."},
        "family_name":      {"type": "string", "default": "ArchHubMass"},
        "family_template":  {"type": "string", "default": "Metric Mass.rft",
                              "description": "Revit family template (.rft) for new families."},
        "parameters":       {"type": "object", "default": {},
                              "description": "Parameter map {revit_param_name: value_or_source_path}."},
    },
    ann_expr=_MAX_ANN,
    status_expr=_MAX_STATUS,
    ann_seed_keys=["target_category", "family_name", "family_template",
                   "parameters"],
    status_seed_keys=["target_category", "family_name"],
)


# ---------------------------------------------------------------------------
# adapter.cad_to_revit_detail_line
#
# Bespoke:
#     view_id    = config.get("view_id", 0) or 0
#     line_style = (config.get("line_style") or "Thin Lines").strip()
#     ... revit_view_id: int(view_id) if view_id else 0
# `config.get("view_id", 0) or 0` → `(view_id if view_id is not None else 0)
# or 0`. `int(view_id)` matches the bespoke for any numeric / numeric-string
# view_id; a falsy view_id short-circuits to 0 before `int()` is ever called
# (identical to the bespoke's `if view_id` guard).
_DL_ANN = (
    "{"
    "'revit_target_category': 'DetailLines', "
    "'revit_view_id': (lambda vid: int(vid) if vid else 0)"
    "((view_id if view_id is not None else 0) or 0), "
    "'revit_line_style': (line_style or 'Thin Lines').strip(), "
    "'_archhub_adapter': 'cad_to_revit_detail_line'"
    "}"
)
_DL_STATUS = (
    "{'ok': True, 'count': len(v) if isinstance(v, list) else 1, "
    "'target_category': 'DetailLines', "
    "'line_style': (line_style or 'Thin Lines').strip()}"
)

_DL_SPEC = _register_enrich_adapter(
    type_id="adapter.cad_to_revit_detail_line",
    category="adapter",
    display_name="CAD → Revit Detail Line",
    description=(
        "Annotates CAD polyline(s) so the Revit receive-side "
        "creates view-specific DetailCurve(s). Pick the target "
        "view (0 = active view) and the line style."
    ),
    icon="┄",
    config_schema={
        "view_id":    {"type": "number", "default": 0,
                        "description": "Target view ElementId; 0 = active view."},
        "line_style": {"type": "string", "default": "Thin Lines",
                        "description": "Revit line style name."},
    },
    ann_expr=_DL_ANN,
    status_expr=_DL_STATUS,
    ann_seed_keys=["view_id", "line_style"],
    status_seed_keys=["line_style"],
)


# ---------------------------------------------------------------------------
# adapter.rhino_to_revit_beam
#
# Bespoke:
#     beam_family = (config.get("beam_family") or "W-Wide Flange").strip()
#     beam_type   = (config.get("beam_type") or "W12X26").strip()
#     level       = (config.get("level") or "Level 1").strip()
#     ... revit_structural: True
_BEAM_ANN = (
    "{"
    "'revit_target_category': 'StructuralFraming', "
    "'revit_beam_family': (beam_family or 'W-Wide Flange').strip(), "
    "'revit_beam_type': (beam_type or 'W12X26').strip(), "
    "'revit_level': (level or 'Level 1').strip(), "
    "'revit_structural': True, "
    "'_archhub_adapter': 'rhino_to_revit_beam'"
    "}"
)
_BEAM_STATUS = (
    "{'ok': True, 'count': len(v) if isinstance(v, list) else 1, "
    "'target_category': 'StructuralFraming', "
    "'beam_family': (beam_family or 'W-Wide Flange').strip(), "
    "'beam_type': (beam_type or 'W12X26').strip(), "
    "'level': (level or 'Level 1').strip()}"
)

_BEAM_SPEC = _register_enrich_adapter(
    type_id="adapter.rhino_to_revit_beam",
    category="adapter",
    display_name="Rhino → Revit Beam",
    description=(
        "Annotates Rhino curve(s) so the Revit receive-side "
        "creates native StructuralFraming beams. Pick the beam "
        "family, type, and host level."
    ),
    icon="━",
    config_schema={
        "beam_family": {"type": "string", "default": "W-Wide Flange",
                          "description": "Beam family name."},
        "beam_type":   {"type": "string", "default": "W12X26",
                          "description": "Beam type within the family."},
        "level":       {"type": "string", "default": "Level 1",
                          "description": "Host level name."},
    },
    ann_expr=_BEAM_ANN,
    status_expr=_BEAM_STATUS,
    ann_seed_keys=["beam_family", "beam_type", "level"],
    status_seed_keys=["beam_family", "beam_type", "level"],
)


# ---------------------------------------------------------------------------
# adapter.excel_to_revit_params — the row-FOLD (not an enrich).
#
# Bespoke:
#     id_column = (config.get("element_id_column") or "ElementId").strip()
#     ignore = set(c.strip() for c in
#                  (config.get("ignore_columns") or "").split(",") if c.strip())
#     def _to_param_row(row):
#         eid_raw = row.get(id_column)
#         try:    eid = int(eid_raw)
#         except (TypeError, ValueError):  eid = 0
#         params = {k: v for k, v in row.items()
#                   if k != id_column and k not in ignore and v is not None}
#         return {revit_element_id, revit_parameters, _archhub_adapter, _source_row}
#     rows = value if isinstance(value, list) else
#            ([value] if isinstance(value, dict) else [])
#     out = [_to_param_row(r) for r in rows if isinstance(r, dict)]
#
# The literal `try/except int()` is reproduced in a `code.python` body — the
# sandbox now exposes the pure exception classes (nodes/code.py), so the body
# cooks byte-identically. `element_id_column` + `ignore_columns` are
# config-sourced seeds; the whole fold is one pure cell, the status its own.
_EXCEL_VALUE_BODY = (
    "id_column = (id_column_cfg or 'ElementId').strip()\n"
    "ignore = set(c.strip() for c in (ignore_columns_cfg or '').split(',') "
    "if c.strip())\n"
    "def _to_param_row(row):\n"
    "    eid_raw = row.get(id_column)\n"
    "    try:\n"
    "        eid = int(eid_raw)\n"
    "    except (TypeError, ValueError):\n"
    "        eid = 0\n"
    "    params = {k: v for k, v in row.items() "
    "if k != id_column and k not in ignore and v is not None}\n"
    "    return {'revit_element_id': eid, 'revit_parameters': params, "
    "'_archhub_adapter': 'excel_to_revit_params', '_source_row': row}\n"
    "rows = value if isinstance(value, list) else "
    "([value] if isinstance(value, dict) else [])\n"
    "result = [_to_param_row(r) for r in rows if isinstance(r, dict)]\n"
)
_EXCEL_STATUS_BODY = (
    "id_column = (id_column_cfg or 'ElementId').strip()\n"
    "rows = value if isinstance(value, list) else "
    "([value] if isinstance(value, dict) else [])\n"
    "n = len([r for r in rows if isinstance(r, dict)])\n"
    "result = {'ok': True, 'count': n, 'element_id_column': id_column}\n"
)

_EXCEL_INNER_GRAPH = {
    "nodes": [
        {"id": "vin", "type": "data.passthrough", "config": {},
         "ins":  [{"id": "value", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gval", "type": "code.python",
         "config": {"body": _EXCEL_VALUE_BODY},
         "ins":  [{"id": "value", "t": "any"},
                  {"id": "id_column_cfg", "t": "any"},
                  {"id": "ignore_columns_cfg", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
        {"id": "gstatus", "type": "code.python",
         "config": {"body": _EXCEL_STATUS_BODY},
         "ins":  [{"id": "value", "t": "any"},
                  {"id": "id_column_cfg", "t": "any"}],
         "outs": [{"id": "value", "t": "any"}]},
    ],
    "wires": [
        {"from": ["vin", "value"], "to": ["gval", "value"]},
        {"from": ["vin", "value"], "to": ["gstatus", "value"]},
    ],
}
_EXCEL_INNER_INPUTS = [
    {"port": "value", "inner_node": "vin", "inner_port": "value", "type": "any"},
    {"port": "element_id_column__val", "inner_node": "gval",
     "inner_port": "id_column_cfg", "source": "config",
     "config_key": "element_id_column", "type": "any"},
    {"port": "ignore_columns__val", "inner_node": "gval",
     "inner_port": "ignore_columns_cfg", "source": "config",
     "config_key": "ignore_columns", "type": "any"},
    {"port": "element_id_column__status", "inner_node": "gstatus",
     "inner_port": "id_column_cfg", "source": "config",
     "config_key": "element_id_column", "type": "any"},
]
_EXCEL_INNER_OUTPUTS = [
    {"port": "value", "inner_node": "gval", "inner_port": "value",
     "type": "any"},
    {"port": "status", "inner_node": "gstatus", "inner_port": "value",
     "type": "object"},
]

_EXCEL_SPEC = {
    "type": "adapter.excel_to_revit_params",
    "category": "adapter",
    "display_name": "Excel → Revit Parameters",
    "description": (
        "Folds each Excel row into a `{revit_element_id, "
        "revit_parameters}` annotation. Downstream `revit."
        "batch_set_parameters` walks the list and pushes each "
        "row's parameters onto the named element."
    ),
    "inputs": [{"name": "value", "type": "any"}],
    "outputs": [{"name": "value", "type": "any"},
                {"name": "status", "type": "object"}],
    "config_schema": {
        "element_id_column": {"type": "string", "default": "ElementId",
                                "description": "Column whose value is the target ElementId."},
        "ignore_columns":    {"type": "string", "default": "",
                                "description": "Comma-separated column names to skip (e.g. 'Notes,Date')."},
    },
    "icon": "▦",
    "impl": {
        "kind": "graph",
        "graph": _EXCEL_INNER_GRAPH,
        "inner_inputs": _EXCEL_INNER_INPUTS,
        "inner_outputs": _EXCEL_INNER_OUTPUTS,
    },
}


def _register_excel_adapter() -> None:
    node_spec = _spec_from_dict(_EXCEL_SPEC)
    for p in node_spec.inputs:
        if p.name == "value":
            p.required = True
    register(node_spec, _build_executor(_EXCEL_SPEC, node_spec))


_register_excel_adapter()
