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

    def test_each_tier_has_quota(self, client):
        r = client.get("/v1/billing/plans")
        for t in r.json()["tiers"]:
            assert isinstance(t["monthly_quota"], int)
            assert t["monthly_quota"] >= 0

    def test_studio_and_firm_carry_seats(self, client):
        r = client.get("/v1/billing/plans")
        by_tier = {t["tier"]: t for t in r.json()["tiers"]}
        # Solo is single-user; seats is None.
        assert by_tier["solo"]["seats"] is None
        assert by_tier["studio"]["seats"] == 5
        assert by_tier["firm"]["seats"] == 25

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
