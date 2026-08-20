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
    read_definition,
    CODEC_NAME,
    COMMAND_BUDGET,
    CallerCommandCapability,
    CommandResult,
    UnifiedAuthority,
    append_relation_member,
    build_value,
    commit_with_receipt,
    decode_value,
    digest,
    find_receipt,
    new_id,
    typed_relation_cells,
    validate_command_participants,
    audit_authority_history,
    verify_exact_authority_head,
    composition_root,
    read_scope_level,
    validate_composition,
)
from .cell_control_bindings import (
    CAPABILITY_COMPOSITION,
    CAPABILITY_EXECUTE,
    CAPABILITY_INSTANTIATE,
    CAPABILITY_SCOPE,
)
from .clean_subsystem_revision import replace_interface_subsystem
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


CONTROL_RUN = "app:control:canvas:run"
CONTROL_GROUP = "app:control:canvas:group"
CONTROL_UNGROUP = "app:control:canvas:ungroup"
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

    @property
    def root_scope(self) -> str | None:
        """The door: the one scope every other scope can open the way back to.

        Not stored -- read off the set itself, so an installed table and a
        derivation answer alike. With one scope it is that scope; with
        many, it is the scope that is the target of a binding from every
        other scope (the way-back binding each scope below it carries).
        """
        held = _ROOT_SCOPE_MEMO.get(id(self))
        if held is not None and held[0] is self:
            return held[1]
        keys = tuple(self.bindings)
        door: str | None = None
        if len(keys) == 1:
            door = keys[0]
        else:
            targets_by_scope = {
                scope: {item.target_root for item in controls.values()}
                for scope, controls in self.bindings.items()
            }
            for scope in keys:
                if all(
                    scope in targets_by_scope[other]
                    for other in keys if other != scope
                ):
                    door = scope
                    break
        if len(_ROOT_SCOPE_MEMO) >= 8:
            _ROOT_SCOPE_MEMO.pop(next(iter(_ROOT_SCOPE_MEMO)))
        _ROOT_SCOPE_MEMO[id(self)] = (self, door)
        return door


_ROOT_SCOPE_MEMO: dict[int, tuple["CleanScopeInteractions", str | None]] = {}


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


# Identity derived from what a thing IS, not from when it was written.
# Every rebind used to mint a fresh uuid for the event, for each
# interaction, and for each entry -- so a binding that had not changed
# still became new cells, and one rebind wrote 1,133,504 of them. Two
# rebinds of the same bindings now produce the same identities, and the
# store already holds those cells.
_IDENTITY_NAMESPACE = uuid.UUID("6f2a1d3e-7c4b-5a89-9e01-2b3c4d5e6f70")


def _derived_id(graph_id: str, *parts: str) -> str:
    return str(uuid.uuid5(_IDENTITY_NAMESPACE, "::".join((graph_id, *parts))))


