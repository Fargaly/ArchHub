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
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QScrollBar, QSizePolicy, QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWidget,
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
# Note: workflows_panel.WorkflowsPanel was imported here historically but is
# no longer instantiated anywhere — the Skills panel hosts workflow editing
# and the Studio shell embeds workflow_canvas.WorkflowCanvas for the
# blueprint view. The module file stays on disk for the JSON-contract docs.
from skills_panel import SkillsPanel
from update_dialog import UpdateDialog
import skills


# ---------------------------------------------------------------------------
# History compression helpers — keep prompts under provider context
# limits when a session has accumulated large tool results.

# Truncate text content above this size when rebuilding history for
# the LLM. The on-disk session keeps the full text; only the prompt
# we re-send gets shortened.
_HISTORY_CONTENT_MAX = 4000        # chars per assistant/user msg
_HISTORY_INV_RESULT_MAX = 2000     # chars per tool result blob


def _compress_content(text: str) -> str:
    if not text:
        return text or ""
    if len(text) <= _HISTORY_CONTENT_MAX:
        return text
    keep = _HISTORY_CONTENT_MAX - 80
    head = text[: int(keep * 0.6)]
    tail = text[-int(keep * 0.4):]
    return (head + "\n\n[…truncated " + str(len(text) - keep)
             + " chars…]\n\n" + tail)


def _compress_inv(inv: "ToolInvocation") -> dict:
    """Cheap clone of inv.to_dict() with the result blob shortened."""
    d = inv.to_dict()
    result = d.get("result")
    if isinstance(result, dict):
        # Keep status + error verbatim; compress every other field
        # whose stringified value exceeds the cap.
        compressed = {}
        for k, v in result.items():
            if k in ("status", "error", "policy"):
                compressed[k] = v
                continue
            sv = v
            try:
                sv_str = str(v) if not isinstance(v, (dict, list)) else repr(v)
            except Exception:
                sv_str = ""
            if isinstance(sv, (dict, list)) and len(repr(sv)) > _HISTORY_INV_RESULT_MAX:
                compressed[k] = (
                    repr(sv)[:_HISTORY_INV_RESULT_MAX]
                    + f" [...truncated; original {len(repr(sv))} chars]"
                )
            elif isinstance(sv, str) and len(sv) > _HISTORY_INV_RESULT_MAX:
                compressed[k] = (
                    sv[:_HISTORY_INV_RESULT_MAX]
                    + f" [...truncated; original {len(sv)} chars]"
                )
            else:
                compressed[k] = sv
        d["result"] = compressed
    elif isinstance(result, str) and len(result) > _HISTORY_INV_RESULT_MAX:
        d["result"] = (
            result[:_HISTORY_INV_RESULT_MAX]
            + f" [...truncated; original {len(result)} chars]"
        )
    return d


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
    reasoning = pyqtSignal(str)              # extended-thinking fragments
    status = pyqtSignal(str)                 # "Thinking…", "Calling tool: ..."
    tool_invoked = pyqtSignal(object)        # ToolInvocation
    finished = pyqtSignal(object)            # LLMResponse
    failed = pyqtSignal(str)

    def __init__(self, router: LLMRouter, history: list[ChatMessage], model: str,
                 session_pin: str | None = None):
        super().__init__()
        self.router = router
        self.history = history
        self.model = model
        self.session_pin = session_pin
        self._stop = False

    def run(self) -> None:
        try:
            self.status.emit("Thinking…")

            def on_chunk(text: str) -> None:
                if self._stop: return
                self.chunk.emit(text)

            def on_reasoning(text: str) -> None:
                if self._stop: return
                self.reasoning.emit(text)

            def on_tool(inv: ToolInvocation) -> None:
                if self._stop: return
                # Surface the tool name in the status line so the user
                # sees what's actually running.
                try:
                    name = getattr(inv, "tool_name", "") or "tool"
                    self.status.emit(f"Calling {name}…")
                except Exception:
                    pass
                self.tool_invoked.emit(inv)

            # Truncate huge tool result blobs before sending history
            # to the LLM. A single outlook_execute_python that dumps
            # email bodies can be 200+ KB; re-sending that on every
            # turn blows the prompt cache + can outright exceed the
            # provider's context window. Compress past invocation
            # results to summaries that preserve status + key fields.
            history_dicts = [
                {"role": m.role,
                 "content": _compress_content(m.content),
                 "tool_invocations": [
                    _compress_inv(inv) for inv in m.tool_invocations
                 ],
                 "images": list(m.images)}
                for m in self.history
            ]
            def on_status_change(text: str) -> None:
                if self._stop: return
                self.status.emit(text)

            response = self.router.complete(
                history_dicts,
                model=self.model,
                on_chunk=on_chunk,
                on_tool_invocation=on_tool,
                on_reasoning=on_reasoning,
                on_status=on_status_change,
                session_pin=self.session_pin,
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
#  AutoHideLabel — collapses + hides the status bar when both labels are
#  blank. Round 2 dead-surface pass: the bar was always 24px of chrome
#  that almost never said anything. Now it disappears entirely until a
#  transient routing-note / warning needs to surface.
# ---------------------------------------------------------------------------
class _AutoHideLabel(QLabel):
    def __init__(self, owner_window, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner = owner_window

    def setText(self, s: str) -> None:        # type: ignore[override]
        super().setText(s or "")
        try:
            sync = getattr(self._owner, "_sync_status_visibility", None)
            if callable(sync):
                sync()
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  Multi-line chat input — QPlainTextEdit with QLineEdit-compatible API.
#  Enter sends, Shift+Enter inserts newline. Auto-grows up to MAX_LINES.
#  Mirrors the original _PasteInput surface (text/setText/clear/
#  returnPressed/setCursorPosition/image_pasted) so every caller works
#  unchanged.
# ---------------------------------------------------------------------------
from PyQt6.QtWidgets import QPlainTextEdit


class _PasteInput(QPlainTextEdit):
    image_pasted = pyqtSignal(str)   # emits temp file path
    returnPressed = pyqtSignal()     # mirrors QLineEdit's signal name

    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    _MIN_LINES = 1
    _MAX_LINES = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        # No tab characters — Tab moves focus instead of indenting.
        self.setTabChangesFocus(True)
        # Hide horizontal scrollbar; vertical only when over MAX_LINES.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # Force the palette text + placeholder roles to the active
        # brand tokens. Qt's Fusion style ignores QSS `color:` for the
        # document content in QPlainTextEdit — it reads QPalette.Text
        # for typed characters and QPalette.PlaceholderText for the
        # placeholder. Setting them explicitly here is the load-
        # bearing fix for "I type and nothing shows up" in dark mode.
        try:
            from PyQt6.QtGui import QPalette, QColor
            from design_tokens import current as _palette
            p = _palette()
            qp = self.palette()
            qp.setColor(QPalette.ColorRole.Base, QColor(p["bgRaised"]))
            qp.setColor(QPalette.ColorRole.Text, QColor(p["ink"]))
            qp.setColor(QPalette.ColorRole.PlaceholderText,
                         QColor(p.get("inkSoft") or p["ink"]))
            qp.setColor(QPalette.ColorRole.Highlight,
                         QColor(p.get("accent") or "#d97757"))
            qp.setColor(QPalette.ColorRole.HighlightedText,
                         QColor("#ffffff"))
            self.setPalette(qp)
        except Exception:
            pass
        # Sensible single-line default height.
        self._adjust_height()
        self.textChanged.connect(self._adjust_height)

    # ---- QLineEdit-compatible shim API -----------------------------------
    # Existing call sites expect text()/setText()/setCursorPosition();
    # provide those on top of the QPlainTextEdit storage so chat_window
    # + studio_shell don't have to change.

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, s: str) -> None:
        self.setPlainText(s or "")

    def setCursorPosition(self, pos: int) -> None:
        cur = self.textCursor()
        try:
            cur.setPosition(int(pos))
            self.setTextCursor(cur)
        except Exception:
            pass

    # ---- height auto-grow ------------------------------------------------
    def _adjust_height(self) -> None:
        # Compute required height for current content, clamped to
        # [MIN_LINES..MAX_LINES] in line units. The constants below
        # account for the full chrome: QSS padding (12+12=24px),
        # frame border (1+1=2px), document margin (4+4=8px). Without
        # this buffer setFixedHeight clips the text and the user sees
        # an apparently-empty input even though characters are there.
        fm = self.fontMetrics()
        line_h = fm.lineSpacing()
        doc = self.document()
        doc.setTextWidth(self.viewport().width()
                         if self.viewport().width() > 0
                         else self.width())
        try:
            n_lines = max(1, int(doc.size().height() / line_h))
        except Exception:
            n_lines = 1
        clamped = max(self._MIN_LINES, min(self._MAX_LINES, n_lines))
        # Chrome: 24px QSS padding + 2px frame + 8px doc margin = ~34.
        # A few extra px buffer so the cursor isn't kissed by the
        # bottom border.
        chrome = 36
        h = clamped * line_h + chrome
        self.setFixedHeight(int(h))

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        # Width changed → wrapping may have changed → re-measure height.
        self._adjust_height()

    # ---- drag and drop ---------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasImage():
            from PyQt6.QtGui import QImage
            img = mime.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self._save_and_emit(img)
                event.acceptProposedAction()
                return
        if mime.hasUrls():
            from os.path import splitext
            n = 0
            for url in mime.urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                ext = splitext(path)[1].lower()
                if ext in self._IMAGE_EXTS:
                    self.image_pasted.emit(path)
                    n += 1
            if n:
                event.acceptProposedAction()
                return
        event.ignore()

    # ---- key handling: Enter sends, Shift+Enter newline, Ctrl+V image ----

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()

        # Ctrl+V — clipboard image takes precedence over text paste so
        # screenshot pastes route through image_pasted instead of pasting
        # binary garbage as text.
        if (key == Qt.Key.Key_V
                and mods == Qt.KeyboardModifier.ControlModifier):
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime.hasImage():
                img = clipboard.image()
                if not img.isNull():
                    self._save_and_emit(img)
                    return
            # else fall through to default paste

        # Enter / Return — submit; Shift+Enter — insert newline; Ctrl+
        # Enter also inserts newline (matches Slack/Discord convention).
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & (Qt.KeyboardModifier.ShiftModifier
                        | Qt.KeyboardModifier.ControlModifier):
                # Insert real newline into the document.
                self.insertPlainText("\n")
                return
            # Plain Enter → submit. Don't insert newline.
            self.returnPressed.emit()
            return

        super().keyPressEvent(event)

    # ---- shared helper ---------------------------------------------------

    def _save_and_emit(self, img) -> None:
        """Write a QImage to a temp PNG and emit the path."""
        import tempfile, os
        renders_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "ArchHub" / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", delete=False, dir=str(renders_dir),
        )
        tmp.close()
        img.save(tmp.name)
        self.image_pasted.emit(tmp.name)


