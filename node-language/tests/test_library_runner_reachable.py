"""R5 — the library-minted node must REACH THE RUNNER and cook.

The dual-registry trap: `app/library.py` keeps the LIBRARY-FIRST inventory
that the Composer + LLM tools search, but the workflow RUNNER cooks from a
SEPARATE store — `app/workflows/registry.py`'s `_REGISTRY`, keyed by the
same `type`. Before this fix, `library.create_node_type` wrote ONLY to the
library inventory, so a user/AI-minted node was searchable but could not
cook (`runner.py` returns "no executor for <type>").

These tests pin the close of that trap end-to-end:

1. A node minted through the library mint path appears in
   `workflows.registry.get(type)` as a real `(NodeSpec, executor)` pair.
2. The runner COOKS a graph containing the minted node to its expected
   value (python-impl body — a real executor that cooks, not a stub).
3. A bodyless (passthrough) mint also reaches the runner and cooks.
4. The bridge BOOT-LOAD path (a node minted + persisted in a prior
   session) reaches the runner registry after `_library_bootstrap` on a
   fresh bridge — the boot half of R5.
5. Deleting a library node UN-registers its runner executor — the two
   stores stay in lock-step, no orphan executor.

The fix reuses the ONE in-place registration path
(`workflows.custom_nodes.register_spec`, which pops + rebinds + builds the
executor) — no parallel mechanism (ONE-SYSTEM mandate).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import library as _lib  # noqa: E402
from workflows import registry as _reg  # noqa: E402
from workflows.runner import WorkflowRunner  # noqa: E402


# Test-minted types — cleaned out of BOTH registries before + after each
# test so a runner-registry binding never leaks across tests (the runner
# `_REGISTRY` is module-global + has no public reset).
_TEST_TYPES = (
    "demo.runner_double",
    "demo.runner_pass",
    "demo.runner_boot",
    "demo.runner_del",
)


def _purge_runner_registry() -> None:
    for t in _TEST_TYPES:
        _reg._REGISTRY.pop(t, None)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Redirect persistence to tmp + reset both registries around each test.

    library_persistence.default_registry_path() reads LOCALAPPDATA on
    Windows but XDG_DATA_HOME on POSIX — BOTH must be monkeypatched or the
    CI Linux/macOS runners fall back to one real shared registry file.
    """
    appdata = tmp_path / "appdata"
    appdata.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setenv("XDG_DATA_HOME", str(appdata))
    _lib.reset_registry()
    _purge_runner_registry()
    yield
    _lib.reset_registry()
    _purge_runner_registry()


def _double_spec(type_name: str = "demo.runner_double") -> dict:
    """A modular node whose python body doubles its numeric `x` input.

    Carries an `impl` block — the ModularNodeSpec dump DROPS it, but the
    mirror folds it back from the raw spec so the runner builds the real
    executor (not a passthrough)."""
    return {
        "type": type_name,
        "display_name": "Runner Double",
        "category": "shape",
        "inputs": [{"name": "x", "port_type": "number"}],
        "outputs": [{"name": "doubled", "port_type": "number"}],
        "config_schema": {"properties": {"factor": {"type": "number"}}},
        "description": (
            "A modular node minted via the library that doubles its numeric "
            "input — proves a library-minted node reaches and cooks in the "
            "workflow runner."
        ),
        "examples": [
            {"input": {"x": 3}, "output": {"doubled": 6}, "note": "happy"},
        ],
        "side_effects": "pure",
        "impl": {
            "kind": "python",
            "code": (
                "def execute(config, inputs, ctx):\n"
                "    return {'doubled': (inputs.get('x') or 0) * 2}"
            ),
        },
    }


def _passthrough_spec(type_name: str = "demo.runner_pass") -> dict:
    """A bodyless modular node (no impl) — the mirror still registers a
    runner executor (passthrough), so it cooks by mapping the same-named
    input straight through."""
    return {
        "type": type_name,
        "display_name": "Runner Pass",
        "category": "shape",
        "inputs": [{"name": "value", "port_type": "any"}],
        "outputs": [{"name": "value", "port_type": "any"}],
        "config_schema": {"properties": {"mode": {"type": "string"}}},
        "description": (
            "A modular passthrough node minted via the library with no impl "
            "block — proves even a bodyless mint reaches the runner registry."
        ),
        "examples": [
            {"input": {"value": 1}, "output": {"value": 1}, "note": "id"},
        ],
        "side_effects": "pure",
    }


# ---------------------------------------------------------------------------
# 1 — mint path lands a real (spec, executor) pair in the runner registry


def test_library_mint_reaches_runner_registry():
    res = _lib.create_node_type(_double_spec())
    assert res["registered"] is True

    tup = _reg.get("demo.runner_double")
    assert tup is not None, (
        "library-minted node is NOT in the runner registry — the "
        "dual-registry trap is open; the runner cannot cook it"
    )
    spec, executor = tup
    # A real pair: the engine NodeSpec dataclass + a callable executor.
    assert isinstance(spec, _reg.NodeSpec)
    assert spec.type == "demo.runner_double"
    assert callable(executor)
    # The minted ports survived the bridge into the runner spec.
    assert [p.name for p in spec.outputs] == ["doubled"]


