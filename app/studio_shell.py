"""Studio shell — 3-pane chrome wired to live ArchHub data.

Layout (matches studio.jsx from the Claude Design handoff):

    ┌──────────┬─────────────────────────┬──────────┐
    │  rail    │  main view              │ inspector│
    │  232px   │  flex                   │  304px   │
    │          │                         │          │
    │  brand   │  (Home / Chat / Skills/ │ live ctx │
    │  ⌘K box  │   Flows / Market /      │ (model · │
    │  nav     │   Telemetry / Settings) │  hosts · │
    │  HOSTS   │                         │  files…) │
    │  THREADS │                         │          │
    │  user    │                         │          │
    ├──────────┴─────────────────────────┴──────────┤
    │  status rule  (26px · live mono telemetry)    │
    └───────────────────────────────────────────────┘

Live wiring:
  HOSTS      <- ConnectorManager.entries + connector_health.instance().state(family)
                Toggle row calls manager.activate / deactivate.
                Status dot color from health: live/loaded_dead/host_offline/unknown.
  THREADS    <- session_io.list_sessions() (top 5 newest). Click loads via
                chat_widget._open_sessions.
  user card  <- secrets_store load_setting('user_email') + cloud_sync.is_signed_in
                fall back to OS username.
  inspector  <- active host (manager), model picker (chat_widget if exposed),
                last latency (router last_response_ms if exposed), session
                step count.
  status     <- connector_health.snapshot() live count + healing count, model,
                latency, spend (telemetry total_cost_usd if exposed).
  Home       <- same wiring as the rail/status surfaces.
  Skills     <- embeds existing SkillsPanel as a widget.
  Workflows  <- embeds existing WorkflowsPanel as a widget.
  Settings   <- embeds existing SettingsDialog content as a widget.

Refresh: a single QTimer ticks every 2s and rebuilds the live surfaces.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QSize, QPointF, QPropertyAnimation, QEasingCurve,
    QSequentialAnimationGroup, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QKeySequence, QPainter, QPainterPath, QPen,
    QPixmap, QShortcut,
)
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)


# Studio palette + brand from app/design_tokens.py.
# Use `current()` at refresh time so light↔dark theme swaps propagate.
from design_tokens import (
    BRAND, COLOR, COLOR_DARK, SPACE, RADIUS, TYPE,
    active_theme, current as current_palette, focus_ring_qss,
    load_theme_pref as _load_theme_pref, set_theme,
)
# Use a live palette proxy so any code that reads T['key'] always gets
# the active theme — avoids the bug where modules cached COLOR at
# import time and painted dark-mode UIs in light-theme ink.
class _LivePalette:
    def __getitem__(self, k):
        return current_palette()[k]
    def get(self, k, default=None):
        return current_palette().get(k, default)
# Read persisted theme pref before first palette access so the first
# QSS build uses dark when that's the user's preference.
try: _load_theme_pref()
except Exception: pass
T = _LivePalette()

NAV_ITEMS = [
    ("home",      "Home",        "1"),
    ("chat",      "Chat",        "2"),
    ("skills",    "Skills",      "3"),
    ("flows",     "Workflows",   "4"),
    ("market",    "Marketplace", "5"),
    ("telemetry", "Telemetry",   "6"),
    ("pricing",   "Pricing",     "7"),
    ("settings",  "Settings",    ","),
]


# Map ConnectorEntry.family → port (mirrors connector_health.LISTENER_URL).
FAMILY_PORT = {
    "revit":   ":48884",
    "autocad": ":48885",
    "max":     ":48886",
    "blender": ":9876",
}


class StudioShell(QMainWindow):
    """3-pane Studio shell. Wraps a ChatWindow for the 'chat' page."""

    nav_changed = pyqtSignal(str)

    def __init__(self, *, chat_widget: QWidget,
                 router=None, manager=None, tools=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("ArchHub")
        self.setObjectName("studioShell")
        self.resize(1280, 820)
        # Force the ArchHub icon onto the title bar / taskbar even when
        # QApplication.windowIcon hasn't been set yet (e.g. shell
        # constructed in a smoke test).
        try:
            from pathlib import Path as _P
            from PyQt6.QtGui import QIcon as _QIcon
            ico = _P(__file__).resolve().parent / "assets" / "archhub.ico"
            if ico.exists():
                self.setWindowIcon(_QIcon(str(ico)))
        except Exception:
            pass

        self.router = router
        self.manager = manager
        self.tools = tools
        self.chat_widget = chat_widget
        self._active_page = "home"
        # Per-family previous state — drives ConnectorBirth pulse on
        # state transitions (v0.32, brand principle 07: quiet motion).
        self._host_prev_state: dict[str, str] = {}
        # Per-family expanded sub-list state — driven by HOSTS-row click
        # so the architect can pick "Tower-A" out of three Revit
        # instances. Click on the row body toggles; rebuild keys off
        # this set so the sub-rows survive the 5-s refresh tick.
        self._hosts_expanded: set[str] = set()

        # Apply persisted theme preference before building any pages.
        try:
            from design_tokens import load_theme_pref
            load_theme_pref()
            global T
            T = current_palette()
        except Exception:
            pass

        central = QWidget()
        central.setObjectName("studioRoot")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        body.setObjectName("studioBody")
        outer.addWidget(body, 1)

        body_row = QHBoxLayout(body)
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)

        # ── Left rail ──────────────────────────────────────────────────
        self.rail = self._build_rail()
        body_row.addWidget(self.rail)

        # ── Centre stack ───────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setObjectName("studioStack")
        self.pages = {
            "home":      self._build_home(),
            "chat":      self._wrap_chat(chat_widget),
            "skills":    self._build_skills_page(),
            "flows":     self._build_workflows_page(),
            "market":    self._build_marketplace_page(),
            "telemetry": self._build_telemetry_page(),
            "pricing":   self._build_pricing_page(),
            "settings":  self._build_settings_page(),
            "addhost":   self._build_addhost_page(),
        }
        for k, w in self.pages.items():
            self.stack.addWidget(w)
        body_row.addWidget(self.stack, 1)

        # ── Right inspector ────────────────────────────────────────────
        self.inspector = self._build_inspector()
        body_row.addWidget(self.inspector)

        # ── Bottom status rule (26px) ──────────────────────────────────
        self.status_rule = self._build_status_rule()
        outer.addWidget(self.status_rule)

        # Default page
        self._set_page("home")

        # Apply Studio styles inline (in addition to theme.qss).
        self.setStyleSheet(_inline_qss())

        # Global shortcuts: 1..6 = nav, ⌘, = Settings.
        for nav_id, _, key in NAV_ITEMS:
            sc = QShortcut(QKeySequence(f"Ctrl+{key}"), self)
            sc.activated.connect(lambda _id=nav_id: self._set_page(_id))
        # ⌘K command palette overlay.
        self._palette_sc = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_sc.activated.connect(self._open_palette)

        # Live refresh — diff-driven. Tick is 5s (was 2s) and we only
        # rebuild the rail/threads/etc. when their *signature* changes
        # since the last tick. Status rule + inspector are cheap setText
        # calls so they always run. Page-specific refreshes (home,
        # telemetry) gate on whether their page is currently visible.
        # The previous 2s, full-rebuild loop was the source of the
        # "feels heavy / laggy" feedback.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self._refresh_live)
        self._refresh_timer.start()
        # Caches for diff comparisons + TTL'd disk reads.
        self._last_hosts_sig: tuple = ()
        self._last_threads_sig: tuple = ()
        self._sessions_cache: tuple[float, list] = (0.0, [])
        self._skills_cache: tuple[float, list] = (0.0, [])
        # First refresh immediately so we don't show stale fake values.
        QTimer.singleShot(50, self._refresh_live)
        # Startup banner — if the user has no API keys configured AND
        # no local Ollama models available, the chat will silently hang
        # the moment they hit Send. Surface the gap up front so they
        # know to add a key before typing.
        QTimer.singleShot(800, self._maybe_show_no_llm_banner)

    # ──────────────────────────────────────────────────────────────────
    # Rail
    # ──────────────────────────────────────────────────────────────────
    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("studioRail")
        rail.setFixedWidth(232)

        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Brand row — ArchMark (arch + node keystone) + 'Arch' + italic 'Hub'
        # + theme-toggle sun/moon button on the right (matches studio.jsx).
        brand_wrap = QWidget()
        brand_row = QHBoxLayout(brand_wrap)
        brand_row.setContentsMargins(14, 14, 14, 10)
        brand_row.setSpacing(10)
        self._brand_mark = ArchMark(size=30)
        brand_row.addWidget(self._brand_mark)
        brand_col_w = QWidget()
        brand_col = QVBoxLayout(brand_col_w)
        brand_col.setContentsMargins(0, 0, 0, 0)
        brand_col.setSpacing(0)
        self._brand_word = Wordmark(size=19)
        brand_col.addWidget(self._brand_word)
        self._brand_sub = QLabel("STUDIO · BOOTING")
        self._brand_sub.setObjectName("studioBrandSub")
        brand_col.addWidget(self._brand_sub)
        brand_row.addWidget(brand_col_w, 1)
        # Theme toggle — sun glyph in light, moon glyph in dark.
        self._theme_btn = QToolButton()
        self._theme_btn.setObjectName("studioThemeToggle")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.setFixedSize(24, 24)
        self._theme_btn.setText("☾" if active_theme() == "dark" else "☀")
        self._theme_btn.setToolTip("Switch theme (graphite, never black)")
        self._theme_btn.clicked.connect(self._toggle_theme)
        brand_row.addWidget(self._theme_btn)
        v.addWidget(brand_wrap)

        # ⌘K command box (placeholder — palette overlay deferred)
        ck_wrap = QWidget()
        ck_l = QVBoxLayout(ck_wrap)
        ck_l.setContentsMargins(12, 2, 12, 12)
        ck = QPushButton("Ask, search, run skill…  ⌘K")
        ck.setObjectName("studioCommandBox")
        ck.setCursor(Qt.CursorShape.PointingHandCursor)
        ck.clicked.connect(self._open_palette)
        ck_l.addWidget(ck)
        v.addWidget(ck_wrap)

        # Nav
        nav_wrap = QWidget()
        nav_l = QVBoxLayout(nav_wrap)
        nav_l.setContentsMargins(8, 0, 8, 0)
        nav_l.setSpacing(1)
        self._nav_buttons: dict[str, QPushButton] = {}
        for nav_id, label, key in NAV_ITEMS:
            btn = QPushButton(f"{label}     ⌘{key}")
            btn.setObjectName("studioNavItem")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_nav_style(False))
            btn.clicked.connect(lambda _=False, _id=nav_id: self._set_page(_id))
            self._nav_buttons[nav_id] = btn
            nav_l.addWidget(btn)
        v.addWidget(nav_wrap)

        # HOSTS section — content rebuilt by _refresh_hosts.
        hosts_header, self._hosts_count_lbl = _section_label_with_label("HOSTS · …")
        v.addWidget(hosts_header)
        self._hosts_container = QWidget()
        self._hosts_container.setLayout(QVBoxLayout())
        self._hosts_container.layout().setContentsMargins(8, 0, 8, 0)
        self._hosts_container.layout().setSpacing(1)
        v.addWidget(self._hosts_container)

        # "+ Add host..." inline row with AUTO-BUILD badge — the
        # primary affordance for connecting a new host (matches
        # studio.jsx HOSTS section).
        addhost_row = QFrame()
        addhost_row.setObjectName("studioAddHostRow")
        addhost_row.setCursor(Qt.CursorShape.PointingHandCursor)
        ahl = QHBoxLayout(addhost_row)
        ahl.setContentsMargins(9, 6, 9, 6)
        ahl.setSpacing(8)
        plus = QLabel("+")
        plus.setObjectName("studioAddHostPlus")
        plus.setFixedWidth(10)
        ahl.addWidget(plus)
        nm = QLabel("Add host…")
        nm.setObjectName("studioAddHostText")
        ahl.addWidget(nm, 1)
        badge = QLabel("AUTO-BUILD")
        badge.setObjectName("studioAddHostBadge")
        ahl.addWidget(badge)
        addhost_row.mousePressEvent = lambda _e: self._open_add_host()
        v.addWidget(addhost_row)

        # THREADS section — content rebuilt by _refresh_threads.
        threads_header, _ = _section_label_with_label("THREADS")
        v.addWidget(threads_header)
        self._threads_container = QWidget()
        self._threads_container.setLayout(QVBoxLayout())
        self._threads_container.layout().setContentsMargins(8, 0, 8, 0)
        self._threads_container.layout().setSpacing(0)
        v.addWidget(self._threads_container, 1)        # stretch fills space

        # User card — built from secrets/cloud_sync.
        self._user_card_wrap = QWidget()
        ul = QVBoxLayout(self._user_card_wrap)
        ul.setContentsMargins(8, 8, 8, 8)
        self._user_card = self._build_user_card_real()
        ul.addWidget(self._user_card)
        v.addWidget(self._user_card_wrap)

        return rail

    # ──────────────────────────────────────────────────────────────────
    # Centre pages
    # ──────────────────────────────────────────────────────────────────
    def _wrap_chat(self, chat_widget: QWidget) -> QWidget:
        """Wrap the existing ChatWindow's central widget so it lives
        inside the Studio shell instead of as its own QMainWindow."""
        wrap = QWidget()
        l = QVBoxLayout(wrap)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        try:
            inner = chat_widget.centralWidget()
            if inner is not None:
                inner.setParent(wrap)
                l.addWidget(inner)
            else:
                l.addWidget(QLabel("Chat widget has no centralWidget."))
        except Exception as ex:
            l.addWidget(QLabel(f"Chat widget unavailable: {ex}"))

        return wrap

    def _build_home(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studioPage")
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setObjectName("studioScroll")
        scroll.setStyleSheet("QScrollArea#studioScroll { background: transparent; border: none; }")

        wrap = QWidget()
        wrap.setObjectName("studioHomeBody")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(40, 32, 40, 40)
        wl.setSpacing(16)

        self._home_date = QLabel("")
        self._home_date.setObjectName("studioMonoCap")
        wl.addWidget(self._home_date)

        self._home_h1 = QLabel("Welcome.")
        self._home_h1.setObjectName("studioH1")
        wl.addWidget(self._home_h1)

        # Brand tagline — italic serif, brand voice line.
        self._home_tagline = QLabel(BRAND["tagline"])
        self._home_tagline.setObjectName("studioTagline")
        wl.addWidget(self._home_tagline)

        self._home_sub = QLabel("")
        self._home_sub.setObjectName("studioH1Sub")
        self._home_sub.setWordWrap(True)
        wl.addWidget(self._home_sub)

        # Composer card — soft raised card, real text input, terra Send.
        # Send routes text to the chat widget's input + triggers send so
        # the user can fire a prompt from Home without a context switch.
        composer = QFrame()
        composer.setObjectName("studioComposer")
        cl = QVBoxLayout(composer)
        cl.setContentsMargins(SPACE["lg"], SPACE["md"]+2,
                              SPACE["lg"], SPACE["md"]+2)
        cl.setSpacing(SPACE["md"]-2)
        from PyQt6.QtWidgets import QLineEdit
        self._home_input = QLineEdit()
        self._home_input.setObjectName("studioComposerInput")
        self._home_input.setPlaceholderText(
            "Dimension all walls in the active view…")
        self._home_input.returnPressed.connect(self._send_from_home)
        cl.addWidget(self._home_input)
        chip_row = QHBoxLayout()
        chip_row.setSpacing(SPACE["xs"]+2)
        chip_actions = [
            ("✦ Sketch", self._home_attach_sketch),
            ("● Voice",  self._home_voice),
            ("@ Skill",  self._open_palette),
            ("+ Host",   lambda: self._set_page("addhost")),
        ]
        for label, fn in chip_actions:
            b = QPushButton(label)
            b.setObjectName("studioChip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, _fn=fn: _fn())
            chip_row.addWidget(b)
        chip_row.addStretch(1)
        self._home_meta = QLabel("…")
        self._home_meta.setObjectName("studioMonoMuted")
        chip_row.addWidget(self._home_meta)
        send = QPushButton("Send  ↗")
        send.setObjectName("primaryButton")
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.clicked.connect(self._send_from_home)
        chip_row.addWidget(send)
        cl.addLayout(chip_row)
        wl.addWidget(composer)

        # Suggested skills (built from real Skills library).
        # Header: "Suggested Skills" + "from your library" + right-side
        # "BROWSE ALL →" link that jumps to the Skills page.
        self._home_skills_header = _section_h2_with_action(
            "Suggested Skills", "from your library",
            action_label="BROWSE ALL →",
            on_action=lambda: self._set_page("skills"),
        )
        wl.addWidget(self._home_skills_header)
        self._home_skills_grid_wrap = QWidget()
        self._home_skills_grid_wrap.setLayout(QHBoxLayout())
        self._home_skills_grid_wrap.layout().setSpacing(10)
        self._home_skills_grid_wrap.layout().setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self._home_skills_grid_wrap)

        # Pick up where you left off — real recent sessions.
        self._home_activity_header = _section_h2(
            "Pick up where you left off", None)
        wl.addWidget(self._home_activity_header)
        self._home_activity = QFrame()
        self._home_activity.setObjectName("studioListCard")
        self._home_activity.setLayout(QVBoxLayout())
        self._home_activity.layout().setContentsMargins(0, 0, 0, 0)
        self._home_activity.layout().setSpacing(0)
        wl.addWidget(self._home_activity)

        # Live tasks — only shown when something's actually in progress
        # (healing, queued). All-clear state hides the section.
        self._home_tasks_header = _section_h2(
            "Live tasks", "self-healing in real time")
        wl.addWidget(self._home_tasks_header)
        self._home_tasks = QFrame()
        self._home_tasks.setObjectName("studioListCard")
        self._home_tasks.setLayout(QVBoxLayout())
        self._home_tasks.layout().setContentsMargins(0, 0, 0, 0)
        self._home_tasks.layout().setSpacing(0)
        wl.addWidget(self._home_tasks)

        wl.addStretch(1)
        scroll.setWidget(wrap)

        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)
        page_l.addWidget(scroll)
        return page

    def _build_skills_page(self) -> QWidget:
        """Skills — Studio-native card grid (replaces embedded QDialog).

        Same data source (skills.library) but rendered as a real Studio
        page that matches the Marketplace visual language: card grid,
        host-coloured pills, italic-serif titles, terra Run buttons.
        """
        try:
            from skills_grid_panel import SkillsGridPanel
            return SkillsGridPanel(router=self.router, tools=self.tools,
                                   manager=self.manager,
                                   chat_widget=self.chat_widget,
                                   parent=None)
        except Exception as ex:
            return self._error_card("Skills", str(ex))

    def _build_workflows_page(self) -> QWidget:
        """Workflows — Blueprint-style node canvas (v0.29).

        Drop-in replacement for the legacy list view: same Workflow
        data model, same JSON file format. Anyone still wanting the
        list view can open Settings → Workflows or run skills via the
        Skills page.
        """
        try:
            from workflow_canvas import WorkflowCanvas
            return WorkflowCanvas(router=self.router, tool_engine=self.tools,
                                  manager=self.manager, parent=None)
        except Exception as ex:
            return self._error_card("Workflows", str(ex))

    def _build_settings_page(self) -> QWidget:
        """Settings — Studio-native sectioned chrome (v0.41).

        Replaces the previous embed-the-modal-dialog-into-the-page
        approach with SettingsPage, which has a left nav of sections
        + right content stack. Each section can be deep-linked from
        the main shell once routing supports query strings.
        """
        try:
            from settings_page import SettingsPage
            return SettingsPage(router=self.router, parent=None)
        except Exception as ex:
            page = QWidget()
            page.setObjectName("studioPage")
            v = QVBoxLayout(page)
            v.setContentsMargins(40, 32, 40, 40)
            v.addWidget(self._error_card("Settings", str(ex)))
            return page

    def _build_pricing_page(self) -> QWidget:
        """Two-tier pricing comparison ($0 BYO vs $199 Studio)."""
        try:
            from pricing_page import PricingPage
            return PricingPage(parent=None)
        except Exception as ex:
            return self._build_placeholder("Pricing", str(ex))

    def _build_marketplace_page(self) -> QWidget:
        """Marketplace — official catalog of Skills + Workflows. v0.30."""
        try:
            from marketplace_panel import MarketplacePanel
            return MarketplacePanel(parent=None)
        except Exception as ex:
            return self._error_card("Marketplace", str(ex))

    def _build_addhost_page(self) -> QWidget:
        """Add Host — Studio-native host detection + auto-build panel.

        Replaces the modal onboarding wizard fall-through. v0.28.
        """
        try:
            from add_host_panel import AddHostPanel
            return AddHostPanel(manager=self.manager, parent=None)
        except Exception as ex:
            return self._error_card("Add Host", str(ex))

    def _build_telemetry_page(self) -> QWidget:
        """Telemetry — KPI card grid + connector health table.

        Three KPI cards across the top (live hosts · self-healing ·
        spend) with mono numerals, then a list-card with one row per
        host family for state / attempts / last-error.
        """
        page = QWidget()
        page.setObjectName("studioPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header.
        head = QWidget()
        hh = QVBoxLayout(head)
        hh.setContentsMargins(40, 32, 40, 12)
        hh.setSpacing(4)
        cap = QLabel("TELEMETRY")
        cap.setObjectName("studioMonoCap")
        hh.addWidget(cap)
        h1 = QLabel("Live system telemetry")
        h1.setObjectName("studioH1")
        hh.addWidget(h1)
        outer.addWidget(head)

        # Scroll wrap.
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setObjectName("studioScroll")
        scroll.setStyleSheet(
            "QScrollArea#studioScroll { background:transparent; border:none; }")
        body = QWidget()
        body.setObjectName("studioPage")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(40, 0, 40, 40)
        bl.setSpacing(SPACE["lg"])

        # KPI grid (3 cards).
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(SPACE["md"])
        self._tel_kpi_hosts = _kpi_card("HOSTS LIVE", "0 / 0",
                                         T["ok"])
        self._tel_kpi_heal  = _kpi_card("SELF-HEALING", "0",
                                         T["warn"])
        self._tel_kpi_spend = _kpi_card("MONTH SPEND", "$0.00",
                                         T["accent"])
        for c in (self._tel_kpi_hosts, self._tel_kpi_heal,
                  self._tel_kpi_spend):
            kpi_row.addWidget(c, 1)
        kpi_w = QWidget(); kpi_w.setLayout(kpi_row)
        bl.addWidget(kpi_w)

        # Section header.
        bl.addWidget(_section_h2("Connector health", "live snapshot"))
        # Existing list-card holds per-family rows.
        self._tel_table = QFrame()
        self._tel_table.setObjectName("studioListCard")
        self._tel_table.setLayout(QVBoxLayout())
        self._tel_table.layout().setContentsMargins(0, 0, 0, 0)
        self._tel_table.layout().setSpacing(0)
        bl.addWidget(self._tel_table)

        # Reality Check sparklines (v0.42) — per-host 24h trend.
        bl.addWidget(_section_h2("Reality Check", "last 24 hours"))
        try:
            from reality_check_panel import RealityCheckPanel
            rc = RealityCheckPanel(router=self.router, parent=None)
            # Drop the panel's own header — telemetry already has one.
            try:
                rc.layout().setContentsMargins(0, 0, 0, 0)
                # Hide the panel's H1+sub since we surface them above.
                for i in range(min(3, rc.layout().count())):
                    w = rc.layout().itemAt(i).widget()
                    if isinstance(w, QLabel):
                        w.hide()
            except Exception:
                pass
            bl.addWidget(rc)
        except Exception as ex:
            bl.addWidget(self._error_card("Reality Check", str(ex)))

        bl.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        return page

    def _build_placeholder(self, title: str, sub: str) -> QWidget:
        page = QWidget()
        page.setObjectName("studioPage")
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 40, 40, 40)
        l.setSpacing(8)
        cap = QLabel(title.upper())
        cap.setObjectName("studioMonoCap")
        l.addWidget(cap)
        h = QLabel(title)
        h.setObjectName("studioH1")
        l.addWidget(h)
        s = QLabel(sub)
        s.setObjectName("studioH1Sub")
        s.setWordWrap(True)
        l.addWidget(s)
        l.addStretch(1)
        return page

    def _error_card(self, label: str, msg: str) -> QFrame:
        card = QFrame()
        card.setObjectName("studioListCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 20, 20, 20)
        h = QLabel(f"{label} — failed to embed")
        h.setObjectName("studioH2")
        v.addWidget(h)
        m = QLabel(msg)
        m.setObjectName("studioH1Sub")
        m.setWordWrap(True)
        v.addWidget(m)
        return card

    # ──────────────────────────────────────────────────────────────────
    # Inspector
    # ──────────────────────────────────────────────────────────────────
    def _build_inspector(self) -> QFrame:
        """Right inspector — three stacked sections matching studio.jsx:

          LLM ROUTER     model rows with active dot, latency, price
          SELECTION      contextual entity + property rows
          QUICK ACTIONS  chevron-prefix command list

        On Chat the SELECTION section swaps to the live ParametersPanel.
        """
        ins = QFrame()
        ins.setObjectName("studioInspector")
        ins.setFixedWidth(304)
        outer = QVBoxLayout(ins)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("studioScroll")
        scroll.setStyleSheet(
            "QScrollArea#studioScroll { background:transparent; border:none; }")
        body = QWidget()
        body.setObjectName("studioInspectorBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(SPACE["lg"])

        # ── LLM ROUTER ────────────────────────────────────────────
        cap1 = QLabel("LLM ROUTER")
        cap1.setObjectName("studioMonoCap")
        v.addWidget(cap1)
        self._ins_router_wrap = QWidget()
        rwl = QVBoxLayout(self._ins_router_wrap)
        rwl.setContentsMargins(0, 0, 0, 0)
        rwl.setSpacing(SPACE["xs"]+2)
        v.addWidget(self._ins_router_wrap)

        # ── SELECTION (or PARAMETERS on Chat) ─────────────────────
        self._ins_cap = QLabel("SELECTION")
        self._ins_cap.setObjectName("studioMonoCap")
        v.addWidget(self._ins_cap)
        self._ins_title = QLabel("Nothing selected")
        self._ins_title.setObjectName("studioInspectorTitle")
        v.addWidget(self._ins_title)

        # Static KV rows for SELECTION default state.
        self._ins_kv_wrap = QWidget()
        kv_l = QVBoxLayout(self._ins_kv_wrap)
        kv_l.setContentsMargins(0, 0, 0, 0)
        kv_l.setSpacing(SPACE["xs"])
        self._ins_rows: dict[str, QLabel] = {}
        for key in ("Active host", "Connectors", "Skills", "Model", "Latency"):
            row, value_lbl = _inspector_kv(key, "…")
            kv_l.addWidget(row)
            self._ins_rows[key] = value_lbl
        v.addWidget(self._ins_kv_wrap)

        # Parameters panel slot — instantiated lazily when entering Chat.
        self._ins_params_wrap = QWidget()
        pl = QVBoxLayout(self._ins_params_wrap)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self._ins_params_wrap.setVisible(False)
        v.addWidget(self._ins_params_wrap)
        self._ins_params_panel = None

        # ── QUICK ACTIONS ────────────────────────────────────────
        cap3 = QLabel("QUICK ACTIONS")
        cap3.setObjectName("studioMonoCap")
        v.addWidget(cap3)
        self._ins_actions_wrap = QWidget()
        awl = QVBoxLayout(self._ins_actions_wrap)
        awl.setContentsMargins(0, 0, 0, 0)
        awl.setSpacing(SPACE["xs"])
        v.addWidget(self._ins_actions_wrap)

        v.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # Initial fill.
        self._refresh_router_rows()
        self._refresh_quick_actions()
        return ins

    def _refresh_router_rows(self) -> None:
        layout = self._ins_router_wrap.layout()
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        models = self._known_models()
        active = (self._current_model() or "").strip()
        for m in models:
            row = self._make_router_row(
                name=m["name"], company=m["company"],
                price=m.get("price", ""), latency=m.get("latency", ""),
                active=(m["id"] == active or m["name"] == active),
                model_id=m["id"],
            )
            layout.addWidget(row)

    def _make_router_row(self, *, name: str, company: str, price: str,
                         latency: str, active: bool, model_id: str) -> QFrame:
        row = QFrame()
        row.setObjectName("studioRouterRow")
        row.setProperty("active", active)
        h = QHBoxLayout(row)
        h.setContentsMargins(SPACE["sm"]+1, SPACE["sm"]-1,
                             SPACE["sm"]+1, SPACE["sm"]-1)
        h.setSpacing(SPACE["sm"])
        # Active dot.
        dot = QLabel("●" if active else "○")
        dot.setStyleSheet(
            f"color:{T['accent'] if active else T['inkDim']}; font-size:9px;")
        dot.setFixedWidth(10)
        h.addWidget(dot)
        # Name + company column.
        col_w = QWidget()
        col = QVBoxLayout(col_w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        nl = QLabel(name)
        nl.setObjectName("studioRouterName")
        col.addWidget(nl)
        meta = QLabel(f"{company.upper()}  ·  {price}" if price else company.upper())
        meta.setObjectName("studioMonoCap")
        col.addWidget(meta)
        h.addWidget(col_w, 1)
        # Latency right-aligned.
        if latency:
            lat = QLabel(latency)
            lat.setObjectName("studioMonoMuted")
            h.addWidget(lat)
        # Click to switch (best-effort — sets default_model setting).
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.mousePressEvent = lambda _e, mid=model_id: self._set_default_model(mid)
        # Restyle so :active variant repaints.
        row.setStyleSheet(_router_row_qss(active))
        return row

    def _set_default_model(self, model_id: str) -> None:
        try:
            from secrets_store import save_setting
            save_setting("default_model", model_id)
        except Exception:
            pass
        # Push through chat widget's model picker. setCurrentText only
        # works if the visible label matches; correct path is to find
        # the item whose itemData() equals model_id and setCurrentIndex.
        for attr in ("model_combo", "model_picker", "_model_combo"):
            w = getattr(self.chat_widget, attr, None)
            if w is None:
                continue
            try:
                target_id = model_id
                # Inspector seeds use bare ids ("claude-sonnet-4.5");
                # picker uses provider-prefixed ids ("anthropic:...").
                # If exact match fails, try prefix-match against ids
                # that end with this label.
                idx = -1
                for i in range(w.count()):
                    data = w.itemData(i)
                    if data == target_id or (data and data.endswith(":" + target_id)):
                        idx = i
                        break
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    # Last resort: try setCurrentText (works on QComboBox
                    # with the visible label).
                    if hasattr(w, "setCurrentText"):
                        w.setCurrentText(model_id)
            except Exception:
                pass
            break
        # Refresh router rows so the active dot moves.
        self._refresh_router_rows()
        # Force status rule re-read.
        self._refresh_status_rule()
        # Toast confirms the switch.
        try:
            from toast import show_toast
            show_toast(self, f"Switched to {model_id}", kind="ok")
        except Exception:
            pass

    def _known_models(self) -> list[dict]:
        """Return up to 4 models surfaced in the inspector. Pulls from
        the live llm_router catalog when available; falls back to a
        seeded list so the panel never looks empty."""
        out: list[dict] = []
        try:
            from llm_router import KNOWN_MODELS
            for m in (KNOWN_MODELS or [])[:4]:
                if isinstance(m, dict):
                    out.append({
                        "id":      m.get("id") or m.get("name") or "",
                        "name":    m.get("display") or m.get("name") or m.get("id") or "model",
                        "company": (m.get("provider") or "").upper(),
                        "price":   m.get("price") or "",
                        "latency": m.get("latency") or "",
                    })
                elif isinstance(m, str):
                    out.append({"id": m, "name": m, "company": "",
                                "price": "", "latency": ""})
        except Exception:
            pass
        if not out:
            # Brand-coherent seed — same lineup the handoff inspector
            # mocks. Strict labels: company caps mono, price right-mono.
            out = [
                {"id": "claude-sonnet-4.5", "name": "Claude Sonnet 4.5",
                 "company": "anthropic", "price": "$3/M", "latency": "420ms"},
                {"id": "gpt-5",             "name": "GPT-5",
                 "company": "openai",    "price": "$5/M", "latency": "510ms"},
                {"id": "gemini-2.5-pro",    "name": "Gemini 2.5 Pro",
                 "company": "google",    "price": "$2/M", "latency": "380ms"},
                {"id": "qwen3:32b",         "name": "qwen3:32b (local)",
                 "company": "ollama",    "price": "free", "latency": "980ms"},
            ]
        return out

    def _refresh_quick_actions(self) -> None:
        layout = self._ins_actions_wrap.layout()
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        # Page-aware action list.
        actions = self._quick_actions_for_page()
        for label, fn in actions:
            row = QFrame()
            row.setObjectName("studioQuickAction")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            h = QHBoxLayout(row)
            h.setContentsMargins(SPACE["sm"]+2, SPACE["xs"]+1,
                                 SPACE["sm"]+2, SPACE["xs"]+1)
            h.setSpacing(SPACE["sm"])
            chev = QLabel("›")
            chev.setObjectName("studioQuickActionChev")
            h.addWidget(chev)
            t = QLabel(label)
            t.setObjectName("studioQuickActionText")
            h.addWidget(t, 1)
            row.mousePressEvent = lambda _e, _fn=fn: _fn()
            layout.addWidget(row)

    def _quick_actions_for_page(self) -> list[tuple[str, callable]]:
        # v1.3.1 dead-surface pass: dropped "New session" (chat) and
        # "Spawn pet strip" (default). The former wired to a method
        # that doesn't exist on ChatWindow (`_new_session`), so the row
        # silently no-op'd. The latter was a deprecation toast left over
        # from the v1.0.2 pet-strip removal. To revive: re-add the
        # tuple in the matching branch.
        page = self._active_page
        if page == "chat":
            return [
                ("Save session", lambda: getattr(self.chat_widget,
                    "_save_session", lambda: None)()),
                ("Open session…", lambda: getattr(self.chat_widget,
                    "_open_sessions", lambda: None)()),
            ]
        if page == "addhost":
            return [
                ("Refresh detection", lambda: (self.manager.refresh()
                    if self.manager is not None else None)),
            ]
        # Default: shell-wide actions.
        return [
            ("Open ⌘K palette",     self._open_palette),
            ("Add host…",           lambda: self._set_page("addhost")),
            ("Browse Marketplace",  lambda: self._set_page("market")),
            ("Switch theme",        self._toggle_theme),
        ]

    def _ensure_params_panel(self):
        """Instantiate (once) the live ParametersPanel bound to the
        chat session. Returns True if the panel is available."""
        if self._ins_params_panel is not None:
            return True
        try:
            from parameters_panel import ParametersPanel
            session = getattr(self.chat_widget, "session", None)
            if session is None:
                return False
            panel = ParametersPanel()
            panel.set_session(session)
            self._ins_params_panel = panel
            self._ins_params_wrap.layout().addWidget(panel)
            # Edits route through the existing chat-window handler so
            # downstream steps re-run the same way they would from the
            # legacy split-pane sidebar.
            try:
                handler = getattr(self.chat_widget,
                                  "_on_parameter_edited", None)
                if callable(handler):
                    panel.parameter_edited.connect(handler)
            except Exception:
                pass
            return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────
    # Status rule
    # ──────────────────────────────────────────────────────────────────
    def _build_status_rule(self) -> QFrame:
        """Bottom status rule — matches studio.jsx reference layout:

        ●  N/M hosts    tokens 2.4M    spend $47.82    ↻ 1 self-healing
                                        ⌘K palette  ⌘↩ run skill  ⌘/ docs  v0.27.6
        """
        rule = QFrame()
        rule.setObjectName("studioStatusRule")
        rule.setFixedHeight(26)
        h = QHBoxLayout(rule)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(18)
        self._sr_hosts = QLabel("● 0/0 hosts")
        self._sr_hosts.setObjectName("studioStatusItem")
        h.addWidget(self._sr_hosts)
        # `tokens —` placeholder was always "—" — no live data was ever
        # wired in. v1.3.1 hides it. To revive: setVisible(True) here
        # and write `self._sr_tokens.setText(...)` from a token-count
        # source (router last-response usage, or a rolling tally).
        self._sr_tokens = QLabel("tokens —")
        self._sr_tokens.setObjectName("studioStatusItem")
        self._sr_tokens.setVisible(False)
        h.addWidget(self._sr_tokens)
        self._sr_spend = QLabel("spend $0.00")
        self._sr_spend.setObjectName("studioStatusItem")
        h.addWidget(self._sr_spend)
        # ArchHub Cloud usage meter — shown only when the user is
        # signed in to the paid managed proxy. Updates every 5s when
        # the Telemetry tick runs; click opens billing portal.
        self._sr_cloud = QLabel("")
        self._sr_cloud.setObjectName("studioStatusItem")
        self._sr_cloud.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sr_cloud.setVisible(False)
        self._sr_cloud.mousePressEvent = lambda _e: self._open_cloud_portal()
        h.addWidget(self._sr_cloud)
        # Healing item — small pulsing dot + label, only shown when
        # at least one connector is actively self-healing.
        heal_wrap = QWidget()
        heal_h = QHBoxLayout(heal_wrap)
        heal_h.setContentsMargins(0, 0, 0, 0)
        heal_h.setSpacing(SPACE["xs"]+1)
        self._sr_heal_dot = _PulseDot(T["warn"])
        heal_h.addWidget(self._sr_heal_dot)
        self._sr_heal = QLabel("")
        self._sr_heal.setObjectName("studioStatusItem")
        heal_h.addWidget(self._sr_heal)
        self._sr_heal_wrap = heal_wrap
        heal_wrap.setVisible(False)
        h.addWidget(heal_wrap)
        h.addStretch(1)
        # Read version dynamically so the status bar reflects the
        # actual VERSION file, not a stale hardcoded string. Falls
        # back to "dev" if the file is unreadable.
        ver_str = "dev"
        try:
            from pathlib import Path as _P
            vpath = _P(__file__).resolve().parent.parent / "VERSION"
            if vpath.exists():
                ver_str = vpath.read_text(encoding="utf-8").strip() or "dev"
        except Exception:
            pass
        right = QLabel(
            f"⌘K palette     ⌘↩ run skill     "
            f"⌘/ docs     v{ver_str}"
        )
        right.setObjectName("studioStatusItem")
        h.addWidget(right)
        return rule

    # ──────────────────────────────────────────────────────────────────
    # User card (real account)
    # ──────────────────────────────────────────────────────────────────
    def _build_user_card_real(self) -> QFrame:
        # Resolve user email + display name + tier.
        email = ""
        name = ""
        tier = "BYO · LOCAL"
        try:
            from secrets_store import load_setting
            email = (load_setting("user_email") or "").strip()
            name = (load_setting("user_name") or "").strip()
        except Exception:
            pass
        if not name:
            name = email.split("@")[0] if email else (os.environ.get("USERNAME") or "User")
        try:
            from cloud_sync import is_signed_in
            if is_signed_in():
                tier = "BYO · CLOUD"
        except Exception:
            pass

        card = QFrame()
        card.setObjectName("studioUserCard")
        h = QHBoxLayout(card)
        h.setContentsMargins(10, 7, 10, 7)
        h.setSpacing(9)
        av = QLabel((name[:1] or "U").upper())
        av.setObjectName("studioAvatar")
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setFixedSize(24, 24)
        h.addWidget(av)
        col_w = QWidget()
        col = QVBoxLayout(col_w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        n = QLabel(name)
        n.setObjectName("studioUserName")
        t = QLabel(tier)
        t.setObjectName("studioMonoCap")
        col.addWidget(n)
        col.addWidget(t)
        h.addWidget(col_w, 1)
        cog = QToolButton()
        cog.setText("⚙")
        cog.setObjectName("studioCog")
        cog.setCursor(Qt.CursorShape.PointingHandCursor)
        cog.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # Cog menu: Settings · Theme toggle · Sign out.
        menu = QMenu(cog)
        act_settings = menu.addAction("Settings")
        act_settings.triggered.connect(lambda: self._set_page("settings"))
        menu.addSeparator()
        act_theme = menu.addAction(
            "Switch to dark theme" if active_theme() == "light"
            else "Switch to light theme"
        )
        act_theme.triggered.connect(self._toggle_theme)
        menu.addSeparator()
        act_about = menu.addAction(f"About — {BRAND['name']} {BRAND['version']}")
        act_about.setEnabled(False)
        cog.setMenu(menu)
        h.addWidget(cog)
        return card

    # ──────────────────────────────────────────────────────────────────
    # Live refresh
    # ──────────────────────────────────────────────────────────────────
    def _refresh_live(self) -> None:
        # Cheap, always-run text updates first.
        try:
            self._refresh_status_rule()
        except Exception:
            pass
        try:
            self._refresh_inspector()
        except Exception:
            pass
        # Rail surfaces — diff-rebuild only on signature change.
        try:
            self._refresh_hosts()
        except Exception:
            pass
        try:
            self._refresh_threads()
        except Exception:
            pass
        # Page-specific — gate on which page the user is actually
        # looking at. No reason to rebuild Home's three lists every
        # 5 s when the user is on Settings.
        if self._active_page == "home":
            try:
                self._refresh_home()
            except Exception:
                pass
        if self._active_page == "telemetry":
            try:
                self._refresh_telemetry_page()
            except Exception:
                pass

    def _refresh_hosts(self) -> None:
        if self.manager is None:
            return
        entries = list(self.manager.entries)
        # Health snapshot once.
        try:
            from connector_health import instance as _hi
            health = _hi()
        except Exception:
            health = None

        # Build a cheap signature: (entry.id, entry.state, health.state(family),
        # expanded?). Skip the entire rebuild when nothing's changed.
        # Expansion participates so sub-rows toggle without waiting for
        # a state transition to invalidate the signature.
        from manager import ConnectorState
        sig_items = []
        for e in entries:
            fam = getattr(e, "family", "")
            try:
                hs = health.state(fam) if (health is not None and fam) else "unknown"
            except Exception:
                hs = "unknown"
            expanded = fam in self._hosts_expanded
            sig_items.append((e.id,
                              e.state.name if isinstance(e.state, ConnectorState) else str(e.state),
                              hs, expanded))
        sig = tuple(sig_items)
        if sig == self._last_hosts_sig:
            return  # nothing to do — saves ~30 widget recreations per tick

        self._last_hosts_sig = sig
        self._hosts_count_lbl.setText(f"HOSTS · {len(entries)}")
        layout = self._hosts_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for e in entries:
            row = self._make_host_row(e, health)
            layout.addWidget(row)
        if health is not None:
            for e in entries:
                fam = getattr(e, "family", "")
                if not fam:
                    continue
                try:
                    self._host_prev_state[fam] = health.state(fam)
                except Exception:
                    pass

    def _make_host_row(self, entry, health) -> QFrame:
        # Wrapper: header row on top + optional sessions sub-list below
        # when the user has expanded this family. We return the wrapper
        # so the rail layout can keep treating each entry as one widget.
        wrap = QFrame()
        wrap.setObjectName("studioHostRowWrap")
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(0)

        row = QFrame()
        row.setObjectName("studioHostRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(9, 5, 9, 5)
        h.setSpacing(8)
        wv.addWidget(row)

        # Health-driven dot.
        family = getattr(entry, "family", "")
        state_str = "unknown"
        if health is not None and family:
            try:
                state_str = health.state(family)
            except Exception:
                state_str = "unknown"
        # ConnectorEntry.state is the manager-side flag (READY/ACTIVE/...).
        from manager import ConnectorState
        active = entry.state == ConnectorState.ACTIVE
        unavailable = entry.state == ConnectorState.UNAVAILABLE
        # Color rule: live=ok; loaded_dead=warn; host_offline=muted;
        # inactive when active flag set=muted; unavailable=dim.
        if state_str == "live":
            color = T["ok"]
        elif state_str == "loaded_dead":
            color = T["warn"]
        elif state_str == "host_offline":
            color = T["inkCap"]
        else:
            color = T["inkCap"] if active else T["inkDim"]
        dot = _PulseDot(color)
        h.addWidget(dot)
        # Track previous state per family so we can pulse on transition
        # ("ConnectorBirth" — quiet motion when a host comes alive or
        # heals). Storage lives on the shell instance.
        prev = self._host_prev_state.get(family) if hasattr(self, "_host_prev_state") else None
        if prev is not None and prev != state_str:
            # Pulse only on transitions INTO live or loaded_dead — not on
            # outbound death (which would be loud + distracting).
            if state_str in ("live", "loaded_dead"):
                QTimer.singleShot(50, dot.pulse)

        n = QLabel(entry.display_name)
        n.setObjectName("studioHostName")
        h.addWidget(n, 1)

        # Detail: for revit + outlook, surface session count when >1
        # ("Revit · 2 sess"); for other families, port or status word.
        port = FAMILY_PORT.get(family, "")
        sessions_n = 0
        if health is not None and family == "revit":
            try:
                sessions_n = int(health.info("revit").get("sessions") or 0)
            except Exception:
                sessions_n = 0
        elif family == "outlook":
            try:
                import outlook_broker
                sessions_n = outlook_broker.sessions_count()
            except Exception:
                sessions_n = 0
        elif family == "max":
            try:
                import max_broker
                sessions_n = max_broker.sessions_count()
            except Exception:
                sessions_n = 0
        elif family == "autocad":
            try:
                import acad_broker
                sessions_n = acad_broker.sessions_count()
            except Exception:
                sessions_n = 0
        if state_str == "live":
            if family in ("revit", "outlook", "max", "autocad") and sessions_n > 1:
                detail = f"{sessions_n} sess"
            else:
                detail = port or "live"
        elif state_str == "loaded_dead":
            detail = "↻ heal"
        elif state_str == "host_offline":
            detail = "host off"
        elif unavailable:
            detail = "n/a"
        elif active:
            detail = "loading"
        else:
            detail = "off"
        p = QLabel(detail)
        p.setObjectName("studioMonoMuted")
        # Tooltip lists per-session breakdown for revit + outlook.
        if family == "revit" and sessions_n >= 1:
            p.setToolTip(_revit_sessions_tooltip())
        elif family == "outlook" and sessions_n >= 1:
            p.setToolTip(_outlook_sessions_tooltip())
        h.addWidget(p)

        # Toggle — iOS-style sliding-knob switch (matches studio.jsx).
        tog = _ToggleSwitch(on=active)
        tog.setEnabledState(not unavailable)
        # Use a closure that captures the entry.id.
        def on_toggled(checked, entry_id=entry.id, btn=tog):
            try:
                if checked:
                    ok, msg = self.manager.activate(entry_id)
                else:
                    ok, msg = self.manager.deactivate(entry_id)
                if not ok:
                    btn.blockSignals(True)
                    btn.setChecked(not checked)
                    btn.blockSignals(False)
                    p.setText("err")
                    p.setToolTip(msg)
                # Invalidate the diff signature so the next tick rebuilds.
                self._last_hosts_sig = ()
                QTimer.singleShot(200, self._refresh_hosts)
            except Exception as ex:
                p.setText("err")
                p.setToolTip(str(ex))
        tog.toggled.connect(on_toggled)
        h.addWidget(tog)

        # Click on the row body (anywhere except the toggle) toggles
        # the per-session sub-list. Only meaningful for multi-instance
        # families with at least one live session.
        multi_capable = family in ("revit", "max", "autocad", "outlook")
        if multi_capable and sessions_n >= 1:
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            def _toggle_expand(_e, fam=family):
                if fam in self._hosts_expanded:
                    self._hosts_expanded.discard(fam)
                else:
                    self._hosts_expanded.add(fam)
                self._last_hosts_sig = ()
                self._refresh_hosts()
            row.mousePressEvent = _toggle_expand

        # Sub-list — only render when expanded.
        if family in self._hosts_expanded and multi_capable:
            sub_rows = self._make_session_sublist(family)
            if sub_rows is not None:
                wv.addWidget(sub_rows)

        return wrap

    # --- per-session sub-list (HOSTS row expansion) -----------------------

    def _make_session_sublist(self, family: str) -> QFrame | None:
        """Build the indented sessions list shown when a HOSTS row is
        expanded. Each child row pins to one session via @<id> when
        clicked. Returns None when the broker yields nothing."""
        try:
            sessions = self._broker_sessions(family)
        except Exception:
            sessions = []
        if not sessions:
            return None
        box = QFrame()
        box.setObjectName("studioHostSubList")
        v = QVBoxLayout(box)
        v.setContentsMargins(SPACE["xl"], 0, SPACE["sm"], SPACE["xs"])
        v.setSpacing(2)
        for s in sessions:
            child = QFrame()
            child.setObjectName("studioHostSubRow")
            ch = QHBoxLayout(child)
            ch.setContentsMargins(6, 3, 6, 3)
            ch.setSpacing(8)
            healthy = bool(getattr(s, "healthy", False))
            dot = QLabel("●" if healthy else "○")
            dot.setStyleSheet(
                f"color: {T['ok'] if healthy else T['inkDim']}; "
                f"font-size: 10px;"
            )
            ch.addWidget(dot)
            label = self._fmt_session_label(family, s)
            name = QLabel(label)
            name.setObjectName("studioMonoMuted")
            ch.addWidget(name, 1)
            pin_token = self._fmt_session_pin(family, s)
            chip = QLabel(f"@{pin_token}")
            chip.setObjectName("studioPinChip")
            ch.addWidget(chip)
            child.setCursor(Qt.CursorShape.PointingHandCursor)
            child.setToolTip(f"Pin chat to {pin_token}")
            child.mousePressEvent = (
                lambda _e, tok=pin_token: self._inject_pin_into_chat(tok)
            )
            v.addWidget(child)
        return box

    def _broker_sessions(self, family: str) -> list:
        if family == "revit":
            import revit_broker as b
        elif family == "max":
            import max_broker as b
        elif family == "autocad":
            import acad_broker as b
        elif family == "outlook":
            import outlook_broker as b
        else:
            return []
        return list(b.list_sessions(prune=False) or [])

    @staticmethod
    def _fmt_session_label(family: str, s) -> str:
        title = (getattr(s, "doc_title", "") or "").strip()
        ver = getattr(s, "version", "") or ""
        if family == "outlook":
            smtp = getattr(s, "smtp_address", "") or ""
            return title or smtp or "Account"
        bits = []
        if title:
            bits.append(title[:32])
        else:
            bits.append(f"pid {getattr(s, 'pid', 0)}")
        if ver:
            bits.append(ver)
        return " · ".join(bits)

    @staticmethod
    def _fmt_session_pin(family: str, s) -> str:
        # Tokens that survive the chat composer's @-parser. Doc title
        # wins when slug-friendly; falls back to PID; falls back to
        # session_id; for Outlook the SMTP local-part is friendliest.
        title = (getattr(s, "doc_title", "") or "").strip()
        if family == "outlook":
            smtp = getattr(s, "smtp_address", "") or ""
            if smtp:
                return smtp.split("@")[0]
            return title.replace(" ", "_") or "outlook"
        if title and all(c.isalnum() or c in "._-" for c in title):
            return title
        pid = getattr(s, "pid", 0)
        if pid:
            return str(pid)
        return getattr(s, "session_id", family)

    def _inject_pin_into_chat(self, token: str) -> None:
        """Switch to chat page, prepend `@token ` to the input, focus."""
        self._set_page("chat")
        try:
            inp = getattr(self.chat_widget, "input", None)
            if inp is None:
                return
            existing = inp.text()
            mention = f"@{token} "
            if mention.strip() in existing:
                inp.setFocus()
                return
            inp.setText(mention + existing)
            inp.setFocus()
            try:
                # Cursor to end so the user types after the chip.
                inp.setCursorPosition(len(inp.text()))
            except Exception:
                pass
        except Exception:
            pass

    def _refresh_threads(self) -> None:
        sessions = self._cached_sessions()
        # Diff signature: top-8 (path, saved_at). Rebuild only on change.
        sig = tuple((str(p), s) for p, _n, s in sessions[:8])
        if sig == self._last_threads_sig:
            return
        self._last_threads_sig = sig
        layout = self._threads_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not sessions:
            empty = QLabel("  No saved sessions yet.")
            empty.setObjectName("studioMonoMuted")
            layout.addWidget(empty)
            return
        # Pinned set comes from secrets_store. The most recent session
        # is auto-pinned when no manual pins exist so the rail always
        # has at least one starred row.
        try:
            from secrets_store import load_setting
            pinned_ids = set(load_setting("pinned_threads") or [])
        except Exception:
            pinned_ids = set()
        for i, (path, name, saved_at) in enumerate(sessions[:8]):
            when = _short_when(saved_at)
            display = name or path.stem
            pinned = (str(path) in pinned_ids
                      or (not pinned_ids and i == 0))
            row = _thread_row(display, when, pinned=pinned)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip(display)
            row.mousePressEvent = lambda _e, p=path: self._open_session_path(p)
            layout.addWidget(row)

    # ------------------------------------------------------------------
    # Disk-read caches — list_sessions and list_skills both walk the
    # disk + parse JSON; doing that every tick on the Qt main thread
    # was a big chunk of the perceived lag. 5-second TTL is plenty
    # given the rail's 5-s refresh cadence.
    # ------------------------------------------------------------------
    def _cached_sessions(self) -> list:
        import time as _t
        ts, val = self._sessions_cache
        if (_t.time() - ts) < 5.0:
            return val
        try:
            from session_io import list_sessions
            val = list_sessions() or []
        except Exception:
            val = []
        self._sessions_cache = (_t.time(), val)
        return val

    def _cached_skills(self) -> list:
        import time as _t
        ts, val = self._skills_cache
        if (_t.time() - ts) < 5.0:
            return val
        try:
            from skills.library import list_skills
            val = list_skills() or []
        except Exception:
            val = []
        self._skills_cache = (_t.time(), val)
        return val

    def _open_session_path(self, path: Path) -> None:
        # Switch to chat page, then ask the chat widget to load the
        # full conversation transcript (not just session params).
        self._set_page("chat")
        try:
            from session_io import load_session_with_messages
            new_session, name, msgs = load_session_with_messages(path)
            if hasattr(self.chat_widget, "session"):
                self.chat_widget.session = new_session
            if hasattr(self.chat_widget, "parameters_panel"):
                try:
                    self.chat_widget.parameters_panel.set_session(new_session)
                except Exception:
                    pass
            # Re-render chat bubbles from the persisted message list.
            if hasattr(self.chat_widget, "_restore_history"):
                try:
                    self.chat_widget._restore_history(msgs)
                    # Pin the autosave path so subsequent saves overwrite
                    # this session instead of forking a new file.
                    self.chat_widget._autosave_path = path
                except Exception:
                    pass
        except Exception:
            pass

    def _refresh_status_rule(self) -> None:
        live = 0
        heal = 0
        total = 0
        try:
            from connector_health import instance as _hi
            snap = _hi().snapshot()
            total = len(snap)
            for fam, info in snap.items():
                st = info.get("state", "unknown")
                if st == "live":
                    live += 1
                elif st == "loaded_dead":
                    heal += 1
        except Exception:
            pass
        self._sr_hosts.setText(f"● {live}/{total} hosts")
        self._sr_tokens.setText(f"tokens {self._tokens_label()}")
        self._sr_spend.setText(f"spend {self._spend_label()}")
        if heal > 0:
            self._sr_heal.setText(f"↻ {heal} self-healing")
            self._sr_heal_wrap.setVisible(True)
            try:
                self._sr_heal_dot.pulse()
            except Exception:
                pass
        else:
            self._sr_heal_wrap.setVisible(False)

        # ArchHub Cloud usage chip. Only visible when signed in.
        self._refresh_cloud_meter()

    def _refresh_cloud_meter(self) -> None:
        try:
            from cloud_client import is_signed_in
            if not is_signed_in():
                self._sr_cloud.setVisible(False)
                return
            from cloud_usage import snapshot, refresh_async
            snap = snapshot()
            if snap is None:
                # Kick a background refresh and render a placeholder
                # until the response lands.
                refresh_async(callback=lambda _p: None)
                self._sr_cloud.setText("☁ Cloud · syncing…")
            else:
                rem = snap.get("remaining_messages")
                plan = snap.get("plan") or "trial"
                if rem is None:
                    self._sr_cloud.setText(f"☁ Cloud · {plan}")
                else:
                    self._sr_cloud.setText(f"☁ Cloud · {rem} left")
            self._sr_cloud.setVisible(True)
        except Exception:
            self._sr_cloud.setVisible(False)

    def _open_cloud_portal(self) -> None:
        """Click on the cloud meter → open Stripe Customer Portal in
        the user's default browser so they can change plan / cancel /
        update card without leaving the app."""
        try:
            from cloud_client import portal_url
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            url = portal_url() or "https://archhub.app/billing"
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            pass

    def _tokens_label(self) -> str:
        # Best-effort: read telemetry total tokens; fall back to dash.
        try:
            from secrets_store import load_setting
            n = load_setting("month_tokens_total")
            if isinstance(n, (int, float)) and n > 0:
                if n > 1_000_000:
                    return f"{n / 1_000_000:.1f}M"
                if n > 1000:
                    return f"{n / 1000:.1f}K"
                return str(int(n))
        except Exception:
            pass
        return "—"

    def _refresh_inspector(self) -> None:
        active_count = 0
        active_name = "—"
        if self.manager is not None:
            try:
                from manager import ConnectorState
                actives = [e for e in self.manager.entries if e.state == ConnectorState.ACTIVE]
                active_count = len(actives)
                if actives:
                    active_name = actives[0].display_name
            except Exception:
                pass
        skills_count = self._skills_count()
        model = self._current_model() or "—"
        lat = self._last_latency_ms() or "—"

        self._ins_rows["Active host"].setText(active_name)
        self._ins_rows["Connectors"].setText(f"{active_count} active")
        self._ins_rows["Skills"].setText(f"{skills_count} synced")
        self._ins_rows["Model"].setText(model)
        self._ins_rows["Latency"].setText(lat)

    def _refresh_home(self) -> None:
        # Date caption.
        now = datetime.now()
        # %#d on Windows / %-d on POSIX — fall back to %d if neither.
        try:
            self._home_date.setText(now.strftime("%a · %b %#d · %H:%M").upper())
        except Exception:
            try:
                self._home_date.setText(now.strftime("%a · %b %d · %H:%M").upper())
            except Exception:
                self._home_date.setText("")
        # Greeting based on hour.
        hour = now.hour
        if hour < 5:    salute = "Working late,"
        elif hour < 12: salute = "Good morning,"
        elif hour < 17: salute = "Good afternoon,"
        else:           salute = "Good evening,"
        # Display name from secrets / OS.
        name = ""
        try:
            from secrets_store import load_setting
            name = (load_setting("user_name") or "").strip()
            if not name:
                email = (load_setting("user_email") or "").strip()
                name = email.split("@")[0] if email else ""
        except Exception:
            pass
        if not name:
            name = os.environ.get("USERNAME") or "there"
        self._home_h1.setText(f"{salute} {name}.")
        # Sub-line — real counts.
        live, heal, total = self._connector_counts()
        skills_n = self._skills_count()
        spend = self._spend_label()
        self._home_sub.setText(
            f"{live}/{total} connectors live · {heal} self-healing · "
            f"{skills_n} Skills synced · {spend} spent."
        )
        # Meta line under composer.
        model = self._current_model() or "—"
        lat = self._last_latency_ms() or "—"
        self._home_meta.setText(f"{model} · {lat}")

        # Brand sub-caption (rail).
        self._brand_sub.setText(f"STUDIO · {live} LIVE")

        # Skills grid — top 3 by use (or first 3).
        self._refresh_home_skills()
        # Activity (recent sessions).
        self._refresh_home_activity()
        # Live tasks — connector health states surfaced as tasks.
        self._refresh_home_tasks(heal=heal)

    def _refresh_home_skills(self) -> None:
        layout = self._home_skills_grid_wrap.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        sks = self._cached_skills()
        # Rank by real usage: skills that have been run before float
        # to the top. Pure-placeholder skills (run_count == 0) get
        # quietly demoted so the row always feels earned.
        sks_ranked = sorted(sks,
                             key=lambda s: -int(s.get("run_count", 0) or 0))
        # Only feature skills with at least 1 actual run on Home; the
        # rest live in the full Skills page.
        ranked_used = [s for s in sks_ranked
                       if int(s.get("run_count", 0) or 0) > 0]
        showing = ranked_used[:3] if ranked_used else sks_ranked[:3]
        for s in showing:
            cat = (s.get("category") or s.get("type") or "SKILL").upper()
            name = s.get("name") or s.get("id") or "Untitled"
            runs = f"{s.get('run_count', 0)} runs"
            hosts = s.get("hosts") or []
            layout.addWidget(_skill_card(cat, name, runs, hosts[:3]))
        # Hide the section header + grid when no skills exist at all
        # rather than showing an empty grey box.
        has_any = bool(showing)
        self._home_skills_grid_wrap.setVisible(has_any)
        try:
            self._home_skills_header.setVisible(has_any)
        except Exception:
            pass
        layout.addStretch(1)

    def _refresh_home_activity(self) -> None:
        layout = self._home_activity.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        sessions = self._cached_sessions()
        # Empty state: hide BOTH the section header and the card so we
        # don't show "Pick up where you left off" with nothing under it.
        has_any = bool(sessions)
        self._home_activity.setVisible(has_any)
        try:
            self._home_activity_header.setVisible(has_any)
        except Exception:
            pass
        if not sessions:
            return
        for i, (path, name, saved_at) in enumerate(sessions[:6]):
            row = QFrame()
            row.setObjectName("studioListRow")
            row.setProperty("first", i == 0)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(SPACE["lg"]-2, SPACE["md"]-2,
                                  SPACE["lg"]-2, SPACE["md"]-2)
            rl.setSpacing(SPACE["md"])
            # Bullet glyph in muted ink.
            bullet = QLabel("◯")
            bullet.setStyleSheet(
                f"color:{T['inkMuted']}; font-size:11px;")
            rl.addWidget(bullet)
            t = QLabel(name)
            t.setObjectName("studioListText")
            rl.addWidget(t, 1)
            # Best-effort host inference from session name.
            host = _guess_host(name)
            if host:
                pill = QLabel(host)
                pill.setObjectName("skillCardBadge")
                color = HOST_PILL_COLOR.get(host.lower(), T["inkSoft"])
                pill.setStyleSheet(
                    f"QLabel#skillCardBadge {{ "
                    f"  font-family:{TYPE['fontMono']}; font-size:9px; "
                    f"  color:{color}; padding:1px 6px; "
                    f"  background:rgba(255,255,255,0.04); "
                    f"  border:1px solid {color}; "
                    f"  border-radius:{RADIUS['xs']}px; }}"
                )
                rl.addWidget(pill)
            when_lbl = QLabel(_short_when(saved_at))
            when_lbl.setObjectName("studioMonoMuted")
            when_lbl.setMinimumWidth(60)
            when_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rl.addWidget(when_lbl)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.mousePressEvent = lambda _e, p=path: self._open_session_path(p)
            layout.addWidget(row)

    def _refresh_home_tasks(self, *, heal: int) -> None:
        """Live tasks list. Suppress the 'every host listener live' noise
        — only show ACTUAL work-in-progress (healing, queued, building).
        When everything is steady, hide the card entirely; the rail's
        host status dots already convey 'all systems live'.
        """
        layout = self._home_tasks.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        try:
            from connector_health import instance as _hi
            snap = _hi().snapshot()
        except Exception:
            snap = {}
        rows = []
        for fam, info in snap.items():
            st = info.get("state", "unknown")
            attempts = info.get("netload_attempts", 0)
            if st == "loaded_dead":
                rows.append(("HEALING",
                             f"Reconnect {fam} (retry {attempts})",
                             min(30 + attempts * 20, 95)))
            elif st == "host_offline" and attempts > 0:
                # Only surface offline hosts the user has tried to use,
                # not every cold connector. Less noise.
                rows.append(("QUEUED",
                             f"{fam} host offline — start app", 0))
        # Collapse both header + card when nothing's in progress.
        has_any = bool(rows)
        self._home_tasks.setVisible(has_any)
        try:
            self._home_tasks_header.setVisible(has_any)
        except Exception:
            pass
        for state, label, pct in rows:
            layout.addWidget(_task_row(state, label, pct))

    def _refresh_telemetry_page(self) -> None:
        # KPI cards first.
        try:
            live, heal, total = self._connector_counts()
            self._tel_kpi_hosts.setProperty("value", f"{live} / {total}")
            # Re-set value via property update path used by _kpi_card.
            v_lbl = self._tel_kpi_hosts.findChild(QLabel, "kpiValue")
            if v_lbl is not None:
                v_lbl.setText(f"{live} / {total}")
            v_lbl2 = self._tel_kpi_heal.findChild(QLabel, "kpiValue")
            if v_lbl2 is not None:
                v_lbl2.setText(str(heal))
            v_lbl3 = self._tel_kpi_spend.findChild(QLabel, "kpiValue")
            if v_lbl3 is not None:
                v_lbl3.setText(self._spend_label())
        except Exception:
            pass
        layout = self._tel_table.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        try:
            from connector_health import instance as _hi
            snap = _hi().snapshot()
        except Exception:
            snap = {}
        if not snap:
            row = QFrame()
            row.setObjectName("studioListRow")
            row.setProperty("first", True)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            empty = QLabel("connector_health daemon not running.")
            empty.setObjectName("studioMonoMuted")
            rl.addWidget(empty)
            layout.addWidget(row)
            return
        for i, (fam, info) in enumerate(snap.items()):
            row = QFrame()
            row.setObjectName("studioListRow")
            row.setProperty("first", i == 0)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            rl.setSpacing(12)
            st = info.get("state", "unknown")
            color = {"live": T["ok"], "loaded_dead": T["warn"],
                     "host_offline": T["inkCap"]}.get(st, T["inkDim"])
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color}; font-size:11px;")
            rl.addWidget(dot)
            n = QLabel(fam)
            n.setObjectName("studioListText")
            rl.addWidget(n, 1)
            kv = QLabel(f"{st}  ·  attempts {info.get('netload_attempts', 0)}  ·  err {info.get('last_error') or '—'}")
            kv.setObjectName("studioMonoMuted")
            rl.addWidget(kv)
            layout.addWidget(row)

    # ──────────────────────────────────────────────────────────────────
    # Live-data probes (best-effort)
    # ──────────────────────────────────────────────────────────────────
    def _current_model(self) -> str:
        # Try chat widget's model picker first.
        try:
            cw = self.chat_widget
            for attr in ("model_combo", "model_picker", "_model_combo"):
                w = getattr(cw, attr, None)
                if w is not None and hasattr(w, "currentText"):
                    txt = w.currentText()
                    if txt:
                        return txt
        except Exception:
            pass
        # Fall back to settings.
        try:
            from secrets_store import load_setting
            m = load_setting("default_model") or ""
            if m:
                return m
        except Exception:
            pass
        return ""

    def _last_latency_ms(self) -> str:
        try:
            cw = self.chat_widget
            for attr in ("_last_response_ms", "last_response_ms",
                         "_last_latency_ms"):
                v = getattr(cw, attr, None)
                if isinstance(v, (int, float)) and v > 0:
                    return f"{int(v)}ms"
        except Exception:
            pass
        return ""

    def _spend_label(self) -> str:
        # Try telemetry total cost; fall back to "—".
        for attr in ("total_cost_usd", "month_cost_usd", "spend_usd"):
            try:
                import telemetry as _t
                v = getattr(_t, attr, None)
                if callable(v):
                    n = v()
                    if isinstance(n, (int, float)):
                        return f"${n:.2f}"
                elif isinstance(v, (int, float)):
                    return f"${v:.2f}"
            except Exception:
                continue
        # Fall back to settings counter if user logged it.
        try:
            from secrets_store import load_setting
            n = load_setting("month_cost_usd")
            if isinstance(n, (int, float)):
                return f"${n:.2f}"
        except Exception:
            pass
        return "$0.00"

    def _connector_counts(self) -> tuple[int, int, int]:
        """Return (live, heal, total)."""
        live = 0
        heal = 0
        total = 0
        try:
            from connector_health import instance as _hi
            snap = _hi().snapshot()
            total = len(snap)
            for fam, info in snap.items():
                st = info.get("state", "unknown")
                if st == "live":
                    live += 1
                elif st == "loaded_dead":
                    heal += 1
        except Exception:
            pass
        return live, heal, total

    def _skills_count(self) -> int:
        try:
            return len(self._cached_skills())
        except Exception:
            return 0

    # ──────────────────────────────────────────────────────────────────
    def _send_from_home(self) -> None:
        """Take the Home composer text + push it to the chat widget's
        input, then trigger the chat widget's send and switch pages.

        Best-effort: the chat widget exposes `.input` (QLineEdit-ish)
        and `._on_send` (slot). If either is missing we fall back to
        just switching pages so we never trap input.
        """
        text = (self._home_input.text() or "").strip()
        if not text:
            self._set_page("chat")
            try:
                cw = self.chat_widget
                inp = getattr(cw, "input", None)
                if inp is not None and hasattr(inp, "setFocus"):
                    inp.setFocus()
            except Exception:
                pass
            return
        cw = self.chat_widget
        inp = getattr(cw, "input", None)
        try:
            if inp is not None and hasattr(inp, "setText"):
                inp.setText(text)
        except Exception:
            pass
        # Switch to chat first so the user sees the prompt land.
        self._set_page("chat")
        # Clear Home composer + fire send on chat.
        self._home_input.clear()
        try:
            send_slot = getattr(cw, "_on_send", None)
            if callable(send_slot):
                # Defer one tick so the page swap repaints first.
                QTimer.singleShot(50, send_slot)
        except Exception:
            pass

    def _home_attach_sketch(self) -> None:
        """Open a file picker for an image and route it to the chat
        widget's image-pasted handler. Switches to Chat after."""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach sketch",
            filter="Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)",
        )
        if not path:
            return
        cw = self.chat_widget
        handler = getattr(cw, "_on_image_pasted", None)
        if callable(handler):
            try:
                handler(path)
            except Exception:
                pass
        self._set_page("chat")
        try:
            from toast import show_toast
            show_toast(self, f"Attached {Path(path).name}", kind="ok")
        except Exception:
            pass

    def _home_voice(self) -> None:
        """Voice input — hand off to Windows Speech Recognition (Win+H).

        Pragmatic v0.34 implementation: focus the composer input, then
        synthesise Win+H so Windows' native dictation panel opens and
        types into the focused field. Works offline (uses the OS-level
        STT model), no Python audio deps, no microphone lock.

        Falls back to a toast hint on non-Windows or if the keypress
        synthesiser isn't available.
        """
        try:
            self._home_input.setFocus()
        except Exception:
            pass
        import sys as _sys
        if _sys.platform != "win32":
            try:
                from toast import show_toast
                show_toast(self,
                           "Voice dictation needs Windows 10+ — type your prompt instead.",
                           kind="warn")
            except Exception:
                pass
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            # Synthesise Win+H using SendInput (more reliable than
            # keybd_event on modern Windows).
            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002
            VK_LWIN = 0x5B
            VK_H = 0x48

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk",         wintypes.WORD),
                    ("wScan",       wintypes.WORD),
                    ("dwFlags",     wintypes.DWORD),
                    ("time",        wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
                ]

            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]

            class INPUT(ctypes.Structure):
                _anonymous_ = ("u",)
                _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

            def _press(vk: int, up: bool = False) -> None:
                ev = INPUT(
                    type=INPUT_KEYBOARD,
                    u=_INPUT_UNION(ki=KEYBDINPUT(
                        wVk=vk, wScan=0,
                        dwFlags=KEYEVENTF_KEYUP if up else 0,
                        time=0, dwExtraInfo=None,
                    )),
                )
                user32.SendInput(1, ctypes.byref(ev), ctypes.sizeof(INPUT))

            _press(VK_LWIN)
            _press(VK_H)
            _press(VK_H, up=True)
            _press(VK_LWIN, up=True)
            try:
                from toast import show_toast
                show_toast(self,
                           "Speak now — Windows dictation typing into composer.",
                           kind="ok")
            except Exception:
                pass
        except Exception as ex:
            try:
                from toast import show_toast
                show_toast(self,
                           f"Voice dictation failed — {type(ex).__name__}",
                           kind="err")
            except Exception:
                pass

    def _maybe_show_no_llm_banner(self) -> None:
        """If no API keys are configured AND Ollama isn't reachable,
        surface a single toast nudging the user toward Settings —
        otherwise the chat hangs silently the first time they send."""
        try:
            from secrets_store import load_api_key
            keys = [load_api_key(p) for p in
                    ("anthropic", "openai", "google", "openrouter", "relay")]
            has_cloud_key = any(bool(k) for k in keys)
        except Exception:
            has_cloud_key = False
        has_local = False
        try:
            from llm_router import ollama_models
            has_local = bool(ollama_models())
        except Exception:
            has_local = False
        if has_cloud_key or has_local:
            return
        try:
            from toast import show_toast
            show_toast(
                self,
                "No LLM configured. Open Settings → Sign-ins to add a key.",
                kind="warn", duration_ms=6000,
            )
        except Exception:
            pass

    def _open_palette(self) -> None:
        """Open the ⌘K command palette overlay (v0.31)."""
        try:
            from command_palette import CommandPalette
            CommandPalette(shell=self, parent=self).exec()
        except Exception as ex:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Palette failed", f"{type(ex).__name__}: {ex}")

    def _open_add_host(self) -> None:
        """'+ Add' button on the HOSTS rail header — switches the
        centre stack to the Add Host panel (v0.28). The panel itself
        does detection + per-host build with live progress."""
        # Refresh the manager so any newly-installed hosts surface.
        try:
            if self.manager is not None:
                self.manager.refresh()
        except Exception:
            pass
        # If the addhost page exists in the stack, jump to it; otherwise
        # fall back to the legacy onboarding wizard.
        if "addhost" in self.pages:
            self._set_page("addhost")
            try:
                # Refresh per-row state in case manager.refresh changed something.
                p = self.pages["addhost"]
                if hasattr(p, "_refresh_all"):
                    p._refresh_all()
            except Exception:
                pass
            return
        try:
            from onboarding import OnboardingWizard
            OnboardingWizard(router=self.router, manager=self.manager,
                             parent=self).exec()
        except Exception:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Add Host",
                "Add Host panel failed to open. Use Settings → Connectors "
                "or close + reopen ArchHub."
            )

    def resizeEvent(self, ev) -> None:
        """Responsive collapse — rail+inspector hide below narrow widths.

        Above 1100 px: full 3-pane.
        900-1100 px:    inspector hides (rail kept, centre expands).
        Below 900 px:   rail collapses to icons-only (60 px), inspector
                        hidden. User card hidden too.
        """
        super().resizeEvent(ev)
        try:
            w = self.width()
            self.inspector.setVisible(w >= 1100)
            if w < 900:
                self.rail.setFixedWidth(60)
                # Hide labels on rail nav buttons; show only key.
                for nid, btn in self._nav_buttons.items():
                    btn.setText("⌘" + dict(((k, n) for k, _, n in NAV_ITEMS))[nid])
            else:
                self.rail.setFixedWidth(232)
                for nid, btn in self._nav_buttons.items():
                    label = dict(((k, l) for k, l, _ in NAV_ITEMS))[nid]
                    key = dict(((k, n) for k, _, n in NAV_ITEMS))[nid]
                    btn.setText(f"{label}     ⌘{key}")
        except Exception:
            pass

    def _toggle_theme(self) -> None:
        """Light↔dark — graphite, never black (per brand principle 01).

        Two stylesheets to re-apply: the global theme.qss (rebuilt from
        the active palette by theme_builder) which styles ChatWindow
        and the embedded panels, and the studio-shell-specific inline
        QSS which styles the rail / inspector / status rule.
        """
        next_theme = "dark" if active_theme() == "light" else "light"
        set_theme(next_theme)
        global T
        T = current_palette()

        # 1. Global QSS — re-build from theme.qss with new palette so
        # the chat widget + every embedded dialog re-themes too.
        try:
            from PyQt6.QtWidgets import QApplication
            from theme_builder import build_global_qss
            from pathlib import Path as _P
            theme_path = _P(__file__).resolve().parent / "theme.qss"
            QApplication.instance().setStyleSheet(build_global_qss(theme_path))
        except Exception:
            pass

        # 2. Shell-local inline QSS for studio-only selectors.
        self.setStyleSheet(_inline_qss())
        for nid, btn in self._nav_buttons.items():
            btn.setStyleSheet(_nav_style(nid == self._active_page))
        # Force a rebuild of host rows so the toggle/dot colors swap.
        self._last_hosts_sig = ()
        self._refresh_live()
        self._brand_mark.update()
        try:
            self._theme_btn.setText("☾" if active_theme() == "dark" else "☀")
        except Exception:
            pass

        # Rebuild user card so the cog menu's "Switch to ..." label flips.
        try:
            old = self._user_card
            parent_layout = self._user_card_wrap.layout()
            parent_layout.removeWidget(old)
            old.deleteLater()
            self._user_card = self._build_user_card_real()
            parent_layout.addWidget(self._user_card)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────
    def _set_page(self, page_id: str) -> None:
        if page_id not in self.pages:
            return
        self._active_page = page_id
        self.stack.setCurrentWidget(self.pages[page_id])
        for nid, btn in self._nav_buttons.items():
            active = nid == page_id
            btn.setStyleSheet(_nav_style(active))

        # v0.33 — SELECTION section swaps between static KV rows and the
        # live Parameters panel when on Chat.
        try:
            on_chat = (page_id == "chat")
            if on_chat and self._ensure_params_panel():
                self._ins_kv_wrap.setVisible(False)
                self._ins_params_wrap.setVisible(True)
                self._ins_cap.setText("PARAMETERS · LIVE")
                self._ins_title.setText("Session parameters")
            else:
                self._ins_kv_wrap.setVisible(True)
                self._ins_params_wrap.setVisible(False)
                self._ins_cap.setText("SELECTION")
                # Title surfaces the active host when one's connected.
                self._ins_title.setText(self._selection_title())
        except Exception:
            pass

        # Page-aware QUICK ACTIONS list.
        try:
            self._refresh_quick_actions()
        except Exception:
            pass

        self.nav_changed.emit(page_id)

    def _selection_title(self) -> str:
        """Pull the most useful "what's open right now" string we can:

        1. Most recent Revit session's doc title (via revit_broker).
        2. The first ACTIVE connector's display name.
        3. Nothing-selected fallback.
        """
        # Revit doc title from the multi-session broker.
        try:
            import revit_broker
            for s in revit_broker.list_sessions(prune=False):
                if s.healthy and s.doc_title:
                    return s.doc_title
        except Exception:
            pass
        # Active connector display name.
        try:
            if self.manager is not None:
                from manager import ConnectorState
                for e in self.manager.entries:
                    if e.state == ConnectorState.ACTIVE:
                        return e.display_name
        except Exception:
            pass
        return "Nothing selected"

    # ──────────────────────────────────────────────────────────────────
    def show_centered(self) -> None:
        """Restore + centre on primary screen. Same contract as ChatWindow.show_centered.

        Belt-and-suspenders: under pythonw on Windows we sometimes see
        Qt report the window as visible (`isVisible()` True, internal
        widget tree painted) while Win32 keeps WS_VISIBLE off so the
        window never actually appears on the user's desktop. To prevent
        the recurring 'alive but hidden — force-shown' loop, after the
        normal Qt path we directly call Win32 ShowWindow(SW_SHOW) +
        SetForegroundWindow on our HWND. No-op on non-Windows."""
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

        # Win32 force-show. pythonw sometimes leaves WS_VISIBLE off
        # despite Qt's showNormal — this guarantees the window is on
        # screen and foregrounded.
        try:
            import sys as _sys
            if _sys.platform == "win32":
                import win32gui, win32con  # noqa
                hwnd = int(self.winId())
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    # SetForegroundWindow can fail if the calling
                    # thread isn't the foreground one — non-fatal.
                    pass
        except Exception:
            # Win32 fallback failure is non-fatal; Qt's show is enough
            # in most cases. We'd rather log + continue than crash.
            pass


