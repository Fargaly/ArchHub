"""Bounded conformance court for the explanatory Node Language handbook.

This court binds one reviewed handbook revision to the current specification
and authority index. It proves document structure, declared source mappings,
and selected exact normative restatements. It does not prove product behavior,
literature truth, usability, security, or release eligibility.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "NODE-LANGUAGE-HANDBOOK.md"
SPEC = ROOT / "SPEC.md"
AUTHORITY = ROOT / "AUTHORITY.md"

REVIEWED_SHA256 = {
    "AUTHORITY.md": "5c66ec0304152d75ed54697387cce1293424f1f7e264f85ca13d9c1d985624c0",
    "SPEC.md": "13664a6dde239dca498c2820601377412eb615ee98ac3dc7b0d80e3803224cbd",
    "NODE-LANGUAGE-HANDBOOK.md": (
        "bfc02b5ddabdd8c0638b4d000e1b56e6f8192bacf90ed0377230d399f9ca2f00"
    ),
}
QUESTIONS = ("WHAT", "WHY", "HOW", "WHO", "WHEN", "WHERE", "PROOF")
H2 = re.compile(r"^## (?P<number>\d+)\. (?P<title>.+)$", re.MULTILINE)
H3 = re.compile(r"^### (?P<question>[A-Z]+)$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)", re.DOTALL)
COURT_PATH = re.compile(r"`((?:tests_replica|tests_js)/[^`]+)`")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sections(handbook: str) -> list[tuple[int, str, str]]:
    matches = list(H2.finditer(handbook))
    return [
        (
            int(match.group("number")),
            match.group("title"),
            handbook[
                match.end() : (
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else len(handbook)
                )
            ],
        )
        for index, match in enumerate(matches)
    ]


def _external_urls(value: str) -> set[str]:
    return {
        target.strip()
        for target in MARKDOWN_LINK.findall(value)
        if target.strip().startswith(("https://", "http://"))
    }


def test_handbook_revision_is_the_reviewed_wip_explanatory_artifact() -> None:
    for name, digest in REVIEWED_SHA256.items():
        assert _digest(ROOT / name) == digest, (
            f"{name} changed after the handbook conformance review"
        )

    handbook = _text(HANDBOOK)
    normalized = _normalized(handbook)
    assert handbook.startswith("# ArchHub Node Language Handbook\n")
    assert "Status: WIP explanatory handbook" in handbook
    assert "not a completion, release, or deployment claim" in handbook
    assert "**Current evidence warning:**" in handbook
    assert "cannot prove present behavior, acceptance, or release eligibility" in (
        normalized
    )
    assert "`tests_replica/test_node_language_handbook_conformance.py`" in handbook
    assert (
        "does not establish semantic correctness or product release" in normalized
    )


def test_every_numbered_section_repeats_the_recursive_teaching_contract() -> None:
    handbook = _text(HANDBOOK)
    sections = _sections(handbook)
    assert [number for number, _title, _body in sections] == list(range(1, 18))

    for number, title, body in sections:
        assert tuple(H3.findall(body)) == QUESTIONS, (
            f"section {number} does not preserve the seven-question order"
        )
        assert "Scale:" in body, f"section {number} lacks its recursive scale"
        assert (
            "**Worked example:**" in body or "Worked Example" in title
        ), f"section {number} lacks an example"
        assert "**Failure/counterexample:**" in body, (
            f"section {number} lacks a failure/counterexample"
        )
        proof = body.split("### PROOF", 1)[1]
        assert "**Authority:**" in proof
        assert "**Literature:**" in proof
        assert "court" in proof.lower()


def test_normative_restatements_match_the_current_specification() -> None:
    handbook = _normalized(_text(HANDBOOK))
    specification = _normalized(_text(SPEC))
    attention_anchors = (
        "A **Signal** records an observed committed change with source revision, "
        "provenance, trust, audience, time, and deduplication identity.",
        "**Attention** relates an observer to an authorised candidate, source "
        "snapshot, explicit reasons, ordering policy revision, expiry, and evidence.",
        "**Focus** records the bounded current working set for an actor/view session, "
        "including scope, reason, origin, interruption state, and recovery history.",
        "An **Obligation** unifies requirements, Grand Map leaves, Core Value gaps, "
        "failing courts, security findings, accepted work, dependencies, evidence, "
        "and resolution history.",
        "**Decision** and **Outcome** compositions preserve the selected action, "
        "actor, authority, evidence, effect receipt, reconciliation, and "
        "reversal/compensation.",
    )
    for anchor in attention_anchors:
        assert anchor in specification
        assert anchor in handbook

    ordering = (
        "safety and data-loss risk",
        "explicit user/founder pin",
        "blocking dependency",
        "failed active court",
        "accepted due work and fairness",
        "optional model-proposed relevance",
    )
    positions = [handbook.index(item) for item in ordering]
    assert positions == sorted(positions)

    performance_anchors = (
        ("p95 <= 16.7 ms", "p95 <= 16.7 ms"),
        ("same-frame selection feedback", "| Selection feedback | same frame |"),
        (
            "local mutation acknowledgement <= 100 ms",
            "| Local mutation acknowledgement | <= 100 ms |",
        ),
        (
            "bounded scope entry <= 150 ms",
            "| Bounded scope entry | <= 150 ms |",
        ),
        (
            "no steady-state long task over 50 ms on the reference machine",
            "| Steady-state long task | no task > 50 ms on the reference machine |",
        ),
    )
    for specification_anchor, handbook_anchor in performance_anchors:
        assert specification_anchor in specification
        assert handbook_anchor in handbook


def test_all_local_links_and_declared_courts_resolve() -> None:
    handbook = _text(HANDBOOK)
    for raw_target in MARKDOWN_LINK.findall(handbook):
        target = raw_target.strip()
        if target.startswith(("https://", "http://", "#")):
            continue
        relative = unquote(target.split("#", 1)[0])
        if relative:
            assert (ROOT / relative).resolve().exists(), (
                f"handbook link does not resolve: {target}"
            )

    declared = {
        raw_path.split("::", 1)[0]
        for raw_path in COURT_PATH.findall(handbook)
    }
    assert len(declared) >= 42
    for relative in declared:
        assert (ROOT / relative).is_file(), (
            f"declared court path does not exist: {relative}"
        )


def test_external_sources_are_classified_with_limits_in_the_matrix() -> None:
    handbook = _text(HANDBOOK)
    section_17 = next(body for number, _title, body in _sections(handbook) if number == 17)
    pre_matrix = handbook[: handbook.index("## 17. Sources Matrix and Maintenance")]
    cited_before_matrix = _external_urls(pre_matrix)
    matrix_urls = _external_urls(section_17)
    assert len(cited_before_matrix) >= 20
    assert cited_before_matrix <= matrix_urls

    rows = [
        line
        for line in section_17.splitlines()
        if line.startswith("| ") and not line.startswith("|---")
    ]
    assert len(rows) >= len(matrix_urls)
    for row in rows:
        columns = [column.strip() for column in row.strip("|").split("|")]
        assert len(columns) == 4
        assert all(columns)

    for url in matrix_urls:
        lowered = url.lower()
        assert "/main/" not in lowered
        assert "/dev/" not in lowered
        assert "/current/" not in lowered
        if lowered.startswith("https://www.w3.org/tr/"):
            assert re.match(r"https://www\.w3\.org/TR/\d{4}/", url)


def test_handbook_remains_ascii_and_does_not_promote_proposals() -> None:
    raw = HANDBOOK.read_bytes()
    raw.decode("ascii")
    handbook = raw.decode("ascii")
    normalized = _normalized(handbook)
    assert len(re.findall(r"\b[\w'-]+\b", handbook)) >= 9_000
    assert "Non-normative coordination proposal" in handbook
    assert "`SPEC.md` and `AUTHORITY.md` have not adopted that named architecture" in (
        normalized
    )
    assert "WIP/research evidence, never authority" in handbook
