"""First-run onboarding wizard.

v1.3.2 round-2 cut: collapsed from a 3-step Continue/Next stack into ONE
modal with three real CTAs and a skip footer. The three steps were
'show one screen, click Continue, show next screen' chrome that wasted
the user's time on day one. The compressed flow surfaces:

  • Sign-ins   (primary OpenRouter button + Anthropic/OpenAI/Google secondaries)
  • Connectors (live detection summary + 'Open connector settings' link)
  • Skill library (top 4 starter skills as one-click chips)

All three blocks live in one scrollable column. Skip dismisses; clicking
any chip auto-completes onboarding.

The wizard records `onboarding_completed` in settings.json and never
appears again. The user can re-run it from Settings → "Show
onboarding again" if they want a refresher.

Sign-in path uses the same SignInDialog the Settings panel uses, so we
don't duplicate the OAuth flow.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
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
    """Single-screen first-run wizard. Modal but skippable."""

    finished_onboarding = pyqtSignal()

    def __init__(self, router, manager, parent=None):
        super().__init__(parent)
        self.router = router
        self.manager = manager
        self.setWindowTitle("Welcome to ArchHub")
        self.setObjectName("panel")
        self.setMinimumSize(640, 560)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        # Scrollable single-screen body — three sections stacked top to
        # bottom: Sign-ins · Connectors · Starter skills. No Continue
        # button, no "Step 1 of 3" chrome.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(40, 20, 40, 20)
        bl.setSpacing(20)
        bl.addWidget(self._build_section_signin())
        bl.addWidget(self._build_section_connectors())
        bl.addWidget(self._build_section_first_skill())
        bl.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        outer.addWidget(self._build_footer())
        self._refresh_connector_summary()

    # ---- header ----------------------------------------------------------

    def _build_header(self) -> QFrame:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(28, 24, 28, 18); v.setSpacing(6)
        t = QLabel("Welcome to ArchHub")
        t.setObjectName("panelTitle"); v.addWidget(t)
        s = QLabel(
            "A two-minute setup — sign in to an AI, see your tools, "
            "try a starter skill. Skip anything, change later in Settings."
        )
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        v.addWidget(s)
        # v1.3.2 round-2: the 3-step dot indicator was decoration when
        # we still had a Continue button between screens; with the
        # single-screen layout it's meaningless. Removed.
        return hf

    # ---- section 1: sign in ----------------------------------------------

    def _build_section_signin(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        title = QLabel("<b>Sign in to a cloud AI</b>")
        title.setStyleSheet("font-size: 17px; color: #f4efe8;")
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

        self._or_btn = QPushButton("Sign in with OpenRouter")
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

    def _update_signin_status(self) -> None:
        configured = sorted(self.router.configured_providers())
        cloud = [p for p in configured if p in ("anthropic", "openai", "google", "openrouter")]
        if cloud:
            self._signin_status.setText(
                f"Signed in: <b>{', '.join(cloud)}</b>"
            )
        else:
            self._signin_status.setText(
                "<i>Not signed in to a cloud LLM yet. You can still use a "
                "local Ollama model if you have one running.</i>"
            )

    # ---- section 2: connectors ------------------------------------------

    def _build_section_connectors(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        title = QLabel("<b>Your AEC tools</b>")
        title.setStyleSheet("font-size: 17px; color: #f4efe8;")
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

    # ---- section 3: first skill -----------------------------------------

    def _build_section_first_skill(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        title = QLabel("<b>Try a starter skill</b>")
        title.setStyleSheet("font-size: 17px; color: #f4efe8;")
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
                chip = QPushButton(f"  ·  {s['name']}  —  {s['intent'][:60]}")
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
        # Forward the run request to the chat backend. Parent may be
        # the StudioShell (which holds the chat backend as `chat_widget`)
        # or the bare ChatWindow itself in the fallback path.
        parent = self.parent()
        target = parent
        if parent is not None and hasattr(parent, "chat_widget"):
            target = parent.chat_widget
        if target is not None and hasattr(target, "_run_skill_by_id"):
            try:
                # Switch to the Chat page first if we're inside the Studio
                # shell so the user sees the run unfold instead of landing
                # on Home with no visible response.
                if parent is not None and hasattr(parent, "_set_page"):
                    try:
                        parent._set_page("chat")
                    except Exception:
                        pass
                target._run_skill_by_id(skill_id, {"prompt": ""})
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

        # v1.3.2: single-screen layout — no Continue button, just Finish.
        self._finish_btn = QPushButton("Finish")
        self._finish_btn.setObjectName("primaryButton")
        self._finish_btn.clicked.connect(self._on_finish)
        h.addWidget(self._finish_btn)

        return f

    def _on_finish(self) -> None:
        mark_completed()
        self.finished_onboarding.emit()
        self.accept()

    def _on_skip(self) -> None:
        mark_completed()
        self.finished_onboarding.emit()
        self.reject()
