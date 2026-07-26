"""SLICE 2 forcing tests: WIRE-AS-NODE with GATES, GROUP-RUNS, PARAM-AS-NODE,
SCALE=GROUPING (SPEC sections 1, 3, 7, 8; section 19 operad forcing).

Written adversarially: every assertion is against a HAND-DERIVED value, the
validator is shown to actually FAIL on a corrupted gate, and every test ends
by re-running the one-table forcing validator from core (validate_store).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.core as core
from nodelang import (
    NO_VALUE, Store, OneTableViolation, FrozenNode, validate_store,
    set_gate, clear_gate, group, ungroup, promote_param, demote_param,
)


# ===================================================================== 1. GATES

def build_gated_sum(x_initial):
    """a(7) --plain wire--> sum <--GATED wire-- b(100); gate = (x > 5).
    Returns (store, ids). Hand values: gate open -> 7+100=107; closed-from-
    birth -> just 7."""
    s = Store()
    ids = {}
    ids['a'] = s.add('value', 'a', floor={'op': 'value', 'value': 7})
    ids['b'] = s.add('value', 'b', floor={'op': 'value', 'value': 100})
    ids['sum'] = s.add('op', 'a+b?', floor={'op': 'math', 'fn': '+'})
    ids['w_a'] = s.wire(ids['a'], ids['sum'])
    ids['w_b'] = s.wire(ids['b'], ids['sum'])

    # the gate subgraph: x > limit (wire order: x first, limit second)
    ids['x'] = s.add('value', 'x', floor={'op': 'value', 'value': x_initial})
    ids['limit'] = s.add('value', 'limit', floor={'op': 'value', 'value': 5})
    ids['gate'] = s.add('op', 'x>limit', floor={'op': 'compare', 'cmp': '>'})
    s.wire(ids['x'], ids['gate'])
    s.wire(ids['limit'], ids['gate'])

    set_gate(s, ids['w_b'], ids['gate'])
    return s, ids


def test_wire_opens_into_its_gate():
    s, ids = build_gated_sum(10)
    # the relation is a NODE in the one table; open() exposes endpoints + gate
    assert s.nodes[ids['w_b']]['kind'] == 'wire'
    inner = s.open(ids['w_b'])
    assert ids['gate'] in inner
    assert any(stage['role'] == 'gate' and stage['node_id'] == ids['gate']
               for stage in core.relation_stages(s.nodes, s.nodes[ids['w_b']]))
    endpoints = s.endpoints(ids['w_b'])
    assert [e['node_id'] for e in endpoints] == [ids['b'], ids['sum']]
    # the gate itself is an ordinary openable node computing a boolean
    assert s.open(ids['gate'])['op'] == 'compare'
    assert s.pull(ids['gate']) is True     # 10 > 5, hand-derived
    validate_store(s)


def test_gate_conducts_then_holds_last_without_touching_the_wire():
    s, ids = build_gated_sum(10)
    assert s.pull(ids['sum']) == 107            # gate open: 7 + 100

    # flip ONLY x (a value the gate reads) -> gate closes -> wire holds 100
    s.edit(ids['x'], ['body', 'floor', 'value'], 3)
    assert s.pull(ids['gate']) is False
    assert s.pull(ids['sum']) == 107            # holds last (100), not live

    # PROOF the gate blocks: change the source behind the closed gate
    s.edit(ids['b'], ['body', 'floor', 'value'], 999)
    assert s.pull(ids['sum']) == 107            # were the gate open: 1006

    # reopen by flipping x back -- still never touching the wire node
    s.edit(ids['x'], ['body', 'floor', 'value'], 10)
    assert s.pull(ids['sum']) == 1006           # 7 + 999 conducts live
    validate_store(s)


def test_gate_closed_from_birth_downstream_sees_no_value():
    s, ids = build_gated_sum(3)                 # 3 > 5 is False, never conducted
    assert s.pull(ids['w_b']) is NO_VALUE       # the wire itself: no value
    assert s.pull(ids['sum']) == 7              # downstream sees ONLY a

    # live recook: flip the value the gate reads; wire untouched
    s.edit(ids['x'], ['body', 'floor', 'value'], 10)
    assert s.pull(ids['sum']) == 107
    validate_store(s)


def test_clear_gate_makes_the_wire_a_plain_relation_again():
    s, ids = build_gated_sum(3)
    assert s.pull(ids['sum']) == 7
    clear_gate(s, ids['w_b'])
    assert not any(stage['role'] == 'gate'
                   for stage in core.relation_stages(s.nodes, s.nodes[ids['w_b']]))
    assert ids['gate'] not in s.open(ids['w_b'])
    assert s.pull(ids['sum']) == 107            # conducts unconditionally
    validate_store(s)


def test_validator_actually_fails_on_a_gate_outside_the_table():
    """Adversarial: the forcing validator must be able to FAIL."""
    s, ids = build_gated_sum(10)
    # bypass set_gate's check: corrupt the gate reference directly
    assignment = next(stage['assignment_param']
                      for stage in core.relation_stages(s.nodes, s.nodes[ids['w_b']])
                      if stage['role'] == 'gate')
    s.edit(assignment, ['body', 'floor', 'value', 'node_id'], 'n999999')
    with pytest.raises(OneTableViolation):
        validate_store(s)
    # and set_gate itself refuses out-of-table gates and non-wires
    with pytest.raises(KeyError):
        set_gate(s, ids['w_b'], 'n999999')
    with pytest.raises(ValueError):
        set_gate(s, ids['a'], ids['gate'])      # a value node is not a wire
    # repair -> validator green again
    set_gate(s, ids['w_b'], ids['gate'])
    validate_store(s)


# ================================================== 2. GROUP RUNS + REGROUPING

def build_six(store=None):
    """The 6-node graph used for the operad forcing.
    a=2, b=3, c=4; m=a+b=5; n=m*c=20; sink(+ over [n])=20. Returns ids."""
    s = store if store is not None else Store()
    ids = {}
    ids['a'] = s.add('value', 'a', floor={'op': 'value', 'value': 2})
    ids['b'] = s.add('value', 'b', floor={'op': 'value', 'value': 3})
    ids['c'] = s.add('value', 'c', floor={'op': 'value', 'value': 4})
    ids['m'] = s.add('op', 'a+b', floor={'op': 'math', 'fn': '+'})
    ids['n'] = s.add('op', 'm*c', floor={'op': 'math', 'fn': '*'})
    ids['sink'] = s.add('op', 'sink', floor={'op': 'math', 'fn': '+'})
    s.wire(ids['a'], ids['m'])
    s.wire(ids['b'], ids['m'])
    s.wire(ids['m'], ids['n'])
    s.wire(ids['c'], ids['n'])
    s.wire(ids['n'], ids['sink'])
    return s, ids


def test_group_runs_as_node_value_is_live_result_of_inners():
    s, ids = build_six()
    gid = group(s, [ids['a'], ids['b'], ids['m']], 'gA')
    assert s.nodes[gid]['kind'] == 'group'          # ONE node, in the table
    assert set(s.open(gid)) == {ids['a'], ids['b'], ids['m']}
    # computed port: m is the only inner wiring OUT (m -> n); value = m = 5
    assert s.pull(gid) == 5
    # LIVE: edit an inner leaf -> the group's value recooks
    s.edit(ids['a'], ['body', 'floor', 'value'], 12)
    assert s.pull(gid) == 15                        # 12 + 3
    assert s.pull(ids['sink']) == 60                # 15 * 4, through the graph
    validate_store(s)


def test_group_with_two_boundary_crossers_has_two_ports():
    s, ids = build_six()
    gid = group(s, [ids['a'], ids['b']], 'gC')      # both a and b wire out to m
    assert s.pull(gid) == [2, 3]                    # two computed ports
    validate_store(s)


def test_regroup_invariance_two_stores():
    """Same 6-node graph, grouped two different ways -> identical sink values
    (section 19: operadic composition must be associative)."""
    s1, i1 = build_six()
    group(s1, [i1['a'], i1['b'], i1['m']], 'gA')
    group(s1, [i1['c'], i1['n']], 'gB')

    s2, i2 = build_six()
    group(s2, [i2['a'], i2['b']], 'gC')
    group(s2, [i2['c'], i2['m'], i2['n']], 'gD')

    assert s1.pull(i1['sink']) == s2.pull(i2['sink']) == 20   # hand-derived
    validate_store(s1)
    validate_store(s2)


def test_regroup_invariance_one_store_regrouped_in_place():
    s, ids = build_six()
    gA = group(s, [ids['a'], ids['b'], ids['m']], 'gA')
    gB = group(s, [ids['c'], ids['n']], 'gB')
    v1 = s.pull(ids['sink'])
    ungroup(s, gA)
    ungroup(s, gB)
    gC = group(s, [ids['a'], ids['b']], 'gC')
    gD = group(s, [ids['c'], ids['m'], ids['n']], 'gD')
    v2 = s.pull(ids['sink'])
    assert v1 == v2 == 20
    assert gC in s.nodes and gD in s.nodes
    validate_store(s)


def test_collapse_expand_is_identity():
    s, ids = build_six()
    before_sink = s.pull(ids['sink'])
    before_m = s.pull(ids['m'])
    gid = group(s, [ids['a'], ids['b'], ids['m']], 'g')
    assert s.pull(ids['sink']) == before_sink       # grouping changed nothing
    children = ungroup(s, gid)
    assert children == [ids['a'], ids['b'], ids['m']]
    assert gid not in s.nodes                       # the group node is GONE
    assert s.pull(ids['sink']) == before_sink == 20
    assert s.pull(ids['m']) == before_m == 5
    validate_store(s)


def test_ungroup_splices_children_into_the_parent_group():
    s, ids = build_six()
    g_in = group(s, [ids['a'], ids['b']], 'inner')
    g_out = group(s, [g_in, ids['m']], 'outer')
    assert s.open(g_out) == [g_in, ids['m']]
    ungroup(s, g_in)
    assert s.open(g_out) == [ids['a'], ids['b'], ids['m']]   # spliced in place
    assert s.pull(ids['sink']) == 20
    validate_store(s)


def test_ungroup_refuses_non_groups_and_frozen_groups():
    s, ids = build_six()
    with pytest.raises(ValueError):
        ungroup(s, ids['a'])                        # a floor node, not a group
    gid = s.add('group', 'frozen-g', inner=[ids['a']], frozen=True)
    with pytest.raises(FrozenNode):
        ungroup(s, gid)
    validate_store(s)


# ============================================================ 3. PARAM-AS-NODE

def test_promote_param_makes_a_param_node_that_recooks_the_owner():
    s = Store()
    n8 = s.add('value', 'n8', floor={'op': 'value', 'value': 8})
    n4 = s.add('value', 'n4', floor={'op': 'value', 'value': 4})
    total = s.add('op', 'total', floor={'op': 'math', 'fn': '+'})
    s.wire(n8, total)
    s.wire(n4, total)
    assert s.pull(total) == 12

    pid = promote_param(s, n8, 'value')
    # the param IS a node, in the ONE table, wired in via the params map
    assert s.nodes[pid]['kind'] == 'param'
    assert s.nodes[n8]['params']['value'] == pid
    assert s.nodes[n8]['body']['floor']['value'] == {'$param': 'value'}
    assert s.open(pid) == {'op': 'value', 'value': 8}
    assert s.pull(total) == 12                      # promotion changed nothing

    # editing the PARAM NODE recooks the owner and everything downstream
    s.edit(pid, ['body', 'floor', 'value'], 30)
    assert s.pull(n8) == 30
    assert s.pull(total) == 34                      # 30 + 4, hand-derived
    validate_store(s)


def test_demote_param_is_identity():
    s = Store()
    n8 = s.add('value', 'n8', floor={'op': 'value', 'value': 8})
    n4 = s.add('value', 'n4', floor={'op': 'value', 'value': 4})
    total = s.add('op', 'total', floor={'op': 'math', 'fn': '+'})
    s.wire(n8, total)
    s.wire(n4, total)
    original_floor = dict(s.nodes[n8]['body']['floor'])

    promote_param(s, n8, 'value')
    demote_param(s, n8, 'value')
    assert s.nodes[n8]['body']['floor'] == original_floor   # exact identity
    assert s.nodes[n8]['params'] == {}
    assert s.pull(total) == 12
    validate_store(s)


def test_demote_carries_the_edited_value_back_to_the_floor():
    s = Store()
    n8 = s.add('value', 'n8', floor={'op': 'value', 'value': 8})
    pid = promote_param(s, n8, 'value')
    s.edit(pid, ['body', 'floor', 'value'], 30)
    demote_param(s, n8, 'value')
    assert s.nodes[n8]['body']['floor'] == {'op': 'value', 'value': 30}
    assert s.pull(n8) == 30
    validate_store(s)


def test_promote_param_adversarial_cases():
    s = Store()
    n8 = s.add('value', 'n8', floor={'op': 'value', 'value': 8})
    promote_param(s, n8, 'value')
    with pytest.raises(ValueError):
        promote_param(s, n8, 'value')               # already promoted
    with pytest.raises(KeyError):
        promote_param(s, n8, 'nope')                # no such floor field
    g = s.add('group', 'g', inner=[n8])
    with pytest.raises(ValueError):
        promote_param(s, g, 'value')                # group-ish has no floor
    with pytest.raises(KeyError):
        demote_param(s, n8, 'nope')                 # nothing promoted there
    validate_store(s)


def test_promote_a_math_fn_param_flips_the_operator_live():
    """Params are not just literals: promote the OPERATOR of a math node."""
    s = Store()
    a = s.add('value', 'a', floor={'op': 'value', 'value': 10})
    b = s.add('value', 'b', floor={'op': 'value', 'value': 4})
    op = s.add('op', 'op', floor={'op': 'math', 'fn': '-'})
    s.wire(a, op)
    s.wire(b, op)
    assert s.pull(op) == 6                          # 10 - 4
    pid = promote_param(s, op, 'fn')
    assert s.pull(op) == 6
    s.edit(pid, ['body', 'floor', 'value'], '*')
    assert s.pull(op) == 40                         # 10 * 4: the op recooked
    validate_store(s)


# ======================================================== 4. SCALE = GROUPING

def build_twenty():
    """Exactly 20 computational nodes:
    v1..v10 (1..10); s1=v1+v2=3, s2=v3+v4=7, s3=v5+v6=11, s4=v7+v8=15,
    s5=v9+v10=19; t1=s1+s2=10; t2=s3+s4=26; total=t1+t2+s5=55; k=100;
    final=total+k=155."""
    s = Store()
    v = [s.add('value', 'v%d' % i, floor={'op': 'value', 'value': i})
         for i in range(1, 11)]
    sums = []
    for j in range(5):
        sj = s.add('op', 's%d' % (j + 1), floor={'op': 'math', 'fn': '+'})
        s.wire(v[2 * j], sj)
        s.wire(v[2 * j + 1], sj)
        sums.append(sj)
    t1 = s.add('op', 't1', floor={'op': 'math', 'fn': '+'})
    s.wire(sums[0], t1)
    s.wire(sums[1], t1)
    t2 = s.add('op', 't2', floor={'op': 'math', 'fn': '+'})
    s.wire(sums[2], t2)
    s.wire(sums[3], t2)
    total = s.add('op', 'total', floor={'op': 'math', 'fn': '+'})
    s.wire(t1, total)
    s.wire(t2, total)
    s.wire(sums[4], total)
    k = s.add('value', 'k', floor={'op': 'value', 'value': 100})
    final = s.add('op', 'final', floor={'op': 'math', 'fn': '+'})
    s.wire(total, final)
    s.wire(k, final)
    ids = dict(v=v, sums=sums, t1=t1, t2=t2, total=total, k=k, final=final)
    assert len(v) + len(sums) + 5 == 20             # 10 + 5 + t1,t2,total,k,final
    return s, ids


def test_scale_four_deep_open_shows_one_level_pull_runs_through_all():
    s, ids = build_twenty()
    v, sums = ids['v'], ids['sums']
    g1 = group(s, [v[0], v[1], sums[0]], 'g1')
    g2 = group(s, [g1, v[2], v[3], sums[1], ids['t1']], 'g2')
    g3 = group(s, [g2, v[4], v[5], v[6], v[7], sums[2], sums[3], ids['t2']], 'g3')
    g4 = group(s, [g3, v[8], v[9], sums[4], ids['total']], 'g4')

    # open() shows EXACTLY one level at every depth (section 8: folded away)
    assert set(s.open(g4)) == {g3, v[8], v[9], sums[4], ids['total']}
    assert g2 not in s.open(g4) and v[0] not in s.open(g4)
    assert set(s.open(g3)) == {g2, v[4], v[5], v[6], v[7], sums[2], sums[3], ids['t2']}
    assert g1 not in s.open(g3)
    assert set(s.open(g2)) == {g1, v[2], v[3], sums[1], ids['t1']}
    assert v[0] not in s.open(g2)
    assert set(s.open(g1)) == {v[0], v[1], sums[0]}

    # pull at the top is correct through all 4 levels (hand-derived)
    assert s.pull(g1) == 3                          # 1+2
    assert s.pull(g2) == 10                         # t1
    # g3 exports TWO values (slice-4 correction, SPEC sections 3/19): t1's
    # value crosses g3's TRANSITIVE boundary too (t1, deep inside g2, wires
    # to total which lives outside g3) -- so g3's ports are [g2->10, t2->26].
    # The old '== 26' hand-derivation missed the t1->total crossing (the same
    # one-level blindness that broke regroup-invariance).
    assert s.pull(g3) == [10, 26]                   # t1 (via g2), t2
    assert s.pull(g4) == 55                         # total = 10+26+19
    assert s.pull(ids['final']) == 155              # 55 + 100

    # LIVE through 4 levels: edit the deepest leaf, the top recooks
    s.edit(v[0], ['body', 'floor', 'value'], 101)   # v1: 1 -> 101 (+100)
    assert s.pull(g4) == 155
    assert s.pull(ids['final']) == 255
    validate_store(s)


def test_everything_from_this_slice_lives_in_the_one_table():
    """The section 19 forcing on THIS slice: gate, group, param -- all rows of
    the ONE table, plus the append-only history the ops left behind."""
    s, ids = build_gated_sum(10)
    gid = group(s, [ids['a'], ids['b'], ids['sum']], 'g')
    pid = promote_param(s, ids['limit'], 'value')

    kinds = {n['kind'] for n in s.nodes.values()}
    assert {'value', 'op', 'wire', 'group', 'param', 'history'} <= kinds
    # the wire with the gate, the group, the param: same shape, same table
    for nid in (ids['w_b'], gid, pid):
        assert set(s.nodes[nid].keys()) == set(core.NODE_KEYS)
        core.validate_node(s.nodes, s.nodes[nid])
    # no second container anywhere on the store (the whitelist is closed)
    node_like = [k for k, val in vars(s).items()
                 if k != 'nodes' and isinstance(val, dict)
                 and any(isinstance(x, dict) and 'kind' in x for x in val.values())]
    assert node_like == []
    validate_store(s)
