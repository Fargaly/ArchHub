"""Graph-defined compositions above the universal-cell physical kernel.

Nothing in this module creates a new persisted record type. A relation is one
reusable binary-cell protocol: a chain cell points to an incidence cell and the
next chain cell; each incidence points to a role cell and a participant cell.
The role identities are supplied by the graph, never selected by the kernel.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Iterable
import hashlib
import uuid

from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
    Snapshot,
)


@dataclass(frozen=True, slots=True)
class RelationBuild:
    root_id: str
    incidence_ids: tuple[str, ...]
    chain_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelationCells:
    build: RelationBuild
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class RelationPatch:
    incidence_id: str
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class RelationRemovalPatch:
    removed: tuple[RelationMember, ...]
    replace: tuple[Cell, ...]


_RELATION_PROJECTION_CACHE: ContextVar[
    dict[tuple[int, int, str], "RelationProjectionReuse"] | None
] = ContextVar("relation_projection_cache", default=None)
_RELATION_PROJECTION_BATCH_SEALS: ContextVar[
    dict[int, tuple[tuple["RelationProjectionReuse", ...], str]] | None
] = ContextVar("relation_projection_batch_seals", default=None)


@contextmanager
def relation_projection_scope():
    """Reuse relation walks only inside one interpreter request."""
    existing = _RELATION_PROJECTION_CACHE.get()
    if existing is not None:
        if _RELATION_PROJECTION_BATCH_SEALS.get() is None:
            raise InvalidCell("relation projection request scope is incomplete")
        yield
        return
    cache_token = _RELATION_PROJECTION_CACHE.set({})
    seal_token = _RELATION_PROJECTION_BATCH_SEALS.set({})
    try:
        yield
    finally:
        _RELATION_PROJECTION_BATCH_SEALS.reset(seal_token)
        _RELATION_PROJECTION_CACHE.reset(cache_token)


def with_relation_projection_scope(function):
    """Run an interpreter entrypoint with a request-local relation cache."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with relation_projection_scope():
            return function(*args, **kwargs)
    return wrapped


@dataclass(frozen=True, slots=True)
class RelationAppendPatch:
    incidence_ids: tuple[str, ...]
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class RelationMember:
    incidence_id: str
    role_id: str
    participant_id: str


@dataclass(frozen=True, slots=True)
class RelationProjectionReuse:
    """One exact relation walk reusable only across one accepted commit."""

    source_revision: int
    relation_root: str
    members: tuple[RelationMember, ...]
    steps: int
    source_cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class PropertyProjection:
    relation_root: str
    owner_root: str
    value_root: str
    label_root: str


class CellBatch:
    """Compose many ordinary Cells and publish them in one Store revision."""

    def __init__(self, store: CellStore) -> None:
        self.store = store
        # Snapshot mappings are immutable. Retaining the mapping preserves the
        # same membership check without copying the entire graph for every
        # small interaction batch.
        self._existing = store.snapshot().cells
        self._cells: dict[str, Cell] = {}
        self._committed = False

    def add(self, cell: Cell) -> str:
        if self._committed:
            raise InvalidCell("a committed batch cannot be reused")
        if cell.id in self._cells or cell.id in self._existing:
            raise InvalidCell("batch cell identity already exists: %r" % cell.id)
        self._cells[cell.id] = cell
        return cell.id

    def relation(
        self,
        members: Iterable[tuple[str, str]],
        *,
        relation_id: str | None = None,
    ) -> RelationBuild:
        composed = compose_relation_cells(members, relation_id=relation_id)
        for cell in composed.cells:
            self.add(cell)
        return composed.build

    def commit(self) -> int:
        if self._committed:
            raise InvalidCell("a committed batch cannot be reused")
        self._committed = True
        return self.store.commit(
            self.store.revision,
            create=tuple(self._cells.values()),
        )


def _new_id(prefix: str) -> str:
    return "%s:%s" % (prefix, uuid.uuid4())


