"""Command palette — ⌘K global search overlay (v0.31).

Studio implementation of the Cockpit-direction palette (handoff
cockpit.jsx). Frameless overlay floats centred over the shell, captures
keystrokes, ranks results across nav · skills · sessions · settings ·
marketplace items.

UX
--
- Open: Ctrl+K (Studio shell binds the QShortcut).
- Search: live ranking across registered providers.
- Up / Down: move selection.
- Enter: invoke the selected item.
- Esc: close.
- Click outside: close.

Each result has:
  category    e.g. "Page" / "Skill" / "Session" / "Action"
  title       primary label
  detail      secondary line
  on_invoke   callable() that performs the action

Providers are registered at construction by `_default_providers()`. Add
new sources there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget,
)

from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


# ---------------------------------------------------------------------------
@dataclass
class PaletteResult:
    category: str
    title: str
    detail: str = ""
    on_invoke: Optional[Callable[[], None]] = None
    score: float = 0.0


def _score(query: str, hay: str) -> float:
    """Rough fuzzy-ish score — not perfect, but good enough for a UI
    that shows ~10 items."""
    if not query:
        return 1.0
    q = query.lower()
    h = hay.lower()
    if q == h:
        return 1.0
    if h.startswith(q):
        return 0.9
    if q in h:
        return 0.7
    # Subsequence match.
    i = 0
    for c in h:
        if i < len(q) and c == q[i]:
            i += 1
    if i == len(q):
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
class CommandPalette(QDialog):
    """Modal frameless overlay. Owned by the StudioShell."""

    def __init__(self, *, shell, parent=None):
        super().__init__(parent or shell)
        self.shell = shell
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)

        # Translucent backdrop wraps a centred card so the rest of the
        # shell shows through but is dimmed.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        backdrop = QFrame()
        backdrop.setObjectName("paletteBackdrop")
        outer.addWidget(backdrop, 1)

        bv = QVBoxLayout(backdrop)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)
        bv.addStretch(1)

        # Centred card.
        card_row = QHBoxLayout()
        card_row.addStretch(1)
        card = QFrame()
        card.setObjectName("paletteCard")
        card.setMaximumWidth(640)
        card.setMinimumWidth(560)
        card.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(SPACE["md"], SPACE["md"],
                               SPACE["md"], SPACE["md"])
        cv.setSpacing(SPACE["sm"])

        cap = QLabel("⌘K  ·  COMMAND PALETTE")
        cap.setObjectName("studioMonoCap")
        cv.addWidget(cap)

        self.input = QLineEdit()
        self.input.setObjectName("paletteInput")
        self.input.setPlaceholderText(
            "Search nav · skills · sessions · settings · marketplace…"
        )
        self.input.textChanged.connect(self._refilter)
        self.input.installEventFilter(self)
        cv.addWidget(self.input)

        self.results_list = QListWidget()
        self.results_list.setObjectName("paletteList")
        self.results_list.setUniformItemSizes(False)
        self.results_list.setSpacing(2)
        self.results_list.itemActivated.connect(self._invoke_current)
        self.results_list.installEventFilter(self)
        cv.addWidget(self.results_list, 1)

        hint = QLabel("↑↓ navigate · ↵ select · Esc close")
        hint.setObjectName("studioMonoMuted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cv.addWidget(hint)

        card_row.addWidget(card)
        card_row.addStretch(1)
        cw = QWidget(); cw.setLayout(card_row)
        bv.addWidget(cw)
        bv.addStretch(2)         # bias card up to ~33% from top

        # Providers — populate on demand each time text changes.
        self._providers = self._default_providers(shell)

        self.setStyleSheet(_palette_qss())
        self._refilter()

    # ------------------------------------------------------------------
    def showEvent(self, ev) -> None:
        # Resize to overlay the shell exactly so the backdrop dim matches.
        try:
            self.resize(self.shell.size())
            self.move(self.shell.geometry().topLeft())
        except Exception:
            pass
        self.input.setFocus()
        self.input.selectAll()
        super().showEvent(ev)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Type.KeyPress:
            assert isinstance(ev, QKeyEvent)
            if ev.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
            if ev.key() == Qt.Key.Key_Down:
                row = self.results_list.currentRow()
                self.results_list.setCurrentRow(
                    min(row + 1, self.results_list.count() - 1))
                return True
            if ev.key() == Qt.Key.Key_Up:
                row = self.results_list.currentRow()
                self.results_list.setCurrentRow(max(row - 1, 0))
                return True
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._invoke_current()
                return True
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------------
    def _refilter(self) -> None:
        q = (self.input.text() or "").strip()
        results: list[PaletteResult] = []
        for prov in self._providers:
            try:
                results.extend(prov(q))
            except Exception:
                continue
        # Score and sort.
        for r in results:
            r.score = max(_score(q, r.title), _score(q, r.detail) * 0.6)
        results = [r for r in results if r.score > 0.0 or not q]
        results.sort(key=lambda r: -r.score)
        results = results[:30]

        self.results_list.clear()
        for r in results:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, r)
            it.setSizeHint(QSize(0, 44))
            self.results_list.addItem(it)
            row_w = self._row_widget(r)
            self.results_list.setItemWidget(it, row_w)
        if results:
            self.results_list.setCurrentRow(0)

    def _row_widget(self, r: PaletteResult) -> QWidget:
        w = QFrame()
        w.setObjectName("paletteRow")
        h = QHBoxLayout(w)
        h.setContentsMargins(SPACE["sm"], SPACE["xs"]+2,
                             SPACE["sm"], SPACE["xs"]+2)
        h.setSpacing(SPACE["sm"])
        cat = QLabel(r.category.upper())
        cat.setObjectName("studioMonoCap")
        cat.setFixedWidth(82)
        h.addWidget(cat)
        col_w = QWidget()
        col = QVBoxLayout(col_w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        title = QLabel(r.title)
        title.setObjectName("paletteRowTitle")
        col.addWidget(title)
        if r.detail:
            detail = QLabel(r.detail)
            detail.setObjectName("studioMonoMuted")
            col.addWidget(detail)
        h.addWidget(col_w, 1)
        return w

    def _invoke_current(self) -> None:
        it = self.results_list.currentItem()
        if it is None:
            return
        r = it.data(Qt.ItemDataRole.UserRole)
        if r is None or not getattr(r, "on_invoke", None):
            return
        try:
            r.on_invoke()
        finally:
            self.accept()

    # ------------------------------------------------------------------
    def _default_providers(self, shell):
        """Each provider is a callable(query: str) → list[PaletteResult].
        We close over `shell` so providers can drive its navigation."""
        # v1.3.2 round-2: rail has been split into primary NAV_ITEMS + a
        # secondary NAV_ITEMS_MORE behind a 'More' disclosure. Palette
        # surfaces every page (NAV_ITEMS_ALL) so users can ⌘K-jump to
        # any page without expanding the disclosure first.
        from studio_shell import NAV_ITEMS_ALL as _NAV

        def nav_provider(_q: str) -> list[PaletteResult]:
            out = []
            for nav_id, label, key in _NAV:
                out.append(PaletteResult(
                    category="Page",
                    title=label,
                    detail=f"⌘{key}",
                    on_invoke=lambda nid=nav_id: shell._set_page(nid),
                ))
            # Add Host page is reachable too.
            out.append(PaletteResult(
                category="Page",
                title="Add Host",
                detail="Detect + build connectors",
                on_invoke=lambda: shell._set_page("addhost"),
            ))
            return out

        def skills_provider(_q: str) -> list[PaletteResult]:
            out: list[PaletteResult] = []
            try:
                from skills.library import list_skills
                for s in (list_skills() or [])[:25]:
                    name = s.get("name") or s.get("id") or ""
                    if not name:
                        continue
                    runs = s.get("run_count", 0)
                    out.append(PaletteResult(
                        category="Skill",
                        title=name,
                        detail=f"{runs} runs",
                        on_invoke=lambda: shell._set_page("skills"),
                    ))
            except Exception:
                pass
            return out

        def sessions_provider(_q: str) -> list[PaletteResult]:
            out: list[PaletteResult] = []
            try:
                from session_io import list_sessions
                for path, name, saved_at in (list_sessions() or [])[:15]:
                    out.append(PaletteResult(
                        category="Session",
                        title=name,
                        detail=saved_at[:10] or "",
                        on_invoke=(lambda p=path: shell._open_session_path(p)),
                    ))
            except Exception:
                pass
            return out

        def actions_provider(_q: str) -> list[PaletteResult]:
            return [
                PaletteResult(
                    category="Action",
                    title="Switch theme (light ↔ dark)",
                    detail="Graphite, never black",
                    on_invoke=lambda: shell._toggle_theme(),
                ),
                PaletteResult(
                    category="Action",
                    title="Refresh detection",
                    detail="Re-scan installed hosts",
                    on_invoke=lambda: (shell.manager.refresh()
                                       if shell.manager is not None else None),
                ),
                PaletteResult(
                    category="Action",
                    title="Open Add Host",
                    detail="Build + activate connectors",
                    on_invoke=lambda: shell._set_page("addhost"),
                ),
            ]

        def marketplace_provider(_q: str) -> list[PaletteResult]:
            out: list[PaletteResult] = []
            try:
                from marketplace_panel import _ensure_catalog
                for item in _ensure_catalog()[:25]:
                    out.append(PaletteResult(
                        category="Market",
                        title=item.get("name", ""),
                        detail=f"{item.get('kind','')} · {item.get('author','')}",
                        on_invoke=lambda: shell._set_page("market"),
                    ))
            except Exception:
                pass
            return out

        return [
            nav_provider, actions_provider,
            skills_provider, sessions_provider, marketplace_provider,
        ]


# ---------------------------------------------------------------------------
def _palette_qss() -> str:
    return (
        f"QFrame#paletteBackdrop {{ background: rgba(0, 0, 0, 0.45); }}"
        f"QFrame#paletteCard {{ background:{T['bgPanel']}; "
        f"  border:1px solid {T['line']}; border-radius:{RADIUS['xl']}px; "
        f"}}"
        f"QLineEdit#paletteInput {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; "
        f"  padding:8px 12px; color:{T['ink']}; "
        f"  font-family:{TYPE['fontSans']}; font-size:14px; }}"
        f"QLineEdit#paletteInput:focus {{ border-color:{T['accent']}; }}"
        f"QListWidget#paletteList {{ background:transparent; "
        f"  border:none; outline:none; }}"
        f"QListWidget#paletteList::item {{ background:transparent; "
        f"  border-radius:{RADIUS['md']}px; padding:0; }}"
        f"QListWidget#paletteList::item:selected {{ "
        f"  background:{T['bgHover']}; }}"
        f"QFrame#paletteRow {{ background:transparent; }}"
        f"QLabel#paletteRowTitle {{ color:{T['ink']}; "
        f"  font-family:{TYPE['fontSans']}; font-size:13px; }}"
    )
