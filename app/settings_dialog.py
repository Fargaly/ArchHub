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

        setup_btn = QPushButton("⚡  Set up local Speckle for me")
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
        sp_show = QPushButton("👁"); sp_show.setFixedWidth(34); sp_show.setObjectName("ghostButton")
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

        outer.addStretch(1)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close"); close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

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
        icon = QLabel("☁"); icon.setObjectName("providerIcon")
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
                    f"⚠ {status.behind} update(s) on the remote "
                    f"haven't been pulled yet."
                )
            if status.ahead > 0:
                help_lines.append(
                    f"⚠ {status.ahead} local commit(s) "
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

        # "Show local Ollama models" toggle persisted so the next launch
        # respects the choice without nagging.
        save_setting("show_local_models", self._show_local.isChecked())

        if hasattr(self.router, "_clients"):
            self.router._clients.clear()
        self.notify_changed()
        self.accept()