def compose_relation_cells(
    members: Iterable[tuple[str, str]],
    *,
    relation_id: str | None = None,
) -> RelationCells:
    """Compose a relation without committing it, for larger atomic rewrites."""
    pairs = tuple(members)
    root_id = relation_id or _new_id("relation")
    if not pairs:
        build = RelationBuild(root_id, (), (root_id,))
        return RelationCells(
            build, (Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, b""),)
        )
    incidence_ids = tuple(
        "%s:incidence:%s" % (root_id, index)
        for index in range(len(pairs))
    )
    chain_ids = (root_id,) + tuple(
        "%s:chain:%s" % (root_id, index)
        for index in range(1, len(pairs))
    )
    cells: list[Cell] = []
    for index, ((role_id, participant_id), incidence_id) in enumerate(
        zip(pairs, incidence_ids)
    ):
        cells.append(Cell(incidence_id, role_id, participant_id, b""))
        next_chain = (
            chain_ids[index + 1]
            if index + 1 < len(chain_ids)
            else NULL_CELL_ID
        )
        cells.append(Cell(chain_ids[index], incidence_id, next_chain, b""))
    return RelationCells(
        RelationBuild(root_id, incidence_ids, chain_ids), tuple(cells)
    )


def build_relation(
    store: CellStore,
    members: Iterable[tuple[str, str]],
    *,
    relation_id: str | None = None,
) -> RelationBuild:
    """Materialize an arbitrary-arity relation protocol in one transaction."""
    batch = CellBatch(store)
    built = batch.relation(members, relation_id=relation_id)
    batch.commit()
    return built


def read_relation(
    snapshot: Snapshot,
    relation_root: str,
    *,
    budget: int = 10_000,
) -> tuple[RelationMember, ...]:
    """Project one root through the reusable relation-chain protocol."""
    if budget < 1:
        raise MatchBudgetExceeded("relation projection budget must be positive")
    cache = _RELATION_PROJECTION_CACHE.get()
    cache_key = (snapshot.revision, id(snapshot.cells), relation_root)
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        if cached.steps > budget:
            raise MatchBudgetExceeded(
                "relation projection exceeded %s chain cells" % budget
            )
        return cached.members
    if relation_root not in snapshot.cells:
        raise InvalidCell("relation root is missing")

    members: list[RelationMember] = []
    seen: set[str] = set()
    cursor = relation_root
    steps = 0
    source_cells: list[Cell] = []
    while cursor != NULL_CELL_ID:
        steps += 1
        if steps > budget:
            raise MatchBudgetExceeded(
                "relation projection exceeded %s chain cells" % budget
            )
        if cursor in seen:
            raise InvalidCell("relation chain contains a cycle")
        seen.add(cursor)
        chain = snapshot.cells.get(cursor)
        if chain is None:
            raise InvalidCell("relation chain contains a dangling cell")
        source_cells.append(chain)
        if chain.link0 == NULL_CELL_ID:
            if chain.link1 != NULL_CELL_ID:
                raise InvalidCell("empty relation root has a non-empty tail")
            break
        incidence = snapshot.cells.get(chain.link0)
        if incidence is None:
            raise InvalidCell("relation incidence is missing")
        source_cells.append(incidence)
        if (
            incidence.link0 not in snapshot.cells
            or incidence.link1 not in snapshot.cells
        ):
            raise InvalidCell("relation incidence contains a dangling link")
        members.append(RelationMember(
            incidence.id,
            incidence.link0,
            incidence.link1,
        ))
        cursor = chain.link1
    projected = tuple(members)
    if cache is not None:
        cache[cache_key] = RelationProjectionReuse(
            source_revision=snapshot.revision,
            relation_root=relation_root,
            members=projected,
            steps=steps,
            source_cells=tuple(source_cells),
        )
    return projected


def capture_relation_projections(
    snapshot: Snapshot,
    relation_roots: Iterable[str],
) -> tuple[RelationProjectionReuse, ...]:
    """Capture only relation walks already performed in this request scope."""
    cache = _RELATION_PROJECTION_CACHE.get()
    if cache is None:
        raise InvalidCell("relation projection capture requires a request scope")
    captured = []
    for relation_root in dict.fromkeys(relation_roots):
        if type(relation_root) is not str:
            raise InvalidCell("relation projection root is invalid")
        entry = cache.get((
            snapshot.revision,
            id(snapshot.cells),
            relation_root,
        ))
        if entry is not None:
            captured.append(entry)
    return tuple(captured)


