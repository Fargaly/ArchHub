"""AgDR-0038 slice 1 — Composer Capability Nodes: the executor substrate.

Covers the `impl` discriminator, `_build_executor` dispatch, the python
sandbox (Delta 4 — closes the arbitrary-code-execution hole that was
`custom_nodes.py:117` exec'ing with the real `__builtins__`), and
bare-`code` back-compat so every existing custom-node file keeps working.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.custom_nodes import (  # noqa: E402
    _build_executor,
    _map_outputs,
    _resolve_impl,
    _spec_from_dict,
    register_spec,
)


def _executor(spec: dict):
    """Build the executor for a raw spec dict the way register_spec does."""
    return _build_executor(spec, _spec_from_dict(spec))


# ─── 1. _resolve_impl — discriminator normalisation ─────────────────


def test_resolve_impl_uses_explicit_block():
    impl = _resolve_impl({"type": "x", "impl": {"kind": "passthrough"}})
    assert impl["kind"] == "passthrough"


def test_resolve_impl_legacy_bare_code_becomes_python():
    """A pre-AgDR-0038 spec (bare top-level `code`, no `impl`) normalises
    to impl.kind=python — back-compat for every existing node file."""
    impl = _resolve_impl(
        {"type": "x", "code": "def execute(c, i, x):\n    return {}"})
    assert impl["kind"] == "python"
    assert "def execute" in impl["code"]


def test_resolve_impl_empty_spec_is_passthrough():
    assert _resolve_impl({"type": "x"})["kind"] == "passthrough"


# ─── 2. passthrough ─────────────────────────────────────────────────


def test_passthrough_maps_named_outputs():
    fn = _executor({"type": "p", "inputs": ["a"], "outputs": ["a"]})
    assert fn({}, {"a": 7}, None) == {"a": 7}


def test_passthrough_falls_back_to_first_input():
    fn = _executor({"type": "p2", "inputs": ["a"], "outputs": ["out"]})
    assert fn({}, {"a": 42}, None) == {"out": 42}


# ─── 3. python kind + back-compat ───────────────────────────────────


def test_python_impl_runs_execute():
    spec = {
        "type": "py.add1", "outputs": ["value"],
        "impl": {"kind": "python",
                 "code": "def execute(config, inputs, ctx):\n"
                         "    return {'value': inputs.get('n', 0) + 1}"},
    }
    assert _executor(spec)({}, {"n": 4}, None) == {"value": 5}


def test_legacy_bare_code_still_runs():
    """Back-compat: a spec with a bare `code` key and no `impl`."""
    spec = {
        "type": "legacy.node", "outputs": ["value"],
        "code": "def execute(config, inputs, ctx):\n"
                "    return {'value': 'ok'}",
    }
    assert _executor(spec)({}, {}, None) == {"value": "ok"}


def test_python_runtime_error_is_caught_as_typed_error():
    spec = {
        "type": "py.boom", "outputs": ["value"],
        "impl": {"kind": "python",
                 "code": "def execute(config, inputs, ctx):\n"
                         "    return {'value': 1 / 0}"},
    }
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "ZeroDivisionError" in out["error"]


# ─── 4. Delta 4 — the sandbox (the security fix) ────────────────────


def test_sandbox_blocks_open():
    """A python impl that calls open() is rejected by the token gate —
    the arbitrary-code-execution hole at custom_nodes.py:117 is closed."""
    spec = {
        "type": "evil.read", "outputs": ["value"],
        "impl": {"kind": "python",
                 "code": "def execute(c, i, x):\n"
                         "    return {'value': open('/etc/passwd').read()}"},
    }
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "forbidden" in out["error"]


def test_sandbox_blocks_import():
    spec = {
        "type": "evil.import", "outputs": ["value"],
        "impl": {"kind": "python",
                 "code": "import os\n"
                         "def execute(c, i, x):\n"
                         "    return {'value': os.getcwd()}"},
    }
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "forbidden" in out["error"]


def test_sandbox_restricts_builtins():
    """Even past the token gate, the exec namespace carries only the
    curated builtins — `getattr` is not in the allow-list, so a body
    using it raises NameError inside the sandbox."""
    spec = {
        "type": "evil.getattr", "outputs": ["value"],
        "impl": {"kind": "python",
                 "code": "def execute(c, i, x):\n"
                         "    return {'value': getattr(str, 'upper', 1)}"},
    }
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "NameError" in out["error"]


def test_safe_mode_false_opts_out():
    """A power user can opt out — impl.safe_mode=false restores full
    builtins, so the same getattr body now runs."""
    spec = {
        "type": "power.getattr", "outputs": ["value"],
        "impl": {"kind": "python", "safe_mode": False,
                 "code": "def execute(c, i, x):\n"
                         "    return {'value': getattr(str, 'upper', 1) "
                         "is not None}"},
    }
    assert _executor(spec)({}, {}, None) == {"value": True}


# ─── 5. slice 2 — connector kind ────────────────────────────────────


def test_connector_executor_calls_run_op(monkeypatch):
    """impl.kind=connector remaps inputs via arg_map and calls run_op."""
    import connectors.base as cb
    calls = {}

    class _R:
        ok = True
        value = {"rows": 3}
        value_preview = ""
        error = ""

    def _fake(op_id, **params):
        calls["op_id"] = op_id
        calls["params"] = params
        return _R()

    monkeypatch.setattr(cb, "run_op", _fake)
    spec = {"type": "c.read", "outputs": ["value"],
            "impl": {"kind": "connector", "host": "excel",
                     "op": "read_range", "arg_map": {"range": "rng"}}}
    out = _executor(spec)({}, {"rng": "A1:B2"}, None)
    assert calls["op_id"] == "excel.read_range"
    assert calls["params"] == {"range": "A1:B2"}
    assert out == {"value": {"rows": 3}}


def test_connector_executor_honest_error_when_host_offline(monkeypatch):
    """An offline host -> honest typed error, never a fabricated value."""
    import connectors.base as cb

    class _R:
        ok = False
        value = None
        error = "excel not running"
        value_preview = ""

    monkeypatch.setattr(cb, "run_op", lambda op_id, **k: _R())
    spec = {"type": "c.off", "outputs": ["value"],
            "impl": {"kind": "connector", "host": "excel", "op": "read_range"}}
    out = _executor(spec)({}, {}, None)
    assert out["error"] == "excel not running"
    assert out["op_id"] == "excel.read_range"


def test_connector_executor_needs_host_and_op():
    spec = {"type": "c.bad", "outputs": ["value"],
            "impl": {"kind": "connector"}}
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "host" in out["error"]


# ─── 6. slice 2 — ai kind ───────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text, model="auto"):
        self.text = text
        self.model = model


class _FakeRouter:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def complete(self, history, model, on_chunk=None, on_tool_invocation=None):
        self.calls.append({"history": history, "model": model})
        return _FakeResponse(self._text, model)


class _FakeCtx:
    def __init__(self, router):
        self.router = router


def test_ai_executor_missing_router_is_honest():
    spec = {"type": "a.x", "outputs": ["text"],
            "impl": {"kind": "ai", "prompt_template": "hi"}}
    out = _executor(spec)({}, {}, None)
    assert out["status"] == "missing_dep"


def test_ai_executor_text_output_fills_template():
    router = _FakeRouter("hello world")
    spec = {"type": "a.t", "outputs": ["text"],
            "impl": {"kind": "ai", "prompt_template": "say {word}"}}
    out = _executor(spec)({}, {"word": "hi"}, _FakeCtx(router))
    assert out == {"text": "hello world"}
    assert router.calls[0]["history"][0]["content"] == "say hi"


def test_ai_executor_json_parse():
    router = _FakeRouter('{"answer": 42}')
    spec = {"type": "a.j", "outputs": ["answer"],
            "impl": {"kind": "ai", "prompt_template": "q",
                     "output_parse": "json"}}
    out = _executor(spec)({}, {}, _FakeCtx(router))
    assert out == {"answer": 42}


def test_ai_executor_json_parse_failure_is_typed_error():
    router = _FakeRouter("not json at all")
    spec = {"type": "a.jf", "outputs": ["answer"],
            "impl": {"kind": "ai", "prompt_template": "q",
                     "output_parse": "json"}}
    out = _executor(spec)({}, {}, _FakeCtx(router))
    assert "error" in out and "JSON" in out["error"]


# ─── 7. _map_outputs + unknown kind ─────────────────────────────────


def test_map_outputs_dict_passthrough():
    assert _map_outputs({"a": 1}, ["a", "b"]) == {"a": 1}


def test_map_outputs_single_output():
    assert _map_outputs(7, ["only"]) == {"only": 7}


def test_map_outputs_fallback_to_value():
    assert _map_outputs([1, 2], ["x", "y"]) == {"value": [1, 2]}


def test_unknown_kind_is_typed_error():
    spec = {"type": "u.node", "outputs": ["value"],
            "impl": {"kind": "wat"}}
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "wat" in out["error"]


# ─── 6. integration — register_spec still round-trips ───────────────


def test_register_spec_accepts_impl_spec():
    """register_spec validates + registers a Capability spec without
    raising — the slice-1 substrate is wired into the registry path."""
    spec = {
        "type": "cap.demo", "category": "document",
        "display_name": "Cap Demo", "outputs": ["value"],
        "impl": {"kind": "python",
                 "code": "def execute(config, inputs, ctx):\n"
                         "    return {'value': 1}"},
    }
    node_spec = register_spec(spec)
    assert node_spec.type == "cap.demo"


# ─── AgDR-0039 — impl.kind=graph: logic IS a sub-graph ──────────────


def test_graph_impl_runs_inner_graph():
    """impl.kind=graph — a node whose logic is an inner graph of
    primitives, cooked through the subgraph machinery. Logic composed,
    not coded."""
    spec = {
        "type": "cap.graphnode",
        "outputs": [{"name": "result", "type": "any"}],
        "impl": {
            "kind": "graph",
            "graph": {
                "nodes": [{"id": "c1", "type": "code.expression",
                           "config": {"expr": "21 * 2"}}],
                "wires": [],
            },
            "inner_outputs": [{"port": "result", "inner_node": "c1",
                               "inner_port": "value"}],
        },
    }
    out = _executor(spec)({}, {}, None)
    assert out.get("result") == 42


def test_graph_impl_seeds_outer_input():
    """An outer input seeds the inner graph's entry port — the
    composite's I/O bridges into the inner logic."""
    spec = {
        "type": "cap.graphadd",
        "inputs": [{"name": "n", "type": "any"}],
        "outputs": [{"name": "result", "type": "any"}],
        "impl": {
            "kind": "graph",
            "graph": {
                "nodes": [{"id": "e1", "type": "code.expression",
                           "config": {"expr": "a + 10"}}],
                "wires": [],
            },
            "inner_inputs": [{"port": "n", "inner_node": "e1",
                              "inner_port": "a"}],
            "inner_outputs": [{"port": "result", "inner_node": "e1",
                               "inner_port": "value"}],
        },
    }
    out = _executor(spec)({}, {"n": 5}, None)
    assert out.get("result") == 15


