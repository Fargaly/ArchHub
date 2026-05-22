"""Semantic memory facts — ADR-002 v1.3.4+.

Five tiers in scope:
  HOT       — in-process, not tested here
  EPISODIC  — training_samples, tested in test_memory.py
  SEMANTIC  — memory_facts + FTS5, tested below
  COLLECTIVE — collective_memory + access log, tested below
  PROCEDURAL — deferred to v1.5

The tests pin the Mem0-style ADD/UPDATE/DELETE/NOOP semantics, the
redaction policy enforcement on shared writes, the FTS5 search path,
and the audit log invariants.
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


def _signed_in_user(suffix: str = "") -> tuple[dict, dict]:
    import db
    email = f"memfact+{suffix or uuid.uuid4().hex[:6]}@example.com"
    u = db.get_or_create_user(email)
    token = db.issue_token(u["id"])
    return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    import main
    with TestClient(main.app) as c:
        yield c


# ── DAO ────────────────────────────────────────────────────────────
class TestFactsDAO:
    def test_insert_returns_row_id(self):
        import db
        u, _ = _signed_in_user("dao1")
        fid = db.insert_memory_fact(
            user_id=u["id"], text="User prefers metric units")
        assert isinstance(fid, int) and fid > 0
        row = db.get_memory_fact(fid)
        assert row["text"] == "User prefers metric units"
        assert row["visibility"] == "private"
        assert row["valid_until"] is None
        assert row["reinforce_count"] == 1

    def test_insert_rejects_bad_scope(self):
        import db
        u, _ = _signed_in_user("dao2")
        with pytest.raises(ValueError):
            db.insert_memory_fact(
                user_id=u["id"], text="x", scope="cosmos")

    def test_insert_rejects_empty_text(self):
        import db
        u, _ = _signed_in_user("dao3")
        with pytest.raises(ValueError):
            db.insert_memory_fact(user_id=u["id"], text="   ")

    def test_list_filters_by_scope_and_validity(self):
        import db
        u, _ = _signed_in_user("dao4")
        a = db.insert_memory_fact(user_id=u["id"], text="A", scope="user")
        b = db.insert_memory_fact(user_id=u["id"], text="B", scope="project",
                                    project_id="p1")
        c = db.insert_memory_fact(user_id=u["id"], text="C", scope="user")
        db.delete_memory_fact(c)
        listed = db.list_memory_facts(user_id=u["id"])
        ids = [f["id"] for f in listed]
        assert a in ids and b in ids
        assert c not in ids   # soft-deleted, excluded
        user_only = db.list_memory_facts(user_id=u["id"], scope="user")
        assert {f["id"] for f in user_only} == {a}

    def test_update_bumps_reinforce_count(self):
        import db
        u, _ = _signed_in_user("dao5")
        fid = db.insert_memory_fact(user_id=u["id"],
                                      text="User uses Revit 2024")
        db.update_memory_fact(fid, text="User uses Revit 2024 + 2025",
                                confidence=0.85)
        row = db.get_memory_fact(fid)
        assert row["text"] == "User uses Revit 2024 + 2025"
        assert row["reinforce_count"] == 2
        assert row["confidence"] == pytest.approx(0.85)

    def test_delete_soft_deletes(self):
        import db
        u, _ = _signed_in_user("dao6")
        fid = db.insert_memory_fact(user_id=u["id"], text="ephemeral")
        db.delete_memory_fact(fid)
        row = db.get_memory_fact(fid)
        # Row remains; valid_until is set.
        assert row is not None
        assert row["valid_until"] is not None


# ── FTS5 search ────────────────────────────────────────────────────
class TestFactsSearch:
    def test_search_finds_term(self):
        import db
        u, _ = _signed_in_user("fts1")
        db.insert_memory_fact(user_id=u["id"],
                                text="User prefers metric units")
        db.insert_memory_fact(user_id=u["id"],
                                text="Project Tower-A uses imperial")
        hits = db.search_memory_facts(user_id=u["id"], query="metric")
        assert any("metric" in h["text"].lower() for h in hits)

    def test_search_isolated_to_user_unless_shared(self):
        import db
        u1, _ = _signed_in_user("fts2a")
        u2, _ = _signed_in_user("fts2b")
        db.insert_memory_fact(user_id=u1["id"],
                                text="User1's private wall preference")
        db.insert_memory_fact(user_id=u2["id"],
                                text="User2's private wall preference")
        u2_hits = db.search_memory_facts(user_id=u2["id"],
                                           query="wall preference")
        # u2 should only see u2's row + shared (none).
        assert all(h["user_id"] == u2["id"] for h in u2_hits)

    def test_search_returns_empty_on_empty_query(self):
        import db
        u, _ = _signed_in_user("fts3")
        assert db.search_memory_facts(user_id=u["id"], query="") == []
        assert db.search_memory_facts(user_id=u["id"], query="   ") == []


# ── Mem0-style writer ops ──────────────────────────────────────────
class TestWriterOps:
    def test_add_inserts_with_floor_confidence(self):
        import db, memory_writer
        u, _ = _signed_in_user("op1")
        res = memory_writer.apply_ops(
            user_id=u["id"],
            ops=[{"op": "ADD", "text": "a fact", "confidence": 0.1}],
        )
        assert len(res["added"]) == 1 and not res["errors"]
        row = db.get_memory_fact(res["added"][0])
        # MIN_ADD_CONFIDENCE floor kicks in
        assert row["confidence"] >= memory_writer.MIN_ADD_CONFIDENCE

    def test_update_changes_text_and_logs(self):
        import db, memory_writer
        u, _ = _signed_in_user("op2")
        fid = db.insert_memory_fact(user_id=u["id"], text="old")
        res = memory_writer.apply_ops(
            user_id=u["id"],
            ops=[{"op": "UPDATE", "fact_id": fid, "text": "new"}],
        )
        assert res["updated"] == [fid] and not res["errors"]
        assert db.get_memory_fact(fid)["text"] == "new"
        ops_log = db.list_memory_ops(user_id=u["id"], limit=5)
        assert any(o["op"] == "UPDATE" and o["before_text"] == "old"
                    and o["after_text"] == "new" for o in ops_log)

    def test_delete_soft_deletes_via_writer(self):
        import db, memory_writer
        u, _ = _signed_in_user("op3")
        fid = db.insert_memory_fact(user_id=u["id"], text="gone")
        res = memory_writer.apply_ops(
            user_id=u["id"],
            ops=[{"op": "DELETE", "fact_id": fid}],
        )
        assert res["deleted"] == [fid] and not res["errors"]
        assert db.get_memory_fact(fid)["valid_until"] is not None

    def test_noop_logs_but_does_not_touch_facts(self):
        import db, memory_writer
        u, _ = _signed_in_user("op4")
        res = memory_writer.apply_ops(
            user_id=u["id"],
            ops=[{"op": "NOOP", "text": "x", "rationale": "known"}],
        )
        assert res["noop"] == 1 and not res["errors"]
        log = db.list_memory_ops(user_id=u["id"], limit=5)
        assert any(o["op"] == "NOOP" for o in log)

    def test_unknown_op_records_error(self):
        import memory_writer
        u, _ = _signed_in_user("op5")
        res = memory_writer.apply_ops(
            user_id=u["id"],
            ops=[{"op": "BANANA", "text": "nope"}],
        )
        assert res["errors"]
        assert "BANANA" in res["errors"][0]

    def test_update_rejects_cross_user(self):
        import db, memory_writer
        u1, _ = _signed_in_user("op6a")
        u2, _ = _signed_in_user("op6b")
        fid = db.insert_memory_fact(user_id=u1["id"], text="mine")
        res = memory_writer.apply_ops(
            user_id=u2["id"],
            ops=[{"op": "UPDATE", "fact_id": fid, "text": "stolen"}],
        )
        # Error recorded; u1's fact unchanged.
        assert res["errors"]
        assert db.get_memory_fact(fid)["text"] == "mine"


# ── Redaction + promotion ──────────────────────────────────────────
class TestRedactionAndPromote:
    def test_redact_strips_email(self):
        import memory_writer
        out = memory_writer.redact_text(
            "Send to fargaly@archhub.com please")
        assert "[email]" in out
        assert "fargaly" not in out

    def test_redact_strips_windows_path(self):
        import memory_writer
        out = memory_writer.redact_text(
            r"File at C:\\Users\\Fargaly\\Documents\\Tower-A.rvt is open")
        # Strict redactor turns the path into [path]; the absolute Windows
        # token is gone.
        assert "C:\\\\Users" not in out
        assert "[path]" in out

    def test_redact_drops_client_name_line(self):
        import memory_writer
        out = memory_writer.redact_text(
            "Wall types preferred\nClient: Bayaty Architects\nlevel 3")
        assert "Bayaty" not in out
        assert "Wall types preferred" in out

    def test_promote_requires_transform_policy(self):
        import db, memory_writer
        u, _ = _signed_in_user("rp1")
        fid = db.insert_memory_fact(user_id=u["id"],
                                      text="Standard wall pattern")
        with pytest.raises(ValueError):
            memory_writer.promote_to_shared(
                fact_id=fid, user_id=u["id"],
                redaction_policy="simple",
            )

    def test_promote_persists_and_redacts(self):
        import db, memory_writer
        u, _ = _signed_in_user("rp2")
        # Fact with a hidden email — must be stripped at promotion.
        fid = db.insert_memory_fact(
            user_id=u["id"],
            text="Standard pattern; question to me@archhub.com\nClient: Acme")
        cid = memory_writer.promote_to_shared(
            fact_id=fid, user_id=u["id"],
            access_policy="public", domain="aec.walls")
        assert cid > 0
        listed = db.list_collective_memory(domain="aec.walls")
        assert any(c["id"] == cid for c in listed)
        # The stored collective text must not contain the email or client.
        target = next(c for c in listed if c["id"] == cid)
        assert "me@archhub.com" not in target["text"]
        assert "Acme" not in target["text"]

    def test_promote_rejects_cross_user(self):
        import db, memory_writer
        u1, _ = _signed_in_user("rp3a")
        u2, _ = _signed_in_user("rp3b")
        fid = db.insert_memory_fact(user_id=u1["id"], text="mine")
        with pytest.raises(ValueError):
            memory_writer.promote_to_shared(
                fact_id=fid, user_id=u2["id"],
            )


# ── Heuristic extractor ────────────────────────────────────────────
class TestExtractor:
    def test_remember_command_extracts(self):
        import memory_extractor
        u, _ = _signed_in_user("ex1")
        ops = memory_extractor.extract_ops(
            user_id=u["id"],
            text="/remember I work in metric units only")
        assert ops and ops[0]["op"] == "ADD"
        assert "metric" in ops[0]["text"].lower()

    def test_my_x_is_y_pattern(self):
        import memory_extractor
        u, _ = _signed_in_user("ex2")
        ops = memory_extractor.extract_ops(
            user_id=u["id"],
            text="my drafting standard is BS1192")
        assert ops and ops[0]["op"] == "ADD"

    def test_overlap_routes_to_update_or_noop(self):
        import db, memory_extractor, memory_writer
        u, _ = _signed_in_user("ex3")
        # Seed an existing fact via /remember
        ops0 = memory_extractor.extract_ops(
            user_id=u["id"],
            text="/remember User uses Revit 2024")
        memory_writer.apply_ops(user_id=u["id"], ops=ops0)
        # Re-extract a closely-related claim — expect UPDATE not ADD
        ops1 = memory_extractor.extract_ops(
            user_id=u["id"],
            text="/remember User uses Revit 2024 + 2025")
        assert ops1
        assert ops1[0]["op"] in ("UPDATE", "NOOP")


# ── HTTP endpoints ──────────────────────────────────────────────────
class TestEndpoints:
    def test_facts_create_round_trip(self, client):
        _, h = _signed_in_user("ep1")
        r = client.post("/v1/memory/facts", headers=h, json={
            "text": "User prefers terracotta accents",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stage"] == "added"
        assert body["id"] > 0

    def test_facts_create_requires_text(self, client):
        _, h = _signed_in_user("ep2")
        r = client.post("/v1/memory/facts", headers=h, json={})
        assert r.status_code == 400

    def test_facts_list_returns_caller_facts(self, client):
        _, h = _signed_in_user("ep3")
        client.post("/v1/memory/facts", headers=h, json={
            "text": "Alpha fact"})
        client.post("/v1/memory/facts", headers=h, json={
            "text": "Beta fact"})
        r = client.get("/v1/memory/facts", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert len(body["results"]) >= 2

    def test_facts_search_via_q_param(self, client):
        _, h = _signed_in_user("ep4")
        client.post("/v1/memory/facts", headers=h, json={
            "text": "wall types preferred"})
        client.post("/v1/memory/facts", headers=h, json={
            "text": "door schedule config"})
        r = client.get("/v1/memory/facts?q=wall", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert any("wall" in row["text"].lower()
                    for row in body["results"])

    def test_facts_update_changes_text(self, client):
        import db
        u, h = _signed_in_user("ep5")
        fid = db.insert_memory_fact(user_id=u["id"], text="old text")
        r = client.put(f"/v1/memory/facts/{fid}", headers=h, json={
            "text": "new text"})
        assert r.status_code == 200
        assert db.get_memory_fact(fid)["text"] == "new text"

    def test_facts_delete_soft_deletes(self, client):
        import db
        u, h = _signed_in_user("ep6")
        fid = db.insert_memory_fact(user_id=u["id"], text="ephemeral")
        r = client.delete(f"/v1/memory/facts/{fid}", headers=h)
        assert r.status_code == 200
        assert db.get_memory_fact(fid)["valid_until"] is not None

    def test_promote_requires_existing_fact(self, client):
        _, h = _signed_in_user("ep7")
        r = client.post("/v1/memory/facts/999999/promote",
                         headers=h, json={})
        assert r.status_code == 400

    def test_extract_endpoint_applies_ops(self, client):
        _, h = _signed_in_user("ep8")
        r = client.post("/v1/memory/extract", headers=h, json={
            "text": "/remember I love Revit 2025"})
        assert r.status_code == 200
        body = r.json()
        assert body["ops_proposed"]
        assert (body["result"]["added"]
                 or body["result"]["updated"]
                 or body["result"]["noop"] > 0)

    def test_ops_log_returns_entries(self, client):
        _, h = _signed_in_user("ep9")
        client.post("/v1/memory/facts", headers=h, json={
            "text": "audit me"})
        r = client.get("/v1/memory/ops", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert any(o["op"] == "ADD" for o in body["results"])

    def test_auth_required(self, client):
        for path, method in (
            ("/v1/memory/facts", "GET"),
            ("/v1/memory/facts", "POST"),
            ("/v1/memory/collective", "GET"),
            ("/v1/memory/extract", "POST"),
            ("/v1/memory/ops", "GET"),
        ):
            if method == "GET":
                r = client.get(path)
            else:
                r = client.post(path, json={"text": "x"})
            assert r.status_code in (401, 403), f"{method} {path} → {r.status_code}"


# ── Audit log invariants ────────────────────────────────────────────
class TestAuditLog:
    def test_search_of_shared_logs_access(self, client):
        """Searching shared facts must record a row in memory_access_log."""
        import db, memory_writer
        u1, h1 = _signed_in_user("audit1")
        u2, h2 = _signed_in_user("audit2")
        # u1 creates + promotes a fact
        fid = db.insert_memory_fact(user_id=u1["id"],
                                      text="Standard dimension policy")
        memory_writer.promote_to_shared(
            fact_id=fid, user_id=u1["id"],
            access_policy="public", domain="aec.dims")
        # u2 browses collective
        r = client.get("/v1/memory/collective?domain=aec.dims", headers=h2)
        assert r.status_code == 200
        # Audit row should exist for u2
        with db.connect() as con:
            rows = con.execute(
                "SELECT COUNT(*) AS n FROM memory_access_log"
                " WHERE reader_user_id = ?",
                (u2["id"],),
            ).fetchone()
        assert rows["n"] >= 1
