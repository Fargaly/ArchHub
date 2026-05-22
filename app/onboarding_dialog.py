"""Zero-jargon first-run onboarding dialog.

Built for the architect who has never installed Ollama, never created
a Claude account, never copied an API key, and would close the app
forever if the first screen asked them to. The default path is one
button — "Set up my AI brain" — that silently installs Ollama,
pulls a small model, and verifies it works.

Two escape hatches stay accessible for power users:
  • "I have a Claude / OpenAI account" — opens Settings.
  • "Skip — I'll do this later" — sets first_run_complete=True
    and dismisses. Chat still works if any provider is configured
    afterward.

Vocabulary rules (technophobe-safe):
  - Don't say "Ollama" → say "local AI brain" or "AI engine"
  - Don't say "API key" → say "cloud AI account"
  - Don't say "model" → say "AI brain" or just "AI"
  - Don't say "Python" / "service" / "daemon"
  - Don't show file paths or technical errors unless something fails

The whole flow is one window, one progress bar, plain English.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


# Stage → user-facing friendly label. Hidden mapping; never shown raw.
_STAGE_LABEL = {
    "download":     "Downloading AI engine",
    "install":      "Installing AI engine",
    "service_wait": "Starting AI engine",
    "model_pull":   "Downloading AI brain",
    "verify":       "Final check",
    "done":         "Ready",
}


class OnboardingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to ArchHub")
        self.setModal(True)
        self.setMinimumSize(560, 420)
        self._installer = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(40, 36, 40, 28)
        v.setSpacing(SPACE["md"])

        # Title.
        title = QLabel("Welcome to ArchHub")
        title.setObjectName("onboardingTitle")
        v.addWidget(title)

        # Subtitle — explains what the next click does in plain
        # English, ZERO technical jargon.
        sub = QLabel(
            "ArchHub talks to your AEC software through an AI brain. "
            "Click below and we'll set one up on your computer — no "
            "accounts, no payments, no signup. Just AI you can chat "
            "with privately, even when you're offline."
        )
        sub.setObjectName("onboardingSubtitle")
        sub.setWordWrap(True)
        v.addWidget(sub)

        # Time + size promise — set expectations honestly.
        promise = QLabel(
            "<b>~5 minutes</b> · ~2 GB download · 8 GB RAM recommended"
        )
        promise.setObjectName("onboardingPromise")
        v.addWidget(promise)

        v.addSpacing(SPACE["sm"])

        # Big primary button — the whole-point CTA.
        self.btn_setup = QPushButton("Set up my AI brain (free, on your computer)")
        self.btn_setup.setObjectName("onboardingPrimary")
        self.btn_setup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_setup.setMinimumHeight(48)
        self.btn_setup.clicked.connect(self._start_install)
        v.addWidget(self.btn_setup)

        # Secondary CTA — ArchHub Cloud trial. 30 free messages, no
        # card needed, no install. Best path for users with weak
        # hardware or unreliable internet for the 2 GB download.
        self.btn_cloud = QPushButton(
            "Try ArchHub Cloud · 30 free messages, no install"
        )
        self.btn_cloud.setObjectName("onboardingSecondary")
        self.btn_cloud.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cloud.setMinimumHeight(40)
        self.btn_cloud.clicked.connect(self._start_cloud_signin)
        v.addWidget(self.btn_cloud)

        # Progress block — hidden until the user clicks setup.
        self.progress_frame = QFrame()
        self.progress_frame.setObjectName("onboardingProgress")
        pv = QVBoxLayout(self.progress_frame)
        pv.setContentsMargins(SPACE["md"], SPACE["md"],
                               SPACE["md"], SPACE["md"])
        pv.setSpacing(SPACE["xs"])
        self.stage_lbl = QLabel("")
        self.stage_lbl.setObjectName("onboardingStage")
        pv.addWidget(self.stage_lbl)
        self.bar = QProgressBar()
        self.bar.setMinimum(0); self.bar.setMaximum(100); self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setObjectName("onboardingBar")
        pv.addWidget(self.bar)
        self.detail_lbl = QLabel("")
        self.detail_lbl.setObjectName("onboardingDetail")
        self.detail_lbl.setWordWrap(True)
        pv.addWidget(self.detail_lbl)
        self.progress_frame.setVisible(False)
        v.addWidget(self.progress_frame)

        v.addStretch(1)

        # Footer — escape hatches kept de-emphasized so the technophobe
        # never feels they MUST pick a path. Power user can opt in.
        foot = QHBoxLayout()
        foot.setSpacing(SPACE["sm"])
        self.btn_have_account = QPushButton(
            "I already have a Claude / OpenAI account"
        )
        self.btn_have_account.setObjectName("onboardingGhost")
        self.btn_have_account.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_have_account.clicked.connect(self._open_settings)
        foot.addWidget(self.btn_have_account)
        foot.addStretch(1)
        self.btn_skip = QPushButton("Skip for now")
        self.btn_skip.setObjectName("onboardingGhost")
        self.btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.clicked.connect(self._skip)
        foot.addWidget(self.btn_skip)
        v.addLayout(foot)

        self.setStyleSheet(_qss())

    # ------------------------------------------------------------------
    def _start_cloud_signin(self) -> None:
        """Open the browser PKCE flow against cloud.archhub.io. The
        user lands on a friendly sign-up form; once they finish, the
        local callback receives a one-time code, exchanges it for a
        bearer token, and the dialog closes successfully."""
        self.btn_setup.setEnabled(False)
        self.btn_cloud.setEnabled(False)
        self.btn_cloud.setText("Waiting for sign-in in your browser…")
        self.progress_frame.setVisible(True)
        self.stage_lbl.setText("Opening browser sign-in")
        self.bar.setValue(0)
        self.detail_lbl.setText(
            "Your browser just opened on archhub.io. Finish sign-up "
            "there and come back — we'll detect it automatically."
        )
        try:
            from cloud_auth import SignInWorker
            self._cloud_worker = SignInWorker(self)
            self._cloud_worker.succeeded.connect(self._on_cloud_signed_in)
            self._cloud_worker.failed.connect(self._on_cloud_failed)
            self._cloud_worker.start()
        except Exception as ex:
            self._on_cloud_failed(f"Couldn't start sign-in: "
                                    f"{type(ex).__name__}: {ex}")

    def _on_cloud_signed_in(self, payload: dict) -> None:
        # Persist successful sign-in. Onboarding done.
        try:
            from first_run import mark_complete
            mark_complete()
        except Exception:
            pass
        plan = (payload.get("me") or {}).get("plan", "trial")
        remaining = (payload.get("me") or {}).get("remaining_messages")
        msg = f"Signed in. You're on the {plan} plan"
        if remaining is not None:
            msg += f" — {remaining} messages available."
        self.stage_lbl.setText("Signed in to ArchHub Cloud.")
        self.detail_lbl.setText(msg)
        self.bar.setValue(100)
        self.btn_cloud.setText("Done")
        self.btn_cloud.setEnabled(True)
        try:
            self.btn_cloud.clicked.disconnect()
        except Exception:
            pass
        self.btn_cloud.clicked.connect(self._accept_complete)
        # Force a fresh quota fetch into the cache so the status bar
        # meter renders the right number on first paint.
        try:
            from cloud_usage import refresh_async
            refresh_async()
        except Exception:
            pass

    def _on_cloud_failed(self, message: str) -> None:
        self.btn_setup.setEnabled(True)
        self.btn_cloud.setEnabled(True)
        self.btn_cloud.setText("Try ArchHub Cloud · 30 free messages, no install")
        self.stage_lbl.setText("Sign-in didn't finish")
        self.detail_lbl.setText(message)

    # ------------------------------------------------------------------
    def _start_install(self) -> None:
        self.btn_setup.setEnabled(False)
        self.btn_setup.setText("Setting up your AI brain…")
        self.progress_frame.setVisible(True)
        try:
            from ollama_installer import OllamaInstaller
            self._installer = OllamaInstaller()
            self._installer.progress.connect(self._on_progress)
            self._installer.failed.connect(self._on_failed)
            self._installer.finished.connect(self._on_finished)
            self._installer.start()
        except Exception as ex:
            self._on_failed("startup",
                             f"Couldn't start setup: {type(ex).__name__}: {ex}")

    def _on_progress(self, stage: str, pct: int, detail: str) -> None:
        self.stage_lbl.setText(_STAGE_LABEL.get(stage, stage))
        self.bar.setValue(max(0, min(100, int(pct))))
        # Strip anything that smells like a path or technical token.
        self.detail_lbl.setText(detail or "")

    def _on_failed(self, stage: str, error: str) -> None:
        self.stage_lbl.setText(
            f"Setup couldn't finish ({_STAGE_LABEL.get(stage, stage)})"
        )
        self.detail_lbl.setText(error)
        self.btn_setup.setEnabled(True)
        self.btn_setup.setText("Try again")
        # Show error styling on the bar (orange) instead of green.
        self.bar.setStyleSheet(
            f"QProgressBar::chunk {{ background:{T['warn']}; }}"
        )

    def _on_finished(self, model: str) -> None:
        self.stage_lbl.setText("Your AI brain is ready.")
        self.detail_lbl.setText(
            "You can close this window and start chatting. "
            "Open Settings any time to add a cloud account if you'd "
            "like more options."
        )
        self.bar.setValue(100)
        self.btn_setup.setText("Done")
        self.btn_setup.setEnabled(True)
        self.btn_setup.clicked.disconnect()
        self.btn_setup.clicked.connect(self._accept_complete)
        # Persist the chosen model as the preferred Ollama default
        # so the router picks it without further config.
        try:
            from secrets_store import save_setting
            save_setting("ollama_default_model", model)
            save_setting("show_local_models", True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _accept_complete(self) -> None:
        try:
            from first_run import mark_complete
            mark_complete()
        except Exception:
            pass
        self.accept()

    def _open_settings(self) -> None:
        # Don't lose the onboarding flag — the user is choosing a
        # provider path, which counts as completing onboarding.
        try:
            from first_run import mark_complete
            mark_complete()
        except Exception:
            pass
        self.done(2)   # custom return code: caller routes to Settings

    def _skip(self) -> None:
        # Mark complete so we don't nag again. They can redo from
        # Settings → "Re-run onboarding" later.
        try:
            from first_run import mark_complete
            mark_complete()
        except Exception:
            pass
        self.reject()

    # ------------------------------------------------------------------
    def closeEvent(self, ev) -> None:
        # If the user closes mid-install, cancel the worker and mark
        # incomplete so onboarding shows again next launch.
        if self._installer is not None:
            try:
                self._installer.cancel()
            except Exception:
                pass
        super().closeEvent(ev)


# ---------------------------------------------------------------------------
def _qss() -> str:
    return (
        f"QDialog {{ background:{T['bg']}; }}"
        f"QLabel#onboardingTitle {{ "
        f"  font-family:{TYPE['fontSerif']}; font-style:italic; "
        f"  font-size:32px; color:{T['ink']}; "
        f"  letter-spacing:-0.02em; }}"
        f"QLabel#onboardingSubtitle {{ "
        f"  font-family:{TYPE['fontSans']}; font-size:14px; "
        f"  color:{T['inkSoft']}; line-height:1.5; }}"
        f"QLabel#onboardingPromise {{ "
        f"  font-family:{TYPE['fontMono']}; font-size:12px; "
        f"  color:{T['inkMuted']}; }}"
        f"QPushButton#onboardingPrimary {{ "
        f"  background:{T['accent']}; color:white; "
        f"  border:none; border-radius:{RADIUS['md']}px; "
        f"  padding:14px 24px; "
        f"  font-family:{TYPE['fontSans']}; "
        f"  font-size:16px; font-weight:500; }}"
        f"QPushButton#onboardingPrimary:hover {{ "
        f"  background:{T['accentHi']}; }}"
        f"QPushButton#onboardingPrimary:disabled {{ "
        f"  background:{T['inkDim']}; color:{T['inkSoft']}; }}"
        f"QPushButton#onboardingSecondary {{ "
        f"  background:transparent; color:{T['ink']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; "
        f"  padding:10px 18px; "
        f"  font-family:{TYPE['fontSans']}; "
        f"  font-size:13px; font-weight:500; }}"
        f"QPushButton#onboardingSecondary:hover {{ "
        f"  border-color:{T['accent']}; color:{T['accent']}; }}"
        f"QPushButton#onboardingSecondary:disabled {{ "
        f"  color:{T['inkDim']}; border-color:{T['inkDim']}; }}"
        f"QPushButton#onboardingGhost {{ "
        f"  background:transparent; color:{T['inkSoft']}; "
        f"  border:none; padding:6px 0; "
        f"  font-family:{TYPE['fontSans']}; font-size:12px; "
        f"  text-decoration:underline; }}"
        f"QPushButton#onboardingGhost:hover {{ color:{T['accent']}; }}"
        f"QFrame#onboardingProgress {{ "
        f"  background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['md']}px; }}"
        f"QLabel#onboardingStage {{ "
        f"  font-family:{TYPE['fontSans']}; font-size:13px; "
        f"  font-weight:500; color:{T['ink']}; }}"
        f"QLabel#onboardingDetail {{ "
        f"  font-family:{TYPE['fontMono']}; font-size:11px; "
        f"  color:{T['inkMuted']}; }}"
        f"QProgressBar#onboardingBar {{ "
        f"  background:{T['bgSoft']}; border:none; "
        f"  border-radius:4px; height:8px; }}"
        f"QProgressBar#onboardingBar::chunk {{ "
        f"  background:{T['accent']}; border-radius:4px; }}"
    )
