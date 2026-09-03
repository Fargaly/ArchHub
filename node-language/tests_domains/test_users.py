import pytest

from nodelang import KINDS, Store, relation_sources, relation_targets, validate_store
from nodelang.domains.users import (
    assigned_role,
    build_users_domain,
    privacy_allowed,
    rewire_role,
    rewire_session_owner,
    session_owner,
    set_entitlement_parameter,
    set_profile_parameter,
    set_role_parameter,
)


def _user(user_id: str, role: str):
    return {
        "id": user_id,
        "display_name": user_id.title(),
        "email": "%s@Example.com" % user_id,
        "role": role,
        "entitlements": ["workspace"],
        "auth": {
            "capability_ref": "op://archhub/auth/%s" % user_id,
            "evidence": {
                "provider": "external-oidc",
                "method": "pkce",
                "verified": True,
                "verified_at": "2026-07-12T20:00:00Z",
                "subject_ref": "subject:%s" % user_id,
            },
        },
    }


def _build():
    store = Store()
    domain = build_users_domain(
        store,
        users=[_user("founder", "owner"), _user("architect", "member")],
        sessions=[
            {
                "id": "project-wip",
                "title": "Project WIP",
                "owner": "founder",
                "privacy_scope": "CONFIDENTIAL",
            }
        ],
    )
    return store, domain


def _pairs(store: Store) -> set[tuple[str, str]]:
    pairs = set()
    for relation in store.nodes.values():
        if relation["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, relation):
            for target in relation_targets(store.nodes, relation):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def test_users_domain_is_one_open_table_with_explicit_relations():
    store, domain = _build()

    assert validate_store(store) is True
    assert {node["kind"] for node in store.nodes.values()} <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    assert store.nodes[domain["privacy_policy"]]["kind"] == "group"
    assert {name: store.pull(pid) for name, pid in
            store.nodes[domain["privacy_policy"]]["params"].items()} == {
                "PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "SECRET": 3}
    assert store.open(domain["users"]["founder"])
    assert store.open(domain["profiles"]["founder"])
    assert store.open(domain["roles"]["owner"])
    assert store.open(domain["entitlements"]["workspace"])
    assert store.open(domain["sessions"]["project-wip"])

    for owner in (
        domain["profiles"]["founder"],
        domain["roles"]["owner"],
        domain["entitlements"]["workspace"],
        domain["sessions"]["project-wip"],
    ):
        assert all(store.nodes[param]["kind"] == "param"
                   for param in store.nodes[owner]["params"].values())

    pairs = _pairs(store)
    assert (domain["roles"]["owner"], domain["users"]["founder"]) in pairs
    assert (domain["users"]["founder"], domain["firm"]) in pairs
    assert (domain["entitlements"]["workspace"],
            domain["users"]["architect"]) in pairs
    assert (domain["users"]["founder"],
            domain["sessions"]["project-wip"]) in pairs


def test_role_and_session_ownership_are_authoritative_rewirable_relations():
    store, domain = _build()

    assert assigned_role(store, domain, "architect") == "member"
    assert session_owner(store, domain, "project-wip") == "founder"

    rewire_role(store, domain, "architect", "admin", actor="founder")
    rewire_session_owner(
        store, domain, "project-wip", "architect", actor="founder"
    )

    assert assigned_role(store, domain, "architect") == "admin"
    assert session_owner(store, domain, "project-wip") == "architect"
    owner_sources = relation_sources(
        store.nodes, store.nodes[domain["ownership_relations"]["project-wip"]]
    )
    assert [item["node_id"] for item in owner_sources] == [
        domain["users"]["architect"]
    ]
    assert validate_store(store) is True


def test_privacy_gate_is_driven_by_wired_role_and_scope_parameters():
    store, domain = _build()

    # The gate is initially wired to the owner's role assignment.
    assert privacy_allowed(store, domain, "project-wip") is True
    clearance_wire, scope_wire = domain["privacy_relations"]["project-wip"]
    compare = domain["privacy_compare_nodes"]["project-wip"]
    assert [item["node_id"] for item in relation_targets(
        store.nodes, store.nodes[clearance_wire]
    )] == [compare]
    assert [item["node_id"] for item in relation_targets(
        store.nodes, store.nodes[scope_wire]
    )] == [compare]

    rewire_role(store, domain, "founder", "member", actor="founder")
    assert privacy_allowed(store, domain, "project-wip") is False

    rewire_role(store, domain, "founder", "admin", actor="founder")
    assert privacy_allowed(store, domain, "project-wip") is True

    set_role_parameter(
        store, domain, "admin", "privacy_clearance", "INTERNAL", actor="founder"
    )
    assert privacy_allowed(store, domain, "project-wip") is False
    assert validate_store(store) is True


def test_profile_role_and_entitlement_parameters_are_editable_and_audited():
    store, domain = _build()
    history_before = sum(node["kind"] == "history" for node in store.nodes.values())

    set_profile_parameter(
        store, domain, "architect", "display_name", "Project Architect",
        actor="architect",
    )
    set_profile_parameter(
        store, domain, "architect", "email", "NEW@EXAMPLE.COM",
        actor="architect",
    )
    set_entitlement_parameter(
        store, domain, "workspace", "enabled", False, actor="founder"
    )

    assert store.pull(domain["profile_params"]["architect"]["display_name"]) == \
        "Project Architect"
    assert store.pull(domain["profile_params"]["architect"]["email"]) == \
        "new@example.com"
    assert store.pull(domain["entitlements"]["workspace"]) is False
    history_after = sum(node["kind"] == "history" for node in store.nodes.values())
    assert history_after >= history_before + 3
    assert validate_store(store) is True


def test_raw_credentials_are_rejected_and_external_references_are_preserved():
    unsafe = _user("unsafe", "member")
    unsafe["auth"]["password"] = "raw-password"
    with pytest.raises(ValueError, match="fields mismatch|raw credential"):
        build_users_domain(Store(), users=[unsafe])

    unsafe = _user("unsafe", "member")
    unsafe["auth"]["capability_ref"] = "inline-token"
    with pytest.raises(ValueError, match="op://"):
        build_users_domain(Store(), users=[unsafe])

    unsafe = _user("unsafe", "member")
    unsafe["auth"]["evidence"]["access_token"] = "raw-token"
    with pytest.raises(ValueError, match="fields mismatch|raw credential"):
        build_users_domain(Store(), users=[unsafe])

    store, domain = _build()
    capability = store.nodes[domain["auth_capabilities"]["founder"]]
    assert capability["kind"] == "secret_ref"
    assert capability["body"]["floor"] == {
        "op": "secret_ref",
        "ref": "op://archhub/auth/founder",
    }
    assert "raw-password" not in repr(store.nodes)
    assert "raw-token" not in repr(store.nodes)
    assert validate_store(store) is True
