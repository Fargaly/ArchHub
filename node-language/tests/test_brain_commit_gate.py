"""Tests for the no-brain-on-commit floor (tools/brain_commit_gate.py, AgDR-0050).

The gate codifies BRAIN-FIRST's "no brain.write = extra scrutiny" clause into a
commit-time check. These tests pin its four contract guarantees:

  1. touches-app/payload  → the gate runs the brain check.
  2. no app/payload paths  → the gate SKIPS (exit 0, no brain call).
  3. daemon-down            → FAIL-OPEN (exit 0) in BOTH warn and block mode —
                              a fresh clone / CI must never be blocked.
  4. block-mode behaviour   → reachable + no qualifying fragment + env=block →
                              exit 1; everything else (warn mode, found, down) →
                              exit 0.

Plus: found→exit0, and the real urllib/SSE transport is exercised end-to-end
(mock only at urlopen, the same seam test_brainwrap.py uses) so the JSON-RPC
`tools/call` envelope + `data:` SSE parsing are covered, not stubbed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# tools/ on path so `import brain_commit_gate` works.
TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import brain_commit_gate as gate  # noqa: E402


# ───────────────────────── transport fakes (urlopen seam) ──────────────────


def _sse_bytes(result: dict) -> bytes:
    """Encode a tool result the way the FastMCP HTTP transport does: an SSE
    `data:` line whose JSON-RPC result.structuredContent is the tool's return
    dict. brain_commit_gate._parse_sse must decode exactly this."""
    envelope = {"jsonrpc": "2.0", "id": 1,
                "result": {"structuredContent": result}}
    return f"event: message\ndata: {json.dumps(envelope)}\n\n".encode("utf-8")


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _browse_payload(cards: list[dict], *, generated_at: str = "2026-06-01",
                    key: str = "search") -> dict:
    """A minimal brain.browse structuredContent payload carrying `cards` under
    the given key (search | top_of_mind), shaped like the real daemon's."""
    payload = {
        "ok": True,
        "generated_at": generated_at,
        "totals": {},
        "top_of_mind": [],
        "search": [],
        "timeline": [],
    }
    payload[key] = cards
    return payload


def _card(headline: str, *, last_used: str = "2026-06-01",
          why: str = "used recently", text: str = "",
          details: dict | None = None) -> dict:
    """A browse card shaped like organize._card output."""
    det = details if details is not None else {"text": text or headline}
    return {
        "id": "frag:" + headline[:8],
        "facet": "Memory",
        "headline": headline,
        "last_used": last_used,
        "why": why,
        "details": det,
    }


def _patched_urlopen(payload: dict):
    """Return a urlopen replacement that always replies with `payload` as SSE."""
    def _fake(req, timeout=None):
        return _FakeResp(_sse_bytes(payload))
    return _fake


def _urlopen_raises(exc: Exception):
    def _fake(req, timeout=None):
        raise exc
    return _fake


# ───────────────────────── repo-identity pin ───────────────────────────────


