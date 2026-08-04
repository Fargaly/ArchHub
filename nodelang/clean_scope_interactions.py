"""Install and execute clean graph-held scope-open interactions.

These interactions are installed once through the clean authority receipt path.
Canvas projection only reads the published interaction roots and issues a
disposable lease; it never mutates the graph during GET.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sys
import uuid
from types import MappingProxyType
from typing import Mapping

from . import cell_interactions
from .cell_interactions import (
    InteractionProjectionBroker,
    InteractionProtocol,
    ROLE_NAMES,
    STATE_NAMES,
    build_interaction,
    project_interaction_protocol,
    read_interaction,
)
from .cell_protocols import read_relation
from .cell_source_assembly import SourceCellBatch, remap_source_cells, source_modules_digest
from .clean_browser_authority import CleanBrowserAuthority
from .unified_authority import (
    CODEC_NAME,
    COMMAND_BUDGET,
    CallerCommandCapability,
    CommandResult,
    UnifiedAuthority,
    _append_relation_member,
    _build_value,
    _commit_with_receipt,
    _decode_value,
    _digest,
    _find_receipt,
    _new_id,
    _typed_relation_cells,
    _validate_command_participants,
    audit_authority_history,
    verify_exact_authority_head,
    composition_root,
    read_scope_level,
    validate_composition,
)
from .cell_control_bindings import CAPABILITY_SCOPE
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


CLEAN_SCOPE_INTERACTIONS_LABEL = "ArchHub clean scope interactions"
CLEAN_SCOPE_INTERACTIONS_VERSION = "clean-scope-interactions/v1"
_SOURCE_PREFIX = "source:clean-scope-interactions"
_EVENT_LABEL = "open"


@dataclass(frozen=True, slots=True)
class ScopeOpenBinding:
    scope_root: str
    control_root: str
    target_root: str
    interaction_root: str


@dataclass(frozen=True, slots=True)
class CleanScopeInteractions:
    graph_id: str
    root_id: str
    protocol: InteractionProtocol
    event_root: str
    source_digest: str
    revision: int
    replayed: bool
    receipt_root: str | None
    bindings: Mapping[str, Mapping[str, ScopeOpenBinding]]

    def binding_for(self, scope_root: str, control_root: str) -> ScopeOpenBinding | None:
        return self.bindings.get(scope_root, {}).get(control_root)


def _compile_protocol_source() -> tuple[tuple[Cell, ...], InteractionProtocol]:
    batch = SourceCellBatch()
    source_roles = {
        name: f"{_SOURCE_PREFIX}:role:{name}" for name in ROLE_NAMES
    }
    source_states = {
        name: f"{_SOURCE_PREFIX}:state:{name}" for name in STATE_NAMES
    }
    source_root = f"{_SOURCE_PREFIX}:root"
    for name, root_id in source_roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    for name, root_id in source_states.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    batch.relation(
        (
            (source_roles["vocabulary-member"], root)
            for root in (*source_roles.values(), *source_states.values())
        ),
        relation_id=source_root,
    )
    cells, identities = remap_source_cells(batch.cells)
    return cells, InteractionProtocol(
        identities[source_root],
        MappingProxyType({
            name: identities[root] for name, root in source_roles.items()
        }),
        MappingProxyType({
            name: identities[root] for name, root in source_states.items()
        }),
    )


def _entry_cells(
    authority: UnifiedAuthority,
    label: str,
    target_root: str,
) -> tuple[str, tuple[Cell, ...]]:
    label_root, label_cells = _build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        label,
        shape_root=authority.shape("value"),
    )
    entry_root = _new_id()
    cells = _typed_relation_cells(
        entry_root,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("body"), target_root),
        ),
    )
    return entry_root, (*label_cells, *cells)


def _one_member(members, role_id: str, label: str) -> str:
    roots = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(roots) != 1:
        raise InvalidCell("clean scope interactions require one %s" % label)
    return roots[0]


def _read_entry(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    entry_root: str,
) -> tuple[str, str]:
    validate_composition(authority, snapshot, entry_root)
    members = read_relation(snapshot, entry_root, budget=256)
    label_root = _one_member(members, authority.role("label"), "entry label")
    target_root = _one_member(members, authority.role("body"), "entry target")
    label = _decode_value(authority, snapshot, label_root)
    if type(label) is not str or not label:
        raise InvalidCell("clean scope interaction entry label is invalid")
    if target_root not in snapshot.cells:
        raise InvalidCell("clean scope interaction entry target is missing")
    return label, target_root


def _binding_specs(
    authority: UnifiedAuthority,
    scope_root: str,
    caller: CallerCommandCapability,
) -> tuple[tuple[str, str, str], ...]:
    snapshot = authority.store.snapshot()
    queue = [scope_root]
    seen: set[str] = set()
    specs: list[tuple[str, str, str]] = []
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        level = read_scope_level(
            authority,
            current,
            scope_root=current,
            caller=caller,
            at_revision=snapshot.revision,
            budget=COMMAND_BUDGET,
        )
        for target_root in sorted(level.composition_roots):
            specs.append((current, target_root, target_root))
            if target_root not in seen:
                queue.append(target_root)
    return tuple(specs)


def _source_digest(binding_specs: tuple[tuple[str, str, str], ...]) -> str:
    module_digest = source_modules_digest(
        CLEAN_SCOPE_INTERACTIONS_VERSION,
        (sys.modules[__name__], cell_interactions),
    )
    return _digest({
        "module-digest": module_digest,
        "bindings": binding_specs,
        "event": _EVENT_LABEL,
        "version": CLEAN_SCOPE_INTERACTIONS_VERSION,
    })


def _interaction_sets_in_interface(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    interface_root: str,
) -> tuple[CleanScopeInteractions, ...]:
    members = read_relation(snapshot, interface_root, budget=10_000)
    roots = tuple(
        member.participant_id
        for member in members
        if member.role_id == authority.role("composition")
    )
    systems: list[CleanScopeInteractions] = []
    for root_id in roots:
        try:
            current = _read_scope_interactions(authority, snapshot, root_id)
        except InvalidCell:
            continue
        if current is not None:
            systems.append(current)
    return tuple(systems)


def _read_scope_interactions(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
) -> CleanScopeInteractions | None:
    composition = validate_composition(authority, snapshot, root_id)
    if composition.protocol_root != authority.shape("composition"):
        return None
    members = composition.members
    label_root = _one_member(members, authority.role("label"), "label")
    label = _decode_value(authority, snapshot, label_root)
    if label != CLEAN_SCOPE_INTERACTIONS_LABEL:
        return None
    digest_root = _one_member(members, authority.role("content-digest"), "digest")
    protocol_root = _one_member(
        members, authority.role("protocol-definition"), "protocol definition"
    )
    source_digest = _decode_value(authority, snapshot, digest_root)
    if type(source_digest) is not str or len(source_digest) != 64:
        raise InvalidCell("clean scope interaction source digest is invalid")
    protocol = project_interaction_protocol(snapshot, protocol_root, budget=1024)
    bindings: dict[str, dict[str, ScopeOpenBinding]] = {}
    event_root: str | None = None
    for entry_root in (
        member.participant_id
        for member in members
        if member.role_id == authority.role("item")
    ):
        label, target_root = _read_entry(authority, snapshot, entry_root)
        parts = label.split("/")
        if parts[:2] == ["event", _EVENT_LABEL] and len(parts) == 2:
            if event_root is not None and event_root != target_root:
                raise InvalidCell("clean scope interaction event is duplicated")
            event_root = target_root
            continue
        if len(parts) == 2 and parts[0] in {"role", "state"}:
            continue
        if len(parts) != 4 or parts[0] != "binding":
            raise InvalidCell("clean scope interaction entry label is invalid")
        scope_root, control_root, declared_target = parts[1:]
        interaction = read_interaction(snapshot, protocol, target_root, budget=1024)
        if (
            interaction.control_root != control_root
            or interaction.event_root == NULL_CELL_ID
            or len(interaction.input_roots) != 2
            or interaction.input_roots[0] != scope_root
            or interaction.input_roots[1] != declared_target
        ):
            raise InvalidCell("clean scope interaction binding drifted")
        bindings.setdefault(scope_root, {})[control_root] = ScopeOpenBinding(
            scope_root,
            control_root,
            declared_target,
            interaction.root_id,
        )
    if event_root is None:
        raise InvalidCell("clean scope interaction event is missing")
    return CleanScopeInteractions(
        authority.manifest.graph_id,
        root_id,
        protocol,
        event_root,
        source_digest,
        snapshot.revision,
        False,
        None,
        MappingProxyType({
            scope_root: MappingProxyType(controls)
            for scope_root, controls in bindings.items()
        }),
    )


def install_clean_scope_interactions(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CleanScopeInteractions:
    """Install one signed clean interaction set for all reachable open scopes."""
    binding_specs = _binding_specs(authority, scope_root, caller)
    source_digest = _source_digest(binding_specs)
    request_digest = _digest({
        "intent": "install-clean-scope-interactions",
        "scope-root": scope_root,
        "source-digest": source_digest,
        "version": CLEAN_SCOPE_INTERACTIONS_VERSION,
    })
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="install-clean-scope-interactions",
        request_digest=request_digest,
        object_root=interface_root,
        scope_root=interface_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        current = authority.store.snapshot()
        installed = _read_scope_interactions(authority, current, existing.result_root)
        if installed is None:
            raise InvalidCell("clean scope interaction receipt result is invalid")
        return CleanScopeInteractions(
            installed.graph_id,
            installed.root_id,
            installed.protocol,
            installed.event_root,
            installed.source_digest,
            installed.revision,
            True,
            existing.root_id,
            installed.bindings,
        )
    installed = _interaction_sets_in_interface(authority, snapshot, interface_root)
    if installed:
        current = installed[0]
        if current.source_digest != source_digest:
            raise InvalidCell(
                "a different clean scope interaction source is already installed"
            )
        return CleanScopeInteractions(
            current.graph_id,
            current.root_id,
            current.protocol,
            current.event_root,
            current.source_digest,
            current.revision,
            True,
            None,
            current.bindings,
        )

    protocol_cells, protocol = _compile_protocol_source()
    event_root = _new_id()
    event_cell = Cell(event_root, NULL_CELL_ID, NULL_CELL_ID, _EVENT_LABEL.encode("utf-8"))
    interaction_batch = SourceCellBatch()
    bindings: dict[str, dict[str, ScopeOpenBinding]] = {}
    for current_scope, control_root, target_root in binding_specs:
        interaction_root = _new_id()
        build_interaction(
            authority.store,
            protocol,
            interaction_id=interaction_root,
            control_root=control_root,
            event_root=event_root,
            target_root=browser.root_id,
            input_roots=(current_scope, target_root),
            action_root=CAPABILITY_SCOPE,
            subject_root=caller.actor_root,
            policy_root=authority.manifest.policy_root,
            authorization_action_root=authority.role("composition"),
            authorization_object_root=target_root,
            authorization_scope_roots=(
                authority.manifest.application_root,
                current_scope,
            ),
            version="0.1.0",
            batch=interaction_batch,
        )
        bindings.setdefault(current_scope, {})[control_root] = ScopeOpenBinding(
            current_scope,
            control_root,
            target_root,
            interaction_root,
        )

    cells: list[Cell] = [*protocol_cells, event_cell, *interaction_batch.cells]
    if CAPABILITY_SCOPE not in snapshot.cells:
        # The scope capability is the graph-held action every binding points
        # at; the first install must create it or the interaction relation
        # would reference a dangling identity.
        cells.append(
            Cell(CAPABILITY_SCOPE, NULL_CELL_ID, NULL_CELL_ID, b"scope")
        )
    entries: list[str] = []
    for category, roots in (
        ("role", protocol.roles),
        ("state", protocol.states),
    ):
        for name, target in sorted(roots.items()):
            entry_root, entry_cells = _entry_cells(
                authority, f"{category}/{name}", target
            )
            entries.append(entry_root)
            cells.extend(entry_cells)
    event_entry_root, event_entry_cells = _entry_cells(
        authority,
        f"event/{_EVENT_LABEL}",
        event_root,
    )
    entries.append(event_entry_root)
    cells.extend(event_entry_cells)
    for current_scope, control_bindings in sorted(bindings.items()):
        for control_root, binding in sorted(control_bindings.items()):
            entry_root, entry_cells = _entry_cells(
                authority,
                f"binding/{current_scope}/{control_root}/{binding.target_root}",
                binding.interaction_root,
            )
            entries.append(entry_root)
            cells.extend(entry_cells)
    label_root, label_cells = _build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        CLEAN_SCOPE_INTERACTIONS_LABEL,
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = _build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    root_id = _new_id()
    root_cells = _typed_relation_cells(
        root_id,
        authority.role("conforms-to"),
        authority.shape("composition"),
        (
            (authority.role("label"), label_root),
            (authority.role("content-digest"), digest_root),
            (authority.role("protocol-definition"), protocol.root_id),
            *((authority.role("item"), entry) for entry in entries),
        ),
    )
    interface_patch = _append_relation_member(
        snapshot,
        interface_root,
        authority.role("composition"),
        root_id,
    )
    result = _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *cells,
            *label_cells,
            *digest_cells,
            *root_cells,
            *interface_patch.create,
        ),
        resource_replace=interface_patch.replace,
        authenticated=authenticated,
        result_root=root_id,
        policy_proof=policy_proof,
    )
    current = authority.store.snapshot()
    installed_current = _read_scope_interactions(authority, current, result.root_id)
    if installed_current is None:
        raise InvalidCell("installed clean scope interactions are unreadable")
    return CleanScopeInteractions(
        installed_current.graph_id,
        installed_current.root_id,
        installed_current.protocol,
        installed_current.event_root,
        installed_current.source_digest,
        installed_current.revision,
        False,
        result.receipt_root,
        installed_current.bindings,
    )


def open_clean_scope_interactions(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> CleanScopeInteractions:
    """Open the one installed clean scope interaction set."""
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    installed = _interaction_sets_in_interface(authority, snapshot, interface_root)
    if len(installed) != 1:
        raise InvalidCell("clean scope interaction installation is incomplete")
    return installed[0]


def _submit_command_id(
    interaction_root: str,
    browser_session_root: str,
    control_root: str,
    event_root: str,
    expected_revision: int,
) -> str:
    """One stable identity for an exact scope-open submission."""
    return str(uuid.uuid5(
        uuid.UUID(interaction_root),
        f"{browser_session_root}:{control_root}:{event_root}:{expected_revision}",
    ))


def submit_clean_scope_interaction(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    interactions: CleanScopeInteractions,
    projection_broker: InteractionProjectionBroker,
    projection_handle: object,
    browser_session_root: str,
    *,
    interaction_root: str,
    control_root: str,
    event_root: str,
    expected_revision: int,
    projected_canvas: Mapping[str, object],
    caller: CallerCommandCapability,
) -> CommandResult:
    """Execute one preinstalled scope-open interaction through a signed receipt."""
    snapshot = authority.store.snapshot()
    # An exact retry of a command that already succeeded must return its
    # existing receipt. The command identity embeds the base revision, and a
    # successful submit advances that revision, so the replay lookup has to
    # happen before staleness is enforced or the retry path is unreachable.
    command_id = _submit_command_id(
        interaction_root,
        browser_session_root,
        control_root,
        event_root,
        expected_revision,
    )
    replayed = _find_receipt(
        authority,
        snapshot,
        caller.actor_root,
        caller.session_root,
        command_id,
    )
    if replayed is not None:
        return CommandResult(
            replayed.result_root,
            replayed.result_revision,
            True,
            0,
            0,
            replayed.root_id,
        )
    if snapshot.revision != expected_revision:
        raise InvalidCell("scope interaction base is stale")
    # Per-submission work must stay bounded. The exact signed head for this
    # revision is what authorizes this command; replaying the entire history
    # on every click would make each interaction cost grow with the graph,
    # which is the failure this rebuild exists to remove. The full audit
    # stays available for authority open and for the courts.
    verify_exact_authority_head(authority, snapshot)
    lease = projection_broker.resolve(
        projection_handle,
        snapshot,
        expected_revision=expected_revision,
        control_root=control_root,
        interaction_root=interaction_root,
    )
    interaction = read_interaction(snapshot, interactions.protocol, interaction_root)
    if interaction.event_root != event_root:
        raise InvalidCell("scope interaction event drifted")
    if (
        interaction.action_root != CAPABILITY_SCOPE
        or interaction.target_root != browser.root_id
        or interaction.subject_root != caller.actor_root
        or len(interaction.input_roots) != 2
    ):
        raise InvalidCell("scope interaction authority is invalid")
    current_scope, target_scope = interaction.input_roots
    if lease.session_root != browser_session_root:
        raise InvalidCell("scope interaction session drifted")
    if projected_canvas.get("root") != current_scope:
        raise InvalidCell("scope interaction current root drifted")
    binding = interactions.binding_for(current_scope, control_root)
    if (
        binding is None
        or binding.interaction_root != interaction_root
        or binding.target_root != target_scope
    ):
        raise InvalidCell("scope interaction destination is not projected")
    request_digest = _digest({
        "intent": "submit-clean-scope-interaction",
        "browser-session": browser_session_root,
        "control": control_root,
        "event": event_root,
        "expected-revision": expected_revision,
        "interaction": interaction_root,
        "scope": current_scope,
        "target": target_scope,
    })
    command_id = _submit_command_id(
        interaction_root,
        browser_session_root,
        control_root,
        event_root,
        expected_revision,
    )
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="submit-clean-scope-interaction",
        request_digest=request_digest,
        object_root=target_scope,
        scope_root=current_scope,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    session_members = read_relation(snapshot, browser_session_root, budget=512)
    def _member(role_name: str) -> str:
        return _one_member(session_members, browser.protocol.role(role_name), role_name)
    if _member("subject") != authenticated.actor_root:
        raise InvalidCell("scope interaction subject drifted")
    if _member("view") != authenticated.session_root:
        raise InvalidCell("scope interaction view drifted")
    if _member("tenant") != authority.manifest.application_root:
        raise InvalidCell("scope interaction tenant drifted")
    if _member("assurance") != browser.root_id:
        raise InvalidCell("scope interaction assurance drifted")
    state_root = _member("state")
    if state_root != browser.protocol.states["active"]:
        raise InvalidCell("scope interaction browser session is revoked")
    try:
        issued_at = float(snapshot.cells[_member("issued-at")].atom.decode("utf-8"))
        expires_at = float(snapshot.cells[_member("expires-at")].atom.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("scope interaction browser session timing is invalid") from exc
    now = datetime.now(timezone.utc).timestamp()
    if issued_at > now + 5 or expires_at <= now:
        raise InvalidCell("scope interaction browser session is expired")
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(),
        resource_replace=(),
        authenticated=authenticated,
        result_root=target_scope,
        policy_proof=policy_proof,
    )


__all__ = [
    "CLEAN_SCOPE_INTERACTIONS_LABEL",
    "CLEAN_SCOPE_INTERACTIONS_VERSION",
    "CleanScopeInteractions",
    "ScopeOpenBinding",
    "install_clean_scope_interactions",
    "open_clean_scope_interactions",
    "submit_clean_scope_interaction",
]
