"""Parameters sidebar — live UI for the session's parameter pool.

Each parameter renders as the right kind of control:
  - LENGTH/ANGLE/NUMBER  → labeled slider + numeric spinbox (kept in sync)
  - INTEGER              → spinbox
  - BOOLEAN              → toggle switch
  - ENUM                 → dropdown
  - COLOR                → color swatch button (opens picker)
  - STRING               → single-line text field
  - IMAGE / GEOMETRY     → readonly path label with a "view" link

The widget watches the session's notification hooks. When a new parameter
appears it is added to the panel immediately. When a value changes from
elsewhere (e.g. a chat turn that updates a parameter via the LLM) the
control is updated in place without firing a feedback edit event.

Edits in the panel route to session.update_parameter() which marks dirty
downstream steps. The panel does NOT trigger re-runs itself; it emits a
Qt signal `parameter_edited(name, value)` that the chat window subscribes
to and decides whether to dispatch the runner.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from session import (
    Parameter, ParamType, Session,
)


# ---------------------------------------------------------------------------
# Per-parameter row widgets.
# ---------------------------------------------------------------------------

class ParamRow(QFrame):
    """Base row: a header (label + unit/range) and a control area below it."""
    edited = pyqtSignal(str, object)              # (parameter_name, new_value)

    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(parent)
        self.param = param
        self._suppress = False
        self.setObjectName("paramRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        # ---- header ----
        head = QHBoxLayout(); head.setSpacing(6)
        self.label = QLabel(param.label)
        self.label.setObjectName("paramLabel")
        head.addWidget(self.label, 1)
        meta_text = ""
        if param.unit:
            meta_text = param.unit
        elif param.type == ParamType.ENUM and param.options:
            meta_text = f"{len(param.options)} options"
        if meta_text:
            self.meta = QLabel(meta_text)
            self.meta.setObjectName("paramMeta")
            head.addWidget(self.meta, 0, Qt.AlignmentFlag.AlignRight)
        outer.addLayout(head)

        # ---- control (subclasses populate) ----
        self.control_layout = QHBoxLayout(); self.control_layout.setSpacing(8)
        outer.addLayout(self.control_layout)

    def _emit(self, value) -> None:
        if self._suppress: return
        self.edited.emit(self.param.name, value)

    def update_value(self, value) -> None:
        """Subclasses override. Should NOT emit `edited`."""
        self._suppress = True
        try: self._set_value(value)
        finally: self._suppress = False

    def _set_value(self, value) -> None:                     # pragma: no cover
        raise NotImplementedError


class NumericRow(ParamRow):
    """Slider + spinbox kept in sync. Used for NUMBER, LENGTH, ANGLE."""
    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(param, parent)
        lo = float(param.min if param.min is not None else 0.0)
        hi = float(param.max if param.max is not None else max(lo + 100.0, float(param.value or 0) * 2))
        step = float(param.step or (hi - lo) / 100.0 or 0.1)

        # Qt's QSlider only does ints — scale by an internal factor to support floats
        self._scale = 1.0 / step if step > 0 else 100.0
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(lo * self._scale))
        self.slider.setMaximum(int(hi * self._scale))
        self.slider.setSingleStep(1)
        self.slider.setTracking(True)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        decimals = 0 if param.type == ParamType.ANGLE else max(0, len(str(step).split(".")[-1]) if "." in str(step) else 0)
        self.spin.setDecimals(decimals)
        self.spin.setMinimumWidth(72)
        self.spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)

        self._set_value(param.value or 0.0)

        self.control_layout.addWidget(self.slider, 1)
        self.control_layout.addWidget(self.spin, 0)

        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)

    def _on_slider(self, raw: int) -> None:
        v = raw / self._scale
        self._suppress = True
        self.spin.setValue(v)
        self._suppress = False
        self._emit(v)

    def _on_spin(self, v: float) -> None:
        self._suppress = True
        self.slider.setValue(int(v * self._scale))
        self._suppress = False
        self._emit(v)

    def _set_value(self, value) -> None:
        v = float(value or 0.0)
        self.spin.setValue(v)
        self.slider.setValue(int(v * self._scale))


class IntegerRow(ParamRow):
    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(param, parent)
        self.spin = QSpinBox()
        self.spin.setRange(int(param.min or 0), int(param.max or 1000))
        self.spin.setSingleStep(int(param.step or 1))
        self.spin.setMinimumWidth(80)
        self._set_value(param.value or 0)
        self.control_layout.addWidget(self.spin, 1)
        self.spin.valueChanged.connect(self._emit)

    def _set_value(self, value) -> None:
        self.spin.setValue(int(value or 0))


class BooleanRow(ParamRow):
    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(param, parent)
        self.check = QCheckBox()
        self._set_value(bool(param.value))
        self.control_layout.addWidget(self.check, 0)
        self.control_layout.addStretch(1)
        self.check.stateChanged.connect(lambda s: self._emit(s == Qt.CheckState.Checked.value))

    def _set_value(self, value) -> None:
        self.check.setChecked(bool(value))


class EnumRow(ParamRow):
    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(param, parent)
        self.combo = QComboBox()
        self.combo.addItems(param.options or [])
        self._set_value(param.value)
        self.control_layout.addWidget(self.combo, 1)
        self.combo.currentTextChanged.connect(self._emit)

    def _set_value(self, value) -> None:
        if value is None: return
        idx = self.combo.findText(str(value))
        if idx >= 0: self.combo.setCurrentIndex(idx)


class ColorRow(ParamRow):
    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(param, parent)
        self.swatch = QPushButton()
        self.swatch.setFixedHeight(28)
        self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_value(param.value or "#cc785c")
        self.swatch.clicked.connect(self._open_picker)
        self.control_layout.addWidget(self.swatch, 1)

    def _open_picker(self) -> None:
        cur = QColor(self.param.value or "#cc785c")
        new = QColorDialog.getColor(cur, self, "Pick color")
        if new.isValid():
            hexv = new.name()
            self._set_value(hexv)
            self._emit(hexv)

    def _set_value(self, value) -> None:
        hexv = str(value or "#cc785c")
        self.param.value = hexv
        self.swatch.setStyleSheet(
            f"background-color: {hexv}; border: 1px solid #3c3c40; border-radius: 4px;")
        self.swatch.setText(hexv.upper())


class StringRow(ParamRow):
    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(param, parent)
        self.edit = QLineEdit()
        self._set_value(param.value or "")
        self.control_layout.addWidget(self.edit, 1)
        self.edit.editingFinished.connect(lambda: self._emit(self.edit.text()))

    def _set_value(self, value) -> None:
        self.edit.setText(str(value or ""))


class ReadonlyRow(ParamRow):
    """Used for IMAGE / GEOMETRY — paths are not directly editable."""
    def __init__(self, param: Parameter, parent=None) -> None:
        super().__init__(param, parent)
        self.lbl = QLabel(str(param.value or ""))
        self.lbl.setObjectName("paramReadonly")
        self.lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl.setWordWrap(True)
        self.control_layout.addWidget(self.lbl, 1)

    def _set_value(self, value) -> None:
        self.lbl.setText(str(value or ""))


def _row_for(param: Parameter) -> ParamRow:
    t = param.type
    if t in (ParamType.NUMBER, ParamType.LENGTH, ParamType.ANGLE):
        return NumericRow(param)
    if t == ParamType.INTEGER:
        return IntegerRow(param)
    if t == ParamType.BOOLEAN:
        return BooleanRow(param)
    if t == ParamType.ENUM:
        return EnumRow(param)
    if t == ParamType.COLOR:
        return ColorRow(param)
    if t == ParamType.STRING:
        return StringRow(param)
    if t in (ParamType.IMAGE, ParamType.GEOMETRY, ParamType.POINT3):
        return ReadonlyRow(param)
    return StringRow(param)


# ---------------------------------------------------------------------------
# The panel.
# ---------------------------------------------------------------------------

class ParametersPanel(QWidget):
    """Sidebar that mirrors the session's parameter pool.

    Emits `parameter_edited(name, value)` when the user changes any control.
    The chat window connects this to session.update_parameter and decides
    whether to dispatch the runner immediately or coalesce edits.
    """
    parameter_edited = pyqtSignal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("paramsPanel")
        self.setMinimumWidth(280)

        self._session: Optional[Session] = None
        self._rows: dict[str, ParamRow] = {}

        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # Header
        header = QFrame(); header.setObjectName("paramsPanelHeader")
        h = QVBoxLayout(header); h.setContentsMargins(16, 14, 16, 12); h.setSpacing(2)
        title = QLabel("Parameters"); title.setObjectName("paramsPanelTitle")
        sub = QLabel("Live values from the current session.")
        sub.setObjectName("paramsPanelSubtitle"); sub.setWordWrap(True)
        h.addWidget(title); h.addWidget(sub)
        outer.addWidget(header)

        # Empty state
        self.empty = QLabel("No parameters yet.\nStart a chat that builds something.")
        self.empty.setObjectName("paramsPanelEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)

        # Scroll area
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.body = QWidget(); self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 8, 8, 8); self.body_layout.setSpacing(6)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)

        outer.addWidget(self.empty, 0)
        outer.addWidget(self.scroll, 1)
        self.empty.show(); self.scroll.hide()

    # ---- public API -------------------------------------------------------

    def set_session(self, session: Session) -> None:
        """Bind to a session. Disconnects from any previous one."""
        if self._session is session: return
        self._session = session

        # Clear existing rows
        for row in self._rows.values():
            row.setParent(None); row.deleteLater()
        self._rows.clear()
        self._sync_empty()

        # Hook session events
        session.on_parameter_added   = self._on_added
        session.on_parameter_changed = self._on_changed

        # Populate from any pre-existing parameters
        for p in session.parameters.values():
            self._on_added(p)

    # ---- session callbacks ----

    def _on_added(self, param: Parameter) -> None:
        if param.name in self._rows: return
        row = _row_for(param)
        row.edited.connect(self.parameter_edited.emit)
        self._rows[param.name] = row
        # Insert before the trailing stretch
        self.body_layout.insertWidget(self.body_layout.count() - 1, row)
        self._sync_empty()

    def _on_changed(self, param: Parameter) -> None:
        row = self._rows.get(param.name)
        if row is not None:
            row.update_value(param.value)

    def _sync_empty(self) -> None:
        any_rows = bool(self._rows)
        self.scroll.setVisible(any_rows)
        self.empty.setVisible(not any_rows)
