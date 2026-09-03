"""Bounded court for the Universal Cell 100-layer architecture document.

This court proves document structure, recursive question coverage, source
classification, local-link integrity, and selected constitutional boundaries.
It does not prove implementation, usability, security, performance, deployment,
release eligibility, literature truth, or patentability.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "NODE-LANGUAGE-100-LAYER-ARCHITECTURE.md"

LAYER = re.compile(
    r"^## Layer (?P<number>\d+): (?P<title>.+)$",
    re.MULTILINE,
)
STRATUM = re.compile(
    r"^# Stratum (?P<letter>[A-J]) - (?P<title>.+)$",
    re.MULTILINE,
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)", re.DOTALL)
REFERENCE = re.compile(r"\[(?P<identifier>[IE]\d{2})\]")
DECLARED_REFERENCE = re.compile(r"^\| (?P<identifier>[IE]\d{2}) \|", re.MULTILINE)
RECURSIVE_FIELDS = (
    "AUTHORITY",
    "WHAT",
    "WHY",
    "HOW",
    "WHO",
    "WHEN",
    "WHERE",
    "EXAMPLE",
    "FAILURE",
    "PROOF TARGET",
)

FIRST_TWENTY_TITLES = (
    "The Physical Cell",
    "Meaning From Released Protocols",
    "Relations And Wires",
    "Composition And Catalogue",
    "Transactions, Revisions, And Lifecycle",
    "Authority And Security",
    "External Effects And Adapters",
    "Brain, Attention, And Agents",
    "UI And Lawful Lenses",
    "Cloud, Devices, And Migration",
    "Stable Identity And Canonical Bytes",
    "Snapshot And Commit Chain",
    "Signed Bootstrap And Trusted Base",
    "Pattern, Binding, And Rewrite",
    "Executable Interfaces And Relations",
    "Incremental Evaluation And Persistent Attention",
    "Information-Flow Security",
    "Effect Uncertainty And Reconciliation",
    "Replication And Offline Work",
    "Proof, Release, And Independent Truth",
)


def _text() -> str:
    return DOCUMENT.read_text(encoding="utf-8")


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _layer_blocks(document: str) -> list[tuple[int, str, str]]:
    matches = list(LAYER.finditer(document))
    blocks: list[tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        blocks.append(
            (
                int(match.group("number")),
                match.group("title"),
                document[match.end() : end],
            )
        )
    return blocks


def test_document_declares_its_status_scope_and_non_authority_boundary() -> None:
    document = _normalized(_text())
    required = (
        "Status: WIP explanatory and candidate-detail compendium",
        "document the existing twenty architecture layers and descend eighty layers deeper",
        "not a second specification, implementation evidence, a completion claim, or a release decision",
        "`AUTHORITY.md` decides precedence",
        "`SPEC.md` remains the normative product target",
        "not one hundred deployable services, tables, node kinds, or sequential runtime tiers",
        "No layer may introduce a persisted semantic shape other than `Cell(id, link0, link1, atom)`",
        "A proof target is not a claim that the proof currently passes",
        "cannot prove that any layer is implemented, usable, secure, performant, deployed, complete, or patentable",
    )
    for statement in required:
        assert statement in document


def test_document_contains_exactly_one_hundred_ordered_layers_in_ten_strata() -> None:
    document = _text()
    layers = _layer_blocks(document)
    assert [number for number, _title, _body in layers] == list(range(1, 101))
    assert len({title for _number, title, _body in layers}) == 100
    assert tuple(title for _number, title, _body in layers[:20]) == FIRST_TWENTY_TITLES

    strata = STRATUM.findall(document)
    assert [letter for letter, _title in strata] == list("ABCDEFGHIJ")
    assert len({title for _letter, title in strata}) == 10


def test_every_layer_answers_the_recursive_documentation_contract() -> None:
    layers = _layer_blocks(_text())
    for number, title, body in layers:
        for field in RECURSIVE_FIELDS:
            assert f"- **{field}:**" in body, (
                f"Layer {number} ({title}) is missing {field}"
            )
        assert re.search(r"\[(?:I|E)\d{2}\]", body), (
            f"Layer {number} ({title}) has no declared evidence reference"
        )
        word_count = len(re.findall(r"\b[\w'-]+\b", body))
        assert word_count >= 100, (
            f"Layer {number} ({title}) is too shallow: {word_count} words"
        )


def test_internal_links_resolve_and_every_reference_is_declared() -> None:
    document = _text()
    for raw_target in MARKDOWN_LINK.findall(document):
        target = raw_target.strip()
        if target.startswith(("https://", "http://", "#")):
            continue
        relative = unquote(target.split("#", 1)[0])
        if relative:
            assert (ROOT / relative).resolve().exists(), (
                f"100-layer document link does not resolve: {target}"
            )

    declared = set(DECLARED_REFERENCE.findall(document))
    used = set(REFERENCE.findall(document))
    assert declared == {f"I{number:02d}" for number in range(1, 8)} | {
        f"E{number:02d}" for number in range(1, 46)
    }
    assert used <= declared
    assert declared <= used


def test_external_sources_are_classified_and_not_mutable_github_main_links() -> None:
    document = _text()
    external_section = document.split(
        "## External Primary And Official Sources", 1
    )[1].split("# Adoption And Maintenance", 1)[0]
    assert "External sources establish lineage and constraints." in external_section
    assert "They do not become ArchHub" in external_section
    assert "authority." in external_section
    assert "Version/date-pinned sources are preferred." in external_section
    assert "must be reverified when a dependent decision is promoted." in external_section

    urls = re.findall(r"https://[^)\s]+", external_section)
    assert len(urls) == 45
    for url in urls:
        assert "/blob/main/" not in url
        assert "/tree/main/" not in url
        assert "/releases/latest" not in url


def test_candidate_details_cannot_promote_themselves() -> None:
    document = _text()
    authority_lines = re.findall(r"^- \*\*AUTHORITY:\*\* (.+)$", document, re.MULTILINE)
    assert len(authority_lines) == 100
    classifications = (
        "Restatement",
        "restatement",
        "Candidate",
        "candidate",
        "Accepted",
        "Normative",
        "Founder",
        "Grand Map",
        "Workspace",
    )
    for line in authority_lines:
        assert any(classification in line for classification in classifications)

    adoption = document.split("# Adoption And Maintenance", 1)[1]
    required_steps = (
        "trace the exact founder requirement",
        "reverify time-sensitive primary sources",
        "identify contradictions and security/failure implications",
        "add red executable courts before behavior",
        "implement as WIP on the Universal Cell floor",
        "obtain independent verification and required founder review",
        "switch authority only after no-fallback proof",
    )
    for step in required_steps:
        assert step in adoption


def test_cross_layer_example_preserves_one_graph_and_external_uncertainty() -> None:
    document = _text()
    example = document.split("# Cross-Layer End-To-End Example", 1)[1].split(
        "# Source Registry", 1
    )[0]
    required = (
        "The same project root is visible through an authorised lens.",
        "The editor creates a proposal against an exact snapshot.",
        "Serializable commit either accepts all or publishes nothing.",
        "Attempt, host outcome, and reconciliation remain distinct.",
        "WIP/Shared/Published remain independent immutable views.",
        "No Brain database, client domain store, dashboard JSON, or peer bus owns a",
        "copied version of the issue.",
    )
    for statement in required:
        assert statement in example


def test_document_is_ascii_and_does_not_claim_current_product_acceptance() -> None:
    document = DOCUMENT.read_bytes().decode("ascii")
    normalized = _normalized(document)
    assert len(re.findall(r"\b[\w'-]+\b", document)) >= 6_000
    forbidden = (
        "all 100 layers are implemented",
        "the complete product is delivered",
        "the system is release eligible",
        "the product is deployed",
        "the architecture is patentable",
    )
    for claim in forbidden:
        assert claim not in normalized.lower()
