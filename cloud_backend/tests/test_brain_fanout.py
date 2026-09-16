"""Tests — Slice 17 cloud fanout: firm + community scope converge across
devices/members through SHARED replicas, while USER scope stays private.

What the fanout must guarantee (and these tests pin):
  1. FIRM scope fans out across firm-mates. Two users in the SAME cloud
     company push FIRM-scope fragments; each reads back the OTHER's.
  2. A second DEVICE of the same user pulls the firm/community facts the
     first device pushed (the founder's "join from a 2nd device" goal).
  3. COMMUNITY scope converges through a shared per-community replica keyed
     by community_id (the cloud_relay transport).
  4. USER scope stays PRIVATE per user — the fanout does NOT leak a user's
     USER-scope facts to a firm-mate (the per-user-isolation contract).
  5. The HLC/CRDT merge is idempotent + commutative: re-applying a delta
     adds no duplicate; the highest-HLC write wins regardless of order.
  6. Migration safety: a pre-Slice-17 replica (a bare per-user brain.db with
     only USER rows + no firm/community dirs) still opens + exports cleanly,
     and the new shared dirs are additive (never touch existing user dirs).

These run at the BrainReplica + HTTP layer. The HTTP tests reuse the
`/v1/brain/sync` route so the server wiring (firm-mate resolution) is
exercised end-to-end, not just the primitive.
"""
from __future__ import annotations

import sqlite3
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


def _user(suffix: str = "") -> tuple[dict, dict]:
    import db
    email = f"fanout+{suffix or uuid.uuid4().hex[:6]}@example.com"
    u = db.get_or_create_user(email)
    token = db.issue_token(u["id"])
    return u, {"Authorization": f"Bearer {token}"}


def _join(client, headers, community_id):
    """Membership is what the cloud verified from the owner's signed join-code,
    never a key named on the wire (2026-09-04 audit finding 23)."""
    import base64, time, uuid
    sys.path.insert(0, str(BACKEND_ROOT.parent / "personal-brain-mcp" / "src"))
    from personal_brain.firm import _generate_keypair, _sign
    from community_join import _payload_bytes
    priv, pub = _generate_keypair()
    now = time.time()
    data = {"community_id": community_id, "name": "Court", "owner_pub": pub, "role": "member",
            "transport": {}, "issued_by": "owner", "issued_at": now, "expires_at": now + 3600,
            "nonce": uuid.uuid4().hex[:12]}
    payload = _payload_bytes(data)
    env = base64.urlsafe_b64encode(payload).decode() + "." + _sign(priv, payload)
    r = client.post("/v1/community/join", headers=headers, json={"envelope": env})
    assert r.status_code == 200, r.text


def _frag(fid, scope, text, hlc, **extra):
    f = {"id": fid, "kind": "fact", "text": text, "scope": scope, "hlc": hlc}
    f.update(extra)
    return f