def relation_projection_fingerprint(
    projections: Iterable[RelationProjectionReuse],
) -> str:
    """Fingerprint one ordered, disposable batch without minting authority."""
    digest = hashlib.sha256()

    def add(value: str | bytes | int) -> None:
        encoded = (
            value if type(value) is bytes else str(value).encode("utf-8")
        )
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)

    entries = tuple(projections)
    add(len(entries))
    for entry in entries:
        if (
            type(entry) is not RelationProjectionReuse
            or type(entry.source_revision) is not int
            or type(entry.relation_root) is not str
            or type(entry.steps) is not int
            or entry.steps < 1
            or not entry.source_cells
        ):
            raise InvalidCell("relation projection reuse is invalid")
        add(entry.source_revision)
        add(entry.relation_root)
        add(entry.steps)
        add(len(entry.members))
        for member in entry.members:
            if type(member) is not RelationMember:
                raise InvalidCell("relation projection reuse is invalid")
            add(member.incidence_id)
            add(member.role_id)
            add(member.participant_id)
        add(len(entry.source_cells))
        for cell in entry.source_cells:
            if type(cell) is not Cell:
                raise InvalidCell("relation projection reuse is invalid")
            add(cell.id)
            add(cell.link0)
            add(cell.link1)
            add(cell.atom)
    fingerprint = digest.hexdigest()
    seals = _RELATION_PROJECTION_BATCH_SEALS.get()
    if seals is not None:
        seals[id(entries)] = (entries, fingerprint)
    return fingerprint


def seed_relation_projections(
    snapshot: Snapshot,
    projections: Iterable[RelationProjectionReuse],
    *,
    expected_source_revision: int,
    expected_target_revision: int,
    expected_fingerprint: str,
    changed_roots: Iterable[str],
) -> None:
    """Seed the current request cache after exact revision/dependency proof."""
    cache = _RELATION_PROJECTION_CACHE.get()
    if cache is None:
        raise InvalidCell("relation projection seed requires a request scope")
    if (
        type(expected_source_revision) is not int
        or type(expected_target_revision) is not int
        or expected_target_revision != expected_source_revision + 1
        or snapshot.revision != expected_target_revision
    ):
        raise InvalidCell("relation projection reuse revision drifted")
    entries = tuple(projections)
    if type(expected_fingerprint) is not str:
        raise InvalidCell("relation projection fingerprint drifted")
    seals = _RELATION_PROJECTION_BATCH_SEALS.get()
    registered = seals.get(id(entries)) if seals is not None else None
    if registered is not None:
        registered_entries, registered_fingerprint = registered
        fingerprint_matches = (
            registered_entries is entries
            and registered_fingerprint == expected_fingerprint
        )
    else:
        fingerprint_matches = (
            relation_projection_fingerprint(entries) == expected_fingerprint
        )
    if not fingerprint_matches:
        raise InvalidCell("relation projection fingerprint drifted")
    changed = tuple(changed_roots)
    if (
        len(changed) != len(set(changed))
        or any(type(root_id) is not str for root_id in changed)
    ):
        raise InvalidCell("relation projection changed-root receipt is invalid")
    changed_set = set(changed)
    seen_roots = set()
    for entry in entries:
        if (
            type(entry) is not RelationProjectionReuse
            or entry.source_revision not in (
                expected_source_revision,
                expected_target_revision,
            )
            or entry.relation_root in seen_roots
        ):
            raise InvalidCell("relation projection reuse revision drifted")
        seen_roots.add(entry.relation_root)
        for source_cell in entry.source_cells:
            if (
                source_cell.id in changed_set
                and snapshot.cells.get(source_cell.id) != source_cell
            ):
                raise InvalidCell("relation projection source Cell drifted")
        cache_key = (
            snapshot.revision,
            id(snapshot.cells),
            entry.relation_root,
        )
        existing = cache.get(cache_key)
        if existing is not None and existing != entry:
            raise InvalidCell("relation projection cache conflicts")
        cache[cache_key] = entry


def rewire_incidence(
    store: CellStore,
    incidence_id: str,
    participant_id: str,
) -> int:
    incidence = store.read(incidence_id)
    return store.commit(store.revision, replace=[
        Cell(
            incidence.id,
            incidence.link0,
            participant_id,
            incidence.atom,
        )
    ])


