"""AgDR-0019 — typed AI nodes split.

The `ai` master primitive carried one `action` parameter and routed
to one of 4 engine types. The right-panel rail showed the SAME chat
UI for all 4 actions — wrong for non-chat. This slice splits the
master into 4 typed primitives (AI Chat / AI Complete / AI Classify
/ AI Tools), each declaring its action-relevant params. The legacy
`ai` master stays in PRIMITIVES with `hidden=True` for engine
resolution + saved-graph back-compat.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows import node_grammar as ng  # noqa: E402


# ─── 1. typed primitives registered ──────────────────────────────────


@pytest.fixture
def primitives_by_kind():
    return {p.kind: p for p in ng.PRIMITIVES}


def test_typed_ai_chat_registered(primitives_by_kind):
    assert "ai_chat" in primitives_by_kind
    p = primitives_by_kind["ai_chat"]
    assert p.cat == "ai"
    assert p.hidden is False


def test_typed_ai_complete_registered(primitives_by_kind):
    assert "ai_complete" in primitives_by_kind
    assert primitives_by_kind["ai_complete"].cat == "ai"


def test_typed_ai_classify_registered(primitives_by_kind):
    assert "ai_classify" in primitives_by_kind
    assert primitives_by_kind["ai_classify"].cat == "ai"


def test_typed_ai_tools_registered(primitives_by_kind):
    assert "ai_tools" in primitives_by_kind
    assert primitives_by_kind["ai_tools"].cat == "ai"


# ─── 2. legacy `ai` master is hidden ─────────────────────────────────


def test_legacy_ai_master_is_hidden(primitives_by_kind):
    """The `ai` master primitive stays in PRIMITIVES (for engine
    resolution + legacy graph back-compat) but is HIDDEN from the
    palette via `hidden=True`."""
    assert "ai" in primitives_by_kind
    assert primitives_by_kind["ai"].hidden is True


def test_ai_master_not_in_grammar_payload():
    """`grammar_payload()` is the JSX-facing list — `ai` master
    must not appear there (`hidden` filter)."""
    payload = ng.grammar_payload()
    kinds = {p["kind"] for p in payload}
    assert "ai" not in kinds
    # All 4 typed nodes ARE in the payload.
    assert "ai_chat" in kinds
    assert "ai_complete" in kinds
    assert "ai_classify" in kinds
    assert "ai_tools" in kinds


# ─── 3. engine type resolution ───────────────────────────────────────


def test_ai_chat_resolves_to_conversation_chat():
    assert ng.engine_type("ai_chat") == "conversation.chat"


def test_ai_complete_resolves_to_llm_complete():
    assert ng.engine_type("ai_complete") == "llm.complete"


def test_ai_classify_resolves_to_llm_classify():
    assert ng.engine_type("ai_classify") == "llm.classify"


def test_ai_tools_resolves_to_llm_complete_with_tools():
    assert ng.engine_type("ai_tools") == "llm.complete_with_tools"


def test_legacy_ai_master_still_resolves_per_action():
    """Saved graphs with `kind: 'ai'` + `action: 'chat'` must still
    resolve to the right engine type — the master's selector logic
    drives the dispatch."""
    assert ng.engine_type("ai", {"action": "chat"}) == "conversation.chat"
    assert ng.engine_type("ai", {"action": "complete"}) == "llm.complete"
    assert ng.engine_type("ai", {"action": "classify"}) == "llm.classify"
    assert ng.engine_type("ai", {"action": "tools"}) == "llm.complete_with_tools"


# ─── 4. action-relevant params surfaced per typed node ───────────────


def test_ai_chat_carries_model_param(primitives_by_kind):
    """AI Chat declares only `model` — the chat UI is the primary
    surface; no other config needed in the rail."""
    p = primitives_by_kind["ai_chat"]
    keys = [pp["k"] for pp in p.params]
    assert "model" in keys


def test_ai_complete_carries_prompt_param(primitives_by_kind):
    p = primitives_by_kind["ai_complete"]
    keys = [pp["k"] for pp in p.params]
    assert "model" in keys
    assert "prompt" in keys


def test_ai_classify_carries_options_param(primitives_by_kind):
    p = primitives_by_kind["ai_classify"]
    keys = [pp["k"] for pp in p.params]
    assert "options" in keys


def test_ai_tools_carries_allowed_tools_param(primitives_by_kind):
    p = primitives_by_kind["ai_tools"]
    keys = [pp["k"] for pp in p.params]
    assert "prompt" in keys
    assert "allowed_tools" in keys


# ─── 5. grammar count stays under cap ────────────────────────────────


def test_grammar_count_after_ai_split():
    """Cap raised to 80 (was 75) after AgDR-0021 ai_plan + AgDR-0020
    code-split. `grammar_payload()` palette-facing cap stays ≤70
    because the master nodes are hidden."""
    assert len(ng.PRIMITIVES) <= 80
    payload = ng.grammar_payload()
    assert len(payload) <= 70
    # Adapter (6) + share (3) + AI typed (4) → at least 13 AgDR-derived
    # primitives in the visible payload.
    cats_count = {}
    for p in payload:
        cats_count[p["cat"]] = cats_count.get(p["cat"], 0) + 1
    # AgDR-0019 split AI master into 4 typed nodes; AgDR-0021 added
    # `ai_plan` as the 5th typed AI primitive. Update if more land.
    assert cats_count.get("ai", 0) == 5, cats_count


# ─── 6. typed nodes also accept the master's action mapping ──────────


def test_typed_ai_nodes_use_fixed_engine_types(primitives_by_kind):
    """Each typed AI primitive resolves to a fixed engine type (no
    `selector` parameter — Slice I pattern)."""
    for kind in ("ai_chat", "ai_complete", "ai_classify", "ai_tools"):
        p = primitives_by_kind[kind]
        assert p.selector == "", f"{kind!r} should be fixed-type"
        # Single engine_type entry, keyed by "".
        assert "" in p.engine_types, f"{kind!r} missing fixed engine type"
