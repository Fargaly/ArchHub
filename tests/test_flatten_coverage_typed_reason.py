"""APP-09 — flatten_to_code: coverage == op count + TYPED not-flattenable
reason (no bare _ChainError leaking as an opaque toast).

origin/main gaps closed:
  * `_TEXT_TEMPLATES` covered only 5 of text.op's 13 ops; the other 8
    (split / replace / format / match / regex_*) raised a generic
    `_ChainError` surfaced as an opaque string.
  * the public API returned `{"error": "<str>"}` with no machine-readable
    `reason`, so the UI could only echo the raw message.

The fix:
  * adds expression coverage for `replace` + `split` (config-literal baked,
    sandbox-safe), and
  * classifies the genuinely-inexpressible ops (match / format / regex_*)
    with a TYPED reason (`reason == "op_not_expressible"`, `flattenable:
    False`, structured `op`/`node`/`detail`).
  * `op_coverage()` proves EVERY engine op is classified (unknown == []).

These assertions go RED on origin/main (parametrized ops error opaquely;
`op_coverage` import is absent) and GREEN with the fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import workflows.nodes  # noqa: F401, E402 — register engines
from workflows.flatten_to_code import (  # noqa: E402
    chain_to_expression,
    flatten_chain,
)
from workflows.runner import WorkflowRunner  # noqa: E402
from workflows.node_grammar import normalize_canvas_graph  # noqa: E402
from workflows.registry import get as _reg_get  # noqa: E402


def _engine_ops(engine_type: str) -> list[str]:
    spec = _reg_get(engine_type)[0]
    return list(spec.config_schema["op"]["enum"])


# ─── coverage == op count ────────────────────────────────────────────


@pytest.mark.parametrize("engine_type", ["math.op", "text.op"])
def test_every_engine_op_is_classified(engine_type):
    """coverage == op count: EVERY op the engine supports is either
    emitted as code OR carries a typed not-flattenable reason. The
    `unknown` bucket — ops with neither — MUST be empty."""
    from workflows.flatten_to_code import op_coverage
    cov = op_coverage(engine_type)
    assert cov["unknown"] == [], (
        f"{engine_type} ops with no flatten classification: {cov['unknown']}")
    assert cov["covered"] is True
    # The classified set equals the full engine op set.
    assert cov["coverage_count"] == cov["op_count"] == len(
        _engine_ops(engine_type))


@pytest.mark.parametrize("op", [
    # The 8 text ops that raised a bare _ChainError on origin/main.
    "split", "replace", "format", "match",
    "regex_findall", "regex_match", "regex_replace", "regex_split",
])
def test_text_op_emits_code_or_typed_reason(op):
    """For EVERY text op: flatten either emits code, or returns a TYPED
    not-flattenable reason. Never a bare/opaque error. This is the heart
    of the gate — on main these ops produced an untyped error string with
    no `reason` field."""
    node = {"id": "n", "type": "text.op", "config": {"op": op,
                                                       "pattern": "x",
                                                       "replacement": "y",
                                                       "separator": ","}}
    r = chain_to_expression({"nodes": [node], "wires": []}, ["n"])
    if "error" in r:
        # Not-flattenable → MUST be typed.
        assert r.get("flattenable") is False
        assert r.get("reason") == "op_not_expressible", r
        assert r.get("op") == op
        assert r.get("detail"), "typed reason must carry a plain explanation"
    else:
        # Flattenable → real code emitted.
        assert r.get("expression")


@pytest.mark.parametrize("op", _engine_ops("math.op"))
def test_every_math_op_flattens_to_code(op):
    """EVERY math op emits a real expression — math.op coverage is total."""
    node = {"id": "n", "type": "math.op", "config": {"op": op}}
    r = chain_to_expression({"nodes": [node], "wires": []}, ["n"])
    assert "error" not in r, r
    assert r.get("expression")


# ─── newly-covered ops cook to the same value ────────────────────────


def test_replace_flattens_and_cooks_equivalent():
    """`replace` (config-baked) now flattens AND the code cooks to the
    same string as the original node — proving the new template is real,
    not a placeholder that merely silences the error."""
    original = {
        "nodes": [
            {"id": "a", "type": "data.constant",
             "config": {"value": "hello world world"}},
            {"id": "rep", "type": "text.op",
             "config": {"op": "replace", "pattern": "world",
                        "replacement": "X"}},
            {"id": "out", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["rep", "a"]},
            {"from": ["rep", "value"], "to": ["out", "value"]},
        ],
    }
    res = flatten_chain(original, ["rep"])
    assert "error" not in res, res

    def cook(g):
        return WorkflowRunner(normalize_canvas_graph(g)).run_all()

    expect = cook(original)["results"]["out"]["value"]
    got = cook(res["graph"])["results"]["out"]["value"]
    assert expect == "hello X X"
    assert got == expect


def test_split_flattens_and_cooks_equivalent():
    """`split` (config separator) flattens to a list-producing expression
    equivalent to the original node."""
    original = {
        "nodes": [
            {"id": "a", "type": "data.constant",
             "config": {"value": "x,y,z"}},
            {"id": "sp", "type": "text.op",
             "config": {"op": "split", "separator": ","}},
            {"id": "out", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["sp", "a"]},
            {"from": ["sp", "value"], "to": ["out", "value"]},
        ],
    }
    res = flatten_chain(original, ["sp"])
    assert "error" not in res, res

    def cook(g):
        return WorkflowRunner(normalize_canvas_graph(g)).run_all()

    assert cook(original)["results"]["out"]["value"] == ["x", "y", "z"]
    assert cook(res["graph"])["results"]["out"]["value"] == ["x", "y", "z"]


# ─── all error paths are typed (no bare error) ───────────────────────


def test_unflattenable_type_is_typed():
    r = chain_to_expression(
        {"nodes": [{"id": "c", "type": "conversation.chat", "config": {}}],
         "wires": []}, ["c"])
    assert r["reason"] == "unflattenable_type"
    assert r["flattenable"] is False
    assert "math.op" in r["supported"]


def test_unknown_op_is_typed():
    r = chain_to_expression(
        {"nodes": [{"id": "w", "type": "math.op",
                    "config": {"op": "wibble"}}], "wires": []}, ["w"])
    assert r["reason"] == "unsupported_op"
    assert r["flattenable"] is False
    assert r["op"] == "wibble"


def test_match_op_is_typed_not_expressible():
    """`match` is the canonical not-flattenable op: it needs `re`, which the
    sandbox blocks. On main it errored opaquely; now it's typed."""
    r = chain_to_expression(
        {"nodes": [{"id": "m", "type": "text.op",
                    "config": {"op": "match", "pattern": "x"}}],
         "wires": []}, ["m"])
    assert r["reason"] == "op_not_expressible"
    assert r["op"] == "match"
    assert r["flattenable"] is False
    assert "re" in r["detail"]