# ---------------------------------------------------------------------------
# Brand widgets — ArchMark + Wordmark per brand.jsx (handoff v0.1)
# ---------------------------------------------------------------------------
class ArchMark(QWidget):
    """ArchHub brand mark — arch with parametric node keystone.

    Direct port of brand.jsx::ArchMark. Renders crisply at any size.
    Reads as a doorway, an arch, an A, and a graph node — all in one mark.
    """
    def __init__(self, size: int = 32, color: str | None = None,
                 mono: bool = False, parent=None):
        super().__init__(parent)
        self._size = size
        self._color = color
        self._mono = mono
        self.setFixedSize(size, size)

    def setSize(self, size: int) -> None:
        self._size = size
        self.setFixedSize(size, size)
        self.update()

    def paintEvent(self, ev) -> None:
        p = current_palette()
        c_main = QColor(p["ink"] if self._mono else (self._color or p["terra"]))
        c_deep = QColor(p["ink"] if self._mono else p["terraDeep"])
        c_paper = QColor(p["paper"])

        s = self._size
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Scale so the painter operates in the brand.jsx 64×64 viewbox.
        painter.scale(s / 64.0, s / 64.0)

        # Arch shoulders + jambs — path "M10 56 V32 a22 22 0 0 1 44 0 V56".
        path = QPainterPath()
        path.moveTo(10, 56)
        path.lineTo(10, 32)
        path.arcTo(10, 10, 44, 44, 180, -180)   # 22-radius semicircle
        path.lineTo(54, 56)
        pen = QPen(c_main)
        pen.setWidthF(4.5)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(pen)
        painter.drawPath(path)

        # Inner reveal — "M18 56 V34 a14 14 0 0 1 28 0 V56".
        inner = QPainterPath()
        inner.moveTo(18, 56)
        inner.lineTo(18, 34)
        inner.arcTo(18, 20, 28, 28, 180, -180)
        inner.lineTo(46, 56)
        pen2 = QPen(c_main)
        pen2.setWidthF(1.3)
        c_inner = QColor(c_main)
        c_inner.setAlphaF(0.45)
        pen2.setColor(c_inner)
        painter.setPen(pen2)
        painter.drawPath(inner)

        # Keystone — node socket. Ring + dot.
        painter.setPen(QPen(c_deep, 2.4))
        painter.setBrush(QBrush(c_paper))
        painter.drawEllipse(QPointF(32, 22), 5.2, 5.2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(c_deep))
        painter.drawEllipse(QPointF(32, 22), 1.8, 1.8)

        # Ground line.
        pen3 = QPen(c_main)
        pen3.setWidthF(1.5)
        pen3.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen3)
        painter.drawLine(6, 58, 58, 58)


