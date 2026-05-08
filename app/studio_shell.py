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

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)


# Studio palette (light, matches theme.qss tokens)
T = {
    "bg":          "#f7f4ee",
    "bgPanel":     "#fbf9f4",
    "bgSoft":      "#efeae0",
    "bgHover":     "#ebe6db",
    "ink":         "#251f17",
    "inkSoft":     "#6b6256",
    "inkMuted":    "#9a9183",
    "line":        "#e3ddd0",
    "lineSoft":    "#ece6d8",
    "accent":      "#c96442",
    "accentSoft":  "#f5e3db",
    "ok":          "#5a8a5e",
    "warn":        "#c08533",
    "err":         "#b8493e",
    "selBg":       "#ffffff",
}

NAV_ITEMS = [
    ("home",      "Home",        "1"),
    ("chat",      "Chat",        "2"),
    ("skills",    "Skills",      "3"),
    ("flows",     "Workflows",   "4"),
    ("market",    "Marketplace", "5"),
    ("telemetry", "Telemetry",   "6"),
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

        self.router = router
        self.manager = manager
        self.tools = tools
        self.chat_widget = chat_widget

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
            "market":    self._build_placeholder("Marketplace", "Workflows + Skills · official + community."),
            "telemetry": self._build_telemetry_page(),
            "settings":  self._build_settings_page(),
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

        # Live refresh — 2s tick rebuilds rail + status + inspector + home.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2000)
        self._refresh_timer.timeout.connect(self._refresh_live)
        self._refresh_timer.start()
        # First refresh immediately so we don't show stale fake values.
        QTimer.singleShot(50, self._refresh_live)

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

        # Brand row
        brand_wrap = QWidget()
        brand_row = QHBoxLayout(brand_wrap)
        brand_row.setContentsMargins(14, 14, 14, 10)
        brand_row.setSpacing(10)
        logo = QLabel("a")
        logo.setObjectName("studioLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(30, 30)
        brand_row.addWidget(logo)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        title = QLabel("ArchHub")
        title.setObjectName("studioBrand")
        self._brand_sub = QLabel("STUDIO · BOOTING")
        self._brand_sub.setObjectName("studioBrandSub")
        brand_col.addWidget(title)
        brand_col.addWidget(self._brand_sub)
        brand_row.addLayout(brand_col, 1)
        v.addWidget(brand_wrap)

        # ⌘K command box (placeholder — palette overlay deferred)
        ck_wrap = QWidget()
        ck_l = QVBoxLayout(ck_wrap)
        ck_l.setContentsMargins(12, 2, 12, 12)
        ck = QPushButton("Ask, search, run skill…  ⌘K")
        ck.setObjectName("studioCommandBox")
        ck.setCursor(Qt.CursorShape.PointingHandCursor)
        ck.clicked.connect(lambda: self._set_page("chat"))
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

        # THREADS section — content rebuilt by _refresh_threads.
        v.addWidget(_section_label("THREADS"))
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

        self._home_sub = QLabel("")
        self._home_sub.setObjectName("studioH1Sub")
        self._home_sub.setWordWrap(True)
        wl.addWidget(self._home_sub)

        # Composer card
        composer = QFrame()
        composer.setObjectName("studioComposer")
        cl = QVBoxLayout(composer)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        prompt = QLabel("Ask anything — type below in Chat.")
        prompt.setObjectName("studioComposerPrompt")
        cl.addWidget(prompt)
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        for c in ("✦ Sketch", "● Voice", "@ Skill", "+ Host"):
            b = QPushButton(c)
            b.setObjectName("studioChip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False: self._set_page("chat"))
            chip_row.addWidget(b)
        chip_row.addStretch(1)
        self._home_meta = QLabel("…")
        self._home_meta.setObjectName("studioMonoMuted")
        chip_row.addWidget(self._home_meta)
        send = QPushButton("Open chat  ➤")
        send.setObjectName("primaryButton")
        send.clicked.connect(lambda: self._set_page("chat"))
        chip_row.addWidget(send)
        cl.addLayout(chip_row)
        wl.addWidget(composer)

        # Suggested skills (built from real Skills library).
        wl.addWidget(_section_h2("Suggested Skills", "from your library"))
        self._home_skills_grid_wrap = QWidget()
        self._home_skills_grid_wrap.setLayout(QHBoxLayout())
        self._home_skills_grid_wrap.layout().setSpacing(10)
        self._home_skills_grid_wrap.layout().setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self._home_skills_grid_wrap)

        # Pick up where you left off — real recent sessions.
        wl.addWidget(_section_h2("Pick up where you left off", None))
        self._home_activity = QFrame()
        self._home_activity.setObjectName("studioListCard")
        self._home_activity.setLayout(QVBoxLayout())
        self._home_activity.layout().setContentsMargins(0, 0, 0, 0)
        self._home_activity.layout().setSpacing(0)
        wl.addWidget(self._home_activity)

        # Live tasks
        wl.addWidget(_section_h2("Live tasks", "self-healing in real time"))
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
        page = QWidget()
        page.setObjectName("studioPage")
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        try:
            from skills_panel import SkillsPanel
            panel = SkillsPanel(self.router, self.tools,
                                self.manager, parent=None)
            # SkillsPanel is a QDialog; flatten so it renders inline.
            panel.setWindowFlags(Qt.WindowType.Widget)
            l.addWidget(panel)
        except Exception as ex:
            l.addWidget(self._error_card("Skills", str(ex)))
        return page

    def _build_workflows_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studioPage")
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        try:
            from workflows_panel import WorkflowsPanel
            panel = WorkflowsPanel(self.router, self.tools,
                                   self.manager, parent=None)
            panel.setWindowFlags(Qt.WindowType.Widget)
            l.addWidget(panel)
        except Exception as ex:
            l.addWidget(self._error_card("Workflows", str(ex)))
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studioPage")
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        try:
            from settings_dialog import SettingsDialog
            dlg = SettingsDialog(self.router, parent=None)
            dlg.setWindowFlags(Qt.WindowType.Widget)
            l.addWidget(dlg)
        except Exception as ex:
            l.addWidget(self._error_card("Settings", str(ex)))
        return page

    def _build_telemetry_page(self) -> QWidget:
        """Telemetry — show connector_health snapshot + recent events."""
        page = QWidget()
        page.setObjectName("studioPage")
        l = QVBoxLayout(page)
        l.setContentsMargins(40, 40, 40, 40)
        l.setSpacing(8)
        cap = QLabel("TELEMETRY")
        cap.setObjectName("studioMonoCap")
        l.addWidget(cap)
        h = QLabel("Live connector health")
        h.setObjectName("studioH1")
        l.addWidget(h)
        self._tel_table = QFrame()
        self._tel_table.setObjectName("studioListCard")
        self._tel_table.setLayout(QVBoxLayout())
        self._tel_table.layout().setContentsMargins(0, 0, 0, 0)
        self._tel_table.layout().setSpacing(0)
        l.addWidget(self._tel_table)
        l.addStretch(1)
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
        ins = QFrame()
        ins.setObjectName("studioInspector")
        ins.setFixedWidth(304)
        v = QVBoxLayout(ins)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(10)

        cap = QLabel("CONTEXT")
        cap.setObjectName("studioMonoCap")
        v.addWidget(cap)
        self._ins_title = QLabel("ArchHub — Studio")
        self._ins_title.setObjectName("studioInspectorTitle")
        v.addWidget(self._ins_title)

        # Five KV rows; values updated by _refresh_inspector.
        self._ins_rows: dict[str, QLabel] = {}
        for key in ("Active host", "Connectors", "Skills", "Model", "Latency"):
            row, value_lbl = _inspector_kv(key, "…")
            v.addWidget(row)
            self._ins_rows[key] = value_lbl

        v.addStretch(1)
        return ins

    # ──────────────────────────────────────────────────────────────────
    # Status rule
    # ──────────────────────────────────────────────────────────────────
    def _build_status_rule(self) -> QFrame:
        rule = QFrame()
        rule.setObjectName("studioStatusRule")
        rule.setFixedHeight(26)
        h = QHBoxLayout(rule)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(14)
        self._sr_health = QLabel("● 0 LIVE  ↻ 0 HEAL")
        self._sr_health.setObjectName("studioStatusItem")
        h.addWidget(self._sr_health)
        self._sr_model = QLabel("MODEL  …")
        self._sr_model.setObjectName("studioStatusItem")
        h.addWidget(self._sr_model)
        self._sr_lat = QLabel("LAT  —")
        self._sr_lat.setObjectName("studioStatusItem")
        h.addWidget(self._sr_lat)
        self._sr_spend = QLabel("SPEND  —")
        self._sr_spend.setObjectName("studioStatusItem")
        h.addWidget(self._sr_spend)
        h.addStretch(1)
        right = QLabel("⌘K  PALETTE     ⌘,  SETTINGS")
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
        cog.clicked.connect(lambda: self._set_page("settings"))
        h.addWidget(cog)
        return card

    # ──────────────────────────────────────────────────────────────────
    # Live refresh
    # ──────────────────────────────────────────────────────────────────
    def _refresh_live(self) -> None:
        try:
            self._refresh_hosts()
        except Exception:
            pass
        try:
            self._refresh_threads()
        except Exception:
            pass
        try:
            self._refresh_status_rule()
        except Exception:
            pass
        try:
            self._refresh_inspector()
        except Exception:
            pass
        try:
            self._refresh_home()
        except Exception:
            pass
        try:
            self._refresh_telemetry_page()
        except Exception:
            pass

    def _refresh_hosts(self) -> None:
        if self.manager is None:
            return
        # Sample current entries.
        entries = list(self.manager.entries)
        self._hosts_count_lbl.setText(f"HOSTS · {len(entries)}")
        layout = self._hosts_container.layout()
        # Clear existing rows.
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        # Health snapshot once.
        try:
            from connector_health import instance as _hi
            health = _hi()
        except Exception:
            health = None

        for e in entries:
            row = self._make_host_row(e, health)
            layout.addWidget(row)

    def _make_host_row(self, entry, health) -> QFrame:
        row = QFrame()
        row.setObjectName("studioHostRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(9, 5, 9, 5)
        h.setSpacing(8)

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
        # Color rule: live=green; loaded_dead/unknown when active=warn;
        # host_offline=muted; inactive=muted; unavailable=muted-dim.
        if state_str == "live":
            color = "#5a8a5e"
        elif state_str == "loaded_dead":
            color = "#c08533"
        elif state_str == "host_offline":
            color = "#9a9183"
        else:
            color = "#9a9183" if active else "#cdc6b8"
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size: 10px;")
        h.addWidget(dot)

        n = QLabel(entry.display_name)
        n.setObjectName("studioHostName")
        h.addWidget(n, 1)

        # Detail: port if known, else short status word.
        port = FAMILY_PORT.get(family, "")
        if state_str == "live":
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
        h.addWidget(p)

        # Toggle.
        tog = QToolButton()
        tog.setCheckable(True)
        tog.setChecked(active)
        tog.setEnabled(not unavailable)
        tog.setObjectName("studioToggle")
        tog.setFixedSize(24, 14)
        tog.setStyleSheet(_toggle_style(active))
        # Use a closure that captures the entry.id.
        def on_toggled(checked, entry_id=entry.id, btn=tog):
            try:
                if checked:
                    ok, msg = self.manager.activate(entry_id)
                else:
                    ok, msg = self.manager.deactivate(entry_id)
                if not ok:
                    # Revert visual state and surface the failure in the row.
                    btn.blockSignals(True)
                    btn.setChecked(not checked)
                    btn.setStyleSheet(_toggle_style(btn.isChecked()))
                    btn.blockSignals(False)
                    p.setText("err")
                    p.setToolTip(msg)
                else:
                    btn.setStyleSheet(_toggle_style(checked))
                # Force a fresh refresh so the row reflects the new state.
                QTimer.singleShot(200, self._refresh_hosts)
            except Exception as ex:
                p.setText("err")
                p.setToolTip(str(ex))
        tog.toggled.connect(on_toggled)
        h.addWidget(tog)
        return row

    def _refresh_threads(self) -> None:
        layout = self._threads_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        try:
            from session_io import list_sessions
            sessions = list_sessions()
        except Exception:
            sessions = []
        if not sessions:
            empty = QLabel("  No saved sessions yet.")
            empty.setObjectName("studioMonoMuted")
            layout.addWidget(empty)
            return
        for path, name, saved_at in sessions[:8]:
            when = _short_when(saved_at)
            row = _thread_row(name or path.stem, when, pinned=False)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.mousePressEvent = lambda _e, p=path: self._open_session_path(p)
            layout.addWidget(row)

    def _open_session_path(self, path: Path) -> None:
        # Switch to chat page, then ask the chat widget to load.
        self._set_page("chat")
        try:
            from session_io import load_session
            new_session, name = load_session(path)
            if hasattr(self.chat_widget, "session"):
                self.chat_widget.session = new_session
            if hasattr(self.chat_widget, "parameters_panel"):
                try:
                    self.chat_widget.parameters_panel.set_session(new_session)
                except Exception:
                    pass
        except Exception:
            pass

    def _refresh_status_rule(self) -> None:
        live = 0
        heal = 0
        try:
            from connector_health import instance as _hi
            snap = _hi().snapshot()
            for fam, info in snap.items():
                st = info.get("state", "unknown")
                if st == "live":
                    live += 1
                elif st == "loaded_dead":
                    heal += 1
        except Exception:
            pass
        self._sr_health.setText(f"● {live} LIVE  ↻ {heal} HEAL")

        # Model — try chat widget's combo box or default model setting.
        model = self._current_model() or "—"
        self._sr_model.setText(f"MODEL  {model}")

        # Latency — read last_response_ms off chat_widget if exposed.
        lat = self._last_latency_ms()
        self._sr_lat.setText(f"LAT  {lat}" if lat else "LAT  —")

        # Spend — read settings counter if telemetry tracks it.
        spend = self._spend_label()
        self._sr_spend.setText(f"SPEND  {spend}")

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
        try:
            from skills.library import list_skills
            sks = list_skills() or []
        except Exception:
            sks = []
        for s in sks[:3]:
            cat = (s.get("category") or s.get("type") or "SKILL").upper()
            name = s.get("name") or s.get("id") or "Untitled"
            runs = f"{s.get('run_count', 0)} runs"
            hosts = s.get("hosts") or []
            layout.addWidget(_skill_card(cat, name, runs, hosts[:3]))
        if not sks:
            empty = QLabel("No Skills in your library yet — run /skills to seed.")
            empty.setObjectName("studioMonoMuted")
            layout.addWidget(empty)
        layout.addStretch(1)

    def _refresh_home_activity(self) -> None:
        layout = self._home_activity.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        try:
            from session_io import list_sessions
            sessions = list_sessions()
        except Exception:
            sessions = []
        if not sessions:
            row = QFrame()
            row.setObjectName("studioListRow")
            row.setProperty("first", True)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            empty = QLabel("No sessions yet — open Chat and ask anything.")
            empty.setObjectName("studioMonoMuted")
            rl.addWidget(empty)
            layout.addWidget(row)
            return
        for i, (path, name, saved_at) in enumerate(sessions[:6]):
            row = QFrame()
            row.setObjectName("studioListRow")
            row.setProperty("first", i == 0)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            rl.setSpacing(12)
            rl.addWidget(QLabel("◆"))
            t = QLabel(name)
            t.setObjectName("studioListText")
            rl.addWidget(t, 1)
            when_lbl = QLabel(_short_when(saved_at))
            when_lbl.setObjectName("studioMonoMuted")
            when_lbl.setMinimumWidth(60)
            when_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rl.addWidget(when_lbl)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.mousePressEvent = lambda _e, p=path: self._open_session_path(p)
            layout.addWidget(row)

    def _refresh_home_tasks(self, *, heal: int) -> None:
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
                rows.append(("HEALING", f"Reconnect {fam} (retry {attempts})", min(30 + attempts*20, 95)))
            elif st == "host_offline":
                rows.append(("QUEUED", f"{fam} host offline — start app", 0))
            elif st == "live":
                rows.append(("RUNNING", f"{fam} listener live", 100))
        if not rows:
            row = QFrame()
            row.setObjectName("studioListRow")
            row.setProperty("first", True)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            empty = QLabel("No active tasks. All systems idle.")
            empty.setObjectName("studioMonoMuted")
            rl.addWidget(empty)
            layout.addWidget(row)
            return
        for state, label, pct in rows:
            layout.addWidget(_task_row(state, label, pct))

    def _refresh_telemetry_page(self) -> None:
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
            color = {"live": "#5a8a5e", "loaded_dead": "#c08533",
                     "host_offline": "#9a9183"}.get(st, "#cdc6b8")
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
            from skills.library import list_skills
            return len(list_skills() or [])
        except Exception:
            return 0

    # ──────────────────────────────────────────────────────────────────
    def _set_page(self, page_id: str) -> None:
        if page_id not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[page_id])
        for nid, btn in self._nav_buttons.items():
            active = nid == page_id
            btn.setStyleSheet(_nav_style(active))
        self.nav_changed.emit(page_id)

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
    rule.setStyleSheet("background:#ece6d8; max-height:1px;")
    h.addWidget(rule, 1)
    return w, lbl


def _section_h2(title: str, sub: Optional[str]) -> QWidget:
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


def _skill_card(cat: str, name: str, runs: str, hosts: list[str]) -> QFrame:
    card = QFrame()
    card.setObjectName("skillCard")
    v = QVBoxLayout(card)
    v.setContentsMargins(12, 12, 12, 12)
    v.setSpacing(8)
    top = QHBoxLayout()
    top.setSpacing(6)
    c = QLabel(cat)
    c.setObjectName("skillCardTags")
    top.addWidget(c)
    top.addStretch(1)
    r = QLabel(runs)
    r.setObjectName("skillCardStats")
    top.addWidget(r)
    top_w = QWidget(); top_w.setLayout(top)
    v.addWidget(top_w)
    n = QLabel(name)
    n.setObjectName("skillCardTitle")
    n.setWordWrap(True)
    v.addWidget(n)
    bot = QHBoxLayout()
    bot.setSpacing(5)
    for h in hosts:
        p = QLabel(str(h))
        p.setObjectName("skillCardBadge")
        bot.addWidget(p)
    bot.addStretch(1)
    bot_w = QWidget(); bot_w.setLayout(bot)
    v.addWidget(bot_w)
    return card


def _task_row(state: str, label: str, pct: int) -> QFrame:
    row = QFrame()
    row.setObjectName("studioListRow")
    h = QHBoxLayout(row)
    h.setContentsMargins(14, 10, 14, 10)
    h.setSpacing(12)
    color = {"RUNNING": "#c96442", "HEALING": "#c08533",
             "QUEUED": "#9a9183"}.get(state, "#9a9183")
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
    if p <= 0.0:
        bar.setStyleSheet("background: #efeae0; border-radius: 1.5px;")
    elif p >= 1.0:
        bar.setStyleSheet(f"background: {color}; border-radius: 1.5px;")
    else:
        bar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {color}, stop:{p:.3f} {color}, "
            f"stop:{p + 0.001:.3f} #efeae0, stop:1 #efeae0); "
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
    if active:
        return (
            "QPushButton#studioNavItem { "
            "  background:#ffffff; color:#251f17; border:1px solid #e3ddd0; "
            "  border-radius:6px; padding:7px 10px; text-align:left; "
            "  font-family:'Inter',sans-serif; font-size:13px; font-weight:500; "
            "}"
        )
    return (
        "QPushButton#studioNavItem { "
        "  background:transparent; color:#6b6256; border:1px solid transparent; "
        "  border-radius:6px; padding:7px 10px; text-align:left; "
        "  font-family:'Inter',sans-serif; font-size:13px; "
        "} "
        "QPushButton#studioNavItem:hover { background:#ebe6db; color:#251f17; }"
    )


def _toggle_style(on: bool) -> str:
    bg = "#c96442" if on else "#ece6d8"
    return (
        f"QToolButton#studioToggle {{ background:{bg}; border:none; border-radius:7px; }}"
    )


def _inline_qss() -> str:
    """Inline QSS specific to studio shell. Loaded after global theme.qss."""
    return (
        # Rail
        "QFrame#studioRail { background:#fbf9f4; border-right:1px solid #e3ddd0; }"
        "QLabel#studioLogo { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #c96442,stop:1 #8a3a25); "
        "  color:#fff; font-family:'Instrument Serif','Lora',serif; font-style:italic; "
        "  font-size:18px; border-radius:8px; }"
        "QLabel#studioBrand { font-family:'Instrument Serif','Lora','Georgia',serif; "
        "  font-style:italic; font-size:19px; color:#251f17; letter-spacing:-0.01em; }"
        "QLabel#studioBrandSub { font-family:'JetBrains Mono','Cascadia Mono',monospace; "
        "  font-size:9.5px; color:#9a9183; letter-spacing:0.12em; }"
        "QPushButton#studioCommandBox { background:#fff; border:1px solid #e3ddd0; "
        "  border-radius:7px; padding:7px 10px; color:#9a9183; "
        "  font-family:'JetBrains Mono','Cascadia Mono',monospace; font-size:11.5px; "
        "  text-align:left; letter-spacing:0.04em; }"
        "QPushButton#studioCommandBox:hover { background:#fbf9f4; border-color:#c96442; }"

        # Mono caps + monospace muted
        "QLabel#studioMonoCap { font-family:'JetBrains Mono','Cascadia Mono',monospace; "
        "  font-size:9.5px; color:#9a9183; letter-spacing:0.12em; }"
        "QLabel#studioMonoMuted { font-family:'JetBrains Mono','Cascadia Mono',monospace; "
        "  font-size:10.5px; color:#9a9183; letter-spacing:0.04em; }"

        # Hosts / threads / user card
        "QFrame#studioHostRow:hover, QFrame#studioThreadRow:hover { background:#ebe6db; border-radius:5px; }"
        "QLabel#studioHostName { font-size:12.5px; color:#251f17; }"
        "QLabel#studioThreadText { font-size:12px; color:#6b6256; }"
        "QLabel#studioPinIcon { color:#c96442; font-size:10px; }"

        "QFrame#studioUserCard { background:#ffffff; border:1px solid #e3ddd0; border-radius:7px; }"
        "QLabel#studioAvatar { background:#d8c5a8; color:#5a4a2a; font-weight:700; "
        "  font-size:11px; border-radius:12px; }"
        "QLabel#studioUserName { font-size:12.5px; color:#251f17; font-weight:500; }"
        "QToolButton#studioCog { background:transparent; color:#6b6256; border:none; "
        "  font-size:13px; padding:0 4px; }"
        "QToolButton#studioCog:hover { color:#c96442; }"

        # Page typography
        "QWidget#studioPage, QWidget#studioHomeBody { background:#f7f4ee; }"
        "QLabel#studioH1 { font-family:'Instrument Serif','Lora','Georgia',serif; "
        "  font-size:40px; color:#251f17; letter-spacing:-0.02em; font-weight:400; }"
        "QLabel#studioH1Sub { color:#6b6256; font-size:14px; line-height:1.6; }"
        "QLabel#studioH2 { font-family:'Instrument Serif','Lora','Georgia',serif; "
        "  font-size:21px; color:#251f17; letter-spacing:-0.01em; font-weight:400; }"

        # Composer
        "QFrame#studioComposer { background:#ffffff; border:1px solid #e3ddd0; "
        "  border-radius:10px; }"
        "QLabel#studioComposerPrompt { font-family:'Instrument Serif','Lora',serif; "
        "  font-style:italic; font-size:22px; color:#9a9183; letter-spacing:-0.01em; }"
        "QPushButton#studioChip { background:transparent; color:#6b6256; "
        "  border:1px solid #e3ddd0; border-radius:6px; padding:4px 10px; "
        "  font-family:'Inter',sans-serif; font-size:11.5px; }"
        "QPushButton#studioChip:hover { border-color:#c96442; color:#c96442; }"

        # List cards (activity, tasks, telemetry)
        "QFrame#studioListCard { background:#ffffff; border:1px solid #e3ddd0; "
        "  border-radius:8px; }"
        "QFrame#studioListRow { background:transparent; border-top:1px solid #ece6d8; }"
        "QFrame#studioListRow[first='true'] { border-top:none; }"
        "QFrame#studioListRow:hover { background:#fbf9f4; }"
        "QLabel#studioListText { font-size:13.5px; color:#251f17; }"

        # Inspector
        "QFrame#studioInspector { background:#fbf9f4; border-left:1px solid #e3ddd0; }"
        "QLabel#studioInspectorTitle { font-family:'Instrument Serif','Lora',serif; "
        "  font-size:21px; color:#251f17; letter-spacing:-0.01em; }"
        "QFrame#studioInspectorRow { background:#ffffff; border:1px solid #e3ddd0; "
        "  border-radius:8px; }"
        "QLabel#studioInspectorValue { font-family:'JetBrains Mono','Cascadia Mono',monospace; "
        "  font-size:12px; color:#251f17; letter-spacing:0.02em; }"

        # Status rule
        "QFrame#studioStatusRule { background:#fbf9f4; border-top:1px solid #e3ddd0; }"
        "QLabel#studioStatusItem { font-family:'JetBrains Mono','Cascadia Mono',monospace; "
        "  font-size:10px; color:#6b6256; letter-spacing:0.10em; }"
    )
