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

The READER executors (dxf / ifc / csv) are pure-Python + stdlib by
default. ezdxf / ifcopenshell / file I/O are tried inside the executor;
absence is reported back, not crashed on. These three are IMPURE (they
read a file / import an optional native library) — NOT normalization
rebuilds — so they stay bespoke; see the SKIP note on each.

────────────────────────────────────────────────────────────────────────
WAVE-4 STEM-CELL REBUILD (in place). The SIX normalization-bearing aec
composites — qto_pricing, cost_estimate, column, revit_wall,
team_member_selector, schedule_builder — have had their bespoke
hand-written executors RETIRED and replaced IN PLACE (same registry slot,
same type id, same frozen G4 port contract) by stem-cell compositions
(`impl.kind=graph` — a typed sub-graph of EXISTING library cells). The
normalization each bespoke did is reproduced EXACTLY by the WAVE-4
infra cells, never re-handwritten:

  • `inputs.get(x) or config.get(x) or default`  →  an input-seed + a
    config-sourced seed (an `inner_inputs` entry with `source:"config"`)
    fanned through `data.coalesce` (mode="falsy" → the `x or y` idiom).
  • `if not isinstance(x, list): return {status:error}`  →  `data.ensure`
    (type="list", on_fail="error"); the subgraph engine PROPAGATES the
    inner `status:"error"` (subgraph.py), reproducing the early return.
  • the residual PURE transform (the arithmetic / format string / C#
    emission / sum-loop) is one `code.python` body cell fed the NORMALISED
    inputs, with per-declared-output `code.expression` extractor cells.

Each rebuild is proven byte-identical to its retired bespoke over its
FULL declared output contract on adversarial fixtures (None / missing /
non-list dict|str → the guard path / config-only with no input wire →
the config-fallback / falsy-present 0|""|[]|False / unicode / float) in
`tests/test_rebuild_in_place_parity.py`.

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


# ═══════════════════════════════════════════════════════════════════════
# STEM-CELL COMPOSITION HELPERS
#
# The rebuilds below are typed sub-graphs of EXISTING cells. These helpers
# only EMIT node/wire dicts (the exact shape control.if / control.merge
# hand-author) — they introduce NO new mechanism. They exist so the six
# rebuilds reproduce the SAME `inputs.get(x) or config.get(x) or default`
# normalization without re-handwriting the wiring six times (and getting
# it subtly wrong). Every node a helper emits is a registered library cell
# (data.passthrough / data.constant / data.coalesce / data.ensure /
# code.expression / code.python).
# ═══════════════════════════════════════════════════════════════════════


def _const_node(node_id: str, value) -> dict:
    """A `data.constant` source cell carrying `value` on port `value`."""
    return {"id": node_id, "type": "data.constant",
            "config": {"value": value},
            "ins": [], "outs": [{"id": "value", "t": "any"}]}


def _coalesce_node(node_id: str, mode: str = "falsy") -> dict:
    """A `data.coalesce` cell — `value if value else fallback` (falsy) or
    `value if value is not None else fallback` (none)."""
    return {"id": node_id, "type": "data.coalesce",
            "config": {"mode": mode},
            "ins": [{"id": "value", "t": "any"},
                    {"id": "fallback", "t": "any"}],
            "outs": [{"id": "value", "t": "any"}]}


def _passthrough_node(node_id: str) -> dict:
    """A `data.passthrough` identity cell (fans one facade input to many
    inner consumers — the round-1 lesson: a facade input seeds ONE inner
    port, so fan-out needs a passthrough)."""
    return {"id": node_id, "type": "data.passthrough", "config": {},
            "ins": [{"id": "value", "t": "any"}],
            "outs": [{"id": "value", "t": "any"}]}


