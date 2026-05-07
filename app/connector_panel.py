"""Connector panel — modal dialog showing toggles for each AEC tool."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from manager import ConnectorManager, ConnectorState, ConnectorEntry
from build_progress_dialog import BuildProgressDialog
import auto_build


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    _ANIM_DURATION_MS = 140
    _ANIM_INTERVAL_MS = 10

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._knob_x = 24.0 if checked else 4.0
        self._anim_target = self._knob_x
        self._anim_steps_left = 0
        self._anim_step_size = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self._ANIM_INTERVAL_MS)
        self._timer.timeout.connect(self._anim_tick)

    def isChecked(self): return self._checked

    def setChecked(self, checked: bool, animate=True) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        target = 24.0 if checked else 4.0
        if animate:
            steps = max(1, self._ANIM_DURATION_MS // self._ANIM_INTERVAL_MS)
            self._anim_target = target
            self._anim_steps_left = steps
            self._anim_step_size = (target - self._knob_x) / steps
            self._timer.start()
        else:
            self._timer.stop()
            self._knob_x = target
            self.update()

    def _anim_tick(self) -> None:
        if self._anim_steps_left <= 0:
            self._timer.stop()
            self._knob_x = self._anim_target
            self.update()
            return
        self._knob_x += self._anim_step_size
        self._anim_steps_left -= 1
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        super().mousePressEvent(ev)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor("#cc785c" if self._checked else "#2a2a2c")
        p.setBrush(QBrush(track)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 13, 13)
        p.setBrush(QBrush(QColor("#f4efe8")))
        p.drawEllipse(QRectF(self._knob_x, 3, 20, 20))


class _Row(QFrame):
    def __init__(self, entry: ConnectorEntry, on_toggle, parent=None):
        super().__init__(parent)
        self.setObjectName("connectorRow")
        self.entry = entry
        self.on_toggle = on_toggle
        self.setMinimumHeight(72)

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(14)

        icon = QLabel(entry.short_letter)
        icon.setObjectName("connectorIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(40, 40)
        h.addWidget(icon)

        col = QVBoxLayout(); col.setSpacing(2)
        name = QLabel(entry.display_name); name.setObjectName("connectorName")
        col.addWidget(name)
        self.status = QLabel(self._status_text())
        self.status.setObjectName("connectorStatus")
        col.addWidget(self.status)
        h.addLayout(col, 1)

        self.toggle = ToggleSwitch(entry.state == ConnectorState.ACTIVE)
        if entry.state == ConnectorState.UNAVAILABLE:
            self.setEnabled(False)
        self.toggle.toggled.connect(self._on)
        h.addWidget(self.toggle)

    # Local listener probe ports per family. Used to differentiate
    # 'Active in registry' (the lying status) from 'Listener actually
    # responding' (the truth).
    _PROBE_URL = {
        "revit":   "http://localhost:48884/ping",
        "autocad": "http://localhost:48885/ping",
        "max":     "http://localhost:48886/ping",
        "blender": "http://localhost:9876/ping",
    }

    def _listener_alive(self) -> bool:
        url = self._PROBE_URL.get((self.entry.family or "").lower())
        if not url:
            # Connectors without a listener (Speckle / Outlook) — treat
            # ACTIVE registry state as truth.
            return True
        import urllib.request, urllib.error
        try:
            with urllib.request.urlopen(url, timeout=0.6) as r:
                return 200 <= r.status < 300
        except Exception:
            return False

    def _status_text(self) -> str:
        s = self.entry.state
        if s == ConnectorState.ACTIVE:
            if self._listener_alive():
                return "Live · " + (self.entry.detail or "connected")
            # ACTIVE registry but listener dead = addin loaded once,
            # process closed/restarted, or never auto-loaded. Tell the
            # user the truth instead of lying 'Live'.
            return "Loaded · waiting for host (open the app or run NETLOAD)"
        if s == ConnectorState.READY:       return "Detected · off"
        if s == ConnectorState.UNAVAILABLE: return "Not installed"
        if s == ConnectorState.ERROR:       return "Error · " + (self.entry.detail or "see settings")
        return ""

    def _on(self, on: bool) -> None:
        print(f"[connector] toggle {self.entry.id} -> {on}", flush=True)
        self.on_toggle(self.entry, on)
        print(f"[connector] post-toggle state={self.entry.state}", flush=True)

        # If activation failed because the binary isn't there, offer to build it
        # automatically — no terminal, no copy-paste. The connector panel calls
        # us back through on_toggle to retry after a successful build.
        if (on and self.entry.state == ConnectorState.ERROR
                and self._is_missing_payload_error(self.entry.detail)):
            print(f"[connector] offering auto-setup for {self.entry.id}", flush=True)
            if self._offer_auto_setup():
                return  # user accepted; setup dialog will retry the toggle

        # Sync the toggle's visual state to the actual state — never lie.
        actual_on = self.entry.state == ConnectorState.ACTIVE
        if actual_on != on:
            self.toggle.setChecked(actual_on, animate=True)
        self.status.setText(self._status_text())

    def _is_missing_payload_error(self, detail: str | None) -> bool:
        if not detail:
            return False
        d = detail.lower()
        return ("no " in d and "payload" in d) or "payload" in d and "missing" in d

    def _offer_auto_setup(self) -> bool:
        """Ask the user whether to auto-build the connector. Returns True if accepted."""
        family = (self.entry.family or "").lower()
        # Try to extract the year from the connector id (e.g. "revit-2025")
        year_match = next((tok for tok in (self.entry.id or "").split("-")
                           if tok.isdigit() and len(tok) == 4), None)
        if not year_match:
            return False
        year = int(year_match)

        msg = QMessageBox(self)
        msg.setWindowTitle("Set up this connector?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(f"<b>{self.entry.display_name}</b> needs a one-time setup.")
        msg.setInformativeText(
            "ArchHub will configure it for you automatically — no terminal, "
            "no copy-paste. This usually takes under a minute.\n\n"
            "Set it up now?"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes |
                               QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return False

        # Pick the right setup function for the family.
        # Cloud-first: try to fetch a prebuilt MCP DLL bundle from the
        # latest GitHub Release; only fall back to a local `dotnet
        # build` if the fetch fails (no internet, private repo, etc.).
        # The local-build path needs the .NET SDK and is the slow,
        # error-prone path we used to lead with — it's now the safety
        # net, not the default.
        from mcp_fetcher import fetch_connector

        def _cloud_then_local(builder):
            def runner(cb):
                fr = fetch_connector(family, year, on_progress=cb)
                if fr.success:
                    from auto_build import BuildResult
                    return BuildResult(True, fr.detail, fr.files_written)
                cb("Cloud fetch failed, falling back to local build", 10, fr.detail)
                return builder(cb)
            return runner

        build_fn = None
        title = f"Setting up {self.entry.display_name}"
        if family == "revit":
            build_fn = _cloud_then_local(
                lambda cb: auto_build.build_revit_connector(year, cb))
        elif family in ("autocad", "acad"):
            build_fn = _cloud_then_local(
                lambda cb: auto_build.build_acad_connector(year, cb))
        elif family in ("max", "3dsmax"):
            # 3ds Max connector is a Python script, no compile needed.
            build_fn = lambda cb: auto_build.install_max_connector(year, cb)
        else:
            return False

        dlg = BuildProgressDialog(self, title, build_fn=build_fn)
        dlg.exec()

        # If the build succeeded, retry activation
        if dlg.result_ok:
            self.on_toggle(self.entry, True)
            actual_on = self.entry.state == ConnectorState.ACTIVE
            self.toggle.setChecked(actual_on, animate=True)
            self.status.setText(self._status_text())
            return True

        # Build failed or cancelled — snap toggle back to off
        self.toggle.setChecked(False, animate=True)
        self.status.setText(self._status_text())
        return True   # we handled the UI sync ourselves


class ConnectorPanel(QDialog):
    def __init__(self, manager: ConnectorManager, parent=None, router=None):
        super().__init__(parent)
        self.manager = manager
        self._router = router
        self.setWindowTitle("ArchHub — Connectors")
        self.setObjectName("panel")
        self.resize(520, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(); header.setObjectName("panelHeader")
        hl = QVBoxLayout(header); hl.setContentsMargins(24, 22, 24, 18); hl.setSpacing(4)
        t = QLabel("Connect your tools"); t.setObjectName("panelTitle")
        s = QLabel("Toggle to make a tool available. Open the tool to start the live link.")
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        hl.addWidget(t); hl.addWidget(s)
        outer.addWidget(header)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setObjectName("panelScroll"); scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(16, 8, 16, 16); self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        scroll.setWidget(self.list_container)
        outer.addWidget(scroll, 1)

        footer = QFrame(); footer.setObjectName("panelFooter")
        fh = QHBoxLayout(footer); fh.setContentsMargins(20, 12, 20, 14)
        refresh = QPushButton("↻ Refresh"); refresh.setObjectName("ghostButton")
        refresh.clicked.connect(self._refresh)
        fh.addWidget(refresh); fh.addStretch(1)
        close = QPushButton("Close"); close.setObjectName("primaryButton")
        close.clicked.connect(self.accept)
        fh.addWidget(close)
        outer.addWidget(footer)

        self._rows: list[_Row] = []
        self._build_rows()

    def _build_rows(self) -> None:
        for r in self._rows:
            self.list_layout.removeWidget(r); r.deleteLater()
        self._rows.clear()
        for e in self.manager.entries:
            row = _Row(e, self._on_toggle, self.list_container)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows.append(row)

    def _refresh(self) -> None:
        self.manager.refresh()
        self._build_rows()

    def _on_toggle(self, entry, on: bool) -> None:
        if on:
            self.manager.activate(entry.id)
            # Post-activation: for Blender, kick off meta-connector generation
            if entry.family == "blender" and entry.state.name == "ACTIVE":
                self._trigger_blender_meta_gen(entry)
        else:
            self.manager.deactivate(entry.id)

    def _trigger_blender_meta_gen(self, entry) -> None:
        """Background: generate improved Blender addon via meta-connector if router available."""
        # Only if we have a router (passed from ChatWindow). Skip silently if not.
        router = getattr(self, "_router", None)
        if router is None:
            return
        import threading
        from connectors import blender_runner
        version = blender_runner.detect_blender_version(
            blender_runner.find_blender_executable() or __import__("pathlib").Path("/")
        ) or "4.0"

        def generate():
            try:
                from meta_connector import generate_blender_addon
                result = generate_blender_addon(version, router)
                if result and result.files:
                    blender_runner.install_addon(result, blender_version=version)
            except Exception:
                pass   # silent — fallback addon still works

        t = threading.Thread(target=generate, daemon=True)
        t.start()
