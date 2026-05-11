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
    def test_two_tiers_defined(self):
        from pricing_page import TIERS
        assert len(TIERS) == 2
        ids = {t["id"] for t in TIERS}
        assert ids == {"byo", "studio"}

    def test_byo_is_zero_dollars(self):
        from pricing_page import TIERS
        byo = next(t for t in TIERS if t["id"] == "byo")
        assert byo["price"] == "$0"
        assert byo["url"] is None

    def test_studio_has_upgrade_url(self):
        from pricing_page import TIERS
        studio = next(t for t in TIERS if t["id"] == "studio")
        assert studio["price"] == "$199"
        assert studio["url"] is not None
        assert studio["url"].startswith("https://")

    def test_each_tier_has_features(self):
        from pricing_page import TIERS
        for t in TIERS:
            assert isinstance(t["features"], list)
            assert len(t["features"]) >= 3   # not an accidental empty list

    def test_studio_includes_byo_features(self):
        # The Studio tier must explicitly include "Everything in BYO".
        from pricing_page import TIERS
        studio = next(t for t in TIERS if t["id"] == "studio")
        assert any("BYO" in f or "Everything" in f for f in studio["features"])


class TestPageBuild:
    def test_page_instantiates(self, qapp):
        from pricing_page import PricingPage
        page = PricingPage()
        assert page is not None
        from PyQt6.QtWidgets import QPushButton
        # Two CTA buttons, one per tier.
        ctas = [b for b in page.findChildren(QPushButton)]
        assert len(ctas) >= 2

    def test_byo_card_label_contains_zero(self, qapp):
        from pricing_page import PricingPage
        from PyQt6.QtWidgets import QLabel
        page = PricingPage()
        labels = [lab.text() for lab in page.findChildren(QLabel)]
        assert any("$0" in t for t in labels)
        assert any("$199" in t for t in labels)


class TestVersionBumped:
    def test_version_file_is_one_zero(self):
        path = Path(__file__).resolve().parent.parent / "VERSION"
        assert path.exists()
        v = path.read_text(encoding="utf-8").strip()
        assert v == "1.0.0"
