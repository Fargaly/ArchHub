"""WorkspaceShell — graph-first ArchHub (ADR-003 pivot, v1.4.0-alpha).

Replaces the page-based StudioShell. Every "thing" — chat, host, document,
skill, tool — is a typed node on one canvas. The shell here is the chrome:

    ┌──────┬────────┬──────────────────────────────┬────────┐
    │ icon │ panel  │  workspace (canvas)          │ insp.  │
    │ rail │ (rail  │  ┌─[tabs: graph1 graph2 +]─┐ │ (focus │
    │ 44px │ pkg)   │  │                         │ │ node)  │
    │      │ 220px  │  │   QGraphicsView with    │ │ 300px  │
    │      │        │  │   the active graph      │ │        │
    │      │        │  └─────────────────────────┘ │        │
    │      │        │   ╭ composer ─ /slash ──╮    │        │
    │      │        │   ╰──────────────────────╯    │        │
    ├──────┴────────┴──────────────────────────────┴────────┤
    │ status rule  ●  N/M hosts  ·  spend  ·  v…             │
    └────────────────────────────────────────────────────────┘

Per the studio-lm.jsx design bundle:
  • Icon rail: Brand · Chats · Nodes (default) · Skills · Search · Settings
  • Content panel switches with the active rail icon
  • Workspace tabs above the canvas = open graphs
  • Settings is a modal, not a page
  • Hosts live in Settings → Hosts (moved out of rail)

This shell is the new default in app/main.py. StudioShell is kept on
disk for the fallback launch path until WorkspaceShell is proven in
the wild (cf. ADR-003 §"Reversal plan").
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QPushButton, QScrollArea, QStackedWidget, QTabBar, QToolButton,
    QVBoxLayout, QWidget,
)

from design_tokens import (
    SPACE, TYPE, RADIUS,
    current as current_palette,
    load_theme_pref as _load_theme_pref,
)


# Live palette proxy — same pattern as studio_shell.
try:
    _load_theme_pref()
except Exception:
    pass

class _LivePalette:
    def __getitem__(self, k):
        return current_palette()[k]
    def get(self, k, default=None):
        return current_palette().get(k, default)


T = _LivePalette()


# ── Icon-rail panels (LM Studio pattern) ─────────────────────────────
RAIL_PANELS = [
    # (id, label, shortcut)
    ("chats",   "Chats",   "1"),
    ("nodes",   "Nodes",   "2"),
    ("skills",  "Skills",  "3"),
    ("search",  "Search",  "4"),
]


class WorkspaceShell(QMainWindow):
    """The new shell. Single canvas, four rail panels, gear-opened Settings.

    Constructor compatibility note: matches StudioShell so main.py can
    swap one for the other without touching the launch path.
    """

    nav_changed = pyqtSignal(str)

    def __init__(self, *, chat_widget: QWidget,
                  router=None, manager=None, tools=None,
                  parent=None):
        super().__init__(parent)
        self.setWindowTitle("ArchHub")
        self.setObjectName("workspaceShell")
        self.resize(1440, 900)
        # ArchHub icon on the title bar.
        try:
            from pathlib import Path as _P
            ico = _P(__file__).resolve().parent / "assets" / "archhub.ico"
            if ico.exists():
                self.setWindowIcon(QIcon(str(ico)))
        except Exception:
            pass

        self.router = router
        self.manager = manager
        self.tools = tools
        self.chat_widget = chat_widget       # kept for compatibility; not rendered as a page
        self._active_rail = "nodes"          # default panel: node library
        self._open_graphs: list[dict] = []   # list of {id, name, graph_dict}
        self._active_graph_idx = 0

        # ── Outer container ─────────────────────────────────────
        outer_w = QWidget()
        outer = QVBoxLayout(outer_w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)

        # ── Icon rail (44px) ───────────────────────────────────
        body_row.addWidget(self._build_icon_rail())
        # ── Content panel (220px, switches with active rail icon)
        self.rail_panel = self._build_rail_panel()
        body_row.addWidget(self.rail_panel)
        # ── Workspace (center) ─────────────────────────────────
        body_row.addWidget(self._build_workspace(), 1)
        # ── Inspector (right, 300px) ───────────────────────────
        self.inspector = self._build_inspector()
        body_row.addWidget(self.inspector)

        outer.addLayout(body_row, 1)
        outer.addWidget(self._build_status_rule())
        self.setCentralWidget(outer_w)

        # Shortcuts: ⌘1-⌘4 = switch rail panel
        for pid, _label, key in RAIL_PANELS:
            sc = QShortcut(QKeySequence(f"Ctrl+{key}"), self)
            sc.activated.connect(lambda _id=pid: self._set_rail(_id))
        # ⌘, opens Settings modal
        sc_set = QShortcut(QKeySequence("Ctrl+,"), self)
        sc_set.activated.connect(self._open_settings_modal)

        # Apply inline style overrides.
        self.setStyleSheet(self._inline_qss())

        # Boot with one empty graph.
        self._open_new_graph()

    # ────────────────────────────────────────────────────────────
    # Icon rail
    # ────────────────────────────────────────────────────────────
    def _build_icon_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("wsRail")
        rail.setFixedWidth(44)
        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 12, 0, 12)
        v.setSpacing(6)

        # Brand mark — terracotta A monogram, click-through to Home (=empty graph).
        brand = QToolButton()
        brand.setText("A")
        brand.setObjectName("wsBrand")
        brand.setFixedSize(28, 28)
        brand.setCursor(Qt.CursorShape.PointingHandCursor)
        brand.clicked.connect(self._open_new_graph)
        brand_wrap = QHBoxLayout()
        brand_wrap.setContentsMargins(0, 0, 0, 0)
        brand_wrap.addStretch(1)
        brand_wrap.addWidget(brand)
        brand_wrap.addStretch(1)
        v.addLayout(brand_wrap)
        v.addSpacing(8)

        self._rail_btns: dict[str, QToolButton] = {}
        for pid, label, _key in RAIL_PANELS:
            btn = QToolButton()
            btn.setText(self._panel_glyph(pid))
            btn.setToolTip(f"{label}  ⌘{_key}")
            btn.setObjectName("wsRailBtn")
            btn.setFixedSize(28, 28)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, _id=pid: self._set_rail(_id))
            wrap = QHBoxLayout()
            wrap.setContentsMargins(0, 0, 0, 0)
            wrap.addStretch(1)
            wrap.addWidget(btn)
            wrap.addStretch(1)
            v.addLayout(wrap)
            self._rail_btns[pid] = btn

        v.addStretch(1)

        # Gear at bottom — opens Settings modal.
        gear = QToolButton()
        gear.setText("⚙")
        gear.setObjectName("wsRailBtn")
        gear.setToolTip("Settings  ⌘,")
        gear.setFixedSize(28, 28)
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.clicked.connect(self._open_settings_modal)
        gw = QHBoxLayout()
        gw.setContentsMargins(0, 0, 0, 0)
        gw.addStretch(1)
        gw.addWidget(gear)
        gw.addStretch(1)
        v.addLayout(gw)

        # Reflect default-active panel.
        self._reflect_active_rail()
        return rail

    def _panel_glyph(self, pid: str) -> str:
        return {"chats": "✦", "nodes": "◇", "skills": "★", "search": "⌕"}.get(pid, "·")

    def _reflect_active_rail(self) -> None:
        for pid, btn in self._rail_btns.items():
            btn.setChecked(pid == self._active_rail)

    def _set_rail(self, pid: str) -> None:
        if pid not in {p for p, _, _ in RAIL_PANELS}:
            return
        self._active_rail = pid
        self._reflect_active_rail()
        self._rail_panel_stack.setCurrentWidget(self._panel_widgets[pid])
        self.nav_changed.emit(pid)

    # ────────────────────────────────────────────────────────────
    # Rail content panel — 220px column that switches per active rail icon
    # ────────────────────────────────────────────────────────────
    def _build_rail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("wsRailPanel")
        panel.setFixedWidth(220)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._rail_panel_stack = QStackedWidget()
        self._panel_widgets: dict[str, QWidget] = {
            "chats":  self._build_chats_panel(),
            "nodes":  self._build_nodes_panel(),
            "skills": self._build_skills_panel(),
            "search": self._build_search_panel(),
        }
        for w in self._panel_widgets.values():
            self._rail_panel_stack.addWidget(w)
        self._rail_panel_stack.setCurrentWidget(self._panel_widgets["nodes"])

        v.addWidget(self._rail_panel_stack, 1)
        return panel

    def _build_chats_panel(self) -> QWidget:
        """Open graphs / saved sessions. v1: list of open graphs."""
        w = QWidget()
        w.setObjectName("wsRailPanel")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(8)

        v.addWidget(_caption_label("CHATS"))
        self._chats_list = QListWidget()
        self._chats_list.setObjectName("wsList")
        v.addWidget(self._chats_list, 1)

        new_btn = QPushButton("+ New chat")
        new_btn.setObjectName("wsRailButton")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self._open_new_graph)
        v.addWidget(new_btn)
        return w

    def _build_nodes_panel(self) -> QWidget:
        """Node library — categorized, search, drag-or-double-click to add."""
        w = QWidget()
        w.setObjectName("wsRailPanel")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(8)

        v.addWidget(_caption_label("NODES"))
        search = QLineEdit()
        search.setObjectName("wsSearch")
        search.setPlaceholderText("Filter library…")
        v.addWidget(search)

        # Scroll wrap for the categorized list.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 4, 0, 0)
        bv.setSpacing(2)

        # Pull every registered node spec from the workflows registry,
        # group by category, render one row per type.
        try:
            from workflows.registry import _REGISTRY
            by_cat: dict[str, list] = {}
            for tname, (spec, _exec) in sorted(_REGISTRY.items()):
                by_cat.setdefault(spec.category or "misc", []).append(spec)
            for cat, specs in sorted(by_cat.items()):
                cap = QLabel(cat.upper())
                cap.setObjectName("studioMonoCap")
                bv.addSpacing(8)
                bv.addWidget(cap)
                for spec in specs:
                    row = self._library_row(spec)
                    bv.addWidget(row)
        except Exception:
            bv.addWidget(QLabel("(node registry unavailable)"))

        bv.addStretch(1)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        # Filter wire — hide rows that don't match.
        def _apply_filter():
            q = search.text().strip().lower()
            for i in range(bv.count()):
                item = bv.itemAt(i).widget()
                if isinstance(item, _LibraryRow):
                    item.setVisible(q == "" or q in item.title.lower()
                                     or q in item.spec_type.lower())
        search.textChanged.connect(_apply_filter)
        return w

    def _library_row(self, spec) -> "_LibraryRow":
        return _LibraryRow(
            title=spec.display_name or spec.type,
            spec_type=spec.type,
            description=spec.description,
            icon=spec.icon,
            on_add=lambda: self._add_node_to_active_graph(spec.type),
        )

    def _build_skills_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("wsRailPanel")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(8)
        v.addWidget(_caption_label("SKILLS"))
        # MVP: empty state; Phase 5 wires this to skills.library
        empty = QLabel("Saved skills appear here.\n"
                        "Collapse any subgraph and click ‘Save as Skill’.")
        empty.setWordWrap(True)
        empty.setObjectName("studioMonoMuted")
        v.addWidget(empty)
        v.addStretch(1)
        return w

    def _build_search_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("wsRailPanel")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(8)
        v.addWidget(_caption_label("SEARCH"))
        search = QLineEdit()
        search.setObjectName("wsSearch")
        search.setPlaceholderText("Find a chat, node, skill, memory…")
        v.addWidget(search)
        v.addStretch(1)
        return w

    # ────────────────────────────────────────────────────────────
    # Workspace (center): tabs + canvas + composer
    # ────────────────────────────────────────────────────────────
    def _build_workspace(self) -> QWidget:
        w = QWidget()
        w.setObjectName("wsWorkspace")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── Tab strip (open graphs) ─────────────────────────────
        self.tabs = QTabBar()
        self.tabs.setObjectName("wsTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabCloseRequested.connect(self._on_tab_closed)
        v.addWidget(self.tabs)

        # ── Canvas ──────────────────────────────────────────────
        # Reuse the existing WorkflowCanvas — it already supports
        # right-click menu, undo/redo, drag of nodes, etc. Phase 5
        # adds the slash menu + library drag-drop on top.
        try:
            from workflow_canvas import WorkflowCanvas
            self.canvas = WorkflowCanvas(
                router=self.router, tool_engine=self.tools,
                manager=self.manager, parent=None,
            )
            v.addWidget(self.canvas, 1)
        except Exception as ex:
            err = QLabel(f"Canvas unavailable: {ex}")
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err.setObjectName("studioMonoMuted")
            v.addWidget(err, 1)
            self.canvas = None

        # ── Composer at the bottom-center ──────────────────────
        v.addWidget(self._build_composer())
        return w

    def _build_composer(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("wsComposer")
        bar.setFixedHeight(64)
        h = QHBoxLayout(bar)
        h.setContentsMargins(40, 12, 40, 12)
        h.setSpacing(8)
        self.composer_input = QLineEdit()
        self.composer_input.setObjectName("wsComposerInput")
        self.composer_input.setPlaceholderText(
            "Type / for a node · type a question to start chatting…")
        self.composer_input.returnPressed.connect(self._on_composer_send)
        h.addWidget(self.composer_input, 1)
        send_btn = QPushButton("Send ↗")
        send_btn.setObjectName("wsSendBtn")
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.clicked.connect(self._on_composer_send)
        h.addWidget(send_btn)
        return bar

    # ────────────────────────────────────────────────────────────
    # Inspector (right rail) — empty until a node is focused.
    # ────────────────────────────────────────────────────────────
    def _build_inspector(self) -> QFrame:
        f = QFrame()
        f.setObjectName("wsInspector")
        f.setFixedWidth(300)
        v = QVBoxLayout(f)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(10)
        v.addWidget(_caption_label("INSPECTOR"))
        empty = QLabel("Select a node to inspect.")
        empty.setObjectName("studioMonoMuted")
        empty.setWordWrap(True)
        v.addWidget(empty)
        v.addStretch(1)
        return f

    # ────────────────────────────────────────────────────────────
    # Status rule
    # ────────────────────────────────────────────────────────────
    def _build_status_rule(self) -> QFrame:
        f = QFrame()
        f.setObjectName("studioStatusRule")
        f.setFixedHeight(26)
        h = QHBoxLayout(f)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(18)
        self._sr_hosts = QLabel("● 0/0 hosts")
        self._sr_hosts.setObjectName("studioStatusItem")
        h.addWidget(self._sr_hosts)
        self._sr_graphs = QLabel("● 0 graphs")
        self._sr_graphs.setObjectName("studioStatusItem")
        h.addWidget(self._sr_graphs)
        h.addStretch(1)
        ver = QLabel("v1.4.0-alpha")
        ver.setObjectName("studioMonoMuted")
        h.addWidget(ver)
        return f

    # ────────────────────────────────────────────────────────────
    # Tabs / graph life-cycle
    # ────────────────────────────────────────────────────────────
    def _open_new_graph(self) -> None:
        from session_graph_migrator import wrap_legacy_as_graph
        from session import Session
        s = Session()
        g = wrap_legacy_as_graph(s, [], name=f"Graph {len(self._open_graphs)+1}")
        self._open_graphs.append({"id": g["id"], "name": g["name"],
                                    "graph": g, "session": s})
        idx = self.tabs.addTab(g["name"])
        self.tabs.setCurrentIndex(idx)
        self._sr_graphs.setText(f"● {len(self._open_graphs)} graphs")

    def _on_tab_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._open_graphs):
            self._active_graph_idx = idx
            self._refresh_chats_list()

    def _on_tab_closed(self, idx: int) -> None:
        if 0 <= idx < len(self._open_graphs):
            self._open_graphs.pop(idx)
            self.tabs.removeTab(idx)
            self._sr_graphs.setText(f"● {len(self._open_graphs)} graphs")
            self._refresh_chats_list()
            if not self._open_graphs:
                self._open_new_graph()

    def _refresh_chats_list(self) -> None:
        if not hasattr(self, "_chats_list"):
            return
        self._chats_list.clear()
        for entry in self._open_graphs:
            item = QListWidgetItem(entry["name"])
            self._chats_list.addItem(item)

    # ────────────────────────────────────────────────────────────
    # Composer + node insertion
    # ────────────────────────────────────────────────────────────
    def _on_composer_send(self) -> None:
        text = self.composer_input.text().strip()
        if not text:
            return
        # Slash-menu opt-in: `/<type>` inserts a node of that type into
        # the active graph. Phase 5 makes this a richer overlay.
        if text.startswith("/"):
            node_type = text[1:].strip()
            self._add_node_to_active_graph(node_type)
            self.composer_input.clear()
            return
        # Otherwise the text is a chat prompt — append to the active
        # graph's conversation node body. Phase 4 wires the executor
        # to llm_router.complete; for now we just persist the turn.
        if self._open_graphs:
            g = self._open_graphs[self._active_graph_idx]["graph"]
            for n in g["nodes"]:
                if (n.get("type") or "") == "conversation.chat":
                    body = n.setdefault("config", {}).setdefault("body", {})
                    msgs = body.setdefault("messages", [])
                    msgs.append({"role": "user", "content": text})
                    break
        self.composer_input.clear()

    def _add_node_to_active_graph(self, node_type: str) -> None:
        """Append a node of the given type to the active graph dict."""
        from workflows.registry import get as _registry_get
        spec_tup = _registry_get(node_type)
        if not spec_tup:
            return
        spec, _exec = spec_tup
        if not self._open_graphs:
            self._open_new_graph()
        import uuid
        g = self._open_graphs[self._active_graph_idx]["graph"]
        node = {
            "id":       f"n_{uuid.uuid4().hex[:10]}",
            "type":     spec.type,
            "label":    spec.display_name,
            "config":   {},
            "inputs":   [p.to_dict() for p in spec.inputs],
            "outputs":  [p.to_dict() for p in spec.outputs],
            "position": {"x": 40.0 * (len(g.get("nodes", []))),
                          "y": 40.0},
        }
        g.setdefault("nodes", []).append(node)

    # ────────────────────────────────────────────────────────────
    # Tray + summon contract (matches StudioShell + ChatWindow)
    # ────────────────────────────────────────────────────────────
    def show_centered(self) -> None:
        """Restore + centre on the primary screen.

        Matches the contract of StudioShell.show_centered + ChatWindow.
        show_centered so the tray + single-instance summoner can keep
        calling `surface.show_centered()` regardless of which shell is
        active.
        """
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

    # ────────────────────────────────────────────────────────────
    # Settings modal
    # ────────────────────────────────────────────────────────────
    def _open_settings_modal(self) -> None:
        try:
            from settings_dialog import SettingsDialog
            dlg = SettingsDialog(parent=self, router=self.router,
                                   manager=self.manager, tools=self.tools)
            dlg.exec()
        except Exception:
            # Best-effort: if SettingsDialog needs a different signature
            # we fall back to opening a notice rather than crashing.
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Settings",
                "Open the legacy settings shell — Settings dialog "
                "couldn't open in modal mode in this build.")

    # ────────────────────────────────────────────────────────────
    # Inline QSS
    # ────────────────────────────────────────────────────────────
    def _inline_qss(self) -> str:
        return (
            f"QMainWindow#workspaceShell {{ background:{T['paper']}; }} "
            f"QFrame#wsRail {{ background:{T['paperSoft']}; "
            f"  border-right:1px solid {T['line']}; }} "
            f"QFrame#wsRailPanel {{ background:{T['paperSoft']}; "
            f"  border-right:1px solid {T['line']}; }} "
            f"QToolButton#wsBrand {{ "
            f"  background:{T['accent']}; color:#fff; "
            f"  border:none; border-radius:14px; "
            f"  font-family:{TYPE['fontMono']}; font-size:14px; "
            f"  font-weight:500; }} "
            f"QToolButton#wsRailBtn {{ "
            f"  background:transparent; color:{T['inkSoft']}; "
            f"  border:none; border-radius:6px; font-size:14px; }} "
            f"QToolButton#wsRailBtn:hover {{ background:{T['bgHover']}; }} "
            f"QToolButton#wsRailBtn:checked {{ "
            f"  background:{T['bgRaised']}; color:{T['accent']}; }} "
            f"QFrame#wsWorkspace {{ background:{T['paper']}; }} "
            f"QFrame#wsInspector {{ background:{T['paperSoft']}; "
            f"  border-left:1px solid {T['line']}; }} "
            f"QFrame#wsComposer {{ background:{T['paperSoft']}; "
            f"  border-top:1px solid {T['line']}; }} "
            f"QLineEdit#wsComposerInput, QLineEdit#wsSearch {{ "
            f"  background:{T['bgRaised']}; color:{T['ink']}; "
            f"  border:1px solid {T['line']}; "
            f"  border-radius:8px; padding:8px 12px; "
            f"  font-family:{TYPE['fontSans']}; font-size:14px; }} "
            f"QPushButton#wsSendBtn, QPushButton#wsRailButton {{ "
            f"  background:{T['accent']}; color:#fff; border:none; "
            f"  border-radius:8px; padding:8px 14px; "
            f"  font-family:{TYPE['fontSans']}; font-size:13px; "
            f"  font-weight:500; }} "
            f"QPushButton#wsSendBtn:hover, "
            f"QPushButton#wsRailButton:hover {{ background:{T['accentHi']}; }} "
            f"QTabBar#wsTabs::tab {{ "
            f"  background:{T['paperSoft']}; color:{T['inkSoft']}; "
            f"  padding:6px 12px; border:none; "
            f"  border-right:1px solid {T['line']}; "
            f"  font-family:{TYPE['fontMono']}; font-size:11px; }} "
            f"QTabBar#wsTabs::tab:selected {{ "
            f"  background:{T['paper']}; color:{T['ink']}; "
            f"  border-bottom:2px solid {T['accent']}; }} "
            f"QLabel#studioMonoCap {{ "
            f"  font-family:{TYPE['fontMono']}; "
            f"  letter-spacing:0.16em; color:{T['inkMuted']}; "
            f"  font-size:10px; font-weight:500; }} "
            f"QLabel#studioMonoMuted {{ "
            f"  font-family:{TYPE['fontMono']}; color:{T['inkMuted']}; "
            f"  font-size:11px; }} "
            f"QFrame#studioStatusRule {{ background:{T['paperSoft']}; "
            f"  border-top:1px solid {T['line']}; }} "
            f"QLabel#studioStatusItem {{ "
            f"  font-family:{TYPE['fontMono']}; color:{T['inkSoft']}; "
            f"  font-size:11px; }} "
            f"QListWidget#wsList {{ "
            f"  background:transparent; border:none; "
            f"  font-family:{TYPE['fontSans']}; font-size:12px; "
            f"  color:{T['ink']}; }} "
            f"QListWidget#wsList::item:hover {{ "
            f"  background:{T['bgHover']}; }} "
        )


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────
def _caption_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("studioMonoCap")
    return lbl


class _LibraryRow(QFrame):
    """One row in the Nodes library panel. Click = add node to active graph.

    Phase 5 will wire HTML5-style drag-drop onto the canvas; today's
    MVP is single-click-to-insert + double-click also-insert.
    """

    def __init__(self, *, title: str, spec_type: str, description: str,
                  icon: str, on_add: Callable[[], None]):
        super().__init__()
        self.title = title
        self.spec_type = spec_type
        self._on_add = on_add
        self.setObjectName("wsLibraryRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(8)
        ic = QLabel(icon or "·")
        ic.setObjectName("studioMonoMuted")
        ic.setFixedWidth(14)
        h.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(title)
        t.setStyleSheet(f"font-family:{TYPE['fontSans']}; "
                          f"font-size:12px; color:{T['ink']};")
        s = QLabel(spec_type)
        s.setObjectName("studioMonoMuted")
        col.addWidget(t)
        col.addWidget(s)
        col_w = QWidget(); col_w.setLayout(col)
        h.addWidget(col_w, 1)
        self.setStyleSheet(
            f"QFrame#wsLibraryRow {{ background:transparent; "
            f"  border-radius:6px; }} "
            f"QFrame#wsLibraryRow:hover {{ background:{T['bgHover']}; }}"
        )

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            try:
                self._on_add()
            except Exception:
                pass
        super().mousePressEvent(ev)
