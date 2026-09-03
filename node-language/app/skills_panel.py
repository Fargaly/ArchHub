"""Skills panel — discover, browse, run, edit, and delete saved Skills.

The Skills panel is the user-facing surface of the skills package. It shows
each Skill as a card with its intent, examples, tags, and usage stats. From
here the user can run a Skill, edit its metadata, view the underlying
Workflow JSON, or delete the Skill.

The Workflow JSON tab is preserved (advanced view) for power users who want
to wire skills by hand or audit what a captured chat became.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

import skills
from workflows import (
    list_workflows, load_workflow, save_workflow, delete_workflow, Workflow,
)


SKILL_FILE_FILTER = "ArchHub Skill (*.archhub-workflow.json);;JSON (*.json);;All files (*)"


# ---------------------------------------------------------------------------
class SkillCard(QFrame):
    """One Skill rendered as a clickable card."""

    run_clicked = pyqtSignal(str)              # skill_id
    delete_clicked = pyqtSignal(str)
    edit_clicked = pyqtSignal(str)
    share_clicked = pyqtSignal(str)
    export_clicked = pyqtSignal(str)

    def __init__(self, skill: dict, usage: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("skillCard")
        self.skill = skill

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(skill["name"])
        title.setObjectName("skillCardTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        scope_badge = QLabel(skill.get("library", "user"))
        scope_badge.setObjectName("skillCardBadge")
        title_row.addWidget(scope_badge)
        v.addLayout(title_row)

        if skill.get("intent"):
            intent = QLabel(skill["intent"])
            intent.setObjectName("skillCardIntent")
            intent.setWordWrap(True)
            v.addWidget(intent)

        tags = skill.get("tags") or []
        if tags:
            tag_row = QLabel(" · ".join(tags))
            tag_row.setObjectName("skillCardTags")
            v.addWidget(tag_row)

        examples = skill.get("examples") or []
        if examples:
            ex_label = QLabel("Examples:")
            ex_label.setObjectName("skillCardSection")
            v.addWidget(ex_label)
            for ex in examples[:2]:
                line = QLabel(f"  “{ex.get('prompt','')}”")
                line.setObjectName("skillCardExample")
                line.setWordWrap(True)
                v.addWidget(line)

        runs = usage.get("runs") or 0
        if runs:
            successes = usage.get("successes") or 0
            rate = f"{int(100 * successes / runs)}%" if runs else "—"
            last = usage.get("last_used") or ""
            last_str = ""
            if last:
                try:
                    dt = datetime.fromisoformat(last)
                    last_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass
            stats = QLabel(f"Runs: {runs} · Success: {rate}"
                           + (f" · Last: {last_str}" if last_str else ""))
            stats.setObjectName("skillCardStats")
            v.addWidget(stats)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch(1)

        share_btn = QPushButton("Share")
        share_btn.setObjectName("ghostButton")
        share_btn.setToolTip("Copy this Skill's JSON to the clipboard so you can paste it elsewhere.")
        share_btn.clicked.connect(lambda: self.share_clicked.emit(skill["id"]))
        action_row.addWidget(share_btn)

        export_btn = QPushButton("Export")
        export_btn.setObjectName("ghostButton")
        export_btn.setToolTip("Save this Skill as a .archhub-workflow.json file.")
        export_btn.clicked.connect(lambda: self.export_clicked.emit(skill["id"]))
        action_row.addWidget(export_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setObjectName("ghostButton")
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(skill["id"]))
        action_row.addWidget(edit_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("ghostButton")
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(skill["id"]))
        action_row.addWidget(delete_btn)

        run_btn = QPushButton("▶  Run")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(lambda: self.run_clicked.emit(skill["id"]))
        action_row.addWidget(run_btn)

        v.addLayout(action_row)


# ---------------------------------------------------------------------------
class SkillsPanel(QDialog):
    """Modal dialog with two tabs: Skills (cards) and Workflows (raw JSON)."""

    skill_run_requested = pyqtSignal(str, dict)        # (skill_id, inputs)
    workflow_run_requested = pyqtSignal(str, dict)     # (workflow_id, inputs)

    def __init__(self, router, tool_engine, manager, parent=None):
        super().__init__(parent)
        self.router = router
        self.tool_engine = tool_engine
        self.manager = manager
        self.setWindowTitle("ArchHub — Skills")
        self.setObjectName("panel")
        self.resize(900, 640)
        # Accept drag-drop of .archhub-workflow.json files anywhere on the panel.
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.setObjectName("skillsTabs")
        self.tabs.addTab(self._build_skills_tab(), "Skills")
        self.tabs.addTab(self._build_workflows_tab(), "Workflows")
        outer.addWidget(self.tabs, 1)

        self._refresh_skills()
        self._refresh_workflows()

    # ---- header ------------------------------------------------------------

    def _build_header(self) -> QWidget:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(24, 22, 24, 18); v.setSpacing(4)
        t = QLabel("Skills"); t.setObjectName("panelTitle")
        s = QLabel(
            "Reusable, AI-assisted shortcuts for the things you do every day. "
            "Run from chat by name, or let ArchHub propose one when it spots "
            "your intent."
        )
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        v.addWidget(t); v.addWidget(s)
        return hf

    # ---- skills tab --------------------------------------------------------

    def _build_skills_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(12)

        # Top action row
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.refresh_skills_btn = QPushButton("↻ Refresh")
        self.refresh_skills_btn.setObjectName("ghostButton")
        self.refresh_skills_btn.clicked.connect(self._refresh_skills)
        actions.addWidget(self.refresh_skills_btn)
        actions.addStretch(1)

        self.import_clip_btn = QPushButton("Paste from clipboard")
        self.import_clip_btn.setObjectName("ghostButton")
        self.import_clip_btn.setToolTip("Import a Skill JSON copied from another machine or chat.")
        self.import_clip_btn.clicked.connect(self._on_import_from_clipboard)
        actions.addWidget(self.import_clip_btn)

        self.import_file_btn = QPushButton("Import file…")
        self.import_file_btn.setObjectName("ghostButton")
        self.import_file_btn.setToolTip("Import a .archhub-workflow.json file from disk.")
        self.import_file_btn.clicked.connect(self._on_import_from_file)
        actions.addWidget(self.import_file_btn)

        v.addLayout(actions)

        # Scrollable card grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._skills_container = QWidget()
        self._skills_layout = QVBoxLayout(self._skills_container)
        self._skills_layout.setContentsMargins(0, 0, 0, 0)
        self._skills_layout.setSpacing(12)
        self._skills_layout.addStretch(1)
        scroll.setWidget(self._skills_container)
        v.addWidget(scroll, 1)

        return page

    def _refresh_skills(self) -> None:
        # Clear existing cards (leave the trailing stretch).
        while self._skills_layout.count() > 1:
            item = self._skills_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        items = skills.list_skills()
        if not items:
            empty = QLabel(
                "No Skills yet. Have a useful chat, then type "
                "`/skill save` to capture it."
            )
            empty.setObjectName("panelEmptyState")
            empty.setWordWrap(True)
            self._skills_layout.insertWidget(0, empty)
            return

        for item in items:
            usage = skills.get_usage(item["id"])
            card = SkillCard(item, usage)
            card.run_clicked.connect(self._on_run_skill)
            card.delete_clicked.connect(self._on_delete_skill)
            card.edit_clicked.connect(self._on_edit_skill)
            card.share_clicked.connect(self._on_share_skill)
            card.export_clicked.connect(self._on_export_skill)
            self._skills_layout.insertWidget(self._skills_layout.count() - 1, card)

    def _on_run_skill(self, skill_id: str) -> None:
        wf = skills.load_skill(skill_id)
        if wf is None:
            return
        inputs = self._collect_inputs(wf)
        if inputs is None:
            return
        self.skill_run_requested.emit(skill_id, inputs)
        self.accept()

    def _on_delete_skill(self, skill_id: str) -> None:
        item = next((s for s in skills.list_skills() if s["id"] == skill_id), None)
        if item is None:
            return
        if QMessageBox.question(
            self, "Delete Skill",
            f"Delete '{item['name']}' permanently?",
        ) != QMessageBox.StandardButton.Yes:
            return
        skills.delete_skill(skill_id)
        self._refresh_skills()

    def _on_edit_skill(self, skill_id: str) -> None:
        wf = skills.load_skill(skill_id)
        if wf is None:
            return
        # Switch to the Workflows tab and open this one for editing.
        self.tabs.setCurrentIndex(1)
        # Pre-fill the JSON view.
        self.json_view.setPlainText(wf.to_json())
        self.detail_label.setText(f"<b>{wf.name}</b> — editing as JSON")

    def _on_share_skill(self, skill_id: str) -> None:
        """Copy the Skill JSON to the system clipboard."""
        try:
            text = skills.export_skill_to_string(skill_id)
        except Exception as ex:
            QMessageBox.warning(self, "Could not share Skill", str(ex))
            return
        QGuiApplication.clipboard().setText(text)
        item = next((s for s in skills.list_skills() if s["id"] == skill_id), None)
        name = item["name"] if item else skill_id
        QMessageBox.information(
            self, "Copied to clipboard",
            f"'{name}' copied as JSON.\n\n"
            f"Paste anywhere to share — into a chat, an email, or onto another "
            f"ArchHub machine via the Skills panel's “Paste from clipboard”.",
        )

    def _on_export_skill(self, skill_id: str) -> None:
        """Save the Skill JSON to a user-chosen file."""
        item = next((s for s in skills.list_skills() if s["id"] == skill_id), None)
        if item is None:
            return
        from workflows.library import _slug
        default_name = f"{_slug(item['name'])}.archhub-workflow.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Skill", default_name, SKILL_FILE_FILTER
        )
        if not path:
            return
        try:
            written = skills.export_skill_to_file(skill_id, Path(path))
        except Exception as ex:
            QMessageBox.warning(self, "Export failed", str(ex))
            return
        QMessageBox.information(
            self, "Exported", f"Saved to:\n{written}"
        )

    def _on_import_from_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text or not text.strip():
            QMessageBox.information(
                self, "Clipboard empty",
                "Copy a Skill's JSON first, then click Paste from clipboard.",
            )
            return
        self._import_text(text, source="clipboard")

    def _on_import_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Skill", "", SKILL_FILE_FILTER
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception as ex:
            QMessageBox.warning(self, "Cannot read file", str(ex))
            return
        self._import_text(text, source=path)

    def _import_text(self, text: str, *, source: str) -> None:
        try:
            wf = skills.import_skill_from_string(text)
        except skills.SkillImportError as ex:
            QMessageBox.warning(self, "Import failed", str(ex))
            return
        except Exception as ex:
            QMessageBox.warning(self, "Import failed",
                                f"Unexpected error: {type(ex).__name__}: {ex}")
            return
        self._refresh_skills()
        QMessageBox.information(
            self, "Skill imported",
            f"Imported '{wf.name}' from {source}.\n\n"
            f"It now appears in your Skills library and the matcher can find it.",
        )

    # ---- drag and drop ----------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        # Files first — drag a .archhub-workflow.json onto the panel.
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    try:
                        text = path.read_text(encoding="utf-8")
                    except Exception as ex:
                        QMessageBox.warning(self, "Cannot read file", str(ex))
                        continue
                    self._import_text(text, source=str(path))
            event.acceptProposedAction()
            return
        # Plain text drop — treat it as raw JSON paste.
        if mime.hasText():
            text = mime.text()
            if skills.looks_like_skill_json(text):
                self._import_text(text, source="dropped text")
                event.acceptProposedAction()
                return
        event.ignore()

    # ---- workflows tab (raw JSON, advanced) -------------------------------

    def _build_workflows_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(8)

        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(1)

        left = QWidget()
        lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 8, 0); lv.setSpacing(8)
        self.wf_list = QListWidget()
        self.wf_list.setObjectName("workflowList")
        self.wf_list.itemSelectionChanged.connect(self._on_select_workflow)
        lv.addWidget(self.wf_list)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(8, 0, 0, 0); rv.setSpacing(8)
        self.detail_label = QLabel("Select a workflow.")
        self.detail_label.setObjectName("connectorStatus")
        self.detail_label.setWordWrap(True)
        rv.addWidget(self.detail_label)
        self.json_view = QTextEdit()
        self.json_view.setObjectName("messageText")
        self.json_view.setPlaceholderText("(workflow JSON appears here when you select one)")
        rv.addWidget(self.json_view, 1)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        v.addWidget(split, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.refresh_wf_btn = QPushButton("↻ Refresh")
        self.refresh_wf_btn.setObjectName("ghostButton")
        self.refresh_wf_btn.clicked.connect(self._refresh_workflows)
        actions.addWidget(self.refresh_wf_btn)
        actions.addStretch(1)
        self.delete_wf_btn = QPushButton("Delete")
        self.delete_wf_btn.setObjectName("ghostButton")
        self.delete_wf_btn.clicked.connect(self._on_delete_workflow)
        self.delete_wf_btn.setEnabled(False)
        actions.addWidget(self.delete_wf_btn)
        self.save_wf_btn = QPushButton("Save edits")
        self.save_wf_btn.setObjectName("ghostButton")
        self.save_wf_btn.clicked.connect(self._on_save_workflow_json)
        self.save_wf_btn.setEnabled(False)
        actions.addWidget(self.save_wf_btn)
        self.run_wf_btn = QPushButton("▶ Run")
        self.run_wf_btn.setObjectName("primaryButton")
        self.run_wf_btn.clicked.connect(self._on_run_workflow)
        self.run_wf_btn.setEnabled(False)
        actions.addWidget(self.run_wf_btn)
        v.addLayout(actions)

        return page

    def _refresh_workflows(self) -> None:
        from PyQt6.QtWidgets import QListWidgetItem
        self.wf_list.clear()
        for item in list_workflows():
            li = QListWidgetItem(item["name"])
            li.setData(Qt.ItemDataRole.UserRole, item)
            self.wf_list.addItem(li)

    def _selected_workflow(self) -> Optional[dict]:
        cur = self.wf_list.currentItem()
        return cur.data(Qt.ItemDataRole.UserRole) if cur else None

    def _on_select_workflow(self) -> None:
        item = self._selected_workflow()
        if item is None:
            self.detail_label.setText("Select a workflow.")
            self.json_view.clear()
            self.delete_wf_btn.setEnabled(False)
            self.save_wf_btn.setEnabled(False)
            self.run_wf_btn.setEnabled(False)
            return
        wf = load_workflow(Path(item["path"]))
        desc = wf.description or "(no description)"
        self.detail_label.setText(
            f"<b>{wf.name}</b><br>{desc}<br>"
            f"<i>{len(wf.nodes)} nodes, {len(wf.edges)} edges</i>"
        )
        self.json_view.setPlainText(wf.to_json())
        self.delete_wf_btn.setEnabled(True)
        self.save_wf_btn.setEnabled(True)
        self.run_wf_btn.setEnabled(True)

    def _on_save_workflow_json(self) -> None:
        item = self._selected_workflow()
        if not item:
            return
        try:
            wf = Workflow.from_json(self.json_view.toPlainText())
        except Exception as ex:
            QMessageBox.warning(self, "Invalid JSON", f"Could not parse: {ex}")
            return
        errors = wf.validate()
        if errors:
            QMessageBox.warning(
                self, "Workflow has errors",
                "\n".join(errors[:6]) + ("\n…" if len(errors) > 6 else ""),
            )
            return
        save_workflow(wf)
        self._refresh_workflows()
        self._refresh_skills()

    def _on_delete_workflow(self) -> None:
        item = self._selected_workflow()
        if not item:
            return
        if QMessageBox.question(
            self, "Delete workflow",
            f"Delete '{item['name']}' permanently?",
        ) != QMessageBox.StandardButton.Yes:
            return
        delete_workflow(item["id"])
        self._refresh_workflows()
        self._refresh_skills()
        self._on_select_workflow()

    def _on_run_workflow(self) -> None:
        item = self._selected_workflow()
        if not item:
            return
        wf = load_workflow(Path(item["path"]))
        inputs = self._collect_inputs(wf)
        if inputs is None:
            return
        self.workflow_run_requested.emit(wf.id, inputs)
        self.accept()

    # ---- shared helpers ----------------------------------------------------

    def _collect_inputs(self, wf: Workflow) -> Optional[dict]:
        """Prompt for each required workflow input. Cancel returns None."""
        inputs: dict = {}
        for p in wf.inputs:
            text, ok = QInputDialog.getText(
                self, f"Input: {p.name}",
                p.description or p.name,
                text=str(p.default or ""),
            )
            if not ok:
                return None
            inputs[p.name] = text
        return inputs