def _entry_cells(
    authority: UnifiedAuthority,
    label: str,
    target_root: str,
) -> tuple[str, tuple[Cell, ...]]:
    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        label,
        shape_root=authority.shape("value"),
    )
    entry_root = _derived_id(
        authority.manifest.graph_id, "entry", label, target_root
    )
    cells = typed_relation_cells(
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
    label = decode_value(authority, snapshot, label_root)
    if type(label) is not str or not label:
        raise InvalidCell("clean scope interaction entry label is invalid")
    if target_root not in snapshot.cells:
        raise InvalidCell("clean scope interaction entry target is missing")
    return label, target_root


def _binding_specs(
    authority: UnifiedAuthority,
    scope_root: str,
    caller: CallerCommandCapability,
) -> tuple[tuple[str, str, str, str], ...]:
    snapshot = authority.store.snapshot()
    published = tuple(
        member.participant_id
        for member in read_relation(
            snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
        )
        if member.role_id == authority.role("definition")
        and read_definition(
            authority, member.participant_id, caller=caller
        ).lifecycle == "published"
    )
    queue = [scope_root]
    seen: set[str] = set()
    specs: list[tuple[str, str, str, str]] = []
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
            # A scope that lists itself would produce an interaction whose
            # two inputs are the same root, and an interaction that repeats
            # a participant is refused on read -- which makes the whole
            # installed set unreadable, not just that one entry. Opening a
            # scope into itself is not an interaction anyone can take.
            if target_root == current:
                continue
            specs.append((current, target_root, target_root, CAPABILITY_SCOPE))
            if target_root not in seen:
                queue.append(target_root)
        # Opening a scope is not the only thing a scope affords. Running
        # what is focused is a second one, and the client will not activate
        # a control the graph has declared no interaction for -- so a Run
        # button with no interaction behind it is a button that does
        # nothing, silently. Which node it runs is decided by the focus at
        # the moment it is pressed, so the interaction belongs to the
        # scope rather than to any one node in it.
        specs.append((current, CONTROL_RUN, CONTROL_RUN, CAPABILITY_EXECUTE))
        # Grouping the selection and dissolving a group are scope acts the
        # toolbar declares; without interactions behind them the buttons
        # were chrome. What they act on is the graph-held focus, read at
        # submit time.
        specs.append((
            current, CONTROL_GROUP, CONTROL_GROUP, CAPABILITY_COMPOSITION,
        ))
        specs.append((
            current, CONTROL_UNGROUP, CONTROL_UNGROUP, CAPABILITY_COMPOSITION,
        ))
        # Placing a definition from the library is a third thing a scope
        # affords, and the client will not activate a place control that
        # the graph declared no interaction for. Each published definition
        # is its own control here, the same way each node is its own
        # control for opening.
        for definition_root in published:
            if definition_root == current:
                continue
            specs.append((
                current, definition_root, definition_root,
                CAPABILITY_INSTANTIATE,
            ))
        # The way back. Entering a domain was a one-way door: the trail
        # held only the scope the founder stood in, and the graph had
        # declared no interaction that opens the map again, so the
        # breadcrumb drew nothing to press. Opening the door scope from any
        # scope below it is the same kind of act as opening a child, and
        # it is derived here the same way.
        if current != scope_root:
            specs.append((current, scope_root, scope_root, CAPABILITY_SCOPE))
    return tuple(specs)


def unbound_published_definitions(
    authority: UnifiedAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
) -> tuple[str, ...]:
    """Published definitions the installed set cannot place in this scope.

    Publishing a definition and binding it are two acts. The library
    lists what is published; only what is bound can be placed. Do the
    first without the second and the canvas fills with cards that
    refuse -- no error anywhere, because nothing is wrong until somebody
    clicks.

    This is the question an operator has after publishing anything, and
    the answer nobody could get before: the empty tuple means the
    library is honest.
    """
    snapshot = authority.store.snapshot()
    published = tuple(
        member.participant_id
        for member in read_relation(
            snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
        )
        if member.role_id == authority.role("definition")
        and read_definition(
            authority, member.participant_id, caller=caller
        ).lifecycle == "published"
    )
    try:
        installed = open_clean_scope_interactions(authority, caller=caller)
    except InvalidCell:
        return published
    bound = set(installed.bindings.get(scope_root, {}))
    return tuple(
        definition_root for definition_root in published
        if definition_root not in bound and definition_root != scope_root
    )


def _source_digest(binding_specs: tuple[tuple[str, str, str, str], ...]) -> str:
    module_digest = source_modules_digest(
        CLEAN_SCOPE_INTERACTIONS_VERSION,
        (sys.modules[__name__], cell_interactions),
    )
    return digest({
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
    members = read_relation(snapshot, interface_root, budget=COMMAND_BUDGET)
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
    # The installed set is a command-scale structure: one entry per scope
    # per control, across every scope the canvas can reach. Reading it at
    # the ten-thousand-cell default refused the whole set once it grew,
    # and a set that cannot be read is a canvas where no control works.
    composition = validate_composition(
        authority, snapshot, root_id, budget=COMMAND_BUDGET
    )
    if composition.protocol_root != authority.shape("composition"):
        return None
    members = composition.members
    label_root = _one_member(members, authority.role("label"), "label")
    label = decode_value(authority, snapshot, label_root)
    if label != CLEAN_SCOPE_INTERACTIONS_LABEL:
        return None
    digest_root = _one_member(members, authority.role("content-digest"), "digest")
    protocol_root = _one_member(
        members, authority.role("protocol-definition"), "protocol definition"
    )
    source_digest = decode_value(authority, snapshot, digest_root)
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


WRITTEN_CELL_LIMIT = 250_000


def revise_clean_scope_interactions(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
    cell_limit: int | None = WRITTEN_CELL_LIMIT,
) -> CleanScopeInteractions:
    """Carry a newer interaction source onto a graph that holds an older one.

    Installing refuses a source it did not already have, so without this a
    graph could never be told about an interaction that did not exist when
    it was first installed -- a control added later would be a button the
    client refuses to activate, silently, forever.
    """
    binding_specs = _binding_specs(authority, scope_root, caller)
    source_digest = _source_digest(binding_specs)
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    installed = _interaction_sets_in_interface(
        authority, snapshot, interface_root
    )
    if not installed:
        raise InvalidCell("no clean scope interaction set is installed to revise")
    held = installed[0]
    if held.source_digest == source_digest:
        raise InvalidCell(
            "the installed clean scope interactions already carry this source"
        )
    protocol_cells, protocol = _compile_protocol_source()
    event_root = _derived_id(
        authority.manifest.graph_id, "event", _EVENT_LABEL
    )
    event_cell = Cell(event_root, NULL_CELL_ID, NULL_CELL_ID, _EVENT_LABEL.encode("utf-8"))
    interaction_batch = SourceCellBatch()
    bindings: dict[str, dict[str, ScopeOpenBinding]] = {}
    for current_scope, control_root, target_root, capability_root in binding_specs:
        interaction_root = _derived_id(
            authority.manifest.graph_id, "interaction",
            current_scope, control_root, target_root, capability_root,
        )
        build_interaction(
            authority.store,
            protocol,
            interaction_id=interaction_root,
            control_root=control_root,
            event_root=event_root,
            target_root=browser.root_id,
            input_roots=(current_scope, target_root),
            action_root=capability_root,
            subject_root=caller.actor_root,
            policy_root=authority.manifest.policy_root,
            authorization_action_root=authority.role("composition"),
            authorization_object_root=target_root,
            # The proof asks whether the subject may compose the target
            # within a scope that holds it. A child is held by the scope it
            # is opened from; the door -- the way back, opened from a scope
            # below it -- is held by itself.
            authorization_scope_roots=(
                authority.manifest.application_root,
                target_root if target_root == scope_root else current_scope,
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
    for declared_root, declared_label in (
        (CAPABILITY_SCOPE, b"scope"),
        (CAPABILITY_EXECUTE, b"execute"),
        # A scope-open binding names a node that already exists, so its
        # control needs no cell of its own. The Run control is named by the
        # catalogue rather than by the canvas, so the graph has to carry
        # its identity or every interaction pointing at it dangles.
        (CONTROL_RUN, b"run"),
        (CONTROL_GROUP, b"group"),
        (CONTROL_UNGROUP, b"ungroup"),
        (CAPABILITY_INSTANTIATE, b"instantiate"),
        (CAPABILITY_COMPOSITION, b"composition"),
    ):
        if declared_root not in snapshot.cells:
            cells.append(
                Cell(declared_root, NULL_CELL_ID, NULL_CELL_ID, declared_label)
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
    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        CLEAN_SCOPE_INTERACTIONS_LABEL,
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    root_id = new_id()
    root_cells = typed_relation_cells(
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
    written = len(cells) + len(label_cells) + len(digest_cells) + len(root_cells)
    if cell_limit is not None and written > cell_limit:
        # This rewrites every binding for every scope, so its cost grows
        # with the whole catalogue rather than with what changed. Four of
        # these turned a 654 MB graph into 2.3 GB and a two-minute start
        # into thirteen. Nothing else in the system can write a million
        # cells on one call, and nothing was watching this one.
        raise InvalidCell(
            "revising the interaction set would write %d cells, over the "
            "%d limit; the set rewrites every binding for every scope, so "
            "pass cell_limit to accept the cost deliberately"
            % (written, cell_limit)
        )
    receipt = replace_interface_subsystem(
        authority,
        caller=caller,
        command_id=command_id,
        intent="revise-clean-scope-interactions",
        held_root=held.root_id,
        replacement_root=root_id,
        replacement_cells=(
            *cells, *label_cells, *digest_cells, *root_cells
        ),
        source_digest=source_digest,
    )
    current = authority.store.snapshot()
    revised = _read_scope_interactions(authority, current, root_id)
    if revised is None:
        raise InvalidCell("revised clean scope interaction set is invalid")
    return CleanScopeInteractions(
        revised.graph_id,
        revised.root_id,
        revised.protocol,
        revised.event_root,
        revised.source_digest,
        revised.revision,
        False,
        getattr(receipt, "root_id", None),
        revised.bindings,
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
    request_digest = digest({
        "intent": "install-clean-scope-interactions",
        "scope-root": scope_root,
        "source-digest": source_digest,
        "version": CLEAN_SCOPE_INTERACTIONS_VERSION,
    })
    snapshot = authority.store.snapshot()
    interface_root = composition_root(authority, "Interface", caller=caller)
    authenticated, policy_proof = validate_command_participants(
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
    existing = find_receipt(
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
    event_root = _derived_id(
        authority.manifest.graph_id, "event", _EVENT_LABEL
    )
    event_cell = Cell(event_root, NULL_CELL_ID, NULL_CELL_ID, _EVENT_LABEL.encode("utf-8"))
    interaction_batch = SourceCellBatch()
    bindings: dict[str, dict[str, ScopeOpenBinding]] = {}
    for current_scope, control_root, target_root, capability_root in binding_specs:
        interaction_root = _derived_id(
            authority.manifest.graph_id, "interaction",
            current_scope, control_root, target_root, capability_root,
        )
        build_interaction(
            authority.store,
            protocol,
            interaction_id=interaction_root,
            control_root=control_root,
            event_root=event_root,
            target_root=browser.root_id,
            input_roots=(current_scope, target_root),
            action_root=capability_root,
            subject_root=caller.actor_root,
            policy_root=authority.manifest.policy_root,
            authorization_action_root=authority.role("composition"),
            authorization_object_root=target_root,
            # The proof asks whether the subject may compose the target
            # within a scope that holds it. A child is held by the scope it
            # is opened from; the door -- the way back, opened from a scope
            # below it -- is held by itself.
            authorization_scope_roots=(
                authority.manifest.application_root,
                target_root if target_root == scope_root else current_scope,
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
    for declared_root, declared_label in (
        (CAPABILITY_SCOPE, b"scope"),
        (CAPABILITY_EXECUTE, b"execute"),
        # A scope-open binding names a node that already exists, so its
        # control needs no cell of its own. The Run control is named by the
        # catalogue rather than by the canvas, so the graph has to carry
        # its identity or every interaction pointing at it dangles.
        (CONTROL_RUN, b"run"),
        (CONTROL_GROUP, b"group"),
        (CONTROL_UNGROUP, b"ungroup"),
        (CAPABILITY_INSTANTIATE, b"instantiate"),
        (CAPABILITY_COMPOSITION, b"composition"),
    ):
        if declared_root not in snapshot.cells:
            cells.append(
                Cell(declared_root, NULL_CELL_ID, NULL_CELL_ID, declared_label)
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
    label_root, label_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        CLEAN_SCOPE_INTERACTIONS_LABEL,
        shape_root=authority.shape("value"),
    )
    digest_root, digest_cells = build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        source_digest,
        shape_root=authority.shape("value"),
    )
    root_id = new_id()
    root_cells = typed_relation_cells(
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
    interface_patch = append_relation_member(
        snapshot,
        interface_root,
        authority.role("composition"),
        root_id,
    )
    result = commit_with_receipt(
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


def derive_clean_scope_interactions(
    authority: UnifiedAuthority,
    browser: CleanBrowserAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
) -> tuple[CleanScopeInteractions, tuple[Cell, ...]]:
    """The exact set revise would persist, computed instead of written.

    Every interaction the installed table holds is already built from
    derived identities -- the same (scope, control, target, capability)
    always names the same cells. That makes the whole table a projection
    of graph facts it merely repeats: the scope tree and the published
    catalogue. Four persisted copies of that projection are 78%% of the
    live graph and the reason it boots in minutes.

    This computes the same cells and the same bindings without committing
    anything. The equivalence court holds it cell-for-cell against the
    installed table; once the read path consumes this, the table is
    redundant state a compaction can drop.
    """
    binding_specs = _binding_specs(authority, scope_root, caller)
    source_digest = _source_digest(binding_specs)
    snapshot = authority.store.snapshot()
    protocol_cells, protocol = _compile_protocol_source()
    event_root = _derived_id(
        authority.manifest.graph_id, "event", _EVENT_LABEL
    )
    event_cell = Cell(
        event_root, NULL_CELL_ID, NULL_CELL_ID, _EVENT_LABEL.encode("utf-8")
    )
    interaction_batch = SourceCellBatch()
    bindings: dict[str, dict[str, ScopeOpenBinding]] = {}
    for current_scope, control_root, target_root, capability_root in binding_specs:
        interaction_root = _derived_id(
            authority.manifest.graph_id, "interaction",
            current_scope, control_root, target_root, capability_root,
        )
        build_interaction(
            authority.store,
            protocol,
            interaction_id=interaction_root,
            control_root=control_root,
            event_root=event_root,
            target_root=browser.root_id,
            input_roots=(current_scope, target_root),
            action_root=capability_root,
            subject_root=caller.actor_root,
            policy_root=authority.manifest.policy_root,
            authorization_action_root=authority.role("composition"),
            authorization_object_root=target_root,
            # The proof asks whether the subject may compose the target
            # within a scope that holds it. A child is held by the scope it
            # is opened from; the door -- the way back, opened from a scope
            # below it -- is held by itself.
            authorization_scope_roots=(
                authority.manifest.application_root,
                target_root if target_root == scope_root else current_scope,
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
    derived_root = _derived_id(
        authority.manifest.graph_id, "derived-scope-interactions", source_digest
    )
    declared_cells: list[Cell] = []
    for declared_root, declared_label in (
        (CAPABILITY_SCOPE, b"scope"),
        (CAPABILITY_EXECUTE, b"execute"),
        # Interactions name these controls and capabilities directly. A
        # graph whose installed-table era persisted them resolves against
        # the raw store; a graph that never installed them -- the live one
        # after the table retired -- has no cell behind the name, so every
        # interaction pointing at one dangles unless the derived set
        # carries the identity. Unlike revise and install, nothing here is
        # committed, so sourcing is unconditional: when the graph already
        # holds the cell the derived copy shadows it with identical
        # content, and when it does not the identity still resolves.
        (CONTROL_RUN, b"run"),
        (CONTROL_GROUP, b"group"),
        (CONTROL_UNGROUP, b"ungroup"),
        (CAPABILITY_INSTANTIATE, b"instantiate"),
        (CAPABILITY_COMPOSITION, b"composition"),
    ):
        declared_cells.append(
            Cell(declared_root, NULL_CELL_ID, NULL_CELL_ID, declared_label)
        )
    cells = (
        *protocol_cells, event_cell, *interaction_batch.cells, *declared_cells
    )
    return (
        CleanScopeInteractions(
            authority.manifest.graph_id,
            derived_root,
            protocol,
            event_root,
            source_digest,
            snapshot.revision,
            False,
            None,
            MappingProxyType({
                held_scope: MappingProxyType(controls)
                for held_scope, controls in bindings.items()
            }),
        ),
        cells,
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
    read_snapshot: Snapshot | None = None,
) -> CommandResult:
    """Execute one preinstalled scope-open interaction through a signed receipt.

    `read_snapshot` is the snapshot the interaction is READ from. When the
    bindings are derived rather than persisted, the interaction cells live
    only in an overlay the server holds; the commit itself still runs
    against the graph's own snapshot and writes only its receipt.
    """
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
    replayed = find_receipt(
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
    reading = snapshot if read_snapshot is None else read_snapshot
    lease = projection_broker.resolve(
        projection_handle,
        reading,
        expected_revision=expected_revision,
        control_root=control_root,
        interaction_root=interaction_root,
    )
    interaction = read_interaction(reading, interactions.protocol, interaction_root)
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
    request_digest = digest({
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
    authenticated, policy_proof = validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="submit-clean-scope-interaction",
        request_digest=request_digest,
        object_root=target_scope,
        # The policy asks whether the subject may act on the target within
        # a scope that holds it. Opening a child is proven within the scope
        # it is opened from; opening the door from a scope below it -- the
        # way back -- is proven within the door itself, which holds both.
        scope_root=(
            target_scope
            if target_scope == interactions.root_scope
            else current_scope
        ),
        budget=COMMAND_BUDGET,
    )
    existing = find_receipt(
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
    return commit_with_receipt(
        authority,
        snapshot,
        resource_create=(),
        resource_replace=(),
        authenticated=authenticated,
        result_root=target_scope,
        policy_proof=policy_proof,
    )


__all__ = [
    "WRITTEN_CELL_LIMIT",
    "derive_clean_scope_interactions",
    "unbound_published_definitions",
    "CLEAN_SCOPE_INTERACTIONS_LABEL",
    "CLEAN_SCOPE_INTERACTIONS_VERSION",
    "CleanScopeInteractions",
    "ScopeOpenBinding",
    "install_clean_scope_interactions",
    "open_clean_scope_interactions",
    "submit_clean_scope_interaction",
]
