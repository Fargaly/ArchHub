"""Multi-device community — create / join-code / converge.

Covers the founder's 2026-06-01 goal: "create a community" + "join it from
a second device" + the two devices converging their brains.

Three layers, each an independent regression guard:

  1. UNIT — community_groups primitives: create makes the list non-empty;
     join-code signs, parses, verifies; tampering + expiry are rejected;
     the archhub:// URL form round-trips; the transport config rides in
     the code.

  2. CONVERGENCE — the END-TO-END multi-device proof (ANTI-LIE): device A
     creates a community + writes a COMMUNITY-scope fact; device B joins via
     A's join-code; B's SyncWorker (with the COMMUNITY scope_resolver, the
     same wiring workers.py ships) pulls A's community record, member roster,
     AND the shared fact through ONE JsonFileTransport — proving two devices
     on the same community would converge. A stub second peer (a second
     BrainStore) stands in for the laptop that isn't physically here.

  3. MCP — the tool surface real clients hit: create -> groups (non-empty) ->
     join_code -> join (second store) -> members -> set_transport -> leave,
     plus the owned-server Docker gate.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import pytest

from personal_brain import community_groups as cg
from personal_brain.hlc import reset_device_clock
from personal_brain.models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from personal_brain.storage import BrainStore
from personal_brain.sync import JsonFileTransport
from personal_brain.sync_worker import SyncWorker


# ─────────────────────── fixtures / helpers ────────────────────────────


@pytest.fixture(autouse=True)
def fresh_hlc():
    reset_device_clock()
    yield
    reset_device_clock()


def _community_fact(fid: str, text: str, owner: str, community_id: str) -> Fragment:
    """A COMMUNITY-scope fact a member shares with the rest of the group."""
    return Fragment(
        id=fid, kind=FragmentKind.FACT, text=text,
        scope=Scope.COMMUNITY, visibility=Visibility.SHARED_PUBLIC,
        owner_user=owner,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="test", contributing_user=owner,
            created_at=datetime.now(timezone.utc),
        ),
        extra={"community_id": community_id},
    )


# A scope_resolver mirroring workers._build_sync: sync COMMUNITY only when
# this device has joined a community.
def _community_scope_resolver(store: BrainStore):
    def _resolve():
        scopes = [Scope.FIRM, Scope.PROJECT]
        if cg.current_community_id(store):
            scopes.append(Scope.COMMUNITY)
        return scopes
    return _resolve


# ════════════════════════ 1. UNIT ══════════════════════════════════════


def test_create_makes_list_non_empty(tmp_path):
    store = BrainStore.open(str(tmp_path / "a.db"))
    try:
        assert cg.list_communities(store) == []
        c = cg.create_community(store, name="Studio Devices", created_by="founder")
        assert c.community_id.startswith("comm-")
        assert c.role == "owner"
        assert c.owner_priv  # creator holds the signing key locally

        comms = cg.list_communities(store)
        assert len(comms) == 1
        assert comms[0].community_id == c.community_id
        # current_community reflects it
        cur = cg.current_community(store)
        assert cur is not None and cur.community_id == c.community_id
        # owner is the first member
        members = cg.list_members(store)
        assert [m.member_id for m in members] == ["founder"]
        assert members[0].role == "owner"
    finally:
        store.close()


def test_transport_config_rides_in_membership_and_code(tmp_path):
    store = BrainStore.open(str(tmp_path / "a.db"))
    try:
        cg.create_community(
            store, name="Relay Group", created_by="founder",
            transport=cg.TransportConfig(
                kind="cloud_relay", base_url="https://cloud.archhub.io",
                note="owned relay",
            ),
        )
        cur = cg.current_community(store)
        assert cur.transport.kind == "cloud_relay"
        assert cur.transport.base_url == "https://cloud.archhub.io"

        code = cg.create_join_code(store)
        decoded, sig = cg.decode_join_code(code)
        assert decoded.transport.get("kind") == "cloud_relay"
        assert decoded.transport.get("base_url") == "https://cloud.archhub.io"
    finally:
        store.close()


def test_join_code_verify_good_tamper_expiry_url(tmp_path):
    store = BrainStore.open(str(tmp_path / "a.db"))
    try:
        cg.create_community(store, name="Verify Group", created_by="founder")

        code = cg.create_join_code(store, role="member", ttl_hours=168)
        # good
        decoded, ok, reason = cg.verify_join_code(code)
        assert ok is True and reason == "ok"
        assert decoded.role == "member"

        # URL form round-trips
        url = cg.join_url(code)
        assert url.startswith("archhub://community/join?code=")
        _, ok_url, _ = cg.verify_join_code(url)
        assert ok_url is True

        # tampered signature -> rejected
        tampered = code[:-4] + ("AAAA" if code[-4:] != "AAAA" else "BBBB")
        _, ok_t, reason_t = cg.verify_join_code(tampered)
        assert ok_t is False
        assert reason_t in ("signature mismatch", "malformed: " + reason_t.split(": ", 1)[-1])

        # tampered PAYLOAD (flip the community name) -> signature mismatch
        import base64 as _b64
        import json as _json
        payload_b64, sig = code.split(".", 1)
        payload = _json.loads(_b64.urlsafe_b64decode(payload_b64.encode()))
        payload["name"] = "Evil Renamed Group"
        new_b64 = _b64.urlsafe_b64encode(
            _json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).decode()
        forged = new_b64 + "." + sig
        _, ok_f, reason_f = cg.verify_join_code(forged)
        assert ok_f is False and reason_f == "signature mismatch"
    finally:
        store.close()


def test_join_code_expiry_rejected(tmp_path, monkeypatch):
    store = BrainStore.open(str(tmp_path / "a.db"))
    try:
        cg.create_community(store, name="Expiry Group", created_by="founder")
        # Issue a token that's already expired (negative ttl).
        code = cg.create_join_code(store, ttl_hours=-1)
        decoded, ok, reason = cg.verify_join_code(code)
        assert ok is False and reason == "expired"
    finally:
        store.close()


def test_join_code_requires_owner_priv(tmp_path):
    """A device that JOINED (no owner_priv) cannot mint a join-code."""
    owner_store = BrainStore.open(str(tmp_path / "owner.db"))
    joiner_store = BrainStore.open(str(tmp_path / "joiner.db"))
    try:
        cg.create_community(owner_store, name="No-Reissue", created_by="founder")
        code = cg.create_join_code(owner_store)
        cg.join_community(joiner_store, envelope=code, member_id="laptop")
        # Joiner has membership but no signing key.
        assert cg.current_community(joiner_store).owner_priv is None
        with pytest.raises(RuntimeError, match="not the community owner"):
            cg.create_join_code(joiner_store)
    finally:
        owner_store.close()
        joiner_store.close()


def test_leave_clears_membership(tmp_path):
    store = BrainStore.open(str(tmp_path / "a.db"))
    try:
        cg.create_community(store, name="Leavers", created_by="founder")
        assert cg.current_community(store) is not None
        cg.leave_community(store)
        assert cg.current_community(store) is None
        assert cg.current_community_id(store) is None
    finally:
        store.close()


# ════════════════════════ 2. CONVERGENCE (END-TO-END) ══════════════════


def test_two_devices_converge_on_community_scope(tmp_path):
    """THE multi-device proof. Device A creates a community + a shared fact;
    device B joins via the join-code; B's SyncWorker (community scope_resolver)
    pulls A's community record + roster + the shared fact through ONE shared
    transport. Then A pulls B's member row back — bidirectional convergence."""
    transport_path = tmp_path / "community-shared.json"
    a = BrainStore.open(str(tmp_path / "device-a.db"))
    b = BrainStore.open(str(tmp_path / "device-b.db"))
    try:
        # Device A creates the community + shares a COMMUNITY-scope fact.
        community = cg.create_community(
            a, name="Studio Fleet", created_by="founder",
            transport=cg.TransportConfig(kind="disk",
                                          base_url=str(transport_path)),
        )
        a.write_fragment(_community_fact(
            "shared-detail-1", "approved curtain-wall mullion spacing = 1500mm",
            "founder", community.community_id,
        ))

        # Device A pushes (community scope active because A is in a community).
        wa = SyncWorker(a, JsonFileTransport(transport_path),
                        interval_s=60, device_id="A",
                        scope_resolver=_community_scope_resolver(a))
        res_a = wa.tick()
        assert Scope.COMMUNITY.value in wa.status()["scopes"]
        assert res_a.ok

        # Device B receives the join-code (the laptop's one action) and joins.
        code = cg.create_join_code(a, role="member")
        joined = cg.join_community(b, envelope=code, member_id="laptop")
        assert joined.community_id == community.community_id
        assert joined.role == "member"
        # B adopted A's transport config from the code.
        assert joined.transport.kind == "disk"

        # Device B's worker pulls A's community-scope state.
        wb = SyncWorker(b, JsonFileTransport(transport_path),
                        interval_s=60, device_id="B", owner_user="laptop",
                        scope_resolver=_community_scope_resolver(b))
        res_b = wb.tick()
        assert Scope.COMMUNITY.value in wb.status()["scopes"]

        # CRITICAL: device B now has device A's shared COMMUNITY fact.
        got = b.get_fragment("shared-detail-1")
        assert got is not None, f"B should have A's shared fact; res={res_b}"
        assert "1500mm" in got.text
        assert got.scope == Scope.COMMUNITY

        # And B sees the community + the owner in its synced roster.
        comms_b = cg.list_communities(b)
        assert any(c.community_id == community.community_id for c in comms_b)
        members_b = {m.member_id for m in cg.list_members(b, community.community_id)}
        assert "founder" in members_b, f"B should see owner; got {members_b}"
        assert "laptop" in members_b, "B should see its own member row"

        # Bidirectional: A pulls B's member row back.
        wa2 = SyncWorker(a, JsonFileTransport(transport_path),
                         interval_s=60, device_id="A",
                         scope_resolver=_community_scope_resolver(a))
        wa2.tick()
        members_a = {m.member_id for m in cg.list_members(a, community.community_id)}
        assert "laptop" in members_a, (
            f"A should see B (laptop) after pulling; got {members_a}"
        )
    finally:
        a.close()
        b.close()


