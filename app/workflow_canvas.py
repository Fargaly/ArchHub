"""Workflow node canvas — Blueprint direction (handoff blueprint.jsx).

A real QGraphicsScene canvas that reads and writes the existing
`workflows.graph.Workflow` data model — same JSON shape the
WorkflowsPanel list view uses, so a workflow saved here loads in the
list view and vice versa.

Layout & feel
-------------
- Drafting paper: 12-px minor grid, 60-px major grid (mirrors
  blueprint.jsx::BlueprintFlow exactly).
- Border-in-a-border drafting frame around the visible scene.
- Title block bottom-right (workflow name · stage · state · elapsed).
- Nodes are rounded-rect cards: kind tag, host pill, title, sub.
- Edges are right-angle "elbow" paths with an accent arrow head
  (same as the JSX prototype).

Interactions
------------
- Click + drag a node moves it; edges follow.
- Drag from a node's right slot to another node's left slot creates
  an edge. Drop in empty space cancels.
- Right-click an empty area opens a node palette.
- Right-click a node opens delete + edit-config.
- Ctrl+S saves the current Workflow to the workflows library.
- Ctrl+R runs the workflow via WorkflowExecutor (best-effort).

Caveats / what's NOT in this PR
-------------------------------
- No drag-and-drop FROM an external palette dock; right-click context
  menu is the palette for now.
- Node-config editor surfaces a tiny dialog with raw JSON; the
  per-node-type form editor lands in v0.33 (Parameters sidebar).
- Save uses the workflows.library path; the executor wiring is
  best-effort and falls back to a status line if the executor isn't
  available in this shell.
"""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QFont,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QInputDialog,
    QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from design_tokens import SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


# Node visual sizing matches blueprint.jsx ratios.
NODE_W = 200
NODE_H = 90
SLOT_R = 5         # connection dot radius

# Type → color hue (one warm color rule still applies, so non-accent
# differences are hue-shifted greys/cools, never new emotional colors).
KIND_COLOR = {
    "input":   T["accent"],     # warm — entry point
    "llm":     T["cyan"],       # technical — model call
    "tool":    T["inkSoft"],    # neutral — tool/host action
    "control": T["warn"],       # decision/loop
    "output":  T["ok"],         # terminus
}


# ---------------------------------------------------------------------------
def _kind_for_type(node_type: str) -> str:
    if not node_type:
        return "tool"
    t = node_type.lower()
    if t.startswith("user.") or t.startswith("input."):
        return "input"
    if t.startswith("llm."):
        return "llm"
    if t.startswith("control."):
        return "control"
    if t.startswith("output."):
        return "output"
    return "tool"


# ---------------------------------------------------------------------------
class NodeItem(QGraphicsItem):
    """One workflow node rendered as a rounded card."""
    def __init__(self, node, parent=None):
        super().__init__(parent)
        self.node = node
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        x = float(node.position.get("x", 0))
        y = float(node.position.get("y", 0))
        self.setPos(x, y)

    # Bounding box used for hit-testing + repaint.
    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, NODE_W + 4, NODE_H + 4)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        kind = _kind_for_type(self.node.type)
        accent = QColor(KIND_COLOR.get(kind, T["inkSoft"]))

        # Card.
        rect = QRectF(0, 0, NODE_W, NODE_H)
        bg = QColor(T["bgRaised"])
        line = QColor(T["line"])
        if self.isSelected():
            line = QColor(T["accent"])
        painter.setPen(QPen(line, 1.0))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(rect, 8, 8)

        # Left ribbon (kind color).
        ribbon = QRectF(0, 0, 4, NODE_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        painter.drawRoundedRect(ribbon, 2, 2)

        # Kind label (mono cap).
        painter.setPen(QPen(QColor(T["inkCap"])))
        f_cap = QFont("JetBrains Mono", 8)
        f_cap.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
        painter.setFont(f_cap)
        painter.drawText(QPointF(14, 16), kind.upper())

        # Title (serif italic).
        f_t = QFont("Instrument Serif", 13)
        f_t.setItalic(True)
        painter.setFont(f_t)
        painter.setPen(QPen(QColor(T["ink"])))
        painter.drawText(QRectF(14, 22, NODE_W - 28, 24),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.node.label or self.node.type)

        # Sub-line: type · port summary.
        f_sub = QFont("Inter", 9)
        painter.setFont(f_sub)
        painter.setPen(QPen(QColor(T["inkSoft"])))
        sub = f"{self.node.type}  ·  {len(self.node.inputs)}↓ {len(self.node.outputs)}↑"
        painter.drawText(QRectF(14, 50, NODE_W - 28, 18),
                         Qt.AlignmentFlag.AlignLeft, sub)

        # Slots.
        painter.setBrush(QBrush(QColor(T["bgPanel"])))
        painter.setPen(QPen(QColor(T["accent"]), 1.5))
        # Left input slot.
        if self.node.inputs:
            painter.drawEllipse(QPointF(0, NODE_H / 2), SLOT_R, SLOT_R)
        # Right output slot.
        if self.node.outputs:
            painter.drawEllipse(QPointF(NODE_W, NODE_H / 2), SLOT_R, SLOT_R)

    # ------------------------------------------------------------------
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.node.position = {"x": float(self.pos().x()),
                                  "y": float(self.pos().y())}
            scene = self.scene()
            if isinstance(scene, CanvasScene):
                scene.refresh_edges_for(self)
        return super().itemChange(change, value)

    # Slot scene positions — used by EdgeItem to compute path endpoints.
    def input_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, NODE_H / 2))

    def output_pos(self) -> QPointF:
        return self.mapToScene(QPointF(NODE_W, NODE_H / 2))

    def hit_kind_at(self, scene_pos: QPointF) -> Optional[str]:
        """Return 'in' / 'out' / None depending on which slot the
        scene position is over (with a small click-tolerance)."""
        local = self.mapFromScene(scene_pos)
        if (local - QPointF(0, NODE_H / 2)).manhattanLength() < 14:
            return "in" if self.node.inputs else None
        if (local - QPointF(NODE_W, NODE_H / 2)).manhattanLength() < 14:
            return "out" if self.node.outputs else None
        return None


