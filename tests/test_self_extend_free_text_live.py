"""FREE-TEXT LIVE — the REAL model drives self-extend (engine rung, item 2).

This is the witnessed seam the binding names: a typed free-text composer ask
("add an Airtable connector") goes to the REAL model through the SAME router the
chat/composer uses (run_agent_step → router.complete with the BUILD tools in
TOOL_SCHEMA). The MODEL — not a deterministic marker — DECIDES to call
create_connector; the self-extend loop then builds the real artifact and the
ROMA court must GREEN it on the real file before anything is learned.

This file has TWO layers, by design (ANTI-LIE — no fake proves a live model):

  1. A REAL-MODEL run, gated on NVIDIA_API_KEY (or any configured provider).
     Skipped when no key is reachable so CI without secrets stays green; run
     locally / in the keyed env it proves the model picked the tool + the court
     greened — NOT the deterministic marker. Pin the model to NVIDIA Llama-3.3-
     70B (NVIDIA_FREE_TEXT_MODEL overridable) so the seam is witnessed on the
     exact reachable_model the free-default path resolves.

  2. A FAKE-ROUTER unit that proves the WIRING (extract_build_call → run_self_
     extend) deterministically — so the seam's plumbing is covered even when no
     live key is present. The fake router EMITS a create_connector invocation
     exactly as a real tool-use model would; we assert the loop fired build →
     court → learn on the model's choice.

How the live seam is witnessed (for the report): the returned receipt carries
`picked` = the {tool, args} the MODEL chose (set by the model, not the test) and
`court.verdict == "green"` on the REAL connector file. seams.model_picked True
means the model — over the live router — selected the build tool.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_BRAIN_SRC = _ROOT / "personal-brain-mcp" / "src"
_APP = _ROOT / "app"
for _p in (str(_BRAIN_SRC), str(_APP)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("pydantic")
pytest.importorskip("personal_brain.roma")

from agents import self_extend          # noqa: E402
from connectors import scaffold         # noqa: E402


_LIVE_HOST = "airtable"
_FAKE_HOST = "selfext_freetext_probe"


def _store():
    from personal_brain.storage import BrainStore
    return BrainStore.open(":memory:")


def _clean(host: str) -> None:
    p = scaffold.connector_path(host)
    if p.exists():
        p.unlink()


# ── layer 2: deterministic WIRING proof (no live key needed) ─────────────────


class _FakeToolUseRouter:
    """A router stand-in that behaves like a tool-use model: on complete() it
    fires on_tool_invocation with a create_connector call (the model's choice),
    then returns a short text. This proves the free-text WIRING — the seam from
    a model's emitted tool through extract_build_call into the loop — without a
    live key."""

    def __init__(self, host: str):
        self._host = host

    def complete(self, history=None, model="auto", on_chunk=None,
                 on_tool_invocation=None, extra_tools=None, **kw):
        from types import SimpleNamespace
        # Mimic a ToolInvocation the real router would surface to _on_inv.
        inv = SimpleNamespace(
            tool_name="create_connector",
            arguments={"host": self._host, "label": "Self-Ext Free-Text Probe",
                       "operations": [{"op_id": "list_things", "kind": "read"}]},
            result={"ok": True},
        )
        if on_tool_invocation:
            on_tool_invocation(inv)
        text = f"The {self._host} connector has been added."
        if on_chunk:
            on_chunk(text)
        return SimpleNamespace(text=text)


def test_extract_build_call_reads_model_choice():
    # A YOLO action carries the tool + args at the top level.
    rr = {"actions": [{"tool": "create_connector",
                       "args": {"host": "x"}, "result": {"ok": True}}]}
    picked = self_extend.extract_build_call(rr)
    assert picked == {"tool": "create_connector", "args": {"host": "x"}}
    # No build tool → None.
    assert self_extend.extract_build_call({"actions": [{"tool": "spawn_node"}]}) is None


def test_free_text_wiring_fires_loop_on_model_choice():
    """The model (here a fake tool-use router) emits create_connector → the
    free-text driver routes it into run_self_extend → build + court + learn fire
    on the model's choice. Court is still the gate (green on the real file)."""
    _clean(_FAKE_HOST)
    captured = {}

    def _fake_brain(tool, args):
        captured["tool"] = tool
        return {"ops_applied": 1}

    try:
        out = self_extend.run_free_text_self_extend(
            "add a self-ext free-text probe connector",
            router=_FakeToolUseRouter(_FAKE_HOST),
            store=_store(), brain_call=_fake_brain,
        )
        assert out["picked"]["tool"] == "create_connector", out
        assert out["seams"]["model_picked"] is True
        assert out["seams"]["build"] is True
        assert out["seams"]["court"] is True   # COURT greened the real artifact
        assert out["seams"]["brain"] is True
        assert out["court"]["verdict"] == "green"
        assert captured["tool"] == "brain.write"
        assert scaffold.connector_path(_FAKE_HOST).exists()
    finally:
        _clean(_FAKE_HOST)


def test_free_text_no_build_tool_is_honest():
    """A model that does NOT emit a build tool yields an honest non-green receipt
    (no fabricated build)."""
    class _ChatOnly:
        def complete(self, history=None, model="auto", on_chunk=None,
                     on_tool_invocation=None, **kw):
            from types import SimpleNamespace
            if on_chunk:
                on_chunk("here is some advice")
            return SimpleNamespace(text="here is some advice")

    out = self_extend.run_free_text_self_extend(
        "what is the weather", router=_ChatOnly(), store=_store(),
        brain_call=lambda *a: {"ops_applied": 1})
    assert out["ok"] is False
    assert out["picked"] is None
    assert out["seams"]["model_picked"] is False


# ── layer 1: REAL-MODEL run, gated on a reachable provider key ───────────────


def _reachable_provider_model():
    """Return the (model_string) to pin for a real run, or None to skip. Prefers
    NVIDIA Llama-3.3-70B (the reachable_model the free-default resolves); falls
    back to letting the router auto-pick when only another key is configured."""
    try:
        from llm_router import load_api_key
    except Exception:
        return None
    nv = (os.environ.get("NVIDIA_API_KEY", "").strip()
          or (load_api_key("nvidia") or "").strip())
    if nv:
        return os.environ.get("NVIDIA_FREE_TEXT_MODEL",
                              "nvidia:meta/llama-3.3-70b-instruct")
    # Any other configured provider → let auto routing pick (still a real model).
    for prov in ("google", "openai", "anthropic", "openrouter"):
        try:
            if (load_api_key(prov) or "").strip():
                return "auto"
        except Exception:
            pass
    return None


@pytest.mark.live
def test_free_text_live_real_model_picks_and_court_greens():
    """REAL MODEL: a typed free-text ask makes the live model EMIT
    create_connector; the loop builds the real connector + the ROMA court greens
    it. Skipped when no provider key is reachable (CI without secrets)."""
    model = _reachable_provider_model()
    if model is None:
        pytest.skip("no reachable LLM provider key (set NVIDIA_API_KEY to run live)")

    from manager import ConnectorManager
    from tool_engine import ToolEngine
    from llm_router import LLMRouter

    _clean(_LIVE_HOST)
    captured = {}

    def _fake_brain(tool, args):
        captured["tool"] = tool
        captured["args"] = args
        return {"ops_applied": 1, "fragments_added": 1}

    router = LLMRouter(ToolEngine(ConnectorManager()))
    try:
        out = self_extend.run_free_text_self_extend(
            "add an Airtable connector so I can read and write Airtable bases",
            router=router, model=model,
            store=_store(), brain_call=_fake_brain,
        )
        # The MODEL — not the test — chose the build tool.
        assert out["picked"] is not None, (
            "the live model did not emit a build tool: "
            + str((out.get("agent") or {}).get("text", ""))[:200])
        assert out["picked"]["tool"] in self_extend.BUILD_TOOLS
        assert out["seams"]["model_picked"] is True
        # The COURT greened the REAL artifact (not the marker, not a claim).
        assert out["seams"]["court"] is True, out
        assert out["court"]["verdict"] == "green"
        assert out["seams"]["brain"] is True
        assert captured["tool"] == "brain.write"
    finally:
        _clean(_LIVE_HOST)
