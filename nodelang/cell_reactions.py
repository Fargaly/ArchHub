"""Graph-held reactive observations for universal-cell assemblies.

The runtime dispatches no Watcher or product name. It reads reaction manifests
from a graph registry, fingerprints graph-declared sources, and atomically
records state plus event history. A background worker is optional; deterministic
tests and hosts may call ``drain`` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid

from .cell_catalog import AssemblyProtocol
from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_member,
    prepare_append_relation_members,
    read_relation,
    rewire_incidence,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
    Snapshot,
    overlay_read_snapshot,
)


REACTION_ROLE_NAMES = (
    "vocabulary-member",
    "reaction-member",
    "source-interface",
    "event-log",
    "fingerprint-state",
    "cursor-state",
    "enabled-state",
    "status-state",
    "error-state",
    "event-member",
    "event-source",
    "event-fingerprint",
    "event-revision",
)


class ReactionBudgetExceeded(RuntimeError):
    """A reactive graph did not reach a fixed point within its court budget."""


@dataclass(frozen=True, slots=True)
class ReactionProtocol:
    root_id: str
    registry_root: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown reaction role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class ReactionBuild:
    root_id: str
    part_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReactionEventProjection:
    root_id: str
    source_root: str
    fingerprint: str
    revision: int


@dataclass(frozen=True, slots=True)
class ReactionRegistrationPatch:
    """Unpublished registry membership for graph-declared reaction rules."""

    roots: tuple[str, ...]
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeProjection:
    root_id: str
    source_interface: str
    event_log: str
    fingerprint_state: str
    cursor_state: str
    enabled_state: str
    status_state: str
    error_state: str
    enabled_incidence: str


def bootstrap_reaction_protocol(
    store: CellStore,
    *,
    prefix: str = "reaction-protocol",
) -> ReactionProtocol:
    roles = {
        name: "%s:role:%s" % (prefix, name)
        for name in REACTION_ROLE_NAMES
    }
    states = {
        "enabled": "%s:state:enabled" % prefix,
        "disabled": "%s:state:disabled" % prefix,
    }
    registry_root = "%s:registry" % prefix
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    for name, root_id in states.items():
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
    batch.relation((), relation_id=registry_root)
    root_id = "%s:root" % prefix
    batch.relation([
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
        (roles["vocabulary-member"], registry_root),
    ], relation_id=root_id)
    batch.commit()
    return ReactionProtocol(
        root_id=root_id,
        registry_root=registry_root,
        roles=MappingProxyType(roles),
        states=MappingProxyType(states),
    )


def build_reaction_manifest(
    store: CellStore,
    protocol: ReactionProtocol,
    *,
    reaction_id: str,
    source_interface: str,
    event_log: str,
    fingerprint_state: str,
    cursor_state: str,
    status_state: str,
    error_state: str,
) -> ReactionBuild:
    batch = CellBatch(store)
    built = batch.relation([
        (protocol.role("source-interface"), source_interface),
        (protocol.role("event-log"), event_log),
        (protocol.role("fingerprint-state"), fingerprint_state),
        (protocol.role("cursor-state"), cursor_state),
        (protocol.role("enabled-state"), protocol.states["enabled"]),
        (protocol.role("status-state"), status_state),
        (protocol.role("error-state"), error_state),
    ], relation_id=reaction_id)
    batch.commit()
    return ReactionBuild(
        reaction_id,
        tuple(dict.fromkeys((*built.chain_ids, *built.incidence_ids))),
    )


def _for_role(members, role_id: str):
    return tuple(
        member for member in members if member.role_id == role_id
    )


def _one_member(members, role_id: str, label: str):
    found = _for_role(members, role_id)
    if len(found) != 1:
        raise InvalidCell("reaction requires exactly one %s" % label)
    return found[0]


def _runtime(
    snapshot: Snapshot,
    protocol: ReactionProtocol,
    reaction_root: str,
) -> _RuntimeProjection:
    members = read_relation(snapshot, reaction_root, budget=100_000)

    def participant(role_name: str):
        return _one_member(
            members, protocol.role(role_name), role_name
        ).participant_id

    enabled = _one_member(
        members, protocol.role("enabled-state"), "enabled-state"
    )
    return _RuntimeProjection(
        root_id=reaction_root,
        source_interface=participant("source-interface"),
        event_log=participant("event-log"),
        fingerprint_state=participant("fingerprint-state"),
        cursor_state=participant("cursor-state"),
        enabled_state=enabled.participant_id,
        status_state=participant("status-state"),
        error_state=participant("error-state"),
        enabled_incidence=enabled.incidence_id,
    )


def prepare_reaction_instance_registration(
    snapshot: Snapshot,
    assembly: AssemblyProtocol,
    reaction: ReactionProtocol,
    instance_root: str,
    *,
    pending_cells: Iterable[Cell] = (),
) -> ReactionRegistrationPatch:
    """Validate and prepare reaction membership for one atomic caller commit."""
    pending = tuple(pending_cells)
    pending_ids = tuple(cell.id for cell in pending)
    if (
        len(pending_ids) != len(set(pending_ids))
        or any(cell_id in snapshot.cells for cell_id in pending_ids)
    ):
        raise InvalidCell("reaction registration has invalid pending identities")
    candidate = (
        overlay_read_snapshot(snapshot, create=pending)
        if pending
        else snapshot
    )
    instance = read_relation(candidate, instance_root, budget=100_000)
    roots = tuple(
        member.participant_id for member in instance
        if member.role_id == assembly.role("rule")
    )
    if not roots:
        raise InvalidCell("assembly instance exposes no reaction rule")
    existing = {
        member.participant_id for member in read_relation(
            snapshot, reaction.registry_root, budget=100_000
        )
        if member.role_id == reaction.role("reaction-member")
    }
    for root_id in roots:
        _runtime(candidate, reaction, root_id)
    patch = prepare_append_relation_members(
        snapshot,
        reaction.registry_root,
        (
            (reaction.role("reaction-member"), root_id)
            for root_id in roots
            if root_id not in existing
        ),
        budget=100_000,
    )
    return ReactionRegistrationPatch(roots, patch.create, patch.replace)


def register_reaction_instance(
    store: CellStore,
    assembly: AssemblyProtocol,
    reaction: ReactionProtocol,
    instance_root: str,
) -> tuple[str, ...]:
    """Register graph-declared rule roots from any assembly instance."""
    snapshot = store.snapshot()
    patch = prepare_reaction_instance_registration(
        snapshot, assembly, reaction, instance_root
    )
    if patch.create or patch.replace:
        store.commit(
            snapshot.revision, create=patch.create, replace=patch.replace
        )
    return patch.roots


def wire_instance_source(
    store: CellStore,
    assembly: AssemblyProtocol,
    instance_root: str,
    source_root: str,
) -> str:
    """Rewire the single public interface of a reaction instance."""
    instance = read_relation(store.snapshot(), instance_root, budget=100_000)
    interfaces = tuple(
        member.participant_id for member in instance
        if member.role_id == assembly.role("interface")
    )
    if len(interfaces) != 1:
        raise InvalidCell("reaction instance requires one source interface")
    members = read_relation(store.snapshot(), interfaces[0], budget=100_000)
    target = _one_member(
        members, assembly.role("interface-target"), "interface target"
    )
    rewire_incidence(store, target.incidence_id, source_root)
    return interfaces[0]


def set_reaction_enabled(
    store: CellStore,
    protocol: ReactionProtocol,
    reaction_root: str,
    enabled: bool,
) -> int:
    runtime = _runtime(store.snapshot(), protocol, reaction_root)
    return rewire_incidence(
        store,
        runtime.enabled_incidence,
        protocol.states["enabled" if enabled else "disabled"],
    )


def reaction_events(
    snapshot: Snapshot,
    protocol: ReactionProtocol,
    reaction_root: str,
) -> tuple[ReactionEventProjection, ...]:
    runtime = _runtime(snapshot, protocol, reaction_root)
    events = read_relation(snapshot, runtime.event_log, budget=100_000)
    result: list[ReactionEventProjection] = []
    for event_member in events:
        if event_member.role_id != protocol.role("event-member"):
            continue
        event = read_relation(
            snapshot, event_member.participant_id, budget=100_000
        )
        source = _one_member(
            event, protocol.role("event-source"), "event source"
        ).participant_id
        fingerprint_root = _one_member(
            event, protocol.role("event-fingerprint"), "event fingerprint"
        ).participant_id
        revision_root = _one_member(
            event, protocol.role("event-revision"), "event revision"
        ).participant_id
        result.append(ReactionEventProjection(
            event_member.participant_id,
            source,
            snapshot.cells[fingerprint_root].atom.decode("ascii"),
            int(snapshot.cells[revision_root].atom.decode("ascii")),
        ))
    return tuple(result)


class ReactionEngine:
    """Coalescing, restartable reaction scheduler over graph-held manifests."""

    def __init__(
        self,
        store: CellStore,
        assembly: AssemblyProtocol,
        reaction: ReactionProtocol,
        *,
        fingerprint_budget: int = 250_000,
    ) -> None:
        self.store = store
        self.assembly = assembly
        self.reaction = reaction
        self.fingerprint_budget = fingerprint_budget
        self._drain_lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._unsubscribe = None
        self._failures: list[str] = []

    def _source_root(self, snapshot: Snapshot, runtime: _RuntimeProjection) -> str:
        interface = read_relation(
            snapshot, runtime.source_interface, budget=100_000
        )
        return _one_member(
            interface,
            self.assembly.role("interface-target"),
            "source interface target",
        ).participant_id

    @staticmethod
    def _observation_exclusions(
        runtime: _RuntimeProjection,
    ) -> tuple[str, ...]:
        return (
            runtime.root_id,
            runtime.event_log,
            runtime.fingerprint_state,
            runtime.cursor_state,
            runtime.enabled_state,
            runtime.status_state,
            runtime.error_state,
        )

    def _state_replacements(
        self,
        snapshot: Snapshot,
        runtime: _RuntimeProjection,
        *,
        fingerprint: bytes,
        cursor: bytes,
        status: bytes,
        error: bytes,
    ) -> tuple[Cell, ...]:
        replacements = []
        for root_id, atom in (
            (runtime.fingerprint_state, fingerprint),
            (runtime.cursor_state, cursor),
            (runtime.status_state, status),
            (runtime.error_state, error),
        ):
            cell = snapshot.cells[root_id]
            if cell.atom != atom:
                replacements.append(Cell(
                    cell.id, cell.link0, cell.link1, atom
                ))
        return tuple(replacements)

    def _baseline(
        self,
        snapshot: Snapshot,
        runtime: _RuntimeProjection,
        fingerprint: str,
    ) -> bool:
        replacements = self._state_replacements(
            snapshot,
            runtime,
            fingerprint=fingerprint.encode("ascii"),
            cursor=str(snapshot.revision).encode("ascii"),
            status=b"ready",
            error=b"",
        )
        if not replacements:
            return False
        self.store.commit(snapshot.revision, replace=replacements)
        return True

    def _emit(
        self,
        snapshot: Snapshot,
        runtime: _RuntimeProjection,
        source_root: str,
        fingerprint: str,
    ) -> None:
        token = uuid.uuid4().hex
        event_root = "reaction-event:%s" % token
        fingerprint_root = event_root + ":fingerprint"
        revision_root = event_root + ":revision"
        event_cells = compose_relation_cells([
            (self.reaction.role("event-source"), source_root),
            (self.reaction.role("event-fingerprint"), fingerprint_root),
            (self.reaction.role("event-revision"), revision_root),
        ], relation_id=event_root)
        append = prepare_append_relation_member(
            snapshot,
            runtime.event_log,
            self.reaction.role("event-member"),
            event_root,
            budget=100_000,
        )
        state = self._state_replacements(
            snapshot,
            runtime,
            fingerprint=fingerprint.encode("ascii"),
            cursor=str(snapshot.revision).encode("ascii"),
            status=b"changed",
            error=b"",
        )
        self.store.commit(
            snapshot.revision,
            create=(
                Cell(
                    fingerprint_root,
                    NULL_CELL_ID,
                    NULL_CELL_ID,
                    fingerprint.encode("ascii"),
                ),
                Cell(
                    revision_root,
                    NULL_CELL_ID,
                    NULL_CELL_ID,
                    str(snapshot.revision).encode("ascii"),
                ),
                *event_cells.cells,
                *append.create,
            ),
            replace=(*append.replace, *state),
        )

    def _evaluate(self, reaction_root: str) -> bool:
        snapshot = self.store.snapshot()
        runtime = _runtime(snapshot, self.reaction, reaction_root)
        if runtime.enabled_state != self.reaction.states["enabled"]:
            return False
        source_root = self._source_root(snapshot, runtime)
        fingerprint = self.store.fingerprint(
            source_root,
            budget=self.fingerprint_budget,
            excluded_roots=self._observation_exclusions(runtime),
        )
        prior = snapshot.cells[runtime.fingerprint_state].atom
        if not prior:
            return self._baseline(snapshot, runtime, fingerprint)
        if prior == fingerprint.encode("ascii"):
            return False
        self._emit(snapshot, runtime, source_root, fingerprint)
        return True

    def _disable_with_error(self, reaction_root: str, message: str) -> None:
        snapshot = self.store.snapshot()
        try:
            runtime = _runtime(snapshot, self.reaction, reaction_root)
        except Exception:
            return
        replacements = list(self._state_replacements(
            snapshot,
            runtime,
            fingerprint=snapshot.cells[runtime.fingerprint_state].atom,
            cursor=snapshot.cells[runtime.cursor_state].atom,
            status=b"error",
            error=message.encode("utf-8", errors="replace")[:4096],
        ))
        incidence = snapshot.cells[runtime.enabled_incidence]
        replacements.append(Cell(
            incidence.id,
            incidence.link0,
            self.reaction.states["disabled"],
            incidence.atom,
        ))
        self.store.commit(snapshot.revision, replace=replacements)

    def drain(self, *, max_rounds: int = 100) -> int:
        """Run to a fixed point; source bursts coalesce into one latest event."""
        if max_rounds < 1:
            raise ValueError("reaction max_rounds must be positive")
        committed = 0
        with self._drain_lock:
            for _ in range(max_rounds):
                snapshot = self.store.snapshot()
                registry = read_relation(
                    snapshot, self.reaction.registry_root, budget=100_000
                )
                roots = tuple(
                    member.participant_id for member in registry
                    if member.role_id == self.reaction.role("reaction-member")
                )
                round_changed = False
                for root_id in roots:
                    try:
                        changed = self._evaluate(root_id)
                    except (InvalidCell, MatchBudgetExceeded) as exc:
                        self._disable_with_error(root_id, str(exc))
                        committed += 1
                        continue
                    if changed:
                        round_changed = True
                        committed += 1
                if not round_changed:
                    return committed
            registry = read_relation(
                self.store.snapshot(), self.reaction.registry_root, budget=100_000
            )
            roots = tuple(
                member.participant_id for member in registry
                if member.role_id == self.reaction.role("reaction-member")
            )
            for root_id in roots:
                runtime = _runtime(self.store.snapshot(), self.reaction, root_id)
                if runtime.enabled_state == self.reaction.states["enabled"]:
                    self._disable_with_error(
                        root_id, "reaction fixed-point budget exceeded"
                    )
            raise ReactionBudgetExceeded(
                "reaction graph did not stabilize in %s rounds" % max_rounds
            )

    def start(self) -> None:
        """Start one hidden daemon worker; no terminal or process is spawned."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._unsubscribe = self.store.subscribe(lambda event: self._wake.set())

        def run() -> None:
            self._wake.set()
            while not self._stop.is_set():
                self._wake.wait(0.5)
                self._wake.clear()
                if self._stop.is_set():
                    break
                try:
                    self.drain()
                except Exception as exc:
                    self._failures.append("%s: %s" % (type(exc).__name__, exc))
                    if len(self._failures) > 100:
                        del self._failures[:-100]

        self._thread = threading.Thread(
            target=run, name="archhub-cell-reactions", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def failures(self) -> tuple[str, ...]:
        return tuple(self._failures)

    def __enter__(self) -> "ReactionEngine":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()


__all__ = [
    "ReactionBudgetExceeded",
    "ReactionProtocol",
    "ReactionBuild",
    "ReactionEventProjection",
    "ReactionRegistrationPatch",
    "ReactionEngine",
    "bootstrap_reaction_protocol",
    "build_reaction_manifest",
    "prepare_reaction_instance_registration",
    "register_reaction_instance",
    "wire_instance_source",
    "set_reaction_enabled",
    "reaction_events",
]
