"""Tests for the brain diligence (anti-laziness) policy core."""
from __future__ import annotations

from personal_brain.diligence import (
    POLICY_VERSION,
    DiligenceVerdict,
    evaluate_diligence,
    _is_mandate_doc,
)


def test_clean_summary_with_no_claim_allows():
    v = evaluate_diligence(
        last_message="Investigated the bug; root cause is the off-by-one "
                     "in the token expiry check. Proposing a fix next.",
    )
    assert v.ok
    assert v.verdict == "allow"
    assert v.policy_version == POLICY_VERSION


def test_claim_without_proof_blocks():
    v = evaluate_diligence(
        last_message="Done — the feature is shipped and fully working.",
        session_signals={"ran_tests": False, "wrote_files": False},
    )
    assert not v.ok
    assert v.verdict == "block"
    codes = [x.code for x in v.violations]
    assert "CLAIM_WITHOUT_PROOF" in codes
    assert "BRAIN DILIGENCE GATE" in v.reason_text()


def test_claim_with_proof_signal_allows():
    # v2: proof satisfies the proof-demand; the anti-sycophancy tax also needs
    # a limitation / all-clear, so this proven claim carries an explicit one.
    v = evaluate_diligence(
        last_message="Done — endpoint returns 200 now; verified end-to-end.",
        session_signals={"ran_curl": True, "wrote_files": True},
    )
    assert v.ok, v.to_dict()


def test_claim_with_audit_table_allows():
    msg = (
        "Shipped.\n\n"
        "| Feature | Primitive | Runtime | UI | Live-verified |\n"
        "|---|---|---|---|---|\n"
        "| sync | ✓ | ✓ | ✓ | ✓ |\n"
    )
    v = evaluate_diligence(last_message=msg, session_signals={})
    assert v.ok, v.to_dict()
    assert v.checked["has_audit_table"] is True


def test_deferral_phrase_blocks():
    v = evaluate_diligence(
        last_message="Looks good. We can wire that up next session.",
        session_signals={"wrote_files": True},  # proof present, but deferral still blocks
    )
    assert not v.ok
    assert "DEFERRED_WORK" in [x.code for x in v.violations]


def test_leftover_marker_in_touched_file_blocks():
    v = evaluate_diligence(
        last_message="Refactored the parser.",
        touched_files=["app/parser.py"],
        file_contents={"app/parser.py": "def parse():\n    pass  # TODO(founder): finish\n"},
        session_signals={"wrote_files": True},
    )
    assert not v.ok
    codes = [x.code for x in v.violations]
    assert "LEFTOVER_MARKER" in codes


def test_clean_touched_file_with_proof_allows():
    v = evaluate_diligence(
        last_message="Refactored the parser; all tests green.",
        touched_files=["app/parser.py"],
        file_contents={"app/parser.py": "def parse():\n    return 42\n"},
        session_signals={"ran_tests": True},
    )
    assert v.ok, v.to_dict()


def test_verdict_serialization_round_trips():
    v = evaluate_diligence(
        last_message="done",
        session_signals={},
    )
    d = v.to_dict()
    assert set(d) >= {"verdict", "ok", "violations", "policy_version", "reason", "checked"}
    assert isinstance(d["violations"], list)
    assert d["verdict"] in ("allow", "block")


def test_proof_signals_surface_in_checked():
    v = evaluate_diligence(
        last_message="finished; nothing outstanding.",
        session_signals={"ran_tests": True},
    )
    assert v.checked["proof_signals"]["ran_tests"] is True
    # v2: proof satisfies the proof-demand + an all-clear satisfies the tax → allow
    assert v.ok


# ───────────── mandate-doc exemption for the leftover-marker scan ─────────────


def test_is_mandate_doc_exempts_governance_docs():
    # Rulebook files that DOCUMENT the banned markers are exempt…
    assert _is_mandate_doc("CLAUDE.md")
    assert _is_mandate_doc("claude.md")
    assert _is_mandate_doc("AGENTS.md")
    assert _is_mandate_doc("docs/FAILURE_LOG.md")
    assert _is_mandate_doc("C:/repo/CLAUDE.md")
    assert _is_mandate_doc("C:\\repo\\AGENTS.md")          # windows backslashes
    assert _is_mandate_doc("docs/agdr/AgDR-0001-foo.md")
    assert _is_mandate_doc("C:\\repo\\docs\\agdr\\x.md")   # windows agdr path
    # v2: the policy SOURCE files are exempt — matched by PATH SUFFIX (not
    # basename) — they DEFINE the marker literals, so scanning them self-blocks.
    assert _is_mandate_doc("src/personal_brain/diligence.py")
    assert _is_mandate_doc("C:/repo/personal-brain-mcp/src/personal_brain/diligence.py")
    assert _is_mandate_doc("tools/anti_laziness_gate.py")
    assert _is_mandate_doc("personal-brain-mcp/tests/test_diligence.py")
    # …suffix-match, so a similarly-NAMED non-policy file is NOT exempt — this
    # guards against widening the exemption surface (Copilot review on #261):
    assert not _is_mandate_doc("app/diligence.py")
    assert not _is_mandate_doc("src/app/anti_laziness_gate.py")
    # …and real code/work files are NOT exempt.
    assert not _is_mandate_doc("app/foo.py")
    assert not _is_mandate_doc("README.md")                # not a mandate doc
    assert not _is_mandate_doc("docs/ROADMAP.md")
    assert not _is_mandate_doc("")
    assert not _is_mandate_doc(None)