def _input_then_config_then_default(
        field: str, *, has_config_leg: bool, default,
        nid_prefix: str):
    """Build the normalised-input fragment for ONE field.

    Reproduces (left-associative, matching Python `or`):
        inputs.get(field) or config.get(field) or default     (has_config_leg)
        inputs.get(field) or default                          (no config leg)

    Returns (nodes, wires, facade_inputs, (out_node, out_port)).

    Cells used (all existing): data.constant (the literal default),
    data.coalesce (the `or` joins), and the facade input/config seeds
    are declared in facade_inputs (the subgraph seeder fills them).
    """
    nodes: list = []
    wires: list = []
    facade: list = []

    p = nid_prefix
    # The literal default lives in a constant cell (only when a default
    # leg exists; default may legitimately be "" / 0 / [] — all falsy, so
    # we include the const whenever the bespoke had a literal default).
    const_id = f"{p}_def"
    nodes.append(_const_node(const_id, default))

    if has_config_leg:
        # config_leg = config.get(field) or default
        cfg_co = f"{p}_cfgco"
        nodes.append(_coalesce_node(cfg_co, "falsy"))
        wires.append({"from": [const_id, "value"], "to": [cfg_co, "fallback"]})
        facade.append({"port": f"cfg__{field}", "inner_node": cfg_co,
                       "inner_port": "value", "type": "any",
                       "source": "config", "config_key": field})
        # in_leg = inputs.get(field) or config_leg
        in_co = f"{p}_inco"
        nodes.append(_coalesce_node(in_co, "falsy"))
        wires.append({"from": [cfg_co, "value"], "to": [in_co, "fallback"]})
        facade.append({"port": field, "inner_node": in_co,
                       "inner_port": "value", "type": "any"})
        return nodes, wires, facade, (in_co, "value")
    else:
        # in_leg = inputs.get(field) or default
        in_co = f"{p}_inco"
        nodes.append(_coalesce_node(in_co, "falsy"))
        wires.append({"from": [const_id, "value"], "to": [in_co, "fallback"]})
        facade.append({"port": field, "inner_node": in_co,
                       "inner_port": "value", "type": "any"})
        return nodes, wires, facade, (in_co, "value")


def _register_graph_spec(spec_dict: dict, *, required: dict | None = None):
    """Register an `impl.kind=graph` spec IN PLACE through the EXACT
    machinery control.if / control.merge use
    (`custom_nodes._build_executor` dispatching on impl.kind=graph). ONE
    system — no bespoke executor, no parallel composition mechanism. The
    `custom_nodes` import is deferred (it imports `nodes.code`; importing
    at module top would re-enter the `nodes` package mid-load), mirroring
    control.py's `_register_if_node`.

    `required` re-stamps the `required` flag on named input ports
    (`_spec_from_dict` defaults it False) so the declared contract stays
    byte-identical to the retired bespoke's NodeSpec.
    """
    from ..custom_nodes import _build_executor, _spec_from_dict

    node_spec = _spec_from_dict(spec_dict)
    if required:
        for p in node_spec.inputs:
            if required.get(p.name):
                p.required = True
    register(node_spec, _build_executor(spec_dict, node_spec))
    return node_spec


# ---------------------------------------------------------------------------
# 1. DXF Reader — parse a .dwg/.dxf and return layers + entity count.
#
# SKIP (impure — NOT a normalization rebuild): this executor READS A FILE
# (`ezdxf.readfile(path)`) and imports the optional native `ezdxf`
# library. Its behaviour depends on the filesystem + an external package,
# not on pure input/config normalization, so it has no stem-cell
# composition that could be byte-identical to it. It correctly stays
# bespoke. (The WAVE-4 infra reproduces falsy/None/config/type-guard
# normalization — not file I/O.)
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
#
# SKIP (impure — NOT a normalization rebuild): reads a file
# (`ifcopenshell.open(path)`) + imports the optional native `ifcopenshell`
# library. Filesystem + external-package dependent, no pure composition —
# stays bespoke, correctly.
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
#
# SKIP (impure — NOT a normalization rebuild): reads a file
# (`open(path)` + `csv.DictReader`). Filesystem-dependent — no pure
# composition is byte-identical to it. Stays bespoke, correctly.
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


# ═══════════════════════════════════════════════════════════════════════
# 4. aec.revit_wall — IN-PLACE STEM-CELL REBUILD (impl.kind=graph).
#
# Retired bespoke (frozen as the oracle in the parity test):
#     length_mm = float(inputs.get("length_mm") or config.get("length_mm") or 3000)
#     height_mm = float(inputs.get("height_mm") or config.get("height_mm") or 2700)
#     width_mm  = float(inputs.get("width_mm")  or config.get("width_mm")  or 200)
#     level     = (inputs.get("level") or config.get("level") or "Level 1").strip()
#     wall_type = (inputs.get("wall_type") or config.get("wall_type") or "Generic - 200mm").strip()
#     <emit C# from the five values>  → {csharp, length_mm, height_mm, ...}
#
# Pure: NO file/LLM/host — just `float(...)` coercion, `.strip()`, and an
# f-string + json.dumps C# emission. The normalization is FIVE
# `inputs.get(x) or config.get(x) or default` chains → reproduced by five
# `_fallback_chain` fragments (input-seed + config-seed → coalesce). The
# residual pure transform (float-coerce + strip + C# build) is one
# `code.python` body, exposed per declared output by `code.expression`
# extractors. Declared output ports: csharp / length_mm / height_mm.
# ═══════════════════════════════════════════════════════════════════════

