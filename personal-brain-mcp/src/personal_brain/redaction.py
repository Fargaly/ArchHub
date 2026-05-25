"""Redaction — strip PII before a fragment crosses scope boundary upward.

Per AgDR-0044 Slice 7. Required for any promotion into community or
global scope. Two paths:

  1. Heuristic redactor (this module) — regex-based, deterministic, zero
     dependencies. Catches the obvious classes (emails, names, addresses,
     amounts, project/client identifiers, file paths, secrets).

  2. LLM redactor (optional) — invokes a critic model to do a deeper
     context-aware redaction. Wires through the same Redactor Protocol so
     consumers don't branch.

The redacted fragment carries a `redaction_policy_id` so audits can
trace which policy applied.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol


# ─────────────────────── Protocol ───────────────────────────────────────


class Redactor(Protocol):
    """Plug LLM critic here for deeper redaction."""

    policy_id: str

    def redact(self, text: str) -> tuple[str, list[str]]:
        """Return (redacted_text, list_of_findings_descriptions)."""
        ...


# ─────────────────────── heuristic redactor ────────────────────────────


# Pattern → category (used for finding descriptions). Order matters
# (more specific first).
_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # Secret keys (defense-in-depth even after strip_secrets in memory_gate)
    # Accepts both `sk_` (some providers) and `sk-` (Anthropic / OpenAI default).
    (re.compile(r"\b(sk|ghp|gho|ghu|ghs|ghr)[_\-][A-Za-z0-9_\-]{16,}"), "<secret-key>", "API key prefix"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}"), "<aws-key>", "AWS access key"),
    (re.compile(r"\bya29\.[A-Za-z0-9_-]+"), "<google-token>", "Google OAuth token"),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{6,}"), "<jwt>", "JWT"),

    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>", "email"),

    # Phone numbers (loose — international + national)
    (re.compile(r"\+?\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}\b"), "<phone>", "phone"),

    # SSN-like (very loose; conservative substitute is intentional)
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<id>", "SSN-like"),

    # IBAN
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"), "<iban>", "IBAN"),

    # Credit-card-ish
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "<card>", "card-like"),

    # Money amounts ($, €, £)
    (re.compile(r"\b(?:USD|EUR|GBP|AED|SAR|JPY)\s*\d[\d,]*\.?\d*"), "<amount>", "amount (ccy-prefix)"),
    (re.compile(r"[\$£€¥]\s*\d[\d,]*\.?\d*"), "<amount>", "amount (sign-prefix)"),

    # File paths (Windows + POSIX) — only when 3+ segments deep so we
    # don't redact every casual mention of "src/foo"
    (re.compile(r"\b[A-Za-z]:\\(?:[\w \-.]+\\){2,}[\w \-.]+"), "<path>", "Windows path"),
    (re.compile(r"\B/[\w\-.]+/[\w\-.]+/[\w\-.]+(?:/[\w\-.]+)*"), "<path>", "POSIX path"),

    # URLs (sweeps query strings that often contain tokens)
    (re.compile(r"https?://[^\s<>\"']{8,}"), "<url>", "URL"),

    # IP addresses
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>", "IP"),
]

# Project / client / customer name HEURISTIC — anything CAPITALISED with
# 4+ chars that's not an ALL_CAPS acronym. Rough — relies on consumers
# passing a `known_entities` list when possible for precision.
_PROPER_NAME_RE = re.compile(r"\b([A-Z][a-z]{3,}(?:[ -][A-Z][a-z]+)*)\b")


@dataclass
class RedactionReport:
    """What was redacted, why, and how much survived."""

    findings: list[str]
    redacted_chars: int
    original_chars: int
    policy_id: str

    @property
    def coverage(self) -> float:
        if self.original_chars == 0:
            return 1.0
        return self.redacted_chars / self.original_chars


class HeuristicRedactor:
    """Regex pipeline. Deterministic. Zero deps. Sub-ms per fragment."""

    policy_id: str = "heuristic-v1"

    def __init__(self, *, known_entities: Optional[list[str]] = None,
                 redact_proper_names: bool = True):
        self.known_entities = [e.lower() for e in (known_entities or [])]
        self.redact_proper_names = redact_proper_names

    def redact(self, text: str) -> tuple[str, list[str]]:
        if not text:
            return text, []
        findings: list[str] = []
        redacted = text

        # 1. Known entities first (firm name, client names, project codes)
        for ent in self.known_entities:
            if not ent:
                continue
            pat = re.compile(re.escape(ent), re.IGNORECASE)
            count = len(pat.findall(redacted))
            if count > 0:
                findings.append(f"{count}× known entity '{ent}' → <entity>")
                redacted = pat.sub("<entity>", redacted)

        # 2. Built-in patterns
        for pattern, placeholder, label in _PATTERNS:
            count = len(pattern.findall(redacted))
            if count > 0:
                findings.append(f"{count}× {label} → {placeholder}")
                redacted = pattern.sub(placeholder, redacted)

        # 3. Proper-name heuristic (best-effort)
        if self.redact_proper_names:
            proper_count = 0
            def _swap(m):
                nonlocal proper_count
                name = m.group(1)
                # Skip if name looks like a common technical noun:
                # don't redact e.g. "User", "Project", "Memory"
                if name.lower() in _COMMON_TECHNICAL_NOUNS:
                    return name
                proper_count += 1
                return "<name>"
            redacted = _PROPER_NAME_RE.sub(_swap, redacted)
            if proper_count:
                findings.append(f"{proper_count}× capitalised proper-noun → <name>")

        return redacted, findings


_COMMON_TECHNICAL_NOUNS = frozenset({
    "user", "project", "memory", "skill", "skills", "facts", "wiring",
    "secrets", "brain", "agent", "tool", "tools", "session", "trace",
    "founder", "team", "firm", "company", "global", "community",
    "anthropic", "openai", "google", "claude", "gpt", "gemini",
    "windows", "linux", "macos", "python", "javascript", "typescript",
    "revit", "autocad", "blender", "speckle", "notion", "github",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "summer", "winter", "spring", "autumn", "fall",
})


# ─────────────────────── promote pipeline ──────────────────────────────


def redact_fragment(
    fragment: dict[str, Any],
    *,
    redactor: Optional[Redactor] = None,
    known_entities: Optional[list[str]] = None,
) -> tuple[dict[str, Any], RedactionReport]:
    """Apply redaction to a fragment about to be promoted across scope.

    Mutates a COPY; original fragment untouched. Returns (redacted, report).
    """
    r = redactor or HeuristicRedactor(known_entities=known_entities)
    out = dict(fragment)

    findings: list[str] = []
    total_orig = 0
    total_red = 0

    for field in ("text", "subject", "object"):
        value = out.get(field)
        if not isinstance(value, str) or not value:
            continue
        total_orig += len(value)
        redacted_value, found = r.redact(value)
        total_red += sum(len(repl) for _, repl, _ in _PATTERNS) if found else 0
        if redacted_value != value:
            findings.extend(found)
            out[field] = redacted_value

    # body of a Skill
    if "body" in out and isinstance(out["body"], str):
        total_orig += len(out["body"])
        redacted_body, found = r.redact(out["body"])
        if redacted_body != out["body"]:
            findings.extend(found)
            out["body"] = redacted_body

    # provenance — preserve contributing_user as hash for audit but never
    # leak in the promoted fragment
    prov = dict(out.get("provenance") or {})
    contributing_user = prov.get("contributing_user")
    if contributing_user:
        prov["contributing_user_hash"] = hashlib.sha256(
            contributing_user.encode("utf-8")
        ).hexdigest()[:16]
        del prov["contributing_user"]
    prov["redaction_policy_id"] = r.policy_id
    prov["redacted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out["provenance"] = prov

    report = RedactionReport(
        findings=findings,
        redacted_chars=total_red,
        original_chars=total_orig,
        policy_id=r.policy_id,
    )
    return out, report
