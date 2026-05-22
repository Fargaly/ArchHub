"""Real-executor tests — make sure the conversation.chat + host.* nodes
actually wire through to the live adapters when ctx is populated.

Per the founder complaint ("nodes are still empty shells that is not
working properly"), the runner now threads ctx (router, tool_engine,
manager) into every executor, and these tests pin:

  - `_conversation_exec` calls `ctx.router.complete(...)` when present,
    appends the assistant turn back to `messages`, and returns the
    response text on the `response` key.
  - `_host_exec` for `outlook` reports `host_alive=False` when the
    connector says `is_reachable() → False`, without raising.
  - `_host_exec` for missing modules surfaces `status="missing_dep"`.
  - The WorkflowRunner constructor accepts router/tool_engine/manager
    and the cooked ctx flows into the executor (not None).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes triggers registration of conversation +
# host families (so the runner can resolve them).
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows.nodes.core import _conversation_exec, _host_exec
from workflows.runner import WorkflowRunner


# ─── helpers ────────────────────────────────────────────────────────

class _StubResponse:
    """Mimics the LLMRouter.complete() response object."""
    def __init__(self, text: str, model: str = "stub-1"):
        self.text = text
        self.model = model


class _StubRouter:
    """Mimics the LLMRouter contract used by _conversation_exec."""
    def __init__(self, reply: str = "pong"):
        self.reply = reply
        self.last_history: list = []
        self.last_model: str = ""

    def complete(self, *, history, model, on_chunk, on_tool_invocation,
                  **_kw):
        self.last_history = list(history or [])
        self.last_model = model
        # Mimic streaming so the JSX side gets chunks.
        for piece in self.reply.split():
            try:
                on_chunk(piece + " ")
            except Exception:
                pass
        return _StubResponse(self.reply, model="stub-1")


def _ctx(router=None, tool_engine=None, manager=None):
    return SimpleNamespace(router=router,
                            tool_engine=tool_engine,
                            manager=manager)


# ─── conversation.chat ──────────────────────────────────────────────

def test_conversation_exec_uses_router_when_present():
    router = _StubRouter(reply="hello world from stub")
    out = _conversation_exec(
        {"model": "auto"},
        {"prompt": "hi"},
        _ctx(router=router),
    )
    assert out["status"] == "ok"
    assert out["response"] == "hello world from stub"
    # Last two turns must be user + assistant in order.
    msgs = out["messages"]
    assert msgs[-2] == {"role": "user", "content": "hi"}
    assert msgs[-1] == {"role": "assistant",
                         "content": "hello world from stub"}
    # Router got the right history shape.
    assert router.last_history[-1] == {"role": "user", "content": "hi"}
    assert router.last_model == "auto"


def test_conversation_exec_falls_back_when_router_missing():
    """No router → deterministic stub keeps the shape contract."""
    out = _conversation_exec(
        {"model": "auto"},
        {"prompt": "hi"},
        _ctx(router=None),
    )
    assert out["status"] == "ok"
    assert out["response"].startswith("[stub-auto]")
    assert out["messages"][-1]["role"] == "assistant"


def test_conversation_exec_router_failure_returns_missing_dep():
    class _BoomRouter:
        def complete(self, **_kw):
            raise RuntimeError("no provider key")

        def blocked_providers(self):
            return {}

        def configured_providers(self):
            return []

    out = _conversation_exec(
        {"model": "auto"},
        {"prompt": "anything"},
        _ctx(router=_BoomRouter()),
    )
    assert out["status"] == "missing_dep"
    assert "no provider key" in out["reason"]
    assert "Settings" in out["hint"] or "Ollama" in out["hint"]


# ─── host.outlook ───────────────────────────────────────────────────

def test_host_exec_outlook_unreachable_marks_host_dead(monkeypatch):
    """outlook_runner.is_reachable() returns False → host_alive=False
    + status='ok' (not missing_dep) so the workflow doesn't abort."""
    import sys as _sys
    import types as _types
    fake = _types.ModuleType("connectors.outlook_runner")
    fake.is_reachable = lambda: False
    fake.info = lambda: {}
    fake.list_folders = lambda: []
    pkg = _sys.modules.get("connectors") or _types.ModuleType("connectors")
    monkeypatch.setitem(_sys.modules, "connectors", pkg)
    monkeypatch.setitem(_sys.modules, "connectors.outlook_runner", fake)
    monkeypatch.setattr(pkg, "outlook_runner", fake, raising=False)

    out = _host_exec(
        {"_family": "outlook"},
        {},
        _ctx(),
    )
    assert out["family"] == "outlook"
    assert out["host_alive"] is False
    assert out["status"] == "ok"


