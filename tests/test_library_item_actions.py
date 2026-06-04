"""AgDR-0028 — library item actions (delete + bulk clear).

Pins:
  - workflows.custom_nodes.delete_spec removes spec file + unregisters
  - bridge slots exist: delete_saved_skill, delete_custom_node,
    clear_all_custom_nodes, clear_all_saved_skills
  - JSX wires per-item right-click + bulk-clear panel actions
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


# ─── 1. delete_spec round-trip ──────────────────────────────────────


def test_delete_spec_removes_file_and_returns_true(tmp_path, monkeypatch):
    from workflows import custom_nodes
    monkeypatch.setattr(custom_nodes, "custom_nodes_dir", lambda: tmp_path)
    spec = {
        "type": "x.delete_me",
        "category": "transform",
        "display_name": "delete me",
        "inputs":  ["a"],
        "outputs": ["b"],
        "code": "",
    }
    custom_nodes.write_spec(spec)
    custom_nodes.register_spec(spec)
    p = tmp_path / "x.delete_me.json"
    assert p.exists()

    ok = custom_nodes.delete_spec("x.delete_me")
    assert ok is True
    assert not p.exists()


def test_delete_spec_returns_false_when_missing(tmp_path, monkeypatch):
    from workflows import custom_nodes
    monkeypatch.setattr(custom_nodes, "custom_nodes_dir", lambda: tmp_path)
    assert custom_nodes.delete_spec("nope.nothing") is False


def test_delete_spec_empty_type_id_returns_false():
    from workflows import custom_nodes
    assert custom_nodes.delete_spec("") is False
    assert custom_nodes.delete_spec(None) is False


# ─── 2. bridge slots present ────────────────────────────────────────


def test_bridge_exposes_delete_saved_skill():
    import bridge
    assert hasattr(bridge.ArchHubBridge, "delete_saved_skill")


def test_bridge_exposes_delete_custom_node():
    import bridge
    assert hasattr(bridge.ArchHubBridge, "delete_custom_node")


def test_bridge_exposes_clear_all_custom_nodes():
    import bridge
    assert hasattr(bridge.ArchHubBridge, "clear_all_custom_nodes")


def test_bridge_exposes_clear_all_saved_skills():
    import bridge
    assert hasattr(bridge.ArchHubBridge, "clear_all_saved_skills")


# ─── 3. JSX wires the new context-menu kinds ───────────────────────


def test_jsx_ctxmenu_dispatches_on_kind():
    src = (APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    # New kinds.
    assert "ctxMenu.kind === 'custom-node'" in src
    assert "ctxMenu.kind === 'saved-skill'" in src
    # Bulk-clear bridge calls in the panel menu.
    assert "'clear_all_custom_nodes'" in src
    assert "'clear_all_saved_skills'" in src
    # Per-item bridge calls.
    assert "'delete_custom_node'" in src
    assert "'delete_saved_skill'" in src


def test_jsx_rows_set_ctxmenu_kind():
    """MY NODES + SKILLS rows wrap in onContextMenu that sets the
    item-specific `kind` field."""
    src = (APP / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "kind:'custom-node'" in src
    assert "kind:'saved-skill'" in src


# ─── 4. AgDR-0028 doc exists ───────────────────────────────────────


def test_agdr_0028_exists():
    p = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
         / "AgDR-0028-library-item-actions.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "status: executed" in text
    assert "delete_custom_node" in text
    assert "delete_saved_skill" in text
    assert "clear_all_custom_nodes" in text