# ===========================================================================
# 1 + 4. FIRM fans out across firm-mates; USER stays private — HTTP level
# ===========================================================================
class TestFirmFanoutCrossMember:
    def test_two_firm_members_see_each_others_firm_facts_not_user_facts(
        self, client, replicas_root,
    ):
        import db
        owner, ho = _user("firmowner")
        mate, hm = _user("firmmate")
        company = db.create_company(name="Studio Foo", owner_user_id=owner["id"])
        db.add_company_member(company_id=company["id"], user_id=mate["id"])
        firm_key = company["id"]

        # Owner pushes ONE firm fact + ONE private user fact.
        client.post("/v1/brain/sync", headers=ho, json={"delta": {"fragments": [
            _frag("firm-A", "firm", "ACME standard detail set",
                  "0000000000000001.aaaaaaaa", firm_id=firm_key),
            _frag("user-A", "user", "owner private note",
                  "0000000000000001.aaaaaaab"),
        ]}})
        # Mate pushes a different firm fact + its own private user fact.
        rb = client.post("/v1/brain/sync", headers=hm, json={"delta": {"fragments": [
            _frag("firm-B", "firm", "Firm wall type library",
                  "0000000000000002.bbbbbbbb", firm_id=firm_key),
            _frag("user-B", "user", "mate private note",
                  "0000000000000002.bbbbbbbc"),
        ]}}).json()

        # Mate's merged view: BOTH firm facts (cross-member convergence)…
        mate_ids = {f["id"] for f in rb["merged"]["fragments"]}
        assert "firm-A" in mate_ids, "firm fact from the OTHER member must converge"
        assert "firm-B" in mate_ids
        # …its OWN user fact…
        assert "user-B" in mate_ids
        # …but NOT the owner's PRIVATE user fact.
        assert "user-A" not in mate_ids, "USER scope must NOT leak across members"

        # Owner reads back (empty push) → sees both firm facts + own user note,
        # never the mate's private user note.
        ra = client.post("/v1/brain/sync", headers=ho,
                         json={"delta": {"fragments": []}}).json()
        owner_ids = {f["id"] for f in ra["merged"]["fragments"]}
        assert {"firm-A", "firm-B", "user-A"} <= owner_ids
        assert "user-B" not in owner_ids

        # The firm fact's contributing owner_user is PRESERVED (not flattened
        # to the reader) — that is how a teammate is attributable.
        firm_b = next(f for f in ra["merged"]["fragments"] if f["id"] == "firm-B")
        assert firm_b["owner_user"] == mate["id"]

    def test_solo_user_with_no_company_keeps_private_backup(self, client):
        # A user in NO company has an empty firm read-set: pushing a firm
        # fragment routes to a shared replica keyed by its firm_id, and the
        # user reads it back via the touched-keys round-trip, but no OTHER
        # user can reach it. (Pure-backup posture for solo users preserved.)
        solo, hs = _user("solo")
        r = client.post("/v1/brain/sync", headers=hs, json={"delta": {"fragments": [
            _frag("solo-firm", "firm", "solo firm note",
                  "0000000000000001.aaaaaaaa", firm_id="local-firm-xyz"),
        ]}}).json()
        # Firm writes obey the server-resolved company membership (security
        # closure 2026-09-03): a solo user names no company, so the firm
        # fragment is refused -- and nothing else of theirs is touched.
        assert any("firm" in (x.get("reason") or "") for x in r["rejected"]), r["rejected"]
        ids = {f["id"] for f in r["merged"]["fragments"]}
        assert "solo-firm" not in ids


# ===========================================================================
# 2. Second device of the SAME user pulls device-1's firm/community facts
# ===========================================================================
class TestSecondDevice:
    def test_second_device_same_account_pulls_firm_and_community(
        self, client,
    ):
        # Same account, two devices = same bearer/user_id. Device 1 pushes
        # firm + community facts; device 2 (empty push) pulls them.
        user, h = _user("multidev")
        _join(client, h, "comm-foo-123")
        import db
        firm_k = db.create_company(name="Studio K", owner_user_id=user["id"])["id"]
        client.post("/v1/brain/sync", headers=h, json={"delta": {"fragments": [
            _frag("dev1-firm", "firm", "firm-wide note",
                  "0000000000000001.aaaaaaaa", firm_id=firm_k),
            _frag("dev1-comm", "community", "community pattern",
                  "0000000000000001.aaaaaaab",
                  extra={"community_id": "comm-foo-123"}),
            _frag("dev1-user", "user", "device-1 private",
                  "0000000000000001.aaaaaaac"),
        ]}})
        # Device 2 declares the community it belongs to (join-code authorised
        # it client-side) and pulls.
        r2 = client.post("/v1/brain/sync", headers=h, json={
            "delta": {"fragments": []},
            "community_keys": ["comm-foo-123"],
        }).json()
        ids = {f["id"] for f in r2["merged"]["fragments"]}
        assert "dev1-firm" in ids
        assert "dev1-comm" in ids
        assert "dev1-user" in ids  # same user → own USER replica is shared


