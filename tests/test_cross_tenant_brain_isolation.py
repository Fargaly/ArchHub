"""One firm's brain must not be readable or writable by another firm.

Both of these were live in the cloud backend. `shared_company` was
admitted on the visibility word alone, so any signed-up stranger read a
firm's private notes; and /v1/brain/sync routed a fragment to whatever
`firm_id` the CLIENT named, so one junk write both poisoned another
firm's shared brain and — because contributing widens the caller's read
set — turned the writer into a permanent reader of it.

Both tests fail on the code as it stood before the fix.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "cloud_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "cloud.db"))
    monkeypatch.setenv("REPLICAS_ROOT", str(tmp_path / "replicas"))
    for name in ("config", "db", "brain_replica"):
        sys.modules.pop(name, None)
    import db as _db

    _db.init_schema()
    return _db


def _member_of_own_company(db, email, company_name):
    """A user who owns one company and is its current member."""
    user = db.get_or_create_user(email)
    company = db.create_company(
        name=company_name, owner_user_id=user["id"], plan="studio"
    )
    company_id = str(company["id"])
    with db.connect() as con:
        con.execute(
            "UPDATE users SET current_company_id = ? WHERE id = ?",
            (company_id, user["id"]),
        )
    return db.get_user(user["id"]), company_id


def test_shared_company_fact_stays_inside_its_company(db):
    alice, alice_company = _member_of_own_company(
        db, "alice@firm-a.test", "Firm A"
    )
    bob, _bob_company = _member_of_own_company(db, "bob@firm-b.test", "Firm B")

    secret = "Firm A charges four and a half percent on schematic design"
    db.insert_memory_fact(
        user_id=alice["id"],
        text=secret,
        scope="company",
        visibility="shared_company",
        company_id=alice_company,
    )

    mine = db.search_memory_facts(user_id=alice["id"], query="schematic")
    assert any(secret in (row.get("text") or "") for row in mine), (
        "a member must still read their own firm's shared fact"
    )

    theirs = db.search_memory_facts(user_id=bob["id"], query="schematic")
    assert all(secret not in (row.get("text") or "") for row in theirs), (
        "another firm's shared_company fact leaked to an outsider"
    )


def test_sync_cannot_write_into_a_firm_the_caller_is_not_in(db):
    import brain_replica

    outsider = "outsider-" + uuid.uuid4().hex[:8]
    victim_firm = "firm-" + uuid.uuid4().hex[:8]

    # This caller belongs to no company, so the server resolves an empty
    # firm read-set — and the WRITE must obey that same list.
    replica = brain_replica.BrainReplica.open(
        user_id=outsider, firm_keys=[], community_keys=[]
    )
    outcome = replica.apply_delta(
        {
            "fragments": [
                {
                    "id": "frag-" + uuid.uuid4().hex[:8],
                    "scope": "firm",
                    "firm_id": victim_firm,
                    "text": "poisoned",
                    "kind": "fact",
                    "owner_user": outsider,
                }
            ]
        }
    )

    assert outcome["accepted"] == 0, "a non-member's firm write was accepted"
    assert victim_firm not in [
        str(key) for key in (outcome.get("firm_keys") or [])
    ], "the write handed the outsider a key to the victim firm"
    assert any(
        "not a member" in (row.get("reason") or "")
        for row in (outcome.get("rejected") or [])
    ), "the write was dropped without saying why"
