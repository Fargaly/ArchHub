"""Account-binding tests — local brain ⇄ cloud user_id (MAKE-IT-REAL).

Proves the binding is REAL end-to-end, not a stored string:

  1. Fresh store → default owner is the env/OS/'founder' fallback (unbound).
  2. brain.set_owner(user_id, email) → brain.get_owner reports bound=true and
     the cloud user_id, and validates a non-empty user_id.
  3. THE CORE PROOF: a fragment-writing tool (brain.skill_mint) called with NO
     owner_user, AFTER set_owner and WITHOUT any restart, persists a fragment
     whose owner_user == the bound cloud user_id (NOT 'founder'). This is what
     makes "a user's local brain is their account's brain" true: the binding
     GOVERNS ownership in-process.
  4. The binding persists across a daemon restart (new BrainStore + new server
     on the SAME db file still resolves the bound owner).
  5. brain.clear_owner reverts the default owner to the fallback; a NEW write is
     owned by the fallback again — but the alice-owned fragment from step 3
     REMAINS (clearing the binding never deletes data).

Tool invocation mirrors tests/test_cloud_archive_tool._call (FastMCP call_tool
+ payload unwrap) so it exercises the same path real MCP clients hit.
"""
from __future__ import annotations

from typing import Any

from personal_brain.server import build_server
from personal_brain.storage import BrainStore
from personal_brain.models import FragmentKind


