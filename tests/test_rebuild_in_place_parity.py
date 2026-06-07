"""G3 — the byte-identical in-place stem-cell rebuild parity gate.

This is the round-2 G3 proof: ONE library node — ``control.if`` — has had its
bespoke hand-written executor RETIRED and replaced IN PLACE (same registry slot,
same type id, same frozen port contract) by a stem-cell composition
(``impl.kind=graph`` — a typed sub-graph of existing pure cells). This test is
the court: it FAILS TO REFUTE the rebuild by proving the LIVE registered
``control.if`` is byte-identical to the retired bespoke over its FULL declared
output contract on EVERY fixture, including the adversarial ones.

WHY control.if (and why the round-1 ``aec.schedule_builder`` rebuild was
REFUTED): the retired ``_if_executor`` was a PURE FUNCTION of its two declared
input ports. The four refutations that sank round-1 CANNOT arise here:

  1. ``inputs.get('rows') or []`` — schedule_builder normalised a falsy/None
     ``rows`` to ``[]``; a pure passthrough yields ``None``. DIVERGENCE.
     → control.if does NO ``x or []`` falsy-list normalization at all.
  2. ``columns or config.get('columns') or []`` — the subgraph threads only
     INPUTS into the inner graph, never config, so a config-set value with no
     input wire is lost. DIVERGENCE.
     → control.if's ``config_schema`` is EMPTY. There is NO config value that
       feeds an output, so there is structurally nothing for the graph to lose.
       (The CONFIG_ONLY fixture below pins this: config is ignored by both.)
  3. non-list input: schedule_builder's ``isinstance`` guard returned
     ``status:error``; the rebuild coerced + hardcoded ``status:ok``.
     DIVERGENCE in status AND data.
     → control.if has NO ``isinstance``-guard-to-error. It has exactly two
       return shapes and NEVER returns ``status:error`` on any input — so there
       is no ok-vs-error status conflict to create (the STATUS_AXIS test pins
       this across every fixture).
  4. the 5 fixtures never exercised None/dict/str/config-only — a BLIND gate.
     → ADVERSARIAL_FIXTURES below exercises None, missing, a dict, a str, the
       three falsy-string forms (``'false'`` / ``'0'`` / ``''``), a config-only
       case, plus unicode + float on the safe axis.

The declared output contract (what the court compares byte-for-byte) is the
NodeSpec's output PORTS — ``true`` / ``false`` / ``taken`` — exactly what the
WorkflowRunner reads off a node (``parent_out.get(src_port)``) and wires
downstream. The runner-level ``status`` channel is NOT a declared port; it is
the universal health flag the runner branches on (``status == 'error'`` →
propagate). The rebuild adds ``status:'ok'`` (the subgraph engine's success
flag); the bespoke omitted ``status`` (also success — the runner treats absent
and ``'ok'`` identically). The STATUS_AXIS test pins that this is a benign
no-conflict (neither side ever yields ``status:error`` on these fixtures), which
is exactly the divergence class round-1 hit and this rebuild does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import workflows  # noqa: E402,F401  importing the package registers every node
from workflows import registry  # noqa: E402


TYPE_ID = "control.if"


# ─────────────────────────────────────────────────────────────────────────────
# THE FROZEN BESPOKE ORACLE — captured PRE-SWAP, verbatim from the retired
# ``_if_executor`` (git HEAD ``app/workflows/nodes/control.py`` lines 17-23,
# before this change-set deleted it). This is the reference the court grades
# against; it is NOT the rebuilt spec compared to itself — it is the original
# hand-written behaviour, frozen here so the gate keeps meaning after the
# bespoke executor is gone from the codebase.
# ─────────────────────────────────────────────────────────────────────────────
def _retired_bespoke_if(config: dict, inputs: dict, ctx) -> dict:
    cond = inputs.get("condition")
    truthy = bool(cond) and cond not in ("false", "False", "0", 0, "")
    value = inputs.get("value")
    if truthy:
        return {"true": value, "false": None, "taken": "true"}
    return {"true": None, "false": value, "taken": "false"}


# The retired bespoke's PORT SIGNATURE, captured pre-swap as a frozen literal
# (ordered (name, type) pairs per side — the same shape custom_nodes._port_
# signature freezes). The G4 test asserts the LIVE rebuilt spec equals THIS
# captured contract, so the equality is bespoke-vs-rebuild, never rebuild-vs-
# rebuild.
_BESPOKE_INPUT_SIG = [("condition", "any"), ("value", "any")]
_BESPOKE_OUTPUT_SIG = [("true", "any"), ("false", "any"), ("taken", "string")]

# The node's DECLARED output ports — the full output contract the court
# compares byte-for-byte. (Derived from the captured bespoke output signature so
# it stays anchored to the pre-swap contract, not the rebuilt one.)
_DECLARED_OUTPUT_PORTS = [name for name, _t in _BESPOKE_OUTPUT_SIG]


# ─────────────────────────────────────────────────────────────────────────────
# ADVERSARIAL FIXTURES — every input the round-1 gate was blind to, plus the
# safe axis (unicode / float) to confirm clean transcoding. Each entry is
# ``(label, inputs, config)``.
# ─────────────────────────────────────────────────────────────────────────────
ADVERSARIAL_FIXTURES = [
    # ── the divergence classes round-1's gate never tested ──────────────────
    ("none_condition",     {"condition": None, "value": None},        {}),
    ("none_value_truthy",  {"condition": True, "value": None},        {}),
    ("missing_both",       {},                                        {}),
    ("missing_value",      {"condition": True},                       {}),
    ("missing_condition",  {"value": 7},                              {}),
    ("nonlist_dict_value", {"condition": True, "value": {"k": 1}},    {}),
    ("nonlist_str_value",  {"condition": False, "value": "abc"},      {}),
    ("dict_condition",     {"condition": {"a": 1}, "value": 9},       {}),
    ("list_condition",     {"condition": [1, 2], "value": [3, 4]},    {}),
    ("empty_list_cond",    {"condition": [], "value": 1},             {}),
    ("empty_dict_cond",    {"condition": {}, "value": 1},             {}),
    # ── the bespoke's special falsy-string forms (the predicate's `not in`) ──
    ("str_false",          {"condition": "false", "value": [1, 2]},   {}),
    ("str_False",          {"condition": "False", "value": "x"},      {}),
    ("str_zero",           {"condition": "0", "value": 5},            {}),
    ("empty_string_cond",  {"condition": "", "value": 9},             {}),
    ("str_true_word",      {"condition": "true", "value": 1},         {}),
    ("str_anything",       {"condition": "yes", "value": 2},          {}),
    # ── numeric edges (int 0 is falsy via `not in (...,0,...)`; 0.0/1 too) ───
    ("int_zero",           {"condition": 0, "value": "z"},            {}),
    ("int_one",            {"condition": 1, "value": "o"},            {}),
    ("float_zero",         {"condition": 0.0, "value": 3.14},         {}),
    ("float_nonzero",      {"condition": 2.5, "value": 9.99},         {}),
    ("bool_false",         {"condition": False, "value": 1},          {}),
    # ── CONFIG-ONLY: control.if has an EMPTY config_schema. A stray config
    #    key must be IGNORED by BOTH the bespoke and the rebuild (round-1's
    #    refutation #2 was a config value silently lost; here there is none to
    #    lose — this fixture proves config is inert on this node). ────────────
    ("config_only_ignored", {"condition": True, "value": "kept"},
                            {"columns": ["X"], "title": "ignored", "junk": 1}),
    # ── the safe axis — unicode + float survive the cell transcode intact ────
    ("unicode_value",      {"condition": True, "value": "café-naïve-✓"}, {}),
    ("unicode_condition",  {"condition": "naïve", "value": "résumé"},    {}),
]


def _live_executor():
    """The LIVE registered control.if (the rebuilt graph composition) — the
    SAME (config, inputs, ctx) -> outputs callable the WorkflowRunner invokes,
    resolved straight from the registry by type id. Proves what the engine would
    actually run, not a locally-built copy."""
    hit = registry.get(TYPE_ID)
    assert hit is not None, f"{TYPE_ID} is not registered"
    _spec, executor = hit
    return executor


def _project(out: dict) -> dict:
    """Project an executor return down to the DECLARED output contract — the
    ports the runner actually reads + wires. This is the 'full declared output
    contract' the byte-identity is measured over."""
    return {port: out.get(port) for port in _DECLARED_OUTPUT_PORTS}


# ─────────────────────────────────────────────────────────────────────────────
# G3 — byte-identical cook over the FULL declared output contract, on EVERY
# fixture (including every adversarial one).
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label,inputs,config",
                         ADVERSARIAL_FIXTURES,
                         ids=[f[0] for f in ADVERSARIAL_FIXTURES])
def test_rebuild_byte_identical_to_bespoke(label, inputs, config):
    """The rebuilt control.if's declared outputs (true/false/taken) are
    byte-identical to the retired bespoke's on this fixture."""
    bespoke_out = _retired_bespoke_if(dict(config), dict(inputs), None)
    rebuilt_out = _live_executor()(dict(config), dict(inputs), None)

    assert _project(rebuilt_out) == _project(bespoke_out), (
        f"[{label}] declared-contract divergence\n"
        f"  inputs   = {inputs}\n"
        f"  bespoke  = {_project(bespoke_out)}\n"
        f"  rebuilt  = {_project(rebuilt_out)}")


def test_every_declared_port_present_on_every_fixture():
    """Defensive: the rebuilt node emits ALL declared output ports (not a
    subset) on every fixture — a missing port is a silent contract break the
    per-fixture equality could otherwise mask if both sides omitted it."""
    ex = _live_executor()
    for label, inputs, config in ADVERSARIAL_FIXTURES:
        out = ex(dict(config), dict(inputs), None)
        for port in _DECLARED_OUTPUT_PORTS:
            assert port in out, f"[{label}] rebuilt output missing port {port!r}"


# ─────────────────────────────────────────────────────────────────────────────
# STATUS AXIS — the round-1 refutation #3 was a status DIVERGENCE (bespoke
# status:error vs rebuild status:ok on non-list input). Pin that NO such
# conflict exists here: on every fixture, neither the bespoke nor the rebuild
# yields status:error. (The bespoke omits status entirely — also success — and
# the rebuild's subgraph engine sets status:ok; the runner treats absent and
# 'ok' identically, so the extra key is benign, never a conflict.)
# ─────────────────────────────────────────────────────────────────────────────
def test_status_axis_no_ok_vs_error_conflict():
    ex = _live_executor()
    for label, inputs, config in ADVERSARIAL_FIXTURES:
        bespoke_out = _retired_bespoke_if(dict(config), dict(inputs), None)
        rebuilt_out = ex(dict(config), dict(inputs), None)
        # The bespoke never sets status (always success); the rebuild may set
        # 'ok' but must NEVER set 'error' on these pure-function inputs.
        assert bespoke_out.get("status") != "error", (
            f"[{label}] (sanity) bespoke unexpectedly errored")
        assert rebuilt_out.get("status") != "error", (
            f"[{label}] rebuilt control.if returned status:error — a status "
            f"divergence (the round-1 refutation class). inputs={inputs} "
            f"out={rebuilt_out}")


# ─────────────────────────────────────────────────────────────────────────────
# G4 — port-signature equality vs the CAPTURED bespoke spec (pre-swap), NOT a
# self-comparison. The live rebuilt spec must carry exactly the frozen bespoke
# contract: condition/value -> true/false/taken, same types.
# ─────────────────────────────────────────────────────────────────────────────
def test_g4_live_port_signature_equals_captured_bespoke():
    spec, _ex = registry.get(TYPE_ID)
    live_in = [(p.name, p.type.value) for p in spec.inputs]
    live_out = [(p.name, p.type.value) for p in spec.outputs]
    assert live_in == _BESPOKE_INPUT_SIG, (
        f"input signature drifted from the captured bespoke contract: "
        f"{live_in} != {_BESPOKE_INPUT_SIG}")
    assert live_out == _BESPOKE_OUTPUT_SIG, (
        f"output signature drifted from the captured bespoke contract: "
        f"{live_out} != {_BESPOKE_OUTPUT_SIG}")


def test_g4_inplace_swap_refuses_a_port_rename():
    """The G4 gate is LIVE on control.if's slot: an in-place re-register that
    renames a port is refused (renaming breaks every saved graph keyed on the
    old id). Proves the rebuilt slot is still contract-frozen, not just that
    the current spec happens to match."""
    from workflows.custom_nodes import PortSignatureError, register_spec

    bad = {
        "type": TYPE_ID,
        "category": "control",
        "display_name": "If",
        "description": "x",
        # rename output 'true' -> 'yes' — a delete-by-mutation.
        "inputs": [{"name": "condition", "type": "any"},
                   {"name": "value", "type": "any"}],
        "outputs": [{"name": "yes", "type": "any"},
                    {"name": "false", "type": "any"},
                    {"name": "taken", "type": "string"}],
        "impl": {"kind": "passthrough"},
    }
    saved = dict(registry._REGISTRY)
    try:
        with pytest.raises(PortSignatureError):
            register_spec(bad)
        # the refusal is total — the live slot is untouched.
        spec, _ex = registry.get(TYPE_ID)
        assert [p.name for p in spec.outputs] == ["true", "false", "taken"]
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


