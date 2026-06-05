"""ai.plan node — M4 foundation (AgDR-0021).

Tests verify:
  1. Grammar primitive registered, resolves to `ai.plan` engine.
  2. Engine calls llm.complete_with_tools on fresh runs + persists.
  3. Replay mode returns the cached record without calling the LLM.
  4. Failure records still persist (error preserved).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import workflows.nodes  # noqa: F401, E402 — registers ai.plan + deps
from workflows import node_grammar as ng  # noqa: E402
from workflows.registry import get as registry_get  # noqa: E402
from plan_history import PlanHistory  # noqa: E402


# ─── 1. grammar primitive ────────────────────────────────────────────


def test_ai_plan_grammar_primitive_registered():
    by_kind = {p.kind: p for p in ng.PRIMITIVES}
    assert "ai_plan" in by_kind
    p = by_kind["ai_plan"]
    assert p.cat == "ai"
    assert p.hidden is False


def test_ai_plan_resolves_to_ai_plan_engine():
    assert ng.engine_type("ai_plan") == "ai.plan"


def test_ai_plan_appears_in_payload():
    payload = ng.grammar_payload()
    kinds = {p["kind"] for p in payload}
    assert "ai_plan" in kinds


def test_ai_plan_grammar_count_within_cap():
    """Grammar grew by 1 (ai_plan); cap raised to 80, then +1 → 81 for
    stem-rebuild Phase-0 `verify.assert` (verify gate / branch primitive),
    then +1 → 82 for stem-rebuild Phase-0 `fs.list` (READ-ONLY IO read cell)."""
    # +3 -> 85: stem-rebuild Phase-0 batch-2 cells (fs.read + data.dedupe
    # + data.json) — cap bumped in lockstep with their node_grammar entries.
    # +2 -> 87: stem-rebuild Phase-0 IO-write cells fs.write + fs.move.
    assert len(ng.PRIMITIVES) <= 91


def test_ai_plan_carries_replay_param():
    by_kind = {p.kind: p for p in ng.PRIMITIVES}
    p = by_kind["ai_plan"]
    keys = [pp["k"] for pp in p.params]
    assert "model" in keys
    assert "prompt" in keys
    assert "replay" in keys
    assert "allowed_tools" in keys


# ─── 2. engine — fresh run ───────────────────────────────────────────


def _stub_llm_complete_with_tools(monkeypatch, response):
    """Patch the registered llm.complete_with_tools executor to
    return `response`. Tests exercise the ai.plan wrapper without
    a real LLM. Direct-mutates the registry's `_REGISTRY` dict
    (the public `register()` refuses re-registration on purpose,
    so for tests we swap the tuple in place + monkeypatch restores
    it after the test)."""
    from workflows.registry import _REGISTRY, get as _g
    spec, original_ex = _g("llm.complete_with_tools")
    called = {"count": 0, "last_cfg": None}

    def _fake(cfg, inputs, ctx):
        called["count"] += 1
        called["last_cfg"] = cfg
        return response

    monkeypatch.setitem(_REGISTRY, "llm.complete_with_tools",
                         (spec, _fake))
    return called


def test_ai_plan_calls_llm_when_not_replay(monkeypatch, tmp_path):
    _, ex = registry_get("ai.plan")
    calls = _stub_llm_complete_with_tools(monkeypatch, {
        "text": "I called the tool!",
        "model": "claude-4",
        "tool_invocations": [{"tool": "demo.x", "args": {}}],
        "status": "ok",
    })
    out = ex({"prompt": "do something",
              "model": "claude-4",
              "replay": False,
              "project_dir": str(tmp_path)},
             {"prompt": "do something"},
             SimpleNamespace())
    assert calls["count"] == 1
    assert out["cached"] is False
    assert out["status"] == "ok"
    assert out["result"] == "I called the tool!"
    assert out["plan"] == [{"tool": "demo.x", "args": {}}]
    assert out["plan_id"]


def test_ai_plan_persists_record_to_disk(monkeypatch, tmp_path):
    _, ex = registry_get("ai.plan")
    _stub_llm_complete_with_tools(monkeypatch, {
        "text": "done", "model": "auto",
        "tool_invocations": [], "status": "ok",
    })
    out = ex({"prompt": "persist this",
              "model": "auto",
              "project_dir": str(tmp_path)},
             {"prompt": "persist this"},
             SimpleNamespace())
    h = PlanHistory(tmp_path)
    rec = h.load(out["plan_id"])
    assert rec is not None
    assert rec["prompt"] == "persist this"
    assert rec["status"] == "ok"


# ─── 3. engine — replay ──────────────────────────────────────────────


def test_ai_plan_replay_returns_cache_without_llm_call(monkeypatch,
                                                          tmp_path):
    _, ex = registry_get("ai.plan")
    calls = _stub_llm_complete_with_tools(monkeypatch, {
        "text": "first", "model": "m",
        "tool_invocations": [{"t": "a"}], "status": "ok",
    })
    # First cook — populates the cache.
    first = ex({"prompt": "same",
                "model": "m",
                "replay": False,
                "project_dir": str(tmp_path)},
               {"prompt": "same"}, SimpleNamespace())
    assert calls["count"] == 1
    assert first["cached"] is False

    # Stub returns a NEW value — but with replay=True we should NOT
    # call the LLM and instead return the cached "first" record.
    _stub_llm_complete_with_tools(monkeypatch, {
        "text": "second", "model": "m",
        "tool_invocations": [{"t": "b"}], "status": "ok",
    })
    second = ex({"prompt": "same",
                 "model": "m",
                 "replay": True,
                 "project_dir": str(tmp_path)},
                {"prompt": "same"}, SimpleNamespace())
    assert second["cached"] is True
    assert second["result"] == "first"  # from cache, not the new stub


def test_ai_plan_replay_falls_through_when_no_cache(monkeypatch, tmp_path):
    """replay=True + cache miss → call the LLM (don't error)."""
    _, ex = registry_get("ai.plan")
    calls = _stub_llm_complete_with_tools(monkeypatch, {
        "text": "fresh", "model": "m",
        "tool_invocations": [], "status": "ok",
    })
    out = ex({"prompt": "uncached",
              "model": "m",
              "replay": True,  # replay requested but nothing cached
              "project_dir": str(tmp_path)},
             {"prompt": "uncached"}, SimpleNamespace())
    assert calls["count"] == 1
    assert out["cached"] is False
    assert out["result"] == "fresh"


# ─── 4. failure path ─────────────────────────────────────────────────


def test_ai_plan_persists_failure_record(monkeypatch, tmp_path):
    """Even on LLM error, the turn record is saved."""
    _, ex = registry_get("ai.plan")
    _stub_llm_complete_with_tools(monkeypatch, {
        "text": "", "model": "",
        "tool_invocations": [],
        "status": "error",
        "error": "rate limit",
    })
    out = ex({"prompt": "fail this",
              "model": "auto",
              "project_dir": str(tmp_path)},
             {"prompt": "fail this"}, SimpleNamespace())
    assert out["status"] == "error"
    assert out["error"] == "rate limit"
    # Failure record persisted.
    h = PlanHistory(tmp_path)
    rec = h.load(out["plan_id"])
    assert rec is not None
    assert rec["status"] == "error"
    assert rec["error"] == "rate limit"


# ─── 5. allowed_tools threading ──────────────────────────────────────


def test_ai_plan_threads_allowed_tools_to_llm(monkeypatch, tmp_path):
    """`allowed_tools` config is parsed (comma-string OR list) +
    forwarded as the LLM's tool whitelist."""
    _, ex = registry_get("ai.plan")
    calls = _stub_llm_complete_with_tools(monkeypatch, {
        "text": "", "model": "m",
        "tool_invocations": [], "status": "ok",
    })
    ex({"prompt": "p",
        "model": "m",
        "allowed_tools": "revit.list_walls, revit.list_doors",
        "project_dir": str(tmp_path)},
       {"prompt": "p"}, SimpleNamespace())
    cfg = calls["last_cfg"]
    assert cfg["allowed_tools"] == ["revit.list_walls", "revit.list_doors"]
