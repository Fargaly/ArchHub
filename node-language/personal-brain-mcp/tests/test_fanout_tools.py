"""Tests — Slice-17 cloud-fanout brain tools: brain.fanout_export +
brain.fanout_apply.

These are the desktop's brain-side surface for the cloud fanout:
  * fanout_export enumerates RAW USER/FIRM/COMMUNITY rows (no DP gate —
    distinct from brain.dataset_export which routes COMMUNITY to DP
    aggregates) so the desktop can push them to /v1/brain/sync.
  * fanout_apply writes pulled FIRM/COMMUNITY rows back via the store's CRDT
    upsert (the SyncWorker inbound pattern), NOT brain.write — so a direct
    community write isn't refused by the promote/redaction ACL gate. The
    merge is idempotent + last-writer-wins by HLC.

Driven through FastMCP `call_tool` — the same path the desktop daemon hits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from personal_brain.server import build_server
from personal_brain.models import (
    Confidence, Fragment, FragmentKind, Provenance, Scope, Visibility,
)
from personal_brain.storage import BrainStore


def _call(mcp, name: str, arguments: dict[str, Any] | None = None) -> dict:
    # InHouseMCP.call_tool is SYNCHRONOUS and returns the RESULT envelope as a
    # plain dict; read structuredContent (with a text-content fallback).
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


def _server(tmp_path):
    store = BrainStore.open(str(tmp_path / "brain.db"))
    mcp = build_server(store=store, default_owner_user="founder")
    return mcp, store


def _seed(store, fid, scope, *, firm_id=None, community_id=None,
          owner="founder", vis=Visibility.PRIVATE):
    extra = {"community_id": community_id} if community_id else {}
    store.write_fragment(Fragment(
        id=fid, kind=FragmentKind.FACT, text=f"{fid} body",
        scope=scope, visibility=vis, owner_user=owner,
        firm_id=firm_id, confidence=Confidence.EXTRACTED,
        provenance=Provenance(contributing_agent="t", contributing_user=owner,
                              created_at=datetime.now(timezone.utc)),
        extra=extra,
    ))


# ---------------------------------------------------------------------------
# fanout_export
# ---------------------------------------------------------------------------
def test_fanout_export_returns_raw_user_firm_community_rows(tmp_path):
    mcp, store = _server(tmp_path)
    try:
        _seed(store, "u1", Scope.USER)
        _seed(store, "f1", Scope.FIRM, firm_id="firm-X",
              vis=Visibility.SHARED_PROJECT)
        _seed(store, "c1", Scope.COMMUNITY, community_id="comm-1",
              vis=Visibility.SHARED_PUBLIC)
        resp = _call(mcp, "brain.fanout_export",
                     {"scopes": ["user", "firm", "community"]})
        assert resp["ok"] is True
        # RAW rows for all three scopes (NOT DP aggregates).
        ids = {f["id"] for f in resp["fragments"]}
        assert ids == {"u1", "f1", "c1"}
        scopes = {f["scope"] for f in resp["fragments"]}
        assert scopes == {"user", "firm", "community"}
        # Every row carries a fixed-width comparable HLC string.
        for f in resp["fragments"]:
            assert isinstance(f["hlc"], str) and len(f["hlc"]) == 16
        # community_id rides in extra (so the cloud can key its replica).
        c1 = next(f for f in resp["fragments"] if f["id"] == "c1")
        assert c1["extra"].get("community_id") == "comm-1"
    finally:
        store.close() if hasattr(store, "close") else None


def test_fanout_export_refuses_global_scope(tmp_path):
    mcp, store = _server(tmp_path)
    resp = _call(mcp, "brain.fanout_export", {"scopes": ["global"]})
    assert resp["ok"] is False
    assert "global" in resp["error"].lower()


def test_fanout_export_user_scope_gated_to_owner(tmp_path):
    # A USER row owned by someone else must not export under our owner.
    mcp, store = _server(tmp_path)
    _seed(store, "mine", Scope.USER, owner="founder")
    _seed(store, "theirs", Scope.USER, owner="someone-else")
    resp = _call(mcp, "brain.fanout_export",
                 {"scopes": ["user"], "owner_user": "founder"})
    ids = {f["id"] for f in resp["fragments"]}
    assert "mine" in ids
    assert "theirs" not in ids, "USER scope export is owner-gated"


# ---------------------------------------------------------------------------
# fanout_apply — inbound merge, idempotent + LWW
# ---------------------------------------------------------------------------
def test_fanout_apply_writes_firm_community_and_is_idempotent(tmp_path):
    mcp, store = _server(tmp_path)
    rows = [
        {"id": "rf", "kind": "fact", "text": "remote firm",
         "scope": "firm", "visibility": "shared_project",
         "owner_user": "teammate", "firm_id": "firm-Z",
         "confidence": "extracted", "extra": {}, "hlc": f"{100:016x}"},
        {"id": "rc", "kind": "fact", "text": "remote community",
         "scope": "community", "visibility": "shared_public",
         "owner_user": "peer", "firm_id": None,
         "confidence": "extracted", "extra": {"community_id": "comm-9"},
         "hlc": f"{100:016x}"},
    ]
    r1 = _call(mcp, "brain.fanout_apply", {"fragments": rows})
    assert r1["ok"] is True
    assert r1["applied"] == 2 and r1["skipped"] == 0
    # The rows landed in the local store with their owner_user preserved.
    assert store.get_fragment("rf").owner_user == "teammate"
    assert store.get_fragment("rc").scope == Scope.COMMUNITY
    # Re-applying the SAME delta is a no-op (idempotent LWW skip).
    r2 = _call(mcp, "brain.fanout_apply", {"fragments": rows})
    assert r2["applied"] == 0 and r2["skipped"] == 2


def test_fanout_apply_last_writer_wins_by_hlc(tmp_path):
    mcp, store = _server(tmp_path)
    base = {"id": "x", "kind": "fact", "scope": "firm",
            "visibility": "shared_project", "owner_user": "u",
            "firm_id": "f", "confidence": "extracted", "extra": {}}
    # Apply newer first, then older — older must NOT clobber newer.
    _call(mcp, "brain.fanout_apply", {"fragments": [
        {**base, "text": "newer", "hlc": f"{900:016x}"}]})
    r = _call(mcp, "brain.fanout_apply", {"fragments": [
        {**base, "text": "older", "hlc": f"{100:016x}"}]})
    assert r["skipped"] == 1 and r["applied"] == 0
    assert store.get_fragment("x").text == "newer"
    # A strictly-newer write DOES win.
    _call(mcp, "brain.fanout_apply", {"fragments": [
        {**base, "text": "newest", "hlc": f"{9999:016x}"}]})
    assert store.get_fragment("x").text == "newest"


def test_fanout_apply_refuses_user_scope(tmp_path):
    # USER rows are the account's own private state — never fanned in.
    mcp, store = _server(tmp_path)
    r = _call(mcp, "brain.fanout_apply", {"fragments": [
        {"id": "u-no", "kind": "fact", "text": "x", "scope": "user",
         "visibility": "private", "owner_user": "u", "confidence": "extracted",
         "extra": {}, "hlc": f"{1:016x}"}]})
    assert r["applied"] == 0 and r["refused"] == 1
    assert store.get_fragment("u-no") is None
