"""ArchHub chat window — the main user interface.

Looks like a modern AI chat app: conversation in the centre, model picker
and connector status in the header, input bar at the bottom. Tool calls
render as collapsible cards inline with the conversation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer
from PyQt6.QtGui import QAction, QFont, QTextCursor, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from connector_panel import ConnectorPanel
from llm_router import LLMRouter, LLMResponse, ROUTE_AUTO, KNOWN_MODELS
from manager import ConnectorManager
from settings_dialog import SettingsDialog
from tool_engine import ToolEngine, ToolInvocation


# ---------------------------------------------------------------------------
@dataclass
class ChatMessage:
    role: str                          # "user" | "assistant" | "system"
    content: str
    tool_invocations: list[ToolInvocation] = field(default_factory=list)
    model: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
#  LLM worker — runs the router on a background thread, emits signals.
# ---------------------------------------------------------------------------
class _LLMWorker(QObject):
    chunk = pyqtSignal(str)
    tool_invoked = pyqtSignal(object)         # ToolInvocation
    finished = pyqtSignal(object)             # LLMResponse
    failed = pyqtSignal(str)

    def __init__(self, router: LLMRouter, history: list[ChatMessage], model: str):
        super().__init__()
        self.router = router
        self.history = history
        self.model = model
        self._stop = False

    def run(self) -> None:
        try:
            def on_chunk(text: str) -> None:
                if self._stop: return
                self.chunk.emit(text)

            def on_tool(inv: ToolInvocation) -> None:
                if self._stop: return
                self.tool_invoked.emit(inv)

            history_dicts = [
                {"role": m.role, "content": m.content,
                 "tool_invocations": [inv.to_dict() for inv in m.tool_invocations]}
                for m in self.history
            ]
            response = self.router.complete(
                history_dicts,
                model=self.model,
                on_chunk=on_chunk,
                on_tool_invocation=on_tool,
            )
            self.finished.emit(response)
        except Exception as ex:
            self.failed.emit(f"{type(ex).__name__}: {ex}")

    def stop(self) -> None:
        self._stop = True


# ---------------------------------------------------------------------------
#  Tool invocation card — collapsible inline card for tool calls.
# ---------------------------------------------------------------------------
class ToolCard(QFrame):
    def __init__(self, invocation: ToolInvocation, parent=None):
        super().__init__(parent)
        self.setObjectName("toolCard")
        self.invocation = invocation
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("▸")
        self.toggle_btn.setObjectName("toolCardChevron")
        self.toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self.toggle_btn)

        title = QLabel(f"<b>{invocation.tool_name}</b>")
        title.setObjectName("toolCardTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.status_label = QLabel(invocation.status)
        self.status_label.setObjectName("toolCardStatus")
        header.addWidget(self.status_label)
        outer.addLayout(header)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setObjectName("toolCardDetail")
        self.detail.setMinimumHeight(0)
        self.detail.setMaximumHeight(0)
        self.detail.setVisible(False)
        outer.addWidget(self.detail)

        self.refresh()

    def refresh(self) -> None:
        self.status_label.setText(self.invocation.status)
        if self._expanded:
            args = self.invocation.arguments or {}
            result = self.invocation.result or {}
            text = "ARGS\n" + str(args)[:2000] + "\n\nRESULT\n" + str(result)[:2000]
            self.detail.setPlainText(text)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.toggle_btn.setText("▾" if self._expanded else "▸")
        self.detail.setVisible(self._expanded)
        self.detail.setMaximumHeight(280 if self._expanded else 0)
        self.refresh()


# ---------------------------------------------------------------------------
#  Message bubble.
# ---------------------------------------------------------------------------
class MessageBubble(QFrame):
    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.setObjectName("userBubble" if role == "user" else "assistantBubble")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)

        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setObjectName("messageText")
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.document().setDocumentMargin(0)
        self.text_view.textChanged.connect(self._adjust_height)
        v.addWidget(self.text_view)

        self.tool_cards_container = QVBoxLayout()
        self.tool_cards_container.setContentsMargins(0, 0, 0, 0)
        self.tool_cards_container.setSpacing(6)
        v.addLayout(self.tool_cards_container)

    def append_text(self, fragment: str) -> None:
        cur = self.text_view.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(fragment)
        self.text_view.setTextCursor(cur)
        self._adjust_height()

    def set_text(self, text: str) -> None:
        self.text_view.setPlainText(text)
        self._adjust_height()

    def _adjust_height(self) -> None:
        doc = self.text_view.document()
        doc.setTextWidth(self.text_view.viewport().width())
        h = int(doc.size().height()) + 4
        self.text_view.setFixedHeight(max(20, h))

    def add_tool_card(self, invocation: ToolInvocation) -> ToolCard:
        card = ToolCard(invocation)
        self.tool_cards_container.addWidget(card)
        return card


# ---------------------------------------------------------------------------
#  Main window.
# ---------------------------------------------------------------------------
class ChatWindow(QMainWindow):
    def __init__(self, router: LLMRouter, manager: ConnectorManager, tools: ToolEngine):
        super().__init__()
        self.router = router
        self.manager = manager
        self.tools = tools

        self.history: list[ChatMessage] = []
        self._current_bubble: Optional[MessageBubble] = None
        self._current_invocations: dict[str, tuple[ToolInvocation, ToolCard]] = {}

        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[_LLMWorker] = None

        self.setWindowTitle("ArchHub")
        self.resize(960, 720)
        self.setMinimumSize(720, 520)

        self._build_ui()
        self._refresh_status()

        # Periodic connector refresh every 30s (background)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(30000)
        self._refresh_timer.timeout.connect(self._refresh_status)
        self._refresh_timer.start()

    # ---- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_conversation_area(), 1)
        outer.addWidget(self._build_input_bar())
        outer.addWidget(self._build_status_bar())

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 10, 14, 10)
        h.setSpacing(10)

        title = QLabel("ArchHub")
        title.setObjectName("brand")
        h.addWidget(title)
        h.addStretch(1)

        self.model_picker = QComboBox()
        self.model_picker.setObjectName("modelPicker")
        self.model_picker.addItem("Auto · best model per task", ROUTE_AUTO)
        for model_id, label in KNOWN_MODELS:
            self.model_picker.addItem(label, model_id)
        h.addWidget(self.model_picker)

        connectors_btn = QPushButton("Connectors")
        connectors_btn.setObjectName("ghostButton")
        connectors_btn.clicked.connect(self._open_connectors)
        h.addWidget(connectors_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("ghostButton")
        settings_btn.setFixedWidth(38)
        settings_btn.clicked.connect(self._open_settings)
        h.addWidget(settings_btn)

        return bar

    def _build_conversation_area(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("conversationScroll")

        self.conv_container = QWidget()
        self.conv_layout = QVBoxLayout(self.conv_container)
        self.conv_layout.setContentsMargins(28, 22, 28, 22)
        self.conv_layout.setSpacing(14)
        self.conv_layout.addStretch(1)
        scroll.setWidget(self.conv_container)

        self.scroll_area = scroll
        self._show_welcome()
        return scroll

    def _show_welcome(self) -> None:
        welcome = QFrame()
        welcome.setObjectName("welcomeCard")
        w = QVBoxLayout(welcome)
        w.setContentsMargins(28, 26, 28, 26)
        w.setSpacing(8)

        title = QLabel("What do you want to build?")
        title.setObjectName("welcomeTitle")
        w.addWidget(title)

        sub = QLabel(
            "ArchHub connects you to your AEC tools. Toggle the ones you have, then tell me what to do.\n"
            "Examples: \"Add a 6m wall in the Revit project\", \"Pull the latest model from Speckle\","
            " \"Render the active 3ds Max scene\"."
        )
        sub.setObjectName("welcomeSubtitle")
        sub.setWordWrap(True)
        w.addWidget(sub)

        self.conv_layout.insertWidget(self.conv_layout.count() - 1, welcome)
        self._welcome_widget = welcome

    def _build_input_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("inputBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 12, 20, 14)
        h.setSpacing(10)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Message ArchHub… (Enter to send, Shift+Enter for newline)")
        self.input.setObjectName("inputField")
        self.input.returnPressed.connect(self._on_send)
        h.addWidget(self.input, 1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.clicked.connect(self._on_send)
        h.addWidget(self.send_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setVisible(False)
        h.addWidget(self.stop_btn)

        return bar

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 6, 18, 6)
        h.setSpacing(10)

        self.status_left = QLabel("")
        self.status_left.setObjectName("statusText")
        h.addWidget(self.status_left)
        h.addStretch(1)

        self.status_right = QLabel("")
        self.status_right.setObjectName("statusText")
        h.addWidget(self.status_right)
        return bar

    # ---- Send / receive ----------------------------------------------------

    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()

        if hasattr(self, "_welcome_widget") and self._welcome_widget is not None:
            self._welcome_widget.deleteLater()
            self._welcome_widget = None

        self._add_user_message(text)
        self._start_assistant_response()

    def _add_user_message(self, text: str) -> None:
        msg = ChatMessage(role="user", content=text)
        self.history.append(msg)
        self._render_message(msg)

    def _start_assistant_response(self) -> None:
        # Reserve a streaming bubble
        msg = ChatMessage(role="assistant", content="", model=self.model_picker.currentData())
        self.history.append(msg)
        self._current_bubble = self._render_message(msg)
        self._current_invocations.clear()

        # Spin up worker thread
        self.send_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.input.setEnabled(False)

        # Pass a snapshot of history WITHOUT the empty assistant message
        snapshot = self.history[:-1]
        worker = _LLMWorker(self.router, snapshot, self.model_picker.currentData())
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_chunk)
        worker.tool_invoked.connect(self._on_tool_invoked)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self.worker = worker
        self.worker_thread = thread
        thread.start()

    def _on_chunk(self, fragment: str) -> None:
        if self._current_bubble is None: return
        self._current_bubble.append_text(fragment)
        self.history[-1].content += fragment
        self._scroll_to_bottom()

    def _on_tool_invoked(self, invocation: ToolInvocation) -> None:
        if self._current_bubble is None: return
        if invocation.id in self._current_invocations:
            inv, card = self._current_invocations[invocation.id]
            inv.status = invocation.status
            inv.result = invocation.result
            card.refresh()
        else:
            card = self._current_bubble.add_tool_card(invocation)
            self._current_invocations[invocation.id] = (invocation, card)
            self.history[-1].tool_invocations.append(invocation)
        self._scroll_to_bottom()

    def _on_finished(self, response: LLMResponse) -> None:
        self._reset_input_state()
        if response.routing_note:
            self.status_left.setText(response.routing_note)

    def _on_failed(self, msg: str) -> None:
        self._reset_input_state()
        if self._current_bubble is not None:
            self._current_bubble.append_text(f"\n\n[Error] {msg}")
            self.history[-1].content += f"\n\n[Error] {msg}"

    def _on_stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        self._reset_input_state()

    def _reset_input_state(self) -> None:
        self.send_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.input.setEnabled(True)
        self.input.setFocus()
        self._current_bubble = None
        self.worker = None
        self.worker_thread = None

    # ---- Rendering ---------------------------------------------------------

    def _render_message(self, msg: ChatMessage) -> MessageBubble:
        row = QFrame()
        row.setObjectName("messageRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)

        bubble = MessageBubble(msg.role)
        bubble.set_text(msg.content)
        for inv in msg.tool_invocations:
            bubble.add_tool_card(inv)

        if msg.role == "user":
            h.addStretch(1)
            h.addWidget(bubble, 0)
        else:
            h.addWidget(bubble, 0)
            h.addStretch(1)

        bubble.setMaximumWidth(720)
        bubble.setMinimumWidth(280)

        self.conv_layout.insertWidget(self.conv_layout.count() - 1, row)
        QTimer.singleShot(0, self._scroll_to_bottom)
        return bubble

    def _scroll_to_bottom(self) -> None:
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---- Misc --------------------------------------------------------------

    def _refresh_status(self) -> None:
        self.manager.refresh()
        active = [e for e in self.manager.entries if e.state.name == "ACTIVE"]
        ready  = [e for e in self.manager.entries if e.state.name == "READY"]
        if active:
            names = ", ".join(e.display_name for e in active)
            self.status_left.setText(f"Live: {names}")
        else:
            self.status_left.setText(f"{len(ready)} tools detected · open Connectors to enable")

        if self.router.has_credentials():
            providers = ", ".join(self.router.configured_providers())
            self.status_right.setText(f"LLM: {providers}")
        else:
            self.status_right.setText("Add API keys in Settings to start chatting")

    def _open_connectors(self) -> None:
        dlg = ConnectorPanel(self.manager, self)
        dlg.exec()
        self._refresh_status()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.router, self)
        dlg.exec()
        self._refresh_status()

    def show_centered(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def closeEvent(self, ev) -> None:
        # Hide to tray instead of quitting
        ev.ignore()
        self.hide()
