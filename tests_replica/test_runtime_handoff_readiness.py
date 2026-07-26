"""Courts for the local, graph-native runtime handoff readiness lens."""
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_runtime_handoff_readiness,
)


def test_unowned_idle_graph_is_clear_only_for_founder_review():
    store, registry = build_universal_application(resolve_map_path())
    revision = store.revision

    readiness = project_universal_runtime_handoff_readiness(
        store,
        registry,
        authentication_context=registry.authorization.session.context(),
    )

    assert store.revision == revision
    assert readiness == {
        "cell_native": True,
        "projection": "app:runtime-handoff-readiness:v1",
        "revision": revision,
        "runtime_owner": {"state": "unclaimed", "generation": 0},
        "activity": {
            "active_runtime_owners": 0,
            "active_runtime_sessions": 0,
            "active_runtime_presence_leases": 0,
            "pending_or_active_work": 0,
            "work": {
                "total": 0,
                "open": 0,
                "claimed": 0,
                "blocked": 0,
                "review": 0,
            },
        },
        "founder_review": {
            "required": True,
            "graph_clear": True,
            "blockers": [],
        },
    }