def test_mandate_doc_with_markers_is_not_flagged():
    """CLAUDE.md quotes FIXME(later)/FOUNDER:/TODO(founder) as examples — the
    gate must NOT flag the rulebook (the recurring false positive)."""
    rulebook = (
        "## NO-OPEN-THREADS MANDATE\n"
        "Banned markers include TODO(founder), FIXME(later), FOUNDER:, "
        "verify in app — never leave these in code.\n"
    )
    v = evaluate_diligence(
        last_message="Refactored the parser; all tests green.",
        touched_files=["CLAUDE.md"],
        file_contents={"CLAUDE.md": rulebook},
        session_signals={"ran_tests": True},
    )
    assert v.ok, v.to_dict()
    assert "LEFTOVER_MARKER" not in [x.code for x in v.violations]
    assert v.checked["exempt_mandate_docs"] == ["CLAUDE.md"]


def test_agdr_doc_with_markers_is_not_flagged():
    v = evaluate_diligence(
        last_message="Documented the decision.",
        touched_files=["docs/agdr/AgDR-0099-policy.md"],
        file_contents={
            "docs/agdr/AgDR-0099-policy.md": "We ban FIXME(later) and FOUNDER: markers.\n"
        },
        session_signals={"wrote_files": True},
    )
    assert v.ok, v.to_dict()
    assert "LEFTOVER_MARKER" not in [x.code for x in v.violations]


def test_code_file_with_markers_still_flagged_alongside_mandate_doc():
    """The exemption is surgical: a real code file with the SAME marker is
    still flagged even when scanned together with an exempt rulebook file."""
    v = evaluate_diligence(
        last_message="Touched both files.",
        touched_files=["CLAUDE.md", "app/foo.py"],
        file_contents={
            "CLAUDE.md": "Banned: FIXME(later), FOUNDER:, TODO(founder).\n",
            "app/foo.py": "x = 1  # FIXME(later)\n",
        },
        session_signals={"ran_tests": True},
    )
    assert not v.ok
    leftovers = [x for x in v.violations if x.code == "LEFTOVER_MARKER"]
    # exactly one leftover finding — the code file, not the rulebook
    assert len(leftovers) == 1
    assert "app/foo.py" in leftovers[0].detail
    assert "CLAUDE.md" not in leftovers[0].detail


# ───────────── diligence-v2: honest-exit + anti-sycophancy tax ─────────────


def test_proven_claim_without_limitation_blocks():
    """v2 anti-sycophancy tax: a *proven* completion claim that states NO
    limitation / 'what I did not verify' is blocked — surface the downside."""
    v = evaluate_diligence(
        last_message="Done — it works now.",
        session_signals={"ran_tests": True},
    )
    assert not v.ok
    assert "CLAIM_WITHOUT_LIMITS" in [x.code for x in v.violations]


def test_proven_claim_with_limitation_allows():
    v = evaluate_diligence(
        last_message="Done and tests pass. One thing I did not verify: the restart path.",
        session_signals={"ran_tests": True},
    )
    assert v.ok, v.to_dict()
    assert v.checked["has_limitation"] is True


def test_honest_exit_allows_without_proof():
    """An honest exit is never blocked — honesty about an unfinished thing
    beats a fake 'done' (ImpossibleBench: an explicit honest exit cut
    cheating 54%→9%)."""
    v = evaluate_diligence(
        last_message="I could not verify the hook firing; blocked on your /hooks reload.",
    )
    assert v.ok, v.to_dict()
    assert v.checked["honest_exit"]


def test_policy_source_marker_is_exempt():
    """diligence.py holds the marker literals in CODE_MARKERS; editing the
    rulebook must not self-block the stop (the real regression this fixed)."""
    v = evaluate_diligence(
        last_message="Extended the policy.",
        touched_files=["src/personal_brain/diligence.py"],
        file_contents={"src/personal_brain/diligence.py":
                       "CODE_MARKERS = ('TODO(founder)',)  # rulebook literal\n"},
        session_signals={"wrote_files": True},
    )
    assert "LEFTOVER_MARKER" not in [x.code for x in v.violations]
    assert v.ok, v.to_dict()
