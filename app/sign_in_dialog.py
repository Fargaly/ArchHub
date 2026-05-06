"""Sign-in dialog — clipboard-watch flow for a single LLM provider.

UX contract:

    [ Open <Provider> page ] ──► browser opens to key creation page
    [ status: "Waiting for key on your clipboard…" ]
    user clicks "Copy" on provider's site
    ArchHub auto-detects the key, saves it via secrets_store, closes dialog.

The dialog never asks the user to paste anything. It also lets the user
cancel at any time. There is a 3-minute hard timeout so the watcher does
not run forever in the background.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from secrets_store import save_api_key
import sign_in


_POLL_INTERVAL_MS = 250
_TIMEOUT_MS = 180_000     # 3 minutes


class SignInDialog(QDialog):
    """Per-provider sign-in via clipboard auto-capture."""

    signed_in = pyqtSignal(str)        # provider id

    def __init__(self, provider: str, parent=None):
        super().__init__(parent)
        self.plan = sign_in.SignInPlan.for_provider(provider)
        self.setWindowTitle(f"ArchHub — Sign in with {self.plan.display_name}")
        self.setObjectName("panel")
        self.setMinimumWidth(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QFrame()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(24, 18, 24, 8)
        bv.setSpacing(10)

        steps = QLabel(
            f"<b>1.</b> Click below to open the {self.plan.display_name} key "
            f"page in your browser.<br>"
            f"<b>2.</b> Click <i>Create new key</i>, then click the "
            f"<i>Copy</i> button beside the new key.<br>"
            f"<b>3.</b> Come back to ArchHub — it will detect the key on your "
            f"clipboard automatically. No paste needed."
        )
        steps.setObjectName("settingsSubtitle")
        steps.setWordWrap(True)
        bv.addWidget(steps)

        self.open_btn = QPushButton(f"🌐  Open {self.plan.display_name} key page")
        self.open_btn.setObjectName("primaryButton")
        self.open_btn.clicked.connect(self._on_open)
        bv.addWidget(self.open_btn)

        self.status = QLabel(
            f"After you copy a key (looks like  <code>{self.plan.sample_prefix}</code>), "
            f"ArchHub will save it automatically."
        )
        self.status.setObjectName("settingsSubtitle")
        self.status.setWordWrap(True)
        bv.addWidget(self.status)

        outer.addWidget(body, 1)
        outer.addWidget(self._build_footer())

        # Pre-snapshot whatever is in the clipboard so we don't auto-import
        # a key the user copied for some other reason.
        cb = QGuiApplication.clipboard()
        self._initial_clipboard = (cb.text() or "").strip()
        self._captured_key: str | None = None

        # Watcher state — armed only after the user clicks Open.
        self._poll_timer: QTimer | None = None
        self._timeout_timer: QTimer | None = None

    # ---- header / footer -------------------------------------------------

    def _build_header(self) -> QFrame:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(24, 22, 24, 14); v.setSpacing(4)
        t = QLabel(f"Sign in with {self.plan.display_name}")
        t.setObjectName("panelTitle"); v.addWidget(t)
        s = QLabel("Two clicks. No typing.")
        s.setObjectName("panelSubtitle"); v.addWidget(s)
        return hf

    def _build_footer(self) -> QFrame:
        f = QFrame(); f.setObjectName("panelFooter")
        h = QHBoxLayout(f); h.setContentsMargins(20, 12, 20, 14); h.setSpacing(8)
        h.addStretch(1)
        cancel = QPushButton("Cancel"); cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)
        return f

    # ---- flow ------------------------------------------------------------

    def _on_open(self) -> None:
        self.open_btn.setText(f"⏳  Waiting for {self.plan.display_name} key…")
        self.open_btn.setEnabled(False)
        self.status.setText(
            f"Browser opened. After you click <i>Copy</i> on a new "
            f"{self.plan.display_name} API key, this dialog will save it "
            f"automatically and close.<br><br>"
            f"Watching your clipboard… (cancel any time)"
        )
        if not sign_in.open_provider_page(self.plan.provider):
            self.status.setText(
                "⚠️ Could not open your default browser. "
                f"Visit <a href='{self.plan.key_url}'>{self.plan.key_url}</a> "
                f"manually, copy a new key, and ArchHub will still pick it up."
            )

        self._start_watching()

    def _start_watching(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._check_clipboard)
        self._poll_timer.start()

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(_TIMEOUT_MS)

    def _check_clipboard(self) -> None:
        cb = QGuiApplication.clipboard()
        text = (cb.text() or "").strip()
        if not text or text == self._initial_clipboard:
            return
        if not sign_in.looks_like_key(self.plan.provider, text):
            return
        self._captured_key = text
        self._on_captured()

    def _on_captured(self) -> None:
        self._stop_timers()
        try:
            save_api_key(self.plan.provider, self._captured_key or "")
        except Exception as ex:
            self.status.setText(
                f"⚠️ Detected a {self.plan.display_name} key but could not "
                f"save it: {ex}"
            )
            return

        masked = (self._captured_key or "")[:10] + "…"
        self.status.setText(
            f"✓ {self.plan.display_name} key saved ({masked}). You're "
            f"signed in. Closing…"
        )
        self.signed_in.emit(self.plan.provider)
        QTimer.singleShot(700, self.accept)

    def _on_timeout(self) -> None:
        self._stop_timers()
        self.status.setText(
            f"No {self.plan.display_name} key showed up on your clipboard "
            f"in 3 minutes. Click the open button to try again, or cancel."
        )
        self.open_btn.setText(f"🌐  Open {self.plan.display_name} key page")
        self.open_btn.setEnabled(True)

    def _stop_timers(self) -> None:
        for t in (self._poll_timer, self._timeout_timer):
            if t is not None:
                t.stop()
        self._poll_timer = None
        self._timeout_timer = None

    def reject(self) -> None:
        self._stop_timers()
        super().reject()