# ─── AgDR-0039 slice 3 — auto-derived composite I/O ─────────────────


def test_graph_impl_auto_derives_io():
    """impl.kind=graph with NO explicit I/O maps — the composite's
    ports are derived from the inner graph's open ends."""
    spec = {
        "type": "cap.autoio",
        "outputs": [{"name": "value", "type": "any"}],
        "impl": {
            "kind": "graph",
            "graph": {
                "nodes": [{"id": "e1", "type": "code.expression",
                           "config": {"expr": "a + 100"}}],
                "wires": [],
            },
        },
    }
    out = _executor(spec)({}, {"a": 5}, None)
    assert out.get("value") == 105


def test_graph_impl_auto_io_excludes_wired_ports():
    """A wired inner port is internal — never exposed on the composite
    face. Only open ends become I/O."""
    spec = {
        "type": "cap.chain",
        "outputs": [{"name": "value", "type": "any"}],
        "impl": {
            "kind": "graph",
            "graph": {
                "nodes": [
                    {"id": "e1", "type": "code.expression",
                     "config": {"expr": "10"}},
                    {"id": "e2", "type": "code.expression",
                     "config": {"expr": "a * 2"}},
                ],
                "wires": [{"from": ["e1", "value"], "to": ["e2", "a"]}],
            },
        },
    }
    out = _executor(spec)({}, {}, None)
    assert out.get("value") == 20
