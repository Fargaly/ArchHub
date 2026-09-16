"""The offer gate: the cloud relays the offer, it never authors one.

S1 GET /v1/offer serves the offer record from the founder map push and fails
CLOSED with no push or a malformed record. S2 while pricing is hidden the plan
catalogue is empty and checkout is refused. S3 both founder addresses own the
cockpit. S4 the subscriptions panel carries no price source while pricing is
hidden. Plus the map push timestamp, so a stale map is never labelled live.

The record shape is the one the desktop publishes (13.NODE-LANGUAGE
nodelang/cloud_relay.py OFFER_KEYS): revision, sha256, availability,
pricing_visible, public_label.

This tree is the deployed cloud source and is retirement-bound until the
cockpit/brain port into the canonical project.

Run: python -m pytest cloud_backend/tests/test_offer_gate.py -q
"""
from __future__ import annotations

import hashlib
import json
import time

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def map_files(tmp_path, monkeypatch):
    """Point the offer/map files at a per-test dir, so no test reads the
    dev box's real founder-map.json."""
    import config
    import founder_cockpit
    body = tmp_path / "founder-map.json"
    stamp = tmp_path / "founder-map.pushed-at.json"
    monkeypatch.setattr(config, "FOUNDER_MAP_STATE", body)
    monkeypatch.setattr(config, "FOUNDER_MAP_PUSHED_AT", stamp)
    monkeypatch.setattr(founder_cockpit, "_MAP_STATE", body)
    monkeypatch.delenv("FOUNDER_EMAIL", raising=False)
    monkeypatch.delenv("FOUNDER_EMAILS", raising=False)
    return {"body": body, "stamp": stamp}


def _offer(availability: str, pricing_visible: bool, label: str) -> dict:
    """One offer record in exactly the published form."""
    return {
        "revision": 7,
        "sha256": hashlib.sha256(label.encode("utf-8")).hexdigest(),
        "availability": availability,
        "pricing_visible": pricing_visible,
        "public_label": label,
    }


BETA = _offer("free-during-beta", False, "Free during beta")
PAID = _offer("paid", True, "Paid plans")


def _auth(email: str) -> dict:
    import db
    user = db.get_or_create_user(email)
    return {"Authorization": "Bearer " + db.issue_token(user["id"])}