# ─────────────────────────────────────────────────────────────────────────────
# THE REBUILD IS A STEM-CELL COMPOSITION (not a code blob) AND THE BESPOKE IS
# RETIRED — the make-it-real half of the proof.
# ─────────────────────────────────────────────────────────────────────────────
def test_rebuild_is_a_graph_composition_of_existing_cells():
    """control.if's logic is now a typed sub-graph of EXISTING registered cells
    (data.passthrough + code.expression), not a bespoke python executor."""
    from workflows.nodes import control as control_mod

    spec_dict = control_mod._IF_SPEC
    assert spec_dict["impl"]["kind"] == "graph", (
        "control.if must be rebuilt as impl.kind=graph, got "
        f"{spec_dict['impl'].get('kind')!r}")

    inner = spec_dict["impl"]["graph"]
    inner_types = sorted({n["type"] for n in inner["nodes"]})
    # Every inner node is an existing, registered library cell — no new type,
    # no inline code blob masquerading as a node.
    for t in inner_types:
        assert registry.get(t) is not None, (
            f"inner cell type {t!r} is not a registered library node — the "
            f"rebuild must compose EXISTING cells")
    # The composition is genuinely multi-cell (a real graph, not a 1-node
    # wrapper hiding a blob).
    assert len(inner["nodes"]) >= 3, (
        "the rebuild should be a real multi-cell composition")
    assert "data.passthrough" in inner_types
    assert "code.expression" in inner_types


def test_bespoke_executor_is_retired():
    """The hand-written ``_if_executor`` is GONE from the control module — the
    in-place rebuild RETIRED it (no twin, no dead parallel impl)."""
    from workflows.nodes import control as control_mod

    assert not hasattr(control_mod, "_if_executor"), (
        "the retired bespoke _if_executor must be deleted from the module")
    # And the live registration is the graph executor, not the old function.
    _spec, ex = registry.get(TYPE_ID)
    assert getattr(ex, "__name__", "") != "_if_executor"


# ═════════════════════════════════════════════════════════════════════════════
# control.merge — the SECOND in-place stem-cell rebuild (wave-3), same G3
# recipe that proved control.if. The bespoke ``_merge_executor`` (a two-port
# coalescer) is RETIRED and replaced IN PLACE by a stem-cell composition
# (``impl.kind=graph`` — passthroughs + code.expression cells). The block below
# is the same court applied to it: FAIL TO REFUTE the rebuild by proving the
# LIVE registered ``control.merge`` is byte-identical to the retired bespoke
# over its FULL declared output contract (value / source) on EVERY fixture,
# including the adversarial ones.
#
# WHY control.merge is clean (the round-1 schedule_builder refutations CANNOT
# arise here — the same three absences that made control.if safe):
#   1. NO ``x or []`` / ``x or y`` falsy-normalization. The bespoke tests
#      ``a is not None`` (an EXPLICIT None check), so a falsy-but-PRESENT ``a``
#      (0, "", [], False) is KEPT on ``value`` and labelled source "a" — never
#      coalesced to ``b``. The FALSY fixtures below pin this exactly (a
#      ``x or y`` rebuild would wrongly pick ``b`` for a=0/""/[]/False).
#   2. NO ``config.get(...)`` fallback. ``config_schema`` is EMPTY; no config
#      value feeds an output, so the subgraph (which threads only INPUTS) loses
#      nothing. The CONFIG_ONLY fixture pins config is inert on both sides.
#   3. NO ``isinstance``-guard-to-``status:error``. Exactly one return shape,
#      NEVER ``status:error`` on any input — the MERGE_STATUS_AXIS test pins it.
# ═════════════════════════════════════════════════════════════════════════════
MERGE_TYPE_ID = "control.merge"


# THE FROZEN BESPOKE ORACLE — captured PRE-SWAP, verbatim from the retired
# ``_merge_executor`` (git HEAD ``app/workflows/nodes/control.py`` lines 172-176,
# before this change-set deleted it). This is the reference the court grades
# against; NOT the rebuilt spec compared to itself — the original hand-written
# behaviour, frozen so the gate keeps meaning after the bespoke is gone.
def _retired_bespoke_merge(config: dict, inputs: dict, ctx) -> dict:
    a = inputs.get("a")
    b = inputs.get("b")
    chosen = a if a is not None else b
    return {"value": chosen,
            "source": "a" if a is not None else ("b" if b is not None else None)}


# The retired bespoke's PORT SIGNATURE, captured pre-swap as a frozen literal.
# (a/b -> value/source; value:any, source:string.) The G4 test asserts the LIVE
# rebuilt spec equals THIS captured contract — bespoke-vs-rebuild, never
# rebuild-vs-rebuild.
_BESPOKE_MERGE_INPUT_SIG = [("a", "any"), ("b", "any")]
_BESPOKE_MERGE_OUTPUT_SIG = [("value", "any"), ("source", "string")]
_DECLARED_MERGE_OUTPUT_PORTS = [name for name, _t in _BESPOKE_MERGE_OUTPUT_SIG]


# ADVERSARIAL FIXTURES — every divergence class round-1 was blind to. Each
# entry is ``(label, inputs, config)``.
MERGE_ADVERSARIAL_FIXTURES = [
    # ── the basic coalesce truth table ──────────────────────────────────────
    ("both_none",          {"a": None, "b": None},              {}),
    ("a_only",             {"a": 1, "b": None},                 {}),
    ("b_only",             {"a": None, "b": 2},                 {}),
    ("both_present",       {"a": 1, "b": 2},                    {}),
    # ── missing ports (the get-returns-None path) ───────────────────────────
    ("missing_both",       {},                                  {}),
    ("missing_a",          {"b": 9},                            {}),
    ("missing_b",          {"a": 9},                            {}),
    # ── FALSY-but-PRESENT `a` — the `is not None` vs `or` divergence (a
    #    `x or y` rebuild would wrongly pick b here; `a is not None` keeps a) ─
    ("a_falsy_zero",       {"a": 0, "b": 5},                    {}),
    ("a_falsy_empty_str",  {"a": "", "b": "x"},                 {}),
    ("a_falsy_empty_list", {"a": [], "b": [1]},                 {}),
    ("a_falsy_empty_dict", {"a": {}, "b": {"k": 1}},            {}),
    ("a_falsy_false",      {"a": False, "b": True},             {}),
    ("a_falsy_zero_float", {"a": 0.0, "b": 1.5},                {}),
    # ── FALSY-but-PRESENT `b` with a=None (b kept; source "b") ──────────────
    ("b_falsy_zero",       {"a": None, "b": 0},                 {}),
    ("b_falsy_empty_str",  {"a": None, "b": ""},                {}),
    ("b_falsy_false",      {"a": None, "b": False},             {}),
    # ── non-scalar payloads survive the cell transcode intact ───────────────
    ("dict_a",             {"a": {"k": 1}, "b": 2},             {}),
    ("str_a",              {"a": "abc", "b": "def"},            {}),
    ("list_both",          {"a": [1, 2], "b": [3, 4]},          {}),
    ("nested_a",           {"a": {"x": [1, {"y": 2}]}, "b": 0}, {}),
    # ── numeric / unicode safe axis ─────────────────────────────────────────
    ("float_both",         {"a": 3.14, "b": 2.71},             {}),
    ("unicode_a",          {"a": "café-naïve-✓", "b": "x"},     {}),
    ("unicode_b",          {"a": None, "b": "résumé-naïve"},    {}),
    # ── CONFIG-ONLY: control.merge has an EMPTY config_schema. A stray config
    #    key must be IGNORED by BOTH the bespoke and the rebuild (round-1's
    #    refutation #2 was a config value silently lost; here there is none to
    #    lose — config is inert on this node). ────────────────────────────────
    ("config_only_ignored", {"a": "kept", "b": "other"},
                            {"columns": ["X"], "title": "ignored", "junk": 1}),
]


def _live_merge_executor():
    """The LIVE registered control.merge (the rebuilt graph composition) — the
    SAME (config, inputs, ctx) -> outputs callable the WorkflowRunner invokes,
    resolved straight from the registry by type id."""
    hit = registry.get(MERGE_TYPE_ID)
    assert hit is not None, f"{MERGE_TYPE_ID} is not registered"
    _spec, executor = hit
    return executor


def _project_merge(out: dict) -> dict:
    """Project an executor return down to the DECLARED output contract — the
    ports the runner actually reads + wires (value / source)."""
    return {port: out.get(port) for port in _DECLARED_MERGE_OUTPUT_PORTS}


@pytest.mark.parametrize("label,inputs,config",
                         MERGE_ADVERSARIAL_FIXTURES,
                         ids=[f[0] for f in MERGE_ADVERSARIAL_FIXTURES])
def test_merge_rebuild_byte_identical_to_bespoke(label, inputs, config):
    """The rebuilt control.merge's declared outputs (value/source) are
    byte-identical to the retired bespoke's on this fixture."""
    bespoke_out = _retired_bespoke_merge(dict(config), dict(inputs), None)
    rebuilt_out = _live_merge_executor()(dict(config), dict(inputs), None)

    assert _project_merge(rebuilt_out) == _project_merge(bespoke_out), (
        f"[{label}] declared-contract divergence\n"
        f"  inputs   = {inputs}\n"
        f"  bespoke  = {_project_merge(bespoke_out)}\n"
        f"  rebuilt  = {_project_merge(rebuilt_out)}")


def test_merge_every_declared_port_present_on_every_fixture():
    """The rebuilt node emits ALL declared output ports (value + source) on
    every fixture — a missing port is a silent contract break the per-fixture
    equality could mask if both sides omitted it."""
    ex = _live_merge_executor()
    for label, inputs, config in MERGE_ADVERSARIAL_FIXTURES:
        out = ex(dict(config), dict(inputs), None)
        for port in _DECLARED_MERGE_OUTPUT_PORTS:
            assert port in out, f"[{label}] rebuilt output missing port {port!r}"


def test_merge_status_axis_no_ok_vs_error_conflict():
    """Round-1 refutation #3 was a status DIVERGENCE (bespoke status:error vs
    rebuild status:ok on a guarded input). Pin that NO such conflict exists:
    on every fixture, neither the bespoke nor the rebuild yields status:error.
    (The bespoke omits status entirely — success — and the rebuild's subgraph
    engine sets status:ok; the runner treats absent and 'ok' identically.)"""
    ex = _live_merge_executor()
    for label, inputs, config in MERGE_ADVERSARIAL_FIXTURES:
        bespoke_out = _retired_bespoke_merge(dict(config), dict(inputs), None)
        rebuilt_out = ex(dict(config), dict(inputs), None)
        assert bespoke_out.get("status") != "error", (
            f"[{label}] (sanity) bespoke unexpectedly errored")
        assert rebuilt_out.get("status") != "error", (
            f"[{label}] rebuilt control.merge returned status:error — a status "
            f"divergence (the round-1 refutation class). inputs={inputs} "
            f"out={rebuilt_out}")


def test_merge_g4_live_port_signature_equals_captured_bespoke():
    """G4 — port-signature equality vs the CAPTURED bespoke spec (pre-swap),
    NOT a self-comparison. The live rebuilt spec carries exactly the frozen
    bespoke contract: a/b -> value/source, same types."""
    spec, _ex = registry.get(MERGE_TYPE_ID)
    live_in = [(p.name, p.type.value) for p in spec.inputs]
    live_out = [(p.name, p.type.value) for p in spec.outputs]
    assert live_in == _BESPOKE_MERGE_INPUT_SIG, (
        f"input signature drifted from the captured bespoke contract: "
        f"{live_in} != {_BESPOKE_MERGE_INPUT_SIG}")
    assert live_out == _BESPOKE_MERGE_OUTPUT_SIG, (
        f"output signature drifted from the captured bespoke contract: "
        f"{live_out} != {_BESPOKE_MERGE_OUTPUT_SIG}")


