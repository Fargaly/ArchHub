"""The action-history projection may reuse walks, never change what it means.

Reading the founder graph re-walked all 357 committed change transactions on
every canvas read: 8.8 s of a 8.9 s read (3ca3205, 7.08 GB store, revision
112817). These courts hold the accelerator to SPEC 3.1.6-7 -- disposable,
revision-bound, meaning-preserving. They do NOT hold it to the SPEC 11.14 bar
of 0.150 s, and no court in this file asserts that bar: it is missed on both
real stores (see the latency court below for the measured numbers). A fixture
that is built fresh in the same process cannot fail the way those stores fail,
so a fixture green is not evidence that the bar is met.
"""
from __future__ import annotations

import json

import statistics
import time
from types import SimpleNamespace

import pytest

import nodelang.cell_change_history as change_history_module
from nodelang.cell_change_history import (
    _history_summary,
    bootstrap_change_history_protocol,
    commit_tracked_change,
    redo_last_change,
    undo_last_change,
)

# The accelerator is reached through the module so a build without it fails
# each court where the court makes its claim, not at import.
from nodelang.cell_protocols import CellBatch, relation_projection_scope
from nodelang.universal_application import _project_session_action_history
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    MatchBudgetExceeded,
)

HISTORY_ROOT = "memo:history"
BAR_SECONDS = 0.150


def _fixture(width=3, database_path=None):
    store = CellStore(database_path)
    protocol = bootstrap_change_history_protocol(
        store, prefix="memo:change-history-protocol"
    )
    batch = CellBatch(store)
    for root, atom in (
        ("memo:actor", b"Actor"),
        ("memo:session", b"Session"),
        ("memo:operation:set", b"Set"),
        ("memo:authority:set", b"Set value"),
    ):
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom))
    for index in range(width):
        batch.add(Cell(
            "memo:value:%d" % index, NULL_CELL_ID, NULL_CELL_ID, b"0"
        ))
    batch.relation((), relation_id=HISTORY_ROOT)
    batch.commit()
    return store, protocol


def _set_values(store, protocol, value, width=3):
    snapshot = store.snapshot()
    replace = []
    for index in range(width):
        current = snapshot.cells["memo:value:%d" % index]
        replace.append(Cell(
            current.id, current.link0, current.link1,
            ("%s-%d" % (value, index)).encode("ascii"),
        ))
    return commit_tracked_change(
        store,
        protocol,
        history_root=HISTORY_ROOT,
        actor_root="memo:actor",
        session_root="memo:session",
        operation_root="memo:operation:set",
        authority_root="memo:authority:set",
        scope_roots=tuple("memo:value:%d" % i for i in range(width)),
        replace=tuple(replace),
    )


def _registry(protocol):
    return SimpleNamespace(
        change_history_protocol=protocol,
        application_http_route_roots={},
    )


def _view_session():
    return SimpleNamespace(action_history_root=HISTORY_ROOT)


def _projection(store, protocol, *, memo_store=None):
    with relation_projection_scope():
        return _project_session_action_history(
            store.dense_snapshot(), _registry(protocol), _view_session(),
            store=memo_store,
        )


def _grown(transactions=120, width=3, database_path=None):
    store, protocol = _fixture(width, database_path)
    for index in range(transactions):
        _set_values(store, protocol, "v%d" % index, width)
    return store, protocol


def test_the_memo_projects_exactly_what_the_walk_projects():
    store, protocol = _grown(transactions=40)
    walked = _projection(store, protocol)
    memoised = _projection(store, protocol, memo_store=store)
    reused = _projection(store, protocol, memo_store=store)
    assert walked == memoised == reused
    memo = change_history_module.change_transaction_header_memo(store)
    assert len(memo) == len(walked["transactions"]) == 40
    assert memo.hits >= 40


def test_deleting_the_accelerator_changes_nothing_but_time():
    store, protocol = _grown(transactions=30)
    warm = _projection(store, protocol, memo_store=store)
    assert len(change_history_module.change_transaction_header_memo(store)) == 30
    change_history_module.forget_change_transaction_header_memo(store)
    rebuilt = _projection(store, protocol, memo_store=store)
    assert rebuilt == warm
    assert _projection(store, protocol) == warm