def append_relation_member(
    store: CellStore,
    relation_root: str,
    role_id: str,
    participant_id: str,
    *,
    budget: int = 10_000,
) -> str:
    """Extend a relation chain without replacing its stable root identity."""
    snapshot = store.snapshot()
    patch = prepare_append_relation_member(
        snapshot,
        relation_root,
        role_id,
        participant_id,
        budget=budget,
    )
    store.commit(
        snapshot.revision, create=patch.create, replace=patch.replace
    )
    return patch.incidence_id


def prepare_append_relation_member(
    snapshot: Snapshot,
    relation_root: str,
    role_id: str,
    participant_id: str,
    *,
    budget: int = 10_000,
) -> RelationPatch:
    """Prepare an append patch that can share a larger atomic commit."""
    patch = prepare_append_relation_members(
        snapshot,
        relation_root,
        ((role_id, participant_id),),
        budget=budget,
    )
    return RelationPatch(
        patch.incidence_ids[0], patch.create, patch.replace
    )


def prepare_append_relation_members(
    snapshot: Snapshot,
    relation_root: str,
    members: Iterable[tuple[str, str]],
    *,
    budget: int = 10_000,
) -> RelationAppendPatch:
    """Prepare one atomic append of zero or more relation members."""
    pairs = tuple(members)
    if not pairs:
        return RelationAppendPatch((), (), ())
    if relation_root not in snapshot.cells:
        raise InvalidCell("relation root is missing")
    cursor = relation_root
    seen: set[str] = set()
    steps = 0
    while True:
        steps += 1
        if steps > budget:
            raise MatchBudgetExceeded(
                "relation append exceeded %s chain cells" % budget
            )
        if cursor in seen:
            raise InvalidCell("relation chain contains a cycle")
        seen.add(cursor)
        chain = snapshot.cells[cursor]
        if chain.link0 == NULL_CELL_ID:
            if chain.link1 != NULL_CELL_ID:
                raise InvalidCell("empty relation root has a non-empty tail")
            incidence_ids = tuple(_new_id("incidence") for _ in pairs)
            chain_ids = tuple(
                _new_id("chain") for _ in range(max(0, len(pairs) - 1))
            )
            created: list[Cell] = []
            for index, ((role_id, participant_id), incidence_id) in enumerate(
                zip(pairs, incidence_ids)
            ):
                created.append(Cell(
                    incidence_id, role_id, participant_id, b""
                ))
                if index > 0:
                    next_chain = (
                        chain_ids[index]
                        if index < len(chain_ids)
                        else NULL_CELL_ID
                    )
                    created.append(Cell(
                        chain_ids[index - 1],
                        incidence_id,
                        next_chain,
                        b"",
                    ))
            first_tail = chain_ids[0] if chain_ids else NULL_CELL_ID
            return RelationAppendPatch(
                incidence_ids,
                tuple(created),
                (Cell(
                    chain.id,
                    incidence_ids[0],
                    first_tail,
                    chain.atom,
                ),),
            )
        if chain.link1 == NULL_CELL_ID:
            incidence_ids = tuple(_new_id("incidence") for _ in pairs)
            chain_ids = tuple(_new_id("chain") for _ in pairs)
            created = []
            for index, ((role_id, participant_id), incidence_id) in enumerate(
                zip(pairs, incidence_ids)
            ):
                next_chain = (
                    chain_ids[index + 1]
                    if index + 1 < len(chain_ids)
                    else NULL_CELL_ID
                )
                created.extend((
                    Cell(incidence_id, role_id, participant_id, b""),
                    Cell(chain_ids[index], incidence_id, next_chain, b""),
                ))
            return RelationAppendPatch(
                incidence_ids,
                tuple(created),
                (Cell(
                    chain.id,
                    chain.link0,
                    chain_ids[0],
                    chain.atom,
                ),),
            )
        cursor = chain.link1


def _relation_chain_ids(
    snapshot: Snapshot,
    relation_root: str,
    *,
    budget: int,
) -> tuple[str, ...]:
    if relation_root not in snapshot.cells:
        raise InvalidCell("relation root is missing")
    cursor = relation_root
    chain_ids: list[str] = []
    seen: set[str] = set()
    while cursor != NULL_CELL_ID:
        if len(chain_ids) >= budget:
            raise MatchBudgetExceeded(
                "relation traversal exceeded %s chain cells" % budget
            )
        if cursor in seen:
            raise InvalidCell("relation chain contains a cycle")
        seen.add(cursor)
        chain = snapshot.cells[cursor]
        chain_ids.append(cursor)
        cursor = chain.link1
    return tuple(chain_ids)