def test_merge_g4_inplace_swap_refuses_a_port_rename():
    """The G4 gate is LIVE on control.merge's slot: an in-place re-register
    that renames a port is refused. Proves the rebuilt slot is still
    contract-frozen, not just that the current spec happens to match."""
    from workflows.custom_nodes import PortSignatureError, register_spec

    bad = {
        "type": MERGE_TYPE_ID,
        "category": "control",
        "display_name": "Merge",
        "description": "x",
        # rename output 'value' -> 'val' — a delete-by-mutation.
        "inputs": [{"name": "a", "type": "any"},
                   {"name": "b", "type": "any"}],
        "outputs": [{"name": "val", "type": "any"},
                    {"name": "source", "type": "string"}],
        "impl": {"kind": "passthrough"},
    }
    saved = dict(registry._REGISTRY)
    try:
        with pytest.raises(PortSignatureError):
            register_spec(bad)
        # the refusal is total — the live slot is untouched.
        spec, _ex = registry.get(MERGE_TYPE_ID)
        assert [p.name for p in spec.outputs] == ["value", "source"]
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


def test_merge_rebuild_is_a_graph_composition_of_existing_cells():
    """control.merge's logic is now a typed sub-graph of EXISTING registered
    cells (data.passthrough + code.expression), not a bespoke python executor.
    Two passthroughs (one per facade input, so each can fan to BOTH expression
    cells) + two expression cells (value + 3-way source)."""
    from workflows.nodes import control as control_mod

    spec_dict = control_mod._MERGE_SPEC
    assert spec_dict["impl"]["kind"] == "graph", (
        "control.merge must be rebuilt as impl.kind=graph, got "
        f"{spec_dict['impl'].get('kind')!r}")

    inner = spec_dict["impl"]["graph"]
    inner_types = sorted({n["type"] for n in inner["nodes"]})
    for t in inner_types:
        assert registry.get(t) is not None, (
            f"inner cell type {t!r} is not a registered library node — the "
            f"rebuild must compose EXISTING cells")
    # A real multi-cell composition (a 1-node wrapper hiding a blob would be a
    # cheat). The merge rebuild is genuinely 4 cells.
    assert len(inner["nodes"]) >= 4, (
        "the merge rebuild should be a real multi-cell composition "
        "(2 passthroughs + 2 expression cells)")
    assert "data.passthrough" in inner_types
    assert "code.expression" in inner_types


def test_merge_bespoke_executor_is_retired():
    """The hand-written ``_merge_executor`` is GONE from the control module —
    the in-place rebuild RETIRED it (no twin, no dead parallel impl)."""
    from workflows.nodes import control as control_mod

    assert not hasattr(control_mod, "_merge_executor"), (
        "the retired bespoke _merge_executor must be deleted from the module")
    # And the live registration is the graph executor, not the old function.
    _spec, ex = registry.get(MERGE_TYPE_ID)
    assert getattr(ex, "__name__", "") != "_merge_executor"


# ═════════════════════════════════════════════════════════════════════════════
# control.switch — the THIRD in-place stem-cell rebuild (wave-4), and the FIRST
# to exercise the NORMALIZATION INFRA. The bespoke ``_switch_executor`` (a
# value-equality router) is RETIRED and replaced IN PLACE by a stem-cell
# composition (``impl.kind=graph`` — a passthrough + a ``data.coalesce`` cell +
# ``code.expression`` cells). This block is the same court applied to it: FAIL
# TO REFUTE the rebuild by proving the LIVE registered ``control.switch`` is
# byte-identical to the retired bespoke over its FULL declared output contract
# (match / default / taken) on EVERY fixture, including the adversarial ones.
#
# WHY control.switch is the FIRST infra-bearing rebuild (where control.if /
# control.merge were clean): the bespoke carried a CONFIG-FALLBACK —
# ``case = inputs.get('case'); if case is None: case = config.get('case')`` —
# which is EXACTLY round-1's refutation #2 (a config value the bare subgraph
# engine loses, because the inner runner threads only INPUTS, never the facade
# node's config). The wave-4 infra closes it: a ``data.coalesce`` (mode ``none``)
# whose ``value`` is the ``case`` INPUT and whose ``fallback`` is the facade
# ``config['case']`` threaded in via a CONFIG-SOURCED seed (``source:"config"``,
# subgraph.py). The adversarial axis below PINS this byte-for-byte:
#   • CONFIG_FALLBACK — case input None, config['case'] set → the config value
#     IS used (the round-1 divergence — a bare-subgraph rebuild would lose it).
#   • CONFIG_ONLY — no `case` input wired at all, config['case'] set → same.
#   • The bespoke's OTHER subtleties also pinned: the ``str(value) == str(case)``
#     cross-type branch (1 == "1" matches), the ``None == None`` match (both
#     absent → matched on `default`-less route), and falsy-but-present `case`
#     (0/""/[]/False) which an `or`-style rebuild would mishandle.
# (No type-guard here — the bespoke has exactly two return shapes, NEVER
# ``status:error``; the SWITCH_STATUS_AXIS test pins no ok-vs-error conflict.)
# ═════════════════════════════════════════════════════════════════════════════
SWITCH_TYPE_ID = "control.switch"


# THE FROZEN BESPOKE ORACLE — captured PRE-SWAP, verbatim from the retired
# ``_switch_executor`` (git HEAD ``app/workflows/nodes/control.py``, before this
# change-set deleted it). This is the reference the court grades against; NOT the
# rebuilt spec compared to itself — the original hand-written behaviour, frozen
# so the gate keeps meaning after the bespoke is gone. Note the config-fallback
# (``if case is None: case = config.get('case')``) — the infra-closed pattern.
def _retired_bespoke_switch(config: dict, inputs: dict, ctx) -> dict:
    value = inputs.get("value")
    case = inputs.get("case")
    if case is None:
        case = (config or {}).get("case")
    matched = value == case or str(value) == str(case)
    if matched:
        return {"match": value, "default": None, "taken": "match"}
    return {"match": None, "default": value, "taken": "default"}


# The retired bespoke's PORT SIGNATURE, captured pre-swap as a frozen literal.
# (value/case -> match/default/taken; match:any default:any taken:string.) The
# G4 test asserts the LIVE rebuilt spec equals THIS captured contract —
# bespoke-vs-rebuild, never rebuild-vs-rebuild.
_BESPOKE_SWITCH_INPUT_SIG = [("value", "any"), ("case", "any")]
_BESPOKE_SWITCH_OUTPUT_SIG = [("match", "any"), ("default", "any"),
                              ("taken", "string")]
_DECLARED_SWITCH_OUTPUT_PORTS = [name for name, _t in _BESPOKE_SWITCH_OUTPUT_SIG]


# ADVERSARIAL FIXTURES — every divergence class round-1 was blind to, with the
# CONFIG-FALLBACK / CONFIG-ONLY axis front and centre (the wave-4 infra's reason
# to exist). Each entry is ``(label, inputs, config)``.
SWITCH_ADVERSARIAL_FIXTURES = [
    # ── basic equality routing (value == case) ──────────────────────────────
    ("eq_int_match",        {"value": 5, "case": 5},            {}),
    ("eq_int_nomatch",      {"value": 5, "case": 6},            {}),
    ("eq_str_match",        {"value": "a", "case": "a"},        {}),
    ("eq_str_nomatch",      {"value": "a", "case": "b"},        {}),
    # ── the str(value) == str(case) CROSS-TYPE branch (1 matches "1") ────────
    ("strcross_int_str",    {"value": 1, "case": "1"},          {}),
    ("strcross_str_int",    {"value": "2", "case": 2},          {}),
    ("strcross_float_str",  {"value": 1.5, "case": "1.5"},      {}),
    ("strcross_bool_str",   {"value": True, "case": "True"},    {}),
    ("strcross_none_str",   {"value": None, "case": "None"},    {}),
    ("strcross_no_match",   {"value": 1, "case": "2"},          {}),
    # ── both None: value=None, case=None → None == None is True → matched ────
    ("both_none_match",     {"value": None, "case": None},      {}),
    ("missing_both",        {},                                 {}),
    # ── value present, case missing/None (no config) → case stays None ───────
    ("value_set_case_none", {"value": 7, "case": None},         {}),
    ("value_none_case_set", {"value": None, "case": 3},         {}),
    ("missing_case",        {"value": "x"},                     {}),
    # ── CONFIG-FALLBACK: case input None, config['case'] set → config used.
    #    This is the round-1 refutation #2 — a config value the BARE subgraph
    #    engine would LOSE; the wave-4 config-seed threads it in. A match here
    #    proves the config-fallback fires byte-identically. ───────────────────
    ("config_fallback_match",   {"value": 9, "case": None},   {"case": 9}),
    ("config_fallback_nomatch", {"value": 9, "case": None},   {"case": 8}),
    ("config_fallback_strcross",{"value": 1, "case": None},   {"case": "1"}),
    # ── CONFIG-ONLY: no `case` input wired AT ALL, config['case'] set → the
    #    config value is the case (the inputs.get('case') -> None -> fallback
    #    path). Pins the config-seed fires even with no facade `case` wire. ────
    ("config_only_match",   {"value": "k"},               {"case": "k"}),
    ("config_only_nomatch", {"value": "k"},               {"case": "z"}),
    ("config_only_none_val",{},                            {"case": None}),
    # ── WIRED case BEATS config (case is not None → config ignored) ──────────
    ("wired_case_beats_cfg",   {"value": 1, "case": 1},   {"case": 999}),
    ("wired_case_beats_cfg_nm",{"value": 1, "case": 2},   {"case": 1}),
    # ── FALSY-but-PRESENT `case` — `case is None` is the trigger, so a falsy
    #    case (0/""/[]/False) is NOT replaced by config; an `or`-style rebuild
    #    would wrongly fall back to config here. ───────────────────────────────
    ("case_falsy_zero_keep",   {"value": 0, "case": 0},   {"case": 5}),
    ("case_falsy_zero_match",  {"value": 0, "case": 0},   {}),
    ("case_falsy_empty_str",   {"value": "", "case": ""}, {"case": "x"}),
    ("case_falsy_empty_list",  {"value": [], "case": []}, {"case": [1]}),
    ("case_falsy_false",       {"value": False, "case": False}, {"case": True}),
    ("case_falsy_zero_float",  {"value": 0.0, "case": 0.0},     {}),
    # ── value falsy variants routed on a non-match (default carries value) ───
    ("value_falsy_zero_nm",    {"value": 0, "case": 1},   {}),
    ("value_falsy_empty_nm",   {"value": "", "case": "x"},{}),
    ("value_falsy_false_nm",   {"value": False, "case": True}, {}),
    # ── non-scalar payloads survive the cell transcode (list/dict eq) ────────
    ("list_eq_match",       {"value": [1, 2], "case": [1, 2]}, {}),
    ("list_eq_nomatch",     {"value": [1, 2], "case": [3, 4]}, {}),
    ("dict_eq_match",       {"value": {"k": 1}, "case": {"k": 1}}, {}),
    ("dict_eq_nomatch",     {"value": {"k": 1}, "case": {"k": 2}}, {}),
    # ── numeric / unicode safe axis ─────────────────────────────────────────
    ("float_match",         {"value": 3.14, "case": 3.14},  {}),
    ("unicode_match",       {"value": "café-✓", "case": "café-✓"}, {}),
    ("unicode_nomatch",     {"value": "café", "case": "naïve"},    {}),
    ("unicode_config_fb",   {"value": "résumé", "case": None}, {"case": "résumé"}),
]


def _live_switch_executor():
    """The LIVE registered control.switch (the rebuilt graph composition) — the
    SAME (config, inputs, ctx) -> outputs callable the WorkflowRunner invokes,
    resolved straight from the registry by type id."""
    hit = registry.get(SWITCH_TYPE_ID)
    assert hit is not None, f"{SWITCH_TYPE_ID} is not registered"
    _spec, executor = hit
    return executor


def _project_switch(out: dict) -> dict:
    """Project an executor return down to the DECLARED output contract — the
    ports the runner actually reads + wires (match / default / taken)."""
    return {port: out.get(port) for port in _DECLARED_SWITCH_OUTPUT_PORTS}


@pytest.mark.parametrize("label,inputs,config",
                         SWITCH_ADVERSARIAL_FIXTURES,
                         ids=[f[0] for f in SWITCH_ADVERSARIAL_FIXTURES])
def test_switch_rebuild_byte_identical_to_bespoke(label, inputs, config):
    """The rebuilt control.switch's declared outputs (match/default/taken) are
    byte-identical to the retired bespoke's on this fixture — INCLUDING the
    config-fallback fixtures the wave-4 infra exists to close."""
    bespoke_out = _retired_bespoke_switch(dict(config), dict(inputs), None)
    rebuilt_out = _live_switch_executor()(dict(config), dict(inputs), None)

    assert _project_switch(rebuilt_out) == _project_switch(bespoke_out), (
        f"[{label}] declared-contract divergence\n"
        f"  inputs   = {inputs}\n"
        f"  config   = {config}\n"
        f"  bespoke  = {_project_switch(bespoke_out)}\n"
        f"  rebuilt  = {_project_switch(rebuilt_out)}")


