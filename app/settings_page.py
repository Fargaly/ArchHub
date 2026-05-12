"""Studio-native sectioned Settings page (v0.41).

The legacy SettingsDialog still works as a modal entry point, but
embedding it directly into the Studio shell crammed every knob —
provider keys, cloud sync, Speckle, telemetry, Discord webhooks,
firm relay — into one tall scrolling rail. v0.41 wraps that content
in a sectioned chrome (left nav + QStackedWidget) so the user
navigates between concern areas the way macOS System Settings does.

For v0.41 we ship three sections without refactoring the
SettingsDialog internals (which are tightly coupled to that class's
self._* state):

  • Providers   — wraps SettingsDialog as-is
  • About       — version, git sha, changelog
  • Diagnostics — connector health snapshot, log file path,
                   "open data folder" button

Future PRs split the Providers section into Sign-ins / Cloud sync /
Privacy / Speckle as the SettingsDialog refactor lands.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


# Section catalog — (id, label, builder_method). Builder lives on
# SettingsPage to keep self._router available.
_SECTIONS: list[tuple[str, str]] = [
    ("providers", "Providers"),
    ("ai_behaviour", "AI Behaviour"),
    ("about", "About"),
    ("diagnostics", "Diagnostics"),
]


class SettingsPage(QWidget):
    def __init__(self, router=None, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPage")
        self.router = router
        self._buttons: dict[str, QPushButton] = {}
        self._build()
        self._select("providers")

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header row — caption + h1 + sub.
        head = QWidget()
        hh = QVBoxLayout(head)
        hh.setContentsMargins(40, 32, 40, 12)
        hh.setSpacing(4)
        cap = QLabel("SETTINGS")
        cap.setObjectName("studioMonoCap")
        hh.addWidget(cap)
        h1 = QLabel("Settings")
        h1.setObjectName("studioH1")
        hh.addWidget(h1)
        sub = QLabel(
            "Sign-ins, cloud sync, privacy, diagnostics. "
            "Changes take effect on save — no restart needed."
        )
        sub.setObjectName("studioH1Sub")
        sub.setWordWrap(True)
        hh.addWidget(sub)
        outer.addWidget(head)

        # Body row — left nav + right content stack.
        body = QWidget()
        bh = QHBoxLayout(body)
        bh.setContentsMargins(40, 0, 40, 40)
        bh.setSpacing(SPACE["lg"])

        # Left nav (sectioned chrome).
        nav = QFrame()
        nav.setObjectName("settingsNav")
        nav.setFixedWidth(180)
        nv = QVBoxLayout(nav)
        nv.setContentsMargins(SPACE["sm"], SPACE["sm"],
                               SPACE["sm"], SPACE["sm"])
        nv.setSpacing(2)
        cap2 = QLabel("SECTIONS")
        cap2.setObjectName("studioMonoCap")
        nv.addWidget(cap2)
        nv.addSpacing(SPACE["xs"])
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for sid, label in _SECTIONS:
            btn = QPushButton(label)
            btn.setObjectName("settingsNavBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, s=sid: self._select(s))
            self._group.addButton(btn)
            self._buttons[sid] = btn
            nv.addWidget(btn)
        nv.addStretch(1)
        bh.addWidget(nav, 0)

        # Right content stack.
        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsStack")
        bh.addWidget(self.stack, 1)

        # Build each section once + add to stack in declared order.
        self.stack.addWidget(self._build_providers_section())
        self.stack.addWidget(self._build_ai_behaviour_section())
        self.stack.addWidget(self._build_about_section())
        self.stack.addWidget(self._build_diagnostics_section())

        outer.addWidget(body, 1)
        self.setStyleSheet(_qss())

    # ------------------------------------------------------------------
    def _select(self, section_id: str) -> None:
        try:
            idx = next(i for i, (sid, _) in enumerate(_SECTIONS)
                        if sid == section_id)
        except StopIteration:
            return
        self.stack.setCurrentIndex(idx)
        for sid, btn in self._buttons.items():
            btn.setChecked(sid == section_id)

    # ------------------------------------------------------------------
    def _build_providers_section(self) -> QWidget:
        """Wraps the legacy SettingsDialog inside a scrollable card."""
        wrap = QScrollArea()
        wrap.setObjectName("studioScroll")
        wrap.setWidgetResizable(True)
        wrap.setStyleSheet(
            "QScrollArea#studioScroll { background:transparent; "
            "border:none; }"
        )
        try:
            from settings_dialog import SettingsDialog
            dlg = SettingsDialog(self.router, parent=None)
            dlg.setWindowFlags(Qt.WindowType.Widget)
            dlg.setSizePolicy(QSizePolicy.Policy.Preferred,
                              QSizePolicy.Policy.MinimumExpanding)
            wrap.setWidget(dlg)
        except Exception as ex:
            err = QLabel(f"Settings unavailable: {type(ex).__name__}: {ex}")
            err.setWordWrap(True)
            err.setStyleSheet(
                f"color:{T['warn']}; padding:{SPACE['md']}px;"
            )
            wrap.setWidget(err)
        return wrap

    # ------------------------------------------------------------------
    def _build_ai_behaviour_section(self) -> QWidget:
        """Extended-thinking effort + per-tool permission table."""
        from PyQt6.QtWidgets import (
            QButtonGroup, QComboBox, QRadioButton, QScrollArea,
            QGridLayout,
        )
        import ai_behaviour as ab

        scroll = QScrollArea()
        scroll.setObjectName("studioScroll")
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea#studioScroll { background:transparent; "
            "border:none; }"
        )
        page = QWidget()
        page.setObjectName("studioPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(SPACE["md"], 0, SPACE["md"], 0)
        v.setSpacing(SPACE["md"])

        # ── Extended-thinking effort card ──────────────────────────
        card = QFrame()
        card.setObjectName("settingsCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(SPACE["md"], SPACE["md"],
                               SPACE["md"], SPACE["md"])
        cv.setSpacing(SPACE["xs"])
        cap = QLabel("EXTENDED THINKING")
        cap.setObjectName("studioMonoCap")
        cv.addWidget(cap)
        sub = QLabel(
            "Let the model reason before responding. Higher effort "
            "= deeper thinking + higher token cost + slower replies. "
            "Anthropic Sonnet/Opus, Gemini 2.5 Pro, and OpenAI "
            "o-series honour this. GPT-4o, Haiku, and Ollama ignore."
        )
        sub.setObjectName("settingsKvVal")
        sub.setWordWrap(True)
        cv.addWidget(sub)

        cv.addSpacing(SPACE["xs"])
        row = QHBoxLayout()
        row.setSpacing(SPACE["xs"])
        self._thinking_group = QButtonGroup(self)
        current = ab.get_thinking_effort()
        for level, label in (
            ("off", "Off"),
            ("low", "Low · 1K tokens"),
            ("medium", "Medium · 4K"),
            ("high", "High · 16K"),
        ):
            btn = QRadioButton(label)
            btn.setObjectName("settingsKvVal")
            btn.setChecked(level == current)
            btn.toggled.connect(
                lambda checked, lvl=level:
                    ab.set_thinking_effort(lvl) if checked else None
            )
            self._thinking_group.addButton(btn)
            row.addWidget(btn)
        row.addStretch(1)
        row_w = QWidget(); row_w.setLayout(row)
        cv.addWidget(row_w)
        v.addWidget(card)

        # ── Per-tool permission table ──────────────────────────────
        card2 = QFrame()
        card2.setObjectName("settingsCard")
        cv2 = QVBoxLayout(card2)
        cv2.setContentsMargins(SPACE["md"], SPACE["md"],
                                SPACE["md"], SPACE["md"])
        cv2.setSpacing(SPACE["xs"])
        cap2 = QLabel("TOOL PERMISSIONS")
        cap2.setObjectName("studioMonoCap")
        cv2.addWidget(cap2)
        sub2 = QLabel(
            "Per-tool policy. 'Allow' fires immediately. 'Ask' "
            "prompts you in chat before the model can use it. "
            "'Deny' blocks it outright. Defaults are sensible: "
            "read-only tools allow, mutate/execute tools ask."
        )
        sub2.setObjectName("settingsKvVal")
        sub2.setWordWrap(True)
        cv2.addWidget(sub2)
        cv2.addSpacing(SPACE["xs"])

        # Build rows for every registered tool.
        try:
            from tool_engine import TOOLS
            grid = QGridLayout()
            grid.setHorizontalSpacing(SPACE["md"])
            grid.setVerticalSpacing(SPACE["xs"])
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 0)
            # Header row.
            h1 = QLabel("TOOL"); h1.setObjectName("studioMonoCap")
            h2 = QLabel("POLICY"); h2.setObjectName("studioMonoCap")
            grid.addWidget(h1, 0, 0)
            grid.addWidget(h2, 0, 1)
            self._tool_combos: dict = {}
            for i, t in enumerate(sorted(TOOLS, key=lambda x: x["name"]),
                                  start=1):
                name = t["name"]
                lbl = QLabel(name)
                lbl.setObjectName("settingsKvVal")
                grid.addWidget(lbl, i, 0)
                combo = QComboBox()
                combo.setObjectName("settingsCombo")
                combo.addItems(["allow", "ask", "deny"])
                combo.setCurrentText(ab.get_tool_policy(name))
                combo.currentTextChanged.connect(
                    lambda val, n=name: ab.set_tool_policy(n, val)
                )
                grid.addWidget(combo, i, 1)
                self._tool_combos[name] = combo
            grid_w = QWidget(); grid_w.setLayout(grid)
            cv2.addWidget(grid_w)
        except Exception as ex:
            err = QLabel(f"Tool list unavailable: {type(ex).__name__}")
            err.setObjectName("settingsKvVal")
            cv2.addWidget(err)
        v.addWidget(card2)
        v.addStretch(1)

        scroll.setWidget(page)
        return scroll

    # ------------------------------------------------------------------
    def _build_about_section(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studioPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(SPACE["md"], 0, SPACE["md"], 0)
        v.setSpacing(SPACE["md"])

        card = self._kv_card("App", [
            ("Name", "ArchHub"),
            ("Version", _read_version() or "0.40 (dev)"),
            ("Build", _read_git_sha() or "—"),
            ("Python", f"{sys.version.split()[0]}"),
            ("Platform", f"{platform.system()} {platform.release()}"),
        ])
        v.addWidget(card)

        card2 = self._kv_card("Links", [], buttons=[
            ("Open changelog", lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/archhub/archhub/blob/main/CHANGELOG.md"))),
            ("File a bug", lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/archhub/archhub/issues/new"))),
            ("Open docs", lambda: QDesktopServices.openUrl(
                QUrl("https://archhub.app/docs"))),
        ])
        v.addWidget(card2)
        v.addStretch(1)
        return page

    # ------------------------------------------------------------------
    def _build_diagnostics_section(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studioPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(SPACE["md"], 0, SPACE["md"], 0)
        v.setSpacing(SPACE["md"])

        # Connector health snapshot.
        rows: list[tuple[str, str]] = []
        try:
            from connector_health import instance as _hi
            health = _hi()
            for fam in ("revit", "acad", "max", "blender", "outlook"):
                try:
                    state = health.state(fam)
                except Exception:
                    state = "unknown"
                rows.append((fam.title(), state))
        except Exception as ex:
            rows.append(("Health probe", f"unavailable ({type(ex).__name__})"))
        v.addWidget(self._kv_card("Connector health", rows))

        # File system locations.
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
        sessions_dir = local / "sessions"
        log_path = local / "logs" / "archhub.log"
        v.addWidget(self._kv_card("Filesystem", [
            ("Data dir", str(local)),
            ("Sessions dir", str(sessions_dir)),
            ("Log file", str(log_path)),
        ], buttons=[
            ("Open data folder", lambda p=local: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(p)))),
            ("Open log file", lambda p=log_path: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(p)))
                if p.exists() else None),
        ]))
        v.addStretch(1)
        return page

    # ------------------------------------------------------------------
    def _kv_card(self, title: str, rows: list[tuple[str, str]],
                  buttons: list[tuple[str, callable]] | None = None
                  ) -> QFrame:
        card = QFrame()
        card.setObjectName("settingsCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(SPACE["md"], SPACE["md"],
                               SPACE["md"], SPACE["md"])
        cv.setSpacing(SPACE["xs"])
        cap = QLabel(title.upper())
        cap.setObjectName("studioMonoCap")
        cv.addWidget(cap)
        for k, val in rows:
            line = QHBoxLayout()
            line.setSpacing(SPACE["sm"])
            kl = QLabel(k)
            kl.setObjectName("settingsKvKey")
            kl.setMinimumWidth(120)
            vl = QLabel(str(val))
            vl.setObjectName("settingsKvVal")
            vl.setWordWrap(True)
            line.addWidget(kl)
            line.addWidget(vl, 1)
            row_w = QWidget(); row_w.setLayout(line)
            cv.addWidget(row_w)
        if buttons:
            cv.addSpacing(SPACE["xs"])
            br = QHBoxLayout()
            br.setSpacing(SPACE["xs"])
            for label, fn in buttons:
                b = QPushButton(label)
                b.setObjectName("studioChip")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(fn)
                br.addWidget(b)
            br.addStretch(1)
            row_w = QWidget(); row_w.setLayout(br)
            cv.addWidget(row_w)
        return card


# ---------------------------------------------------------------------------
def _read_version() -> str | None:
    try:
        p = Path(__file__).resolve().parent.parent / "VERSION"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return None


def _read_git_sha() -> str | None:
    try:
        repo = Path(__file__).resolve().parent.parent
        head = (repo / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            ref_path = repo / ".git" / ref
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:8]
        return head[:8]
    except Exception:
        return None


# ---------------------------------------------------------------------------
def _qss() -> str:
    return (
        f"QFrame#settingsNav {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; }}"
        f"QPushButton#settingsNavBtn {{ "
        f"  text-align:left; padding:{SPACE['xs']+2}px {SPACE['sm']+2}px; "
        f"  background:transparent; color:{T['inkSoft']}; "
        f"  border:none; border-radius:{RADIUS['sm']}px; "
        f"  font-family:{TYPE['fontSans']}; font-size:12.5px; }}"
        f"QPushButton#settingsNavBtn:hover {{ "
        f"  background:{T['bgHover']}; color:{T['ink']}; }}"
        f"QPushButton#settingsNavBtn:checked {{ "
        f"  background:{T['accent']}; color:white; "
        f"  font-weight:500; }}"
        f"QFrame#settingsCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; }}"
        f"QLabel#settingsKvKey {{ color:{T['inkMuted']}; "
        f"  font-family:{TYPE['fontMono']}; font-size:11px; "
        f"  letter-spacing:0.04em; }}"
        f"QLabel#settingsKvVal {{ color:{T['ink']}; "
        f"  font-family:{TYPE['fontSans']}; font-size:12.5px; }}"
        f"QStackedWidget#settingsStack {{ background:transparent; }}"
    )
