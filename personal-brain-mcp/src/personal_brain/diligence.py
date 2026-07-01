"""Diligence policy — the brain's anti-laziness enforcement core.

The brain OWNS the definition of "lazy" so every client (Claude Code,
Cursor, Codex, Gemini, ArchHub Composer) is held to the same bar, and
the bar syncs across devices like any other brain fact. The Stop-hook
gate (`tools/anti_laziness_gate.py`) gathers evidence from a session and
calls `evaluate_diligence`; a `block` verdict makes the hook refuse to
let the agent stop — feeding the violations back so it must DO THE WORK.

This is the ANTI-LIE + NO-OPEN-THREADS + PROTOTYPE-FIRST mandates made
mechanical: an AI cannot *claim* completion here, it must *prove* it.

Pure functions only — no I/O, no network. Fully unit-testable. The hook
and the `brain.enforce_diligence` MCP tool are the I/O shells around it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

POLICY_VERSION = "diligence-v2"

# Words that assert completion. Their presence triggers the proof demand.
COMPLETION_CLAIMS = (
    "shipped", "done", "complete", "completed", "delivered",
    "finished", "wired up", "fully working", "it works now",
    "good to go", "ready to ship", "all set",
)

# Phrases that defer work to "later" / the founder / a future session.
# NO-OPEN-THREADS + PROTOTYPE-FIRST ban these outright.
DEFERRAL_PHRASES = (
    "next session", "i'll test it later", "ill test it later",
    "i will test it later", "you can test", "you can wire",
    "we can wire that up", "we can wire it up", "leaving a todo",
    "leaving a todo for", "todo for the founder", "for you to verify",
    "founder to test", "founder to confirm", "founder to click",
    "verify in app later", "i'll wire that up next",
    "left as a follow-up", "out of scope for now, will do",
)

# Markers that must never survive in code touched this session.
CODE_MARKERS = (
    "TODO(founder)", "FOUNDER:", "FIXME(later)", "XXX(later)",
    "verify in app", "for testing only", "placeholder — remove",
)

# Mandate / governance docs DOCUMENT the banned markers above as examples
# (CLAUDE.md & the AgDR docs literally quote `TODO(founder)`, `FIXME(later)`,
# `FOUNDER:`, …). They are the rulebook, not work-product with stray markers,
# so the leftover-marker scan must skip them — otherwise the Stop-hook gate
# false-blocks the rulebook on every turn, one marker per stop, forever.
# This exemption applies ONLY to the marker scan; every other (code/work)
# file is still scanned in full.
_MANDATE_DOC_BASENAMES = frozenset({
    "claude.md", "agents.md", "failure_log.md",
})

# The policy SOURCE files DEFINE/exercise the banned markers as string data
# (diligence.py's CODE_MARKERS, the gate itself, and the policy test), so the
# marker scan skips them — else editing the rulebook self-blocks the stop.
# Matched by PATH SUFFIX, NOT basename, so an unrelated file that merely shares
# the name (e.g. `app/diligence.py`) is NOT exempted and the scan still catches
# real markers there. Marker scan ONLY; every other check still applies.
_POLICY_SOURCE_SUFFIXES = (
    "personal_brain/diligence.py",
    "tools/anti_laziness_gate.py",
    "tests/test_diligence.py",
)


def _is_mandate_doc(path: Any) -> bool:
    """True if `path` is a mandate/governance doc that legitimately quotes the
    banned markers (CLAUDE.md, AGENTS.md, FAILURE_LOG.md, or anything under a
    `docs/agdr/` directory). getattr/try-safe: any odd input → not exempt."""
    try:
        norm = str(path or "").replace("\\", "/").lower()
    except Exception:
        return False
    if not norm:
        return False
    basename = norm.rsplit("/", 1)[-1]
    if basename in _MANDATE_DOC_BASENAMES:
        return True
    if "/docs/agdr/" in norm or norm.startswith("docs/agdr/"):
        return True
    # policy sources — matched by PATH SUFFIX (not basename) so a stray file
    # that merely shares the name (app/diligence.py) is NOT exempted.
    if any(norm.endswith(sfx) for sfx in _POLICY_SOURCE_SUFFIXES):
        return True
    return False

# Evidence that real verification happened this session.
PROOF_SIGNAL_KEYS = (
    "ran_tests", "ran_curl", "wrote_files", "took_screenshot",
    "ran_build", "started_server",
)

# An ANTI-LIE audit table looks like a markdown table mentioning the
# verification columns. If a completion claim ships WITH this, we trust it.
_AUDIT_HINT = re.compile(
    r"\|.*(primitive|runtime|live[- ]?verif|ui\s*✓|cross[- ]?process)",
    re.IGNORECASE,
)

# ── diligence-v2: honest-exit + anti-sycophancy limitation tax ──────────
# The 8-rule anti-false-done protocol (30.KNOWLEDGE/strategy/anti-false-done-
# protocol.md, web-verified against the reward-hacking / shortcut-learning /
# Goodhart / cognitive-miser literatures) adds two machine-checkable rules on
# top of v1's proof demand:
#   • HONEST EXIT is first-class — an agent that truthfully says "I couldn't /
#     didn't verify X / blocked on your sign-in" is NEVER blocked; honesty
#     about an unfinished thing beats a fake "done" (ImpossibleBench: an
#     explicit honest exit cut cheating 54%→9%). (protocol rule 2)
#   • ANTI-SYCOPHANCY LIMITATION TAX — a *proven* completion claim must also
#     surface a limitation / "what it did NOT verify" (or an explicit
#     all-clear). Sycophancy suppresses bad news to look done; this forces it
#     out. (protocol rules 4/6)
# The remaining protocol rules are already v1 (proof=rule 3, deferral+markers=
# rules 5/7) or are NOT text-checkable at stop-time (freeze-target, construct
# validity) — those live in the COURT (brain.tree_court's independent lenses),
# not here. This gate is deliberately conservative: honest exits pass freely
# and any limitation/all-clear phrase satisfies the tax, so it surfaces the
# missing downside without over-gating a genuinely-complete turn.

# Honest-exit language — a truthful "not done / couldn't / needs you". A
# POSITIVE signal: never blocked, and it satisfies the limitation tax.
HONEST_EXIT_PHRASES = (
    "i could not", "i couldn't", "could not verify", "couldn't verify",
    "i was unable", "unable to verify", "blocked on", "i did not verify",
    "i didn't verify", "did not verify", "didn't verify", "not verified",
    "haven't verified", "have not verified", "could not confirm",
    "cannot verify", "underspecified", "needs your", "needs founder",
    "escalat", "honest exit", "i'm stopping here because",
    "im stopping here because", "not yet verified", "i have not verified",
)

# A stated limitation / caveat / "what I did not check". Satisfies the tax.
LIMITATION_MARKERS = (
    "limitation", "caveat", "did not verify", "didn't verify",
    "not verified", "did not test", "didn't test", "did not check",
    "didn't check", "one thing", "one caveat", "the one thing", "note:",
    "however,", "won't like", "wont like", "gap:", "what i did not",
    "what i didn't", "not tested", "unverified", "honest limit",
)

# Explicit all-clear — a positive assertion that everything was verified and
# nothing is outstanding. Also satisfies the tax.
ALL_CLEAR_PHRASES = (
    "verified end-to-end", "verified end to end", "nothing outstanding",
    "no open threads", "all checks pass", "everything verified",
    "fully verified", "zero open", "no caveats", "nothing deferred",
)


def _has_any(text_lower: str, needles: tuple[str, ...]) -> Optional[str]:
    """Return the first needle found in text_lower, else None."""
    for n in needles:
        if n in text_lower:
            return n
    return None


@dataclass
class Violation:
    code: str
    detail: str
    severity: str = "block"   # "block" | "warn"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class DiligenceVerdict:
    verdict: str                       # "allow" | "block"
    violations: list[Violation] = field(default_factory=list)
    policy_version: str = POLICY_VERSION
    checked: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict == "allow"

    def reason_text(self) -> str:
        """Human-readable block reason fed back to the model."""
        if self.ok:
            return ""
        lines = [
            "BRAIN DILIGENCE GATE — you are not done. Do the work, don't stop:",
        ]
        for v in self.violations:
            if v.severity == "block":
                lines.append(f"  ✗ [{v.code}] {v.detail}")
        lines.append(
            "Close every thread: run the test / curl / build, write the "
            "files, capture the proof, then summarize with an honest "
            "audit. Only then end the turn."
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "ok": self.ok,
            "violations": [v.to_dict() for v in self.violations],
            "policy_version": self.policy_version,
            "checked": self.checked,
            "reason": self.reason_text(),
        }


def _first_claim(text_lower: str) -> Optional[str]:
    for w in COMPLETION_CLAIMS:
        if w in text_lower:
            return w
    return None


def _first_deferral(text_lower: str) -> Optional[str]:
    for p in DEFERRAL_PHRASES:
        if p in text_lower:
            return p
    return None


def evaluate_diligence(
    *,
    last_message: str,
    touched_files: Optional[list[str]] = None,
    file_contents: Optional[dict[str, str]] = None,
    session_signals: Optional[dict[str, Any]] = None,
) -> DiligenceVerdict:
    """Decide whether an agent has earned the right to stop.

    Args:
      last_message:   the agent's final assistant turn (plain text).
      touched_files:  paths edited/written this session.
      file_contents:  optional {path: content} for marker scanning. If a
                      path in touched_files is absent here, it's skipped.
      session_signals: evidence dict, e.g. {"ran_tests": True,
                      "ran_curl": False, "wrote_files": True, ...}.

    Returns a DiligenceVerdict; `block` means "keep working".
    """
    msg = last_message or ""
    low = msg.lower()
    sig = session_signals or {}
    violations: list[Violation] = []

    claim = _first_claim(low)
    has_audit = bool(_AUDIT_HINT.search(msg))
    proven = any(bool(sig.get(k)) for k in PROOF_SIGNAL_KEYS)

    # diligence-v2 signals: honest exit (positive) + limitation acknowledgment.
    honest_exit = _has_any(low, HONEST_EXIT_PHRASES)
    has_limitation = bool(
        honest_exit
        or has_audit
        or _has_any(low, LIMITATION_MARKERS)
        or _has_any(low, ALL_CLEAR_PHRASES)
    )

    # 1) Claimed completion without proof AND without an audit table.
    if claim and not proven and not has_audit:
        violations.append(Violation(
            code="CLAIM_WITHOUT_PROOF",
            detail=(
                f"Claimed '{claim}' but this session shows no verification "
                f"artifact (no test run, curl, build, server start, file "
                f"write, or screenshot) and no ANTI-LIE audit table. "
                f"Tests/curl/screenshot or demote the wording."
            ),
            severity="block",
        ))

    # 1b) diligence-v2 anti-sycophancy tax: a *proven* completion claim must
    #     also surface a limitation / "what I did not verify" (or an explicit
    #     all-clear). Suppressing the downside to look "done" is the exact
    #     sycophancy the protocol bans. An honest exit IS a stated limit, so
    #     it is never taxed. Fires only when proof exists (else rule 1 covers
    #     it) — so a genuinely-verified turn just names its one caveat.
    if claim and proven and not has_limitation:
        violations.append(Violation(
            code="CLAIM_WITHOUT_LIMITS",
            detail=(
                f"Claimed '{claim}' with proof but stated NO limitation or "
                f"'what I did not verify'. Anti-sycophancy: name the one "
                f"thing you're unsure about / didn't check, or give an "
                f"explicit all-clear (verified end-to-end, nothing "
                f"outstanding)."
            ),
            severity="block",
        ))

    # 2) Deferral language — work pushed to later / the founder.
    deferral = _first_deferral(low)
    if deferral:
        violations.append(Violation(
            code="DEFERRED_WORK",
            detail=(
                f"Deferral phrase '{deferral}' — NO-OPEN-THREADS forbids "
                f"leaving work for later or for the founder. Do it now."
            ),
            severity="block",
        ))

    # 3) Leftover markers in code touched this session.
    #    Mandate/governance docs (CLAUDE.md, AGENTS.md, docs/agdr/*,
    #    FAILURE_LOG.md) DOCUMENT these markers as examples — skip them so the
    #    gate doesn't false-flag the rulebook. The scan stays fully active for
    #    every other (code/work) file.
    if file_contents:
        for path, content in file_contents.items():
            if not content:
                continue
            if _is_mandate_doc(path):
                continue
            for marker in CODE_MARKERS:
                if marker in content:
                    violations.append(Violation(
                        code="LEFTOVER_MARKER",
                        detail=f"'{marker}' left in {path} — resolve before stopping.",
                        severity="block",
                    ))
                    break

    verdict = "block" if any(v.severity == "block" for v in violations) else "allow"
    return DiligenceVerdict(
        verdict=verdict,
        violations=violations,
        policy_version=POLICY_VERSION,
        checked={
            "claim": claim,
            "has_audit_table": has_audit,
            "proven": proven,
            "proof_signals": {k: bool(sig.get(k)) for k in PROOF_SIGNAL_KEYS},
            "honest_exit": honest_exit,
            "has_limitation": has_limitation,
            "touched_files": list(touched_files or []),
            "scanned_files": list((file_contents or {}).keys()),
            "exempt_mandate_docs": [
                p for p in (file_contents or {}) if _is_mandate_doc(p)
            ],
        },
    )
