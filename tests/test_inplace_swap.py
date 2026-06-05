"""G-05 — in-place node-type swap + the G4 port-signature gate.

An in-place ``register_spec`` swap is a pop-then-rebind at one type id:
it lets the founder edit a minted node's BEHAVIOUR (swap an `add` body for
a `multiply` body) without crashing on the registry's dupe-raise. This is
the live-edit path the UI's "save custom node" uses.

G4 freezes the typed CONTRACT across that swap. A type id is what every
saved graph keys its wires on, so a same-type re-register that renames or
retypes a port is a delete-by-mutation — it silently breaks every saved
graph wired on the old id. The swap of behaviour is allowed; the swap of
the port signature is REFUSED with ``PortSignatureError``. A genuine
duplicate that bypasses the in-place path still hits the registry's own
dupe-raise.

Covers:
  (a) register type T with a v1 impl (a + b -> 15 for 5,10);
  (b) in-place swap T to v2 (a * b -> 50) with IDENTICAL ports — T now
      cooks 50 (the swap works);
  (c) a swap that CHANGES a port id, and one that changes a port TYPE,
      are both REFUSED (G4) and leave the live registration untouched;
  (d) a naive duplicate register (bypassing the in-place pop) raises
      (registry dupe-raise).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows import registry  # noqa: E402
from workflows.custom_nodes import (  # noqa: E402
    PortSignatureError,
    register_spec,
)
from workflows.registry import NodeSpec, get, register  # noqa: E402
from workflows.graph import Port, PortType  # noqa: E402


# The registry is a process-global. Snapshot + restore it around every
# test so a swap in one case can never leak into another (and so the
# real code.expression / etc. registrations survive the suite).
@pytest.fixture(autouse=True)
def _isolated_registry():
    saved = dict(registry._REGISTRY)
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


T = "swap.under_test"

# v1: inputs a,b -> add. v2: inputs a,b -> multiply. Identical ports
# (a, b -> result); only the body differs — the legal in-place swap.
_ADD = ("def execute(config, inputs, ctx):\n"
        "    return {'result': inputs.get('a', 0) + inputs.get('b', 0)}")
_MUL = ("def execute(config, inputs, ctx):\n"
        "    return {'result': inputs.get('a', 0) * inputs.get('b', 0)}")


def _spec(code: str, inputs=None, outputs=None) -> dict:
    return {
        "type": T,
        "category": "data",
        "display_name": "Swap Under Test",
        "description": "A two-input arithmetic cell used to prove the "
                       "in-place swap and the G4 port-signature gate.",
        "inputs": inputs if inputs is not None
        else [{"name": "a", "type": "number"},
              {"name": "b", "type": "number"}],
        "outputs": outputs if outputs is not None
        else [{"name": "result", "type": "number"}],
        "impl": {"kind": "python", "code": code},
    }


def _cook(type_id: str, inputs: dict) -> dict:
    """Resolve the LIVE executor from the registry by type id and cook it
    — the same (config, inputs, ctx) -> outputs contract the runner uses.
    Proves what the registry would actually run, not a local build."""
    hit = get(type_id)
    assert hit is not None, f"{type_id} is not registered"
    _spec_obj, executor = hit
    return executor({}, inputs, None)


# ── (a) register v1, it cooks 15 ────────────────────────────────────────

def test_v1_registers_and_cooks_add():
    node_spec = register_spec(_spec(_ADD))
    assert node_spec.type == T
    assert _cook(T, {"a": 5, "b": 10}) == {"result": 15}


# ── (b) in-place swap to v2 with identical ports → cooks 50 ─────────────

def test_inplace_swap_changes_behaviour_same_ports():
    register_spec(_spec(_ADD))
    assert _cook(T, {"a": 5, "b": 10}) == {"result": 15}

    # Same type id, same ports (a, b -> result), new body. The swap must
    # succeed AND the registry must now run the multiply executor.
    swapped = register_spec(_spec(_MUL))
    assert swapped.type == T
    assert _cook(T, {"a": 5, "b": 10}) == {"result": 50}

    # Exactly one registration for the type after the swap — a rebind,
    # not a second entry.
    assert sum(1 for k in registry._REGISTRY if k == T) == 1


# ── (c) G4 — a swap that changes the port signature is REFUSED ──────────

def test_swap_changing_a_port_id_is_refused():
    register_spec(_spec(_ADD))
    # Rename input 'b' -> 'c'. Every saved graph wired on 'b' would break.
    bad = _spec(_MUL, inputs=[{"name": "a", "type": "number"},
                              {"name": "c", "type": "number"}])
    with pytest.raises(PortSignatureError):
        register_spec(bad)
    # The refusal is total: the live executor is still the v1 add, and the
    # port 'b' still exists — the swap did not partially apply.
    assert _cook(T, {"a": 5, "b": 10}) == {"result": 15}
    assert [p.name for p in get(T)[0].inputs] == ["a", "b"]


def test_swap_changing_a_port_type_is_refused():
    register_spec(_spec(_ADD))
    # Same ids, but retype output 'result' number -> string. Saved graphs
    # type-checked on the old type would silently mis-wire.
    bad = _spec(_MUL, outputs=[{"name": "result", "type": "string"}])
    with pytest.raises(PortSignatureError):
        register_spec(bad)
    assert get(T)[0].outputs[0].type == PortType.NUMBER
    assert _cook(T, {"a": 5, "b": 10}) == {"result": 15}


def test_swap_adding_a_port_is_refused():
    """Even a purely additive port change is refused — adding 'c' changes
    the frozen signature, so it must be a new type, not an in-place swap."""
    register_spec(_spec(_ADD))
    bad = _spec(_ADD, inputs=[{"name": "a", "type": "number"},
                              {"name": "b", "type": "number"},
                              {"name": "c", "type": "number"}])
    with pytest.raises(PortSignatureError):
        register_spec(bad)
    assert [p.name for p in get(T)[0].inputs] == ["a", "b"]


# ── (d) naive duplicate register raises (registry dupe-raise) ───────────

def test_naive_duplicate_register_raises():
    """The low-level registry.register is the dupe backstop: a second
    register of an already-present type id raises, independent of the
    G4 signature gate. (register_spec's in-place path pops first to make
    a legal same-signature swap; calling register twice does NOT.)"""
    spec = NodeSpec(
        type="dupe.raise_me",
        category="data",
        display_name="Dupe",
        description="",
        inputs=[Port(name="a", type=PortType.NUMBER)],
        outputs=[Port(name="value", type=PortType.NUMBER)],
    )

    def _exec(config, inputs, ctx):
        return {"value": inputs.get("a", 0)}

    register(spec, _exec)              # first registration — fine
    with pytest.raises(ValueError):    # second — registry dupe-raise
        register(spec, _exec)
