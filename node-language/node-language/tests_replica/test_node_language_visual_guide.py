"""Bounded conformance court for the simplified Node Language visual guide.

This court binds one reviewed visual artifact to reviewed authority, specification,
and handbook revisions. It proves document structure, visual coverage, source
links, and selected exact restatements. It does not prove product behavior,
literature truth, usability, security, performance, or release eligibility.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "NODE-LANGUAGE-VISUAL-GUIDE.md"
HANDBOOK = ROOT / "NODE-LANGUAGE-HANDBOOK.md"
SPEC = ROOT / "SPEC.md"
AUTHORITY = ROOT / "AUTHORITY.md"

REVIEWED_SHA256 = {
    "AUTHORITY.md": "5c66ec0304152d75ed54697387cce1293424f1f7e264f85ca13d9c1d985624c0",
    "SPEC.md": "13664a6dde239dca498c2820601377412eb615ee98ac3dc7b0d80e3803224cbd",
    "NODE-LANGUAGE-HANDBOOK.md": (
        "bfc02b5ddabdd8c0638b4d000e1b56e6f8192bacf90ed0377230d399f9ca2f00"
    ),
    "NODE-LANGUAGE-VISUAL-GUIDE.md": (
        "08a532d1cf1b1856528b71ac851f44fb853ab968cdcfd3b8b7ca8b266d450461"
    ),
}
PLATE = re.compile(r"^## Plate (?P<number>\d+): (?P<title>.+)$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)", re.DOTALL)
MERMAID = re.compile(r"```mermaid\n(?P<body>.*?)\n```", re.DOTALL)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_visual_guide_is_bound_to_reviewed_sources_and_declares_its_limit() -> None:
    for name, digest in REVIEWED_SHA256.items():
        assert _digest(ROOT / name) == digest, (
            f"{name} changed after the visual-guide review"
        )

    guide = _normalized(_text(GUIDE))
    assert "Status: WIP explanatory visual guide." in guide
    assert "not a second specification, a completion claim, or evidence" in guide
    assert "These are normative targets, not current pass claims." in guide
    assert "It does not prove:" in guide
    assert "or the diagrams are implemented, usable, secure, performant" in guide


def test_visual_guide_covers_the_full_requested_visual_model() -> None:
    guide = _text(GUIDE)
    plates = PLATE.findall(guide)
    assert [int(number) for number, _title in plates] == list(range(1, 13))
    diagrams = MERMAID.findall(guide)
    assert len(diagrams) >= 14
    for diagram in diagrams:
        assert re.search(r"^\s+accTitle: .+$", diagram, re.MULTILINE)
        assert re.search(r"^\s+accDescr: .+$", diagram, re.MULTILINE)

    required = (
        "The One Physical Block",
        "One Root, Four Lawful Views",
        "Composition Is Scale, Not a Container Type",
        "A Wire Is A Real Editable Relation",
        "The Properties Rail Is Also A Composition",
        "The Catalogue Contains Preassembled Building Blocks",
        "One Application, Not Separate Dashboards",
        "A Gesture Travels Through One Governed Pipeline",
        "WIP, Shared, And Published Are Revision Views",
        "Adapters Are Narrow Doors, Not The Building",
        "How To Tell A Real Node-Native Feature From A Shell",
        "Source And Proof Chain",
    )
    assert tuple(title for _number, title in plates) == required


def test_visual_guide_preserves_core_language_invariants() -> None:
    guide = _normalized(_text(GUIDE))
    specification = _normalized(_text(SPEC))
    anchors = (
        "Cell { id: CellId link0: CellId link1: CellId atom: Bytes }",
        "Opening a composition changes the active scope.",
        "The catalogue is the higher-level constraint layer.",
        "The right rail is not a hard-coded JSON report.",
        "The visible cable is a presentation of the relation root and its explicit incidences.",
        "Brain, Cockpit, Grand Map, domains, sessions, website, governance, and design system are openable regions and lenses of the same root graph.",
        "Unknown adapters and actions fail closed.",
    )
    for anchor in anchors:
        assert anchor in guide

    forbidden = (
        "Cell kind",
        "Group kind",
        "Session kind",
        "Wire kind",
        "physical node kinds",
    )
    for phrase in forbidden:
        if phrase == "physical node kinds":
            assert guide.count(phrase) == 1
        else:
            assert phrase not in guide

    spec_anchors = (
        "The application itself is the top composition.",
        "A visible wire is a lens over an actual relation and its incidences.",
        "A property or parameter is not an inline field.",
        "Raw Cell construction is a Floor privilege, not the ordinary composer API.",
    )
    for anchor in spec_anchors:
        assert anchor in specification


def test_visual_guide_preserves_authority_and_interaction_boundaries() -> None:
    guide = _text(GUIDE)
    normalized = _normalized(guide)
    assert "### Precedence Index" in guide
    assert "### Controlling Sources" not in guide
    assert "AUTHORITY.md) alone defines the complete active precedence" in guide
    assert "Node Language Handbook" in guide
    assert "It is not a controlling source" in normalized
    precedence_section = guide.split(
        "### Precedence Index", 1
    )[1].split("### Explanatory Artifact", 1)[0]
    precedence = (
        "Current explicit founder decisions",
        "SPEC.md",
        "Workspace Standard",
        "Released detailed protocol",
        "Grand Map source graph",
        "Revision-bound implementation evidence",
        "Research and adversarial evidence",
    )
    positions = [precedence_section.index(item) for item in precedence]
    assert positions == sorted(positions)

    assert "Committed selection,\nfocus" in guide
    assert "active scope are\nauthoritative graph-held relations" in guide
    assert "the browser\ncannot own or grant them" in guide
    assert "Local selection, pan, zoom, marquee, and scope\nnavigation" not in guide
    assert (
        "Hashes and raw identities\nappear only when the authorised Govern/Floor "
        "lens, audience, scope, and grant\npermit them."
    ) in guide
    assert "A user request can seek access but cannot broaden authority." in guide
    assert "unless the user asks for them" not in guide


def test_visual_guide_keeps_default_panels_separate() -> None:
    guide = _text(GUIDE)
    assert 'P7["Access"]' in guide
    assert 'P8["Evidence"]' in guide
    assert 'P9["Floor"]' in guide
    assert "Access and Evidence" not in guide


def test_visual_guide_performance_targets_match_the_specification() -> None:
    guide = _text(GUIDE)
    specification = _normalized(_text(SPEC))
    pairs = (
        ("p95 frame <= 16.7 ms", "p95 <= 16.7 ms"),
        ("same frame", "same-frame selection feedback"),
        ("p95 <= 100 ms", "local mutation acknowledgement <= 100 ms"),
        ("p95 <= 150 ms", "bounded scope entry <= 150 ms"),
        ("no long task over 50 ms", "no steady-state long task over 50 ms"),
    )
    for guide_anchor, spec_anchor in pairs:
        assert guide_anchor in guide
        assert spec_anchor in specification


def test_visual_guide_local_links_resolve_and_sources_are_classified() -> None:
    guide = _text(GUIDE)
    for raw_target in MARKDOWN_LINK.findall(guide):
        target = raw_target.strip()
        if target.startswith(("https://", "http://", "#")):
            continue
        relative = unquote(target.split("#", 1)[0])
        if relative:
            assert (ROOT / relative).resolve().exists(), (
                f"visual-guide link does not resolve: {target}"
            )

    assert "### Precedence Index" in guide
    assert "### Explanatory Artifact" in guide
    assert "### Accepted Detailed Design" in guide
    assert "### Research Lineage, Not ArchHub Authority" in guide
    assert "External source currency must still\n  be reverified at release." in guide
    reviewed_external = (
        "https://www.w3.org/TR/2026/CRD-pointerevents3-20260522/",
        "https://www.designtokens.org/tr/2025.10/format/",
    )
    handbook = _text(HANDBOOK)
    for url in reviewed_external:
        assert url in handbook
        assert url in guide


def test_visual_guide_remains_ascii_and_does_not_claim_product_acceptance() -> None:
    raw = GUIDE.read_bytes()
    guide = raw.decode("ascii")
    normalized = _normalized(guide)
    assert len(re.findall(r"\b[\w'-]+\b", guide)) >= 2_000
    assert "complete, published, deployed, or patentable" in normalized
    assert "current pass claims" in guide
    assert "Current truth must come from revision-bound evidence" in guide
    assert "cannot prove them" in guide
    assert "does not prove\nthe Mermaid syntax parses" in guide
