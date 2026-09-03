"""LEGACY CATALOGUE RATCHET, superseded as architecture authority 2026-07-15.

The founder rejected the fixed role catalogue itself as non-universal. These
tests remain only to stop the legacy runtime growing while it is retained for
migration comparison. They do NOT establish that value/group/session/ui/etc.
are accepted primitives. The replacement authority is
``RESEARCH-UNIVERSAL-CELL.md`` and ``test_universal_cell_kernel.py``.

Historical line (founder, 2026-07-09): the kernel is a fixed set of roles and
floor capabilities, not a growing catalogue of special product nodes.

  "No new product feature gets a custom node type unless it is an irreducible
   floor primitive. Everything else must be a visible composition of generic
   nodes, params, wires, groups, gates, and adapters."

This test made that historical rule mechanical. It pins the closed kind set and the
closed floor-op set. Adding a bespoke product kind (e.g. 'revit', 'invoice',
'cornice') or a bespoke product op -> this test goes RED. A new entry is only
allowed after it is classified here as either an irreducible primitive or a
known-non-primitive to decompose. That is the line between the intended product
and another fake node catalogue.
"""
import os
import re

from nodelang.core import KINDS

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'nodelang', 'core.py')

# ---- Legacy migration catalogue. These are NOT accepted universal primitives.
# Each entry documents WHY it is a role, not a feature. Grow this ONLY for an
# irreducible role, never for a product feature.
PRIMITIVE_KIND_ROLES = {
    'value':      'a literal -- the leaf of every computation',
    'op':         'a computation; ALL behavior lives in its floor op, not in new kinds',
    'wire':       'a relation presentation role; its authority is open inner nodes',
    'group':      'composition / scale (structural role)',
    'param':      'a parameter IS a node (role)',
    'session':    'a group at scale + a stage param (federation role)',
    'ui':         'the surface/render floor capability (SPEC section 10)',
    'proposal':   'the AI-action safety role -- frozen until approved (section 5b)',
    'secret_ref': 'the safe-secret floor capability -- op:// only (section 5b)',
    'history':    'the append-only audit floor capability (section 5b)',
}

# ---- floor ops: irreducible generic primitives (behavior is composed FROM these)
GENERIC_FLOOR_OPS = {
    'value', 'item', 'math', 'compare', 'reduce', 'foreach', 'copy', 'merge', 'format',
    'reference', 'field', 'codec', 'aead', 'host', 'mcp', 'probe', 'probe_ok',
    'secret_ref', 'effect',
    'history',
}

# ---- floor ops that are NOT irreducible (a composable ALGORITHM baked in as a
# shortcut) and MUST be decomposed into a visible composition of generic ops.
# This set is a RATCHET: it may shrink (as items are decomposed) but a new
# bespoke op may not be added here without an explicit decision.
# EMPTY as of 2026-07-09: topsis was decomposed into an OPENABLE GROUP of generic
# nodes (nodelang.laws_decision.build_topsis_group) and its floor op removed.
KNOWN_NONPRIMITIVE_OPS_TO_DECOMPOSE = set()

PRODUCT_TERMS = ('revit', 'cornice', 'monetization', 'cockpit', 'stripe',
                 'client_project', 'client_brand', 'speckle', 'invoice',
                 'render_pdf', 'brain', 'cloud')


def _floor_ops_in_core():
    """The floor ops the compute path actually dispatches (`if op == '...'`)."""
    src = open(CORE, encoding='utf-8').read()
    return set(re.findall(r"\bop == '([a-z_0-9]+)'", src))


def test_kinds_are_exactly_the_primitive_roles():
    # closed set, pinned -- a new kind cannot be added without updating this map
    assert set(KINDS) == set(PRIMITIVE_KIND_ROLES)


def test_no_kind_is_a_product_feature():
    for k in KINDS:
        assert not any(term in k for term in PRODUCT_TERMS), \
            'kind %r looks like a product feature, not a primitive role' % k


def test_floor_ops_are_generic_primitives_or_flagged_debt():
    ops = _floor_ops_in_core()
    allowed = GENERIC_FLOOR_OPS | KNOWN_NONPRIMITIVE_OPS_TO_DECOMPOSE
    unexpected = ops - allowed
    assert not unexpected, (
        'new floor op(s) %r -- classify as an irreducible generic primitive '
        '(GENERIC_FLOOR_OPS) or as debt to decompose '
        '(KNOWN_NONPRIMITIVE_OPS_TO_DECOMPOSE). Do NOT bake a product '
        'algorithm into the floor.' % sorted(unexpected))


def test_no_floor_op_is_a_product_name():
    for op in _floor_ops_in_core():
        assert not any(term in op for term in PRODUCT_TERMS), \
            'floor op %r looks like a product feature, not a primitive' % op


def test_the_nonprimitive_ratchet_is_empty():
    # topsis was decomposed into an openable group; no bespoke algorithm remains
    # baked into the floor. Nothing may be added here without a deliberate decision.
    assert KNOWN_NONPRIMITIVE_OPS_TO_DECOMPOSE == set()
