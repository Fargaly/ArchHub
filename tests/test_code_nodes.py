"""SLICE L — `code.expression` + `code.python` executors (AgDR-0020).

Pin: arithmetic + builtins work; sandbox rejects `import` / `open` /
`__` attrs in safe_mode; explicit opt-out (`safe_mode=False`) allows
the user power; bad source surfaces typed errors; grammar primitive
resolves the right engine per `mode` selector.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Force registration.
import workflows.nodes  # noqa: F401, E402
from workflows.registry import get as registry_get  # noqa: E402
from workflows import node_grammar as ng  # noqa: E402


# ─── 1. code.expression ──────────────────────────────────────────────


@pytest.fixture
def code_expr():
    _, ex = registry_get("code.expression")
    return ex


def test_code_expression_basic_arithmetic(code_expr):
    r = code_expr({"expr": "a + b"}, {"a": 2, "b": 3}, None)
    assert r["status"] == "ok"
    assert r["value"] == 5


def test_code_expression_uses_safe_builtins(code_expr):
    r = code_expr({"expr": "sum([a, b, c])"},
                   {"a": 1, "b": 2, "c": 3}, None)
    assert r["value"] == 6


def test_code_expression_str_concat(code_expr):
    r = code_expr({"expr": "str(a) + b"}, {"a": 42, "b": "hello"}, None)
    assert r["value"] == "42hello"


def test_code_expression_empty_errors(code_expr):
    r = code_expr({"expr": ""}, {}, None)
    assert r["status"] == "error"
    assert "empty" in r["error"].lower()


def test_code_expression_bad_syntax_errors(code_expr):
    r = code_expr({"expr": "a + + +"}, {"a": 1}, None)
    assert r["status"] == "error"
    assert "syntax" in r["error"].lower()


# ─── 2. code.python ──────────────────────────────────────────────────


@pytest.fixture
def code_py():
    _, ex = registry_get("code.python")
    return ex


def test_code_python_sets_result(code_py):
    r = code_py({"body": "result = a * 2"}, {"a": 7}, None)
    assert r["status"] == "ok"
    assert r["value"] == 14


def test_code_python_no_result_returns_none(code_py):
    """If the body never sets `result`, output is None (honest)."""
    r = code_py({"body": "x = a + b"}, {"a": 1, "b": 2}, None)
    assert r["status"] == "ok"
    assert r["value"] is None


def test_code_python_can_use_inputs_dict(code_py):
    r = code_py({"body": "result = sum(inputs.values())"},
                 {"a": 10, "b": 20, "c": 30}, None)
    assert r["value"] == 60


def test_code_python_multi_line_body(code_py):
    body = "x = a * 2\ny = b + 1\nresult = x + y"
    r = code_py({"body": body}, {"a": 3, "b": 4}, None)
    assert r["value"] == 11


def test_code_python_empty_body_errors(code_py):
    r = code_py({"body": ""}, {}, None)
    assert r["status"] == "error"


# ─── 3. sandbox — safe_mode default rejects dangerous tokens ─────────


def test_safe_mode_rejects_import_in_expression(code_expr):
    r = code_expr({"expr": "__import__('os').listdir('.')"},
                   {}, None)
    assert r["status"] == "error"
    assert "forbidden" in r["error"].lower()


def test_safe_mode_rejects_open_in_expression(code_expr):
    r = code_expr({"expr": "open('/etc/passwd').read()"}, {}, None)
    assert r["status"] == "error"
    assert "forbidden" in r["error"].lower()


def test_safe_mode_rejects_exec_in_python(code_py):
    r = code_py({"body": "exec('result = 1')"}, {}, None)
    assert r["status"] == "error"
    assert "forbidden" in r["error"].lower()


def test_safe_mode_rejects_dunder_class_access(code_expr):
    r = code_expr(
        {"expr": "().__class__.__bases__[0].__subclasses__()"},
        {}, None)
    assert r["status"] == "error"


def test_safe_mode_rejects_import_keyword_in_python(code_py):
    """Pre-check catches `import ` in the source even before exec."""
    r = code_py({"body": "import os\nresult = 1"}, {}, None)
    assert r["status"] == "error"
    assert "forbidden" in r["error"].lower()


# ─── 4. opt-out (safe_mode=False) allows broader access ──────────────


def test_safe_mode_off_allows_import_in_python(code_py):
    """The user explicitly opted out — `import` is now allowed."""
    body = "import math\nresult = math.floor(a)"
    r = code_py({"body": body, "safe_mode": False},
                 {"a": 3.7}, None)
    assert r["status"] == "ok"
    assert r["value"] == 3


def test_safe_mode_off_still_surfaces_runtime_errors(code_expr):
    """`safe_mode=False` removes the source pre-check but the
    runtime still raises ZeroDivisionError → typed error."""
    r = code_expr({"expr": "a / b", "safe_mode": False},
                   {"a": 1, "b": 0}, None)
    assert r["status"] == "error"
    assert "ZeroDivisionError" in r["error"]


# ─── 5. grammar primitive ────────────────────────────────────────────


def test_code_grammar_legacy_master_is_hidden():
    """Founder demand: no dropdown selectors on the canvas surface.
    `code` master with `mode: expression/python` was the last
    selector-pattern primitive. Split per Slice-I into `code_expr`
    + `code_py`; master goes hidden for saved-graph back-compat."""
    by_kind = {p.kind: p for p in ng.PRIMITIVES}
    assert "code" in by_kind
    p = by_kind["code"]
    assert p.cat == "code"
    assert p.selector == "mode"
    assert p.hidden is True  # ← no longer in the palette


def test_code_grammar_mode_resolves_to_expression():
    """Legacy master still resolves for saved graphs that reference
    `kind: 'code'` + `mode: 'expression'`."""
    assert ng.engine_type("code", {"mode": "expression"}) == \
        "code.expression"


def test_code_grammar_mode_resolves_to_python():
    assert ng.engine_type("code", {"mode": "python"}) == "code.python"


def test_typed_code_expr_resolves_to_code_expression():
    """The typed split primitive `code_expr` resolves directly."""
    assert ng.engine_type("code_expr") == "code.expression"


def test_typed_code_py_resolves_to_code_python():
    assert ng.engine_type("code_py") == "code.python"


def test_typed_code_primitives_in_visible_payload():
    """Palette shows the typed nodes (no mode dropdown). Legacy
    `code` master is hidden."""
    payload = ng.grammar_payload()
    kinds = {p["kind"] for p in payload}
    assert "code_expr" in kinds
    assert "code_py" in kinds
    # Legacy master hidden.
    assert "code" not in kinds


def test_typed_code_primitives_carry_only_relevant_params():
    """`code_expr` declares `expr` + `safe_mode` (no `mode`, no
    `body`); `code_py` declares `body` + `safe_mode` (no `mode`,
    no `expr`). No dropdown UX."""
    by_kind = {p.kind: p for p in ng.PRIMITIVES}
    expr_keys = [pp["k"] for pp in by_kind["code_expr"].params]
    py_keys = [pp["k"] for pp in by_kind["code_py"].params]
    # Expression node: expr + safe_mode, NO mode/body.
    assert "expr" in expr_keys
    assert "safe_mode" in expr_keys
    assert "mode" not in expr_keys
    assert "body" not in expr_keys
    # Python node: body + safe_mode, NO mode/expr.
    assert "body" in py_keys
    assert "safe_mode" in py_keys
    assert "mode" not in py_keys
    assert "expr" not in py_keys


def test_code_grammar_count_after_slice_l():
    """PRIMITIVES ≤ 80 (cap raised post AgDR-0021 + this code split).
    Visible HARDCODED payload ≤ 70 (bridge cap on the grammar — the
    "not a catalogue" rule). Synthesized entries (Tier 1/2 typed
    primitives + shipped Skills auto-surfaced from registry/library)
    are uncapped because they ARE real registered types, not a
    decorative palette."""
    assert len(ng.PRIMITIVES) <= 80
    payload = ng.grammar_payload()
    hardcoded = [e for e in payload if not e.get("_source")]
    assert len(hardcoded) <= 70


# ─── 6. integration — code node cooks through runner ─────────────────


def test_code_expression_cooks_through_runner():
    """A simple graph: 2 constants → code.expression → result."""
    from workflows.runner import WorkflowRunner
    g = {
        "nodes": [
            {"id": "a", "type": "data.constant", "config": {"value": 10}},
            {"id": "b", "type": "data.constant", "config": {"value": 5}},
            {"id": "calc", "type": "code.expression",
             "config": {"expr": "a + b * 2"}},
        ],
        "wires": [
            {"from": ["a", "value"], "to": ["calc", "a"]},
            {"from": ["b", "value"], "to": ["calc", "b"]},
        ],
    }
    r = WorkflowRunner(g)
    result = r.run_all()
    assert result["status"] == "ok"
    assert result["results"]["calc"]["value"] == 20  # 10 + 5*2


def test_code_python_cooks_through_runner():
    from workflows.runner import WorkflowRunner
    g = {
        "nodes": [
            {"id": "v", "type": "data.constant", "config": {"value": 7}},
            {"id": "py", "type": "code.python",
             "config": {"body": "result = a ** 2"}},
        ],
        "wires": [{"from": ["v", "value"], "to": ["py", "a"]}],
    }
    r = WorkflowRunner(g)
    result = r.run_all()
    assert result["results"]["py"]["value"] == 49
