"""Regression guard — stock palette nodes must be drag-to-canvas.

Bug 2026-05-21: commit eccfc2c rewrote NodesPanel with collapsible
categories and copy-pasted the SKILLS row's `draggable={false}` onto
the stock grammar-node row.  Every placeable primitive (Number, Text,
If, Add, …) rendered `draggable="false"` → drag-drop onto the canvas
dead.  Only SKILLS rows should be `draggable={false}` (they spawn via
double-click, not drag).

Also pins the flashToast scope fix: AgDR-0028's ctxMenu delete handlers
called flashToast, which lives in NodeCanvas scope — NodesPanel needs
its own.
"""
from __future__ import annotations

import re
from pathlib import Path


JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def _node_lib_item_calls(src: str) -> list[str]:
    """Return each `<NodeLibItem ... />` JSX element text.  Elements
    span multiple lines and contain `>` inside arrow funcs / objects,
    so match lazily to the closing `/>`."""
    return re.findall(r"<NodeLibItem\b[\s\S]*?/>", src)


# ─── 1. stock palette row is draggable ──────────────────────────────


def test_stock_palette_node_row_is_draggable():
    """The grammar-node palette row (inside the collapsible category
    map) must NOT carry draggable={false}.  NodeLibItem defaults
    draggable=true; the stock row must inherit that default."""
    src = _src()
    # Locate the category-map render — `items.map(({ key, it, cat })`
    # then take the NodeLibItem element that follows it.
    idx = src.find("items.map(({ key, it, cat })")
    assert idx >= 0, "stock palette items.map render not found"
    window = src[idx:idx + 1500]
    m = re.search(r"<NodeLibItem\b[\s\S]*?/>", window)
    assert m, "NodeLibItem element not found after items.map"
    element = m.group(0)
    assert "draggable={false}" not in element, (
        "stock palette NodeLibItem has draggable={false} — "
        "drag-to-canvas is dead for every placeable primitive")


# ─── 2. SKILLS rows stay non-draggable ──────────────────────────────


def test_skill_rows_stay_non_draggable():
    """SKILLS rows spawn via double-click / lm-spawn-skill, NOT drag.
    They legitimately keep draggable={false}.  At least one
    NodeLibItem call must still carry it."""
    src = _src()
    calls = _node_lib_item_calls(src)
    non_draggable = [c for c in calls if "draggable={false}" in c]
    assert len(non_draggable) >= 1, (
        "expected the SKILLS-row NodeLibItem to keep draggable={false}")


# ─── 3. NodeLibItem default + dragstart wiring intact ──────────────


def test_node_lib_item_defaults_draggable_true():
    src = _src()
    m = re.search(r"const NodeLibItem = \(\{[^}]*\}\) =>", src)
    assert m, "NodeLibItem definition not found"
    assert "draggable = true" in m.group(0), (
        "NodeLibItem must default draggable=true")


def test_node_lib_item_dragstart_sets_payload():
    """onDragStart must put the node spec on the dataTransfer so the
    canvas onDrop can read `application/x-lm-node`."""
    src = _src()
    assert "'application/x-lm-node'" in src
    assert "e.dataTransfer.setData('application/x-lm-node'" in src


def test_canvas_ondrop_reads_lm_node_payload():
    src = _src()
    assert "e.dataTransfer.getData('application/x-lm-node')" in src
    assert "addNodeFromLibrary" in src


# ─── 4. flashToast in NodesPanel scope ──────────────────────────────


def test_nodes_panel_has_local_flash_toast():
    """AgDR-0028 ctxMenu delete handlers call flashToast.  NodesPanel
    must define its own (NodeCanvas's is out of scope)."""
    src = _src()
    start = src.find("const NodesPanel = ({ addNodeFromLibrary }) =>")
    assert start >= 0
    # Bound at the next top-level `const ` component declaration.
    end = src.find("\nconst NodeLibItem", start)
    body = src[start:end if end > 0 else start + 8000]
    assert "const flashToast =" in body, (
        "NodesPanel must define a local flashToast — AgDR-0028 delete "
        "handlers reference it")
    # And it dispatches the lm-canvas-toast window event the canvas listens for.
    assert "lm-canvas-toast" in body
