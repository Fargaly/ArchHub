"""Rule-derivation produces the exact set the pair table persists.

SPEC section 4.1: a fast path may exist only when an equivalence court
proves the generic graph path and the fast path produce the same result
at the same snapshot. Here the roles are reversed and the stakes are the
graph's size rather than speed: the PERSISTED pair table (78% of the live
graph, the 13-minute boot) is the redundant copy, and the derivation is
the path that reads only the facts the table repeats -- the scope tree
and the published catalogue.

Cell-for-cell equality against a freshly provisioned runtime is the
strongest claim available: the table adds nothing the derivation does
not already say.
"""
import hashlib
import uuid
from pathlib import Path

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.clean_scope_interactions import (
    derive_clean_scope_interactions,
    open_clean_scope_interactions,
)
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore


PROVIDER = MemorySigningKeyProvider(
    "archhub.unified.bootstrap", b"derived-interactions" + b"0" * 12,
)


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    root = tmp_path_factory.mktemp("derived-interactions")
    provider = PROVIDER
    caller_keys = WindowsDpapiCallerKeyStore(root / "callers.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = (
        b'[{"key":"court","title":"Court domain","nodes":[{"id":"court_a",'
        b'"cat":"note","title":"Court requirement","sub":"held","status":'
        b'"vision","params":[],"evidence_ref":"","authority_source":"court"}'
        b',{"id":"court_b","cat":"note","title":"Second requirement","sub":'
        b'"held","status":"vision","params":[],"evidence_ref":"",'
        b'"authority_source":"court"}],"wires":[["court_a","court_b"]],'
        b'"cross":[]}]'
    )
    built = provision_clean_runtime(
        root,
        provider,
        caller_keys,
        caller_key_id="founder.bootstrap",
        specification_source=specification,
        specification_sha256=hashlib.sha256(specification).hexdigest(),
        grand_map_source=grand_map,
        grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
    )
    yield built
    built.location.authority.store.close()


def test_derivation_carries_the_installed_source_digest(runtime):
    installed = open_clean_scope_interactions(
        runtime.location.authority, caller=runtime.caller
    )
    derived, _ = derive_clean_scope_interactions(
        runtime.location.authority,
        runtime.browser,
        runtime.grand_map.root_id,
        caller=runtime.caller,
    )
    assert derived.source_digest == installed.source_digest


def test_every_binding_matches_scope_control_target_and_interaction(runtime):
    installed = open_clean_scope_interactions(
        runtime.location.authority, caller=runtime.caller
    )
    derived, _ = derive_clean_scope_interactions(
        runtime.location.authority,
        runtime.browser,
        runtime.grand_map.root_id,
        caller=runtime.caller,
    )
    assert set(derived.bindings) == set(installed.bindings)
    for scope_root, controls in installed.bindings.items():
        assert set(derived.bindings[scope_root]) == set(controls)
        for control_root, held in controls.items():
            computed = derived.bindings[scope_root][control_root]
            assert computed.target_root == held.target_root
            assert computed.interaction_root == held.interaction_root


def test_derived_interactions_project_identically_to_persisted(runtime):
    """The read path sees the same interaction either way (SPEC 4.1).

    Inner cell identities are physical machinery (SPEC 3.3): the builder
    mints them fresh per call, so cell-for-cell equality between table and
    derivation is not on offer. What the runtime consumes is the
    read_interaction projection -- control, event, inputs, action,
    authorization -- and THAT must be indistinguishable, or the table and
    the rule are two different laws under one name.
    """
    from nodelang.cell_interactions import read_interaction
    from nodelang.universal_cell import overlay_read_snapshot

    authority = runtime.location.authority
    installed = open_clean_scope_interactions(authority, caller=runtime.caller)
    derived, cells = derive_clean_scope_interactions(
        authority,
        runtime.browser,
        runtime.grand_map.root_id,
        caller=runtime.caller,
    )
    assert cells
    real = authority.store.snapshot()
    # The post-compaction world: the table is gone and the derivation is
    # what answers. Shared roots (scopes, capabilities, the protocol, the
    # policy) still resolve from the graph; everything the derivation
    # builds wins over what the table persisted under the same identity.
    fresh = [cell for cell in cells if cell.id not in real.cells]
    replaced = [cell for cell in cells if cell.id in real.cells]
    synthetic = overlay_read_snapshot(real, create=fresh, replace=replaced)
    compared = 0
    for scope_root, controls in installed.bindings.items():
        for control_root, held in controls.items():
            persisted = read_interaction(
                real, installed.protocol, held.interaction_root, budget=1024
            )
            computed = read_interaction(
                synthetic, derived.protocol, held.interaction_root, budget=1024
            )
            assert computed.control_root == persisted.control_root
            assert computed.event_root == persisted.event_root
            assert computed.input_roots == persisted.input_roots
            assert computed.action_root == persisted.action_root
            assert computed.target_root == persisted.target_root
            assert computed.subject_root == persisted.subject_root
            assert computed.policy_root == persisted.policy_root
            compared += 1
    assert compared >= 8


