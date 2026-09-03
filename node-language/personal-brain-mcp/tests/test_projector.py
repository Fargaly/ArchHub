"""BRV-09 — thinking-system projector (versioned brain governance → CLAUDE.md).

Proves: (1) brain MANDATE fragments compile to a CLAUDE.md artifact, and (2) a
mandate bump WITHOUT is_root_authority is REFUSED (founder-signed). Before this
work there was no projector module and `FragmentKind` lacked MANDATE / HOOK /
PRACTICE, so governance rules were hand-edited markdown — un-versioned and
un-signable.

RED on origin/main: `personal_brain.projector` does not exist and
`FragmentKind.MANDATE` is undefined → collection/import fails.
GREEN on the branch: the kinds + projector exist; mandates compile to the
artifact; the bump guard refuses without the founder.

Run: pytest -k projector -p no:cacheprovider
"""
from __future__ import annotations

import pytest

from personal_brain.models import FragmentKind
from personal_brain.storage import BrainStore
from personal_brain import projector as P


@pytest.fixture
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


# ─────────────────── FragmentKind now carries governance kinds ──────────


def test_fragment_kind_has_mandate_hook_practice():
    """BRV-09 enum extension — the three governance kinds exist with the
    expected wire values (the stable MCP contract)."""
    assert FragmentKind.MANDATE.value == "mandate"
    assert FragmentKind.HOOK.value == "hook"
    assert FragmentKind.PRACTICE.value == "practice"
    assert set(P.PROJECTED_KINDS) == {
        FragmentKind.MANDATE, FragmentKind.HOOK, FragmentKind.PRACTICE
    }


# ─────────────────── mandates compile to a CLAUDE.md artifact ───────────


def test_mandate_fragments_compile_to_claude_md(store, tmp_path):
    """ACCEPTANCE part 1: brain MANDATE (and HOOK/PRACTICE) fragments compile to
    a CLAUDE.md projection — both as a string and as a written file artifact."""
    P.record_fragment(
        store, kind=FragmentKind.MANDATE, title="Engineering Mandate",
        body="Every problem dives to the ROOT. No quick patches, no stitching.")
    P.record_fragment(
        store, kind=FragmentKind.MANDATE, title="Anti-Lie Mandate",
        body="Code in modules is not shipped. Run the lie-check before 'done'.")
    P.record_fragment(
        store, kind=FragmentKind.HOOK, title="Brain Context Inject",
        body="UserPromptSubmit hook routes to brain.context on every prompt.")
    P.record_fragment(
        store, kind=FragmentKind.PRACTICE, title="Secrets Are Refs Only",
        body="Never inline a secret value; use op:// references resolved at call time.")

    md = P.project_claude_md(store)

    # The artifact is a real CLAUDE.md projection carrying the mandate content.
    assert md.lstrip().startswith("#")                      # markdown doc
    assert "MANDATES" in md                                 # the mandate section
    assert "Engineering Mandate" in md
    assert "dives to the ROOT" in md                        # the mandate BODY, compiled
    assert "Anti-Lie Mandate" in md
    assert "HOOKS" in md and "Brain Context Inject" in md
    assert "PRACTICES" in md and "op://" in md
    # Versioned: first codification renders as v1.
    assert "— v1" in md
    # Self-describing provenance footer (auditable compile).
    assert "active governance fragments" in md

    # And it writes to a real file artifact (distinct from the human CLAUDE.md).
    out = tmp_path / "CLAUDE.brain.md"
    written = P.write_projection(store, path=out)
    assert written.exists()
    disk = written.read_text(encoding="utf-8")
    assert "Engineering Mandate" in disk and "dives to the ROOT" in disk


def test_projection_is_deterministic_and_ordered(store):
    """Mandates render before hooks before practices; the COMPILED CONTENT is
    stable across compiles (only the self-describing compile-timestamp footer,
    which is intentionally live, differs)."""
    P.record_fragment(store, kind=FragmentKind.PRACTICE, title="P One", body="practice one body text")
    P.record_fragment(store, kind=FragmentKind.HOOK, title="H One", body="hook one body text")
    P.record_fragment(store, kind=FragmentKind.MANDATE, title="M One", body="mandate one body text")

    def _body(md: str) -> str:
        # Drop the trailing live-timestamp footer line; everything above it is
        # the deterministic compiled content.
        return md.split("<!-- projection:", 1)[0]

    md = P.project_claude_md(store)
    assert _body(P.project_claude_md(store)) == _body(md)   # content deterministic
    assert md.index("MANDATES") < md.index("HOOKS") < md.index("PRACTICES")