# ---------------------------------------------------------------------------
class EdgeItem(QGraphicsPathItem):
    """Right-angle elbow path with an arrow head."""
    def __init__(self, edge, src: NodeItem, dst: NodeItem, parent=None):
        super().__init__(parent)
        self.edge = edge
        self.src = src
        self.dst = dst
        self.setZValue(-1)
        pen = QPen(QColor(T["accent"]), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.refresh()

    def refresh(self) -> None:
        if self.src is None or self.dst is None:
            return
        a = self.src.output_pos()
        b = self.dst.input_pos()
        mx = (a.x() + b.x()) / 2.0
        path = QPainterPath(a)
        path.lineTo(QPointF(mx, a.y()))
        path.lineTo(QPointF(mx, b.y()))
        path.lineTo(b)
        # Arrow head.
        arrow_size = 7.0
        ang = 0.0  # arrow always points right at b
        ax, ay = b.x(), b.y()
        head = QPolygonF([
            QPointF(ax, ay),
            QPointF(ax - arrow_size, ay - arrow_size / 2),
            QPointF(ax - arrow_size, ay + arrow_size / 2),
        ])
        path.addPolygon(head)
        self.setPath(path)


# ---------------------------------------------------------------------------
class DraggingEdgeItem(QGraphicsPathItem):
    """Transient edge while user drags from a slot to another slot."""
    def __init__(self, src: NodeItem, parent=None):
        super().__init__(parent)
        self.src = src
        pen = QPen(QColor(T["accent"]), 1.2, Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setZValue(10)
        self._end = src.output_pos()

    def update_end(self, pos: QPointF) -> None:
        self._end = pos
        a = self.src.output_pos()
        path = QPainterPath(a)
        mx = (a.x() + pos.x()) / 2.0
        path.lineTo(QPointF(mx, a.y()))
        path.lineTo(QPointF(mx, pos.y()))
        path.lineTo(pos)
        self.setPath(path)


# ---------------------------------------------------------------------------
class CanvasScene(QGraphicsScene):
    """Holds Workflow data + node/edge items + drag-edge state."""
    def __init__(self, workflow=None, parent=None):
        super().__init__(parent)
        from workflows.graph import Workflow
        self.workflow = workflow if workflow is not None else Workflow(
            id=uuid.uuid4().hex[:10], name="Untitled workflow",
        )
        self.setBackgroundBrush(QBrush(QColor(T["bg"])))
        self.setSceneRect(0, 0, 2000, 1400)
        self._node_items: dict[str, NodeItem] = {}
        self._edge_items: list[EdgeItem] = []
        self._dragging: Optional[DraggingEdgeItem] = None
        self._dragging_from: Optional[NodeItem] = None
        # Undo / redo stacks — store JSON snapshots of the workflow.
        # Pushed before every mutating op; redo cleared on new mutation.
        # Bound to 100 entries each; oldest dropped when full.
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._UNDO_CAP = 100
        self._render_workflow()

    # ---- undo / redo --------------------------------------------------
    def _snapshot_text(self) -> str:
        """Serialise the workflow to a JSON string. Used as the undo
        stack entry."""
        return json.dumps(self.workflow.to_dict(), sort_keys=True)

    def _content_fingerprint(self) -> str:
        """Like _snapshot_text but with timestamp metadata stripped, so
        a comparison isn't fooled by `updated_at` ticking forward on
        every Workflow construction (Workflow.from_dict refreshes it)."""
        d = self.workflow.to_dict()
        d.pop("created_at", None)
        d.pop("updated_at", None)
        return json.dumps(d, sort_keys=True)

    def _push_undo(self) -> None:
        """Capture the CURRENT workflow before mutation. Always clears
        the redo stack (a new branch invalidates the future history).
        Dedupe rule: if the current content fingerprint matches the
        fingerprint we observed the LAST time push was called, skip.
        That guards against double-push from cascading UI events
        (e.g. click + mouseRelease both triggering a save). The cap
        prevents unbounded growth as a backstop."""
        fp = self._content_fingerprint()
        if getattr(self, "_last_push_fp", None) == fp:
            return
        self._undo.append(self._snapshot_text())
        self._last_push_fp = fp
        if len(self._undo) > self._UNDO_CAP:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, snap_json: str) -> None:
        from workflows.graph import Workflow
        try:
            d = json.loads(snap_json)
        except Exception:
            return
        self.workflow = Workflow.from_dict(d)
        self._render_workflow()

    def undo(self) -> bool:
        """Pop one snapshot. Returns True iff a state was actually
        restored. The CURRENT state is pushed onto the redo stack
        before the previous state is applied so redo works."""
        if not self._undo:
            return False
        cur = self._snapshot_text()
        prev = self._undo.pop()
        self._restore(prev)
        self._redo.append(cur)
        if len(self._redo) > self._UNDO_CAP:
            self._redo.pop(0)
        # Invalidate the dedupe fingerprint so the next mutation always
        # produces a fresh undo entry (the current state was just
        # restored, but it is NO LONGER the same as the next future
        # push's reference state).
        self._last_push_fp = None
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cur = self._snapshot_text()
        nxt = self._redo.pop()
        self._restore(nxt)
        self._undo.append(cur)
        if len(self._undo) > self._UNDO_CAP:
            self._undo.pop(0)
        self._last_push_fp = None
        return True

    # ------------------------------------------------------------------
    def _render_workflow(self) -> None:
        for it in list(self._node_items.values()):
            self.removeItem(it)
        for ed in list(self._edge_items):
            self.removeItem(ed)
        self._node_items.clear()
        self._edge_items.clear()
        for n in self.workflow.nodes:
            it = NodeItem(n)
            self.addItem(it)
            self._node_items[n.id] = it
        for e in self.workflow.edges:
            self._add_edge_item(e)

    def _add_edge_item(self, edge) -> None:
        src = self._node_items.get(edge.src_node)
        dst = self._node_items.get(edge.dst_node)
        if src is None or dst is None:
            return
        ei = EdgeItem(edge, src, dst)
        self.addItem(ei)
        self._edge_items.append(ei)

    def refresh_edges_for(self, node_item: NodeItem) -> None:
        for ei in self._edge_items:
            if ei.src is node_item or ei.dst is node_item:
                ei.refresh()

    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        # Drafting grid: minor 12 px, major 60 px.
        minor = QColor(T["lineSoft"])
        major = QColor(T["line"])
        painter.setPen(QPen(minor, 1))
        x0 = int(rect.left() // 12 * 12)
        y0 = int(rect.top() // 12 * 12)
        x = x0
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += 12
        y = y0
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += 60 if y % 60 == 0 else 12  # walked anyway
            y += 12
        painter.setPen(QPen(major, 1))
        x = int(rect.left() // 60 * 60)
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += 60
        y = int(rect.top() // 60 * 60)
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += 60

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """Drafting double-border + title block — matches blueprint.jsx
        BlueprintFlow chrome."""
        super().drawForeground(painter, rect)
        scene_rect = self.sceneRect()
        ink = QColor(T["ink"])
        line = QColor(T["line"])
        # Outer border (1 px ink).
        painter.setPen(QPen(ink, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(scene_rect.adjusted(14, 14, -14, -14))
        # Inner border (1 px line).
        painter.setPen(QPen(line, 1))
        painter.drawRect(scene_rect.adjusted(18, 18, -18, -18))

        # Title block bottom-right.
        tb_w = 260
        tb_h = 80
        tb_x = scene_rect.right() - 18 - tb_w
        tb_y = scene_rect.bottom() - 18 - tb_h
        painter.setBrush(QBrush(QColor(T["bgPanel"])))
        painter.setPen(QPen(ink, 1))
        painter.drawRect(int(tb_x), int(tb_y), tb_w, tb_h)
        # Header strip.
        painter.setPen(QPen(ink, 1))
        painter.drawLine(int(tb_x), int(tb_y) + 22,
                         int(tb_x) + tb_w, int(tb_y) + 22)
        # Header text.
        painter.setPen(QPen(ink))
        f_h = QFont("JetBrains Mono", 9)
        f_h.setBold(True)
        f_h.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
        painter.setFont(f_h)
        wf_name = (getattr(self.workflow, "name", "") or "WORKFLOW").upper()
        painter.drawText(int(tb_x) + 8, int(tb_y) + 16, wf_name[:24])
        # Right-aligned WF id.
        wf_id = (getattr(self.workflow, "id", "") or "WF–001").upper()
        painter.drawText(int(tb_x) + tb_w - 60, int(tb_y) + 16, wf_id)
        # KV rows.
        f_kv = QFont("JetBrains Mono", 8)
        f_kv.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        painter.setFont(f_kv)
        cap = QColor(T["inkMuted"])
        body = QColor(T["ink"])
        rows = [
            ("STAGE",   f"{len(self.workflow.nodes)} nodes"),
            ("STATE",   "DRAFT"),
            ("EDGES",   f"{len(self.workflow.edges)}"),
            ("BY",      "FARGALY"),
        ]
        for i, (k, v) in enumerate(rows):
            y_row = int(tb_y) + 36 + i * 11
            painter.setPen(QPen(cap))
            painter.drawText(int(tb_x) + 8, y_row, k)
            painter.setPen(QPen(body))
            painter.drawText(int(tb_x) + 80, y_row, v)

    # ------------------------------------------------------------------
    # Edge drag handling — start on a node's right slot, finish on
    # another node's left slot.
    # ------------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        scene_pos = ev.scenePos()
        # Did we hit a node slot?
        item = self.itemAt(scene_pos, self.views()[0].transform()
                           if self.views() else None)
        if isinstance(item, NodeItem):
            kind = item.hit_kind_at(scene_pos)
            if kind == "out":
                self._dragging_from = item
                self._dragging = DraggingEdgeItem(item)
                self.addItem(self._dragging)
                self._dragging.update_end(scene_pos)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._dragging is not None:
            self._dragging.update_end(ev.scenePos())
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if self._dragging is not None and self._dragging_from is not None:
            target = None
            for it in self.items(ev.scenePos()):
                if isinstance(it, NodeItem) and it is not self._dragging_from:
                    if it.hit_kind_at(ev.scenePos()) == "in":
                        target = it
                        break
            self.removeItem(self._dragging)
            self._dragging = None
            src = self._dragging_from
            self._dragging_from = None
            if target is not None:
                self._make_edge(src, target)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def _make_edge(self, src: NodeItem, dst: NodeItem) -> None:
        from workflows.graph import Edge
        if not src.node.outputs or not dst.node.inputs:
            return
        self._push_undo()
        edge = Edge(
            id=uuid.uuid4().hex[:10],
            src_node=src.node.id, src_port=src.node.outputs[0].name,
            dst_node=dst.node.id, dst_port=dst.node.inputs[0].name,
        )
        self.workflow.edges.append(edge)
        self._add_edge_item(edge)

    def duplicate_node(self, item: NodeItem) -> Optional["NodeItem"]:
        """Clone the given node + offset 24px down-right. Returns the
        new NodeItem so the caller can select it (Ctrl+D shortcut)."""
        self._push_undo()
        from workflows.graph import Node, Port
        src = item.node
        new = Node(
            id=uuid.uuid4().hex[:10],
            type=src.type,
            label=src.label,
            inputs=[Port(**p.to_dict()) for p in src.inputs],
            outputs=[Port(**p.to_dict()) for p in src.outputs],
            config=dict(src.config or {}),
            position={
                "x": (src.position or {}).get("x", 0) + 24,
                "y": (src.position or {}).get("y", 0) + 24,
            },
        )
        self.workflow.nodes.append(new)
        ni = NodeItem(new)
        self.addItem(ni)
        self._node_items[new.id] = ni
        return ni

    def nudge_selected(self, dx: int, dy: int) -> None:
        """Arrow-key handler — move every selected NodeItem by (dx,dy)
        scene units. Pushed once per direction so a key-hold doesn't
        flood the undo stack."""
        moved = False
        items = [it for it in self.selectedItems() if isinstance(it, NodeItem)]
        if not items:
            return
        if not getattr(self, "_nudge_pending", False):
            self._push_undo()
            self._nudge_pending = True
        for it in items:
            p = it.pos()
            it.setPos(p.x() + dx, p.y() + dy)
            it.node.position = {"x": it.pos().x(), "y": it.pos().y()}
            self.refresh_edges_for(it)
            moved = True
        if moved:
            # Reset nudge flag on idle so next arrow-press starts a new
            # undo group.
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(400,
                lambda: setattr(self, "_nudge_pending", False))

    def delete_selected(self) -> int:
        """Delete every selected NodeItem. Returns count deleted."""
        items = [it for it in self.selectedItems() if isinstance(it, NodeItem)]
        if not items:
            return 0
        self._push_undo()
        for it in items:
            # Delete without pushing undo again — we already snapshotted.
            nid = it.node.id
            self.workflow.nodes = [n for n in self.workflow.nodes if n.id != nid]
            self.workflow.edges = [e for e in self.workflow.edges
                                    if e.src_node != nid and e.dst_node != nid]
            kept = []
            for ei in self._edge_items:
                if ei.src is it or ei.dst is it:
                    self.removeItem(ei)
                else:
                    kept.append(ei)
            self._edge_items = kept
            self.removeItem(it)
            self._node_items.pop(nid, None)
        return len(items)

    # ------------------------------------------------------------------
    # Right-click palette / node menu.
    # ------------------------------------------------------------------
    def contextMenuEvent(self, ev) -> None:
        scene_pos = ev.scenePos()
        item = self.itemAt(scene_pos, self.views()[0].transform()
                           if self.views() else None)
        if isinstance(item, NodeItem):
            self._show_node_menu(item, ev.screenPos())
            ev.accept()
            return
        self._show_palette(scene_pos, ev.screenPos())
        ev.accept()

    def _show_palette(self, scene_pos: QPointF, screen_pos) -> None:
        """Right-click palette — now pulls EVERY registered node from
        `workflows.registry`, grouped by category submenu. Was hardcoded
        to 6 placeholder items, so the 9 AEC nodes + tool.* dynamic
        nodes never showed up. Founder feedback: "where are the nodes?"
        — the menu wasn't wired to the registry.
        """
        menu = QMenu()
        # Pull live catalog.
        try:
            from workflows.registry import _REGISTRY
            specs = [s for s, _ in _REGISTRY.values()]
        except Exception:
            specs = []

        if not specs:
            # Fallback: minimal hardcoded set so the menu isn't empty
            # if the registry import fails.
            specs = []
            from collections import namedtuple
            FB = namedtuple("FB", "type category display_name icon")
            for t, c, d, i in (
                ("user.prompt",   "io",      "User prompt",   "→"),
                ("llm.complete",  "llm",     "LLM · complete", "✦"),
                ("output.value",  "io",      "Output value",  "←"),
            ):
                specs.append(FB(t, c, d, i))

        # Group by top-level category so 30+ entries don't dump in one list.
        by_cat: dict[str, list] = {}
        for spec in specs:
            cat = (getattr(spec, "category", "") or "misc").split(".")[0]
            by_cat.setdefault(cat, []).append(spec)

        # Preferred ordering — io / aec / llm / tool / control / misc.
        order = ["io", "aec", "llm", "tool", "control", "data", "misc"]
        seen = set()
        for cat in order + sorted(by_cat.keys()):
            if cat in seen or cat not in by_cat:
                continue
            seen.add(cat)
            entries = sorted(by_cat[cat], key=lambda s: s.display_name)
            if len(entries) == 1:
                spec = entries[0]
                act = menu.addAction(
                    f"{getattr(spec, 'icon', '·')}  {spec.display_name}")
                t = spec.type
                act.triggered.connect(
                    lambda _=False, tn=t, p=scene_pos: self._add_node(tn, p))
                continue
            sub = menu.addMenu(cat.upper())
            for spec in entries:
                act = sub.addAction(
                    f"{getattr(spec, 'icon', '·')}  {spec.display_name}")
                t = spec.type
                act.triggered.connect(
                    lambda _=False, tn=t, p=scene_pos: self._add_node(tn, p))

        menu.addSeparator()
        clear = menu.addAction("Clear canvas")
        clear.triggered.connect(self._clear)
        menu.exec(screen_pos)

    def _show_node_menu(self, item: NodeItem, screen_pos) -> None:
        menu = QMenu()
        edit = menu.addAction("Edit config (JSON)")
        edit.triggered.connect(lambda _=False, n=item: self._edit_node(n))
        menu.addSeparator()
        delete = menu.addAction("Delete node")
        delete.triggered.connect(lambda _=False, n=item: self._delete_node(n))
        menu.exec(screen_pos)

    def _add_node(self, type_name: str, scene_pos: QPointF) -> None:
        self._push_undo()
        from workflows.graph import Node, Port
        node = Node(
            id=uuid.uuid4().hex[:10],
            type=type_name,
            label=type_name.split(".")[-1].title(),
            inputs=[Port(name="in")],
            outputs=[Port(name="out")],
            position={"x": scene_pos.x(), "y": scene_pos.y()},
        )
        self.workflow.nodes.append(node)
        ni = NodeItem(node)
        self.addItem(ni)
        self._node_items[node.id] = ni

    def _delete_node(self, item: NodeItem) -> None:
        self._push_undo()
        nid = item.node.id
        self.workflow.nodes = [n for n in self.workflow.nodes if n.id != nid]
        self.workflow.edges = [e for e in self.workflow.edges
                                if e.src_node != nid and e.dst_node != nid]
        # Drop edge items for this node.
        kept = []
        for ei in self._edge_items:
            if ei.src is item or ei.dst is item:
                self.removeItem(ei)
            else:
                kept.append(ei)
        self._edge_items = kept
        self.removeItem(item)
        self._node_items.pop(nid, None)

    def _edit_node(self, item: NodeItem) -> None:
        text, ok = QInputDialog.getMultiLineText(
            None, "Edit config",
            f"Config JSON for node {item.node.id} ({item.node.type}):",
            json.dumps(item.node.config, indent=2),
        )
        if not ok:
            return
        try:
            new_config = json.loads(text)
        except Exception as ex:
            QMessageBox.warning(None, "Invalid JSON", str(ex))
            return
        if new_config != item.node.config:
            self._push_undo()
            item.node.config = new_config
            item.update()

    def _clear(self) -> None:
        from workflows.graph import Workflow
        self._push_undo()
        self.workflow = Workflow(id=uuid.uuid4().hex[:10],
                                  name="Untitled workflow")
        self._render_workflow()


# ---------------------------------------------------------------------------
class _CanvasView(QGraphicsView):
    """QGraphicsView subclass with Ctrl+Wheel zoom + middle-mouse pan.

    Zoom range clamped to 0.25x..3x so the canvas can't be lost. Middle
    mouse drag pans the viewport; release returns to the rubber-band
    selection drag mode the toolbar configures.
    """
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self._zoom_min = 0.25
        self._zoom_max = 3.0
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # Required so keyPressEvent fires on click — QGraphicsView
        # doesn't take focus by default.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, ev):
        from PyQt6.QtCore import Qt as _Qt
        key = ev.key()
        mods = ev.modifiers()
        scene = self.scene()
        if scene is None:
            super().keyPressEvent(ev); return

        # Ctrl+Z / Ctrl+Shift+Z — undo / redo
        if mods & _Qt.KeyboardModifier.ControlModifier and key == _Qt.Key.Key_Z:
            if mods & _Qt.KeyboardModifier.ShiftModifier:
                scene.redo()
            else:
                scene.undo()
            ev.accept(); return

        # Ctrl+Y — alternative redo (Windows convention)
        if mods & _Qt.KeyboardModifier.ControlModifier and key == _Qt.Key.Key_Y:
            scene.redo()
            ev.accept(); return

        # Delete / Backspace — drop selected nodes
        if key in (_Qt.Key.Key_Delete, _Qt.Key.Key_Backspace):
            n = scene.delete_selected()
            if n:
                ev.accept(); return

        # Ctrl+D — duplicate selected node(s)
        if mods & _Qt.KeyboardModifier.ControlModifier and key == _Qt.Key.Key_D:
            from PyQt6.QtWidgets import QGraphicsItem  # noqa: F401
            items = [it for it in scene.selectedItems()
                     if hasattr(it, "node")]
            if items:
                # Deselect originals so duplicates become the selection.
                for it in items:
                    it.setSelected(False)
                for it in items:
                    new = scene.duplicate_node(it)
                    if new is not None:
                        new.setSelected(True)
                ev.accept(); return

        # Ctrl+A — select all nodes
        if mods & _Qt.KeyboardModifier.ControlModifier and key == _Qt.Key.Key_A:
            for it in scene._node_items.values():
                it.setSelected(True)
            ev.accept(); return

        # Arrow keys — nudge selected. Shift = 5x step.
        step = 1 if not (mods & _Qt.KeyboardModifier.ShiftModifier) else 5
        unit = 8 * step
        nudge = {
            _Qt.Key.Key_Left:  (-unit, 0),
            _Qt.Key.Key_Right: ( unit, 0),
            _Qt.Key.Key_Up:    (0, -unit),
            _Qt.Key.Key_Down:  (0,  unit),
        }
        if key in nudge:
            scene.nudge_selected(*nudge[key])
            ev.accept(); return

        super().keyPressEvent(ev)

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = ev.angleDelta().y()
            factor = 1.15 if delta > 0 else (1 / 1.15)
            new_zoom = self._zoom * factor
            new_zoom = max(self._zoom_min, min(self._zoom_max, new_zoom))
            if abs(new_zoom - self._zoom) > 1e-3:
                applied = new_zoom / self._zoom
                self.scale(applied, applied)
                self._zoom = new_zoom
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            # Synthesize a left-press so ScrollHandDrag actually starts.
            from PyQt6.QtGui import QMouseEvent
            fake = QMouseEvent(
                ev.type(), ev.position(), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, ev.modifiers(),
            )
            super().mousePressEvent(fake)
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            from PyQt6.QtGui import QMouseEvent
            fake = QMouseEvent(
                ev.type(), ev.position(), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, ev.modifiers(),
            )
            super().mouseReleaseEvent(fake)
            return
        super().mouseReleaseEvent(ev)


class _Minimap(QWidget):
    """Bird's-eye overview anchored bottom-right of the canvas.

    Renders every NodeItem as a tiny filled rect at its scaled position
    plus a viewport-rect indicator that follows the main view's scroll
    + zoom. Click in the minimap to recenter the main view on that
    point. v0.40 keeps it visual-first; drag-to-pan is a v0.41 nice-to-
    have.
    """
    def __init__(self, scene: "CanvasScene", view: "_CanvasView", parent=None):
        super().__init__(parent)
        self._scene = scene
        self._view = view
        self.setFixedSize(192, 128)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          False)
        # Repaint when the main view scrolls or zooms — we hook the
        # scrollbars + just trigger update on every frame the parent
        # repaints (cheap for ~10 nodes).
        try:
            view.horizontalScrollBar().valueChanged.connect(self.update)
            view.verticalScrollBar().valueChanged.connect(self.update)
        except Exception:
            pass

    def paintEvent(self, _ev):
        from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # Background card.
            p.fillRect(self.rect(),
                       QColor(T["bgRaised"]))
            p.setPen(QPen(QColor(T["line"]), 1))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

            sr = self._scene.sceneRect()
            if sr.width() <= 0 or sr.height() <= 0:
                return
            # Scale scene → minimap, preserving aspect.
            sx = (self.width() - 8) / sr.width()
            sy = (self.height() - 8) / sr.height()
            scale = min(sx, sy)
            ox = (self.width() - sr.width() * scale) / 2
            oy = (self.height() - sr.height() * scale) / 2

            # Nodes.
            p.setPen(QPen(QColor(T["accent"]), 1))
            p.setBrush(QBrush(QColor(T["accent"])))
            for ni in self._scene._node_items.values():
                br = ni.boundingRect()
                pos = ni.pos()
                x = ox + (pos.x() - sr.left()) * scale
                y = oy + (pos.y() - sr.top()) * scale
                w = max(2, br.width() * scale)
                h = max(2, br.height() * scale)
                p.drawRect(QRectF(x, y, w, h))

            # Viewport rect — what the main view is currently showing.
            view = self._view
            view_rect_scene = view.mapToScene(view.viewport().rect()
                                              ).boundingRect()
            vx = ox + (view_rect_scene.x() - sr.left()) * scale
            vy = oy + (view_rect_scene.y() - sr.top()) * scale
            vw = view_rect_scene.width() * scale
            vh = view_rect_scene.height() * scale
            p.setPen(QPen(QColor(T["accent"]), 1.5))
            p.setBrush(QBrush(QColor(0, 0, 0, 0)))
            p.drawRect(QRectF(vx, vy, vw, vh))
        finally:
            p.end()

    def mousePressEvent(self, ev):
        # Click → recenter main view on that scene point.
        sr = self._scene.sceneRect()
        if sr.width() <= 0 or sr.height() <= 0:
            return
        sx = (self.width() - 8) / sr.width()
        sy = (self.height() - 8) / sr.height()
        scale = min(sx, sy)
        ox = (self.width() - sr.width() * scale) / 2
        oy = (self.height() - sr.height() * scale) / 2
        scene_x = sr.left() + (ev.position().x() - ox) / scale
        scene_y = sr.top() + (ev.position().y() - oy) / scale
        self._view.centerOn(scene_x, scene_y)
        self.update()


class WorkflowCanvas(QWidget):
    """Top-level page widget — toolbar + QGraphicsView + scene."""

    workflow_saved = pyqtSignal(str)

    def __init__(self, *, router=None, tool_engine=None, manager=None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("studioPage")
        self.router = router
        self.tool_engine = tool_engine
        self.manager = manager

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header.
        head = QWidget()
        hh = QVBoxLayout(head)
        hh.setContentsMargins(40, 32, 40, 12)
        hh.setSpacing(4)
        cap = QLabel("WORKFLOWS · NODE CANVAS")
        cap.setObjectName("studioMonoCap")
        hh.addWidget(cap)
        h1 = QLabel("Workflows")
        h1.setObjectName("studioH1")
        hh.addWidget(h1)
        v.addWidget(head)

        # Toolbar.
        tb = QHBoxLayout()
        tb.setContentsMargins(40, 0, 40, 8)
        tb.setSpacing(SPACE["sm"])
        self._name_lbl = QLabel("Untitled workflow")
        self._name_lbl.setObjectName("studioH2")
        tb.addWidget(self._name_lbl)
        tb.addStretch(1)
        self.btn_rename = QPushButton("Rename")
        self.btn_rename.setObjectName("studioChip")
        self.btn_rename.clicked.connect(self._rename)
        tb.addWidget(self.btn_rename)
        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("studioChip")
        self.btn_save.clicked.connect(self._save)
        tb.addWidget(self.btn_save)
        self.btn_load = QPushButton("Open")
        self.btn_load.setObjectName("studioChip")
        self.btn_load.clicked.connect(self._open)
        tb.addWidget(self.btn_load)
        self.btn_run = QPushButton("Run")
        self.btn_run.setObjectName("primaryButton")
        self.btn_run.clicked.connect(self._run)
        tb.addWidget(self.btn_run)
        # Undo / redo (Ctrl+Z / Ctrl+Shift+Z also wired in _CanvasView).
        self.btn_undo = QPushButton("↶")
        self.btn_undo.setObjectName("studioChip")
        self.btn_undo.setFixedWidth(28)
        self.btn_undo.setToolTip("Undo · Ctrl+Z")
        self.btn_undo.clicked.connect(lambda: self.scene.undo())
        tb.addWidget(self.btn_undo)
        self.btn_redo = QPushButton("↷")
        self.btn_redo.setObjectName("studioChip")
        self.btn_redo.setFixedWidth(28)
        self.btn_redo.setToolTip("Redo · Ctrl+Shift+Z")
        self.btn_redo.clicked.connect(lambda: self.scene.redo())
        tb.addWidget(self.btn_redo)
        # Zoom controls.
        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setObjectName("studioChip")
        self.btn_zoom_out.setFixedWidth(28)
        self.btn_zoom_out.setToolTip("Zoom out · Ctrl-wheel")
        self.btn_zoom_out.clicked.connect(lambda: self._zoom_step(1 / 1.15))
        tb.addWidget(self.btn_zoom_out)
        self.btn_zoom_fit = QPushButton("Fit")
        self.btn_zoom_fit.setObjectName("studioChip")
        self.btn_zoom_fit.setToolTip("Zoom to fit (1×)")
        self.btn_zoom_fit.clicked.connect(self._zoom_fit)
        tb.addWidget(self.btn_zoom_fit)
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setObjectName("studioChip")
        self.btn_zoom_in.setFixedWidth(28)
        self.btn_zoom_in.setToolTip("Zoom in · Ctrl-wheel")
        self.btn_zoom_in.clicked.connect(lambda: self._zoom_step(1.15))
        tb.addWidget(self.btn_zoom_in)
        tb_w = QWidget(); tb_w.setLayout(tb)
        v.addWidget(tb_w)

        # The canvas.
        self.scene = CanvasScene()
        self.view = _CanvasView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setStyleSheet(
            f"QGraphicsView {{ background:{T['bg']}; border:none; }}")
        v.addWidget(self.view, 1)

        # Minimap — child of the view's viewport so it floats above
        # the scene at the bottom-right corner regardless of scroll.
        self.minimap = _Minimap(self.scene, self.view, self.view.viewport())
        self._reposition_minimap()
        # Repaint minimap on scene mutations (cheap; ~10 nodes).
        try:
            self.scene.changed.connect(lambda _r=None: self.minimap.update())
        except Exception:
            pass

        # Empty-state hint — only shown if no nodes.
        self._hint = QLabel(
            "Right-click anywhere to add a node. "
            "Drag from a node's right slot to another node's left slot to wire."
        )
        self._hint.setObjectName("studioMonoMuted")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet("padding:8px;")
        v.addWidget(self._hint)

    # ------------------------------------------------------------------
    def _reposition_minimap(self) -> None:
        if not getattr(self, "minimap", None):
            return
        vp = self.view.viewport()
        margin = 16
        x = max(0, vp.width() - self.minimap.width() - margin)
        y = max(0, vp.height() - self.minimap.height() - margin)
        self.minimap.move(x, y)
        self.minimap.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._reposition_minimap()

    # ------------------------------------------------------------------
    def _zoom_step(self, factor: float) -> None:
        new_zoom = self.view._zoom * factor
        new_zoom = max(self.view._zoom_min, min(self.view._zoom_max, new_zoom))
        if abs(new_zoom - self.view._zoom) < 1e-3:
            return
        applied = new_zoom / self.view._zoom
        self.view.scale(applied, applied)
        self.view._zoom = new_zoom

    def _zoom_fit(self) -> None:
        applied = 1.0 / self.view._zoom
        self.view.scale(applied, applied)
        self.view._zoom = 1.0

    def _rename(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Rename workflow", "Workflow name:",
            text=self.scene.workflow.name or "")
        if ok and name.strip():
            self.scene.workflow.name = name.strip()
            self._name_lbl.setText(self.scene.workflow.name)

    def _save(self) -> None:
        try:
            from workflows import save_workflow
            path = save_workflow(self.scene.workflow)
            self.workflow_saved.emit(str(path))
            QMessageBox.information(self, "Saved",
                f"Saved {self.scene.workflow.name} to:\n{path}")
        except Exception as ex:
            QMessageBox.warning(self, "Save failed",
                f"{type(ex).__name__}: {ex}")

    def _open(self) -> None:
        try:
            from workflows.library import list_workflows, load_workflow
            wfs = list_workflows() or []
        except Exception as ex:
            QMessageBox.warning(self, "Library unavailable", str(ex))
            return
        if not wfs:
            QMessageBox.information(self, "No saved workflows",
                "Save one with Save first.")
            return
        names = [getattr(w, "name", "") or getattr(w, "id", "") for w in wfs]
        choice, ok = QInputDialog.getItem(self, "Open workflow",
            "Choose:", names, 0, False)
        if not ok or not choice:
            return
        for w in wfs:
            if (getattr(w, "name", "") == choice
                or getattr(w, "id", "") == choice):
                self.scene.workflow = w
                self.scene._render_workflow()
                self._name_lbl.setText(getattr(w, "name", "") or "Untitled")
                return

    def _run(self) -> None:
        if self.router is None or self.tool_engine is None or self.manager is None:
            QMessageBox.information(self, "Run unavailable",
                "Workflow runner needs router + tools + manager. Save and "
                "run from the legacy list view, or relaunch ArchHub.")
            return
        try:
            from workflows import WorkflowExecutor
            executor = WorkflowExecutor(self.router, self.tool_engine, self.manager)
            inputs = {p.name: p.default for p in
                      getattr(self.scene.workflow, "inputs", [])}
            executor.run(self.scene.workflow, inputs=inputs)
            QMessageBox.information(self, "Workflow running",
                "Run started — watch the status bar for completion.")
        except Exception as ex:
            QMessageBox.warning(self, "Run failed",
                f"{type(ex).__name__}: {ex}")
