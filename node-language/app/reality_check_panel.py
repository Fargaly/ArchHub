"""Reality Check (v0.42) — per-host 24h sparklines.

Replaces the previous one-shot probe dialog. The new panel is a
Studio-native page with:

  • One row per connector family (Revit, AutoCAD, Max, Blender,
    Outlook). Each row paints a 24h sparkline of the family's
    health state, success-rate %, last-failure timestamp, and the
    current live dot.
  • A "Run live probe" button at the top that fires the original
    end-to-end smoke test (kept as _ProbeWorker) into a status
    band below the rows.

The sparkline reads from `health_history`, which the
ConnectorHealth tick records into every 5s. State colors:
  live          → ok (terra-tinted green)
  loaded_dead   → warn (ochre)
  host_offline  → inkDim
  unknown       → inkDim
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional

from PyQt6.QtCore import QObject, QRectF, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


# Families surfaced in the panel + the order they render.
_FAMILIES: list[tuple[str, str]] = [
    ("revit", "Revit"),
    ("autocad", "AutoCAD"),
    ("max", "3ds Max"),
    ("blender", "Blender"),
    ("outlook", "Outlook"),
]


def _state_color(state: str) -> QColor:
    if state == "live":
        return QColor(T["ok"])
    if state == "loaded_dead":
        return QColor(T["warn"])
    return QColor(T["inkDim"])


# ---------------------------------------------------------------------------
class _Sparkline(QWidget):
    """Paints a sparkline of (timestamp, state) tuples across `window`
    seconds. Each segment is one state-run; color encodes state."""
    def __init__(self, family: str, *, window_seconds: int = 86400,
                  parent=None):
        super().__init__(parent)
        self._family = family
        self._window = window_seconds
        self.setMinimumSize(QSize(180, 24))
        self.setMaximumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setToolTip(f"Last 24h health for {family}")

    def refresh(self) -> None:
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            rect = self.rect().adjusted(0, 4, 0, -4)
            # Background track.
            p.fillRect(rect, QColor(T["bgSoft"]))
            # Resolve data.
            try:
                import health_history as hh
                items = hh.history(self._family, since_seconds=self._window)
            except Exception:
                items = []
            if not items:
                p.setPen(QPen(QColor(T["inkDim"]), 1, Qt.PenStyle.DashLine))
                y = rect.center().y()
                p.drawLine(rect.left(), y, rect.right(), y)
                return
            now = time.time()
            cutoff = now - self._window
            span = max(1.0, now - cutoff)

            def x_for(ts: float) -> float:
                clamped = max(cutoff, min(now, ts))
                return rect.left() + (clamped - cutoff) / span * rect.width()

            # Walk segments. First segment back-fills from cutoff so
            # the line covers the whole window — assume state held
            # before the window started.
            segs: list[tuple[float, float, str]] = []
            prev_t, prev_s = items[0]
            if prev_t > cutoff:
                segs.append((cutoff, prev_t, prev_s))
            for t, s in items[1:]:
                segs.append((prev_t, t, prev_s))
                prev_t, prev_s = t, s
            segs.append((prev_t, now, prev_s))

            for start, end, st in segs:
                x0 = x_for(start)
                x1 = x_for(end)
                if x1 - x0 < 0.5:
                    continue
                p.fillRect(QRectF(x0, rect.top(), max(1.0, x1 - x0),
                                   rect.height()), _state_color(st))
        finally:
            p.end()


# ---------------------------------------------------------------------------
class _HostRow(QFrame):
    """One row in the Reality Check list."""
    def __init__(self, family: str, label: str, parent=None):
        super().__init__(parent)
        self._family = family
        self.setObjectName("realityRow")
        h = QHBoxLayout(self)
        h.setContentsMargins(SPACE["sm"]+2, SPACE["xs"]+2,
                              SPACE["sm"]+2, SPACE["xs"]+2)
        h.setSpacing(SPACE["sm"])

        self.dot = QLabel("●")
        self.dot.setObjectName("realityDot")
        self.dot.setFixedWidth(14)
        h.addWidget(self.dot)

        name = QLabel(label)
        name.setObjectName("realityName")
        name.setMinimumWidth(80)
        h.addWidget(name)

        self.spark = _Sparkline(family)
        h.addWidget(self.spark, 1)

        self.rate = QLabel("—")
        self.rate.setObjectName("realityRate")
        self.rate.setFixedWidth(54)
        self.rate.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.rate)

        self.last_fail = QLabel("—")
        self.last_fail.setObjectName("realityFail")
        self.last_fail.setFixedWidth(110)
        self.last_fail.setAlignment(Qt.AlignmentFlag.AlignRight
                                     | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.last_fail)

    def refresh(self, current_state: str) -> None:
        color = _state_color(current_state)
        self.dot.setStyleSheet(f"color:{color.name()}; font-size:12px;")
        try:
            import health_history as hh
            sr = hh.success_rate(self._family)
            self.rate.setText(f"{int(round(sr * 100))}%")
            lf = hh.last_failure(self._family)
            if lf is None:
                self.last_fail.setText("none in 24h")
            else:
                ts, state = lf
                age = max(0, int(time.time() - ts))
                self.last_fail.setText(f"{_fmt_age(age)} · {state}")
        except Exception:
            pass
        self.spark.refresh()


def _fmt_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


# ---------------------------------------------------------------------------
# Live-probe worker — same behavior as v0.41's _ProbeWorker.
# ---------------------------------------------------------------------------
_PROBES: list[tuple[str, str, str, dict, str]] = [
    ("Revit",   "http://localhost:48884/ping",
     "http://localhost:48884/exec",
     {"code": "result = Doc.Title;", "transaction_name": "ArchHub: probe"},
     "result"),
    ("AutoCAD", "http://localhost:48885/ping",
     "http://localhost:48885/exec",
     {"code": "result = Doc.Name;"},
     "result"),
    ("3ds Max", "http://localhost:48886/max-mcp/ping",
     "http://localhost:48886/max-mcp/exec",
     {"code": "result = rt.maxFileName"},
     "result"),
    ("Blender", "http://localhost:9876/ping",
     "http://localhost:9876/exec",
     {"code": "import bpy; result = bpy.data.filepath or '(unsaved)'"},
     "result"),
]


class _ProbeWorker(QObject):
    finished = pyqtSignal(list)

    def run(self) -> None:
        results: list[dict] = []
        for label, ping_url, exec_url, payload, _key in _PROBES:
            entry = {"label": label, "ping": False, "exec": False,
                     "error": None, "ms": 0}
            t0 = time.time()
            try:
                with urllib.request.urlopen(ping_url, timeout=1.5) as r:
                    entry["ping"] = (200 <= r.status < 300)
            except Exception as ex:
                entry["error"] = f"ping: {type(ex).__name__}"
                entry["ms"] = int((time.time() - t0) * 1000)
                results.append(entry); continue
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    exec_url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10.0) as r:
                    body = json.loads(r.read().decode())
                entry["exec"] = (body or {}).get("status") == "ok"
            except Exception as ex:
                entry["error"] = f"exec: {type(ex).__name__}"
            entry["ms"] = int((time.time() - t0) * 1000)
            results.append(entry)
        self.finished.emit(results)


# ---------------------------------------------------------------------------
class RealityCheckPanel(QWidget):
    """Studio page version of Reality Check."""
    def __init__(self, *, router=None, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPage")
        self.router = router
        self._rows: dict[str, _HostRow] = {}
        self._build()
        self._refresh_timer = None
        self._start_refresh_timer()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 40)
        outer.setSpacing(SPACE["md"])

        # Header.
        cap = QLabel("REALITY CHECK")
        cap.setObjectName("studioMonoCap")
        outer.addWidget(cap)
        h1 = QLabel("Reality Check")
        h1.setObjectName("studioH1")
        outer.addWidget(h1)
        sub = QLabel(
            "Per-host health for the last 24 hours. Sparklines update "
            "every 5 seconds; the percentage is the time-weighted "
            "fraction the host was live."
        )
        sub.setObjectName("studioH1Sub")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # Top action row.
        tools = QHBoxLayout()
        tools.setSpacing(SPACE["sm"])
        self.btn_probe = QPushButton("Run live probe")
        self.btn_probe.setObjectName("primaryButton")
        self.btn_probe.clicked.connect(self._start_probe)
        tools.addWidget(self.btn_probe)
        self.probe_status = QLabel("")
        self.probe_status.setObjectName("studioMonoMuted")
        tools.addWidget(self.probe_status, 1)
        outer.addLayout(tools)

        # Column header row.
        hdr = QHBoxLayout()
        hdr.setContentsMargins(SPACE["sm"]+2, 0, SPACE["sm"]+2, 0)
        hdr.setSpacing(SPACE["sm"])
        for label, w in (("HOST", 14 + SPACE["sm"] + 80),
                         ("LAST 24H", -1),
                         ("UPTIME", 54),
                         ("LAST FAILURE", 110)):
            lbl = QLabel(label)
            lbl.setObjectName("studioMonoCap")
            if w > 0:
                lbl.setFixedWidth(w)
            hdr.addWidget(lbl, 1 if w < 0 else 0)
        outer.addLayout(hdr)

        # Host rows.
        rows_frame = QFrame()
        rows_frame.setObjectName("realityCard")
        rv = QVBoxLayout(rows_frame)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(1)
        for fam, label in _FAMILIES:
            row = _HostRow(fam, label)
            self._rows[fam] = row
            rv.addWidget(row)
        outer.addWidget(rows_frame)
        outer.addStretch(1)

        self.setStyleSheet(_qss())
        self._refresh_rows()

    # ------------------------------------------------------------------
    def _start_refresh_timer(self) -> None:
        from PyQt6.QtCore import QTimer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5_000)   # match health tick
        self._refresh_timer.timeout.connect(self._refresh_rows)
        self._refresh_timer.start()

    def _refresh_rows(self) -> None:
        try:
            from connector_health import instance as _hi
            health = _hi()
        except Exception:
            health = None
        for fam, row in self._rows.items():
            try:
                state = health.state(fam) if health else "unknown"
            except Exception:
                state = "unknown"
            row.refresh(state)

    # ------------------------------------------------------------------
    def _start_probe(self) -> None:
        self.btn_probe.setEnabled(False)
        self.probe_status.setText("Probing…")
        self._probe_thread = QThread(self)
        self._probe_worker = _ProbeWorker()
        self._probe_worker.moveToThread(self._probe_thread)
        self._probe_thread.started.connect(self._probe_worker.run)
        self._probe_worker.finished.connect(self._on_probe_done)
        self._probe_worker.finished.connect(self._probe_thread.quit)
        self._probe_thread.finished.connect(self._probe_worker.deleteLater)
        self._probe_thread.finished.connect(self._probe_thread.deleteLater)
        self._probe_thread.start()

    def _on_probe_done(self, results: list) -> None:
        self.btn_probe.setEnabled(True)
        if not results:
            self.probe_status.setText("Probe returned no data.")
            return
        wins = sum(1 for r in results if r.get("ping") and r.get("exec"))
        self.probe_status.setText(
            f"Probe done — {wins}/{len(results)} hosts answered."
        )


# ---------------------------------------------------------------------------
# Backwards-compat: keep the legacy modal dialog so older callers still
# work. Internally it's a wrapper around RealityCheckPanel.
# ---------------------------------------------------------------------------
class RealityCheckDialog(QDialog):
    def __init__(self, router=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ArchHub — Reality Check")
        self.resize(720, 480)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(RealityCheckPanel(router=router, parent=self))


def _qss() -> str:
    return (
        f"QFrame#realityCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; }}"
        f"QFrame#realityRow {{ background:transparent; }}"
        f"QFrame#realityRow:hover {{ background:{T['bgHover']}; }}"
        f"QLabel#realityName {{ {_lbl()} color:{T['ink']}; }}"
        f"QLabel#realityRate {{ {_lbl()} color:{T['accent']}; "
        f"  font-family:{TYPE['fontMono']}; }}"
        f"QLabel#realityFail {{ font-family:{TYPE['fontMono']}; "
        f"  font-size:10px; color:{T['inkMuted']}; "
        f"  letter-spacing:0.04em; }}"
    )


def _lbl() -> str:
    return (
        f"font-family:{TYPE['fontSans']}; font-size:12.5px; "
    )
