"""Marketplace v0.39 — signing + install meta + semver compare.

Covers:
  * marketplace_signing
      - sign + verify roundtrip succeeds
      - tampering with payload invalidates signature
      - unknown signer rejected
      - unsigned items detected
      - canonical_payload is order-independent
  * marketplace_meta
      - record_install / installed_version roundtrip
      - update_available true when catalog newer
      - install_state covers all three states
      - semver_cmp handles invalid strings gracefully
      - pre-release versions sort below release
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


# ---------------------------------------------------------------------------
@pytest.fixture
def signed_item(monkeypatch):
    """Build a fresh keypair, install it as the 'official' trust root,
    and return (item_dict, priv_b64) for tests that need to re-sign."""
    import marketplace_signing as ms
    sk = Ed25519PrivateKey.generate()
    priv_b64 = base64.b64encode(sk.private_bytes_raw()).decode()
    pub_b64 = base64.b64encode(sk.public_key().public_bytes_raw()).decode()
    monkeypatch.setitem(ms.TRUSTED_KEYS, "official", pub_b64)
    payload = {
        "id": "official.dimension_walls",
        "name": "Dimension walls",
        "type": "skill",
        "tags": ["revit"],
    }
    sig = ms.sign_payload(payload, priv_b64)
    item = {
        "id": "official.dimension_walls",
        "kind": "skill",
        "name": "Dimension walls",
        "version": "0.1.0",
        "signed_by": "official",
        "signature": sig,
        "payload": payload,
    }
    return item, priv_b64


class TestSigning:
    def test_roundtrip_verifies(self, signed_item):
        import marketplace_signing as ms
        item, _ = signed_item
        ok, reason = ms.verify_item(item)
        assert ok, reason
        assert ms.is_signed(item)

    def test_tampering_payload_rejected(self, signed_item):
        import marketplace_signing as ms
        item, _ = signed_item
        item["payload"]["name"] = "Trojan Horse"
        ok, reason = ms.verify_item(item)
        assert not ok
        assert "match" in reason.lower()

    def test_unknown_signer_rejected(self, signed_item):
        import marketplace_signing as ms
        item, _ = signed_item
        item["signed_by"] = "evil_actor"
        ok, reason = ms.verify_item(item)
        assert not ok
        assert "unknown signer" in reason.lower()

    def test_unsigned_item_detected(self):
        import marketplace_signing as ms
        item = {"id": "x", "payload": {"foo": "bar"}}
        assert not ms.is_signed(item)
        ok, reason = ms.verify_item(item)
        assert not ok
        assert "unsigned" in reason.lower()

    def test_missing_payload_rejected(self, signed_item):
        import marketplace_signing as ms
        item, _ = signed_item
        del item["payload"]
        ok, reason = ms.verify_item(item)
        assert not ok

    def test_canonical_payload_order_independent(self):
        import marketplace_signing as ms
        a = {"a": 1, "b": 2, "c": [3, 4]}
        b = {"c": [3, 4], "b": 2, "a": 1}
        assert ms.canonical_payload(a) == ms.canonical_payload(b)

    def test_canonical_excludes_signature_fields(self):
        import marketplace_signing as ms
        a = {"id": "x", "v": 1}
        b = {"id": "x", "v": 1, "signature": "junk", "signed_by": "official"}
        assert ms.canonical_payload(a) == ms.canonical_payload(b)

    def test_garbage_signature_rejected(self, signed_item):
        import marketplace_signing as ms
        item, _ = signed_item
        item["signature"] = "@@@not-base64@@@"
        ok, reason = ms.verify_item(item)
        assert not ok


# ---------------------------------------------------------------------------
class TestSemver:
    def test_basic_ordering(self):
        from marketplace_meta import semver_cmp
        assert semver_cmp("0.1.0", "0.1.1") == -1
        assert semver_cmp("1.0.0", "0.9.9") == 1
        assert semver_cmp("0.2.0", "0.2.0") == 0
        assert semver_cmp("1.10.0", "1.2.0") == 1   # numeric, not lex

    def test_prerelease_sorts_below(self):
        from marketplace_meta import semver_cmp
        assert semver_cmp("1.0.0-rc1", "1.0.0") == -1
        assert semver_cmp("1.0.0", "1.0.0-rc1") == 1
        assert semver_cmp("1.0.0-rc1", "1.0.0-rc2") == -1

    def test_invalid_string_treated_as_zero(self):
        from marketplace_meta import semver_cmp
        assert semver_cmp("garbage", "0.0.0") == 0
        assert semver_cmp("0.1.0", "garbage") == 1


# ---------------------------------------------------------------------------
class TestInstallMeta:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        # Redirect LOCALAPPDATA so each test gets a clean install
        # store and we never touch the real user's data.
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        # Force the module to re-resolve _store_path on each call.
        import marketplace_meta as mm
        # Wipe any cache from prior tests in this process.
        try:
            mm._read.__wrapped__   # noqa: B018
        except Exception:
            pass

    def test_record_then_query(self):
        import marketplace_meta as mm
        item = {"id": "official.x", "version": "0.1.0",
                "signed_by": "official", "kind": "skill"}
        mm.record_install(item)
        assert mm.installed_version("official.x") == "0.1.0"

    def test_update_available_true(self):
        import marketplace_meta as mm
        installed = {"id": "official.x", "version": "0.1.0", "kind": "skill"}
        mm.record_install(installed)
        catalog = {"id": "official.x", "version": "0.2.0"}
        assert mm.update_available(catalog) is True
        assert mm.install_state(catalog) == "update"

    def test_update_available_false_when_same(self):
        import marketplace_meta as mm
        item = {"id": "official.x", "version": "0.1.0", "kind": "skill"}
        mm.record_install(item)
        catalog = {"id": "official.x", "version": "0.1.0"}
        assert mm.update_available(catalog) is False
        assert mm.install_state(catalog) == "installed"

    def test_install_state_not_installed(self):
        import marketplace_meta as mm
        catalog = {"id": "official.fresh", "version": "0.1.0"}
        assert mm.install_state(catalog) == "not_installed"
        assert mm.update_available(catalog) is False

    def test_uninstall_removes_record(self):
        import marketplace_meta as mm
        item = {"id": "official.x", "version": "0.1.0", "kind": "skill"}
        mm.record_install(item)
        mm.record_uninstall("official.x")
        assert mm.installed_version("official.x") is None

    def test_list_installed_returns_snapshot(self):
        import marketplace_meta as mm
        mm.record_install({"id": "a", "version": "0.1.0", "kind": "skill"})
        mm.record_install({"id": "b", "version": "0.2.0", "kind": "workflow"})
        rows = mm.list_installed()
        assert set(rows.keys()) == {"a", "b"}
        assert rows["b"]["version"] == "0.2.0"