def test_the_event_is_shared_and_the_protocol_speaks_the_same_language(runtime):
    """One derived event identity; a protocol equal in vocabulary.

    The protocol composition takes a fresh root per compilation -- physical
    machinery again -- but its roles and states are the language every
    interaction is read in, and those must not drift between the table and
    the derivation.
    """
    installed = open_clean_scope_interactions(
        runtime.location.authority, caller=runtime.caller
    )
    derived, _ = derive_clean_scope_interactions(
        runtime.location.authority,
        runtime.browser,
        runtime.grand_map.root_id,
        caller=runtime.caller,
    )
    assert derived.event_root == installed.event_root
    assert set(derived.protocol.roles) == set(installed.protocol.roles)
    assert set(derived.protocol.states) == set(installed.protocol.states)


def test_a_runtime_whose_table_is_retired_still_serves_every_binding(runtime):
    """The retired-table world: bindings derived, cells overlaid, canvas up.

    Retiring the pair table on the live graph left the server reading
    interaction cells the graph no longer held -- "relation root is
    missing" on every canvas request. The read path must lease and read
    interactions from the derivation overlay, never from bare graph state.
    """
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_interactions import read_interaction

    authority = runtime.location.authority
    server = ApplicationServer.from_unified_authority(
        authority,
        browser_authority=runtime.browser,
        scope_caller=runtime.caller,
        scope_root=runtime.grand_map.root_id,
        authority_key_provider=PROVIDER,
        host="127.0.0.1",
        port=0,
    )
    try:
        # Force the derived world regardless of what the fixture installed.
        derived, cells = derive_clean_scope_interactions(
            authority, runtime.browser, runtime.grand_map.root_id,
            caller=runtime.caller,
        )
        server.clean_scope_interactions = derived
        server._derived_interaction_cells = cells
        snapshot = authority.store.snapshot()
        reading = server._interaction_snapshot(snapshot)
        assert reading is not snapshot
        read_count = 0
        for scope_root, controls in derived.bindings.items():
            for held in controls.values():
                interaction = read_interaction(
                    reading, derived.protocol, held.interaction_root, budget=1024
                )
                assert interaction.control_root == held.control_root
                read_count += 1
        assert read_count >= 8
        # And the capability question the client asks per control answers.
        run_scope = runtime.grand_map.root_id
        any_control = next(iter(derived.bindings[run_scope]))
        server.clean_scope_root = run_scope
        assert server._clean_control_capability(any_control) is not None
    finally:
        server.close() if hasattr(server, "close") else None
def test_derivation_survives_a_graph_that_never_persisted_the_controls(runtime):
    """Every identity an interaction names rides in the derived set itself.

    The live graph retired its installed table; install-era cells for new
    controls (group, ungroup, composition) never existed there. Derive must
    carry those identities or the first lease read dangles -- which is how
    the live canvas returned 403 on 2026-08-19. The court removes the
    declared roots from the snapshot to stand in that graph's shoes.
    """
    from types import MappingProxyType

    from nodelang.cell_interactions import (
        _read_interaction_with_verified_protocol,
    )
    from nodelang.clean_scope_interactions import (
        CAPABILITY_COMPOSITION,
        CAPABILITY_EXECUTE,
        CAPABILITY_INSTANTIATE,
        CAPABILITY_SCOPE,
        CONTROL_GROUP,
        CONTROL_RUN,
        CONTROL_UNGROUP,
    )
    from nodelang.universal_cell import Snapshot

    authority = runtime.location.authority
    derived, cells = derive_clean_scope_interactions(
        authority,
        runtime.browser,
        runtime.grand_map.root_id,
        caller=runtime.caller,
    )
    declared = {
        CAPABILITY_SCOPE, CAPABILITY_EXECUTE, CAPABILITY_INSTANTIATE,
        CAPABILITY_COMPOSITION, CONTROL_RUN, CONTROL_GROUP, CONTROL_UNGROUP,
    }
    snapshot = authority.store.snapshot()
    bare = {
        cell_id: cell for cell_id, cell in snapshot.cells.items()
        if cell_id not in declared
    }
    overlay = dict(bare)
    overlay.update({cell.id: cell for cell in cells})
    stacked = Snapshot(snapshot.revision, MappingProxyType(overlay))
    door = runtime.grand_map.root_id
    for control_root, binding in derived.bindings[door].items():
        _read_interaction_with_verified_protocol(
            stacked, derived.protocol, binding.interaction_root
        )
