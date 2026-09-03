"""Edge extractor — similarity + realization links over an existing graph.

AgDR-0042 slice 6/6 (the connective pass). The library / decision /
project / turn extractors (slices 2 + 4 + 5) are good at MINTING nodes
but they only emit *structural* edges (contains, builds_on, supersedes,
wires_with). On the real ArchHub graph that left ~84% of nodes isolated
(deg 0): 153 capabilities with no port-type overlap and 48 decisions
that don't all cite each other.

This pass adds the two *semantic* relations that connect the graph:

  relation=similar_to   — capability↔capability and decision↔decision.
                          INFERRED. Each node is embedded (label + key
                          props) via the always-available lexical
                          embedder; a node links to its top-k most
                          similar SAME-KIND peers with cosine ≥
                          sim_threshold. Symmetric — emitted once per
                          unordered pair (the natural key dedupes the
                          mirror, but we skip the wasted write too).
                          props {"cosine": round(c, 3)}.

  relation=realized_by  — capability → decision. INFERRED. A capability
                          is "realized by" a decision when either
                          (a) their embeddings cosine ≥ sim_threshold,
                          OR (b) the decision's label / props mention the
                          capability's id or slug (e.g. an AgDR titled
                          "QTO pricing engine" realizes lib:cap:aec.
                          qto_pricing). Directional cap → decision.

Why the lexical embedder + a LOW threshold:
  The lexical backend is bag-of-words TF-IDF with the hashing trick
  (see personal_brain.embeddings.LexicalEmbedder). It's deterministic
  and offline but SPARSE — short technical labels share few tokens, so
  cosines run much lower than a neural model. Empirically (calibrated
  against the live graph.sqlite) cosine ≥ 0.82 connects almost nothing
  (~79% still isolated); 0.55 hits ~35% isolated with ~250 edges total
  — dense enough to be useful, sparse enough to be signal not noise.
  Hence the default `sim_threshold=0.55`.

Idempotent — MemoryEdge's natural key (source, target, relation) means
a re-run upserts in place and adds nothing new. Safe to schedule.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# Local app import — extractor lives under app/memory/extractors/edges.py
_APP = Path(__file__).resolve().parents[2]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from memory.graph import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence, default_graph_path,
)


# ── embedder loader ──────────────────────────────────────────────────


def _personal_brain_src() -> Optional[Path]:
    """Locate personal-brain-mcp/src so the lexical embedder imports.

    The brain package sits as a sibling of `app/` under the repo root:
        <repo>/app/memory/extractors/edges.py   (this file)
        <repo>/personal-brain-mcp/src/personal_brain/embeddings.py
    parents[3] of this file is the repo root.
    """
    repo = Path(__file__).resolve().parents[3]
    cand = repo / "personal-brain-mcp" / "src"
    return cand if cand.is_dir() else None


def _default_embedder():
    """Return the always-available lexical embedder.

    Forces `prefer='lexical'` so we never trigger a fastembed model
    download — this pass must run fully offline (BRAIN-FIRST: the daemon
    may already hold the embedder, but we don't depend on it). Falls
    back to a tiny in-module bag-of-words cosine if the brain package
    isn't importable at all, so the extractor never hard-crashes.
    """
    src = _personal_brain_src()
    if src is not None and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from personal_brain.embeddings import get_embedder
        return get_embedder(prefer="lexical")
    except Exception:
        return _FallbackEmbedder()


class _FallbackEmbedder:
    """Last-resort bag-of-words cosine if personal_brain isn't on disk.

    Same surface as the lexical embedder (encode / encode_batch /
    cosine) but a trivially-simple sparse-dict TF. Only used when the
    brain package is missing; the real lexical embedder is preferred.
    """

    backend_name = "edges-fallback-bow"
    dim = 0

    _TOK = re.compile(r"[A-Za-z][A-Za-z0-9]+")

    def encode(self, text: str) -> dict:
        toks = [t.lower() for t in self._TOK.findall(text or "") if len(t) > 1]
        if not toks:
            return {}
        d: dict = {}
        for t in toks:
            d[t] = d.get(t, 0.0) + 1.0
        norm = sum(v * v for v in d.values()) ** 0.5
        if norm > 0:
            for k in d:
                d[k] /= norm
        return d

    def encode_batch(self, texts: list) -> list:
        return [self.encode(t) for t in texts]

    def cosine(self, a, b) -> float:
        if not a or not b:
            return 0.0
        # Iterate the smaller dict.
        if len(a) > len(b):
            a, b = b, a
        return sum(w * b.get(k, 0.0) for k, w in a.items())


# ── text projection ──────────────────────────────────────────────────


# Props that carry discriminating vocabulary for similarity. Labels on
# the real graph are terse ("Input", "If", "LLM completion"); the type /
# category / status fields supply the tokens that actually separate
# nodes (aec.qto vs llm vs host.*).
_TEXT_PROP_KEYS = (
    "type", "category", "side_effects", "display_name",
    "status", "agdr_id", "name",
)


def _node_text(node: MemoryNode) -> str:
    """Project a node to the string we embed: label + key props.

    Mirrors the deliverable spec ("label + key props"). Type/category
    are split on dots so `aec.qto_pricing` contributes `aec`, `qto`,
    `pricing` tokens to the bag-of-words rather than one opaque token.
    """
    parts: list[str] = [node.label or node.id]
    p = node.props or {}
    for key in _TEXT_PROP_KEYS:
        v = p.get(key)
        if v:
            s = str(v)
            parts.append(s)
            # Help the lexical tokenizer see dotted/underscored segments.
            if any(sep in s for sep in "._/"):
                parts.append(re.sub(r"[._/]+", " ", s))
    return " ".join(parts)


# ── slug / id mention helpers (realized_by fallback) ─────────────────


def _cap_slugs(cap: MemoryNode) -> set[str]:
    """Tokens that, if mentioned by a decision, imply it realizes `cap`.

    From `lib:cap:aec.qto_pricing` (id) + props.type we derive:
        {'aec.qto_pricing', 'aec', 'qto_pricing', 'qto', 'pricing',
         'aec.qto.pricing', ...} minus tiny / generic tokens.
    Only multi-char, non-generic tokens count so a decision mentioning
    "io" or "data" doesn't realize every io/data cap.
    """
    raw: set[str] = set()
    bare = cap.id.split(":")[-1]                  # aec.qto_pricing
    raw.add(bare)
    t = (cap.props or {}).get("type") or ""
    if t:
        raw.add(str(t))
    out: set[str] = set()
    for token in raw:
        out.add(token.lower())
        for seg in re.split(r"[._/\s]+", token):
            seg = seg.strip().lower()
            if len(seg) >= 4 and seg not in _GENERIC_SLUG_TOKENS:
                out.add(seg)
    # Drop the very generic full tokens too (keep only specific ones).
    return {s for s in out if s and s not in _GENERIC_SLUG_TOKENS}


_GENERIC_SLUG_TOKENS = frozenset({
    "io", "data", "llm", "control", "host", "aec", "input", "output",
    "file", "node", "parameter", "param", "util", "core", "base", "main",
    "lib", "cap", "skill", "type", "value", "console", "display",
})


def _decision_haystack(dec: MemoryNode) -> str:
    """Lower-cased text of a decision we scan for capability mentions."""
    parts = [dec.id, dec.label or ""]
    p = dec.props or {}
    for k in ("agdr_id", "category", "status", "path"):
        v = p.get(k)
        if v:
            parts.append(str(v))
    return " ".join(parts).lower()


# ── isolation accounting ─────────────────────────────────────────────


def _isolated_count(graph: MemoryGraph) -> tuple[int, int]:
    """(isolated, total) — nodes with zero incident edges (in OR out)."""
    deg: dict[str, int] = {}
    for e in graph.all_edges():
        deg[e.source] = deg.get(e.source, 0) + 1
        deg[e.target] = deg.get(e.target, 0) + 1
    ids = [n.id for n in graph.all_nodes()]
    iso = sum(1 for i in ids if deg.get(i, 0) == 0)
    return iso, len(ids)


# ── main entry ───────────────────────────────────────────────────────


def extract_edges(graph: MemoryGraph,
                  *,
                  sim_threshold: float = 0.55,
                  max_edges_per_node: int = 6,
                  embedder=None) -> dict:
    """Add semantic `similar_to` + `realized_by` edges to `graph`.

    Args:
      graph              — open MemoryGraph (in-memory or on-disk).
      sim_threshold      — minimum cosine for a similarity link. Default
                           0.55, calibrated for the SPARSE lexical
                           embedder against the live graph (0.82 is too
                           strict; see module docstring). Tune DOWN if a
                           future graph stays too isolated, UP if edges
                           explode past signal.
      max_edges_per_node — top-k cap per node, per relation. Keeps a hub
                           node from linking to dozens of peers.
      embedder           — optional Embedder (encode_batch + cosine). When
                           None, the always-available lexical embedder is
                           loaded (offline, no model download).

    Returns:
      {"added", "similar_to", "realized_by", "isolated_before",
       "isolated_after", "isolated_pct_after"}.

    Idempotent — re-running upserts the same triples and adds nothing.
    """
    emb = embedder if embedder is not None else _default_embedder()

    caps = graph.all_nodes(kind="capability")
    decs = graph.all_nodes(kind="decision")

    iso_before, total = _isolated_count(graph)

    sim_edges: list[MemoryEdge] = []
    realized_edges: list[MemoryEdge] = []

    # Pre-embed each kind in one batch (cheap, deterministic).
    cap_vecs = emb.encode_batch([_node_text(n) for n in caps]) if caps else []
    dec_vecs = emb.encode_batch([_node_text(n) for n in decs]) if decs else []

    # ── 1. similar_to within each kind ──
    # Symmetric: build per-node top-k candidate lists, then emit each
    # unordered pair once via a seen-set (avoids the mirror write even
    # though the natural key would dedupe it).
    seen_pairs: set[tuple[str, str]] = set()
    for nodes, vecs in ((caps, cap_vecs), (decs, dec_vecs)):
        n = len(nodes)
        for i in range(n):
            vi = vecs[i]
            cands: list[tuple[float, int]] = []
            for j in range(n):
                if i == j:
                    continue
                c = emb.cosine(vi, vecs[j])
                if c >= sim_threshold:
                    cands.append((c, j))
            cands.sort(key=lambda kv: kv[0], reverse=True)
            for c, j in cands[:max_edges_per_node]:
                a, b = nodes[i].id, nodes[j].id
                key = (a, b) if a <= b else (b, a)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                sim_edges.append(MemoryEdge(
                    source=key[0], target=key[1],
                    relation="similar_to",
                    confidence=Confidence.INFERRED,
                    props={"cosine": round(c, 3)},
                ))

    # ── 2. realized_by: capability → decision ──
    # (a) embedding cosine ≥ threshold, OR (b) decision text mentions the
    # capability's id / slug. Top-k decisions per capability by cosine;
    # the slug-mention matches are always included (they're high-signal).
    dec_haystacks = [_decision_haystack(d) for d in decs]
    for i, cap in enumerate(caps):
        slugs = _cap_slugs(cap)
        scored: list[tuple[float, int, bool]] = []  # (cosine, dec_idx, mention)
        for j, dec in enumerate(decs):
            c = emb.cosine(cap_vecs[i], dec_vecs[j]) if cap_vecs and dec_vecs else 0.0
            mention = any(s in dec_haystacks[j] for s in slugs) if slugs else False
            if c >= sim_threshold or mention:
                scored.append((c, j, mention))
        # Mentions first (rank True>False), then by cosine.
        scored.sort(key=lambda t: (t[2], t[0]), reverse=True)
        for c, j, mention in scored[:max_edges_per_node]:
            props: dict = {"cosine": round(c, 3)}
            if mention:
                props["via"] = "mention"
            realized_edges.append(MemoryEdge(
                source=cap.id, target=decs[j].id,
                relation="realized_by",
                confidence=Confidence.INFERRED,
                props=props,
            ))

    # ── write (one transaction; endpoints already exist) ──
    with graph.transaction():
        if sim_edges:
            graph.add_edges(sim_edges)
        if realized_edges:
            graph.add_edges(realized_edges)

    iso_after, _ = _isolated_count(graph)
    pct_after = round(100.0 * iso_after / total, 1) if total else 0.0

    return {
        "added": len(sim_edges) + len(realized_edges),
        "similar_to": len(sim_edges),
        "realized_by": len(realized_edges),
        "isolated_before": iso_before,
        "isolated_after": iso_after,
        "isolated_pct_after": pct_after,
    }


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Run the edge extractor against the REAL on-disk graph.

    Usage:
        python -m memory.extractors.edges        (cwd = ArchHub/app)
        python app/memory/extractors/edges.py    (cwd = repo root)

    Opens default_graph_path(). The brain daemon may hold a handle on
    the same sqlite file; MemoryGraph opens its own connection (WAL
    journaling allows concurrent readers). We additionally set a busy
    timeout on that connection so a momentary writer lock from the
    daemon retries rather than failing.
    """
    import argparse

    parser = argparse.ArgumentParser(description="ArchHub memory graph edge extractor")
    parser.add_argument("--threshold", type=float, default=0.55,
                        help="cosine similarity threshold (default 0.55)")
    parser.add_argument("--max-per-node", type=int, default=6,
                        help="max edges per node per relation (default 6)")
    parser.add_argument("--path", type=str, default=None,
                        help="graph sqlite path (default: default_graph_path())")
    parser.add_argument(
        "--standalone", action="store_true",
        help="operate the legacy standalone graph.sqlite instead of the "
             "unified brain.db (offline / debugging). Default: unified store.")
    args = parser.parse_args(argv)

    # ONE-SYSTEM ADOPTION (BRV-01): by default this CLI now enriches the SAME
    # unified brain.db the running app reads, so freshly-extracted edges are
    # immediately live everywhere — not stranded in a separate staging
    # graph.sqlite that needs a later copy. --standalone (or an explicit
    # --path) keeps the old raw-sqlite behaviour for offline/debug runs.
    if args.path:
        path = Path(args.path)
        print(f"[edges] opening graph (explicit path): {path}")
        graph = MemoryGraph.open(path, standalone=True)
    elif args.standalone:
        path = default_graph_path()
        print(f"[edges] opening standalone graph.sqlite: {path}")
        graph = MemoryGraph.open(path, standalone=True)
    else:
        graph = MemoryGraph.open()  # unified brain.db (the default)
        backing = getattr(getattr(graph, "store", None), "path", "unified")
        print(f"[edges] opening UNIFIED brain store: {backing}")
    # Daemon-friendly: retry up to 5s on a momentary writer lock. Only the
    # standalone raw-sqlite handle exposes ._conn; the unified BrainStore
    # already sets its own busy_timeout in open(), so skip the poke there.
    conn = getattr(graph, "_conn", None)
    if conn is not None:
        try:
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass

    iso_before, total = _isolated_count(graph)
    pct_before = round(100.0 * iso_before / total, 1) if total else 0.0
    print(f"[edges] nodes={total} edges={graph.count_edges()} "
          f"isolated_before={iso_before}/{total} ({pct_before}%)")

    stats = extract_edges(graph,
                          sim_threshold=args.threshold,
                          max_edges_per_node=args.max_per_node)

    total_edges_after = graph.count_edges()
    density = round(total_edges_after / total, 2) if total else 0.0
    print(f"[edges] threshold={args.threshold} "
          f"similar_to={stats['similar_to']} realized_by={stats['realized_by']} "
          f"added={stats['added']}")
    print(f"[edges] edges_after={total_edges_after} "
          f"density(edges/node)={density}")
    print(f"[edges] ISOLATED {pct_before}% -> {stats['isolated_pct_after']}% "
          f"({iso_before} -> {stats['isolated_after']} of {total})")
    graph.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