def test_switch_every_declared_port_present_on_every_fixture():
    """The rebuilt node emits ALL declared output ports (match + default +
    taken) on every fixture — a missing port is a silent contract break the
    per-fixture equality could mask if both sides omitted it."""
    ex = _live_switch_executor()
    for label, inputs, config in SWITCH_ADVERSARIAL_FIXTURES:
        out = ex(dict(config), dict(inputs), None)
        for port in _DECLARED_SWITCH_OUTPUT_PORTS:
            assert port in out, f"[{label}] rebuilt output missing port {port!r}"


def test_switch_config_fallback_actually_fires():
    """Sharpest infra pin: with NO `case` input and config['case'] set, the
    rebuilt switch MUST route to `match` when value equals config['case'] — i.e.
    the config value reached the inner coalesce via the config-seed. A
    bare-subgraph rebuild (no config-seed) would lose config['case'], leave the
    coalesced case None, and mis-route. This test would FAIL on that broken
    rebuild — it is the round-1 refutation #2 made a live gate."""
    ex = _live_switch_executor()
    # value == config['case'] and NO case input → must be a `match` route.
    out = ex({"case": "target"}, {"value": "target"}, None)
    assert out.get("taken") == "match", (
        f"config-fallback did NOT fire — config['case'] was lost (the round-1 "
        f"refutation). out={out}")
    assert out.get("match") == "target" and out.get("default") is None
    # value != config['case'] and NO case input → must be a `default` route.
    out2 = ex({"case": "target"}, {"value": "other"}, None)
    assert out2.get("taken") == "default", (
        f"config-fallback mis-routed on a non-match. out={out2}")
    assert out2.get("default") == "other" and out2.get("match") is None


def test_switch_status_axis_no_ok_vs_error_conflict():
    """Round-1 refutation #3 was a status DIVERGENCE (bespoke status:error vs
    rebuild status:ok on a guarded input). Pin that NO such conflict exists:
    on every fixture, neither the bespoke nor the rebuild yields status:error.
    (The bespoke omits status entirely — success — and the rebuild's subgraph
    engine sets status:ok; the runner treats absent and 'ok' identically. switch
    has NO type-guard, so the coalesce-only inner graph never errors.)"""
    ex = _live_switch_executor()
    for label, inputs, config in SWITCH_ADVERSARIAL_FIXTURES:
        bespoke_out = _retired_bespoke_switch(dict(config), dict(inputs), None)
        rebuilt_out = ex(dict(config), dict(inputs), None)
        assert bespoke_out.get("status") != "error", (
            f"[{label}] (sanity) bespoke unexpectedly errored")
        assert rebuilt_out.get("status") != "error", (
            f"[{label}] rebuilt control.switch returned status:error — a status "
            f"divergence (the round-1 refutation class). inputs={inputs} "
            f"config={config} out={rebuilt_out}")


def test_switch_g4_live_port_signature_equals_captured_bespoke():
    """G4 — port-signature equality vs the CAPTURED bespoke spec (pre-swap),
    NOT a self-comparison. The live rebuilt spec carries exactly the frozen
    bespoke contract: value/case -> match/default/taken, same types."""
    spec, _ex = registry.get(SWITCH_TYPE_ID)
    live_in = [(p.name, p.type.value) for p in spec.inputs]
    live_out = [(p.name, p.type.value) for p in spec.outputs]
    assert live_in == _BESPOKE_SWITCH_INPUT_SIG, (
        f"input signature drifted from the captured bespoke contract: "
        f"{live_in} != {_BESPOKE_SWITCH_INPUT_SIG}")
    assert live_out == _BESPOKE_SWITCH_OUTPUT_SIG, (
        f"output signature drifted from the captured bespoke contract: "
        f"{live_out} != {_BESPOKE_SWITCH_OUTPUT_SIG}")


def test_switch_g4_required_flag_preserved():
    """The bespoke marked `value` required=True (and `case` not). The in-place
    rebuild re-stamps it, so the declared contract — including the required flag
    the graph validator reads — stays byte-identical."""
    spec, _ex = registry.get(SWITCH_TYPE_ID)
    req = {p.name: p.required for p in spec.inputs}
    assert req.get("value") is True, "value must stay required=True (bespoke)"
    assert req.get("case") is False, "case must stay optional (bespoke)"


def test_switch_g4_inplace_swap_refuses_a_port_rename():
    """The G4 gate is LIVE on control.switch's slot: an in-place re-register
    that renames a port is refused. Proves the rebuilt slot is still
    contract-frozen, not just that the current spec happens to match."""
    from workflows.custom_nodes import PortSignatureError, register_spec

    bad = {
        "type": SWITCH_TYPE_ID,
        "category": "control",
        "display_name": "Switch",
        "description": "x",
        # rename output 'match' -> 'hit' — a delete-by-mutation.
        "inputs": [{"name": "value", "type": "any"},
                   {"name": "case", "type": "any"}],
        "outputs": [{"name": "hit", "type": "any"},
                    {"name": "default", "type": "any"},
                    {"name": "taken", "type": "string"}],
        "impl": {"kind": "passthrough"},
    }
    saved = dict(registry._REGISTRY)
    try:
        with pytest.raises(PortSignatureError):
            register_spec(bad)
        # the refusal is total — the live slot is untouched.
        spec, _ex = registry.get(SWITCH_TYPE_ID)
        assert [p.name for p in spec.outputs] == ["match", "default", "taken"]
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


def test_switch_rebuild_is_a_graph_composition_of_existing_cells():
    """control.switch's logic is now a typed sub-graph of EXISTING registered
    cells (data.passthrough + data.coalesce + code.expression), not a bespoke
    python executor. Crucially it WIRES IN the data.coalesce normalization cell
    (the wave-4 infra) for the config-fallback — it does NOT hand-roll the
    fallback as a code.expression (that would re-mint the pattern the infra
    exists to retire)."""
    from workflows.nodes import control as control_mod

    spec_dict = control_mod._SWITCH_SPEC
    assert spec_dict["impl"]["kind"] == "graph", (
        "control.switch must be rebuilt as impl.kind=graph, got "
        f"{spec_dict['impl'].get('kind')!r}")

    inner = spec_dict["impl"]["graph"]
    inner_types = sorted({n["type"] for n in inner["nodes"]})
    for t in inner_types:
        assert registry.get(t) is not None, (
            f"inner cell type {t!r} is not a registered library node — the "
            f"rebuild must compose EXISTING cells")
    # The normalization infra is USED — data.coalesce closes the config-fallback,
    # not a bespoke code.expression. (ONE-SYSTEM: reuse the infra cell.)
    assert "data.coalesce" in inner_types, (
        "the config-fallback must be a wired data.coalesce cell (the wave-4 "
        "normalization infra), not a hand-rolled expression")
    assert "data.passthrough" in inner_types
    assert "code.expression" in inner_types
    # A real multi-cell composition (a 1-node wrapper hiding a blob is a cheat).
    assert len(inner["nodes"]) >= 5, (
        "the switch rebuild should be a real multi-cell composition "
        "(passthrough + coalesce + predicate + 3 gates)")


def test_switch_config_seed_wired_into_coalesce():
    """The config-fallback is closed by a CONFIG-SOURCED inner-input
    (``source:"config"`` + ``config_key:"case"``) seeding the coalesce
    `fallback` — the wave-4 subgraph.py mechanism. Pin that the rebuild actually
    declares it (not an input-only wiring that would lose config['case'])."""
    from workflows.nodes import control as control_mod

    entries = control_mod._SWITCH_INNER_INPUTS
    cfg_seeds = [e for e in entries if e.get("source") == "config"]
    assert len(cfg_seeds) == 1, (
        "exactly one config-sourced seed expected (the case fallback), got "
        f"{cfg_seeds}")
    seed = cfg_seeds[0]
    assert seed.get("config_key") == "case", (
        f"the config-seed must read config['case'], got {seed.get('config_key')!r}")
    assert seed.get("inner_port") == "fallback", (
        "the config-seed must feed the coalesce `fallback` port (the fallback "
        f"half of the config-fallback), got {seed.get('inner_port')!r}")


def test_switch_bespoke_executor_is_retired():
    """The hand-written ``_switch_executor`` is GONE from the control module —
    the in-place rebuild RETIRED it (no twin, no dead parallel impl)."""
    from workflows.nodes import control as control_mod

    assert not hasattr(control_mod, "_switch_executor"), (
        "the retired bespoke _switch_executor must be deleted from the module")
    # And the live registration is the graph executor, not the old function.
    _spec, ex = registry.get(SWITCH_TYPE_ID)
    assert getattr(ex, "__name__", "") != "_switch_executor"

# WAVE-4 — the aec.* normalization-bearing composites, rebuilt IN PLACE as
# stem-cell graph compositions (impl.kind=graph) on the WAVE-4 normalization
# infra (data.coalesce / data.ensure / config-sourced seeds). The SIX bespoke
# executors — qto_pricing / cost_estimate / column / revit_wall /
# team_member_selector / schedule_builder — are RETIRED and replaced; the block
# below is the court applied to each: FAIL TO REFUTE by proving the LIVE
# registered node is byte-identical to the retired bespoke over its FULL
# declared output contract on EVERY fixture, including the adversarial ones.
#
# WHY these are now rebuildable (where round-1's schedule_builder was REFUTED):
# the three refutation classes that sank round-1 each now have an EXACT infra
# cell, so the rebuild reproduces — not approximates — the bespoke:
#   1. `inputs.get(x) or config.get(x) or default` → an input-seed + a
#      config-sourced seed (inner_inputs `source:"config"`) fanned through
#      `data.coalesce` (mode=falsy ≡ `x or y`). The CONFIG_ONLY fixtures pin
#      that the config leg is recovered with NO input wire (round-1's #2).
#   2. `if not isinstance(x, list): return {status:error}` → `data.ensure`
#      (type=list, on_fail=error); the subgraph PROPAGATES the inner
#      status:error. The TRUTHY-non-list fixtures pin the error path; the
#      FALSY-non-list fixtures pin the coalesce-BEFORE-guard order (round-1's
#      #3 — a status divergence — is pinned absent by the STATUS-AXIS test).
#   3. the adversarial axis round-1 never tested (None/missing/dict/str/
#      config-only/falsy-present/unicode/float) is exercised exhaustively below
#      (round-1's #4, the blind gate).
#
# The frozen oracles are captured PRE-SWAP, verbatim from the retired bespoke
# bodies (git HEAD app/workflows/nodes/aec.py before this change-set deleted
# them), and are invoked through `_run_bespoke` — the SAME try/except the
# WorkflowRunner wraps an executor in (runner.py) — so a bespoke that CRASHED
# on a non-numeric input (e.g. `float('abc')`) is graded as the status:error it
# actually was inside the runner, never as an unhandled raise. This makes the
# error axis a fair bespoke-vs-rebuild comparison.
# ═════════════════════════════════════════════════════════════════════════════


def _run_bespoke(besp, config: dict, inputs: dict) -> dict:
    """Invoke a frozen bespoke oracle EXACTLY as the WorkflowRunner would —
    wrapping a raised exception into {status:error} (runner.py). The retired
    bespoke ran INSIDE the runner, so a crash WAS a status:error there."""
    try:
        out = besp(dict(config), dict(inputs), None)
        return out if isinstance(out, dict) else {"value": out}
    except Exception as ex:   # noqa: BLE001 — mirrors runner's broad catch
        return {"status": "error", "error": f"{type(ex).__name__}: {ex}"}


def _live(type_id: str):
    """The LIVE registered executor for `type_id` — the SAME callable the
    WorkflowRunner invokes, resolved straight from the registry."""
    hit = registry.get(type_id)
    assert hit is not None, f"{type_id} is not registered"
    return hit[1]


def _proj_ports(out: dict, ports) -> dict:
    return {p: out.get(p) for p in ports}


# ── the frozen bespoke oracles (verbatim from the retired aec.py) ────────────
def _bespoke_qto(config, inputs, ctx):
    quantity = float(inputs.get("quantity") or 0)
    unit_price = float(inputs.get("unit_price") or config.get("unit_price") or 0)
    currency = (inputs.get("currency") or config.get("currency") or "AED").strip()
    line_item = (inputs.get("line_item") or config.get("line_item") or "").strip()
    line_total = round(quantity * unit_price, 2)
    return {
        "status": "ok", "line_item": line_item, "quantity": quantity,
        "unit_price": unit_price, "currency": currency, "line_total": line_total,
        "formatted": f"{line_item}: {quantity:.2f} × {unit_price:.2f} {currency}"
                     f" = {line_total:.2f} {currency}",
    }


