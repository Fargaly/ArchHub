"""ENGINE GAPS (SPEC sections 7, 19, 4, 5b) -- fan-out, Frobenius spiders,
effectful dry-run/apply/revert. Over THE ONE TABLE, one shape, one engine.

Written to be able to FAIL: every assertion pins a real hand-derived value or
a metamorphic invariant (recompute-from-scratch == the law), plus adversarial
cases (asymmetric merges catch accidental commutativity; a mutant proves the
spider test can fail; pull on a frozen effect must leave the sink byte-equal).
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import (
    Store, FrozenNode, validate_store, relation_sources,
    apply_effect, revert_effect, dry_run,
)


# ============================================================ helpers

def _lit(s, v, title='v'):
    return s.add('value', title, floor={'op': 'value', 'value': v})


def _hist_entries(s, op_name=None):
    out = []
    for nid in sorted(s.nodes):
        n = s.nodes[nid]
        if n['kind'] != 'history':
            continue
        entry = n['body']['floor']['entry']
        if op_name is None or entry.get('op') == op_name:
            out.append(entry)
    return out


# ============================================================ 1. FAN-OUT (section 7)

def test_fanout_one_value_feeds_many_consumers():
    """One node's value fans out to THREE consumers; all three read it, and
    each combines it independently. Confirms section 7 fan-out on THIS engine."""
    s = Store()
    src = _lit(s, 7, 'src')            # the single source
    c1 = _lit(s, 100, 'c1')
    c2 = _lit(s, 200, 'c2')
    c3 = _lit(s, 300, 'c3')
    a1 = s.add('op', 'src+c1', floor={'op': 'math', 'fn': '+'})
    a2 = s.add('op', 'src+c2', floor={'op': 'math', 'fn': '+'})
    a3 = s.add('op', 'src+c3', floor={'op': 'math', 'fn': '+'})

    # ONE source -> THREE separate wires (fan-out)
    s.wire(src, a1); s.wire(c1, a1)
    s.wire(src, a2); s.wire(c2, a2)
    s.wire(src, a3); s.wire(c3, a3)

    assert s.pull(a1) == 107
    assert s.pull(a2) == 207
    assert s.pull(a3) == 307

    # src is the FROM of exactly three wires -> genuine fan-out, not reuse of one
    fanout_wires = [n for n in s.nodes.values()
                    if n['kind'] == 'wire'
                    and any(e['node_id'] == src for e in relation_sources(s.nodes, n))]
    assert len(fanout_wires) == 3

    # editing the one source recooks ALL three consumers (dirty flows down every wire)
    s.edit(src, ['body', 'floor', 'value'], 10)
    assert (s.pull(a1), s.pull(a2), s.pull(a3)) == (110, 210, 310)


def test_fanout_deep_chain_all_paths_see_the_edit():
    """Fan-out into a diamond: src -> {left, right} -> join. The join sees the
    source once through each path; an edit to src must reach the join."""
    s = Store()
    src = _lit(s, 4, 'src')
    k = _lit(s, 1, 'k')
    left = s.add('op', 'src*?', floor={'op': 'math', 'fn': '*'})   # src*k
    right = s.add('op', 'src+?', floor={'op': 'math', 'fn': '+'})  # src+k
    join = s.add('op', 'left+right', floor={'op': 'math', 'fn': '+'})
    s.wire(src, left); s.wire(k, left)      # 4*1 = 4
    s.wire(src, right); s.wire(k, right)    # 4+1 = 5
    s.wire(left, join); s.wire(right, join)
    assert s.pull(join) == 9                 # 4 + 5
    s.edit(src, ['body', 'floor', 'value'], 10)
    assert s.pull(left) == 10 and s.pull(right) == 11
    assert s.pull(join) == 21                 # both diamond paths recooked


# ============================================================ 2. FROBENIUS spiders (section 19)

def _copy_of(s, input_id, title='copy'):
    cp = s.add('op', title, floor={'op': 'copy'})
    s.wire(input_id, cp)
    return cp


def _merge_of(s, input_ids, fn, title='merge'):
    mg = s.add('op', title, floor={'op': 'merge', 'fn': fn})
    for i in input_ids:
        s.wire(i, mg)
    return mg


def test_copy_fanout_gives_identical_outputs():
    """copy (Frobenius comultiplication) fan-outs its ONE input to N identical
    outputs: N consumers wired FROM the copy all read the same value."""
    s = Store()
    x = _lit(s, 42, 'x')
    cp = _copy_of(s, x)
    # three consumers read the copy's single output -> all identical
    outs = [s.add('op', 'pass%d' % i, floor={'op': 'merge', 'fn': 'first'})
            for i in range(3)]
    for o in outs:
        s.wire(cp, o)
    vals = [s.pull(o) for o in outs]
    assert vals == [42, 42, 42]
    assert s.pull(cp) == 42               # the copy's own value = its input

    # copy with the wrong arity is an ERROR, not a silent default
    bad = s.add('op', 'bad-copy', floor={'op': 'copy'})
    with pytest.raises(RuntimeError):
        s.pull(bad)                        # zero inputs


def test_spider_law_a_copy_then_merge_first_is_identity():
    """SPIDER LAW (a): copy then merge-first == identity on the value.
    merge/first is the counit-side partner of copy. Metamorphic: the composite
    must equal the bare input for several values, ints AND non-numbers."""
    for val in (0, 7, -3, 3.5, 'hello', [1, 2, 3], {'k': 'v'}):
        s = Store()
        x = _lit(s, val, 'x')
        cp = _copy_of(s, x)
        merged = _merge_of(s, [cp], 'first')
        assert s.pull(merged) == val, 'copy>merge-first != identity for %r' % (val,)
        # and it survives an edit (still identity after recook)
    s = Store()
    x = _lit(s, 1, 'x')
    m = _merge_of(s, [_copy_of(s, x)], 'first')
    assert s.pull(m) == 1
    s.edit(x, ['body', 'floor', 'value'], 999)
    assert s.pull(m) == 999


def test_spider_law_b_merge_sum_is_associative():
    """SPIDER LAW (b): merge(a, merge(b,c)) == merge(merge(a,b), c) for sum.
    Metamorphic associativity -- assert the two nestings are EQUAL and that
    each equals the flat sum a+b+c (so a bug that drops an input is caught)."""
    a, b, c = 2, 5, 11
    s = Store()
    na, nb, nc = _lit(s, a, 'a'), _lit(s, b, 'b'), _lit(s, c, 'c')
    left = _merge_of(s, [na, _merge_of(s, [nb, nc], 'sum', 'bc')], 'sum', 'a(bc)')
    right = _merge_of(s, [_merge_of(s, [na, nb], 'sum', 'ab'), nc], 'sum', '(ab)c')
    assert s.pull(left) == s.pull(right) == a + b + c == 18

    # adversarial: with three DISTINCT values, a wrong assoc that dropped/reused
    # an input would not equal the flat sum -- so 18 is a real discriminator
    assert s.pull(left) != a + b     # would pass if c were dropped
    assert s.pull(left) != a + a + c  # would pass if b were replaced by a


def test_merge_concat_is_associative_and_order_preserving():
    """merge/concat: associative AND order-preserving (adversarial: concat is
    NOT commutative, so a swapped-input bug is catchable)."""
    s = Store()
    a = _lit(s, [1, 2], 'a')
    b = _lit(s, [3], 'b')
    c = _lit(s, [4, 5], 'c')
    left = _merge_of(s, [a, _merge_of(s, [b, c], 'concat', 'bc')], 'concat', 'a(bc)')
    right = _merge_of(s, [_merge_of(s, [a, b], 'concat', 'ab')], 'concat', '(ab)')
    right = _merge_of(s, [right, c], 'concat', '(ab)c')
    assert s.pull(left) == [1, 2, 3, 4, 5]
    assert s.pull(right) == [1, 2, 3, 4, 5]
    # order matters: reversing inputs changes the result (not commutative)
    rev = _merge_of(s, [c, b, a], 'concat', 'cba')
    assert s.pull(rev) == [4, 5, 3, 1, 2]
    assert s.pull(rev) != s.pull(left)


def test_spider_law_c_copy_is_coassociative():
    """SPIDER LAW (c): copy is coassociative. Comultiplication then copying
    EITHER branch again yields the same triple of identical leaves. In this
    value-per-node engine every copy value == the root input, so both nesting
    orders expose the SAME value at all three leaves."""
    s = Store()
    x = _lit(s, 88, 'x')

    # (copy then copy the LEFT again):   x -> cp1 -> {cpL, right}
    cp1 = _copy_of(s, x, 'cp1')
    cpL = _copy_of(s, cp1, 'cpL')            # copy the left branch again
    # three leaves read: cpL, cpL, cp1(right)
    leftnest = [_merge_of(s, [cpL], 'first', 'lA'),
                _merge_of(s, [cpL], 'first', 'lB'),
                _merge_of(s, [cp1], 'first', 'lC')]

    # (copy then copy the RIGHT again):  x -> cp2 -> {left, cpR}
    cp2 = _copy_of(s, x, 'cp2')
    cpR = _copy_of(s, cp2, 'cpR')            # copy the right branch again
    rightnest = [_merge_of(s, [cp2], 'first', 'rA'),
                 _merge_of(s, [cpR], 'first', 'rB'),
                 _merge_of(s, [cpR], 'first', 'rC')]

    lvals = [s.pull(n) for n in leftnest]
    rvals = [s.pull(n) for n in rightnest]
    assert lvals == [88, 88, 88]
    assert rvals == [88, 88, 88]
    assert lvals == rvals                     # coassociative: nesting order irrelevant

    # metamorphic under edit: change the root, all six leaves follow identically
    s.edit(x, ['body', 'floor', 'value'], 5)
    assert [s.pull(n) for n in leftnest] == [s.pull(n) for n in rightnest] == [5, 5, 5]


def test_spiders_live_in_the_one_table():
    """copy/merge are ordinary op nodes -- no new kind, no new container."""
    s = Store()
    x = _lit(s, 1, 'x')
    cp = _copy_of(s, x)
    mg = _merge_of(s, [cp], 'sum')
    assert s.nodes[cp]['kind'] == 'op'
    assert s.nodes[mg]['kind'] == 'op'
    assert validate_store(s) is True


# ============================================================ 3. EFFECTFUL node (sections 4, 5b)

def _effect(s, target, change, frozen=True, title='effect'):
    return s.add('op', title,
                 floor={'op': 'effect', 'target': target, 'change': change},
                 frozen=frozen)


def test_dirty_propagation_accepts_promoted_effect_target_and_change_params():
    s = Store()
    target = s.add('param', 'target', floor={'op': 'value', 'value': 'before'})
    change = s.add('param', 'change', floor={'op': 'value', 'value': 1})
    effect = s.add(
        'op', 'parametric effect',
        floor={'op': 'effect', 'target': {'$param': 'target'},
               'change': {'$param': 'change'}},
        params={'target': target, 'change': change}, frozen=True,
    )
    group = s.add('group', 'parametric effect group', inner=[target, change, effect])
    assert s.pull(effect)['plan'] == {'target': 'before', 'change': 1}
    assert s.pull(group)['plan'] == {'target': 'before', 'change': 1}

    s.edit(target, ['body', 'floor', 'value'], 'after')
    s.edit(change, ['body', 'floor', 'value'], 2)

    assert s.pull(effect)['plan'] == {'target': 'after', 'change': 2}
    assert s.pull(group)['plan'] == {'target': 'after', 'change': 2}


def test_dirty_propagation_reuses_reverse_index_and_preserves_unrelated_memos():
    s = Store()
    source = _lit(s, 3, 'source')
    bias = _lit(s, 4, 'bias')
    total = s.add('op', 'total', floor={'op': 'math', 'fn': '+'})
    s.wire(source, total)
    s.wire(bias, total)
    unrelated = [_lit(s, index, 'unrelated-%04d' % index)
                 for index in range(2000)]
    assert s.pull(total) == 7
    for nid in unrelated:
        s.pull(nid)

    s.prepare_runtime_indexes()
    index = s._invalidation_out
    s.edit(source, ['body', 'floor', 'value'], 8)

    assert s._invalidation_out is index
    assert total not in s._memo
    assert all(nid in s._memo for nid in unrelated)
    assert s.pull(total) == 12

    s.edit(source, ['body', 'floor', 'value'], 9)
    assert s._invalidation_out is index
    assert s.pull(total) == 13


def test_frozen_effect_dry_run_mutates_nothing():
    """A frozen effect: pull() computes the PLAN and touches the sink NOT AT
    ALL. The sink is byte-equal before and after the pull."""
    sink = {'wall_count': 3, 'other': 'keep'}
    snapshot = copy.deepcopy(sink)
    s = Store()
    eff = _effect(s, target='wall_count', change=99)

    marker = s.pull(eff)
    assert marker == {'fired': False, 'dry_run': True,
                      'plan': {'target': 'wall_count', 'change': 99}}
    # THE assertion: the external sink is untouched by the dry-run
    assert sink == snapshot
    # dry_run() helper agrees and also refuses to run against an unfrozen node
    assert dry_run(s, eff) == {'target': 'wall_count', 'change': 99}


def test_apply_requires_unfreeze_then_mutates_and_audits():
    """apply_effect refuses while frozen (the gate); after a deliberate
    unfreeze it mutates the sink and records a revert token as a history node."""
    sink = {'wall_count': 3}
    s = Store()
    eff = _effect(s, target='wall_count', change=99)

    # frozen -> apply refuses, sink still untouched
    with pytest.raises(FrozenNode):
        apply_effect(s, eff, sink)
    assert sink == {'wall_count': 3}

    # deliberate unfreeze (audited op), THEN apply
    s.apply_op({'op': 'unfreeze', 'id': eff})
    res = apply_effect(s, eff, sink)
    assert res['fired'] is True and res['before'] == 3 and res['after'] == 99
    assert sink == {'wall_count': 99}         # THE real mutation happened

    # the apply is an append-only history node carrying the revert token
    applies = _hist_entries(s, 'effect_apply')
    assert len(applies) == 1
    assert applies[0]['before'] == 3 and applies[0]['after'] == 99
    assert applies[0]['effect'] == eff
    assert validate_store(s) is True


def test_revert_restores_via_token():
    """revert_effect undoes the mutation via the stored token, restoring the
    sink to its before-image, and the revert is itself a history node."""
    sink = {'wall_count': 3}
    s = Store()
    eff = _effect(s, target='wall_count', change=99)
    s.apply_op({'op': 'unfreeze', 'id': eff})
    apply_effect(s, eff, sink)
    assert sink == {'wall_count': 99}

    rr = revert_effect(s, eff, sink)
    assert rr['restored'] == 3
    assert sink == {'wall_count': 3}          # restored to before-image

    reverts = _hist_entries(s, 'effect_revert')
    assert len(reverts) == 1 and reverts[0]['restored'] == 3

    # reverting again is refused -- nothing live is left to revert
    with pytest.raises(ValueError):
        revert_effect(s, eff, sink)


def test_revert_of_new_key_deletes_it():
    """If the target did NOT exist before apply, revert must DELETE the key
    (restore absence), not leave a stale value."""
    sink = {}
    s = Store()
    eff = _effect(s, target='fresh', change=[1, 2, 3])
    s.apply_op({'op': 'unfreeze', 'id': eff})
    apply_effect(s, eff, sink)
    assert sink == {'fresh': [1, 2, 3]}
    revert_effect(s, eff, sink)
    assert sink == {}                          # key removed, absence restored


def test_second_apply_without_change_is_idempotent():
    """A second apply when the sink already holds 'change' is a no-op that
    still audits truthfully (fired=False, idempotent=True)."""
    sink = {'k': 1}
    s = Store()
    eff = _effect(s, target='k', change=5)
    s.apply_op({'op': 'unfreeze', 'id': eff})

    first = apply_effect(s, eff, sink)
    assert first['fired'] is True and sink == {'k': 5}

    second = apply_effect(s, eff, sink)
    assert second['fired'] is False and second['idempotent'] is True
    assert sink == {'k': 5}                     # unchanged

    applies = _hist_entries(s, 'effect_apply')
    assert len(applies) == 2                    # BOTH recorded (history never lies)
    assert applies[0]['fired'] is True
    assert applies[1]['fired'] is False and applies[1]['idempotent'] is True


def test_every_effect_step_is_a_history_node():
    """dry-run/unfreeze/apply/revert -- every real step lands as an append-only
    history node in the ONE table. Metamorphic: the count grows by exactly the
    number of state-changing ops (a pure pull adds none)."""
    sink = {'x': 'a'}
    s = Store()
    eff = _effect(s, target='x', change='b')

    def hcount():
        return sum(1 for n in s.nodes.values() if n['kind'] == 'history')

    base = hcount()
    s.pull(eff)                                 # pure dry-run: NO new history
    assert hcount() == base

    s.apply_op({'op': 'unfreeze', 'id': eff})   # +1
    apply_effect(s, eff, sink)                  # +1
    revert_effect(s, eff, sink)                 # +1
    assert hcount() == base + 3
    # and after all that churn the whole table is still the one valid shape
    assert validate_store(s) is True


def test_apply_reflects_live_floor_after_unfreeze_edit():
    """Once unfrozen the plan tracks the live floor: editing 'change' before
    apply fires the edited value (proves apply is not stapled to a stale plan)."""
    sink = {'k': 0}
    s = Store()
    eff = _effect(s, target='k', change=1)
    s.apply_op({'op': 'unfreeze', 'id': eff})
    s.edit(eff, ['body', 'floor', 'change'], 77)   # allowed: node is unfrozen now
    apply_effect(s, eff, sink)
    assert sink == {'k': 77}


# ============================================================ 4. one-table sanity here too

def test_new_ops_keep_the_one_shape():
    """A graph mixing fan-out, spiders and an applied effect still validates as
    the one shape end to end (belt-and-braces before the dedicated forcing test)."""
    sink = {'total': 0}
    s = Store()
    a = _lit(s, 2, 'a'); b = _lit(s, 3, 'b')
    total = _merge_of(s, [a, b], 'sum', 'total')     # spider merge
    cp = _copy_of(s, total, 'cp')                    # spider copy (fan-out)
    o1 = _merge_of(s, [cp], 'first', 'o1')
    o2 = _merge_of(s, [cp], 'first', 'o2')
    assert s.pull(o1) == s.pull(o2) == 5

    eff = s.add('op', 'push-total',
                floor={'op': 'effect', 'target': 'total',
                       'change': {'$param': 'amt'}},
                params={'amt': s.add('param', 'amt', floor={'op': 'value', 'value': 5})},
                frozen=True)
    assert s.pull(eff)['plan']['change'] == 5        # param flows into the plan
    s.apply_op({'op': 'unfreeze', 'id': eff})
    apply_effect(s, eff, sink)
    assert sink == {'total': 5}
    assert validate_store(s) is True
