"""First-run telemetry consent dialog.

Shows once, the first time `telemetry.consent_state()` returns None.
The user picks Allow / Deny / "Ask me later" — we persist via
`telemetry.set_consent`. Skipping the dialog (close button) leaves
consent unset, so we'll ask again next launch.

Visual style matches `onboarding.py` (Anthropic palette, glass-card).

This is a tiny modal so it's deliberately separate from the heavier
3-step `OnboardingWizard` — telemetry is a one-question decision and
should be obvious the very first second the app opens.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

import telemetry


class TelemetryConsentDialog(QDialog):
    """Returns one of:
        QDialog.DialogCode.Accepted  →  user opted IN  (consent=True)
        QDialog.DialogCode.Rejected  →  user opted OUT (consent=False)
        (closed by X)                →  consent left None (ask again)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help improve ArchHub")
        self.setModal(True)
        self.setMinimumWidth(520)

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        v.setSpacing(14)

        title = QLabel("Help us see what's broken")
        title.setStyleSheet(
            "font-size: 22px; font-weight: 600; color: #f4efe8;"
        )
        v.addWidget(title)

        body = QLabel(
            "ArchHub can send <b>anonymous</b> usage events (which Skill ran, "
            "how long it took, which connector failed) plus <b>crash reports</b> "
            "to help us prioritise fixes.<br><br>"
            "<b>What we collect:</b><br>"
            "• Skill name + duration + success/failure<br>"
            "• Connector ping results<br>"
            "• Crashes (stack trace only — file paths, prompts, project names "
            "are redacted before they leave your machine)<br><br>"
            "<b>What we never collect:</b><br>"
            "• Your prompts or chat history<br>"
            "• Your API keys<br>"
            "• Project file names or contents<br>"
            "• Email or hostname<br><br>"
            "Switch this off any time in <b>Settings → Privacy</b>. "
            "Off-by-default for users who close this dialog."
        )
        body.setStyleSheet(
            "color: #b0aea5; font-size: 13px; line-height: 1.5;"
        )
        body.setWordWrap(True)
        v.addWidget(body)

        # Buttons row
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)

        deny = QPushButton("No thanks")
        deny.setObjectName("ghostButton")
        deny.clicked.connect(self._deny)
        row.addWidget(deny)

        allow = QPushButton("Allow")
        allow.setObjectName("primaryButton")
        allow.clicked.connect(self._allow)
        allow.setDefault(True)
        row.addWidget(allow)

        v.addLayout(row)

    # ----- handlers --------------------------------------------------------
    def _allow(self) -> None:
        telemetry.set_consent(True)
        # Fire one event right away so the dashboard shows life.
        telemetry.track_event(
            "telemetry_opted_in",
            source="first_run_dialog",
        )
        self.accept()

    def _deny(self) -> None:
        telemetry.set_consent(False)
        self.reject()


def maybe_prompt(parent=None) -> bool:
    """Show the dialog iff consent is unset. Returns True if consent
    was changed (either direction) by this call."""
    if telemetry.consent_state() is not None:
        return False
    dlg = TelemetryConsentDialog(parent=parent)
    dlg.exec()
    return telemetry.consent_state() is not None