@pytest.fixture
def pinned_repo(monkeypatch):
    """Pin repo_identity() to a deterministic (root, basename) so tie-matching
    does not depend on where the test runner happens to live."""
    monkeypatch.setattr(gate, "repo_identity",
                        lambda: ("c:/users/dev/archhub", "archhub"))
    return ("c:/users/dev/archhub", "archhub")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts from a known env: warn mode, default window."""
    monkeypatch.delenv(gate.GATE_MODE_ENV, raising=False)
    monkeypatch.delenv(gate.WINDOW_ENV, raising=False)


# ═══════════════════════════════════════════════════════════════════════════
#  1 + 2.  trigger scope:  touches app/payload → check ;  else → skip
# ═══════════════════════════════════════════════════════════════════════════


def test_no_app_paths_skips_without_calling_brain(pinned_repo):
    """A commit with no app/ or payload/ paths must SKIP — exit 0 and NEVER
    touch the network."""
    staged = ["docs/agdr/AgDR-0050-x.md", "tests/test_x.py", "README.md"]
    with patch.object(gate.urllib.request, "urlopen") as uo:
        rc = gate.decide(staged)
    assert rc == 0
    uo.assert_not_called()  # skip path makes zero brain calls


def test_app_path_triggers_brain_check(pinned_repo):
    """A staged app/ path must trigger the brain query (the check runs)."""
    staged = ["app/web_ui/studio-lm.jsx", "docs/notes.md"]
    payload = _browse_payload([])  # reachable, nothing found
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)) as uo:
        rc = gate.decide(staged)
    assert uo.called, "expected the gate to query the brain for an app/ commit"
    assert rc == 0  # warn mode default → never blocks


def test_payload_path_also_triggers(pinned_repo):
    staged = ["payload/sources/RevitMCPCore.cs"]
    assert gate.touches_surface(staged) == ["payload/sources/RevitMCPCore.cs"]


def test_touches_surface_is_path_normalised(pinned_repo):
    """Backslash / leading ./ / case variations all still match the prefix."""
    staged = [r"app\bridge.py", "./app/tool_engine.py", "APP/x.py",
              "applesauce/not_app.py"]  # 'applesauce' must NOT match 'app/'
    hits = gate.touches_surface(staged)
    assert r"app\bridge.py" in hits
    assert "./app/tool_engine.py" in hits
    assert "APP/x.py" in hits
    assert "applesauce/not_app.py" not in hits


# ═══════════════════════════════════════════════════════════════════════════
#  3.  daemon-down → FAIL-OPEN in BOTH modes
# ═══════════════════════════════════════════════════════════════════════════


def test_daemon_down_fails_open_warn_mode(pinned_repo, monkeypatch):
    staged = ["app/bridge.py"]
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_urlopen_raises(ConnectionRefusedError())):
        rc = gate.decide(staged)
    assert rc == 0  # fresh clone / CI: never blocked


def test_daemon_down_fails_open_even_in_block_mode(pinned_repo, monkeypatch):
    """The strongest guarantee: even with block mode ON, an unreachable brain
    must FAIL-OPEN. Blocking a commit because the daemon is down would brick a
    fresh clone — explicitly forbidden by AgDR-0050."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/bridge.py"]
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_urlopen_raises(OSError("no route"))):
        rc = gate.decide(staged)
    assert rc == 0


def test_malformed_response_fails_open(pinned_repo, monkeypatch):
    """A 200 with a body that isn't the expected SSE/JSON shape → treated as
    unreachable → fail-open."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/bridge.py"]

    def _garbage(req, timeout=None):
        return _FakeResp(b"event: message\ndata: not-json\n\n")

    with patch.object(gate.urllib.request, "urlopen", side_effect=_garbage):
        rc = gate.decide(staged)
    assert rc == 0


# ═══════════════════════════════════════════════════════════════════════════
#  4.  block-mode behaviour  +  found→exit0
# ═══════════════════════════════════════════════════════════════════════════


def test_block_mode_blocks_when_reachable_and_nothing_found(pinned_repo,
                                                            monkeypatch):
    """Reachable brain + NO qualifying recent fragment + env=block → exit 1."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/web_ui/studio-lm.jsx"]
    payload = _browse_payload([])  # reachable, empty
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)):
        rc = gate.decide(staged)
    assert rc == 1


def test_warn_mode_never_blocks_when_nothing_found(pinned_repo, monkeypatch):
    """Same situation as above but warn mode (default) → exit 0 with a warning."""
    # env intentionally unset (defaults to warn via _clean_env)
    staged = ["app/web_ui/studio-lm.jsx"]
    payload = _browse_payload([])
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)):
        rc = gate.decide(staged)
    assert rc == 0


def test_found_recent_fragment_tied_to_repo_passes_in_block_mode(pinned_repo,
                                                                 monkeypatch):
    """A fragment dated today whose text names the repo basename satisfies the
    gate — exit 0 EVEN in block mode."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/bridge.py"]
    card = _card("Wired the ArchHub bridge slot for X",
                 last_used="2026-06-01", why="used recently",
                 text="touched archhub app/bridge.py this session")
    payload = _browse_payload([card], generated_at="2026-06-01")
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)):
        rc = gate.decide(staged)
    assert rc == 0


def test_found_via_staged_path_in_accessed_resources(pinned_repo, monkeypatch):
    """The strongest provenance tie: the staged file path appears in the
    fragment's accessed_resources. Matches even in block mode."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/tool_engine.py"]
    card = {
        "id": "frag:res",
        "headline": "some unrelated headline",
        "last_used": "2026-06-01",
        "why": "used recently",
        "accessed_resources": ["app/tool_engine.py", "app/bridge.py"],
        "details": {"text": "no repo name here"},
    }
    payload = _browse_payload([card])
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)):
        rc = gate.decide(staged)
    assert rc == 0