def _bespoke_cost(config, inputs, ctx):
    items = inputs.get("items") or []
    if not isinstance(items, list):
        return {"status": "error", "error": "items must be an array"}
    currency = (inputs.get("currency") or config.get("currency") or "AED").strip()
    total = 0.0
    for it in items:
        if isinstance(it, dict):
            v = it.get("line_total") or it.get("total") or 0
        else:
            v = it
        try:
            total += float(v)
        except (TypeError, ValueError):
            pass
    return {
        "status": "ok", "currency": currency, "item_count": len(items),
        "grand_total": round(total, 2),
        "formatted": f"{len(items)} items · {total:,.2f} {currency}",
    }


def _bespoke_column(config, inputs, ctx):
    section = (inputs.get("section") or config.get("section") or "300x300").strip()
    height_mm = float(inputs.get("height_mm") or config.get("height_mm") or 3000)
    material = (inputs.get("material") or config.get("material") or "Concrete").strip()
    try:
        w_mm, h_mm = [float(p) for p in section.replace("x", "X").split("X")[:2]]
    except Exception:
        return {"status": "error",
                "error": f"section '{section}' must be WxH (e.g. 300x300)"}
    volume_m3 = (w_mm / 1000) * (h_mm / 1000) * (height_mm / 1000)
    return {
        "status": "ok", "section": section, "height_mm": height_mm,
        "material": material, "width_mm": w_mm, "depth_mm": h_mm,
        "volume_m3": round(volume_m3, 4),
    }


def _bespoke_revit_wall(config, inputs, ctx):
    length_mm = float(inputs.get("length_mm") or config.get("length_mm") or 3000)
    height_mm = float(inputs.get("height_mm") or config.get("height_mm") or 2700)
    width_mm = float(inputs.get("width_mm") or config.get("width_mm") or 200)
    level = (inputs.get("level") or config.get("level") or "Level 1").strip()
    wall_type = (inputs.get("wall_type") or config.get("wall_type")
                 or "Generic - 200mm").strip()
    import json as _json
    level_lit = _json.dumps(level)
    wall_type_lit = _json.dumps(wall_type)
    csharp = (
        f"// auto-emitted by aec.revit_wall node\n"
        f"var lvl = new FilteredElementCollector(Doc)\n"
        f"    .OfClass(typeof(Level)).Cast<Level>()\n"
        f"    .FirstOrDefault(l => l.Name == {level_lit});\n"
        f"if (lvl == null) {{ result = new {{ status = \"error\","
        f" reason = \"level {level} not found\" }}; return; }}\n"
        f"var wt = new FilteredElementCollector(Doc)\n"
        f"    .OfClass(typeof(WallType)).Cast<WallType>()\n"
        f"    .FirstOrDefault(t => t.Name == {wall_type_lit});\n"
        f"if (wt == null) {{ result = new {{ status = \"error\","
        f" reason = \"wall type {wall_type} not found\" }}; return; }}\n"
        f"var line = Line.CreateBound(\n"
        f"    new XYZ(0, 0, 0),\n"
        f"    new XYZ({length_mm}/304.8, 0, 0));\n"
        f"var w = Wall.Create(Doc, line, wt.Id, lvl.Id,\n"
        f"    {height_mm}/304.8, 0, false, false);\n"
        f"result = new {{ status = \"ok\", wall_id = w.Id.IntegerValue }};\n"
    )
    return {
        "status": "ok", "length_mm": length_mm, "height_mm": height_mm,
        "width_mm": width_mm, "level": level, "wall_type": wall_type,
        "csharp": csharp,
    }


def _bespoke_team(config, inputs, ctx):
    roster = inputs.get("roster") or config.get("roster") or []
    if not isinstance(roster, list):
        return {"status": "error", "error": "roster must be an array"}
    role = (inputs.get("role") or config.get("role") or "").strip().lower()
    if role:
        picks = [m for m in roster if isinstance(m, dict)
                 and (m.get("role") or "").strip().lower() == role]
    else:
        picks = list(roster)
    return {"status": "ok", "role_filter": role, "members": picks,
            "count": len(picks)}


def _bespoke_schedule(config, inputs, ctx):
    rows = inputs.get("rows") or []
    columns = inputs.get("columns") or config.get("columns") or []
    if not isinstance(rows, list) or not isinstance(columns, list):
        return {"status": "error", "error": "rows + columns must be arrays"}
    title = (inputs.get("title") or config.get("title") or "Schedule").strip()
    return {"status": "ok", "title": title, "columns": columns,
            "row_count": len(rows), "rows": rows}


# ── per-node descriptor: (type_id, oracle, declared_ports, has_error_path,
#    fixtures). Each fixture is (label, config, inputs). ───────────────────────
AEC_NODES = {
    "aec.qto_pricing": {
        "oracle": _bespoke_qto,
        "ports": ["line_total", "formatted"],
        "has_error_path": True,   # float() of a non-numeric raises → status:error
        "input_sig": [("quantity", "number"), ("unit_price", "number"),
                      ("line_item", "string")],
        "output_sig": [("line_total", "number"), ("formatted", "string")],
        "module_attr": "_qto_pricing_exec",
        "spec_attr": "_QTO_SPEC",
        "fixtures": [
            ("basic",              {}, {"quantity": 3, "unit_price": 10}),
            ("config_only_price",  {"unit_price": 99}, {"quantity": 3}),
            ("all_missing",        {}, {}),
            ("config_currency_item", {"currency": "EGP", "line_item": "Conc"},
                                   {"quantity": 2.5}),
            ("falsy_zero_qty",     {}, {"quantity": 0, "unit_price": 5}),
            ("falsy_zero_price",   {}, {"quantity": 5, "unit_price": 0}),
            ("numeric_strings",    {}, {"quantity": "2", "unit_price": "3"}),
            ("nonnumeric_qty_errors", {}, {"quantity": "abc"}),
            ("float_values",       {}, {"quantity": 1.5, "unit_price": 2.25}),
            ("unicode_currency_item", {},
                                   {"quantity": 1, "unit_price": 1,
                                    "currency": "café", "line_item": "naïve✓"}),
            ("input_overrides_config", {"unit_price": 99, "currency": "USD"},
                                   {"quantity": 2, "unit_price": 10,
                                    "currency": "AED"}),
        ],
    },
    "aec.cost_estimate": {
        "oracle": _bespoke_cost,
        "ports": ["grand_total", "formatted"],
        "has_error_path": True,
        "input_sig": [("items", "list")],
        "output_sig": [("grand_total", "number"), ("formatted", "string")],
        "module_attr": "_cost_estimate_exec",
        "spec_attr": "_COST_SPEC",
        "fixtures": [
            ("mixed_items",        {}, {"items": [{"line_total": 5},
                                                  {"total": 3}, 2]}),
            ("none_items",         {}, {"items": None}),
            ("missing_items",      {}, {}),
            ("falsy_zero_to_empty", {}, {"items": 0}),
            ("falsy_str_to_empty", {}, {"items": ""}),
            ("falsy_dict_to_empty", {}, {"items": {}}),
            ("truthy_dict_errors", {}, {"items": {"k": 1}}),
            ("truthy_str_errors",  {}, {"items": "abc"}),
            ("truthy_number_errors", {}, {"items": 5}),
            ("config_currency",    {"currency": "EGP"}, {"items": [10, 20]}),
            ("falsy_line_totals",  {}, {"items": [{"line_total": 0},
                                                  {"line_total": None,
                                                   "total": 7}]}),
            ("float_scalars",      {}, {"items": [1.1, 2.2, 3.3]}),
            ("unicode_currency",   {}, {"items": [5], "currency": "€café"}),
        ],
    },
    "aec.column": {
        "oracle": _bespoke_column,
        "ports": ["volume_m3", "width_mm", "depth_mm"],
        "has_error_path": True,
        "input_sig": [("section", "string"), ("height_mm", "number"),
                      ("material", "string")],
        "output_sig": [("volume_m3", "number"), ("width_mm", "number"),
                       ("depth_mm", "number")],
        "module_attr": "_column_exec",
        "spec_attr": "_COLUMN_SPEC",
        "fixtures": [
            ("basic",              {}, {"section": "300x500", "height_mm": 3000}),
            ("config_section",     {"section": "400x400"}, {}),
            ("all_missing",        {}, {}),
            ("bad_section_errors", {}, {"section": "bad"}),
            ("falsy_section_default", {}, {"section": ""}),
            ("uppercase_X",        {}, {"section": "250X250"}),
            ("falsy_height_default", {}, {"height_mm": 0}),
            ("float_height",       {}, {"section": "300x300", "height_mm": 2750.5}),
            ("config_height",      {"height_mm": 4000}, {"section": "200x200"}),
            ("single_dim_errors",  {}, {"section": "300"}),
            ("input_overrides_config", {"section": "999x999", "height_mm": 1},
                                   {"section": "100x200", "height_mm": 1000}),
        ],
    },
    "aec.revit_wall": {
        "oracle": _bespoke_revit_wall,
        "ports": ["csharp", "length_mm", "height_mm"],
        "has_error_path": True,   # float() of non-numeric length/height raises
        "input_sig": [("length_mm", "number"), ("height_mm", "number"),
                      ("width_mm", "number"), ("level", "string"),
                      ("wall_type", "string")],
        "output_sig": [("csharp", "string"), ("length_mm", "number"),
                       ("height_mm", "number")],
        "module_attr": "_revit_wall_exec",
        "spec_attr": "_REVIT_WALL_SPEC",
        "fixtures": [
            ("basic",              {}, {"length_mm": 5000, "level": "L2"}),
            ("config_level",       {"level": "Roof"}, {}),
            ("all_missing",        {}, {}),
            ("falsy_length_default", {}, {"length_mm": 0}),
            ("quote_in_wall_type", {}, {"wall_type": 'Gen 100"'}),
            ("unicode_level_type", {}, {"level": "naïve", "wall_type": "café"}),
            ("config_dims",        {"length_mm": 1234, "height_mm": 2345}, {}),
            ("float_dims",         {}, {"length_mm": 3000.5, "height_mm": 2700.25}),
            ("nonnumeric_length_errors", {}, {"length_mm": "abc"}),
            ("backslash_level",    {}, {"level": "A\\B"}),
            ("input_overrides_config", {"length_mm": 9999, "level": "CfgLvl"},
                                   {"length_mm": 100, "level": "InLvl"}),
        ],
    },
    "aec.team_member_selector": {
        "oracle": _bespoke_team,
        "ports": ["members", "count"],
        "has_error_path": True,
        "input_sig": [("roster", "list"), ("role", "string")],
        "output_sig": [("members", "list"), ("count", "number")],
        "module_attr": "_team_member_exec",
        "spec_attr": "_TEAM_SPEC",
        "fixtures": [
            ("filter_arch",        {}, {"roster": [{"role": "arch"},
                                                   {"role": "eng"}],
                                        "role": "arch"}),
            ("none_roster",        {}, {"roster": None}),
            ("all_missing",        {}, {}),
            ("falsy_roster_to_empty", {}, {"roster": 0}),
            ("truthy_dict_errors", {}, {"roster": {"k": 1}}),
            ("truthy_str_errors",  {}, {"roster": "abc"}),
            ("config_roster_role", {"roster": [{"role": "PM"}]}, {"role": "pm"}),
            ("no_role_returns_all", {}, {"roster": [{"role": "x"}, {"y": 1}]}),
            ("role_case_insensitive", {}, {"roster": [{"role": "Architect"}],
                                           "role": "ARCHITECT"}),
            ("non_dict_members_skipped", {}, {"roster": ["scalar",
                                                         {"role": "eng"}],
                                              "role": "eng"}),
            ("unicode_role",       {}, {"roster": [{"role": "naïve"}],
                                        "role": "naïve"}),
            ("input_roster_overrides_config", {"roster": [{"role": "z"}]},
                                   {"roster": [{"role": "q"}], "role": "q"}),
        ],
    },
    "aec.schedule_builder": {
        "oracle": _bespoke_schedule,
        "ports": ["rows", "columns", "row_count"],
        "has_error_path": True,
        "input_sig": [("rows", "list"), ("columns", "list"),
                      ("title", "string")],
        "output_sig": [("rows", "list"), ("columns", "list"),
                       ("row_count", "number")],
        "module_attr": "_schedule_builder_exec",
        "spec_attr": "_SCHEDULE_SPEC",
        "fixtures": [
            ("basic",              {}, {"rows": [{"a": 1}], "columns": ["A"]}),
            ("config_columns",     {"columns": ["X"]}, {"rows": [1, 2]}),
            ("all_missing",        {}, {}),
            ("falsy_rows_cols_to_empty", {}, {"rows": 0, "columns": ""}),
            ("truthy_rows_errors", {}, {"rows": {"k": 1}}),
            ("truthy_cols_errors", {}, {"columns": "abc"}),
            ("config_title",       {"title": "My Schedule"},
                                   {"rows": [], "columns": []}),
            ("falsy_cols_config_fallback", {"columns": ["C1", "C2"]},
                                   {"rows": [{"r": 1}], "columns": []}),
            ("unicode_title",      {}, {"rows": [], "columns": [],
                                        "title": "Schédule✓"}),
            ("nested_rows",        {}, {"rows": [{"x": [1, {"y": 2}]}],
                                        "columns": ["x"]}),
            ("input_cols_override_config", {"columns": ["Cfg"]},
                                   {"rows": [], "columns": ["In"]}),
        ],
    },
}


