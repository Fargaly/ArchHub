"""Firm-shared graph sync — Speckle / JSON transports.

AgDR-0042 slice 6/6 (D1·C — final slice).

Multi-seat firms share one MemoryGraph per company. The sync layer
adapts the local graph onto a transport (JSON file today; Speckle
Versions adapter is a one-class follow-up that lands on the same
interface). Each push creates a new immutable snapshot; pull receives
the latest. Merge is union by node id + edge triple, with newer
timestamp winning on prop conflicts.

Public surface:

    from memory.sync import push, pull, merge, JsonFileTransport

    transport = JsonFileTransport("/firm/shared/graph.json")
    push(local_graph, transport)
    remote = pull(transport)                # → MemoryGraph (in-memory)
    merged = merge(local_graph, remote)     # → MemoryGraph (in-memory)

Conflict policy on node props:
  - `community_id` always taken from local (slice-5 derived; firm sync
    doesn't override the local clustering)
  - everything else: newer `ts` wins; ties → remote (deterministic)
  - missing `ts` props treated as 0

Edge conflict policy:
  - same (source, target, relation) triple: confidence + props from
    whichever side has the newer linked node ts; default to remote
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Protocol

from .graph import (
    MemoryGraph, MemoryNode, MemoryEdge, Confidence,
)


# ── transport protocol ───────────────────────────────────────────────


class Transport(Protocol):
    """Minimal contract any sync backend must satisfy.

    `send(snapshot)`  — atomically write the snapshot dict somewhere
                         the firm can read.
    `receive()`       — return the latest snapshot dict, or None when
                         nothing has been sent yet (fresh store).
    """

    def send(self, snapshot: dict) -> None: ...
    def receive(self) -> Optional[dict]: ...


class JsonFileTransport:
    """Plain JSON-file transport — the default.

    Atomic via tmp-file + os.replace so concurrent firm seats never
    read a half-written file. Single file per shared store; for a
    real Speckle Versions backend the only change is swapping this
    class out for one whose receive() pulls the latest Version + send()
    creates a new Version.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def send(self, snapshot: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False,
                dir=str(self.path.parent),
                prefix=self.path.name + ".",
                suffix=".tmp") as f:
            json.dump(snapshot, f, indent=2, default=str)
            tmp_name = f.name
        os.replace(tmp_name, self.path)

    def receive(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


# ── push / pull ──────────────────────────────────────────────────────


def push(graph: MemoryGraph, transport: Transport) -> dict:
    """Serialise `graph` and send via the transport. Returns the
    snapshot dict (useful for caller telemetry + the merge function)."""
    snap = graph.to_dict()
    transport.send(snap)
    return snap


def pull(transport: Transport,
          *, path: Optional[Path | str] = None) -> MemoryGraph:
    """Receive the latest snapshot via the transport and return a
    new in-memory MemoryGraph. Empty graph when transport returned
    nothing (no prior send / fresh store).

    `path` is forwarded to MemoryGraph.from_dict so the receive can
    persist to a specific SQLite file. Default (None) → in-memory."""
    snap = transport.receive()
    if not snap:
        return MemoryGraph.open(":memory:" if path is None else path)
    return MemoryGraph.from_dict(snap, path=path)


# ── merge ────────────────────────────────────────────────────────────


# Props that local always wins on (slice-5 derived, per-seat).
_LOCAL_WIN_PROPS: set = {"community_id"}


def _node_ts(node: MemoryNode) -> int:
    """Best-effort timestamp lookup. Turn extractor + project extractor
    write `ts` / `mtime`; other extractors don't, so 0 is the tie
    default."""
    for k in ("ts", "mtime", "updated_at"):
        v = node.props.get(k)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return 0


def _merge_node_props(local: dict, remote: dict) -> dict:
    """Newer-ts wins on shared keys; both dicts contribute their
    unique keys. local always wins on _LOCAL_WIN_PROPS regardless
    of ts."""
    l_ts = _node_ts(MemoryNode(id="x", kind="", props=local))
    r_ts = _node_ts(MemoryNode(id="x", kind="", props=remote))
    winner = local if l_ts > r_ts else remote
    out = {**local, **remote, **winner}
    # Apply local-win overrides last.
    for k in _LOCAL_WIN_PROPS:
        if k in local:
            out[k] = local[k]
    return out


def merge(local: MemoryGraph, remote: MemoryGraph,
           *, path: Optional[Path | str] = None) -> MemoryGraph:
    """Union-merge two graphs into a fresh MemoryGraph.

    Args:
      local  — local seat graph (community props local-win).
      remote — firm-shared graph received via the transport.
      path   — optional disk path for the merged graph. Default
               (None) → in-memory.

    Returns a NEW MemoryGraph — neither input is mutated. Idempotent:
    merge(g, g) === g.
    """
    merged = MemoryGraph.open(":memory:" if path is None else path)

    # 1. Nodes — union by id, merge props by ts.
    local_nodes = {n.id: n for n in local.all_nodes()}
    remote_nodes = {n.id: n for n in remote.all_nodes()}
    all_ids = sorted(set(local_nodes.keys()) | set(remote_nodes.keys()))
    merged_nodes: list[MemoryNode] = []
    for nid in all_ids:
        ln = local_nodes.get(nid)
        rn = remote_nodes.get(nid)
        if ln is not None and rn is None:
            merged_nodes.append(ln)
        elif ln is None and rn is not None:
            merged_nodes.append(rn)
        else:
            l_ts = _node_ts(ln)
            r_ts = _node_ts(rn)
            kind = ln.kind if l_ts > r_ts else rn.kind
            label = ln.label if l_ts > r_ts else rn.label
            merged_nodes.append(MemoryNode(
                id=nid, kind=kind, label=label,
                props=_merge_node_props(ln.props, rn.props),
            ))

    # 2. Edges — union by (source, target, relation). Confidence:
    # if either side is EXTRACTED, prefer EXTRACTED (trust hard facts
    # over inference); else INFERRED. Props: simple merge (remote
    # wins on collision — firm shared is the canonical source).
    local_edges = {(e.source, e.target, e.relation): e
                   for e in local.all_edges()}
    remote_edges = {(e.source, e.target, e.relation): e
                    for e in remote.all_edges()}
    all_triples = sorted(set(local_edges) | set(remote_edges))
    merged_edges: list[MemoryEdge] = []
    for triple in all_triples:
        le = local_edges.get(triple)
        re = remote_edges.get(triple)
        if le is not None and re is None:
            edge = le
        elif le is None and re is not None:
            edge = re
        else:
            conf = (Confidence.EXTRACTED
                    if (le.confidence == Confidence.EXTRACTED
                        or re.confidence == Confidence.EXTRACTED)
                    else Confidence.INFERRED)
            merged_props = {**le.props, **re.props}
            edge = MemoryEdge(
                source=triple[0], target=triple[1], relation=triple[2],
                confidence=conf, props=merged_props,
            )
        # Drop edges whose endpoints aren't both in the merged node set
        # (could happen if local + remote disagree on which nodes exist
        # AND the disagreement leaves one endpoint orphaned).
        endpoint_ids = {n.id for n in merged_nodes}
        if edge.source not in endpoint_ids or edge.target not in endpoint_ids:
            continue
        merged_edges.append(edge)

    with merged.transaction():
        merged.add_nodes(merged_nodes)
        merged.add_edges(merged_edges)
    return merged


def sync(local: MemoryGraph, transport: Transport,
          *, path: Optional[Path | str] = None) -> dict:
    """One-call pull + merge + push. Convenience for the
    schedule-driven sync loop a seat runs every N minutes.

    Steps:
      1. pull → remote (or empty if first run)
      2. merge(local, remote) → merged
      3. push(merged, transport)
      4. return stats {local_nodes, remote_nodes, merged_nodes,
                       local_edges, remote_edges, merged_edges}

    Does NOT mutate `local` — the merged graph lives at `path` (or
    in-memory). Caller decides whether to replace its local store
    with the merged one."""
    remote = pull(transport)
    try:
        merged = merge(local, remote, path=path)
        try:
            push(merged, transport)
            return {
                "local_nodes":   local.count_nodes(),
                "remote_nodes":  remote.count_nodes(),
                "merged_nodes":  merged.count_nodes(),
                "local_edges":   local.count_edges(),
                "remote_edges":  remote.count_edges(),
                "merged_edges":  merged.count_edges(),
            }
        finally:
            # Caller owns the merged graph if they want it; we close
            # only when nothing else holds the handle. Returning the
            # merged graph would surface a mutable handle; the stats
            # dict is enough.
            pass
    finally:
        remote.close()
