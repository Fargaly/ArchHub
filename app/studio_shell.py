"""Studio shell — 3-pane chrome from Claude Design handoff (Direction D).

Layout (matches studio.jsx):

    ┌──────────┬─────────────────────────┬──────────┐
    │  rail    │  main view              │ inspector│
    │  232px   │  flex                   │  304px   │
    │          │                         │          │
    │  brand   │  (Home / Chat / Skills/ │ Params / │
    │  ⌘K box  │   Flows / Market /      │ host info│
    │  nav     │   Telemetry / Settings) │          │
    │  HOSTS   │                         │          │
    │  THREADS │                         │          │
    │  user    │                         │          │
    ├──────────┴─────────────────────────┴──────────┤
    │  status rule  (26px · mono telemetry)         │
    └───────────────────────────────────────────────┘

Wraps the existing ChatWindow in the centre 'chat' page. Other pages
are first-pass placeholders that match the design's visual language —
they'll be filled in piece by piece (Marketplace, Settings sections,
Parameters sidebar with live sliders, ⌘K palette).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
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
            "skills":    self._build_placeholder("Skills",   "Browse + run saved workflows."),
            "flows":     self._build_placeholder("Workflows", "Node canvas — coming next PR."),
            "market":    self._build_placeholder("Marketplace", "Workflows + Skills · official + community."),
            "telemetry": self._build_placeholder("Telemetry", "Live tasks · finance · cohort metrics."),
            "settings":  self._build_placeholder("Settings",  "General · Projects · API keys · Connectors · Billing."),
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

        # Global shortcuts: 1..6 = nav, ⌘K to focus the palette stub.
        for nav_id, _, key in NAV_ITEMS:
            sc = QShortcut(QKeySequence(f"Ctrl+{key}"), self)
            sc.activated.connect(lambda _id=nav_id: self._set_page(_id))

    # ──────────────────────────────────────────────────────────────────
    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("studioRail")
        rail.setFixedWidth(232)

        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Brand row
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(14, 14, 14, 10)
        brand_row.setSpacing(10)
        logo = QLabel("a")
        logo.setObjectName("studioLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(30, 30)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        title = QLabel("ArchHub")
        title.setObjectName("studioBrand")
        sub = QLabel("STUDIO · TOWER A")
        sub.setObjectName("studioBrandSub")
        brand_col.addWidget(title)
        brand_col.addWidget(sub)
        brand_row.addLayout(brand_col, 1)
        brand_wrap = QWidget()
        brand_wrap.setLayout(brand_row)
        # Insert logo first
        brand_row.insertWidget(0, logo)
        v.addWidget(brand_wrap)

        # ⌘K command box
        ck = QPushButton("Ask, search, run skill…  ⌘K")
        ck.setObjectName("studioCommandBox")
        ck.setCursor(Qt.CursorShape.PointingHandCursor)
        ck_wrap = QWidget()
        ck_l = QVBoxLayout(ck_wrap)
        ck_l.setContentsMargins(12, 2, 12, 12)
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
            btn.setProperty("active", False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_nav_style(False))
            btn.clicked.connect(lambda _=False, _id=nav_id: self._set_page(_id))
            self._nav_buttons[nav_id] = btn
            nav_l.addWidget(btn)
        v.addWidget(nav_wrap)

        # HOSTS section
        v.addWidget(_section_label("HOSTS · 5"))
        hosts_wrap = QWidget()
        hl = QVBoxLayout(hosts_wrap)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(1)
        for name, status, port in [
            ("Revit",    "connected",    ":48884"),
            ("Blender",  "connected",    ":9876"),
            ("AutoCAD",  "reconnecting", "↻ heal"),
            ("3ds Max",  "idle",         "idle"),
            ("Speckle",  "connected",    "cloud"),
        ]:
            hl.addWidget(_host_row(name, status, port))
        v.addWidget(hosts_wrap)

        # THREADS section
        v.addWidget(_section_label("THREADS"))
        th_wrap = QWidget()
        th_l = QVBoxLayout(th_wrap)
        th_l.setContentsMargins(8, 0, 8, 0)
        th_l.setSpacing(0)
        for title_text, when, pinned in [
            ("Tower A — schedule wall types",     "now",    True),
            ("Convert sketch to 6m gabled mass",  "12 min", False),
            ("Why are doors flipping?",           "1 h",    False),
            ("Site massing → Speckle stream",     "yest",   False),
            ("Camera rig — 12 angles",            "2 d",    False),
        ]:
            th_l.addWidget(_thread_row(title_text, when, pinned))
        v.addWidget(th_wrap, 1)        # stretch fills space

        # User card
        user_wrap = QWidget()
        ul = QVBoxLayout(user_wrap)
        ul.setContentsMargins(8, 8, 8, 8)
        ul.addWidget(_user_card())
        v.addWidget(user_wrap)

        return rail

    # ──────────────────────────────────────────────────────────────────
    def _wrap_chat(self, chat_widget: QWidget) -> QWidget:
        """Wrap the existing ChatWindow's central widget so it lives
        inside the Studio shell instead of as its own QMainWindow."""
        wrap = QWidget()
        l = QVBoxLayout(wrap)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        # Pull the central widget OUT of the ChatWindow's layout
        # so we can re-parent it. We'll keep `chat_widget` (ChatWindow
        # itself) hidden as a no-op shell — its instance methods still
        # back the chat callbacks.
        try:
            inner = chat_widget.centralWidget()
            if inner is not None:
                inner.setParent(wrap)
                l.addWidget(inner)
        except Exception:
            l.addWidget(QLabel("Chat widget unavailable."))

        return wrap

    # ──────────────────────────────────────────────────────────────────
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

        date_lbl = QLabel("TUE · MAY 7 · 14:32")
        date_lbl.setObjectName("studioMonoCap")
        wl.addWidget(date_lbl)

        h = QLabel("Good afternoon, Fargaly.")
        h.setObjectName("studioH1")
        wl.addWidget(h)

        sub = QLabel("4 connectors live · 1 self-healing · 47 Skills synced · $47.82 spent this month.")
        sub.setObjectName("studioH1Sub")
        wl.addWidget(sub)

        # Composer card
        composer = QFrame()
        composer.setObjectName("studioComposer")
        cl = QVBoxLayout(composer)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        prompt = QLabel("Dimension all walls in the active view…")
        prompt.setObjectName("studioComposerPrompt")
        cl.addWidget(prompt)
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        for c in ("✦ Sketch", "● Voice", "@ Skill", "+ Host"):
            b = QPushButton(c)
            b.setObjectName("studioChip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            chip_row.addWidget(b)
        chip_row.addStretch(1)
        meta = QLabel("claude-sonnet-4.5 · ~420ms")
        meta.setObjectName("studioMonoMuted")
        chip_row.addWidget(meta)
        send = QPushButton("Send  ➤")
        send.setObjectName("primaryButton")
        send.clicked.connect(lambda: self._set_page("chat"))
        chip_row.addWidget(send)
        cl.addLayout(chip_row)
        wl.addWidget(composer)

        # Section: Suggested skills
        wl.addWidget(_section_h2("Suggested for what's open", "Tower-A_central.rvt"))
        grid = QHBoxLayout()
        grid.setSpacing(10)
        for cat, name, runs, hosts in [
            ("PIPELINE", "Sketch → Production", "47 runs", ["Revit", "Blender", "Speckle"]),
            ("ANNOTATE", "Dimension walls in view", "312 runs", ["Revit"]),
            ("PIPELINE", "Construction Doc Sprint", "18 runs", ["Revit"]),
        ]:
            grid.addWidget(_skill_card(cat, name, runs, hosts))
        grid_w = QWidget(); grid_w.setLayout(grid)
        wl.addWidget(grid_w)

        # Section: Activity
        wl.addWidget(_section_h2("Pick up where you left off", None))
        activity = QFrame()
        activity.setObjectName("studioListCard")
        al = QVBoxLayout(activity)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        for i, (text, host, when) in enumerate([
            ("Tower A — schedule wall types",    "revit",   "now"),
            ("Convert sketch to 6m gabled mass", "blender", "12 min"),
            ("Why are doors flipping?",          "revit",   "1 h"),
            ("Site massing → Speckle stream",    "speckle", "yesterday"),
        ]):
            row = QFrame()
            row.setObjectName("studioListRow")
            row.setProperty("first", i == 0)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            rl.setSpacing(12)
            rl.addWidget(QLabel("◆"))
            t = QLabel(text)
            t.setObjectName("studioListText")
            rl.addWidget(t, 1)
            host_pill = QLabel(host)
            host_pill.setObjectName("studioMonoPill")
            rl.addWidget(host_pill)
            when_lbl = QLabel(when)
            when_lbl.setObjectName("studioMonoMuted")
            when_lbl.setMinimumWidth(60)
            when_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rl.addWidget(when_lbl)
            al.addWidget(row)
        wl.addWidget(activity)

        # Section: Live tasks
        wl.addWidget(_section_h2("Live tasks", "self-healing in real time"))
        tasks = QFrame()
        tasks.setObjectName("studioListCard")
        tl = QVBoxLayout(tasks)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        for i, (state, label, pct) in enumerate([
            ("RUNNING", "Auto-update connector DLL",       64),
            ("RUNNING", "Sync Skills repo (28 files)",     92),
            ("HEALING", "Reconnect AutoCAD (retry 2)",     30),
            ("QUEUED",  "Index Speckle commits",            0),
        ]):
            tl.addWidget(_task_row(state, label, pct))
        wl.addWidget(tasks)

        wl.addStretch(1)
        scroll.setWidget(wrap)

        page_l = QVBoxLayout(page)
        page_l.setContentsMargins(0, 0, 0, 0)
        page_l.addWidget(scroll)
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
        s = QLabel(sub + "\n\nThis page is the next PR — design is locked, implementation queued.")
        s.setObjectName("studioH1Sub")
        s.setWordWrap(True)
        l.addWidget(s)
        l.addStretch(1)
        return page

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
        title = QLabel("Tower A — Floor 03")
        title.setObjectName("studioInspectorTitle")
        v.addWidget(title)

        v.addWidget(_inspector_kv("Active host", "Revit 2025"))
        v.addWidget(_inspector_kv("File",        "Tower-A_central.rvt"))
        v.addWidget(_inspector_kv("Selection",   "47 walls"))
        v.addWidget(_inspector_kv("LLM",         "claude-sonnet-4.5"))
        v.addWidget(_inspector_kv("Latency",     "~420ms"))

        v.addStretch(1)
        return ins

    # ──────────────────────────────────────────────────────────────────
    def _build_status_rule(self) -> QFrame:
        rule = QFrame()
        rule.setObjectName("studioStatusRule")
        rule.setFixedHeight(26)
        h = QHBoxLayout(rule)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(14)
        items = [
            "● 4 LIVE  ↻ 1 HEAL",
            "MODEL  claude-sonnet-4.5",
            "LAT  420ms",
            "SPEND  $47.82 / $200",
        ]
        for txt in items:
            lbl = QLabel(txt)
            lbl.setObjectName("studioStatusItem")
            h.addWidget(lbl)
        h.addStretch(1)
        right = QLabel("⌘K  PALETTE     ⌘,  SETTINGS")
        right.setObjectName("studioStatusItem")
        h.addWidget(right)
        return rule

    # ──────────────────────────────────────────────────────────────────
    def _set_page(self, page_id: str) -> None:
        if page_id not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[page_id])
        for nid, btn in self._nav_buttons.items():
            active = nid == page_id
            btn.setProperty("active", active)
            btn.setStyleSheet(_nav_style(active))
        self.nav_changed.emit(page_id)

    # ──────────────────────────────────────────────────────────────────
    def show_centered(self) -> None:
        """Restore + centre on primary screen. Same contract as ChatWindow.show_centered."""
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


# ---------------------------------------------------------------------------
# Small helper widgets
# ---------------------------------------------------------------------------
def _section_label(text: str) -> QWidget:
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
    return w


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


def _host_row(name: str, status: str, port: str) -> QFrame:
    row = QFrame()
    row.setObjectName("studioHostRow")
    h = QHBoxLayout(row)
    h.setContentsMargins(9, 5, 9, 5)
    h.setSpacing(8)
    dot = QLabel("●")
    color = {"connected": "#5a8a5e", "reconnecting": "#c08533",
             "idle": "#9a9183", "off": "#ece6d8"}.get(status, "#b8493e")
    dot.setStyleSheet(f"color:{color}; font-size: 10px;")
    h.addWidget(dot)
    n = QLabel(name)
    n.setObjectName("studioHostName")
    h.addWidget(n, 1)
    p = QLabel(port)
    p.setObjectName("studioMonoMuted")
    h.addWidget(p)
    # Toggle switch (visual only — wires later to manager.activate)
    tog = QToolButton()
    tog.setCheckable(True)
    tog.setChecked(status != "off" and status != "idle")
    tog.setObjectName("studioToggle")
    tog.setFixedSize(24, 14)
    tog.setStyleSheet(_toggle_style(tog.isChecked()))
    def _flip(checked, b=tog):
        b.setStyleSheet(_toggle_style(checked))
    tog.toggled.connect(_flip)
    h.addWidget(tog)
    return row


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
    t.setWordWrap(False)
    h.addWidget(t, 1)
    w = QLabel(when)
    w.setObjectName("studioMonoMuted")
    h.addWidget(w)
    return row


def _user_card() -> QFrame:
    card = QFrame()
    card.setObjectName("studioUserCard")
    h = QHBoxLayout(card)
    h.setContentsMargins(10, 7, 10, 7)
    h.setSpacing(9)
    av = QLabel("F")
    av.setObjectName("studioAvatar")
    av.setAlignment(Qt.AlignmentFlag.AlignCenter)
    av.setFixedSize(24, 24)
    h.addWidget(av)
    col = QVBoxLayout()
    col.setSpacing(0)
    name = QLabel("Fargaly")
    name.setObjectName("studioUserName")
    tier = QLabel("BYO · PRO")
    tier.setObjectName("studioMonoCap")
    col.addWidget(name)
    col.addWidget(tier)
    col_w = QWidget(); col_w.setLayout(col)
    h.addWidget(col_w, 1)
    cog = QLabel("⚙")
    cog.setObjectName("studioInkSoft")
    h.addWidget(cog)
    return card


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
        p = QLabel(h)
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
    color = {"RUNNING": "#c96442", "HEALING": "#c08533", "QUEUED": "#9a9183"}[state]
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
    bar.setStyleSheet(
        f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {color}, stop:{max(pct/100,0.001):.3f} {color}, "
        f"stop:{max(pct/100,0.001) + 0.001:.3f} #efeae0, stop:1 #efeae0); "
        f"border-radius:1.5px;"
    )
    h.addWidget(bar)
    return row


def _inspector_kv(key: str, value: str) -> QFrame:
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
    return row


# ---------------------------------------------------------------------------
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
    knob_left = "10px" if on else "1px"
    return (
        f"QToolButton#studioToggle {{ background:{bg}; border:none; border-radius:7px; }} "
        f"QToolButton#studioToggle::after {{ content:''; }}"
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
        "QLabel#studioMonoPill { font-family:'JetBrains Mono','Cascadia Mono',monospace; "
        "  font-size:10.5px; color:#6b6256; padding:1px 6px; "
        "  background:rgba(0,0,0,0.04); border-radius:3px; }"

        # Hosts / threads / user card
        "QFrame#studioHostRow:hover, QFrame#studioThreadRow:hover { background:#ebe6db; }"
        "QLabel#studioHostName { font-size:12.5px; color:#251f17; }"
        "QLabel#studioThreadText { font-size:12px; color:#6b6256; }"
        "QLabel#studioPinIcon { color:#c96442; font-size:10px; }"

        "QFrame#studioUserCard { background:#ffffff; border:1px solid #e3ddd0; border-radius:7px; }"
        "QLabel#studioAvatar { background:#d8c5a8; color:#5a4a2a; font-weight:700; "
        "  font-size:11px; border-radius:12px; }"
        "QLabel#studioUserName { font-size:12.5px; color:#251f17; font-weight:500; }"
        "QLabel#studioInkSoft { color:#6b6256; font-size:13px; }"

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

        # List cards (activity, tasks)
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
