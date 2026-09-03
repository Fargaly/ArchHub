"""Memory writer — applies Mem0-style ops to memory_facts.

The extractor emits a list of operations:

    [
      {"op": "ADD",    "text": "User prefers metric units"},
      {"op": "UPDATE", "fact_id": 17, "text": "User uses Revit 2024 + 2025"},
      {"op": "DELETE", "fact_id": 9,  "rationale": "Superseded by 23"},
      {"op": "NOOP",   "text": "User uses Revit",
                       "rationale": "Already known as fact 4"},
    ]

`apply_ops` walks the list inside a single transaction, persists each
op to memory_op_log, and returns the resulting fact_id (or None for
DELETE/NOOP). The redaction policy gate (`promote_to_shared`) lives
here too — it's the ONE place that converts private facts into
visibility='shared_*'.

Per ADR-002:
- Any visibility upgrade away from 'private' MUST pass redact_text.
- `confidence` floors apply on ADD (0.5 minimum).
- `text` is stripped + length-capped to 2000 chars to keep search fast.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import db


MAX_FACT_LEN = 2000
MIN_ADD_CONFIDENCE = 0.5


# ── Redaction ────────────────────────────────────────────────────────
# v1 is regex-based. v2 calls an instructor LLM with a redaction prompt
# (in agents/memory_redactor.py) but the calling shape stays the same.
_PII_PATTERNS = [
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
     "[email]"),
    # Phone numbers (loose)
    (re.compile(r"\+?\d[\d\s\-()]{7,}\d"), "[phone]"),
    # Absolute Windows / POSIX paths
    (re.compile(r"[A-Z]:\\[^\s\"']+"), "[path]"),
    (re.compile(r"/(?:home|Users)/[^\s\"']+"), "[path]"),
    # Bare IPs
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    # USD amounts > 100 (likely a project cost / client invoice)
    (re.compile(r"\$\s?[1-9]\d{2,}(?:[,.]\d+)?\b"), "[amount]"),
]

_CLIENT_NAME_HINTS = (
    "client:", "customer:", "owner:", "project owner:",
    "for client", "for customer",
)


def redact_text(text: str, *, policy: str = "transform") -> str:
    """Apply the configured redaction policy. Returns a redacted copy.

    `transform` policy (the only non-trivial one in v1):
      - Strip PII regex patterns (emails, phones, paths, IPs, amounts)
      - Drop lines containing client-name hints entirely (over-cut on
        purpose; reviewer can re-add what's safe)
      - Collapse repeated whitespace
    """
    if policy == "simple":
        return (text or "").strip()
    out = text or ""
    for rx, repl in _PII_PATTERNS:
        out = rx.sub(repl, out)
    out_lines = []
    for line in out.splitlines():
        low = line.lower()
        if any(h in low for h in _CLIENT_NAME_HINTS):
            continue
        out_lines.append(line)
    out = "\n".join(out_lines)
    # Collapse whitespace
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


# ── Op application ──────────────────────────────────────────────────
def _validate_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        raise ValueError("fact text required")
    if len(t) > MAX_FACT_LEN:
        t = t[:MAX_FACT_LEN].rstrip() + "…"
    return t


def _apply_add(*, user_id: str, op: dict,
                source_sample_id: Optional[int]) -> int:
    text = _validate_text(op.get("text", ""))
    confidence = max(MIN_ADD_CONFIDENCE,
                      float(op.get("confidence", 0.7)))
    fact_id = db.insert_memory_fact(
        user_id=user_id,
        text=text,
        subject=op.get("subject", ""),
        predicate=op.get("predicate", ""),
        object=op.get("object", ""),
        scope=op.get("scope", "user"),
        visibility="private",   # ADD always lands private; promotion is separate
        confidence=confidence,
        company_id=op.get("company_id"),
        project_id=op.get("project_id"),
        source_sample_id=source_sample_id,
    )
    db.log_memory_op(
        user_id=user_id, op="ADD", fact_id=fact_id,
        source_sample_id=source_sample_id,
        rationale=op.get("rationale", ""),
        after_text=text,
    )
    return fact_id


def _apply_update(*, user_id: str, op: dict,
                   source_sample_id: Optional[int]) -> int:
    fact_id = int(op.get("fact_id") or 0)
    if not fact_id:
        raise ValueError("UPDATE requires fact_id")
    existing = db.get_memory_fact(fact_id)
    if not existing or existing["user_id"] != user_id:
        raise ValueError(f"fact {fact_id} not owned by user")
    new_text = _validate_text(op.get("text") or existing["text"])
    new_conf = op.get("confidence")
    db.update_memory_fact(
        fact_id,
        text=new_text,
        confidence=(float(new_conf) if new_conf is not None else None),
        reinforce=True,
    )
    db.log_memory_op(
        user_id=user_id, op="UPDATE", fact_id=fact_id,
        source_sample_id=source_sample_id,
        rationale=op.get("rationale", ""),
        before_text=existing["text"], after_text=new_text,
    )
    return fact_id


def _apply_delete(*, user_id: str, op: dict,
                   source_sample_id: Optional[int]) -> None:
    fact_id = int(op.get("fact_id") or 0)
    if not fact_id:
        raise ValueError("DELETE requires fact_id")
    existing = db.get_memory_fact(fact_id)
    if not existing or existing["user_id"] != user_id:
        raise ValueError(f"fact {fact_id} not owned by user")
    db.delete_memory_fact(fact_id)
    db.log_memory_op(
        user_id=user_id, op="DELETE", fact_id=fact_id,
        source_sample_id=source_sample_id,
        rationale=op.get("rationale", ""),
        before_text=existing["text"],
    )


def _apply_noop(*, user_id: str, op: dict,
                 source_sample_id: Optional[int]) -> None:
    db.log_memory_op(
        user_id=user_id, op="NOOP",
        fact_id=op.get("fact_id"),
        source_sample_id=source_sample_id,
        rationale=op.get("rationale", "Already known"),
        before_text=op.get("text"),
    )


def apply_ops(*, user_id: str, ops: list,
               source_sample_id: Optional[int] = None) -> dict:
    """Apply a batch of memory ops.

    Returns: {"added": [ids], "updated": [ids], "deleted": [ids],
              "noop": int, "errors": [str]}.
    """
    added: list[int] = []
    updated: list[int] = []
    deleted: list[int] = []
    noop_count = 0
    errors: list[str] = []
    for op in (ops or []):
        op_name = (op.get("op") or "").upper()
        try:
            if op_name == "ADD":
                added.append(_apply_add(
                    user_id=user_id, op=op,
                    source_sample_id=source_sample_id))
            elif op_name == "UPDATE":
                updated.append(_apply_update(
                    user_id=user_id, op=op,
                    source_sample_id=source_sample_id))
            elif op_name == "DELETE":
                fid = int(op.get("fact_id") or 0)
                _apply_delete(user_id=user_id, op=op,
                                source_sample_id=source_sample_id)
                deleted.append(fid)
            elif op_name == "NOOP":
                _apply_noop(user_id=user_id, op=op,
                              source_sample_id=source_sample_id)
                noop_count += 1
            else:
                errors.append(f"unknown op: {op_name!r}")
        except Exception as ex:
            errors.append(f"{op_name}: {type(ex).__name__}: {ex}")
    return {
        "added":   added,
        "updated": updated,
        "deleted": deleted,
        "noop":    noop_count,
        "errors":  errors,
    }


# ── Promotion: private → collective ─────────────────────────────────
def promote_to_shared(*, fact_id: int, user_id: str,
                       access_policy: str = "public",
                       domain: str = "aec.general",
                       redaction_policy: str = "transform") -> int:
    """Promote a private fact to collective_memory after redaction.

    Per ADR-002 §"Privacy + redaction" the `transform` policy is the
    only acceptable policy for non-private writes. `simple` is rejected.
    """
    if redaction_policy != "transform":
        raise ValueError(
            "promote_to_shared requires redaction_policy='transform'")
    src = db.get_memory_fact(fact_id)
    if not src:
        raise ValueError(f"fact {fact_id} not found")
    if src["user_id"] != user_id:
        raise ValueError("fact not owned by promoter")
    redacted = redact_text(src["text"], policy="transform")
    if not redacted:
        raise ValueError(
            "redaction stripped all content — fact unsafe to promote")
    return db.promote_to_collective(
        fact_id=fact_id, contributing_user_id=user_id,
        redaction_policy=redaction_policy,
        access_policy=access_policy, domain=domain,
        redacted_text=redacted,
    )
