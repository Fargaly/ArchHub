"""Court A: BABOOM's next-launch startup choice is one owner-held graph value.

Founder approval (2026-09-15): the choice takes effect at the next launch, is
owner-only, is anchored to app:agent-body:baboom, and fails closed when it
cannot be read. It is written through the admitted interaction route (or the
one writer behind it), never into canvas undo history, and the launcher reads
it through the same decoder as the projection.

RED-first: against source without read_universal_baboom_startup,
set_universal_baboom_startup, configuration.baboom_startup, the
baboom-startup control and the launcher gate, every case below fails.
"""
from __future__ import annotations

from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import uuid

import pytest

import nodelang.universal_application as universal_application_module

from nodelang.application_server import ApplicationServer
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_lifecycle import append_wip_revision
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    move_universal_root,
    project_universal_canvas,
    provision_universal_view_session,
    restore_universal_application,
    undo_universal_change,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell
from tests_replica.test_application_server_governance import (
    _interaction_request,
    _json,
)
from tests_replica.test_baboom_startup_lifecycle import launcher_names

BODY = "app:agent-body:baboom"
CONTROL_RELATION = "app:agent-control:baboom"
CONTRACT = "app:contract:baboom-startup:v1"
CONTRACT_TEXT = b"BABOOM startup at next launch: on or off"
OPERATION = "app:appearance-operation:baboom-startup:v1"
SUBMITTED_VALUE = "app:event-fact:submitted-value:v1"
UNREADABLE_REASON = (
    "BABOOM did not start because its Settings value is unreadable; "
    "no action was performed."
)
DEFAULT_READ = {
    "value": "on", "source": "default", "revision": None,
    "actor": None, "asset": None, "binding": None,
}


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"b" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"s" * 32)
    return provider


def _roots(registry):
    """Restate the contract's root derivation so source drift is caught."""
    owner = registry.authorization.subject_root
    view_root = registry.view_sessions[owner].root_id
    token = uuid.uuid5(uuid.NAMESPACE_URL, view_root + "\0" + BODY).hex
    return (
        "assembly-instance:baboom-startup-" + token,
        "app:baboom-startup-binding:" + token,
    )


def _read(store, registry):
    return universal_application_module.read_universal_baboom_startup(
        store.snapshot(), registry
    )


def _set(store, registry, value, **kwargs):
    return universal_application_module.set_universal_baboom_startup(
        store, registry, value, **kwargs
    )


def _control_members(store):
    return tuple(
        (member.role_id, member.participant_id)
        for member in read_relation(
            store.snapshot(), CONTROL_RELATION, budget=100_000
        )
    )


def _owner_projection(registry, **changes):
    owner = registry.authorization.subject_root
    return {
        "value": "on",
        "source": "default",
        "revision": None,
        "actor": None,
        "available": True,
        "control": universal_application_module._appearance_control_root(
            owner, BODY, OPERATION
        ),
        "event_fact_input": SUBMITTED_VALUE,
        "effect": "next-launch",
        "error": None,
        **changes,
    }


def _startup_request(canvas, value):
    startup = canvas["configuration"]["baboom_startup"]
    request = _interaction_request(canvas, startup["control"])
    request["event_facts"] = [
        {"input": startup["event_fact_input"], "value": value}
    ]
    return request


def _launcher_server(store, registry):
    return SimpleNamespace(
        mutation_lock=threading.RLock(),
        universal_store=store,
        universal_registry=registry,
    )


def test_a_fresh_graph_reads_default_on_without_a_write_or_a_cell():
    store, registry = build_universal_application(resolve_map_path())
    asset, binding = _roots(registry)
    before = store.revision
    assert _read(store, registry) == DEFAULT_READ
    assert store.revision == before
    cells = store.snapshot().cells
    assert asset not in cells and binding not in cells
    # Restore finds the theme asset by this prefix (universal_application.py:14017-14021).
    assert not asset.startswith("assembly-instance:view-settings-")
    view_root = registry.view_sessions[
        registry.authorization.subject_root
    ].root_id
    assert universal_application_module._baboom_startup_roots(view_root) == (
        asset, binding,
    )
    projection = project_universal_canvas(store, registry)
    assert projection["configuration"]["baboom_startup"] == _owner_projection(
        registry
    )


