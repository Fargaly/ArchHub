"""Cell-native court for application, website, and canvas boundary interfaces.

This supersedes the old typed-runtime boundary-port test. A boundary is not a
``port`` field on a typed node; it is an inspectable Cell relation with exact
owner, contract, presentation, policy, lifecycle, and route/action authority.
"""
from __future__ import annotations

import pytest

from nodelang.cell_protocols import read_relation
from nodelang.cell_website import (
    PUBLIC_WEBSITE_ROUTES,
    read_universal_website,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
)
from nodelang.universal_cell import Cell, InvalidCell


def _replace_participant(store, incidence_root, participant_root):
    incidence = store.read(incidence_root)
    store.commit(store.revision, replace=(Cell(
        incidence.id, incidence.link0, participant_root, incidence.atom
    ),))


def _read_website(store, registry):
    return read_universal_website(
        store.snapshot(),
        registry.website.protocol,
        registry.website.root_id,
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        ui_protocol=registry.ui_protocol,
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
        published_lifecycle_root=(
            registry.standard_library.lifecycle_protocol.states["published"]
        ),
        read_action_root=registry.authorization.protocol.actions["read"],
    )


def test_website_boundary_is_exact_cell_authority_not_typed_port_fields():
    store, registry = build_universal_application(resolve_map_path())

    assert set(Cell.__dataclass_fields__) == {"id", "link0", "link1", "atom"}
    website = _read_website(store, registry)
    members = read_relation(store.snapshot(), website.root_id, budget=2_000)
    by_role = {
        role_name: {
            member.participant_id
            for member in members
            if member.role_id == registry.website.protocol.role(role_name)
        }
        for role_name in (
            "application",
            "interface",
            "action",
            "audience",
            "classification",
            "lifecycle-state",
            "purpose",
            "source",
        )
    }

    assert by_role == {
        "application": {registry.application_root},
        "interface": {registry.ui_protocol.root_id},
        "action": {registry.authorization.protocol.actions["read"]},
        "audience": {website.audience_root},
        "classification": {website.classification_root},
        "lifecycle-state": {website.lifecycle_root},
        "purpose": {website.purpose_root},
        "source": {"app:website:source:universal-lens-decision"},
    }
    assert set(website.route_roots) == set(PUBLIC_WEBSITE_ROUTES)
    assert set(website.cloud_route_roots) == set(PUBLIC_WEBSITE_ROUTES)
    assert all(root in store.snapshot().cells for root in (
        website.root_id,
        *website.route_roots.values(),
        *website.cloud_route_roots.values(),
    ))


def test_website_boundary_policy_tamper_fails_closed():
    store, registry = build_universal_application(resolve_map_path())
    members = read_relation(
        store.snapshot(), registry.website.root_id, budget=2_000
    )
    action_incidence = next(
        member.incidence_id
        for member in members
        if member.role_id == registry.website.protocol.role("action")
    )

    _replace_participant(
        store,
        action_incidence,
        registry.authorization.protocol.actions["edit"],
    )

    with pytest.raises(InvalidCell, match="website action authority drifted"):
        _read_website(store, registry)


def test_canvas_ports_are_real_interface_relations_with_exact_choices():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    snapshot = store.snapshot()
    ports = [
        port
        for node in projection["nodes"]
        for port in node["ports"]
        if port["mode"] == "connection"
    ]

    assert ports
    for port in ports:
        assert port["id"] in snapshot.cells
        members = read_relation(snapshot, port["id"], budget=100_000)
        assert {
            member.participant_id
            for member in members
            if member.role_id == registry.assembly_protocol.role(
                "interface-target"
            )
        } == {port["owner"]}
        assert {
            member.participant_id
            for member in members
            if member.role_id == registry.assembly_protocol.role(
                "interface-contract"
            )
        } == {port["contract_root"]}
        assert {
            member.participant_id
            for member in members
            if member.role_id == registry.assembly_protocol.role(
                "interface-presentation"
            )
        } == {port["presentation_root"]}

    connectable = [port for port in ports if port["connectable"]]
    assert connectable
    assert all(port["connect_control"] for port in connectable)
    for port in connectable:
        for choice in port["connect_choices"]:
            assert choice["id"] in snapshot.cells
            assert choice["id"] != choice["owner"]
            assert choice["id"].startswith("app:canvas-interface:")
