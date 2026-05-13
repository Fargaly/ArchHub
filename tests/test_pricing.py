"""Pricing tiers page (v1.0).

Lightweight assertions on tier definitions + page assembly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


class TestTierData:
    def test_four_tiers_defined(self):
        # v1.0: BYO / Solo / Studio / Firm
        from pricing_page import TIERS
        assert len(TIERS) == 4
        ids = {t["id"] for t in TIERS}
        assert ids == {"byo", "solo", "studio", "firm"}

    def test_byo_is_zero_dollars(self):
        from pricing_page import TIERS
        byo = next(t for t in TIERS if t["id"] == "byo")
        assert byo["price"] == "$0"
        assert byo["url"] is None

    def test_studio_is_primary_at_79(self):
        # Studio is the highlighted middle tier — $79/mo.
        from pricing_page import TIERS
        studio = next(t for t in TIERS if t["id"] == "studio")
        assert studio["price"] == "$79"
        assert studio["primary"] is True
        assert studio["url"] is not None
        assert studio["url"].startswith("https://")

    def test_each_tier_has_features(self):
        from pricing_page import TIERS
        for t in TIERS:
            assert isinstance(t["features"], list)
            assert len(t["features"]) >= 3

    def test_solo_studio_firm_have_checkout_tier(self):
        from pricing_page import TIERS
        for tid in ("solo", "studio", "firm"):
            t = next(t for t in TIERS if t["id"] == tid)
            assert t["checkout_tier"] == tid


class TestPageBuild:
    def test_page_instantiates(self, qapp):
        from pricing_page import PricingPage
        page = PricingPage()
        assert page is not None
        from PyQt6.QtWidgets import QPushButton
        # Four CTA buttons + header buttons.
        ctas = [b for b in page.findChildren(QPushButton)]
        assert len(ctas) >= 4

    def test_byo_card_label_contains_zero(self, qapp):
        from pricing_page import PricingPage
        from PyQt6.QtWidgets import QLabel
        page = PricingPage()
        labels = [lab.text() for lab in page.findChildren(QLabel)]
        # All four tier prices appear.
        assert any("$0" in t for t in labels)
        assert any("$19" in t for t in labels)
        assert any("$79" in t for t in labels)
        assert any("$299" in t for t in labels)


class TestVersionBumped:
    def test_version_file_is_one_zero(self):
        path = Path(__file__).resolve().parent.parent / "VERSION"
        assert path.exists()
        v = path.read_text(encoding="utf-8").strip()
        # Track the latest stable. v1.1.0 is the "deep build" minor
        # bump — Rhino + Procore connectors, marketplace v1 cloud
        # backend, cross-platform CI matrix, code-signing infra, plus
        # Civil 3D / trademark / SOC 2 prep docs.
        assert v == "1.1.0"