def test_owner_turns_startup_off_through_the_interaction_route_and_restart_keeps_it(
    tmp_path,
):
    state_path = tmp_path / "baboom-startup-http.sqlite3"
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(state_path), key_provider=provider
    )
    owner = registry.authorization.subject_root
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    try:
        token = server.browser_session_token
        status, canvas = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        assert canvas["authorization"]["subject"] == owner
        startup = canvas["configuration"]["baboom_startup"]
        assert startup == _owner_projection(registry)
        binding_row = next(
            row for row in canvas["interaction_projection"]["bindings"]
            if row["control"] == startup["control"]
        )
        assert [spec["input"] for spec in binding_row["event_facts"]] == [
            SUBMITTED_VALUE
        ]
        controls_before = _control_members(server.universal_store)
        stale_request = _startup_request(canvas, "on")

        status, changed = _json(
            server.url, "/api/universal/interaction",
            _startup_request(canvas, "off"), token=token,
        )
        assert status == 200, changed
        state = changed["configuration_state"]["baboom_startup"]
        assert state["value"] == "off" and state["source"] == "graph"
        assert state["actor"] == owner and isinstance(state["revision"], str)
        written = state["revision"]
        assert _read(server.universal_store, registry)["revision"] == written
        assert _control_members(server.universal_store) == controls_before

        status, fresh = _json(server.url, "/api/universal/canvas", token=token)
        assert status == 200
        assert fresh["configuration"]["baboom_startup"]["value"] == "off"
        before = server.universal_store.revision
        status, refused = _json(
            server.url, "/api/universal/interaction",
            _startup_request(fresh, "off"), token=token,
        )
        assert status == 400, refused
        assert "already off" in refused["error"]
        assert server.universal_store.revision == before

        # Cut from the projection read before the write: refused, no write.
        status, stale = _json(
            server.url, "/api/universal/interaction", stale_request, token=token,
        )
        assert status in (400, 409), stale
        assert server.universal_store.revision == before
        assert _read(server.universal_store, registry)["revision"] == written
    finally:
        server.close()

    reopened = CellStore(state_path)
    try:
        reopened, restored = restore_universal_application(
            resolve_map_path(), reopened, key_provider=provider
        )
        current = universal_application_module.read_universal_baboom_startup(
            reopened.snapshot(), restored
        )
        assert current["value"] == "off" and current["source"] == "graph"
        assert current["revision"] == written
        assert current["actor"] == restored.authorization.subject_root == owner
        projection = project_universal_canvas(reopened, restored)
        assert projection["configuration"]["baboom_startup"]["value"] == "off"
        # The launcher reads the same decoder from the restored registry.
        choose = launcher_names(
            "_baboom_startup_choice",
            server=_launcher_server(reopened, restored),
            _baboom_stop=threading.Event(),
        )["_baboom_startup_choice"]
        assert choose() == "off"
    finally:
        reopened.close()


def test_startup_value_is_graph_held_outside_undo_and_restores_without_a_write(
    tmp_path,
):
    path = tmp_path / "baboom-startup-graph.sqlite3"
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    owner = registry.authorization.subject_root
    view_root = registry.view_sessions[owner].root_id
    asset, binding = _roots(registry)
    controls_before = _control_members(store)

    before = store.revision
    for refused in ("on", "enabled"):
        with pytest.raises(InvalidCell):
            _set(store, registry, refused)
    with pytest.raises(InvalidCell):
        _set(store, registry, "off", base_revision_root="app:no-such-revision")
    assert store.revision == before

    root = registry.visible_roots[0]
    x_root = registry.position_properties[root]["position_x"].value_root
    original_x = store.read(x_root).atom
    move_universal_root(store, registry, root, 431.0, 287.0)

    written = _set(store, registry, "off")
    current = _read(store, registry)
    assert current == {
        "value": "off", "source": "graph", "revision": written,
        "actor": owner, "asset": asset, "binding": binding,
    }
    snapshot = store.snapshot()
    assert snapshot.cells[CONTRACT] == Cell(
        CONTRACT, NULL_CELL_ID, NULL_CELL_ID, CONTRACT_TEXT
    )
    members = read_relation(snapshot, binding, budget=16)
    assert len(members) == 5
    assert {member.participant_id for member in members} == {
        BODY, asset, view_root, owner, CONTRACT,
    }
    application_members = {
        member.participant_id
        for member in read_relation(
            snapshot, registry.application_root, budget=1_000_000
        )
    }
    assert {asset, binding, CONTRACT} <= application_members
    assert _control_members(store) == controls_before

    # Canvas undo compensates the move; it never flips the startup setting.
    undo_universal_change(store, registry)
    assert store.read(x_root).atom == original_x
    assert _read(store, registry) == current

    turned_on = _set(store, registry, "on", base_revision_root=written)
    assert _read(store, registry)["revision"] == turned_on
    before = store.revision
    with pytest.raises(InvalidCell, match="refresh"):
        _set(store, registry, "off", base_revision_root=written)
    with pytest.raises(InvalidCell):
        _set(store, registry, "on", base_revision_root=turned_on)
    assert store.revision == before
    expected_revision, expected = store.revision, _read(store, registry)
    assert expected["value"] == "on" and expected["actor"] == owner
    store.close()

    reopened = CellStore(path)
    try:
        reopened, restored = restore_universal_application(
            resolve_map_path(), reopened, key_provider=provider
        )
        assert reopened.revision == expected_revision
        assert universal_application_module.read_universal_baboom_startup(
            reopened.snapshot(), restored
        ) == expected
        assert reopened.revision == expected_revision
    finally:
        reopened.close()


