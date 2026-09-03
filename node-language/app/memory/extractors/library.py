"""Library extractor — library + registry → MemoryGraph nodes/edges.

AgDR-0042 slice 2/6.

Emits three node kinds and two edge relations:

  kind=capability — every registry NodeSpec + every library Capability
                    that is NOT a composite Skill. Id: `lib:cap:<type>`.
  kind=skill      — every library Capability whose type starts with
                    `skill.` (the impl.kind=graph composites). Id:
                    `lib:skill:<type>`. Props carry display_name +
                    side_effects + category.
  relation=contains — skill → capability. Emitted for each inner
                      node inside the skill's impl.graph. Confidence:
                      EXTRACTED (the graph walks the actual spec).
  relation=wires_with — capability ↔ capability. INFERRED edge between
                        a cap whose output port type matches another
                        cap's input port type. Bidirectional, but only
                        emitted once per ordered pair (src→dst) so the
                        graph isn't doubled. Skips the trivial ANY-ANY
                        cases (too noisy — every node would link).

Hooks into MemoryGraph batch ops so a fresh extraction across the
default library (~80 caps) commits in a single SQLite transaction.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

# Local app import — extractor lives under app/memory/extractors/library.py
_APP = Path(__file__).resolve().parents[2]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from memory.graph import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence,
)


# ── node id helpers ──────────────────────────────────────────────────


def _cap_id(type_name: str) -> str:
    return f"lib:cap:{type_name}"


def _skill_id(type_name: str) -> str:
    return f"lib:skill:{type_name}"


def _is_skill_type(type_name: str) -> bool:
    return isinstance(type_name, str) and type_name.startswith("skill.")


# ── library walkers ──────────────────────────────────────────────────


def _library_items() -> list[dict]:
    """Library Capability summaries — every disk-saved spec. May raise
    if library isn't initialised (caller catches)."""
    try:
        import library as _lib
        return _lib.list_node_types(category=None) or []
    except Exception:
        return []


def _library_full(type_name: str) -> dict:
    """Full library spec for one type — None on miss / library missing.

    NOTE: library's Pydantic ModularNodeSpec strips fields it doesn't
    know about (in particular `impl`, which AgDR-0040 introduced AFTER
    the library schema). So this dict is the *summary* shape; the full
    impl is recovered separately via `_skill_source_spec`."""
    try:
        import library as _lib
        return _lib.inspect(type_name) or {}
    except Exception:
        return {}


# Map shipped Skill type → source-module `_build_spec` callable. Source
# modules ship the FULL spec (incl. impl.kind=graph + inner graph) which
# the library stripped on registration. Used to recover the contains
# edges for slice 2.
def _skill_source_specs() -> dict:
    """{skill_type: full_spec_dict} for every shipped Skill. Empty on
    import failure so the rest of extraction still runs cleanly."""
    out: dict = {}
    try:
        from workflows.skills import (  # noqa: F401
            revit_to_render, photo_to_rhino_mass, drone_to_revit_walls,
        )
        for mod in (revit_to_render, photo_to_rhino_mass, drone_to_revit_walls):
            try:
                spec = mod._build_spec()
                t = spec.get("type", "")
                if t:
                    out[t] = spec
            except Exception:
                continue
    except Exception:
        pass
    return out


def _registry_items() -> list:
    """Registry NodeSpecs — typed primitives shipped in-process."""
    try:
        # Auto-import workflows package so registry is populated.
        import workflows  # noqa: F401
        from workflows import registry as _reg
        return list(_reg.all_specs())
    except Exception:
        return []


# ── port-type compatibility helpers ──────────────────────────────────


def _norm_port_type(t) -> str:
    """Lower-case string of a port-type marker. Accepts PortType enum,
    string, or None; ANY falls through unchanged so the wires_with
    filter can skip it."""
    if t is None:
        return "any"
    name = getattr(t, "name", None) or getattr(t, "value", None) or t
    return str(name).lower()


def _cap_io(spec) -> tuple[list[str], list[str]]:
    """Lower-case port-type lists for a NodeSpec OR a library Capability
    dict. Tolerates both shapes (registry NodeSpec.inputs[].type vs
    library inputs[].port_type)."""
    # Registry NodeSpec — has .inputs / .outputs of Port objects.
    if hasattr(spec, "inputs") and hasattr(spec, "outputs"):
        ins = [_norm_port_type(getattr(p, "type", None)) for p in spec.inputs]
        outs = [_norm_port_type(getattr(p, "type", None)) for p in spec.outputs]
        return ins, outs
    # Library dict — inputs/outputs lists with `port_type` field.
    ins = [_norm_port_type(p.get("port_type") or p.get("type"))
           for p in (spec.get("inputs") or [])]
    outs = [_norm_port_type(p.get("port_type") or p.get("type"))
            for p in (spec.get("outputs") or [])]
    return ins, outs


# ── main entry ───────────────────────────────────────────────────────


