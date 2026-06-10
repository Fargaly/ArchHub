"""ArchHub — SettingsDialog (v1.6 IA refresh — Accessibility tab added).

Eleven tabs, each a small QWidget subclass: General, Providers, Secrets,
Hosts, Memory, Brain, Permissions, Storage, Shortcuts, Accessibility,
About. Every button fires a real bridge slot; nothing is decorative.
Public constructor stays
`SettingsDialog(router, parent, manager=None, tools=None, **_kwargs)`
to keep existing callers working.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from secrets_store import (
    load_api_key, delete_api_key, save_setting, load_setting,
)


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


# ── SIGNED palette (docs/prototypes/signed/brain-settings-2026-05-25,
#    AgDR-0045/0046) — used ONLY by the sidebar-shell rebuild. These are the
#    founder-signed tokens; do NOT invent new hexes. ───────────────────────
SIGNED = {
    "bg":     "#0a0a0c",   # window
    "bg2":    "#111114",   # sidebar fill
    "bg3":    "#16161b",   # active row / hover
    "line":   "#22222a",
    "ink":    "#e8e8ea",
    "ink2":   "#9a9aa3",
    "ink3":   "#5e5e68",
    "accent": "#e8743a",
    "mono":   TOKENS["mono"],
}

# QSS applied to the new sidebar shell on top of DIALOG_QSS. Keyed object
# names: settingsDialog (window bg), settingsNav (QListWidget sidebar),
# settingsBrand* (lockup), settingsDivider, settingsStack (content host),
# sectionSubLabel (mono-uppercase per-tab divider inside multi-tab pages).
SHELL_QSS = f"""
QDialog#settingsDialog {{ background:{SIGNED['bg']}; color:{SIGNED['ink']}; }}

/* LEFT SIDEBAR — 220px nav of 5 sections */
QListWidget#settingsNav {{
    background:{SIGNED['bg2']};
    border:none; border-right:1px solid {SIGNED['line']};
    outline:0; padding:6px 0 6px 0;
}}
QListWidget#settingsNav::item {{
    color:{SIGNED['ink2']};
    padding:9px 12px 9px 14px;
    margin:1px 0 1px 0;
    border-left:2px solid transparent;
    border-top-right-radius:8px; border-bottom-right-radius:8px;
}}
QListWidget#settingsNav::item:hover {{
    color:{SIGNED['ink']}; background:{SIGNED['bg3']};
}}
QListWidget#settingsNav::item:selected {{
    color:{SIGNED['ink']};
    background:{SIGNED['bg3']};
    border-left:2px solid {SIGNED['accent']};
}}

/* Brand lockup top-left of sidebar */
QLabel#settingsBrand {{ font-size:20px; font-weight:600; padding:0; }}
QLabel#settingsBrandSub {{
    font-family:{SIGNED['mono']}; font-size:10px; font-weight:600;
    color:{SIGNED['ink3']}; letter-spacing:0.16em;
}}
QFrame#settingsDivider {{ background:{SIGNED['line']}; border:none; max-height:1px; min-height:1px; }}

/* Content host */
QStackedWidget#settingsStack {{ background:{SIGNED['bg']}; }}
QWidget#settingsSectionPage {{ background:{SIGNED['bg']}; }}

/* Mono-uppercase per-tab sub-label inside a multi-tab section page */
QLabel#sectionSubLabel {{
    font-family:{SIGNED['mono']}; font-size:11px; font-weight:600;
    color:{SIGNED['ink3']};
    text-transform:uppercase; letter-spacing:0.14em;
    padding:2px 0 0 2px;
}}
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


def _danger_row(label: str, blurb: str, on_click) -> QFrame:
    """A single destructive-action row: bold label + muted blurb on the
    left, a red `danger` button on the right. Body uses only module-level
    TOKENS + Qt classes (no `self`), so it lives here as one shared helper
    rather than being duplicated per tab."""
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


def _run_js_best_effort(parent, js: str) -> bool:
    """Walk up the parent chain to the bridge and call `run_js(js)` if the
    slot exists. Returns True if the call was dispatched, False if no
    bridge / no run_js slot (headless / tests) — in which case the caller
    relies on the persisted secrets_store value being read on the NEXT
    reload.

    This is the SAME bridge-gap pattern documented on
    `GeneralTab._on_host_node_v2`: the JSX side reads its prefs from
    localStorage, and the native dialog mirrors a write through `run_js`
    when (and only when) the WebChannel exposes it. When it doesn't, the
    write is an honest no-op rather than a crash."""
    obj = parent
    seen = set()
    while obj is not None and id(obj) not in seen:
        seen.add(id(obj))
        bridge = getattr(obj, "bridge", None) or getattr(obj, "_bridge", None)
        run_js = getattr(bridge, "run_js", None) if bridge else None
        if callable(run_js):
            try:
                run_js(js)
                return True
            except Exception:
                return False
        obj = obj.parent() if hasattr(obj, "parent") else None
    return False


# JSX localStorage keys the native System controls mirror (kept byte-for-
# byte aligned with studio-lm.jsx so behaviour is preserved across the
# migration — see ia-critique-ai-stemcells-2026-06-03 §1):
#   archhub.perfhud         — Perf HUD overlay on/off (read in PerfHud)
#   archhub.theme           — 'forge'|'blueprint'|'vellum' (applied as
#                             document.body[data-theme]; default 'forge')
#   jsx_cache_v1_<sha>      — the in-browser Babel compile cache entries
#                             clearJsxCache() purges
LS_PERFHUD = "archhub.perfhud"
LS_THEME = "archhub.theme"
JSX_CACHE_PREFIX = "jsx_cache_v1_"

# The founder-authored, signed theme vocabulary (PROTOTYPE-IS-CONTRACT).
# The native dark/light/system combo folds INTO this single control:
# 'system' maps to 'forge' (the default branded dark theme = "auto"),
# 'dark' → forge, 'light' → vellum. ONE theme control, no second taxonomy.
THEME_CHOICES = (
    ("Forge — warm dark (default)", "forge"),
    ("Blueprint — cool dark",       "blueprint"),
    ("Vellum — warm light",         "vellum"),
)
# Legacy dark/light/system → branded theme, so an old saved value still
# resolves to a real branded theme (back-compat: system==auto==forge).
_LEGACY_THEME_MAP = {
    "dark": "forge", "system": "forge", "auto": "forge", "light": "vellum",
}


def _normalize_theme(value: str | None) -> str:
    """Coerce any saved theme value (branded or legacy dark/light/system)
    to one of the three branded ids. Unknown/empty → 'forge' (the signed
    default)."""
    v = (value or "").strip().lower()
    if v in ("forge", "blueprint", "vellum"):
        return v
    return _LEGACY_THEME_MAP.get(v, "forge")


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
        # Theme moved to the System section (ONE unified Forge/Blueprint/
        # Vellum control — the old dark/light/system combo folded into it,
        # ia-critique-ai-stemcells-2026-06-03 §1). A pointer row keeps the
        # founder's muscle-memory: "theme lives in System now".
        theme_ptr = QLabel(
            "Theme moved to <b>System</b> — Forge / Blueprint / Vellum."
        )
        theme_ptr.setObjectName("muted"); theme_ptr.setWordWrap(True)
        af.addRow("Theme", theme_ptr)
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

        # Theme now lives in the System section (SystemTab) — one unified
        # Forge/Blueprint/Vellum control. GeneralTab no longer owns it.

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

        # Theme is saved from the System section now (SystemTab._save).

        # Language + default model — local settings.
        save_setting("language", self._lang.currentData() or "en")
        save_setting("default_model", self._model.currentData() or "auto")

        QMessageBox.information(self, "General", "Saved.")
        self._parent_dlg.notify_changed()


# ── Tab: Providers ───────────────────────────────────────────────────────
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
                    "Which AI providers you've connected, and their live "
                    "status. Key management now lives in one place — "
                    "<b>Connections › Keys &amp; Secrets</b>.",
                    scope="USER")

        # Status banner — uses bridge.get_provider_stats.
        self._banner = QLabel("")
        self._banner.setObjectName("mono")
        outer.addWidget(self._banner)

        # No per-provider key rows here anymore — anthropic/openai/etc keys
        # are managed in the comprehensive Keys & Secrets table (SecretsTab),
        # so this tab stops duplicating key management. `self._rows` stays an
        # empty list so refresh()'s `for row in self._rows` is a safe no-op.
        self._rows: list = []

        # Prototype "Provider keys" card (settings-redesign-2026-06-02.html
        # line 226): one row that routes to the single key surface.
        keys_card = QFrame()
        keys_card.setObjectName("settingsCard")
        keys_card.setStyleSheet(
            f"QFrame#settingsCard {{ background: {TOKENS['card']}; "
            f"border: 1px solid {TOKENS['border']}; border-radius: 8px; }}"
        )
        kc = QHBoxLayout(keys_card)
        kc.setContentsMargins(14, 10, 14, 10)
        kc.setSpacing(12)
        kcol = QVBoxLayout(); kcol.setSpacing(2)
        klabel = QLabel("Manage API keys")
        klabel.setStyleSheet("font-weight: 600;")
        kdesc = QLabel("Now one place — see Connections › Keys & Secrets")
        kdesc.setObjectName("muted"); kdesc.setWordWrap(True)
        kcol.addWidget(klabel); kcol.addWidget(kdesc)
        kc.addLayout(kcol, 1)
        keys_btn = QPushButton("Go to Keys && Secrets")
        keys_btn.setObjectName("primary")
        keys_btn.clicked.connect(
            lambda: self._parent_dlg.focus_section("secrets")
        )
        kc.addWidget(keys_btn)
        outer.addWidget(keys_card)

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