# The C# body — verbatim from the retired bespoke (same f-string, same
# json.dumps quoting, same /304.8 conversions). Runs in the code.python
# sandbox with safe_mode=False (json import). The five inputs arrive
# already normalised (the coalesce chains did `inputs.get or config.get
# or default`); the body only float-coerces + strips + emits, exactly as
# the bespoke's tail did.
_REVIT_WALL_BODY = r'''
import json as _json
length_mm = float(length_mm)
height_mm = float(height_mm)
width_mm = float(width_mm)
level = str(level).strip()
wall_type = str(wall_type).strip()
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
result = {"csharp": csharp, "length_mm": length_mm,
          "height_mm": height_mm, "width_mm": width_mm,
          "level": level, "wall_type": wall_type}
'''


def _build_revit_wall_graph() -> dict:
    nodes: list = []
    wires: list = []
    facade_in: list = []
    body_inputs: dict = {}   # body inner-port -> (src_node, src_port)

    fields = [
        ("length_mm", 3000), ("height_mm", 2700), ("width_mm", 200),
        ("level", "Level 1"), ("wall_type", "Generic - 200mm"),
    ]
    for field, default in fields:
        fn, fw, ff, (out_node, out_port) = _input_then_config_then_default(
            field, has_config_leg=True, default=default, nid_prefix=field)
        nodes += fn
        wires += fw
        facade_in += ff
        body_inputs[field] = (out_node, out_port)

    # The pure body cell — fed the five NORMALISED values.
    body_ins = [{"id": k, "t": "any"} for k in body_inputs]
    nodes.append({"id": "body", "type": "code.python",
                  "config": {"body": _REVIT_WALL_BODY, "safe_mode": False},
                  "ins": body_ins, "outs": [{"id": "value", "t": "any"}]})
    for inner_port, (src_node, src_port) in body_inputs.items():
        wires.append({"from": [src_node, src_port], "to": ["body", inner_port]})

    # Per-declared-output extractor cells (index the body's result dict).
    out_ports = [("csharp", "string"), ("length_mm", "number"),
                 ("height_mm", "number")]
    facade_out: list = []
    for port, ptype in out_ports:
        ex_id = f"x_{port}"
        nodes.append({"id": ex_id, "type": "code.expression",
                      "config": {"expr": f"d[{port!r}]"},
                      "ins": [{"id": "d", "t": "any"}],
                      "outs": [{"id": "value", "t": "any"}]})
        wires.append({"from": ["body", "value"], "to": [ex_id, "d"]})
        facade_out.append({"port": port, "inner_node": ex_id,
                           "inner_port": "value", "type": ptype})

    return {"nodes": nodes, "wires": wires,
            "inner_inputs": facade_in, "inner_outputs": facade_out}


_REVIT_WALL_IMPL = _build_revit_wall_graph()

_REVIT_WALL_SPEC = {
    "type": "aec.revit_wall",
    "category": "aec.revit",
    "display_name": "Revit Wall",
    "description": "Emit a wall-creation C# snippet. Pipe into revit_execute_csharp.",
    "inputs": [
        {"name": "length_mm", "type": "number"},
        {"name": "height_mm", "type": "number"},
        {"name": "width_mm",  "type": "number"},
        {"name": "level",     "type": "string"},
        {"name": "wall_type", "type": "string"},
    ],
    "outputs": [
        {"name": "csharp",    "type": "string"},
        {"name": "length_mm", "type": "number"},
        {"name": "height_mm", "type": "number"},
    ],
    "config_schema": {
        "length_mm": {"type": "number", "default": 3000},
        "height_mm": {"type": "number", "default": 2700},
        "width_mm":  {"type": "number", "default": 200},
        "level":     {"type": "string", "default": "Level 1"},
        "wall_type": {"type": "string", "default": "Generic - 200mm"},
    },
    "icon": "▐",
    "impl": {
        "kind": "graph",
        "graph": {"nodes": _REVIT_WALL_IMPL["nodes"],
                  "wires": _REVIT_WALL_IMPL["wires"]},
        "inner_inputs": _REVIT_WALL_IMPL["inner_inputs"],
        "inner_outputs": _REVIT_WALL_IMPL["inner_outputs"],
    },
}

_register_graph_spec(_REVIT_WALL_SPEC)


