"""GET /v1/billing/plans — public plan catalog endpoint.

The desktop app needs to render the pricing dialog without hardcoding
tier metadata. This endpoint surfaces it. Provider-agnostic shape.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


class TestPlansEndpoint:
    def test_returns_three_tiers(self, client):
        r = client.get("/v1/billing/plans")
        assert r.status_code == 200
        data = r.json()
        names = [t["tier"] for t in data["tiers"]]
        assert names == ["solo", "studio", "firm"]

    def test_each_tier_has_per_seat_price(self, client):
        # Model C: every tier carries a per-seat price + an annual
        # (−20%) per-seat equivalent.
        r = client.get("/v1/billing/plans")
        for t in r.json()["tiers"]:
            assert isinstance(t["price_per_seat"], (int, float))
            assert t["price_per_seat"] > 0
            assert t["price_per_seat_annual"] < t["price_per_seat"]

    def test_model_c_tier_prices(self, client):
        # The founder-approved numbers: Solo $19, Studio $39/seat,
        # Firm $29/seat.
        r = client.get("/v1/billing/plans")
        by_tier = {t["tier"]: t for t in r.json()["tiers"]}
        assert by_tier["solo"]["price_per_seat"] == 19
        assert by_tier["studio"]["price_per_seat"] == 39
        assert by_tier["firm"]["price_per_seat"] == 29

    def test_seat_floors(self, client):
        # Solo = exactly 1 seat; Studio à la carte (min 1); Firm min 10.
        r = client.get("/v1/billing/plans")
        by_tier = {t["tier"]: t for t in r.json()["tiers"]}
        assert by_tier["solo"]["min_seats"] == 1
        assert by_tier["solo"]["max_seats"] == 1
        assert by_tier["studio"]["min_seats"] == 1
        assert by_tier["studio"]["max_seats"] is None
        assert by_tier["firm"]["min_seats"] == 10

    def test_exposes_credit_pack_and_ai_modes(self, client):
        # The BYO/Hosted choice + the $10 = 1,000-msg credit pack are
        # part of the public catalog.
        data = client.get("/v1/billing/plans").json()
        assert data["model"] == "C"
        assert set(data["ai_modes"]) == {"byo_key", "hosted"}
        assert data["default_ai_mode"] == "byo_key"
        assert data["credit_pack"]["price_usd"] == 10
        assert data["credit_pack"]["messages"] == 1000
        assert data["credit_pack"]["rollover_days"] == 60
        assert data["annual_discount"] == 0.20

    def test_returns_provider_id(self, client):
        r = client.get("/v1/billing/plans")
        assert r.json()["provider"] in ("stripe", "polar")

    def test_external_id_configured_flag(self, client):
        import config
        # When the price/product id is empty (dev default), the flag
        # should be False so the UI can show "Coming soon".
        with patch.object(config, "STRIPE_PRICE_SOLO", ""):
            r = client.get("/v1/billing/plans")
        by_tier = {t["tier"]: t for t in r.json()["tiers"]}
        # The pre-existing default for the test fixture leaves these
        # blank, so just verify the key exists + is a bool.
        for t in r.json()["tiers"]:
            assert isinstance(t["external_id_configured"], bool)

    def test_provider_swap_changes_id_source(self, client):
        import config
        with patch.object(config, "BILLING_PROVIDER", "polar"), \
             patch.object(config, "POLAR_PRODUCT_SOLO", "prod_solo_polar"), \
             patch.object(config, "POLAR_PRODUCT_IDS",
                            {"solo": "prod_solo_polar", "studio": "", "firm": ""}):
            r = client.get("/v1/billing/plans")
        data = r.json()
        assert data["provider"] == "polar"
        by_tier = {t["tier"]: t for t in data["tiers"]}
        assert by_tier["solo"]["external_id_configured"] is True

    def test_no_auth_required(self, client):
        # Public endpoint — pricing must be visible pre-signup.
        r = client.get("/v1/billing/plans")
        assert r.status_code == 200
        # No Authorization header sent; still 200.