def test_host_exec_outlook_module_missing_returns_missing_dep(
        monkeypatch):
    """If the connectors.outlook_runner MODULE itself is missing, the
    envelope surfaces status='missing_dep' so the user sees a hint."""
    import sys as _sys
    import builtins as _builtins
    real_import = _builtins.__import__

    def _blocking_import(name, *a, **kw):
        if name == "connectors" or name.startswith("connectors."):
            raise ImportError(
                "no connectors package (simulated for test)")
        if name == "connectors.outlook_runner":
            raise ImportError("module missing")
        return real_import(name, *a, **kw)

    # Drop any cached connectors so the import path re-evaluates.
    for mod in list(_sys.modules):
        if mod == "connectors" or mod.startswith("connectors."):
            monkeypatch.delitem(_sys.modules, mod, raising=False)
    monkeypatch.setattr(_builtins, "__import__", _blocking_import)

    out = _host_exec(
        {"_family": "outlook"},
        {},
        _ctx(),
    )
    assert out["host_alive"] is False
    assert out["status"] == "missing_dep"
    assert "outlook" in out["hint"].lower()


# ─── WorkflowRunner ctx threading ───────────────────────────────────

def test_runner_threads_ctx_into_executor():
    """When the runner cooks a node, the executor receives a ctx with
    router/tool_engine/manager — not None."""
    seen: dict = {}

    from workflows.registry import register, NodeSpec, get as _get
    from workflows.graph import Port, PortType

    def _probe_exec(config, inputs, ctx):
        seen["router"]      = getattr(ctx, "router", "<missing>")
        seen["tool_engine"] = getattr(ctx, "tool_engine", "<missing>")
        seen["manager"]     = getattr(ctx, "manager", "<missing>")
        return {"status": "ok"}

    if _get("_test.ctx_probe") is None:
        register(NodeSpec(
            type="_test.ctx_probe", category="_test",
            display_name="Ctx Probe", description="Echoes ctx",
            inputs=[], outputs=[Port(name="ok", type=PortType.STRING)],
            config_schema={}, icon="?",
        ), _probe_exec)

    fake_router = object()
    fake_tools  = object()
    fake_mgr    = object()
    runner = WorkflowRunner(
        {"nodes": [{"id": "n1", "type": "_test.ctx_probe",
                    "config": {}}],
         "wires": []},
        router=fake_router, tool_engine=fake_tools, manager=fake_mgr,
    )
    runner.pull("n1")
    assert seen["router"] is fake_router
    assert seen["tool_engine"] is fake_tools
    assert seen["manager"] is fake_mgr


def test_runner_accepts_prebuilt_ctx_object():
    """Passing a single `ctx=` works too (for subgraph propagation)."""
    captured: dict = {}

    from workflows.registry import register, NodeSpec, get as _get
    from workflows.graph import Port, PortType

    def _exec(config, inputs, ctx):
        captured["ctx"] = ctx
        return {"status": "ok"}

    if _get("_test.ctx_passthru") is None:
        register(NodeSpec(
            type="_test.ctx_passthru", category="_test",
            display_name="Passthru", description="",
            inputs=[], outputs=[Port(name="ok", type=PortType.STRING)],
            config_schema={}, icon="?",
        ), _exec)

    prebuilt = SimpleNamespace(router="R", tool_engine="T", manager="M")
    runner = WorkflowRunner(
        {"nodes": [{"id": "n1", "type": "_test.ctx_passthru",
                    "config": {}}],
         "wires": []},
        ctx=prebuilt,
    )
    runner.pull("n1")
    assert captured["ctx"] is prebuilt