def insert_relation_member(
    store: CellStore,
    relation_root: str,
    role_id: str,
    participant_id: str,
    *,
    before_incidence: str | None = None,
    after_incidence: str | None = None,
    budget: int = 10_000,
) -> str:
    """Atomically insert one stable incidence into an ordered relation."""
    if before_incidence is not None and after_incidence is not None:
        raise InvalidCell("relation insertion accepts one anchor direction")
    snapshot = store.snapshot()
    chain_ids = _relation_chain_ids(
        snapshot, relation_root, budget=budget
    )
    members = read_relation(snapshot, relation_root, budget=budget)
    incidence_ids = tuple(member.incidence_id for member in members)
    anchor = before_incidence or after_incidence
    if anchor is not None and anchor not in incidence_ids:
        raise InvalidCell("relation insertion anchor is not a member")

    incidence_id = _new_id("incidence")
    incidence = Cell(incidence_id, role_id, participant_id, b"")
    root = snapshot.cells[relation_root]
    if not members:
        store.commit(snapshot.revision, create=(incidence,), replace=(
            Cell(root.id, incidence_id, NULL_CELL_ID, root.atom),
        ))
        return incidence_id

    if before_incidence is None and after_incidence is None:
        after_incidence = incidence_ids[-1]

    if before_incidence is not None:
        target_index = incidence_ids.index(before_incidence)
        if target_index == 0:
            shifted_id = _new_id("chain")
            shifted = Cell(shifted_id, root.link0, root.link1, b"")
            store.commit(snapshot.revision, create=(incidence, shifted), replace=(
                Cell(root.id, incidence_id, shifted_id, root.atom),
            ))
            return incidence_id
        predecessor = snapshot.cells[chain_ids[target_index - 1]]
        inserted_id = _new_id("chain")
        inserted = Cell(
            inserted_id, incidence_id, chain_ids[target_index], b""
        )
        store.commit(snapshot.revision, create=(incidence, inserted), replace=(
            Cell(
                predecessor.id,
                predecessor.link0,
                inserted_id,
                predecessor.atom,
            ),
        ))
        return incidence_id

    target_index = incidence_ids.index(after_incidence)
    target = snapshot.cells[chain_ids[target_index]]
    inserted_id = _new_id("chain")
    inserted = Cell(inserted_id, incidence_id, target.link1, b"")
    store.commit(snapshot.revision, create=(incidence, inserted), replace=(
        Cell(target.id, target.link0, inserted_id, target.atom),
    ))
    return incidence_id


def remove_relation_member(
    store: CellStore,
    relation_root: str,
    incidence_id: str,
    *,
    budget: int = 10_000,
) -> RelationMember:
    """Atomically detach one incidence while preserving history snapshots."""
    snapshot = store.snapshot()
    removed, patch = prepare_remove_relation_member(
        snapshot, relation_root, incidence_id, budget=budget
    )
    store.commit(snapshot.revision, replace=patch.replace)
    return removed


def prepare_remove_relation_member(
    snapshot: Snapshot,
    relation_root: str,
    incidence_id: str,
    *,
    budget: int = 10_000,
) -> tuple[RelationMember, RelationPatch]:
    """Prepare one stable-incidence detach for a larger atomic commit."""
    removal = prepare_remove_relation_members(
        snapshot, relation_root, (incidence_id,), budget=budget
    )
    return removal.removed[0], RelationPatch(
        incidence_id, (), removal.replace
    )


