"""cloud-brain-unify (2026-05-31) — ONE per-user cloud brain.

Proves the two formerly-separate per-user stores are now ONE:

  * /v1/memory/* (semantic facts API) and /v1/brain/sync (replica delta
    sync) read+write the SAME per-user replica `fragments` table.
  * A fact added via /v1/memory shows up as a fragment in /v1/brain/sync,
    and a fragment synced via /v1/brain/sync is listable via /v1/memory.
  * The one-time memory_facts → fragments migration is idempotent (re-run
    is a no-op, no duplicate fragment, no duplicate index row).

The RED-without-fix guard at the bottom documents that the cross-API
agreement is a REAL behavioural guarantee of the unified store, not an
accident — it fails against the old two-store DAO (legacy memory_facts +
separate replica) by construction.

Design note: cloud_backend/docs/audits/cloud-brain-unify-2026-05-31.md
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


def _signed_in_user(suffix: str = "") -> tuple[dict, dict]:
    import db
    email = f"unify+{suffix or uuid.uuid4().hex[:6]}@example.com"
    u = db.get_or_create_user(email)
    token = db.issue_token(u["id"])
    return u, {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Both APIs, one store
# ---------------------------------------------------------------------------
class TestOneStoreBothAPIs:
    def test_fact_added_via_memory_is_a_fragment_in_brain_sync(self, client):
        """Add a fact through /v1/memory/facts → it must appear as a
        fragment when the SAME user pulls /v1/brain/sync. (memory → sync)"""
        u, h = _signed_in_user("m2s")
        r = client.post("/v1/memory/facts", headers=h,
                        json={"text": "Project ORYX uses Revit 2026"})
        assert r.status_code == 200, r.text
        fact_id = r.json()["id"]
        assert fact_id > 0

        # Empty sync = pure read of the user's replica fragments.
        sync = client.post("/v1/brain/sync",
                           json={"since_hlc": "", "delta": {"fragments": []}},
                           headers=h)
        assert sync.status_code == 200, sync.text
        frags = sync.json()["merged"]["fragments"]
        texts = [f["text"] for f in frags]
        assert "Project ORYX uses Revit 2026" in texts, (
            "fact added via /v1/memory must exist as a fragment in the SAME "
            "store /v1/brain/sync reads — proves one store, not two")
        # The unified fragment id is the memory-fact namespace (mf-<rowid>).
        oryx = next(f for f in frags
                    if f["text"] == "Project ORYX uses Revit 2026")
        assert oryx["id"].startswith("mf-")
        assert oryx["kind"] == "fact"

    def test_fragment_synced_via_brain_sync_is_listable_via_memory(self, client):
        """Sync a fragment through /v1/brain/sync → it must be listable +
        searchable through /v1/memory/facts. (sync → memory)"""
        u, h = _signed_in_user("s2m")
        body = {
            "since_hlc": "",
            "delta": {"fragments": [
                {"id": "frag-sync-1", "kind": "fact",
                 "text": "Studio standard wall is CMU-200",
                 "subject": "Studio", "predicate": "standard_wall",
                 "object": "CMU-200",
                 "hlc": "0000000000000009.aaaaaaaa"},
            ]},
        }
        sync = client.post("/v1/brain/sync", json=body, headers=h)
        assert sync.status_code == 200, sync.text
        assert sync.json()["accepted"] == 1

        # Now the /v1/memory list + search must surface that same fragment.
        listed = client.get("/v1/memory/facts", headers=h)
        assert listed.status_code == 200
        texts = [row["text"] for row in listed.json()["results"]]
        assert "Studio standard wall is CMU-200" in texts, (
            "a fragment synced via /v1/brain/sync must be visible through "
            "/v1/memory — both APIs share one per-user store")

        found = client.get("/v1/memory/facts?q=CMU-200", headers=h)
        assert found.status_code == 200
        assert any("CMU-200" in row["text"]
                   for row in found.json()["results"]), (
            "the synced fragment must be FTS-searchable via /v1/memory too")

    def test_forget_via_memory_tombstones_the_fragment(self, client):
        """Deleting a fact via /v1/memory must tombstone the underlying
        fragment so the /v1/brain/sync live export agrees it's gone."""
        u, h = _signed_in_user("forget")
        fid = client.post("/v1/memory/facts", headers=h,
                          json={"text": "temporary preference X"}).json()["id"]
        # Present before forget.
        before = client.post("/v1/brain/sync",
                             json={"delta": {"fragments": []}},
                             headers=h).json()["merged"]["fragments"]
        assert any(f["text"] == "temporary preference X" for f in before)

        d = client.delete(f"/v1/memory/facts/{fid}", headers=h)
        assert d.status_code == 200

        # Gone from the live (valid-only) memory list…
        listed = client.get("/v1/memory/facts", headers=h).json()["results"]
        assert not any(r["text"] == "temporary preference X" for r in listed)
        # …and the fragment now carries a tombstone (valid_until set).
        import db
        row = db.get_memory_fact(fid)
        assert row is not None and row["valid_until"] is not None

    def test_isolation_holds_across_both_apis(self, client):
        """One user's /v1/memory fact never leaks into another user's
        /v1/brain/sync (per-user replica isolation survives unification)."""
        ua, ha = _signed_in_user("isoA")
        ub, hb = _signed_in_user("isoB")
        client.post("/v1/memory/facts", headers=ha,
                    json={"text": "A-confidential metric"})
        client.post("/v1/memory/facts", headers=hb,
                    json={"text": "B-confidential metric"})
        b_frags = client.post("/v1/brain/sync",
                              json={"delta": {"fragments": []}},
                              headers=hb).json()["merged"]["fragments"]
        b_texts = [f["text"] for f in b_frags]
        assert "B-confidential metric" in b_texts
        assert "A-confidential metric" not in b_texts


