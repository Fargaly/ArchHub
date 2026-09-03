"""Graph-held contract for the legacy Brain governance control plane.

Brain is useful during migration only when its channels are admitted by the
Universal Cell authority and remain visibly fenced as projections. This module
records those admitted channels as Cells. It does not import Brain, open its
database, start MCP, repair hooks, or invoke any host capability.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import CellBatch, RelationMember, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "capability",
    "source-path",
    "source-symbol",
    "tool",
    "authority",
    "authority-mode",
    "legacy-status",
    "legacy-migration-only",
    "brain-meta-write",
    "cell-read",
    "cell-write",
    "effect-boundary",
    "requires-court",
    "promotion-allowed",
    "digest",
)

ACTIVE_CELL_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
DEFAULT_CONTRACT_ROOT = "legacy-brain-governance:control-contract:v1"
AUTHORITY_MODES = frozenset({
    "cell-first-route",
    "mixed-cell-first",
    "cell-verified-projection",
    "legacy-control-projection",
    "external-adapter-projection",
})
EFFECT_BOUNDARIES = frozenset({
    "none",
    "governed-work-transition",
    "cell-route",
    "hook-repair",
    "audit-ledger",
    "requirement-sync",
    "core-values-projection",
    "workshop-gate",
    "court-attestation",
    "secret-custody",
    "process-audit",
    "agent-skill-proposal",
})

BRAIN_GOVERNANCE_SPECS = (
    {
        "capability": "universal-runtime-work",
        "source_path": "personal-brain-mcp/src/personal_brain/server.py",
        "source_symbol": "UniversalRuntimeBridge",
        "tool_names": (
            "brain.universal_work_status",
            "brain.universal_work_next",
            "brain.universal_work_create",
            "brain.universal_work_transition",
            "brain.universal_work_court",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "cell-route",
        "required_courts": (
            "personal-brain-mcp/tests/test_universal_runtime_bridge.py",
            "personal-brain-mcp/tests/test_universal_session_manager.py",
        ),
    },
    {
        "capability": "active-work-assignment",
        "source_path": "personal-brain-mcp/src/personal_brain/active_work.py",
        "source_symbol": "register_active_work_tools",
        "tool_names": (
            "brain.work_add_cell_first",
            "brain.work_next_cell_first",
            "brain.work_claim_cell_first",
            "brain.work_release_cell_first",
            "brain.work_court_run_cell_first",
            "brain.work_assigned_block",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "governed-work-transition",
        "required_courts": (
            "personal-brain-mcp/tests/test_active_work_db.py",
            "personal-brain-mcp/tests/test_active_work_cell_migration.py",
            "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
        ),
    },
    {
        "capability": "hook-coverage",
        "source_path": "personal-brain-mcp/src/personal_brain/hook_coverage.py",
        "source_symbol": "register_hook_coverage_tools",
        "tool_names": (
            "brain.hook_coverage_audit_cell_first",
            "brain.hook_coverage_get",
            "brain.hook_coverage_repair_cell_first",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "hook-repair",
        "required_courts": (
            "personal-brain-mcp/tests/test_hook_coverage.py",
            "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
            "personal-brain-mcp/tests/test_installer_coverage.py",
        ),
    },
    {
        "capability": "compliance-history",
        "source_path": "personal-brain-mcp/src/personal_brain/compliance_report.py",
        "source_symbol": "register_compliance_report_tools",
        "tool_names": (
            "brain.compliance_report",
            "brain.compliance_event_append_cell_first",
            "brain.compliance_history_get",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "audit-ledger",
        "required_courts": (
            "personal-brain-mcp/tests/test_compliance_report.py",
            "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
        ),
    },
    {
        "capability": "run-report",
        "source_path": "personal-brain-mcp/src/personal_brain/run_report.py",
        "source_symbol": "register_run_report_tools",
        "tool_names": (
            "brain.run_report_append_cell_first",
            "brain.run_report_get",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "audit-ledger",
        "required_courts": (
            "personal-brain-mcp/tests/test_run_report.py",
            "personal-brain-mcp/tests/test_brain_control_cell_migration.py",
        ),
    },
    {
        "capability": "core-values-authority",
        "source_path": "personal-brain-mcp/src/personal_brain/core_values_authority.py",
        "source_symbol": "register_core_values_authority_tools",
        "tool_names": (
            "brain.core_values_authority_audit",
            "brain.core_values_authority_get",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "audit-ledger",
        "required_courts": (
            "personal-brain-mcp/tests/test_core_values_authority_cell_migration.py",
            "personal-brain-mcp/tests/test_universal_runtime_bridge.py",
        ),
    },
    {
        "capability": "workshop-room",
        "source_path": "personal-brain-mcp/src/personal_brain/cell_room.py",
        "source_symbol": "register_cell_room_tools",
        "tool_names": (
            "brain.room_say",
            "brain.room_read",
            "brain.room_leaf_gate",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "workshop-gate",
        "required_courts": (
            "personal-brain-mcp/tests/test_active_work_db.py",
            "personal-brain-mcp/tests/test_server.py",
        ),
    },
    {
        "capability": "grand-map-sync",
        "source_path": "personal-brain-mcp/src/personal_brain/grand_map_sync.py",
        "source_symbol": "register_grand_map_sync_tools",
        "tool_names": (
            "brain.grand_map_work_preview_cell_first",
            "brain.grand_map_work_sync_cell_first",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "requirement-sync",
        "required_courts": (
            "personal-brain-mcp/tests/test_grand_map_sync.py",
            "personal-brain-mcp/tests/test_universal_runtime_bridge.py",
        ),
    },
    {
        "capability": "roma-requirement-court",
        "source_path": "personal-brain-mcp/src/personal_brain/roma.py",
        "source_symbol": "register_roma_tools",
        "tool_names": (
            "brain.roma_atomize",
            "brain.roma_decompose",
            "brain.roma_claim",
            "brain.roma_judge",
            "brain.roma_server_verify",
            "brain.roma_sweep",
            "brain.roma_frontier",
            "brain.roma_list",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "cell-first-route",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "false",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "court-attestation",
        "required_courts": (
            "personal-brain-mcp/tests/test_roma.py",
            "personal-brain-mcp/tests/test_server_verify.py",
        ),
    },
    {
        "capability": "secret-resolution",
        "source_path": "personal-brain-mcp/src/personal_brain/secret_resolver.py",
        "source_symbol": "resolve_secret",
        "tool_names": (),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "external-adapter-projection",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "true",
        "brain_meta_write": "false",
        "cell_read": "false",
        "cell_write": "false",
        "effect_boundary": "secret-custody",
        "required_courts": (
            "personal-brain-mcp/tests/test_secret_resolver.py",
        ),
    },
    {
        "capability": "runtime-holder-audit",
        "source_path": "tools/legacy_runtime_drain.py",
        "source_symbol": "sync_runtime_holders_to_universal",
        "tool_names": (),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "mixed-cell-first",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "true",
        "brain_meta_write": "false",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "process-audit",
        "required_courts": (
            "tests/test_live_runtime_holders.py",
            "tests/test_legacy_runtime_drain.py",
            "tests/test_runtime_retirement_hook.py",
        ),
    },
    {
        "capability": "reflexion-skill-mint",
        "source_path": "personal-brain-mcp/src/personal_brain/server.py",
        "source_symbol": "queue_skill_mint_with_cell_receipt",
        "tool_names": (
            "brain.skill_mint",
        ),
        "authority": ACTIVE_CELL_AUTHORITY,
        "authority_mode": "mixed-cell-first",
        "legacy_status": AUTHORITY_STATUS,
        "legacy_migration_only": "true",
        "brain_meta_write": "true",
        "cell_read": "true",
        "cell_write": "true",
        "effect_boundary": "agent-skill-proposal",
        "required_courts": (
            "personal-brain-mcp/tests/test_reflexion.py",
        ),
    },
)

SPEC_FIELDS = (
    "capability",
    "source_path",
    "source_symbol",
    "authority",
    "authority_mode",
    "legacy_status",
    "legacy_migration_only",
    "brain_meta_write",
    "cell_read",
    "cell_write",
    "effect_boundary",
)
MULTI_FIELDS = ("tool_names", "required_courts")


@dataclass(frozen=True, slots=True)
class LegacyBrainGovernanceProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown legacy Brain governance role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class LegacyBrainGovernanceContract:
    root_id: str
    capability_roots: tuple[str, ...]


def brain_governance_contract_digest(
    specs: tuple[Mapping[str, object], ...],
) -> str:
    normalized = _validate_specs(specs)
    lines: list[str] = []
    for spec in normalized:
        lines.append("|".join(str(spec[field]) for field in SPEC_FIELDS))
        lines.extend("tool:%s" % item for item in spec["tool_names"])
        lines.extend("court:%s" % item for item in spec["required_courts"])
        lines.append("")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def bootstrap_legacy_brain_governance_protocol(
    store: CellStore,
    *,
    prefix: str = "legacy-brain-governance-protocol",
) -> LegacyBrainGovernanceProtocol:
    roles = MappingProxyType({
        name: "%s:role:%s" % (prefix, name)
        for name in ROLE_NAMES
    })
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    root_id = prefix + ":root"
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return LegacyBrainGovernanceProtocol(root_id, roles)


def build_legacy_brain_governance_contract(
    store: CellStore,
    protocol: LegacyBrainGovernanceProtocol,
    *,
    specs: tuple[Mapping[str, object], ...] = BRAIN_GOVERNANCE_SPECS,
    contract_id: str = DEFAULT_CONTRACT_ROOT,
) -> LegacyBrainGovernanceContract:
    normalized = _validate_specs(specs)
    digest_root = contract_id + ":digest"
    promotion_allowed_root = contract_id + ":promotion-allowed"
    batch = CellBatch(store)
    batch.add(Cell(
        digest_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        brain_governance_contract_digest(normalized).encode("ascii"),
    ))
    batch.add(Cell(
        promotion_allowed_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"false",
    ))

    capability_roots = []
    for spec in normalized:
        slug = str(spec["capability"])
        capability_root = "%s:capability:%s" % (contract_id, slug)
        field_roots = {}
        for field in SPEC_FIELDS:
            root_id = "%s:%s" % (capability_root, field.replace("_", "-"))
            batch.add(
                Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(spec[field]).encode("utf-8"))
            )
            field_roots[field] = root_id
        tool_roots = []
        for index, tool_name in enumerate(spec["tool_names"]):
            root_id = "%s:tool:%s" % (capability_root, index)
            batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, tool_name.encode("utf-8")))
            tool_roots.append(root_id)
        court_roots = []
        for index, court in enumerate(spec["required_courts"]):
            root_id = "%s:court:%s" % (capability_root, index)
            batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, court.encode("utf-8")))
            court_roots.append(root_id)
        batch.relation(
            (
                (protocol.role("capability"), field_roots["capability"]),
                (protocol.role("source-path"), field_roots["source_path"]),
                (protocol.role("source-symbol"), field_roots["source_symbol"]),
                (protocol.role("authority"), field_roots["authority"]),
                (protocol.role("authority-mode"), field_roots["authority_mode"]),
                (protocol.role("legacy-status"), field_roots["legacy_status"]),
                (
                    protocol.role("legacy-migration-only"),
                    field_roots["legacy_migration_only"],
                ),
                (protocol.role("brain-meta-write"), field_roots["brain_meta_write"]),
                (protocol.role("cell-read"), field_roots["cell_read"]),
                (protocol.role("cell-write"), field_roots["cell_write"]),
                (protocol.role("effect-boundary"), field_roots["effect_boundary"]),
                (protocol.role("promotion-allowed"), promotion_allowed_root),
                *((protocol.role("tool"), root) for root in tool_roots),
                *((protocol.role("requires-court"), root) for root in court_roots),
            ),
            relation_id=capability_root,
        )
        capability_roots.append(capability_root)

    batch.relation(
        (
            (protocol.role("digest"), digest_root),
            (protocol.role("promotion-allowed"), promotion_allowed_root),
            *((protocol.role("capability"), root) for root in capability_roots),
        ),
        relation_id=contract_id,
    )
    batch.commit()
    return LegacyBrainGovernanceContract(contract_id, tuple(capability_roots))


def project_legacy_brain_governance_contract(
    snapshot: Snapshot,
    protocol: LegacyBrainGovernanceProtocol,
    contract_root: str = DEFAULT_CONTRACT_ROOT,
) -> dict[str, object]:
    members = read_relation(snapshot, contract_root, budget=100_000)
    digest = _text(snapshot, _one(members, protocol.role("digest"), "digest"))
    promotion_allowed = _text(
        snapshot,
        _one(members, protocol.role("promotion-allowed"), "promotion flag"),
    )
    capabilities = []
    for capability_root in _many(members, protocol.role("capability")):
        capability_members = read_relation(snapshot, capability_root, budget=1_000)
        spec: dict[str, object] = {
            "capability": _text(
                snapshot,
                _one(capability_members, protocol.role("capability"), "capability"),
            ),
            "source_path": _text(
                snapshot,
                _one(capability_members, protocol.role("source-path"), "source path"),
            ),
            "source_symbol": _text(
                snapshot,
                _one(
                    capability_members,
                    protocol.role("source-symbol"),
                    "source symbol",
                ),
            ),
            "authority": _text(
                snapshot,
                _one(capability_members, protocol.role("authority"), "authority"),
            ),
            "authority_mode": _text(
                snapshot,
                _one(
                    capability_members,
                    protocol.role("authority-mode"),
                    "authority mode",
                ),
            ),
            "legacy_status": _text(
                snapshot,
                _one(
                    capability_members,
                    protocol.role("legacy-status"),
                    "legacy status",
                ),
            ),
            "legacy_migration_only": _text(
                snapshot,
                _one(
                    capability_members,
                    protocol.role("legacy-migration-only"),
                    "legacy migration flag",
                ),
            ),
            "brain_meta_write": _text(
                snapshot,
                _one(
                    capability_members,
                    protocol.role("brain-meta-write"),
                    "Brain meta write flag",
                ),
            ),
            "cell_read": _text(
                snapshot,
                _one(capability_members, protocol.role("cell-read"), "Cell read flag"),
            ),
            "cell_write": _text(
                snapshot,
                _one(
                    capability_members,
                    protocol.role("cell-write"),
                    "Cell write flag",
                ),
            ),
            "effect_boundary": _text(
                snapshot,
                _one(
                    capability_members,
                    protocol.role("effect-boundary"),
                    "effect boundary",
                ),
            ),
            "tool_names": tuple(
                _text(snapshot, root)
                for root in _many(capability_members, protocol.role("tool"))
            ),
            "required_courts": tuple(
                _text(snapshot, root)
                for root in _many(
                    capability_members,
                    protocol.role("requires-court"),
                )
            ),
        }
        _expect_shared(
            capability_members,
            protocol.role("promotion-allowed"),
            promotion_allowed,
            snapshot=snapshot,
            label="promotion flag",
        )
        capabilities.append(spec)
    specs = tuple(capabilities)
    if brain_governance_contract_digest(specs) != digest:
        raise InvalidCell("legacy Brain governance contract digest drifted")
    if promotion_allowed != "false":
        raise InvalidCell("legacy Brain governance contract cannot be promotable")
    modes = tuple(str(spec["authority_mode"]) for spec in specs)
    return {
        "root": contract_root,
        "digest": digest,
        "active_authority": ACTIVE_CELL_AUTHORITY,
        "authority_status": AUTHORITY_STATUS,
        "promotion_allowed": False,
        "capability_count": len(specs),
        "authority_modes": modes,
        "capabilities": specs,
    }


def _validate_specs(
    specs: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    if type(specs) is not tuple or not specs:
        raise InvalidCell("legacy Brain governance specs must be a non-empty tuple")
    required = set(SPEC_FIELDS) | set(MULTI_FIELDS)
    seen_capabilities: set[str] = set()
    normalized = []
    for spec in specs:
        if set(spec) != required:
            raise InvalidCell("legacy Brain governance spec fields are invalid")
        item: dict[str, object] = {}
        for field in SPEC_FIELDS:
            value = str(spec[field])
            if not value.strip() or value != value.strip():
                raise InvalidCell("legacy Brain governance field is blank or padded")
            item[field] = value
        capability = str(item["capability"])
        if capability in seen_capabilities:
            raise InvalidCell("legacy Brain governance capability is duplicated")
        seen_capabilities.add(capability)
        source_path = str(item["source_path"])
        if not source_path.endswith(".py") or source_path.startswith(("/", "\\")):
            raise InvalidCell("legacy Brain governance source path is invalid")
        if not (
            source_path.startswith("personal-brain-mcp/src/personal_brain/")
            or source_path.startswith("tools/")
        ):
            raise InvalidCell("legacy Brain governance source path is outside control plane")
        if item["authority"] != ACTIVE_CELL_AUTHORITY:
            raise InvalidCell("legacy Brain governance must be admitted by Cell authority")
        if item["legacy_status"] != AUTHORITY_STATUS:
            raise InvalidCell("legacy Brain governance status drifted")
        if item["authority_mode"] not in AUTHORITY_MODES:
            raise InvalidCell("legacy Brain governance authority mode is invalid")
        if item["effect_boundary"] not in EFFECT_BOUNDARIES:
            raise InvalidCell("legacy Brain governance effect boundary is invalid")
        for field in (
            "legacy_migration_only",
            "brain_meta_write",
            "cell_read",
            "cell_write",
        ):
            if item[field] not in {"true", "false"}:
                raise InvalidCell("legacy Brain governance flags must be true/false")
        tools = _validate_tuple_field(spec["tool_names"], "tool")
        courts = _validate_tuple_field(spec["required_courts"], "court")
        for tool in tools:
            if not tool.startswith("brain."):
                raise InvalidCell("legacy Brain governance tool must be namespaced")
        for court in courts:
            if not (
                court.startswith("personal-brain-mcp/tests/")
                or court.startswith("tests/")
            ):
                raise InvalidCell("legacy Brain governance court is outside test roots")
        if item["authority_mode"] in {"cell-first-route", "mixed-cell-first"}:
            if item["cell_read"] != "true" and item["cell_write"] != "true":
                raise InvalidCell("cell-first Brain channels must touch Cell routes")
        if item["brain_meta_write"] == "true" and item["legacy_migration_only"] != "true":
            raise InvalidCell("Brain meta writers must remain legacy migration only")
        item["tool_names"] = tools
        item["required_courts"] = courts
        normalized.append(MappingProxyType(item))
    return tuple(normalized)


def _validate_tuple_field(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise InvalidCell("legacy Brain governance %s list must be a tuple" % label)
    seen = set()
    out = []
    for item in value:
        text = str(item)
        if not text.strip() or text != text.strip():
            raise InvalidCell("legacy Brain governance %s value is blank or padded" % label)
        if text in seen:
            raise InvalidCell("legacy Brain governance %s value is duplicated" % label)
        seen.add(text)
        out.append(text)
    return tuple(out)


def _many(members: tuple[RelationMember, ...], role_root: str) -> tuple[str, ...]:
    return tuple(member.participant_id for member in members if member.role_id == role_root)


def _one(members: tuple[RelationMember, ...], role_root: str, label: str) -> str:
    values = _many(members, role_root)
    if len(values) != 1:
        raise InvalidCell("legacy Brain governance contract requires exactly one %s" % label)
    return values[0]


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("legacy Brain governance contract references a missing Cell")
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("legacy Brain governance contract expected a terminal atom")
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("legacy Brain governance contract atom is not UTF-8") from exc


def _expect_shared(
    members: tuple[RelationMember, ...],
    role_root: str,
    expected_text: str,
    *,
    snapshot: Snapshot,
    label: str,
) -> None:
    root = _one(members, role_root, label)
    if _text(snapshot, root) != expected_text:
        raise InvalidCell("legacy Brain governance contract has inconsistent %s" % label)


__all__ = [
    "ACTIVE_CELL_AUTHORITY",
    "AUTHORITY_STATUS",
    "BRAIN_GOVERNANCE_SPECS",
    "DEFAULT_CONTRACT_ROOT",
    "LegacyBrainGovernanceContract",
    "LegacyBrainGovernanceProtocol",
    "bootstrap_legacy_brain_governance_protocol",
    "brain_governance_contract_digest",
    "build_legacy_brain_governance_contract",
    "project_legacy_brain_governance_contract",
]