def prepare_remove_relation_members(
    snapshot: Snapshot,
    relation_root: str,
    incidence_ids: Iterable[str],
    *,
    budget: int = 10_000,
) -> RelationRemovalPatch:
    """Prepare an atomic detach of several stable relation incidences."""
    requested = tuple(dict.fromkeys(incidence_ids))
    if not requested:
        return RelationRemovalPatch((), ())
    chain_ids = _relation_chain_ids(
        snapshot, relation_root, budget=budget
    )
    members = read_relation(snapshot, relation_root, budget=budget)
    member_by_incidence = {
        member.incidence_id: member for member in members
    }
    if any(incidence_id not in member_by_incidence for incidence_id in requested):
        raise InvalidCell("relation removal target is not a member")
    removed_ids = set(requested)
    removed = tuple(member_by_incidence[root] for root in requested)
    remaining = tuple(
        (index, member) for index, member in enumerate(members)
        if member.incidence_id not in removed_ids
    )
    root = snapshot.cells[relation_root]
    if not remaining:
        return RelationRemovalPatch(
            removed,
            (Cell(root.id, NULL_CELL_ID, NULL_CELL_ID, root.atom),),
        )
    root_replacement = Cell(
        root.id,
        remaining[0][1].incidence_id,
        chain_ids[remaining[1][0]] if len(remaining) > 1 else NULL_CELL_ID,
        root.atom,
    )
    replacements = (
        [root_replacement] if root_replacement != root else []
    )
    for offset, (index, member) in enumerate(remaining[1:], start=1):
        chain = snapshot.cells[chain_ids[index]]
        replacement = Cell(
            chain.id,
            member.incidence_id,
            (
                chain_ids[remaining[offset + 1][0]]
                if offset + 1 < len(remaining) else NULL_CELL_ID
            ),
            chain.atom,
        )
        if replacement != chain:
            replacements.append(replacement)
    return RelationRemovalPatch(removed, tuple(replacements))


def prepare_reorder_relation_members(
    snapshot: Snapshot,
    relation_root: str,
    incidence_order: Iterable[str],
    *,
    budget: int = 10_000,
) -> tuple[Cell, ...]:
    """Prepare an exact relation permutation without changing identities."""
    requested = tuple(incidence_order)
    chain_ids = _relation_chain_ids(
        snapshot, relation_root, budget=budget
    )
    members = read_relation(snapshot, relation_root, budget=budget)
    current = tuple(member.incidence_id for member in members)
    if len(requested) != len(set(requested)) or set(requested) != set(current):
        raise InvalidCell("relation reorder must be an exact member permutation")
    replacements = []
    for chain_id, incidence_id in zip(chain_ids, requested):
        chain = snapshot.cells[chain_id]
        if chain.link0 != incidence_id:
            replacements.append(Cell(
                chain.id, incidence_id, chain.link1, chain.atom
            ))
    return tuple(replacements)


def reorder_relation_members(
    store: CellStore,
    relation_root: str,
    incidence_order: Iterable[str],
    *,
    budget: int = 10_000,
) -> int:
    """Atomically reorder existing members without changing incidence identity."""
    snapshot = store.snapshot()
    replacements = prepare_reorder_relation_members(
        snapshot, relation_root, incidence_order, budget=budget
    )
    if not replacements:
        return snapshot.revision
    return store.commit(snapshot.revision, replace=replacements)


def _participant_for_role(
    members: Iterable[RelationMember],
    role_id: str,
) -> str | None:
    matches = [
        member.participant_id for member in members if member.role_id == role_id
    ]
    if len(matches) > 1:
        raise InvalidCell("a single-valued lens role has multiple participants")
    return matches[0] if matches else None


def inspect_properties(
    snapshot: Snapshot,
    *,
    selected_root: str,
    relation_roots: Iterable[str],
    owner_role: str,
    value_role: str,
    label_role: str,
    budget: int = 10_000,
) -> tuple[PropertyProjection, ...]:
    """Project right-panel rows from caller-supplied role cell identities."""
    rows: list[PropertyProjection] = []
    for relation_root in relation_roots:
        members = read_relation(snapshot, relation_root, budget=budget)
        owner = _participant_for_role(members, owner_role)
        if owner != selected_root:
            continue
        value = _participant_for_role(members, value_role)
        label = _participant_for_role(members, label_role)
        if value is None or label is None:
            continue
        rows.append(PropertyProjection(relation_root, owner, value, label))
    return tuple(rows)


def inspect_wired_properties(
    snapshot: Snapshot,
    *,
    lens_root: str,
    selection_role: str,
    scope_role: str,
    owner_role: str,
    value_role: str,
    label_role: str,
    budget: int = 10_000,
) -> tuple[PropertyProjection, ...]:
    """Resolve selection and readable relation scope from one wired lens."""
    lens_members = read_relation(snapshot, lens_root, budget=budget)
    selection = _participant_for_role(lens_members, selection_role)
    if selection is None:
        return ()
    relation_roots = tuple(
        member.participant_id
        for member in lens_members
        if member.role_id == scope_role
    )
    return inspect_properties(
        snapshot,
        selected_root=selection,
        relation_roots=relation_roots,
        owner_role=owner_role,
        value_role=value_role,
        label_role=label_role,
        budget=budget,
    )


