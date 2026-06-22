"""Tests — Slice 3 cloud brain PORTAL: the owner-only, tier-gated READ +
SEARCH surface over the per-user replica that /v1/brain/sync writes.

These pin the genuine new contract (the write-only /v1/brain/sync had no read
path before):
  1. GET /v1/brain/facts returns the caller's OWN synced facts, kind='fact'.
  2. Per-user isolation: user B can NEVER read user A's USER-scope facts
     (owner-only — the same contract TestPerUserIsolation pins for sync).
  3. Tier cap enforcement: a trial caller's `limit` is clamped to the
     config.BRAIN_FACT_CAPS['trial'] ceiling (real, not cosmetic).
  4. Search gating: trial → typed 402 upgrade_required; paid → results.
  5. Search filtering: a query returns only matching facts, scored.
  6. Stats: total + per-scope counts + last-sync watermark; honest zeros
     for a user who never synced.
  7. /v1/me still returns plan/remaining (the badge source) — unchanged.

They read THROUGH the live FastAPI routes (TestClient) against the real
BrainReplica, so the endpoint wiring (owner forcing, tier gate, replica
read) is exercised end-to-end — not just the primitive.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def client():
    import main
    with TestClient(main.app) as c:
        yield c


def _user(plan: str = "trial") -> tuple[dict, dict]:
    import db
    email = f"portal+{uuid.uuid4().hex[:8]}@example.com"
    u = db.get_or_create_user(email)
    if plan != "trial":
        db.update_user_plan(u["id"], plan=plan)
        u = db.get_or_create_user(email)  # refresh plan
    token = db.issue_token(u["id"])
    return u, {"Authorization": f"Bearer {token}"}


def _seed(user_id: str, frags: list[dict]) -> None:
    """Write fact fragments straight into the user's replica via apply_delta —
    the SAME path /v1/brain/sync uses."""
    import brain_replica
    replica = brain_replica.BrainReplica.open(user_id=user_id)
    replica.apply_delta({"fragments": frags})


def _frag(fid, text, hlc, scope="user", **extra):
    f = {"id": fid, "kind": "fact", "text": text, "scope": scope, "hlc": hlc}
    f.update(extra)
    return f


# ===========================================================================
# 1. facts: caller reads their OWN synced facts
# ===========================================================================
def test_facts_returns_own_synced_facts(client):
    u, H = _user("solo")
    _seed(u["id"], [
        _frag("f1", "uses Revit 2025", "0000000000000001.00000000"),
        _frag("f2", "prefers terracotta accent", "0000000000000002.00000000"),
    ])
    r = client.get("/v1/brain/facts", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    texts = {f["text"] for f in body["results"]}
    assert texts == {"uses Revit 2025", "prefers terracotta accent"}
    assert body["count"] == 2
    assert body["plan"] == "solo"


# ===========================================================================
# 2. owner-only isolation: B cannot read A's USER facts
# ===========================================================================
def test_user_facts_are_owner_only(client):
    a, Ha = _user("solo")
    b, Hb = _user("solo")
    _seed(a["id"], [_frag("a1", "A private fact", "0000000000000001.00000000")])
    # A sees it
    ra = client.get("/v1/brain/facts", headers=Ha).json()
    assert any(f["text"] == "A private fact" for f in ra["results"])
    # B does NOT (separate replica, owner-forced)
    rb = client.get("/v1/brain/facts", headers=Hb).json()
    assert rb["count"] == 0
    assert all(f["text"] != "A private fact" for f in rb["results"])


# ===========================================================================
# 3. tier cap enforcement (trial clamps limit)
# ===========================================================================
def test_trial_fact_cap_enforced(client, monkeypatch):
    import config
    monkeypatch.setitem(config.BRAIN_FACT_CAPS, "trial", 3)
    u, H = _user("trial")
    _seed(u["id"], [
        _frag(f"t{i}", f"fact {i}", f"00000000000000{i:02d}.00000000")
        for i in range(10)
    ])
    # ask for 50 but trial cap is 3
    r = client.get("/v1/brain/facts?limit=50", headers=H).json()
    assert r["count"] == 3
    assert r["cap"] == 3
    assert r["capped"] is True


def test_paid_gets_higher_cap(client, monkeypatch):
    import config
    monkeypatch.setitem(config.BRAIN_FACT_CAPS, "trial", 3)
    monkeypatch.setitem(config.BRAIN_FACT_CAPS, "studio", 100)
    u, H = _user("studio")
    # HLCs start at 1 (studio unions shared scopes via export_delta, which is
    # hlc > since=zero — an hlc OF zero would be excluded, like a no-op delta).
    _seed(u["id"], [
        _frag(f"s{i}", f"fact {i}", f"00000000000000{i+1:02d}.00000000")
        for i in range(10)
    ])
    r = client.get("/v1/brain/facts?limit=50", headers=H).json()
    assert r["count"] == 10  # all 10 (under the 100 cap)
    assert r["cap"] == 100


# ===========================================================================
# 4. search gating: trial denied (402), paid allowed
# ===========================================================================
def test_search_denied_for_trial(client):
    u, H = _user("trial")
    _seed(u["id"], [_frag("f1", "uses Revit", "0000000000000001.00000000")])
    r = client.get("/v1/brain/search?q=revit", headers=H)
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "upgrade_required"


def test_search_allowed_for_paid(client):
    u, H = _user("solo")
    _seed(u["id"], [
        _frag("f1", "uses Revit 2025", "0000000000000001.00000000"),
        _frag("f2", "prefers AutoCAD", "0000000000000002.00000000"),
    ])
    r = client.get("/v1/brain/search?q=revit", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["results"][0]["text"] == "uses Revit 2025"


# ===========================================================================
# 5. search filtering / scoring
# ===========================================================================
def test_search_filters_and_is_owner_only(client):
    a, Ha = _user("studio")
    b, Hb = _user("studio")
    _seed(a["id"], [
        _frag("a1", "A uses Revit", "0000000000000001.00000000"),
        _frag("a2", "A uses Rhino", "0000000000000002.00000000"),
    ])
    _seed(b["id"], [_frag("b1", "B uses Revit", "0000000000000003.00000000")])
    # A searching 'revit' gets only A's revit fact, never B's
    ra = client.get("/v1/brain/search?q=revit", headers=Ha).json()
    assert ra["count"] == 1
    assert ra["results"][0]["text"] == "A uses Revit"


# ===========================================================================
# 6. stats: counts + honest empty state
# ===========================================================================
def test_stats_counts_and_scopes(client):
    u, H = _user("solo")
    _seed(u["id"], [
        _frag("f1", "user fact", "0000000000000001.00000000", scope="user"),
        _frag("f2", "proj fact", "0000000000000002.00000000",
              scope="project", project_id="p1"),
    ])
    r = client.get("/v1/brain/stats", headers=H).json()
    assert r["total_facts"] == 2
    assert r["by_scope"].get("user") == 1
    assert r["by_scope"].get("project") == 1
    assert r["ever_synced"] is True
    assert r["caps"]["can_search"] is True  # solo


def test_stats_honest_empty_state_when_never_synced(client):
    u, H = _user("trial")
    r = client.get("/v1/brain/stats", headers=H).json()
    assert r["total_facts"] == 0
    assert r["by_scope"] == {}
    assert r["ever_synced"] is False
    assert r["caps"]["can_search"] is False  # trial


def test_facts_empty_state_when_never_synced(client):
    u, H = _user("trial")
    r = client.get("/v1/brain/facts", headers=H).json()
    assert r["count"] == 0
    assert r["results"] == []


# ===========================================================================
# 7. auth required (no token → 401)
# ===========================================================================
def test_facts_requires_auth(client):
    assert client.get("/v1/brain/facts").status_code == 401
    assert client.get("/v1/brain/search?q=x").status_code == 401
    assert client.get("/v1/brain/stats").status_code == 401


# ===========================================================================
# 8. /brain portal page serves HTML (the self-contained portal)
# ===========================================================================
def test_brain_portal_page_serves_html(client):
    r = client.get("/brain")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Your ArchHub brain" in r.text
    # mirrors /dashboard's PKCE flow (same auth, no parallel system)
    assert "/v1/auth/register" in r.text
    assert "/v1/auth/exchange" in r.text
    # reads the new endpoints
    assert "/v1/brain/stats" in r.text
    assert "/v1/brain/facts" in r.text


# ===========================================================================
# 9. /v1/me still carries the plan badge source (unchanged)
# ===========================================================================
def test_me_returns_plan(client):
    u, H = _user("studio")
    me = client.get("/v1/me", headers=H).json()
    assert me["plan"] == "studio"
    assert "remaining_messages" in me
