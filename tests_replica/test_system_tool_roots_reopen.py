"""PM gate 2026-10-13 (NO-GO on 315f3678): boot -> save -> relaunch refused the saved graph.

The System tool roots were appended to the view-visibility relation on every boot, so the
second open raised "view visibility repeats a canvas root" and the app kept the founder's
graph closed. Reopening the same store must open, with each tool root held once.
"""
from collections import Counter

from nodelang import universal_application as ua
from nodelang.cell_protocols import read_relation
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
    restore_universal_application,
)


def _visible_pairs(store, registry):
    snapshot = store.snapshot()
    visibility_root = registry.authorization.session.root_id + ":visibility"
    return Counter((m.role_id, m.participant_id) for m in read_relation(snapshot, visibility_root, budget=100_000))


def _provider():
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    provider = MemorySigningKeyProvider("archhub.local.relationship-authority", b"r" * 32)
    provider.add_key("archhub.local.court-attestation", b"e" * 32)
    return provider


def test_relaunch_on_the_same_store_opens_the_saved_graph_and_holds_each_tool_once():
    provider = _provider()
    store, registry = build_universal_application(resolve_map_path(), key_provider=provider)
    first = project_universal_canvas(store, registry)
    # Relaunch twice on the SAME durable graph (what the app does on every restart).
    store, registry = restore_universal_application(resolve_map_path(), store, key_provider=provider)
    store, registry = restore_universal_application(resolve_map_path(), store, key_provider=provider)
    reopened = project_universal_canvas(store, registry)
    assert {node["id"] for node in reopened["nodes"]} == {node["id"] for node in first["nodes"]}
    tools = {ua._system_tool_canvas_root(t) for t in ("tool_studio", "tool_workshop", "tool_baboom")}
    assert tools <= {node["id"] for node in reopened["nodes"]}
    repeats = {pair: n for pair, n in _visible_pairs(store, registry).items() if n > 1}
    assert repeats == {}, "no visible root is held twice after relaunches"


def test_a_graph_already_holding_a_repeated_visible_root_still_opens():
    # A graph saved by the bad builds (673a1f7d..0d79d86f) may hold a tool root twice.
    store, registry = build_universal_application(resolve_map_path())
    root = ua._system_tool_canvas_root("tool_studio")
    assigned = (root, root)
    roots, _relations, _properties = ua._canvas_scope_for_assigned(store.snapshot(), registry, assigned)
    assert list(roots).count(root) == 1