def _aec_fixture_params(type_id: str):
    """(label, config, inputs) tuples for one node, with pytest ids."""
    return [(f["label"] if isinstance(f, tuple) else f[0],) + tuple(f[1:])
            for f in AEC_NODES[type_id]["fixtures"]]


def _all_aec_cases():
    """Flatten to (type_id, label, config, inputs) for one big parametrize."""
    out = []
    for type_id, d in AEC_NODES.items():
        for label, config, inputs in d["fixtures"]:
            out.append((type_id, label, config, inputs))
    return out


_AEC_CASES = _all_aec_cases()


# ─────────────────────────────────────────────────────────────────────────────
# G3 — byte-identical declared-output cook on EVERY fixture (incl. adversarial).
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "type_id,label,config,inputs", _AEC_CASES,
    ids=[f"{t}-{lbl}" for (t, lbl, _c, _i) in _AEC_CASES])
def test_aec_rebuild_byte_identical_to_bespoke(type_id, label, config, inputs):
    """The rebuilt aec node's declared outputs are byte-identical to the
    retired bespoke's on this fixture."""
    d = AEC_NODES[type_id]
    ports = d["ports"]
    bespoke_out = _run_bespoke(d["oracle"], config, inputs)
    rebuilt_out = _live(type_id)(dict(config), dict(inputs), None)
    assert _proj_ports(rebuilt_out, ports) == _proj_ports(bespoke_out, ports), (
        f"[{type_id}/{label}] declared-contract divergence\n"
        f"  config   = {config}\n  inputs   = {inputs}\n"
        f"  bespoke  = {_proj_ports(bespoke_out, ports)}\n"
        f"  rebuilt  = {_proj_ports(rebuilt_out, ports)}")


# ─────────────────────────────────────────────────────────────────────────────
# STATUS AXIS — the bespoke and the rebuild agree on error-vs-ok on EVERY
# fixture (round-1's refutation #3 was a status divergence on the guard path).
# For guarded nodes this is an IFF: the rebuilt errors EXACTLY when (and only
# when) the bespoke does — the type-guard path + the float-coerce crash both.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "type_id,label,config,inputs", _AEC_CASES,
    ids=[f"{t}-{lbl}" for (t, lbl, _c, _i) in _AEC_CASES])
def test_aec_status_axis_matches_bespoke(type_id, label, config, inputs):
    d = AEC_NODES[type_id]
    bespoke_err = _run_bespoke(d["oracle"], config, inputs).get("status") == "error"
    rebuilt_err = _live(type_id)(dict(config), dict(inputs), None).get("status") == "error"
    assert rebuilt_err == bespoke_err, (
        f"[{type_id}/{label}] status divergence (the round-1 refutation class): "
        f"bespoke_error={bespoke_err} rebuilt_error={rebuilt_err} "
        f"config={config} inputs={inputs}")


def test_aec_every_declared_port_present_on_ok_fixtures():
    """On NON-error fixtures the rebuilt node emits ALL declared output ports
    (not a subset) — a missing port is a silent contract break the per-fixture
    equality could mask if both sides omitted it. (On the error path BOTH sides
    legitimately omit the ports, pinned by the byte-identical test instead.)"""
    for type_id, d in AEC_NODES.items():
        ex = _live(type_id)
        for label, config, inputs in d["fixtures"]:
            out = ex(dict(config), dict(inputs), None)
            if out.get("status") == "error":
                continue
            for port in d["ports"]:
                assert port in out, (
                    f"[{type_id}/{label}] rebuilt output missing port {port!r}")


# ─────────────────────────────────────────────────────────────────────────────
# G4 — port-signature equality vs the captured bespoke spec (the frozen
# pre-swap contract), NOT a self-comparison. The live rebuilt spec carries
# exactly the bespoke's ordered (name, type) pairs per side.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("type_id", list(AEC_NODES),
                         ids=list(AEC_NODES))
def test_aec_g4_live_port_signature_equals_captured_bespoke(type_id):
    d = AEC_NODES[type_id]
    spec, _ex = registry.get(type_id)
    live_in = [(p.name, p.type.value) for p in spec.inputs]
    live_out = [(p.name, p.type.value) for p in spec.outputs]
    assert live_in == d["input_sig"], (
        f"[{type_id}] input signature drifted from the captured bespoke "
        f"contract: {live_in} != {d['input_sig']}")
    assert live_out == d["output_sig"], (
        f"[{type_id}] output signature drifted from the captured bespoke "
        f"contract: {live_out} != {d['output_sig']}")


@pytest.mark.parametrize("type_id", list(AEC_NODES),
                         ids=list(AEC_NODES))
def test_aec_g4_inplace_swap_refuses_a_port_rename(type_id):
    """The G4 gate is LIVE on each rebuilt aec slot: an in-place re-register
    that renames an output port is refused (renaming breaks every saved graph
    keyed on the old id). Proves the rebuilt slot is still contract-frozen."""
    from workflows.custom_nodes import PortSignatureError, register_spec

    d = AEC_NODES[type_id]
    orig_out_names = [n for n, _t in d["output_sig"]]
    bad = {
        "type": type_id, "category": "aec", "display_name": "x",
        "description": "x",
        "inputs": [{"name": n, "type": t} for n, t in d["input_sig"]],
        # rename the FIRST output port — a delete-by-mutation.
        "outputs": [{"name": ("__renamed__" if i == 0 else n), "type": t}
                    for i, (n, t) in enumerate(d["output_sig"])],
        "impl": {"kind": "passthrough"},
    }
    saved = dict(registry._REGISTRY)
    try:
        with pytest.raises(PortSignatureError):
            register_spec(bad)
        spec, _ex = registry.get(type_id)
        assert [p.name for p in spec.outputs] == orig_out_names, (
            f"[{type_id}] live slot output ports changed despite refusal")
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


# ─────────────────────────────────────────────────────────────────────────────
# THE REBUILD IS A STEM-CELL COMPOSITION (not a code blob) AND THE BESPOKE IS
# RETIRED — the make-it-real half of the proof.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("type_id", list(AEC_NODES),
                         ids=list(AEC_NODES))
def test_aec_rebuild_is_a_graph_composition_of_existing_cells(type_id):
    """Each rebuilt aec node's logic is now a typed sub-graph of EXISTING
    registered cells (data.coalesce / data.ensure / data.constant /
    data.passthrough / code.expression / code.python), not a bespoke python
    executor. The WAVE-4 normalization cells must actually appear."""
    from workflows.nodes import aec as aec_mod

    spec_dict = getattr(aec_mod, AEC_NODES[type_id]["spec_attr"])
    assert spec_dict["impl"]["kind"] == "graph", (
        f"{type_id} must be rebuilt as impl.kind=graph, got "
        f"{spec_dict['impl'].get('kind')!r}")
    inner = spec_dict["impl"]["graph"]
    inner_types = sorted({n["type"] for n in inner["nodes"]})
    for t in inner_types:
        assert registry.get(t) is not None, (
            f"[{type_id}] inner cell type {t!r} is not a registered library "
            f"node — the rebuild must compose EXISTING cells")
    assert len(inner["nodes"]) >= 3, (
        f"[{type_id}] the rebuild should be a real multi-cell composition")
    # The WAVE-4 normalization primitive is present (every aec rebuild does a
    # `inputs.get(x) or config.get(x) or default` chain via data.coalesce).
    assert "data.coalesce" in inner_types, (
        f"[{type_id}] the rebuild must use the data.coalesce normalization "
        f"cell to reproduce the bespoke `x or y` fallback")


def test_aec_guarded_nodes_use_data_ensure():
    """The three aec nodes whose bespoke had an `isinstance(x, list) →
    status:error` guard (cost_estimate / schedule_builder / team_member_
    selector) reproduce it with the data.ensure cell — not a re-handwritten
    isinstance. (revit_wall / column / qto_pricing have no list-guard; their
    only error path is a float-coerce crash, reproduced by the code body.)"""
    from workflows.nodes import aec as aec_mod

    for type_id in ("aec.cost_estimate", "aec.schedule_builder",
                    "aec.team_member_selector"):
        spec_dict = getattr(aec_mod, AEC_NODES[type_id]["spec_attr"])
        inner_types = {n["type"] for n in spec_dict["impl"]["graph"]["nodes"]}
        assert "data.ensure" in inner_types, (
            f"[{type_id}] the isinstance→error guard must be reproduced by the "
            f"data.ensure cell, got inner cells {sorted(inner_types)}")


@pytest.mark.parametrize("type_id", list(AEC_NODES),
                         ids=list(AEC_NODES))
def test_aec_bespoke_executor_is_retired(type_id):
    """The hand-written bespoke executor is GONE from the aec module — the
    in-place rebuild RETIRED it (no twin, no dead parallel impl). And the live
    registration is the graph executor, not the old function."""
    from workflows.nodes import aec as aec_mod

    attr = AEC_NODES[type_id]["module_attr"]
    assert not hasattr(aec_mod, attr), (
        f"the retired bespoke {attr} must be deleted from the aec module")
    _spec, ex = registry.get(type_id)
    assert getattr(ex, "__name__", "") != attr


def test_aec_config_sourced_seed_recovers_config_only_value():
    """Direct proof of the config-sourced-seed mechanism (round-1 refutation
    #2): with NO input wire for a field, the rebuilt node still recovers the
    `config.get(field)` value — exactly what the subgraph could NOT do before
    config-seeds existed (it threaded only INPUTS). Pinned on qto_pricing's
    unit_price (config-only) and schedule_builder's columns (config-only)."""
    qto = _live("aec.qto_pricing")
    out = qto({"unit_price": 7}, {"quantity": 3}, None)
    assert out.get("line_total") == 21.0, (
        f"config-sourced unit_price not recovered: {out}")
    sched = _live("aec.schedule_builder")
    out2 = sched({"columns": ["A", "B"]}, {"rows": [1]}, None)
    assert out2.get("columns") == ["A", "B"], (
        f"config-sourced columns not recovered: {out2}")


# ─────────────────────────────────────────────────────────────────────────────
# The WAVE-4 normalization cells are themselves registered library primitives
# (the infra the rebuilds compose). A floor test that they exist + behave.
# ─────────────────────────────────────────────────────────────────────────────
def test_wave4_data_coalesce_cell_behaviour():
    _spec, ex = registry.get("data.coalesce")
    # falsy mode reproduces `x or fallback`
    assert ex({"mode": "falsy"}, {"value": 0, "fallback": 9}, None)["value"] == 9
    assert ex({"mode": "falsy"}, {"value": 5, "fallback": 9}, None)["value"] == 5
    assert ex({"mode": "falsy"}, {"value": "", "fallback": "x"}, None)["value"] == "x"
    # none mode reproduces `x if x is not None else fallback` (falsy KEPT)
    assert ex({"mode": "none"}, {"value": 0, "fallback": 9}, None)["value"] == 0
    assert ex({"mode": "none"}, {"value": None, "fallback": 9}, None)["value"] == 9


def test_wave4_data_ensure_cell_behaviour():
    _spec, ex = registry.get("data.ensure")
    # on_fail=error → status:error on a type mismatch (the subgraph propagates)
    ok = ex({"type": "list", "on_fail": "error"}, {"value": [1, 2]}, None)
    assert ok["status"] == "ok" and ok["value"] == [1, 2]
    bad = ex({"type": "list", "on_fail": "error"}, {"value": {"k": 1}}, None)
    assert bad["status"] == "error"
    # on_fail=coerce → wrap/convert, never errors
    co = ex({"type": "list", "on_fail": "coerce"}, {"value": None}, None)
    assert co["status"] == "ok" and co["value"] == []
    co2 = ex({"type": "list", "on_fail": "coerce"}, {"value": 5}, None)
    assert co2["status"] == "ok" and co2["value"] == [5]
    # on_fail=passthrough → value untouched, never errors
    pt = ex({"type": "list", "on_fail": "passthrough"}, {"value": "x"}, None)
    assert pt["status"] == "ok" and pt["value"] == "x"

