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
    # Floor = the last release whose exact value this test once pinned.
    # VERSION may move forward past it, never back below it.
    _MIN_STABLE = (1, 4, 1)

    def test_version_file_is_one_zero(self, qapp):
        """Release-discipline guard for the VERSION file.

        ROOT-CAUSE NOTE (2026-06-18): this assertion used to be a frozen
        literal — `assert v == "1.4.1"`. Every release that bumped VERSION
        but forgot to also edit this line turned the WHOLE cross-platform
        matrix red on an unrelated PR (it broke at 1.4.0→1.4.1, then again
        at 1.4.1→1.5.0 when the v1.5.0 finalization release landed on main
        without touching this test). A version pin that has to be hand-edited
        in lock-step with every release is a recurring-breakage class, not a
        guard. Per the ENGINEERING mandate we fix the MECHANISM: assert the
        invariants the test actually cares about — VERSION is a well-formed
        STABLE semver, it never regresses below the last pinned floor, and it
        matches what the running app serves — so it tracks real releases
        instead of rotting on each one. (Method name kept for back-compat.)
        """
        path = Path(__file__).resolve().parent.parent / "VERSION"
        assert path.exists(), "VERSION file is missing"
        v = path.read_text(encoding="utf-8").strip()
        assert v, "VERSION file is empty"

        # 1) Well-formed STABLE semver MAJOR.MINOR.PATCH — no pre-release /
        #    alpha / build suffix. A stable release ships a clean triple
        #    (the get_version fallback '1.4.0-alpha' must never be committed).
        parts = v.split(".")
        assert len(parts) == 3 and all(p.isdigit() for p in parts), (
            f"VERSION must be a stable MAJOR.MINOR.PATCH semver, got {v!r}"
        )
        ver = tuple(int(p) for p in parts)

        # 2) Forward-only: the released version never regresses below the
        #    floor this test historically guarded.
        assert ver >= self._MIN_STABLE, (
            f"VERSION {v} regressed below the {'.'.join(map(str, self._MIN_STABLE))} floor"
        )

        # 3) Internal consistency: the value the running app reports
        #    (ArchHubBridge.get_version → the same VERSION file) matches the
        #    file on disk. This is the invariant that actually matters — it
        #    catches VERSION drifting away from what users see in-app, which
        #    a frozen literal never could. (qapp ensures a QApplication for
        #    the QObject-derived bridge.)
        from bridge import ArchHubBridge
        # defer_boot/auto_extract_memory off → no disk-scan daemon thread,
        # no memory side effects; we only need the version slot.
        served = ArchHubBridge(
            tools=None, auto_extract_memory=False, defer_boot=False
        ).get_version()
        assert served == v, (
            f"app get_version() ({served!r}) disagrees with VERSION file ({v!r})"
        )