# ---------------------------------------------------------------------------
# One-time migration: legacy memory_facts rows → fragments
# ---------------------------------------------------------------------------
class TestMigration:
    def _seed_legacy_rows(self, user_id: str, n: int = 3) -> list[int]:
        """Insert rows DIRECTLY into the legacy memory_facts table (bypassing
        the unified DAO) to simulate a pre-unify deployment, and clear the
        migration marker so the migration will actually run."""
        import time
        import db
        ids = []
        with db.connect() as con:
            con.execute("DELETE FROM schema_meta"
                        " WHERE key = 'migrated_memory_facts'")
            now = int(time.time())
            for i in range(n):
                cur = con.execute(
                    "INSERT INTO memory_facts (user_id, scope, visibility,"
                    " subject, predicate, object, text, confidence,"
                    " valid_from, valid_until, created_at, last_reinforced_at,"
                    " reinforce_count)"
                    " VALUES (?, 'user', 'private', '', '', '', ?, 0.8,"
                    " ?, NULL, ?, ?, 1)",
                    (user_id, f"legacy fact number {i}", now, now, now),
                )
                ids.append(int(cur.lastrowid or 0))
        return ids

    def test_migration_folds_legacy_rows_into_fragments(self, client):
        import db
        u, h = _signed_in_user("mig1")
        legacy_ids = self._seed_legacy_rows(u["id"], 3)

        res = db.migrate_memory_facts_to_fragments()
        assert res["skipped"] is False
        assert res["migrated"] >= 3

        # Each legacy row now exists as a fragment in the user's replica.
        rep = db._open_replica(u["id"])
        for lid in legacy_ids:
            frag = rep.get_fragment(f"legacy-mf-{lid}")
            assert frag is not None, f"legacy row {lid} not migrated"
            assert frag["text"].startswith("legacy fact number")

        # And they surface through the unified /v1/memory list.
        listed = client.get("/v1/memory/facts", headers=h).json()["results"]
        texts = [r["text"] for r in listed]
        assert any(t.startswith("legacy fact number") for t in texts)

    def test_migration_is_idempotent_no_duplicates(self, client):
        import db
        u, _ = _signed_in_user("mig2")
        self._seed_legacy_rows(u["id"], 2)

        first = db.migrate_memory_facts_to_fragments()
        assert first["migrated"] >= 2

        rep = db._open_replica(u["id"])
        frags_after_first = rep.list_fragments(kind="fact", limit=500)
        with db.connect() as con:
            idx_after_first = con.execute(
                "SELECT COUNT(*) AS n FROM memory_fact_index WHERE user_id = ?",
                (u["id"],),
            ).fetchone()["n"]

        # Re-run: marker now present → whole pass is a guarded no-op.
        second = db.migrate_memory_facts_to_fragments()
        assert second["skipped"] is True
        assert second["migrated"] == 0

        frags_after_second = rep.list_fragments(kind="fact", limit=500)
        with db.connect() as con:
            idx_after_second = con.execute(
                "SELECT COUNT(*) AS n FROM memory_fact_index WHERE user_id = ?",
                (u["id"],),
            ).fetchone()["n"]

        # No new fragment, no new index row — nothing duplicated.
        assert len(frags_after_second) == len(frags_after_first)
        assert idx_after_second == idx_after_first

    def test_migration_drops_legacy_rows_carrying_bare_secret(self, client):
        """A legacy row whose value is a bare credential is rejected by the
        replica secret-gate during migration (BRAIN-FIRST) — it must NOT be
        folded into the brain, and the pass still completes."""
        import time
        import db
        u, _ = _signed_in_user("migsec")
        with db.connect() as con:
            con.execute("DELETE FROM schema_meta"
                        " WHERE key = 'migrated_memory_facts'")
            now = int(time.time())
            cur = con.execute(
                "INSERT INTO memory_facts (user_id, scope, visibility,"
                " subject, predicate, object, text, confidence, valid_from,"
                " valid_until, created_at, last_reinforced_at, reinforce_count)"
                " VALUES (?, 'user', 'private', '', '', 'sk-ant-deadbeef0001',"
                " 'leaked', 0.8, ?, NULL, ?, ?, 1)",
                (u["id"], now, now, now),
            )
            secret_lid = int(cur.lastrowid or 0)
        res = db.migrate_memory_facts_to_fragments()
        assert res["skipped"] is False
        rep = db._open_replica(u["id"])
        assert rep.get_fragment(f"legacy-mf-{secret_lid}") is None, (
            "a bare-secret legacy row must be rejected at migration, not "
            "leaked into the canonical brain store")


