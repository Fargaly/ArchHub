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


# ─── 5. slice-2 kinds + unknown kinds — honest typed errors ─────────


def test_connector_kind_pending_slice_2():
    spec = {
        "type": "c.node", "outputs": ["value"],
        "impl": {"kind": "connector", "host": "revit", "op": "exec"},
    }
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "slice 2" in out["error"]


def test_ai_kind_pending_slice_2():
    spec = {"type": "a.node", "outputs": ["value"],
            "impl": {"kind": "ai", "model": "auto"}}
    out = _executor(spec)({}, {}, None)
    assert "error" in out and "slice 2" in out["error"]


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
