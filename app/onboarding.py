"""First-run onboarding wizard.

Shows once per device, the very first time the user opens ArchHub. Walks
them through three steps:

  1. Sign in to a cloud LLM (OpenRouter is the default — real OAuth,
     covers Claude / GPT / Gemini / Llama / Qwen).
  2. Show what AEC tools were detected on this machine and which
     connectors are ready.
  3. Demo a first Skill so the user has something concrete to click.

The wizard records `onboarding_completed` in settings.json and never
appears again. The user can re-run it from Settings → "Show
onboarding again" if they want a refresher.

Design choices:
  - No back button. Each step is small enough that "go forward, change
    your mind later in Settings" is the right UX.
  - Skip is always available — onboarding shouldn't block the user
    from reaching the chat.
  - Sign-in step uses the same SignInDialog the Settings panel uses,
    so we don't duplicate the OAuth flow.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from secrets_store import load_setting, save_setting


ONBOARDING_KEY = "onboarding_completed"


def needs_onboarding() -> bool:
    """True if we should show the wizard on this launch."""
    return not bool(load_setting(ONBOARDING_KEY))


def mark_completed() -> None:
    save_setting(ONBOARDING_KEY, True)


# ---------------------------------------------------------------------------
class OnboardingWizard(QDialog):
    """Three-step first-run wizard. Modal but skippable."""

    finished_onboarding = pyqtSignal()

    def __init__(self, router, manager, parent=None):
        super().__init__(parent)
        self.router = router
        self.manager = manager
        self.setWindowTitle("Welcome to ArchHub")
        self.setObjectName("panel")
        self.setMinimumSize(640, 480)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_step_signin())
        self._stack.addWidget(self._build_step_connectors())
        self._stack.addWidget(self._build_step_first_skill())
        outer.addWidget(self._stack, 1)

        outer.addWidget(self._build_footer())
        self._update_buttons()

    # ---- header ----------------------------------------------------------

    def _build_header(self) -> QFrame:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(28, 24, 28, 18); v.setSpacing(6)
        t = QLabel("Welcome to ArchHub")
        t.setObjectName("panelTitle"); v.addWidget(t)
        s = QLabel(
            "A two-minute setup — then you can stop reading and start "
            "asking ArchHub to do things."
        )
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        v.addWidget(s)

        # Step indicator: ● ○ ○ → ○ ● ○ → ○ ○ ●
        self._dots = QLabel("●  ○  ○")
        self._dots.setStyleSheet(
            "color: #cc785c; font-size: 14px; letter-spacing: 6px; padding-top: 8px;"
        )
        v.addWidget(self._dots)
        return hf

    # ---- step 1: sign in --------------------------------------------------

    def _build_step_signin(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(40, 28, 40, 20); v.setSpacing(14)

        title = QLabel("<b>Step 1 of 3 — Sign in to a cloud AI</b>")
        title.setStyleSheet("font-size: 18px; color: #f4efe8;")
        v.addWidget(title)

        body = QLabel(
            "ArchHub uses a large-language model to understand what you want "
            "and drive your tools. The fastest way to get a good model is "
            "<b>OpenRouter</b> — one OAuth click covers Claude, GPT, "
            "Gemini, Llama, Qwen, and ~300 other models. Pay-as-you-go.<br><br>"
            "Already have an Anthropic, OpenAI, or Google API key? You can "
            "skip this and add it from Settings any time."
        )
        body.setObjectName("settingsSubtitle"); body.setWordWrap(True)
        v.addWidget(body)

        button_row = QHBoxLayout(); button_row.setSpacing(10)

        self._or_btn = QPushButton("🔐  Sign in with OpenRouter")
        self._or_btn.setObjectName("primaryButton")
        self._or_btn.clicked.connect(lambda: self._open_signin("openrouter"))
        button_row.addWidget(self._or_btn)

        self._ant_btn = QPushButton("Anthropic")
        self._ant_btn.setObjectName("ghostButton")
        self._ant_btn.clicked.connect(lambda: self._open_signin("anthropic"))
        button_row.addWidget(self._ant_btn)

        self._oai_btn = QPushButton("OpenAI")
        self._oai_btn.setObjectName("ghostButton")
        self._oai_btn.clicked.connect(lambda: self._open_signin("openai"))
        button_row.addWidget(self._oai_btn)

        self._google_btn = QPushButton("Google")
        self._google_btn.setObjectName("ghostButton")
        self._google_btn.clicked.connect(lambda: self._open_signin("google"))
        button_row.addWidget(self._google_btn)

        button_row.addStretch(1)
        v.addLayout(button_row)

        self._signin_status = QLabel("")
        self._signin_status.setObjectName("settingsSubtitle"); self._signin_status.setWordWrap(True)
        v.addWidget(self._signin_status)

        v.addStretch(1)
        self._update_signin_status()
        return page

    def _open_signin(self, provider: str) -> None:
        from sign_in_dialog import SignInDialog
        dlg = SignInDialog(provider, self)
        dlg.signed_in.connect(lambda _p: self._update_signin_status())
        dlg.exec()
        self._update_signin_status()
        self._update_buttons()

    def _update_signin_status(self) -> None:
        configured = sorted(self.router.configured_providers())
        cloud = [p for p in configured if p in ("anthropic", "openai", "google", "openrouter")]
        if cloud:
            self._signin_status.setText(
                f"✓ Signed in to: <b>{', '.join(cloud)}</b>"
            )
        else:
            self._signin_status.setText(
                "<i>Not signed in to a cloud LLM yet. You can still use a "
                "local Ollama model if you have one running.</i>"
            )

    # ---- step 2: connectors ----------------------------------------------

    def _build_step_connectors(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(40, 28, 40, 20); v.setSpacing(14)

        title = QLabel("<b>Step 2 of 3 — Your AEC tools</b>")
        title.setStyleSheet("font-size: 18px; color: #f4efe8;")
        v.addWidget(title)

        body = QLabel(
            "ArchHub looked at this machine and found these AEC apps. The "
            "ones marked <b>READY</b> can be turned on with one click; the "
            "ones marked <b>ACTIVE</b> already are. ArchHub will only drive "
            "applications you toggle on."
        )
        body.setObjectName("settingsSubtitle"); body.setWordWrap(True)
        v.addWidget(body)

        self._connector_summary = QLabel("")
        self._connector_summary.setObjectName("settingsSubtitle"); self._connector_summary.setWordWrap(True)
        v.addWidget(self._connector_summary)

        button_row = QHBoxLayout(); button_row.setSpacing(10)
        open_conn = QPushButton("Open connector settings")
        open_conn.setObjectName("ghostButton")
        open_conn.clicked.connect(self._open_connectors_panel)
        button_row.addWidget(open_conn)
        button_row.addStretch(1)
        v.addLayout(button_row)
        v.addStretch(1)
        return page

    def _refresh_connector_summary(self) -> None:
        from manager import ConnectorState
        active, ready, unavailable = [], [], []
        try:
            self.manager.refresh()
            for e in self.manager.entries:
                if e.state == ConnectorState.ACTIVE:
                    active.append(e.display_name)
                elif e.state == ConnectorState.READY:
                    ready.append(e.display_name)
                else:
                    unavailable.append(e.display_name)
        except Exception:
            pass

        lines = []
        if active:
            lines.append(f"<b>ACTIVE</b>  ({len(active)}):  {', '.join(active)}")
        if ready:
            lines.append(f"<b>READY</b>  ({len(ready)}):  {', '.join(ready)}")
        if unavailable and not active and not ready:
            lines.append(
                "<i>No AEC apps detected on this machine. ArchHub still "
                "works for chat-only tasks; you can install Revit, "
                "Blender, AutoCAD, or 3ds Max and re-run this wizard "
                "from Settings.</i>"
            )
        self._connector_summary.setText("<br>".join(lines) or "<i>Detecting…</i>")

    def _open_connectors_panel(self) -> None:
        # Defer import — avoids a circular import at module-load time.
        from connector_panel import ConnectorPanel
        dlg = ConnectorPanel(self.manager, self)
        dlg.exec()
        self._refresh_connector_summary()

    # ---- step 3: first skill ---------------------------------------------

    def _build_step_first_skill(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(40, 28, 40, 20); v.setSpacing(14)

        title = QLabel("<b>Step 3 of 3 — Try a Skill</b>")
        title.setStyleSheet("font-size: 18px; color: #f4efe8;")
        v.addWidget(title)

        body = QLabel(
            "Skills are reusable shortcuts ArchHub ships with — and that "
            "you create yourself by saving useful chats. Pick one to run "
            "now, or skip to the chat and discover them as you go."
        )
        body.setObjectName("settingsSubtitle"); body.setWordWrap(True)
        v.addWidget(body)

        chip_col = QVBoxLayout(); chip_col.setSpacing(8)
        try:
            import skills as _skills
            for s in _skills.list_skills()[:4]:
                chip = QPushButton(f"  ✦  {s['name']}  —  {s['intent'][:60]}")
                chip.setObjectName("welcomeChip")
                chip.clicked.connect(
                    lambda _checked=False, sid=s["id"]: self._launch_skill(sid)
                )
                chip_col.addWidget(chip)
        except Exception:
            chip_col.addWidget(QLabel("<i>Skills will appear once cloud sync finishes.</i>"))
        v.addLayout(chip_col)

        v.addStretch(1)
        hint = QLabel(
            "<i>Tip: in chat you can also type "
            "<code>/skill list</code> to see every Skill, or "
            "<code>/skill save</code> after a useful conversation to save "
            "it for next time.</i>"
        )
        hint.setObjectName("settingsSubtitle"); hint.setWordWrap(True)
        v.addWidget(hint)
        return page

    def _launch_skill(self, skill_id: str) -> None:
        # Mark onboarding done first so we don't re-prompt next launch even
        # if the skill run fails.
        mark_completed()
        self.finished_onboarding.emit()
        # Forward the run request to the parent chat window.
        parent = self.parent()
        if parent is not None and hasattr(parent, "_run_skill_by_id"):
            try:
                parent._run_skill_by_id(skill_id, {"prompt": ""})
            except Exception:
                pass
        self.accept()

    # ---- footer ----------------------------------------------------------

    def _build_footer(self) -> QFrame:
        f = QFrame(); f.setObjectName("panelFooter")
        h = QHBoxLayout(f); h.setContentsMargins(24, 14, 24, 16); h.setSpacing(10)

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setObjectName("ghostButton")
        self._skip_btn.clicked.connect(self._on_skip)
        h.addWidget(self._skip_btn)

        h.addStretch(1)

        self._next_btn = QPushButton("Continue →")
        self._next_btn.setObjectName("primaryButton")
        self._next_btn.clicked.connect(self._on_next)
        h.addWidget(self._next_btn)

        return f

    def _update_buttons(self) -> None:
        idx = self._stack.currentIndex()
        dots = ["●  ○  ○", "○  ●  ○", "○  ○  ●"][idx]
        self._dots.setText(dots)
        if idx == 1:
            self._refresh_connector_summary()
        if idx == self._stack.count() - 1:
            self._next_btn.setText("Finish")
        else:
            self._next_btn.setText("Continue →")

    def _on_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
            self._update_buttons()
        else:
            mark_completed()
            self.finished_onboarding.emit()
            self.accept()

    def _on_skip(self) -> None:
        mark_completed()
        self.finished_onboarding.emit()
        self.reject()
