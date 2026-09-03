"""A head audit costs its own change, not the whole graph (SPEC 3.1.6).

Opening the founder's graph after a single gesture cost 121 seconds, and
115.5 of them were one step of the head audit: the step lifted every one
of 5.79 million head rows into a trie so that 291 changed cells could be
reverted. The head IS read on demand -- but the journal handed the store
a MappingProxyType wrapped AROUND the lazy head, and every consumer that
asks "is this lazy?" was answered no.

These courts hold the two facts that make a step cheap: the store opens
onto the lazy head itself, and stepping down from it stays lazy. Both are
invisible in a diff -- a proxy is a correct read-only mapping, and a trie
is a correct map -- so they are asserted rather than assumed.
"""
import hashlib
from pathlib import Path

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority_runtime import open_current_authority
from nodelang.universal_cell import _LazyHeadCellMap


PROVIDER = MemorySigningKeyProvider(
    "archhub.unified.bootstrap", b"lazy-head-step" + b"0" * 18,
)
GRAND_MAP = (
    b'[{"key":"k","title":"K","nodes":[{"id":"a","cat":"note","title":"A",'
    b'"sub":"h","status":"vision","params":[],"evidence_ref":"",'
    b'"authority_source":"c"}],"wires":[],"cross":[]}]'
)


@pytest.fixture(scope="module")
def reopened(tmp_path_factory):
    root = tmp_path_factory.mktemp("lazy-head")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    built = provision_clean_runtime(
        root,
        PROVIDER,
        WindowsDpapiCallerKeyStore(root / "callers.dpapi.json"),
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=GRAND_MAP,
        grand_map_sha256=hashlib.sha256(GRAND_MAP).hexdigest(),
    )
    built.location.authority.store.close()
    location = open_current_authority(root, PROVIDER)
    yield location
    location.authority.store.close()


def test_a_reopened_store_holds_the_lazy_head_itself(reopened):
    cells = reopened.authority.store.snapshot().cells
    assert isinstance(cells, _LazyHeadCellMap), type(cells).__name__


def test_stepping_below_the_head_stays_lazy(reopened):
    store = reopened.authority.store
    below = store.at(store.revision - 1)
    assert below.revision == store.revision - 1
    assert isinstance(below.cells, _LazyHeadCellMap), type(below.cells).__name__


def test_a_step_costs_far_less_than_reading_the_revision_whole(reopened):
    """The cost of a step is its change; the cost it replaces is the graph.

    Counted in sqlite virtual-machine steps, which is the work the engine
    actually does rather than a wall clock that depends on the machine.
    """
    store = reopened.authority.store
    connection = store._journal._connection

    def cost(work):
        counted = {"steps": 0}

        def tick():
            counted["steps"] += 1
            return 0

        connection.set_progress_handler(tick, 1000)
        try:
            work()
        finally:
            connection.set_progress_handler(None, 0)
        return counted["steps"]

    target = store.revision - 1
    store._historical_snapshots.clear()
    stepped = cost(lambda: store.at(target))
    whole = cost(lambda: store._history_reader.snapshot_at(target))
    assert stepped * 4 < whole, (stepped, whole)


def test_the_stepped_snapshot_answers_the_same_cells_as_a_full_read(reopened):
    """Laziness must not change WHAT a revision says, only what it costs."""
    store = reopened.authority.store
    target = store.revision - 1
    stepped = store.at(target)
    full = store._history_reader.snapshot_at(target)
    assert stepped.revision == full.revision
    assert set(stepped.cells) == set(full.cells)
    for cell_id, cell in full.cells.items():
        assert stepped.cells[cell_id] == cell
