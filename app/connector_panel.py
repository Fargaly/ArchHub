"""Connector panel — modal dialog showing toggles for each AEC tool."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QRectF, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from manager import ConnectorManager, ConnectorState, ConnectorEntry


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._knob_x = 24 if checked else 4
        self._anim = QPropertyAnimation(self, b"_knob_x_property")
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_knob_x(self): return self._knob_x
    def set_knob_x(self, v): self._knob_x = v; self.update()
    _knob_x_property = pyqtProperty(float, fget=get_knob_x, fset=set_knob_x)

    def isChecked(self): return self._checked

    def setChecked(self, checked: bool, animate=True) -> None:
        if checked == self._checked: return
        self._checked = checked
        target = 24 if checked else 4
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._knob_x)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._knob_x = target; self.update()

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

    def _status_text(self) -> str:
        s = self.entry.state
        if s == ConnectorState.ACTIVE:      return "Live · " + (self.entry.detail or "connected")
        if s == ConnectorState.READY:       return "Detected · off"
        if s == ConnectorState.UNAVAILABLE: return "Not installed"
        if s == ConnectorState.ERROR:       return "Error · " + (self.entry.detail or "see settings")
        return ""

    def _on(self, on: bool) -> None:
        self.on_toggle(self.entry, on)
        # After the manager has run activate/deactivate, the entry's state
        # reflects what really happened — which may differ from what the user
        # clicked (e.g. activation failed because a payload is missing). Sync
        # the toggle widget back to the actual state so the UI doesn't lie.
        actual_on = self.entry.state == ConnectorState.ACTIVE
        if actual_on != on:
            self.toggle.setChecked(actual_on, animate=True)
        self.status.setText(self._status_text())


class ConnectorPanel(QDialog):
    def __init__(self, manager: ConnectorManager, parent=None):
        super().__init__(parent)
        self.manager = manager
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
        else:
            self.manager.deactivate(entry.id)
