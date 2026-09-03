"""Memory / training-samples pipeline — v1.3.3.

The Memory page in the desktop client posts approved chat turns to
`POST /v1/memory/capture`; the right-column pipeline pills read from
`GET /v1/memory/stats`. These tests pin both endpoints + the DAO
beneath them.

Stages a sample moves through:
  captured -> redacted -> judged -> approved (or rejected)

The redact + judge worker jobs live in agents/; here we only test
that the server-side DB ops advance the stage correctly.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


def _signed_in_user(email_suffix: str = "") -> tuple[dict, dict]:
    """Create a fresh user + return (user, auth_headers)."""
    import db
    email = f"mem+{email_suffix or uuid.uuid4().hex[:6]}@example.com"
    u = db.get_or_create_user(email)
    token = db.issue_token(u["id"])
    return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    """FastAPI test client. Schema is auto-applied via startup event."""
    import main
    with TestClient(main.app) as c:
        yield c


class TestCaptureDAO:
    def test_insert_training_sample_returns_id(self):
        import db
        u, _ = _signed_in_user("dao1")
        sid = db.insert_training_sample(
            user_id=u["id"],
            role="user",
            content="Dimension every wall on Level 3.",
        )
        assert isinstance(sid, int)
        assert sid > 0

    def test_inserted_row_is_in_captured_stage(self):
        import db
        u, _ = _signed_in_user("dao2")
        sid = db.insert_training_sample(
            user_id=u["id"],
            role="assistant",
            content="I placed 12 dimensions.",
        )
        row = db.get_training_sample(sid)
        assert row is not None
        assert row["stage"] == "captured"
        assert row["role"] == "assistant"
        assert row["judge_score"] is None

    def test_tool_trace_serializes_to_json(self):
        import db, json
        u, _ = _signed_in_user("dao3")
        trace = [
            {"name": "revit_get_selection", "args": {}, "result": {"count": 12}},
            {"name": "revit_dimension",     "args": {"ids": [1, 2, 3]},
             "result": {"placed": 3}},
        ]
        sid = db.insert_training_sample(
            user_id=u["id"], role="tool", content="trace",
            tool_trace=trace,
        )
        row = db.get_training_sample(sid)
        # Stored as JSON text — round-trip parse should match input.
        assert json.loads(row["tool_trace"]) == trace

    def test_advance_to_redacted_stamps_redacted_at(self):
        import db
        u, _ = _signed_in_user("dao4")
        sid = db.insert_training_sample(
            user_id=u["id"], role="user", content="…")
        db.advance_training_sample(sid, stage="redacted")
        row = db.get_training_sample(sid)
        assert row["stage"] == "redacted"
        assert row["redacted_at"] is not None
        assert row["judged_at"] is None

    def test_advance_to_judged_records_score(self):
        import db
        u, _ = _signed_in_user("dao5")
        sid = db.insert_training_sample(
            user_id=u["id"], role="assistant", content="ok")
        db.advance_training_sample(sid, stage="judged", judge_score=0.87)
        row = db.get_training_sample(sid)
        assert row["stage"] == "judged"
        assert row["judge_score"] == pytest.approx(0.87)
        assert row["judged_at"] is not None


class TestMemoryStats:
    def test_empty_stats_for_new_user(self):
        import db
        u, _ = _signed_in_user("stats1")
        s = db.memory_stats(user_id=u["id"])
        assert s["capture_today"] == 0
        assert s["redact_clean"] == 0
        assert s["judge_queued"] == 0
        assert s["approved"] == 0
        assert s["train_ready"] is False
        assert s["threshold"] >= 1   # default 100

    def test_capture_today_counts_recent_inserts(self):
        import db
        u, _ = _signed_in_user("stats2")
        for _ in range(3):
            db.insert_training_sample(
                user_id=u["id"], role="user", content="x")
        s = db.memory_stats(user_id=u["id"])
        assert s["capture_today"] == 3
        # All three are in `captured` stage, not redacted/judged/approved.
        assert s["redact_clean"] == 0
        assert s["judge_queued"] == 0
        assert s["approved"] == 0

    def test_stats_segregate_by_stage(self):
        import db
        u, _ = _signed_in_user("stats3")
        ids = [
            db.insert_training_sample(user_id=u["id"], role="user", content=str(i))
            for i in range(4)
        ]
        db.advance_training_sample(ids[0], stage="redacted")
        db.advance_training_sample(ids[1], stage="judged",
                                    judge_score=0.9)
        db.advance_training_sample(ids[2], stage="approved",
                                    judge_score=0.95)
        # ids[3] stays captured.
        s = db.memory_stats(user_id=u["id"])
        assert s["redact_clean"] == 1
        assert s["judge_queued"] == 1
        assert s["approved"] == 1
        # capture_today counts ALL today regardless of stage.
        assert s["capture_today"] == 4

    def test_stats_isolated_per_user(self):
        import db
        u1, _ = _signed_in_user("stats4a")
        u2, _ = _signed_in_user("stats4b")
        db.insert_training_sample(user_id=u1["id"],
                                   role="user", content="alpha")
        db.insert_training_sample(user_id=u1["id"],
                                   role="user", content="beta")
        s1 = db.memory_stats(user_id=u1["id"])
        s2 = db.memory_stats(user_id=u2["id"])
        assert s1["capture_today"] == 2
        assert s2["capture_today"] == 0

    def test_train_ready_flips_at_threshold(self):
        import db, config
        # Bypass insert: directly mark TRAIN_READY_THRESHOLD samples
        # as approved. Threshold defaults to 100; using monkeypatch
        # to drop it would change global config — instead we insert
        # the configured count.
        u, _ = _signed_in_user("stats5")
        # Use a small threshold to keep the test fast.
        original = config.TRAIN_READY_THRESHOLD
        config.TRAIN_READY_THRESHOLD = 3
        try:
            for _ in range(3):
                sid = db.insert_training_sample(
                    user_id=u["id"], role="user", content="approved")
                db.advance_training_sample(sid, stage="approved",
                                            judge_score=1.0)
            s = db.memory_stats(user_id=u["id"])
            assert s["approved"] == 3
            assert s["train_ready"] is True
        finally:
            config.TRAIN_READY_THRESHOLD = original


class TestCaptureEndpoint:
    def test_capture_requires_auth(self, client):
        r = client.post("/v1/memory/capture", json={
            "role": "user", "content": "hello"})
        assert r.status_code in (401, 403)

    def test_capture_round_trip(self, client):
        _, headers = _signed_in_user("ep1")
        r = client.post("/v1/memory/capture", headers=headers, json={
            "role": "user",
            "content": "Place dimensions on Level 3 walls.",
            "tool_trace": [],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stage"] == "captured"
        assert body["id"] > 0

    def test_capture_rejects_bad_role(self, client):
        _, headers = _signed_in_user("ep2")
        r = client.post("/v1/memory/capture", headers=headers, json={
            "role": "system", "content": "x"})
        assert r.status_code == 400

    def test_capture_rejects_empty_content(self, client):
        _, headers = _signed_in_user("ep3")
        r = client.post("/v1/memory/capture", headers=headers, json={
            "role": "user", "content": "  "})
        assert r.status_code == 400

    def test_capture_rejects_non_list_tool_trace(self, client):
        _, headers = _signed_in_user("ep4")
        r = client.post("/v1/memory/capture", headers=headers, json={
            "role": "user", "content": "hi",
            "tool_trace": {"oops": "object"}})
        assert r.status_code == 400


class TestStatsEndpoint:
    def test_stats_requires_auth(self, client):
        r = client.get("/v1/memory/stats")
        assert r.status_code in (401, 403)

    def test_stats_reflects_capture(self, client):
        _, headers = _signed_in_user("statsep1")
        client.post("/v1/memory/capture", headers=headers, json={
            "role": "user", "content": "Hello"})
        client.post("/v1/memory/capture", headers=headers, json={
            "role": "assistant", "content": "Hi"})
        r = client.get("/v1/memory/stats", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["capture_today"] >= 2
        assert "train_ready" in body
        assert "threshold" in body