# ═══════════════════════════════════════════════════════════════════════
# 5. aec.column — IN-PLACE STEM-CELL REBUILD (impl.kind=graph).
#
# Retired bespoke:
#     section   = (inputs.get("section") or config.get("section") or "300x300").strip()
#     height_mm = float(inputs.get("height_mm") or config.get("height_mm") or 3000)
#     material  = (inputs.get("material") or config.get("material") or "Concrete").strip()
#     try: w_mm, h_mm = [float(p) for p in section.replace("x","X").split("X")[:2]]
#     except Exception: return {"status":"error", "error": "section ... must be WxH"}
#     volume_m3 = (w/1000)*(h/1000)*(height/1000)  → {volume_m3, width_mm, depth_mm, ...}
#
# Pure: three `inputs.get(x) or config.get(x) or default` chains + a
# section-parse that on malformed input returns status:error (an EARLY
# return). The rebuild reproduces the normalization with three coalesce
# chains; the parse+volume body is a `code.python` cell that RAISES on a
# malformed section — the runner wraps the exception → the subgraph
# returns status:error, reproducing the bespoke early return EXACTLY (same
# trigger: section not parseable as WxH; same effect: status:error, no
# declared outputs). Declared ports: volume_m3 / width_mm / depth_mm.
# ═══════════════════════════════════════════════════════════════════════
_COLUMN_BODY = r'''
section = str(section).strip()
height_mm = float(height_mm)
material = str(material).strip()
parts = section.replace("x", "X").split("X")[:2]
nums = [float(p) for p in parts]
w_mm, h_mm = nums[0], nums[1]
volume_m3 = (w_mm / 1000) * (h_mm / 1000) * (height_mm / 1000)
result = {"section": section, "height_mm": height_mm, "material": material,
          "width_mm": w_mm, "depth_mm": h_mm,
          "volume_m3": round(volume_m3, 4)}
'''


def _build_column_graph() -> dict:
    nodes: list = []
    wires: list = []
    facade_in: list = []
    body_inputs: dict = {}

    for field, default in [("section", "300x300"), ("height_mm", 3000),
                           ("material", "Concrete")]:
        fn, fw, ff, endpoint = _input_then_config_then_default(
            field, has_config_leg=True, default=default, nid_prefix=field)
        nodes += fn
        wires += fw
        facade_in += ff
        body_inputs[field] = endpoint

    body_ins = [{"id": k, "t": "any"} for k in body_inputs]
    nodes.append({"id": "body", "type": "code.python",
                  "config": {"body": _COLUMN_BODY, "safe_mode": False},
                  "ins": body_ins, "outs": [{"id": "value", "t": "any"}]})
    for inner_port, (src_node, src_port) in body_inputs.items():
        wires.append({"from": [src_node, src_port], "to": ["body", inner_port]})

    facade_out: list = []
    for port in ("volume_m3", "width_mm", "depth_mm"):
        ex_id = f"x_{port}"
        nodes.append({"id": ex_id, "type": "code.expression",
                      "config": {"expr": f"d[{port!r}]"},
                      "ins": [{"id": "d", "t": "any"}],
                      "outs": [{"id": "value", "t": "any"}]})
        wires.append({"from": ["body", "value"], "to": [ex_id, "d"]})
        facade_out.append({"port": port, "inner_node": ex_id,
                           "inner_port": "value", "type": "number"})

    return {"nodes": nodes, "wires": wires,
            "inner_inputs": facade_in, "inner_outputs": facade_out}


_COLUMN_IMPL = _build_column_graph()

_COLUMN_SPEC = {
    "type": "aec.column",
    "category": "aec.parts",
    "display_name": "Column",
    "description": "Structural column. Computes volume from section + height.",
    "inputs": [
        {"name": "section",   "type": "string"},
        {"name": "height_mm", "type": "number"},
        {"name": "material",  "type": "string"},
    ],
    "outputs": [
        {"name": "volume_m3", "type": "number"},
        {"name": "width_mm",  "type": "number"},
        {"name": "depth_mm",  "type": "number"},
    ],
    "config_schema": {
        "section":   {"type": "string", "default": "300x300"},
        "height_mm": {"type": "number", "default": 3000},
        "material":  {"type": "string", "default": "Concrete"},
    },
    "icon": "█",
    "impl": {
        "kind": "graph",
        "graph": {"nodes": _COLUMN_IMPL["nodes"], "wires": _COLUMN_IMPL["wires"]},
        "inner_inputs": _COLUMN_IMPL["inner_inputs"],
        "inner_outputs": _COLUMN_IMPL["inner_outputs"],
    },
}

_register_graph_spec(_COLUMN_SPEC)


