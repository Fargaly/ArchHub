"""Tests — Track D §5: per-user cloud brain replica + /v1/brain/sync endpoint.

Coverage:
  1. Unauthenticated POST → 401 (no replica created).
  2. Authenticated POST with a delta → 200 + merged delta + new_hlc.
  3. DELETE /v1/brain/sync removes the per-user replica directory.
  4. Two users have fully isolated replicas (no cross-leak).

Privacy: every test that pushes a fragment with a bare `sk-ant-...`
verifies it lands in the `rejected` array (no secrets leak into the
replica db).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def replicas_root(tmp_path, monkeypatch):
    """Point BrainReplica.DEFAULT_REPLICAS_ROOT at a tmp directory.

    Without this every test would scribble under cloud_backend/data/replicas/
    on the dev box."""
    import brain_replica
    root = tmp_path / "replicas"
    root.mkdir()
    monkeypatch.setattr(brain_replica, "DEFAULT_REPLICAS_ROOT", root)
    return root


@pytest.fixture
def client(replicas_root):
    import main
    with TestClient(main.app) as c:
        yield c


def _signed_in_user(suffix: str = "") -> tuple[dict, dict]:
    import db
    email = f"brain+{suffix or uuid.uuid4().hex[:6]}@example.com"
    u = db.get_or_create_user(email)
    token = db.issue_token(u["id"])
    return u, {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestBrainSyncAuth:
    def test_unauthenticated_post_returns_401(self, client):
        r = client.post("/v1/brain/sync",
                        json={"delta": {"fragments": []}})
        assert r.status_code == 401

    def test_bearer_garbage_returns_401(self, client):
        r = client.post(
            "/v1/brain/sync",
            json={"delta": {"fragments": []}},
            headers={"Authorization": "Bearer notarealtoken"},
        )
        assert r.status_code == 401


class TestBrainSyncMerge:
    def test_valid_call_returns_merged_delta_and_hlc(self, client):
        _, h = _signed_in_user("merge1")
        body = {
            "since_hlc": "",
            "delta": {
                "fragments": [
                    {"id": "frag-001", "kind": "fact",
                     "text": "Project ACME uses Revit 2025.",
                     "subject": "ACME", "predicate": "uses",
                     "object": "Revit 2025",
                     "hlc": "0000000000000001.aaaaaaaa"},
                ],
                "wiring": [
                    {"name": "revit", "device_id": "dev-A",
                     "kind": "mcp", "endpoint": "http://localhost:48884"},
                ],
            },
        }
        r = client.post("/v1/brain/sync", json=body, headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["accepted"] == 1
        assert j["rejected"] == []
        assert j["new_hlc"], "HLC must be issued"
        # Round-trip — merged payload contains the fragment we just sent.
        ids = [f["id"] for f in j["merged"]["fragments"]]
        assert "frag-001" in ids
        # Wiring round-trips too.
        names = [w["name"] for w in j["merged"]["wiring"]]
        assert "revit" in names

    def test_bare_secret_is_rejected_not_persisted(self, client):
        """The BRAIN-FIRST privacy contract: bare credentials are blocked."""
        _, h = _signed_in_user("secret1")
        body = {
            "delta": {
                "fragments": [
                    {"id": "good-ref", "kind": "fact",
                     "text": "Anthropic key reference",
                     "object": "op://vault/anthropic/key",
                     "hlc": "0000000000000001.bbbbbbbb"},
                    {"id": "bad-leak", "kind": "fact",
                     "text": "leaked",
                     "object": "sk-ant-1234567890abcdef",
                     "hlc": "0000000000000002.cccccccc"},
                    {"id": "bad-aws", "kind": "fact",
                     "text": "AKIAIOSFODNN7EXAMPLE",
                     "hlc": "0000000000000003.dddddddd"},
                ],
            },
        }
        r = client.post("/v1/brain/sync", json=body, headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        # Reference fragment accepted; both bare secrets rejected.
        assert j["accepted"] == 1
        rejected_ids = {x["id"] for x in j["rejected"]}
        assert "bad-leak" in rejected_ids
        assert "bad-aws" in rejected_ids
        # Reasons cite secret_blocked so the desktop client can surface it.
        assert all("secret_blocked" in x["reason"] for x in j["rejected"])
        # And nothing under the bad ids made it into the merged export.
        merged_ids = {f["id"] for f in j["merged"]["fragments"]}
        assert "bad-leak" not in merged_ids
        assert "bad-aws" not in merged_ids
        assert "good-ref" in merged_ids


class TestGDPRDelete:
    def test_delete_endpoint_removes_replica(self, client, replicas_root):
        u, h = _signed_in_user("gdpr1")
        # Push one fragment so the replica directory definitely exists.
        client.post(
            "/v1/brain/sync",
            json={"delta": {"fragments": [
                {"id": "frag-gdpr", "kind": "fact",
                 "text": "to-be-forgotten",
                 "hlc": "0000000000000001.aaaaaaaa"},
            ]}},
            headers=h,
        )
        user_dir = replicas_root / u["id"]
        assert user_dir.exists(), "replica should exist after sync"
        # GDPR erasure.
        r = client.delete("/v1/brain/sync", headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["deleted"] is True
        assert j["user_id"] == u["id"]
        assert not user_dir.exists(), "replica directory should be gone"

    def test_delete_when_no_replica_returns_false(self, client):
        _, h = _signed_in_user("gdpr2")
        # No prior sync — directory never created. Delete is idempotent.
        r = client.delete("/v1/brain/sync", headers=h)
        assert r.status_code == 200
        assert r.json()["deleted"] is False


class TestPerUserIsolation:
    def test_two_users_have_isolated_replicas(self, client, replicas_root):
        ua, ha = _signed_in_user("iso-A")
        ub, hb = _signed_in_user("iso-B")
        # User A pushes their fragment.
        client.post(
            "/v1/brain/sync",
            json={"delta": {"fragments": [
                {"id": "A-only", "kind": "fact",
                 "text": "Studio A confidential",
                 "hlc": "0000000000000001.aaaaaaaa"},
            ]}},
            headers=ha,
        )
        # User B pushes a different fragment.
        client.post(
            "/v1/brain/sync",
            json={"delta": {"fragments": [
                {"id": "B-only", "kind": "fact",
                 "text": "Firm B confidential",
                 "hlc": "0000000000000001.bbbbbbbb"},
            ]}},
            headers=hb,
        )
        # User A reads back — must NOT see B's fragment.
        ra = client.post("/v1/brain/sync",
                         json={"delta": {"fragments": []}},
                         headers=ha).json()
        a_ids = {f["id"] for f in ra["merged"]["fragments"]}
        assert "A-only" in a_ids
        assert "B-only" not in a_ids
        # And vice-versa.
        rb = client.post("/v1/brain/sync",
                         json={"delta": {"fragments": []}},
                         headers=hb).json()
        b_ids = {f["id"] for f in rb["merged"]["fragments"]}
        assert "B-only" in b_ids
        assert "A-only" not in b_ids
        # Filesystem proof: two separate directories.
        assert (replicas_root / ua["id"]).exists()
        assert (replicas_root / ub["id"]).exists()
        assert ua["id"] != ub["id"]
