"""AgDR-0015 Phase 4: radio-group keyboard navigation.

The group-style and save-skill mode pickers are graph-authored UI surfaces now.
This court checks the node authority plus the generic UI renderer, not obsolete
hand-coded JSX pills.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
JSX = APP / "web_ui" / "studio-lm.jsx"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.grand_map_ui import grand_map_ui_surface  # noqa: E402


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def _nodes(surface: str) -> dict[str, dict]:
    payload = grand_map_ui_surface(surface)
    assert payload["ok"] is True
    return {node["id"]: node for node in payload["nodes"]}


def test_group_style_pills_have_radiogroup():
    nodes = _nodes("canvas-group-dialog")
    label = nodes["ui:grandmap:group-style-label"]["data"]
    group = nodes["ui:grandmap:group-style-list"]["data"]
    assert label["data_attrs"]["id"] == "lm-group-style-label"
    assert group["data_attrs"]["aria-labelledby"] == "lm-group-style-label"
    assert group["role"] == "radiogroup"


def test_save_skill_mode_pills_have_radiogroup():
    nodes = _nodes("canvas-save-skill-dialog")
    label = nodes["ui:grandmap:save-skill-mode-label"]["data"]
    group = nodes["ui:grandmap:save-skill-mode-list"]["data"]
    assert label["data_attrs"]["id"] == "lm-save-skill-mode-label"
    assert group["data_attrs"]["aria-labelledby"] == "lm-save-skill-mode-label"
    assert group["role"] == "radiogroup"


def test_radiogroup_count_at_least_two():
    all_nodes = list(_nodes("canvas-group-dialog").values())
    all_nodes += list(_nodes("canvas-save-skill-dialog").values())
    assert sum(1 for node in all_nodes if node["data"].get("role") == "radiogroup") >= 2
    assert sum(1 for node in all_nodes if node["data"].get("role") == "radio") >= 4


def test_radio_buttons_carry_aria_checked():
    src = _src()
    assert "props['aria-checked'] = active ? 'true' : 'false';" in src
    nodes = _nodes("canvas-group-dialog")
    assert nodes["ui:grandmap:group-style-transform"]["data"]["active_bind"] == "slot:group-style"


def test_arrow_key_handler_present():
    key_actions = _nodes("canvas-group-dialog")["ui:grandmap:group-style-transform"]["data"]["key_actions"]
    for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"):
        assert key in key_actions, f"keyboard nav missing {key!r}"
    src = _src()
    assert "props.onKeyDown" in src and "d.key_actions" in src


def test_radio_tab_index_roving():
    src = _src()
    assert "props.tabIndex = active ? 0 : -1;" in src
