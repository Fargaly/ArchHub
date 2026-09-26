"""Memory extractor — turns approved chat samples into fact-ops.

v1 (this file) is heuristic + tag-template based. It catches a small
class of explicit assertions and converts them to ADD/UPDATE/NOOP
operations against the user's existing memory_facts.

v2 (deferred) calls an instructor LLM with a structured-output prompt
to extract richer facts. Shape stays the same so swap is in-place.

The point of v1 is to validate the writer pipeline + give the Memory
page real counters before we burn LLM calls on extraction.
"""
from __future__ import annotations

import re
from typing import Optional

import db


# Patterns that signal an explicit user-stated fact. Order matters —
# earlier patterns are more specific.
_EXPLICIT_PATTERNS = [
    # `/remember <fact>` slash-command — the strongest signal.
    re.compile(
        r"(?i)^\s*/remember\s+(?P<text>.+)$",
        re.MULTILINE,
    ),
    # "remember that X" / "remember: X"
    re.compile(
        r"(?i)\bremember\s*[:,]?\s*(?:that\s+)?(?P<text>.+?)(?:[.!?]|$)",
    ),
    # "my <role> is <thing>"
    re.compile(
        r"(?i)\bmy\s+(?P<predicate>\w+(?:\s+\w+){0,2})\s+is\s+(?P<object>[^.!?\n]+)",
    ),
    # "I use <tool>"
    re.compile(
        r"(?i)\bI\s+(?P<predicate>use|prefer|need|want)\s+(?P<object>[^.!?\n]+)",
    ),
]


def _existing_overlap(*, user_id: str, candidate: str) -> Optional[dict]:
    """Look for an existing fact that overlaps with the candidate so
    we can issue UPDATE instead of ADD when appropriate.

    Crude in v1: case-insensitive substring or shared keyword.
    """
    cand = (candidate or "").lower().strip()
    if not cand:
        return None
    existing = db.list_memory_facts(user_id=user_id, limit=200)
    for f in existing:
        t = (f.get("text") or "").lower()
        if not t:
            continue
        # Tight overlap: candidate is substring or vice versa
        if cand in t or t in cand:
            return f
        # Shared meaningful tokens (4+ chars, both have >=2 in common)
        a = {w for w in re.findall(r"\b\w{4,}\b", cand)}
        b = {w for w in re.findall(r"\b\w{4,}\b", t)}
        if len(a & b) >= max(2, min(len(a), len(b)) // 2):
            return f
    return None


def extract_ops(*, user_id: str, text: str) -> list[dict]:
    """Return a list of memory-op dicts. Heuristic v1.

    Caller (typically POST /v1/memory/extract) feeds these straight
    to memory_writer.apply_ops.
    """
    ops: list[dict] = []
    seen_texts: set[str] = set()
    for rx in _EXPLICIT_PATTERNS:
        for m in rx.finditer(text or ""):
            gd = m.groupdict()
            raw = (gd.get("text") or "").strip()
            if not raw:
                pred = (gd.get("predicate") or "").strip()
                obj  = (gd.get("object") or "").strip()
                if pred and obj:
                    raw = f"User {pred} {obj}"
            if not raw or raw.lower() in seen_texts:
                continue
            seen_texts.add(raw.lower())
            # Look for a fact to UPDATE / NOOP against.
            match = _existing_overlap(user_id=user_id, candidate=raw)
            if match is None:
                ops.append({"op": "ADD", "text": raw,
                             "confidence": 0.6,
                             "rationale": "extracted from chat"})
            else:
                # Same content? NOOP. Different? UPDATE.
                if match["text"].strip().lower() == raw.lower():
                    ops.append({
                        "op": "NOOP", "fact_id": match["id"],
                        "text": raw,
                        "rationale": "already known",
                    })
                else:
                    ops.append({
                        "op": "UPDATE", "fact_id": match["id"],
                        "text": raw, "confidence": 0.7,
                        "rationale": "refined from chat",
                    })
    return ops