# ===========================================================================
# 3. COMMUNITY converges across DIFFERENT members through shared replica
# ===========================================================================
class TestCommunityFanout:
    def test_community_members_converge(self, client):
        a, ha = _user("commA")
        b, hb = _user("commB")
        cid = "comm-bar-777"
        _join(client, ha, cid)
        _join(client, hb, cid)
        # Member A contributes a community fragment.
        client.post("/v1/brain/sync", headers=ha, json={
            "delta": {"fragments": [
                _frag("commfrag-A", "community", "shared community fact",
                      "0000000000000001.aaaaaaaa",
                      extra={"community_id": cid})]},
            "community_keys": [cid],
        })
        # Member B (different user/token) names the same community + pulls.
        rb = client.post("/v1/brain/sync", headers=hb, json={
            "delta": {"fragments": []},
            "community_keys": [cid],
        }).json()
        ids = {f["id"] for f in rb["merged"]["fragments"]}
        assert "commfrag-A" in ids, "community fact must cross to another member"

    def test_unknown_community_member_cannot_read(self, client):
        # A user who does NOT name the community key never sees its fragments.
        a, ha = _user("commowner2")
        outsider, ho = _user("outsider")
        cid = "comm-secret-999"
        _join(client, ha, cid)
        client.post("/v1/brain/sync", headers=ha, json={
            "delta": {"fragments": [
                _frag("secretfrag", "community", "members-only",
                      "0000000000000001.aaaaaaaa",
                      extra={"community_id": cid})]},
            "community_keys": [cid],
        })
        # Outsider doesn't list the community → empty community read-set.
        ro = client.post("/v1/brain/sync", headers=ho,
                         json={"delta": {"fragments": []}}).json()
        ids = {f["id"] for f in ro["merged"]["fragments"]}
        assert "secretfrag" not in ids


# ===========================================================================
# 5. Idempotent + commutative HLC merge — replica primitive level
# ===========================================================================
class TestMergeIdempotent:
    def test_reapply_same_delta_no_duplicate(self, replicas_root):
        import brain_replica
        rep = brain_replica.BrainReplica.open_shared(
            "firm", "firm-idem", root=replicas_root)
        delta = {"fragments": [
            _frag("x1", "firm", "v1", "0000000000000001.aaaaaaaa",
                  firm_id="firm-idem", owner_user="u-1")]}
        r1 = rep.apply_delta(delta)
        r2 = rep.apply_delta(delta)  # identical re-apply
        assert r1["accepted"] == 1 and r2["accepted"] == 1
        rows = rep._own_fragments("0000000000000000.00000000")
        assert len([f for f in rows if f["id"] == "x1"]) == 1, "no duplicate row"
        assert next(f for f in rows if f["id"] == "x1")["text"] == "v1"

    def test_last_writer_wins_regardless_of_order(self, replicas_root):
        import brain_replica
        lo = _frag("y1", "firm", "older", "0000000000000001.aaaaaaaa",
                   firm_id="f", owner_user="u-1")
        hi = _frag("y1", "firm", "newer", "0000000000000009.zzzzzzzz",
                   firm_id="f", owner_user="u-1")

        # Apply hi THEN lo — lo must NOT clobber hi (LWW by HLC).
        rep1 = brain_replica.BrainReplica.open_shared(
            "firm", "firm-lww1", root=replicas_root)
        rep1.apply_delta({"fragments": [hi]})
        rep1.apply_delta({"fragments": [lo]})
        v1 = next(f for f in rep1._own_fragments("0") if f["id"] == "y1")
        assert v1["text"] == "newer"

        # Apply lo THEN hi — converges to the same winner (commutative).
        rep2 = brain_replica.BrainReplica.open_shared(
            "firm", "firm-lww2", root=replicas_root)
        rep2.apply_delta({"fragments": [lo]})
        rep2.apply_delta({"fragments": [hi]})
        v2 = next(f for f in rep2._own_fragments("0") if f["id"] == "y1")
        assert v2["text"] == "newer"
        assert v1["text"] == v2["text"]


