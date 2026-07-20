"""Legacy typed workflow graph data model.

This module preserves the old directed-acyclic Workflow/Node/Edge/Port shape for
saved typed Studio graphs, comparison courts, and migration adapters.
It is not the active node-language authority. The active product authority is
the Universal Cell specification under 10.PRODUCT/13.NODE-LANGUAGE.

Keep this compatibility layer explicit while its behavior is consumed into Cell
protocols and courts. Do not promote this typed DAG shape as a second graph language.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


SCHEMA_VERSION = "1.0"
LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "superseded_by_universal_cell"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False


# ---------------------------------------------------------------------------
class PortType(str, Enum):
    """Type tags for ports. Used for compatibility checking when wiring.

    Type families per ADR-003:
      Primitives   — ANY, STRING, NUMBER, BOOLEAN, OBJECT, LIST
      Bridge       — HOST, DOCUMENT, MODEL, PROJECT
      AI           — PROMPT, MESSAGE, CONVERSATION, TOOL_RESULT, INTENT,
                     COMPLETION
      AEC          — ELEMENT, SELECTION (subsumes WALL/DOOR/etc when LOD
                     differentiation isn't required)
      UI           — UI (self-hosted canvas/card element references)
      Files / IO   — FILE, PATH, IMAGE, IFC, CSV
      Geometry     — GEOMETRY (Speckle / Rhino object graph)
      Control      — EXEC (Unreal-style execution pin, white-arrow wire)
                     CRON, TRIGGER, EVENT
    """
    # Primitives
    ANY        = "any"
    STRING     = "string"
    NUMBER     = "number"
    BOOLEAN    = "boolean"
    OBJECT     = "object"
    LIST       = "list"
    # Bridge (ADR-003)
    HOST       = "host"        # one of the AEC host adapters
    DOCUMENT   = "document"    # an opened document inside a host
    MODEL      = "model"       # alias for DOCUMENT in 3D contexts
    PROJECT    = "project"     # a project / firm scope grouping
    # AI
    PROMPT       = "prompt"
    MESSAGE      = "message"
    CONVERSATION = "conversation"
    INTENT       = "intent"
    COMPLETION   = "completion"
    TOOL_RESULT  = "tool_result"
    # AEC entity references
    ELEMENT    = "element"
    SELECTION  = "selection"
    # Files / IO
    FILE       = "file"
    PATH       = "path"
    IMAGE      = "image"
    IFC        = "ifc"
    CSV        = "csv"
    # Geometry
    GEOMETRY   = "geometry"
    # Control flow
    EXEC       = "exec"        # white-arrow execution wire (Unreal pattern)
    CRON       = "cron"
    TRIGGER    = "trigger"
    EVENT      = "event"
    # Legacy typed-runtime UI compatibility. Universal Cell is the active
    # authority; this port type remains only for saved typed graphs and old
    # Studio comparison courts while the behavior is consumed into Cell courts.
    UI         = "ui"

    # ── AgDR-0012 §232-233 migration · Q4 founder pick 2026-05-26 ──────
    # Bidirectional adapter to / from Speckle's protocol type string.
    # Speckle-native shapes use the official `Objects.*` namespace; control
    # flow + canvas-internal types use an `archhub.*` namespace so the
    # round-trip is lossless. Stage 1 of the staged migration: the helpers
    # land WITHOUT changing wire behaviour — wires + colour + coercion
    # still read PortType. Stages 2-6 (separate commits) move consumers to
    # read speckle_type first, fall back to PortType for back-compat.
    def to_speckle_type(self) -> str:
        """Return the Speckle-protocol type string for this PortType."""
        return _PORT_TO_SPECKLE.get(self, f"archhub.unknown.{self.value}")

    @classmethod
    def from_speckle_type(cls, speckle_type: Optional[str]) -> "PortType":
        """Map a Speckle protocol type back to the canvas PortType.
        Unknown / missing string → ANY (matches AgDR-0012 §312 deprecation
        path: legacy receivers always succeed on unknown types)."""
        if not speckle_type:
            return cls.ANY
        return _SPECKLE_TO_PORT.get(speckle_type, cls.ANY)


# Direction A of the AgDR-0012 §232-233 mapping. The strings are the
# stable wire-format identifiers; ArchHub's own non-Speckle types live
# under the `archhub.*` namespace so a future replay tool can ingest a
# .speckle JSON dump and reconstruct a canvas graph deterministically.
_PORT_TO_SPECKLE: dict = {
    # Primitives
    None: "archhub.any",  # placeholder if a PortType lookup ever misses
}


def _build_port_to_speckle_map() -> dict:
    """Module-level helper. Defined as a function so it runs AFTER the
    enum is fully constructed (otherwise the enum members aren't
    available at class-body time)."""
    return {
        # Primitives
        PortType.ANY:        "archhub.any",
        PortType.STRING:     "Objects.Primitive.String",
        PortType.NUMBER:     "Objects.Primitive.Number",
        PortType.BOOLEAN:    "Objects.Primitive.Boolean",
        PortType.OBJECT:     "Objects.Other.Object",
        PortType.LIST:       "Objects.Other.List",
        # Bridge
        PortType.HOST:       "archhub.bridge.host",
        PortType.DOCUMENT:   "archhub.bridge.document",
        PortType.MODEL:      "archhub.bridge.model",
        PortType.PROJECT:    "archhub.bridge.project",
        # AI
        PortType.PROMPT:     "archhub.ai.prompt",
        PortType.MESSAGE:    "archhub.ai.message",
        PortType.CONVERSATION: "archhub.ai.conversation",
        PortType.INTENT:     "archhub.ai.intent",
        PortType.COMPLETION: "archhub.ai.completion",
        PortType.TOOL_RESULT: "archhub.ai.tool_result",
        # AEC entities — these MAP to Speckle's built-element family
        PortType.ELEMENT:    "Objects.BuiltElements.Base",
        PortType.SELECTION:  "archhub.aec.selection",
        # UI entities — ArchHub-internal canvas/card references
        PortType.UI:         "archhub.ui.element",
        # Files / IO
        PortType.FILE:       "archhub.io.file",
        PortType.PATH:       "archhub.io.path",
        PortType.IMAGE:      "archhub.io.image",
        PortType.IFC:        "Objects.Other.IFC",
        PortType.CSV:        "archhub.io.csv",
        # Geometry — true Speckle geometry namespace
        PortType.GEOMETRY:   "Objects.Geometry.Base",
        # Control flow — archhub-only; no Speckle equivalent
        PortType.EXEC:       "archhub.control.exec",
        PortType.CRON:       "archhub.control.cron",
        PortType.TRIGGER:    "archhub.control.trigger",
        PortType.EVENT:      "archhub.control.event",
    }


_PORT_TO_SPECKLE = _build_port_to_speckle_map()
_SPECKLE_TO_PORT: dict = {v: k for k, v in _PORT_TO_SPECKLE.items()}


PortTypeRef = PortType | str


def normalize_port_type_ref(value: PortTypeRef | None) -> PortTypeRef:
    """Keep known legacy types convenient and unknown types lossless."""
    if isinstance(value, PortType):
        return value
    raw = str(value or "any").strip() or "any"
    try:
        return PortType(raw)
    except ValueError:
        return _SPECKLE_TO_PORT.get(raw, raw)


def port_type_id(value: PortTypeRef | None) -> str:
    normalized = normalize_port_type_ref(value)
    return normalized.value if isinstance(normalized, PortType) else normalized


def port_speckle_type(value: PortTypeRef | None) -> str:
    normalized = normalize_port_type_ref(value)
    if isinstance(normalized, PortType):
        return normalized.to_speckle_type()
    return normalized


@dataclass
class Port:
    name: str
    type: PortTypeRef = PortType.ANY
    description: str = ""
    required: bool = False
    default: Any = None
    # ADR-003 additions:
    exec: bool = False         # True = execution pin (draws white arrow)
    multiple: bool = False     # True = input accepts multiple wires

    def to_dict(self) -> dict:
        # AgDR-0012 §232-233 migration · Stage 2 (2026-05-26): emit
        # `speckle_type` alongside the legacy `type` field. Old readers
        # ignore the new key; new readers prefer it.
        return {"name": self.name, "type": port_type_id(self.type),
                "speckle_type": port_speckle_type(self.type),
                "description": self.description, "required": self.required,
                "default": self.default,
                "exec": self.exec, "multiple": self.multiple}

    @staticmethod
    def from_dict(d: dict) -> "Port":
        # AgDR-0012 §232-233 migration · Stage 2 reader: prefer
        # speckle_type when present; fall back to legacy type for back-compat.
        if "speckle_type" in d and d["speckle_type"]:
            speckle_raw = str(d["speckle_type"]).strip()
            port_type = _SPECKLE_TO_PORT.get(speckle_raw)
            # If the speckle_type was unknown the fallback returns ANY —
            # in that case respect the legacy `type` if it's there.
            if port_type is None and "type" in d:
                port_type = normalize_port_type_ref(d.get("type", "any"))
            elif port_type is None:
                port_type = normalize_port_type_ref(speckle_raw)
        else:
            port_type = normalize_port_type_ref(d.get("type", "any"))
        return Port(name=d["name"],
                    type=port_type,
                    description=d.get("description", ""),
                    required=d.get("required", False),
                    default=d.get("default"),
                    exec=bool(d.get("exec", False)),
                    multiple=bool(d.get("multiple", False)))


# ---------------------------------------------------------------------------
@dataclass
class Node:
    id: str                                   # unique within the workflow
    type: str                                 # registered node type, e.g. "llm.complete"
    label: str = ""                           # display label
    config: dict = field(default_factory=dict)        # type-specific config
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    position: dict = field(default_factory=lambda: {"x": 0.0, "y": 0.0})

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "label": self.label,
            "config": self.config,
            "inputs":  [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "position": self.position,
        }

    @staticmethod
    def from_dict(d: dict) -> "Node":
        return Node(
            id=d["id"], type=d["type"], label=d.get("label", ""),
            config=d.get("config", {}),
            inputs=[Port.from_dict(p) for p in d.get("inputs",  [])],
            outputs=[Port.from_dict(p) for p in d.get("outputs", [])],
            position=d.get("position", {"x": 0.0, "y": 0.0}),
        )


@dataclass
class Edge:
    id: str
    src_node: str
    src_port: str
    dst_node: str
    dst_port: str
    # v1.4 (ADR-003 §"Execution model" + Agent A wire-research):
    # Edges carry runtime data state on disk. The actual `value` lives
    # only in the in-process WireBus to avoid bloating session.graph;
    # `cache_key` lets a re-opened session detect "still fresh".
    cache_key: str = ""
    state: str = "idle"   # idle | flowing | cached | stale | error | upstream_error
    value_preview: str = ""   # repr(value)[:200] for hover tooltip
    # v1.4+ "profound wires" (founder direction 2026-05-14):
    # Edges aren't just hoses — they can pick a sub-field of the source
    # output and/or wrap into a sub-key of the destination input.
    # Example: src_field="selection.walls" picks only the walls list
    # from a selection dict before flowing. dst_field="messages[-1]"
    # writes incoming value into messages[-1] of the input slot dict.
    # Empty string = pass-through (no transform).
    src_field: str = ""
    dst_field: str = ""
    # v1.5 wire layers. The canvas represents these as editable wire/layer
    # nodes; the headless Workflow format must preserve the same contract so
    # saved or generated workflows do not collapse rich wires into thin hoses.
    wire_node: str = ""
    junction_node: str = ""
    junction_nodes: list[str] = field(default_factory=list)
    value_type: str = ""
    schema_ref: str = ""
    gate_policy: str = ""
    codec: str = ""
    encryption: str = ""
    encryption_key_ref: str = ""
    behavior: str = ""
    presentation: str = ""
    provenance: Any = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "src_node": self.src_node, "src_port": self.src_port,
                "dst_node": self.dst_node, "dst_port": self.dst_port,
                "cache_key": self.cache_key, "state": self.state,
                "value_preview": self.value_preview,
                "src_field": self.src_field, "dst_field": self.dst_field,
                "wire_node": self.wire_node,
                "junction_node": self.junction_node,
                "junction_nodes": self.junction_nodes,
                "value_type": self.value_type,
                "schema_ref": self.schema_ref,
                "gate_policy": self.gate_policy,
                "codec": self.codec,
                "encryption": self.encryption,
                "encryption_key_ref": self.encryption_key_ref,
                "behavior": self.behavior,
                "presentation": self.presentation,
                "provenance": self.provenance}

    @staticmethod
    def from_dict(d: dict) -> "Edge":
        return Edge(id=d["id"], src_node=d["src_node"], src_port=d["src_port"],
                    dst_node=d["dst_node"], dst_port=d["dst_port"],
                    cache_key=d.get("cache_key", "") or "",
                    state=d.get("state", "idle") or "idle",
                    value_preview=d.get("value_preview", "") or "",
                    src_field=d.get("src_field", "") or "",
                    dst_field=d.get("dst_field", "") or "",
                    wire_node=d.get("wire_node", "") or "",
                    junction_node=d.get("junction_node", "") or "",
                    junction_nodes=d.get("junction_nodes", []) or [],
                    value_type=d.get("value_type", "") or "",
                    schema_ref=d.get("schema_ref", "") or "",
                    gate_policy=d.get("gate_policy", "") or "",
                    codec=d.get("codec", "") or "",
                    encryption=d.get("encryption", "") or "",
                    encryption_key_ref=d.get("encryption_key_ref", "") or "",
                    behavior=d.get("behavior", "") or "",
                    presentation=d.get("presentation", "") or "",
                    provenance=d.get("provenance", "") or "")


# ---------------------------------------------------------------------------
@dataclass
class Trigger:
    """How a workflow is fired. Phase 1 supports: manual, cron, speckle_webhook, file_watch."""
    id: str
    type: str                                  # "manual" | "cron" | "speckle_webhook" | "file_watch"
    config: dict = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Trigger":
        return Trigger(id=d["id"], type=d["type"],
                       config=d.get("config", {}), enabled=d.get("enabled", True))


# ---------------------------------------------------------------------------
@dataclass
class Workflow:
    id: str
    name: str
    description: str = ""
    schema_version: str = SCHEMA_VERSION
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    inputs: list[Port] = field(default_factory=list)     # workflow-level inputs
    outputs: list[Port] = field(default_factory=list)    # workflow-level outputs
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Skill metadata. When `intent` is non-empty, the workflow is discoverable
    # as a Skill: the matcher can pick it for a user prompt, the chat can
    # propose it, and the library shows it under the Skills tab.
    # Empty intent = plain workflow (manual run only).
    metadata: dict = field(default_factory=dict)

    # ---- factory helpers ----
    @staticmethod
    def new(name: str, description: str = "") -> "Workflow":
        return Workflow(id=str(uuid.uuid4()), name=name, description=description,
                        triggers=[Trigger(id=str(uuid.uuid4()), type="manual")])

    # ---- mutation -----------
    def add_node(self, node: Node) -> Node:
        self.nodes.append(node)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return node

    def add_edge(self, edge: Edge) -> Edge:
        self.edges.append(edge)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return edge

    def get_node(self, node_id: str) -> Optional[Node]:
        return next((n for n in self.nodes if n.id == node_id), None)

    def edges_into(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.dst_node == node_id]

    def edges_out_of(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.src_node == node_id]

    # ---- serialization -----
    def _enriched_edge_dict(self, edge: "Edge") -> dict:
        """AgDR-0012 §232-233 migration · Stage 3 (Q4 2026-05-26):
        emit `speckle_type` per edge by deriving it from the source
        node's source port. Edge struct stays slim (no new field);
        the enrichment happens at serialization time so consumers
        like the JSX wire renderer can read it directly without a
        node + port lookup of their own.

        Falls back gracefully: if src node / src port can't be
        resolved, the key is omitted (back-compat — consumers must
        tolerate missing key per Stage 2 contract).
        """
        d = edge.to_dict()
        src_node = self.get_node(edge.src_node)
        if src_node is not None:
            port = next((p for p in src_node.outputs
                          if p.name == edge.src_port), None)
            if port is not None:
                d["speckle_type"] = port_speckle_type(port.type)
        return d

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "schema_version": self.schema_version,
            "nodes":    [n.to_dict() for n in self.nodes],
            "edges":    [self._enriched_edge_dict(e) for e in self.edges],
            "triggers": [t.to_dict() for t in self.triggers],
            "inputs":   [p.to_dict() for p in self.inputs],
            "outputs":  [p.to_dict() for p in self.outputs],
            "metadata": self.metadata,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "Workflow":
        return Workflow(
            id=d["id"], name=d["name"],
            description=d.get("description", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            nodes=[Node.from_dict(n) for n in d.get("nodes", [])],
            edges=[Edge.from_dict(e) for e in d.get("edges", [])],
            triggers=[Trigger.from_dict(t) for t in d.get("triggers", [])],
            inputs=[Port.from_dict(p) for p in d.get("inputs", [])],
            outputs=[Port.from_dict(p) for p in d.get("outputs", [])],
            metadata=d.get("metadata", {}) or {},
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=d.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def from_json(text: str) -> "Workflow":
        return Workflow.from_dict(json.loads(text))

    @staticmethod
    def load(path: Path) -> "Workflow":
        return Workflow.from_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    # ---- validation ---------
    def validate(self) -> list[str]:
        """Return a list of error messages. Empty list = valid.
        Back-compat shim around validate_v2() — surfaces only `err`
        items as strings for callers from before AgDR-0041 P5."""
        return [iss["msg"] for iss in self.validate_v2()
                if iss.get("level") == "err"]

    def validate_v2(self) -> list[dict]:
        """Structured validation — returns issues as dicts so the
        Inspector / GraphHealthPanel can colour wires + nodes.

        Issue shape:
          {level: "err" | "warn" | "ok",
           code:  "duplicate_id" | "missing_src" | "missing_dst" |
                  "unknown_src_port" | "unknown_dst_port" |
                  "type_mismatch" | "cycle" | "unset_input",
           node_id: str | None,
           edge_id: str | None,
           msg: str}

        Levels:
          err  — graph cannot cook (wire blocked, type mismatch)
          warn — graph can cook with defaults (required input unset)

        AgDR-0041 P5 — live validator. Runs cheaply on every edit so
        the canvas can colour wires green / yellow / red without
        waiting for cook time."""
        issues: list[dict] = []
        ids = {n.id for n in self.nodes}

        if len(ids) != len(self.nodes):
            issues.append({
                "level": "err", "code": "duplicate_id",
                "node_id": None, "edge_id": None,
                "msg": "Duplicate node ids in graph."})

        for e in self.edges:
            if e.src_node not in ids:
                issues.append({"level": "err", "code": "missing_src",
                    "node_id": None, "edge_id": e.id,
                    "msg": f"Edge {e.id}: src_node '{e.src_node}' missing."})
                continue
            if e.dst_node not in ids:
                issues.append({"level": "err", "code": "missing_dst",
                    "node_id": None, "edge_id": e.id,
                    "msg": f"Edge {e.id}: dst_node '{e.dst_node}' missing."})
                continue
            src = self.get_node(e.src_node)
            dst = self.get_node(e.dst_node)
            src_port = next((p for p in (src.outputs if src else [])
                              if p.name == e.src_port), None)
            dst_port = next((p for p in (dst.inputs if dst else [])
                              if p.name == e.dst_port), None)
            if src and not src_port:
                issues.append({"level": "err", "code": "unknown_src_port",
                    "node_id": src.id, "edge_id": e.id,
                    "msg": (f"Edge {e.id}: src_port '{e.src_port}' "
                            f"not on node '{src.id}'.")})
            if dst and not dst_port:
                issues.append({"level": "err", "code": "unknown_dst_port",
                    "node_id": dst.id, "edge_id": e.id,
                    "msg": (f"Edge {e.id}: dst_port '{e.dst_port}' "
                            f"not on node '{dst.id}'.")})
            # Port-type compatibility — AgDR-0041 P5 wire colouring.
            # ANY accepts anything; identical types compatible; mismatch
            # = err (cook would propagate as upstream_error).
            if src_port and dst_port:
                from .typesystem import can_wire
                st = src_port.type
                dt = dst_port.type
                if not can_wire(st, dt,
                                output_is_exec=src_port.exec,
                                input_is_exec=dst_port.exec):
                    issues.append({"level": "err", "code": "type_mismatch",
                        "node_id": dst.id, "edge_id": e.id,
                        "msg": (f"Edge {e.id}: type {port_type_id(st)!r} from "
                                 f"'{src.id}.{e.src_port}' does not match "
                                 f"{port_type_id(dt)!r} on "
                                 f"'{dst.id}.{e.dst_port}'.")})

        # Required-input-unset detection (warn, not err — many nodes
        # tolerate defaults). A required input port with no incoming
        # edge is what we surface.
        wired_in: set = {(e.dst_node, e.dst_port) for e in self.edges}
        for n in self.nodes:
            for p in n.inputs:
                if p.required and (n.id, p.name) not in wired_in:
                    issues.append({"level": "warn", "code": "unset_input",
                        "node_id": n.id, "edge_id": None,
                        "msg": (f"Node '{n.id}': required input "
                                f"'{p.name}' ({port_type_id(p.type)}) unset.")})

        # Cycles — block cook, surface as err.
        try:
            self._topo_sort()
        except RuntimeError as ex:
            issues.append({"level": "err", "code": "cycle",
                "node_id": None, "edge_id": None,
                "msg": str(ex)})

        return issues

    def _topo_sort(self) -> list[str]:
        in_deg = {n.id: 0 for n in self.nodes}
        for e in self.edges:
            if e.dst_node in in_deg:
                in_deg[e.dst_node] += 1
        queue = [nid for nid, d in in_deg.items() if d == 0]
        order: list[str] = []
        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for e in self.edges_out_of(nid):
                # Edges to ghost / missing dst nodes are reported as
                # 'missing_dst' by validate_v2; skip them here so the
                # cycle detector doesn't KeyError on a broken graph
                # (AgDR-0041 P5 — validator runs on edit-time graphs
                # that may be transiently inconsistent).
                if e.dst_node not in in_deg:
                    continue
                in_deg[e.dst_node] -= 1
                if in_deg[e.dst_node] == 0:
                    queue.append(e.dst_node)
        if len(order) != len(self.nodes):
            raise RuntimeError("Cycle detected in workflow graph.")
        return order
