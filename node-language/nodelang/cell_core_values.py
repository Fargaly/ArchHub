"""Versioned Core Values authority composed from universal Cells.

The Notion page is preserved as a source. Its ArchHub interpretation, control
coverage, gaps, and decisions are separate relations so prose cannot silently
become executable policy and a missing control cannot render as compliant.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .cell_protocols import CellBatch, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


CORE_VALUES_SOURCE_URL = (
    "https://app.notion.com/p/2c6f57b4e72f805997bbd24013cc69a4"
)
CORE_VALUES_SOURCE_UPDATED = "2025-11-11"

SYSTEM_SPECS = (
    (
        "identity-trust", "Identity and Trust Spine", 1,
        "Identity, relationships, authorization, classification, custody, "
        "signatures, courts, and recovery.",
    ),
    (
        "knowledge-provenance", "Knowledge and Provenance Fabric", 2,
        "Grand Map, Brain, sources, revisions, evidence, history, and "
        "governed federation.",
    ),
    (
        "operational-orchestration", "Operational Orchestration", 3,
        "Application, sessions, domains, composer, approved adapters, effects, "
        "CDE workflows, and deployment.",
    ),
    (
        "sustainable-ecosystem", "Sustainable Ecosystem", 4,
        "Community and future marketplace mechanisms; monetization remains "
        "dormant by founder direction while the product foundation is open.",
    ),
)

PILLAR_SPECS = (
    (
        "amanah", "Amanah - Sacred Stewardship",
        "Steward data, authority, time, security, truth, and maintainability.",
    ),
    (
        "shura", "Shura - Collective Wisdom",
        "Use relevant perspectives and independent review where consequence "
        "warrants it.",
    ),
    (
        "tajdid", "Tajdid - Continuous Renewal",
        "Learn through evidence, preserve history, improve the system, and "
        "prevent recurrence.",
    ),
)

VALUE_SPECS = (
    (
        "security", 1, "Security is Sacred Trust", "amanah", "hard-gate",
        "identity, authorization, data, adapters, effects, release, deployment",
        "Deny by default; protect data and authority at every boundary; require "
        "exact evidence before sensitive effects or release.",
    ),
    (
        "truth", 2, "Truth Over Comfort", "amanah", "hard-gate",
        "completion claims, status, documentation, reports, evidence",
        "State what is proven, partial, missing, or externally blocked; never "
        "promote a claim beyond its evidence.",
    ),
    (
        "ownership", 3, "You Build It, You Own It", "amanah", "hard-gate",
        "authorship, provenance, monitoring, rollback, incident responsibility",
        "Every change and effect carries actor, owner, provenance, recovery, "
        "and operational responsibility.",
    ),
    (
        "respect-time", 4, "Respect Every Second", "amanah", "measured-court",
        "user workflows, latency, responsiveness, accessibility, interruption",
        "Measure user effort and response, keep interaction direct and "
        "predictable, and prevent avoidable interruption or waiting.",
    ),
    (
        "architect-review", 5, "Architect Review is Mandatory", "shura",
        "risk-triggered-human-gate",
        "architecture, security, privacy, destructive effects, authority, release",
        "Require accountable human review for high-impact decisions; use "
        "automated courts for ordinary low-risk work.",
    ),
    (
        "real-pain", 6, "Solve Real Pain", "shura", "portfolio-gate",
        "roadmap priority and major feature proposals",
        "Major feature priority must cite observed user or operational pain; "
        "routine implementation choices need not repeat portfolio review.",
    ),
    (
        "simplicity", 7, "Simplicity Conquers Complexity", "shura",
        "design-architecture-court",
        "user workflows, catalogue design, authority duplication, maintenance",
        "Prefer one authority and coherent direct manipulation; multiple views "
        "are valid only when they resolve to the same identity and state.",
    ),
    (
        "test-ship", 8, "Test What You Ship", "tajdid", "hard-gate",
        "Shared, Published, Production, Deployed, real integrations",
        "Promotion requires evidence from the exact artifact and relevant real "
        "boundary; mocks may support units but never be the sole release proof.",
    ),
    (
        "iterate", 9, "Break It Down, Iterate Fast", "tajdid", "wip-workflow",
        "planning and reversible construction",
        "Build small reversible WIP revisions and learn quickly; iteration never "
        "waives complete, tested, authorized release criteria.",
    ),
    (
        "root-cause", 10, "Fix Root Causes", "tajdid", "recurrence-gate",
        "repeated defects, incidents, security failures, recurring drift",
        "A recurrence requires causal analysis and a preventive control or a "
        "recorded reason why prevention is not currently possible.",
    ),
)

CORE_VALUE_KEYS = tuple(item[0] for item in VALUE_SPECS)

CONFLICT_SPECS = (
    (
        "quality-vs-iteration", "Excellence versus iteration",
        "Move quickly through reversible WIP; release only complete, tested, "
        "and authorized exact revisions.",
    ),
    (
        "review-scope", "Mandatory review versus uninterrupted routine work",
        "Human review is risk-triggered for high-impact decisions; deterministic "
        "courts decide ordinary low-risk conformance.",
    ),
    (
        "mocks", "Real validation versus unit isolation",
        "Mocks are valid unit tools but cannot be sole evidence for an external "
        "integration, effect, or release claim.",
    ),
    (
        "one-path", "Simplicity versus multiple lenses",
        "Keep one canonical authority while permitting multiple views and "
        "shortcuts that resolve to the same identity.",
    ),
    (
        "applicability", "No neutral ground versus legitimate non-applicability",
        "Every material decision records applicability and reasons; it does not "
        "force irrelevant values into a false moral verdict.",
    ),
)

_SOURCE_CANONICAL = {
    "page_id": "2c6f57b4e72f805997bbd24013cc69a4",
    "title": "CORE VALUES",
    "updated": CORE_VALUES_SOURCE_UPDATED,
    "legacy_product": "ACCYON",
    "anchor": "Ihsan - Build as if God will use it",
    "pillars": [item[0] for item in PILLAR_SPECS],
    "values": [item[2] for item in VALUE_SPECS],
    "systems": [item[1] for item in SYSTEM_SPECS],
}

_TRANSLATION_CANONICAL = {
    "product": "ArchHub",
    "systems": SYSTEM_SPECS,
    "pillars": PILLAR_SPECS,
    "values": VALUE_SPECS,
    "conflicts": CONFLICT_SPECS,
    "source_execution": "never",
    "lifecycle": "WIP until reviewed and explicitly promoted",
}

_EXTRA_ROLE_NAMES = (
    "actor", "subject", "system", "pillar", "governing-value", "control",
    "gap", "status", "recommendation", "evidence", "reviewer", "risk",
    "applicability", "translation", "lifecycle", "source-version", "digest",
)


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


SOURCE_DIGEST = _canonical_digest(_SOURCE_CANONICAL)
TRANSLATION_DIGEST = _canonical_digest(_TRANSLATION_CANONICAL)


@dataclass(frozen=True, slots=True)
class ControlCoverage:
    control_roots: tuple[str, ...]
    gap_descriptions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ControlCoverageProjection:
    binding_root: str
    control_roots: tuple[str, ...]
    gap_roots: tuple[str, ...]
    status_root: str
    status: str


@dataclass(frozen=True, slots=True)
class CoreValuesAuthority:
    roles: Mapping[str, str]
    root_id: str
    source_root: str
    source_digest_root: str
    source_digest: str
    translation_digest_root: str
    translation_digest: str
    anchor_root: str
    systems_root: str
    system_roots: Mapping[str, str]
    pillars_root: str
    pillar_roots: Mapping[str, str]
    value_roots: Mapping[str, str]
    control_map_root: str
    control_binding_roots: Mapping[str, str]
    conflicts_root: str
    conflict_roots: tuple[str, ...]
    adoption_decision_root: str
    coverage: Mapping[str, ControlCoverageProjection]


@dataclass(frozen=True, slots=True)
class ValueTracedDecision:
    root_id: str
    actor_root: str
    subject_root: str
    scope_root: str
    system_roots: tuple[str, ...]
    pillar_roots: tuple[str, ...]
    value_roots: tuple[str, ...]
    recommendation_root: str
    evidence_roots: tuple[str, ...]
    risk_root: str
    reviewer_root: str | None
    status_root: str


def _terminal(batch: CellBatch, root_id: str, value: str) -> str:
    atom = str(value).encode("utf-8")
    if not atom:
        raise InvalidCell("Core Values terminal values cannot be empty")
    batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom))
    return root_id


def _for_role(members, role_id: str) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(members, role_id: str, label: str) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("Core Values relation requires exactly one %s" % label)
    return values[0]


def _coverage_status(controls: tuple[str, ...], gaps: tuple[str, ...]) -> str:
    if controls and not gaps:
        return "covered"
    if controls and gaps:
        return "partial"
    if gaps:
        return "gap"
    raise InvalidCell("a Core Value requires a control or an explicit gap")


def compose_core_values_authority(
    batch: CellBatch,
    base_roles: Mapping[str, str],
    add_property: Callable[[str, str, str, object], object],
    control_coverage: Mapping[str, ControlCoverage],
    *,
    wip_state_root: str,
    actor_root: str,
    prefix: str = "app:core-values:v1",
) -> CoreValuesAuthority:
    """Compose the WIP constitution and its honest live-control coverage."""
    required_roles = {
        "owner", "value", "label", "member", "scope", "source", "target",
        "why", "property", "authority",
    }
    missing_roles = required_roles - set(base_roles)
    if missing_roles:
        raise InvalidCell(
            "Core Values base roles are incomplete: %s" % sorted(missing_roles)
        )
    if set(control_coverage) != set(CORE_VALUE_KEYS):
        raise InvalidCell("Core Values control coverage must name all ten values")
    existing = batch.store.snapshot().cells
    for root in (wip_state_root, actor_root):
        if root not in existing:
            raise InvalidCell("Core Values authority references a missing root")

    roles = dict(base_roles)
    for name in _EXTRA_ROLE_NAMES:
        role_id = "%s:role:%s" % (prefix, name)
        _terminal(batch, role_id, name)
        roles[name] = role_id

    source_root = prefix + ":source"
    source_url_root = _terminal(
        batch, source_root + ":url", CORE_VALUES_SOURCE_URL
    )
    source_version_root = _terminal(
        batch, source_root + ":updated", CORE_VALUES_SOURCE_UPDATED
    )
    source_digest_root = _terminal(
        batch, source_root + ":digest", SOURCE_DIGEST
    )
    source_legacy_product_root = _terminal(
        batch, source_root + ":legacy-product", "ACCYON"
    )
    source_execution_root = _terminal(
        batch, source_root + ":execution", "source-only; never executed"
    )
    batch.relation([
        (roles["source"], source_url_root),
        (roles["source-version"], source_version_root),
        (roles["digest"], source_digest_root),
        (roles["scope"], source_legacy_product_root),
        (roles["why"], source_execution_root),
    ], relation_id=source_root)
    add_property(source_root, "field", "title", "Founder Core Values source")
    add_property(source_root, "source", "source_url", CORE_VALUES_SOURCE_URL)
    add_property(source_root, "source", "source_updated", CORE_VALUES_SOURCE_UPDATED)
    add_property(source_root, "source", "legacy_product", "ACCYON")
    add_property(source_root, "source", "source_digest", SOURCE_DIGEST)
    add_property(source_root, "governance", "execution", "source-only; never executed")

    translation_digest_root = _terminal(
        batch, prefix + ":translation-digest", TRANSLATION_DIGEST
    )
    anchor_root = prefix + ":anchor:ihsan"
    anchor_statement_root = _terminal(
        batch, anchor_root + ":statement",
        "Pursue excellence as worship and honor the trust carried by the work.",
    )
    anchor_boundary_root = _terminal(
        batch, anchor_root + ":machine-boundary",
        "human anchor; machines enforce only explicit operational translations",
    )
    batch.relation([
        (roles["source"], source_root),
        (roles["translation"], anchor_statement_root),
        (roles["applicability"], anchor_boundary_root),
        (roles["digest"], translation_digest_root),
    ], relation_id=anchor_root)
    add_property(anchor_root, "field", "title", "Ihsan - Excellence as Worship")
    add_property(anchor_root, "governance", "statement", (
        "Pursue excellence as worship and honor the trust carried by the work."
    ))
    add_property(anchor_root, "governance", "machine_role", (
        "Human anchor; no machine verdict on divine acceptance"
    ))

    system_roots = {
        key: "%s:system:%s" % (prefix, key)
        for key, _title, _priority, _meaning in SYSTEM_SPECS
    }
    for key, title, priority, meaning in SYSTEM_SPECS:
        root = system_roots[key]
        meaning_root = _terminal(batch, root + ":meaning", meaning)
        batch.relation([
            (roles["translation"], meaning_root),
            (roles["source"], source_root),
        ], relation_id=root)
        add_property(root, "field", "title", title)
        add_property(root, "governance", "priority", priority)
        add_property(root, "governance", "meaning", meaning)
        add_property(
            root, "governance", "status",
            "dormant by founder direction" if key == "sustainable-ecosystem" else "active",
        )
    systems_root = prefix + ":systems"
    batch.relation([
        (roles["member"], system_roots[key])
        for key, _title, _priority, _meaning in SYSTEM_SPECS
    ], relation_id=systems_root)
    add_property(systems_root, "field", "title", "Dependency Systems")
    add_property(systems_root, "governance", "rule", (
        "Dependency priority guides recommendations; critical incidents may override order"
    ))

    pillar_roots = {
        key: "%s:pillar:%s" % (prefix, key)
        for key, _title, _meaning in PILLAR_SPECS
    }
    value_roots = {
        key: "%s:value:%02d:%s" % (prefix, number, key)
        for key, number, _title, _pillar, _enforcement, _applies, _translation
        in VALUE_SPECS
    }
    control_binding_roots = {
        key: "%s:control-binding:%s" % (prefix, key)
        for key in CORE_VALUE_KEYS
    }

    for key, number, title, pillar, enforcement, applies_to, translation in VALUE_SPECS:
        root = value_roots[key]
        translation_root = _terminal(batch, root + ":translation", translation)
        batch.relation([
            (roles["pillar"], pillar_roots[pillar]),
            (roles["translation"], translation_root),
            (roles["member"], control_binding_roots[key]),
        ], relation_id=root)
        add_property(root, "field", "title", title)
        add_property(root, "governance", "number", number)
        add_property(root, "governance", "pillar", pillar)
        add_property(root, "governance", "enforcement", enforcement)
        add_property(root, "governance", "applies_to", applies_to)
        add_property(root, "governance", "translation", translation)

    for key, title, meaning in PILLAR_SPECS:
        root = pillar_roots[key]
        meaning_root = _terminal(batch, root + ":meaning", meaning)
        members = [
            (roles["member"], value_roots[value_key])
            for value_key, _number, _value_title, pillar, _enforcement,
            _applies, _translation in VALUE_SPECS
            if pillar == key
        ]
        batch.relation([
            (roles["source"], anchor_root),
            (roles["translation"], meaning_root),
            *members,
        ], relation_id=root)
        add_property(root, "field", "title", title)
        add_property(root, "governance", "meaning", meaning)
    pillars_root = prefix + ":pillars"
    batch.relation([
        (roles["member"], pillar_roots[key])
        for key, _title, _meaning in PILLAR_SPECS
    ], relation_id=pillars_root)
    add_property(pillars_root, "field", "title", "Pillars and Operational Values")

    coverage_projection = {}
    for key in CORE_VALUE_KEYS:
        declared = control_coverage[key]
        controls = tuple(dict.fromkeys(declared.control_roots))
        gaps = tuple(dict.fromkeys(declared.gap_descriptions))
        if len(controls) != len(declared.control_roots):
            raise InvalidCell("Core Value control roots cannot contain duplicates")
        if len(gaps) != len(declared.gap_descriptions):
            raise InvalidCell("Core Value gaps cannot contain duplicates")
        for control_root in controls:
            if control_root not in existing:
                raise InvalidCell(
                    "Core Value %s points to a missing live control" % key
                )
            if control_root == source_root:
                raise InvalidCell("source prose cannot be a live control")
        gap_roots = []
        for index, description in enumerate(gaps):
            gap_root = "%s:gap:%s:%d" % (prefix, key, index)
            reason_root = _terminal(batch, gap_root + ":reason", description)
            batch.relation([
                (roles["why"], reason_root),
                (roles["governing-value"], value_roots[key]),
            ], relation_id=gap_root)
            add_property(gap_root, "field", "title", "Open governance gap")
            add_property(gap_root, "governance", "value", key)
            add_property(gap_root, "governance", "reason", description)
            add_property(gap_root, "governance", "status", "open")
            gap_roots.append(gap_root)
        gap_roots_tuple = tuple(gap_roots)
        status = _coverage_status(controls, gap_roots_tuple)
        status_root = _terminal(
            batch, "%s:coverage-status:%s" % (prefix, key), status
        )
        binding_root = control_binding_roots[key]
        batch.relation([
            (roles["source"], value_roots[key]),
            *((roles["target"], root) for root in controls),
            *((roles["gap"], root) for root in gap_roots_tuple),
            (roles["status"], status_root),
        ], relation_id=binding_root)
        add_property(binding_root, "field", "title", "%s control coverage" % key)
        add_property(binding_root, "governance", "status", status)
        add_property(binding_root, "governance", "control_count", len(controls))
        add_property(binding_root, "governance", "gap_count", len(gap_roots_tuple))
        coverage_projection[key] = ControlCoverageProjection(
            binding_root, controls, gap_roots_tuple, status_root, status
        )
    control_map_root = prefix + ":control-map"
    batch.relation([
        (roles["member"], control_binding_roots[key])
        for key in CORE_VALUE_KEYS
    ], relation_id=control_map_root)
    add_property(control_map_root, "field", "title", "Values to Live Controls")
    add_property(control_map_root, "governance", "truth_rule", (
        "Partial and open gaps never render as compliant"
    ))

    conflict_roots = []
    for key, title, resolution in CONFLICT_SPECS:
        root = "%s:conflict:%s" % (prefix, key)
        resolution_root = _terminal(batch, root + ":resolution", resolution)
        batch.relation([
            (roles["source"], source_root),
            (roles["translation"], resolution_root),
        ], relation_id=root)
        add_property(root, "field", "title", title)
        add_property(root, "governance", "resolution", resolution)
        conflict_roots.append(root)
    conflicts_root = prefix + ":conflicts"
    batch.relation([
        (roles["member"], root) for root in conflict_roots
    ], relation_id=conflicts_root)
    add_property(conflicts_root, "field", "title", "Resolved Interpretation Conflicts")

    adoption_decision_root = prefix + ":decision:adopt-translation-wip"
    decision_scope_root = _terminal(
        batch, adoption_decision_root + ":scope", "ArchHub governance"
    )
    recommendation_root = _terminal(
        batch,
        adoption_decision_root + ":recommendation",
        "Adopt the ArchHub translation as WIP; publish only after exact founder review",
    )
    risk_root = _terminal(
        batch, adoption_decision_root + ":risk", "medium"
    )
    research_evidence_root = _terminal(
        batch,
        adoption_decision_root + ":research-evidence",
        "file:30.KNOWLEDGE/strategy/core-values-governance-authority-2026-07-16.md",
    )
    adoption_value_keys = (
        "truth", "architect-review", "simplicity", "test-ship", "iterate"
    )
    adoption_pillars = tuple(dict.fromkeys(
        pillar_roots[next(
            item[3] for item in VALUE_SPECS if item[0] == key
        )]
        for key in adoption_value_keys
    ))
    batch.relation([
        (roles["actor"], actor_root),
        (roles["subject"], translation_digest_root),
        (roles["scope"], decision_scope_root),
        *((roles["system"], system_roots[key]) for key in (
            "identity-trust", "knowledge-provenance", "operational-orchestration"
        )),
        *((roles["pillar"], root) for root in adoption_pillars),
        *((roles["governing-value"], value_roots[key]) for key in adoption_value_keys),
        (roles["recommendation"], recommendation_root),
        (roles["evidence"], source_root),
        (roles["evidence"], research_evidence_root),
        (roles["risk"], risk_root),
        (roles["status"], wip_state_root),
    ], relation_id=adoption_decision_root)
    add_property(adoption_decision_root, "field", "title", "Adopt Core Values translation")
    add_property(adoption_decision_root, "governance", "risk", "medium")
    add_property(adoption_decision_root, "governance", "status", "WIP")
    add_property(adoption_decision_root, "governance", "recommendation", (
        "Publish only after exact founder review"
    ))

    root_id = prefix
    batch.relation([
        (roles["member"], source_root),
        (roles["member"], anchor_root),
        (roles["member"], systems_root),
        (roles["member"], pillars_root),
        (roles["member"], control_map_root),
        (roles["member"], conflicts_root),
        (roles["member"], adoption_decision_root),
        (roles["source"], source_root),
        (roles["authority"], translation_digest_root),
        (roles["lifecycle"], wip_state_root),
    ], relation_id=root_id)
    add_property(root_id, "field", "title", "Core Values and Governance")
    add_property(root_id, "governance", "lifecycle", "WIP")
    add_property(root_id, "governance", "source_digest", SOURCE_DIGEST)
    add_property(root_id, "governance", "translation_digest", TRANSLATION_DIGEST)
    add_property(root_id, "governance", "release_rule", (
        "Notion edits never auto-activate; reviewed exact revisions are selected explicitly"
    ))

    return CoreValuesAuthority(
        roles=MappingProxyType(roles),
        root_id=root_id,
        source_root=source_root,
        source_digest_root=source_digest_root,
        source_digest=SOURCE_DIGEST,
        translation_digest_root=translation_digest_root,
        translation_digest=TRANSLATION_DIGEST,
        anchor_root=anchor_root,
        systems_root=systems_root,
        system_roots=MappingProxyType(system_roots),
        pillars_root=pillars_root,
        pillar_roots=MappingProxyType(pillar_roots),
        value_roots=MappingProxyType(value_roots),
        control_map_root=control_map_root,
        control_binding_roots=MappingProxyType(control_binding_roots),
        conflicts_root=conflicts_root,
        conflict_roots=tuple(conflict_roots),
        adoption_decision_root=adoption_decision_root,
        coverage=MappingProxyType(coverage_projection),
    )


def project_core_values_authority(
    snapshot: Snapshot,
    base_roles: Mapping[str, str],
    *,
    prefix: str = "app:core-values:v1",
) -> CoreValuesAuthority:
    roles = dict(base_roles)
    for name in _EXTRA_ROLE_NAMES:
        roles[name] = "%s:role:%s" % (prefix, name)
    required = (*roles.values(), prefix, prefix + ":source")
    if any(root_id not in snapshot.cells for root_id in required):
        raise InvalidCell("Core Values authority is missing or incomplete")
    system_roots = {
        key: "%s:system:%s" % (prefix, key)
        for key, _title, _priority, _meaning in SYSTEM_SPECS
    }
    pillar_roots = {
        key: "%s:pillar:%s" % (prefix, key)
        for key, _title, _meaning in PILLAR_SPECS
    }
    value_roots = {
        key: "%s:value:%02d:%s" % (prefix, number, key)
        for key, number, _title, _pillar, _enforcement, _applies, _translation
        in VALUE_SPECS
    }
    control_binding_roots = {
        key: "%s:control-binding:%s" % (prefix, key)
        for key in CORE_VALUE_KEYS
    }
    coverage = {}
    for key, binding_root in control_binding_roots.items():
        members = read_relation(snapshot, binding_root, budget=128)
        controls = _for_role(members, roles["target"])
        gaps = _for_role(members, roles["gap"])
        status_root = _one(members, roles["status"], "coverage status")
        try:
            status = snapshot.cells[status_root].atom.decode("ascii")
        except (KeyError, UnicodeDecodeError) as exc:
            raise InvalidCell("Core Values coverage status is invalid") from exc
        coverage[key] = ControlCoverageProjection(
            binding_root, controls, gaps, status_root, status
        )
    authority = CoreValuesAuthority(
        roles=MappingProxyType(roles),
        root_id=prefix,
        source_root=prefix + ":source",
        source_digest_root=prefix + ":source:digest",
        source_digest=SOURCE_DIGEST,
        translation_digest_root=prefix + ":translation-digest",
        translation_digest=TRANSLATION_DIGEST,
        anchor_root=prefix + ":anchor:ihsan",
        systems_root=prefix + ":systems",
        system_roots=MappingProxyType(system_roots),
        pillars_root=prefix + ":pillars",
        pillar_roots=MappingProxyType(pillar_roots),
        value_roots=MappingProxyType(value_roots),
        control_map_root=prefix + ":control-map",
        control_binding_roots=MappingProxyType(control_binding_roots),
        conflicts_root=prefix + ":conflicts",
        conflict_roots=tuple(
            "%s:conflict:%s" % (prefix, key)
            for key, _title, _resolution in CONFLICT_SPECS
        ),
        adoption_decision_root=prefix + ":decision:adopt-translation-wip",
        coverage=MappingProxyType(coverage),
    )
    validate_core_values_authority(snapshot, authority)
    return authority


def validate_core_values_authority(
    snapshot: Snapshot, authority: CoreValuesAuthority
) -> bool:
    roles = authority.roles
    if snapshot.cells[authority.source_digest_root].atom.decode("ascii") != SOURCE_DIGEST:
        raise InvalidCell("Core Values source extraction digest drifted")
    if (
        snapshot.cells[authority.translation_digest_root].atom.decode("ascii")
        != TRANSLATION_DIGEST
    ):
        raise InvalidCell("Core Values ArchHub translation digest drifted")
    root_members = read_relation(snapshot, authority.root_id, budget=128)
    expected_children = {
        authority.source_root, authority.anchor_root, authority.systems_root,
        authority.pillars_root, authority.control_map_root,
        authority.conflicts_root, authority.adoption_decision_root,
    }
    if set(_for_role(root_members, roles["member"])) != expected_children:
        raise InvalidCell("Core Values root composition drifted")
    if _one(root_members, roles["source"], "source") != authority.source_root:
        raise InvalidCell("Core Values source binding drifted")
    if (
        _one(root_members, roles["authority"], "translation authority")
        != authority.translation_digest_root
    ):
        raise InvalidCell("Core Values translation authority drifted")
    system_members = read_relation(snapshot, authority.systems_root, budget=32)
    if tuple(_for_role(system_members, roles["member"])) != tuple(
        authority.system_roots[key]
        for key, _title, _priority, _meaning in SYSTEM_SPECS
    ):
        raise InvalidCell("Core Values dependency systems drifted")
    pillar_members = read_relation(snapshot, authority.pillars_root, budget=32)
    if tuple(_for_role(pillar_members, roles["member"])) != tuple(
        authority.pillar_roots[key] for key, _title, _meaning in PILLAR_SPECS
    ):
        raise InvalidCell("Core Values pillars drifted")
    for pillar_key, _title, _meaning in PILLAR_SPECS:
        members = read_relation(
            snapshot, authority.pillar_roots[pillar_key], budget=64
        )
        expected_values = tuple(
            authority.value_roots[key]
            for key, _number, _value_title, pillar, _enforcement,
            _applies, _translation in VALUE_SPECS
            if pillar == pillar_key
        )
        if _for_role(members, roles["member"]) != expected_values:
            raise InvalidCell("Core Values pillar membership drifted")
    control_map = read_relation(snapshot, authority.control_map_root, budget=64)
    if _for_role(control_map, roles["member"]) != tuple(
        authority.control_binding_roots[key] for key in CORE_VALUE_KEYS
    ):
        raise InvalidCell("Core Values control map drifted")
    for key in CORE_VALUE_KEYS:
        projected = authority.coverage[key]
        if not projected.control_roots and not projected.gap_roots:
            raise InvalidCell("Core Value has neither a control nor a declared gap")
        if set(projected.control_roots) & {authority.source_root}:
            raise InvalidCell("source prose cannot satisfy a control")
        if any(
            root_id not in snapshot.cells
            for root_id in (*projected.control_roots, *projected.gap_roots)
        ):
            raise InvalidCell("Core Value control coverage contains a dangling root")
        expected_status = _coverage_status(
            projected.control_roots, projected.gap_roots
        )
        if projected.status != expected_status:
            raise InvalidCell("Core Value coverage status is false")
        if snapshot.cells[projected.status_root].atom.decode("ascii") != expected_status:
            raise InvalidCell("Core Value coverage status node drifted")
    read_value_traced_decision(
        snapshot, authority, authority.adoption_decision_root
    )
    return True


def _value_spec(key: str):
    for item in VALUE_SPECS:
        if item[0] == key:
            return item
    raise InvalidCell("unknown Core Value %r" % key)


def build_value_traced_decision(
    store: CellStore,
    authority: CoreValuesAuthority,
    *,
    decision_id: str,
    actor_root: str,
    subject_root: str,
    system_keys: Iterable[str],
    value_keys: Iterable[str],
    recommendation: str,
    evidence_roots: Iterable[str],
    risk: str,
    status_root: str,
    reviewer_root: str | None = None,
    scope: str = "governed decision",
) -> str:
    """Append a decision whose values, evidence, risk, and review are explicit."""
    systems = tuple(dict.fromkeys(system_keys))
    values = tuple(dict.fromkeys(value_keys))
    evidence = tuple(dict.fromkeys(evidence_roots))
    if not systems or any(key not in authority.system_roots for key in systems):
        raise InvalidCell("value-traced decision requires known systems")
    if not values or any(key not in authority.value_roots for key in values):
        raise InvalidCell("value-traced decision requires known values")
    if not recommendation.strip():
        raise InvalidCell("value-traced decision requires a recommendation")
    hard_gate = any(_value_spec(key)[4] == "hard-gate" for key in values)
    if hard_gate and not evidence:
        raise InvalidCell("hard-gate value-traced decision requires evidence")
    risk_name = risk.strip().lower()
    if risk_name not in {"low", "medium", "high", "critical"}:
        raise InvalidCell("value-traced decision risk is invalid")
    if risk_name in {"high", "critical"} and reviewer_root is None:
        raise InvalidCell("high-risk value-traced decision requires a reviewer")
    snapshot = store.snapshot()
    references = {
        actor_root, subject_root, status_root, *evidence,
        *(system_root for key, system_root in authority.system_roots.items()
          if key in systems),
        *(value_root for key, value_root in authority.value_roots.items()
          if key in values),
    }
    if reviewer_root is not None:
        references.add(reviewer_root)
    if any(root_id not in snapshot.cells for root_id in references):
        raise InvalidCell("value-traced decision contains a dangling reference")

    pillar_keys = tuple(dict.fromkeys(_value_spec(key)[3] for key in values))
    batch = CellBatch(store)
    scope_root = _terminal(batch, decision_id + ":scope", scope)
    recommendation_root = _terminal(
        batch, decision_id + ":recommendation", recommendation
    )
    risk_root = _terminal(batch, decision_id + ":risk", risk_name)
    roles = authority.roles
    batch.relation([
        (roles["actor"], actor_root),
        (roles["subject"], subject_root),
        (roles["scope"], scope_root),
        *((roles["system"], authority.system_roots[key]) for key in systems),
        *((roles["pillar"], authority.pillar_roots[key]) for key in pillar_keys),
        *((roles["governing-value"], authority.value_roots[key]) for key in values),
        (roles["recommendation"], recommendation_root),
        *((roles["evidence"], root) for root in evidence),
        (roles["risk"], risk_root),
        *(([(roles["reviewer"], reviewer_root)]) if reviewer_root else ()),
        (roles["status"], status_root),
    ], relation_id=decision_id)
    batch.commit()
    read_value_traced_decision(store.snapshot(), authority, decision_id)
    return decision_id


def read_value_traced_decision(
    snapshot: Snapshot,
    authority: CoreValuesAuthority,
    decision_root: str,
) -> ValueTracedDecision:
    members = read_relation(snapshot, decision_root, budget=256)
    roles = authority.roles
    actor = _one(members, roles["actor"], "actor")
    subject = _one(members, roles["subject"], "subject")
    scope = _one(members, roles["scope"], "scope")
    systems = _for_role(members, roles["system"])
    pillars = _for_role(members, roles["pillar"])
    values = _for_role(members, roles["governing-value"])
    recommendation = _one(
        members, roles["recommendation"], "recommendation"
    )
    evidence = _for_role(members, roles["evidence"])
    risk = _one(members, roles["risk"], "risk")
    reviewers = _for_role(members, roles["reviewer"])
    status = _one(members, roles["status"], "status")
    if not systems or set(systems) - set(authority.system_roots.values()):
        raise InvalidCell("value-traced decision has invalid systems")
    if not values or set(values) - set(authority.value_roots.values()):
        raise InvalidCell("value-traced decision has invalid values")
    expected_pillars = {
        authority.pillar_roots[_value_spec(key)[3]]
        for key, root in authority.value_roots.items() if root in values
    }
    if set(pillars) != expected_pillars:
        raise InvalidCell("value-traced decision pillar trace is incomplete")
    try:
        risk_name = snapshot.cells[risk].atom.decode("ascii")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("value-traced decision risk is invalid") from exc
    if risk_name in {"high", "critical"} and len(reviewers) != 1:
        raise InvalidCell("high-risk value-traced decision requires one reviewer")
    if risk_name not in {"high", "critical"} and len(reviewers) > 1:
        raise InvalidCell("value-traced decision has multiple reviewers")
    selected_keys = tuple(
        key for key, root in authority.value_roots.items() if root in values
    )
    if any(_value_spec(key)[4] == "hard-gate" for key in selected_keys) and not evidence:
        raise InvalidCell("hard-gate value-traced decision has no evidence")
    referenced = {
        actor, subject, scope, *systems, *pillars, *values, recommendation,
        *evidence, risk, *reviewers, status,
    }
    if any(root_id not in snapshot.cells for root_id in referenced):
        raise InvalidCell("value-traced decision contains a dangling reference")
    return ValueTracedDecision(
        decision_root, actor, subject, scope, systems, pillars, values,
        recommendation, evidence, risk, reviewers[0] if reviewers else None,
        status,
    )


__all__ = [
    "CORE_VALUE_KEYS",
    "CORE_VALUES_SOURCE_URL",
    "CORE_VALUES_SOURCE_UPDATED",
    "SOURCE_DIGEST",
    "TRANSLATION_DIGEST",
    "ControlCoverage",
    "ControlCoverageProjection",
    "CoreValuesAuthority",
    "ValueTracedDecision",
    "compose_core_values_authority",
    "project_core_values_authority",
    "validate_core_values_authority",
    "build_value_traced_decision",
    "read_value_traced_decision",
]