# ---------------------------------------------------------------------------
#  Tool invocation card — collapsible inline card for tool calls.
# ---------------------------------------------------------------------------
class ToolCard(QFrame):
    """Inline card for a tool invocation. Renders status + collapsible
    detail. When the invocation status is 'needs_confirmation' (set by
    the tool engine when the user's policy is 'ask'), the card surfaces
    inline Approve / Deny buttons that re-fire or block the call."""

    # Emitted when the user clicks Approve. Chat layer listens to
    # re-invoke the tool with user_confirmed=True.
    approve_requested = pyqtSignal(object)   # ToolInvocation
    deny_requested = pyqtSignal(object)       # ToolInvocation

    def __init__(self, invocation: ToolInvocation, parent=None):
        super().__init__(parent)
        self.setObjectName("toolCard")
        self.invocation = invocation
        # On error OR needs_confirmation, default to expanded so the
        # user sees the cause / the args they're approving.
        self._expanded = invocation.status in ("error", "needs_confirmation")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("▾" if self._expanded else "▸")
        self.toggle_btn.setObjectName("toolCardChevron")
        self.toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self.toggle_btn)

        title = QLabel(f"<b>{invocation.tool_name}</b>")
        title.setObjectName("toolCardTitle")
        header.addWidget(title)
        header.addStretch(1)

        # Inline error preview to the right of the title — saves a click.
        self.error_preview = QLabel("")
        self.error_preview.setObjectName("toolCardStatus")
        try:
            from design_tokens import current as _palette
            _err = _palette()["err"]
        except Exception:
            _err = "#b8493e"
        self.error_preview.setStyleSheet(f"color: {_err};")
        header.addWidget(self.error_preview)

        self.status_label = QLabel(invocation.status)
        self.status_label.setObjectName("toolCardStatus")
        header.addWidget(self.status_label)
        outer.addLayout(header)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setObjectName("toolCardDetail")
        self.detail.setMinimumHeight(0)
        self.detail.setMaximumHeight(280 if self._expanded else 0)
        self.detail.setVisible(self._expanded)
        outer.addWidget(self.detail)

        # Approve / Deny row — visible only on needs_confirmation.
        self._approve_row = QFrame()
        ar = QHBoxLayout(self._approve_row)
        ar.setContentsMargins(0, 4, 0, 0)
        ar.setSpacing(8)
        self._approve_btn = QPushButton("Approve")
        self._approve_btn.setObjectName("primaryButton")
        self._approve_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._approve_btn.clicked.connect(self._on_approve)
        self._deny_btn = QPushButton("Deny")
        self._deny_btn.setObjectName("ghostButton")
        self._deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._deny_btn.clicked.connect(self._on_deny)
        ar.addWidget(self._approve_btn)
        ar.addWidget(self._deny_btn)
        ar.addStretch(1)
        self._approve_row.setVisible(False)
        outer.addWidget(self._approve_row)

        self.refresh()

    # ---- approve / deny handlers -----------------------------------
    def _on_approve(self) -> None:
        self._approve_row.setVisible(False)
        self.approve_requested.emit(self.invocation)

    def _on_deny(self) -> None:
        self._approve_row.setVisible(False)
        self.deny_requested.emit(self.invocation)

    def refresh(self) -> None:
        self.status_label.setText(self.invocation.status)

        # needs_confirmation → reveal Approve/Deny + open the detail
        # so the user can see the args before approving.
        if self.invocation.status == "needs_confirmation":
            self._approve_row.setVisible(True)
            if not self._expanded:
                self._expanded = True
                self.toggle_btn.setText("▾")
                self.detail.setVisible(True)
                self.detail.setMaximumHeight(280)
            args = self.invocation.arguments or {}
            self.detail.setPlainText(
                f"This tool needs your approval (Settings → AI "
                f"Behaviour → Tool permissions).\n\n"
                f"ARGS\n{str(args)[:2000]}"
            )
            self.error_preview.setText("⏸ awaiting approval")
            return
        else:
            self._approve_row.setVisible(False)

        # Pull a short error preview from the result so the user sees the
        # actual cause inline (instead of a useless "error" badge).
        result = self.invocation.result or {}
        err_msg = ""
        if isinstance(result, dict):
            err_msg = str(result.get("error") or "").strip()
        if self.invocation.status == "error" and err_msg:
            short = err_msg.replace("\n", " ").strip()
            if len(short) > 70:
                short = short[:67] + "…"
            self.error_preview.setText(short)
            # Ensure the detail panel is open on first error.
            if not self._expanded:
                self._expanded = True
                self.toggle_btn.setText("▾")
                self.detail.setVisible(True)
                self.detail.setMaximumHeight(280)
        else:
            self.error_preview.setText("")

        if self._expanded:
            args = self.invocation.arguments or {}
            text = ""
            if self.invocation.status == "error" and err_msg:
                text += f"ERROR\n{err_msg}\n\n"
            text += "ARGS\n" + str(args)[:2000] + "\n\nRESULT\n" + str(result)[:2000]
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
# ---------------------------------------------------------------------------
#  Skill execution UI — progress stepper for chained skills, worker thread.
# ---------------------------------------------------------------------------
class _SkillRunWorker(QObject):
    """Runs WorkflowExecutor.run on a background thread, forwarding the
    executor's ExecutionEvent stream as Qt signals so the UI can render
    a stepper without blocking the main loop."""
    event_received = pyqtSignal(object)        # ExecutionEvent
    finished = pyqtSignal(object)              # ExecutionResult or None

    def __init__(self, workflow, inputs, router, tool_engine, manager):
        super().__init__()
        self._workflow = workflow
        self._inputs = inputs
        self._router = router
        self._tool_engine = tool_engine
        self._manager = manager

    def run(self) -> None:
        try:
            executor = WorkflowExecutor(self._router, self._tool_engine, self._manager)
            result = executor.run(
                self._workflow, inputs=self._inputs,
                on_event=self.event_received.emit,
            )
            self.finished.emit(result)
        except Exception as ex:
            self.event_received.emit(_make_failed_event(str(ex)))
            self.finished.emit(None)


def _make_failed_event(msg: str):
    """Build a minimal failure event the stepper can render when the worker
    itself crashes before WorkflowExecutor produces one."""
    from workflows.executor import ExecutionEvent
    return ExecutionEvent(type="failed", detail=msg)


class SkillStepperCard(QFrame):
    """Live progress card with one row per node in the running skill. Each
    row gets a tick / spinner / cross icon as the executor runs through.

    For single-stage skills (4-node chain) the card collapses to one
    visible step ("LLM reasoning"). For multi-stage skills like
    sketch-to-production it shows six rows the user can watch tick off."""

    def __init__(self, workflow, parent=None):
        super().__init__(parent)
        self.setObjectName("toolCard")
        self._workflow = workflow

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)

        title = QLabel(f"<b>{workflow.name}</b>")
        title.setObjectName("toolCardTitle")
        v.addWidget(title)

        self._rows: dict[str, QLabel] = {}
        # Show a row per "interesting" node — skip wiring nodes
        # (input.parameter, output.parameter, data.template, data.constant).
        wiring = {"input.parameter", "output.parameter", "data.template", "data.constant"}
        for node in workflow.nodes:
            if node.type in wiring:
                continue
            row = QLabel(self._format_row("○", node.label or node.type, "queued"))
            row.setObjectName("toolCardStatus")
            v.addWidget(row)
            self._rows[node.id] = row

        # Fallback for skills that have no non-wiring nodes
        if not self._rows:
            row = QLabel(self._format_row("○", workflow.name, "queued"))
            row.setObjectName("toolCardStatus")
            v.addWidget(row)
            self._rows["__only__"] = row

    def _format_row(self, icon: str, label: str, status: str) -> str:
        # Pull accent + muted from the live palette so the stepper card
        # matches whichever theme is active. The previous hardcoded
        # "#cc785c" / "#8a8580" drifted from COLOR.accent (#c96442)
        # and didn't track dark mode.
        try:
            from design_tokens import current as _palette
            p = _palette()
            accent = p["accent"]
            muted = p["inkMuted"]
        except Exception:
            accent = "#c96442"
            muted = "#7a7064"
        return (
            f"<span style='color:{accent};font-size:14px;'>{icon}</span>  "
            f"{label}  <i style='color:{muted};'>{status}</i>"
        )

    def handle_event(self, ev) -> None:
        nid = getattr(ev, "node_id", None)
        et = getattr(ev, "type", "")
        label_node = None
        for node in self._workflow.nodes:
            if node.id == nid:
                label_node = node
                break
        label = (label_node.label or label_node.type) if label_node else "Step"

        if et == "node_started" and nid in self._rows:
            self._rows[nid].setText(self._format_row("◐", label, "running…"))
        elif et == "node_finished" and nid in self._rows:
            elapsed = getattr(ev, "elapsed_ms", 0) or 0
            self._rows[nid].setText(self._format_row("✓", label, f"{elapsed/1000:.1f}s"))
        elif et == "node_failed" and nid in self._rows:
            detail = getattr(ev, "detail", "") or "failed"
            self._rows[nid].setText(self._format_row("✗", label, str(detail)[:80]))
        elif et == "log":
            # Optional: surface log lines as tooltips on the most recent row.
            pass

    def finalise(self, *, success: bool) -> None:
        # Mark any still-queued rows as skipped on overall failure.
        if not success:
            for nid, row in self._rows.items():
                txt = row.text()
                if "queued" in txt:
                    label = txt.split(">", 2)[2].split("<", 1)[0].strip() if ">" in txt else "Step"
                    row.setText(self._format_row("·", label, "skipped"))


class _StatusDot(QLabel):
    """Single 8-px terra dot that fades 1.0 → 0.35 → 1.0 every 1.2s.

    Replaces the loud `● ● ●` typing dots the user complained about.
    Quiet motion per brand principle 07: one element, one rhythm,
    no jitter. Uses QPropertyAnimation on a custom intensity property
    so the alpha animates smoothly without redrawing layout.
    """
    from PyQt6.QtCore import (
        QPropertyAnimation, QEasingCurve, pyqtProperty,
        QSequentialAnimationGroup,
    )

    def __init__(self, parent=None):
        super().__init__("●", parent)
        self._intensity = 1.0
        self.setFixedSize(10, 14)
        self._anim_group = None
        self._update_style()

    def _update_style(self) -> None:
        from PyQt6.QtGui import QColor
        # Read accent from the active palette so the pulsing status dot
        # tracks light/dark theme. Previously hardcoded #c96442 (light).
        try:
            from design_tokens import current as _palette
            _accent_hex = _palette()["accent"]
        except Exception:
            _accent_hex = "#c96442"
        c = QColor(_accent_hex)
        c.setAlphaF(max(0.0, min(1.0, 0.35 + 0.65 * self._intensity)))
        self.setStyleSheet(
            f"color:{c.name(QColor.NameFormat.HexArgb)}; "
            f"font-size:11px; padding:0; margin:0;"
        )

    def start(self) -> None:
        from PyQt6.QtCore import (
            QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup,
        )
        if self._anim_group is not None and self._anim_group.state() == QPropertyAnimation.State.Running:
            return
        a1 = QPropertyAnimation(self, b"intensity")
        a1.setDuration(600)
        a1.setStartValue(1.0)
        a1.setEndValue(0.0)
        a1.setEasingCurve(QEasingCurve.Type.InOutSine)
        a2 = QPropertyAnimation(self, b"intensity")
        a2.setDuration(600)
        a2.setStartValue(0.0)
        a2.setEndValue(1.0)
        a2.setEasingCurve(QEasingCurve.Type.InOutSine)
        group = QSequentialAnimationGroup(self)
        group.addAnimation(a1)
        group.addAnimation(a2)
        group.setLoopCount(-1)
        group.start()
        self._anim_group = group

    def stop(self) -> None:
        if self._anim_group is not None:
            self._anim_group.stop()
            self._anim_group = None
        self._intensity = 1.0
        self._update_style()

    def _get_intensity(self) -> float:
        return self._intensity

    def _set_intensity(self, v: float) -> None:
        self._intensity = float(v)
        self._update_style()

    from PyQt6.QtCore import pyqtProperty as _pyqtProperty
    intensity = _pyqtProperty(float, _get_intensity, _set_intensity)


