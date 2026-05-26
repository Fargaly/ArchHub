"""ArchHub — SettingsDialog (v1.5 IA refresh).

Eight tabs, each a small QWidget subclass: General, Providers, Hosts,
Memory, Permissions, Storage, Shortcuts, About. Every button fires a
real bridge slot; nothing is decorative. Public constructor stays
`SettingsDialog(router, parent, manager=None, tools=None, **_kwargs)`
to keep existing callers working.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from secrets_store import (
    load_api_key, delete_api_key, save_setting, load_setting,
)
from sign_in_dialog import SignInDialog


# ── Dark-theme tokens (LM aesthetic) ──────────────────────────────────────
TOKENS = {
    "bg":     "#0e0e11",  "panel":  "#15151a",  "card":   "#1a1a21",
    "border": "#2a2a33",  "text":   "#ece8e0",  "muted":  "#8a8a93",
    "accent": "#d97757",  "good":   "#6fb88a",  "warn":   "#d6a05e",
    "bad":    "#b8625f",
    "mono":   "JetBrains Mono, Consolas, ui-monospace, monospace",
}

DIALOG_QSS = f"""
QDialog#settingsDialog {{ background:{TOKENS['bg']}; color:{TOKENS['text']}; }}
QWidget#settingsPage   {{ background:{TOKENS['panel']}; color:{TOKENS['text']}; }}
QLabel                 {{ color:{TOKENS['text']}; }}
QLabel#muted           {{ color:{TOKENS['muted']}; }}
QLabel#h1              {{ font-size:18px; font-weight:600; padding-bottom:4px; }}
QLabel#mono            {{ font-family:{TOKENS['mono']}; color:{TOKENS['muted']}; }}
QLabel#good            {{ color:{TOKENS['good']}; }}
QLabel#accent          {{ color:{TOKENS['accent']}; }}
QGroupBox {{
    background:{TOKENS['card']}; border:1px solid {TOKENS['border']};
    border-radius:10px; margin-top:14px; padding:14px 12px 10px 12px;
    color:{TOKENS['text']};
}}
QGroupBox::title {{
    subcontrol-origin:margin; subcontrol-position:top left;
    left:10px; padding:0 6px; color:{TOKENS['muted']}; font-weight:600;
}}
QTabWidget::pane {{
    background:{TOKENS['panel']}; border:1px solid {TOKENS['border']};
    border-radius:8px; top:-1px;
}}
QTabBar::tab {{
    background:transparent; color:{TOKENS['muted']};
    padding:8px 16px; margin-right:2px;
    border:1px solid transparent; border-bottom:none;
    border-top-left-radius:8px; border-top-right-radius:8px;
    font-weight:500;
}}
QTabBar::tab:hover    {{ color:{TOKENS['text']}; }}
QTabBar::tab:selected {{
    background:{TOKENS['panel']}; color:{TOKENS['accent']};
    border:1px solid {TOKENS['border']};
    border-bottom:1px solid {TOKENS['panel']};
}}
QLineEdit, QComboBox {{
    background:{TOKENS['bg']}; color:{TOKENS['text']};
    border:1px solid {TOKENS['border']}; border-radius:6px;
    padding:6px 9px; selection-background-color:{TOKENS['accent']};
}}
QLineEdit:focus, QComboBox:focus {{ border:1px solid {TOKENS['accent']}; }}
QComboBox QAbstractItemView {{
    background:{TOKENS['card']}; color:{TOKENS['text']};
    border:1px solid {TOKENS['border']};
    selection-background-color:{TOKENS['accent']};
}}
QPushButton {{
    background:transparent; color:{TOKENS['text']};
    border:1px solid {TOKENS['border']}; border-radius:6px;
    padding:6px 14px; font-weight:500;
}}
QPushButton:hover    {{ border-color:{TOKENS['accent']}; color:{TOKENS['accent']}; }}
QPushButton:disabled {{ color:{TOKENS['muted']}; border-color:{TOKENS['border']}; }}
QPushButton#primary {{
    background:{TOKENS['accent']}; color:#1a1209;
    border:1px solid {TOKENS['accent']};
}}
QPushButton#primary:hover {{ background:#e88766; border-color:#e88766; }}
QPushButton#danger {{ color:{TOKENS['bad']}; border-color:{TOKENS['bad']}; }}
QPushButton#danger:hover {{ background:{TOKENS['bad']}; color:#1a1209; }}
QCheckBox {{ color:{TOKENS['text']}; spacing:8px; }}
QCheckBox::indicator {{
    width:14px; height:14px; border:1px solid {TOKENS['border']};
    border-radius:3px; background:{TOKENS['bg']};
}}
QCheckBox::indicator:checked {{
    background:{TOKENS['accent']}; border-color:{TOKENS['accent']};
}}
QTableWidget, QListWidget {{
    background:{TOKENS['bg']}; color:{TOKENS['text']};
    border:1px solid {TOKENS['border']}; border-radius:6px;
    gridline-color:{TOKENS['border']};
    alternate-background-color:{TOKENS['card']};
}}
QHeaderView::section {{
    background:{TOKENS['card']}; color:{TOKENS['muted']};
    border:none; border-bottom:1px solid {TOKENS['border']};
    padding:6px 8px; font-weight:600;
    text-transform:uppercase; font-size:11px; letter-spacing:0.8px;
}}
QTableWidget::item:selected, QListWidget::item:selected {{
    background:{TOKENS['accent']}; color:#1a1209;
}}
QScrollArea {{ background:transparent; border:none; }}
QScrollBar:vertical {{ background:transparent; width:10px; }}
QScrollBar::handle:vertical {{
    background:{TOKENS['border']}; border-radius:5px; min-height:24px;
}}
QScrollBar::handle:vertical:hover {{ background:{TOKENS['muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
"""


# ── Helpers ───────────────────────────────────────────────────────────────
def _safe(call, default=None):
    try:
        return call()
    except Exception:
        return default


def _bridge_call(parent, method: str, *args, default=None):
    """Walk up the parent chain, find a `bridge` slot, json-decode result.
    Returns `default` if no bridge / slot raises / json invalid."""
    obj = parent
    seen = set()
    while obj is not None and id(obj) not in seen:
        seen.add(id(obj))
        bridge = getattr(obj, "bridge", None) or getattr(obj, "_bridge", None)
        if bridge is not None and hasattr(bridge, method):
            try:
                fn = getattr(bridge, method)
                raw = fn(*args) if args else fn()
                if isinstance(raw, str):
                    return json.loads(raw or "null")
                return raw
            except Exception:
                return default
        obj = obj.parent() if hasattr(obj, "parent") else None
    return default


def _make_table(cols: list[str], stretch_first: bool = True) -> QTableWidget:
    """Spin up a QTableWidget with our standard chrome."""
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    h = t.horizontalHeader()
    for i in range(len(cols)):
        mode = (QHeaderView.ResizeMode.Stretch
                if (stretch_first and i == 0)
                else QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(i, mode)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    return t


def _qbrush(hex_str: str):
    from PyQt6.QtGui import QBrush, QColor
    return QBrush(QColor(hex_str))


def _add_title(layout, title: str, blurb: str, scope: str = "") -> None:
    """Add an h1 + muted subtitle pair to the given layout. If `scope`
    is given, a small chip ([USER] / [PROJECT] / [FIRM] / [DEVICE]) is
    placed next to the title to tell the founder where these settings
    live."""
    head = QHBoxLayout(); head.setSpacing(8); head.setContentsMargins(0, 0, 0, 0)
    t = QLabel(title); t.setObjectName("h1")
    head.addWidget(t)
    if scope:
        head.addWidget(_make_scope_chip(scope))
    head.addStretch(1)
    layout.addLayout(head)
    s = QLabel(blurb); s.setObjectName("muted"); s.setWordWrap(True)
    layout.addWidget(s)


def _make_scope_chip(scope: str) -> QLabel:
    """Render a small rounded scope chip. Scope is one of:
    USER / PROJECT / FIRM / DEVICE. Visual-only — does not change
    persistence."""
    label = (scope or "").strip().upper()
    chip = QLabel(label)
    chip.setObjectName("scopeChip")
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setStyleSheet(
        f"QLabel#scopeChip {{"
        f" background:{TOKENS['bg']};"
        f" color:{TOKENS['accent']};"
        f" border:1px solid {TOKENS['accent']};"
        f" border-radius:8px;"
        f" padding:1px 7px;"
        f" font-size:9px;"
        f" font-weight:700;"
        f" letter-spacing:0.10em;"
        f"}}"
    )
    return chip


def _groupbox_with_chip(title: str, scope: str = "") -> QGroupBox:
    """A QGroupBox whose title carries a small scope chip on the right
    side. Same dark chrome as a plain QGroupBox."""
    grp = QGroupBox(title)
    if not scope:
        return grp
    chip = _make_scope_chip(scope)
    chip.setParent(grp)
    chip.setStyleSheet(chip.styleSheet() + " QLabel#scopeChip { margin-top:-1px; }")
    # Place the chip in the top-right inside the group margin.
    def _position():
        try:
            chip.adjustSize()
            x = max(8, grp.width() - chip.width() - 12)
            chip.move(x, 2)
            chip.raise_()
        except Exception:
            pass
    # QGroupBox emits resizeEvent — hook via eventFilter would be heavy;
    # use a short-circuit: re-position on show + on resize via a tiny
    # subclass-by-override.
    _orig_resize = grp.resizeEvent
    def _resize(ev):
        _orig_resize(ev)
        _position()
    grp.resizeEvent = _resize  # type: ignore[assignment]
    _position()
    return grp


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"


def _profile_path() -> Path:
    return _local_appdata() / "profile.json"


def _theme_path() -> Path:
    return _local_appdata() / "theme.json"


def _brain_tuning_path() -> Path:
    """Where BrainTab persists local toggle state when the daemon
    doesn't expose a `brain.settings_*` tool (which it doesn't today).
    Founder picked: %LOCALAPPDATA%/ArchHub/brain/tuning.json."""
    return _local_appdata() / "brain" / "tuning.json"


def _load_brain_tuning() -> dict:
    p = _brain_tuning_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}") or {}
    except Exception:
        return {}


def _save_brain_tuning(data: dict) -> None:
    p = _brain_tuning_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data or {}, indent=2), encoding="utf-8")
    except Exception:
        pass


def _fmt_bytes(b: int) -> str:
    b = float(b or 0)
    if b < 1024:
        return f"{int(b)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        b /= 1024.0
        if b < 1024:
            return f"{b:.1f} {unit}"
    return f"{b:.1f} PB"


def _cloud_client():
    try:
        import cloud_client as _cc
        return _cc
    except Exception:
        return None


def _detect_brain_agent(slug: str) -> dict:
    """Detect whether a given MCP-client agent has the brain wired into
    its config. Returns {'name','path','state','detail'} with state in
    {'wired','unwired','not_detected'}.

    Detection is conservative: file must exist (else not_detected); if
    file exists, search for 'personal-brain' or 'brain' MCP entry to
    declare 'wired'. ChatGPT desktop is always 'unwired' (OAuth pending).
    """
    home = Path(os.path.expanduser("~"))
    if slug == "claude_code":
        cfg = home / ".claude" / "settings.json"
        name = "Claude Code"
        detail = "~/.claude/settings.json · hooks + stdio"
    elif slug == "cursor":
        cfg = home / ".cursor" / "mcp.json"
        name = "Cursor"
        detail = "~/.cursor/mcp.json · HTTP"
    elif slug == "codex":
        cfg = home / ".codex" / "config.toml"
        name = "Codex CLI"
        detail = "~/.codex/config.toml · stdio"
    elif slug == "gemini":
        cfg = home / ".gemini" / "settings.json"
        name = "Gemini CLI"
        detail = "~/.gemini/settings.json · session inject"
    elif slug == "archhub_composer":
        # In-process — Layer 5 in app/llm_router.py.
        cfg = Path(__file__).resolve().parent / "llm_router.py"
        name = "ArchHub Composer"
        detail = "app/llm_router.py · Layer 5 hooks · in-process"
        return {
            "name": name, "path": str(cfg), "detail": detail,
            "state": "wired" if cfg.is_file() else "unwired",
        }
    elif slug == "chatgpt_desktop":
        return {
            "name": "ChatGPT desktop", "path": "OAuth 2.1 + PKCE",
            "detail": "Requires public HTTPS endpoint",
            "state": "unwired",
        }
    else:
        return {"name": slug, "path": "", "detail": "", "state": "not_detected"}

    if not cfg.is_file():
        return {"name": name, "path": str(cfg), "detail": detail,
                "state": "not_detected"}
    try:
        raw = cfg.read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        raw = ""
    wired = ("personal-brain" in raw) or ("personal_brain" in raw) \
            or ("8473" in raw and "mcp" in raw)
    return {
        "name": name, "path": str(cfg), "detail": detail,
        "state": "wired" if wired else "unwired",
    }


def _read_version() -> str:
    p = Path(__file__).resolve().parent.parent / "VERSION"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip() or "1.5.0-alpha"
        except Exception:
            pass
    return "1.5.0-alpha"


def _read_git_sha() -> str:
    head = Path(__file__).resolve().parent.parent / ".git" / "HEAD"
    if not head.exists():
        return ""
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            ref_path = Path(__file__).resolve().parent.parent / ".git" / ref.split()[1]
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:8]
        return ref[:8]
    except Exception:
        return ""


# ── Provider sign-in row (restyled from v1.4) ────────────────────────────
PROVIDER_META = [
    # (id, env_var, supports_oauth)
    ("openrouter", "",                 True),
    ("anthropic",  "ANTHROPIC_API_KEY", False),
    ("openai",     "OPENAI_API_KEY",   False),
    ("google",     "GOOGLE_API_KEY",   False),
    ("ollama",     "",                 False),
    ("lmstudio",   "",                 False),
]

PROVIDER_LABELS = {
    "openrouter": "OpenRouter",
    "anthropic":  "Anthropic",
    "openai":     "OpenAI",
    "google":     "Google",
    "ollama":     "Ollama (local)",
    "lmstudio":   "LM Studio (local)",
}


def _key_present(provider: str, env_var: str) -> bool:
    if load_api_key(provider):
        return True
    return bool(env_var and os.environ.get(env_var, ""))


# ── Tab: General ─────────────────────────────────────────────────────────
class GeneralTab(QWidget):
    """Profile (name / email / firm) + theme + default model."""

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "General",
                    "Identity, appearance, default model. All values stay "
                    "on this machine.",
                    scope="USER")

        prof = QGroupBox("Profile")
        pf = QFormLayout(prof); pf.setSpacing(8); pf.setContentsMargins(12, 18, 12, 12)
        self._name = QLineEdit(); self._name.setPlaceholderText("Ada Lovelace")
        self._email = QLineEdit(); self._email.setPlaceholderText("ada@firm.com")
        self._firm = QLineEdit(); self._firm.setPlaceholderText("Firm name")
        pf.addRow("Name", self._name); pf.addRow("Email", self._email); pf.addRow("Firm", self._firm)
        outer.addWidget(prof)

        appe = QGroupBox("Appearance")
        af = QFormLayout(appe); af.setSpacing(8); af.setContentsMargins(12, 18, 12, 12)
        self._theme = QComboBox()
        for label, val in (("Dark", "dark"), ("Light", "light"), ("System", "system")):
            self._theme.addItem(label, val)
        af.addRow("Theme", self._theme)
        self._lang = QComboBox()
        for code, label in (("en", "English"), ("es", "Español"), ("fr", "Français"),
                            ("de", "Deutsch"), ("ja", "日本語"), ("zh", "中文")):
            self._lang.addItem(label, code)
        af.addRow("Language", self._lang)
        outer.addWidget(appe)

        modg = QGroupBox("Default model")
        mf = QVBoxLayout(modg); mf.setSpacing(8); mf.setContentsMargins(12, 18, 12, 12)
        hint = QLabel("Model new sessions start in. Switch per-session with "
                       "<kbd>Ctrl+M</kbd>.")
        hint.setObjectName("muted"); hint.setWordWrap(True)
        mf.addWidget(hint)
        self._model = QComboBox(); mf.addWidget(self._model)
        outer.addWidget(modg)

        # ── Canvas behaviour (closes FAILURE_LOG agdr-0024-hostnodev2-
        # localstorage-gated-off — DEVICE scope: this is a per-machine
        # canvas render preference, not a profile setting).
        canvas_grp = QGroupBox("Canvas behaviour")
        cgf = QVBoxLayout(canvas_grp); cgf.setSpacing(8); cgf.setContentsMargins(12, 18, 12, 12)
        cgf_hint = QLabel(
            "<b>HostNode v2</b> is the per-AgDR-0024 connector-node design "
            "(op-grid + typed wires + floating verb bar). It's the canon "
            "render path; default ON. Toggle off only to A/B against the v1 "
            "fallback during host-debugging."
        )
        cgf_hint.setObjectName("muted"); cgf_hint.setWordWrap(True)
        cgf.addWidget(cgf_hint)
        self._host_node_v2 = QCheckBox("Use HostNode v2 design for connector nodes")
        # Default ON to match the JSX-side default (studio-lm.jsx
        # _readHostNodeV2 returns true when the value is empty).
        saved_v2 = load_setting("host_node_v2")
        self._host_node_v2.setChecked(bool(saved_v2) if saved_v2 is not None else True)
        self._host_node_v2.toggled.connect(self._on_host_node_v2)
        cgf.addWidget(self._host_node_v2)
        outer.addWidget(canvas_grp)

        outer.addStretch(1)

        # Save row
        save_row = QHBoxLayout()
        self._save_btn = QPushButton("Save changes"); self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._save)
        save_row.addStretch(1); save_row.addWidget(self._save_btn)
        outer.addLayout(save_row)

        self._load()

    def _load(self) -> None:
        # Profile from %LOCALAPPDATA%/ArchHub/profile.json.
        try:
            p = _profile_path()
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8") or "{}") or {}
                self._name.setText(data.get("name", "") or "")
                self._email.setText(data.get("email", "") or "")
                self._firm.setText(data.get("firm", "") or "")
        except Exception:
            pass

        # Theme — bridge.get_theme returns {"theme": "dark|light|system"}.
        theme = "dark"
        bt = _bridge_call(self._parent_dlg, "get_theme", default={}) or {}
        if isinstance(bt, dict) and bt.get("theme") in ("dark", "light", "system"):
            theme = bt["theme"]
        elif _theme_path().is_file():
            try:
                t = json.loads(_theme_path().read_text(encoding="utf-8") or "{}")
                if t.get("theme") in ("dark", "light", "system"):
                    theme = t["theme"]
            except Exception:
                pass
        idx = self._theme.findData(theme)
        if idx >= 0:
            self._theme.setCurrentIndex(idx)

        # Language — just a saved setting; not yet wired to i18n.
        lang = (load_setting("language") or "en") or "en"
        idx = self._lang.findData(lang)
        if idx >= 0:
            self._lang.setCurrentIndex(idx)

        # Models via bridge.get_models. Fall back to a tiny set if no
        # bridge is reachable (offline / test harness).
        models = _bridge_call(self._parent_dlg, "get_models", default=None)
        if not isinstance(models, list) or not models:
            models = [
                {"id": "auto", "label": "Auto · best model per task",
                 "provider": "auto", "configured": True},
            ]
        self._model.blockSignals(True)
        self._model.clear()
        saved = load_setting("default_model") or "auto"
        sel = 0
        for i, m in enumerate(models):
            label = m.get("label", m.get("id", "?")) or "?"
            if not m.get("configured", True):
                label = label + "  ·  not configured"
            self._model.addItem(label, m.get("id", "auto"))
            if m.get("id") == saved:
                sel = i
        self._model.setCurrentIndex(sel)
        self._model.blockSignals(False)

    def _on_host_node_v2(self, on: bool) -> None:
        """Persist the HostNode v2 preference and (best-effort) flip
        the JSX-side localStorage flag so the canvas reflects the
        change without a manual reload.

        Bridge gap (documented per founder spec): the JS side reads its
        value from <code>localStorage['archhub.host_node_v2']</code> via
        <code>window.__archhubSetHostNodeV2</code>. Bridge has no
        <code>set_pref</code> / <code>run_js</code> slot to flip that
        from Python. The Qt-side checkbox + secrets_store save is the
        SAFE persisted value; JSX reads default-ON, so toggling here
        guarantees correctness on the NEXT reload. Live-flip via the
        bridge can land later as a small <code>set_pref</code> slot."""
        save_setting("host_node_v2", bool(on))
        # Best-effort: drive JSX via the bridge if a JS-eval slot ever
        # appears. Today none exists — silent no-op is the right thing.
        bridge = (getattr(self._parent_dlg, "bridge", None)
                  or getattr(self._parent_dlg, "_bridge", None))
        run_js = getattr(bridge, "run_js", None) if bridge else None
        if callable(run_js):
            try:
                run_js(
                    "try { window.__archhubSetHostNodeV2 && "
                    f"window.__archhubSetHostNodeV2({str(bool(on)).lower()}); }} "
                    "catch (e) {}"
                )
            except Exception:
                pass

    def _save(self) -> None:
        # Profile JSON.
        try:
            p = _profile_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({
                "name":  self._name.text().strip(),
                "email": self._email.text().strip(),
                "firm":  self._firm.text().strip(),
            }, indent=2), encoding="utf-8")
        except Exception as ex:
            QMessageBox.warning(self, "Profile", f"Save failed: {ex}")

        # Theme via bridge so the rest of the app picks it up.
        theme = self._theme.currentData() or "dark"
        _bridge_call(self._parent_dlg, "set_theme", theme, default={})

        # Language + default model — local settings.
        save_setting("language", self._lang.currentData() or "en")
        save_setting("default_model", self._model.currentData() or "auto")

        QMessageBox.information(self, "General", "Saved.")
        self._parent_dlg.notify_changed()


# ── Tab: Providers ───────────────────────────────────────────────────────
class _ProviderRow(QFrame):
    """Single provider row — icon · name · status · Sign-in/Sign-out."""

    def __init__(self, provider: str, env_var: str, supports_oauth: bool,
                 parent_tab: "ProvidersTab"):
        super().__init__()
        self.provider = provider
        self.env_var = env_var
        self.supports_oauth = supports_oauth
        self._tab = parent_tab
        self.setStyleSheet(
            f"_ProviderRow {{ background: {TOKENS['card']}; "
            f"border: 1px solid {TOKENS['border']}; border-radius: 8px; }}"
        )

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(12)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        h.addWidget(self._dot)

        name = QLabel(PROVIDER_LABELS.get(provider, provider.title()))
        font = QFont(); font.setBold(True); font.setPointSize(11)
        name.setFont(font)
        h.addWidget(name)

        self._status = QLabel("")
        self._status.setObjectName("mono")
        h.addWidget(self._status, 1)

        self._btn = QPushButton(""); self._btn.setMinimumWidth(120)
        self._btn.clicked.connect(self._on_click)
        h.addWidget(self._btn)

        self.refresh()

    def refresh(self) -> None:
        signed = _key_present(self.provider, self.env_var)
        if signed:
            self._dot.setText("●")
            self._dot.setStyleSheet(f"color: {TOKENS['good']};")
            key = load_api_key(self.provider) or os.environ.get(self.env_var, "")
            masked = (f"…{key[-4:]}" if key else "")
            self._status.setText(f"signed in {masked}".strip())
            self._btn.setText("Sign out")
            self._btn.setObjectName("")
        else:
            self._dot.setText("○")
            self._dot.setStyleSheet(f"color: {TOKENS['muted']};")
            if self.provider in ("ollama", "lmstudio"):
                self._status.setText("optional — local server")
            else:
                self._status.setText("not signed in")
            self._btn.setText("Sign in")
            self._btn.setObjectName("primary")
        # Re-polish so QSS object-name change repaints.
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)

    def _on_click(self) -> None:
        if _key_present(self.provider, self.env_var):
            label = PROVIDER_LABELS.get(self.provider, self.provider.title())
            if QMessageBox.question(
                self, f"Sign out of {label}?",
                f"Remove the saved {label} key from this device?",
            ) == QMessageBox.StandardButton.Yes:
                delete_api_key(self.provider)
                self.refresh()
                self._tab.notify_changed()
            return
        # Local-only providers don't have a real sign-in — surface help.
        if self.provider in ("ollama", "lmstudio"):
            QMessageBox.information(
                self,
                PROVIDER_LABELS[self.provider],
                "Local providers are auto-detected when their server is "
                "running on localhost. Start Ollama / LM Studio, then click "
                "Refresh on this tab — no key required.",
            )
            return
        dlg = SignInDialog(self.provider, self)
        dlg.signed_in.connect(lambda _p: self._tab.notify_changed())
        dlg.exec()
        self.refresh()


class ProvidersTab(QWidget):
    """All LLM providers — sign-in state + connection counts."""

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Providers",
                    "ArchHub never asks you to type or paste an API key. "
                    "Click <b>Sign in</b>, copy the key from the provider's "
                    "site, and ArchHub will detect it on your clipboard.",
                    scope="USER")

        # Status banner — uses bridge.get_provider_stats.
        self._banner = QLabel("")
        self._banner.setObjectName("mono")
        outer.addWidget(self._banner)

        self._rows: list[_ProviderRow] = []
        for pid, env, oauth in PROVIDER_META:
            row = _ProviderRow(pid, env, oauth, self)
            self._rows.append(row)
            outer.addWidget(row)

        # Trailing toggle: show local Ollama models in the picker.
        self._show_local = QCheckBox(
            "Show local Ollama models in the picker  "
            "(advanced — local inference is slower than cloud)"
        )
        self._show_local.setChecked(bool(load_setting("show_local_models")))
        self._show_local.toggled.connect(
            lambda v: save_setting("show_local_models", bool(v))
        )
        outer.addWidget(self._show_local)

        # Refresh row.
        rrow = QHBoxLayout()
        rrow.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        rrow.addWidget(refresh)
        outer.addLayout(rrow)

        outer.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        for row in self._rows:
            row.refresh()
        stats = _bridge_call(self._parent_dlg, "get_provider_stats",
                             default={"configured": 0, "blocked": 0}) or {}
        configured = int(stats.get("configured", 0) or 0)
        blocked = int(stats.get("blocked", 0) or 0)
        self._banner.setText(
            f"{configured} provider(s) configured" +
            (f"  ·  {blocked} blocked" if blocked else "")
        )

    def notify_changed(self) -> None:
        self.refresh()
        self._parent_dlg.notify_changed()


# ── Tab: Hosts ───────────────────────────────────────────────────────────
class HostsTab(QWidget):
    """Live desktop / SaaS host detection + per-host enable/disable.

    Two sources of truth:
      bridge.get_hosts        — connector-side (Revit, AutoCAD, ...) with
                                 active/discovered state from `manager`
      bridge.get_all_hosts    — host_detector view of every external app
                                 ArchHub knows about (Outlook, Teams, etc.)
    Merged into one table; toggle calls bridge.set_host_active."""

    COLS = ("Host", "Family", "State", "Version", "Action")

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Hosts",
                    "Desktop and SaaS apps ArchHub can talk to. State is "
                    "detected from running processes / installed apps. Toggle "
                    "a host off if you don't want ArchHub to attach to it.",
                    scope="DEVICE")

        self._table = _make_table(list(self.COLS))
        outer.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        btn_row.addStretch(1); btn_row.addWidget(self._refresh_btn)
        outer.addLayout(btn_row)

        self.refresh()

    def refresh(self) -> None:
        # Active connector entries (manager-backed).
        connectors = _bridge_call(self._parent_dlg, "get_hosts", default=[]) or []
        if not isinstance(connectors, list):
            connectors = []
        # External-host detection (Outlook, Teams, Word, ...).
        externals = _bridge_call(self._parent_dlg, "get_all_hosts", default={}) or {}
        if not isinstance(externals, dict):
            externals = {}

        rows: list[dict] = []
        seen_ids: set[str] = set()
        for entry in connectors:
            if not isinstance(entry, dict):
                continue
            hid = str(entry.get("id") or entry.get("family") or "")
            if not hid or hid in seen_ids:
                continue
            seen_ids.add(hid)
            rows.append({
                "id":      hid,
                "family":  entry.get("family", hid),
                "name":    entry.get("name", hid.title()),
                "state":   str(entry.get("state", "unknown")).lower(),
                "version": entry.get("version", "") or "",
                "kind":    "connector",
            })
        for fam, info in externals.items():
            if fam in seen_ids:
                continue
            seen_ids.add(fam)
            info = info if isinstance(info, dict) else {}
            rows.append({
                "id":      fam,
                "family":  fam,
                "name":    fam.title(),
                "state":   str(info.get("status", "unknown")).lower(),
                "version": info.get("version", "") or "",
                "kind":    "external",
            })

        rows.sort(key=lambda r: (r["state"] != "running"
                                 and r["state"] != "active", r["name"]))
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(r["name"]))
            fam_item = QTableWidgetItem(r["family"])
            fam_item.setForeground(_qbrush(TOKENS["muted"]))
            self._table.setItem(i, 1, fam_item)
            state_item = QTableWidgetItem(self._state_label(r["state"]))
            state_item.setForeground(_qbrush(self._state_colour(r["state"])))
            self._table.setItem(i, 2, state_item)
            ver_item = QTableWidgetItem(str(r["version"]))
            ver_item.setForeground(_qbrush(TOKENS["muted"]))
            self._table.setItem(i, 3, ver_item)

            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(4, 2, 4, 2); cl.setSpacing(4)
            is_active = r["state"] in ("active", "running", "connected")
            btn = QPushButton("Disable" if is_active else "Enable")
            if r["kind"] != "connector":
                btn.setEnabled(False)
                btn.setToolTip("Detected externally — managed by the host app.")
            else:
                btn.clicked.connect(
                    lambda _, hid=r["id"], on=not is_active:
                        self._toggle(hid, on)
                )
            cl.addStretch(1); cl.addWidget(btn)
            self._table.setCellWidget(i, 4, cell)

    @staticmethod
    def _state_label(state: str) -> str:
        return {
            "active":     "Active",
            "running":    "Running",
            "connected":  "Connected",
            "stopped":    "Stopped",
            "available":  "Installed",
            "missing":    "Not installed",
            "error":      "Error",
            "unknown":    "—",
        }.get(state, state.title() or "—")

    @staticmethod
    def _state_colour(state: str) -> str:
        if state in ("active", "running", "connected"):
            return TOKENS["good"]
        if state in ("available", "installed"):
            return TOKENS["warn"]
        if state in ("error",):
            return TOKENS["bad"]
        return TOKENS["muted"]

    def _toggle(self, host_id: str, on: bool) -> None:
        res = _bridge_call(self._parent_dlg, "set_host_active",
                           host_id, bool(on), default={"error": "no bridge"}) or {}
        if isinstance(res, dict) and res.get("error"):
            QMessageBox.warning(self, "Hosts", f"{res.get('error')}")
        self.refresh()


# ── Tab: Memory ──────────────────────────────────────────────────────────
class MemoryTab(QWidget):
    """Managed memory facts (cloud_client) + auto-capture toggle."""

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Memory",
                    "Facts ArchHub remembers across sessions. Auto-capture "
                    "pulls explicit statements ('I prefer SI units') out of "
                    "chats; you can also add or remove facts manually.",
                    scope="USER")

        # Stats banner — cloud_client.memory_stats via bridge.
        self._banner = QLabel("")
        self._banner.setObjectName("mono")
        outer.addWidget(self._banner)

        # Auto-capture toggle.
        toggle_row = QFrame()
        toggle_row.setStyleSheet(
            f"QFrame {{ background: {TOKENS['card']}; "
            f"border: 1px solid {TOKENS['border']}; border-radius: 8px; }}"
        )
        tr = QHBoxLayout(toggle_row)
        tr.setContentsMargins(14, 10, 14, 10)
        self._autocap = QCheckBox("Auto-capture facts from conversations")
        self._autocap.setChecked(bool(load_setting("memory_autocapture")))
        self._autocap.toggled.connect(
            lambda v: save_setting("memory_autocapture", bool(v))
        )
        tr.addWidget(self._autocap); tr.addStretch(1)
        outer.addWidget(toggle_row)

        self._table = _make_table(["Fact", "Scope", "Captured"])
        outer.addWidget(self._table, 1)

        # Action row.
        ar = QHBoxLayout()
        self._add_btn = QPushButton("Add fact"); self._add_btn.setObjectName("primary")
        self._edit_btn = QPushButton("Edit")
        self._forget_btn = QPushButton("Forget"); self._forget_btn.setObjectName("danger")
        self._refresh_btn = QPushButton("Refresh")
        for b in (self._add_btn, self._edit_btn, self._forget_btn):
            ar.addWidget(b)
        ar.addStretch(1)
        ar.addWidget(self._refresh_btn)
        outer.addLayout(ar)

        self._add_btn.clicked.connect(self._on_add)
        self._edit_btn.clicked.connect(self._on_edit)
        self._forget_btn.clicked.connect(self._on_forget)
        self._refresh_btn.clicked.connect(self.refresh)

        self.refresh()

    def refresh(self) -> None:
        # Stats first.
        stats = _bridge_call(self._parent_dlg, "get_memory_stats", default={}) or {}
        if isinstance(stats, dict) and not stats.get("error"):
            total = stats.get("total") or stats.get("count") or 0
            self._banner.setText(f"{total} fact(s) on record")
        else:
            self._banner.setText("Cloud memory unreachable — local cache only.")

        # Pull facts (prefer cloud_client directly for the full list; the
        # bridge endpoint returns the same shape).
        facts: list[dict] = []
        cc = _cloud_client()
        if cc is not None:
            try:
                fn = getattr(cc, "list_memory_facts", None)
                if callable(fn):
                    raw = fn() or []
                    if isinstance(raw, dict):
                        raw = raw.get("facts") or raw.get("items") or []
                    if isinstance(raw, list):
                        facts = raw
            except Exception:
                facts = []
        if not facts:
            # Try the bridge route as a fallback.
            via = _bridge_call(self._parent_dlg, "list_memory_facts", "", default=None)
            if isinstance(via, dict):
                via = via.get("facts") or via.get("items") or []
            if isinstance(via, list):
                facts = via

        self._table.setRowCount(len(facts))
        for i, f in enumerate(facts):
            if not isinstance(f, dict):
                f = {"content": str(f)}
            content = f.get("content") or f.get("text") or ""
            scope = f.get("scope") or "user"
            when = (f.get("created_at") or f.get("captured_at") or "")
            fid = f.get("id") or f.get("fact_id") or ""
            it = QTableWidgetItem(str(content))
            it.setData(Qt.ItemDataRole.UserRole, str(fid))
            self._table.setItem(i, 0, it)
            scope_it = QTableWidgetItem(str(scope))
            scope_it.setForeground(QGuiApplication.palette().mid())
            self._table.setItem(i, 1, scope_it)
            when_it = QTableWidgetItem(str(when)[:19].replace("T", " "))
            when_it.setForeground(QGuiApplication.palette().mid())
            self._table.setItem(i, 2, when_it)

        # Enable/disable mutators based on cloud reachability.
        can_mutate = bool(cc and getattr(cc, "list_memory_facts", None))
        for b in (self._add_btn, self._edit_btn, self._forget_btn):
            b.setEnabled(can_mutate)
        if not can_mutate:
            self._banner.setText(
                "Cloud unreachable — Add / Edit / Forget disabled. "
                "Sign in to your cloud relay to manage facts."
            )

    def _selected_id(self) -> str:
        row = self._table.currentRow()
        if row < 0:
            return ""
        it = self._table.item(row, 0)
        return (it.data(Qt.ItemDataRole.UserRole) if it else "") or ""

    def _on_add(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self, "Add memory fact",
            "What should ArchHub remember?"
        )
        if not ok or not text.strip():
            return
        cc = _cloud_client()
        fn = getattr(cc, "add_memory_fact", None) if cc else None
        if not callable(fn):
            via = _bridge_call(self._parent_dlg, "add_memory_fact",
                               text.strip(), "user", default=None)
            if via is None:
                QMessageBox.warning(self, "Memory", "Add endpoint unavailable.")
                return
        else:
            try:
                fn(text.strip())
            except Exception as ex:
                QMessageBox.warning(self, "Memory", f"Add failed: {ex}")
        self.refresh()

    def _on_edit(self) -> None:
        fid = self._selected_id()
        if not fid:
            return
        row = self._table.currentRow()
        current = self._table.item(row, 0).text() if self._table.item(row, 0) else ""
        text, ok = QInputDialog.getMultiLineText(
            self, "Edit memory fact", "Updated text:", current
        )
        if not ok:
            return
        cc = _cloud_client()
        fn = getattr(cc, "update_memory_fact", None) if cc else None
        if callable(fn):
            try:
                fn(fid, text.strip())
            except Exception as ex:
                QMessageBox.warning(self, "Memory", f"Update failed: {ex}")
        else:
            _bridge_call(self._parent_dlg, "update_memory_fact",
                         fid, text.strip(), default=None)
        self.refresh()

    def _on_forget(self) -> None:
        fid = self._selected_id()
        if not fid:
            return
        if QMessageBox.question(
            self, "Forget fact?",
            "Forget the selected memory fact?",
        ) != QMessageBox.StandardButton.Yes:
            return
        cc = _cloud_client()
        fn = (getattr(cc, "delete_memory_fact", None)
              or getattr(cc, "forget_memory_fact", None)
              if cc else None)
        if callable(fn):
            try:
                fn(fid)
            except Exception as ex:
                QMessageBox.warning(self, "Memory", f"Delete failed: {ex}")
        else:
            _bridge_call(self._parent_dlg, "forget_memory_fact", fid, default=None)
        self.refresh()


# ── Tab: Permissions ─────────────────────────────────────────────────────
class PermissionsTab(QWidget):
    """Per-tool AUTO / ASK / BLOCK policy matrix.

    Pulled from `ai_behaviour.tools_grouped_by_host()` so it stays in
    sync with the active tool registry — new connectors light up here
    automatically on the next dialog open."""

    POLICY_LABELS = [("Auto", "allow"), ("Ask", "ask"), ("Block", "deny")]
    # Bridge `get_permissions` uses (auto / ask / block); we accept both
    # name systems and normalise on save.
    POLICY_ALIASES = {"allow": "auto", "deny": "block"}

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Permissions",
                    "Decide which tool calls run silently, prompt, or are "
                    "blocked. Defaults are sane (writes ask, reads auto).",
                    scope="USER")

        # Thinking effort lives in the same neighbourhood — the model's
        # reasoning depth is also a "behaviour" knob.
        eff_grp = QGroupBox("Reasoning budget")
        eg = QVBoxLayout(eff_grp); eg.setSpacing(8); eg.setContentsMargins(12, 18, 12, 12)
        eff_help = QLabel(
            "Controls extended thinking for models that support it (Claude, "
            "GPT-o, Gemini). Off = fastest and cheapest; High = deepest."
        )
        eff_help.setObjectName("muted"); eff_help.setWordWrap(True)
        eg.addWidget(eff_help)
        self._effort = QComboBox()
        for label, val in (
            ("Off — fastest, cheapest",                  "off"),
            ("Low — quick reasoning (~1k tokens)",       "low"),
            ("Medium — balanced (~4k tokens)",           "medium"),
            ("High — deepest (~16k tokens)",             "high"),
        ):
            self._effort.addItem(label, val)
        try:
            import ai_behaviour as _aib
            cur = _aib.get_thinking_effort() or "off"
        except Exception:
            cur = "off"
        idx = self._effort.findData(cur)
        if idx >= 0:
            self._effort.setCurrentIndex(idx)
        self._effort.currentIndexChanged.connect(self._on_effort_changed)
        eg.addWidget(self._effort)
        outer.addWidget(eff_grp)

        # Tool table — scrollable group.
        tools_grp = QGroupBox("Tool policies")
        tg = QVBoxLayout(tools_grp); tg.setSpacing(6); tg.setContentsMargins(12, 18, 12, 12)

        self._table = _make_table(["Tool", "Host", "Policy"])
        tg.addWidget(self._table, 1)
        outer.addWidget(tools_grp, 1)

        br = QHBoxLayout()
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._on_reset)
        br.addStretch(1); br.addWidget(reset_btn)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        br.addWidget(refresh_btn)
        outer.addLayout(br)

        self.refresh()

    def _on_effort_changed(self, _i: int) -> None:
        try:
            import ai_behaviour as _aib
            _aib.set_thinking_effort(self._effort.currentData() or "off")
        except Exception:
            pass

    def refresh(self) -> None:
        # Source of truth is ai_behaviour.tools_grouped_by_host; the
        # bridge.get_permissions slot returns a flat list which we use
        # as fallback when ai_behaviour isn't importable in tests.
        try:
            import ai_behaviour as _aib
            grouped = _aib.tools_grouped_by_host() or {}
        except Exception:
            grouped = {}

        rows: list[tuple[str, str, str, str]] = []  # (tool_id, name, family, policy)
        if grouped:
            for fam, tools in grouped.items():
                fam_label = _safe(lambda: __import__("ai_behaviour").host_display_label(fam),
                                  default=fam) or fam
                for t in tools:
                    rows.append((
                        t["name"],
                        t["name"].split("_", 1)[-1] if "_" in t["name"] else t["name"],
                        fam_label,
                        t.get("policy", "allow"),
                    ))
        else:
            via = _bridge_call(self._parent_dlg, "get_permissions", default=[]) or []
            if isinstance(via, list):
                for t in via:
                    if not isinstance(t, dict):
                        continue
                    rows.append((
                        str(t.get("id", "")),
                        str(t.get("label") or t.get("id", "")),
                        str(t.get("sub", "")),
                        str(t.get("mode", "ask")),
                    ))

        self._table.setRowCount(len(rows))
        for i, (tool_id, label, family, policy) in enumerate(rows):
            name_item = QTableWidgetItem(label)
            name_item.setData(Qt.ItemDataRole.UserRole, tool_id)
            name_item.setToolTip(tool_id)
            self._table.setItem(i, 0, name_item)
            fam_item = QTableWidgetItem(family)
            fam_item.setForeground(_qbrush(TOKENS["muted"]))
            self._table.setItem(i, 1, fam_item)
            combo = QComboBox()
            for txt, val in self.POLICY_LABELS:
                combo.addItem(txt, val)
            # Accept both 'allow/deny' and 'auto/block' names.
            cur = policy
            for j in range(combo.count()):
                if combo.itemData(j) == cur:
                    combo.setCurrentIndex(j); break
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, tid=tool_id: self._on_policy_changed(tid, c)
            )
            self._table.setCellWidget(i, 2, combo)

    def _on_policy_changed(self, tool_id: str, combo: QComboBox) -> None:
        new = combo.currentData() or "allow"
        # ai_behaviour uses allow/ask/deny vocab. Save through it so we
        # don't fork persistence; the bridge maps the names internally.
        try:
            import ai_behaviour as _aib
            _aib.set_tool_policy(tool_id, new)
        except Exception:
            mapped = self.POLICY_ALIASES.get(new, new)
            _bridge_call(self._parent_dlg, "set_permission", tool_id, mapped,
                         default=None)

    def _on_reset(self) -> None:
        if QMessageBox.question(
            self, "Reset permissions?",
            "Restore every tool to its default policy?",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            import ai_behaviour as _aib
            _aib.reset_tool_policies()
        except Exception:
            save_setting("tool_policies", {})
        self.refresh()


# ── Tab: Storage ─────────────────────────────────────────────────────────
class StorageTab(QWidget):
    """Real disk usage + the buttons every user expects to find here."""

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Storage",
                    "Local-first — everything lives under "
                    "<code>%LOCALAPPDATA%\\ArchHub</code>. Nothing is "
                    "uploaded unless you sign in to a cloud relay.",
                    scope="DEVICE")

        # Usage list.
        usage_grp = QGroupBox("Disk usage")
        ug = QVBoxLayout(usage_grp); ug.setSpacing(6); ug.setContentsMargins(12, 18, 12, 12)
        self._usage = QListWidget(); self._usage.setAlternatingRowColors(True)
        self._usage.setStyleSheet(f"font-family: {TOKENS['mono']};")
        ug.addWidget(self._usage)
        outer.addWidget(usage_grp)

        # Open-folder buttons.
        of_grp = QGroupBox("Open in Explorer")
        og = QHBoxLayout(of_grp); og.setSpacing(8); og.setContentsMargins(12, 18, 12, 12)
        for kind, label in (
            ("sessions",     "Sessions"),
            ("skills",       "Skills"),
            ("custom_nodes", "Custom nodes"),
            ("app",          "App folder"),
            ("logs",         "Logs"),
        ):
            b = QPushButton(label)
            b.clicked.connect(lambda _, k=kind: self._open(k))
            og.addWidget(b)
        og.addStretch(1)
        outer.addWidget(of_grp)

        # Export.
        exp_grp = QGroupBox("Backup")
        eg = QVBoxLayout(exp_grp); eg.setSpacing(6); eg.setContentsMargins(12, 18, 12, 12)
        help_e = QLabel(
            "Zip sessions, skills, custom nodes and your profile into "
            "<code>~/Downloads/archhub-export-{timestamp}.zip</code>. "
            "Drag-drop the zip back onto ArchHub to restore."
        )
        help_e.setObjectName("muted"); help_e.setWordWrap(True)
        eg.addWidget(help_e)
        export_row = QHBoxLayout()
        self._export_btn = QPushButton("Export everything to zip")
        self._export_btn.setObjectName("primary")
        self._export_btn.clicked.connect(self._on_export)
        export_row.addStretch(1); export_row.addWidget(self._export_btn)
        eg.addLayout(export_row)
        outer.addWidget(exp_grp)

        # Danger zone.
        dz = QGroupBox("Danger zone")
        dg = QVBoxLayout(dz); dg.setSpacing(8); dg.setContentsMargins(12, 18, 12, 12)
        dg.addWidget(self._danger_row(
            "Clear model cache",
            "Free disk used by cached LLM responses. Won't affect saved sessions.",
            self._on_clear_cache,
        ))
        dg.addWidget(self._danger_row(
            "Forget all memory",
            "Wipes every memory fact (local + cloud). Sessions are untouched.",
            self._on_forget_memory,
        ))
        dg.addWidget(self._danger_row(
            "Delete all sessions",
            "Permanently removes every saved canvas. There is no undo.",
            self._on_delete_sessions,
        ))
        outer.addWidget(dz)

        refresh_row = QHBoxLayout()
        rb = QPushButton("Refresh")
        rb.clicked.connect(self.refresh)
        refresh_row.addStretch(1); refresh_row.addWidget(rb)
        outer.addLayout(refresh_row)

        outer.addStretch(1)
        self.refresh()

    def _danger_row(self, label: str, blurb: str, on_click) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {TOKENS['card']}; "
            f"border: 1px solid {TOKENS['border']}; border-radius: 6px; }}"
        )
        rl = QHBoxLayout(row); rl.setContentsMargins(12, 10, 12, 10); rl.setSpacing(10)
        col = QVBoxLayout(); col.setSpacing(2)
        l1 = QLabel(label); l1.setStyleSheet("font-weight: 600;")
        l2 = QLabel(blurb); l2.setObjectName("muted"); l2.setWordWrap(True)
        col.addWidget(l1); col.addWidget(l2)
        rl.addLayout(col, 1)
        btn = QPushButton(label); btn.setObjectName("danger")
        btn.clicked.connect(on_click)
        rl.addWidget(btn)
        return row

    def refresh(self) -> None:
        stats = _bridge_call(self._parent_dlg, "get_storage_stats", default={}) or {}
        self._usage.clear()
        if not isinstance(stats, dict) or stats.get("error"):
            self._usage.addItem(QListWidgetItem(
                "Storage stats unavailable. Run ArchHub once to seed paths."
            ))
            return
        total = int(stats.get("total_bytes") or 0)
        for key, label in (
            ("sessions",     "Sessions"),
            ("skills",       "Skills"),
            ("custom_nodes", "Custom nodes"),
            ("app",          "App data"),
        ):
            blob = stats.get(key) or {}
            if not isinstance(blob, dict):
                blob = {}
            cnt = int(blob.get("count") or 0)
            byt = int(blob.get("bytes") or 0)
            path = str(blob.get("path") or "")
            item = QListWidgetItem(
                f"{label:<14}  {cnt:>5} files  {_fmt_bytes(byt):>10}    {path}"
            )
            self._usage.addItem(item)
        total_item = QListWidgetItem(f"{'TOTAL':<14}  {'':>5}        {_fmt_bytes(total):>10}")
        total_item.setForeground(_qbrush(TOKENS["accent"]))
        self._usage.addItem(total_item)

    def _open(self, kind: str) -> None:
        res = _bridge_call(self._parent_dlg, "open_folder", kind, default={}) or {}
        if isinstance(res, dict) and res.get("error"):
            # Bridge couldn't open — fall back to a direct startfile.
            try:
                p = _local_appdata()
                if kind != "app":
                    p = p / kind
                p.mkdir(parents=True, exist_ok=True)
                os.startfile(str(p))  # type: ignore[attr-defined]
            except Exception as ex:
                QMessageBox.warning(self, "Open folder", f"Could not open: {ex}")

    def _on_export(self) -> None:
        self._export_btn.setEnabled(False)
        self._export_btn.setText("Exporting…")
        QApplication.processEvents()
        try:
            res = _bridge_call(self._parent_dlg, "export_all", default={}) or {}
            if isinstance(res, dict) and res.get("ok") and res.get("path"):
                QMessageBox.information(
                    self, "Export complete",
                    f"Saved to:\n{res['path']}\n\n"
                    f"Size: {_fmt_bytes(int(res.get('size') or 0))}",
                )
            else:
                msg = res.get("error", "unknown error") if isinstance(res, dict) else "no bridge"
                QMessageBox.warning(self, "Export", f"Export failed: {msg}")
        finally:
            self._export_btn.setEnabled(True)
            self._export_btn.setText("Export everything to zip")

    def _on_clear_cache(self) -> None:
        if QMessageBox.question(
            self, "Clear model cache?",
            "Remove cached LLM responses? Saved sessions are untouched.",
        ) != QMessageBox.StandardButton.Yes:
            return
        res = _bridge_call(self._parent_dlg, "clear_model_cache", default={}) or {}
        freed = int((res or {}).get("freed_bytes") or 0)
        QMessageBox.information(self, "Model cache",
                                f"Freed {_fmt_bytes(freed)}.")
        self.refresh()

    def _on_forget_memory(self) -> None:
        if QMessageBox.question(
            self, "Forget all memory?",
            "Wipe every memory fact (local cache + cloud). Sessions stay.",
        ) != QMessageBox.StandardButton.Yes:
            return
        _bridge_call(self._parent_dlg, "forget_all_memory", default=None)
        QMessageBox.information(self, "Memory", "Memory cleared.")
        self.refresh()

    def _on_delete_sessions(self) -> None:
        if QMessageBox.question(
            self, "Delete all sessions?",
            "This permanently removes every saved canvas. There is no undo.",
        ) != QMessageBox.StandardButton.Yes:
            return
        res = _bridge_call(self._parent_dlg, "delete_all_sessions", default={}) or {}
        deleted = int((res or {}).get("deleted") or 0)
        QMessageBox.information(self, "Sessions",
                                f"Deleted {deleted} session(s).")
        self.refresh()


# ── Tab: Shortcuts ───────────────────────────────────────────────────────
class ShortcutsTab(QWidget):
    """Read-only keybindings reference. Mirrors studio-lm.jsx."""

    SHORTCUTS = [
        ("Canvas", [("Open palette", "Ctrl+K"), ("New session", "Ctrl+N"),
                    ("Open settings", "Ctrl+,"), ("Pan canvas", "drag empty"),
                    ("Zoom canvas", "Ctrl + scroll"), ("Fit to view", "Ctrl+0")]),
        ("Nodes",  [("Run focused node", "Ctrl+Enter"),
                    ("Add node — library", "Ctrl+L"),
                    ("Branch from message", "Alt+B"),
                    ("Save as Skill", "Ctrl+Shift+S")]),
        ("Chat",   [("Switch model", "Ctrl+M"), ("Toggle reasoning", "Alt+R"),
                    ("Toggle HUD mode", "Ctrl+Space"), ("Collapse HUD", "Esc")]),
    ]

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Shortcuts",
                    "The keys that matter. Custom bindings ship in a later "
                    "release — for now this is the canon.",
                    scope="USER")

        mono = QFont(); mono.setFamily("JetBrains Mono"); mono.setPointSize(10)
        for group_label, items in self.SHORTCUTS:
            grp = QGroupBox(group_label)
            g = QVBoxLayout(grp); g.setSpacing(0); g.setContentsMargins(12, 18, 12, 12)
            tbl = _make_table(["Action", "Keys"])
            tbl.setRowCount(len(items))
            tbl.setShowGrid(False)
            tbl.setFixedHeight(28 + len(items) * 26)
            for i, (action, key) in enumerate(items):
                tbl.setItem(i, 0, QTableWidgetItem(action))
                key_item = QTableWidgetItem(key)
                key_item.setFont(mono)
                tbl.setItem(i, 1, key_item)
            g.addWidget(tbl)
            outer.addWidget(grp)

        outer.addStretch(1)


# ── Tab: About ───────────────────────────────────────────────────────────
class AboutTab(QWidget):
    """Version, build SHA, runtime, server, license, links."""

    # Marketing pages (archhub.io/docs etc.) were never built — point
    # straight at the open-source repo, which is the real source of
    # truth and definitely resolves. Repo is github.com/Fargaly/ArchHub.
    LINKS = [
        ("Docs",          "https://github.com/Fargaly/ArchHub/tree/main/docs"),
        ("Changelog",     "https://github.com/Fargaly/ArchHub/blob/main/CHANGELOG.md"),
        ("Report a bug",  "https://github.com/Fargaly/ArchHub/issues"),
    ]

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "About",
                    "What ArchHub is running, where to file issues, who owns "
                    "the data. Select any value to copy it.",
                    scope="DEVICE")

        # Build / runtime panel.
        info_grp = QGroupBox("Build")
        ig = QFormLayout(info_grp); ig.setSpacing(8); ig.setContentsMargins(12, 18, 12, 12)
        version = _read_version()
        sha = _read_git_sha() or "—"
        py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        try:
            import PyQt6  # noqa
            from PyQt6.QtCore import QT_VERSION_STR as _qt_v
            qt_v = _qt_v
        except Exception:
            qt_v = "—"
        platform = sys.platform
        for label, value in (
            ("Version",   version),
            ("Build",     sha),
            ("Python",    py),
            ("Qt",        qt_v),
            ("Platform",  platform),
            ("Install",   str(_local_appdata())),
        ):
            v_lbl = QLabel(str(value)); v_lbl.setObjectName("mono")
            v_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            ig.addRow(label + " ", v_lbl)
        outer.addWidget(info_grp)

        # Server / relay panel.
        srv_grp = QGroupBox("Cloud relay")
        sg = QFormLayout(srv_grp); sg.setSpacing(8); sg.setContentsMargins(12, 18, 12, 12)
        relay_url = load_setting("relay_base_url") or "—"
        cloud_state = _bridge_call(self._parent_dlg, "get_provider_stats", default={}) or {}
        configured = int((cloud_state or {}).get("configured", 0) or 0)
        for label, value in (
            ("Relay URL",          str(relay_url)),
            ("Providers signed in", str(configured)),
        ):
            v_lbl = QLabel(str(value)); v_lbl.setObjectName("mono")
            v_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            sg.addRow(label + " ", v_lbl)
        outer.addWidget(srv_grp)

        # License + links.
        lic_grp = QGroupBox("License & links")
        lg = QVBoxLayout(lic_grp); lg.setSpacing(8); lg.setContentsMargins(12, 18, 12, 12)
        lic = QLabel(
            "ArchHub is dual-licensed: <b>Apache-2.0</b> for the open "
            "core (canvas, runtime, host connectors), commercial for the "
            "managed cloud relay. Bring your own keys — there is no lock-in."
        )
        lic.setWordWrap(True)
        lg.addWidget(lic)
        link_row = QHBoxLayout(); link_row.setSpacing(6)
        for label, url in self.LINKS:
            b = QPushButton(label)
            b.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            link_row.addWidget(b)
        link_row.addStretch(1)
        lg.addLayout(link_row)
        outer.addWidget(lic_grp)

        outer.addStretch(1)


# ── Tab: Brain (AgDR-0044 · personal-brain-mcp) ──────────────────────────
class BrainTab(QWidget):
    """Native Qt brain settings — daemon status · firm identity · invite
    flow · seats list · communities · tuning. Replaces the JSX
    BrainSection (which lived in the fallback modal that never opens).

    All MCP calls hit the local daemon at http://127.0.0.1:8473/mcp via
    stateless HTTP — the same wire Layer 5 uses. Timeout-bounded so a
    dead daemon never blocks the UI thread.
    """

    DAEMON_URL = "http://127.0.0.1:8473/mcp"

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Brain",
                    "Shared memory + skills + setups across every AI you use. "
                    "Lives in a local daemon (port 8473) that ArchHub talks to "
                    "and that survives ArchHub being closed.",
                    scope="FIRM")

        # ── status card ──────────────────────────────────────────────
        st = QGroupBox("Status")
        sv = QVBoxLayout(st); sv.setSpacing(8); sv.setContentsMargins(12, 18, 12, 12)
        status_row = QHBoxLayout(); status_row.setSpacing(10)
        self._pulse = QLabel("●"); self._pulse.setObjectName("muted")
        self._pulse.setStyleSheet("font-size:14px;")
        self._status_text = QLabel("probing daemon…")
        self._status_text.setObjectName("muted")
        status_row.addWidget(self._pulse)
        status_row.addWidget(self._status_text, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        status_row.addWidget(refresh_btn)
        sv.addLayout(status_row)

        # Stat tiles row
        tiles = QHBoxLayout(); tiles.setSpacing(8)
        self._tile_skills = self._make_tile("Skills", "—")
        self._tile_facts = self._make_tile("Facts", "—")
        self._tile_wirings = self._make_tile("MCPs", "—")
        self._tile_lastmint = self._make_tile("Last mint", "—")
        for t in (self._tile_skills, self._tile_facts, self._tile_wirings, self._tile_lastmint):
            tiles.addWidget(t)
        sv.addLayout(tiles)

        # db path label
        self._db_path = QLabel("db_path: —")
        self._db_path.setObjectName("mono")
        self._db_path.setWordWrap(True)
        sv.addWidget(self._db_path)
        outer.addWidget(st)

        # ── firm card ─────────────────────────────────────────────────
        fm = QGroupBox("Firm")
        fv = QVBoxLayout(fm); fv.setSpacing(10); fv.setContentsMargins(12, 18, 12, 12)

        self._firm_label = QLabel("No firm yet")
        self._firm_label.setStyleSheet(f"color:{TOKENS['muted']};")
        fv.addWidget(self._firm_label)

        # Create-firm row
        create_row = QHBoxLayout(); create_row.setSpacing(6)
        self._create_name = QLineEdit()
        self._create_name.setPlaceholderText("Firm name (e.g. ArchHub Studio)")
        self._create_btn = QPushButton("Create firm")
        self._create_btn.setObjectName("primary")
        self._create_btn.clicked.connect(self._on_create_firm)
        create_row.addWidget(self._create_name, 1)
        create_row.addWidget(self._create_btn)
        self._create_row_widget = QWidget()
        self._create_row_widget.setLayout(create_row)
        fv.addWidget(self._create_row_widget)

        # Join-firm row
        join_row = QHBoxLayout(); join_row.setSpacing(6)
        self._join_token = QLineEdit()
        self._join_token.setPlaceholderText("Paste invite token to join an existing firm")
        self._join_btn = QPushButton("Join")
        self._join_btn.clicked.connect(self._on_join_firm)
        join_row.addWidget(self._join_token, 1)
        join_row.addWidget(self._join_btn)
        self._join_row_widget = QWidget()
        self._join_row_widget.setLayout(join_row)
        fv.addWidget(self._join_row_widget)

        # Invite-create row (shown when in firm as admin)
        invite_row = QHBoxLayout(); invite_row.setSpacing(6)
        self._invite_btn = QPushButton("Create invite token (24h)")
        self._invite_btn.setObjectName("primary")
        self._invite_btn.clicked.connect(self._on_create_invite)
        self._invite_btn.setVisible(False)
        self._leave_btn = QPushButton("Leave firm")
        self._leave_btn.clicked.connect(self._on_leave_firm)
        self._leave_btn.setVisible(False)
        invite_row.addWidget(self._invite_btn)
        invite_row.addWidget(self._leave_btn)
        invite_row.addStretch(1)
        self._invite_row_widget = QWidget()
        self._invite_row_widget.setLayout(invite_row)
        fv.addWidget(self._invite_row_widget)

        # Invite token preview
        self._invite_preview = QLabel("")
        self._invite_preview.setObjectName("mono")
        self._invite_preview.setWordWrap(True)
        self._invite_preview.setVisible(False)
        self._invite_preview.setStyleSheet(
            f"border:1px dashed {TOKENS['accent']}; padding:8px; "
            f"border-radius:6px; background:{TOKENS['bg']}; "
            f"color:{TOKENS['text']}; font-family:{TOKENS['mono']};"
        )
        fv.addWidget(self._invite_preview)
        self._copy_invite_btn = QPushButton("Copy token")
        self._copy_invite_btn.setVisible(False)
        self._copy_invite_btn.clicked.connect(self._on_copy_invite)
        fv.addWidget(self._copy_invite_btn)

        # Seats list
        seats_label = QLabel("Seats")
        seats_label.setStyleSheet(f"color:{TOKENS['muted']}; padding-top:6px;")
        fv.addWidget(seats_label)
        self._seats_list = QListWidget()
        self._seats_list.setMaximumHeight(110)
        fv.addWidget(self._seats_list)

        outer.addWidget(fm)

        # ── communities card ────────────────────────────────────────
        cm = QGroupBox("Communities")
        cv = QVBoxLayout(cm); cv.setSpacing(8); cv.setContentsMargins(12, 18, 12, 12)
        sub_row = QHBoxLayout(); sub_row.setSpacing(6)
        self._sub_url = QLineEdit()
        self._sub_url.setPlaceholderText("Peer firm outbox URL (e.g. https://peer.example/actor)")
        self._sub_btn = QPushButton("Subscribe")
        self._sub_btn.clicked.connect(self._on_subscribe)
        sub_row.addWidget(self._sub_url, 1)
        sub_row.addWidget(self._sub_btn)
        cv.addLayout(sub_row)
        self._comm_list = QListWidget()
        self._comm_list.setMaximumHeight(90)
        cv.addWidget(self._comm_list)
        outer.addWidget(cm)

        # ── connected agents card ──────────────────────────────────
        ag = QGroupBox("Connected agents")
        av = QVBoxLayout(ag); av.setSpacing(6); av.setContentsMargins(12, 18, 12, 12)
        ag_hint = QLabel(
            "Each agent's config is scanned for a <code>personal-brain</code> "
            "MCP entry. <b>wired</b> = the agent fires brain.context on every "
            "prompt; <b>unwired</b> = installed but not yet routed; "
            "<b>not detected</b> = no config on this device."
        )
        ag_hint.setObjectName("muted"); ag_hint.setWordWrap(True)
        av.addWidget(ag_hint)
        self._agent_list = QListWidget()
        self._agent_list.setStyleSheet(
            f"QListWidget {{ background:{TOKENS['bg']}; "
            f"border:1px solid {TOKENS['border']}; border-radius:6px; }}"
        )
        self._agent_list.setMinimumHeight(170)
        av.addWidget(self._agent_list)

        ag_btn_row = QHBoxLayout(); ag_btn_row.setSpacing(6)
        self._chatgpt_setup_btn = QPushButton("Set up ChatGPT desktop…")
        self._chatgpt_setup_btn.clicked.connect(self._on_chatgpt_setup)
        rescan_btn = QPushButton("Rescan agents")
        rescan_btn.clicked.connect(self._render_agents)
        ag_btn_row.addWidget(self._chatgpt_setup_btn)
        ag_btn_row.addStretch(1)
        ag_btn_row.addWidget(rescan_btn)
        av.addLayout(ag_btn_row)
        outer.addWidget(ag)

        # ── tuning & safety card ────────────────────────────────────
        tn = QGroupBox("Tuning & safety")
        tv = QVBoxLayout(tn); tv.setSpacing(8); tv.setContentsMargins(12, 18, 12, 12)
        tn_hint = QLabel(
            "R1–R4 are the four reliability rails described in "
            "<code>personal-brain-mcp/src/personal_brain</code>. Defaults are "
            "ON — turn off only if a rail is misbehaving. State is persisted "
            "to <code>%LOCALAPPDATA%/ArchHub/brain/tuning.json</code>."
        )
        tn_hint.setObjectName("muted"); tn_hint.setWordWrap(True)
        tv.addWidget(tn_hint)
        tuning = _load_brain_tuning()
        self._tune_r1 = QCheckBox("R1 · Adaptive skill-mint floor (calibration.py)")
        self._tune_r2 = QCheckBox("R2 · Echo Trap defense (exploration.py)")
        self._tune_r3 = QCheckBox("R3 · Resilience wrapper (liveness.py)")
        self._tune_r4 = QCheckBox("R4 · Bayesian reputation (reputation.py)")
        for cb, key in (
            (self._tune_r1, "r1_calibration"),
            (self._tune_r2, "r2_echo_trap"),
            (self._tune_r3, "r3_resilience"),
            (self._tune_r4, "r4_reputation"),
        ):
            # Default ON per founder spec.
            cb.setChecked(bool(tuning.get(key, True)))
            cb.toggled.connect(
                lambda v, k=key: self._persist_tuning(k, bool(v))
            )
            tv.addWidget(cb)

        critic_row = QHBoxLayout(); critic_row.setSpacing(8)
        critic_lbl = QLabel("LLM critic:")
        self._critic_pick = QComboBox()
        for label, val in (
            ("Heuristic (zero LLM)",          "heuristic"),
            ("Anthropic claude-sonnet-4-6",   "anthropic"),
            ("OpenAI gpt-5",                   "openai"),
            ("Hybrid (heuristic ratify, LLM refine)", "hybrid"),
        ):
            self._critic_pick.addItem(label, val)
        cur = tuning.get("llm_critic") or "anthropic"
        idx = self._critic_pick.findData(cur)
        if idx >= 0:
            self._critic_pick.setCurrentIndex(idx)
        self._critic_pick.currentIndexChanged.connect(
            lambda _i: self._persist_tuning(
                "llm_critic", self._critic_pick.currentData() or "heuristic"
            )
        )
        critic_row.addWidget(critic_lbl)
        critic_row.addWidget(self._critic_pick, 1)
        tv.addLayout(critic_row)
        outer.addWidget(tn)

        # ── danger card (red border, bottom) ───────────────────────
        dz = QGroupBox("Danger zone")
        dz.setStyleSheet(
            f"QGroupBox {{ background:{TOKENS['card']}; "
            f"border:1px solid {TOKENS['bad']}; border-radius:10px; "
            f"margin-top:14px; padding:14px 12px 10px 12px; "
            f"color:{TOKENS['text']}; }}"
            f"QGroupBox::title {{ subcontrol-origin:margin; "
            f"subcontrol-position:top left; left:10px; padding:0 6px; "
            f"color:{TOKENS['bad']}; font-weight:600; }}"
        )
        dv = QVBoxLayout(dz); dv.setSpacing(8); dv.setContentsMargins(12, 18, 12, 12)
        dv.addWidget(self._danger_row(
            "Export brain",
            "Download the full SQLite + skill markdowns. Restorable on any device.",
            self._on_export_brain,
        ))
        dv.addWidget(self._danger_row(
            "Clear cache",
            "Wipes the resilient-client journal + cached context. Daemon untouched.",
            self._on_clear_brain_cache,
        ))
        dv.addWidget(self._danger_row(
            "Reset brain",
            "Wipes everything. Skills, facts, wiring, secrets refs, audit log. Cannot be undone.",
            self._on_reset_brain,
        ))
        outer.addWidget(dz)

        # Footer hint
        hint = QLabel(
            "All actions hit the local brain daemon at "
            "<code>127.0.0.1:8473/mcp</code>. If the status is offline, "
            "the daemon isn't running."
        )
        hint.setObjectName("muted"); hint.setWordWrap(True)
        outer.addWidget(hint)

        outer.addStretch(1)

        # Probe on construction
        self._render_agents()
        self._refresh()

    # ── widgets ──────────────────────────────────────────────────────

    def _make_tile(self, label: str, value: str) -> QWidget:
        w = QFrame()
        w.setStyleSheet(
            f"background:{TOKENS['card']}; border:1px solid {TOKENS['border']}; "
            f"border-radius:8px; padding:10px;"
        )
        lv = QVBoxLayout(w); lv.setContentsMargins(8, 6, 8, 6); lv.setSpacing(2)
        value_lbl = QLabel(value)
        value_lbl.setStyleSheet("font-size:22px; font-weight:600;")
        label_lbl = QLabel(label)
        label_lbl.setObjectName("muted")
        label_lbl.setStyleSheet("font-size:10px; letter-spacing:0.08em; text-transform:uppercase;")
        lv.addWidget(value_lbl); lv.addWidget(label_lbl)
        # Cache the value label so we can update later
        w._value_lbl = value_lbl  # type: ignore[attr-defined]
        return w

    # ── HTTP helpers ─────────────────────────────────────────────────

    def _mcp_call(self, tool: str, args: dict | None = None,
                  *, timeout: float = 2.0) -> dict:
        """POST a tools/call to the brain daemon. Returns the parsed
        structuredContent (or {'ok': False, 'error': ...} on failure).
        Timeout-bounded so a dead daemon never freezes the dialog."""
        import urllib.error
        import urllib.request
        import json as _json
        import time as _time
        body = _json.dumps({
            "jsonrpc": "2.0", "id": int(_time.time() * 1000),
            "method": "tools/call",
            "params": {"name": tool, "arguments": args or {}},
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                self.DAEMON_URL, data=body, method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError,
                 TimeoutError, OSError) as ex:
            return {"ok": False, "error": f"daemon unreachable: {ex}"}

        # SSE parse
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                obj = _json.loads(line[5:].strip())
            except _json.JSONDecodeError:
                continue
            result = obj.get("result") or {}
            if isinstance(result, dict):
                sc = result.get("structuredContent")
                if sc is not None:
                    return sc
                content = result.get("content") or []
                if content and isinstance(content[0], dict):
                    txt = content[0].get("text", "")
                    try:
                        return _json.loads(txt)
                    except Exception:
                        return {"ok": False, "text": txt}
            return result
        return {"ok": False, "error": "no SSE data line in response"}

    # ── refresh / render ─────────────────────────────────────────────

    def _refresh(self) -> None:
        """Pull health + firm seats + (TODO) communities. Update UI."""
        # 1. health
        health = self._mcp_call("brain.health", {})
        if health.get("ok"):
            self._pulse.setText("●")
            self._pulse.setStyleSheet(f"font-size:14px; color:{TOKENS['good']};")
            self._status_text.setText(
                f"LIVE · daemon v{health.get('version', '?')} · "
                f"{health.get('skills', 0)} skills · {health.get('facts', 0)} facts"
            )
            self._status_text.setStyleSheet(f"color:{TOKENS['good']};")
            self._db_path.setText(f"db_path: {health.get('db_path', '—')}")
            self._tile_skills._value_lbl.setText(str(health.get("skills", 0)))
            self._tile_facts._value_lbl.setText(str(health.get("facts", 0)))
            self._tile_wirings._value_lbl.setText(str(health.get("wiring_active", 0)))
        else:
            self._pulse.setText("●")
            self._pulse.setStyleSheet(f"font-size:14px; color:{TOKENS['bad']};")
            err = health.get("error", "unknown")
            self._status_text.setText(f"OFFLINE — {err[:120]}")
            self._status_text.setStyleSheet(f"color:{TOKENS['bad']};")
            self._db_path.setText(
                "db_path: — (daemon down · run "
                "`personal-brain --http 8473` or restart ArchHub)"
            )
            return

        # 2. firm
        seats = self._mcp_call("brain.firm_seats", {})
        self._render_firm(seats)

    def _render_firm(self, seats_resp: dict) -> None:
        self._seats_list.clear()
        if not seats_resp.get("ok") or not seats_resp.get("firm_id"):
            # Not in any firm — show create/join rows, hide invite/leave
            self._firm_label.setText("No firm yet — create one or paste an invite token.")
            self._firm_label.setStyleSheet(f"color:{TOKENS['muted']};")
            self._create_row_widget.setVisible(True)
            self._join_row_widget.setVisible(True)
            self._invite_row_widget.setVisible(False)
            return

        firm_name = seats_resp.get("firm_name") or seats_resp.get("firm_id")
        firm_id = seats_resp.get("firm_id")
        self._firm_label.setText(
            f"<b>{firm_name}</b>   <span style='color:{TOKENS['muted']};'>{firm_id}</span>"
        )
        self._firm_label.setStyleSheet("")
        self._create_row_widget.setVisible(False)
        self._join_row_widget.setVisible(False)
        self._invite_row_widget.setVisible(True)

        for seat in seats_resp.get("seats", []) or []:
            user_id = seat.get("user_id", "?")
            role = seat.get("role", "seat")
            item = QListWidgetItem(f"{user_id}   ({role})")
            self._seats_list.addItem(item)

    # ── handlers ─────────────────────────────────────────────────────

    def _on_create_firm(self) -> None:
        name = (self._create_name.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "Firm name required",
                                 "Enter a firm name first.")
            return
        r = self._mcp_call("brain.firm_create", {"name": name})
        if r.get("ok"):
            QMessageBox.information(
                self, "Firm created",
                f"Firm '{r.get('name', name)}' created.\n"
                f"ID: {r.get('firm_id', '?')}\n\n"
                f"You are the admin · share invite tokens from this tab.",
            )
            self._refresh()
        else:
            QMessageBox.critical(self, "Create failed",
                                  r.get("error", "unknown error"))

    def _on_join_firm(self) -> None:
        token = (self._join_token.text() or "").strip()
        if not token:
            QMessageBox.warning(self, "Token required",
                                 "Paste an invite token first.")
            return
        r = self._mcp_call("brain.firm_invite_accept", {"token": token})
        if r.get("ok"):
            QMessageBox.information(
                self, "Joined firm",
                f"Joined firm {r.get('firm_id', '?')} as {r.get('role', 'seat')}",
            )
            self._join_token.clear()
            self._refresh()
        else:
            QMessageBox.critical(self, "Join failed",
                                  r.get("error", "unknown error"))

    def _on_create_invite(self) -> None:
        r = self._mcp_call("brain.firm_invite_create",
                            {"role": "seat", "ttl_hours": 24})
        if r.get("ok"):
            token = r.get("token", "")
            self._invite_preview.setText(token)
            self._invite_preview.setVisible(True)
            self._copy_invite_btn.setVisible(True)
        else:
            QMessageBox.critical(self, "Invite create failed",
                                  r.get("error", "unknown error"))

    def _on_copy_invite(self) -> None:
        QGuiApplication.clipboard().setText(self._invite_preview.text())
        QMessageBox.information(self, "Copied",
                                 "Invite token copied to clipboard.")

    def _on_leave_firm(self) -> None:
        reply = QMessageBox.question(
            self, "Leave firm",
            "Leave the current firm? Your local seat record is removed.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._mcp_call("brain.firm_leave", {})
        self._refresh()

    def _on_subscribe(self) -> None:
        url = (self._sub_url.text() or "").strip()
        if not url:
            QMessageBox.warning(self, "URL required",
                                 "Paste a peer firm outbox URL first.")
            return
        # Brain MCP doesn't yet expose community subscribe as a tool —
        # the community module is daemon-internal. Show a clear note
        # for now; Slice C wires this through.
        QMessageBox.information(
            self, "Subscribe (deferred)",
            f"Community subscribe to {url[:60]}… is wired in the "
            f"community module but not yet exposed as an MCP tool. "
            f"Tracked in the runtime queue; reachable via "
            f"`personal_brain.community.subscribe()` from the CLI.",
        )

    # ── connected agents ─────────────────────────────────────────────

    AGENT_SLUGS = (
        "claude_code", "cursor", "codex", "gemini",
        "archhub_composer", "chatgpt_desktop",
    )

    def _render_agents(self) -> None:
        """Re-scan each agent's config + repaint the list rows."""
        self._agent_list.clear()
        for slug in self.AGENT_SLUGS:
            info = _detect_brain_agent(slug)
            state = info.get("state", "not_detected")
            if state == "wired":
                badge = "wired"; colour = TOKENS["good"]
            elif state == "unwired":
                badge = "unwired"; colour = TOKENS["muted"]
            else:
                badge = "not detected"; colour = TOKENS["muted"]
            text = f"  {info['name']:<22}  {info['detail']:<50}  [{badge}]"
            item = QListWidgetItem(text)
            item.setForeground(_qbrush(colour))
            item.setToolTip(info.get("path", ""))
            self._agent_list.addItem(item)

    def _on_chatgpt_setup(self) -> None:
        """OAuth flow is deferred — show what's needed so the founder
        sees the gap honestly instead of clicking a button that lies."""
        QMessageBox.information(
            self, "ChatGPT desktop · setup deferred",
            "ChatGPT desktop requires:\n"
            "  • A public HTTPS endpoint pointing at the brain daemon\n"
            "  • OAuth 2.1 + PKCE registration with OpenAI\n"
            "  • Brain federation server running\n\n"
            "Tracked in the brain roadmap; OAuth path not yet wired. "
            "Other 5 agents (Claude Code, Cursor, Codex, Gemini, ArchHub "
            "Composer) connect directly with no OAuth.",
        )

    # ── tuning persistence ───────────────────────────────────────────

    def _persist_tuning(self, key: str, value) -> None:
        """First try the daemon (in case a future build exposes
        `brain.settings_set`). On failure, fall back to a local
        tuning.json — the founder still gets a working toggle."""
        try:
            r = self._mcp_call("brain.settings_set", {"key": key, "value": value})
        except Exception:
            r = {"ok": False}
        if r.get("ok"):
            return
        # Daemon doesn't expose a settings tool — keep local copy.
        data = _load_brain_tuning()
        data[key] = value
        _save_brain_tuning(data)

    # ── danger zone handlers ─────────────────────────────────────────

    def _danger_row(self, label: str, blurb: str, on_click) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background:{TOKENS['card']}; "
            f"border:1px solid {TOKENS['border']}; border-radius:6px; }}"
        )
        rl = QHBoxLayout(row); rl.setContentsMargins(12, 10, 12, 10); rl.setSpacing(10)
        col = QVBoxLayout(); col.setSpacing(2)
        l1 = QLabel(label); l1.setStyleSheet("font-weight:600;")
        l2 = QLabel(blurb); l2.setObjectName("muted"); l2.setWordWrap(True)
        col.addWidget(l1); col.addWidget(l2)
        rl.addLayout(col, 1)
        btn = QPushButton(label); btn.setObjectName("danger")
        btn.clicked.connect(on_click)
        rl.addWidget(btn)
        return row

    def _on_export_brain(self) -> None:
        # Try the daemon first; if no export tool, point at the SQLite
        # file location so the founder can grab it manually.
        r = self._mcp_call("brain.export", {})
        if r.get("ok") and r.get("path"):
            QMessageBox.information(
                self, "Brain export",
                f"Exported to:\n{r['path']}",
            )
            return
        db_hint = _local_appdata() / "brain" / "brain.db"
        QMessageBox.information(
            self, "Brain export",
            "Daemon doesn't expose a brain.export tool yet. The full "
            "SQLite file lives at:\n\n"
            f"  {db_hint}\n\n"
            "Copy it (and the skills/ markdown directory next to it) to "
            "back up your brain. Restore by stopping the daemon, replacing "
            "the file, and restarting.",
        )

    def _on_clear_brain_cache(self) -> None:
        if QMessageBox.question(
            self, "Clear brain cache?",
            "Wipe the resilient-client journal + cached context? "
            "The daemon and its DB are untouched.",
        ) != QMessageBox.StandardButton.Yes:
            return
        r = self._mcp_call("brain.cache_clear", {})
        if r.get("ok"):
            QMessageBox.information(self, "Brain cache",
                                     "Cache cleared.")
            return
        # No daemon tool — best-effort wipe of the local journal file.
        try:
            jrn = _local_appdata() / "brain" / "client_journal.jsonl"
            if jrn.is_file():
                jrn.unlink()
        except Exception:
            pass
        QMessageBox.information(self, "Brain cache",
                                 "Local cache cleared (daemon tool "
                                 "unavailable — wiped client journal).")

    def _on_reset_brain(self) -> None:
        if QMessageBox.question(
            self, "Reset brain?",
            "This wipes EVERYTHING — skills, facts, wiring, secrets refs, "
            "audit log. There is no undo. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        r = self._mcp_call("brain.reset", {"confirm": True})
        if r.get("ok"):
            QMessageBox.information(self, "Brain reset",
                                     "Brain wiped. Daemon restart recommended.")
            self._refresh()
            return
        QMessageBox.warning(
            self, "Brain reset (unavailable)",
            "Daemon doesn't expose a brain.reset tool. To wipe the "
            "brain manually: stop the daemon, delete "
            f"{_local_appdata() / 'brain' / 'brain.db'}, restart the "
            "daemon.",
        )


# ── Tab: Secrets & Keys ──────────────────────────────────────────────────
class SecretsTab(QWidget):
    """One table of every secret ArchHub references — resolver source +
    masked last-4 + Set / Replace + Test.

    Source of truth: secrets_store.load_api_key for known providers,
    environment variables for the rest. The brain mandate (CLAUDE.md
    line 425) says ArchHub stores `op://` references in the brain —
    never values. This tab makes that contract visible to the founder.
    """

    # (slug, label, env_var, kind) — kind drives the test probe
    KEY_ROWS = [
        ("openrouter",  "OpenRouter",        "OPENROUTER_API_KEY", "llm"),
        ("anthropic",   "Anthropic",         "ANTHROPIC_API_KEY",  "llm"),
        ("openai",      "OpenAI",            "OPENAI_API_KEY",     "llm"),
        ("google",      "Google",            "GOOGLE_API_KEY",     "llm"),
        ("speckle",     "Speckle token",     "SPECKLE_TOKEN",      "speckle"),
        ("github",      "GitHub PAT",        "GITHUB_TOKEN",       "github"),
        ("notion",      "Notion token",      "NOTION_TOKEN",       "notion"),
    ]

    COLS = ("Provider", "Source", "Value", "Actions")

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Keys & Secrets",
                    "Every credential ArchHub knows about — resolver source "
                    "and a masked last-4. Set a value inline, or paste an "
                    "<code>op://</code> reference to keep the value in your "
                    "secret manager.",
                    scope="DEVICE")

        # Banner — restates the brain mandate so the founder reads it
        # every time he opens this tab.
        banner = QLabel(
            "ArchHub never stores secret values in the brain — only "
            "<code>op://</code> references. Resolved at tool-call time."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            f"background:{TOKENS['card']}; "
            f"border:1px solid {TOKENS['accent']}; "
            f"border-radius:8px; padding:10px 14px; "
            f"color:{TOKENS['text']};"
        )
        outer.addWidget(banner)

        self._table = _make_table(list(self.COLS))
        outer.addWidget(self._table, 1)

        # Refresh
        btn_row = QHBoxLayout()
        rb = QPushButton("Refresh")
        rb.clicked.connect(self.refresh)
        btn_row.addStretch(1); btn_row.addWidget(rb)
        outer.addLayout(btn_row)

        self.refresh()

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _mask_value(val: str) -> str:
        if not val:
            return "(empty)"
        if val.lower().startswith("op://"):
            return val
        if len(val) <= 6:
            return "…" + val[-2:]
        return f"{val[:3]}…{val[-4:]}"

    @staticmethod
    def _resolver_source(slug: str, env_var: str) -> tuple[str, str]:
        """Return (source_label, value) for the given key. Honours
        the BRAIN-FIRST mandate: op:// > 1Password > WCM > .env >
        inline file > none."""
        try:
            stored = load_api_key(slug)
        except Exception:
            stored = None
        if stored and stored.startswith("op://"):
            return ("1Password (op://)", stored)
        # Try Windows Credential Manager via keyring.
        try:
            import keyring
            kr_val = keyring.get_password("ArchHub", slug)
            if kr_val:
                return ("WCM (keyring)", kr_val)
        except Exception:
            pass
        # Environment variable (.env / system env).
        env_val = os.environ.get(env_var, "") if env_var else ""
        if env_val:
            return (".env / system env", env_val)
        # Inline file (secrets_store obfuscated file).
        if stored:
            return ("inline (local file)", stored)
        return ("not set", "")

    # ── refresh / render ─────────────────────────────────────────────

    def refresh(self) -> None:
        self._table.setRowCount(len(self.KEY_ROWS))
        for i, (slug, label, env, kind) in enumerate(self.KEY_ROWS):
            source, value = self._resolver_source(slug, env)

            name_it = QTableWidgetItem(label)
            name_it.setData(Qt.ItemDataRole.UserRole, slug)
            self._table.setItem(i, 0, name_it)

            src_it = QTableWidgetItem(source)
            src_it.setForeground(_qbrush(
                TOKENS["good"] if value else TOKENS["muted"]
            ))
            self._table.setItem(i, 1, src_it)

            val_it = QTableWidgetItem(self._mask_value(value))
            val_it.setForeground(_qbrush(TOKENS["muted"]))
            val_it.setFont(QFont("JetBrains Mono", 9))
            self._table.setItem(i, 2, val_it)

            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(4, 2, 4, 2); cl.setSpacing(4)
            set_btn = QPushButton("Set / replace")
            set_btn.clicked.connect(
                lambda _, s=slug, lbl=label: self._on_set(s, lbl)
            )
            test_btn = QPushButton("Test")
            test_btn.clicked.connect(
                lambda _, s=slug, lbl=label, k=kind: self._on_test(s, lbl, k)
            )
            test_btn.setEnabled(bool(value))
            cl.addStretch(1); cl.addWidget(set_btn); cl.addWidget(test_btn)
            self._table.setCellWidget(i, 3, cell)

    # ── handlers ─────────────────────────────────────────────────────

    def _on_set(self, slug: str, label: str) -> None:
        dlg = _SetSecretDialog(slug, label, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self._parent_dlg.notify_changed()

    def _on_test(self, slug: str, label: str, kind: str) -> None:
        # Anthropic gets a real probe; the others are honest stubs.
        _, value = self._resolver_source(slug, "")
        if not value:
            QMessageBox.warning(self, f"Test {label}",
                                 "No value resolved — set the key first.")
            return
        if value.startswith("op://"):
            QMessageBox.information(
                self, f"Test {label}",
                "op:// references are resolved at tool-call time by the "
                "1Password CLI. Run `op signin` if you haven't already; "
                "ArchHub will pick the value up on the next request.",
            )
            return
        if slug == "anthropic":
            ok, msg = self._probe_anthropic(value)
            if ok:
                QMessageBox.information(self, f"Test {label}",
                                         f"Anthropic live · {msg}")
            else:
                QMessageBox.warning(self, f"Test {label}",
                                     f"Probe failed: {msg}")
            return
        QMessageBox.information(
            self, f"Test {label}",
            f"Stub probe — {label} value is resolved ({self._mask_value(value)}). "
            "A live ping for this provider isn't wired yet (only Anthropic "
            "has a real test today)."
        )

    @staticmethod
    def _probe_anthropic(api_key: str) -> tuple[bool, str]:
        """Tiny GET against the Anthropic /v1/models list. 5s timeout
        so a slow network doesn't freeze the dialog."""
        import urllib.error
        import urllib.request
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/models",
                method="GET",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=5.0) as r:
                if 200 <= r.status < 300:
                    return True, f"HTTP {r.status}"
                return False, f"HTTP {r.status}"
        except urllib.error.HTTPError as ex:
            return False, f"HTTP {ex.code} — {ex.reason}"
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            return False, str(ex)[:120]


class _SetSecretDialog(QDialog):
    """Tiny modal for SecretsTab — paste a raw value or an op://
    reference. On Save: writes via secrets_store.save_api_key for
    known providers; otherwise drops into secrets_store.save_setting
    keyed by '<slug>_token' so the value survives restart."""

    def __init__(self, slug: str, label: str, parent: QWidget):
        super().__init__(parent)
        self.slug = slug
        self.setWindowTitle(f"Set {label}")
        self.setStyleSheet(DIALOG_QSS)
        self.setMinimumWidth(440)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 14); v.setSpacing(8)
        head = QLabel(f"<b>{label}</b>")
        v.addWidget(head)
        blurb = QLabel(
            "Paste the raw token <i>or</i> a <code>op://vault/item/field</code> "
            "reference. ArchHub stores op:// references verbatim and resolves "
            "them at tool-call time."
        )
        blurb.setWordWrap(True); blurb.setObjectName("muted")
        v.addWidget(blurb)

        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("sk-… OR op://vault/item/field")
        self._edit.setMaximumHeight(80)
        v.addWidget(self._edit)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _on_save(self) -> None:
        val = (self._edit.toPlainText() or "").strip()
        if not val:
            QMessageBox.warning(self, "Empty value",
                                 "Paste a token or op:// reference first.")
            return
        try:
            from secrets_store import save_api_key, save_setting
            # Known LLM providers go through the standard slot; the
            # others live in settings.json (same secret_store file).
            known = {"openrouter", "anthropic", "openai", "google"}
            if self.slug in known:
                save_api_key(self.slug, val)
            else:
                save_setting(f"{self.slug}_token", val)
        except Exception as ex:
            QMessageBox.warning(self, "Save failed", str(ex))
            return
        self.accept()


# ── Dialog shell ─────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    """ArchHub settings — eight tabs, every button fires a real bridge slot.

    Public constructor preserved from v1.4:

        SettingsDialog(router, parent=None, manager=None, tools=None, **_kw)

    Callers (bridge.open_settings, chat_window, workspace_shell,
    settings_page) hit this signature; tests don't import this dialog
    directly."""

    TABS = [
        ("General",     GeneralTab),
        ("Providers",   ProvidersTab),
        ("Secrets",     SecretsTab),
        ("Hosts",       HostsTab),
        ("Memory",      MemoryTab),
        ("Brain",       BrainTab),
        ("Permissions", PermissionsTab),
        ("Storage",     StorageTab),
        ("Shortcuts",   ShortcutsTab),
        ("About",       AboutTab),
    ]

    def __init__(self, router=None, parent=None, manager=None, tools=None,
                 **_kwargs):
        super().__init__(parent)
        self.router = router
        self.manager = manager
        self.tools = tools
        # The bridge lives on the parent of this dialog (chat_window /
        # workspace_shell). _bridge_call walks up via .parent() so we
        # don't need to thread it through; expose `.bridge` here too in
        # case a child widget asks the dialog directly.
        self.bridge = getattr(parent, "bridge", None) or getattr(parent, "_bridge", None)

        self.setObjectName("settingsDialog")
        self.setWindowTitle("ArchHub — Settings")
        self.resize(960, 680)
        self.setStyleSheet(DIALOG_QSS)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(14, 14, 14, 12)
        shell.setSpacing(10)

        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(False)
        shell.addWidget(self._tabs, 1)

        self._tab_widgets: dict[str, QWidget] = {}
        for label, cls in self.TABS:
            w = cls(self)
            # Wrap in a scroll area so long tabs (Memory, Hosts) never
            # clip on smaller displays.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(w)
            self._tabs.addTab(scroll, label)
            self._tab_widgets[label] = w

        # Footer — a single Close button per founder's "no save dialog
        # whiplash" rule. Per-tab Save lives inside each tab.
        footer = QHBoxLayout()
        version_lbl = QLabel(f"v{_read_version()}")
        version_lbl.setObjectName("muted")
        footer.addWidget(version_lbl)
        footer.addStretch(1)
        close = QPushButton("Close"); close.setObjectName("primary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        shell.addLayout(footer)

    # ── Public API consumed by SignInDialog + _ProviderRow ────────────
    def notify_changed(self) -> None:
        """A provider signed in / out; clear router cache + nudge parent."""
        if self.router and hasattr(self.router, "invalidate_clients"):
            try: self.router.invalidate_clients()
            except Exception: pass
        if self.router and hasattr(self.router, "_clients"):
            try: self.router._clients.clear()
            except Exception: pass
        parent = self.parent()
        if parent is not None and hasattr(parent, "_refresh_model_picker"):
            try: parent._refresh_model_picker()
            except Exception: pass

    # ── Convenience used in tests / scripts that want a tab by name ───
    def tab(self, label: str) -> QWidget | None:
        return self._tab_widgets.get(label)