# ═══════════════════════════════════════════════════════════════════════
# 6. aec.qto_pricing — IN-PLACE STEM-CELL REBUILD (impl.kind=graph).
#
# Retired bespoke:
#     quantity   = float(inputs.get("quantity") or 0)
#     unit_price = float(inputs.get("unit_price") or config.get("unit_price") or 0)
#     currency   = (inputs.get("currency") or config.get("currency") or "AED").strip()
#     line_item  = (inputs.get("line_item") or config.get("line_item") or "").strip()
#     line_total = round(quantity * unit_price, 2)
#     formatted  = f"{line_item}: {quantity:.2f} × {unit_price:.2f} {currency} = ..."
#
# Pure. `quantity` is `inputs.get(x) or 0` (NO config leg); the other three
# are `inputs.get(x) or config.get(x) or default`. The body float-coerces
# quantity+unit_price (a non-numeric string → ValueError → subgraph
# status:error, same as the bespoke crash) and builds line_total +
# formatted. Declared ports: line_total / formatted.
# ═══════════════════════════════════════════════════════════════════════
_QTO_BODY = r'''
quantity = float(quantity)
unit_price = float(unit_price)
currency = str(currency).strip()
line_item = str(line_item).strip()
line_total = round(quantity * unit_price, 2)
formatted = f"{line_item}: {quantity:.2f} × {unit_price:.2f} {currency} = {line_total:.2f} {currency}"
result = {"line_total": line_total, "formatted": formatted}
'''


def _build_qto_graph() -> dict:
    nodes: list = []
    wires: list = []
    facade_in: list = []
    body_inputs: dict = {}

    # quantity — inputs.get(x) or 0  (NO config leg)
    fn, fw, ff, endpoint = _input_then_config_then_default(
        "quantity", has_config_leg=False, default=0, nid_prefix="quantity")
    nodes += fn; wires += fw; facade_in += ff
    body_inputs["quantity"] = endpoint

    # the three with a config leg
    for field, default in [("unit_price", 0), ("currency", "AED"),
                           ("line_item", "")]:
        fn, fw, ff, endpoint = _input_then_config_then_default(
            field, has_config_leg=True, default=default, nid_prefix=field)
        nodes += fn; wires += fw; facade_in += ff
        body_inputs[field] = endpoint

    body_ins = [{"id": k, "t": "any"} for k in body_inputs]
    nodes.append({"id": "body", "type": "code.python",
                  "config": {"body": _QTO_BODY, "safe_mode": False},
                  "ins": body_ins, "outs": [{"id": "value", "t": "any"}]})
    for inner_port, (src_node, src_port) in body_inputs.items():
        wires.append({"from": [src_node, src_port], "to": ["body", inner_port]})

    facade_out: list = []
    for port, ptype in [("line_total", "number"), ("formatted", "string")]:
        ex_id = f"x_{port}"
        nodes.append({"id": ex_id, "type": "code.expression",
                      "config": {"expr": f"d[{port!r}]"},
                      "ins": [{"id": "d", "t": "any"}],
                      "outs": [{"id": "value", "t": "any"}]})
        wires.append({"from": ["body", "value"], "to": [ex_id, "d"]})
        facade_out.append({"port": port, "inner_node": ex_id,
                           "inner_port": "value", "type": ptype})

    return {"nodes": nodes, "wires": wires,
            "inner_inputs": facade_in, "inner_outputs": facade_out}


_QTO_IMPL = _build_qto_graph()

_QTO_SPEC = {
    "type": "aec.qto_pricing",
    "category": "aec.qto",
    "display_name": "QTO Pricing",
    "description": "Multiply quantity × unit price to get a line total.",
    "inputs": [
        {"name": "quantity",   "type": "number"},
        {"name": "unit_price", "type": "number"},
        {"name": "line_item",  "type": "string"},
    ],
    "outputs": [
        {"name": "line_total", "type": "number"},
        {"name": "formatted",  "type": "string"},
    ],
    "config_schema": {
        "unit_price": {"type": "number", "default": 0},
        "currency":   {"type": "string", "default": "AED"},
        "line_item":  {"type": "string", "default": ""},
    },
    "icon": "¤",
    "impl": {
        "kind": "graph",
        "graph": {"nodes": _QTO_IMPL["nodes"], "wires": _QTO_IMPL["wires"]},
        "inner_inputs": _QTO_IMPL["inner_inputs"],
        "inner_outputs": _QTO_IMPL["inner_outputs"],
    },
}

_register_graph_spec(_QTO_SPEC)


