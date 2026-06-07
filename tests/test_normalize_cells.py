"""stem-rebuild Phase-0 (NORMALIZATION INFRA) — `data.coalesce` + `data.ensure`.

The two reusable NORMALIZE stem cells that close the patterns the messy
composites hand-rolled inline (and so blocked a byte-identical rebuild):

  * `data.coalesce` — the reusable `x or default` / `x if x is not None else y`
    config-fallback pattern. mode=none falls back only on None; mode=falsy falls
    back on any falsy value. ALWAYS status:ok (pure — total by construction).
  * `data.ensure` — the reusable type-guard. A match → {value, ok:true}; a miss
    is handled by on_fail: 'error' → status:"error" (the guard a subgraph
    PROPAGATES via subgraph.py:537), 'coerce' → best-effort, 'passthrough' →
    untouched. A clean ok:false (coerce/passthrough) is branchable, NOT an error.

What's pinned here:
  * both coalesce modes over real values (None / 0 / "" / [] / present);
  * a wired input beats config + a wired None is honoured (data.join parity);
  * every ensure type (list/dict/number/string/bool/any) matches/misses
    correctly, incl. the bool-is-not-a-number / int-is-not-a-bool discipline;
  * every on_fail branch (error → status:error + value None; coerce → the
    shared `_num`/wrap/str() coercion + ok:false + status ok; passthrough →
    untouched + ok:false + status ok);
  * a MALFORMED config (unknown type / on_fail) is a typed status:error,
    never a fabricated verdict;
  * both cells are registered (`registry.get(...) is not None`), ports typed,
    resolve in the node grammar, and cook end-to-end through a real
    WorkflowRunner — including the ensure status:error path a subgraph
    propagates (the whole point of this wave).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.normalize import (  # noqa: E402
    _coalesce_executor, _ensure_executor, _matches, _coerce,
)


# ═══════════════════════════════════════════════════════════════════════
# data.coalesce
# ═══════════════════════════════════════════════════════════════════════

# ─── mode=none — fall back only on None ─────────────────────────────


def test_coalesce_none_present_value_wins():
    out = _coalesce_executor(
        {"mode": "none"}, {"value": "ARC", "fallback": "DEF"}, None)
    assert out["status"] == "ok"
    assert out["value"] == "ARC"


def test_coalesce_none_falls_back_only_on_None():
    out = _coalesce_executor(
        {"mode": "none"}, {"value": None, "fallback": "DEF"}, None)
    assert out["status"] == "ok"
    assert out["value"] == "DEF"


def test_coalesce_none_keeps_falsy_non_None_values():
    # The defining difference vs `falsy`: 0 / "" / [] / False are PRESENT
    # under mode=none and must NOT trigger the fallback.
    for present in (0, "", [], {}, False):
        out = _coalesce_executor(
            {"mode": "none"}, {"value": present, "fallback": "DEF"}, None)
        assert out["value"] == present, present


# ─── mode=falsy — fall back on any falsy value ──────────────────────


def test_coalesce_falsy_present_value_wins():
    out = _coalesce_executor(
        {"mode": "falsy"}, {"value": "ARC", "fallback": "DEF"}, None)
    assert out["value"] == "ARC"


def test_coalesce_falsy_falls_back_on_every_falsy_value():
    for falsy in (None, 0, "", [], {}, False):
        out = _coalesce_executor(
            {"mode": "falsy"}, {"value": falsy, "fallback": "DEF"}, None)
        assert out["value"] == "DEF", falsy


def test_coalesce_falsy_keeps_truthy_values():
    for truthy in (1, "x", [0], {"k": 1}, True):
        out = _coalesce_executor(
            {"mode": "falsy"}, {"value": truthy, "fallback": "DEF"}, None)
        assert out["value"] == truthy, truthy


# ─── default mode + always-ok ───────────────────────────────────────


def test_coalesce_mode_defaults_to_none():
    # No mode set → defaults to `none`: a present falsy 0 is kept.
    out = _coalesce_executor({}, {"value": 0, "fallback": 9}, None)
    assert out["value"] == 0


def test_coalesce_unknown_mode_degrades_to_none_not_error():
    # mode is a closed enum; a typo must never strand a pipeline — it degrades
    # to the `none` semantics and STILL returns status ok (coalesce is total).
    out = _coalesce_executor(
        {"mode": "bogus"}, {"value": 0, "fallback": 9}, None)
    assert out["status"] == "ok"
    assert out["value"] == 0          # `none` semantics: 0 is present


def test_coalesce_is_always_status_ok():
    for cfg, ins in (
        ({"mode": "none"}, {"value": None, "fallback": None}),  # both None
        ({"mode": "falsy"}, {}),                                # nothing wired
        ({}, {"value": 1}),                                     # no fallback
    ):
        assert _coalesce_executor(cfg, ins, None)["status"] == "ok"


# ─── wired beats config; wired None honoured (data.join parity) ─────


def test_coalesce_config_value_used_when_nothing_wired():
    out = _coalesce_executor(
        {"mode": "none", "value": "CFG", "fallback": "FB"}, {}, None)
    assert out["value"] == "CFG"


def test_coalesce_wired_value_beats_config_value():
    out = _coalesce_executor(
        {"mode": "none", "value": "CFG"}, {"value": "WIRED"}, None)
    assert out["value"] == "WIRED"


def test_coalesce_wired_None_is_honoured_and_defers_to_fallback():
    # A wired explicit None is a real value: under mode=none it triggers the
    # fallback rather than reading the config `value` (the sentinel distinguishes
    # "wired None" from "nothing wired").
    out = _coalesce_executor(
        {"mode": "none", "value": "CFG", "fallback": "FB"},
        {"value": None}, None)
    assert out["value"] == "FB"


def test_coalesce_wired_fallback_beats_config_fallback():
    out = _coalesce_executor(
        {"mode": "none", "fallback": "CFG_FB"},
        {"value": None, "fallback": "WIRED_FB"}, None)
    assert out["value"] == "WIRED_FB"


# ═══════════════════════════════════════════════════════════════════════
# data.ensure
# ═══════════════════════════════════════════════════════════════════════

# ─── _matches — the type predicate (incl. bool/int discipline) ──────


def test_matches_each_type_positive():
    assert _matches([1, 2], "list")
    assert _matches({"k": 1}, "dict")
    assert _matches(3, "number")
    assert _matches(3.5, "number")
    assert _matches("x", "string")
    assert _matches(True, "bool")
    assert _matches(object(), "any")      # any always matches


def test_matches_bool_is_not_a_number():
    # bool is an int subclass; for a `number` guard a bool must NOT count
    # (mirrors math_text._num's isinstance(x, bool) discipline).
    assert _matches(True, "number") is False
    assert _matches(False, "number") is False


def test_matches_int_is_not_a_bool():
    assert _matches(1, "bool") is False
    assert _matches(0, "bool") is False


def test_matches_negative_cases():
    assert _matches("x", "list") is False
    assert _matches([1], "dict") is False
    assert _matches(None, "number") is False
    assert _matches(5, "string") is False


# ─── a match → value passes through, ok=true ────────────────────────


def test_ensure_match_passes_value_through_ok_true():
    out = _ensure_executor({"type": "list"}, {"value": [1, 2, 3]}, None)
    assert out["status"] == "ok"
    assert out["value"] == [1, 2, 3]      # unchanged
    assert out["ok"] is True


def test_ensure_type_any_always_matches():
    out = _ensure_executor({"type": "any"}, {"value": 42}, None)
    assert out["status"] == "ok"
    assert out["value"] == 42
    assert out["ok"] is True


def test_ensure_type_defaults_to_any():
    # No type set → `any` → always matches.
    out = _ensure_executor({}, {"value": "whatever"}, None)
    assert out["ok"] is True
    assert out["status"] == "ok"


# ─── on_fail=error → status:error (the subgraph-propagated guard) ───


def test_ensure_on_fail_error_is_status_error_with_blanked_value():
    out = _ensure_executor(
        {"type": "list", "on_fail": "error"}, {"value": "not-a-list"}, None)
    assert out["status"] == "error"       # subgraph.py:537 propagates this
    assert out["ok"] is False
    assert out["value"] is None           # blanked — no malformed value leaks
    assert out["error"] == "expected list"


def test_ensure_on_fail_error_is_the_default_on_fail():
    # on_fail defaults to 'error' (the type-guard the composites relied on).
    out = _ensure_executor({"type": "number"}, {"value": "x"}, None)
    assert out["status"] == "error"
    assert out["error"] == "expected number"


def test_ensure_on_fail_error_message_names_the_type():
    for t in ("list", "dict", "number", "string", "bool"):
        out = _ensure_executor(
            # a value that misses every one of these types:
            {"type": t, "on_fail": "error"}, {"value": object()}, None)
        assert out["status"] == "error"
        assert out["error"] == f"expected {t}"


# ─── on_fail=coerce → best-effort coerce, ok=false, status ok ───────


def test_ensure_coerce_scalar_to_list_wraps():
    out = _ensure_executor(
        {"type": "list", "on_fail": "coerce"}, {"value": "ARC"}, None)
    assert out["status"] == "ok"          # a clean coerce is NOT an error
    assert out["value"] == ["ARC"]        # wrapped
    assert out["ok"] is False             # but it didn't natively match


def test_ensure_coerce_None_to_list_is_empty_list():
    out = _ensure_executor(
        {"type": "list", "on_fail": "coerce"}, {"value": None}, None)
    assert out["value"] == []             # None → [], never [None]
    assert out["ok"] is False


def test_ensure_coerce_to_string_uses_str():
    out = _ensure_executor(
        {"type": "string", "on_fail": "coerce"}, {"value": 123}, None)
    assert out["value"] == "123"
    assert out["status"] == "ok"
    assert out["ok"] is False


def test_ensure_coerce_to_number_uses_shared_num():
    # ONE-SYSTEM: number coercion reuses math_text._num — a numeric string
    # parses, a non-numeric coerces to 0.0 (never raises).
    out = _ensure_executor(
        {"type": "number", "on_fail": "coerce"}, {"value": "42"}, None)
    assert out["value"] == 42.0
    out2 = _ensure_executor(
        {"type": "number", "on_fail": "coerce"}, {"value": "nope"}, None)
    assert out2["value"] == 0.0           # _num's total coercion
    assert out2["status"] == "ok"


def test_ensure_coerce_to_bool_uses_truthiness():
    assert _ensure_executor(
        {"type": "bool", "on_fail": "coerce"}, {"value": ""}, None)["value"] is False
    assert _ensure_executor(
        {"type": "bool", "on_fail": "coerce"}, {"value": "x"}, None)["value"] is True


def test_ensure_coerce_non_dict_to_dict_is_empty_dict():
    out = _ensure_executor(
        {"type": "dict", "on_fail": "coerce"}, {"value": [1, 2]}, None)
    assert out["value"] == {}
    assert out["ok"] is False


# ─── on_fail=passthrough → untouched, ok=false, status ok ───────────


def test_ensure_passthrough_emits_value_untouched():
    out = _ensure_executor(
        {"type": "list", "on_fail": "passthrough"}, {"value": "scalar"}, None)
    assert out["status"] == "ok"          # branchable, not an error
    assert out["value"] == "scalar"       # untouched (NOT coerced)
    assert out["ok"] is False


def test_ensure_passthrough_keeps_None():
    out = _ensure_executor(
        {"type": "dict", "on_fail": "passthrough"}, {"value": None}, None)
    assert out["value"] is None
    assert out["ok"] is False


# ─── _coerce direct (total-tolerant) ────────────────────────────────


def test_coerce_list_keeps_an_existing_list():
    assert _coerce([1, 2], "list") == [1, 2]


def test_coerce_dict_keeps_an_existing_dict():
    assert _coerce({"k": 1}, "dict") == {"k": 1}


def test_coerce_any_is_identity():
    sentinel = object()
    assert _coerce(sentinel, "any") is sentinel


# ─── malformed config → typed error, never fabricated ───────────────


def test_ensure_unknown_type_is_typed_error():
    out = _ensure_executor({"type": "tensor"}, {"value": 1}, None)
    assert out["status"] == "error"
    assert out["ok"] is False
    assert out["value"] is None
    assert "unknown type" in out["error"]


def test_ensure_unknown_on_fail_is_typed_error():
    out = _ensure_executor(
        {"type": "list", "on_fail": "explode"}, {"value": 1}, None)
    assert out["status"] == "error"
    assert out["value"] is None
    assert "unknown on_fail" in out["error"]


# ═══════════════════════════════════════════════════════════════════════
# registration + typed ports + grammar
# ═══════════════════════════════════════════════════════════════════════


def test_both_cells_registered():
    import workflows.nodes.normalize  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("data.coalesce") is not None
    assert reg.get("data.ensure") is not None


def test_coalesce_ports_are_typed():
    import workflows.nodes.normalize  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("data.coalesce")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"value": "any"}
    in_ports = {p.name for p in spec.inputs}
    assert {"value", "fallback"} <= in_ports


def test_ensure_ports_are_typed():
    import workflows.nodes.normalize  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("data.ensure")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"value": "any", "ok": "boolean"}
    in_ports = {p.name for p in spec.inputs}
    assert {"value"} <= in_ports
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"value"}


def test_config_schemas_have_their_enums():
    import workflows.nodes.normalize  # noqa: F401
    import workflows.registry as reg
    c_spec, _ = reg.get("data.coalesce")
    assert set(c_spec.config_schema["mode"]["options"]) == {"none", "falsy"}
    e_spec, _ = reg.get("data.ensure")
    assert set(e_spec.config_schema["type"]["options"]) == {
        "list", "dict", "number", "string", "bool", "any"}
    assert set(e_spec.config_schema["on_fail"]["options"]) == {
        "error", "coerce", "passthrough"}


def test_cells_resolve_in_grammar():
    import workflows  # noqa: F401  registers built-ins
    from workflows import node_grammar as ng
    assert ng.engine_type("coalesce") == "data.coalesce"
    assert ng.engine_type("ensure") == "data.ensure"


# ═══════════════════════════════════════════════════════════════════════
# end-to-end: cook the cells through a real WorkflowRunner
# ═══════════════════════════════════════════════════════════════════════


def _ensure_const(type_name: str):
    """Register an idempotent const source emitting config.value on `value`."""
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType
    tname = f"_test.const_{type_name}"
    if _get_spec(tname) is None:
        register(NodeSpec(
            type=tname, category="_test",
            display_name=f"Test Const {type_name}",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.ANY)],
            config_schema={}, icon="["),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})
    return tname


def test_coalesce_cooks_fallback_through_real_runner():
    """A None source → data.coalesce(mode=none) → the fallback flows out,
    driven through a real outer WorkflowRunner (the canvas cook path)."""
    import workflows.nodes.normalize  # noqa: F401  registers data.coalesce
    from workflows.runner import WorkflowRunner

    src = _ensure_const("none_val")
    graph = {
        "nodes": [
            {"id": "src", "type": src, "config": {"value": None},
             "outs": [{"id": "value", "t": "any"}]},
            {"id": "c", "type": "data.coalesce",
             "config": {"mode": "none", "fallback": "DEFAULT"},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "value", "t": "any"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["c", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("c")
    assert out.get("status") == "ok"
    assert out["value"] == "DEFAULT"       # wired None deferred to the fallback


def test_ensure_cooks_match_through_real_runner():
    """A list source → data.ensure(type=list) → value passes through, ok=true,
    driven through the real runner."""
    import workflows.nodes.normalize  # noqa: F401
    from workflows.runner import WorkflowRunner

    src = _ensure_const("list_val")
    rows = [{"id": "W1"}, {"id": "W2"}]
    graph = {
        "nodes": [
            {"id": "src", "type": src, "config": {"value": rows},
             "outs": [{"id": "value", "t": "any"}]},
            {"id": "e", "type": "data.ensure",
             "config": {"type": "list", "on_fail": "error"},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "value", "t": "any"},
                      {"id": "ok",    "t": "boolean"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["e", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("e")
    assert out.get("status") == "ok"
    assert out["value"] == rows
    assert out["ok"] is True


def test_ensure_error_path_cooks_to_status_error_through_real_runner():
    """The whole point of this wave: a type miss under on_fail=error cooks to
    status:error on the real runner — the typed guard a subgraph PROPAGATES
    (subgraph.py:537) so a composite fails instead of fabricating a value."""
    import workflows.nodes.normalize  # noqa: F401
    from workflows.runner import WorkflowRunner

    src = _ensure_const("bad_val")
    graph = {
        "nodes": [
            {"id": "src", "type": src, "config": {"value": "not-a-list"},
             "outs": [{"id": "value", "t": "any"}]},
            {"id": "e", "type": "data.ensure",
             "config": {"type": "list", "on_fail": "error"},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "value", "t": "any"},
                      {"id": "ok",    "t": "boolean"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["e", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("e")
    assert out.get("status") == "error"    # propagated, not fabricated
    assert out.get("ok") is False


def test_ensure_coerce_path_cooks_through_real_runner():
    """on_fail=coerce cooks to status ok with the coerced value + ok=false (so a
    downstream node can still branch on the `ok` flag), via the real runner."""
    import workflows.nodes.normalize  # noqa: F401
    from workflows.runner import WorkflowRunner

    src = _ensure_const("scalar_val")
    graph = {
        "nodes": [
            {"id": "src", "type": src, "config": {"value": "ARC"},
             "outs": [{"id": "value", "t": "any"}]},
            {"id": "e", "type": "data.ensure",
             "config": {"type": "list", "on_fail": "coerce"},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "value", "t": "any"},
                      {"id": "ok",    "t": "boolean"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["e", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("e")
    assert out.get("status") == "ok"
    assert out["value"] == ["ARC"]         # scalar wrapped
    assert out["ok"] is False
