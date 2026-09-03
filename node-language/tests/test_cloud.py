"""ArchHub Cloud client + auth + usage cache tests.

Backend doesn't exist yet — every HTTP call is mocked. We're testing
the contract the desktop client expects: token roundtrip, PKCE pair
generation, usage-cache decrement semantics, pricing-tier data model.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # secrets_store freezes APP_DIR / SETTINGS_FILE at import time.
    # Override LOCALAPPDATA AND directly patch the frozen paths so
    # this test's read/write goes to tmp_path.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import secrets_store as ss
    app_dir = tmp_path / "ArchHub"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ss, "APP_DIR", app_dir)
    monkeypatch.setattr(ss, "SECRETS_FILE", app_dir / "secrets.dat")
    monkeypatch.setattr(ss, "SETTINGS_FILE", app_dir / "settings.json")


# Realistic-length bearer tokens for tests. A REAL bearer (POST
# /v1/auth/exchange) is always long (32+ chars); cloud_client now refuses to
# persist anything shorter than MIN_TOKEN_LEN (16) as junk. These constants keep
# every test's intent while using lengths a real token would have — distinct
# values where a test needs to tell two tokens apart. (The OLD literals
# "ah_test_123"/"ah_old"/"ah_test"/"ah_forever" were 6–11 chars and now
# correctly fail validation.)
_VALID = "ah_" + "b" * 40          # 43 chars — clearly >= MIN_TOKEN_LEN
_VALID_OLD = "ah_old_" + "c" * 40       # distinct, realistic length
_VALID_FOREVER = "ah_forever_" + "d" * 40   # distinct, realistic length


# ---------------------------------------------------------------------------
class TestTokenStorage:
    def test_initially_signed_out(self):
        import cloud_client as c
        assert c.current_token() is None
        assert c.is_signed_in() is False

    def test_set_token_persists(self):
        import cloud_client as c
        c.set_token(_VALID, expires_at=time.time() + 3600)
        assert c.current_token() == _VALID
        assert c.is_signed_in() is True

    def test_expired_token_returns_none(self):
        import cloud_client as c
        c.set_token(_VALID_OLD, expires_at=time.time() - 10)
        assert c.current_token() is None
        assert c.is_signed_in() is False

    def test_clear_token(self):
        import cloud_client as c
        c.set_token(_VALID, expires_at=time.time() + 3600)
        c.clear_token()
        assert c.current_token() is None

    def test_zero_expiry_means_never_expires(self):
        import cloud_client as c
        c.set_token(_VALID_FOREVER, expires_at=None)
        # current_token() should still return the token when expires_at=0
        assert c.current_token() == _VALID_FOREVER


# ---------------------------------------------------------------------------
class TestPKCE:
    def test_pair_pair_returns_two_strings(self):
        from cloud_auth import _pkce_pair
        verifier, challenge = _pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) >= 40
        assert len(challenge) >= 40

    def test_challenge_is_sha256_of_verifier(self):
        from cloud_auth import _pkce_pair
        verifier, challenge = _pkce_pair()
        # Re-derive the challenge and compare.
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = (base64.urlsafe_b64encode(digest).rstrip(b"=")
                    .decode("ascii"))
        assert challenge == expected

    def test_pair_is_unique_per_call(self):
        from cloud_auth import _pkce_pair
        a = _pkce_pair()
        b = _pkce_pair()
        assert a != b


# ---------------------------------------------------------------------------
class TestUsageCache:
    def setup_method(self):
        import cloud_usage as u
        u.invalidate()

    def test_snapshot_initially_none(self):
        import cloud_usage as u
        assert u.snapshot() is None

    def test_decrement_after_manual_cache_set(self):
        import cloud_usage as u
        # Inject a fake snapshot
        with u._LOCK:
            u._CACHED = {"plan": "solo", "remaining_messages": 500}
            u._FETCHED_AT = time.time()
        u.decrement(1)
        assert u.snapshot()["remaining_messages"] == 499
        u.decrement(5)
        assert u.snapshot()["remaining_messages"] == 494

    def test_decrement_does_not_go_negative(self):
        import cloud_usage as u
        with u._LOCK:
            u._CACHED = {"plan": "trial", "remaining_messages": 2}
            u._FETCHED_AT = time.time()
        u.decrement(10)
        assert u.snapshot()["remaining_messages"] == 0

    def test_invalidate_clears(self):
        import cloud_usage as u
        with u._LOCK:
            u._CACHED = {"plan": "solo", "remaining_messages": 100}
            u._FETCHED_AT = time.time()
        u.invalidate()
        assert u.snapshot() is None

    def test_ttl_expiration(self):
        import cloud_usage as u
        with u._LOCK:
            u._CACHED = {"plan": "solo", "remaining_messages": 100}
            u._FETCHED_AT = time.time() - 120   # 2 min ago, past 60s TTL
        assert u.snapshot() is None


# ---------------------------------------------------------------------------
class TestPricingTiers:
    def test_four_tiers_present(self):
        from pricing_page import TIERS
        ids = {t["id"] for t in TIERS}
        assert ids == {"byo", "solo", "studio", "firm"}

    def test_byo_is_zero_dollars_no_checkout(self):
        from pricing_page import TIERS
        byo = next(t for t in TIERS if t["id"] == "byo")
        assert byo["price"] == "$0"
        assert byo["checkout_tier"] is None

    def test_solo_studio_firm_have_checkout_tiers(self):
        from pricing_page import TIERS
        for tid in ("solo", "studio", "firm"):
            t = next(t for t in TIERS if t["id"] == tid)
            assert t["checkout_tier"] == tid

    def test_studio_is_the_highlighted_primary(self):
        from pricing_page import TIERS
        primaries = [t for t in TIERS if t.get("primary")]
        assert len(primaries) == 1
        assert primaries[0]["id"] == "studio"

    def test_solo_price_is_19(self):
        from pricing_page import TIERS
        solo = next(t for t in TIERS if t["id"] == "solo")
        assert "$19" in solo["price"]

    def test_firm_mentions_self_host(self):
        # Firm tier sells the AGPL self-host grant.
        from pricing_page import TIERS
        firm = next(t for t in TIERS if t["id"] == "firm")
        features_blob = " ".join(firm["features"]).lower()
        assert "self-host" in features_blob


# ---------------------------------------------------------------------------
class TestRouterRegistration:
    """archhub_cloud must appear in configured_providers when a token
    is set, and _get_client must instantiate the right class."""

    def _router(self):
        # LLMRouter requires a ToolEngine; stub one with a fake manager.
        import llm_router as r
        from tool_engine import ToolEngine
        mgr = MagicMock()
        mgr.entries = []
        tools = ToolEngine(mgr)
        return r.LLMRouter(tools)

    def test_cloud_appears_when_signed_in(self):
        import cloud_client as c
        c.set_token(_VALID, expires_at=time.time() + 3600)
        router = self._router()
        providers = router.configured_providers()
        assert "archhub_cloud" in providers

    def test_cloud_absent_when_signed_out(self):
        import cloud_client as c
        c.clear_token()
        router = self._router()
        assert "archhub_cloud" not in router.configured_providers()

    def test_get_client_returns_archhub_cloud_client(self):
        import cloud_client as c
        c.set_token(_VALID, expires_at=time.time() + 3600)
        router = self._router()
        try:
            client = router._get_client("archhub_cloud")
            from llm_providers.archhub_cloud_client import ArchHubCloudClient
            assert isinstance(client, ArchHubCloudClient)
        except RuntimeError as ex:
            assert "openai" in str(ex).lower()


# ---------------------------------------------------------------------------
class TestRequestHelper:
    """_request must surface error envelopes the UI can read."""

    def test_unsigned_request_returns_not_signed_in(self):
        import cloud_client as c
        c.clear_token()
        r = c._request("GET", "/v1/me")
        assert r["status"] == "error"
        assert r["error"] == "not_signed_in"

    def test_unreachable_backend_reports_unreachable(self, monkeypatch):
        import cloud_client as c, urllib.error
        c.set_token(_VALID, expires_at=time.time() + 3600)
        def boom(*a, **kw):
            raise urllib.error.URLError("connection refused")
        monkeypatch.setattr("urllib.request.urlopen", boom)
        r = c._request("GET", "/v1/me")
        assert r["status"] == "error"
        assert r["error"] == "unreachable"
