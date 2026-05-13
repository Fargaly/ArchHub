"""Settings — click-only sign-in for LLM providers, optional Speckle.

The architect never types or pastes an API key. Each provider gets a row
showing its connection status; one click opens the provider's site, and
ArchHub watches the clipboard to pick up the new key automatically when
the user copies it.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from secrets_store import save_api_key, load_api_key, delete_api_key, save_setting, load_setting
from sign_in import DISPLAY_NAMES
from sign_in_dialog import SignInDialog


# LLM providers — env var is checked as a fallback when no saved key exists.
# OpenRouter is at the top because it's the lowest-friction option:
# real OAuth, one sign-in covers Claude / GPT / Gemini / Llama / Qwen.
LLM_PROVIDERS = [
    ("openrouter", "OpenRouter (one OAuth, ~300 models)", ""),
    ("anthropic",  "Anthropic",                            "ANTHROPIC_API_KEY"),
    ("openai",     "OpenAI",                               "OPENAI_API_KEY"),
    ("google",     "Google",                               "GOOGLE_API_KEY"),
]


def _key_present(provider: str, env_var: str) -> bool:
    if load_api_key(provider):
        return True
    return bool(os.environ.get(env_var, ""))


class _ProviderRow(QFrame):
    """One row showing a provider's connection state + a Sign in / Sign out button."""

    def __init__(self, provider: str, env_var: str, parent_dialog):
        super().__init__()
        self.provider = provider
        self.env_var = env_var
        self.parent_dialog = parent_dialog
        self.setObjectName("providerRow")

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        # Typographic bullet — BRAND.voice rule 2 forbids emoji. The
        # providerIcon QSS draws a bordered terra plate around this so
        # it still reads as a credential slot.
        self.icon = QLabel("·")
        self.icon.setObjectName("providerIcon")
        h.addWidget(self.icon)

        self.label = QLabel(DISPLAY_NAMES.get(provider, provider.title()))
        self.label.setObjectName("providerName")
        h.addWidget(self.label)

        self.status = QLabel("")
        self.status.setObjectName("providerStatus")
        h.addWidget(self.status)
        h.addStretch(1)

        self.action_btn = QPushButton("")
        self.action_btn.setObjectName("ghostButton")
        self.action_btn.clicked.connect(self._on_action)
        h.addWidget(self.action_btn)

        self.refresh()

    def refresh(self) -> None:
        if _key_present(self.provider, self.env_var):
            # Filled bullet = key present; hollow circle = none. Both
            # are typographic, not emoji.
            self.icon.setText("●")
            masked = self._masked_key()
            self.status.setText(f"<i>signed in {masked}</i>")
            self.action_btn.setText("Sign out")
        else:
            self.icon.setText("○")
            self.status.setText("<i>not signed in</i>")
            self.action_btn.setText(f"Sign in with {self.label.text()}")

    def _masked_key(self) -> str:
        key = load_api_key(self.provider) or os.environ.get(self.env_var, "")
        if not key:
            return ""
        return f"({key[:8]}…)"

    def _on_action(self) -> None:
        if _key_present(self.provider, self.env_var):
            if QMessageBox.question(
                self, f"Sign out of {self.label.text()}?",
                f"Remove the saved {self.label.text()} key from this device?",
            ) == QMessageBox.StandardButton.Yes:
                delete_api_key(self.provider)
                self.refresh()
                self.parent_dialog.notify_changed()
            return

        dlg = SignInDialog(self.provider, self)
        dlg.signed_in.connect(lambda _p: self.parent_dialog.notify_changed())
        dlg.exec()
        self.refresh()