def _call(mcp, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke an MCP tool via the in-house (sync) call_tool and unwrap the JSON
    payload. InHouseMCP returns the RESULT envelope as a plain dict, so we read
    structuredContent (with a text-content fallback)."""
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


def _server(store: BrainStore, owner: str = "founder"):
    return build_server(store=store, default_owner_user=owner)


# A trace that clears the skill_mint persistence gate (outcome=success AND
# >=2 successful tool_calls) so a TRACE fragment is written, stamped with the
# server-resolved default owner.
_GOOD_TRACE = {
    "trace_id": "t-owner-binding",
    "tool_calls": [
        {"name": "host.probe", "status": "ok"},
        {"name": "host.read", "status": "ok"},
        {"name": "host.write", "status": "ok"},
    ],
}


def _latest_trace_owner(store: BrainStore) -> str | None:
    frags = store.list_fragments(kinds=[FragmentKind.TRACE], limit=20)
    return frags[0].owner_user if frags else None


def test_fresh_store_is_unbound_and_defaults_to_fallback(tmp_path):
    """Unbound: get_owner reports the build fallback ('founder' here) and
    bound=false with a non-'bound' source."""
    store = BrainStore.open(str(tmp_path / "brain.db"))
    try:
        mcp = _server(store, owner="founder")
        owner = _call(mcp, "brain.get_owner")
        assert owner["ok"] is True
        assert owner["bound"] is False
        assert owner["owner_user"] == "founder"
        assert owner["source"] != "bound"
    finally:
        store.close()


def test_set_owner_validates_non_empty_user_id(tmp_path):
    """An empty / whitespace user_id is rejected and leaves the brain unbound."""
    store = BrainStore.open(str(tmp_path / "brain.db"))
    try:
        mcp = _server(store, owner="founder")
        resp = _call(mcp, "brain.set_owner", {"user_id": "   "})
        assert resp["ok"] is False
        assert "user_id" in resp["error"]
        assert _call(mcp, "brain.get_owner")["bound"] is False
    finally:
        store.close()


def test_set_owner_binds_and_get_owner_reports_it(tmp_path):
    store = BrainStore.open(str(tmp_path / "brain.db"))
    try:
        mcp = _server(store, owner="founder")
        resp = _call(mcp, "brain.set_owner", {
            "user_id": "u_abc123",
            "email": "alice@corp.com",
            "display_name": "Alice",
        })
        assert resp["ok"] is True
        assert resp["owner_user"] == "u_abc123"
        assert resp["previously"] is None  # first bind

        owner = _call(mcp, "brain.get_owner")
        assert owner["bound"] is True
        assert owner["owner_user"] == "u_abc123"
        assert owner["email"] == "alice@corp.com"
        assert owner["display_name"] == "Alice"
        assert owner["source"] == "bound"
    finally:
        store.close()


def test_binding_governs_fragment_ownership_in_process_without_restart(tmp_path):
    """CORE PROOF: after set_owner, a fragment written by a tool that falls
    back to the default owner (skill_mint, NO owner_user passed) is owned by
    the bound cloud user_id — proving the binding governs ownership live, in
    the SAME process, with NO restart."""
    store = BrainStore.open(str(tmp_path / "brain.db"))
    try:
        mcp = _server(store, owner="founder")

        # Bind to the cloud account.
        assert _call(mcp, "brain.set_owner", {
            "user_id": "u_abc123", "email": "alice@corp.com",
        })["ok"] is True

        # Write a fragment WITHOUT specifying owner_user — the server resolves
        # the default owner, which must now be the bound user_id.
        mint = _call(mcp, "brain.skill_mint", {
            "trace": _GOOD_TRACE, "outcome": "success",
        })
        assert mint.get("queued") in (True, False)  # tool ran (gate may pass/defer)

        # The persisted TRACE fragment is owned by the cloud user_id, NOT founder.
        assert _latest_trace_owner(store) == "u_abc123"
        founder_traces = [
            f for f in store.list_fragments(kinds=[FragmentKind.TRACE], limit=50)
            if f.owner_user == "founder"
        ]
        assert founder_traces == [], (
            "a fragment was written under 'founder' after binding — the bound "
            "owner did NOT govern ownership in-process"
        )

        # health surfaces the live binding for the desktop/founder to see.
        health = _call(mcp, "brain.health")
        assert health["owner"]["bound"] is True
        assert health["owner"]["owner_user"] == "u_abc123"
        assert health["owner_user_default"] == "u_abc123"
    finally:
        store.close()


def test_binding_persists_across_daemon_restart(tmp_path):
    """A new BrainStore + new server on the SAME db file still resolves the
    bound owner (the binding lives in brain_meta, not in process state)."""
    db = str(tmp_path / "brain.db")

    store1 = BrainStore.open(db)
    try:
        mcp1 = _server(store1, owner="founder")
        assert _call(mcp1, "brain.set_owner", {
            "user_id": "u_abc123", "email": "alice@corp.com",
        })["ok"] is True
    finally:
        store1.close()

    # Simulate daemon restart: brand-new store + server over the same file.
    store2 = BrainStore.open(db)
    try:
        mcp2 = _server(store2, owner="founder")
        owner = _call(mcp2, "brain.get_owner")
        assert owner["bound"] is True
        assert owner["owner_user"] == "u_abc123"
        assert owner["source"] == "bound"

        # And a fresh write under the restarted daemon is still alice's.
        _call(mcp2, "brain.skill_mint", {
            "trace": _GOOD_TRACE, "outcome": "success",
        })
        assert _latest_trace_owner(store2) == "u_abc123"
    finally:
        store2.close()


def test_clear_owner_reverts_default_but_keeps_data(tmp_path):
    """Sign-out: clear_owner reverts the default owner to the fallback; a NEW
    write is owned by the fallback — but the alice-owned fragment REMAINS."""
    store = BrainStore.open(str(tmp_path / "brain.db"))
    try:
        mcp = _server(store, owner="founder")

        # Bind + write one fragment as alice. The fragment id is content-
        # addressed (hash of the trace summary + session), so give alice's
        # write a distinct user_message + session_id from the post-clear one
        # below to guarantee two SEPARATE rows.
        _call(mcp, "brain.set_owner", {"user_id": "u_abc123", "email": "alice@corp.com"})
        alice_trace = dict(_GOOD_TRACE, user_message="alice session work")
        _call(mcp, "brain.skill_mint", {
            "trace": alice_trace, "outcome": "success", "session_id": "alice-1",
        })
        assert _latest_trace_owner(store) == "u_abc123"
        alice_frag_owner = {
            f.owner_user
            for f in store.list_fragments(kinds=[FragmentKind.TRACE], limit=50)
        }
        assert alice_frag_owner == {"u_abc123"}

        # Sign out.
        cleared = _call(mcp, "brain.clear_owner")
        assert cleared["ok"] is True
        assert cleared["previously"] == "u_abc123"
        assert cleared["owner_user"] == "founder"

        owner = _call(mcp, "brain.get_owner")
        assert owner["bound"] is False
        assert owner["owner_user"] == "founder"

        # A new write (distinct content + session → distinct fragment id) is
        # now owned by the fallback again.
        founder_trace = dict(_GOOD_TRACE, user_message="post-signout work")
        _call(mcp, "brain.skill_mint", {
            "trace": founder_trace, "outcome": "success", "session_id": "founder-1",
        })

        owners = {
            f.owner_user
            for f in store.list_fragments(kinds=[FragmentKind.TRACE], limit=50)
        }
        # Both owners coexist: alice's fragment survived the sign-out, and the
        # post-clear write landed under the fallback.
        assert "u_abc123" in owners, "alice's fragment was lost on sign-out"
        assert "founder" in owners, "post-clear write was not owned by fallback"
    finally:
        store.close()
