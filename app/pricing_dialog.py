"""In-app Plans & pricing dialog.

Surfaces the four-tier pricing structure (Free / Pro / Studio / Enterprise)
so users discovering ArchHub via the cog menu see what's coming and can
mark interest. CTA buttons currently route to the landing page; once
Stripe is live they'll deep-link to a checkout session.

Why an in-app dialog and not just the landing page:
  - Most users never visit the landing page after installing.
  - The cog menu is where the existing trust lives — adding "Plans &
    pricing" there makes upgrade discoverable without nagging.
  - Once Stripe is wired, the dialog can manage the active subscription
    in the same surface.
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


_TIERS = [
    {
        "name": "Free",
        "price": "$0",
        "cadence": "/ month",
        "blurb": "Solo, evaluation, students.",
        "features": [
            "Up to 3 saved Skills",
            "Local Ollama only",
            "Single device",
            "Community support",
        ],
        "cta": "Download",
        "cta_url": "https://github.com/Fargaly/ArchHub/releases/latest",
        "primary": False,
        "recommended": False,
        "current": True,         # the user is on Free until Stripe is wired
    },
    {
        "name": "Pro",
        "price": "$39",
        "cadence": "/ seat / month",
        "blurb": "Solo architects + small studios.",
        "features": [
            "Unlimited Skills",
            "Cloud sync via GitHub",
            "BYO API keys",
            "5-device sync",
            "Email support",
        ],
        "cta": "Start Pro (waitlist)",
        "cta_url": LANDING_URL,
        "primary": True,
        "recommended": True,
        "current": False,
    },
    {
        "name": "Studio",
        "price": "$79",
        "cadence": "/ seat / month",
        "blurb": "Firms, 5-100 seats.",
        "features": [
            "Pro features",
            "Cloud LLM relay (we hold keys)",
            "Firm-shared Skill library",
            "Cost dashboard",
            "Phone + email support",
            "Firm SSO",
        ],
        "cta": "Start Studio (waitlist)",
        "cta_url": LANDING_URL,
        "primary": False,
        "recommended": False,
        "current": False,
    },
    {
        "name": "Enterprise",
        "price": "Custom",
        "cadence": "",
        "blurb": "100+ seats, IP-isolated.",
        "features": [
            "Studio features",
            "Self-hosted relay",
            "Custom Skill development",
            "Dedicated support",
            "Annual billing",
        ],
        "cta": "Contact us",
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
            "Use ArchHub free for as long as you like. Pro and Studio "
            "ship with v1.0 — join the waitlist to get a launch discount."
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
