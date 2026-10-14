"""p9: a scope partition must not turn the entire System into user cards."""
import json

from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    group_universal_selection,
    project_universal_canvas,
    remove_universal_composition_member,
    set_universal_selection,
    undo_universal_change,
)


def _system_entry(canvas):
    # These are the actual fields Studio's systemAllowed/SystemMiniGraph read.
    return json.dumps([
        {key: node.get(key) for key in ("id", "application", "group")}
        for node in canvas["nodes"] if node.get("application")
    ], sort_keys=True)


def test_group_partition_preserves_system_entry_and_only_release_is_overlay():
    store, registry = build_universal_application(resolve_map_path())
    before = project_universal_canvas(store, registry)
    system = [node for node in before["nodes"] if node.get("application")]
    assert before["authorization"]["system_view"] is True
    assert len(system) > 2
    selected = tuple(node["id"] for node in system[:2])
    set_universal_selection(store, registry, selected, focus_root=selected[-1])
    group_root, _ = group_universal_selection(store, registry, title="p9 systems")
    grouped = project_universal_canvas(store, registry)
    unaffected = [node for node in before["nodes"] if node["id"] not in selected]
    assert _system_entry({"nodes": [node for node in grouped["nodes"]
                                     if node["id"] != group_root]}) == _system_entry({"nodes": unaffected})
    assert any(node.get("application") for node in grouped["nodes"]), "Settings > System remains admitted"
    grouped_entry = _system_entry(grouped)

    remove_universal_composition_member(store, registry, group_root, selected[0])
    released = project_universal_canvas(store, registry)
    member = next(node for node in released["nodes"] if node["id"] == selected[0])
    assert member.get("application") is False
    assert member["group"] == "", "only the released member becomes a free overlay card"
    group = next(node for node in released["nodes"] if node["id"] == group_root)
    assert group["member_count"] == 1
    assert _system_entry({"nodes": [node for node in released["nodes"]
                                     if node["id"] not in (group_root, selected[0])]}) == _system_entry({"nodes": unaffected})

    undo_universal_change(store, registry)
    restored = project_universal_canvas(store, registry)
    assert _system_entry(restored) == grouped_entry
    assert next(node for node in restored["nodes"] if node["id"] == group_root)["member_count"] == 2
