"""In-app Plans & pricing dialog.

Honest freemium policy: ArchHub is free in full while we're in beta.
A managed cloud-relay tier ("Studio") for firms is in active development
but not yet generally available — we don't show a dollar figure or take
payment for something that isn't deployed. Users who want to be
notified when Studio ships file a GitHub Issue from the dialog and we
let them know.

The full pricing model + tier rationale live in STRATEGY.md (internal).
This dialog only displays what is real today.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)


LANDING_URL = "https://github.com/Fargaly/ArchHub#pricing"
# Until a real domain + mailbox exist, route Enterprise contact through
# GitHub Issues — the Discussion / Issue thread is real, monitored, and
# encrypted in transit. No fake mailbox, no bounced emails.
CONTACT_URL = "https://github.com/Fargaly/ArchHub/issues/new?labels=enterprise&title=Enterprise+enquiry"


_WAITLIST_URL = "https://github.com/Fargaly/ArchHub/issues/new?labels=studio-waitlist&title=Studio+waitlist"

# Only one tier is real today. The two "coming soon" entries are
# placeholders that route to a GitHub Issue waitlist; nothing about
# them collects payment, displays a price, or implies imminent ship.
_TIERS = [
    {
        "name": "Free",
        "price": "$0",
        "cadence": "",
        "blurb": "Everything that works today.",
        "features": [
            "Unlimited Skills",
            "Local LLM via Ollama, or bring your own cloud API key",
            "Cloud sync via your private GitHub repo",
            "Sketch → production pipeline",
            "Vision input (paste sketches)",
            "Auto-update from GitHub Releases",
            "Open source, MIT-licensed",
        ],
        "cta": "Download",
        "cta_url": "https://github.com/Fargaly/ArchHub/releases/latest",
        "primary": True,
        "recommended": True,
        "current": True,
    },
    {
        "name": "Studio",
        "price": "Coming soon",
        "cadence": "",
        "blurb": "Managed cloud relay for firms.",
        "features": [
            "Provider keys live on the relay, not on architect laptops",
            "Per-architect rate limits + audit logs",
            "Firm-shared Skill library",
            "Centralised billing + cost dashboard",
        ],
        "cta": "Join the waitlist",
        "cta_url": _WAITLIST_URL,
        "primary": False,
        "recommended": False,
        "current": False,
    },
    {
        "name": "Enterprise",
        "price": "Coming soon",
        "cadence": "",
        "blurb": "Self-hosted relay + IP isolation.",
        "features": [
            "Self-hosted relay so traffic never leaves your infra",
            "Custom Skill development against firm standards",
            "Annual billing",
        ],
        "cta": "Open an enquiry",
        "cta_url": CONTACT_URL,
        "primary": False,
        "recommended": False,
        "current": False,
    },
]


class _TierCard(QFrame):
    def __init__(self, tier: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("skillCard")
        if tier.get("recommended"):
            self.setStyleSheet(
                "QFrame#skillCard { border: 1px solid rgba(204,120,92,0.45); }"
            )

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 22, 20, 20)
        v.setSpacing(8)

        if tier.get("recommended"):
            badge = QLabel("Recommended")
            badge.setObjectName("skillCardTags")
            v.addWidget(badge)

        name = QLabel(tier["name"])
        name.setObjectName("skillCardTitle")
        v.addWidget(name)

        price_row = QHBoxLayout()
        price = QLabel(tier["price"])
        price.setStyleSheet(
            "font-size: 32px; font-weight: 600; color: #f4efe8;"
        )
        price_row.addWidget(price)
        if tier.get("cadence"):
            cadence = QLabel(tier["cadence"])
            cadence.setObjectName("settingsSubtitle")
            cadence.setStyleSheet("padding-bottom: 4px;")
            price_row.addWidget(cadence)
        price_row.addStretch(1)
        v.addLayout(price_row)

        blurb = QLabel(tier["blurb"])
        blurb.setObjectName("settingsSubtitle")
        blurb.setWordWrap(True)
        v.addWidget(blurb)

        v.addSpacing(6)
        for feat in tier["features"]:
            row = QLabel(f"<span style='color:#cc785c;font-weight:600;'>✓</span>  {feat}")
            row.setObjectName("settingsSubtitle")
            row.setWordWrap(True)
            v.addWidget(row)

        v.addStretch(1)

        if tier.get("current"):
            chip = QLabel("✓  You're on this plan")
            chip.setStyleSheet(
                "color: #cc785c; font-weight: 600; padding: 8px 0;"
            )
            v.addWidget(chip)
        else:
            btn = QPushButton(tier["cta"])
            btn.setObjectName("primaryButton" if tier.get("primary") else "ghostButton")
            url = tier["cta_url"]
            btn.clicked.connect(lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            v.addWidget(btn)


class PricingDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("ArchHub — Plans & pricing")
        self.setObjectName("panel")
        self.resize(960, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(28, 28, 28, 28)
        grid.setSpacing(18)

        for col, tier in enumerate(_TIERS):
            grid.addWidget(_TierCard(tier), 0, col)
            grid.setColumnStretch(col, 1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        outer.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        hf = QFrame(); hf.setObjectName("panelHeader")
        v = QVBoxLayout(hf); v.setContentsMargins(28, 24, 28, 18); v.setSpacing(6)
        t = QLabel("Plans & pricing")
        t.setObjectName("panelTitle"); v.addWidget(t)
        s = QLabel(
            "ArchHub is free in full while we're in beta. We will not "
            "charge for anything we haven't shipped. The Studio tier "
            "(managed cloud relay for firms) is in development — join "
            "the waitlist to be told when it's real, with a price."
        )
        s.setObjectName("panelSubtitle"); s.setWordWrap(True)
        v.addWidget(s)
        return hf

    def _build_footer(self) -> QFrame:
        f = QFrame(); f.setObjectName("panelFooter")
        h = QHBoxLayout(f); h.setContentsMargins(24, 14, 24, 16); h.setSpacing(10)

        view_landing = QPushButton("View full pricing on the website")
        view_landing.setObjectName("ghostButton")
        view_landing.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(LANDING_URL))
        )
        h.addWidget(view_landing)

        h.addStretch(1)

        close = QPushButton("Close")
        close.setObjectName("primaryButton")
        close.clicked.connect(self.accept)
        h.addWidget(close)

        return f
