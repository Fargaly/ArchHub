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
    QCheckBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
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

        self.icon = QLabel("🔒")
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
            self.icon.setText("✓")
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
        self.resize(560, 520)

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

        # ── Provider rows ──────────────────────────────────────────────────
        self._rows: list[_ProviderRow] = []
        for prov, _label, env_var in LLM_PROVIDERS:
            row = _ProviderRow(prov, env_var, self)
            self._rows.append(row)
            outer.addWidget(row)

        # ── Firm relay (path B — OpenAI-compatible self-hosted endpoint) ───
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
        outer.addWidget(relay_box)

        # ── Speckle (optional, collapsed by default) ───────────────────────
        self._speckle_toggle = QCheckBox("Use Speckle for cross-tool data sync  (optional)")
        self._speckle_toggle.setObjectName("settingsSubtitle")
        speckle_enabled = bool(load_setting("speckle_enabled"))
        self._speckle_toggle.setChecked(speckle_enabled)
        outer.addWidget(self._speckle_toggle)

        self._speckle_widget = QWidget()
        speckle_form = QFormLayout(self._speckle_widget)
        speckle_form.setSpacing(8)
        speckle_form.setContentsMargins(0, 4, 0, 0)

        speckle_row = QHBoxLayout()
        speckle_row.setSpacing(6)
        self._speckle_field = QLineEdit()
        self._speckle_field.setEchoMode(QLineEdit.EchoMode.Password)
        existing_tok = load_api_key("speckle")
        if existing_tok:
            self._speckle_field.setText(existing_tok)
        else:
            self._speckle_field.setPlaceholderText(
                "Speckle PAT (no OAuth available — paste from your Speckle profile)"
            )
        speckle_row.addWidget(self._speckle_field, 1)

        sp_show = QPushButton("👁"); sp_show.setFixedWidth(34); sp_show.setObjectName("ghostButton")
        sp_show.setCheckable(True)
        sp_show.toggled.connect(
            lambda c: self._speckle_field.setEchoMode(
                QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password
            )
        )
        speckle_row.addWidget(sp_show)
        sp_clear = QPushButton("Clear"); sp_clear.setObjectName("ghostButton")
        sp_clear.clicked.connect(self._clear_speckle)
        speckle_row.addWidget(sp_clear)
        sp_tok_wrap = QWidget(); sp_tok_wrap.setLayout(speckle_row)
        speckle_form.addRow("Personal Access Token", sp_tok_wrap)

        self._speckle_server = QLineEdit()
        self._speckle_server.setPlaceholderText("https://app.speckle.systems")
        self._speckle_server.setText(load_setting("speckle_server") or "")
        speckle_form.addRow("Speckle server", self._speckle_server)

        note = QLabel(
            "Speckle is open-source — you can self-host it or use the free cloud. "
            "It does not currently offer OAuth for desktop apps, so a Personal "
            "Access Token from your Speckle profile is required."
        )
        note.setObjectName("settingsSubtitle"); note.setWordWrap(True)
        speckle_form.addRow("", note)

        self._speckle_widget.setVisible(speckle_enabled)
        self._speckle_toggle.toggled.connect(self._speckle_widget.setVisible)
        outer.addWidget(self._speckle_widget)

        outer.addStretch(1)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close"); close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

    # ─────────────────────────────────────────────────────────────────────────

    def _clear_speckle(self) -> None:
        delete_api_key("speckle")
        self._speckle_field.clear()

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

        # Firm relay (path B): URL + token are persisted on close.
        relay_url = self._relay_url.text().strip()
        relay_tok = self._relay_token.text().strip()
        if relay_url:
            save_setting("relay_base_url", relay_url)
        if relay_tok:
            save_api_key("relay", relay_tok)

        if hasattr(self.router, "_clients"):
            self.router._clients.clear()
        self.notify_changed()
        self.accept()