def extract_library(graph: MemoryGraph,
                     *, infer_wires: bool = True) -> dict:
    """Walk the library + registry and write Capability / Skill nodes
    + contains / wires_with edges into the graph.

    Idempotent — re-running upserts everything in place.

    Args:
      graph        — open MemoryGraph (in-memory or on-disk).
      infer_wires  — emit INFERRED `wires_with` edges between caps
                     whose port types match. Set False on large
                     libraries if the O(N²) walk becomes hot (slice 5
                     Louvain pass replaces this with cheaper community
                     detection). Default True at our scale.

    Returns counts: {nodes_added, edges_added}.
    """
    nodes: list[MemoryNode] = []
    edges: list[MemoryEdge] = []
    # Track every cap id we surface so we don't try to emit a
    # `wires_with` referencing a node we never added (would raise
    # ValueError inside MemoryGraph.add_edges).
    cap_ids: set[str] = set()
    skill_specs: list[tuple[str, dict]] = []  # (skill_id, library_spec)
    io_map: dict[str, tuple[list[str], list[str]]] = {}  # cap_id → (ins, outs)

    # 1. Registry-backed Capabilities (Tier 1/2 typed primitives etc.)
    for spec in _registry_items():
        t = getattr(spec, "type", "") or ""
        if not t:
            continue
        cid = _cap_id(t)
        ins, outs = _cap_io(spec)
        nodes.append(MemoryNode(
            id=cid, kind="capability",
            label=getattr(spec, "display_name", "") or t,
            props={
                "type": t,
                "category": getattr(spec, "category", "") or "",
                "source": "registry",
                "in_types": ins,
                "out_types": outs,
            },
        ))
        cap_ids.add(cid)
        io_map[cid] = (ins, outs)

    # 2. Library-backed Capabilities + Skills.
    seen_types: set = set()
    for item in _library_items():
        t = item.get("type") or item.get("id") or ""
        if not t:
            continue
        seen_types.add(t)
        full = _library_full(t)
        ins, outs = _cap_io(full)
        if _is_skill_type(t):
            sid = _skill_id(t)
            nodes.append(MemoryNode(
                id=sid, kind="skill",
                label=item.get("name") or full.get("display_name") or t,
                props={
                    "type": t,
                    "category": item.get("category") or full.get("category") or "",
                    "side_effects": item.get("side_effects")
                                     or full.get("side_effects") or "",
                    "source": "library",
                    "in_types": ins,
                    "out_types": outs,
                },
            ))
            skill_specs.append((sid, full))
        else:
            cid = _cap_id(t)
            # Library cap may shadow a registry cap of the same type —
            # MemoryGraph.add_node upserts so the library write wins
            # (richer metadata).
            nodes.append(MemoryNode(
                id=cid, kind="capability",
                label=item.get("name") or full.get("display_name") or t,
                props={
                    "type": t,
                    "category": item.get("category") or full.get("category") or "",
                    "side_effects": item.get("side_effects")
                                     or full.get("side_effects") or "",
                    "source": "library",
                    "in_types": ins,
                    "out_types": outs,
                },
            ))
            cap_ids.add(cid)
            io_map[cid] = (ins, outs)

    # 2b. Source-module Skills (workflows.skills.*) — guarantees the
    # shipped Skills surface even when library state has been cleared
    # (test isolation, fresh install, library.reset_registry). Source
    # spec is the truth; library is a denormalised mirror.
    for skill_type, spec in _skill_source_specs().items():
        if skill_type in seen_types:
            continue
        sid = _skill_id(skill_type)
        # Lift outer port types directly off the source spec — same
        # `_cap_io` shape (inputs/outputs with port_type or type).
        ins, outs = _cap_io(spec)
        nodes.append(MemoryNode(
            id=sid, kind="skill",
            label=spec.get("display_name") or skill_type,
            props={
                "type": skill_type,
                "category": spec.get("category") or "",
                "side_effects": spec.get("side_effects") or "",
                "source": "shipped",
                "in_types": ins,
                "out_types": outs,
            },
        ))
        skill_specs.append((sid, spec))

    # Source-module specs recover the impl block that library's Pydantic
    # validator strips. Used only for `contains` edges; metadata still
    # comes from the library summary above.
    source_specs = _skill_source_specs()

    # Add all nodes first so edges can reference them.
    with graph.transaction():
        graph.add_nodes(nodes)

        # 3. `contains` edges from Skill → Capability for each inner-graph
        # node in a skill spec with impl.kind=graph. Prefer the source
        # spec (carries full impl); fall back to the library summary
        # (which won't have impl, so the loop no-ops cleanly).
        for sid, full in skill_specs:
            # sid is `lib:skill:skill.<slug>`; recover the bare type to
            # look up the source-module spec.
            bare_type = sid[len("lib:skill:"):]
            recovered = source_specs.get(bare_type, full)
            impl = (recovered.get("impl") or {})
            if impl.get("kind") != "graph":
                continue
            inner = (impl.get("graph") or {}).get("nodes") or []
            for inner_node in inner:
                inner_type = inner_node.get("type") or ""
                if not inner_type:
                    continue
                target_cap = _cap_id(inner_type)
                # Only emit when the target cap node exists (skills
                # sometimes reference output.parameter etc. that may
                # not be a library entry on every system).
                if target_cap not in cap_ids:
                    continue
                edges.append(MemoryEdge(
                    source=sid, target=target_cap,
                    relation="contains",
                    confidence=Confidence.EXTRACTED,
                    props={"inner_node_id": inner_node.get("id") or ""},
                ))

        # 4. INFERRED `wires_with` edges — cap whose output type matches
        # another cap's input type. ANY-ANY skipped (every node would
        # match every node). Ordered pairs only (a→b once; b→a separately
        # if applicable).
        if infer_wires:
            for src_cap, (_, src_outs) in io_map.items():
                for dst_cap, (dst_ins, _) in io_map.items():
                    if src_cap == dst_cap:
                        continue
                    for src_t in src_outs:
                        if src_t in ("", "any"):
                            continue
                        if src_t in dst_ins:
                            edges.append(MemoryEdge(
                                source=src_cap, target=dst_cap,
                                relation="wires_with",
                                confidence=Confidence.INFERRED,
                                props={"port_type": src_t},
                            ))
                            break  # one edge per ordered pair is enough

        graph.add_edges(edges)

    return {
        "nodes_added": len(nodes),
        "edges_added": len(edges),
        "skills": len(skill_specs),
        "caps": len(cap_ids),
    }
