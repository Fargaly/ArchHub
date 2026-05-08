"""Marketplace — install Skills + Workflows from the official catalog.

v0.30 ships with a *local* seed catalog so the panel works offline. The
catalog lives in `payload/marketplace/catalog.json` (created lazily if
absent). A future PR adds a remote manifest fetch backed by the
existing `cloud_sync` plumbing.

Each item in the catalog has the shape:

    {
        "kind": "skill" | "workflow",
        "id":   "official.dimension_walls",
        "name": "Dimension walls in active view",
        "author": "ArchHub",
        "tags": ["revit", "annotate"],
        "hosts": ["Revit"],
        "description": "Adds dimensions to every wall in the current view.",
        "runs":  312,
        "version": "0.1.0",
        "payload": { ... full Skill/Workflow JSON ... }
    }

Install action
--------------
- Skill  → writes payload via `skills.library.add_skill(payload)`.
- Workflow → writes payload via `workflows.save_workflow(Workflow.from_dict(...))`.

UI
--
- Two tab-like buttons (Skills · Workflows) gate which catalog rows show.
- Search box (live filter) — name / tag / host / description match.
- Card grid: 3 columns of cards with brand-coherent styling (mono caps,
  italic-serif titles, terra accent on action button).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


PAYLOAD_DIR = Path(__file__).resolve().parent.parent / "payload" / "marketplace"
CATALOG_PATH = PAYLOAD_DIR / "catalog.json"


# Seed catalog — written to disk on first run if no catalog exists. Keeps
# the panel functional with zero network calls.
_SEED_CATALOG = [
    {
        "kind": "skill",
        "id": "official.dimension_walls",
        "name": "Dimension walls in active view",
        "author": "ArchHub",
        "tags": ["revit", "annotate"],
        "hosts": ["Revit"],
        "description": "Adds linear dimensions to every wall in the active "
                       "view. Skips walls already dimensioned.",
        "runs": 312,
        "version": "0.1.0",
        "payload": {
            "id": "official.dimension_walls",
            "name": "Dimension walls in active view",
            "tags": ["revit", "annotate"],
            "hosts": ["Revit"],
            "type": "skill",
        },
    },
    {
        "kind": "skill",
        "id": "official.production_sheets",
        "name": "Production sheets — A101/A102/A103",
        "author": "ArchHub",
        "tags": ["revit", "production"],
        "hosts": ["Revit"],
        "description": "Generates floor-plan + section + elevation sheets "
                       "with a standard Tower-A title block.",
        "runs": 47,
        "version": "0.1.0",
        "payload": {
            "id": "official.production_sheets",
            "name": "Production sheets — A101/A102/A103",
            "tags": ["revit", "production"],
            "hosts": ["Revit"],
            "type": "skill",
        },
    },
    {
        "kind": "skill",
        "id": "official.sketch_to_mass",
        "name": "Sketch → 6m gabled mass",
        "author": "ArchHub",
        "tags": ["blender", "vision"],
        "hosts": ["Blender"],
        "description": "Reads a hand-sketched roof outline and produces a "
                       "6 m gabled mass in Blender.",
        "runs": 18,
        "version": "0.1.0",
        "payload": {
            "id": "official.sketch_to_mass",
            "name": "Sketch → 6m gabled mass",
            "tags": ["blender", "vision"],
            "hosts": ["Blender"],
            "type": "skill",
        },
    },
    {
        "kind": "workflow",
        "id": "official.sketch_to_production",
        "name": "Sketch → Production pipeline",
        "author": "ArchHub",
        "tags": ["pipeline", "revit", "blender", "speckle"],
        "hosts": ["Blender", "Revit", "Speckle"],
        "description": "End-to-end: sketch in → mass extracted → "
                       "Speckle stream → Revit walls → production sheets.",
        "runs": 47,
        "version": "0.1.0",
        "payload": {
            "id": "official.sketch_to_production",
            "name": "Sketch → Production pipeline",
            "nodes": [],
            "edges": [],
        },
    },
    {
        "kind": "workflow",
        "id": "official.constructions_doc_sprint",
        "name": "Construction Doc Sprint",
        "author": "ArchHub",
        "tags": ["pipeline", "revit"],
        "hosts": ["Revit"],
        "description": "Eight-step construction document set generation "
                       "with self-checking dimension audits.",
        "runs": 18,
        "version": "0.1.0",
        "payload": {
            "id": "official.constructions_doc_sprint",
            "name": "Construction Doc Sprint",
            "nodes": [],
            "edges": [],
        },
    },
]


def _ensure_catalog() -> list[dict]:
    """Load catalog from disk; seed if absent. Best-effort."""
    try:
        if CATALOG_PATH.exists():
            return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)
        CATALOG_PATH.write_text(
            json.dumps(_SEED_CATALOG, indent=2), encoding="utf-8")
    except Exception:
        pass
    return list(_SEED_CATALOG)


def fetch_remote_catalog() -> tuple[bool, str, list[dict]]:
    """Pull the official catalog from the cloud_sync registry repo.

    The remote manifest lives at `marketplace/catalog.json` inside the
    user's signed-in Skills git remote (same repo `cloud_sync` already
    uses for Skill share). When found, the local catalog is rewritten
    with the merged item list (remote items first, then any local-only
    items not present in the remote).

    Returns (ok, message, catalog).
    """
    try:
        import cloud_sync
        if not cloud_sync.is_signed_in():
            return False, "Not signed in — local seed only.", _ensure_catalog()
    except Exception as ex:
        return False, f"cloud_sync unavailable — {type(ex).__name__}", _ensure_catalog()
    try:
        # cloud_sync exposes read_remote_file via its bootstrap path.
        repo = getattr(cloud_sync, "_LOCAL_REPO_PATH", None) or getattr(
            cloud_sync, "LOCAL_REPO_PATH", None)
        if repo is None:
            return False, "cloud_sync repo path missing.", _ensure_catalog()
        remote_path = Path(repo) / "marketplace" / "catalog.json"
        try:
            cloud_sync.pull()  # refresh local mirror
        except Exception:
            pass
        if not remote_path.exists():
            return False, "No remote catalog yet — pushed at next release.", _ensure_catalog()
        remote = json.loads(remote_path.read_text(encoding="utf-8"))
        # Merge: remote items win, local-only items appended.
        local = _ensure_catalog()
        seen = {it.get("id") for it in remote if isinstance(it, dict)}
        merged = list(remote)
        for it in local:
            if isinstance(it, dict) and it.get("id") not in seen:
                merged.append(it)
        try:
            CATALOG_PATH.write_text(
                json.dumps(merged, indent=2), encoding="utf-8")
        except Exception:
            pass
        return True, f"Synced {len(remote)} items from cloud.", merged
    except Exception as ex:
        return False, f"Sync failed — {type(ex).__name__}", _ensure_catalog()


# ---------------------------------------------------------------------------
class MarketplaceCard(QFrame):
    """One catalog item — title · description · install button."""
    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("marketCard")

        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE["md"], SPACE["md"],
                             SPACE["md"], SPACE["md"])
        v.setSpacing(SPACE["xs"]+2)

        top = QHBoxLayout()
        top.setSpacing(SPACE["sm"])
        cat = QLabel(item["kind"].upper())
        cat.setObjectName("studioMonoCap")
        top.addWidget(cat)
        top.addStretch(1)
        runs = QLabel(f"{item.get('runs', 0)} runs")
        runs.setObjectName("studioMonoMuted")
        top.addWidget(runs)
        top_w = QWidget(); top_w.setLayout(top)
        v.addWidget(top_w)

        name = QLabel(item["name"])
        name.setObjectName("marketCardTitle")
        name.setWordWrap(True)
        v.addWidget(name)

        desc = QLabel(item.get("description", ""))
        desc.setObjectName("marketCardDesc")
        desc.setWordWrap(True)
        v.addWidget(desc)

        bot = QHBoxLayout()
        bot.setSpacing(SPACE["xs"]+2)
        for h in item.get("hosts", [])[:3]:
            badge = QLabel(h)
            badge.setObjectName("marketBadge")
            bot.addWidget(badge)
        bot.addStretch(1)
        author = QLabel(item.get("author", ""))
        author.setObjectName("studioMonoMuted")
        bot.addWidget(author)
        self.btn_install = QPushButton("Install")
        self.btn_install.setObjectName("marketInstall")
        self.btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install.clicked.connect(self._install)
        bot.addWidget(self.btn_install)
        bot_w = QWidget(); bot_w.setLayout(bot)
        v.addWidget(bot_w)

        self.setStyleSheet(_card_qss())

    def _install(self) -> None:
        kind = self.item.get("kind")
        payload = self.item.get("payload") or {}
        try:
            if kind == "skill":
                from skills.library import add_skill
                add_skill(payload)
                detail = f"Installed Skill — {self.item['name']}."
            elif kind == "workflow":
                from workflows.graph import Workflow
                from workflows import save_workflow
                wf = Workflow.from_dict(payload)
                save_workflow(wf)
                detail = f"Installed Workflow — {self.item['name']}."
            else:
                raise ValueError(f"Unknown kind: {kind}")
            self.btn_install.setText("Installed")
            self.btn_install.setEnabled(False)
            # Force the shell's Skills + Home caches to invalidate so
            # the new item appears immediately when the user navigates
            # to the Skills page.
            try:
                shell = self.window()
                shell._skills_cache = (0.0, [])
                shell._sessions_cache = (0.0, [])
                # Re-render Skills page if it's already constructed.
                p = getattr(shell, "pages", {}).get("skills")
                if p is not None and hasattr(p, "_refresh"):
                    p._refresh()
            except Exception:
                pass
            try:
                from toast import show_toast
                show_toast(self.window(), detail, kind="ok")
            except Exception:
                pass
        except Exception as ex:
            try:
                from toast import show_toast
                show_toast(self.window(),
                           f"Install failed — {type(ex).__name__}",
                           kind="err")
            except Exception:
                QMessageBox.warning(self, "Install failed",
                                    f"{type(ex).__name__}: {ex}")


# ---------------------------------------------------------------------------
class MarketplacePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPage")
        self._catalog = _ensure_catalog()
        self._kind_filter = "skill"   # default tab

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header.
        head = QWidget()
        hh = QVBoxLayout(head)
        hh.setContentsMargins(40, 32, 40, 12)
        hh.setSpacing(4)
        cap = QLabel("MARKETPLACE")
        cap.setObjectName("studioMonoCap")
        hh.addWidget(cap)
        h1 = QLabel("Marketplace")
        h1.setObjectName("studioH1")
        hh.addWidget(h1)
        sub = QLabel(
            "Skills + Workflows from the official catalog. Install adds the "
            "item to your local library — runs the same as anything you "
            "build yourself."
        )
        sub.setObjectName("studioH1Sub")
        sub.setWordWrap(True)
        hh.addWidget(sub)
        outer.addWidget(head)

        # Tab buttons + search.
        tabs = QHBoxLayout()
        tabs.setContentsMargins(40, 0, 40, SPACE["md"])
        tabs.setSpacing(SPACE["sm"])
        self.btn_skills = QPushButton("Skills")
        self.btn_skills.setObjectName("studioChip")
        self.btn_skills.setCheckable(True)
        self.btn_skills.setChecked(True)
        self.btn_skills.clicked.connect(lambda: self._switch_tab("skill"))
        tabs.addWidget(self.btn_skills)
        self.btn_flows = QPushButton("Workflows")
        self.btn_flows.setObjectName("studioChip")
        self.btn_flows.setCheckable(True)
        self.btn_flows.clicked.connect(lambda: self._switch_tab("workflow"))
        tabs.addWidget(self.btn_flows)
        tabs.addStretch(1)
        self.btn_sync = QPushButton("↻ Sync")
        self.btn_sync.setObjectName("studioChip")
        self.btn_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sync.setToolTip("Pull the latest catalog from the cloud")
        self.btn_sync.clicked.connect(self._sync_remote)
        tabs.addWidget(self.btn_sync)
        self.search = QLineEdit()
        self.search.setObjectName("marketSearch")
        self.search.setPlaceholderText("Filter by name · tag · host…")
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(self._refresh)
        tabs.addWidget(self.search)
        tabs_w = QWidget(); tabs_w.setLayout(tabs)
        outer.addWidget(tabs_w)

        # Scrollable card grid.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("studioScroll")
        self.scroll.setStyleSheet(
            "QScrollArea#studioScroll { background:transparent; border:none; }")
        self.body = QWidget()
        self.body.setObjectName("studioPage")
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(40, 0, 40, 40)
        self.grid.setHorizontalSpacing(SPACE["md"])
        self.grid.setVerticalSpacing(SPACE["md"])
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

        self.setStyleSheet(self.styleSheet() + _panel_qss())
        self._refresh()

    def _sync_remote(self) -> None:
        ok, msg, catalog = fetch_remote_catalog()
        self._catalog = catalog
        try:
            from toast import show_toast
            show_toast(self.window(), msg, kind=("ok" if ok else "warn"))
        except Exception:
            pass
        self._refresh()

    def _switch_tab(self, kind: str) -> None:
        self._kind_filter = kind
        self.btn_skills.setChecked(kind == "skill")
        self.btn_flows.setChecked(kind == "workflow")
        self._refresh()

    def _refresh(self) -> None:
        # Clear grid.
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        q = (self.search.text() or "").strip().lower()
        rows = []
        for it in self._catalog:
            if it.get("kind") != self._kind_filter:
                continue
            if q:
                hay = " ".join([
                    it.get("name", ""),
                    " ".join(it.get("tags", []) or []),
                    " ".join(it.get("hosts", []) or []),
                    it.get("description", ""),
                ]).lower()
                if q not in hay:
                    continue
            rows.append(it)
        if not rows:
            empty = QLabel("No catalog matches your filter.")
            empty.setObjectName("studioMonoMuted")
            self.grid.addWidget(empty, 0, 0, 1, 3)
            return
        for i, it in enumerate(rows):
            r, c = divmod(i, 3)
            card = MarketplaceCard(it, parent=self.body)
            self.grid.addWidget(card, r, c)


# ---------------------------------------------------------------------------
def _card_qss() -> str:
    return (
        f"QFrame#marketCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; border-radius:{RADIUS['lg']}px; "
        f"}}"
        f"QFrame#marketCard:hover {{ border-color:{T['accent']}; }}"
        f"QLabel#marketCardTitle {{ font-family:{TYPE['fontSerif']}; "
        f"  font-style:italic; font-size:18px; color:{T['ink']}; "
        f"  letter-spacing:-0.01em; }}"
        f"QLabel#marketCardDesc {{ font-family:{TYPE['fontSans']}; "
        f"  font-size:12px; color:{T['inkSoft']}; line-height:1.5; }}"
        f"QLabel#marketBadge {{ font-family:{TYPE['fontMono']}; "
        f"  font-size:9px; color:{T['inkMuted']}; letter-spacing:0.08em; "
        f"  padding:2px 6px; background:{T['bgSoft']}; "
        f"  border-radius:{RADIUS['xs']}px; }}"
        f"QPushButton#marketInstall {{ background:{T['accent']}; color:#fff; "
        f"  border:none; border-radius:{RADIUS['md']}px; "
        f"  padding:5px 12px; font-family:{TYPE['fontSans']}; "
        f"  font-size:11.5px; font-weight:500; }}"
        f"QPushButton#marketInstall:hover {{ background:{T['accentHi']}; }}"
        f"QPushButton#marketInstall:disabled {{ "
        f"  background:{T['inkDim']}; color:{T['inkSoft']}; }}"
    )


def _panel_qss() -> str:
    return (
        f"QLineEdit#marketSearch {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; border-radius:{RADIUS['md']}px; "
        f"  padding:5px 10px; color:{T['ink']}; "
        f"  font-family:{TYPE['fontMono']}; font-size:11.5px; }}"
        f"QPushButton#studioChip:checked {{ "
        f"  border-color:{T['accent']}; color:{T['accent']}; }}"
    )