def open_composition(
    snapshot: Snapshot,
    root_id: str,
    *,
    budget: int = 100_000,
) -> frozenset[str]:
    """Return a reachable lens region without mutating containment state."""
    if root_id not in snapshot.cells:
        raise InvalidCell("composition root is missing")
    if budget < 1:
        raise MatchBudgetExceeded("composition budget must be positive")
    opened: set[str] = set()
    pending = [root_id]
    while pending:
        cell_id = pending.pop()
        if cell_id in opened:
            continue
        if len(opened) >= budget:
            raise MatchBudgetExceeded(
                "composition exceeded %s reachable cells" % budget
            )
        cell = snapshot.cells.get(cell_id)
        if cell is None:
            raise InvalidCell("composition contains a dangling physical link")
        opened.add(cell_id)
        pending.append(cell.link0)
        pending.append(cell.link1)
    return frozenset(opened)


def _relation_region(
    snapshot: Snapshot,
    relation_root: str,
    *,
    budget: int,
) -> tuple[frozenset[str], tuple[RelationMember, ...]]:
    members = read_relation(snapshot, relation_root, budget=budget)
    region: set[str] = {relation_root, NULL_CELL_ID}
    cursor = relation_root
    steps = 0
    while cursor != NULL_CELL_ID:
        steps += 1
        if steps > budget:
            raise MatchBudgetExceeded(
                "relation region exceeded %s chain cells" % budget
            )
        chain = snapshot.cells[cursor]
        region.add(chain.id)
        if chain.link0 != NULL_CELL_ID:
            incidence = snapshot.cells[chain.link0]
            region.update((incidence.id, incidence.link0, incidence.link1))
        cursor = chain.link1
    return frozenset(region), members


def open_scoped_composition(
    snapshot: Snapshot,
    root_id: str,
    *,
    member_role: str,
    scope_role: str,
    budget: int = 100_000,
) -> frozenset[str]:
    """Open one explicit boundary without chasing cross-boundary endpoints.

    Direct members are exposed as roots. Participants wired under ``scope_role``
    are themselves projected as complete relation regions. Their endpoint roots
    remain visible boundary nodes, but are not recursively expanded.
    """
    root_region, members = _relation_region(snapshot, root_id, budget=budget)
    opened = set(root_region)
    for member in members:
        if member.role_id == scope_role:
            scoped_region, _ = _relation_region(
                snapshot, member.participant_id, budget=budget
            )
            opened.update(scoped_region)
        elif member.role_id == member_role:
            opened.add(member.participant_id)
        else:
            opened.add(member.participant_id)
        if len(opened) > budget:
            raise MatchBudgetExceeded(
                "scoped composition exceeded %s cells" % budget
            )
    return frozenset(opened)


def set_property_atom(
    store: CellStore,
    relation_root: str,
    *,
    value_role: str,
    atom: bytes,
    budget: int = 10_000,
) -> str:
    members = read_relation(store.snapshot(), relation_root, budget=budget)
    value_root = _participant_for_role(members, value_role)
    if value_root is None:
        raise InvalidCell("property relation has no value participant")
    value = store.read(value_root)
    store.commit(store.revision, replace=[
        Cell(value.id, value.link0, value.link1, atom)
    ])
    return value_root


__all__ = [
    "RelationBuild",
    "RelationCells",
    "RelationPatch",
    "RelationRemovalPatch",
    "RelationMember",
    "RelationProjectionReuse",
    "PropertyProjection",
    "CellBatch",
    "build_relation",
    "compose_relation_cells",
    "read_relation",
    "capture_relation_projections",
    "relation_projection_fingerprint",
    "seed_relation_projections",
    "relation_projection_scope",
    "with_relation_projection_scope",
    "rewire_incidence",
    "append_relation_member",
    "prepare_append_relation_member",
    "prepare_remove_relation_member",
    "prepare_remove_relation_members",
    "prepare_reorder_relation_members",
    "insert_relation_member",
    "remove_relation_member",
    "reorder_relation_members",
    "inspect_properties",
    "inspect_wired_properties",
    "open_composition",
    "open_scoped_composition",
    "set_property_atom",
]
