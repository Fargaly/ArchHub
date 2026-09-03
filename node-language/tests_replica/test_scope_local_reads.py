"""A screen costs what it shows, not what the graph holds (SPEC 11.14).

Three reads on the path to one canvas each cost the whole graph:

  * warming a scope's region followed links with no bound, so opening the
    map reached all 5.79 million cells -- 25.2s per scope entry;
  * the published catalogue was read definition by definition on every
    projection, because every gesture commits and the memo was keyed on
    the revision -- 24.8s per entry;
  * the interaction set was derived for all 318 scopes (31,480 bindings,
    1,290,811 cells) at start, to serve the one scope on screen.

Each is held here by the shape of the read rather than by a stopwatch,
so the courts stay true on a machine of any speed.
"""
import hashlib
import uuid
from pathlib import Path

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_browser_authority import (
    issue_clean_browser_session, open_clean_browser_authority,
)
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.clean_scope_interactions import (
    _binding_specs, derive_clean_scope_interactions,
)
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_application_lens import _catalogue, _DEFINITION_MEMOS
from nodelang.unified_authority_runtime import open_current_authority


PROVIDER = MemorySigningKeyProvider(
    "archhub.unified.bootstrap", b"scope-local-reads" + b"0" * 15,
)
GRAND_MAP = (
    b'[{"key":"a","title":"Domain A","nodes":['
    b'{"id":"a1","cat":"note","title":"A one","sub":"h","status":"vision",'
    b'"params":[],"evidence_ref":"","authority_source":"c"},'
    b'{"id":"a2","cat":"note","title":"A two","sub":"h","status":"vision",'
    b'"params":[],"evidence_ref":"","authority_source":"c"}],'
    b'"wires":[["a1","a2"]],"cross":[]},'
    b'{"key":"b","title":"Domain B","nodes":['
    b'{"id":"b1","cat":"note","title":"B one","sub":"h","status":"vision",'
    b'"params":[],"evidence_ref":"","authority_source":"c"}],'
    b'"wires":[],"cross":[]}]'
)


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    root = tmp_path_factory.mktemp("scope-local")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    built = provision_clean_runtime(
        root,
        PROVIDER,
        keys,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=GRAND_MAP,
        grand_map_sha256=hashlib.sha256(GRAND_MAP).hexdigest(),
    )
    built.location.authority.store.close()
    location = open_current_authority(root, PROVIDER)
    caller = WindowsDpapiCallerKeyStore(
        root / "callers.dpapi.json"
    ).bind_bootstrap(location.authority, "founder.bootstrap")
    browser = open_clean_browser_authority(location.authority, caller=caller)
    yield location.authority, browser, caller, built.grand_map.root_id
    location.authority.store.close()


def test_warming_a_region_is_bounded_by_depth_not_by_the_graph(runtime):
    """An unbounded link walk from the map root IS the whole graph."""
    authority = runtime[0]
    cells = authority.store.snapshot().cells
    warm = getattr(cells, "prefetch_region", None)
    if warm is None:
        pytest.skip("this store does not read its head on demand")
    root = authority.manifest.application_root
    shallow = warm(root, 400_000, 1)
    deep = warm(root, 400_000, 64)
    assert shallow < deep, (shallow, deep)
    assert deep <= len(cells)


def test_a_commit_that_touches_nothing_read_keeps_the_catalogue(runtime):
    """Every gesture commits, so a revision-keyed memo is no memo at all."""
    authority, browser, caller, _door = runtime
    first = _catalogue(authority, caller)
    memos = dict(_DEFINITION_MEMOS[authority.store])
    assert memos, "the catalogue read nothing to remember"
    before = authority.store.revision
    issue_clean_browser_session(
        authority,
        browser,
        token="t" * 24,
        csrf_token="c" * 24,
        lifetime_seconds=600.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    assert authority.store.revision > before
    read_definitions = []
    import nodelang.unified_application_lens as lens
    original = lens.read_definition

    def counted(*args, **kwargs):
        read_definitions.append(args[1] if len(args) > 1 else None)
        return original(*args, **kwargs)

    lens.read_definition = counted
    try:
        again = _catalogue(authority, caller)
    finally:
        lens.read_definition = original
    assert [item.root_id for item in again] == [item.root_id for item in first]
    assert read_definitions == [], read_definitions


def test_deriving_one_scope_is_not_deriving_the_tree(runtime):
    """What the canvas can act on is the scope it stands in."""
    authority, browser, caller, door = runtime
    whole = _binding_specs(authority, door, caller)
    local = _binding_specs(authority, door, caller, roots=(door,), depth=1)
    assert set(local) < set(whole)
    assert {spec[0] for spec in local} == {door}
    assert len({spec[0] for spec in whole}) > 1


def test_the_scopes_derived_locally_answer_exactly_as_the_whole_tree_does(
    runtime,
):
    """A cheaper read must be the same read, not a different one."""
    authority, browser, caller, door = runtime
    whole, _cells = derive_clean_scope_interactions(
        authority, browser, door, caller=caller,
    )
    local, _local_cells = derive_clean_scope_interactions(
        authority, browser, door, caller=caller, roots=(door,), depth=1,
    )
    assert set(local.bindings) == {door}
    assert local.event_root == whole.event_root
    for control_root, binding in local.bindings[door].items():
        held = whole.bindings[door][control_root]
        assert binding.target_root == held.target_root
        assert binding.interaction_root == held.interaction_root