class _TypingIndicator(QLabel):
    """Animated three-dot indicator. Shown inside an assistant bubble while
    the LLM is thinking, hidden as soon as the first text chunk arrives."""

    _FRAMES = ("●  ●  ●", "●  ●  ●", "●  ●  ●", "●  ●  ●")
    # Use opacity dance via stylesheet instead of unicode swapping to avoid
    # font-fallback width jitter; each frame highlights a different dot.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("typingIndicator")
        self.setText("●  ●  ●")
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(380)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % 4
        # Each tick shifts which dot is "lit" via different weights; we change
        # only the stylesheet to keep layout perfectly stable.
        weights = [0.3, 0.3, 0.3]
        if self._frame < 3:
            weights[self._frame] = 1.0
        # Build a colour-tinted mark via three labels would be lighter, but a
        # plain text indicator with a marquee-style colour change works too.
        # Cheapest: rotate the colour intensity globally.
        alpha = 0.35 + 0.25 * (self._frame % 4 == 3)
        self.setStyleSheet(
            f"color: rgba(244, 239, 232, {alpha:.2f}); "
            f"font-size: 18px; letter-spacing: 4px; padding: 2px 4px;"
        )

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()


class MessageBubble(QFrame):
    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.setObjectName("userBubble" if role == "user" else "assistantBubble")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Real depth — Qt's drop-shadow effect renders below the bubble's
        # painted background. Combined with the QSS translucent fill this
        # gives a believable "frosted floating panel" feel that flat QSS
        # alone cannot produce.
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QColor
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        # Status row — pulsing terra dot + italic dim text. Replaces
        # the loud "● ● ●" three-dot indicator the user complained about.
        # Quiet motion (brand principle 07): a single dot fades 1.0 →
        # 0.35 → 1.0 every 1.2s. No bouncing, no jitter. Whole row
        # hides when the turn is done.
        self.status_line: Optional[QLabel] = None
        self._status_dot: Optional[_StatusDot] = None
        self._status_row: Optional[QWidget] = None
        if role == "assistant":
            self._status_row = QWidget()
            sr = QHBoxLayout(self._status_row)
            sr.setContentsMargins(0, 2, 0, 2)
            sr.setSpacing(8)
            self._status_dot = _StatusDot()
            sr.addWidget(self._status_dot)
            self.status_line = QLabel("")
            self.status_line.setObjectName("bubbleStatus")
            # Pull muted ink from the active palette so the status row
            # stays legible in both light and dark themes.
            try:
                from design_tokens import current as _palette
                _muted = _palette()["inkMuted"]
            except Exception:
                _muted = "#9a9183"
            self.status_line.setStyleSheet(
                f"color: {_muted}; font-style: italic; font-size: 12px; "
                f"padding: 0; margin: 0;"
            )
            sr.addWidget(self.status_line, 1)
            self._status_row.setVisible(False)
            v.addWidget(self._status_row)

        # Reasoning view — italic dim block ABOVE the answer. Populated
        # by `append_reasoning`. Hidden until the model emits its first
        # thinking block. Collapsible toggle via _reasoning_toggle.
        self.reasoning_view: Optional[QTextEdit] = None
        self._reasoning_toggle: Optional[QToolButton] = None
        if role == "assistant":
            self._reasoning_toggle = QToolButton()
            self._reasoning_toggle.setObjectName("reasoningToggle")
            self._reasoning_toggle.setText("▾  Reasoning")
            self._reasoning_toggle.setCheckable(True)
            self._reasoning_toggle.setChecked(True)
            try:
                from design_tokens import current as _palette
                _p = _palette()
                _muted = _p["inkMuted"]
                _accent = _p["accent"]
            except Exception:
                _muted, _accent = "#9a9183", "#c96442"
            self._reasoning_toggle.setStyleSheet(
                f"QToolButton#reasoningToggle {{ "
                f"  background:transparent; border:none; "
                f"  color:{_muted}; font-size:10.5px; font-weight:500; "
                f"  letter-spacing:0.06em; padding:2px 0; text-align:left; "
                f"}} "
                f"QToolButton#reasoningToggle:hover {{ color:{_accent}; }}"
            )
            self._reasoning_toggle.setVisible(False)
            self._reasoning_toggle.toggled.connect(self._toggle_reasoning)
            v.addWidget(self._reasoning_toggle)
            self.reasoning_view = QTextEdit()
            self.reasoning_view.setReadOnly(True)
            self.reasoning_view.setObjectName("reasoningView")
            self.reasoning_view.setFrameShape(QFrame.Shape.NoFrame)
            self.reasoning_view.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.reasoning_view.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.reasoning_view.document().setDocumentMargin(0)
            self.reasoning_view.textChanged.connect(self._adjust_reasoning_height)
            try:
                from design_tokens import current as _palette
                _p = _palette()
                _soft = _p["inkSoft"]
                _line = _p["line"]
            except Exception:
                _soft, _line = "#7a7064", "#3a3128"
            self.reasoning_view.setStyleSheet(
                f"QTextEdit#reasoningView {{ "
                f"  background:transparent; border:none; "
                f"  color:{_soft}; font-style:italic; font-size:12px; "
                f"  border-left:2px solid {_line}; padding-left:10px; "
                f"  margin-bottom:4px; "
                f"}}"
            )
            self.reasoning_view.setVisible(False)
            v.addWidget(self.reasoning_view)

        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setObjectName("messageText")
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.document().setDocumentMargin(0)
        self.text_view.textChanged.connect(self._adjust_height)
        v.addWidget(self.text_view)

        # Typing indicator removed — replaced by the pulsing-dot status
        # row above. Kept the attribute so legacy callers of
        # `_stop_typing()` don't AttributeError.
        self._typing: Optional[_TypingIndicator] = None

        self.tool_cards_container = QVBoxLayout()
        self.tool_cards_container.setContentsMargins(0, 0, 0, 0)
        self.tool_cards_container.setSpacing(6)
        v.addLayout(self.tool_cards_container)

        # Feedback row — quiet "Helpful? yes/no" links. Hidden until
        # the bubble is hovered so it doesn't draw attention to itself
        # while reading the answer.
        self._feedback_row = None
        if role == "assistant":
            try:
                from feedback_widget import FeedbackRow
                self._feedback_row = FeedbackRow(parent=self)
                v.addWidget(self._feedback_row)
                self.setMouseTracking(True)
            except Exception:
                self._feedback_row = None

    def enterEvent(self, ev) -> None:
        if self._feedback_row is not None:
            self._feedback_row.setVisible(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        if self._feedback_row is not None:
            # Don't hide while a thumb is checked — keeps inline
            # comment box accessible after thumbs-down.
            try:
                still_open = (self._feedback_row._up.isChecked()
                              or self._feedback_row._down.isChecked())
            except Exception:
                still_open = False
            if not still_open:
                self._feedback_row.setVisible(False)
        super().leaveEvent(ev)

    def attach_feedback_meta(self, *, message_id: str | None = None,
                             skill_id: str | None = None) -> None:
        """Backfill the feedback row's metadata after the run finishes."""
        if self._feedback_row is None:
            return
        self._feedback_row._message_id = message_id
        self._feedback_row._skill_id = skill_id

    def _stop_typing(self) -> None:
        if self._typing is not None:
            self._typing.stop()
            self._typing.hide()
            self._typing.deleteLater()
            self._typing = None

    def set_status(self, text: str) -> None:
        """Update the bubble's status row — pulsing dot + italic text.
        Empty text hides the row. No-op on non-assistant bubbles."""
        if self.status_line is None or self._status_row is None:
            return
        if text:
            self.status_line.setText(text)
            self._status_row.setVisible(True)
            if self._status_dot is not None:
                self._status_dot.start()
        else:
            self._status_row.setVisible(False)
            if self._status_dot is not None:
                self._status_dot.stop()

    def append_reasoning(self, fragment: str) -> None:
        """Append a chunk of model reasoning ("thinking" content) to
        the reasoning view above the answer. Surfaces the toggle row +
        view on first call. No-op on non-assistant bubbles."""
        if self.reasoning_view is None:
            return
        if not fragment:
            return
        self._reasoning_toggle.setVisible(True)
        self.reasoning_view.setVisible(self._reasoning_toggle.isChecked())
        cur = self.reasoning_view.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(fragment)
        self.reasoning_view.setTextCursor(cur)
        self._adjust_reasoning_height()

    def _toggle_reasoning(self, checked: bool) -> None:
        if self.reasoning_view is None or self._reasoning_toggle is None:
            return
        self._reasoning_toggle.setText(
            "▾  Reasoning" if checked else "▸  Reasoning")
        self.reasoning_view.setVisible(
            checked and bool(self.reasoning_view.toPlainText()))

    def _adjust_reasoning_height(self) -> None:
        if self.reasoning_view is None:
            return
        doc = self.reasoning_view.document()
        doc.setTextWidth(self.reasoning_view.viewport().width())
        h = int(doc.size().height()) + 4
        self.reasoning_view.setFixedHeight(max(20, min(h, 240)))

    def append_text(self, fragment: str) -> None:
        if fragment:
            self._stop_typing()
        cur = self.text_view.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(fragment)
        self.text_view.setTextCursor(cur)
        self._adjust_height()

    def set_text(self, text: str) -> None:
        if text:
            self._stop_typing()
        self.text_view.setPlainText(text)
        self._adjust_height()

    def _adjust_height(self) -> None:
        # Resolve a reliable text width. viewport().width() returns 0
        # before the bubble is laid out for the first time; using 0
        # collapses the document to one char per line and the height
        # ends up clamped to 20px so the message looks truncated.
        # Fall back to the bubble's own width minus the layout
        # margins, then to the maximumWidth() (720px ceiling), then
        # to a sensible 600px default. Re-measured on resizeEvent.
        view_w = self.text_view.viewport().width()
        if view_w <= 0:
            view_w = self.text_view.width()
        if view_w <= 0:
            # Bubble width minus its content margins on both sides.
            try:
                m = self.layout().contentsMargins()
                view_w = max(0, self.width() - m.left() - m.right())
            except Exception:
                view_w = 0
        if view_w <= 0:
            view_w = self.maximumWidth() if self.maximumWidth() > 0 else 600
        doc = self.text_view.document()
        doc.setTextWidth(view_w)
        h = int(doc.size().height()) + 4
        # No upper clamp — message bubbles must grow to fit the full
        # answer. Scrollbars are off; the parent scroll area handles
        # overflow at the page level.
        self.text_view.setFixedHeight(max(20, h))

    # Re-measure when the bubble's actual width settles (first paint
    # + on layout changes from window resize).
    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        try:
            self._adjust_height()
            self._adjust_reasoning_height()
        except Exception:
            pass

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        # First show — viewport width finally non-zero. Re-measure so
        # the very first message in a session isn't truncated.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._adjust_height)

    def add_tool_card(self, invocation: ToolInvocation) -> ToolCard:
        # Tool calls count as activity → kill the dots.
        self._stop_typing()
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
        # Per-skill last-run window for retry detection. Key = skill_id,
        # value = {"at": float, "success": bool}. Pruned implicitly — we
        # only ever read the entry for the skill we're about to record,
        # so stale keys are harmless.
        self._last_skill_runs: dict[str, dict] = {}

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

        # Auto-save current session every 5 min so the Threads list
        # isn't always empty for new users (and so a crash doesn't lose
        # an in-flight chat). No-op when the chat has no real history.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(5 * 60 * 1000)
        self._autosave_timer.timeout.connect(self._autosave_session)
        self._autosave_timer.start()
        self._autosave_path: Optional[Path] = None
        # Save on every assistant turn finish (in addition to the
        # 5-min timer) so a crash mid-session loses at most one turn.
        # Wired in _on_finished.

        # Auto-resume the most recent session. Without this every
        # launch starts a blank chat and the user thinks the THREADS
        # rail is decorative. With it, click → reload latest session
        # is the default — same as Slack / iMessage / every other
        # chat app the user has used. User can click another thread
        # in the rail to switch.
        try:
            from session_io import list_sessions, load_session_with_messages
            rows = list_sessions()
            if rows:
                latest_path = rows[0][0]
                try:
                    sess, _name, msgs = load_session_with_messages(
                        latest_path)
                    self.session = sess
                    self._autosave_path = latest_path
                    QTimer.singleShot(
                        100,
                        lambda: self._restore_history(msgs) if msgs else None,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _autosave_session(self) -> None:
        """Save the running session + chat history if it has at least
        one user msg. Reuses the same path across ticks so we overwrite,
        not pile up.

        Contract: ALWAYS pass messages=self.history. The chat surface
        stores conversation there, not in self.session, so omitting
        messages= produces the empty-stub bug class that hit users
        before v1.0. session_io.save_session enforces this at the
        write boundary by raising EmptySessionError on an empty
        payload — we catch it here only to keep the timer alive."""
        try:
            real_msgs = [m for m in self.history
                         if m.role == "user" and (m.content or "").strip()]
            if not real_msgs:
                return
            from session_io import save_session, EmptySessionError
            # Pick a name from the first user message (truncated).
            first = real_msgs[0].content.strip()
            name = (first[:48] + "…") if len(first) > 48 else first
            try:
                # NEVER call save_session without messages=. The
                # guard above filters before we get here, but the
                # keyword is mandatory by contract — leaving it
                # off is the historic bug.
                path = save_session(self.session, name,
                                     path=self._autosave_path,
                                     messages=self.history)
                self._autosave_path = path
            except EmptySessionError:
                # Should never reach here given the real_msgs filter,
                # but if it does, log + skip rather than crash the
                # autosave timer.
                pass
        except Exception:
            pass

    # ---- UI construction ---------------------------------------------------

    # ---------------------------------------------------------------------
    # Update banner — "Update available · Restart now / Later"
    # Wired from main.py via release_updater.schedule_auto_check(on_ready=...)
    # which calls self._on_update_ready on a daemon thread; we marshal
    # back to the Qt main thread via update_ready_signal.
    # ---------------------------------------------------------------------
    update_ready_signal = pyqtSignal(object, object)  # (installer_path, release)

    def _build_update_banner(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("updateBanner")
        # Build from design tokens so the banner tracks the active
        # palette. The previous hand-tuned brown (#2a2018 / #f0d49a)
        # only made sense in dark mode and broke the "one warm color"
        # principle in light mode.
        from design_tokens import current as _palette, RADIUS as _R
        p = _palette()
        bar.setStyleSheet(
            f"QFrame#updateBanner {{"
            f"  background:{p['accentSoft']};"
            f"  border-top:1px solid {p['line']};"
            f"  border-bottom:1px solid {p['line']}; }}"
            f"QLabel#updateBannerLabel {{ color:{p['ink']}; padding:0; }}"
            f"QPushButton#updateBannerPrimary {{"
            f"  background:{p['accent']}; color:#fff; border:none;"
            f"  border-radius:{_R['md']}px; padding:6px 14px; font-weight:500; }}"
            f"QPushButton#updateBannerPrimary:hover {{ background:{p['accentHi']}; }}"
            f"QPushButton#updateBannerGhost {{"
            f"  background:transparent; color:{p['inkSoft']};"
            f"  border:1px solid {p['line']}; border-radius:{_R['md']}px;"
            f"  padding:6px 14px; }}"
            f"QPushButton#updateBannerGhost:hover {{ color:{p['accent']};"
            f"  border-color:{p['accent']}; }}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 10, 16, 10)
        h.setSpacing(12)

        icon = QLabel("↻")
        icon.setStyleSheet(
            f"color:{p['accent']}; font-size:16px; font-weight:bold;"
        )
        h.addWidget(icon)

        self._update_banner_label = QLabel("Update downloaded · restart to install.")
        self._update_banner_label.setObjectName("updateBannerLabel")
        h.addWidget(self._update_banner_label, 1)

        self._update_banner_later = QPushButton("Later")
        self._update_banner_later.setObjectName("updateBannerGhost")
        self._update_banner_later.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_banner_later.clicked.connect(self._dismiss_update_banner)
        h.addWidget(self._update_banner_later)

        self._update_banner_restart = QPushButton("Restart now")
        self._update_banner_restart.setObjectName("updateBannerPrimary")
        self._update_banner_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_banner_restart.clicked.connect(self._restart_for_update)
        h.addWidget(self._update_banner_restart)

        self._update_banner = bar
        self._update_banner_installer = None  # populated when signal fires
        self._update_banner_release = None
        bar.setVisible(False)
        # Cross-thread marshalling: daemon-thread callback emits the
        # signal, the slot runs on the Qt main thread.
        self.update_ready_signal.connect(self._on_update_ready_qt)
        return bar

    def _on_update_ready(self, installer_path, release) -> None:
        """Daemon-thread callback from release_updater.schedule_auto_check.
        Emits a Qt signal so the banner update runs on the main thread."""
        try:
            self.update_ready_signal.emit(installer_path, release)
        except Exception:
            pass

    def _on_update_ready_qt(self, installer_path, release) -> None:
        """Main-thread handler — show the banner with the release tag."""
        self._update_banner_installer = installer_path
        self._update_banner_release = release
        tag = getattr(release, "tag_name", None) or getattr(release, "tag", "")
        msg = (f"ArchHub {tag} downloaded · restart to install."
               if tag else "Update downloaded · restart to install.")
        try:
            self._update_banner_label.setText(msg)
            self._update_banner.setVisible(True)
        except Exception:
            pass
        # Also save the snooze breadcrumb so we don't re-prompt on
        # every check while the user is choosing "Later".
        try:
            from secrets_store import save_setting
            save_setting("update_pending_tag", str(tag))
        except Exception:
            pass

    def _dismiss_update_banner(self) -> None:
        """User clicked Later — hide the banner but keep the installer
        on disk so the next prompt (or next launch) can use it."""
        try:
            self._update_banner.setVisible(False)
        except Exception:
            pass

    def _restart_for_update(self) -> None:
        """User clicked Restart now — fire the silent installer.
        run_installer calls os._exit(0) after the spawn; Inno Setup's
        /RESTARTAPPLICATIONS brings ArchHub back up automatically."""
        if not self._update_banner_installer:
            self._dismiss_update_banner()
            return
        try:
            self._update_banner_label.setText("Installing… ArchHub will reopen shortly.")
            self._update_banner_restart.setEnabled(False)
            self._update_banner_later.setEnabled(False)
            QApplication.processEvents()
        except Exception:
            pass
        try:
            import release_updater
            release_updater.run_installer(
                self._update_banner_installer,
                silent=True, relaunch=True,
            )
        except Exception as ex:
            try:
                QMessageBox.warning(
                    self, "Update", f"Could not start installer: {ex}"
                )
                self._update_banner_restart.setEnabled(True)
                self._update_banner_later.setEnabled(True)
            except Exception:
                pass

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        # Update banner — sits between header and body. Hidden until
        # the background update watcher signals that a new release has
        # been downloaded. Claude-Desktop pattern: download silently,
        # then prompt the user to restart at a convenient time.
        outer.addWidget(self._build_update_banner())

        # Body splits horizontally: chat on the left, parameters sidebar on the right.
        body_split = QSplitter(Qt.Orientation.Horizontal)
        body_split.setHandleWidth(1)
        body_split.setChildrenCollapsible(True)
        self._body_split = body_split

        # Left: conversation + input bar stacked vertically
        left = QWidget()
        left_v = QVBoxLayout(left); left_v.setContentsMargins(0, 0, 0, 0); left_v.setSpacing(0)
        left_v.addWidget(self._build_conversation_area(), 1)
        left_v.addWidget(self._build_input_bar())

        # Right: parameters panel, bound to the live session. Hidden when
        # there are no parameters yet — the empty sidebar wasted real estate
        # and made the UI feel cluttered. We restore it the moment a session
        # parameter is added (see _on_session_event / _on_parameter_edited).
        self.parameters_panel = ParametersPanel()
        self.parameters_panel.set_session(self.session)
        self.parameters_panel.parameter_edited.connect(self._on_parameter_edited)

        body_split.addWidget(left)
        body_split.addWidget(self.parameters_panel)
        body_split.setStretchFactor(0, 1)
        body_split.setStretchFactor(1, 0)
        # Start with the sidebar collapsed; show it only when the session
        # actually has parameters.
        if not self.session.parameters:
            self.parameters_panel.hide()
            body_split.setSizes([1200, 0])
        else:
            body_split.setSizes([900, 300])

        outer.addWidget(body_split, 1)
        outer.addWidget(self._build_status_bar())

    def _show_parameters_sidebar(self) -> None:
        """Reveal the parameters sidebar — called when the session gains its
        first parameter so the user sees it appear naturally."""
        if not hasattr(self, "_body_split") or not hasattr(self, "parameters_panel"):
            return
        if self.parameters_panel.isVisible():
            return
        self.parameters_panel.show()
        self._body_split.setSizes([900, 300])

    def _build_header(self) -> QWidget:
        """Slim header (v1.3.2 round-2 density pass).

        Brand text 'ArchHub™' was 80px of redundant chrome — the OS
        window title + taskbar entry already say ArchHub. The brand
        slot is now a tight 'A' monogram in a 24px plate so the brand
        anchor stays without eating header width. Host pills + model
        picker + Add Host + Menu fit under 60% of a 1280px window now.
        To revive the wordmark: restore the QLabel('ArchHub™') line.
        """
        bar = QFrame()
        bar.setObjectName("header")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)

        title = QLabel("A")
        title.setObjectName("brand")
        title.setFixedSize(24, 24)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setToolTip(
            "ArchHub™ — common-law trademark, USPTO filing pending. "
            "Filed under Class 042 (SaaS) by Ahmed Yasser Fargaly."
        )
        h.addWidget(title)

        # Host status pills — one per detected host family, dot colour
        # reflects live broker status. Click any pill to open Add Host
        # pre-scrolled to that family. Refreshed every 6 s by
        # _host_pill_timer.
        self._host_pills_row = QHBoxLayout()
        self._host_pills_row.setSpacing(6)
        self._host_pill_labels: dict[str, QLabel] = {}
        pills_wrap = QWidget()
        pills_wrap.setLayout(self._host_pills_row)
        h.addWidget(pills_wrap)

        h.addStretch(1)

        self.model_picker = QComboBox()
        self.model_picker.setObjectName("modelPicker")
        self._populate_model_picker()
        h.addWidget(self.model_picker)

        # Top-level Add Host button — always visible, never buried.
        self.add_host_btn = QPushButton("+ Add Host")
        self.add_host_btn.setObjectName("ghostButton")
        self.add_host_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_host_btn.setToolTip(
            "Connect Revit / AutoCAD / 3ds Max / Blender / Outlook. "
            "Auto-detects every supported host on this machine."
        )
        self.add_host_btn.clicked.connect(self._open_add_host)
        h.addWidget(self.add_host_btn)

        # Single menu button — everything that used to be a header button
        # is now a labelled item in this menu, with the running version
        # surfaced inline so the user can see it at a glance.
        # Text label "Menu" rather than a gear emoji — BRAND.voice rule:
        # "No emoji." The bordered ghost-button styling makes it read
        # as a menu without iconography.
        self.menu_btn = QToolButton()
        self.menu_btn.setObjectName("menuButton")
        self.menu_btn.setText("Menu")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_btn.setFixedSize(64, 36)
        self.menu_btn.setToolTip("Settings, connectors, skills, updates")
        self.menu_btn.setMenu(self._build_app_menu())
        h.addWidget(self.menu_btn)

        # Kick off the host-pill refresh timer right after the header
        # is constructed (the first refresh runs on the Qt event loop
        # so __init__ stays fast).
        QTimer.singleShot(0, self._refresh_host_pills)
        self._host_pill_timer = QTimer(self)
        self._host_pill_timer.setInterval(6000)
        self._host_pill_timer.timeout.connect(self._refresh_host_pills)
        self._host_pill_timer.start()

        return bar

    # ---------------------------------------------------------------------
    # Host pills — live status indicator per detected host family.
    # ---------------------------------------------------------------------
    _HOST_PILL_FAMILIES: tuple[tuple[str, str, str], ...] = (
        # (family, short label, broker module name)
        ("revit",   "Revit",   "revit_broker"),
        ("acad",    "Acad",    "acad_broker"),
        ("max",     "Max",     "max_broker"),
        ("outlook", "Outlook", "outlook_broker"),
        ("blender", "Blender", None),  # blender has no broker; ping runner
    )

    def _refresh_host_pills(self) -> None:
        """Probe each broker for live sessions, paint a pill per host."""
        try:
            # Clear current pills.
            while self._host_pills_row.count():
                item = self._host_pills_row.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.setParent(None); w.deleteLater()
            self._host_pill_labels.clear()

            for family, short, broker_name in self._HOST_PILL_FAMILIES:
                status = self._probe_host_status(family, broker_name)
                if status == "missing":
                    continue  # don't render a pill for hosts not present
                pill = self._build_host_pill(family, short, status)
                self._host_pills_row.addWidget(pill)
                self._host_pill_labels[family] = pill
        except Exception:
            # Pills are decoration — never let a probe crash kill the
            # chat window.
            pass

    def _probe_host_status(self, family: str, broker_name) -> str:
        """Return 'live' / 'idle' / 'missing'.

        Live  — broker reports ≥1 active session OR runner says so.
        Idle  — host is detected on disk but no session is open.
        Missing — host not installed / not detected; skip the pill.
        """
        try:
            if broker_name:
                mod = __import__(broker_name)
                sessions = []
                try:
                    sessions = list(mod.list_sessions() or [])
                except Exception:
                    sessions = []
                if sessions:
                    return "live"
            # Detect-on-disk probe for the hosts that have one.
            try:
                import auto_build
                if family == "revit":
                    for y in (2025, 2024, 2023, 2022, 2021, 2020):
                        if auto_build.find_revit_install(y):
                            return "idle"
                elif family == "acad":
                    for y in (2026, 2025, 2024):
                        if auto_build.find_autocad_install(y):
                            return "idle"
                elif family == "max":
                    for y in (2026, 2025):
                        if auto_build.find_max_install(y):
                            return "idle"
            except Exception:
                pass
            if family == "outlook":
                # Outlook has no separate broker; the COM proxy works
                # whenever classic Outlook is running.
                try:
                    from connectors import outlook_runner
                    if outlook_runner.is_reachable():
                        return "live"
                except Exception:
                    pass
                return "idle"
            if family == "blender":
                # Blender's addon listens on :9876 when active.
                import socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.15)
                    try:
                        s.connect(("127.0.0.1", 9876))
                        return "live"
                    except Exception:
                        return "missing"
            return "missing"
        except Exception:
            return "missing"

    def _build_host_pill(self, family: str, short: str, status: str) -> QLabel:
        # Read live palette so host pills track light/dark theme swaps
        # instead of carrying the hardcoded "green dot, brown idle"
        # values that drifted from BRAND.principles[2] (one warm color).
        try:
            from design_tokens import current as _palette
            p = _palette()
        except Exception:
            p = {"ok": "#5a8a5e", "warn": "#c08533", "inkDim": "#cdc6b8",
                 "ink": "#1a1612", "inkSoft": "#3a3128"}
        dot = {"live": p["ok"], "idle": p["warn"],
                "missing": p["inkDim"]}[status]
        ink = {"live": p["ink"], "idle": p["inkSoft"],
                "missing": p["inkDim"]}[status]
        pill = QLabel(f"<span style='color:{dot}'>●</span> "
                       f"<span style='color:{ink}'>{short}</span>")
        pill.setObjectName("hostPill")
        pill.setTextFormat(Qt.TextFormat.RichText)
        pill.setToolTip(
            f"{short} · {status}"
            + (" (broker reports a live session)" if status == "live"
                else " (installed, no session)" if status == "idle"
                else "")
        )
        # No native click on QLabel — wrap in a hand cursor and accept
        # mousePress on the label via event filter. Keep simple: install
        # cursor + tooltip; users discover Add Host via the button.
        pill.setCursor(Qt.CursorShape.PointingHandCursor)
        return pill

    # ---------------------------------------------------------------------
    def _open_add_host(self) -> None:
        """Show Add Host panel. Routes to Studio shell page if we live
        inside one; otherwise wraps the panel in a modal dialog so the
        chat window has its own first-class path."""
        # Studio-shell path.
        try:
            win = self.window()
            setter = getattr(win, "_set_page", None)
            if callable(setter):
                setter("addhost")
                return
        except Exception:
            pass
        # Modal-dialog path — works whether or not StudioShell is live.
        try:
            from add_host_panel import AddHostPanel
            dlg = QDialog(self)
            dlg.setWindowTitle("ArchHub — Add Host")
            dlg.resize(720, 640)
            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(0, 0, 0, 0)
            panel = AddHostPanel(manager=self.manager, parent=dlg)
            layout.addWidget(panel)
            dlg.exec()
            # Refresh after closing — user may have built / activated.
            self._refresh_host_pills()
            self._refresh_status()
        except Exception as ex:
            QMessageBox.warning(
                self, "Add Host",
                f"Could not open Add Host panel: {type(ex).__name__}: {ex}"
            )

    def _build_app_menu(self) -> QMenu:
        """The single dropdown that holds every secondary action.

        Labels are plain text — BRAND.voice rule 2 forbids emoji. The
        ASCII-arrow glyphs (↻, etc.) on Updates stay because they're
        typographic, not emoji.
        """
        menu = QMenu(self)
        menu.setObjectName("appMenu")

        # Connections + sign-ins
        sign_in_action = menu.addAction("Sign-ins…")
        sign_in_action.triggered.connect(self._open_settings)
        # v1.3.2 round-2 cut: 'Connectors…' menu item removed. The rail
        # HOSTS section already shows every connector with an inline
        # toggle (live state · port · click-to-activate), and the
        # 'Add Host' button is the primary discovery surface. The modal
        # was REDUNDANT chrome. _open_connectors is retained below so
        # programmatic / palette callers keep working. To revive the
        # menu line, re-add an action that wires self._open_connectors.

        # Skills + sessions
        skills_action = menu.addAction("Skills…")
        skills_action.triggered.connect(self._open_skills_panel)
        sessions_action = menu.addAction("Sessions…")
        sessions_action.triggered.connect(self._open_sessions)
        save_chat_action = menu.addAction("Save chat as Skill…")
        save_chat_action.triggered.connect(self._save_chat_as_skill)

        menu.addSeparator()

        # Updates + about + pricing. 'Plans & pricing' moves to the
        # Studio rail's Pricing page (still accessible through the More
        # disclosure). The menu no longer carries it — the cog menu was
        # cluttered with duplicate paths.
        self._update_menu_action = menu.addAction(self._update_menu_label())
        self._update_menu_action.triggered.connect(self._open_update_dialog)

        # Reality Check used to live here as a modal smoke-test entry.
        # Removed in the v1.3.1 dead-surface pass — the Studio shell's
        # Telemetry page now embeds RealityCheckPanel with live 24h
        # sparklines, which is the supported surface. `_open_reality_check`
        # is retained below so command-palette / programmatic callers
        # keep working. To revive the menu line, re-add an action that
        # wires to self._open_reality_check.

        about_action = menu.addAction("About ArchHub")
        about_action.triggered.connect(self._show_about)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
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
            self, "About ArchHub™",
            f"<h3>ArchHub™</h3>"
            f"<p>Parametric design environment for architects with chat as "
            f"the input surface and AI as the construction agent.</p>"
            f"<p style='color:#8a8a8c;font-size:11px;'>"
            f"Commit:  <code>{commit}</code><br>"
            f"Branch:  <code>{branch}</code><br>"
            f"Remote:  <code>{remote}</code></p>"
            f"<p style='color:#8a8a8c;font-size:10px;margin-top:14px;'>"
            f"ArchHub™ is a trademark of Ahmed Yasser Fargaly. "
            f"USPTO filing pending under Class 042 (SaaS). "
            f"MIT licensed open source.</p>",
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
        """Conversation-area welcome (v1.3.2 round-2 cut).

        Round 1 still rendered a 'What do you want to build?' title + a
        subtitle pointing to the menu — both decoration, both gone now.
        The empty conversation area IS the welcome state: the input bar
        below already says 'Message ArchHub…' with the keyboard hints.
        We keep the saved-skill chip row IFF the user actually has any
        saved skills — that's a real one-click CTA. When the library is
        empty we render nothing at all (the input bar is the only chrome
        the user needs to see). To revive the title + subtitle, restore
        from git history."""
        try:
            top_skills = skills.list_skills()[:3]
        except Exception:
            top_skills = []
        if not top_skills:
            self._welcome_widget = None
            return

        welcome = QFrame()
        welcome.setObjectName("welcomeCard")
        w = QVBoxLayout(welcome)
        w.setContentsMargins(24, 14, 24, 14)
        w.setSpacing(6)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.setContentsMargins(0, 0, 0, 0)
        for s in top_skills:
            chip = QPushButton(f"  ·  {s['name']}")
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
        """LM-Studio-pattern input: floating wrapper, input above tool
        chips below. Chips: Think (reasoning), Vision (image attach),
        Files (chat-with-files placeholder), Code (execute_python).
        Click toggles state; tool_engine + router consume the toggles
        next turn.
        """
        wrapper = QFrame()
        wrapper.setObjectName("inputBar")
        v = QVBoxLayout(wrapper)
        v.setContentsMargins(20, 8, 20, 14)
        v.setSpacing(6)

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

        # Input row (top)
        h = QHBoxLayout()
        h.setSpacing(10)

        attach_btn = QPushButton("+")
        attach_btn.setObjectName("ghostButton")
        attach_btn.setFixedWidth(32)
        attach_btn.setToolTip("Attach image file")
        attach_btn.clicked.connect(self._on_attach_image)
        h.addWidget(attach_btn)

        self.input = _PasteInput()
        self.input.setPlaceholderText("Send a message to the model…")
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

        # Tool-chip row (bottom) — LM-Studio pattern.
        # Each chip is checkable; toggling sets a flag the next send
        # consumes. Click again to disable. Default OFF.
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        chip_row.setContentsMargins(36, 0, 0, 0)   # align with input

        self._chip_state = {
            "think":  False,
            "vision": False,
            "files":  False,
            "code":   False,
        }
        self._chip_buttons: dict[str, QPushButton] = {}
        chip_specs = (
            ("think",  "Think",  "Toggle extended thinking for this turn (anthropic budget_tokens / o-series reasoning_effort)"),
            ("vision", "Vision", "Accept pasted/attached images this turn"),
            ("files",  "Chat with Files", "Inline files referenced in this turn"),
            ("code",   "Code",   "Permit execute_python tools this turn (otherwise auto-deny)"),
        )
        # Inline-style chips so they render correctly even when
        # theme.qss hasn't been regenerated to know about `toolChip`.
        # Pill shape, neutral off / warm-accent on.
        chip_qss = (
            "QPushButton#toolChip { "
            "  background: transparent; "
            "  color: #8a8a8c; "
            "  border: 1px solid #3a3a3c; "
            "  border-radius: 12px; "
            "  padding: 3px 12px; "
            "  font-size: 11px; "
            "} "
            "QPushButton#toolChip:hover { color: #e8e6dc; "
            "  border-color: #5a5a5c; } "
            "QPushButton#toolChip:checked { "
            "  background: #d97757; color: #fff; "
            "  border-color: #d97757; "
            "} "
        )
        for key, label, tip in chip_specs:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("toolChip")
            btn.setStyleSheet(chip_qss)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.toggled.connect(lambda checked, k=key: self._on_chip_toggled(k, checked))
            self._chip_buttons[key] = btn
            chip_row.addWidget(btn)

        # Right side of chip row — % indicator placeholder + future
        # streaming progress dot (mirrors LM Studio's `18%` + stop).
        chip_row.addStretch(1)
        self._stream_pct = QLabel("")
        self._stream_pct.setObjectName("streamPct")
        chip_row.addWidget(self._stream_pct)

        v.addLayout(chip_row)
        return wrapper

    def _on_chip_toggled(self, key: str, checked: bool) -> None:
        """Persist chip state on self._chip_state. Router reads this
        on the next _on_send to decide which tool family to admit
        (vision/files/code) or which thinking budget to apply."""
        self._chip_state[key] = bool(checked)
        # Surface to status bar so the user sees the toggle take effect.
        try:
            active = [k for k, v in self._chip_state.items() if v]
            if active:
                self.status_left.setText(f"chips: {', '.join(active)}")
            else:
                self.status_left.setText("")
        except Exception:
            pass

    def _build_status_bar(self) -> QWidget:
        """Slim status bar — collapses to zero height in steady state (v1.3.2).

        Round 2 cut: the bar was always-visible 24px of chrome that almost
        never said anything actionable. It now exists only as a carrier
        for transient runtime status (routing notes from `_on_finished`,
        skill match nudges, missing-LLM warnings). When both text labels
        are empty the bar hides itself; the moment a label sets text the
        bar reappears. To revive default visibility: drop the
        `_sync_status_visibility` calls and set `bar.setVisible(True)`."""
        bar = QFrame()
        bar.setObjectName("statusBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 4, 18, 4)
        h.setSpacing(10)

        self.status_left = _AutoHideLabel(self)
        self.status_left.setObjectName("statusText")
        h.addWidget(self.status_left)
        h.addStretch(1)

        self.status_right = _AutoHideLabel(self)
        self.status_right.setObjectName("statusText")
        h.addWidget(self.status_right)
        bar.setVisible(False)
        self._status_bar_widget = bar
        return bar

    def _sync_status_visibility(self) -> None:
        """Hide the status bar entirely when both labels are blank — the
        previous always-visible 24px row was decoration."""
        bar = getattr(self, "_status_bar_widget", None)
        if bar is None:
            return
        has_text = bool(
            (getattr(self, "status_left", None) and self.status_left.text())
            or (getattr(self, "status_right", None) and self.status_right.text())
        )
        bar.setVisible(has_text)

    # ---- Send / receive ----------------------------------------------------

    def _on_send(self) -> None:
        text = self.input.text().strip()
        images = list(self._pasted_images)
        if not text and not images:
            return
        # Pull `@<token>` mentions out of the user's text before we save
        # the message bubble. The pin scopes every tool call this turn
        # to one host session (Tower-A out of Revit × 3, etc.) so multi-
        # instance deployments don't fall back to most-recent-active.
        text, pin = self._extract_session_pin(text)
        self._pending_session_pin = pin
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

    # ---- @session mention parser ------------------------------------------

    # Matches @<token> at word boundaries. Token is alphanumerics, dots,
    # hyphens, underscores — covers session_id ("revit-12345"), pid
    # ("12345"), doc title slugs ("Tower-A", "pavilion_north"), and SMTP
    # accounts for Outlook ("ahmed@studio.com" via the local part). The
    # @ must be preceded by start-of-string or whitespace so we don't
    # match emails inside prose ("send to alice@studio.com").
    _PIN_RE = __import__("re").compile(
        r"(?:(?<=^)|(?<=\s))@([A-Za-z0-9][A-Za-z0-9._\-]{0,63})"
    )

    def _extract_session_pin(self, text: str) -> tuple[str, str | None]:
        """Strip the first `@<token>` mention, return (clean_text, token).
        Subsequent mentions are left intact so the assistant still sees
        the literal text — matching Slack/Linear behaviour where the
        first mention drives routing and the rest are conversational.
        Returns (text, None) when no mention is present."""
        m = self._PIN_RE.search(text)
        if not m:
            return text, None
        pin = m.group(1)
        cleaned = (text[:m.start()] + text[m.end():]).strip()
        # If the user typed nothing but `@token`, keep a placeholder so
        # the chat bubble isn't empty.
        if not cleaned:
            cleaned = f"(scoped to @{pin})"
        return cleaned, pin

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
                    f"Heads up — this looks like a **{host.title()}** "
                    f"action, but the {host.title()} connector isn't "
                    f"active.\n\n"
                    f"Open **Connectors** (header), enable {host.title()}, "
                    f"then make sure {host.title()} is running on this "
                    f"machine. I'll never paste code for you to copy — "
                    f"once the connector is live I'll execute the action "
                    f"directly."
                )
                return True
            if not self._host_reachable(host):
                # Differentiate "host process not running at all" vs
                # "host running but addin not loaded". The second case
                # is the common one after an ArchHub install while the
                # host was already open — the autoload registry entry
                # only fires on next host startup.
                process_running = self._host_process_running(host)
                if process_running:
                    self._add_assistant_note(
                        f"{host.title()} is running but the ArchHub "
                        f"addin hasn't loaded into the process yet.\n\n"
                        f"Two ways to fix:\n"
                        f"  • In {host.title()}'s command line type "
                        f"<code>NETLOAD</code> and pick "
                        f"<code>%LOCALAPPDATA%\\ArchHub\\AutoCAD\\&lt;year&gt;\\AcadMCP.dll</code> "
                        f"(or the equivalent for Revit / 3ds Max).\n"
                        f"  • OR close + reopen {host.title()}; the registry "
                        f"autoload will fire on next start.\n\n"
                        f"After either, ask me again."
                    )
                else:
                    self._add_assistant_note(
                        f"The {host.title()} connector is enabled, but "
                        f"{host.title()} isn't running.\n\n"
                        f"Open {host.title()}, wait until the project is "
                        f"loaded, then ask me again."
                    )
                return True
            return False

        # No host keyword. If it's an action verb and NO modelling connector
        # is active at all, we still warn so the LLM doesn't hallucinate code.
        modelling_hosts = {"revit", "autocad", "max", "blender"}
        if (active.isdisjoint(modelling_hosts)
                and any(v in lower for v in self._ACTION_VERBS)):
            self._add_assistant_note(
                "No modelling connector is active. To execute actions in "
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
        """Read from the central connector_health daemon — never probes
        inline. The daemon polls every 5s on a worker thread + caches the
        last result, so this call is O(1) and never blocks."""
        if host not in self._HOST_PING_URL:
            return True
        try:
            from connector_health import instance as _health
            return _health().state(host) == "live"
        except Exception:
            return False

    # Process names by host family. Used to distinguish 'host crashed
    # / not opened yet' from 'host is open but addin didn't load'.
    _HOST_PROCESS_NAMES = {
        "revit":   ("Revit.exe",),
        "autocad": ("acad.exe",),
        "max":     ("3dsmax.exe",),
        "blender": ("blender.exe",),
    }

    def _host_process_running(self, host: str) -> bool:
        """Cheap process-list scan. True iff the host application's exe
        is in the process table — even if its MCP listener isn't up."""
        names = self._HOST_PROCESS_NAMES.get(host)
        if not names:
            return False
        try:
            from proc_utils import run_hidden
            r = run_hidden(
                ["tasklist", "/FI", f"IMAGENAME eq {names[0]}", "/FO", "CSV", "/NH"],
                capture_output=True, timeout=2,
            )
            return names[0].lower() in (r.stdout or "").lower()
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
                error_text = (existing + "\n\n" if existing else "") + f"Error — {error}"
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
        self._show_parameters_sidebar()
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
        pin = getattr(self, "_pending_session_pin", None)
        worker = _LLMWorker(self.router, snapshot,
                             self.model_picker.currentData(),
                             session_pin=pin)
        # Consume the pin — next turn re-parses from input.
        self._pending_session_pin = None
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.chunk.connect(self._on_chunk)
        worker.reasoning.connect(self._on_reasoning)
        worker.status.connect(self._on_status)
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
        # First text chunk = answering. Flip status + clear typing dots.
        try:
            self._current_bubble.set_status("Answering…")
        except Exception:
            pass
        self._current_bubble.append_text(fragment)
        self.history[-1].content += fragment
        self._scroll_to_bottom()

    def _on_reasoning(self, fragment: str) -> None:
        if self._current_bubble is None: return
        try:
            self._current_bubble.set_status("Thinking…")
            self._current_bubble.append_reasoning(fragment)
        except Exception:
            pass
        self._scroll_to_bottom()

    def _on_status(self, text: str) -> None:
        if self._current_bubble is None: return
        try:
            self._current_bubble.set_status(text)
        except Exception:
            pass

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
            # Wire Approve / Deny on the inline ask-permission row.
            try:
                card.approve_requested.connect(self._on_tool_approved)
                card.deny_requested.connect(self._on_tool_denied)
            except Exception:
                pass
        self._scroll_to_bottom()

    def _on_tool_approved(self, inv) -> None:
        """User clicked Approve on a needs_confirmation tool. Re-run
        with user_confirmed=True, update the invocation in place,
        refresh the card."""
        try:
            result = self.router.tools.invoke(
                inv.tool_name, inv.arguments, user_confirmed=True,
            )
        except Exception as ex:
            result = {"status": "error",
                      "error": f"{type(ex).__name__}: {ex}"}
        inv.result = result
        inv.status = ("ok" if (result or {}).get("status") != "error"
                      else "error")
        if inv.id in self._current_invocations:
            _, card = self._current_invocations[inv.id]
            try:
                card.refresh()
            except Exception:
                pass
        # Add a system note to history so the next chat turn sees the
        # tool actually ran. Model can use the result on its next reply.
        try:
            note = (
                f"[user-approved] {inv.tool_name} ran. "
                f"Result: {str(result)[:200]}"
            )
            sys_msg = ChatMessage(role="system", content=note)
            self.history.append(sys_msg)
        except Exception:
            pass

    def _on_tool_denied(self, inv) -> None:
        """User clicked Deny. Mark the invocation as user-denied so the
        chat surface shows the failure without re-running anything."""
        inv.result = {
            "status": "error",
            "error": "Denied by user.",
            "policy": "denied_by_user",
        }
        inv.status = "error"
        if inv.id in self._current_invocations:
            _, card = self._current_invocations[inv.id]
            try:
                card.refresh()
            except Exception:
                pass
        try:
            sys_msg = ChatMessage(
                role="system",
                content=f"[user-denied] {inv.tool_name} blocked.",
            )
            self.history.append(sys_msg)
        except Exception:
            pass

    def _on_finished(self, response: LLMResponse) -> None:
        # Clear the bubble's per-turn status — the answer is now complete.
        if self._current_bubble is not None:
            try:
                self._current_bubble.set_status("")
            except Exception:
                pass
        # Reconciliation: the worker streams chunks via on_chunk, and
        # the bubble accumulates them. But some providers (Google,
        # ArchHub Cloud) return the entire response in a SINGLE chunk
        # — when that chunk's queued signal hasn't been processed by
        # the main thread before `finished` fires, the bubble stays
        # empty even though response.text has the full answer.
        # Force-set the bubble text from response.text if the bubble
        # is behind. This is the load-bearing fix for "I sent a
        # message and the assistant bubble stayed blank".
        try:
            final_text = (response.text or "").strip()
            if self._current_bubble is not None and final_text:
                rendered = self._current_bubble.text_view.toPlainText()
                if len(rendered) < len(final_text):
                    # Authoritative re-paint from the canonical text.
                    self._current_bubble.set_text(response.text)
                    if self.history:
                        self.history[-1].content = response.text
            elif self._current_bubble is not None and not final_text:
                # Provider returned an empty answer — surface a friendly
                # placeholder so the user doesn't stare at a blank
                # bubble wondering what happened.
                self._current_bubble.set_text(
                    "(empty response — provider returned no text. "
                    "Check Settings → Providers for credit / quota "
                    "issues.)"
                )
                if self.history:
                    self.history[-1].content = (
                        "(empty response — provider returned no text.)"
                    )
        except Exception:
            pass
        self._reset_input_state()
        if response.routing_note:
            self.status_left.setText(response.routing_note)
        # Persist after every assistant turn finishes. 5-min timer is
        # still wired as a backup; this catches every successful turn
        # so a crash loses at most one in-progress turn.
        try:
            self._autosave_session()
        except Exception:
            pass

    def _on_failed(self, msg: str) -> None:
        self._reset_input_state()
        if self._current_bubble is not None:
            self._current_bubble.append_text(f"\n\n[Error] {msg}")
            self.history[-1].content += f"\n\n[Error] {msg}"
        else:
            # No bubble was attached (e.g. failure happened in
            # _get_client before streaming began). Surface a system
            # message so the chat doesn't hang silently with the
            # typing dots from the previous turn.
            sys_msg = ChatMessage(role="system",
                                   content=f"[Error] {msg}")
            self.history.append(sys_msg)
            self._render_message(sys_msg)
        # Try a Studio toast too so the failure registers visually
        # outside the chat scroll area.
        try:
            from toast import show_toast
            show_toast(self.window(), msg, kind="err")
        except Exception:
            pass

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

    # ---- session restore -------------------------------------------------
    def _clear_chat_view(self) -> None:
        """Remove every message row from the conversation layout. Keeps
        the trailing stretch item so new bubbles still anchor top."""
        layout = self.conv_layout
        # Layout has rows + a final stretch — drop every widget item but
        # leave the stretch so insertWidget(count-1, ...) keeps working.
        i = 0
        while i < layout.count():
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None:
                i += 1
                continue
            layout.removeWidget(w)
            w.deleteLater()
        # Remove the welcome card if it's still around — restored
        # transcripts replace it.
        if getattr(self, "_welcome_widget", None) is not None:
            try:
                self._welcome_widget.deleteLater()
            except Exception:
                pass
            self._welcome_widget = None

    def _restore_history(self, msg_dicts: list[dict]) -> None:
        """Wipe the current chat view, rebuild ChatMessage objects from
        the persisted dicts, and re-render every bubble. Tool cards are
        restored from invocations[*]; images come back as paths.
        Called on session load."""
        self._clear_chat_view()
        self.history = []
        for d in msg_dicts or []:
            try:
                invs_raw = d.get("tool_invocations") or []
                invs: list[ToolInvocation] = []
                for r in invs_raw:
                    try:
                        invs.append(ToolInvocation(
                            id=r.get("id", ""),
                            tool_name=r.get("tool_name", ""),
                            arguments=r.get("arguments") or {},
                            status=r.get("status", "ok"),
                            result=r.get("result"),
                        ))
                    except Exception:
                        continue
                msg = ChatMessage(
                    role=d.get("role", "user"),
                    content=d.get("content", "") or "",
                    tool_invocations=invs,
                    images=list(d.get("images") or []),
                    model=d.get("model", "") or "",
                )
                self.history.append(msg)
                self._render_message(msg)
            except Exception:
                continue
        QTimer.singleShot(50, self._scroll_to_bottom)

    # ---- Misc --------------------------------------------------------------

    def _refresh_status(self) -> None:
        """Slim the status bar to actionable signals only (v1.3.1 cut).

        The header host pills already paint live host state with a dot;
        repeating "Live: Revit, AutoCAD" in the status bar was a
        REDUNDANT echo. The model picker dropdown already shows which
        providers are configured (greyed rows for unconfigured); the
        "LLM: openai, anthropic" right label was the same data twice.

        We keep the bar present (other call sites write transient
        status into it — e.g. routing notes, send-warnings) but clear
        the default echo. The empty-state nudge ("Add API keys…") stays
        because it's actionable: the user needs to know to open
        Settings before the chat will work."""
        self.manager.refresh()
        # Clear by default. The bar fills with transient status
        # messages from `_on_finished`, `_block_if_required_connector_inactive`,
        # `_propose_skill_match` etc. — those calls overwrite this line
        # when they have something to say.
        self.status_left.setText("")

        if self.router.has_credentials():
            # Picker already shows configured providers. Don't repeat.
            self.status_right.setText("")
        else:
            self.status_right.setText("Add API keys in Settings to start chatting")

    def _open_connectors(self) -> None:
        # TODO(shadow-audit): orphan since v1.3.2. No menu line and no
        # palette / programmatic caller wires to this. Remove after
        # confirming no external caller depends on it (the modal is
        # still reachable via onboarding.py "Open connector settings").
        dlg = ConnectorPanel(self.manager, self, router=self.router)
        dlg.exec()
        self._refresh_status()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.router, self)
        dlg.exec()
        self._refresh_status()

    # Legacy `_open_workflows` and `_save_chat_as_workflow` methods were
    # removed in the v1.3.1 dead-surface pass. The Skills panel is the
    # single library editor (`_open_skills_panel`) and capture verb
    # (`_save_chat_as_skill`). To revive workflow-only capture, restore
    # `_save_chat_as_workflow` from git history and re-add a menu line.

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

    # ---- URL detection in chat -------------------------------------------

    _URL_INTENT_HINTS: list[tuple[str, str, str]] = [
        # (regex pattern, skill_id_prefix, contextual hint to add)
        (r"(google\.[a-z.]+/maps|maps\.app\.goo\.gl|maps\.google\.com|@[\-\d.]+,[\-\d.]+,\d+\.?\d*z)",
         "seed-osm-context-mass-v1",
         "Looks like a map link — pulling OpenStreetMap buildings around it as Blender massing."),
        # Plain "lat, lng" coordinates anywhere in the prompt (whitespace-anchored
        # so we don't trip on "size 24.5, 54.3 mm"-style numbers).
        (r"(?:^|\s)(-?\d{1,3}\.\d{3,7})\s*,\s*(-?\d{1,3}\.\d{3,7})(?=$|\s|[,.;])",
         "seed-osm-context-mass-v1",
         "Coordinates detected — pulling OpenStreetMap buildings around them as Blender massing."),
        (r"\.dwg\b",
         "seed-export-revit-to-dwg-v1",
         "AutoCAD .dwg detected — exporting from Revit."),
    ]

    # Verbs that flip a .dwg-mention from "export FROM Revit"
    # (default) to "audit / inventory the open AutoCAD drawing".
    _DWG_AUDIT_VERBS = (
        "audit", "inventory", "what's in", "whats in", "what is in",
        "inside", "read", "scan", "check", "list layers", "list blocks",
        "summary of", "summarise", "summarize", "hygiene", "issues in",
    )

    def _detect_url_intent(self, prompt: str) -> Optional[str]:
        """Return the skill_id whose URL pattern matches this prompt, or None."""
        import re
        lowered = prompt.lower()
        for pat, skill_id, _hint in self._URL_INTENT_HINTS:
            if re.search(pat, prompt, re.IGNORECASE):
                # Disambiguate .dwg: audit verbs → inventory skill;
                # everything else → export-from-Revit skill (default).
                if skill_id == "seed-export-revit-to-dwg-v1":
                    if any(v in lowered for v in self._DWG_AUDIT_VERBS):
                        return "seed-acad-dwg-inventory-v1"
                return skill_id
        return None

    def _propose_skill_match(self, prompt: str) -> bool:
        """If a Skill matches strongly, propose it as an inline suggestion.
        Returns True if user is being prompted (caller should NOT continue
        to the LLM); False = no strong match, continue normal flow."""
        # URL intent fast-path: paste a Maps URL or .dwg path → propose
        # the matching Skill directly without going through the keyword
        # matcher, which would never match against URLs anyway.
        url_skill_id = self._detect_url_intent(prompt)
        if url_skill_id is not None:
            try:
                wf = skills.load_skill(url_skill_id)
                if wf is not None:
                    from skills.matcher import MatchResult
                    meta = skills.get_meta(wf)
                    self._render_skill_suggestion(
                        MatchResult(
                            skill_id=url_skill_id,
                            name=wf.name,
                            intent=meta.intent if meta else "",
                            score=1.0,
                            why="URL pattern match",
                            requires=meta.requires if meta else [],
                            examples=meta.examples if meta else [],
                        ),
                        prompt,
                    )
                    return True
            except Exception:
                pass     # fall through to keyword matcher

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
            content=(f"**Skill match:** {match.name}\n"
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
            f"Saved as Skill **{wf.name}**.\n"
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

        # Render an announce bubble + a live stepper card showing progress
        # through the skill's nodes. For single-stage skills this is a 1-row
        # check-as-you-go list; for multi-stage skills like
        # sketch-to-production it becomes a meaningful progress UI.
        announce = f"▶ Running Skill **{wf.name}**"
        msg = ChatMessage(role="assistant", content=announce,
                          model=self.model_picker.currentData())
        self.history.append(msg)
        bubble = self._render_message(msg)
        stepper = SkillStepperCard(wf)
        bubble.tool_cards_container.addWidget(stepper)

        # Run the workflow on a background thread so the UI keeps responding
        # while LLM stages execute (multi-stage pipelines can take minutes).
        worker = _SkillRunWorker(wf, inputs or {}, self.router, self.tools, self.manager)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_received.connect(stepper.handle_event)
        worker.finished.connect(
            lambda result: self._on_skill_run_done(
                skill_id, wf, result, bubble, stepper, msg
            )
        )
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Keep refs so they survive the local scope.
        self._skill_thread = thread
        self._skill_worker = worker
        self._skill_t0 = __import__("time").time()
        thread.start()

    def _retry_marker_for(self, skill_id: str, window_seconds: float = 60.0) -> Optional[str]:
        """Return a stable marker string if this run looks like a retry of a
        recent failure of the same Skill, else None.

        We treat re-running the same skill within `window_seconds` after a
        failure as a retry signal — strong proxy for "user re-asked because
        last answer was wrong." Used by `record_run` to bump the per-skill
        retry counter that the friction report consumes.
        """
        import time as _t
        prev = (self._last_skill_runs or {}).get(skill_id)
        if not prev or prev.get("success", True):
            return None
        age = _t.time() - prev.get("at", 0.0)
        if age > window_seconds:
            return None
        return f"{skill_id}@{int(prev['at'])}"

    def _on_skill_run_done(self, skill_id, wf, result, bubble, stepper, msg) -> None:
        import time as _time
        elapsed = int((_time.time() - getattr(self, "_skill_t0", _time.time())) * 1000)
        success = bool(result and result.success)
        error: str | None = None
        if not success and result is not None and result.errors:
            error = result.errors[0]
        summary = "Skill complete." if success else "Skill failed."
        if result and result.errors:
            summary += "\n" + "\n".join(result.errors[:5])
        if result and result.outputs:
            ans = result.outputs.get("answer")
            if isinstance(ans, str) and ans:
                summary += "\n\n" + ans
        announce = f"▶ Skill **{wf.name}**"
        bubble.set_text(f"{announce}\n\n{summary}")
        msg.content = bubble.text_view.toPlainText()
        stepper.finalise(success=success)

        # Retry detection: same skill_id failing twice inside 60s ≈ user
        # re-asking the same thing. Strong signal for the friction
        # report. We pass `retry_of` only if the last run was a failure
        # and within the window.
        retry_of = self._retry_marker_for(skill_id)
        try:
            skills.record_run(skill_id, success=success,
                              elapsed_ms=elapsed, error=error,
                              retry_of=retry_of)
        except Exception:
            pass
        # Update the per-skill last-run window for next call.
        self._last_skill_runs[skill_id] = {
            "at": _time.time(),
            "success": success,
        }

    def _open_skills_panel(self) -> None:
        dlg = SkillsPanel(self.router, self.tools, self.manager, self)
        dlg.skill_run_requested.connect(self._run_skill_by_id)
        dlg.workflow_run_requested.connect(self._run_workflow_by_id)
        dlg.exec()

    def _open_update_dialog(self) -> None:
        dlg = UpdateDialog(self)
        dlg.exec()

    def _open_pricing_dialog(self) -> None:
        from pricing_dialog import PricingDialog
        dlg = PricingDialog(self)
        dlg.exec()

    def _open_reality_check(self) -> None:
        # TODO(shadow-audit): orphan since v1.3.1. Telemetry page
        # embeds RealityCheckPanel for the live surface. Remove after
        # confirming no external caller depends on it.
        from reality_check_panel import RealityCheckDialog
        dlg = RealityCheckDialog(self.router, self)
        dlg.exec()

    # ---- model picker -----------------------------------------------------

    def _populate_model_picker(self) -> None:
        """Fill the model dropdown. Cloud-first when keys exist; if
        none do, Ollama models are surfaced automatically so the user
        always has SOMETHING they can pick. The Settings toggle
        'Show local Ollama models' force-shows them regardless."""
        from PyQt6.QtGui import QStandardItemModel, QStandardItem
        from secrets_store import load_setting

        configured = set(self.router.configured_providers())
        # Local Ollama models always surface when Ollama is reachable.
        # The legacy `show_local_models` setting (default False) used
        # to hide them — overriding that here because users repeatedly
        # asked "where's qwen / llama?" when their local models were
        # silently filtered out. To explicitly hide local models now,
        # set `hide_local_models=True` in Settings.
        hide_local = bool(load_setting("hide_local_models"))
        show_local = ("ollama" in configured) and not hide_local

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
            # Color comes from QSS (`QComboBox QAbstractItemView::item:disabled`)
            # so the dim shade follows the active palette in light AND dark
            # mode. The previous hardcoded `#6a6a6c` foreground was applied
            # to every disabled row regardless of theme — fine in light, but
            # against a dark dropdown bg (#1d1d22) it merged with neighbouring
            # enabled rows, making the WHOLE dropdown look greyed out.
            item_model.appendRow(item)

        _add("Auto · best model per task", ROUTE_AUTO, enabled=True,
             tooltip="ArchHub picks the best available model for each prompt.")

        # Blocked providers (out-of-credit / quota / rate-limit) get
        # marked inline so the user can see WHY the row is greyed out.
        try:
            blocked = self.router.blocked_providers()
        except Exception:
            blocked = {}
        for model_id, label in KNOWN_MODELS:
            provider = model_id.partition(":")[0]
            ok = provider in configured
            block_reason = blocked.get(provider, "")
            if not ok:
                suffix = "  (no key)"
                tip = (f"{provider.title()} not configured. "
                       f"Sign in via Settings (⚙) to enable.")
                row_enabled = False
            elif block_reason:
                suffix = f"  ({block_reason})"
                tip = (f"{provider.title()} temporarily unavailable: "
                       f"{block_reason}. Auto-retry in 10 min, or top "
                       f"up your account.")
                row_enabled = False
            else:
                suffix = ""
                tip = ""
                row_enabled = True
            _add(label + suffix, model_id, enabled=row_enabled,
                 tooltip=tip)

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
        msg = (f"{status.behind} update"
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
            f"Copied **{match['name']}** to your clipboard "
            f"({len(text):,} chars).\n"
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
            f"Imported Skill **{wf.name}**. The matcher can now find it."
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
            summary = "Workflow complete." if result.success else "Workflow failed."
            if result.errors:
                summary += "\n" + "\n".join(result.errors)
            bubble.set_text(f"{announce}\n\n{summary}")
            msg.content = bubble.text_view.toPlainText()
        except Exception as ex:
            bubble.set_text(f"{announce}\n\n[Error] {ex}")
            msg.content = bubble.text_view.toPlainText()

    def _save_session(self) -> None:
        from session_io import save_session
        # Default name from first user message — meaningful > "Session N"
        first = next((m.content.strip() for m in self.history
                       if m.role == "user" and (m.content or "").strip()), "")
        default_name = (first[:48] + "…") if len(first) > 48 else (
            first or f"Session {len(self.session.parameters)} params"
        )
        name, ok = QInputDialog.getText(
            self, "Save session", "Session name:", text=default_name,
        )
        if not ok or not name.strip():
            return
        try:
            path = save_session(self.session, name.strip(),
                                 messages=self.history)
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
        save_btn = QPushButton("Save current session")
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
                    from session_io import load_session_with_messages
                    p = Path(sel.data(Qt.ItemDataRole.UserRole))
                    new_session, name, msg_dicts = (
                        load_session_with_messages(p))
                    self.session = new_session
                    self.parameters_panel.set_session(self.session)
                    self._restore_history(msg_dicts)
                    self._autosave_path = p   # reuse on next autosave
                    dlg.accept()
                    QMessageBox.information(self, "Session loaded",
                        f"Loaded '{name}' — {len(new_session.parameters)} "
                        f"params · {len(msg_dicts)} messages.")
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