def test_community_scope_not_synced_before_join(tmp_path):
    """A device with no community must NOT widen its sync to COMMUNITY scope
    — the resolver only adds it once membership exists (cost-gating)."""
    store = BrainStore.open(str(tmp_path / "solo.db"))
    try:
        w = SyncWorker(store, JsonFileTransport(tmp_path / "s.json"),
                       interval_s=60, scope_resolver=_community_scope_resolver(store))
        assert Scope.COMMUNITY.value not in w.status()["scopes"]
        # After creating a community, the SAME worker widens its scope.
        cg.create_community(store, name="Now Joined", created_by="founder")
        assert Scope.COMMUNITY.value in w.status()["scopes"]
    finally:
        store.close()


# ════════════════════════ 3. MCP TOOL SURFACE ══════════════════════════


def _call(mcp, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke an MCP tool via the in-house (sync) call_tool + unwrap the dict
    payload (same helper shape as test_community_mcp_tools.py). InHouseMCP
    returns the RESULT envelope as a plain dict, so we read structuredContent
    (with a text-content fallback)."""
    result = mcp.call_tool(name, arguments or {})
    sc = result.get("structuredContent") if isinstance(result, dict) \
        else getattr(result, "structured_content", None)
    if sc is not None:
        return sc
    data = result.get("data") if isinstance(result, dict) \
        else getattr(result, "data", None)
    if data is not None:
        return data
    content = result.get("content") if isinstance(result, dict) \
        else getattr(result, "content", None)
    if content:
        import json as _json
        for item in content:
            txt = item.get("text") if isinstance(item, dict) \
                else getattr(item, "text", None)
            if txt:
                try:
                    return _json.loads(txt)
                except Exception:
                    continue
    raise AssertionError(f"unrecognised ToolResult shape: {result!r}")


def _server(tmp_path, name="brain.db"):
    from personal_brain.server import build_server
    store = BrainStore.open(str(tmp_path / name))
    mcp = build_server(store=store, default_owner_user="founder")
    return mcp, store


def test_mcp_create_then_groups_non_empty(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        # Before: groups list empty (distinct from the federation subscription list).
        before = _call(mcp, "brain.community_groups", {})
        assert before["ok"] is True
        assert before["communities"] == []
        assert before["current_community_id"] is None

        created = _call(mcp, "brain.community_create", {
            "name": "Founder Fleet",
            "transport_kind": "cloud_relay",
            "transport_base_url": "https://cloud.archhub.io",
        })
        assert created["ok"] is True
        assert created["is_owner"] is True
        cid = created["community"]["community_id"]
        assert cid.startswith("comm-")
        assert created["community"]["transport"]["kind"] == "cloud_relay"
        # owner_priv must NEVER be exposed over the tool surface.
        assert "owner_priv" not in created["community"]

        after = _call(mcp, "brain.community_groups", {})
        assert after["current_community_id"] == cid
        assert any(c["community_id"] == cid for c in after["communities"])
    finally:
        store.close()


def test_mcp_join_code_and_join_second_device(tmp_path):
    """Owner mints a code on store A; a second store B joins with it via the
    tool surface; B's groups list shows the community + B is not owner."""
    mcp_a, store_a = _server(tmp_path, "a.db")
    mcp_b, store_b = _server(tmp_path, "b.db")
    try:
        _call(mcp_a, "brain.community_create", {"name": "Linked", "transport_kind": "disk"})
        code_resp = _call(mcp_a, "brain.community_join_code", {"role": "member"})
        assert code_resp["ok"] is True
        assert "." in code_resp["token"]
        assert code_resp["url"].startswith("archhub://community/join?code=")

        # Second device joins using the URL form.
        joined = _call(mcp_b, "brain.community_join", {
            "code": code_resp["url"], "member_id": "laptop",
        })
        assert joined["ok"] is True
        assert joined["is_owner"] is False
        groups_b = _call(mcp_b, "brain.community_groups", {})
        assert groups_b["current_community_id"] == joined["community"]["community_id"]

        # B cannot mint a code (no signing key) — honest error, not a crash.
        bad = _call(mcp_b, "brain.community_join_code", {})
        assert bad["ok"] is False
        assert "owner" in bad["error"]
    finally:
        store_a.close()
        store_b.close()


def test_mcp_join_bad_code_returns_error(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        resp = _call(mcp, "brain.community_join", {"code": "not-a-real-code"})
        assert resp["ok"] is False
        assert "error" in resp
    finally:
        store.close()


def test_mcp_set_transport_and_leave(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        _call(mcp, "brain.community_create", {"name": "Switchable", "transport_kind": "disk"})
        upgraded = _call(mcp, "brain.community_set_transport", {
            "transport_kind": "speckle",
            "transport_base_url": "http://localhost:3000",
        })
        assert upgraded["ok"] is True
        assert upgraded["community"]["transport"]["kind"] == "speckle"

        left = _call(mcp, "brain.community_leave", {})
        assert left["ok"] is True
        after = _call(mcp, "brain.community_groups", {})
        assert after["current_community_id"] is None
    finally:
        store.close()


def test_mcp_members_lists_owner(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        _call(mcp, "brain.community_create", {"name": "Roster", "transport_kind": "disk"})
        members = _call(mcp, "brain.community_members", {})
        assert members["ok"] is True
        ids = [m["member_id"] for m in members["members"]]
        assert "founder" in ids
        assert members["members"][0]["role"] == "owner"
    finally:
        store.close()


# ════════════════════════ owned-server gate ════════════════════════════


def test_mcp_owned_server_reports_docker_gate(tmp_path):
    """The owned-server tool must return one of the three honest codes and
    a non-empty message — never crash, never fabricate 'running'."""
    mcp, store = _server(tmp_path)
    try:
        resp = _call(mcp, "brain.community_owned_server", {
            "base_url": "http://localhost:59999",  # nothing runs here
        })
        assert resp["ok"] is True
        assert resp["code"] in ("running", "ready_to_start", "docker_missing")
        assert isinstance(resp["reachable"], bool)
        assert isinstance(resp["docker_available"], bool)
        assert resp["message"]
        # An unreachable port + no docker on this box -> docker_missing path,
        # and can_start must be False in that case.
        if not resp["docker_available"]:
            assert resp["code"] == "docker_missing"
            assert resp["can_start"] is False
    finally:
        store.close()


def test_owned_server_readiness_direct():
    """Unit-level: readiness() never raises + the code matches the gate."""
    from personal_brain import owned_server as osv
    report = osv.readiness("http://localhost:59998")
    assert report["code"] in ("running", "ready_to_start", "docker_missing")
    # docker_available() is pure stdlib + must return a bool without raising.
    assert isinstance(osv.docker_available(), bool)
    assert isinstance(osv.server_reachable("http://localhost:59998"), bool)
