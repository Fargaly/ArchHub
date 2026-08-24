"""Generic visual scope projection over the one Unified Cell authority."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from weakref import WeakKeyDictionary
from typing import Mapping

from .cell_attention import active_focus, open_attention_protocol
from .cell_read_memo import read_set_unchanged
from .cell_protocols import read_relation
from .unified_authority import (
    read_composition_placements,
    property_identities,
    CallerCommandCapability,
    DefinitionProjection,
    UnifiedAuthority,
    composition_root,
    _project_instance,
    read_definition,
    read_scope_level,
    read_view_session_state,
    relation_members,
)
from .universal_cell import InvalidCell


@dataclass(frozen=True, slots=True)
class LensProperty:
    name: str
    value: object
    editor: object
    constraints: Mapping[str, object]
    # Identity of the cells this row was read from. Without them a rendered
    # value cannot be traced back to the graph that produced it, so the
    # visual layer can show a value but not prove it.
    property_root: str | None = None
    owner_root: str | None = None
    name_root: str | None = None
    value_root: str | None = None
    # Continuity: where this row sits in history and what it replaced. Carried
    # on every row, not only revised ones, so a reader never has to guess
    # whether absence means "unchanged" or "not reported".
    history_root: str | None = None
    predecessor_root: str | None = None


@dataclass(frozen=True, slots=True)
class LensPort:
    relation_root: str
    participant_role: str
    connection: str | None
    other_roots: tuple[str, ...]
    # A socket is declared by an interface in the definition and realised by
    # incidences in the relation. Both are named here so a drawn socket can
    # be traced to the cells that authorise it rather than described by
    # whatever the renderer guessed.
    interface_root: str | None = None
    direction: object = None
    multiple: object = None
    permission: object = None
    editable: bool = False
    source_incidence: str | None = None
    target_incidence: str | None = None
    authority_roots: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LensNode:
    root_id: str
    structural_role: str
    label: str
    definition_root: str | None
    definition_name: str | None
    lifecycle: str | None
    state_parameter: str | None
    state: object
    panels: tuple[str, ...]
    properties: tuple[LensProperty, ...]
    ports: tuple[LensPort, ...]
    openable: bool
    # Appearance is declared in the definition's presentation contract. It is
    # carried with the root of each declaring cell so a rendered node can name
    # where every visible attribute came from instead of inventing it.
    presentation_root: str | None = None
    icon: object = None
    color_token: object = None
    resolved_color: object = None
    position: object = None
    icon_root: str | None = None
    color_token_root: str | None = None
    position_root: str | None = None
    # The host operation this node runs, when its definition declares one.
    # A canvas holds nodes that describe something and nodes that DO
    # something, and only the node itself can say which it is.
    operation: str | None = None


@dataclass(frozen=True, slots=True)
class LensRelation:
    root_id: str
    participants: tuple[tuple[str, str], ...]
    properties: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class LensCatalogueItem:
    root_id: str
    name: str
    version: str
    lifecycle: str
    parameters: Mapping[str, object]
    interfaces: Mapping[str, object]
    presentation: Mapping[str, object]
    rules: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class UnifiedScopeLens:
    graph_id: str
    revision: int
    scope_root: str
    scope_label: str | None
    selected_root: str | None
    selected_roots: tuple[str, ...]
    nodes: tuple[LensNode, ...]
    relations: tuple[LensRelation, ...]
    catalogue: tuple[LensCatalogueItem, ...]
    # The view's graph-held working state. A view that never moved sits at
    # the recorded defaults; the lens never invents a viewport of its own.
    viewport: Mapping[str, object] = MappingProxyType({})
    design_tokens: Mapping[str, object] = MappingProxyType({})


def _text_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is not list or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise InvalidCell("%s presentation is invalid" % label)
    return tuple(item.strip() for item in value)


def _definition_item(definition: DefinitionProjection) -> LensCatalogueItem:
    return LensCatalogueItem(
        definition.root_id,
        definition.name,
        definition.version,
        definition.lifecycle,
        MappingProxyType(dict(definition.contracts["parameters"])),
        MappingProxyType(dict(definition.contracts["interfaces"])),
        MappingProxyType(dict(definition.contracts["presentation"])),
        MappingProxyType(dict(definition.contracts.get("rules") or {})),
    )


def _interface_binding(
    authority,
    snapshot,
    level,
    owner_root: str,
    connection: object,
    caller,
    relation_root: str,
    participant_role: str,
) -> dict[str, object]:
    """Name the interface a socket is declared by, and what it declares.

    A socket is drawn because a definition declares an interface for it. If
    that declaration cannot be found the socket carries no interface facts
    rather than invented ones, so a renderer cannot present a guess as a
    contract.
    """
    # A socket exists because a relation puts this node in it. That relation
    # is the authority for the socket even when no interface is declared, so
    # it is named rather than leaving the socket unattributable. Direction,
    # cardinality and permission stay absent until a definition declares
    # them; a default here would assert a contract the graph never made.
    # With no declared interface the graph still states which side of the
    # relation this node occupies. That role is the direction it can honestly
    # report; cardinality and permission remain unknown rather than assumed.
    fallback = {
        "interface_root": relation_root,
        "direction": participant_role,
        "multiple": None,
        "permission": None,
        "authority_roots": (relation_root,),
    }
    instance = level.instances.get(owner_root)
    if instance is None or type(connection) is not str:
        return fallback
    definition_root = instance.get("definition")
    if type(definition_root) is not str:
        return fallback
    definition = read_definition(authority, definition_root, caller=caller)
    interfaces = definition.contracts.get("interfaces") or {}
    declared = interfaces.get(connection)
    if not isinstance(declared, Mapping):
        return fallback
    contract_root = definition.contract_roots.get("interfaces")
    identities = (
        property_identities(authority, snapshot, contract_root)
        if contract_root else {}
    )
    interface_root = (identities.get(connection) or {}).get(
        "property_root"
    ) or contract_root
    authority_roots = tuple(
        root for root in (interface_root, contract_root, definition.revision_root)
        if root and root in snapshot.cells
    )
    return {
        "interface_root": interface_root,
        "direction": declared.get("direction") or participant_role,
        "multiple": declared.get("multiple"),
        "permission": declared.get("permission"),
        "authority_roots": authority_roots,
    }


# The published catalogue is the same 97 definitions on every click;
# reading them per projection cost 0.640s of a 0.75s lens. Entries are
# dropped by what a commit TOUCHES, so a publish or a revision is seen
# immediately while a focus click keeps the read.
_CATALOGUE_MEMOS: "WeakKeyDictionary" = WeakKeyDictionary()


def _catalogue(
    authority: UnifiedAuthority,
    caller: CallerCommandCapability,
) -> tuple[LensCatalogueItem, ...]:
    # Revision-keyed: enumerating what this read touches was tried twice
    # and a publish slipped past the enumeration both times, so the
    # library showed nothing new. The read is made cheap instead of
    # clever -- one statement warms the whole catalogue region, which is
    # where 0.758s of every click went.
    revision = authority.store.revision
    entry = _CATALOGUE_MEMOS.get(authority.store)
    if entry is None or entry[0] != revision:
        entry = (revision, {})
        _CATALOGUE_MEMOS[authority.store] = entry
    held = entry[1].get(caller.actor_root)
    if held is not None:
        return held
    items, _walked = _catalogue_uncached(authority, caller)
    entry[1][caller.actor_root] = items
    return items


# WHICH definitions the catalogue holds is one cheap relation read; WHAT
# each of them says is 97 definition projections, and that is where 24.8s
# of a 51.4s scope entry went. The membership is read every time -- a
# publish must be seen at once -- and each definition is kept until a
# commit writes a cell that IS one it read, or POINTS AT one (a new
# revision cell for a definition names the definition root, and that is
# how two earlier id-only enumerations missed a change).
LAST_LENS_PHASES: dict = {}

_DEFINITION_MEMOS: "WeakKeyDictionary" = WeakKeyDictionary()


def _catalogue_uncached(authority, caller):
    """The catalogue, and every cell reading it walked."""
    from .cell_protocols import read_relation

    snapshot = authority.store.snapshot()
    store = authority.store
    members = relation_members(snapshot, authority.manifest.catalogue_root)
    # Warming the whole catalogue region is one statement instead of a
    # round trip per cell -- worth 24.8s when the definitions must be
    # read, and exactly 24.8s of waste when every one of them is already
    # known. It is paid on the first definition that actually needs it.
    warmed = False

    def warm_once():
        nonlocal warmed
        if warmed:
            return
        warmed = True
        warm = getattr(snapshot.cells, "prefetch_region", None)
        if warm is not None:
            warm(authority.manifest.catalogue_root)
    walked = {member.incidence_id for member in members}
    roots = sorted(
        member.participant_id for member in members
        if member.role_id == authority.role("definition")
    )
    memos = _DEFINITION_MEMOS.get(store)
    if memos is None:
        memos = {}
        _DEFINITION_MEMOS[store] = memos
    items = []
    for root in roots:
        key = (root, caller.actor_root)
        held = memos.get(key)
        if held is not None and read_set_unchanged(store, held[0], held[2]):
            memos[key] = (store.revision, held[1], held[2])
            items.append(held[1])
            walked |= held[2]
            continue
        warm_once()
        projection = read_definition(authority, root, caller=caller)
        item = _definition_item(projection)
        seen = {root, projection.revision_root}
        for member in read_relation(snapshot, root, budget=10_000):
            seen.add(member.incidence_id)
            seen.add(member.participant_id)
        memos[key] = (store.revision, item, frozenset(seen))
        items.append(item)
        walked |= seen
    return tuple(sorted(
        items, key=lambda item: (item.name.casefold(), item.root_id)
    )), frozenset(walked)


def _properties(
    definition: DefinitionProjection,
    values: Mapping[str, object],
    identities: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[LensProperty, ...]:
    projected: list[LensProperty] = []
    for name, raw in sorted(definition.contracts["parameters"].items()):
        if not isinstance(raw, Mapping):
            raise InvalidCell("definition parameter presentation is invalid")
        metadata = dict(raw)
        editor = metadata.pop("editor", None)
        identity = (identities or {}).get(name) or {}
        projected.append(LensProperty(
            name,
            values.get(name),
            editor,
            MappingProxyType(dict(sorted(metadata.items()))),
            identity.get("property_root"),
            identity.get("owner"),
            identity.get("name_root"),
            identity.get("value_root"),
            identity.get("history_root"),
            identity.get("predecessor_root"),
        ))
    return tuple(projected)


# Phase costs of the last projection, for the owner to log. A lens that
# is slow is slow SOMEWHERE; without this the number is a mystery.


def project_unified_scope(
    authority: UnifiedAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
    view_root: str | None = None,
    at_revision: int | None = None,
    resolve_relation_ends: bool = True,
) -> UnifiedScopeLens:
    """Project one bounded scope without adding product-name dispatch."""
    if at_revision is None:
        snapshot = authority.store.snapshot()
    else:
        if type(at_revision) is not int or at_revision < 0:
            raise InvalidCell("scope revision is invalid")
        # Asking for the head revision IS the head snapshot. Routing it
        # through at() walked the delta chain and re-verified the head on
        # every click -- 0.75s of a canvas the founder is owed in 0.150s
        # (SPEC 11.14) -- to arrive at the snapshot already in hand.
        current = authority.store.snapshot()
        snapshot = (
            current if at_revision == current.revision
            else authority.store.at(at_revision)
        )
    import time as _lens_time
    _p0 = _lens_time.perf_counter()
    level = read_scope_level(
        authority,
        scope_root,
        scope_root=scope_root,
        caller=caller,
        at_revision=snapshot.revision,
    )
    selected_root: str | None = None
    selected_roots: tuple[str, ...] = ()
    if view_root is not None:
        if type(view_root) is not str or not view_root:
            raise InvalidCell("view session root is invalid")
        if view_root != caller.session_root:
            raise InvalidCell("view session root does not belong to the caller")
        protocol = open_attention_protocol(snapshot)
        focus = active_focus(snapshot, protocol, session_root=view_root)
        # A session carries one active focus, and it belongs to the scope it
        # was taken in. Refusing to project a different scope because of it
        # made one selection permanent: after a single click the canvas
        # could never open anywhere else, across restarts, because the
        # session is reused. A focus from elsewhere is simply not this
        # scope's focus, and this scope opens with nothing selected.
        #
        # A focus that DOES claim this scope must still name roots this
        # scope shows; that refusal stays, because a selection pointing at
        # roots outside what is drawn is a claim about this scope that the
        # scope contradicts.
        if focus is not None and focus.scope_root == scope_root:
            visible = frozenset(level.composition_roots)
            if not set(focus.selected_roots).issubset(visible):
                raise InvalidCell("active focus selection is outside the projected scope")
            selected_root = focus.primary_root
            selected_roots = focus.selected_roots
    _p1 = _lens_time.perf_counter()
    level_roots = frozenset(level.composition_roots)
    owner = _level_owner_index(authority, snapshot, level.composition_roots)
    projected_relations = []
    for relation in level.relations.values():
        # A canvas rolls relation ends up to the cards it draws and
        # drops what cannot land on one -- a line to nowhere is not a
        # line. A textual lens (the workshop) reads the graph's own
        # participants; resolution is a drawing rule, so the entry
        # point that draws is the one that asks for it.
        if resolve_relation_ends:
            participants = _resolved_participants(
                relation.participants, owner, level_roots
            )
            if participants is None:
                continue
        else:
            participants = tuple(relation.participants)
        projected_relations.append(
            LensRelation(
                relation.root_id,
                participants,
                MappingProxyType(dict(relation.properties)),
            )
        )
    relations = tuple(projected_relations)
    role_names = {authority.role(name): name for name in authority.roles}
    ports: dict[str, list[LensPort]] = {
        root: [] for root in level.composition_roots
    }
    for relation in relations:
        connection = relation.properties.get("connection")
        if connection is not None and type(connection) is not str:
            raise InvalidCell("relation connection presentation is invalid")
        participant_roots = tuple(root for _, root in relation.participants)
        members = read_relation(snapshot, relation.root_id, budget=1024)
        incidence_by_role: dict[str, str] = {}
        for member in members:
            role_name = role_names.get(member.role_id)
            if role_name and role_name not in incidence_by_role:
                incidence_by_role[role_name] = member.incidence_id
        source_incidence = incidence_by_role.get("source")
        target_incidence = incidence_by_role.get("target")
        if source_incidence is None or target_incidence is None:
            ordered = [member.incidence_id for member in members]
            if len(ordered) >= 2:
                source_incidence = source_incidence or ordered[0]
                target_incidence = target_incidence or next(
                    item for item in ordered if item != source_incidence
                )
        for role, root in relation.participants:
            if root not in ports:
                continue
            interface = _interface_binding(
                authority, snapshot, level, root, connection, caller,
                relation.root_id, role,
            )
            ports[root].append(LensPort(
                relation.root_id,
                role,
                connection,
                tuple(item for item in participant_roots if item != root),
                interface.get("interface_root"),
                interface.get("direction"),
                interface.get("multiple"),
                interface.get("permission"),
                bool(interface.get("interface_root")),
                source_incidence,
                target_incidence,
                interface.get("authority_roots", ()),
            ))

    _p2 = _lens_time.perf_counter()
    nodes: list[LensNode] = []
    # Where a composition sits is a graph fact the scope holds, not a
    # number a projector picks. A composition that has never been placed
    # reads as unplaced, so the canvas can say so rather than scatter it.
    placements = read_composition_placements(
        authority,
        authority.store.snapshot(),
        composition_root(authority, "Interface", caller=caller),
        wanted=level.composition_roots,
    )
    for root in level.composition_roots:
        instance = level.instances.get(root)
        if instance is None:
            nodes.append(LensNode(
                root,
                "composition",
                level.composition_labels[root] or "Untitled composition",
                None,
                None,
                None,
                None,
                None,
                (),
                (),
                tuple(sorted(ports[root], key=lambda item: item.relation_root)),
                _opens_onto_something(authority, snapshot, root),
                None,
                None,
                None,
                None,
                placements.get(root),
            ))
            continue
        definition_root = instance.get("definition")
        values = instance.get("values")
        if type(definition_root) is not str or not isinstance(values, Mapping):
            raise InvalidCell("instance lens projection is invalid")
        definition = read_definition(authority, definition_root, caller=caller)
        presentation = definition.contracts["presentation"]
        presentation_root = definition.contract_roots.get("presentation")
        presentation_identities = (
            property_identities(
                authority, authority.store.snapshot(), presentation_root
            )
            if presentation_root else {}
        )
        rules = definition.contracts["rules"]
        label = presentation.get("label", definition.name)
        if type(label) is not str or not label.strip():
            raise InvalidCell("definition label presentation is invalid")
        state_parameter = rules.get("state_parameter")
        if state_parameter is not None and (
            type(state_parameter) is not str or not state_parameter.strip()
        ):
            raise InvalidCell("definition state presentation is invalid")
        nodes.append(LensNode(
            root,
            "instance",
            label.strip(),
            definition.root_id,
            definition.name,
            definition.lifecycle,
            state_parameter,
            None if state_parameter is None else values.get(state_parameter),
            _text_tuple(presentation.get("panels"), "definition panel"),
            _properties(
                definition,
                values,
                property_identities(
                    authority, authority.store.snapshot(), root
                ),
            ),
            tuple(sorted(ports[root], key=lambda item: item.relation_root)),
            _opens_onto_something(authority, snapshot, root),
            presentation_root,
            presentation.get("icon"),
            presentation.get("token"),
            presentation.get("color"),
            # A node's own placement wins over its definition's. Two
            # instances of one definition are two nodes on a canvas and
            # must be able to sit apart; a definition-level position
            # would stack every instance of it in one spot.
            placements.get(root) or presentation.get("position"),
            presentation_identities.get("icon", {}).get("property_root"),
            presentation_identities.get("token", {}).get("property_root"),
            presentation_identities.get("position", {}).get("property_root"),
            (
                rules.get("operation")
                if isinstance(rules.get("operation"), str)
                else None
            ),
        ))
    _p3 = _lens_time.perf_counter()
    viewport, design_tokens = (
        read_view_session_state(
            authority,
            view_root,
            caller=caller,
            at_revision=snapshot.revision,
        )
        if view_root is not None
        else read_view_session_state(
            authority,
            caller.session_root,
            caller=caller,
            at_revision=snapshot.revision,
        )
    )
    return UnifiedScopeLens(
        authority.manifest.graph_id,
        level.revision,
        scope_root,
        _scope_title(authority, snapshot, scope_root, level.label, caller),
        selected_root,
        selected_roots,
        tuple(nodes),
        relations,
        _catalogue_timed(authority, caller, _p0, _p1, _p2, _p3),
        MappingProxyType(viewport),
        MappingProxyType(design_tokens),
    )


def _scope_title(authority, snapshot, scope_root, label, caller):
    """What the scope the founder stands in is called.

    A composition carries its own label. An instance -- every Grand Map
    domain the import placed -- does not: its name is the label its
    definition declares, or the instance's own title property when the
    definition names all its instances alike. That is exactly the rule a
    card on the canvas follows, so the heading over a scope must read the
    same as the card that was double-clicked to enter it. Falling back to
    "Scope" drew a nameless heading over a domain whose card was named.
    """
    if label is not None:
        return label
    try:
        instance = _project_instance(authority, snapshot, scope_root)
    except InvalidCell:
        return None
    definition_root = instance.get("definition")
    values = instance.get("values")
    if type(definition_root) is not str or not isinstance(values, Mapping):
        return None
    definition = read_definition(authority, definition_root, caller=caller)
    presentation = definition.contracts["presentation"]
    declared = presentation.get("label", definition.name)
    if type(declared) is not str or not declared.strip():
        return None
    declared = declared.strip()
    if declared != definition.name:
        return declared
    title = values.get("title")
    if type(title) is str and title.strip():
        return title.strip()
    return declared


def project_workshop_lens(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> UnifiedScopeLens:
    return project_unified_scope(
        authority,
        composition_root(authority, "Workshop", caller=caller),
        caller=caller,
        resolve_relation_ends=False,
    )


def _opens_onto_something(authority, snapshot, root: str) -> bool:
    """Whether entering this node would show anything.

    Every node claimed to be openable, so every card offered to expand and
    every expansion landed on an empty canvas. Openable is not a property
    of being a node; it is a fact about whether this node holds members the
    level below would draw, and it is read from the graph like any other
    fact rather than asserted here.
    """
    try:
        for member in read_relation(snapshot, root, budget=4096):
            if member.role_id == authority.role("composition"):
                return True
    except InvalidCell:
        return False
    return False


def _level_owner_index(
    authority,
    snapshot,
    composition_roots,
    budget: int = 200_000,
) -> dict[str, str]:
    """Which card on this level contains each root beneath it.

    A relation between two requirements inside two domains is a relation
    between those domains as far as this level can see. Without this the
    level drew fifteen domain cards and four hundred and eighty five lines
    whose endpoints were all one level further down, so not one line had
    anything to connect and the domains looked unrelated.
    """
    # Descend containment only. Following every participant instead walks
    # out through the relations themselves into shared definitions and
    # values, and the first card reached claims the whole graph -- which
    # drew every line on this level converging on one card.
    composition = authority.role("composition")
    owner: dict[str, str] = {}
    remaining = budget
    for card in composition_roots:
        pending = [card]
        seen = {card}
        while pending and remaining > 0:
            current = pending.pop()
            owner.setdefault(current, card)
            try:
                members = read_relation(snapshot, current, budget=4096)
            except InvalidCell:
                continue
            for member in members:
                remaining -= 1
                if member.role_id != composition:
                    continue
                child = member.participant_id
                if child in seen:
                    continue
                seen.add(child)
                pending.append(child)
    return owner


def _resolved_participants(participants, owner, level_roots):
    """Move a relation's ends up to the cards this level actually draws.

    A participant already on the level keeps its own identity. One below
    the level is answered for by the card containing it. One outside the
    region entirely cannot be drawn here and drops the relation, because a
    line to nowhere is not a line.
    """
    resolved = []
    for role, root in participants:
        if root in level_roots:
            resolved.append((role, root))
            continue
        holder = owner.get(root)
        if holder is None:
            return None
        resolved.append((role, holder))
    ends = {root for _, root in resolved}
    if len(ends) < 2:
        return None
    return tuple(resolved)


def scope_lens_payload(lens: UnifiedScopeLens) -> dict[str, object]:
    """Convert the immutable projection to transport-safe plain data."""
    def plain(value: object) -> object:
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: plain(getattr(value, field.name))
                for field in fields(value)
            }
        if isinstance(value, Mapping):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [plain(item) for item in value]
        if value is None or type(value) in {bool, int, float, str}:
            return value
        raise InvalidCell("scope lens contains non-transport data")

    payload = plain(lens)
    if not isinstance(payload, dict):
        raise InvalidCell("scope lens payload is invalid")
    return payload


__all__ = [
    "LensCatalogueItem",
    "LensNode",
    "LensPort",
    "LensProperty",
    "LensRelation",
    "UnifiedScopeLens",
    "project_unified_scope",
    "project_workshop_lens",
    "scope_lens_payload",
]


def _catalogue_timed(authority, caller, p0, p1, p2, p3):
    """Read the catalogue, and publish what every lens phase cost."""
    import time as _lens_time
    start = _lens_time.perf_counter()
    catalogue = _catalogue(authority, caller)
    done = _lens_time.perf_counter()
    LAST_LENS_PHASES.clear()
    LAST_LENS_PHASES.update({
        "level": p1 - p0,
        "relations": p2 - p1,
        "nodes": p3 - p2,
        "view": start - p3,
        "catalogue": done - start,
    })
    return catalogue