class SettingsDialog(QDialog):
    def __init__(self, router, parent=None):
        super().__init__(parent)
        self.router = router
        self.setWindowTitle("ArchHub — Settings")
        self.setObjectName("settingsDialog")
        # Bumped from 560×520 in v1.0.2 — the AI Behaviour section
        # (thinking + per-tool policies) needs a taller dialog so
        # everything fits without forcing a global scroll.
        self.resize(640, 720)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        title = QLabel("Sign-ins")
        title.setObjectName("settingsTitle")
        outer.addWidget(title)

        sub = QLabel(
            "ArchHub never asks you to type or paste an API key. Click "
            "<b>Sign in</b>, copy the key from the provider's site, and "
            "ArchHub will detect it on your clipboard automatically."
        )
        sub.setObjectName("settingsSubtitle")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # ── Cloud sync ─────────────────────────────────────────────────────
        outer.addWidget(self._build_cloud_sync_row())

        # ── Provider rows ──────────────────────────────────────────────────
        self._rows: list[_ProviderRow] = []
        for prov, _label, env_var in LLM_PROVIDERS:
            row = _ProviderRow(prov, env_var, self)
            self._rows.append(row)
            outer.addWidget(row)

        # ── "Show local Ollama models" toggle ──────────────────────────────
        self._show_local = QCheckBox(
            "Show local Ollama models in the picker  (advanced; local is slower than cloud)"
        )
        self._show_local.setObjectName("settingsSubtitle")
        self._show_local.setChecked(bool(load_setting("show_local_models")))
        outer.addWidget(self._show_local)

        # ── Firm relay (path B — OpenAI-compatible self-hosted endpoint) ───
        # Hidden behind "Show advanced" toggle in v1.3.1 — most users
        # never run their own OpenAI-compatible gateway. The fields stay
        # populated from disk so values persist across the collapse. To
        # revive default visibility: drop the `relay_box.setVisible(False)`
        # line below and remove the advanced toggle wrapper.
        relay_box = QFrame()
        relay_box.setObjectName("providerRow")
        rb = QVBoxLayout(relay_box)
        rb.setContentsMargins(12, 10, 12, 10)
        rb.setSpacing(6)

        relay_title = QLabel("Firm relay  <i>(optional, OpenAI-compatible)</i>")
        relay_title.setObjectName("providerName")
        rb.addWidget(relay_title)

        relay_help = QLabel(
            "If your firm runs its own OpenAI-compatible gateway "
            "(LiteLLM, AnyScale, vLLM, a custom proxy, etc.), point ArchHub "
            "at it here. Architects use one shared firm token; provider keys "
            "stay on the relay."
        )
        relay_help.setObjectName("settingsSubtitle")
        relay_help.setWordWrap(True)
        rb.addWidget(relay_help)

        relay_form = QHBoxLayout()
        relay_form.setSpacing(6)

        self._relay_url = QLineEdit()
        self._relay_url.setPlaceholderText("https://relay.yourfirm.com/v1")
        self._relay_url.setText(load_setting("relay_base_url") or "")
        relay_form.addWidget(self._relay_url, 2)

        self._relay_token = QLineEdit()
        self._relay_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._relay_token.setPlaceholderText("Relay token")
        existing_relay = load_api_key("relay")
        if existing_relay:
            self._relay_token.setText(existing_relay)
        relay_form.addWidget(self._relay_token, 1)

        rb.addLayout(relay_form)
        # Show advanced disclosure — collapsed by default unless the user
        # already has a relay URL saved (in which case keeping it hidden
        # would be confusing).
        has_relay = bool((load_setting("relay_base_url") or "").strip())
        self._show_relay = QCheckBox("Show advanced — firm relay")
        self._show_relay.setObjectName("settingsSubtitle")
        self._show_relay.setChecked(has_relay)
        relay_box.setVisible(has_relay)
        self._show_relay.toggled.connect(relay_box.setVisible)
        outer.addWidget(self._show_relay)
        outer.addWidget(relay_box)

        # ── Speckle (optional, collapsed by default) ───────────────────────
        from PyQt6.QtWidgets import QRadioButton, QButtonGroup

        self._speckle_toggle = QCheckBox(
            "Use Speckle for cross-tool data sync  (optional — keep off if you don't need it)"
        )
        self._speckle_toggle.setObjectName("settingsSubtitle")
        speckle_enabled = bool(load_setting("speckle_enabled"))
        self._speckle_toggle.setChecked(speckle_enabled)
        outer.addWidget(self._speckle_toggle)

        self._speckle_widget = QWidget()
        speckle_box = QVBoxLayout(self._speckle_widget)
        speckle_box.setContentsMargins(0, 4, 0, 0)
        speckle_box.setSpacing(6)

        # Cloud is the default and only first-class path. Self-host is
        # collapsed under an "Advanced" toggle to keep the UI light.
        owner_label = QLabel("Defaults to <b>app.speckle.systems</b> — no setup.")
        owner_label.setObjectName("settingsSubtitle")
        owner_label.setWordWrap(True)
        speckle_box.addWidget(owner_label)

        self._speckle_owner_group = QButtonGroup(self._speckle_widget)
        self._sp_cloud = QRadioButton("Speckle cloud  (recommended)")
        self._sp_self = QRadioButton("Self-host  (advanced)")
        self._speckle_owner_group.addButton(self._sp_cloud, 0)
        self._speckle_owner_group.addButton(self._sp_self, 1)
        radio_row = QHBoxLayout(); radio_row.setSpacing(16)
        radio_row.addWidget(self._sp_cloud); radio_row.addWidget(self._sp_self)
        radio_row.addStretch(1)
        radio_wrap = QFrame(); radio_wrap.setLayout(radio_row)
        speckle_box.addWidget(radio_wrap)

        # Pre-select based on current server setting.
        current_server = (load_setting("speckle_server") or "").strip()
        if current_server and "speckle.systems" not in current_server:
            self._sp_self.setChecked(True)
        else:
            self._sp_cloud.setChecked(True)

        self_host_box = QFrame(); self_host_box.setObjectName("providerRow")
        sh = QFormLayout(self_host_box); sh.setContentsMargins(10, 8, 10, 8); sh.setSpacing(6)
        self._speckle_server = QLineEdit()
        self._speckle_server.setPlaceholderText("http://localhost:3000")
        if current_server and "speckle.systems" not in current_server:
            self._speckle_server.setText(current_server)
        sh.addRow("Self-hosted URL", self._speckle_server)

        own_help = QLabel(
            "Speckle is open-source (Apache-2.0). The button below installs "
            "Docker Desktop if needed, clones the speckle-server repo, and "
            "runs the full stack on this machine. URL becomes "
            "<code>http://localhost:3000</code>."
        )
        own_help.setObjectName("settingsSubtitle"); own_help.setWordWrap(True)
        sh.addRow("", own_help)

        setup_btn = QPushButton("Set up local Speckle for me")
        setup_btn.setObjectName("primaryButton")
        setup_btn.setToolTip(
            "Runs Setup-Speckle.bat in a console window. Installs Docker "
            "Desktop if needed, clones speckle-server, brings the stack up."
        )
        setup_btn.clicked.connect(self._run_speckle_setup)
        sh.addRow("", setup_btn)

        speckle_box.addWidget(self_host_box)
        self_host_box.setVisible(self._sp_self.isChecked())
        self._sp_self.toggled.connect(self_host_box.setVisible)

        # Token (still required — Speckle has no desktop-app OAuth).
        token_label = QLabel("<b>Personal Access Token</b>")
        token_label.setObjectName("settingsSubtitle")
        speckle_box.addWidget(token_label)

        token_row = QHBoxLayout(); token_row.setSpacing(6)
        self._speckle_field = QLineEdit()
        self._speckle_field.setEchoMode(QLineEdit.EchoMode.Password)
        existing_tok = load_api_key("speckle")
        if existing_tok:
            self._speckle_field.setText(existing_tok)
        else:
            self._speckle_field.setPlaceholderText(
                "Paste a Speckle PAT (Speckle has no OAuth for desktop apps)"
            )
        token_row.addWidget(self._speckle_field, 1)
        sp_show = QPushButton("Show"); sp_show.setFixedWidth(56); sp_show.setObjectName("ghostButton")
        sp_show.setCheckable(True)
        sp_show.toggled.connect(
            lambda c: self._speckle_field.setEchoMode(
                QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password
            )
        )
        token_row.addWidget(sp_show)
        sp_clear = QPushButton("Clear"); sp_clear.setObjectName("ghostButton")
        sp_clear.clicked.connect(self._clear_speckle)
        token_row.addWidget(sp_clear)
        token_wrap = QWidget(); token_wrap.setLayout(token_row)
        speckle_box.addWidget(token_wrap)

        self._speckle_widget.setVisible(speckle_enabled)
        self._speckle_toggle.toggled.connect(self._speckle_widget.setVisible)
        outer.addWidget(self._speckle_widget)

        # ── Construction PM ───────────────────────────────────────────────
        # Procore is the dominant SaaS for construction PM (RFIs,
        # submittals, change orders, daily logs). Token + company id +
        # project id live in secrets_store; the runner is stateless.
        # Procore has OAuth but for desktop tooling a long-lived
        # Personal Access Token (minted in Procore admin) is simpler
        # and matches how Speckle is handled here.
        outer.addWidget(self._build_procore_row())

        # ── Appearance — HUD overlay toggle ────────────────────────────────
        from PyQt6.QtCore import Qt as _Qt
        appearance_box = QFrame(); appearance_box.setObjectName("providerRow")
        ab = QVBoxLayout(appearance_box); ab.setContentsMargins(12, 10, 12, 10); ab.setSpacing(6)
        ab_title = QLabel("Appearance"); ab_title.setObjectName("providerName")
        ab.addWidget(ab_title)
        ab_help = QLabel(
            "<b>HUD overlay mode</b> (off by default) — frameless, always-on-top, "
            "translucent. Floats over Revit / AutoCAD / Blender. "
            "<kbd>Ctrl + Space</kbd> toggles, <kbd>Esc</kbd> collapses.<br>"
            "Off = normal window — opens only when you summon ArchHub. "
            "The ambient layer stays the pet strip either way."
        )
        ab_help.setObjectName("settingsSubtitle"); ab_help.setWordWrap(True)
        ab.addWidget(ab_help)
        self._hud_overlay = QCheckBox("Use HUD overlay chrome")
        self._hud_overlay.setObjectName("settingsSubtitle")
        # Default OFF — opt-in only. The pet strip is the ambient layer;
        # turning HUD on makes the entire chat panel always-on-top too.
        self._hud_overlay.setChecked(bool(load_setting("hud_overlay_mode")))
        ab.addWidget(self._hud_overlay)

        # HUD toggle hotkey — collapsed inside an "advanced" disclosure
        # in v1.3.1. The default `ctrl+space` works for the overwhelming
        # majority of users; the rebind field is power-user kit. To
        # revive default visibility: drop the `hk_wrap.setVisible(...)`
        # gating below.
        hk_wrap = QWidget()
        hk_v = QVBoxLayout(hk_wrap)
        hk_v.setContentsMargins(0, 0, 0, 0)
        hk_v.setSpacing(6)
        hk_form = QFormLayout(); hk_form.setSpacing(6)
        self._hud_hotkey = QLineEdit()
        self._hud_hotkey.setPlaceholderText("ctrl+space")
        self._hud_hotkey.setText(load_setting("hud_hotkey") or "ctrl+space")
        hk_form.addRow("Toggle hotkey", self._hud_hotkey)
        hk_help = QLabel(
            "Examples: <code>ctrl+space</code>, <code>ctrl+shift+a</code>, "
            "<code>f8</code>, <code>alt+f9</code>. Restart ArchHub after "
            "changing. Press once and HUD appears; press again or "
            "<kbd>Esc</kbd> to collapse to pet strip."
        )
        hk_help.setObjectName("settingsSubtitle"); hk_help.setWordWrap(True)
        hk_v.addLayout(hk_form)
        hk_v.addWidget(hk_help)

        # Show advanced disclosure — collapsed unless a non-default hotkey
        # has already been saved (so users who set one don't lose access).
        saved_hk = (load_setting("hud_hotkey") or "ctrl+space").lower().strip()
        self._show_hud_hotkey = QCheckBox("Show advanced — rebind hotkey")
        self._show_hud_hotkey.setObjectName("settingsSubtitle")
        non_default = saved_hk and saved_hk != "ctrl+space"
        self._show_hud_hotkey.setChecked(bool(non_default))
        hk_wrap.setVisible(bool(non_default))
        self._show_hud_hotkey.toggled.connect(hk_wrap.setVisible)
        ab.addWidget(self._show_hud_hotkey)
        ab.addWidget(hk_wrap)

        outer.addWidget(appearance_box)

        # ── AI Behaviour ───────────────────────────────────────────────────
        # Thinking-effort dropdown + per-tool policies, grouped by host.
        # Sections only render for hosts whose tools are registered with
        # the live tool_engine — install a new connector, restart, and a
        # new section appears here. No code change needed.
        outer.addWidget(self._build_ai_behaviour_row())

        # ── Privacy / telemetry ────────────────────────────────────────────
        outer.addWidget(self._build_privacy_row())

        outer.addStretch(1)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close"); close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ai_behaviour_row(self):
        """AI Behaviour panel — thinking budget + per-tool policy.

        Renders dynamically from `tool_engine.TOOLS`. New connectors
        appear here without any code change as soon as they register
        their tools.
        """
        import ai_behaviour as _aib

        row = QFrame(); row.setObjectName("providerRow")
        v = QVBoxLayout(row); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(8)

        title_row = QHBoxLayout(); title_row.setSpacing(8)
        # No emoji per BRAND.voice rule 2 — typographic plate instead.
        icon = QLabel("AI"); icon.setObjectName("providerIcon")
        title_row.addWidget(icon)
        title = QLabel("AI Behaviour"); title.setObjectName("providerName")
        title_row.addWidget(title); title_row.addStretch(1)
        v.addLayout(title_row)

        help_lbl = QLabel(
            "Control how hard the model thinks and which tools it can run "
            "without asking you first. Sections below appear only for hosts "
            "ArchHub has detected — connect a new host and it shows up here "
            "automatically on next restart."
        )
        help_lbl.setObjectName("settingsSubtitle"); help_lbl.setWordWrap(True)
        v.addWidget(help_lbl)

        # Thinking effort ----------------------------------------------------
        eff_row = QHBoxLayout(); eff_row.setSpacing(8)
        eff_lbl = QLabel("Extended thinking"); eff_lbl.setObjectName("settingsSubtitle")
        eff_row.addWidget(eff_lbl)
        eff_row.addStretch(1)
        self._thinking_combo = QComboBox()
        self._thinking_combo.addItem("Off — fastest, cheapest", "off")
        self._thinking_combo.addItem("Low (1k tokens) — quick reasoning", "low")
        self._thinking_combo.addItem("Medium (4k tokens) — balanced", "medium")
        self._thinking_combo.addItem("High (16k tokens) — deepest", "high")
        current_effort = _aib.get_thinking_effort()
        idx = next((i for i in range(self._thinking_combo.count())
                    if self._thinking_combo.itemData(i) == current_effort), 0)
        self._thinking_combo.setCurrentIndex(idx)
        self._thinking_combo.currentIndexChanged.connect(
            lambda _: _aib.set_thinking_effort(
                self._thinking_combo.currentData() or "off"
            )
        )
        eff_row.addWidget(self._thinking_combo, 0)
        v.addLayout(eff_row)

        # Per-tool policy ----------------------------------------------------
        section_caption = QLabel("Tool permissions")
        section_caption.setObjectName("providerName")
        v.addWidget(section_caption)

        # Scrollable container so the dialog stays a sensible height
        # even when the user has 60+ tools registered.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(260)
        scroll.setStyleSheet("QScrollArea{ background:transparent; border:none; }")
        inner = QWidget()
        inner_v = QVBoxLayout(inner)
        inner_v.setContentsMargins(0, 0, 0, 0)
        inner_v.setSpacing(6)

        grouped = _aib.tools_grouped_by_host()
        if not grouped:
            empty = QLabel(
                "No tools registered yet. Install a connector from "
                "Connectors → Add Host and reopen Settings."
            )
            empty.setObjectName("settingsSubtitle"); empty.setWordWrap(True)
            inner_v.addWidget(empty)
        else:
            self._tool_policy_combos: dict[str, QComboBox] = {}
            for family, tools in grouped.items():
                label = _aib.host_display_label(family)
                hdr = QLabel(f"<b>{label}</b>  <span style='opacity:0.65'>· {len(tools)} tool"
                              f"{'s' if len(tools) != 1 else ''}</span>")
                hdr.setObjectName("settingsSubtitle")
                hdr.setTextFormat(Qt.TextFormat.RichText)
                inner_v.addWidget(hdr)
                for tool in tools:
                    inner_v.addLayout(self._make_tool_policy_row(tool, _aib))
                inner_v.addSpacing(4)

        inner_v.addStretch(1)
        scroll.setWidget(inner)
        v.addWidget(scroll)

        return row

    def _make_tool_policy_row(self, tool: dict, aib_mod):
        """One QHBoxLayout per tool: name + tooltip + Allow/Ask/Deny combo."""
        h = QHBoxLayout(); h.setSpacing(8)
        # Tool name — leave the family prefix off for compactness.
        bare = tool["name"]
        if "_" in bare:
            bare = bare.split("_", 1)[1]
        name_lbl = QLabel(bare)
        name_lbl.setObjectName("settingsSubtitle")
        name_lbl.setMinimumWidth(180)
        name_lbl.setToolTip(f"{tool['name']}\n\n{tool['description']}")
        h.addWidget(name_lbl, 1)

        combo = QComboBox()
        combo.addItem("Allow", "allow")
        combo.addItem("Ask",   "ask")
        combo.addItem("Deny",  "deny")
        for i in range(combo.count()):
            if combo.itemData(i) == tool["policy"]:
                combo.setCurrentIndex(i); break
        combo.setToolTip(
            f"Default: {tool['default']}"
            + (" (user override)" if tool["overridden"] else "")
        )
        tool_name = tool["name"]
        combo.currentIndexChanged.connect(
            lambda _, t=tool_name, c=combo:
                aib_mod.set_tool_policy(t, c.currentData() or "allow")
        )
        self._tool_policy_combos[tool_name] = combo
        h.addWidget(combo, 0)
        return h

    # ─────────────────────────────────────────────────────────────────────────
    def _build_privacy_row(self):
        """Privacy + telemetry config: opt-in toggle + PostHog/Sentry keys.

        All three knobs are independent — a user can opt IN to telemetry
        while leaving Sentry off, or vice-versa. Empty key fields = that
        provider stays silent (no events shipped) regardless of consent."""
        import telemetry as _tel
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        row = QFrame(); row.setObjectName("providerRow")
        v = QVBoxLayout(row); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(6)

        title_row = QHBoxLayout(); title_row.setSpacing(8)
        icon = QLabel("Pr"); icon.setObjectName("providerIcon")
        title_row.addWidget(icon)
        title = QLabel("Privacy & crash reports"); title.setObjectName("providerName")
        title_row.addWidget(title); title_row.addStretch(1)
        v.addLayout(title_row)

        help_lbl = QLabel(
            "Anonymous usage analytics + crash reports help us see what "
            "breaks in real projects so we can fix it. <b>Off by default.</b> "
            "Every event is PII-redacted at the source — paths, prompts, "
            "API keys, project names never leave your machine."
        )
        help_lbl.setObjectName("settingsSubtitle"); help_lbl.setWordWrap(True)
        v.addWidget(help_lbl)

        self._telemetry_toggle = QCheckBox(
            "Send anonymous usage events & crashes  (one toggle, both providers)"
        )
        self._telemetry_toggle.setObjectName("settingsSubtitle")
        self._telemetry_toggle.setChecked(_tel.consent_state() is True)
        v.addWidget(self._telemetry_toggle)

        # PostHog row
        ph_form = QFormLayout(); ph_form.setSpacing(6)
        self._posthog_key = QLineEdit()
        self._posthog_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._posthog_key.setPlaceholderText("phc_…")
        self._posthog_key.setText(load_setting("telemetry_posthog_key") or "")
        ph_form.addRow("PostHog project key", self._posthog_key)

        self._posthog_host = QLineEdit()
        # NB: ingest endpoint is eu.i.posthog.com — see telemetry._host().
        self._posthog_host.setPlaceholderText("https://eu.i.posthog.com")
        self._posthog_host.setText(load_setting("telemetry_posthog_host") or "")
        ph_form.addRow("PostHog host", self._posthog_host)
        v.addLayout(ph_form)

        ph_btn_row = QHBoxLayout(); ph_btn_row.setSpacing(6)
        ph_signup = QPushButton("Open PostHog signup")
        ph_signup.setObjectName("ghostButton")
        ph_signup.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://eu.posthog.com/signup"))
        )
        ph_btn_row.addWidget(ph_signup); ph_btn_row.addStretch(1)
        v.addLayout(ph_btn_row)

        # Sentry row
        sn_form = QFormLayout(); sn_form.setSpacing(6)
        self._sentry_dsn = QLineEdit()
        self._sentry_dsn.setEchoMode(QLineEdit.EchoMode.Password)
        self._sentry_dsn.setPlaceholderText("https://…@o…ingest.sentry.io/…")
        self._sentry_dsn.setText(load_setting("sentry_dsn") or "")
        sn_form.addRow("Sentry DSN", self._sentry_dsn)
        v.addLayout(sn_form)

        sn_btn_row = QHBoxLayout(); sn_btn_row.setSpacing(6)
        sn_signup = QPushButton("Open Sentry signup")
        sn_signup.setObjectName("ghostButton")
        sn_signup.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://sentry.io/signup/"))
        )
        sn_btn_row.addWidget(sn_signup)

        test_btn = QPushButton("Send test event")
        test_btn.setObjectName("ghostButton")
        test_btn.clicked.connect(self._on_test_telemetry)
        sn_btn_row.addWidget(test_btn)
        sn_btn_row.addStretch(1)
        v.addLayout(sn_btn_row)

        # Notifications row — Discord webhook URL for autonomous status
        # pings. No OAuth, no app password; user creates a Server →
        # channel webhook in Discord, pastes URL once.
        notif_form = QFormLayout(); notif_form.setSpacing(6)
        self._discord_webhook = QLineEdit()
        self._discord_webhook.setEchoMode(QLineEdit.EchoMode.Password)
        self._discord_webhook.setPlaceholderText(
            "https://discord.com/api/webhooks/…/…"
        )
        self._discord_webhook.setText(load_setting("discord_webhook_url") or "")
        notif_form.addRow("Discord webhook (status pings)", self._discord_webhook)
        v.addLayout(notif_form)

        notif_btn_row = QHBoxLayout(); notif_btn_row.setSpacing(6)
        discord_help = QPushButton("How to create a Discord webhook")
        discord_help.setObjectName("ghostButton")
        discord_help.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(
                "https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks"
            ))
        )
        notif_btn_row.addWidget(discord_help)
        ping_btn = QPushButton("Send test ping")
        ping_btn.setObjectName("ghostButton")
        ping_btn.clicked.connect(self._on_test_notify)
        notif_btn_row.addWidget(ping_btn)
        notif_btn_row.addStretch(1)
        v.addLayout(notif_btn_row)

        return row

    def _on_test_notify(self) -> None:
        """Save the webhook + fire desktop file + toast + Discord ping."""
        from PyQt6.QtWidgets import QMessageBox
        url = (self._discord_webhook.text() or "").strip()
        save_setting("discord_webhook_url", url)
        try:
            import sys, os
            from pathlib import Path
            agents_dir = Path(__file__).resolve().parent.parent / "agents"
            sys.path.insert(0, str(agents_dir))
            from notify import notify
            fired = notify(
                "ArchHub test ping",
                "Wired notify channels — desktop / toast / discord. If you see this in Discord and a desktop file appeared, channel is live.",
                html="<html><body style='font-family:Arial'><h2>ArchHub test ping</h2><p>If this file is on your desktop the channel works.</p></body></html>",
            )
            QMessageBox.information(
                self, "Test ping",
                "Channels fired:\n"
                f"  desktop file: {'OK' if fired['desktop'] else 'FAIL'}\n"
                f"  Windows toast: {'OK' if fired['toast'] else 'install BurntToast or upgrade Win10'}\n"
                f"  Discord webhook: {'OK' if fired['discord'] else 'no URL configured'}",
            )
        except Exception as ex:
            QMessageBox.warning(self, "Test ping failed", str(ex))

    def _on_test_telemetry(self) -> None:
        """Save current Privacy fields, fire a marker event + a benign
        captured exception, show one-line confirmation."""
        from PyQt6.QtWidgets import QMessageBox
        # Persist whatever the user typed.
        save_setting("telemetry_consent", self._telemetry_toggle.isChecked())
        save_setting("telemetry_posthog_key", (self._posthog_key.text() or "").strip())
        save_setting("telemetry_posthog_host", (self._posthog_host.text() or "").strip())
        save_setting("sentry_dsn", (self._sentry_dsn.text() or "").strip())

        # Re-init Sentry now (was a no-op at app start if user was opted out).
        try:
            import sentry_init as _si
            _si.init()
        except Exception:
            pass

        # Drop the cached PostHog client so it picks up the new key.
        try:
            import telemetry as _tel
            _tel._client = None
            _tel.track_event("test_event_from_settings")
            _tel.shutdown()
        except Exception as ex:
            QMessageBox.warning(self, "Test failed", f"Telemetry error: {ex}")
            return
        # Trigger a captured-but-handled Sentry exception.
        sent_to_sentry = False
        try:
            import sentry_sdk
            try:
                raise RuntimeError("ArchHub Settings test event — please ignore")
            except RuntimeError as ex:
                sentry_sdk.capture_exception(ex)
                sent_to_sentry = True
        except Exception:
            pass

        msg = "Test event fired."
        if not (self._posthog_key.text() or "").strip():
            msg += "\n\n(PostHog key empty — event was a no-op. Paste a phc_… key first.)"
        elif not self._telemetry_toggle.isChecked():
            msg += "\n\n(Telemetry toggle is OFF — event was a no-op. Tick it first.)"
        if not (self._sentry_dsn.text() or "").strip():
            msg += "\nSentry DSN empty — no crash sent."
        elif sent_to_sentry:
            msg += "\nSentry capture sent."
        QMessageBox.information(self, "Test event", msg)

    # ─────────────────────────────────────────────────────────────────────────

    def _build_cloud_sync_row(self):
        """Header row for cloud sync — shows status, lets the user kick a
        manual sync, surfaces the GitHub repo link."""
        import cloud_sync
        from PyQt6.QtCore import Qt

        row = QFrame(); row.setObjectName("providerRow")
        v = QVBoxLayout(row); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(6)

        status = cloud_sync.status()

        title_row = QHBoxLayout(); title_row.setSpacing(8)
        icon = QLabel("CS"); icon.setObjectName("providerIcon")
        title_row.addWidget(icon)
        title = QLabel("Cloud sync — Skills, Sessions"); title.setObjectName("providerName")
        title_row.addWidget(title)
        title_row.addStretch(1)

        if status.signed_in and status.initialised:
            badge_text = f"<i>{status.repo_slug}</i>"
        elif status.signed_in and not status.initialised:
            badge_text = "<i>signed in — not initialised</i>"
        elif status.available:
            badge_text = "<i>not signed in</i>"
        else:
            badge_text = "<i>install GitHub CLI</i>"
        title_row.addWidget(QLabel(badge_text))

        self._sync_btn = QPushButton(
            "Sync now" if status.initialised else "Set up cloud sync"
        )
        self._sync_btn.setObjectName("ghostButton")
        self._sync_btn.clicked.connect(self._on_sync_now)
        title_row.addWidget(self._sync_btn)
        v.addLayout(title_row)

        help_lines = []
        if not status.available:
            help_lines.append(
                "Install <code>gh</code> CLI (winget install GitHub.cli) "
                "and run <code>gh auth login</code> to enable sync."
            )
        elif not status.signed_in:
            help_lines.append(
                "You're not signed in to GitHub. Open a terminal and run "
                "<code>gh auth login</code>, then come back."
            )
        elif not status.initialised:
            help_lines.append(
                "Click <b>Set up cloud sync</b> to create a private "
                "<code>ArchHub-data</code> repo on your GitHub account "
                "and start syncing Skills."
            )
        else:
            last_pull = status.last_pull[:19].replace("T", " ") if status.last_pull else "—"
            last_push = status.last_push[:19].replace("T", " ") if status.last_push else "—"
            help_lines.append(
                f"Last pull: <code>{last_pull}</code>"
                f"&nbsp;&nbsp;·&nbsp;&nbsp;Last push: <code>{last_push}</code>"
            )
            if status.behind > 0:
                help_lines.append(
                    f"{status.behind} update(s) on the remote "
                    f"haven't been pulled yet."
                )
            if status.ahead > 0:
                help_lines.append(
                    f"{status.ahead} local commit(s) "
                    f"haven't been pushed yet."
                )

        help_label = QLabel("<br>".join(help_lines))
        help_label.setObjectName("settingsSubtitle")
        help_label.setWordWrap(True)
        help_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        v.addWidget(help_label)
        return row

    def _on_sync_now(self) -> None:
        import cloud_sync
        self._sync_btn.setText("Syncing…")
        self._sync_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            if not cloud_sync.is_initialised():
                result = cloud_sync.bootstrap()
                if not result.success:
                    QMessageBox.warning(self, "Cloud sync", f"{result.message}\n{result.detail}")
                    self._sync_btn.setText("Set up cloud sync")
                    self._sync_btn.setEnabled(True)
                    return
            push = cloud_sync.push("Manual sync from Settings")
            pull = cloud_sync.pull()
            msg = f"{pull.message}\n{push.message}"
            QMessageBox.information(self, "Cloud sync", msg)
        except Exception as ex:
            QMessageBox.warning(self, "Cloud sync", f"Sync failed: {ex}")
        finally:
            self._sync_btn.setText("Sync now")
            self._sync_btn.setEnabled(True)
            self.notify_changed()

    def _clear_speckle(self) -> None:
        delete_api_key("speckle")
        self._speckle_field.clear()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_procore_row(self):
        """Procore (construction PM) — token + company id + project id.

        Mirrors the Speckle Personal Access Token flow: user clicks the
        site button, mints a token in the Procore admin UI, pastes it
        here, ArchHub stores it under the `procore_access_token` key.
        Company + project ids identify the active project context that
        every Procore tool call defaults to."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        row = QFrame(); row.setObjectName("providerRow")
        v = QVBoxLayout(row); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(6)

        title_row = QHBoxLayout(); title_row.setSpacing(8)
        icon = QLabel("Pc"); icon.setObjectName("providerIcon")
        title_row.addWidget(icon)
        title = QLabel("Procore — sign in to enable RFI/submittal tools")
        title.setObjectName("providerName")
        title_row.addWidget(title); title_row.addStretch(1)

        existing_tok = load_api_key("procore_access_token")
        status = QLabel("<i>signed in</i>" if existing_tok else "<i>not signed in</i>")
        status.setObjectName("providerStatus")
        title_row.addWidget(status)
        v.addLayout(title_row)

        help_lbl = QLabel(
            "Procore is the dominant SaaS for construction project "
            "management (RFIs, submittals, change orders, daily logs). "
            "ArchHub talks to Procore's REST API with a Personal "
            "Access Token you mint at <b>developers.procore.com</b>. "
            "Click below to open the developer site, create a token "
            "in your Procore admin, copy it, and ArchHub will pick it "
            "up from your clipboard automatically (same flow as "
            "OpenRouter / Anthropic)."
        )
        help_lbl.setObjectName("settingsSubtitle"); help_lbl.setWordWrap(True)
        v.addWidget(help_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        open_btn = QPushButton("Open developers.procore.com")
        open_btn.setObjectName("primaryButton")
        open_btn.clicked.connect(
            lambda: self._start_procore_clipboard_watch(
                QDesktopServices.openUrl(
                    QUrl("https://developers.procore.com")
                )
            )
        )
        btn_row.addWidget(open_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        # Token field + show/clear (same pattern as Speckle).
        token_label = QLabel("<b>Personal Access Token</b>")
        token_label.setObjectName("settingsSubtitle")
        v.addWidget(token_label)

        token_row = QHBoxLayout(); token_row.setSpacing(6)
        self._procore_token = QLineEdit()
        self._procore_token.setEchoMode(QLineEdit.EchoMode.Password)
        if existing_tok:
            self._procore_token.setText(existing_tok)
        else:
            self._procore_token.setPlaceholderText(
                "Paste a Procore PAT — ArchHub will also auto-detect it "
                "if you copy it to the clipboard"
            )
        token_row.addWidget(self._procore_token, 1)
        pc_show = QPushButton("Show"); pc_show.setFixedWidth(56)
        pc_show.setObjectName("ghostButton")
        pc_show.setCheckable(True)
        pc_show.toggled.connect(
            lambda c: self._procore_token.setEchoMode(
                QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password
            )
        )
        token_row.addWidget(pc_show)
        pc_clear = QPushButton("Clear"); pc_clear.setObjectName("ghostButton")
        pc_clear.clicked.connect(self._clear_procore)
        token_row.addWidget(pc_clear)
        token_wrap = QWidget(); token_wrap.setLayout(token_row)
        v.addWidget(token_wrap)

        # Active project context — company id + project id. The runner
        # uses these as defaults for every list/get tool; an @-mention
        # in chat can still target a different project per-call.
        ctx_form = QFormLayout(); ctx_form.setSpacing(6)
        self._procore_company = QLineEdit()
        self._procore_company.setPlaceholderText("e.g. 1234567")
        cid = load_setting("procore_company_id")
        if cid:
            self._procore_company.setText(str(cid))
        ctx_form.addRow("Company id", self._procore_company)

        self._procore_project = QLineEdit()
        self._procore_project.setPlaceholderText("e.g. 76543")
        pid = load_setting("procore_project_id")
        if pid:
            self._procore_project.setText(str(pid))
        ctx_form.addRow("Active project id", self._procore_project)
        v.addLayout(ctx_form)

        return row

    def _start_procore_clipboard_watch(self, _open_result) -> None:
        """Poll the clipboard for ~3 minutes — when a string that looks
        like a Procore token lands, save it. Same UX as the OpenRouter
        clipboard fallback (see sign_in_dialog._check_clipboard).

        Procore tokens are typically long hex / base64-ish strings; we
        match anything >= 32 chars of url-safe characters that isn't
        already an LLM key shape we know."""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtGui import QGuiApplication

        cb = QGuiApplication.clipboard()
        self._procore_initial_cb = (cb.text() or "").strip()
        self._procore_poll = QTimer(self)
        self._procore_poll.setInterval(250)

        def _check():
            current = (QGuiApplication.clipboard().text() or "").strip()
            if not current or current == self._procore_initial_cb:
                return
            if len(current) < 24 or " " in current or "\n" in current:
                return
            # Skip known LLM key shapes — those belong to other providers.
            if current.startswith(("sk-", "AIza", "phc_")):
                return
            self._procore_token.setText(current)
            save_api_key("procore_access_token", current)
            self._procore_poll.stop()
            QMessageBox.information(
                self, "Procore signed in",
                "Token detected on clipboard and saved. Procore tools "
                "are now live in chat.",
            )
            self.notify_changed()

        self._procore_poll.timeout.connect(_check)
        self._procore_poll.start()
        # Stop polling after 3 minutes so the timer doesn't run forever.
        QTimer.singleShot(180_000, self._procore_poll.stop)

    def _clear_procore(self) -> None:
        delete_api_key("procore_access_token")
        self._procore_token.clear()

    def _run_speckle_setup(self) -> None:
        """Launch Setup-Speckle.bat with a visible console so the user can
        watch progress. Pre-fills the self-hosted URL field optimistically."""
        import subprocess
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent
        script = repo_root / "Setup-Speckle.bat"
        if not script.exists():
            QMessageBox.warning(
                self, "Speckle setup script missing",
                f"Could not find {script}. Pull the latest ArchHub via "
                f"Update.bat and try again.",
            )
            return
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", str(script)],
                cwd=str(repo_root),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except Exception as ex:
            QMessageBox.warning(self, "Could not start setup", str(ex))
            return
        self._speckle_server.setText("http://localhost:3000")
        QMessageBox.information(
            self, "Setting up Speckle",
            "A console window is running the setup. First run takes ~10 "
            "minutes (Docker pulls images). When it finishes, open "
            "http://localhost:3000, create your local admin account, then "
            "paste a Personal Access Token from your Speckle profile into "
            "the field above.",
        )

    def notify_changed(self) -> None:
        """Called by provider rows after a sign-in / sign-out so the parent
        chat window can refresh its model picker."""
        if hasattr(self.router, "_clients"):
            self.router._clients.clear()
        parent = self.parent()
        if parent is not None and hasattr(parent, "_refresh_model_picker"):
            try:
                parent._refresh_model_picker()
            except Exception:
                pass

    def _save_and_close(self) -> None:
        # Speckle settings still need an explicit save (not OAuth).
        speckle_on = self._speckle_toggle.isChecked()
        save_setting("speckle_enabled", speckle_on)
        if speckle_on:
            tok = self._speckle_field.text().strip()
            if tok:
                save_api_key("speckle", tok)
            srv = self._speckle_server.text().strip()
            if srv:
                save_setting("speckle_server", srv)

        # Speckle server based on cloud/self-host radio choice
        if speckle_on:
            if self._sp_self.isChecked():
                srv = self._speckle_server.text().strip()
                if srv:
                    save_setting("speckle_server", srv)
            else:
                save_setting("speckle_server", "https://app.speckle.systems")

        # Firm relay (path B): URL + token are persisted on close.
        relay_url = self._relay_url.text().strip()
        relay_tok = self._relay_token.text().strip()
        if relay_url:
            save_setting("relay_base_url", relay_url)
        if relay_tok:
            save_api_key("relay", relay_tok)

        # Procore — token + active project context. Token saved via
        # save_api_key so it lands in keyring when available; ids are
        # plain settings.
        try:
            pc_tok = (self._procore_token.text() or "").strip()
            if pc_tok:
                save_api_key("procore_access_token", pc_tok)
            pc_company = (self._procore_company.text() or "").strip()
            if pc_company:
                try:
                    save_setting("procore_company_id", int(pc_company))
                except Exception:
                    save_setting("procore_company_id", pc_company)
            pc_project = (self._procore_project.text() or "").strip()
            if pc_project:
                try:
                    save_setting("procore_project_id", int(pc_project))
                except Exception:
                    save_setting("procore_project_id", pc_project)
        except AttributeError:
            # _build_procore_row not yet wired — graceful no-op.
            pass

        # "Show local Ollama models" toggle persisted so the next launch
        # respects the choice without nagging.
        save_setting("show_local_models", self._show_local.isChecked())

        # Privacy block — opt-in toggle + 3 string fields. Empty fields
        # are persisted as "" so the user can blank a key on uninstall.
        save_setting("telemetry_consent", self._telemetry_toggle.isChecked())
        save_setting("telemetry_posthog_key", (self._posthog_key.text() or "").strip())
        save_setting("telemetry_posthog_host", (self._posthog_host.text() or "").strip())
        save_setting("sentry_dsn", (self._sentry_dsn.text() or "").strip())
        save_setting("discord_webhook_url", (self._discord_webhook.text() or "").strip())
        save_setting("hud_overlay_mode", bool(self._hud_overlay.isChecked()))
        save_setting("hud_hotkey", (self._hud_hotkey.text() or "ctrl+space").strip().lower())
        # Re-init Sentry + drop cached PostHog client so the changes
        # take effect without an app restart.
        try:
            import sentry_init as _si
            _si.init()
        except Exception:
            pass
        try:
            import telemetry as _tel
            _tel._client = None
        except Exception:
            pass

        if hasattr(self.router, "_clients"):
            self.router._clients.clear()
        self.notify_changed()
        self.accept()
