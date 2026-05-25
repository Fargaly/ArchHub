"""Decision extractor — docs/agdr/*.md → MemoryGraph.

AgDR-0042 slice 4/6 (D1·C). Parses every AgDR's YAML frontmatter +
Artifacts section and writes:

  kind=decision   — every AgDR record. Id: `agdr:NNNN`. Props carry
                    status, category, timestamp, founder-signoff.
  relation=builds_on    — decision → decision. EXTRACTED — directly
                          read from frontmatter `builds-on: [...]`.
  relation=supersedes   — decision → decision. EXTRACTED — read from
                          `supersedes: AgDR-NNNN` or `status: superseded
                          by AgDR-NNNN`.
  relation=rationale_for — decision → lib:cap:<type> OR lib:skill:<type>.
                            INFERRED — extracted from the Artifacts
                            section by string-matching code paths like
                            `app/workflows/nodes/host_typed.py` against
                            known library/registry types. Confidence
                            stays INFERRED because the match is
                            heuristic; the AgDR text could mention a
                            module without that module containing the
                            actual decision.

Yaml parsing is hand-rolled (no PyYAML dep) — only the small subset
of frontmatter shapes used by AgDR template is supported. Adding more
fields is a one-line _parse_yaml_block extension.
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


def _agdr_id(raw_id: str) -> str:
    """Normalise an AgDR token (`AgDR-0042` or `0042`) to a memory id."""
    m = _AGDR_ID_RE.search(raw_id or "")
    if m:
        return f"agdr:{m.group(1)}"
    n = (raw_id or "").strip().lstrip("0") or "0"
    return f"agdr:{int(n):04d}"


# ── tiny frontmatter parser ──────────────────────────────────────────


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_str). Empty dict when no fence."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text
    yaml_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:])
    return _parse_yaml_block(yaml_lines), body


_INLINE_LIST_RE = re.compile(r"\[(.*?)\]")


def _parse_yaml_block(lines: list[str]) -> dict:
    """Tiny subset YAML reader — `key: value` + `key: [a, b, c]` +
    multi-line `key: |` (treats as a single joined string). No nested
    dicts (AgDR template doesn't use them)."""
    out: dict = {}
    pending_key: Optional[str] = None
    pending_lines: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        # Continuation of a `key: |` block.
        if pending_key is not None and (raw.startswith("  ") or raw.startswith("\t")):
            pending_lines.append(raw.strip())
            continue
        if pending_key is not None:
            out[pending_key] = "\n".join(pending_lines).strip()
            pending_key = None
            pending_lines = []
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "|":
            pending_key = key
            continue
        # Inline list `[a, b, c]`.
        m = _INLINE_LIST_RE.match(value)
        if m:
            items = [s.strip().strip('"').strip("'")
                     for s in m.group(1).split(",") if s.strip()]
            out[key] = items
            continue
        # Bare string — strip quotes if any.
        out[key] = value.strip('"').strip("'")
    if pending_key is not None:
        out[pending_key] = "\n".join(pending_lines).strip()
    return out


# ── artifacts → library refs ─────────────────────────────────────────


# Capture every `app/...` path in a fenced Artifacts section. The
# section header convention is `## Artifacts` (per AgDR template).
_ARTIFACTS_RE = re.compile(
    r"^##\s*Artifacts\s*$(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_APP_PATH_RE = re.compile(r"app/[A-Za-z0-9_./]+\.py")
# `app/workflows/nodes/host_typed.py` → host_typed (no path, no .py)
_MODULE_BASENAME_RE = re.compile(r"([A-Za-z0-9_]+)\.py$")


def _artifact_modules(body: str) -> set[str]:
    """Return the set of module basenames mentioned in the Artifacts
    section of an AgDR body. Used to match against library/registry
    types — a registered type whose source module is referenced gets
    a `rationale_for` edge from the AgDR."""
    out: set[str] = set()
    for m in _ARTIFACTS_RE.finditer(body):
        section = m.group(1)
        for p in _APP_PATH_RE.findall(section):
            mb = _MODULE_BASENAME_RE.search(p)
            if mb:
                out.add(mb.group(1))
    return out


# ── supersedes parsing ───────────────────────────────────────────────


_SUPERSEDED_BY_RE = re.compile(
    r"superseded\s+by\s+(AgDR-\d{4})", re.IGNORECASE)


def _supersedes_targets(frontmatter: dict) -> list[str]:
    """Read both the `supersedes:` field and any `superseded by AgDR-N`
    in `status:` — surfaces both directions of the same relationship.
    Returns a list of agdr:NNNN ids the current AgDR supersedes."""
    out: list[str] = []
    raw = frontmatter.get("supersedes")
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str) and _AGDR_ID_RE.search(x):
                out.append(_agdr_id(x))
    elif isinstance(raw, str) and raw.strip() not in ("", "none", "None"):
        for m in _AGDR_ID_RE.finditer(raw):
            out.append(f"agdr:{m.group(1)}")
    return out


# ── main entry ───────────────────────────────────────────────────────


def extract_decisions(graph: MemoryGraph,
                       agdr_dir: Optional[Path | str] = None,
                       ) -> dict:
    """Walk every AgDR markdown file under `agdr_dir` (default
    docs/agdr/ in the repo root) and write decision nodes + edges.

    Idempotent.

    Returns counts: {decisions_added, builds_on_edges, supersedes_edges,
                      rationale_for_edges}.
    """
    if agdr_dir is None:
        agdr_dir = Path(__file__).resolve().parents[3] / "docs" / "agdr"
    agdr_dir = Path(agdr_dir)
    if not agdr_dir.is_dir():
        return {"decisions_added": 0, "builds_on_edges": 0,
                "supersedes_edges": 0, "rationale_for_edges": 0}

    # Snapshot known caps + skills so cross-source rationale edges
    # only emit against nodes that already exist (library extractor
    # ordering is the caller's problem).
    known_caps = {n.id for n in graph.all_nodes(kind="capability")}
    known_skills = {n.id for n in graph.all_nodes(kind="skill")}

    decision_nodes: list[MemoryNode] = []
    builds_on: list[MemoryEdge] = []
    supersedes: list[MemoryEdge] = []
    rationale_for: list[MemoryEdge] = []

    for p in sorted(agdr_dir.glob("AgDR-*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = _split_frontmatter(text)
        raw_id = fm.get("id") or p.stem  # fallback: filename without .md
        did = _agdr_id(raw_id)
        # Title line — first ATX heading after the frontmatter.
        title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = (title_match.group(1).strip() if title_match
                 else fm.get("id") or p.stem)
        decision_nodes.append(MemoryNode(
            id=did, kind="decision",
            label=title[:120],
            props={
                "agdr_id": raw_id,
                "status": fm.get("status") or "",
                "category": fm.get("category") or "",
                "timestamp": str(fm.get("timestamp") or ""),
                "founder_signoff": fm.get("founder-signoff") or "",
                "path": str(p.relative_to(agdr_dir.parents[1]))
                          if agdr_dir.parents[1] in p.parents else str(p),
            },
        ))

    # First add every decision node so cross-decision edges land cleanly.
    with graph.transaction():
        graph.add_nodes(decision_nodes)
        decision_ids = {n.id for n in decision_nodes}

        # Second pass: edges. Re-read each file (cheap; ~50 small mds).
        for p in sorted(agdr_dir.glob("AgDR-*.md")):
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            fm, body = _split_frontmatter(text)
            raw_id = fm.get("id") or p.stem
            did = _agdr_id(raw_id)

            # builds_on
            for target_raw in (fm.get("builds-on") or []):
                if not isinstance(target_raw, str):
                    continue
                if not _AGDR_ID_RE.search(target_raw):
                    continue
                tid = _agdr_id(target_raw)
                if tid == did:
                    continue
                if tid not in decision_ids:
                    continue
                builds_on.append(MemoryEdge(
                    source=did, target=tid,
                    relation="builds_on",
                    confidence=Confidence.EXTRACTED,
                ))

            # supersedes (frontmatter `supersedes:` + `status: superseded by`)
            for tid in _supersedes_targets(fm):
                if tid == did or tid not in decision_ids:
                    continue
                supersedes.append(MemoryEdge(
                    source=did, target=tid,
                    relation="supersedes",
                    confidence=Confidence.EXTRACTED,
                ))
            # Status string variant — `status: superseded by AgDR-NNNN`
            status_raw = fm.get("status") or ""
            for m in _SUPERSEDED_BY_RE.finditer(status_raw):
                tid = _agdr_id(m.group(1))
                if tid == did or tid not in decision_ids:
                    continue
                supersedes.append(MemoryEdge(
                    source=did, target=tid,
                    relation="supersedes",
                    confidence=Confidence.EXTRACTED,
                ))

            # rationale_for — Artifacts section module references mapped
            # to library/registry types whose source module matches.
            modules = _artifact_modules(body)
            for cap_id in known_caps | known_skills:
                # cap_id format: lib:cap:render.comfyui  → 'comfyui' or
                # 'render' could match. Resolve to source-module name:
                # the type's last dotted segment is the closest match
                # we get without source inspection.
                bare = cap_id.split(":")[-1]
                last_seg = bare.split(".")[-1] if "." in bare else bare
                if last_seg in modules:
                    rationale_for.append(MemoryEdge(
                        source=did, target=cap_id,
                        relation="rationale_for",
                        confidence=Confidence.INFERRED,
                        props={"matched_module": last_seg},
                    ))

        graph.add_edges(builds_on)
        graph.add_edges(supersedes)
        graph.add_edges(rationale_for)

    return {
        "decisions_added":    len(decision_nodes),
        "builds_on_edges":    len(builds_on),
        "supersedes_edges":   len(supersedes),
        "rationale_for_edges": len(rationale_for),
    }