def test_undo_and_redo_keep_the_derived_state_under_the_memo():
    store, protocol = _grown(transactions=6)
    assert _projection(store, protocol, memo_store=store)["can_undo"] is True
    undo_last_change(
        store, protocol, history_root=HISTORY_ROOT, actor_root="memo:actor",
        session_root="memo:session", operation_root="memo:operation:set",
    )
    assert _projection(store, protocol, memo_store=store) == _projection(
        store, protocol
    )
    redo_last_change(
        store, protocol, history_root=HISTORY_ROOT, actor_root="memo:actor",
        session_root="memo:session", operation_root="memo:operation:set",
    )
    assert _projection(store, protocol, memo_store=store) == _projection(
        store, protocol
    )


def test_the_memo_is_not_consulted_when_the_store_advanced():
    store, protocol = _grown(transactions=8)
    honest = _projection(store, protocol)
    _projection(store, protocol, memo_store=store)
    memo = change_history_module.change_transaction_header_memo(store)
    transaction_root = honest["transactions"][0]["root"]
    poisoned = memo._entries[transaction_root]
    header_type = type(poisoned.header)
    memo._entries[transaction_root] = type(poisoned)(
        header_type(*(
            "POISON" if field == "timestamp" else getattr(
                poisoned.header, field
            )
            for field in header_type.__slots__
        )),
        poisoned.steps,
    )
    # The memo really is the thing under test: while nothing advanced, the
    # projection reads it.
    assert _projection(store, protocol, memo_store=store)[
        "transactions"
    ][0]["timestamp"] == "POISON"
    # Advance the Store over the Cells of that transaction.
    stamp = store.read(transaction_root + ":record")
    record = json.loads(stamp.atom)
    record["timestamp"] = "2026-09-18T00:00:00+00:00"
    store.commit(store.revision, replace=[Cell(
        stamp.id, stamp.link0, stamp.link1,
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii"),
    )])
    advanced = _projection(store, protocol)
    assert _projection(store, protocol, memo_store=store) == advanced
    assert advanced["transactions"][0]["timestamp"] != "POISON"


def test_an_unaccountable_advance_empties_the_memo():
    store, protocol = _grown(transactions=5)
    _projection(store, protocol, memo_store=store)
    memo = change_history_module.change_transaction_header_memo(store)
    assert len(memo) == 5
    memo.bind(store, SimpleNamespace(revision=0, cells={}))
    assert len(memo) == 0
    assert _projection(store, protocol, memo_store=store) == _projection(
        store, protocol
    )


def test_a_reused_header_refuses_the_budget_the_walk_would_have_refused():
    store, protocol = _grown(transactions=4, width=4)
    snapshot = store.dense_snapshot()
    memo = change_history_module.ChangeTransactionHeaderMemo()
    memo.bind(store, snapshot)
    with relation_projection_scope():
        state, headers = _history_summary(
            snapshot, protocol, HISTORY_ROOT, memo=memo
        )
    transaction_root = next(iter(headers))
    steps = memo._entries[transaction_root].steps
    with pytest.raises(MatchBudgetExceeded):
        change_history_module._read_change_transaction_header(
            snapshot, protocol, transaction_root, budget=steps - 1, memo=memo,
        )
    with pytest.raises(MatchBudgetExceeded):
        change_history_module._read_change_transaction_header(
            snapshot, protocol, transaction_root, budget=steps - 1,
        )