# ── Tab: System ──────────────────────────────────────────────────────────
class SystemTab(QWidget):
    """Native home for the controls migrated off the vestigial React
    Settings modal (ia-critique-ai-stemcells-2026-06-03 §1: SETTINGS-
    EVERYWHERE). MAKE-IT-REAL: nothing was deleted from the JSX without a
    native home — these ARE that home.

    Holds:
      • Theme — the unified Forge/Blueprint/Vellum control (the signed
        vocabulary), into which the old native dark/light/system combo
        folds (system → forge "auto"). ONE theme taxonomy.
      • Performance HUD overlay toggle (Ctrl+Shift+P) — `archhub.perfhud`.
      • JSX bundle cache — clear `jsx_cache_v1_*` + reload the UI.
      • Reset UI preferences — restore Host-Node-v2 / Perf-HUD / theme.

    Every write goes to secrets_store (the SAFE persisted value the JSX
    reads on the next reload) AND, best-effort, mirrors through the bridge
    `run_js` slot for a live flip — the exact bridge-gap pattern
    documented on GeneralTab._on_host_node_v2. Headless / no-bridge →
    honest no-op on the live flip; the persisted value still lands."""

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "System",
                    "Appearance, performance, and the dev controls that "
                    "used to live in a second settings window. All values "
                    "stay on this machine.",
                    scope="DEVICE")

        # ── Theme (unified Forge/Blueprint/Vellum) ───────────────────
        theme_grp = QGroupBox("Theme")
        tf = QFormLayout(theme_grp); tf.setSpacing(8); tf.setContentsMargins(12, 18, 12, 12)
        theme_hint = QLabel(
            "ArchHub's three signed themes. <b>Forge</b> is the default "
            "warm dark; <b>Blueprint</b> a cool dark; <b>Vellum</b> a warm "
            "light. (The old dark / light / system options folded in here — "
            "system maps to Forge.)"
        )
        theme_hint.setObjectName("muted"); theme_hint.setWordWrap(True)
        self._theme = QComboBox()
        for label, val in THEME_CHOICES:
            self._theme.addItem(label, val)
        tf.addRow(theme_hint)
        tf.addRow("Theme", self._theme)
        outer.addWidget(theme_grp)

        # ── Performance HUD ──────────────────────────────────────────
        perf_grp = QGroupBox("Performance")
        pg = QVBoxLayout(perf_grp); pg.setSpacing(8); pg.setContentsMargins(12, 18, 12, 12)
        perf_hint = QLabel(
            "The Perf HUD overlays live frame-rate, save-call rate and "
            "RAF frames on the canvas — handy for A/B-ing perf wins. "
            "Toggle it any time with <kbd>Ctrl+Shift+P</kbd>."
        )
        perf_hint.setObjectName("muted"); perf_hint.setWordWrap(True)
        pg.addWidget(perf_hint)
        self._perfhud = QCheckBox("Show performance HUD overlay")
        self._perfhud.toggled.connect(self._on_perfhud)
        pg.addWidget(self._perfhud)
        outer.addWidget(perf_grp)

        # ── JSX bundle cache (dev) ───────────────────────────────────
        cache_grp = QGroupBox("Interface cache")
        cg = QVBoxLayout(cache_grp); cg.setSpacing(8); cg.setContentsMargins(12, 18, 12, 12)
        cache_hint = QLabel(
            "ArchHub caches its compiled interface bundle for fast boot. "
            "Clear it if the UI looks stale after an update, then reload."
        )
        cache_hint.setObjectName("muted"); cache_hint.setWordWrap(True)
        cg.addWidget(cache_hint)
        cache_row = QHBoxLayout(); cache_row.setSpacing(8)
        self._clear_cache_btn = QPushButton("Clear interface cache")
        self._clear_cache_btn.clicked.connect(self._on_clear_jsx_cache)
        self._reload_btn = QPushButton("Reload UI now")
        self._reload_btn.clicked.connect(self._on_reload_ui)
        cache_row.addWidget(self._clear_cache_btn)
        cache_row.addWidget(self._reload_btn)
        cache_row.addStretch(1)
        cg.addLayout(cache_row)
        outer.addWidget(cache_grp)

        # ── Reset preferences (danger) ───────────────────────────────
        reset_grp = QGroupBox("Reset")
        rg = QVBoxLayout(reset_grp); rg.setSpacing(8); rg.setContentsMargins(12, 18, 12, 12)
        rg.addWidget(_danger_row(
            "Reset UI preferences",
            "Restore Host-Node-v2, Perf-HUD and theme to their defaults. "
            "Sessions, skills and memory are untouched.",
            self._on_reset_prefs,
        ))
        outer.addWidget(reset_grp)

        # Save row — theme is the only persisted-on-save control; the
        # toggles/buttons persist immediately on interaction.
        save_row = QHBoxLayout()
        self._save_btn = QPushButton("Save changes"); self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._save)
        save_row.addStretch(1); save_row.addWidget(self._save_btn)
        outer.addLayout(save_row)

        outer.addStretch(1)
        self._load()

    # ── load / save ──────────────────────────────────────────────────
    def _load(self) -> None:
        # Theme — prefer the bridge (so we agree with the live app), then
        # the saved setting, normalising any legacy dark/light/system.
        theme = None
        bt = _bridge_call(self._parent_dlg, "get_theme", default={}) or {}
        if isinstance(bt, dict) and bt.get("theme"):
            theme = bt.get("theme")
        if not theme:
            theme = load_setting("theme")
        theme = _normalize_theme(theme)
        idx = self._theme.findData(theme)
        if idx >= 0:
            self._theme.setCurrentIndex(idx)

        # Perf HUD — saved setting drives the checkbox (JSX default OFF).
        self._perfhud.blockSignals(True)
        self._perfhud.setChecked(bool(load_setting(LS_PERFHUD)))
        self._perfhud.blockSignals(False)

    def _on_perfhud(self, on: bool) -> None:
        """Persist + best-effort live-flip the Perf HUD overlay. JSX reads
        localStorage['archhub.perfhud'] AND listens for the toggle event
        the command palette fires (lm-toggle-perf-hud); we set the stored
        value, then dispatch that same event so a visible HUD flips now."""
        save_setting(LS_PERFHUD, bool(on))
        _run_js_best_effort(
            self._parent_dlg,
            "try{localStorage.setItem('%s',String(%s));"
            "window.dispatchEvent(new CustomEvent('lm-toggle-perf-hud',"
            "{detail:{force:%s}}));}catch(e){}"
            % (LS_PERFHUD, str(bool(on)).lower(), str(bool(on)).lower()),
        )

    def _on_clear_jsx_cache(self) -> None:
        """Purge every `jsx_cache_v1_*` key — the exact body clearJsxCache
        runs in the JSX. Needs the live page (that's where localStorage
        is), so this is bridge-only; headless → honest notice."""
        ok = _run_js_best_effort(
            self._parent_dlg,
            "try{var n=0;for(var i=localStorage.length-1;i>=0;i--){"
            "var k=localStorage.key(i);"
            "if(k&&k.indexOf('%s')===0){localStorage.removeItem(k);n++;}}"
            "console.log('[archhub] cleared '+n+' jsx cache entries');}"
            "catch(e){}" % (JSX_CACHE_PREFIX,),
        )
        if ok:
            QMessageBox.information(
                self, "Interface cache",
                "Interface cache cleared. Use “Reload UI now” to pick up "
                "the fresh bundle.",
            )
        else:
            QMessageBox.information(
                self, "Interface cache",
                "Open ArchHub's main window to clear its interface cache — "
                "there's no live UI attached here.",
            )

    def _on_reload_ui(self) -> None:
        """Reload the live web UI (window.location.reload)."""
        ok = _run_js_best_effort(
            self._parent_dlg, "try{window.location.reload();}catch(e){}"
        )
        if not ok:
            QMessageBox.information(
                self, "Reload UI",
                "No live UI is attached here — reload from ArchHub's main "
                "window.",
            )

    def _on_reset_prefs(self) -> None:
        """Restore Host-Node-v2 / Perf-HUD / theme to defaults. Mirrors the
        JSX resetPrefs: remove archhub.host_node_v2 / perfhud / theme from
        localStorage + re-broadcast the host-node-v2 event so the canvas
        repaints. Also resets the persisted secrets_store values so the
        NEXT reload (no-bridge case) honours the reset."""
        if QMessageBox.question(
            self, "Reset UI preferences?",
            "Restore Host-Node-v2, Perf-HUD and theme to defaults? "
            "Sessions, skills and memory are untouched.",
        ) != QMessageBox.StandardButton.Yes:
            return
        # Persisted side (SAFE value read on next reload).
        save_setting("host_node_v2", True)   # JSX default is ON
        save_setting(LS_PERFHUD, False)      # JSX default is OFF
        save_setting("theme", "forge")       # signed default
        _bridge_call(self._parent_dlg, "set_theme", "forge", default={})
        # Live side (best-effort): clear the JSX-owned keys + rebroadcast.
        _run_js_best_effort(
            self._parent_dlg,
            "try{localStorage.removeItem('archhub.host_node_v2');"
            "localStorage.removeItem('%s');"
            "localStorage.removeItem('%s');"
            "window.dispatchEvent(new CustomEvent('archhub-host-node-v2',"
            "{detail:true}));}catch(e){}" % (LS_PERFHUD, LS_THEME),
        )
        # Reflect the reset in this tab's widgets.
        self._load()
        QMessageBox.information(self, "Reset", "UI preferences reset to defaults.")

    def _save(self) -> None:
        """Persist the theme. Theme via bridge (so the rest of the app
        picks it up) AND a mirrored localStorage write + a saved setting,
        so the JSX reads the same branded value on the next reload.

        The live repaint goes through the JSX-owned global
        window.__archhubSetTheme(v): it swaps the mutable theme backing
        object (so inline-style surfaces repaint NOW, matching the deleted
        React control), persists localStorage AND sets body[data-theme]
        AND fires archhub-theme-changed in one call. If that global is
        absent (stale bundle / no live UI), we fall back to the raw
        localStorage + data-theme write so CSS-var surfaces + the next
        cold start still pick up the branded value. Best-effort / no-op
        when run_js is unavailable (mirrors _on_perfhud)."""
        theme = self._theme.currentData() or "forge"
        _bridge_call(self._parent_dlg, "set_theme", theme, default={})
        save_setting("theme", theme)
        _run_js_best_effort(
            self._parent_dlg,
            "try{var v=String('%s').toLowerCase();"
            "if(typeof window.__archhubSetTheme==='function'){"
            "window.__archhubSetTheme(v);}else{"
            "localStorage.setItem('%s',v);"
            "document.body.setAttribute('data-theme',v);}}"
            "catch(e){}" % (theme, LS_THEME),
        )
        QMessageBox.information(self, "System", "Saved.")
        self._parent_dlg.notify_changed()