# ---------------------------------------------------------------------------
# 2 — the RUNNER cooks a graph containing the minted node to the value


def test_runner_cooks_graph_with_minted_node():
    _lib.create_node_type(_double_spec())

    # A seeded primitive (data.constant) feeds the minted node's `x`.
    graph = {
        "nodes": [
            {"id": "c1", "type": "data.constant", "config": {"value": 21}},
            {"id": "n1", "type": "demo.runner_double", "config": {}},
        ],
        "wires": [
            {"from": ["c1", "value"], "to": ["n1", "x"]},
        ],
    }
    runner = WorkflowRunner(graph)
    out = runner.pull("n1")

    # The real executor cooked: 21 * 2 == 42 on the declared `doubled` port.
    assert out.get("doubled") == 42, (
        f"runner did not cook the minted node to the expected value: {out!r}"
    )
    assert out.get("status") != "error"


def test_run_all_cooks_minted_sink():
    """The whole-graph entry point (`run_all`) also cooks the minted sink —
    the path the bridge's run-graph slot actually drives."""
    _lib.create_node_type(_double_spec())
    graph = {
        "nodes": [
            {"id": "c1", "type": "data.constant", "config": {"value": 5}},
            {"id": "n1", "type": "demo.runner_double", "config": {}},
        ],
        "wires": [{"from": ["c1", "value"], "to": ["n1", "x"]}],
    }
    result = WorkflowRunner(graph).run_all()
    assert result["status"] == "ok"
    assert result["results"]["n1"].get("doubled") == 10


# ---------------------------------------------------------------------------
# 3 — a bodyless (passthrough) mint also reaches + cooks


def test_passthrough_mint_reaches_runner_and_cooks():
    _lib.create_node_type(_passthrough_spec())
    assert _reg.get("demo.runner_pass") is not None

    graph = {
        "nodes": [
            {"id": "c1", "type": "data.constant", "config": {"value": "hi"}},
            {"id": "n1", "type": "demo.runner_pass", "config": {}},
        ],
        "wires": [{"from": ["c1", "value"], "to": ["n1", "value"]}],
    }
    out = WorkflowRunner(graph).pull("n1")
    assert out.get("value") == "hi"


# ---------------------------------------------------------------------------
# 4 — the BRIDGE BOOT-LOAD path bridges disk-persisted nodes to the runner


def test_bridge_boot_load_reaches_runner_registry():
    """A node minted + persisted in a prior session must reach the RUNNER
    registry on the next boot — not just the library inventory. Simulate a
    cold restart: persist, wipe both in-process registries, then a fresh
    bridge's `_library_bootstrap` hydrates the library from disk, which
    mirrors each spec into the runner registry."""
    import bridge as _bridge_module

    # Prior session: mint + persist to the (tmp) registry file.
    _lib.create_node_type(_double_spec("demo.runner_boot"))
    _lib.save_to_disk()
    assert _reg.get("demo.runner_boot") is not None  # alive this session

    # Cold restart: wipe BOTH in-process stores.
    _lib.reset_registry()
    _purge_runner_registry()
    assert _lib.registry_size() == 0
    assert _reg.get("demo.runner_boot") is None

    # Fresh bridge boots the library off disk (the same call _deferred_boot
    # makes). load_from_disk now mirrors each spec into the runner registry.
    new_bridge = _bridge_module.ArchHubBridge()
    if hasattr(new_bridge, "_lib_booted"):
        delattr(new_bridge, "_lib_booted")
    new_bridge._library_bootstrap()

    # Library inventory hydrated AND the runner can cook it.
    assert "demo.runner_boot" in {
        i["type"] for i in _lib.list_node_types()
    }
    tup = _reg.get("demo.runner_boot")
    assert tup is not None, (
        "boot-load hydrated the library inventory but NOT the runner "
        "registry — the boot half of the dual-registry trap is still open"
    )
    graph = {
        "nodes": [
            {"id": "c1", "type": "data.constant", "config": {"value": 7}},
            {"id": "n1", "type": "demo.runner_boot", "config": {}},
        ],
        "wires": [{"from": ["c1", "value"], "to": ["n1", "x"]}],
    }
    assert WorkflowRunner(graph).pull("n1").get("doubled") == 14


# ---------------------------------------------------------------------------
# 5 — deleting a library node un-registers its runner executor


def test_library_delete_unmirrors_from_runner():
    _lib.create_node_type(_double_spec("demo.runner_del"))
    assert _reg.get("demo.runner_del") is not None

    _lib.delete_node_type("demo.runner_del")

    # Both stores drop it in lock-step — no orphan executor outlives the
    # library spec.
    assert _reg.get("demo.runner_del") is None
    assert "demo.runner_del" not in {
        i["type"] for i in _lib.list_node_types()
    }