# adapter.* — the wave-4 in-place stem-cell rebuilds (six adapter composites),
# same G3 recipe that proved control.if / control.merge, now exercising the
# WAVE-4 NORMALIZATION INFRA: each bespoke `_*_executor` is RETIRED and replaced
# IN PLACE by an `impl.kind=graph` composition (data.passthrough + code cells)
# whose annotation values come from CONFIG-SOURCED inner seeds (an `inner_inputs`
# entry with `source: "config"` + `config_key: k`, seeded from the facade node's
# `config.get(k)` — app/workflows/subgraph.py, routed through impl.kind=graph by
# custom_nodes._graph_executor). The court below FAILS TO REFUTE each rebuild by
# proving the LIVE registered adapter is byte-identical to its retired bespoke
# over the FULL declared output contract (`value` + `status`) on EVERY fixture —
# including the adversarial ones the round-1 gate was blind to:
#
#   • CONFIG-ONLY (no input wire): the annotation/status values come purely from
#     config — this is the config-sourced-seed path. A subgraph threads only
#     INPUTS, never config; the rebuild closes that with `source: "config"`
#     seeds. The `*_config_only` fixtures (config set, NO `value` input) pin that
#     the seed reproduces `config.get(x)` byte-identically (refutation class #2).
#   • isinstance(value, list) SHAPE-BRANCH: list → annotate each + count=len;
#     scalar → annotate one + count=1. The `*_list` / scalar fixtures pin both.
#   • None / missing value, non-list dict/str/int, falsy-present config (0 / ""),
#     float + unicode — the safe + adversarial axes.
#
# Per-adapter we capture the FROZEN BESPOKE ORACLE verbatim (pre-swap, from git
# HEAD `app/workflows/nodes/adapter.py`), so the equality is bespoke-vs-rebuild,
# never rebuild-vs-rebuild. `_enrich` is the retired helper, frozen here too.
# ═════════════════════════════════════════════════════════════════════════════
def _retired_enrich(value, annotations):
    """The frozen retired `adapter._enrich` (pre-swap, verbatim). Annotation
    keys WIN on collision (`merged.update(annotations)`); a dict source merges,
    None → `{}`, any other (scalar / list) source → `{"_source": value}`."""
    if isinstance(value, dict):
        merged = dict(value)
    elif value is None:
        merged = {}
    else:
        merged = {"_source": value}
    merged.update(annotations)
    return merged


# ── FROZEN BESPOKE ORACLES (verbatim from git HEAD adapter.py, pre-swap) ──────
def _retired_cad_to_revit_wall(config, inputs, ctx):
    value = inputs.get("value")
    level = (config.get("level") or "Level 1").strip()
    wall_type = (config.get("wall_type") or "Generic - 200mm").strip()
    height_mm = float(config.get("height", 3000) or 3000)
    top_offset_mm = float(config.get("top_offset", 0) or 0)
    structural = bool(config.get("structural", False))
    annotations = {
        "revit_target_category": "Walls",
        "revit_wall_type":       wall_type,
        "revit_level":           level,
        "revit_height_mm":       height_mm,
        "revit_top_offset_mm":   top_offset_mm,
        "revit_structural":      structural,
        "_archhub_adapter":      "cad_to_revit_wall",
    }
    if isinstance(value, list):
        out = []
        for item in value:
            out.append(_retired_enrich(item, annotations))
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": "Walls",
                           "level": level, "wall_type": wall_type}}
    out = _retired_enrich(value, annotations)
    return {"value": out,
            "status": {"ok": True, "count": 1,
                       "target_category": "Walls",
                       "level": level, "wall_type": wall_type}}


def _retired_to_revit_directshape(config, inputs, ctx):
    value = inputs.get("value")
    target_category = (config.get("target_category") or "Generic Models").strip()
    category_name = (config.get("category_name") or "ArchHub Direct").strip()
    builtin_category = (config.get("builtin_category")
                         or "OST_GenericModel").strip()
    annotations = {
        "revit_target_category": "DirectShape",
        "revit_directshape_category": target_category,
        "revit_directshape_category_name": category_name,
        "revit_builtin_category": builtin_category,
        "_archhub_adapter":      "to_revit_directshape",
    }
    if isinstance(value, list):
        out = [_retired_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": target_category}}
    return {"value": _retired_enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": target_category}}


def _retired_max_to_revit_family(config, inputs, ctx):
    value = inputs.get("value")
    target_category = (config.get("target_category") or "Mass").strip()
    family_name = (config.get("family_name") or "ArchHubMass").strip()
    family_template = (config.get("family_template")
                        or "Metric Mass.rft").strip()
    parameters = config.get("parameters") or {}
    annotations = {
        "revit_target_category": target_category,
        "revit_family_name":     family_name,
        "revit_family_template": family_template,
        "revit_parameters":      parameters if isinstance(parameters, dict) else {},
        "_archhub_adapter":      "max_to_revit_family",
    }
    if isinstance(value, list):
        out = [_retired_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": target_category,
                           "family_name": family_name}}
    return {"value": _retired_enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": target_category,
                       "family_name": family_name}}


def _retired_cad_to_revit_detail_line(config, inputs, ctx):
    value = inputs.get("value")
    view_id = config.get("view_id", 0) or 0
    line_style = (config.get("line_style") or "Thin Lines").strip()
    annotations = {
        "revit_target_category": "DetailLines",
        "revit_view_id":         int(view_id) if view_id else 0,
        "revit_line_style":      line_style,
        "_archhub_adapter":      "cad_to_revit_detail_line",
    }
    if isinstance(value, list):
        out = [_retired_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": "DetailLines",
                           "line_style": line_style}}
    return {"value": _retired_enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": "DetailLines",
                       "line_style": line_style}}


def _retired_rhino_to_revit_beam(config, inputs, ctx):
    value = inputs.get("value")
    beam_family = (config.get("beam_family") or "W-Wide Flange").strip()
    beam_type = (config.get("beam_type") or "W12X26").strip()
    level = (config.get("level") or "Level 1").strip()
    annotations = {
        "revit_target_category": "StructuralFraming",
        "revit_beam_family":     beam_family,
        "revit_beam_type":       beam_type,
        "revit_level":           level,
        "revit_structural":      True,
        "_archhub_adapter":      "rhino_to_revit_beam",
    }
    if isinstance(value, list):
        out = [_retired_enrich(item, annotations) for item in value]
        return {"value": out,
                "status": {"ok": True, "count": len(out),
                           "target_category": "StructuralFraming",
                           "beam_family": beam_family,
                           "beam_type": beam_type, "level": level}}
    return {"value": _retired_enrich(value, annotations),
            "status": {"ok": True, "count": 1,
                       "target_category": "StructuralFraming",
                       "beam_family": beam_family,
                       "beam_type": beam_type, "level": level}}


def _retired_excel_to_revit_params(config, inputs, ctx):
    value = inputs.get("value")
    id_column = (config.get("element_id_column") or "ElementId").strip()
    ignore = set(
        c.strip() for c in (config.get("ignore_columns") or "").split(",")
        if c.strip())

    def _to_param_row(row):
        eid_raw = row.get(id_column)
        try:
            eid = int(eid_raw)
        except (TypeError, ValueError):
            eid = 0
        params = {k: v for k, v in row.items()
                  if k != id_column and k not in ignore and v is not None}
        return {
            "revit_element_id":  eid,
            "revit_parameters":  params,
            "_archhub_adapter":  "excel_to_revit_params",
            "_source_row":       row,
        }

    rows = value if isinstance(value, list) else (
        [value] if isinstance(value, dict) else [])
    out = [_to_param_row(r) for r in rows if isinstance(r, dict)]
    return {"value": out,
            "status": {"ok": True, "count": len(out),
                       "element_id_column": id_column}}


# The declared output contract every adapter shares (the ports the runner reads
# + wires): value / status. The byte-identity is measured over exactly these.
_ADAPTER_OUTPUT_PORTS = ["value", "status"]
# The captured bespoke port signature (all six share it): value -> value/status.
_BESPOKE_ADAPTER_INPUT_SIG = [("value", "any")]
_BESPOKE_ADAPTER_OUTPUT_SIG = [("value", "any"), ("status", "object")]


def _project_adapter(out: dict) -> dict:
    return {port: out.get(port) for port in _ADAPTER_OUTPUT_PORTS}