def test_the_memo_cuts_the_fixture_walk_while_both_real_stores_miss_the_bar(tmp_path):
    """What this court measures: the memo's own cost on a 300x30 tmp fixture.

    It does NOT measure SPEC 11.14 and it does not assert the 0.150 s bar. That
    bar is missed on every real store this accelerator was run against: warm
    median 3891.3 ms on the founder store (7.08 GB, revision 112817) and 218.3
    ms on the grown store, 25.9x and 1.46x over, independently re-measured in
    verification journal wf_430e9985-8f2 (2026-09-18) where the builder's own
    run of the founder store reported 4280.4 ms. Asserting the bar against a
    fixture built fresh in this process would report a pass for a claim the
    real stores refuse, so this court asserts only the ratio a fixture can
    honestly carry: the warm read costs a small fraction of the walk it
    replaces. Journal-backed on purpose -- the founder cost is Cell reads that
    miss the head reader cache and reach sqlite, which an in-memory Store never
    pays -- but journal-backed is still not the founder store.
    """
    store, protocol = _grown(
        transactions=300, width=30,
        database_path=str(tmp_path / "court.sqlite3"),
    )
    try:
        started = time.perf_counter()
        walked = _projection(store, protocol)
        walk_seconds = time.perf_counter() - started
        started = time.perf_counter()
        first = _projection(store, protocol, memo_store=store)
        cold = time.perf_counter() - started
        warm = []
        for _ in range(6):
            started = time.perf_counter()
            again = _projection(store, protocol, memo_store=store)
            warm.append(time.perf_counter() - started)
            assert again == first == walked
        median = statistics.median(warm)
        assert len(walked["transactions"]) == 300
        assert median * 20 <= walk_seconds, (
            "the memo did not pay for itself on the fixture: warm median "
            "%.4fs against the same projection unaccelerated %.4fs (cold "
            "%.4fs). The SPEC 11.14 bar of %.3fs is NOT under test here and "
            "is not met on either real store."
            % (median, walk_seconds, cold, BAR_SECONDS)
        )
    finally:
        store.close()




class _RecordingCells:
    """A snapshot mapping that separates content reads from existence probes."""

    def __init__(self, cells):
        self._cells = cells
        self.fetched = []
        self.probed = []

    def __getitem__(self, key):
        self.fetched.append(key)
        return self._cells[key]

    def get(self, key, default=None):
        self.fetched.append(key)
        return self._cells.get(key, default)

    def __contains__(self, key):
        self.probed.append(key)
        return key in self._cells

    def __iter__(self):
        return iter(self._cells)

    def __len__(self):
        return len(self._cells)


def test_a_header_reads_content_only_under_its_own_transaction():
    """Why one commit can retire exactly the transactions it wrote.

    The memo drops an entry when a revision writes its identity or anything
    under it, so the dependency is measured rather than asserted. A header
    reads Cell CONTENT only under its own identity. It also probes that the
    role and participant of each incidence exist, which is why the next
    court holds the Store to never taking a Cell away as it advances.
    """
    store, protocol = _grown(transactions=3, width=5)
    snapshot = store.dense_snapshot()
    roots = [row["root"] for row in _projection(store, protocol)["transactions"]]
    assert len(roots) == 3
    for transaction_root in roots:
        recording = _RecordingCells(snapshot.cells)
        watched = type(snapshot)(snapshot.revision, recording)
        change_history_module._read_change_transaction(
            watched, protocol, transaction_root, budget=10_000,
            summary_only=True, protocol_verified=True,
        )
        assert recording.fetched
        outside = sorted({
            cell_id for cell_id in recording.fetched
            if cell_id != transaction_root
            and not cell_id.startswith(transaction_root + ":")
        })
        assert outside == [], outside
        assert recording.probed


def test_a_Store_that_advances_never_takes_a_Cell_away():
    """The existence a reused header already proved cannot be revoked forward.

    commit creates and replaces; it has no removal. A Cell leaves the head
    only by stepping to a lower revision, and a memo bound to a mapping it
    can no longer account for is emptied before it answers anything.
    """
    store, protocol = _grown(transactions=4)
    before = set(store.dense_snapshot().cells)
    _set_values(store, protocol, "after")
    current = store.dense_snapshot().cells
    assert before.issubset(set(current))
    import inspect
    signature = inspect.signature(type(store).commit)
    assert set(signature.parameters) == {
        "self", "expected_revision", "create", "replace", "precommit_guard",
    }
