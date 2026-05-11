"""Pricing tiers (v1.0).

Two-tier offering surfaced as a Studio page:

  • BYO ($0)        — local install, bring-your-own provider keys.
                       Connectors, marketplace, workflows, brand
                       guidelines, full feature set. Ships forever.
  • Studio ($199/mo) — managed firm relay (no per-user keys),
                        priority support, signed update channel,
                        team Skills marketplace.

The page is a comparison card grid. The "Choose Studio" button
opens the upgrade flow on archhub.app/upgrade in the user's
browser; the "Stay on BYO" button is a no-op marker that closes the
page (BYO is the default state).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from design_tokens import RADIUS, SPACE, TYPE, current as _current_palette


class _LivePalette:
    def __getitem__(self, k): return _current_palette()[k]
    def get(self, k, default=None): return _current_palette().get(k, default)
T = _LivePalette()


# Tier definitions — single source of truth. The page renders two
# cards side-by-side; the order here = display order.
TIERS: list[dict] = [
    {
        "id": "byo",
        "name": "BYO",
        "price": "$0",
        "cadence": "forever",
        "tagline": "Your keys. Your Ollama. Your machine.",
        "summary": (
            "The full open-source app. Connectors, marketplace, "
            "workflows, brand guidelines. Use your own Claude / OpenAI / "
            "Gemini keys, or stay 100% offline with a local AI brain. "
            "Free forever."
        ),
        "features": [
            "All host connectors (Revit, AutoCAD, Max, Blender, Outlook)",
            "Marketplace Skills + Workflows",
            "Multi-instance @session routing",
            "Local AI (Ollama) auto-install",
            "Bring your own cloud AI keys",
            "Cloud sync via your own GitHub",
            "Community support (GitHub issues)",
        ],
        "cta": "Stay on BYO",
        "url": None,
        "primary": False,
        "checkout_tier": None,
    },
    {
        "id": "solo",
        "name": "Solo",
        "price": "$19",
        "cadence": "/month",
        "tagline": "Cloud AI, no install, no keys.",
        "summary": (
            "Everything in BYO, plus our managed AI service. Sign in "
            "with email, start chatting. 500 messages a month across "
            "Claude / GPT / Gemini — we pick the best model per task."
        ),
        "features": [
            "Everything in BYO",
            "500 messages / month",
            "Managed AI (no provider keys to manage)",
            "Auto model routing (Claude / GPT / Gemini)",
            "Email support",
        ],
        "cta": "Start free 7-day trial",
        "url": "https://archhub.app/upgrade?tier=solo",
        "primary": False,
        "checkout_tier": "solo",
    },
    {
        "id": "studio",
        "name": "Studio",
        "price": "$79",
        "cadence": "/month",
        "tagline": "For architects who chat a lot.",
        "summary": (
            "Higher quota, team Skill sharing, signed updates, priority "
            "support. The default tier for a working architect or a "
            "two-person practice."
        ),
        "features": [
            "Everything in Solo",
            "2,000 messages / month",
            "Private team Skill marketplace",
            "Signed update channel (Ed25519)",
            "Priority email (24h SLA)",
            "Onboarding session (1h with founder)",
        ],
        "cta": "Choose Studio",
        "url": "https://archhub.app/upgrade?tier=studio",
        "primary": True,
        "checkout_tier": "studio",
    },
    {
        "id": "firm",
        "name": "Firm",
        "price": "$299",
        "cadence": "/mo + $39/seat",
        "tagline": "For practices of 5+.",
        "summary": (
            "Unlimited fair-use messaging, SSO, audit log, on-prem deploy "
            "option, named support contact. Open-source license includes "
            "the right to self-host the relay for fully air-gapped firms."
        ),
        "features": [
            "Everything in Studio",
            "Unlimited fair-use messaging",
            "SSO (SAML / OIDC)",
            "Audit log + usage exports",
            "Self-host relay (AGPL grant)",
            "Named support contact",
            "Volume discounts at 25+ seats",
        ],
        "cta": "Talk to sales",
        "url": "https://archhub.app/firm",
        "primary": False,
        "checkout_tier": "firm",
    },
]


class PricingPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPage")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 40)
        outer.setSpacing(SPACE["lg"])

        # Header.
        cap = QLabel("PRICING")
        cap.setObjectName("studioMonoCap")
        outer.addWidget(cap)
        h1 = QLabel("Two ways to run ArchHub")
        h1.setObjectName("studioH1")
        outer.addWidget(h1)
        sub = QLabel(
            "BYO is the local-first default. Studio is the same app "
            "with a managed relay + signed updates for firms that don't "
            "want to manage provider keys per architect."
        )
        sub.setObjectName("studioH1Sub")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # Two-card grid.
        grid = QHBoxLayout()
        grid.setSpacing(SPACE["lg"])
        grid.setContentsMargins(0, SPACE["md"], 0, 0)
        for tier in TIERS:
            grid.addWidget(self._build_card(tier), 1)
        grid_w = QWidget()
        grid_w.setLayout(grid)
        outer.addWidget(grid_w)

        # Footer note — discreet pointer to compare-tiers detail.
        foot = QLabel(
            "Switching tiers later is a no-op — your local data stays "
            "exactly where it is. Email <a href='mailto:hello@archhub.app'>"
            "hello@archhub.app</a> for firm-wide pricing or volume."
        )
        foot.setObjectName("studioMonoMuted")
        foot.setWordWrap(True)
        foot.setOpenExternalLinks(True)
        outer.addWidget(foot)
        outer.addStretch(1)

        self.setStyleSheet(_qss())

    # ------------------------------------------------------------------
    def _build_card(self, tier: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("pricingCard" if not tier.get("primary")
                            else "pricingCardPrimary")
        card.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.MinimumExpanding)
        v = QVBoxLayout(card)
        v.setContentsMargins(SPACE["lg"], SPACE["lg"],
                              SPACE["lg"], SPACE["lg"])
        v.setSpacing(SPACE["sm"])

        # Tier name (mono cap).
        name = QLabel(tier["name"].upper())
        name.setObjectName("pricingTierName")
        v.addWidget(name)

        # Price line.
        price_row = QHBoxLayout()
        price_row.setSpacing(SPACE["xs"])
        price_lbl = QLabel(tier["price"])
        price_lbl.setObjectName("pricingPrice")
        price_row.addWidget(price_lbl)
        cadence = QLabel(tier["cadence"])
        cadence.setObjectName("pricingCadence")
        cadence.setAlignment(Qt.AlignmentFlag.AlignBottom)
        price_row.addWidget(cadence)
        price_row.addStretch(1)
        price_w = QWidget()
        price_w.setLayout(price_row)
        v.addWidget(price_w)

        # Tagline (italic serif).
        tag = QLabel(tier["tagline"])
        tag.setObjectName("pricingTagline")
        tag.setWordWrap(True)
        v.addWidget(tag)

        # Summary paragraph.
        sm = QLabel(tier["summary"])
        sm.setObjectName("pricingSummary")
        sm.setWordWrap(True)
        v.addWidget(sm)

        # Feature list.
        v.addSpacing(SPACE["xs"])
        for feat in tier["features"]:
            row = QHBoxLayout()
            row.setSpacing(SPACE["xs"]+2)
            check = QLabel("✓")
            check.setObjectName("pricingCheck")
            row.addWidget(check)
            f = QLabel(feat)
            f.setObjectName("pricingFeature")
            f.setWordWrap(True)
            row.addWidget(f, 1)
            row_w = QWidget()
            row_w.setLayout(row)
            v.addWidget(row_w)

        v.addStretch(1)

        # CTA button.
        cta = QPushButton(tier["cta"])
        cta.setObjectName("primaryButton" if tier.get("primary")
                          else "ghostButton")
        cta.setCursor(Qt.CursorShape.PointingHandCursor)
        cta.setMinimumHeight(36)
        checkout_tier = tier.get("checkout_tier")
        fallback_url = tier.get("url")
        if checkout_tier:
            # Two paths:
            #   1. Signed in → ask the backend for a Stripe Checkout URL
            #      bound to this user's customer record. One click,
            #      already pre-filled with their email + plan.
            #   2. Not signed in → open the landing page upgrade flow
            #      which collects an email first, then redirects to
            #      Checkout. Same end state, one extra step.
            cta.clicked.connect(
                lambda _checked=False, t=checkout_tier, u=fallback_url:
                    self._start_checkout(t, u)
            )
        elif fallback_url:
            cta.clicked.connect(
                lambda _checked=False, u=fallback_url:
                    QDesktopServices.openUrl(QUrl(u))
            )
        else:
            cta.clicked.connect(lambda _checked=False, b=cta:
                                  b.setText("Already on BYO ✓"))
        v.addWidget(cta)

        return card

    # ------------------------------------------------------------------
    def _start_checkout(self, tier: str, fallback_url: str | None) -> None:
        """Try the in-app Stripe Checkout URL first; if the backend
        isn't reachable or the user isn't signed in, fall back to the
        landing-page upgrade flow."""
        try:
            from cloud_client import is_signed_in, checkout
            if is_signed_in():
                url = checkout(tier)
                if url:
                    QDesktopServices.openUrl(QUrl(url))
                    return
        except Exception:
            pass
        if fallback_url:
            QDesktopServices.openUrl(QUrl(fallback_url))


# ---------------------------------------------------------------------------
def _qss() -> str:
    return (
        f"QFrame#pricingCard {{ background:{T['bgRaised']}; "
        f"  border:1px solid {T['line']}; "
        f"  border-radius:{RADIUS['lg']}px; }}"
        f"QFrame#pricingCardPrimary {{ background:{T['bgRaised']}; "
        f"  border:2px solid {T['accent']}; "
        f"  border-radius:{RADIUS['lg']}px; }}"
        f"QLabel#pricingTierName {{ "
        f"  font-family:{TYPE['fontMono']}; font-size:11px; "
        f"  letter-spacing:0.12em; color:{T['inkMuted']}; }}"
        f"QLabel#pricingPrice {{ "
        f"  font-family:{TYPE['fontSerif']}; font-size:42px; "
        f"  font-style:italic; color:{T['ink']}; "
        f"  letter-spacing:-0.02em; }}"
        f"QLabel#pricingCadence {{ "
        f"  font-family:{TYPE['fontSans']}; font-size:12px; "
        f"  color:{T['inkSoft']}; padding-bottom:8px; }}"
        f"QLabel#pricingTagline {{ "
        f"  font-family:{TYPE['fontSerif']}; font-style:italic; "
        f"  font-size:16px; color:{T['accent']}; "
        f"  letter-spacing:-0.01em; }}"
        f"QLabel#pricingSummary {{ "
        f"  font-family:{TYPE['fontSans']}; font-size:12.5px; "
        f"  color:{T['inkSoft']}; line-height:1.55; }}"
        f"QLabel#pricingCheck {{ color:{T['accent']}; "
        f"  font-weight:700; font-size:13px; }}"
        f"QLabel#pricingFeature {{ "
        f"  font-family:{TYPE['fontSans']}; font-size:12px; "
        f"  color:{T['ink']}; }}"
    )