# ===========================================================================
# 6. Migration safety — pre-Slice-17 replicas unbroken; dirs additive
# ===========================================================================
class TestMigrationSafety:
    def test_legacy_user_only_replica_opens_and_exports(
        self, client, replicas_root,
    ):
        # Simulate a pre-fanout replica: a bare per-user brain.db that only
        # ever held USER rows, with NO firm/ or community/ sibling dirs.
        user, h = _user("legacy")
        # First sync creates the user replica the old way (user-only fact).
        client.post("/v1/brain/sync", headers=h, json={"delta": {"fragments": [
            _frag("legacy-fact", "user", "pre-existing user note",
                  "0000000000000001.aaaaaaaa")]}})
        user_dir = replicas_root / user["id"]
        assert (user_dir / "brain.db").exists()
        # No shared dirs were created by a USER-only push.
        assert not (replicas_root / "firm").exists()
        assert not (replicas_root / "community").exists()
        # Re-open + export still works and returns the legacy fact.
        r = client.post("/v1/brain/sync", headers=h,
                        json={"delta": {"fragments": []}}).json()
        assert "legacy-fact" in {f["id"] for f in r["merged"]["fragments"]}

    def test_shared_dirs_do_not_touch_existing_user_dirs(
        self, replicas_root,
    ):
        import brain_replica
        # An existing user replica with a real row.
        u = brain_replica.BrainReplica.open("u_existing_123", root=replicas_root)
        u.apply_delta({"fragments": [
            _frag("keep", "user", "keep me", "0000000000000001.aaaaaaaa")]})
        before = (replicas_root / "u_existing_123" / "brain.db").read_bytes()

        # Opening + writing a firm replica must not perturb the user dir.
        f = brain_replica.BrainReplica.open_shared(
            "firm", "u_existing_123", root=replicas_root)  # same-looking key!
        f.apply_delta({"fragments": [
            _frag("firmrow", "firm", "firm", "0000000000000001.bbbbbbbb",
                  firm_id="u_existing_123", owner_user="x")]})
        # Firm replica lives under firm/<key>/, NOT the user dir.
        assert (replicas_root / "firm" / "u_existing_123" / "brain.db").exists()
        # The user replica still has its row and is byte-identical (untouched).
        rows = u._own_fragments("0")
        assert "keep" in {r["id"] for r in rows}
        after = (replicas_root / "u_existing_123" / "brain.db").read_bytes()
        assert before == after, "user replica db must be untouched by firm write"

    def test_path_traversal_key_cannot_escape_root(self, replicas_root):
        import brain_replica
        # A traversal-looking key is sanitised to a safe slug that stays
        # WITHIN the replicas root (the real security invariant) — it never
        # writes outside firm/. A pure-traversal key (only dots/slashes)
        # raises rather than resolving to an empty dir.
        rep = brain_replica.BrainReplica.open_shared(
            "firm", "../escape", root=replicas_root)
        resolved = rep.db_path.resolve()
        firm_root = (replicas_root / "firm").resolve()
        assert str(resolved).startswith(str(firm_root)), "must stay under firm/"
        with pytest.raises(ValueError):
            brain_replica.BrainReplica.open_shared("firm", "../..",
                                                   root=replicas_root)


# ===========================================================================
# 7. C-F0 - a contributed firm key is HISTORY, not a membership: removing a
#    member ends their READ of the firm replica on every read path.
# ===========================================================================
def _paid_user(suffix: str = "", plan: str = "studio") -> tuple[dict, dict]:
    """`_user` on a tier inside BRAIN_SHARED_SCOPE_PLANS, so the portal reads
    (/v1/brain/facts|search|stats and /mcp) exercise the shared-scope union."""
    import db
    u, h = _user(suffix)
    db.update_user_plan(u["id"], plan=plan)
    return db.get_or_create_user(u["email"]), h


def _mcp_fact_texts(client, headers) -> set[str]:
    """The account brain over MCP (POST /mcp) - it reads through
    main._brain_read_replica, so it obeys the same membership law."""
    import json
    r = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "brain.list_facts", "arguments": {"limit": 200}}})
    assert r.status_code == 200, r.text
    data = [ln for ln in r.text.splitlines() if ln.startswith("data: ")][0][6:]
    payload = json.loads(json.loads(data)["result"]["content"][0]["text"])
    return {f["text"] for f in payload["facts"]}


def _all_reads(client, headers) -> dict:
    """Every firm READ path in one call: the sync merge, the facts list, the
    search pool, the stats scope histogram, and the MCP tool surface."""
    sync = client.post("/v1/brain/sync", headers=headers,
                       json={"delta": {"fragments": []}})
    assert sync.status_code == 200, sync.text
    facts = client.get("/v1/brain/facts?limit=200", headers=headers)
    assert facts.status_code == 200, facts.text
    search = client.get("/v1/brain/search?q=firmsecret&limit=200",
                        headers=headers)
    assert search.status_code == 200, search.text
    stats = client.get("/v1/brain/stats", headers=headers)
    assert stats.status_code == 200, stats.text
    return {
        "sync":   {f["id"] for f in sync.json()["merged"]["fragments"]},
        "facts":  {f["id"] for f in facts.json()["results"]},
        "search": {f["id"] for f in search.json()["results"]},
        "scopes": stats.json()["by_scope"],
        "mcp":    _mcp_fact_texts(client, headers),
    }


