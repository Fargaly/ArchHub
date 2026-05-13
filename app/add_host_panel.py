"""Add Host panel — Studio-native replacement for the modal onboarding wizard.

What it does
------------
Lists every host ArchHub knows about (Revit · AutoCAD · 3ds Max ·
Blender · Speckle · Outlook) and surfaces, per row:

  - Detection state          (installed on this machine? where?)
  - Connector state           (built? deployed? live?)
  - Action                    (Build · Activate · Refresh · n/a)

Build buttons stream progress via auto_build's on_progress callback so
the user sees real percent + status line per row, not a blocking modal.

Voice — strictly brand v0.1:
  ✅ "Revit 2024 detected at C:\\Program Files\\Autodesk\\Revit 2024."
  ❌ "Hooray! We found Revit!"
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

import auto_build
from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


# `from design_tokens import COLOR as T` was wrong: COLOR always points
# at the light theme, so dark mode painted host-name labels with
# light-theme ink (#1a1612) on dark bg (#1d1d22) — invisible. Use a
# proxy that delegates `T[key]` to whatever palette is active right now.
class _LivePalette:
    def __getitem__(self, k: str) -> str:
        return _current_palette()[k]
    def get(self, k: str, default=None):
        return _current_palette().get(k, default)
T = _LivePalette()


# Catalog of hosts surfaced in the panel. Each row drives a card.
# `kind` decides the action handler: "revit_year" / "acad_year" /
# "max_year" / "blender" / "speckle" / "outlook".
HOST_CATALOG = [
    {"id": "revit-2025",   "label": "Revit 2025",     "kind": "revit_year",   "year": 2025, "letter": "R"},
    {"id": "revit-2024",   "label": "Revit 2024",     "kind": "revit_year",   "year": 2024, "letter": "R"},
    {"id": "revit-2023",   "label": "Revit 2023",     "kind": "revit_year",   "year": 2023, "letter": "R"},
    {"id": "revit-2022",   "label": "Revit 2022",     "kind": "revit_year",   "year": 2022, "letter": "R"},
    {"id": "revit-2021",   "label": "Revit 2021",     "kind": "revit_year",   "year": 2021, "letter": "R"},
    {"id": "revit-2020",   "label": "Revit 2020",     "kind": "revit_year",   "year": 2020, "letter": "R"},
    {"id": "autocad-2026", "label": "AutoCAD 2026",   "kind": "acad_year",    "year": 2026, "letter": "A"},
    {"id": "autocad-2025", "label": "AutoCAD 2025",   "kind": "acad_year",    "year": 2025, "letter": "A"},
    {"id": "autocad-2024", "label": "AutoCAD 2024",   "kind": "acad_year",    "year": 2024, "letter": "A"},
    {"id": "max-2026",     "label": "3ds Max 2026",   "kind": "max_year",     "year": 2026, "letter": "M"},
    {"id": "max-2025",     "label": "3ds Max 2025",   "kind": "max_year",     "year": 2025, "letter": "M"},
    {"id": "blender",      "label": "Blender",        "kind": "blender",      "year": 0,    "letter": "B"},
    {"id": "rhino",        "label": "Rhino 7 / 8",    "kind": "rhino",        "year": 0,    "letter": "R"},
    {"id": "speckle",      "label": "Speckle",        "kind": "speckle",      "year": 0,    "letter": "S"},
    {"id": "outlook",      "label": "Outlook (classic)", "kind": "outlook",   "year": 0,    "letter": "O"},
]


# ---------------------------------------------------------------------------
class _BuildBridge(QObject):
    """Marshals auto_build's on_progress callbacks (worker thread) onto
    the Qt main thread via signals."""
    progress = pyqtSignal(str, int, str)            # stage, pct, line
    finished = pyqtSignal(bool, str)                # success, detail


# ---------------------------------------------------------------------------
class HostRow(QFrame):
    """One card in the Add Host panel."""
    def __init__(self, *, host: dict, manager, parent=None):
        super().__init__(parent)
        self.setObjectName("addHostRow")
        self.host = host
        self.manager = manager
        self._bridge: Optional[_BuildBridge] = None
        self._building = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["lg"]-2, SPACE["md"]-2,
                                 SPACE["lg"]-2, SPACE["md"]-2)
        outer.setSpacing(SPACE["xs"]+2)

        top = QHBoxLayout()
        top.setSpacing(SPACE["md"])

        self.icon = QLabel(host["letter"])
        self.icon.setObjectName("addHostIcon")
        self.icon.setFixedSize(34, 34)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.icon)

        col_w = QWidget()
        col = QVBoxLayout(col_w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.name = QLabel(host["label"])
        self.name.setObjectName("addHostName")
        col.addWidget(self.name)
        self.detail = QLabel("Probing…")
        self.detail.setObjectName("addHostDetail")
        self.detail.setWordWrap(True)
        col.addWidget(self.detail)
        top.addWidget(col_w, 1)

        self.action = QPushButton("…")
        self.action.setObjectName("addHostAction")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.clicked.connect(self._on_action)
        top.addWidget(self.action)

        outer.addLayout(top)

        # Progress bar (hidden until a build is running).
        self.progress = QProgressBar()
        self.progress.setObjectName("addHostProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        self.refresh_state()

    # ------------------------------------------------------------------
    def refresh_state(self) -> None:
        kind = self.host["kind"]
        try:
            if kind == "revit_year":
                self._refresh_revit()
            elif kind == "acad_year":
                self._refresh_acad()
            elif kind == "max_year":
                self._refresh_max()
            elif kind == "blender":
                self._refresh_blender()
            elif kind == "rhino":
                self._refresh_rhino()
            elif kind == "speckle":
                self._refresh_speckle()
            elif kind == "outlook":
                self._refresh_outlook()
        except Exception as ex:
            self.detail.setText(f"State probe failed — {type(ex).__name__}: {ex}")

    def _set_action(self, label: str, *, enabled: bool = True,
                    primary: bool = False) -> None:
        self.action.setText(label)
        self.action.setEnabled(enabled and not self._building)
        self.action.setProperty("primary", primary)
        # Re-style so :enabled state shows.
        self.action.setStyleSheet(_action_style(primary=primary,
                                                enabled=self.action.isEnabled()))

    def _entry(self):
        """Find the matching ConnectorEntry, or None."""
        if self.manager is None:
            return None
        for e in self.manager.entries:
            if e.id == self.host["id"]:
                return e
        return None

    def _refresh_revit(self) -> None:
        year = self.host["year"]
        path = auto_build.find_revit_install(year)
        entry = self._entry()
        if path is None:
            self.detail.setText("Not installed on this machine.")
            self._set_action("n/a", enabled=False)
            return
        # Detected — show install path + state.
        deployed = (Path("payload") / "Revit" / str(year) / "RevitMCP.dll")
        try:
            from manager import PAYLOAD_DIR, ConnectorState
            deployed = PAYLOAD_DIR / "Revit" / str(year) / "RevitMCP.dll"
        except Exception:
            ConnectorState = None
        active = (entry is not None and ConnectorState is not None
                  and entry.state == ConnectorState.ACTIVE)
        if active:
            self.detail.setText(f"Active · live at {path}.")
            self._set_action("Rebuild", primary=False)
        elif deployed.exists():
            self.detail.setText(f"Detected at {path}. Connector built — toggle on in HOSTS to load.")
            self._set_action("Activate", primary=True)
        else:
            self.detail.setText(f"Detected at {path}. Connector DLL not built yet.")
            self._set_action("Build", primary=True)

    def _refresh_acad(self) -> None:
        year = self.host["year"]
        path = auto_build.find_autocad_install(year)
        entry = self._entry()
        if path is None:
            self.detail.setText("Not installed on this machine.")
            self._set_action("n/a", enabled=False)
            return
        try:
            from manager import PAYLOAD_DIR, ConnectorState
            deployed = PAYLOAD_DIR / "AutoCAD" / str(year) / "AcadMCP.dll"
        except Exception:
            deployed, ConnectorState = Path(""), None
        active = (entry is not None and ConnectorState is not None
                  and entry.state == ConnectorState.ACTIVE)
        if active:
            self.detail.setText(f"Active · live at {path}.")
            self._set_action("Rebuild", primary=False)
        elif deployed.exists():
            self.detail.setText(f"Detected at {path}. Connector built — toggle on in HOSTS.")
            self._set_action("Activate", primary=True)
        else:
            self.detail.setText(f"Detected at {path}. Connector DLL not built yet.")
            self._set_action("Build", primary=True)

    def _refresh_max(self) -> None:
        year = self.host["year"]
        path = auto_build.find_max_install(year)
        if path is None:
            self.detail.setText("Not installed on this machine.")
            self._set_action("n/a", enabled=False)
            return
        self.detail.setText(f"Detected at {path}. Install copies the connector — no compile needed.")
        self._set_action("Install", primary=True)

    def _refresh_blender(self) -> None:
        # No SDK build needed — Blender connector is a Python script.
        self.detail.setText(
            "Python script connector — listens on :9876 when "
            "Blender's running and the addon is loaded."
        )
        self._set_action("Open instructions", primary=False)

    def _refresh_rhino(self) -> None:
        try:
            from connectors import rhino_runner as _rh
            exe = _rh.find_rhino_executable()
            version = _rh.detect_rhino_version(exe) if exe else None
            live = _rh.is_reachable()
        except Exception:
            exe, version, live = None, None, False
        if exe is None:
            self.detail.setText("Rhino not detected on this machine.")
            self._set_action("n/a", enabled=False)
            return
        if live:
            self.detail.setText(
                f"Rhino {version or '?'} live · MCP bridge on :9879."
            )
            self._set_action("Reinstall addon", primary=False)
            return
        self.detail.setText(
            f"Rhino {version or '?'} detected at {exe}. Bridge not "
            f"running — install the addon, then run "
            f"_-RunPythonScript archhub_mcp.py in Rhino."
        )
        self._set_action("Install addon", primary=True)

    def _refresh_speckle(self) -> None:
        self.detail.setText("Cloud only — sign in via Settings → Speckle.")
        self._set_action("Open Settings", primary=False)

    def _refresh_outlook(self) -> None:
        self.detail.setText(
            "COM proxy — works when classic Outlook is open. "
            "No DLL or activation needed."
        )
        self._set_action("Read-only", enabled=False)

    # ------------------------------------------------------------------
    def _on_action(self) -> None:
        if self._building:
            return
        kind = self.host["kind"]
        if kind == "revit_year":
            self._kick_revit()
        elif kind == "acad_year":
            self._kick_acad()
        elif kind == "max_year":
            self._kick_max()
        elif kind == "blender":
            self._show_blender_instructions()
        elif kind == "rhino":
            self._kick_rhino()
        elif kind == "speckle":
            self._open_settings_speckle()

    def _kick_revit(self) -> None:
        year = self.host["year"]
        # If we already have a deployed DLL and the user clicked
        # "Activate", just toggle the connector on through manager.
        if self.action.text().lower() == "activate" and self.manager is not None:
            ok, msg = self.manager.activate(self.host["id"])
            self.detail.setText(msg if not ok else "Activating…")
            QTimer.singleShot(800, self.refresh_state)
            return
        self._start_build(lambda cb: auto_build.build_revit_connector(year, on_progress=cb))

    def _kick_acad(self) -> None:
        year = self.host["year"]
        if self.action.text().lower() == "activate" and self.manager is not None:
            ok, msg = self.manager.activate(self.host["id"])
            self.detail.setText(msg if not ok else "Activating…")
            QTimer.singleShot(800, self.refresh_state)
            return
        self._start_build(lambda cb: auto_build.build_acad_connector(year, on_progress=cb))

    def _kick_max(self) -> None:
        year = self.host["year"]
        self._start_build(lambda cb: auto_build.install_max_connector(year, on_progress=cb))

    def _kick_rhino(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        try:
            from connectors import rhino_runner as _rh
            exe = _rh.find_rhino_executable()
            version = _rh.detect_rhino_version(exe)
            if not version:
                QMessageBox.warning(self, "Rhino",
                    "Could not detect Rhino version. Open Rhino, then "
                    "manually run _-RunPythonScript "
                    "payload/rhino/archhub_mcp.py."
                )
                return
            res = _rh.install_addon(version)
            if res.get("status") != "ok":
                QMessageBox.warning(self, "Rhino",
                    f"Could not install addon: {res.get('error', '?')}"
                )
                return
            QMessageBox.information(self, "Rhino addon installed",
                f"Copied to:\n{res['dest']}\n\n"
                f"In Rhino, run:\n"
                f"_-RunPythonScript archhub_mcp.py\n\n"
                f"The bridge will listen on :9879. ArchHub auto-detects."
            )
            QTimer.singleShot(800, self.refresh_state)
        except Exception as ex:
            QMessageBox.warning(self, "Rhino", f"Install failed: {ex}")

    def _show_blender_instructions(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Blender connector",
            "1. Open Blender.\n"
            "2. Edit → Preferences → Add-ons → Install...\n"
            "3. Pick payload/Blender/blender_mcp.zip from the ArchHub install.\n"
            "4. Enable 'ArchHub MCP'.\n"
            "5. Status bar will report 'live' on :9876."
        )

    def _open_settings_speckle(self) -> None:
        # Best-effort: bubble a request up to the parent shell.
        win = self.window()
        try:
            win._set_page("settings")  # noqa: SLF001
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Worker plumbing — run auto_build off the Qt thread, marshal back.
    # ------------------------------------------------------------------
    def _start_build(self, runner) -> None:
        self._building = True
        self._set_action("Building…", enabled=False)
        self.progress.setValue(0)
        self.progress.setVisible(True)

        bridge = _BuildBridge()
        bridge.progress.connect(self._on_progress)
        bridge.finished.connect(self._on_finished)
        self._bridge = bridge

        def _worker():
            def _cb(stage, pct, line=""):
                # auto_build's signature is (stage, pct, line) but some
                # internal callbacks pass only 2 args.
                bridge.progress.emit(str(stage), int(pct or 0), str(line or ""))
            try:
                result = runner(_cb)
                ok = bool(getattr(result, "success", False))
                detail = getattr(result, "detail", "")
                bridge.finished.emit(ok, str(detail))
            except Exception as ex:
                bridge.finished.emit(False, f"{type(ex).__name__}: {ex}")
        threading.Thread(target=_worker, daemon=True,
                         name=f"build-{self.host['id']}").start()

    def _on_progress(self, stage: str, pct: int, line: str) -> None:
        self.detail.setText(f"{stage} · {pct}%" + (f" · {line}" if line else ""))
        self.progress.setValue(max(0, min(int(pct), 100)))

    def _on_finished(self, ok: bool, detail: str) -> None:
        self._building = False
        self.progress.setValue(100 if ok else 0)
        QTimer.singleShot(1500, lambda: self.progress.setVisible(False))
        self.detail.setText(detail or ("Built." if ok else "Build failed."))
        self.refresh_state()


# ---------------------------------------------------------------------------
class AddHostPanel(QWidget):
    """Studio Add Host page — drop-in for the legacy onboarding wizard."""

    def __init__(self, *, manager, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPage")
        self.manager = manager

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header.
        head = QWidget()
        hh = QVBoxLayout(head)
        hh.setContentsMargins(40, 32, 40, 16)
        hh.setSpacing(4)
        cap = QLabel("ADD HOST")
        cap.setObjectName("studioMonoCap")
        hh.addWidget(cap)
        h1 = QLabel("Connect a host")
        h1.setObjectName("studioH1")
        hh.addWidget(h1)
        sub = QLabel(
            "ArchHub auto-detects every supported host. Click Build "
            "to compile a connector, or Activate to load one already "
            "built into a running session. .NET SDK is required for "
            "Revit + AutoCAD; no system dev packs needed."
        )
        sub.setObjectName("studioH1Sub")
        sub.setWordWrap(True)
        hh.addWidget(sub)
        outer.addWidget(head)

        # Toolbar — Refresh detection.
        tb = QHBoxLayout()
        tb.setContentsMargins(40, 0, 40, 8)
        refresh = QPushButton("↻ Refresh detection")
        refresh.setObjectName("studioChip")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self._refresh_all)
        tb.addWidget(refresh)
        tb.addStretch(1)
        sdk_label = QLabel("")
        sdk_label.setObjectName("studioMonoMuted")
        sdk_version = None
        try:
            sdk_version = auto_build.detect_dotnet_sdk()
        except Exception:
            sdk_version = None
        if sdk_version:
            sdk_label.setText(f".NET SDK · {sdk_version}")
            sdk_label.setStyleSheet(f"color:{T['ok']};")
        else:
            sdk_label.setText(".NET SDK · not detected")
            sdk_label.setStyleSheet(f"color:{T['warn']};")
        tb.addWidget(sdk_label)
        tb_w = QWidget(); tb_w.setLayout(tb)
        outer.addWidget(tb_w)

        # Warning banner — only shown if .NET SDK is missing. Build
        # buttons would fail fast otherwise, so explain up front.
        if not sdk_version:
            banner = QFrame()
            banner.setObjectName("addHostBanner")
            bh = QHBoxLayout(banner)
            bh.setContentsMargins(SPACE["lg"]-2, SPACE["sm"]+1,
                                  SPACE["lg"]-2, SPACE["sm"]+1)
            bh.setSpacing(SPACE["sm"])
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{T['warn']}; font-size:11px;")
            bh.addWidget(dot)
            msg = QLabel(
                ".NET SDK not found. Install it before building "
                "Revit / AutoCAD connectors. Get .NET 8 from "
                "dotnet.microsoft.com — Build buttons will work after."
            )
            msg.setObjectName("studioMonoMuted")
            msg.setWordWrap(True)
            bh.addWidget(msg, 1)
            banner_wrap = QWidget()
            bw = QVBoxLayout(banner_wrap)
            bw.setContentsMargins(40, 0, 40, SPACE["sm"])
            bw.addWidget(banner)
            outer.addWidget(banner_wrap)

        # Scrollable rail of host cards.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setObjectName("studioScroll")
        scroll.setStyleSheet(
            "QScrollArea#studioScroll { background:transparent; border:none; }")
        body = QWidget()
        body.setObjectName("studioPage")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(40, 0, 40, 40)
        bl.setSpacing(SPACE["sm"])
        self._rows: list[HostRow] = []
        for host in HOST_CATALOG:
            row = HostRow(host=host, manager=manager, parent=body)
            self._rows.append(row)
            bl.addWidget(row)
        bl.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.setStyleSheet(_panel_qss())

    def _refresh_all(self) -> None:
        try:
            if self.manager is not None:
                self.manager.refresh()
        except Exception:
            pass
        for r in self._rows:
            r.refresh_state()


# ---------------------------------------------------------------------------
def _action_style(*, primary: bool, enabled: bool) -> str:
    if not enabled:
        return (
            f"QPushButton#addHostAction {{ "
            f"  background:transparent; color:{T['inkDim']}; "
            f"  border:1px solid {T['line']}; "
            f"  border-radius:{RADIUS['md']}px; padding:6px 14px; "
            f"  font-family:{TYPE['fontSans']}; font-size:12px; "
            f"}}"
        )
    if primary:
        return (
            f"QPushButton#addHostAction {{ "
            f"  background:{T['accent']}; color:#fff; border:none; "
            f"  border-radius:{RADIUS['md']}px; padding:6px 14px; "
            f"  font-family:{TYPE['fontSans']}; font-size:12px; font-weight:500; "
            f"}}"
            f"QPushButton#addHostAction:hover {{ background:{T['accentHi']}; }}"
        )
    return (
        f"QPushButton#addHostAction {{ "
        f"  background:transparent; color:{T['inkSoft']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; padding:6px 14px; "
        f"  font-family:{TYPE['fontSans']}; font-size:12px; "
        f"}}"
        f"QPushButton#addHostAction:hover {{ "
        f"  border-color:{T['accent']}; color:{T['accent']}; }}"
    )


def _panel_qss() -> str:
    return (
        f"QFrame#addHostBanner {{ "
        f"  background:rgba(229, 178, 90, 0.08); "
        f"  border:1px solid {T['warn']}; "
        f"  border-radius:{RADIUS['md']}px; }}"
        f"QFrame#addHostRow {{ "
        f"  background:{T['bgRaised']}; border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['lg']}px; }}"
        f"QFrame#addHostRow:hover {{ border-color:{T['accent']}; }}"
        f"QLabel#addHostIcon {{ "
        f"  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        f"    stop:0 {T['accent']}, stop:1 {T['accentHi']}); "
        f"  color:#fff; font-family:{TYPE['fontSerif']}; font-style:italic; "
        f"  font-size:18px; border-radius:{RADIUS['md']+1}px; }}"
        f"QLabel#addHostName {{ font-size:14px; color:{T['ink']}; "
        f"  font-weight:500; }}"
        f"QLabel#addHostDetail {{ font-size:12.5px; color:{T['inkSoft']}; "
        f"  line-height:1.5; }}"
        f"QProgressBar#addHostProgress {{ "
        f"  background:{T['bgSoft']}; border:none; border-radius:2px; }}"
        f"QProgressBar#addHostProgress::chunk {{ "
        f"  background:{T['accent']}; border-radius:2px; }}"
    )
