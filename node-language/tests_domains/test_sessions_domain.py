from __future__ import annotations

import pytest

from nodelang.core import Store, validate_store
from nodelang.domains.sessions import (
    create_session,
    create_session_catalog,
    create_lifecycle_policy,
    govern_existing_session,
    register_session,
    registered_session_ids,
    session_metadata,
    set_session_lifecycle,
)


def _history_count(store: Store) -> int:
    return sum(node["kind"] == "history" for node in store.nodes.values())


def test_create_and_register_sessions_as_grouped_references():
    store = Store()
    catalog = create_session_catalog(store)
    member = store.add("value", "Working graph", floor={"op": "value", "value": 7})
    session = create_session(
        store,
        "design-review",
        "Design Review",
        members=[member],
        owner="founder",
        description="Review the current graph",
        metadata={"pinned": True},
    )

    membership = register_session(store, catalog, session)

    assert store.nodes[catalog]["kind"] == "group"
    assert store.nodes[membership]["kind"] == "wire"
    assert membership in store.open(catalog)
    assert member in store.open(session)
    assert registered_session_ids(store, catalog) == [session]
    assert session_metadata(store, session) == {
        "key": "design-review",
        "lifecycle": "WIP",
        "owner": "founder",
        "description": "Review the current graph",
        "pinned": True,
    }
    assert validate_store(store) is True


def test_lifecycle_policy_is_open_editable_and_wired_to_session():
    store = Store()
    policy = create_lifecycle_policy(store, ["IDEA", "BUILT"])
    session = create_session(store, "concept", "Concept", lifecycle="IDEA",
                             lifecycle_policy=policy)
    allowed = store.nodes[policy]["params"]["allowed_states"]

    store.edit(allowed, ["body", "floor", "value"], ["IDEA", "BUILT", "LIVE"])
    set_session_lifecycle(store, session, "live")

    assert store.pull(store.nodes[session]["params"]["lifecycle"]) == "LIVE"
    assert any(policy in [e["node_id"] for e in store.endpoints(rid)]
               for rid in store.nodes[session]["relations"])
    assert validate_store(store) is True


def test_existing_session_can_be_adopted_without_rebuilding_it():
    store = Store()
    member = store.add("value", "Existing work", floor={"op": "value", "value": 3})
    session = store.add("session", "Existing Session", inner=[member])
    policy = create_lifecycle_policy(store, ["WIP", "LIVE"])

    assert govern_existing_session(store, session, "existing", lifecycle_policy=policy) == session
    assert member in store.open(session)
    assert session_metadata(store, session)["key"] == "existing"
    set_session_lifecycle(store, session, "LIVE")
    assert session_metadata(store, session)["lifecycle"] == "LIVE"
    assert validate_store(store) is True


def test_lifecycle_edit_targets_parameter_node_and_is_audited():
    store = Store()
    session = create_session(store, "delivery", "Delivery")
    lifecycle_id = store.nodes[session]["params"]["lifecycle"]
    before = _history_count(store)

    touched = set_session_lifecycle(store, session, "production", actor="court")

    assert touched == lifecycle_id
    assert store.pull(lifecycle_id) == "PRODUCTION"
    assert session_metadata(store, session)["lifecycle"] == "PRODUCTION"
    assert _history_count(store) == before + 1
    latest = max(
        (node for node in store.nodes.values() if node["kind"] == "history"),
        key=lambda node: node["meta"]["seq"],
    )
    assert latest["body"]["floor"]["entry"] == {
        "op": "set",
        "id": lifecycle_id,
        "path": ["body", "floor", "value"],
            "value": "PRODUCTION",
            "actor": "court",
            "before": "WIP",
        }
    assert validate_store(store) is True


def test_registration_rejects_duplicate_session_and_duplicate_key():
    store = Store()
    catalog = create_session_catalog(store)
    first = create_session(store, "coordination", "Coordination A")
    same_key = create_session(store, "coordination", "Coordination B")
    register_session(store, catalog, first)

    with pytest.raises(ValueError, match="already registered"):
        register_session(store, catalog, first)
    with pytest.raises(ValueError, match="session key"):
        register_session(store, catalog, same_key)

    assert registered_session_ids(store, catalog) == [first]
    assert validate_store(store) is True


def test_invalid_lifecycle_is_refused_without_mutating_session():
    store = Store()
    session = create_session(store, "analysis", "Analysis", lifecycle="SHARED")
    before = _history_count(store)

    with pytest.raises(ValueError, match="lifecycle must be one of"):
        set_session_lifecycle(store, session, "published")

    assert session_metadata(store, session)["lifecycle"] == "SHARED"
    assert _history_count(store) == before
    assert validate_store(store) is True
