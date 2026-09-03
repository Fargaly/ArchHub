"""A wire is a member of the scope, not decoration (SPEC 3.2, 11.14).

The founder's words were "WIRES LOOK LIKE SHELLS WITH NO USE", and they
were: no wire on the canvas could be picked, so none could be read and
none could be removed. Four rules had each been written for cards alone
-- what a focus may name, what a scope shows, what the inspector answers
for, and what a scope will release -- and a relation fell through all
four.

These courts hold the rule that fixes them: what a scope SHOWS is its
cards and the wires between them, and either kind can be selected, read
and released.
"""
import hashlib
import uuid
from pathlib import Path

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_browser_authority import (
    issue_clean_browser_session,
    open_clean_browser_authority,
    revise_clean_browser_focus,
)
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_application_lens import project_unified_scope
from nodelang.unified_authority import (
    InvalidCell,
    read_scope_level,
    remove_composition_member,
)


PROVIDER = MemorySigningKeyProvider(
    "archhub.unified.bootstrap", b"wire-is-a-member" + b"0" * 16,
)
GRAND_MAP = (
    b'[{"key":"a","title":"Domain A","nodes":['
    b'{"id":"a1","cat":"note","title":"A one","sub":"h","status":"vision",'
    b'"params":[],"evidence_ref":"","authority_source":"c"},'
    b'{"id":"a2","cat":"note","title":"A two","sub":"h","status":"vision",'
    b'"params":[],"evidence_ref":"","authority_source":"c"}],'
    b'"wires":[["a1","a2"]],"cross":[]}]'
)


@pytest.fixture
def runtime(tmp_path):
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    built = provision_clean_runtime(
        tmp_path,
        PROVIDER,
        WindowsDpapiCallerKeyStore(tmp_path / "callers.dpapi.json"),
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=GRAND_MAP,
        grand_map_sha256=hashlib.sha256(GRAND_MAP).hexdigest(),
    )
    yield built
    built.location.authority.store.close()


def _domain_with_a_wire(built):
    """The first scope below the map that holds a relation."""
    authority, caller = built.location.authority, built.caller
    door = built.grand_map.root_id
    level = read_scope_level(
        authority, door, scope_root=door, caller=caller,
    )
    for child in level.composition_roots:
        inner = read_scope_level(
            authority, child, scope_root=child, caller=caller,
        )
        if inner.relations:
            return child, next(iter(inner.relations))
    raise AssertionError("the fixture map declares no wire")


def _view(built):
    authority, caller = built.location.authority, built.caller
    browser = open_clean_browser_authority(authority, caller=caller)
    issued = issue_clean_browser_session(
        authority,
        browser,
        token="t" * 24,
        csrf_token="c" * 24,
        lifetime_seconds=600.0,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    return browser, issued


def test_a_scope_admits_a_wire_as_a_selection(runtime):
    """A line you cannot pick is a line you cannot read or remove."""
    authority, caller = runtime.location.authority, runtime.caller
    scope, wire = _domain_with_a_wire(runtime)
    browser, issued = _view(runtime)
    revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=scope,
        selected_roots=[wire],
        primary_root=wire,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )


def test_a_scope_releases_a_wire_the_same_way_it_releases_a_card(runtime):
    authority, caller = runtime.location.authority, runtime.caller
    scope, wire = _domain_with_a_wire(runtime)
    remove_composition_member(
        authority, scope, wire, caller=caller, command_id=str(uuid.uuid4()),
    )
    level = read_scope_level(
        authority, scope, scope_root=scope, caller=caller,
    )
    assert wire not in level.relations


def test_a_selection_the_scope_contradicts_is_dropped_not_fatal(runtime):
    """Deleting the selected card must not take the whole canvas down.

    The projection refused any focus naming a root the scope no longer
    held, so releasing a selected member made every later read fail --
    the founder's graph became unreadable because their session still
    named a card they had just removed.
    """
    authority, caller = runtime.location.authority, runtime.caller
    door = runtime.grand_map.root_id
    level = read_scope_level(
        authority, door, scope_root=door, caller=caller,
    )
    victim = level.composition_roots[0]
    browser, issued = _view(runtime)
    revise_clean_browser_focus(
        authority,
        browser,
        issued.root_id,
        scope_root=door,
        selected_roots=[victim],
        primary_root=victim,
        caller=caller,
        command_id=str(uuid.uuid4()),
    )
    remove_composition_member(
        authority, door, victim, caller=caller, command_id=str(uuid.uuid4()),
    )
    # The view the lens reads is the caller's own session, which is what
    # the browser session was issued against -- the same pair the server
    # uses (focus written for the browser session, projection read for the
    # view session).
    lens = project_unified_scope(
        authority, door, caller=caller, view_root=caller.session_root,
    )
    assert victim not in lens.selected_roots
    assert lens.selected_root != victim