def test_a_non_owner_sees_the_setting_without_a_control_and_cannot_change_it():
    store, registry = build_universal_application(resolve_map_path())
    member_root = "test:baboom-startup:member"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Member browser"),
    ))
    provision_universal_view_session(
        store, registry, member_root, visible_roots=(registry.visible_roots[0],)
    )
    authority = registry.authorization
    member_context = authority.broker.mint_authenticated_context(
        member_root,
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=120,
    )
    before = store.revision
    with pytest.raises(AuthorizationDenied):
        _set(store, registry, "off", authentication_context=member_context)
    assert store.revision == before

    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    try:
        status, owner_canvas = _json(
            server.url, "/api/universal/canvas",
            token=server.browser_session_token,
        )
        assert status == 200
        forged = _startup_request(owner_canvas, "off")
        member_token, _csrf = server.issue_browser_session(member_context)
        status, member_canvas = _json(
            server.url, "/api/universal/canvas", token=member_token
        )
        assert status == 200
        assert member_canvas["authorization"]["subject"] == member_root
        startup = member_canvas["configuration"]["baboom_startup"]
        assert startup["value"] == "on" and startup["source"] == "default"
        assert startup["available"] is False
        assert startup["control"] is None
        assert startup["event_fact_input"] is None
        assert all(
            row["control"] != forged["control"]
            for row in member_canvas["interaction_projection"]["bindings"]
        )
        forged["revision"] = member_canvas["interaction_projection"]["revision"]
        before = server.universal_store.revision
        status, refused = _json(
            server.url, "/api/universal/interaction", forged, token=member_token
        )
        assert status in (400, 403), refused
        assert server.universal_store.revision == before
        assert _read(server.universal_store, registry) == DEFAULT_READ
    finally:
        server.close()


def test_a_malformed_startup_value_is_unreadable_everywhere_and_baboom_does_not_start(
    monkeypatch, capsys,
):
    store, registry = build_universal_application(resolve_map_path())
    owner = registry.authorization.subject_root
    asset, _binding = _roots(registry)
    written = _set(store, registry, "off")
    append_wip_revision(
        store,
        registry.assembly_protocol,
        registry.standard_library.lifecycle_protocol,
        asset,
        content=b"enabled",
        actor_root=owner,
        base_revision_root=written,
        reason="court: malformed BABOOM startup value",
    )
    with pytest.raises(InvalidCell, match="value is invalid"):
        _read(store, registry)
    assert project_universal_canvas(store, registry)["configuration"][
        "baboom_startup"
    ] == {
        "value": None, "source": "unreadable", "revision": None,
        "actor": None, "available": False, "control": None,
        "event_fact_input": None, "effect": "next-launch",
        "error": "InvalidCell",
    }
    before = store.revision
    with pytest.raises(InvalidCell):
        _set(store, registry, "on", base_revision_root=written)
    assert store.revision == before

    monkeypatch.setitem(sys.modules, "nodelang.baboom_attach", SimpleNamespace(
        prepare_baboom_host=lambda *args, **kwargs: pytest.fail(
            "BABOOM host prepared from an unreadable startup setting"
        ),
    ))
    ns = launcher_names(
        "_baboom_startup_choice", "_keep_attaching",
        server=_launcher_server(store, registry),
        _baboom_stop=threading.Event(), _baboom_off_reason=None,
        _baboom_attachment=SimpleNamespace(
            pending_host=None,
            ready=SimpleNamespace(emit=lambda host: pytest.fail("BABOOM host emitted")),
        ),
        state_dir=Path("unused"), descriptor_path=Path("unused"),
        machine_key_provider=object(),
    )
    ns["_keep_attaching"]()
    assert ns["_baboom_off_reason"] == UNREADABLE_REASON
    assert (
        "  BABOOM     : not started; startup setting unreadable (InvalidCell)"
        in capsys.readouterr().out
    )