# ═══════════════════════════════════════════════════════════════════════
# 7. aec.cost_estimate — IN-PLACE STEM-CELL REBUILD (impl.kind=graph).
#
# Retired bespoke:
#     items = inputs.get("items") or []
#     if not isinstance(items, list): return {"status":"error", "error":"items must be an array"}
#     currency = (inputs.get("currency") or config.get("currency") or "AED").strip()
#     total = sum(float(it.get("line_total") or it.get("total") or 0) for dict it; float(it) for scalar)
#     → {grand_total, formatted, item_count, ...}
#
# Note the SUBTLE order: `items = inputs.get("items") or []` runs FIRST
# (falsy-coalesce), THEN `isinstance` guards. So a FALSY non-list (0, "",
# {}, False) is coalesced to [] and PASSES the guard (0 items); only a
# TRUTHY non-list (a non-empty dict / non-empty string / a number) hits
# the isinstance→error path. The rebuild mirrors this order EXACTLY:
#     items  ── coalesce(falsy, fallback=[]) ──> data.ensure(list, error) ──> body
# so the ensure guard sees the ALREADY-coalesced value (post `or []`),
# reproducing the bespoke's coalesce-then-guard sequence. Declared ports:
# grand_total / formatted.
# ═══════════════════════════════════════════════════════════════════════
_COST_BODY = r'''
currency = str(currency).strip()
total = 0.0
for it in items:
    if isinstance(it, dict):
        v = it.get("line_total")
        if not v:
            v = it.get("total")
        if not v:
            v = 0
    else:
        v = it
    try:
        total = total + float(v)
    except (TypeError, ValueError):
        pass
grand_total = round(total, 2)
formatted = f"{len(items)} items · {total:,.2f} {currency}"
result = {"grand_total": grand_total, "formatted": formatted,
          "item_count": len(items)}
'''


def _build_cost_estimate_graph() -> dict:
    nodes: list = []
    wires: list = []
    facade_in: list = []

    # items = inputs.get("items") or []   (falsy-coalesce, no config leg)
    nodes.append(_const_node("items_def", []))
    nodes.append(_coalesce_node("items_co", "falsy"))
    wires.append({"from": ["items_def", "value"], "to": ["items_co", "fallback"]})
    facade_in.append({"port": "items", "inner_node": "items_co",
                      "inner_port": "value", "type": "any"})
    # ── THEN guard: data.ensure(list, on_fail=error) over the coalesced value.
    nodes.append({"id": "items_guard", "type": "data.ensure",
                  "config": {"type": "list", "on_fail": "error"},
                  "ins": [{"id": "value", "t": "any"}],
                  "outs": [{"id": "value", "t": "any"}]})
    wires.append({"from": ["items_co", "value"], "to": ["items_guard", "value"]})

    # currency = inputs.get or config.get or "AED"
    cn, cw, cf, currency_ep = _input_then_config_then_default(
        "currency", has_config_leg=True, default="AED", nid_prefix="currency")
    nodes += cn; wires += cw; facade_in += cf

    nodes.append({"id": "body", "type": "code.python",
                  "config": {"body": _COST_BODY, "safe_mode": False},
                  "ins": [{"id": "items", "t": "any"},
                          {"id": "currency", "t": "any"}],
                  "outs": [{"id": "value", "t": "any"}]})
    wires.append({"from": ["items_guard", "value"], "to": ["body", "items"]})
    wires.append({"from": [currency_ep[0], currency_ep[1]], "to": ["body", "currency"]})

    facade_out: list = []
    for port, ptype in [("grand_total", "number"), ("formatted", "string")]:
        ex_id = f"x_{port}"
        nodes.append({"id": ex_id, "type": "code.expression",
                      "config": {"expr": f"d[{port!r}]"},
                      "ins": [{"id": "d", "t": "any"}],
                      "outs": [{"id": "value", "t": "any"}]})
        wires.append({"from": ["body", "value"], "to": [ex_id, "d"]})
        facade_out.append({"port": port, "inner_node": ex_id,
                           "inner_port": "value", "type": ptype})

    return {"nodes": nodes, "wires": wires,
            "inner_inputs": facade_in, "inner_outputs": facade_out}


_COST_IMPL = _build_cost_estimate_graph()

_COST_SPEC = {
    "type": "aec.cost_estimate",
    "category": "aec.qto",
    "display_name": "Cost Estimate",
    "description": "Sum a list of priced items to get a grand total.",
    "inputs": [{"name": "items", "type": "list"}],
    "outputs": [
        {"name": "grand_total", "type": "number"},
        {"name": "formatted",   "type": "string"},
    ],
    "config_schema": {
        "currency": {"type": "string", "default": "AED"},
    },
    "icon": "Σ",
    "impl": {
        "kind": "graph",
        "graph": {"nodes": _COST_IMPL["nodes"], "wires": _COST_IMPL["wires"]},
        "inner_inputs": _COST_IMPL["inner_inputs"],
        "inner_outputs": _COST_IMPL["inner_outputs"],
    },
}

_register_graph_spec(_COST_SPEC, required={"items": False})


