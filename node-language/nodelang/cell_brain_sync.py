"""Sync: two copies of a brain that cannot disagree about what they hold.

`brain_personal_cloud_sync` moved fragments over the network. The network is the
easy half. The half that loses memory is the merge: if applying the same batch
twice changes anything, or if the order of arrival changes the result, then two
devices holding the same facts will quietly hold different brains.

The transport stays outside, like the embedding provider and the secret vault.
What lives here is the law: a fragment carries its origin and its clock, the
higher clock wins, ties break on origin id so the answer never depends on who
spoke first, and applying a batch again is a no-op.
"""
from __future__ import annotations

from dataclasses import dataclass

from .universal_cell import NULL_CELL_ID, Cell, InvalidCell


@dataclass(frozen=True, slots=True)
class Fragment:
    root_id: str
    origin: str
    clock: int
    value: str

    def wins_over(self, other):
        """Later clock wins; a tie is broken on origin, never on arrival."""
        if self.clock != other.clock:
            return self.clock > other.clock
        if self.origin != other.origin:
            return self.origin > other.origin
        return False


def make_fragment(root_id, origin, clock, value):
    root_id = str(root_id).strip()
    origin = str(origin).strip()
    if not root_id:
        raise InvalidCell("a fragment must name the root it carries")
    if not origin:
        raise InvalidCell("a fragment without an origin cannot be ordered")
    if not isinstance(clock, int) or isinstance(clock, bool) or clock < 0:
        raise InvalidCell("a fragment clock must be a whole number")
    return Fragment(root_id, origin, clock, str(value))


def _clock_root(root_id):
    return root_id + ":sync-clock"


def _origin_root(root_id):
    return root_id + ":sync-origin"


def held(snapshot, root_id):
    """What this replica holds for a root, with the clock and origin that set it."""
    cell = snapshot.cells.get(root_id)
    if cell is None:
        return None
    clock_cell = snapshot.cells.get(_clock_root(root_id))
    origin_cell = snapshot.cells.get(_origin_root(root_id))
    if clock_cell is None or origin_cell is None:
        raise InvalidCell("root %s was written outside sync authority" % root_id)
    return Fragment(
        root_id,
        bytes(origin_cell.atom).decode("utf-8"),
        int(bytes(clock_cell.atom).decode("ascii")),
        bytes(cell.atom).decode("utf-8"),
    )


def apply_fragments(store, fragments):
    """Merge a batch. Order-independent, and applying it twice changes nothing."""
    accepted = 0
    for fragment in fragments:
        if not isinstance(fragment, Fragment):
            raise InvalidCell("only a fragment can be merged")
        snapshot = store.snapshot()
        current = held(snapshot, fragment.root_id)
        if current is not None and not fragment.wins_over(current):
            continue
        value_cell = Cell(
            fragment.root_id, NULL_CELL_ID, NULL_CELL_ID,
            fragment.value.encode("utf-8"),
        )
        clock_cell = Cell(
            _clock_root(fragment.root_id), NULL_CELL_ID, NULL_CELL_ID,
            str(fragment.clock).encode("ascii"),
        )
        origin_cell = Cell(
            _origin_root(fragment.root_id), NULL_CELL_ID, NULL_CELL_ID,
            fragment.origin.encode("utf-8"),
        )
        if current is None:
            store.commit(snapshot.revision, create=(
                value_cell, clock_cell, origin_cell))
        else:
            store.commit(snapshot.revision, replace=(
                value_cell, clock_cell, origin_cell))
        accepted += 1
    return accepted


def export_since(snapshot, roots, since_clock=0):
    """Everything this replica holds at or after a clock, ready to send."""
    if since_clock < 0:
        raise InvalidCell("a sync cannot start before the beginning")
    out = []
    for root_id in roots:
        current = held(snapshot, root_id)
        if current is not None and current.clock >= since_clock:
            out.append(current)
    return tuple(sorted(out, key=lambda f: (f.clock, f.root_id)))


def converged(left_snapshot, right_snapshot, roots):
    """True when two replicas agree about every root, value AND provenance."""
    for root_id in roots:
        if held(left_snapshot, root_id) != held(right_snapshot, root_id):
            return False
    return True
