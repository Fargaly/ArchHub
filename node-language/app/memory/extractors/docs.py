"""Docs extractor — docs/*.md → MemoryGraph (Track C, AgDR-0042 sibling).

Plan: docs/CONTENT-ECOSYSTEM-2026-05-26.md section 4. Sister to
`app/memory/extractors/decisions.py`. Walks every top-level
`docs/*.md` (NOT recursive — `docs/agdr/`, `docs/adr/`,
`docs/archive/`, etc. are owned by their own extractors or are
historical fossils).

Writes:

  kind=document   — every top-level doc. Id: `doc:<slug>`. Props carry
                    title, word_count, mtime, path.
  relation=cites  — document → doc/agdr/cap when the doc text
                     references that artifact by stable id or path.
                     INFERRED — text pattern match, may overcite.

Idempotent — re-running on the same source replaces existing nodes
via MemoryGraph upsert semantics.

NB: This extractor is the brain-graph half of the docs pipeline. The
parallel half is `tools/doc_freshness.py` which writes the freshness
JSON; both share the same slug derivation rules (basename without .md).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

_APP = Path(__file__).resolve().parents[2]
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from memory.graph import (  # noqa: E402
    MemoryGraph, MemoryNode, MemoryEdge, Confidence,
)


# ── id helpers ───────────────────────────────────────────────────────


_AGDR_ID_RE = re.compile(r"AgDR-(\d{4})")
_ADR_ID_RE = re.compile(r"ADR-(\d{3,4})")
# Anything `docs/foo.md` or `docs/bar/baz.md` reference inside another doc.
_DOC_REF_RE = re.compile(r"docs/([A-Za-z0-9_./\-]+)\.md")
# Source-of-truth artefact paths, mirrors decisions.py.
_APP_PATH_RE = re.compile(r"app/[A-Za-z0-9_./\-]+\.py")


def _doc_id(slug: str) -> str:
    """`ROADMAP` → `doc:ROADMAP`; pre-normalised slug."""
    return f"doc:{slug}"


def _slug(p: Path) -> str:
    return p.stem  # filename without .md


# ── lightweight markdown parse (no external deps) ─────────────────────


_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _title_of(text: str, fallback: str) -> str:
    """First `# Heading` line; fall back to slug."""
    m = _H1_RE.search(text)
    if m:
        return m.group(1).strip()
    return fallback


def _word_count(text: str) -> int:
    return len(text.split())


def _references(text: str) -> set[str]:
    """All doc/agdr/adr references inside the body — set of stable ids."""
    refs: set[str] = set()
    for m in _AGDR_ID_RE.finditer(text):
        refs.add(f"agdr:{m.group(1)}")
    for m in _ADR_ID_RE.finditer(text):
        # ADR ids look like `adr:001`. Pad to 3 just like decisions.
        refs.add(f"adr:{int(m.group(1)):03d}")
    for m in _DOC_REF_RE.finditer(text):
        body = m.group(1)
        # Skip subdir refs (agdr/, adr/, archive/) — those go to their
        # own kinds. Only refs to top-level docs become doc:* edges.
        if "/" in body:
            continue
        refs.add(f"doc:{body}")
    return refs


# ── main entry ───────────────────────────────────────────────────────


def extract_docs(graph: MemoryGraph,
                 docs_dir: Optional[Path | str] = None,
                 ) -> dict:
    """Walk every top-level `docs/*.md` and write document nodes +
    `cites` edges to other docs/AgDRs.

    Idempotent.

    Returns counts: {documents_added, cites_edges}.
    """
    if docs_dir is None:
        # extractors/docs.py → app/memory/extractors/docs.py
        # parents[3] = repo root
        docs_dir = Path(__file__).resolve().parents[3] / "docs"
    docs_dir = Path(docs_dir)
    if not docs_dir.is_dir():
        return {"documents_added": 0, "cites_edges": 0}

    doc_nodes: list[MemoryNode] = []
    cites: list[MemoryEdge] = []
    raw_refs_per_doc: dict[str, set[str]] = {}

    # PASS 1 — enumerate every top-level *.md (skip nested dirs).
    for p in sorted(docs_dir.glob("*.md")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        slug = _slug(p)
        did = _doc_id(slug)
        title = _title_of(text, fallback=slug)
        try:
            mtime = int(p.stat().st_mtime)
        except OSError:
            mtime = 0
        doc_nodes.append(MemoryNode(
            id=did, kind="document",
            label=title[:120],
            props={
                "slug": slug,
                "path": f"docs/{p.name}",
                "title": title,
                "word_count": _word_count(text),
                "mtime": mtime,
            },
        ))
        raw_refs_per_doc[did] = _references(text)

    # PASS 2 — emit cites edges. Only land edges where the target node
    # exists in the current graph snapshot OR is another doc we're about
    # to add — same defensive pattern as decisions.py.
    known_decisions = {n.id for n in graph.all_nodes(kind="decision")}
    new_doc_ids = {n.id for n in doc_nodes}

    for did, refs in raw_refs_per_doc.items():
        for tgt in refs:
            if tgt == did:
                continue
            # doc → agdr edges valid if the decision exists.
            if tgt.startswith("agdr:") and tgt not in known_decisions:
                continue
            # doc → doc edges valid if the target is another doc.
            if tgt.startswith("doc:") and tgt not in new_doc_ids:
                continue
            # adr/* — currently no extractor mints `adr:*` ids; skip until
            # an ADR extractor lands.
            if tgt.startswith("adr:"):
                continue
            cites.append(MemoryEdge(
                source=did, target=tgt,
                relation="cites",
                confidence=Confidence.INFERRED,
            ))

    with graph.transaction():
        graph.add_nodes(doc_nodes)
        graph.add_edges(cites)

    return {
        "documents_added": len(doc_nodes),
        "cites_edges": len(cites),
    }
