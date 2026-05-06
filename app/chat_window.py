"""ArchHub chat window — the main user interface.

Looks like a modern AI chat app: conversation in the centre, model picker
and connector status in the header, input bar at the bottom. Tool calls
render as collapsible cards inline with the conversation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer
from PyQt6.QtGui import QAction, QFont, QTextCursor, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QScrollBar,
    QSizePolicy, QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from connector_panel import ConnectorPanel
from llm_router import LLMRouter, LLMResponse, ROUTE_AUTO, KNOWN_MODELS, ollama_models
from manager import ConnectorManager, ConnectorState
from parameters_panel import ParametersPanel
from session import Session, StepStatus
import session_runner
from settings_dialog import SettingsDialog
from tool_engine import ToolEngine, ToolInvocation
from workflows import chat_to_workflow, save_workflow, load_workflow, get_workflow, WorkflowExecutor
from workflows_panel import WorkflowsPanel
from skills_panel import SkillsPanel
from update_dialog import UpdateDialog
import skills


# ---------------------------------------------------------------------------
@dataclass
class ChatMessage:
    role: str                          # "user" | "assistant" | "system"
    content: str
    tool_invocations: list[ToolInvocation] = field(default_factory=list)
    images: list[str] = field(default_factory=list)   # absolute file paths
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
                 "tool_invocations": [inv.to_dict() for inv in m.tool_invocations],
                 "images": list(m.images)}
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
#  Session worker — runs session_runner functions on a background thread.
# ---------------------------------------------------------------------------
class _SessionWorker(QObject):
    """Runs session_runner functions on a background thread."""
    event_received = pyqtSignal(dict)
    finished = pyqtSignal()

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._stop = False

    def run(self) -> None:
        def on_event(ev: dict) -> None:
            if self._stop: return
            self.event_received.emit(ev)
        try:
            self._fn(*self._args, on_event=on_event, **self._kwargs)
        except Exception as ex:
            self.event_received.emit({"type": "step_error", "error": str(ex)})
        finally:
            self.finished.emit()

    def stop(self) -> None:
        self._stop = True

# ---------------------------------------------------------------------------
#  Custom QLineEdit that intercepts Ctrl+V to detect clipboard images.
# ---------------------------------------------------------------------------
class _PasteInput(QLineEdit):
    image_pasted = pyqtSignal(str)   # emits temp file path

    def keyPressEvent(self, event) -> None:
        if (event.key() == Qt.Key.Key_V and
                event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime.hasImage():
                img = clipboard.image()
                if not img.isNull():
                    import tempfile, os
                    renders_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "ArchHub" / "renders"
                    renders_dir.mkdir(parents=True, exist_ok=True)
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False,
                        dir=str(renders_dir)
                    )
                    tmp.close()
                    img.save(tmp.name)
                    self.image_pasted.emit(tmp.name)
                    return
        super().keyPressEvent(event)


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

        # Live parametric session — drives the sidebar and persists across turns.
        self.session: Session = Session()
        self._pasted_images: list[str] = []

        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[_LLMWorker] = None

        self.setWindowTitle("ArchHub")
        self.resize(1200, 760)
        self.setMinimumSize(880, 560)

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

        # Body splits horizontally: chat on the left, parameters sidebar on the right.
        body_split = QSplitter(Qt.Orientation.Horizontal)
        body_split.setHandleWidth(1)
        body_split.setChildrenCollapsible(False)

        # Left: conversation + input bar stacked vertically
        left = QWidget()
        left_v = QVBoxLayout(left); left_v.setContentsMargins(0, 0, 0, 0); left_v.setSpacing(0)
        left_v.addWidget(self._build_conversation_area(), 1)
        left_v.addWidget(self._build_input_bar())

        # Right: parameters panel, bound to the live session
        self.parameters_panel = ParametersPanel()
        self.parameters_panel.set_session(self.session)
        self.parameters_panel.parameter_edited.connect(self._on_parameter_edited)

        body_split.addWidget(left)
        body_split.addWidget(self.parameters_panel)
        body_split.setStretchFactor(0, 3)
        body_split.setStretchFactor(1, 1)
        body_split.setSizes([840, 320])

        outer.addWidget(body_split, 1)
        outer.addWidget(self._build_status_bar())

    def _build_header(self) -> QWidget:
        """Slim header: brand + model picker + single menu button.
        All secondary actions live in the menu so the eye is drawn to chat,
        not the chrome."""
        bar = QFrame()
        bar.setObjectName("header")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 12, 16, 12)
        h.setSpacing(12)

        title = QLabel("ArchHub")
        title.setObjectName("brand")
        h.addWidget(title)
        h.addStretch(1)

        self.model_picker = QComboBox()
        self.model_picker.setObjectName("modelPicker")
        self._populate_model_picker()
        h.addWidget(self.model_picker)

        # Single menu button — everything that used to be a header button
        # is now a labelled item in this menu, with the running version
        # surfaced inline so the user can see it at a glance.
        self.menu_btn = QToolButton()
        self.menu_btn.setObjectName("menuButton")
        self.menu_btn.setText("⚙")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_btn.setFixedSize(40, 36)
        self.menu_btn.setToolTip("Settings, connectors, skills, updates")
        self.menu_btn.setMenu(self._build_app_menu())
        h.addWidget(self.menu_btn)

        return bar

    def _build_app_menu(self) -> QMenu:
        """The single dropdown that holds every secondary action."""
        menu = QMenu(self)
        menu.setObjectName("appMenu")

        # Connections + sign-ins
        sign_in_action = menu.addAction("🔑   Sign-ins…")
        sign_in_action.triggered.connect(self._open_settings)
        connectors_action = menu.addAction("🔌   Connectors…")
        connectors_action.triggered.connect(self._open_connectors)

        menu.addSeparator()

        # Skills + sessions
        skills_action = menu.addAction("✦   Skills…")
        skills_action.triggered.connect(self._open_skills_panel)
        sessions_action = menu.addAction("📂  Sessions…")
        sessions_action.triggered.connect(self._open_sessions)
        save_chat_action = menu.addAction("⇣   Save chat as Skill…")
        save_chat_action.triggered.connect(self._save_chat_as_skill)

        menu.addSeparator()

        # Updates + about
        self._update_menu_action = menu.addAction(self._update_menu_label())
        self._update_menu_action.triggered.connect(self._open_update_dialog)

        about_action = menu.addAction("ⓘ   About ArchHub")
        about_action.triggered.connect(self._show_about)

        menu.addSeparator()
        quit_action = menu.addAction("⏻   Quit")
        quit_action.triggered.connect(QApplication.instance().quit)

        return menu

    def _update_menu_label(self) -> str:
        try:
            import updater
            status = updater.check_for_updates()
            commit = (status.local_commit or "")[:7]
            if status.has_updates:
                return f"↻   Update available  ·  {commit} → new"
            if commit:
                return f"↻   Up to date  ·  {commit}"
        except Exception:
            pass
        return "↻   Check for updates…"

    def _show_about(self) -> None:
        try:
            import updater
            status = updater.check_for_updates()
            commit = status.local_commit or "unknown"
            branch = status.branch or "unknown"
            remote = status.remote_url or "(no remote)"
        except Exception:
            commit = branch = remote = "unknown"
        QMessageBox.information(
            self, "About ArchHub",
            f"<h3>ArchHub</h3>"
            f"<p>Parametric design environment for architects with chat as "
            f"the input surface and AI as the construction agent.</p>"
            f"<p style='color:#8a8a8c;font-size:11px;'>"
            f"Commit:  <code>{commit}</code><br>"
            f"Branch:  <code>{branch}</code><br>"
            f"Remote:  <code>{remote}</code></p>",
        )

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
        w.setContentsMargins(32, 28, 32, 28)
        w.setSpacing(12)

        title = QLabel("What do you want to build?")
        title.setObjectName("welcomeTitle")
        w.addWidget(title)

        sub = QLabel(
            "Type what you want; ArchHub drives the tools.  "
            "Connectors, sign-ins, and skills live behind the menu in the top right."
        )
        sub.setObjectName("welcomeSubtitle")
        sub.setWordWrap(True)
        w.addWidget(sub)

        # Quick-start chips: top 3 saved Skills, surfaced as one-click buttons.
        try:
            top_skills = skills.list_skills()[:3]
        except Exception:
            top_skills = []

        if top_skills:
            chip_label = QLabel("Try a saved Skill:")
            chip_label.setObjectName("welcomeSubtitle")
            w.addSpacing(6)
            w.addWidget(chip_label)

            chip_row = QHBoxLayout()
            chip_row.setSpacing(8)
            chip_row.setContentsMargins(0, 0, 0, 0)
            for s in top_skills:
                chip = QPushButton(f"  ✦  {s['name']}")
                chip.setObjectName("welcomeChip")
                chip.setToolTip(s.get("intent", ""))
                chip.clicked.connect(
                    lambda _checked=False, sid=s["id"]:
                    self._run_skill_by_id(sid, {"prompt": ""})
                )
                chip_row.addWidget(chip)
            chip_row.addStretch(1)
            chip_wrap = QFrame()
            chip_wrap.setLayout(chip_row)
            w.addWidget(chip_wrap)

        self.conv_layout.insertWidget(self.conv_layout.count() - 1, welcome)
        self._welcome_widget = welcome

    def _build_input_bar(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setObjectName("inputBar")
        v = QVBoxLayout(wrapper)
        v.setContentsMargins(20, 8, 20, 14)
        v.setSpacing(4)

        # Image preview bar (hidden by default)
        self._preview_bar = QFrame()
        self._preview_bar.setObjectName("imagePreviewBar")
        self._preview_bar.setVisible(False)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        preview_scroll.setFixedHeight(72)
        preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_inner = QWidget()
        self._preview_layout = QHBoxLayout(self._preview_inner)
        self._preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_layout.setSpacing(6)
        self._preview_layout.addStretch(1)
        preview_scroll.setWidget(self._preview_inner)
        pb_layout = QVBoxLayout(self._preview_bar)
        pb_layout.setContentsMargins(0, 0, 0, 0)
        pb_layout.addWidget(preview_scroll)
        v.addWidget(self._preview_bar)

        # Input row
        h = QHBoxLayout()
        h.setSpacing(10)

        attach_btn = QPushButton("\U0001f4ce")
        attach_btn.setObjectName("ghostButton")
        attach_btn.setFixedWidth(36)
        attach_btn.setToolTip("Attach image file")
        attach_btn.clicked.connect(self._on_attach_image)
        h.addWidget(attach_btn)

        self.input = _PasteInput()
        self.input.setPlaceholderText("Message ArchHub… (Enter to send, Ctrl+V to paste image)")
        self.input.setObjectName("inputField")
        self.input.returnPressed.connect(self._on_send)
        self.input.image_pasted.connect(self._on_image_pasted)
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

        v.addLayout(h)
        return wrapper

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
        images = list(self._pasted_images)
        if not text and not images:
            return
        self.input.clear()
        self._pasted_images.clear()
        self._refresh_preview_bar()

        if hasattr(self, "_welcome_widget") and self._welcome_widget is not None:
            self._welcome_widget.deleteLater()
            self._welcome_widget = None

        if text or images:
            # The user message owns its attached images so the LLM call
            # carries them in the corresponding history entry, and so the
            # bubble can render thumbnails next to the prompt.
            self._add_user_message(text or "(image attached)", images=images)

        if text:
            # Slash commands intercept before the LLM path.
            if text.startswith("/") and self._handle_slash_command(text):
                return

            # Pre-flight: if the prompt clearly targets a host whose connector
            # isn't active, stop here and tell the user. Avoids the LLM
            # falling back to "here's some code, paste it yourself".
            if self._block_if_required_connector_inactive(text):
                return

            # Skill matcher: if a saved Skill clearly fits this prompt,
            # propose running it before the LLM regenerates from scratch.
            if self._propose_skill_match(text):
                return

        if images:
            # Render the thumbnails inside the just-added user bubble.
            self._show_user_images(images)
        self._start_assistant_response()

    # ---- pre-flight intent guard ------------------------------------------

    # Vocabulary that strongly signals "this needs <host>". Keep tight to
    # avoid false positives on conversational text.
    _HOST_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
        "revit": ("revit", "wall", "walls", "door", "doors", "window", "windows",
                  "level", "levels", "room", "rooms", "family", "families",
                  "sheet", "sheets", "schedule", "rvt", "ifc",
                  "dimension", "annotate", "annotation", "tag", "tags"),
        "autocad": ("autocad", "acad", "dwg", "polyline", "block", "xref"),
        "max": ("3ds max", "3dsmax", "max script", "maxscript", "pymxs"),
        "blender": ("blender", "bpy", "extrude", "modifier", "render"),
        "speckle": ("speckle", "stream", "commit"),
    }
    # Generic verbs that, on their own, indicate the user wants ACTION (not chat).
    # Combined with no host hint and no active modelling connector → still warn.
    _ACTION_VERBS: tuple[str, ...] = (
        "create", "make", "build", "add", "place", "draw", "model",
        "generate", "delete", "remove", "move", "rotate", "scale",
    )

    def _block_if_required_connector_inactive(self, text: str) -> bool:
        """Return True if the prompt obviously needs a connector that is OFF
        or unreachable, and we already wrote a guard message. Caller should
        NOT continue.

        Two-level check:
          (a) connector enabled in ConnectorManager (state == ACTIVE)
          (b) host application actually reachable (ping its HTTP endpoint)

        Both must be true before the LLM is allowed to drive the host. Without
        (b) the LLM hits a tool error and falls back to dumping code into chat,
        which is exactly the experience ArchHub exists to prevent.
        """
        lower = text.lower()
        active = self._active_connector_families()

        for host, kws in self._HOST_INTENT_KEYWORDS.items():
            if not any(kw in lower for kw in kws):
                continue
            if host not in active:
                self._add_assistant_note(
                    f"⚠️ This looks like a **{host.title()}** action, but "
                    f"the {host.title()} connector isn't active.\n\n"
                    f"Open **Connectors** (header), enable {host.title()}, "
                    f"then make sure {host.title()} is running on this "
                    f"machine. I'll never paste code for you to copy — "
                    f"once the connector is live I'll execute the action "
                    f"directly."
                )
                return True
            if not self._host_reachable(host):
                self._add_assistant_note(
                    f"⚠️ The {host.title()} connector is enabled, but "
                    f"{host.title()} isn't running (or its ArchHub addin "
                    f"hasn't loaded).\n\n"
                    f"Open {host.title()}, wait until the project is loaded, "
                    f"then ask me again. I'll execute the action directly — "
                    f"never by pasting code for you to copy."
                )
                return True
            return False

        # No host keyword. If it's an action verb and NO modelling connector
        # is active at all, we still warn so the LLM doesn't hallucinate code.
        modelling_hosts = {"revit", "autocad", "max", "blender"}
        if (active.isdisjoint(modelling_hosts)
                and any(v in lower for v in self._ACTION_VERBS)):
            self._add_assistant_note(
                "⚠️ No modelling connector is active. To execute actions in "
                "Revit / AutoCAD / 3ds Max / Blender, enable the matching "
                "connector first via the **Connectors** button in the header, "
                "and have that application open.\n\n"
                "I won't paste code for you to copy — that's the whole point "
                "of ArchHub. Once the connector is live, ask again and I'll "
                "do it directly."
            )
            return True
        return False

    # Per-host ping URL. None = no probe (treat as always reachable).
    _HOST_PING_URL: dict[str, Optional[str]] = {
        "revit":   "http://localhost:48884/ping",
        "autocad": "http://localhost:48885/ping",
        "max":     "http://localhost:48886/max-mcp/ping",
        "blender": "http://localhost:9876/ping",
        # Speckle is cloud-only; treat it as always reachable.
        "speckle": None,
    }

    def _host_reachable(self, host: str) -> bool:
        """Cheap reachability probe. Direct HTTP with a 1-second timeout so
        the chat input never blocks waiting for a host that's not running."""
        url = self._HOST_PING_URL.get(host)
        if url is None:
            return True
        import urllib.request, urllib.error
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            return False
        except Exception:
            return False

    def _on_attach_image(self) -> None:
        """Open a file dialog to attach image files."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach Images", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)"
        )
        for path in paths:
            self._on_image_pasted(path)

    def _on_image_pasted(self, path: str) -> None:
        self._pasted_images.append(path)
        self._refresh_preview_bar()

    def _refresh_preview_bar(self) -> None:
        """Rebuild image thumbnails in the preview bar."""
        from PyQt6.QtGui import QPixmap
        # Remove all thumbnail widgets (leave the trailing stretch)
        while self._preview_layout.count() > 1:
            item = self._preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for path in self._pasted_images:
            cell = QFrame()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.setSpacing(2)

            thumb = QLabel()
            px = QPixmap(path)
            if not px.isNull():
                px = px.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            thumb.setPixmap(px)
            thumb.setFixedSize(56, 56)
            cell_layout.addWidget(thumb)

            remove_btn = QPushButton("x")
            remove_btn.setFixedHeight(14)
            remove_btn.setObjectName("ghostButton")
            remove_btn.clicked.connect(lambda checked, p=path: self._remove_pasted_image(p))
            cell_layout.addWidget(remove_btn)

            self._preview_layout.insertWidget(self._preview_layout.count() - 1, cell)

        self._preview_bar.setVisible(bool(self._pasted_images))

    def _remove_pasted_image(self, path: str) -> None:
        self._pasted_images = [p for p in self._pasted_images if p != path]
        self._refresh_preview_bar()

    def _show_user_images(self, paths: list[str]) -> None:
        """Show user-attached image thumbnails in a user bubble."""
        from PyQt6.QtGui import QPixmap
        row = QFrame()
        row.setObjectName("messageRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)

        bubble = QFrame()
        bubble.setObjectName("userBubble")
        bubble.setMaximumWidth(720)
        bh = QHBoxLayout(bubble)
        bh.setContentsMargins(14, 10, 14, 10)
        bh.setSpacing(6)

        for path in paths:
            lbl = QLabel()
            px = QPixmap(path)
            if not px.isNull():
                px = px.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            lbl.setPixmap(px)
            bh.addWidget(lbl)

        h.addStretch(1)
        h.addWidget(bubble, 0)
        self.conv_layout.insertWidget(self.conv_layout.count() - 1, row)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _start_session_response(self, text: str, images: list) -> None:
        """Route a user message through the session pipeline."""
        # Reserve a streaming bubble for the assistant response
        msg = ChatMessage(role="assistant", content="", model=self.model_picker.currentData())
        self.history.append(msg)
        self._current_bubble = self._render_message(msg)
        self._current_invocations.clear()

        self.send_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.input.setEnabled(False)

        worker = _SessionWorker(
            session_runner.run_from_prompt,
            text, images, self.session, self.router, self.manager
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_received.connect(self._on_session_event)
        worker.finished.connect(self._reset_input_state)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self.worker = worker
        self.worker_thread = thread
        thread.start()

    def _on_session_event(self, ev: dict) -> None:
        """Handle events from session_runner running on background thread."""
        ev_type = ev.get("type", "")

        if ev_type == "progress":
            msg = ev.get("message", "")
            self.status_left.setText(msg)

        elif ev_type == "response":
            text = ev.get("text", "")
            if self._current_bubble and text:
                self._current_bubble.set_text(text)
                if self.history:
                    self.history[-1].content = text

        elif ev_type == "image":
            path = ev.get("path", "")
            if path and self._current_bubble:
                self._show_image_in_chat(path)

        elif ev_type == "step_error":
            error = ev.get("error", "Unknown error")
            if self._current_bubble:
                existing = self.history[-1].content if self.history else ""
                error_text = (existing + "\n\n" if existing else "") + f"⚠️ {error}"
                self._current_bubble.set_text(error_text)
                if self.history:
                    self.history[-1].content = error_text

        elif ev_type == "done":
            self.status_left.setText("")

        self._scroll_to_bottom()

    def _show_image_in_chat(self, path: str) -> None:
        """Show a render image in the conversation."""
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtWidgets import QLabel
        if not self._current_bubble:
            return
        try:
            label = QLabel()
            px = QPixmap(path)
            if not px.isNull():
                px = px.scaledToWidth(min(680, px.width()),
                                      Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(px)
                label.setObjectName("renderImage")
                self._current_bubble.tool_cards_container.addWidget(label)
                self._scroll_to_bottom()
        except Exception:
            pass

    def _on_parameter_edited(self, name: str, value) -> None:
        """Called when user drags a slider. Debounce → rerun dirty steps."""
        self.session.update_parameter(name, value)
        # Restart the 300ms debounce timer
        if not hasattr(self, "_rerun_timer"):
            self._rerun_timer = QTimer(self)
            self._rerun_timer.setSingleShot(True)
            self._rerun_timer.timeout.connect(self._start_rerun_dirty)
        self._rerun_timer.start(300)

    def _start_rerun_dirty(self) -> None:
        """Start re-running dirty steps after a parameter edit."""
        dirty = [s for s in self.session.chain if s.status == StepStatus.DIRTY]
        if not dirty:
            return
        # Add a new assistant bubble for the rerun output
        msg = ChatMessage(role="assistant", content="Re-rendering…",
                          model=self.model_picker.currentData())
        self.history.append(msg)
        self._current_bubble = self._render_message(msg)

        self.send_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.input.setEnabled(False)

        worker = _SessionWorker(
            session_runner.rerun_dirty,
            self.session, self.router, self.manager
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_received.connect(self._on_session_event)
        worker.finished.connect(self._reset_input_state)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self.worker = worker
        self.worker_thread = thread
        thread.start()

    def _add_user_message(self, text: str, *, images: Optional[list[str]] = None) -> None:
        msg = ChatMessage(role="user", content=text, images=list(images or []))
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
        dlg = ConnectorPanel(self.manager, self, router=self.router)
        dlg.exec()
        self._refresh_status()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.router, self)
        dlg.exec()
        self._refresh_status()

    def _open_workflows(self) -> None:
        # Legacy entry point — Skills panel hosts the workflow editor now.
        self._open_skills_panel()

    def _save_chat_as_workflow(self) -> None:
        if not self.history:
            QMessageBox.information(self, "Nothing to save",
                                    "Have a conversation first, then save it as a workflow.")
            return
        # Use the first user message as the default name
        first_user = next((m.content for m in self.history if m.role == "user"), "")
        default_name = (first_user[:60] or f"Workflow {len(self.history)} turns").strip()
        name, ok = QInputDialog.getText(self, "Save as workflow",
                                        "Workflow name:", text=default_name)
        if not ok or not name.strip():
            return
        wf = chat_to_workflow(self.history, name=name.strip(),
                              model=self.model_picker.currentData())
        path = save_workflow(wf)
        QMessageBox.information(
            self, "Workflow saved",
            f"Saved as '{wf.name}'.\n\nLocation:\n{path}\n\n"
            f"Open Workflows to run it again or set a trigger.",
        )

    # ---- Skills: slash commands, matcher, capture -------------------------

    def _handle_slash_command(self, text: str) -> bool:
        """Return True if the slash command was handled and no further chat
        flow should run. False = unknown, fall through to LLM."""
        parts = text.strip().split(maxsplit=2)
        cmd = parts[0].lower() if parts else ""
        sub = parts[1].lower() if len(parts) > 1 else ""
        rest = parts[2] if len(parts) > 2 else ""

        if cmd == "/skill":
            if sub in ("save", "capture"):
                self._save_chat_as_skill(requested_name=rest or None)
                return True
            if sub in ("list", "ls"):
                self._show_skills_listing()
                return True
            if sub == "run":
                self._run_skill_from_prompt(rest)
                return True
            if sub == "share":
                self._share_skill_to_clipboard(rest)
                return True
            if sub == "import":
                self._import_skill_from_clipboard()
                return True
            if sub in ("", "help"):
                self._add_assistant_note(
                    "Skill commands:\n"
                    "  /skill save [name]    — save this conversation as a Skill\n"
                    "  /skill list           — show saved Skills\n"
                    "  /skill run <id|name>  — run a Skill\n"
                    "  /skill share <id|name>— copy a Skill's JSON to the clipboard\n"
                    "  /skill import         — import a Skill JSON from the clipboard"
                )
                return True
        if cmd == "/skills":
            self._open_skills_panel()
            return True
        if cmd in ("/help", "/?"):
            self._add_assistant_note(
                "Commands: /skill save | list | run <id>, /skills, /help."
            )
            return True
        return False

    def _add_assistant_note(self, text: str) -> None:
        msg = ChatMessage(role="assistant", content=text,
                          model=self.model_picker.currentData())
        self.history.append(msg)
        self._render_message(msg)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _propose_skill_match(self, prompt: str) -> bool:
        """If a Skill matches strongly, propose it as an inline suggestion.
        Returns True if user is being prompted (caller should NOT continue
        to the LLM); False = no strong match, continue normal flow."""
        try:
            active = self._active_connector_families()
            matches = skills.match_skills(
                prompt, top_k=3, min_score=0.45, active_connectors=active
            )
        except Exception:
            return False
        if not matches:
            return False
        top = matches[0]
        # Only propose if the top match is clearly best (gap or absolute high).
        gap_ok = (len(matches) < 2) or (top.score - matches[1].score >= 0.10)
        if top.score < 0.55 and not gap_ok:
            return False
        self._render_skill_suggestion(top, prompt)
        return True

    def _active_connector_families(self) -> set[str]:
        try:
            return {
                e.family for e in self.manager.entries
                if e.state == ConnectorState.ACTIVE
            }
        except Exception:
            return set()

    def _render_skill_suggestion(self, match, prompt: str) -> None:
        """Inline assistant bubble proposing the matched Skill."""
        msg = ChatMessage(
            role="assistant",
            content=(f"💡 **Skill match:** {match.name}\n"
                     f"_{match.intent}_\n\n"
                     f"Run this saved Skill or continue for a fresh response."),
            model=self.model_picker.currentData(),
        )
        self.history.append(msg)
        bubble = self._render_message(msg)

        row = QFrame()
        row.setObjectName("skillSuggestionRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 4, 0, 0)
        h.setSpacing(8)

        run_btn = QPushButton(f"▶  Run “{match.name}”")
        run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(
            lambda _=False, sid=match.skill_id, p=prompt: self._run_skill_by_id(sid, {"prompt": p})
        )
        h.addWidget(run_btn)

        skip_btn = QPushButton("Skip — answer fresh")
        skip_btn.setObjectName("ghostButton")
        skip_btn.clicked.connect(self._start_assistant_response)
        h.addWidget(skip_btn)
        h.addStretch(1)

        bubble.tool_cards_container.addWidget(row)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _save_chat_as_skill(self, *, requested_name=None) -> None:
        if len(self.history) < 2:
            QMessageBox.information(
                self, "Nothing to capture",
                "Have a conversation first — at least one user prompt and one "
                "assistant response — then save it as a Skill.",
            )
            return
        try:
            wf, meta, path = skills.capture_chat_as_skill(
                self.history, router=self.router,
                requested_name=requested_name,
            )
        except Exception as ex:
            QMessageBox.warning(self, "Could not capture Skill", str(ex))
            return
        self._add_assistant_note(
            f"✓ Saved as Skill **{wf.name}**.\n"
            f"Intent: {meta.intent}\n"
            f"Keywords: {', '.join(meta.keywords) or '(none)'}\n"
            f"File: {path}"
        )

    def _show_skills_listing(self) -> None:
        items = skills.list_skills()
        if not items:
            self._add_assistant_note("No Skills saved yet. Run /skill save after a useful conversation.")
            return
        lines = ["**Saved Skills:**"]
        for s in items[:20]:
            lines.append(f"- `{s['id'][:8]}` **{s['name']}** — {s['intent']}")
        self._add_assistant_note("\n".join(lines))

    def _run_skill_from_prompt(self, query: str) -> None:
        """`/skill run <id-prefix-or-name>`."""
        items = skills.list_skills()
        if not items:
            self._add_assistant_note("No Skills saved.")
            return
        q = query.strip().lower()
        if not q:
            self._add_assistant_note("Usage: `/skill run <id-prefix-or-name>`")
            return
        match = next(
            (s for s in items
             if s["id"].lower().startswith(q) or q in s["name"].lower()),
            None,
        )
        if not match:
            self._add_assistant_note(f"No Skill matched `{query}`.")
            return
        self._run_skill_by_id(match["id"], {"prompt": query})

    def _run_skill_by_id(self, skill_id: str, inputs: dict) -> None:
        wf = skills.load_skill(skill_id)
        if wf is None:
            self._add_assistant_note(f"Skill `{skill_id}` not found.")
            return
        announce = f"▶ Running Skill **{wf.name}**"
        msg = ChatMessage(role="assistant", content=announce,
                          model=self.model_picker.currentData())
        self.history.append(msg)
        bubble = self._render_message(msg)

        import time as _time
        t0 = _time.time()
        success = False
        error: str | None = None
        try:
            executor = WorkflowExecutor(self.router, self.tools, self.manager)
            result = executor.run(wf, inputs=inputs or {})
            success = result.success
            summary = "✓ Skill complete." if success else "✗ Skill failed."
            if result.errors:
                summary += "\n" + "\n".join(result.errors[:5])
            if result.outputs:
                ans = result.outputs.get("answer")
                if isinstance(ans, str) and ans:
                    summary += "\n\n" + ans
            bubble.set_text(f"{announce}\n\n{summary}")
            msg.content = bubble.text_view.toPlainText()
        except Exception as ex:
            error = f"{type(ex).__name__}: {ex}"
            bubble.set_text(f"{announce}\n\n[Error] {error}")
            msg.content = bubble.text_view.toPlainText()
        finally:
            elapsed = int((_time.time() - t0) * 1000)
            try:
                skills.record_run(skill_id, success=success,
                                  elapsed_ms=elapsed, error=error)
            except Exception:
                pass

    def _open_skills_panel(self) -> None:
        dlg = SkillsPanel(self.router, self.tools, self.manager, self)
        dlg.skill_run_requested.connect(self._run_skill_by_id)
        dlg.workflow_run_requested.connect(self._run_workflow_by_id)
        dlg.exec()

    def _open_update_dialog(self) -> None:
        dlg = UpdateDialog(self)
        dlg.exec()

    # ---- model picker -----------------------------------------------------

    def _populate_model_picker(self) -> None:
        """Fill the model dropdown. Cloud-first: local Ollama models are
        hidden by default — they're slow to launch, heavy on disk, and
        the user said plainly that local is too heavy. The Settings
        toggle 'Show local Ollama models' brings them back when wanted."""
        from PyQt6.QtGui import QStandardItemModel, QStandardItem
        from secrets_store import load_setting

        configured = set(self.router.configured_providers())
        show_local = bool(load_setting("show_local_models"))

        self.model_picker.clear()
        # Replace the underlying model so we can disable individual items.
        item_model = QStandardItemModel(self.model_picker)
        self.model_picker.setModel(item_model)

        def _add(label: str, data: str, *, enabled: bool, tooltip: str = "") -> None:
            item = QStandardItem(label)
            item.setData(data)
            item.setEnabled(enabled)
            if tooltip:
                item.setToolTip(tooltip)
            if not enabled:
                from PyQt6.QtGui import QBrush, QColor
                item.setForeground(QBrush(QColor("#6a6a6c")))
            item_model.appendRow(item)

        _add("Auto · best model per task", ROUTE_AUTO, enabled=True,
             tooltip="ArchHub picks the best available model for each prompt.")

        for model_id, label in KNOWN_MODELS:
            provider = model_id.partition(":")[0]
            ok = provider in configured
            tooltip = ("" if ok
                       else f"{provider.title()} not configured. "
                            f"Sign in via Settings (⚙) to enable.")
            _add(label if ok else f"{label}  (no key)", model_id,
                 enabled=ok, tooltip=tooltip)

        if show_local:
            for model_id, label in ollama_models():
                _add(label, model_id, enabled=True,
                     tooltip="Local model running in Ollama.")

    def _refresh_model_picker(self) -> None:
        """Public hook so SettingsDialog can re-enable models after the user
        adds a key. Preserves the current selection if still valid."""
        current = self.model_picker.currentData()
        self._populate_model_picker()
        if current:
            for i in range(self.model_picker.count()):
                if self.model_picker.itemData(i) == current:
                    self.model_picker.setCurrentIndex(i)
                    break

    # ---- background update check -----------------------------------------

    def _silent_update_check(self) -> None:
        """Fire on launch in a background thread. If updates are available,
        flash a non-modal banner in the status bar and pulse the Update
        button. Never blocks; never pops a dialog without user action."""
        import updater
        from PyQt6.QtCore import QObject, QThread, pyqtSignal

        class _Worker(QObject):
            done = pyqtSignal(object)

            def run(self) -> None:
                try:
                    self.done.emit(updater.check_for_updates())
                except Exception:
                    self.done.emit(None)

        worker = _Worker()
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_silent_update_check_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._update_check_thread = thread
        thread.start()

    def _on_silent_update_check_done(self, status) -> None:
        if status is None or status.error:
            return
        # Refresh the visible version badge regardless.
        if hasattr(self, "update_btn"):
            self.update_btn.setText(self._update_button_label(status))
            self.update_btn.setToolTip(self._update_button_tooltip(status))
        if not status.has_updates:
            return
        # Show a quiet line in the status bar.
        msg = (f"✨ {status.behind} update"
               f"{'s' if status.behind != 1 else ''} available — "
               f"click the ↻ Update button.")
        try:
            self.status_left.setText(msg)
        except Exception:
            pass

    def _update_button_label(self, status=None) -> str:
        """Header button label with current commit suffix so the user can
        always see at a glance which version they're running."""
        if status is None:
            try:
                import updater
                status = updater.check_for_updates()
            except Exception:
                return "↻ Update"
        commit = (status.local_commit or "")[:7]
        if not commit:
            return "↻ Update"
        if status.has_updates:
            return f"↻ Update  ·  {commit} → new"
        return f"↻ Update  ·  {commit}"

    def _update_button_tooltip(self, status=None) -> str:
        if status is None:
            try:
                import updater
                status = updater.check_for_updates()
            except Exception:
                return "Check for and apply the latest ArchHub version."
        if status.error:
            return f"Update check failed: {status.error}"
        if status.has_updates:
            return (f"You're on {status.local_commit} ({status.branch}). "
                    f"{status.behind} update(s) available on {status.remote_url}.")
        return (f"You're on the latest {status.local_commit} ({status.branch}) "
                f"from {status.remote_url}.")

    def _share_skill_to_clipboard(self, query: str) -> None:
        """`/skill share <id|name>` — copy that Skill's JSON to clipboard."""
        items = skills.list_skills()
        if not items:
            self._add_assistant_note("No Skills saved yet.")
            return
        q = (query or "").strip().lower()
        if not q:
            self._add_assistant_note("Usage: `/skill share <id-prefix-or-name>`")
            return
        match = next(
            (s for s in items
             if s["id"].lower().startswith(q) or q in s["name"].lower()),
            None,
        )
        if not match:
            self._add_assistant_note(f"No Skill matched `{query}`.")
            return
        try:
            text = skills.export_skill_to_string(match["id"])
        except Exception as ex:
            self._add_assistant_note(f"Could not export: {ex}")
            return
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
        self._add_assistant_note(
            f"📋 Copied **{match['name']}** to your clipboard ({len(text):,} chars).\n"
            f"Paste it into another ArchHub via `/skill import`, "
            f"or share it however you like — Slack, email, Notion."
        )

    def _import_skill_from_clipboard(self) -> None:
        """`/skill import` — read clipboard, validate, save as Skill."""
        from PyQt6.QtGui import QGuiApplication
        text = QGuiApplication.clipboard().text()
        if not text or not text.strip():
            self._add_assistant_note(
                "Clipboard is empty. Copy a Skill's JSON first."
            )
            return
        if not skills.looks_like_skill_json(text):
            self._add_assistant_note(
                "Clipboard does not look like a Skill JSON. "
                "Copy the full JSON from another ArchHub's `/skill share` output."
            )
            return
        try:
            wf = skills.import_skill_from_string(text)
        except skills.SkillImportError as ex:
            self._add_assistant_note(f"Import failed: {ex}")
            return
        self._add_assistant_note(
            f"✓ Imported Skill **{wf.name}**. The matcher can now find it."
        )

    def _run_workflow_by_id(self, workflow_id: str, inputs: dict) -> None:
        wf = get_workflow(workflow_id)
        if wf is None:
            QMessageBox.warning(self, "Workflow not found",
                                f"Could not load workflow {workflow_id}.")
            return
        executor = WorkflowExecutor(self.router, self.tools, self.manager)
        announce = f"Running workflow: **{wf.name}**"

        # Add an assistant message for the workflow run
        msg = ChatMessage(role="assistant", content=announce,
                          model=self.model_picker.currentData())
        self.history.append(msg)
        bubble = self._render_message(msg)

        try:
            result = executor.run(wf, inputs=inputs)
            summary = "✓ Workflow complete." if result.success else "✗ Workflow failed."
            if result.errors:
                summary += "\n" + "\n".join(result.errors)
            bubble.set_text(f"{announce}\n\n{summary}")
            msg.content = bubble.text_view.toPlainText()
        except Exception as ex:
            bubble.set_text(f"{announce}\n\n[Error] {ex}")
            msg.content = bubble.text_view.toPlainText()

    def _save_session(self) -> None:
        from session_io import save_session
        name, ok = QInputDialog.getText(
            self, "Save session", "Session name:",
            text=f"Session {len(self.session.parameters)} params"
        )
        if not ok or not name.strip():
            return
        try:
            path = save_session(self.session, name.strip())
            QMessageBox.information(self, "Session saved",
                                    f"Saved to:\n{path}")
        except Exception as ex:
            QMessageBox.warning(self, "Save failed", str(ex))

    def _open_sessions(self) -> None:
        """Show a dialog to save current session or open a saved one."""
        from session_io import list_sessions, load_session, save_session
        from PyQt6.QtWidgets import QDialog, QListWidget, QListWidgetItem

        dlg = QDialog(self)
        dlg.setWindowTitle("Sessions")
        dlg.resize(520, 380)
        v = QVBoxLayout(dlg)
        v.setSpacing(10)
        v.setContentsMargins(16, 16, 16, 16)

        # Save current button
        save_btn = QPushButton("💾  Save current session")
        save_btn.clicked.connect(lambda: (dlg.accept(), self._save_session()))
        v.addWidget(save_btn)

        v.addWidget(QLabel("— or open a saved session —"))

        sessions = list_sessions()
        if not sessions:
            v.addWidget(QLabel("No saved sessions yet."))
        else:
            lst = QListWidget()
            for path, name, saved_at in sessions:
                item = QListWidgetItem(f"{name}  ·  {saved_at[:16].replace('T', ' ')}")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                lst.addItem(item)
            v.addWidget(lst, 1)

            open_btn = QPushButton("Open selected")
            def do_open():
                sel = lst.currentItem()
                if sel is None:
                    return
                try:
                    new_session, name = load_session(Path(sel.data(Qt.ItemDataRole.UserRole)))
                    self.session = new_session
                    self.parameters_panel.set_session(self.session)
                    dlg.accept()
                    QMessageBox.information(self, "Session loaded",
                        f"Loaded '{name}' with {len(new_session.parameters)} parameters.")
                except Exception as ex:
                    QMessageBox.warning(dlg, "Load failed", str(ex))
            open_btn.clicked.connect(do_open)
            v.addWidget(open_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.reject)
        v.addWidget(close_btn)
        dlg.exec()

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def show_centered(self) -> None:
        """Restore, raise, and centre the window on the primary screen."""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            self.move(
                geom.x() + (geom.width()  - self.width())  // 2,
                geom.y() + (geom.height() - self.height()) // 2,
            )
        self.showNormal()
        self.raise_()
        self.activateWindow()
        # Silently check for updates on first show. Non-blocking; surfaces a
        # status-bar line if newer commits exist on the remote.
        if not getattr(self, "_update_check_started", False):
            self._update_check_started = True
            QTimer.singleShot(800, self._silent_update_check)