# ─────────────────── the founder-signed bump guard (refusal) ────────────


def test_mandate_bump_without_root_authority_is_refused(store):
    """ACCEPTANCE part 2: a bump of an existing MANDATE WITHOUT
    is_root_authority is REFUSED — a MANDATE is the founder's word."""
    # v1 codification is allowed (seed the brain).
    P.record_fragment(
        store, kind=FragmentKind.MANDATE, title="Roadmap Mandate",
        body="ONE roadmap. docs/ROADMAP.md is the single source of truth.")
    assert P.current_version(store, owner_user="founder", title="Roadmap Mandate") == 1

    # v2 bump WITHOUT the founder is refused.
    with pytest.raises(PermissionError) as ei:
        P.bump_mandate(
            store, title="Roadmap Mandate",
            body="weakened: two roadmaps are fine now")
    assert "is_root_authority" in str(ei.value)

    # The refusal left the brain untouched — still v1, original body.
    assert P.current_version(store, owner_user="founder", title="Roadmap Mandate") == 1
    latest = P.latest_versions(store, owner_user="founder")
    roadmap = latest[P._mandate_key("Roadmap Mandate")]
    assert "single source of truth" in roadmap.text
    assert "weakened" not in roadmap.text


def test_mandate_bump_with_root_authority_versions_and_signs(store):
    """The founder CAN bump: with is_root_authority=True it creates v2, marks it
    founder-signed, and the projection shows the new version (deduped)."""
    P.record_fragment(
        store, kind=FragmentKind.MANDATE, title="Session Close Mandate",
        body="Commit, document, restart, verify live before 'done'.")
    f2 = P.bump_mandate(
        store, title="Session Close Mandate",
        body="Commit, document, restart, CDP-verify, THEN report done.",
        is_root_authority=True)
    assert (f2.extra or {})["version"] == 2
    assert (f2.extra or {})["signed_by_root"] is True

    md = P.project_claude_md(store)
    # Latest version only — one heading, v2, founder-signed badge, new body.
    assert md.count("### Session Close Mandate") == 1
    assert "— v2 · founder-signed" in md
    assert "CDP-verify" in md


def test_hook_and_practice_bumps_do_not_require_founder(store):
    """HOOK / PRACTICE are routine — they version freely without the gate (only
    MANDATE is founder-signed)."""
    P.record_fragment(store, kind=FragmentKind.HOOK, title="Memory Write", body="PostToolUse routes to brain.write.")
    f2 = P.record_fragment(store, kind=FragmentKind.HOOK, title="Memory Write",
                           body="PostToolUse routes to brain.write with ADD/UPDATE/DELETE.")
    assert (f2.extra or {})["version"] == 2          # no PermissionError

    P.record_fragment(store, kind=FragmentKind.PRACTICE, title="Run Suite", body="Run the suite before push.")
    f2p = P.record_fragment(store, kind=FragmentKind.PRACTICE, title="Run Suite",
                            body="Run the FULL suite before push (not just targeted).")
    assert (f2p.extra or {})["version"] == 2


def test_retire_mandate_requires_founder_and_drops_from_projection(store):
    """Retiring a mandate is a founder act; once retired it leaves the
    projection — but its history rows remain (never deleted)."""
    P.record_fragment(store, kind=FragmentKind.MANDATE, title="Temp Mandate", body="A temporary rule body.")
    with pytest.raises(PermissionError):
        P.retire_fragment(store, title="Temp Mandate")            # no founder → refused
    P.retire_fragment(store, title="Temp Mandate", is_root_authority=True)
    md = P.project_claude_md(store)
    assert "Temp Mandate" not in md                                # dropped from active projection
    # History preserved: the row still exists, just inactive.
    all_active_incl = P.latest_versions(store, owner_user="founder", active_only=False)
    assert P._mandate_key("Temp Mandate") in all_active_incl
