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
