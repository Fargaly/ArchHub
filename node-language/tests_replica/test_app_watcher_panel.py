"""The self-hosted Grand Map app has a real properties watcher.

Slice target: click a map node card, the right properties panel (itself made of
ui nodes) shows the node's real value/param nodes, edit a param through
Store.apply_op, and see history grow.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import app_from_grandmap as app
from nodelang.core import validate_store


def _history_count(store):
    return sum(1 for n in store.nodes.values() if n["kind"] == "history")


def test_watcher_opens_a_real_map_node_and_its_param_nodes():
    store, _root, ids = app.build()

    snap = app.watcher_snapshot(store, ids, "ui_design_tokens")

    assert snap["map_id"] == "ui_design_tokens"
    assert snap["value_node"]["kind"] == "value"
    # The status comes from the grand-map SOURCE, not a hand-pinned copy:
    # the pinned "partial" went stale the day the map promoted the node to
    # "live" and the court then failed the truth instead of the drift.
    import json
    from nodelang.map_import import resolve_map_path
    source = json.load(open(resolve_map_path(), encoding="utf-8"))
    def find(obj):
        if isinstance(obj, dict):
            if obj.get("id") == "ui_design_tokens":
                return obj
            for value in obj.values():
                found = find(value)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = find(value)
                if found is not None:
                    return found
        return None
    assert snap["value_node"]["value"] == find(source)["status"]
    assert "accent" in snap["params"]
    assert snap["params"]["accent"]["kind"] == "param"
    assert snap["params"]["accent"]["value"].startswith("#d97757")


def test_watcher_edit_updates_a_param_node_and_adds_history():
    store, _root, ids = app.build()
    accent = ids["reg"]["params"]["ui_design_tokens"]["accent"]
    before_history = _history_count(store)

    out = app.apply_watcher_edit(store, accent, "#00ff88")

    assert out["ok"] is True
    assert store.pull(accent) == "#00ff88"
    assert _history_count(store) == before_history + 1
    assert validate_store(store) is True


def test_render_page_selects_cards_and_shows_node_properties_panel():
    store, root, ids = app.build()

    html = app.render_page(store, root, ids, watch="ui_design_tokens")

    assert 'class="ncard selected"' in html
    assert 'href="/?watch=ui_design_tokens"' in html
    assert '>open<' not in html
    assert 'class="open"' not in html
    assert 'class="properties"' in html
    assert 'data-panel-node="' in html
    assert "ui_design_tokens" in html
    assert "accent" in html
    assert ids["reg"]["params"]["ui_design_tokens"]["accent"] in html
