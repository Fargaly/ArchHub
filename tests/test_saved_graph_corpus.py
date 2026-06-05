"""Saved-graph LOAD CORPUS — the permanent back-compat guard (closes G5).

A standing corpus of realistic saved graphs (the Workflow / LM_GRAPH on-disk
shape produced by `Workflow.to_dict`). For EVERY fixture this test proves the
full re-open path a user hits when they load an old graph:

  1. raw JSON parses;
  2. `Workflow.from_dict` LOADS + NORMALIZES it (Port/Edge.from_dict back-fill
     every key a newer schema added — speckle_type, exec/multiple, the v1.4
     profound-wire edge fields);
  3. it survives a `to_dict` -> `from_dict` ROUND-TRIP unchanged (re-save is
     lossless);
  4. the v2 validator (`Workflow.validate` / `validate_v2`) reports ZERO `err`
     issues — no missing ports, no type_mismatch, no cycle;
  5. the graph COOKS through the real Houdini runner (`WorkflowRunner.pull`)
     and each declared SINK yields its expected value.

The fixtures key on REAL shipped node types only — data.constant, filter.apply,
transform.apply, data.join, math.op, text.op, data.template, output.parameter —
so this corpus is the thing that guards REBUILT-NODE IDENTITY forever: if a
stem cell is rebuilt and its cook output or port contract drifts, a fixture
goes red. At least one fixture (`04_speckle_floor_filter`) carries loose/older
port types whose speckle_type floors to ANY, exercising the AgDR-0012 ANY-floor
(graph.py PortType.from_speckle_type + the validator's ANY compatibility rule)
and the legacy-type identity fallback; `03_legacy_loose_math_chain` is the
pre-Stage-2 / pre-v1.4 minimal on-disk shape.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# The engine lives under app/ (mirrors every other workflow test).
APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import workflows.nodes  # noqa: E402,F401  importing registers every built-in node type
from workflows.graph import Workflow  # noqa: E402
from workflows.registry import get as registry_get  # noqa: E402
from workflows.runner import WorkflowRunner  # noqa: E402


FIXTURES_DIR = Path(__file__).resolve().parent / "_fixtures" / "saved_graphs"


# For each fixture: the sinks to cook + the value each must yield.
#   filename -> [(sink_node_id, output_port, expected_value), ...]
# These are the identity anchors — a rebuilt node that changes a cook result
# breaks the matching assertion here.
EXPECTED_SINKS: dict[str, list[tuple[str, str, object]]] = {
    "01_linear_filter_count.json": [
        ("kept", "value", 2),
    ],
    "02_reconcile_join.json": [
        ("n_matched", "value", 2),
        ("strays", "value", [{"id": "A", "v": 1}]),
    ],
    "03_legacy_loose_math_chain.json": [
        # math.op returns a float; 26 == 26.0 holds.
        ("result", "value", 26),
    ],
    "04_speckle_floor_filter.json": [
        ("kept_count", "value", 2),
    ],
    "05_pluck_then_join.json": [
        ("matched_count", "value", 2),
        ("missing", "value", [{"code": "A-102", "status": "REVISE"}]),
    ],
    "06_text_and_compare.json": [
        ("greeting", "value", "Hello ArchHub!"),
        ("ok", "value", True),
    ],
}

# Every engine `type` the corpus exercises. Asserted to be REAL registered
# types so a fixture can never quietly key on an aspirational node.
CORPUS_NODE_TYPES = {
    "data.constant", "filter.apply", "transform.apply", "data.join",
    "math.op", "text.op", "data.template", "output.parameter",
}


def _fixture_files() -> list[Path]:
    files = sorted(FIXTURES_DIR.glob("*.json"))
    return files


def _load_raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# Parametrize ids are the file stems so a failure names the fixture.
_FIXTURE_PARAMS = [pytest.param(p, id=p.name) for p in _fixture_files()]


# ── corpus shape ──────────────────────────────────────────────────────

def test_corpus_dir_exists_and_is_populated():
    assert FIXTURES_DIR.is_dir(), f"missing corpus dir {FIXTURES_DIR}"
    files = _fixture_files()
    # 4-6 realistic fixtures per the G5 spec.
    assert 4 <= len(files) <= 6, (
        f"expected 4-6 saved-graph fixtures, found {len(files)}: "
        f"{[f.name for f in files]}")


def test_every_fixture_has_expected_sinks():
    # No fixture may exist without at least one cook assertion — otherwise it
    # would load-validate but never prove a cooked value (the identity guard).
    for path in _fixture_files():
        assert path.name in EXPECTED_SINKS, (
            f"fixture {path.name} has no EXPECTED_SINKS entry")
        assert EXPECTED_SINKS[path.name], (
            f"fixture {path.name} declares an empty sink list")


def test_corpus_node_types_are_really_registered():
    # Anti-aspirational: every type the corpus keys on must resolve in the
    # registry. This is the LIBRARY-FIRST / honesty guard at corpus level.
    for node_type in sorted(CORPUS_NODE_TYPES):
        assert registry_get(node_type) is not None, (
            f"corpus keys on unregistered node type {node_type!r}")


# ── per-fixture: load + normalize ─────────────────────────────────────

@pytest.mark.parametrize("path", _FIXTURE_PARAMS)
def test_fixture_parses_as_json(path: Path):
    raw = _load_raw(path)
    assert isinstance(raw, dict)
    assert raw.get("nodes"), f"{path.name}: no nodes"
    assert "edges" in raw, f"{path.name}: no edges key"


@pytest.mark.parametrize("path", _FIXTURE_PARAMS)
def test_fixture_loads_and_normalizes(path: Path):
    raw = _load_raw(path)
    wf = Workflow.from_dict(raw)
    # Every node + edge survived the load.
    assert len(wf.nodes) == len(raw["nodes"])
    assert len(wf.edges) == len(raw.get("edges", []))
    # Normalisation back-filled the typed Port/Edge fields even when the
    # on-disk fixture omitted them (legacy shape) — these attrs always exist.
    for n in wf.nodes:
        for p in list(n.inputs) + list(n.outputs):
            assert p.type is not None            # PortType enum, never raw str
            assert isinstance(p.exec, bool)
            assert isinstance(p.multiple, bool)
    for e in wf.edges:
        assert isinstance(e.state, str) and e.state
        assert isinstance(e.src_field, str)
        assert isinstance(e.dst_field, str)


@pytest.mark.parametrize("path", _FIXTURE_PARAMS)
def test_fixture_round_trips_losslessly(path: Path):
    # A re-opened graph that is re-saved must reload identically — the
    # back-compat contract a user depends on every save.
    raw = _load_raw(path)
    once = Workflow.from_dict(raw)
    twice = Workflow.from_dict(once.to_dict())
    assert once.to_dict() == twice.to_dict()
    # Round-trip must not introduce validation errors either.
    assert twice.validate() == []


# ── per-fixture: validate with ZERO errors ────────────────────────────

@pytest.mark.parametrize("path", _FIXTURE_PARAMS)
def test_fixture_validates_with_zero_errors(path: Path):
    wf = Workflow.from_dict(_load_raw(path))
    # The string back-compat shim: must be empty.
    errs = wf.validate()
    assert errs == [], f"{path.name}: validate() errors: {errs}"
    # The structured v2 validator: zero `err`-level issues (warnings such as
    # unset optional inputs are allowed; errors block the cook).
    err_issues = [i for i in wf.validate_v2() if i.get("level") == "err"]
    assert err_issues == [], (
        f"{path.name}: validate_v2 err issues: {err_issues}")


# ── per-fixture: cook + assert sink values ────────────────────────────

@pytest.mark.parametrize("path", _FIXTURE_PARAMS)
def test_fixture_cooks_and_sinks_match(path: Path):
    raw = _load_raw(path)
    # Cook through the REAL runner (the Houdini lazy/dirty/cached path the
    # bridge drives). Pure data nodes need no router/tool_engine/manager.
    runner = WorkflowRunner(raw)
    for sink_id, port, expected in EXPECTED_SINKS[path.name]:
        out = runner.pull(sink_id)
        assert isinstance(out, dict), (
            f"{path.name}: sink {sink_id} returned non-dict {out!r}")
        assert out.get("status") != "error", (
            f"{path.name}: sink {sink_id} cooked to error: {out!r}")
        assert out.get(port) == expected, (
            f"{path.name}: sink {sink_id}.{port} = {out.get(port)!r}, "
            f"expected {expected!r}")


@pytest.mark.parametrize("path", _FIXTURE_PARAMS)
def test_fixture_cook_is_deterministic(path: Path):
    # Same graph cooked twice → byte-identical sink values. This is the parity
    # basis: a rebuilt node that is non-deterministic breaks the corpus.
    raw = _load_raw(path)
    r1 = WorkflowRunner(raw)
    r2 = WorkflowRunner(raw)
    for sink_id, port, _expected in EXPECTED_SINKS[path.name]:
        assert r1.pull(sink_id).get(port) == r2.pull(sink_id).get(port)


@pytest.mark.parametrize("path", _FIXTURE_PARAMS)
def test_fixture_executor_path_agrees_with_runner(path: Path):
    # Cross-check: the workflow-level WorkflowExecutor (topo-order engine that
    # collects output.parameter nodes) agrees with the runner's per-sink pull
    # for every sink that is an output.parameter. Two independent cook engines,
    # one answer — anti-tamper on the identity assertions above.
    from workflows.executor import WorkflowExecutor

    wf = Workflow.from_dict(_load_raw(path))
    result = WorkflowExecutor(None, None, None).run(wf)
    assert result.success, f"{path.name}: executor failed: {result.errors}"
    out_param_names = {n.config.get("name", n.id)
                       for n in wf.nodes if n.type == "output.parameter"}
    for sink_id, port, expected in EXPECTED_SINKS[path.name]:
        node = wf.get_node(sink_id)
        if node is None or node.type != "output.parameter" or port != "value":
            continue
        key = node.config.get("name", node.id)
        if key not in out_param_names:
            continue
        assert result.outputs.get(key) == expected, (
            f"{path.name}: executor output {key} = "
            f"{result.outputs.get(key)!r}, expected {expected!r}")
