"""Settings dialog — API keys for Anthropic / OpenAI / Google / Speckle, server URLs."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget, QMessageBox,
)

from secrets_store import save_api_key, load_api_key, delete_api_key, save_setting, load_setting


PROVIDERS = [
    ("anthropic", "Anthropic API key", "https://console.anthropic.com/settings/keys"),
    ("openai",    "OpenAI API key",    "https://platform.openai.com/api-keys"),
    ("google",    "Google API key",    "https://aistudio.google.com/app/apikey"),
    ("speckle",   "Speckle Personal Access Token", "https://app.speckle.systems/profile"),
]


class SettingsDialog(QDialog):
    def __init__(self, router, parent=None):
        super().__init__(parent)
        self.router = router
        self.setWindowTitle("ArchHub — Settings")
        self.resize(560, 480)
        self.setObjectName("settingsDialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        title = QLabel("API keys")
        title.setObjectName("settingsTitle")
        outer.addWidget(title)

        sub = QLabel(
            "Add at least one LLM key to start chatting. Speckle is optional but unlocks "
            "cross-tool data interop. Keys are stored in the OS keyring (Windows Credential "
            "Manager) where available, otherwise in an obfuscated file."
        )
        sub.setObjectName("settingsSubtitle")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # Provider rows
        form = QFormLayout()
        form.setSpacing(10)
        self._fields: dict[str, QLineEdit] = {}
        for prov, label, url in PROVIDERS:
            row = QHBoxLayout()
            row.setSpacing(6)
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            existing = load_api_key(prov)
            if existing:
                field.setText(existing)
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

        # Speckle server
        self.speckle_server = QLineEdit()
        self.speckle_server.setPlaceholderText("https://app.speckle.systems")
        existing_srv = load_setting("speckle_server") or ""
        self.speckle_server.setText(existing_srv)
        outer.addWidget(QLabel("Speckle server"))
        outer.addWidget(self.speckle_server)

        outer.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        save = QPushButton("Save")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        btn_row.addWidget(save)
        outer.addLayout(btn_row)

    def _save(self) -> None:
        for prov, field in self._fields.items():
            val = field.text().strip()
            if val:
                save_api_key(prov, val)
            else:
                # Empty → don't touch existing
                pass

        if self.speckle_server.text().strip():
            save_setting("speckle_server", self.speckle_server.text().strip())

        # Tell the router to drop cached clients so new keys take effect
        self.router._clients.clear()
        self.accept()

    def _clear(self, provider: str, field: QLineEdit) -> None:
        delete_api_key(provider)
        field.clear()