class Wordmark(QWidget):
    """ArchHub wordmark — 'Arch' + italic terra 'Hub'.

    Direct port of brand.jsx::Wordmark. Rendered as inline labels so
    Qt picks up font fallbacks correctly.
    """
    def __init__(self, size: int = 19, dark: bool = False, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        p = current_palette()
        ink_color = p["paper"] if dark else p["ink"]
        terra = p["terra"]
        a = QLabel("Arch")
        a.setStyleSheet(
            f"font-family:{TYPE['fontSerif']}; "
            f"font-size:{size}px; color:{ink_color}; "
            f"letter-spacing:-0.02em; font-weight:400;"
        )
        h.addWidget(a)
        b = QLabel("Hub")
        b.setStyleSheet(
            f"font-family:{TYPE['fontSerif']}; "
            f"font-size:{size}px; color:{terra}; "
            f"letter-spacing:-0.02em; font-style:italic;"
        )
        h.addWidget(b)
        h.addStretch(1)


# ---------------------------------------------------------------------------
# Helper widgets / styles
# ---------------------------------------------------------------------------
def _section_label(text: str) -> QFrame:
    w, _ = _section_label_with_label(text)
    return w


def _section_label_with_label(text: str) -> tuple[QFrame, QLabel]:
    """Section header — returns (frame, label) so callers can update later."""
    w = QFrame()
    h = QHBoxLayout(w)
    h.setContentsMargins(14, 14, 14, 6)
    h.setSpacing(8)
    lbl = QLabel(text)
    lbl.setObjectName("studioMonoCap")
    h.addWidget(lbl)
    rule = QFrame()
    rule.setFrameShape(QFrame.Shape.HLine)
    rule.setStyleSheet(f"background:{T['lineSoft']}; max-height:1px;")
    h.addWidget(rule, 1)
    return w, lbl


def _section_h2(title: str, sub: Optional[str]) -> QWidget:
    return _section_h2_with_action(title, sub, action_label=None,
                                    on_action=None)


def _section_h2_with_action(title: str, sub: Optional[str], *,
                             action_label: Optional[str] = None,
                             on_action=None) -> QWidget:
    """H2 section header with an optional right-aligned action link
    (matches studio.jsx 'BROWSE ALL →' affordance)."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 12, 0, 6)
    h.setSpacing(12)
    t = QLabel(title)
    t.setObjectName("studioH2")
    h.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("studioMonoMuted")
        h.addWidget(s)
    h.addStretch(1)
    if action_label:
        link = QPushButton(action_label)
        link.setObjectName("studioH2Link")
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.setFlat(True)
        if on_action is not None:
            link.clicked.connect(lambda _=False: on_action())
        h.addWidget(link)
    return w


def _thread_row(text: str, when: str, pinned: bool) -> QFrame:
    row = QFrame()
    row.setObjectName("studioThreadRow")
    h = QHBoxLayout(row)
    h.setContentsMargins(9, 5, 9, 5)
    h.setSpacing(7)
    pin = QLabel("★" if pinned else " ")
    pin.setObjectName("studioPinIcon")
    pin.setFixedWidth(10)
    h.addWidget(pin)
    t = QLabel(text)
    t.setObjectName("studioThreadText")
    h.addWidget(t, 1)
    w = QLabel(when)
    w.setObjectName("studioMonoMuted")
    h.addWidget(w)
    return row


HOST_PILL_COLOR = {
    "revit":   "#5b8fb8",   # drafting blue
    "autocad": "#c98a47",   # ochre-tinted amber
    "blender": "#7aaa7e",   # ok green
    "max":     "#8a6acc",
    "3ds max": "#8a6acc",
    "speckle": "#a07ac8",   # purple
    "rhino":   "#c0c0c0",
    "outlook": "#5b9fb8",
}


def _skill_card(cat: str, name: str, runs: str, hosts: list[str],
                stage: str = "") -> QFrame:
    """Skill card matching studio.jsx StudioHome card layout.

    Top row    : tag pill + ★ + runs
    Body       : italic-serif title
    Bottom row : host pills (color-coded by host) + stage hint
    """
    card = QFrame()
    card.setObjectName("skillCard")
    card.setMinimumHeight(140)
    v = QVBoxLayout(card)
    v.setContentsMargins(SPACE["md"], SPACE["md"],
                         SPACE["md"], SPACE["md"])
    v.setSpacing(SPACE["sm"])

    # Top row: tag · star · runs.
    top = QHBoxLayout()
    top.setSpacing(SPACE["xs"]+2)
    c = QLabel(cat)
    c.setObjectName("skillCardTags")
    top.addWidget(c)
    star = QLabel("★")
    star.setObjectName("skillCardStar")
    top.addWidget(star)
    top.addStretch(1)
    r = QLabel(runs)
    r.setObjectName("skillCardStats")
    top.addWidget(r)
    top_w = QWidget(); top_w.setLayout(top)
    v.addWidget(top_w)

    # Body — italic-serif title.
    n = QLabel(name)
    n.setObjectName("skillCardTitle")
    n.setWordWrap(True)
    v.addWidget(n, 1)

    # Bottom row: host pills + stage.
    bot = QHBoxLayout()
    bot.setSpacing(SPACE["xs"]+1)
    for h in hosts:
        if not h:
            continue
        pill = QLabel(str(h))
        pill.setObjectName("skillCardBadge")
        color = HOST_PILL_COLOR.get(str(h).strip().lower(), T["inkSoft"])
        pill.setStyleSheet(
            f"QLabel#skillCardBadge {{ "
            f"  font-family:{TYPE['fontMono']}; font-size:9.5px; "
            f"  color:{color}; padding:2px 7px; "
            f"  background:rgba(255,255,255,0.04); "
            f"  border:1px solid {color}; "
            f"  border-radius:{RADIUS['xs']+1}px; "
            f"  letter-spacing:0.06em; }}"
        )
        bot.addWidget(pill)
    bot.addStretch(1)
    if stage:
        st = QLabel(stage)
        st.setObjectName("studioMonoMuted")
        bot.addWidget(st)
    bot_w = QWidget(); bot_w.setLayout(bot)
    v.addWidget(bot_w)
    return card


def _task_row(state: str, label: str, pct: int) -> QFrame:
    """Live task row — see COMPONENTS doc in design_tokens.py."""
    row = QFrame()
    row.setObjectName("studioListRow")
    h = QHBoxLayout(row)
    h.setContentsMargins(SPACE["lg"]-2, SPACE["md"]-2,
                         SPACE["lg"]-2, SPACE["md"]-2)
    h.setSpacing(SPACE["md"])
    color = {"RUNNING": T["accent"], "HEALING": T["warn"],
             "QUEUED": T["inkCap"]}.get(state, T["inkCap"])
    dot = QLabel("●")
    dot.setStyleSheet(f"color:{color}; font-size:11px;")
    h.addWidget(dot)
    s = QLabel(state)
    s.setObjectName("studioMonoCap")
    s.setMinimumWidth(64)
    h.addWidget(s)
    t = QLabel(label)
    t.setObjectName("studioListText")
    h.addWidget(t, 1)
    pct_lbl = QLabel(f"{pct}%")
    pct_lbl.setObjectName("studioMonoMuted")
    h.addWidget(pct_lbl)
    bar = QFrame()
    bar.setFixedSize(120, 3)
    p = max(min(pct, 100), 0) / 100.0
    rest = T["bgSoft"]
    if p <= 0.0:
        bar.setStyleSheet(f"background: {rest}; border-radius: 1.5px;")
    elif p >= 1.0:
        bar.setStyleSheet(f"background: {color}; border-radius: 1.5px;")
    else:
        bar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {color}, stop:{p:.3f} {color}, "
            f"stop:{p + 0.001:.3f} {rest}, stop:1 {rest}); "
            f"border-radius:1.5px;"
        )
    h.addWidget(bar)
    return row


def _inspector_kv(key: str, value: str) -> tuple[QFrame, QLabel]:
    """Return (row_frame, value_label) — caller updates value_label later."""
    row = QFrame()
    row.setObjectName("studioInspectorRow")
    v = QVBoxLayout(row)
    v.setContentsMargins(12, 10, 12, 10)
    v.setSpacing(2)
    k = QLabel(key.upper())
    k.setObjectName("studioMonoCap")
    v.addWidget(k)
    val = QLabel(value)
    val.setObjectName("studioInspectorValue")
    v.addWidget(val)
    return row, val


class _ToggleSwitch(QWidget):
    """iOS-style switch — 28×16 pill with a 12×12 white knob that
    slides between the off (left) and on (right) positions.

    Was: QToolButton with a flat colored rectangle (no knob). The
    handoff design (studio.jsx::HostToggle) shows a proper sliding-knob
    switch — that's what this widget renders. paintEvent draws the
    track + knob; mousePressEvent flips state and emits `toggled`.
    """
    toggled = pyqtSignal(bool)

    def __init__(self, on: bool = False, parent=None):
        super().__init__(parent)
        self._on = bool(on)
        self._enabled = True
        self.setFixedSize(28, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def isChecked(self) -> bool:
        return self._on

    def setChecked(self, v: bool) -> None:
        if self._on == v:
            return
        self._on = bool(v)
        self.update()

    def setEnabledState(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled
                       else Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self, ev) -> None:
        if not self._enabled:
            return
        self._on = not self._on
        self.update()
        self.toggled.emit(self._on)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QColor(T["accent"] if self._on else T["lineSoft"])
        if not self._enabled:
            c = QColor(track)
            c.setAlphaF(0.4)
            track = c
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(track))
        p.drawRoundedRect(0, 0, 28, 16, 8, 8)
        # Knob.
        knob_x = 14 if self._on else 2
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(knob_x, 2, 12, 12)


class _PulseDot(QLabel):
    """Status dot with quiet-motion pulse animation (brand principle 07).

    Used in the HOSTS rail. Calling `.pulse()` runs a soft scale +
    color settle that lasts ~600ms — no bounce, no overshoot. The
    underlying paint is a Unicode bullet styled by stylesheet, but
    we override paintEvent so we can apply a pulse alpha without
    touching the stylesheet on every frame.
    """
    def __init__(self, color: str, parent=None):
        super().__init__("●", parent)
        self._color = QColor(color)
        self._intensity = 1.0       # 0..1, drives alpha
        self.setStyleSheet(f"color:{color}; font-size:10px;")
        self._anim_group: QSequentialAnimationGroup | None = None

    def setPulseColor(self, color: str) -> None:
        self._color = QColor(color)
        self.setStyleSheet(f"color:{color}; font-size:10px;")

    @pyqtProperty(float)
    def intensity(self) -> float:
        return self._intensity

    @intensity.setter
    def intensity(self, v: float) -> None:
        self._intensity = max(0.0, min(1.0, float(v)))
        c = QColor(self._color)
        c.setAlphaF(0.45 + 0.55 * self._intensity)
        self.setStyleSheet(f"color:{c.name(QColor.NameFormat.HexArgb)}; font-size:10px;")

    def pulse(self) -> None:
        """Run a single quiet pulse: 1.0 → 0.5 → 1.0 over 600 ms.

        Two phases, each 300 ms, OutCubic in / OutCubic out. No
        overshoot. Settles back to full intensity at end.
        """
        if self._anim_group is not None and self._anim_group.state() == QPropertyAnimation.State.Running:
            return
        a1 = QPropertyAnimation(self, b"intensity")
        a1.setDuration(300)
        a1.setStartValue(1.0)
        a1.setEndValue(0.5)
        a1.setEasingCurve(QEasingCurve.Type.OutCubic)
        a2 = QPropertyAnimation(self, b"intensity")
        a2.setDuration(300)
        a2.setStartValue(0.5)
        a2.setEndValue(1.0)
        a2.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QSequentialAnimationGroup(self)
        group.addAnimation(a1)
        group.addAnimation(a2)
        self._anim_group = group
        group.start()


def _outlook_sessions_tooltip() -> str:
    """Format the live Outlook account list for the rail tooltip."""
    try:
        import outlook_broker
        sessions = outlook_broker.list_sessions(prune=False)
    except Exception:
        return "Outlook accounts unavailable."
    if not sessions:
        return "No Outlook accounts."
    lines = ["Outlook accounts:"]
    for s in sessions:
        marker = "●" if s.healthy else "○"
        bits = [f"{marker} {s.doc_title or 'Account'}"]
        if s.smtp_address:
            bits.append(s.smtp_address)
        if s.version:
            bits.append(f"v{s.version}")
        lines.append("  " + " · ".join(bits))
    return "\n".join(lines)


def _revit_sessions_tooltip() -> str:
    """Format the live Revit session list for a tooltip."""
    try:
        import revit_broker
        sessions = revit_broker.list_sessions(prune=False)
    except Exception:
        return "Revit sessions unavailable."
    if not sessions:
        return "No Revit sessions."
    lines = ["Revit sessions:"]
    for s in sessions:
        marker = "●" if s.healthy else "○"
        bits = [f"{marker} pid {s.pid}", f":{s.port}"]
        if s.version:
            bits.append(s.version)
        if s.doc_title:
            bits.append(s.doc_title[:40])
        if s.legacy:
            bits.append("(legacy DLL)")
        lines.append("  " + " · ".join(bits))
    return "\n".join(lines)


def _kpi_card(label: str, value: str, accent_hex: str) -> QFrame:
    """KPI card — caption + big mono numerals on a raised card."""
    card = QFrame()
    card.setObjectName("studioKpiCard")
    v = QVBoxLayout(card)
    v.setContentsMargins(SPACE["lg"], SPACE["md"]+2,
                         SPACE["lg"], SPACE["md"]+2)
    v.setSpacing(SPACE["xs"])
    cap = QLabel(label)
    cap.setObjectName("studioMonoCap")
    v.addWidget(cap)
    val = QLabel(value)
    val.setObjectName("kpiValue")
    val.setStyleSheet(
        f"font-family:{TYPE['fontMono']}; font-size:32px; "
        f"font-weight:500; color:{accent_hex}; "
        f"letter-spacing:-0.02em;"
    )
    v.addWidget(val)
    return card


def _guess_host(text: str) -> str:
    """Best-effort host detection from a session name. Returns "" when
    nothing matches — caller hides the host pill in that case."""
    t = (text or "").lower()
    for host in ("revit", "autocad", "blender", "speckle", "max",
                 "rhino", "outlook"):
        if host in t:
            return host
    return ""


def _short_when(saved_at: str) -> str:
    """Convert ISO timestamp to short relative — 'now' / '12 min' / '1 h' / '2 d' / 'yest'."""
    if not saved_at:
        return ""
    try:
        ts = datetime.fromisoformat(saved_at)
    except Exception:
        try:
            ts = datetime.fromisoformat(saved_at[:19])
        except Exception:
            return saved_at[:10]
    delta = datetime.now() - ts
    secs = delta.total_seconds()
    if secs < 0:
        return "now"
    if secs < 60:
        return "now"
    if secs < 60 * 60:
        return f"{int(secs // 60)} min"
    if secs < 60 * 60 * 24:
        return f"{int(secs // 3600)} h"
    if secs < 60 * 60 * 24 * 2:
        return "yest"
    if secs < 60 * 60 * 24 * 14:
        return f"{int(secs // 86400)} d"
    return ts.strftime("%b %d")


def _nav_style(active: bool) -> str:
    """Nav item style — see COMPONENTS doc in design_tokens.py.

    Default: transparent · inkSoft. Hover: bgHover · ink. Active: bgRaised
    · ink · 1px line border · weight 500. All paddings via SPACE scale.
    """
    if active:
        return (
            f"QPushButton#studioNavItem {{ "
            f"  background:{T['bgRaised']}; color:{T['ink']}; "
            f"  border:1px solid {T['line']}; "
            f"  border-radius:{RADIUS['md']}px; "
            f"  padding:{SPACE['xs']+3}px {SPACE['md']-2}px; "
            f"  text-align:left; "
            f"  font-family:{TYPE['fontSans']}; "
            f"  font-size:{TYPE['body']['size']}px; font-weight:500; "
            f"}}"
        )
    return (
        f"QPushButton#studioNavItem {{ "
        f"  background:transparent; color:{T['inkSoft']}; "
        f"  border:1px solid transparent; "
        f"  border-radius:{RADIUS['md']}px; "
        f"  padding:{SPACE['xs']+3}px {SPACE['md']-2}px; "
        f"  text-align:left; "
        f"  font-family:{TYPE['fontSans']}; "
        f"  font-size:{TYPE['body']['size']}px; "
        f"}} "
        f"QPushButton#studioNavItem:hover {{ background:{T['bgHover']}; color:{T['ink']}; }}"
    )


def _router_row_qss(active: bool) -> str:
    if active:
        return (
            f"QFrame#studioRouterRow {{ "
            f"  background:{T['bgRaised']}; "
            f"  border:1px solid {T['line']}; "
            f"  border-radius:{RADIUS['md']}px; "
            f"}}"
        )
    return (
        f"QFrame#studioRouterRow {{ "
        f"  background:transparent; "
        f"  border:1px solid transparent; "
        f"  border-radius:{RADIUS['md']}px; "
        f"}} "
        f"QFrame#studioRouterRow:hover {{ background:{T['bgHover']}; }}"
    )


def _toggle_style(on: bool) -> str:
    """Toggle pill — accent on, lineSoft off. Visual 24×14, hit area
    relaxed via parent ToolButton padding (handled where row is built).
    """
    bg = T["accent"] if on else T["lineSoft"]
    return (
        f"QToolButton#studioToggle {{ "
        f"  background:{bg}; border:none; "
        f"  border-radius:{RADIUS['xs']+4}px; "
        f"}}"
    )


def _inline_qss() -> str:
    """Inline QSS for studio shell — generated from design tokens.

    Loaded after global theme.qss. Token-driven so any palette change
    in `app/design_tokens.py` propagates everywhere automatically.
    """
    s = SPACE
    r = RADIUS

    # Type record renderer.
    def _type(rec_key: str) -> str:
        rec = TYPE[rec_key]
        return (
            f"font-size:{rec['size']}px; "
            f"font-weight:{rec['weight']}; "
            f"letter-spacing:{rec['tracking']};"
        )

    qss = (
        # ── Bleed kill ──────────────────────────────────────────────
        # Anything inside the shell (centralWidget#studioRoot) has its
        # QLabel + QFrame backgrounds forced transparent so leftover
        # theme.qss rules from the ChatWindow era don't paint stray
        # rectangles behind text. Specific selectors below override
        # with explicit backgrounds where we want them.
        f"QWidget#studioRoot QLabel {{ background:transparent; }}"
        f"QWidget#studioRoot QFrame {{ background:transparent; }}"

        # ── Rail ────────────────────────────────────────────────────
        f"QFrame#studioRail {{ background:{T['bgPanel']}; "
        f"  border-right:1px solid {T['line']}; }}"
        f"QLabel#studioLogo {{ "
        f"  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        f"    stop:0 {T['accent']}, stop:1 {T['accentHi']}); "
        f"  color:#fff; font-family:{TYPE['fontSerif']}; font-style:italic; "
        f"  font-size:18px; border-radius:{r['lg']}px; }}"
        f"QLabel#studioBrand {{ font-family:{TYPE['fontSerif']}; "
        f"  font-style:italic; font-size:19px; color:{T['ink']}; "
        f"  letter-spacing:-0.01em; }}"
        f"QLabel#studioBrandSub {{ font-family:{TYPE['fontMono']}; "
        f"  {_type('monoCap')} color:{T['inkCap']}; }}"
        f"QPushButton#studioCommandBox {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{r['md']+1}px; "
        f"  padding:{s['xs']+3}px {s['md']-2}px; color:{T['inkCap']}; "
        f"  font-family:{TYPE['fontMono']}; {_type('monoBody')} "
        f"  text-align:left; }}"
        f"QPushButton#studioCommandBox:hover {{ "
        f"  background:{T['bgPanel']}; border-color:{T['accent']}; }}"

        # ── Mono captions / muted ───────────────────────────────────
        f"QLabel#studioMonoCap {{ font-family:{TYPE['fontMono']}; "
        f"  {_type('monoCap')} color:{T['inkCap']}; }}"
        f"QLabel#studioMonoMuted {{ font-family:{TYPE['fontMono']}; "
        f"  {_type('monoMuted')} color:{T['inkMuted']}; }}"

        # ── Host + thread rows ──────────────────────────────────────
        f"QFrame#studioHostRow:hover, QFrame#studioThreadRow:hover {{ "
        f"  background:{T['bgHover']}; border-radius:{r['sm']}px; }}"
        f"QLabel#studioHostName {{ {_type('label')} color:{T['ink']}; }}"
        f"QLabel#studioThreadText {{ {_type('bodySm')} color:{T['inkSoft']}; }}"
        f"QLabel#studioPinIcon {{ color:{T['accent']}; font-size:10px; }}"
        # ── Per-session sub-list (HOSTS row expansion) ──────────────
        f"QFrame#studioHostRowWrap {{ background:transparent; }}"
        f"QFrame#studioHostSubList {{ background:transparent; "
        f"  border-left:2px solid {T['line']}; "
        f"  margin-left:{s['md']}px; }}"
        f"QFrame#studioHostSubRow:hover {{ "
        f"  background:{T['bgHover']}; border-radius:{r['sm']}px; }}"
        f"QLabel#studioPinChip {{ "
        f"  font-family:{TYPE['fontMono']}; font-size:10px; "
        f"  color:{T['accent']}; padding:1px 6px; "
        f"  background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; border-radius:{r['sm']}px; }}"

        # ── User card ───────────────────────────────────────────────
        f"QFrame#studioUserCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; border-radius:{r['md']+1}px; }}"
        f"QLabel#studioAvatar {{ background:#d8c5a8; color:#5a4a2a; "
        f"  font-weight:700; font-size:11px; "
        f"  border-radius:{r['md']*2}px; }}"
        f"QLabel#studioUserName {{ {_type('label')} color:{T['ink']}; }}"
        f"QToolButton#studioCog {{ background:transparent; "
        f"  color:{T['inkSoft']}; border:none; "
        f"  font-size:{TYPE['body']['size']}px; "
        f"  padding:0 {s['xs']}px; }}"
        f"QToolButton#studioCog:hover {{ color:{T['accent']}; }}"

        # ── Page typography ─────────────────────────────────────────
        f"QWidget#studioPage, QWidget#studioHomeBody {{ "
        f"  background:{T['bg']}; }}"
        f"QLabel#studioH1 {{ font-family:{TYPE['fontSerif']}; "
        f"  {_type('h1')} color:{T['ink']}; }}"
        f"QLabel#studioH1Sub {{ color:{T['inkSoft']}; "
        f"  {_type('bodyLg')} line-height:1.6; }}"
        f"QLabel#studioTagline {{ font-family:{TYPE['fontSerif']}; "
        f"  font-style:italic; font-size:24px; color:{T['inkSoft']}; "
        f"  letter-spacing:-0.01em; }}"
        f"QFrame#studioAddHostRow {{ background:transparent; "
        f"  border:1px dashed {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; margin:4px 8px; }}"
        f"QFrame#studioAddHostRow:hover {{ "
        f"  border-color:{T['accent']}; "
        f"  background:rgba(217,119,87,0.05); }}"
        f"QLabel#studioAddHostPlus {{ color:{T['accent']}; "
        f"  font-size:14px; font-weight:600; }}"
        f"QLabel#studioAddHostText {{ font-family:{TYPE['fontSans']}; "
        f"  font-size:12.5px; color:{T['inkSoft']}; }}"
        f"QLabel#studioAddHostBadge {{ font-family:{TYPE['fontMono']}; "
        f"  font-size:8.5px; color:{T['accent']}; "
        f"  letter-spacing:0.10em; padding:1px 5px; "
        f"  background:{T['accentSoft']}; "
        f"  border-radius:{RADIUS['xs']}px; }}"
        f"QLabel#studioH2 {{ font-family:{TYPE['fontSerif']}; "
        f"  {_type('h2')} color:{T['ink']}; }}"
        f"QPushButton#studioH2Link {{ background:transparent; "
        f"  border:none; color:{T['inkMuted']}; "
        f"  font-family:{TYPE['fontMono']}; font-size:9.5px; "
        f"  letter-spacing:0.12em; padding:2px 4px; }}"
        f"QPushButton#studioH2Link:hover {{ color:{T['accent']}; }}"

        # ── Composer ────────────────────────────────────────────────
        f"QFrame#studioComposer {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; border-radius:{r['xl']}px; }}"
        f"QLabel#studioComposerPrompt {{ font-family:{TYPE['fontSerif']}; "
        f"  font-style:italic; font-size:22px; color:{T['inkCap']}; "
        f"  letter-spacing:-0.01em; }}"
        f"QLineEdit#studioComposerInput {{ "
        f"  background:transparent; border:none; "
        f"  color:{T['ink']}; "
        f"  font-family:{TYPE['fontSerif']}; "
        f"  font-style:italic; font-size:22px; "
        f"  letter-spacing:-0.01em; padding:2px 0; }}"
        f"QLineEdit#studioComposerInput::placeholder {{ "
        f"  color:{T['inkCap']}; }}"
        f"QPushButton#studioChip {{ background:transparent; "
        f"  color:{T['inkSoft']}; border:1px solid {T['line']}; "
        f"  border-radius:{r['md']}px; padding:{s['xs']}px {s['md']-2}px; "
        f"  font-family:{TYPE['fontSans']}; {_type('monoBody')} }}"
        f"QPushButton#studioChip:hover {{ "
        f"  border-color:{T['accent']}; color:{T['accent']}; }}"

        # ── Skill cards ────────────────────────────────────────────
        f"QFrame#skillCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; border-radius:{r['lg']}px; }}"
        f"QFrame#skillCard:hover {{ border-color:{T['accent']}; }}"
        f"QLabel#skillCardTags {{ font-family:{TYPE['fontMono']}; "
        f"  font-size:9px; color:{T['accent']}; "
        f"  letter-spacing:0.14em; padding:2px 7px; "
        f"  background:{T['accentSoft']}; border-radius:{r['xs']}px; }}"
        f"QLabel#skillCardStar {{ color:{T['warn']}; font-size:11px; }}"
        f"QLabel#skillCardStats {{ font-family:{TYPE['fontMono']}; "
        f"  font-size:10px; color:{T['inkSoft']}; "
        f"  letter-spacing:0.04em; }}"
        f"QLabel#skillCardTitle {{ font-family:{TYPE['fontSerif']}; "
        f"  font-style:italic; font-size:18px; color:{T['ink']}; "
        f"  letter-spacing:-0.01em; }}"

        # ── KPI cards ──────────────────────────────────────────────
        f"QFrame#studioKpiCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{r['lg']}px; }}"
        f"QFrame#studioKpiCard:hover {{ border-color:{T['accent']}; }}"

        # ── List cards (activity, tasks, telemetry) ────────────────
        f"QFrame#studioListCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; border-radius:{r['lg']}px; }}"
        f"QFrame#studioListRow {{ background:transparent; "
        f"  border-top:1px solid {T['lineSoft']}; }}"
        f"QFrame#studioListRow[first='true'] {{ border-top:none; }}"
        f"QFrame#studioListRow:hover {{ background:{T['bgPanel']}; }}"
        f"QLabel#studioListText {{ font-size:13.5px; color:{T['ink']}; }}"

        # ── Inspector ───────────────────────────────────────────────
        f"QFrame#studioInspector {{ background:{T['bgPanel']}; "
        f"  border-left:1px solid {T['line']}; }}"
        f"QWidget#studioInspectorBody {{ background:{T['bgPanel']}; }}"
        f"QLabel#studioInspectorTitle {{ font-family:{TYPE['fontSerif']}; "
        f"  {_type('h2')} color:{T['ink']}; }}"
        f"QFrame#studioInspectorRow {{ background:transparent; "
        f"  border:none; border-bottom:1px solid {T['lineSoft']}; "
        f"  border-radius:0; padding:0; }}"
        f"QLabel#studioInspectorValue {{ font-family:{TYPE['fontMono']}; "
        f"  {_type('monoData')} color:{T['ink']}; }}"

        # ── Router rows ─────────────────────────────────────────────
        f"QFrame#studioRouterRow {{ background:transparent; "
        f"  border:1px solid transparent; border-radius:{r['md']}px; }}"
        f"QFrame#studioRouterRow:hover {{ background:{T['bgHover']}; }}"
        f"QLabel#studioRouterName {{ {_type('label')} color:{T['ink']}; }}"

        # ── Quick actions ──────────────────────────────────────────
        f"QFrame#studioQuickAction {{ background:transparent; "
        f"  border-radius:{r['md']}px; }}"
        f"QFrame#studioQuickAction:hover {{ background:{T['bgHover']}; }}"
        f"QLabel#studioQuickActionChev {{ color:{T['inkMuted']}; "
        f"  font-size:14px; }}"
        f"QLabel#studioQuickActionText {{ {_type('body')} color:{T['ink']}; }}"

        # ── Status rule ─────────────────────────────────────────────
        f"QFrame#studioStatusRule {{ background:{T['bgPanel']}; "
        f"  border-top:1px solid {T['line']}; }}"
        f"QLabel#studioStatusItem {{ font-family:{TYPE['fontMono']}; "
        f"  {_type('monoStat')} color:{T['inkSoft']}; }}"

        # ── Theme toggle (sun/moon) ─────────────────────────────────
        f"QToolButton#studioThemeToggle {{ background:transparent; "
        f"  border:1px solid {T['line']}; border-radius:{r['md']+1}px; "
        f"  color:{T['inkSoft']}; font-size:14px; }}"
        f"QToolButton#studioThemeToggle:hover {{ "
        f"  border-color:{T['accent']}; color:{T['accent']}; }}"
    )

    # ── Focus rings — keyboard a11y ─────────────────────────────────
    qss += focus_ring_qss(
        "QPushButton#studioNavItem",
        "QPushButton#studioCommandBox",
        "QPushButton#studioChip",
        "QToolButton#studioToggle",
        "QToolButton#studioCog",
    )
    return qss
