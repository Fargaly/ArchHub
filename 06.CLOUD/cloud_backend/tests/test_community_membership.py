"""A community key named on the wire is a claim; a membership the cloud verified
from a join-code signed by the community's ENROLLED owner is what gates the
shared community replica. Disposable databases and keys only (conftest)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from community_join import REQUIRED, _payload_bytes, enrol_statement, verify_join_code  # noqa: E402


def _envelope(community_id: str, *, ttl: float = 3600.0, priv: str | None = None, pub: str | None = None) -> tuple[str, str]:
    """A join-code exactly as an owner issues it (same payload bytes, same signer)."""
    from tests.join_signing import _generate_keypair, _sign
    if priv is None:
        priv, pub = _generate_keypair()
    now = time.time()
    data = {"community_id": community_id, "name": "Court", "owner_pub": pub, "role": "member",
            "transport": {}, "issued_by": "owner-device", "issued_at": now,
            "expires_at": now + ttl, "nonce": uuid.uuid4().hex[:12]}
    assert set(data) == set(REQUIRED)
    payload = _payload_bytes(data)
    sig = _sign(priv, payload)
    return base64.urlsafe_b64encode(payload).decode() + "." + sig, pub


def test_verifier_checks_only_the_enrolled_key_and_rejects_tampering():
    from tests.join_signing import _generate_keypair
    priv, pub = _generate_keypair()
    env, _ = _envelope("c-1", priv=priv, pub=pub)
    payload, reason = verify_join_code(env, owner_pub=pub)
    assert reason == "ok" and payload["community_id"] == "c-1" and payload["owner_pub"] == pub
    body, sig = env.split(".", 1)
    forged = json.loads(base64.urlsafe_b64decode(body.encode()))
    forged["community_id"] = "c-2"
    forged_env = base64.urlsafe_b64encode(json.dumps(forged, sort_keys=True, separators=(",", ":")).encode()).decode() + "." + sig
    assert verify_join_code(forged_env, owner_pub=pub)[1] == "signature mismatch"
    expired, _ = _envelope("c-3", ttl=-5, priv=priv, pub=pub)
    assert verify_join_code(expired, owner_pub=pub)[1] == "expired"
    assert verify_join_code("garbage", owner_pub=pub)[0] is None
    # A self-signed code verifies against its own key, so its own key is never the reference.
    self_signed, _ = _envelope("c-1")
    assert verify_join_code(self_signed, owner_pub=pub)[0] is None
    assert verify_join_code(env, owner_pub=None) == (None, "community has no enrolled owner")


def test_the_symmetric_fallback_is_refused_even_against_its_own_key():
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    now = time.time()
    data = {"community_id": "hmac-club", "name": "Court", "owner_pub": key, "role": "member", "transport": {},
            "issued_by": "old-device", "issued_at": now, "expires_at": now + 3600, "nonce": "n1"}
    payload = _payload_bytes(data)
    sig = base64.urlsafe_b64encode(hmac.new(b"k" * 32, payload, hashlib.sha256).digest()).decode()
    env = base64.urlsafe_b64encode(payload).decode() + "." + sig
    assert verify_join_code(env, owner_pub=key) == (None, "signature mismatch")


@pytest.fixture
def replicas_root(tmp_path, monkeypatch):
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


def _user(suffix):
    import db
    u = db.get_or_create_user(f"member+{suffix}-{uuid.uuid4().hex[:6]}@example.com")
    return u, {"Authorization": f"Bearer {db.issue_token(u['id'])}"}


def _memberships():
    import db
    with db.connect() as con:
        return sorted(tuple(row) for row in con.execute(
            "SELECT community_id, user_id, role, owner_pub FROM community_members").fetchall())


def _legacy_rows(*rows):
    """Memberships recorded from self-asserted codes before owners were enrolled (no provenance)."""
    import db
    with db.connect() as con:
        for community_id, user, owner_pub in rows:
            con.execute("INSERT INTO community_members (community_id, user_id, role, owner_pub, joined_at)"
                        " VALUES (?, ?, 'member', ?, 1)", (community_id, user["id"], owner_pub))


def _sync_keys(client, headers, community_id):
    """What the shared replica grants: the keys the server resolves, and whether a write to the community lands."""
    r = client.post("/v1/brain/sync", headers=headers, json={"delta": {"fragments": [_community_fragment(community_id, "probe")]}})
    assert r.status_code == 200, r.text
    return r.json()["community_keys"], [x for x in r.json()["rejected"] if "not a member" in (x.get("reason") or "")]


def _enrol_signature(priv, community_id, user_id):
    from tests.join_signing import _sign
    return _sign(priv, enrol_statement(community_id, user_id))


def _recover(community_id, owner, priv, pub):
    """The explicit recovery binds an existing community to a registered account whose key signed the enrolment."""
    import db
    return db.recover_community_owner(community_id, owner_user_id=owner["id"], owner_pub=pub,
                                      signature=_enrol_signature(priv, community_id, owner["id"]))


def _community_fragment(community_id, text):
    # Same shape the desktop brain pushes: the community id rides in `extra`.
    return {"id": "frag-" + uuid.uuid4().hex[:8], "kind": "fact", "text": text, "scope": "community",
            "hlc": "0000000000000001.aaaaaaaa", "extra": {"community_id": community_id}}


def test_a_guessed_community_id_cannot_be_written_or_read(client):
    _, h = _user("stranger")
    r = client.post("/v1/brain/sync", headers=h, json={"delta": {"fragments": [_community_fragment("secret-club", "poison")]},
                                                       "community_keys": ["secret-club"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["community_keys"] == []
    assert any("not a member" in (x.get("reason") or "") for x in out["rejected"]), out["rejected"]


def test_an_existing_invitation_is_accepted_against_the_trusted_enrolled_key(client):
    from tests.join_signing import _generate_keypair
    owner, _ = _user("owner")
    priv, pub = _generate_keypair()
    env, _ = _envelope("legacy-club", priv=priv, pub=pub)  # issued before enrolment existed
    assert _recover("legacy-club", owner, priv, pub) is True
    member, h = _user("member")
    r = client.post("/v1/community/join", headers=h, json={"envelope": env})
    assert r.status_code == 200 and r.json()["community_keys"] == ["legacy-club"], r.text
    assert ("legacy-club", member["id"], "member", pub) in _memberships()


def test_a_forged_or_self_asserted_owner_is_refused_with_zero_membership_writes(client):
    from tests.join_signing import _generate_keypair
    owner, _ = _user("owner")
    priv, pub = _generate_keypair()
    assert _recover("guarded-club", owner, priv, pub) is True
    _, h = _user("attacker")
    before = _memberships()
    self_signed, attacker_pub = _envelope("guarded-club")  # the attacker's own key, named as owner
    refused = client.post("/v1/community/join", headers=h, json={"envelope": self_signed})
    assert refused.status_code == 403 and "different owner" in refused.text
    body, sig = self_signed.split(".", 1)
    claim = json.loads(base64.urlsafe_b64decode(body.encode()))
    claim["owner_pub"] = pub  # names the real owner but the signature is the attacker's
    named = base64.urlsafe_b64encode(json.dumps(claim, sort_keys=True, separators=(",", ":")).encode()).decode() + "." + sig
    refused = client.post("/v1/community/join", headers=h, json={"envelope": named})
    assert refused.status_code == 403 and "signature mismatch" in refused.text
    unenrolled, _ = _envelope("never-enrolled")
    refused = client.post("/v1/community/join", headers=h, json={"envelope": unenrolled})
    assert refused.status_code == 403 and "no enrolled owner" in refused.text
    assert _memberships() == before
    import db
    with pytest.raises(ValueError):
        db.add_community_member("guarded-club", "someone", role="member", owner_pub=attacker_pub)
    assert _memberships() == before


def test_ambiguous_legacy_ownership_stays_unenrolled_with_zero_membership_writes(client):
    import db
    from tests.join_signing import _generate_keypair
    _, first_pub = _generate_keypair()
    old_priv, old_pub = _generate_keypair()
    a, _ = _user("old-a")
    b, _ = _user("old-b")
    _legacy_rows(("old-club", a, old_pub), ("old-club", b, old_pub), ("split-club", a, old_pub), ("split-club", b, first_pub))
    db.init_schema()  # a restart never derives an owner from those rows, even when they agree
    assert db.community_owner("old-club") is None and db.community_owner("split-club") is None
    _, h = _user("newcomer")
    before = _memberships()
    env, _ = _envelope("old-club", priv=old_priv, pub=old_pub)
    refused = client.post("/v1/community/join", headers=h, json={"envelope": env})
    assert refused.status_code == 403 and "no enrolled owner" in refused.text
    assert _memberships() == before


def test_competing_enrolments_are_refused_and_new_ids_are_allocated_to_their_creator(client):
    import db
    from tests.join_signing import _generate_keypair
    owner, _ = _user("owner")
    rival, _ = _user("rival")
    priv, pub = _generate_keypair()
    rival_priv, rival_pub = _generate_keypair()
    assert _recover("contested", owner, priv, pub) is True
    assert _recover("contested", rival, rival_priv, rival_pub) is False  # a competing enrolment changes nothing
    assert db.community_owner("contested")["owner_pub"] == pub
    # Possession of a key is required and bound to this account and id: a signature made for another proves nothing.
    with pytest.raises(ValueError):
        db.recover_community_owner("other-club", owner_user_id=owner["id"], owner_pub=rival_pub,
                                   signature=_enrol_signature(rival_priv, "other-club", rival["id"]))
    with pytest.raises(ValueError):
        db.recover_community_owner("other-club", owner_user_id="no-such-account", owner_pub=rival_pub,
                                   signature=_enrol_signature(rival_priv, "other-club", "no-such-account"))
    assert db.community_owner("other-club") is None
    # A new community: the cloud picks the id and binds it to the signed-in creator.
    _, ho = _user("creator")
    creator = db.user_for_token(ho["Authorization"].split()[1])
    cpriv, cpub = _generate_keypair()
    made = client.post("/v1/community/create", headers=ho, json={
        "owner_pub": cpub, "signature": _enrol_signature(cpriv, "new", creator["id"])}).json()
    enrolled = db.community_owner(made["community_id"])
    assert enrolled["owner_user_id"] == creator["id"] and enrolled["owner_pub"] == cpub
    assert made["community_keys"] == [made["community_id"]]
    stolen = client.post("/v1/community/create", headers=ho, json={
        "owner_pub": rival_pub, "signature": _enrol_signature(rival_priv, "new", rival["id"])})
    assert stolen.status_code == 403


def test_a_verified_join_code_opens_the_community_for_that_user(client):
    import db
    from tests.join_signing import _generate_keypair
    _, ho = _user("host")
    host = db.user_for_token(ho["Authorization"].split()[1])
    priv, pub = _generate_keypair()
    community = client.post("/v1/community/create", headers=ho, json={
        "owner_pub": pub, "signature": _enrol_signature(priv, "new", host["id"])}).json()["community_id"]
    env, _ = _envelope(community, priv=priv, pub=pub)
    u1, h1 = _user("a")
    u2, h2 = _user("b")
    assert client.post("/v1/community/join", headers=h1, json={"envelope": env}).json()["community_keys"] == [community]
    assert client.post("/v1/community/join", headers=h2, json={"envelope": env}).json()["joined"] is True
    r = client.post("/v1/brain/sync", headers=h1, json={"delta": {"fragments": [_community_fragment(community, "hello members")]}})
    assert r.status_code == 200 and r.json()["community_keys"] == [community], r.text
    assert not r.json()["rejected"], r.json()["rejected"]
    # Members pull a version once the founder review admits it (ADGR-0004,
    # test_community_review_gate); membership is what this court is about.
    for item in db.pending_community_versions():
        db.judge_community_version(item["community_id"], item["fragment_id"], item["hlc"],
                                   admit=True, decided_by="court")
    r2 = client.post("/v1/brain/sync", headers=h2, json={"delta": {"fragments": []}})
    texts = json.dumps(r2.json().get("merged") or {})
    assert "hello members" in texts
    bad = client.post("/v1/community/join", headers=h2, json={"envelope": "nope"})
    assert bad.status_code == 400


def test_held_legacy_rows_grant_no_replica_keys_even_after_owner_recovery(client):
    import db
    from tests.join_signing import _generate_keypair
    priv, pub = _generate_keypair()
    holder, h = _user("holder")
    _legacy_rows(("held-club", holder, pub))  # a row a self-asserted code once recorded, with the very key that is later enrolled
    assert db.list_community_keys_for_user(holder["id"]) == []
    keys, rejected = _sync_keys(client, h, "held-club")
    assert keys == [] and rejected, "an unverified row neither reads nor writes the shared replica"
    owner, _ = _user("owner")
    assert _recover("held-club", owner, priv, pub) is True
    assert db.list_community_keys_for_user(holder["id"]) == [], "a matching stored key does not attest how the row was made"
    keys, rejected = _sync_keys(client, h, "held-club")
    assert keys == [] and rejected


def test_a_validated_rejoin_upgrades_the_held_row_in_place(client):
    import db
    from tests.join_signing import _generate_keypair
    priv, pub = _generate_keypair()
    holder, h = _user("rejoin")
    _legacy_rows(("rejoin-club", holder, pub))
    owner, _ = _user("owner")
    assert _recover("rejoin-club", owner, priv, pub) is True
    env, _ = _envelope("rejoin-club", priv=priv, pub=pub)
    assert client.post("/v1/community/join", headers=h, json={"envelope": env}).status_code == 200
    with db.connect() as con:
        row = con.execute("SELECT joined_at, verified_by FROM community_members WHERE community_id = 'rejoin-club'"
                          " AND user_id = ?", (holder["id"],)).fetchone()
    assert tuple(row) == (1, "join"), "the held row is upgraded, not duplicated; its first join time is kept"
    keys, rejected = _sync_keys(client, h, "rejoin-club")
    assert keys == ["rejoin-club"] and not rejected


def test_the_default_sign_in_membership_still_grants_and_upgrades_a_held_row(client, monkeypatch):
    import auth
    import db
    monkeypatch.delenv("ARCHHUB_DEFAULT_COMMUNITY_ID", raising=False)
    fresh, _ = _user("fresh")
    auth.provision_brain(fresh["id"])
    assert db.list_community_keys_for_user(fresh["id"]) == [auth.DEFAULT_COMMUNITY_ID]
    held, _ = _user("held-default")
    _legacy_rows((auth.DEFAULT_COMMUNITY_ID, held, db.PLATFORM_COMMUNITY_OWNER))
    assert db.list_community_keys_for_user(held["id"]) == []
    auth.provision_brain(held["id"])  # the server's own sign-in path is the provenance of the default community
    assert db.list_community_keys_for_user(held["id"]) == [auth.DEFAULT_COMMUNITY_ID]