"""Sign-in dialog — real OAuth where possible, clipboard-watch otherwise.

OpenRouter has a public PKCE OAuth flow → real one-click sign-in:
    Click "Sign in" → browser opens → user clicks Authorize → ArchHub
    catches the redirect, exchanges code for key, stores it. Zero clicks
    in ArchHub after the first one.

Anthropic / OpenAI / Google: no public OAuth for desktop apps. Falls
back to the clipboard-watch flow:
    Click "Sign in" → browser opens to provider key page → user mints a
    key, clicks Copy → ArchHub auto-detects on clipboard, stores it.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from secrets_store import save_api_key
import sign_in


_POLL_INTERVAL_MS = 250
_TIMEOUT_MS = 180_000     # 3 minutes


class _OAuthExchangeWorker(QObject):
    """Runs the OpenRouter token exchange off the UI thread."""
    finished = pyqtSignal(str, str)        # (api_key, error)

    def __init__(self, oauth):
        super().__init__()
        self._oauth = oauth

    def run(self) -> None:
        try:
            key = self._oauth.exchange_code_for_key()
            self.finished.emit(key, "")
        except Exception as ex:
            self.finished.emit("", f"{type(ex).__name__}: {ex}")


class SignInDialog(QDialog):
    """Per-provider sign-in: real OAuth for OpenRouter, clipboard for others."""

    signed_in = pyqtSignal(str)        # provider id

    def __init__(self, provider: str, parent=None):
        super().__init__(parent)
        self.plan = sign_in.SignInPlan.for_provider(provider)
        self.use_oauth = provider in sign_in.OAUTH_PROVIDERS
        self.setWindowTitle(f"ArchHub — Sign in with {self.plan.display_name}")
        self.setObjectName("panel")
        self.setMinimumWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QFrame()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(24, 18, 24, 8)
        bv.setSpacing(10)

        if self.use_oauth:
            steps = QLabel(
                f"<b>1.</b> Click below to open the {self.plan.display_name} "
                f"sign-in page in your browser.<br>"
                f"<b>2.</b> Sign in with Google / GitHub and click "
                f"<i>Authorize ArchHub</i>.<br>"
                f"<b>3.</b> The browser will redirect you back. ArchHub "
                f"finishes the sign-in automatically — nothing else to do."
            )
            self._action_label = f"🔐  Sign in with {self.plan.display_name}"
        else:
            steps = QLabel(
                f"<b>1.</b> Click below to open the {self.plan.display_name} "
                f"key page in your browser.<br>"
                f"<b>2.</b> Click <i>Create new key</i>, then click the "
                f"<i>Copy</i> button beside the new key.<br>"
                f"<b>3.</b> Come back to ArchHub — it will detect the key "
                f"on your clipboard automatically. No paste needed."
            )
            self._action_label = f"🌐  Open {self.plan.display_name} key page"
        steps.setObjectName("settingsSubtitle")
        steps.setWordWrap(True)
        bv.addWidget(steps)

        self.action_btn = QPushButton(self._action_label)
        self.action_btn.setObjectName("primaryButton")
        self.action_btn.clicked.connect(self._on_action)
        bv.addWidget(self.action_btn)

        # Manual-paste fallback. Always visible for OAuth providers
        # (OpenRouter) so users hit by server-side 409 / rate-limit /
        # "Failed to create or update app while creating auth code"
        # have a clear path forward without restarting the dialog.
        # For clipboard-only providers (Anthropic / OpenAI / Google)
        # the primary button already does this — hide.
        self.manual_btn: QPushButton | None = None
        if self.use_oauth:
            self.manual_btn = QPushButton(
                "Or paste a key manually (skip browser auth)"
            )
            self.manual_btn.setObjectName("ghostButton")
            self.manual_btn.clicked.connect(self._switch_to_manual)
            bv.addWidget(self.manual_btn)

        if self.use_oauth:
            status_msg = (
                f"You'll only do this once on this device. ArchHub will "
                f"store an API key from {self.plan.display_name} and use it "
                f"for every cloud model afterwards."
            )
        else:
            status_msg = (
                f"After you copy a key (looks like  "
                f"<code>{self.plan.sample_prefix}</code>), ArchHub will "
                f"save it automatically."
            )
        self.status = QLabel(status_msg)
        self.status.setObjectName("settingsSubtitle")
        self.status.setWordWrap(True)
        bv.addWidget(self.status)

        outer.addWidget(body, 1)
        outer.addWidget(self._build_footer())

        # Clipboard-watch state (only used by the fallback path).
        cb = QGuiApplication.clipboard()
        self._initial_clipboard = (cb.text() or "").strip()
        self._captured_key: str | None = None
        self._poll_timer: QTimer | None = None
        self._timeout_timer: QTimer | None = None

        # OAuth state (only used by the OAuth path).
        self._oauth = None
        self._oauth_poll: QTimer | None = None
        self._exchange_thread: QThread | None = None
        self._exchange_worker: _OAuthExchangeWorker | None = None

    # ---- header / footer -------------------------------------------------

    def _build_header(self) -> QFrame:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(24, 22, 24, 14); v.setSpacing(4)
        t = QLabel(f"Sign in with {self.plan.display_name}")
        t.setObjectName("panelTitle"); v.addWidget(t)
        s = QLabel("One click. No typing." if self.use_oauth else "Two clicks. No typing.")
        s.setObjectName("panelSubtitle"); v.addWidget(s)
        return hf

    def _build_footer(self) -> QFrame:
        f = QFrame(); f.setObjectName("panelFooter")
        v = QVBoxLayout(f); v.setContentsMargins(20, 8, 20, 14); v.setSpacing(8)

        # Manual-paste fallback row — when clipboard auto-detect fails
        # (browser quirks, key reformatted on paste, or user already had
        # the key on clipboard before opening the dialog), this lets
        # them just paste it directly. Always visible; auto-detect path
        # is the fast track, this is the safety net.
        from PyQt6.QtWidgets import QLineEdit
        paste_row = QHBoxLayout()
        paste_row.setSpacing(8)
        self.paste_field = QLineEdit()
        self.paste_field.setObjectName("inputField")
        self.paste_field.setPlaceholderText(
            f"Or paste your {self.plan.display_name} key here directly")
        self.paste_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.paste_field.returnPressed.connect(self._on_paste_save)
        paste_row.addWidget(self.paste_field, 1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._on_paste_save)
        paste_row.addWidget(save_btn)
        v.addLayout(paste_row)

        # Cancel row.
        h = QHBoxLayout(); h.setSpacing(8)
        h.addStretch(1)
        cancel = QPushButton("Cancel"); cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)
        h.addWidget(cancel)
        v.addLayout(h)
        return f

    def _on_paste_save(self) -> None:
        """Save whatever the user pasted into the manual-paste field.
        Permissive — accepts any non-empty trimmed value, then runs the
        regex check for a non-blocking warning. Lets users with new /
        unrecognised key formats still get past the dialog."""
        text = (self.paste_field.text() or "").strip()
        if not text:
            self.status.setText("⚠️ Paste a key first.")
            return
        # Strip common copy artefacts (zero-width spaces, soft hyphens).
        for ch in ("​", "‌", "‍", "﻿", "­"):
            text = text.replace(ch, "")
        text = text.strip()
        self._captured_key = text
        try:
            from sign_in import looks_like_key
            if not looks_like_key(self.plan.provider, text):
                # Not a recognised format; warn but still save — OpenAI
                # rolls new prefixes faster than we update regexes.
                self.status.setText(
                    f"⚠️ Key shape doesn't match {self.plan.sample_prefix}, "
                    "saving anyway. Reload the dialog to retry."
                )
        except Exception:
            pass
        self._on_captured()

    # ---- entry point -----------------------------------------------------

    def _on_action(self) -> None:
        if self.use_oauth:
            self._start_oauth_flow()
        else:
            self._start_clipboard_flow()

    # ---- OAuth path (OpenRouter) ----------------------------------------

    def _start_oauth_flow(self) -> None:
        from oauth_openrouter import OpenRouterOAuth
        self.action_btn.setText("⏳  Opening browser…")
        self.action_btn.setEnabled(False)
        self._oauth = OpenRouterOAuth()
        if not self._oauth.start():
            self.status.setText(f"⚠️ Could not start sign-in: {self._oauth.error}")
            self.action_btn.setText(self._action_label)
            self.action_btn.setEnabled(True)
            return

        self.status.setText(
            "Browser opened. Sign in and click <b>Authorize</b>. ArchHub "
            "will finish automatically.<br><br>Waiting for authorization…"
        )

        self._oauth_poll = QTimer(self)
        self._oauth_poll.setInterval(_POLL_INTERVAL_MS)
        self._oauth_poll.timeout.connect(self._check_oauth)
        self._oauth_poll.start()

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(_TIMEOUT_MS)

    def _check_oauth(self) -> None:
        assert self._oauth is not None
        if not self._oauth.completed:
            return
        if self._oauth_poll is not None:
            self._oauth_poll.stop()
            self._oauth_poll = None
        if self._oauth.error:
            self._fail(f"OAuth error: {self._oauth.error}")
            return
        self.status.setText("Authorized. Exchanging code for key…")
        # Token exchange does network I/O — run on its own thread so the
        # dialog never freezes.
        self._exchange_worker = _OAuthExchangeWorker(self._oauth)
        self._exchange_thread = QThread(self)
        self._exchange_worker.moveToThread(self._exchange_thread)
        self._exchange_thread.started.connect(self._exchange_worker.run)
        self._exchange_worker.finished.connect(self._on_exchange_done)
        self._exchange_worker.finished.connect(self._exchange_thread.quit)
        self._exchange_thread.finished.connect(self._exchange_worker.deleteLater)
        self._exchange_thread.finished.connect(self._exchange_thread.deleteLater)
        self._exchange_thread.start()

    def _on_exchange_done(self, key: str, error: str) -> None:
        if self._oauth is not None:
            self._oauth.stop()
        if error:
            self._fail(error)
            return
        self._captured_key = key
        self._on_captured()

    # ---- clipboard path (Anthropic / OpenAI / Google) -------------------

    def _start_clipboard_flow(self) -> None:
        self.action_btn.setText(f"⏳  Waiting for {self.plan.display_name} key…")
        self.action_btn.setEnabled(False)
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

    # ---- shared completion handlers --------------------------------------

    def _on_captured(self) -> None:
        self._stop_timers()
        try:
            save_api_key(self.plan.provider, self._captured_key or "")
        except Exception as ex:
            self._fail(f"Detected a {self.plan.display_name} key but could "
                       f"not save it: {ex}")
            return

        masked = (self._captured_key or "")[:10] + "…"
        self.status.setText(
            f"✓ Signed in to {self.plan.display_name} ({masked}). Closing…"
        )
        self.signed_in.emit(self.plan.provider)
        QTimer.singleShot(700, self.accept)

    def _on_timeout(self) -> None:
        self._stop_timers()
        if self.use_oauth:
            self.status.setText(
                f"No authorization came back from {self.plan.display_name} "
                f"in 3 minutes. The provider may be rate-limiting "
                f"(error 409 'Failed to create or update app while "
                f"creating auth code' is common — wait 30 s then "
                f"retry). Or click <b>Or paste a key manually</b> "
                f"below to skip the browser flow."
            )
        else:
            self.status.setText(
                f"No {self.plan.display_name} key showed up on your clipboard "
                f"in 3 minutes. Click the button to try again, or cancel."
            )
        self.action_btn.setText(self._action_label)
        self.action_btn.setEnabled(True)

    def _switch_to_manual(self) -> None:
        """Bail out of OAuth, open the provider's API-keys page, and
        flip the dialog into clipboard-watch mode. Lets the user
        recover from OpenRouter's 409 'Failed to create or update
        app while creating auth code' without restarting the dialog."""
        self._stop_timers()
        if self._oauth is not None:
            try:
                self._oauth.stop()
            except Exception:
                pass
            self._oauth = None
        self.use_oauth = False
        self._action_label = (
            f"🌐  Open {self.plan.display_name} key page"
        )
        self.action_btn.setText(self._action_label)
        self.action_btn.setEnabled(True)
        if self.manual_btn is not None:
            self.manual_btn.setVisible(False)
        self.status.setText(
            f"Switched to manual paste. Click the button to open "
            f"{self.plan.display_name}'s keys page; after you click "
            f"<i>Copy</i> on a new key (looks like "
            f"<code>{self.plan.sample_prefix}</code>), ArchHub will "
            f"save it automatically."
        )

    def _fail(self, message: str) -> None:
        self._stop_timers()
        self.status.setText(f"⚠️ {message}")
        self.action_btn.setText(self._action_label)
        self.action_btn.setEnabled(True)

    def _stop_timers(self) -> None:
        for t in (self._poll_timer, self._oauth_poll, self._timeout_timer):
            if t is not None:
                t.stop()
        self._poll_timer = None
        self._oauth_poll = None
        self._timeout_timer = None

    def reject(self) -> None:
        self._stop_timers()
        if self._oauth is not None:
            try:
                self._oauth.stop()
            except Exception:
                pass
        super().reject()