# Shared adversarial fixtures usable by every adapter (config-agnostic shapes).
# Each adapter ALSO adds its own config-bearing fixtures (incl. the config-only
# proof). Each entry is (label, inputs, config).
def _shape_fixtures(cfg: dict) -> list:
    """The value-shape adversarial axis under a fixed config: None / missing /
    non-list dict / str / int / empty-list / list / list-with-none-item /
    nested-dict / unicode."""
    return [
        ("none_value",        {"value": None},                         dict(cfg)),
        ("missing_value",     {},                                      dict(cfg)),
        ("dict_value",        {"value": {"type": "Polyline", "id": 1}}, dict(cfg)),
        ("str_value",         {"value": "abc"},                        dict(cfg)),
        ("int_value",         {"value": 5},                            dict(cfg)),
        ("empty_list",        {"value": []},                           dict(cfg)),
        ("list3",             {"value": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
                                                                       dict(cfg)),
        ("list_with_none",    {"value": [None, {"id": 1}, "scalar"]},  dict(cfg)),
        ("nested_dict",       {"value": {"a": {"b": [1, {"c": 2}]}}},  dict(cfg)),
        ("unicode_value",     {"value": {"id": "x", "n": "café-✓"}},   dict(cfg)),
    ]


# Per-adapter: (oracle, type_id, [extra config-bearing fixtures]). The extra
# fixtures each set config (incl. a *_config_only with NO `value` input — the
# config-sourced-seed proof) + falsy-present config values where they bite.
_WALL_EXTRA = [
    ("wall_full_config", {"value": {"type": "Polyline"}},
     {"level": "L1", "wall_type": "WT", "height": 3000, "top_offset": 100,
      "structural": True}),
    ("wall_config_only", {},                       # NO input — config-seed proof
     {"level": "Roof", "wall_type": "Brick", "height": 2500, "top_offset": 50,
      "structural": True}),
    ("wall_falsy_height_zero", {"value": {"id": 1}}, {"height": 0,
                                                      "top_offset": 0}),
    ("wall_falsy_empty_level", {"value": {"id": 1}}, {"level": "",
                                                      "wall_type": ""}),
    ("wall_whitespace", {"value": {"id": 1}}, {"level": "  L1  ",
                                               "wall_type": "  WT  "}),
    ("wall_float_height", {"value": {"id": 1}}, {"height": 3000.5,
                                                 "top_offset": 12.25}),
    ("wall_structural_falsy", {"value": {"id": 1}}, {"structural": 0}),
    ("wall_structural_truthy_str", {"value": {"id": 1}}, {"structural": "yes"}),
    ("wall_height_numeric_str", {"value": {"id": 1}}, {"height": "4500"}),
    ("wall_unicode_config", {"value": {"id": 1}}, {"level": "café",
                                                   "wall_type": "naïve-✓"}),
]
_DS_EXTRA = [
    ("ds_full_config", {"value": {"speckle_type": "Mesh"}},
     {"target_category": "Site", "category_name": "Sites",
      "builtin_category": "OST_Site"}),
    ("ds_config_only", {},                          # config-seed proof
     {"target_category": "Site", "category_name": "Sites",
      "builtin_category": "OST_Site"}),
    ("ds_falsy_empty", {"value": {"id": 1}}, {"target_category": "",
                                              "category_name": "",
                                              "builtin_category": ""}),
    ("ds_whitespace", {"value": {"id": 1}}, {"target_category": "  Site  "}),
    ("ds_unicode", {"value": {"id": 1}}, {"category_name": "café-✓"}),
]
_MAX_EXTRA = [
    ("max_full_config", {"value": {"speckle_type": "Mesh"}},
     {"target_category": "Mass", "family_name": "RoofPavilion",
      "family_template": "Metric Mass.rft",
      "parameters": {"Height": 12000, "Material": "Concrete"}}),
    ("max_config_only", {},                         # config-seed proof
     {"target_category": "Mass", "family_name": "Block",
      "parameters": {"H": 1}}),
    ("max_params_non_dict", {"value": {"id": 1}}, {"parameters": "not a dict"}),
    ("max_params_falsy_empty", {"value": {"id": 1}}, {"parameters": {}}),
    ("max_params_list_non_dict", {"value": {"id": 1}}, {"parameters": [1, 2]}),
    ("max_falsy_empty_names", {"value": {"id": 1}}, {"target_category": "",
                                                     "family_name": "",
                                                     "family_template": ""}),
    ("max_whitespace", {"value": {"id": 1}}, {"family_name": "  Block  "}),
    ("max_unicode", {"value": {"id": 1}}, {"family_name": "café-✓",
                                           "parameters": {"k": "résumé"}}),
]
_DL_EXTRA = [
    ("dl_full_config", {"value": {"type": "Polyline"}},
     {"view_id": 7, "line_style": "Wide Lines"}),
    ("dl_config_only", {}, {"view_id": 7, "line_style": "Wide Lines"}),  # seed
    ("dl_view_zero", {"value": {"id": 1}}, {"view_id": 0}),
    ("dl_view_numeric_str", {"value": {"id": 1}}, {"view_id": "12"}),
    ("dl_view_float", {"value": {"id": 1}}, {"view_id": 9.0}),
    ("dl_falsy_empty_style", {"value": {"id": 1}}, {"line_style": ""}),
    ("dl_whitespace", {"value": {"id": 1}}, {"line_style": "  Thin  "}),
    ("dl_unicode", {"value": {"id": 1}}, {"line_style": "café-✓"}),
]
_BEAM_EXTRA = [
    ("beam_full_config", {"value": {"type": "Curve"}},
     {"beam_family": "MyBeams", "beam_type": "B-450", "level": "Level 2"}),
    ("beam_config_only", {},                        # config-seed proof
     {"beam_family": "MyBeams", "beam_type": "B-450", "level": "Level 2"}),
    ("beam_falsy_empty", {"value": {"id": 1}}, {"beam_family": "",
                                                "beam_type": "", "level": ""}),
    ("beam_whitespace", {"value": {"id": 1}}, {"beam_family": "  MyBeams  "}),
    ("beam_unicode", {"value": {"id": 1}}, {"beam_type": "café-✓"}),
]
_EXCEL_EXTRA = [
    ("excel_two_rows", {"value": [{"ElementId": 100, "Width": 500,
                                   "Comments": "row1"},
                                  {"ElementId": 101, "Width": 700,
                                   "Comments": "row2"}]},
     {"element_id_column": "ElementId"}),
    ("excel_config_only", {},                       # config-seed proof
     {"element_id_column": "GUID", "ignore_columns": "Notes,Date"}),
    ("excel_ignore_cols", {"value": [{"ElementId": 200, "Width": 1000,
                                      "Notes": "skip", "Date": "2026"}]},
     {"element_id_column": "ElementId", "ignore_columns": "Notes, Date"}),
    ("excel_bad_eid", {"value": [{"ElementId": "not-a-number", "Width": 5}]},
     {"element_id_column": "ElementId"}),
    ("excel_none_filter", {"value": [{"ElementId": 1, "A": 10, "B": None,
                                      "C": 0}]},
     {"element_id_column": "ElementId"}),
    ("excel_single_dict", {"value": {"ElementId": 9, "Y": 2}}, {}),
    ("excel_list_non_dicts", {"value": [{"ElementId": 1}, "skip", 5, None]}, {}),
    ("excel_missing_eid_col", {"value": [{"ElementId": 1, "W": 5}]},
     {"element_id_column": "GUID"}),
    ("excel_float_eid", {"value": [{"ElementId": 3.9, "W": 1}]}, {}),
    ("excel_whitespace_idcol", {"value": [{"ElementId": 1, "W": 1}]},
     {"element_id_column": "  ElementId  "}),
    ("excel_false_kept", {"value": [{"ElementId": 1, "Flag": False}]}, {}),
    ("excel_unicode", {"value": [{"ElementId": 1, "N": "café-✓"}]}, {}),
]

# The full registry of adapters under court: type_id -> (oracle, base_config for
# the shared shape axis, extra fixtures). The shared shape axis runs under the
# base config so the list/scalar branch is exercised WITH a representative
# config too (not just defaults).
_ADAPTERS = {
    "adapter.cad_to_revit_wall": (
        _retired_cad_to_revit_wall, {"level": "Level 1"}, _WALL_EXTRA),
    "adapter.to_revit_directshape": (
        _retired_to_revit_directshape, {}, _DS_EXTRA),
    "adapter.max_to_revit_family": (
        _retired_max_to_revit_family, {"family_name": "Block"}, _MAX_EXTRA),
    "adapter.cad_to_revit_detail_line": (
        _retired_cad_to_revit_detail_line, {"line_style": "Hidden Lines"},
        _DL_EXTRA),
    "adapter.rhino_to_revit_beam": (
        _retired_rhino_to_revit_beam, {}, _BEAM_EXTRA),
    "adapter.excel_to_revit_params": (
        _retired_excel_to_revit_params, {"element_id_column": "ElementId"},
        _EXCEL_EXTRA),
}


def _all_adapter_cases() -> list:
    """Flatten every adapter's (shape axis + extra) fixtures into one
    parametrize list of (type_id, label, inputs, config)."""
    cases: list = []
    for type_id, (_oracle, base_cfg, extra) in _ADAPTERS.items():
        short = type_id.split(".", 1)[1]
        for label, ins, cfg in _shape_fixtures(base_cfg):
            cases.append((type_id, f"{short}-{label}", ins, cfg))
        for label, ins, cfg in extra:
            cases.append((type_id, f"{short}-{label}", ins, cfg))
    return cases


_ADAPTER_CASES = _all_adapter_cases()


def _live_adapter_executor(type_id: str):
    hit = registry.get(type_id)
    assert hit is not None, f"{type_id} is not registered"
    _spec, executor = hit
    return executor


@pytest.mark.parametrize(
    "type_id,label,inputs,config", _ADAPTER_CASES,
    ids=[c[1] for c in _ADAPTER_CASES])
def test_adapter_rebuild_byte_identical_to_bespoke(type_id, label, inputs,
                                                   config):
    """The rebuilt adapter's declared outputs (value/status) are byte-identical
    to its retired bespoke on this fixture — including the config-only fixtures
    (the config-sourced-seed path) and the falsy / float / unicode axes."""
    oracle = _ADAPTERS[type_id][0]
    bespoke_out = oracle(dict(config), dict(inputs), None)
    rebuilt_out = _live_adapter_executor(type_id)(dict(config), dict(inputs),
                                                  None)
    assert _project_adapter(rebuilt_out) == _project_adapter(bespoke_out), (
        f"[{label}] declared-contract divergence\n"
        f"  inputs   = {inputs}\n"
        f"  config   = {config}\n"
        f"  bespoke  = {_project_adapter(bespoke_out)}\n"
        f"  rebuilt  = {_project_adapter(rebuilt_out)}")


def test_adapter_every_declared_port_present_on_every_fixture():
    """Each rebuilt adapter emits BOTH declared output ports (value + status) on
    every fixture — a missing port is a silent contract break the per-fixture
    equality could mask if both sides omitted it."""
    for type_id, label, inputs, config in _ADAPTER_CASES:
        out = _live_adapter_executor(type_id)(dict(config), dict(inputs), None)
        for port in _ADAPTER_OUTPUT_PORTS:
            assert port in out, f"[{label}] rebuilt output missing port {port!r}"


def test_adapter_status_axis_no_ok_vs_error_conflict():
    """The bespoke adapters never set status:error (they hardcode
    status.ok=True); pin that neither the bespoke nor the rebuild yields a
    runner-level status:error on any fixture — the rebuild's subgraph engine
    sets status:'ok', the runner treats absent / 'ok' identically. (The
    declared `status` PORT is a dict carrying `ok: True`; the runner-level
    `status` channel is a separate health flag — neither must be 'error'.)"""
    for type_id, label, inputs, config in _ADAPTER_CASES:
        rebuilt_out = _live_adapter_executor(type_id)(dict(config),
                                                      dict(inputs), None)
        assert rebuilt_out.get("status") != "error", (
            f"[{label}] rebuilt {type_id} returned runner-level status:error — "
            f"a status divergence (the round-1 refutation class). "
            f"inputs={inputs} config={config} out={rebuilt_out}")


@pytest.mark.parametrize("type_id", list(_ADAPTERS), ids=list(_ADAPTERS))
def test_adapter_g4_live_port_signature_equals_captured_bespoke(type_id):
    """G4 — every rebuilt adapter carries exactly the captured bespoke port
    contract: value -> value/status (value:any, status:object), with `value`
    required. Bespoke-vs-rebuild, never rebuild-vs-rebuild."""
    spec, _ex = registry.get(type_id)
    live_in = [(p.name, p.type.value) for p in spec.inputs]
    live_out = [(p.name, p.type.value) for p in spec.outputs]
    assert live_in == _BESPOKE_ADAPTER_INPUT_SIG, (
        f"{type_id} input signature drifted from the captured bespoke "
        f"contract: {live_in} != {_BESPOKE_ADAPTER_INPUT_SIG}")
    assert live_out == _BESPOKE_ADAPTER_OUTPUT_SIG, (
        f"{type_id} output signature drifted from the captured bespoke "
        f"contract: {live_out} != {_BESPOKE_ADAPTER_OUTPUT_SIG}")
    # The bespoke marked `value` required=True — pin the rebuild kept it.
    assert spec.inputs[0].required is True, (
        f"{type_id} lost the required flag on `value` (the bespoke marked it "
        f"required; the graph validator reads it)")


@pytest.mark.parametrize("type_id", list(_ADAPTERS), ids=list(_ADAPTERS))
def test_adapter_g4_inplace_swap_refuses_a_port_rename(type_id):
    """The G4 gate is LIVE on each adapter's slot: an in-place re-register that
    renames a port is refused. Proves the rebuilt slot is still contract-frozen,
    not just that the current spec happens to match."""
    from workflows.custom_nodes import PortSignatureError, register_spec

    bad = {
        "type": type_id, "category": "adapter", "display_name": "x",
        "description": "x",
        "inputs": [{"name": "value", "type": "any"}],
        # rename output 'value' -> 'val' — a delete-by-mutation.
        "outputs": [{"name": "val", "type": "any"},
                    {"name": "status", "type": "object"}],
        "impl": {"kind": "passthrough"},
    }
    saved = dict(registry._REGISTRY)
    try:
        with pytest.raises(PortSignatureError):
            register_spec(bad)
        spec, _ex = registry.get(type_id)
        assert [p.name for p in spec.outputs] == ["value", "status"]
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


@pytest.mark.parametrize("type_id", list(_ADAPTERS), ids=list(_ADAPTERS))
def test_adapter_rebuild_is_a_graph_composition_of_existing_cells(type_id):
    """Each adapter's logic is now a typed sub-graph of EXISTING registered
    cells (data.passthrough + code.expression / code.python), not a bespoke
    python executor. The live spec carries impl.kind=graph and every inner cell
    type is a registered library node."""
    from workflows.nodes import adapter as adapter_mod

    # Find the spec dict the module exposes for this type (the _*_SPEC consts).
    spec_dict = None
    for name in dir(adapter_mod):
        obj = getattr(adapter_mod, name)
        if isinstance(obj, dict) and obj.get("type") == type_id:
            spec_dict = obj
            break
    assert spec_dict is not None, (
        f"no module-level spec dict found for {type_id}")
    assert spec_dict["impl"]["kind"] == "graph", (
        f"{type_id} must be rebuilt as impl.kind=graph, got "
        f"{spec_dict['impl'].get('kind')!r}")
    inner = spec_dict["impl"]["graph"]
    inner_types = sorted({n["type"] for n in inner["nodes"]})
    for t in inner_types:
        assert registry.get(t) is not None, (
            f"inner cell type {t!r} is not a registered library node — the "
            f"rebuild must compose EXISTING cells")
    # A real multi-cell composition (a 1-node wrapper hiding a blob is a cheat):
    # passthrough + value cell + status cell ≥ 3.
    assert len(inner["nodes"]) >= 3, (
        f"{type_id} rebuild should be a real multi-cell composition")
    assert "data.passthrough" in inner_types
    # And at least one config-sourced seed (the WAVE-4 infra under test).
    cfg_seeds = [fp for fp in spec_dict["impl"]["inner_inputs"]
                 if fp.get("source") == "config"]
    assert cfg_seeds, (
        f"{type_id} rebuild must use ≥1 config-sourced inner seed (the "
        f"config-only enrichment path) — found none")


def test_adapter_bespoke_executors_are_retired():
    """The hand-written `_*_executor` blobs are GONE from the adapter module —
    the in-place rebuild RETIRED them (no twin, no dead parallel impl). And each
    live registration is the graph executor, not the old function."""
    from workflows.nodes import adapter as adapter_mod

    retired = [
        "_cad_to_revit_wall_executor", "_to_revit_directshape_executor",
        "_max_to_revit_family_executor", "_cad_to_revit_detail_line_executor",
        "_rhino_to_revit_beam_executor", "_excel_to_revit_params_executor",
    ]
    for name in retired:
        assert not hasattr(adapter_mod, name), (
            f"the retired bespoke {name} must be deleted from the module")
    # The bespoke `_enrich` helper is retired too (its merge is now the inlined
    # `_ENRICH_FN` expression — no runtime python helper left behind).
    assert not hasattr(adapter_mod, "_enrich"), (
        "the retired bespoke `_enrich` helper must be deleted from the module")
    for type_id in _ADAPTERS:
        _spec, ex = registry.get(type_id)
        assert getattr(ex, "__name__", "") not in retired, (
            f"{type_id} is still bound to a retired bespoke executor")