def _publish(client, offer):
    """Publish a map through the real founder route."""
    payload = {"nodes": []}
    if offer is not None:
        payload["offer"] = offer
    r = client.post("/founder/map-state",
                    headers=_auth("ahmed.fargaly98@gmail.com"), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestOfferFailsClosed:
    def test_no_push_means_closed_and_pricing_hidden(self, client):
        r = client.get("/v1/offer")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "closed"
        assert body["availability"] is None
        assert body["public_label"] is None
        assert body["pricing_visible"] is False
        assert body["published_at"] is None

    def test_a_map_without_an_offer_is_still_closed(self, client):
        _publish(client, None)
        assert client.get("/v1/offer").json()["state"] == "closed"

    def test_a_malformed_offer_is_closed_not_crashed(self, client, map_files):
        map_files["body"].write_text(json.dumps({"offer": "free!"}),
                                      encoding="utf-8")
        body = client.get("/v1/offer").json()
        assert body["state"] == "closed" and body["pricing_visible"] is False

    @pytest.mark.parametrize("missing", ["revision", "sha256", "availability",
                                         "pricing_visible", "public_label"])
    def test_a_record_missing_any_published_key_is_closed(self, client, missing):
        partial = dict(PAID)
        del partial[missing]
        _publish(client, partial)
        body = client.get("/v1/offer").json()
        assert body["state"] == "closed"
        assert body["pricing_visible"] is False

    def test_a_string_pricing_flag_does_not_open_pricing(self, client):
        wrong = dict(PAID, pricing_visible="true")
        _publish(client, wrong)
        assert client.get("/v1/offer").json()["pricing_visible"] is False

    def test_the_offer_is_relayed_verbatim(self, client):
        _publish(client, BETA)
        body = client.get("/v1/offer").json()
        assert body["state"] == "open"
        assert body["availability"] == "free-during-beta"
        assert body["public_label"] == "Free during beta"
        assert body["revision"] == 7
        assert body["sha256"] == BETA["sha256"]
        assert body["source"] == "founder-map"


class TestPricingHiddenDuringBeta:
    def test_plans_are_empty_and_carry_no_price(self, client):
        _publish(client, BETA)
        plans = client.get("/v1/billing/plans").json()
        assert plans["tiers"] == []
        assert plans["credit_pack"] is None
        assert plans["pricing_visible"] is False

    def test_checkout_is_refused_by_the_same_gate(self, client):
        _publish(client, BETA)
        r = client.post("/v1/billing/checkout",
                        headers=_auth("buyer@example.com"),
                        json={"tier": "solo"})
        assert r.status_code == 403
        assert r.json()["detail"] == "checkout_closed"

    def test_the_billing_helpers_refuse_too(self, client):
        """The gate lives in billing as well, so no other caller can open a
        session while the offer is closed."""
        import billing
        import db
        _publish(client, BETA)
        user = db.get_or_create_user("buyer2@example.com")
        assert billing.create_checkout_url(user=user, tier="solo") is None
        assert billing.create_credit_pack_checkout(user_id=user["id"]) is None

    def test_pricing_opens_only_when_the_record_says_so(self, client):
        _publish(client, PAID)
        plans = client.get("/v1/billing/plans").json()
        assert plans["pricing_visible"] is True
        assert len(plans["tiers"]) > 0
        r = client.post("/v1/billing/checkout",
                        headers=_auth("buyer3@example.com"),
                        json={"tier": "solo"})
        # The provider is unconfigured in tests; the point is the gate is open.
        assert r.status_code != 403


class TestSubscriptionsPanelHasNoPriceSource:
    def test_counts_only_while_pricing_is_hidden(self, client):
        import founder_cockpit
        _publish(client, BETA)
        panel = founder_cockpit._subscriptions_panel()
        assert panel["mrr_estimate"] is None
        assert panel["arr_estimate"] is None
        assert panel["basis"] == "counts_only_pricing_hidden"
        for tier in panel["tiers"]:
            assert "price_per_seat" not in tier and "mrr" not in tier
        assert isinstance(panel["paying_subscribers"], int)

    def test_the_estimate_returns_when_the_offer_opens(self, client):
        import founder_cockpit
        _publish(client, PAID)
        panel = founder_cockpit._subscriptions_panel()
        assert panel["basis"] == "derived_from_stored_plans"
        assert panel["mrr_estimate"] is not None


class TestMapPushTimestamp:
    def test_the_push_records_when_it_arrived(self, client, map_files):
        result = _publish(client, BETA)
        assert "pushed_at" in result
        stamp = json.loads(map_files["stamp"].read_text(encoding="utf-8"))
        assert stamp["pushed_at"] == result["pushed_at"]
        assert abs(time.time() - stamp["epoch"]) < 120

    def test_a_fresh_map_is_served_live(self, client):
        _publish(client, None)
        asset = client.get("/founder/map-assets/map-data.js",
                           headers=_auth("ahmed.fargaly98@gmail.com")).text
        assert "window.ATLAS_MAP_PUSHED_AT = " in asset
        assert "window.ATLAS_LIVE = true;" in asset

    def test_a_stale_map_is_served_but_never_labelled_live(self, client, map_files):
        """The founder still sees the real graph; he is just never told an
        hour-old map is live."""
        _publish(client, None)
        stamp = json.loads(map_files["stamp"].read_text(encoding="utf-8"))
        stamp["epoch"] = int(time.time()) - 4000
        map_files["stamp"].write_text(json.dumps(stamp), encoding="utf-8")
        asset = client.get("/founder/map-assets/map-data.js",
                           headers=_auth("ahmed.fargaly98@gmail.com")).text
        assert "window.ATLAS_LIVE = false;" in asset
        assert "window.ATLAS_MAP = " in asset

    def test_an_unknown_push_time_is_not_live(self, client, map_files):
        _publish(client, None)
        map_files["stamp"].unlink()
        asset = client.get("/founder/map-assets/map-data.js",
                           headers=_auth("ahmed.fargaly98@gmail.com")).text
        assert "window.ATLAS_LIVE = false;" in asset
        assert "window.ATLAS_MAP_PUSHED_AT = null" in asset


class TestBothFounderAddressesOwnTheCockpit:
    """The desktop signs in with one address and the cloud account was made
    with the other; a gate that knows only one locks the founder out."""

    @pytest.mark.parametrize("email", ["ahmed.fargaly98@gmail.com",
                                       "ahmedfargale@gmail.com"])
    def test_either_founder_address_may_push(self, client, email):
        r = client.post("/founder/map-state", headers=_auth(email),
                        json={"nodes": []})
        assert r.status_code == 200, r.text

    def test_a_third_address_is_refused(self, client):
        r = client.post("/founder/map-state",
                        headers=_auth("someone.else@example.com"),
                        json={"nodes": []})
        assert r.status_code == 403
        assert r.json()["detail"] == "founder_only"

    def test_the_env_overrides_win(self, monkeypatch):
        import config
        monkeypatch.setenv("FOUNDER_EMAIL", "solo@x.com")
        assert config.founder_emails() == frozenset({"solo@x.com"})
        monkeypatch.setenv("FOUNDER_EMAILS", " A@x.com , b@Y.com ")
        assert config.founder_emails() == frozenset({"a@x.com", "b@y.com"})

    def test_purge_protection_covers_both_addresses(self):
        import db
        protected = db._protected_emails()
        assert "ahmed.fargaly98@gmail.com" in protected
        assert "ahmedfargale@gmail.com" in protected