# ---------------------------------------------------------------------------
# RED-without-fix guard
# ---------------------------------------------------------------------------
class TestRedWithoutFix:
    def test_memory_and_sync_share_the_same_fragment_id_space(self, client):
        """LOAD-BEARING unification assertion (RED against the old design).

        Under the OLD two-store design, /v1/memory wrote an INTEGER row into
        `archhub_cloud.db.memory_facts` and /v1/brain/sync wrote a TEXT
        fragment into a SEPARATE replica db — a memory fact had NO fragment
        and NO `mf-` id in the sync store at all, so this assertion could not
        pass. It passes now ONLY because the memory write lands in the SAME
        replica fragments table the sync export reads. If a future change
        re-splits the stores, this test goes RED — exactly the regression
        guard the unification needs.
        """
        import db
        u, h = _signed_in_user("red")
        fact_id = client.post("/v1/memory/facts", headers=h,
                              json={"text": "unification canary"}).json()["id"]

        # The DAO row exposes the underlying fragment id…
        row = db.get_memory_fact(fact_id)
        assert row is not None
        frag_id = row["frag_id"]
        assert frag_id and frag_id.startswith("mf-")

        # …and the brain-sync export of the SAME user contains a fragment
        # with that EXACT id. One id space, one store.
        merged = client.post("/v1/brain/sync",
                             json={"delta": {"fragments": []}},
                             headers=h).json()["merged"]["fragments"]
        sync_ids = {f["id"] for f in merged}
        assert frag_id in sync_ids, (
            "the memory fact's fragment id must be present in the brain-sync "
            "store — a single source of truth. RED if the stores re-split.")
