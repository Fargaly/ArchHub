"""Skills grid — Studio-native card grid for the Skills library.

Replaces the legacy SkillsPanel (a QDialog) embedded into the centre
column of the shell. Same data source — `skills.library.list_skills()`
— but rendered as a proper Studio page that matches the Marketplace
visual language: header with caption + h1 + filter, 3-column card
grid, host-coloured pills, italic-serif titles.

Run / edit / delete actions live on each card. Run wires into the
existing skills.matcher → ToolEngine path through the chat widget so
the Skill executes the same way it would from a chat command.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


HOST_PILL_COLOR = {
    "revit":   "#5b8fb8",
    "autocad": "#c98a47",
    "blender": "#7aaa7e",
    "max":     "#8a6acc",
    "3ds max": "#8a6acc",
    "speckle": "#a07ac8",
    "rhino":   "#c0c0c0",
    "outlook": "#5b9fb8",
}


class SkillCard(QFrame):
    """One skill card — tag · ★ runs · italic title · host pills · Run."""
    run_requested = pyqtSignal(dict)

    def __init__(self, skill: dict, parent=None):
        super().__init__(parent)
        self.skill = skill
        self.setObjectName("skillsGridCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE["md"], SPACE["md"],
                             SPACE["md"], SPACE["md"])
        v.setSpacing(SPACE["sm"])

        # Top row.
        top = QHBoxLayout()
        top.setSpacing(SPACE["xs"]+2)
        cat = (skill.get("category") or skill.get("type") or "SKILL").upper()
        ct = QLabel(cat)
        ct.setObjectName("skillsGridTag")
        top.addWidget(ct)
        runs = int(skill.get("run_count", 0) or 0)
        if runs > 0:
            star = QLabel("★")
            star.setObjectName("skillsGridStar")
            top.addWidget(star)
        top.addStretch(1)
        rl = QLabel(f"{runs} runs")
        rl.setObjectName("skillsGridStats")
        top.addWidget(rl)
        top_w = QWidget(); top_w.setLayout(top)
        v.addWidget(top_w)

        # Title.
        name = skill.get("name") or skill.get("id") or "Untitled"
        title = QLabel(name)
        title.setObjectName("skillsGridTitle")
        title.setWordWrap(True)
        v.addWidget(title)

        # Description.
        desc = skill.get("description") or ""
        if desc:
            d = QLabel(desc)
            d.setObjectName("skillsGridDesc")
            d.setWordWrap(True)
            v.addWidget(d)

        v.addStretch(1)

        # Bottom: host pills + Run button.
        bot = QHBoxLayout()
        bot.setSpacing(SPACE["xs"]+1)
        for h in (skill.get("hosts") or [])[:3]:
            if not h:
                continue
            pill = QLabel(str(h))
            pill.setObjectName("skillsGridBadge")
            color = HOST_PILL_COLOR.get(str(h).strip().lower(), T["inkSoft"])
            pill.setStyleSheet(
                f"QLabel#skillsGridBadge {{ "
                f"  font-family:{TYPE['fontMono']}; font-size:9.5px; "
                f"  color:{color}; padding:2px 7px; "
                f"  background:rgba(255,255,255,0.04); "
                f"  border:1px solid {color}; "
                f"  border-radius:{RADIUS['xs']+1}px; "
                f"  letter-spacing:0.06em; }}"
            )
            bot.addWidget(pill)
        bot.addStretch(1)
        run_btn = QPushButton("Run")
        run_btn.setObjectName("skillsGridRun")
        run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        run_btn.clicked.connect(lambda: self.run_requested.emit(self.skill))
        bot.addWidget(run_btn)
        bot_w = QWidget(); bot_w.setLayout(bot)
        v.addWidget(bot_w)


class SkillsGridPanel(QWidget):
    def __init__(self, *, router=None, tools=None, manager=None,
                 chat_widget=None, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPage")
        self.router = router
        self.tools = tools
        self.manager = manager
        self.chat_widget = chat_widget

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header.
        head = QWidget()
        hh = QVBoxLayout(head)
        hh.setContentsMargins(40, 32, 40, 12)
        hh.setSpacing(4)
        cap = QLabel("SKILLS · LIBRARY")
        cap.setObjectName("studioMonoCap")
        hh.addWidget(cap)
        h1 = QLabel("Skills")
        h1.setObjectName("studioH1")
        hh.addWidget(h1)
        sub = QLabel("Your saved Skills. Run any of them from here, "
                      "or build a new one from a chat session.")
        sub.setObjectName("studioH1Sub")
        sub.setWordWrap(True)
        hh.addWidget(sub)
        outer.addWidget(head)

        # Toolbar.
        tb = QHBoxLayout()
        tb.setContentsMargins(40, 0, 40, SPACE["md"])
        tb.setSpacing(SPACE["sm"])
        self.search = QLineEdit()
        self.search.setObjectName("skillsSearch")
        self.search.setPlaceholderText("Filter by name · tag · host…")
        self.search.setFixedWidth(320)
        self.search.textChanged.connect(self._refresh)
        tb.addWidget(self.search)
        tb.addStretch(1)
        self.btn_browse = QPushButton("Browse marketplace →")
        self.btn_browse.setObjectName("studioH2Link")
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.clicked.connect(self._open_market)
        tb.addWidget(self.btn_browse)
        tb_w = QWidget(); tb_w.setLayout(tb)
        outer.addWidget(tb_w)

        # Card grid.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setObjectName("studioScroll")
        scroll.setStyleSheet(
            "QScrollArea#studioScroll { background:transparent; border:none; }")
        body = QWidget()
        body.setObjectName("studioPage")
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(40, 0, 40, 40)
        self.grid.setHorizontalSpacing(SPACE["md"])
        self.grid.setVerticalSpacing(SPACE["md"])
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.setStyleSheet(_panel_qss())
        self._refresh()

    def _open_market(self) -> None:
        win = self.window()
        try:
            win._set_page("market")
        except Exception:
            pass

    def _refresh(self) -> None:
        # Clear grid.
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        try:
            from skills.library import list_skills
            sks = list_skills() or []
        except Exception:
            sks = []
        q = (self.search.text() or "").strip().lower()
        if q:
            def hay(s: dict) -> str:
                return " ".join([
                    s.get("name", ""),
                    s.get("description", ""),
                    " ".join(s.get("tags", []) or []),
                    " ".join(s.get("hosts", []) or []),
                ]).lower()
            sks = [s for s in sks if q in hay(s)]
        # Rank by usage.
        sks.sort(key=lambda s: -int(s.get("run_count", 0) or 0))
        if not sks:
            empty = QLabel(
                "No Skills match your filter."
                if q else
                "No saved Skills yet — chat with ArchHub and use "
                "'Save as Skill' to add one to your library.")
            empty.setObjectName("studioMonoMuted")
            empty.setWordWrap(True)
            self.grid.addWidget(empty, 0, 0, 1, 3)
            return
        for i, s in enumerate(sks):
            r, c = divmod(i, 3)
            card = SkillCard(s)
            card.run_requested.connect(self._run_skill)
            self.grid.addWidget(card, r, c)

    def _run_skill(self, skill: dict) -> None:
        # Best-effort: tell the chat widget to load this Skill if it
        # exposes a runner; otherwise pop a message.
        cw = self.chat_widget
        runner = getattr(cw, "run_skill", None)
        if callable(runner):
            try:
                runner(skill)
                return
            except Exception as ex:
                QMessageBox.warning(self, "Run failed", str(ex))
                return
        QMessageBox.information(
            self, "Run skill",
            f"Open Chat and type:  /skills run {skill.get('id', '')}")


def _panel_qss() -> str:
    return (
        f"QFrame#skillsGridCard {{ "
        f"  background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['lg']}px; "
        f"  min-height: 180px; }}"
        f"QFrame#skillsGridCard:hover {{ border-color:{T['accent']}; }}"
        f"QLabel#skillsGridTag {{ font-family:{TYPE['fontMono']}; "
        f"  font-size:9px; color:{T['accent']}; "
        f"  letter-spacing:0.14em; padding:2px 7px; "
        f"  background:{T['accentSoft']}; "
        f"  border-radius:{RADIUS['xs']}px; }}"
        f"QLabel#skillsGridStar {{ color:{T['warn']}; font-size:11px; }}"
        f"QLabel#skillsGridStats {{ font-family:{TYPE['fontMono']}; "
        f"  font-size:10px; color:{T['inkSoft']}; "
        f"  letter-spacing:0.04em; }}"
        f"QLabel#skillsGridTitle {{ font-family:{TYPE['fontSerif']}; "
        f"  font-style:italic; font-size:18px; color:{T['ink']}; "
        f"  letter-spacing:-0.01em; }}"
        f"QLabel#skillsGridDesc {{ font-family:{TYPE['fontSans']}; "
        f"  font-size:12px; color:{T['inkSoft']}; line-height:1.5; }}"
        f"QLineEdit#skillsSearch {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; "
        f"  padding:5px 10px; color:{T['ink']}; "
        f"  font-family:{TYPE['fontMono']}; font-size:11.5px; }}"
        f"QPushButton#skillsGridRun {{ background:{T['accent']}; "
        f"  color:#fff; border:none; "
        f"  border-radius:{RADIUS['md']}px; "
        f"  padding:5px 14px; font-family:{TYPE['fontSans']}; "
        f"  font-size:11.5px; font-weight:500; }}"
        f"QPushButton#skillsGridRun:hover {{ background:{T['accentHi']}; }}"
    )