# ═══════════════════════════════════════════════════════════════════════
# 8. aec.schedule_builder — IN-PLACE STEM-CELL REBUILD (impl.kind=graph).
#   (The round-1 node — REFUTED then because the infra didn't exist. NOW
#    rebuildable: `rows or []`, `columns or config.get('columns') or []`,
#    and the isinstance→error guard all have a WAVE-4 cell.)
#
# Retired bespoke:
#     rows    = inputs.get("rows") or []
#     columns = inputs.get("columns") or config.get("columns") or []
#     if not isinstance(rows, list) or not isinstance(columns, list):
#         return {"status":"error", "error":"rows + columns must be arrays"}
#     title = (inputs.get("title") or config.get("title") or "Schedule").strip()
#     → {title, columns, row_count, rows}
#
# SUBTLE order (same as cost_estimate): the `or []` coalesce runs BEFORE
# the isinstance guard, so a FALSY non-list rows/columns is coalesced to []
# and passes; only a TRUTHY non-list errors. The rebuild mirrors it:
#     rows    ── coalesce(falsy,[]) ── ensure(list,error) ──┐
#     columns ── coalesce or-chain ── ensure(list,error) ──┤→ body
# Declared ports: rows / columns / row_count.
# ═══════════════════════════════════════════════════════════════════════
_SCHEDULE_BODY = r'''
title = str(title).strip()
result = {"title": title, "columns": columns, "row_count": len(rows),
          "rows": rows}
'''


def _guard_list_after_coalesce(nodes, wires, facade_in, *, field,
                               has_config_leg, nid_prefix):
    """rows/columns share the shape: `inputs.get(f) [or config.get(f)] or
    []` THEN `isinstance(list) else error`. Emits the coalesce chain (via
    `_input_then_config_then_default` with default=[]) then a
    `data.ensure(list, error)` over its output. Returns the guard's
    (node, port) endpoint."""
    fn, fw, ff, (co_node, co_port) = _input_then_config_then_default(
        field, has_config_leg=has_config_leg, default=[],
        nid_prefix=nid_prefix)
    nodes += fn; wires += fw; facade_in += ff
    guard_id = f"{nid_prefix}_guard"
    nodes.append({"id": guard_id, "type": "data.ensure",
                  "config": {"type": "list", "on_fail": "error"},
                  "ins": [{"id": "value", "t": "any"}],
                  "outs": [{"id": "value", "t": "any"}]})
    wires.append({"from": [co_node, co_port], "to": [guard_id, "value"]})
    return (guard_id, "value")


def _build_schedule_graph() -> dict:
    nodes: list = []
    wires: list = []
    facade_in: list = []

    rows_ep = _guard_list_after_coalesce(
        nodes, wires, facade_in, field="rows",
        has_config_leg=False, nid_prefix="rows")
    cols_ep = _guard_list_after_coalesce(
        nodes, wires, facade_in, field="columns",
        has_config_leg=True, nid_prefix="columns")

    # title = inputs.get or config.get or "Schedule"
    tn, tw, tf, title_ep = _input_then_config_then_default(
        "title", has_config_leg=True, default="Schedule", nid_prefix="title")
    nodes += tn; wires += tw; facade_in += tf

    nodes.append({"id": "body", "type": "code.python",
                  "config": {"body": _SCHEDULE_BODY, "safe_mode": False},
                  "ins": [{"id": "rows", "t": "any"},
                          {"id": "columns", "t": "any"},
                          {"id": "title", "t": "any"}],
                  "outs": [{"id": "value", "t": "any"}]})
    wires.append({"from": [rows_ep[0], rows_ep[1]], "to": ["body", "rows"]})
    wires.append({"from": [cols_ep[0], cols_ep[1]], "to": ["body", "columns"]})
    wires.append({"from": [title_ep[0], title_ep[1]], "to": ["body", "title"]})

    facade_out: list = []
    for port, ptype in [("rows", "list"), ("columns", "list"),
                        ("row_count", "number")]:
        ex_id = f"x_{port}"
        nodes.append({"id": ex_id, "type": "code.expression",
                      "config": {"expr": f"d[{port!r}]"},
                      "ins": [{"id": "d", "t": "any"}],
                      "outs": [{"id": "value", "t": "any"}]})
        wires.append({"from": ["body", "value"], "to": [ex_id, "d"]})
        facade_out.append({"port": port, "inner_node": ex_id,
                           "inner_port": "value", "type": ptype})

    return {"nodes": nodes, "wires": wires,
            "inner_inputs": facade_in, "inner_outputs": facade_out}


_SCHEDULE_IMPL = _build_schedule_graph()

