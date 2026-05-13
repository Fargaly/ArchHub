"""Workflows panel — modal dialog listing saved workflows.

Phase 1 UI: a list of saved workflows with name, description, node count,
and trigger types. Buttons: Run, Edit JSON, Delete. The canvas comes in
phase 3; for now the JSON editor is the editing surface.

TODO(shadow-audit): this module is currently orphan — no code path
instantiates WorkflowsPanel anywhere. The Studio Workflows page uses
WorkflowCanvas, and the chat menu's legacy "Workflows..." item was
removed in v1.3.1. File kept on disk only as documentation of the
underlying Workflow JSON contract (referenced by workflow_canvas.py:5).
Delete after the canvas docs absorb that note.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QTextEdit, QVBoxLayout,
    QWidget, QInputDialog,
)

from workflows import (
    list_workflows, load_workflow, save_workflow, delete_workflow,
    WorkflowExecutor, Workflow,
)


class WorkflowsPanel(QDialog):
    workflow_run_requested = pyqtSignal(str, dict)   # (workflow_id, inputs)

    def __init__(self, router, tool_engine, manager, parent=None):
        super().__init__(parent)
        self.router = router
        self.tool_engine = tool_engine
        self.manager = manager
        self.setWindowTitle("ArchHub — Workflows")
        self.setObjectName("panel")
        self.resize(820, 580)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())

        self._refresh_list()

    # ---- UI ---------------------------------------------------------------

    def _build_header(self) -> QWidget:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(24, 22, 24, 18); v.setSpacing(4)
        t = QLabel("Workflows"); t.setObjectName("panelTitle")
        s = QLabel("Saved chains of LLM and tool calls. Run on demand or on a trigger.")
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        v.addWidget(t); v.addWidget(s)
        return hf

    def _build_body(self) -> QWidget:
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(1)

        # Left: list
        left = QWidget()
        lv = QVBoxLayout(left); lv.setContentsMargins(16, 12, 8, 16); lv.setSpacing(8)
        self.list = QListWidget()
        self.list.setObjectName("workflowList")
        self.list.itemSelectionChanged.connect(self._on_select)
        lv.addWidget(self.list)
        split.addWidget(left)

        # Right: detail + JSON
        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(8, 12, 16, 16); rv.setSpacing(8)
        self.detail_label = QLabel("Select a workflow.")
        self.detail_label.setObjectName("connectorStatus")
        self.detail_label.setWordWrap(True)
        rv.addWidget(self.detail_label)

        self.json_view = QTextEdit()
        self.json_view.setObjectName("messageText")
        self.json_view.setReadOnly(False)
        self.json_view.setPlaceholderText("(workflow JSON appears here when you select one)")
        rv.addWidget(self.json_view, 1)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        return split

    def _build_footer(self) -> QWidget:
        f = QFrame(); f.setObjectName("panelFooter")
        h = QHBoxLayout(f); h.setContentsMargins(20, 12, 20, 14); h.setSpacing(8)

        self.refresh_btn = QPushButton("↻ Refresh"); self.refresh_btn.setObjectName("ghostButton")
        self.refresh_btn.clicked.connect(self._refresh_list)
        h.addWidget(self.refresh_btn)

        h.addStretch(1)

        self.delete_btn = QPushButton("Delete"); self.delete_btn.setObjectName("ghostButton")
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.setEnabled(False)
        h.addWidget(self.delete_btn)

        self.save_json_btn = QPushButton("Save edits"); self.save_json_btn.setObjectName("ghostButton")
        self.save_json_btn.clicked.connect(self._on_save_json)
        self.save_json_btn.setEnabled(False)
        h.addWidget(self.save_json_btn)

        self.run_btn = QPushButton("▶ Run"); self.run_btn.setObjectName("primaryButton")
        self.run_btn.clicked.connect(self._on_run)
        self.run_btn.setEnabled(False)
        h.addWidget(self.run_btn)

        return f

    # ---- behaviour --------------------------------------------------------

    def _refresh_list(self) -> None:
        self.list.clear()
        for item in list_workflows():
            li = QListWidgetItem(item["name"])
            sub = []
            sub.append(f"{item['node_count']} nodes")
            sub.append(", ".join(item.get("trigger_types") or []) or "manual")
            if item.get("updated_at"):
                try:
                    dt = datetime.fromisoformat(item["updated_at"])
                    sub.append(dt.strftime("%Y-%m-%d %H:%M"))
                except Exception: pass
            li.setData(Qt.ItemDataRole.UserRole, item)
            li.setToolTip(" · ".join(sub))
            self.list.addItem(li)

    def _selected_item(self) -> Optional[dict]:
        cur = self.list.currentItem()
        return cur.data(Qt.ItemDataRole.UserRole) if cur else None

    def _on_select(self) -> None:
        item = self._selected_item()
        if item is None:
            self.detail_label.setText("Select a workflow.")
            self.json_view.clear()
            self.delete_btn.setEnabled(False)
            self.save_json_btn.setEnabled(False)
            self.run_btn.setEnabled(False)
            return
        wf = load_workflow(Path(item["path"]))
        desc = wf.description or "(no description)"
        self.detail_label.setText(
            f"<b>{wf.name}</b><br>{desc}<br>"
            f"<i>{len(wf.nodes)} nodes, {len(wf.edges)} edges, "
            f"{len(wf.triggers)} trigger(s)</i>"
        )
        self.json_view.setPlainText(wf.to_json())
        self.delete_btn.setEnabled(True)
        self.save_json_btn.setEnabled(True)
        self.run_btn.setEnabled(True)

    def _on_save_json(self) -> None:
        item = self._selected_item()
        if not item: return
        try:
            wf = Workflow.from_json(self.json_view.toPlainText())
        except Exception as ex:
            QMessageBox.warning(self, "Invalid JSON", f"Could not parse: {ex}")
            return
        errors = wf.validate()
        if errors:
            QMessageBox.warning(self, "Workflow has errors",
                                "\n".join(errors[:6]) +
                                ("\n…" if len(errors) > 6 else ""))
            return
        save_workflow(wf)
        self._refresh_list()

    def _on_delete(self) -> None:
        item = self._selected_item()
        if not item: return
        if QMessageBox.question(self, "Delete workflow",
                                f"Delete '{item['name']}' permanently?") \
                != QMessageBox.StandardButton.Yes:
            return
        delete_workflow(item["id"])
        self._refresh_list()
        self._on_select()

    def _on_run(self) -> None:
        item = self._selected_item()
        if not item: return
        wf = load_workflow(Path(item["path"]))

        # Collect prompts for required workflow inputs (phase 1: simple QInputDialog)
        inputs: dict = {}
        for p in wf.inputs:
            text, ok = QInputDialog.getText(
                self, f"Input: {p.name}",
                p.description or p.name,
                text=str(p.default or ""),
            )
            if not ok:
                return
            inputs[p.name] = text

        # Emit signal so the main window can spawn a non-blocking run + display
        self.workflow_run_requested.emit(wf.id, inputs)
        self.accept()