def test_stale_fragment_does_not_satisfy_block_mode(pinned_repo, monkeypatch):
    """A fragment that names the repo but is NOT recent (old date, no 'recently'
    why) must NOT satisfy the gate → block mode exits 1."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/bridge.py"]
    card = _card("ArchHub bridge work from a week ago",
                 last_used="2026-05-20", why="proven useful",
                 text="archhub app/bridge.py")
    payload = _browse_payload([card], generated_at="2026-06-01")
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)):
        rc = gate.decide(staged)
    assert rc == 1


def test_recent_but_unrelated_fragment_does_not_satisfy(pinned_repo,
                                                        monkeypatch):
    """A fragment that IS recent but references neither the repo nor a staged
    path must NOT satisfy the gate → block mode exits 1."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/bridge.py"]
    card = _card("Bought groceries and watered the plants",
                 last_used="2026-06-01", why="used recently",
                 text="totally unrelated personal note")
    payload = _browse_payload([card], generated_at="2026-06-01")
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)):
        rc = gate.decide(staged)
    assert rc == 1


def test_match_found_in_top_of_mind_lane_too(pinned_repo, monkeypatch):
    """Cards arrive under top_of_mind (not just search) — the gate must scan
    both lanes."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")
    staged = ["app/bridge.py"]
    card = _card("ArchHub session note", text="archhub app/bridge.py edit")
    payload = _browse_payload([card], key="top_of_mind")  # search lane empty
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_patched_urlopen(payload)):
        rc = gate.decide(staged)
    assert rc == 0


# ═══════════════════════════════════════════════════════════════════════════
#  transport + env knobs
# ═══════════════════════════════════════════════════════════════════════════


def test_call_tool_builds_correct_mcp_envelope_and_parses_sse():
    """End-to-end transport: real call_tool + _parse_sse over a mocked urlopen.
    Asserts the JSON-RPC tools/call envelope, the Accept header, and that the
    SSE structuredContent is returned."""
    captured = {}

    def _capture(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["accept"] = req.headers.get("Accept")
        return _FakeResp(_sse_bytes({"ok": True, "echo": 1}))

    with patch.object(gate.urllib.request, "urlopen", side_effect=_capture):
        out = gate.call_tool("brain.browse", {"query": "x"})

    assert out == {"ok": True, "echo": 1}
    assert captured["body"]["method"] == "tools/call"
    assert captured["body"]["params"]["name"] == "brain.browse"
    assert captured["body"]["params"]["arguments"] == {"query": "x"}
    assert "text/event-stream" in (captured["accept"] or "")


def test_call_tool_returns_none_on_transport_error():
    with patch.object(gate.urllib.request, "urlopen",
                      side_effect=_urlopen_raises(ConnectionRefusedError())):
        assert gate.call_tool("brain.health", {}) is None


def test_window_env_override(monkeypatch):
    monkeypatch.setenv(gate.WINDOW_ENV, "45")
    assert gate._window_minutes() == 45
    monkeypatch.setenv(gate.WINDOW_ENV, "garbage")
    assert gate._window_minutes() == gate.DEFAULT_WINDOW_MIN
    monkeypatch.setenv(gate.WINDOW_ENV, "-5")
    assert gate._window_minutes() == gate.DEFAULT_WINDOW_MIN


def test_mode_defaults_to_warn(monkeypatch):
    monkeypatch.delenv(gate.GATE_MODE_ENV, raising=False)
    assert gate._mode() == "warn"
    monkeypatch.setenv(gate.GATE_MODE_ENV, "BLOCK")  # case-insensitive
    assert gate._mode() == "block"
    monkeypatch.setenv(gate.GATE_MODE_ENV, "nonsense")
    assert gate._mode() == "warn"  # unknown → safe default


def test_internal_error_fails_open(pinned_repo, monkeypatch):
    """A bug inside the gate must never block a commit — main() swallows it and
    exits 0."""
    monkeypatch.setenv(gate.GATE_MODE_ENV, "block")

    def _boom(staged):
        raise RuntimeError("simulated gate bug")

    monkeypatch.setattr(gate, "decide", _boom)
    monkeypatch.setattr(gate, "get_staged_files", lambda explicit=None: ["app/x.py"])
    assert gate.main([]) == 0


def test_main_with_explicit_staged_file_skips_git(pinned_repo, monkeypatch):
    """--staged-file feeds the staged list directly; git is never invoked."""
    called = {"git": False}

    def _no_git(*a, **k):
        called["git"] = True
        raise AssertionError("git must not be called when --staged-file given")

    monkeypatch.setattr(gate.subprocess, "run", _no_git)
    # docs-only explicit list → skip → exit 0, and never calls git.
    rc = gate.main(["--staged-file", "docs/x.md"])
    assert rc == 0
    assert called["git"] is False