_SCHEDULE_SPEC = {
    "type": "aec.schedule_builder",
    "category": "aec.qto",
    "display_name": "Schedule Builder",
    "description": "Collect rows + columns into a schedule spec.",
    "inputs": [
        {"name": "rows",    "type": "list"},
        {"name": "columns", "type": "list"},
        {"name": "title",   "type": "string"},
    ],
    "outputs": [
        {"name": "rows",      "type": "list"},
        {"name": "columns",   "type": "list"},
        {"name": "row_count", "type": "number"},
    ],
    "config_schema": {
        "title":   {"type": "string", "default": "Schedule"},
        "columns": {"type": "array",  "default": []},
    },
    "icon": "≣",
    "impl": {
        "kind": "graph",
        "graph": {"nodes": _SCHEDULE_IMPL["nodes"], "wires": _SCHEDULE_IMPL["wires"]},
        "inner_inputs": _SCHEDULE_IMPL["inner_inputs"],
        "inner_outputs": _SCHEDULE_IMPL["inner_outputs"],
    },
}

_register_graph_spec(_SCHEDULE_SPEC)


# ═══════════════════════════════════════════════════════════════════════
# 9. aec.team_member_selector — IN-PLACE STEM-CELL REBUILD (impl.kind=graph).
#
# Retired bespoke:
#     roster = inputs.get("roster") or config.get("roster") or []
#     if not isinstance(roster, list): return {"status":"error", "error":"roster must be an array"}
#     role = (inputs.get("role") or config.get("role") or "").strip().lower()
#     picks = [m for m in roster if isinstance(m,dict) and (m.get("role") or "").strip().lower()==role] if role else list(roster)
#     → {role_filter, members, count}
#
# SUBTLE order (same family): `roster or config or []` coalesce FIRST, THEN
# isinstance guard — a FALSY non-list roster → [] → passes; a TRUTHY
# non-list → error. The rebuild:
#     roster ── coalesce-or-chain(default=[]) ── ensure(list,error) ──┐
#     role   ── coalesce-or-chain(default="")                         ┤→ body
# Declared ports: members / count.
# ═══════════════════════════════════════════════════════════════════════
_TEAM_BODY = r'''
role = str(role).strip().lower()
if role:
    picks = [m for m in roster
             if isinstance(m, dict)
             and str(m.get("role") or "").strip().lower() == role]
else:
    picks = list(roster)
result = {"role_filter": role, "members": picks, "count": len(picks)}
'''


def _build_team_graph() -> dict:
    nodes: list = []
    wires: list = []
    facade_in: list = []

    roster_ep = _guard_list_after_coalesce(
        nodes, wires, facade_in, field="roster",
        has_config_leg=True, nid_prefix="roster")

    rn, rw, rf, role_ep = _input_then_config_then_default(
        "role", has_config_leg=True, default="", nid_prefix="role")
    nodes += rn; wires += rw; facade_in += rf

    nodes.append({"id": "body", "type": "code.python",
                  "config": {"body": _TEAM_BODY, "safe_mode": False},
                  "ins": [{"id": "roster", "t": "any"},
                          {"id": "role", "t": "any"}],
                  "outs": [{"id": "value", "t": "any"}]})
    wires.append({"from": [roster_ep[0], roster_ep[1]], "to": ["body", "roster"]})
    wires.append({"from": [role_ep[0], role_ep[1]], "to": ["body", "role"]})

    facade_out: list = []
    for port, ptype in [("members", "list"), ("count", "number")]:
        ex_id = f"x_{port}"
        nodes.append({"id": ex_id, "type": "code.expression",
                      "config": {"expr": f"d[{port!r}]"},
                      "ins": [{"id": "d", "t": "any"}],
                      "outs": [{"id": "value", "t": "any"}]})
        wires.append({"from": ["body", "value"], "to": [ex_id, "d"]})
        facade_out.append({"port": port, "inner_node": ex_id,
                           "inner_port": "value", "type": ptype})

    return {"nodes": nodes, "wires": wires,
            "inner_inputs": facade_in, "inner_outputs": facade_out}


_TEAM_IMPL = _build_team_graph()

_TEAM_SPEC = {
    "type": "aec.team_member_selector",
    "category": "aec.team",
    "display_name": "Team Member Selector",
    "description": "Filter a roster by role. Returns matching members.",
    "inputs": [
        {"name": "roster", "type": "list"},
        {"name": "role",   "type": "string"},
    ],
    "outputs": [
        {"name": "members", "type": "list"},
        {"name": "count",   "type": "number"},
    ],
    "config_schema": {
        "role":   {"type": "string", "default": ""},
        "roster": {"type": "array",  "default": []},
    },
    "icon": "◍",
    "impl": {
        "kind": "graph",
        "graph": {"nodes": _TEAM_IMPL["nodes"], "wires": _TEAM_IMPL["wires"]},
        "inner_inputs": _TEAM_IMPL["inner_inputs"],
        "inner_outputs": _TEAM_IMPL["inner_outputs"],
    },
}

_register_graph_spec(_TEAM_SPEC)