class TestRemovedMemberLosesFirmRead:
    """`contributed_firm_keys` only records that a user once pushed into a
    firm. Every read re-checks `company_members`, so a removed member stops
    reading the firm replica the moment the membership row is gone."""

    def _firm_with_fact(self, client):
        import db
        owner, ho = _paid_user("cf0owner")
        member, hm = _paid_user("cf0member")
        mate, hc = _paid_user("cf0mate")
        cid = db.create_company(name="Studio CF0",
                                owner_user_id=owner["id"])["id"]
        db.add_company_member(company_id=cid, user_id=member["id"])
        db.add_company_member(company_id=cid, user_id=mate["id"])
        pushed = client.post("/v1/brain/sync", headers=hm, json={"delta": {
            "fragments": [
                _frag("cf0-firm", "firm", "firmsecret detail set",
                      "0000000000000001.aaaaaaaa", firm_id=cid),
                _frag("cf0-own", "user", "member private note",
                      "0000000000000001.aaaaaaab"),
            ]}})
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["rejected"] == []
        return cid, (owner, ho), (member, hm), (mate, hc)

    def test_removed_member_reads_no_firm_fact_on_any_path(self, client):
        import brain_replica
        import db
        cid, (owner, ho), (member, hm), _mate = self._firm_with_fact(client)
        # Baseline: while a member, they read it.
        assert "cf0-firm" in _all_reads(client, hm)["sync"]
        # And the durable contribution record - the thing that used to grant
        # the read forever - is present.
        assert cid in brain_replica.BrainReplica.open(
            user_id=member["id"]).contributed_firm_keys()

        r = client.delete(f"/v1/companies/{cid}/members/{member['id']}",
                          headers=ho)
        assert r.status_code == 200, r.text
        assert db.get_membership(cid, member["id"]) is None

        after = _all_reads(client, hm)
        assert "cf0-firm" not in after["sync"], "sync must drop the firm fact"
        assert "cf0-firm" not in after["facts"]
        assert "cf0-firm" not in after["search"]
        assert "firm" not in after["scopes"], after["scopes"]
        assert "firmsecret detail set" not in after["mcp"]
        # Still theirs: their own USER-scope fact is untouched.
        assert "cf0-own" in after["sync"] and "cf0-own" in after["facts"]

    def test_current_member_still_reads_the_firm_fact(self, client):
        # Positive control: revoking one member must not blind the others.
        cid, (owner, ho), (member, hm), (mate, hc) = self._firm_with_fact(client)
        assert client.delete(
            f"/v1/companies/{cid}/members/{member['id']}",
            headers=ho).status_code == 200
        still = _all_reads(client, hc)
        assert "cf0-firm" in still["sync"]
        assert "cf0-firm" in still["facts"]
        assert "cf0-firm" in still["search"]
        assert still["scopes"].get("firm") == 1
        assert "firmsecret detail set" in still["mcp"]

    def test_re_added_member_reads_again(self, client):
        # The membership table is the authority in BOTH directions: this is a
        # live re-check, not a tombstone burned onto the contributed key.
        import db
        cid, (owner, ho), (member, hm), _mate = self._firm_with_fact(client)
        client.delete(f"/v1/companies/{cid}/members/{member['id']}", headers=ho)
        assert "cf0-firm" not in _all_reads(client, hm)["facts"]
        db.add_company_member(company_id=cid, user_id=member["id"])
        assert "cf0-firm" in _all_reads(client, hm)["facts"]

    def test_removed_member_firm_write_still_refused(self, client):
        # Write-side law unchanged (2026-09-03 closure), so the read cannot be
        # re-earned by pushing into the firm again.
        cid, (owner, ho), (member, hm), _mate = self._firm_with_fact(client)
        client.delete(f"/v1/companies/{cid}/members/{member['id']}", headers=ho)
        r = client.post("/v1/brain/sync", headers=hm, json={"delta": {
            "fragments": [_frag("cf0-late", "firm", "late write",
                                "0000000000000002.aaaaaaaa", firm_id=cid)]}}).json()
        assert any("not a member" in (x.get("reason") or "")
                   for x in r["rejected"]), r["rejected"]
        assert "cf0-late" not in {f["id"] for f in r["merged"]["fragments"]}