# ── Update-check worker (off the Qt main thread) ─────────────────────────
class _UpdateCheckWorker(QObject):
    """Runs `updater.check_for_updates()` on a background QThread and emits
    a single founder-readable status line. The check does a `git fetch`
    (network) so it MUST NOT run on the GUI thread — same rule as every
    other slow op in this file.

    `updater` is imported INSIDE run() (not at module load) so the dialog
    never hard-depends on it: if the module is absent or raises, the worker
    emits an honest "couldn't check" line instead of crashing the UI
    (ANTI-LIE: never fake a capability that isn't reachable)."""

    done = pyqtSignal(str)

    def run(self) -> None:
        text = ""
        try:
            # Pick the RIGHT channel, same split as update_dialog._CheckWorker:
            # a git checkout (developer) → git updater; an installed .exe →
            # the official signed-release channel. The old code only ever ran
            # the git checker, so an installer user got a wrong/empty answer.
            import release_updater
            if release_updater.in_git_checkout():
                import updater  # app/updater.py — real git-backed checker
                status = updater.check_for_updates()
                if getattr(status, "error", ""):
                    text = status.error
                elif getattr(status, "has_updates", False):
                    n = int(getattr(status, "behind", 0) or 0)
                    text = (f"Update available — {n} new change(s) on "
                            f"{getattr(status, 'branch', '') or 'your branch'}. "
                            f"Click Relaunch to install.")
                else:
                    commit = getattr(status, "local_commit", "") or "current build"
                    text = f"You're up to date ({commit})."
            else:
                # Installer user → official GitHub Releases (the production path).
                avail, info, local = release_updater.has_update_available()
                if getattr(info, "error", "") and not getattr(info, "tag", ""):
                    text = info.error
                elif avail:
                    text = (f"Update available — {getattr(info, 'tag', '')}. "
                            f"Click Relaunch to install.")
                else:
                    cur = local or getattr(info, "tag", "") or "current build"
                    text = f"You're up to date ({cur})."
        except Exception as ex:  # pragma: no cover - defensive
            text = f"Couldn't check for updates: {ex}"
        self.done.emit(text)


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

        # ── Updates ──────────────────────────────────────────────────
        # The founder's plain-English control over how ArchHub updates.
        # The checkbox is the UI for the EXISTING `auto_apply_updates_on_quit`
        # gate read by dev_source_sync.apply_staged_update (default OFF — a
        # safe, quiet update model). The button runs the real git-backed
        # updater.check_for_updates() off the GUI thread.
        upd_grp = QGroupBox("Updates")
        upg = QVBoxLayout(upd_grp); upg.setSpacing(8); upg.setContentsMargins(12, 18, 12, 12)
        upd_hint = QLabel(
            "ArchHub improves itself in the background. Choose when those "
            "improvements actually switch on."
        )
        upd_hint.setObjectName("muted"); upd_hint.setWordWrap(True)
        upg.addWidget(upd_hint)

        self._auto_apply = QCheckBox("Install updates automatically when I quit")
        # DEFAULT UNCHECKED — the setting is absent/False by default (the SAFE
        # quiet-update state). Persist immediately on toggle (MemoryTab idiom).
        self._auto_apply.setChecked(bool(load_setting("auto_apply_updates_on_quit")))
        self._auto_apply.toggled.connect(
            lambda v: save_setting("auto_apply_updates_on_quit", bool(v))
        )
        upg.addWidget(self._auto_apply)
        auto_sub = QLabel(
            "Off = updates only install when you click the Relaunch button."
        )
        auto_sub.setObjectName("muted"); auto_sub.setWordWrap(True)
        upg.addWidget(auto_sub)

        chk_row = QHBoxLayout(); chk_row.setSpacing(8)
        self._check_updates_btn = QPushButton("Check for updates now")
        self._check_updates_btn.clicked.connect(self._on_check_updates)
        self._update_status = QLabel("")
        self._update_status.setObjectName("muted"); self._update_status.setWordWrap(True)
        chk_row.addWidget(self._check_updates_btn)
        chk_row.addWidget(self._update_status, 1)
        upg.addLayout(chk_row)
        outer.addWidget(upd_grp)

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
        dg.addWidget(_danger_row(
            "Clear model cache",
            "Free disk used by cached LLM responses. Won't affect saved sessions.",
            self._on_clear_cache,
        ))
        dg.addWidget(_danger_row(
            "Forget all memory",
            "Wipes every memory fact (local + cloud). Sessions are untouched.",
            self._on_forget_memory,
        ))
        dg.addWidget(_danger_row(
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
        # AgDR-0036 follow-up — export_all + clear_model_cache run OFF the Qt
        # main thread now: the slot returns {async, request_id} instantly and
        # emits settings_op_done when the glob+zip / glob+delete lands. We
        # correlate by request_id so the button click never freezes the UI.
        self._pending_ops: dict[str, str] = {}   # request_id -> kind
        # Update-check thread holder (kept on self so it isn't GC'd mid-run).
        self._update_thread: QThread | None = None
        self._update_worker: _UpdateCheckWorker | None = None
        self._connect_bridge_signals()
        self.refresh()

    # ── Bridge plumbing (off-thread Settings ops) ─────────────────────
    def _bridge(self):
        obj = self._parent_dlg
        seen = set()
        while obj is not None and id(obj) not in seen:
            seen.add(id(obj))
            b = getattr(obj, "bridge", None) or getattr(obj, "_bridge", None)
            if b is not None:
                return b
            obj = obj.parent() if hasattr(obj, "parent") else None
        return None

    def _connect_bridge_signals(self) -> None:
        """Listen for settings_op_done so the UI flips the moment the
        background export / cache-clear finishes. Mirrors AccountTab's
        cloud_signin_done wiring."""
        b = self._bridge()
        if b is None:
            return
        sig = getattr(b, "settings_op_done", None)
        if sig is not None and hasattr(sig, "connect"):
            try:
                sig.connect(self._on_settings_op_done)
            except Exception:
                pass

    def _new_request_id(self, kind: str) -> str:
        import uuid as _uuid
        rid = f"{kind}-{_uuid.uuid4().hex[:12]}"
        self._pending_ops[rid] = kind
        return rid

    def _on_settings_op_done(self, result_json: str) -> None:
        """Runs on the GUI thread (Qt auto-queues the cross-thread signal).
        Routes the result to the matching button by request_id."""
        try:
            res = json.loads(result_json or "null")
        except Exception:
            res = None
        if not isinstance(res, dict):
            return
        rid = str(res.get("request_id") or "")
        kind = self._pending_ops.pop(rid, "")
        if not kind:
            return   # not ours (another tab / stale)
        if kind == "export":
            self._export_btn.setEnabled(True)
            self._export_btn.setText("Export everything to zip")
            if res.get("ok") and res.get("path"):
                QMessageBox.information(
                    self, "Export complete",
                    f"Saved to:\n{res['path']}\n\n"
                    f"Size: {_fmt_bytes(int(res.get('size') or 0))}",
                )
            else:
                msg = res.get("error", "unknown error")
                QMessageBox.warning(self, "Export", f"Export failed: {msg}")
        elif kind == "clear_cache":
            if res.get("ok"):
                freed = int(res.get("freed_bytes") or 0)
                QMessageBox.information(self, "Model cache",
                                        f"Freed {_fmt_bytes(freed)}.")
            else:
                QMessageBox.warning(self, "Model cache",
                                    f"Clear failed: {res.get('error', 'unknown error')}")
            self.refresh()

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

    def _on_check_updates(self) -> None:
        """Check for updates without ever blocking the UI thread.

        Prefer a live bridge refresh slot if the running app exposes one
        (it surfaces the same update banner the founder already knows); if
        none is reachable, fall back to running the real git-backed
        updater.check_for_updates() on a background QThread and show the
        returned status inline. Re-entrancy is guarded so a double-click
        doesn't spawn two threads."""
        if self._update_thread is not None:
            return  # a check is already running

        # 1) Best-effort: ALSO refresh the in-app update banner if the running
        # app exposes a slot — fire-and-forget. We do NOT return here: the old
        # code set "Checking via ArchHub…" and returned, leaving the line stuck
        # forever because nothing updated it when the bridge refresh finished
        # (Copilot review, PR #102). The definitive status always comes from the
        # off-thread check below.
        b = self._bridge()
        for slot in ("refresh_updates", "check_for_updates", "check_updates"):
            fn = getattr(b, slot, None) if b is not None else None
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break

        # 2) Definitive off-thread check — ALWAYS runs, always resolves the line.
        self._check_updates_btn.setEnabled(False)
        self._update_status.setText("Checking…")
        self._update_thread = QThread(self)
        self._update_worker = _UpdateCheckWorker()
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.done.connect(self._on_update_checked)
        self._update_thread.start()

    def _on_update_checked(self, text: str) -> None:
        """GUI-thread slot: show the status line + tear the worker down."""
        self._update_status.setText(text or "")
        self._check_updates_btn.setEnabled(True)
        if self._update_thread is not None:
            self._update_thread.quit()
            self._update_thread.wait()
        self._update_thread = None
        self._update_worker = None

    def _on_export(self) -> None:
        # Off-thread: fire export_all with a request_id + let settings_op_done
        # land the result (no QApplication.processEvents spin on the GUI thread,
        # no frozen window while a big library zips). AgDR-0036 follow-up.
        b = self._bridge()
        sig = getattr(b, "settings_op_done", None) if b is not None else None
        if b is not None and sig is not None and hasattr(b, "export_all"):
            self._export_btn.setEnabled(False)
            self._export_btn.setText("Exporting…")
            rid = self._new_request_id("export")
            try:
                b.export_all(rid)   # returns {async, request_id} instantly
                return
            except Exception as ex:
                self._pending_ops.pop(rid, None)
                self._export_btn.setEnabled(True)
                self._export_btn.setText("Export everything to zip")
                QMessageBox.warning(self, "Export", f"Export failed: {ex}")
                return
        # Fallback (no bridge signal, e.g. headless tests) — synchronous path.
        res = _bridge_call(self._parent_dlg, "export_all", default={}) or {}
        if isinstance(res, dict) and res.get("ok") and res.get("path"):
            QMessageBox.information(
                self, "Export complete",
                f"Saved to:\n{res['path']}\n\nSize: {_fmt_bytes(int(res.get('size') or 0))}",
            )
        else:
            msg = res.get("error", "unknown error") if isinstance(res, dict) else "no bridge"
            QMessageBox.warning(self, "Export", f"Export failed: {msg}")

    def _on_clear_cache(self) -> None:
        if QMessageBox.question(
            self, "Clear model cache?",
            "Remove cached LLM responses? Saved sessions are untouched.",
        ) != QMessageBox.StandardButton.Yes:
            return
        # Off-thread (AgDR-0036 follow-up) — same idiom as _on_export.
        b = self._bridge()
        sig = getattr(b, "settings_op_done", None) if b is not None else None
        if b is not None and sig is not None and hasattr(b, "clear_model_cache"):
            rid = self._new_request_id("clear_cache")
            try:
                b.clear_model_cache(rid)
                return
            except Exception:
                self._pending_ops.pop(rid, None)
        # Fallback — synchronous path.
        res = _bridge_call(self._parent_dlg, "clear_model_cache", default={}) or {}
        freed = int((res or {}).get("freed_bytes") or 0)
        QMessageBox.information(self, "Model cache", f"Freed {_fmt_bytes(freed)}.")
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


# ── Tab: Account (ArchHub Cloud sign-in / sign-out) ──────────────────────
class AccountTab(QWidget):
    """ArchHub Cloud account — the REAL in-app sign-in / sign-out surface.

    Before this tab existed, the ONLY token-minting path in the whole UI was
    the first-run onboarding dialog (cloud_auth.SignInWorker). After first run
    there was no way to sign in from the UI, and the Brain "Back up my brain"
    button dead-ended here (Settings → Account) with no sign-in handler.

    This tab makes the SAME real PKCE browser sign-in reachable any time, via
    bridge.cloud_sign_in() (which launches cloud_auth.SignInWorker off the Qt
    main thread), plus a real bridge.cloud_sign_out() that revokes the token
    server-side (POST /v1/auth/logout) and clears it locally. A live status
    line shows the signed-in email + plan.

    SAFETY: the button OPENS the browser to the magic-link — the actual
    sign-in (the founder's one manual step) happens there. This UI never
    types credentials or creates an account.
    """

    # A signed-in account-detail fetch (cloud_client.me()) hits the network,
    # so it runs on a worker thread and lands back on the UI thread via this
    # signal — never block the dialog on a slow / unreachable cloud.
    account_loaded = pyqtSignal(dict)

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")
        self._busy = False           # a sign-in browser flow is open
        self._signed_in = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(outer, "Account",
                    "Sign in to ArchHub Cloud to back up your brain, sync "
                    "across devices, and route AI through the managed relay. "
                    "Bring-your-own-keys still works without an account.",
                    scope="USER")

        # ── Status card ───────────────────────────────────────────────
        st = QGroupBox("ArchHub Cloud")
        sv = QVBoxLayout(st); sv.setSpacing(10); sv.setContentsMargins(12, 18, 12, 12)

        status_row = QHBoxLayout(); status_row.setSpacing(10)
        self._dot = QLabel("○"); self._dot.setFixedWidth(14)
        self._dot.setStyleSheet(f"color:{TOKENS['muted']}; font-size:14px;")
        status_row.addWidget(self._dot)
        self._status_text = QLabel("Checking sign-in…")
        self._status_text.setObjectName("muted")
        status_row.addWidget(self._status_text, 1)
        sv.addLayout(status_row)

        # Detail line (email / plan / remaining) — mono, selectable.
        self._detail = QLabel("")
        self._detail.setObjectName("mono")
        self._detail.setWordWrap(True)
        self._detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sv.addWidget(self._detail)

        # Cloud URL (honest about where it points — env-overridable).
        self._url_lbl = QLabel("")
        self._url_lbl.setObjectName("mono")
        self._url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sv.addWidget(self._url_lbl)

        # ── Action row: Sign in (signed-out) / Sign out (signed-in) ────
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self._signin_btn = QPushButton("Sign in to ArchHub Cloud")
        self._signin_btn.setObjectName("primary")
        self._signin_btn.clicked.connect(self._on_sign_in)
        btn_row.addWidget(self._signin_btn)

        # "Sign in with Google" — same real PKCE browser flow, via
        # bridge.cloud_sign_in_google() (cloud_auth.GoogleSignInWorker).
        self._signin_google_btn = QPushButton("Sign in with Google")
        self._signin_google_btn.clicked.connect(self._on_sign_in_google)
        btn_row.addWidget(self._signin_google_btn)

        self._signout_btn = QPushButton("Sign out")
        self._signout_btn.setObjectName("danger")
        self._signout_btn.clicked.connect(self._on_sign_out)
        self._signout_btn.setVisible(False)
        btn_row.addWidget(self._signout_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh)
        btn_row.addStretch(1)
        btn_row.addWidget(self._refresh_btn)
        sv.addLayout(btn_row)

        # Inline hint shown while the browser sign-in is in flight.
        self._hint = QLabel("")
        self._hint.setObjectName("muted")
        self._hint.setWordWrap(True)
        self._hint.setVisible(False)
        sv.addWidget(self._hint)

        outer.addWidget(st)
        outer.addStretch(1)

        # ── Wire bridge signals so the UI flips when sign-in/out finish ─
        self.account_loaded.connect(self._apply_account)
        self._connect_bridge_signals()

        self._refresh()

    # ── Bridge plumbing ───────────────────────────────────────────────
    def _bridge(self):
        return (getattr(self._parent_dlg, "bridge", None)
                or getattr(self._parent_dlg, "_bridge", None))

    def _connect_bridge_signals(self) -> None:
        """Listen for cloud_signin_done / cloud_signout_done so the tab
        flips to the right state the moment the founder finishes (or
        cancels) the browser flow, or a sign-out completes."""
        b = self._bridge()
        if b is None:
            return
        for name, handler in (
            ("cloud_signin_done", self._on_signin_done),
            ("cloud_signout_done", self._on_signout_done),
        ):
            sig = getattr(b, name, None)
            if sig is not None and hasattr(sig, "connect"):
                try:
                    sig.connect(handler)
                except Exception:
                    pass

    # ── Refresh / render ──────────────────────────────────────────────
    def _refresh(self) -> None:
        """Probe sign-in state (cheap, synchronous) then, if signed in,
        fetch richer account detail on a worker thread."""
        signed_in = False
        cloud_url = ""
        cc = _cloud_client()
        if cc is not None:
            try:
                signed_in = bool(cc.is_signed_in())
                cloud_url = cc.base_url()
            except Exception:
                signed_in = False
        # Bridge cloud_status is the same probe; prefer the direct client
        # call (synchronous, no bridge needed in tests) and fall back to
        # the bridge slot when the client module isn't importable.
        if cc is None:
            st = _bridge_call(self._parent_dlg, "cloud_status", default={}) or {}
            if isinstance(st, dict):
                signed_in = bool(st.get("signed_in"))
                cloud_url = st.get("cloud_url") or ""

        self._signed_in = signed_in
        self._url_lbl.setText(f"relay: {cloud_url}" if cloud_url else "")
        self._render_state()

        if signed_in:
            # Fetch email / plan off-thread; lands via account_loaded.
            self._detail.setText("Loading account…")
            import threading
            threading.Thread(target=self._load_account_worker,
                             daemon=True).start()
        else:
            self._detail.setText("")

    def _load_account_worker(self) -> None:
        """Worker thread: cloud_client.me() (network). Emit result on the
        UI thread via the account_loaded signal."""
        info = {}
        cc = _cloud_client()
        if cc is not None:
            try:
                info = cc.me() or {}
            except Exception:
                info = {}
        try:
            self.account_loaded.emit(info if isinstance(info, dict) else {})
        except Exception:
            pass

    def _apply_account(self, info: dict) -> None:
        """UI-thread: render the email / plan / remaining line."""
        if not self._signed_in:
            return
        info = info or {}
        email = info.get("email") or ""
        plan = info.get("plan") or ""
        remaining = info.get("remaining_messages")
        if email or plan:
            line = email or "(signed in)"
            if plan:
                line += f"  ·  {plan} plan"
            if isinstance(remaining, int):
                line += f"  ·  {remaining} messages left"
            self._detail.setText(line)
        else:
            # Signed in but cloud detail unreachable — stay honest.
            self._detail.setText("Signed in — account detail unreachable "
                                  "(offline?).")

    def _render_state(self) -> None:
        """Flip dot / status text / which button shows, by sign-in state."""
        if self._busy:
            self._dot.setText("◍")
            self._dot.setStyleSheet(f"color:{TOKENS['warn']}; font-size:14px;")
            self._status_text.setText("Waiting for sign-in in your browser…")
            self._signin_btn.setEnabled(False)
            self._signin_btn.setVisible(True)
            self._signin_google_btn.setEnabled(False)
            self._signin_google_btn.setVisible(True)
            self._signout_btn.setVisible(False)
            self._hint.setVisible(True)
            self._hint.setText(
                "Your browser opened on the ArchHub sign-in page. Finish "
                "there and come back — we detect it automatically."
            )
            return
        self._hint.setVisible(False)
        if self._signed_in:
            self._dot.setText("●")
            self._dot.setStyleSheet(f"color:{TOKENS['good']}; font-size:14px;")
            self._status_text.setText("Signed in to ArchHub Cloud.")
            self._signin_btn.setVisible(False)
            self._signin_google_btn.setVisible(False)
            self._signout_btn.setVisible(True)
            self._signout_btn.setEnabled(True)
        else:
            self._dot.setText("○")
            self._dot.setStyleSheet(f"color:{TOKENS['muted']}; font-size:14px;")
            self._status_text.setText("Not signed in.")
            self._signin_btn.setVisible(True)
            self._signin_btn.setEnabled(True)
            self._signin_btn.setText("Sign in to ArchHub Cloud")
            self._signin_google_btn.setVisible(True)
            self._signin_google_btn.setEnabled(True)
            self._signout_btn.setVisible(False)

    # ── Actions ───────────────────────────────────────────────────────
    def _on_sign_in(self) -> None:
        """Launch the real PKCE browser sign-in via bridge.cloud_sign_in().
        Non-blocking; the result lands via the cloud_signin_done signal.

        Fallback when no bridge is wired (preview / odd harness): call
        cloud_auth.SignInWorker directly, same flow. The agent never signs
        in — opening the browser is the founder's one manual step."""
        if self._busy:
            return
        self._busy = True
        self._render_state()
        b = self._bridge()
        if b is not None and hasattr(b, "cloud_sign_in"):
            try:
                b.cloud_sign_in()
                return
            except Exception:
                pass
        # Direct fallback — wire SignInWorker straight to this tab.
        try:
            from cloud_auth import SignInWorker
            self._direct_worker = SignInWorker(self)
            self._direct_worker.succeeded.connect(
                lambda payload: self._on_signin_done(json.dumps({
                    "ok": True, "signed_in": True,
                    "email": (payload.get("me") or {}).get("email", ""),
                    "plan": (payload.get("me") or {}).get("plan", ""),
                })))
            self._direct_worker.failed.connect(
                lambda msg: self._on_signin_done(json.dumps({
                    "ok": False, "signed_in": False, "error": msg})))
            self._direct_worker.start()
        except Exception as ex:
            self._busy = False
            QMessageBox.warning(self, "Sign in",
                                 f"Couldn't start sign-in: {ex}")
            self._render_state()

    def _on_sign_in_google(self) -> None:
        """Launch the real "Sign in with Google" PKCE browser flow via
        bridge.cloud_sign_in_google(). Same pattern as _on_sign_in — non-
        blocking; the result lands via the shared cloud_signin_done signal.

        Fallback when no bridge is wired (preview / odd harness): drive
        cloud_auth.GoogleSignInWorker directly. The agent never signs in —
        opening the browser is the founder's one manual step."""
        if self._busy:
            return
        self._busy = True
        self._render_state()
        b = self._bridge()
        if b is not None and hasattr(b, "cloud_sign_in_google"):
            try:
                b.cloud_sign_in_google()
                return
            except Exception:
                pass
        # Direct fallback — wire GoogleSignInWorker straight to this tab.
        try:
            from cloud_auth import GoogleSignInWorker
            self._direct_worker = GoogleSignInWorker(self)
            self._direct_worker.succeeded.connect(
                lambda payload: self._on_signin_done(json.dumps({
                    "ok": True, "signed_in": True,
                    "email": (payload.get("me") or {}).get("email", ""),
                    "plan": (payload.get("me") or {}).get("plan", ""),
                })))
            self._direct_worker.failed.connect(
                lambda msg: self._on_signin_done(json.dumps({
                    "ok": False, "signed_in": False, "error": msg})))
            self._direct_worker.start()
        except Exception as ex:
            self._busy = False
            QMessageBox.warning(self, "Sign in",
                                 f"Couldn't start Google sign-in: {ex}")
            self._render_state()

    def _on_signin_done(self, result_json: str) -> None:
        """cloud_signin_done handler — flip out of busy, refresh state."""
        self._busy = False
        res = {}
        try:
            res = json.loads(result_json or "{}") or {}
        except Exception:
            res = {}
        if res.get("ok") and res.get("signed_in"):
            self._signed_in = True
            self._render_state()
            # Render the email/plan we already have, then refresh fully.
            self._apply_account({
                "email": res.get("email"),
                "plan": res.get("plan"),
                "remaining_messages": res.get("remaining_messages"),
            })
            self._refresh()
            self._parent_dlg.notify_changed()
        else:
            # Failed / cancelled — stay signed-out, surface the reason.
            self._signed_in = bool(self._signed_in and False)
            self._render_state()
            err = res.get("error") or "Sign-in didn't finish."
            self._status_text.setText(f"Not signed in — {err}")

    def _on_sign_out(self) -> None:
        """Sign out via bridge.cloud_sign_out() (server revoke + local
        clear). Falls back to cloud_client.logout() directly with no
        bridge. Result lands via cloud_signout_done (or inline on
        fallback)."""
        if QMessageBox.question(
            self, "Sign out of ArchHub Cloud?",
            "Sign out on this device? Your local brain stays; only the "
            "cloud session ends.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._signout_btn.setEnabled(False)
        b = self._bridge()
        if b is not None and hasattr(b, "cloud_sign_out"):
            try:
                b.cloud_sign_out()
                return
            except Exception:
                pass
        # Direct fallback.
        cc = _cloud_client()
        if cc is not None and hasattr(cc, "logout"):
            try:
                cc.logout()
            except Exception:
                pass
        self._on_signout_done(json.dumps({"ok": True, "signed_in": False}))

    def _on_signout_done(self, result_json: str) -> None:
        """cloud_signout_done handler — flip to signed-out, refresh."""
        res = {}
        try:
            res = json.loads(result_json or "{}") or {}
        except Exception:
            res = {}
        self._signed_in = False
        self._busy = False
        self._render_state()
        self._detail.setText("")
        msg = res.get("msg") or "Signed out."
        self._status_text.setText(msg if not res.get("ok")
                                   else "Not signed in.")
        self._refresh()
        self._parent_dlg.notify_changed()


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
        dv.addWidget(_danger_row(
            "Export brain",
            "Download the full SQLite + skill markdowns. Restorable on any device.",
            self._on_export_brain,
        ))
        dv.addWidget(_danger_row(
            "Clear cache",
            "Wipes the resilient-client journal + cached context. Daemon untouched.",
            self._on_clear_brain_cache,
        ))
        dv.addWidget(_danger_row(
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


# ── Tab: Accessibility (Track E, WCAG 2.1 AA work in progress) ─────────
class AccessibilityTab(QWidget):
    """Per-user accessibility preferences — font size · contrast ·
    motion · screen-reader optimisation.

    Talks to ``brain.a11y_prefs`` on the local daemon. Prefs land at
    USER scope in the brain so they sync cross-device via the federation
    transport (per AgDR-0044 + Track E of the Content Ecosystem plan).

    Honest scope (ANTI-LIE):
        - Controls render + persist LOCALLY (secrets_store, keys
          ``a11y_*``) as the reliable source of truth, and ALSO sync to
          the brain best-effort when the daemon exposes
          ``brain.a11y_prefs`` (the save no longer fails if it doesn't).
        - reduce-motion is APPLIED: the React UI reads bridge
          ``get_a11y_prefs`` on mount and toggles the ``lm-reduce-motion``
          class (disables canvas animations app-wide, beyond the OS
          ``prefers-reduced-motion`` query).
        - font-size, contrast, and screen-reader-optimised PERSIST but are
          not applied yet (px→scale refactor / high-contrast palette /
          component aria-live work) — deferred pending a design decision,
          NOT faked.
        - The audit doc + full WCAG sweep is multi-session work; this
          tab is the entry point, not the conclusion.
    """

    DAEMON_URL = "http://127.0.0.1:8473/mcp"

    FONT_SIZES = [
        ("Small",   "small"),
        ("Medium",  "medium"),
        ("Large",   "large"),
        ("X-Large", "xlarge"),
    ]
    CONTRASTS = [
        ("Normal",  "normal"),
        ("High",    "high"),
    ]

    def __init__(self, parent_dialog: "SettingsDialog"):
        super().__init__()
        self._parent_dlg = parent_dialog
        self.setObjectName("settingsPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        _add_title(
            outer, "Accessibility",
            "Font size, contrast, motion. Preferences live in your brain "
            "so they follow you across every device you sign in on.",
            scope="USER",
        )

        # ── Display card (font size · contrast) ─────────────────────
        disp = QGroupBox("Display")
        df = QFormLayout(disp); df.setSpacing(8); df.setContentsMargins(12, 18, 12, 12)

        self._font_pick = QComboBox()
        self._font_pick.setObjectName("a11yFontSize")
        self._font_pick.setAccessibleName("Font size")
        self._font_pick.setAccessibleDescription(
            "Choose the base font size used across ArchHub surfaces."
        )
        for label, val in self.FONT_SIZES:
            self._font_pick.addItem(label, val)
        df.addRow("Font size", self._font_pick)

        self._contrast_pick = QComboBox()
        self._contrast_pick.setObjectName("a11yContrast")
        self._contrast_pick.setAccessibleName("Contrast")
        self._contrast_pick.setAccessibleDescription(
            "High contrast strengthens text + border colours to meet "
            "WCAG 2.1 AAA where the default theme is AA-borderline."
        )
        for label, val in self.CONTRASTS:
            self._contrast_pick.addItem(label, val)
        df.addRow("Contrast", self._contrast_pick)

        outer.addWidget(disp)

        # ── Motion + reader card ────────────────────────────────────
        motion = QGroupBox("Motion & assistive tech")
        mv = QVBoxLayout(motion); mv.setSpacing(8); mv.setContentsMargins(12, 18, 12, 12)
        mv_hint = QLabel(
            "Reduce motion turns off canvas animations + transitions "
            "(maps to <code>prefers-reduced-motion</code>). "
            "Screen-reader optimised expands ARIA live regions so a "
            "screen reader narrates every state change."
        )
        mv_hint.setObjectName("muted"); mv_hint.setWordWrap(True)
        mv.addWidget(mv_hint)

        self._reduce_motion = QCheckBox("Reduce motion")
        self._reduce_motion.setObjectName("a11yReduceMotion")
        self._reduce_motion.setAccessibleName("Reduce motion")
        self._reduce_motion.setAccessibleDescription(
            "Disable canvas + UI animations."
        )
        mv.addWidget(self._reduce_motion)

        self._sr_opt = QCheckBox("Screen-reader optimised")
        self._sr_opt.setObjectName("a11yScreenReader")
        self._sr_opt.setAccessibleName("Screen-reader optimised")
        self._sr_opt.setAccessibleDescription(
            "Expand ARIA live regions so screen readers narrate state."
        )
        mv.addWidget(self._sr_opt)
        outer.addWidget(motion)

        # ── Status / audit doc link ─────────────────────────────────
        status = QGroupBox("Audit status")
        sv = QVBoxLayout(status); sv.setSpacing(6); sv.setContentsMargins(12, 18, 12, 12)
        self._status_label = QLabel("Loading prefs from brain…")
        self._status_label.setObjectName("muted")
        self._status_label.setWordWrap(True)
        sv.addWidget(self._status_label)
        audit_hint = QLabel(
            "Full WCAG 2.1 AA audit lives at "
            "<code>docs/ACCESSIBILITY-AUDIT-2026-05-26.md</code>. "
            "Per ANTI-LIE: this tab + a11y_prefs storage is the "
            "current floor — not the AA finish line."
        )
        audit_hint.setObjectName("muted"); audit_hint.setWordWrap(True)
        sv.addWidget(audit_hint)
        outer.addWidget(status)

        outer.addStretch(1)

        # ── Save row ───────────────────────────────────────────────
        save_row = QHBoxLayout()
        self._save_btn = QPushButton("Save changes")
        self._save_btn.setObjectName("primary")
        self._save_btn.setAccessibleName("Save accessibility preferences")
        self._save_btn.clicked.connect(self._save)
        save_row.addStretch(1)
        save_row.addWidget(self._save_btn)
        outer.addLayout(save_row)

        # Load current prefs on construction.
        self._load()

    # ── HTTP helpers ─────────────────────────────────────────────────

    def _mcp_call(self, tool: str, args: dict | None = None,
                  *, timeout: float = 2.0) -> dict:
        """Same SSE-aware POST as BrainTab._mcp_call. Kept local so the
        tab can be exercised without instantiating BrainTab."""
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

    # ── load / save ──────────────────────────────────────────────────

    DEFAULT_PREFS = {
        "font_size": "medium",
        "contrast": "normal",
        "reduce_motion": False,
        "screen_reader_optimised": False,
    }

    def _load(self) -> None:
        """Populate the widgets from the most reliable source available.

        Order of precedence (2026-06-03 — a11y prefs made REAL):
          1. LOCAL persisted prefs (secrets_store.save_setting), the
             source of truth — written every Save, always present once
             the user has saved once, works with the daemon absent.
          2. brain.a11y_prefs (best-effort cross-device sync) — fills
             only the keys the local store hasn't set yet.
          3. DEFAULT_PREFS for anything still unset.

        Local-first means the controls round-trip RELIABLY: a saved
        Reduce-motion choice survives a restart even when the daemon
        never exposes brain.a11y_prefs."""
        prefs = dict(self.DEFAULT_PREFS)

        # (2) Best-effort brain sync — non-fatal, may be absent.
        synced = False
        resp = self._mcp_call("brain.a11y_prefs", {"mode": "get"})
        if isinstance(resp, dict) and resp.get("ok") and isinstance(
            resp.get("prefs"), dict
        ):
            prefs.update(resp["prefs"])
            synced = True

        # (1) LOCAL persisted prefs win over brain + defaults.
        local_font = load_setting("a11y_font_size")
        local_contrast = load_setting("a11y_contrast")
        local_motion = load_setting("a11y_reduce_motion")
        local_sr = load_setting("a11y_screen_reader")
        have_local = any(v is not None for v in (
            local_font, local_contrast, local_motion, local_sr))
        if local_font is not None:
            prefs["font_size"] = local_font
        if local_contrast is not None:
            prefs["contrast"] = local_contrast
        if local_motion is not None:
            prefs["reduce_motion"] = bool(local_motion)
        if local_sr is not None:
            prefs["screen_reader_optimised"] = bool(local_sr)

        if have_local and synced:
            self._status_label.setText(
                "Prefs loaded from this device (also synced to your "
                "brain so they follow you across devices)."
            )
            self._status_label.setStyleSheet(f"color:{TOKENS['good']};")
        elif have_local:
            self._status_label.setText(
                "Prefs loaded from this device. They are saved locally "
                "and will sync to your brain when it's available."
            )
            self._status_label.setStyleSheet(f"color:{TOKENS['good']};")
        elif synced:
            self._status_label.setText(
                "Prefs loaded from your brain — these sync across every "
                "device you sign in on."
            )
            self._status_label.setStyleSheet(f"color:{TOKENS['good']};")
        else:
            self._status_label.setText(
                "No saved preferences yet — showing defaults. Save "
                "stores them on this device (and syncs to your brain "
                "when available)."
            )
            self._status_label.setStyleSheet(f"color:{TOKENS['muted']};")

        # Push values into widgets.
        idx = self._font_pick.findData(prefs.get("font_size", "medium"))
        if idx >= 0:
            self._font_pick.setCurrentIndex(idx)
        idx = self._contrast_pick.findData(prefs.get("contrast", "normal"))
        if idx >= 0:
            self._contrast_pick.setCurrentIndex(idx)
        self._reduce_motion.setChecked(bool(prefs.get("reduce_motion")))
        self._sr_opt.setChecked(bool(prefs.get("screen_reader_optimised")))

    def _collect(self) -> dict:
        return {
            "font_size": self._font_pick.currentData() or "medium",
            "contrast": self._contrast_pick.currentData() or "normal",
            "reduce_motion": bool(self._reduce_motion.isChecked()),
            "screen_reader_optimised": bool(self._sr_opt.isChecked()),
        }

    def _save(self) -> None:
        prefs = self._collect()

        # (1) RELIABLE local persistence — the source of truth. Written
        # under stable keys so bridge.get_a11y_prefs (consumed by the
        # React UI) and _load() both read them back. This makes Save
        # actually persist regardless of whether the daemon exposes the
        # brain.a11y_prefs MCP tool.
        local_ok = True
        try:
            save_setting("a11y_reduce_motion", bool(prefs["reduce_motion"]))
            save_setting("a11y_screen_reader",
                         bool(prefs["screen_reader_optimised"]))
            save_setting("a11y_font_size", str(prefs["font_size"]))
            save_setting("a11y_contrast", str(prefs["contrast"]))
        except Exception as ex:  # pragma: no cover - disk failure is rare
            local_ok = False
            local_err = str(ex)

        # (2) Best-effort cross-device sync via the brain. Absence here is
        # NOT a failure any more — local persistence already succeeded.
        resp = self._mcp_call("brain.a11y_prefs", {
            "mode": "set", "prefs": prefs,
        })
        synced = isinstance(resp, dict) and resp.get("ok")

        if not local_ok:
            # The only real failure mode left: the local write itself
            # failed. Surface it honestly.
            QMessageBox.warning(
                self, "Couldn't save preferences",
                "ArchHub could not write your accessibility preferences "
                "to this device.\n\n"
                f"Error: {local_err[:200]}",
            )
            self._status_label.setText(
                "Save failed — could not write to this device."
            )
            self._status_label.setStyleSheet(f"color:{TOKENS['bad']};")
            return

        if synced:
            QMessageBox.information(
                self, "Saved",
                "Accessibility preferences saved on this device and "
                "synced to your brain, so they follow you across every "
                "device you sign in on.",
            )
            self._status_label.setText(
                "Prefs saved on this device — also synced via brain "
                "federation."
            )
        else:
            QMessageBox.information(
                self, "Saved",
                "Accessibility preferences saved on this device. They "
                "will sync to your brain automatically when it's "
                "available.",
            )
            self._status_label.setText(
                "Prefs saved on this device (brain sync will catch up "
                "when available)."
            )
        self._status_label.setStyleSheet(f"color:{TOKENS['good']};")


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


# ── Back-compat shim for the retired QTabWidget ───────────────────────────
class _TabsCompat:
    """Read-only stand-in for the old `SettingsDialog._tabs` QTabWidget.

    The shell is now a sidebar + QStackedWidget, so there is no real
    QTabWidget. A small amount of dev tooling still reads
    `dlg._tabs.count()` / `dlg._tabs.tabText(i)` (e.g.
    tools/audit_a11y_tab.py). This adapter answers those over the frozen
    canonical TABS label order so that tooling keeps working without a
    crash. It is intentionally minimal — not a QWidget."""

    __slots__ = ("_labels",)

    def __init__(self, labels: list[str]):
        self._labels = list(labels)

    def count(self) -> int:
        return len(self._labels)

    def tabText(self, i: int) -> str:
        return self._labels[i] if 0 <= i < len(self._labels) else ""


# ── Dialog shell ─────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    """ArchHub settings — sidebar + stacked content (5 sections, 12 tabs).

    Public constructor preserved from v1.4:

        SettingsDialog(router, parent=None, manager=None, tools=None, **_kw)

    Callers (bridge.open_settings, chat_window, workspace_shell,
    settings_page) hit this signature; tests don't import this dialog
    directly."""

    # ── Signed IA: a LEFT SIDEBAR of 5 sections, NOT a 12-tab strip ──────
    # AgDR-0045/0046 + docs/prototypes/settings-redesign-2026-06-02.html lock
    # this shape. Each section is one scrollable page; a section with >1 tab
    # stacks its tab widgets vertically, each under a mono-uppercase
    # sub-label. The 12 original *Tab classes are UNCHANGED (shell rebuild —
    # internal merges are a later pass), so all 12 still live, grouped 5-ways.
    #   (section title, sidebar icon glyph, [(tab-label, Tab cls), …])
    SECTIONS = [
        ("General",        "◐", [   # ◐
            ("General",       GeneralTab),
            ("Accessibility", AccessibilityTab),
        ]),
        ("Account & Brain", "◈", [  # ◈
            ("Account",       AccountTab),
            ("Brain",         BrainTab),
            ("Memory",        MemoryTab),
        ]),
        ("AI & Tools",     "✦", [   # ✦
            ("Providers",     ProvidersTab),
            ("Permissions",   PermissionsTab),
        ]),
        ("Connections",    "⛓", [   # ⛓
            ("Hosts",         HostsTab),
            ("Secrets",       SecretsTab),
        ]),
        ("System",         "⚙", [   # ⚙
            # SystemTab FIRST — the native home for the controls migrated
            # off the vestigial React Settings modal (Perf HUD / JSX cache
            # / Reset-prefs) + the unified Forge/Blueprint/Vellum theme.
            # It lives ONLY in SECTIONS (the visual grouping the shell
            # iterates); the frozen TABS contract below stays the 12-label
            # list the tests pin, so this is purely additive to the UI.
            ("System",        SystemTab),
            ("Storage",       StorageTab),
            ("Shortcuts",     ShortcutsTab),
            ("About",         AboutTab),
        ]),
    ]

    # Map a bridge.open_settings(section=...) keyword to a SIDEBAR SECTION
    # title so the founder lands on the right page (e.g. the Brain backup CTA
    # → "Account & Brain"). Every keyword the old flat SECTION_TO_TAB carried
    # is preserved here so focus_section keeps returning True for all of them.
    SECTION = {
        "account":     "Account & Brain",
        "cloud":       "Account & Brain",
        "brain":       "Account & Brain",
        "memory":      "Account & Brain",
        "providers":   "AI & Tools",
        "permissions": "AI & Tools",
        "hosts":       "Connections",
        "secrets":     "Connections",
        "general":     "General",
        "accessibility": "General",
        "about":       "System",
        "storage":     "System",
        "shortcuts":   "System",
    }

    # ── Frozen downstream IA contract (NOT the visual grouping) ───────────
    # The sidebar shell above renders the 12 tabs grouped into 5 sections.
    # These two class attributes remain the documented, order-pinned contract
    # that downstream agents + tests depend on:
    #   • tests/test_settings_dialog_tabs.py asserts TABS == this exact order
    #     (len 12, Brain@5, Secrets@2, Accessibility@9, Account@11).
    #   • tests/test_cloud_signin_wiring.py asserts "Account" in TABS labels
    #     and SECTION_TO_TAB["account"] == "Account".
    # Keeping them here (a) honours PROTOTYPE-IS-CONTRACT without breaking the
    # signed test surface, and (b) gives any code that wants "the canonical
    # list of (label, Tab cls)" a single source. The shell does NOT iterate
    # these — it iterates SECTIONS — so the visual order and this contract
    # order are intentionally independent.
    TABS = [
        ("General",       GeneralTab),
        ("Providers",     ProvidersTab),
        ("Secrets",       SecretsTab),
        ("Hosts",         HostsTab),
        ("Memory",        MemoryTab),
        ("Brain",         BrainTab),
        ("Permissions",   PermissionsTab),
        ("Storage",       StorageTab),
        ("Shortcuts",     ShortcutsTab),
        ("Accessibility", AccessibilityTab),
        ("About",         AboutTab),
        ("Account",       AccountTab),
    ]

    # Legacy keyword → tab-label map (superseded at runtime by SECTION, which
    # maps keyword → sidebar-section title). Retained because downstream code
    # + tests read SECTION_TO_TAB directly; focus_section uses SECTION.
    SECTION_TO_TAB = {
        "account":     "Account",
        "cloud":       "Account",
        "brain":       "Brain",
        "memory":      "Memory",
        "providers":   "Providers",
        "permissions": "Permissions",
        "secrets":     "Secrets",
        "hosts":       "Hosts",
        "general":     "General",
        "accessibility": "General",
        "about":       "About",
        "storage":     "Storage",
        "shortcuts":   "Shortcuts",
    }

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
        # Wider than the old 960 to seat the 220px sidebar AND give the content
        # area ~940px — the width the tab cards were built for — so nothing
        # overflows horizontally (signed shape is sidebar + content, not tabs).
        self.resize(1160, 760)
        self.setStyleSheet(DIALOG_QSS + SHELL_QSS)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        # ── Body: LEFT SIDEBAR (220px) + content QStackedWidget ──────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        shell.addLayout(body, 1)

        # Sidebar column: brand lockup → divider → nav list.
        sidebar = QWidget(self)
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet(f"QWidget#settingsSidebar {{ background:{SIGNED['bg2']}; }}")
        side_col = QVBoxLayout(sidebar)
        side_col.setContentsMargins(12, 18, 0, 12)
        side_col.setSpacing(10)

        # Brand: "Arch" + accent "Hub" + mono "Settings" (top-left).
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(2, 0, 12, 0)
        brand_row.setSpacing(6)
        brand = QLabel(self)
        brand.setObjectName("settingsBrand")
        brand.setTextFormat(Qt.TextFormat.RichText)
        brand.setText(
            f"Arch<span style='color:{SIGNED['accent']}'>Hub</span>"
        )
        brand_row.addWidget(brand)
        brand_sub = QLabel("Settings", self)
        brand_sub.setObjectName("settingsBrandSub")
        brand_sub.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        brand_row.addStretch(1)
        brand_row.addWidget(brand_sub)
        side_col.addLayout(brand_row)

        divider = QFrame(self)
        divider.setObjectName("settingsDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        side_col.addWidget(divider)

        self._nav = QListWidget(self)
        self._nav.setObjectName("settingsNav")
        self._nav.setAccessibleName("Settings sections")
        self._nav.setFrameShape(QFrame.Shape.NoFrame)
        self._nav.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        side_col.addWidget(self._nav, 1)
        body.addWidget(sidebar)

        # Content host.
        self._stack = QStackedWidget(self)
        self._stack.setObjectName("settingsStack")
        body.addWidget(self._stack, 1)

        # ── Build the 5 section pages; keep every tab in _tab_widgets ────
        # _tab_widgets[label] -> tab widget (tests + tab() + focus_section).
        # _tab_section[label] -> stack index of the page that hosts the tab.
        # _tab_scroll[label]  -> the QScrollArea wrapping that page (so
        #                        focus_section can scroll the tab into view).
        self._tab_widgets: dict[str, QWidget] = {}
        self._tab_section: dict[str, int] = {}
        self._tab_scroll: dict[str, QScrollArea] = {}
        self._section_index: dict[str, int] = {}

        for sec_idx, (title, glyph, tabs) in enumerate(self.SECTIONS):
            self._section_index[title] = sec_idx

            # Each section is ONE scrollable page. A page with >1 tab stacks
            # its tab widgets vertically, each under a mono-uppercase label.
            scroll = QScrollArea(self)
            scroll.setObjectName("settingsScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            # Vertical-only: content fits the widened area, so never a
            # horizontal scrollbar (founder 2026-06-03 screenshot caught one).
            scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )

            page = QWidget()
            page.setObjectName("settingsSectionPage")
            page_col = QVBoxLayout(page)
            page_col.setContentsMargins(28, 26, 28, 26)
            page_col.setSpacing(14)

            multi = len(tabs) > 1
            for label, cls in tabs:
                if multi:
                    page_col.addWidget(self._make_sub_label(label))
                w = cls(self)
                page_col.addWidget(w)
                self._tab_widgets[label] = w
                self._tab_section[label] = sec_idx
                self._tab_scroll[label] = scroll
            page_col.addStretch(1)

            scroll.setWidget(page)
            self._stack.addWidget(scroll)

            item = QListWidgetItem(f"{glyph}   {title}")
            # a11y: screen readers announce the clean section title, not the
            # decorative glyph prefix (AccessibleTextRole overrides display text).
            item.setData(Qt.ItemDataRole.AccessibleTextRole, title)
            self._nav.addItem(item)

        # Wire the sidebar selection to the content stack.
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        # Back-compat: the old shell exposed a QTabWidget at self._tabs.
        # Downstream dev tooling (tools/audit_a11y_tab.py) reads
        # self._tabs.count() / .tabText(i). The sidebar shell has no
        # QTabWidget, so expose a tiny read-only adapter over the frozen
        # TABS order (the canonical 12-label list) so that tooling keeps
        # resolving labels.index("Accessibility") etc. without a crash.
        self._tabs = _TabsCompat([label for label, _cls in self.TABS])

        # ── Footer — single Close button (founder's "no save whiplash"). ─
        footer = QHBoxLayout()
        footer.setContentsMargins(28, 10, 28, 12)
        version_lbl = QLabel(f"v{_read_version()}")
        version_lbl.setObjectName("muted")
        footer.addWidget(version_lbl)
        footer.addStretch(1)
        close = QPushButton("Close"); close.setObjectName("primary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        shell.addLayout(footer)

    # ── Mono-uppercase section sub-label (per signed tokens) ──────────────
    def _make_sub_label(self, text: str) -> QLabel:
        """A small mono-uppercase divider shown above each tab widget inside
        a multi-tab section page. Qt QSS ignores text-transform/letter-spacing,
        so uppercase here + set tracking on the QFont for signed fidelity."""
        lbl = QLabel((text or "").upper(), self)
        lbl.setObjectName("sectionSubLabel")
        f = QFont(lbl.font())
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 114)  # ~.14em
        lbl.setFont(f)
        return lbl

    # ── Public API consumed by ProvidersTab (provider sign-in changes) ────
    def notify_changed(self) -> None:
        """A provider signed in / out; clear router cache + nudge parent."""
        if self.router and hasattr(self.router, "invalidate_clients"):
            try: self.router.invalidate_clients()
            except Exception: pass  # audit: deliberate-fail-soft — best-effort router client-cache invalidation on provider change
        if self.router and hasattr(self.router, "_clients"):
            try: self.router._clients.clear()
            except Exception: pass  # audit: deliberate-fail-soft — best-effort router client-cache clear on provider change
        parent = self.parent()
        if parent is not None and hasattr(parent, "_refresh_model_picker"):
            try: parent._refresh_model_picker()
            except Exception: pass  # audit: deliberate-fail-soft — best-effort model-picker refresh nudge

    # ── Convenience used in tests / scripts that want a tab by name ───
    def tab(self, label: str) -> QWidget | None:
        return self._tab_widgets.get(label)

    # ── Focus a section by keyword (bridge.open_settings(section)) ────────
    def focus_section(self, section: str) -> bool:
        """Select the SIDEBAR ROW whose section owns `section` (e.g.
        "account"/"brain"/"memory" → the "Account & Brain" row) and scroll
        that section's target tab into view. Returns True if a row was
        selected. Called by bridge.open_settings BEFORE exec() so the founder
        lands on the right page — e.g. the Brain "Back up my brain" signed-out
        CTA routes here with section="account". Unknown / empty section is a
        no-op (keeps the default first row)."""
        key = (section or "").strip().lower()
        title = self.SECTION.get(key)
        if not title:
            return False
        sec_idx = self._section_index.get(title)
        if sec_idx is None:
            return False
        self._nav.setCurrentRow(sec_idx)  # fires currentRowChanged -> stack

        # Best-effort: scroll the specific tab the keyword names into view
        # (sections with >1 tab stack vertically). Most keywords map 1:1 to a
        # tab label (brain→Brain, memory→Memory, secrets→Secrets, …); fall
        # back to the section's first tab when there's no exact tab match.
        section_tabs = next(
            (tabs for t, g, tabs in self.SECTIONS if t == title), []
        )
        target_label = next(
            (lbl for lbl, _cls in section_tabs if lbl.lower() == key),
            section_tabs[0][0] if section_tabs else None,
        )
        w = self._tab_widgets.get(target_label) if target_label else None
        scroll = self._tab_scroll.get(target_label) if target_label else None
        if w is not None and scroll is not None:
            try:
                scroll.ensureWidgetVisible(w, 0, 0)
            except Exception:
                pass  # audit: deliberate-fail-soft — scroll-into-view is cosmetic
        return True
