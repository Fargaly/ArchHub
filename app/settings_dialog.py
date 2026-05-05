"""Settings dialog — API keys for Anthropic / OpenAI / Google, optional Speckle."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from secrets_store import save_api_key, load_api_key, delete_api_key, save_setting, load_setting


# LLM providers — env var is checked as a fallback when no saved key exists
LLM_PROVIDERS = [
    ("anthropic", "Anthropic API key",  "https://console.anthropic.com/settings/keys", "ANTHROPIC_API_KEY"),
    ("openai",    "OpenAI API key",     "https://platform.openai.com/api-keys",         "OPENAI_API_KEY"),
    ("google",    "Google API key",     "https://aistudio.google.com/app/apikey",        "GOOGLE_API_KEY"),
]


def _load_key(provider: str, env_var: str) -> str:
    """Return saved key, then env var, then empty string."""
    saved = load_api_key(provider)
    if saved:
        return saved
    return os.environ.get(env_var, "")


class SettingsDialog(QDialog):
    def __init__(self, router, parent=None):
        super().__init__(parent)
        self.router = router
        self.setWindowTitle("ArchHub — Settings")
        self.resize(560, 460)
        self.setObjectName("settingsDialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        title = QLabel("API keys")
        title.setObjectName("settingsTitle")
        outer.addWidget(title)

        sub = QLabel(
            "Add at least one LLM key to start chatting. Keys are stored in the OS keyring "
            "(Windows Credential Manager) where available, otherwise in an obfuscated file. "
            "Keys already set in environment variables are auto-detected."
        )
        sub.setObjectName("settingsSubtitle")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # ── LLM provider rows ───────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(10)
        self._fields: dict[str, QLineEdit] = {}

        for prov, label, url, env_var in LLM_PROVIDERS:
            row = QHBoxLayout()
            row.setSpacing(6)

            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            val = _load_key(prov, env_var)
            if val:
                field.setText(val)
            else:
                field.setPlaceholderText(f"Get one at: {url}")

            self._fields[prov] = field
            row.addWidget(field, 1)

            show_btn = QPushButton("👁")
            show_btn.setFixedWidth(34)
            show_btn.setObjectName("ghostButton")
            show_btn.setCheckable(True)
            show_btn.toggled.connect(
                lambda checked, f=field:
                f.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
            )
            row.addWidget(show_btn)

            clear_btn = QPushButton("Clear")
            clear_btn.setObjectName("ghostButton")
            clear_btn.clicked.connect(lambda _checked, p=prov, f=field: self._clear(p, f))
            row.addWidget(clear_btn)

            wrapper = QWidget()
            wrapper.setLayout(row)
            form.addRow(label, wrapper)

        outer.addLayout(form)

        # ── Speckle (optional, collapsed by default) ─────────────────────────
        self._speckle_toggle = QCheckBox("Use Speckle for cross-tool data sync  (optional)")
        self._speckle_toggle.setObjectName("settingsSubtitle")
        speckle_enabled = bool(load_setting("speckle_enabled"))
        self._speckle_toggle.setChecked(speckle_enabled)
        outer.addWidget(self._speckle_toggle)

        self._speckle_widget = QWidget()
        speckle_form = QFormLayout(self._speckle_widget)
        speckle_form.setSpacing(8)
        speckle_form.setContentsMargins(0, 4, 0, 0)

        # token field
        speckle_row = QHBoxLayout()
        speckle_row.setSpacing(6)
        self._speckle_field = QLineEdit()
        self._speckle_field.setEchoMode(QLineEdit.EchoMode.Password)
        existing_tok = load_api_key("speckle")
        if existing_tok:
            self._speckle_field.setText(existing_tok)
        else:
            self._speckle_field.setPlaceholderText("Get one at: https://app.speckle.systems/profile")
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
        sp_clear.clicked.connect(lambda: self._clear("speckle", self._speckle_field))
        speckle_row.addWidget(sp_clear)
        sp_tok_wrap = QWidget(); sp_tok_wrap.setLayout(speckle_row)
        speckle_form.addRow("Personal Access Token", sp_tok_wrap)

        # server field
        self._speckle_server = QLineEdit()
        self._speckle_server.setPlaceholderText("https://app.speckle.systems")
        self._speckle_server.setText(load_setting("speckle_server") or "")
        speckle_form.addRow("Speckle server", self._speckle_server)

        note = QLabel(
            "Speckle is open-source — you can self-host it or use the free cloud. "
            "A Personal Access Token is required because even open-source servers need auth "
            "(same as GitHub needing a PAT). If you don't use Speckle, leave this off."
        )
        note.setObjectName("settingsSubtitle")
        note.setWordWrap(True)
        speckle_form.addRow("", note)

        self._speckle_widget.setVisible(speckle_enabled)
        self._speckle_toggle.toggled.connect(self._speckle_widget.setVisible)
        outer.addWidget(self._speckle_widget)

        outer.addStretch(1)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("Cancel"); cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        save_btn = QPushButton("Save"); save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        outer.addLayout(btn_row)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _clear(self, provider: str, field: QLineEdit) -> None:
        delete_api_key(provider)
        field.clear()

    def _save(self) -> None:
        # LLM keys
        for prov, _, _, env_var in LLM_PROVIDERS:
            val = self._fields[prov].text().strip()
            if val and val != os.environ.get(env_var, ""):
                save_api_key(prov, val)
            elif val and not load_api_key(prov):
                # env var value — save it so it persists if env is later removed
                save_api_key(prov, val)

        # Speckle
        speckle_on = self._speckle_toggle.isChecked()
        save_setting("speckle_enabled", speckle_on)
        if speckle_on:
            tok = self._speckle_field.text().strip()
            if tok:
                save_api_key("speckle", tok)
            srv = self._speckle_server.text().strip()
            if srv:
                save_setting("speckle_server", srv)

        # Drop cached LLM clients so new keys take effect immediately
        if hasattr(self.router, "_clients"):
            self.router._clients.clear()

        self.accept()
