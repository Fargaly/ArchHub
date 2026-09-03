"""THE FORCING TEST (SPEC section 19, section 2): ONE node table, one shape, no
meta-layer. Written adversarially -- includes a MUTANT store that violates the
law to prove this test can catch the violation, and real computed values
(hand-derived) so the assertions can actually FAIL."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.core as core
from nodelang import (
    KINDS, NODE_KEYS, Store, OneTableViolation, HistoryImmutable, FrozenNode,
    validate_node, validate_store, relation_sources,
)
from nodelang.laws_decision import build_topsis_group


# ------------------------------------------------------------ graph builder

def build_full_graph():
    """One graph exercising EVERY kind. Returns (store, ids dict)."""
    s = Store()
    ids = {}

    # value + op (math): 8 + 5 = 13
    ids['a'] = s.add('value', 'a', floor={'op': 'value', 'value': 8})
    ids['b'] = s.add('value', 'b', floor={'op': 'value', 'value': 5})
    ids['add'] = s.add('op', 'a+b', floor={'op': 'math', 'fn': '+'})
    s.wire(ids['a'], ids['add'])
    s.wire(ids['b'], ids['add'])

    # subtraction: wire ORDER matters (10 - 3 = 7, deterministic)
    ids['ten'] = s.add('value', 'ten', floor={'op': 'value', 'value': 10})
    ids['three'] = s.add('value', 'three', floor={'op': 'value', 'value': 3})
    ids['sub'] = s.add('op', 'ten-three', floor={'op': 'math', 'fn': '-'})
    s.wire(ids['ten'], ids['sub'])
    s.wire(ids['three'], ids['sub'])

    # division, min, max, avg
    ids['twenty'] = s.add('value', 'twenty', floor={'op': 'value', 'value': 20})
    ids['four'] = s.add('value', 'four', floor={'op': 'value', 'value': 4})
    ids['div'] = s.add('op', '20/4', floor={'op': 'math', 'fn': '/'})
    s.wire(ids['twenty'], ids['div'])
    s.wire(ids['four'], ids['div'])
    ids['mn'] = s.add('op', 'min', floor={'op': 'math', 'fn': 'min'})
    ids['mx'] = s.add('op', 'max', floor={'op': 'math', 'fn': 'max'})
    ids['av'] = s.add('op', 'avg', floor={'op': 'math', 'fn': 'avg'})
    for t in ('mn', 'mx', 'av'):
        s.wire(ids['four'], ids[t])
        s.wire(ids['ten'], ids[t])
        s.wire(ids['a'], ids[t])   # 4, 10, 8

    # group: inner (2, 3, +) with the sum wired OUT -> group value = 5
    ids['g2'] = s.add('value', 'g2', floor={'op': 'value', 'value': 2})
    ids['g3'] = s.add('value', 'g3', floor={'op': 'value', 'value': 3})
    ids['gsum'] = s.add('op', 'g2+g3', floor={'op': 'math', 'fn': '+'})
    s.wire(ids['g2'], ids['gsum'])
    s.wire(ids['g3'], ids['gsum'])
    ids['c100'] = s.add('value', 'c100', floor={'op': 'value', 'value': 100})
    ids['consumer'] = s.add('op', 'gsum+100', floor={'op': 'math', 'fn': '+'})
    s.wire(ids['gsum'], ids['consumer'])   # crosses OUT of the group
    s.wire(ids['c100'], ids['consumer'])
    ids['group'] = s.add('group', 'G', inner=[ids['g2'], ids['g3'], ids['gsum']])

    # session: a group at scale (same primitive, kind is just data)
    ids['session'] = s.add('session', 'S', inner=[ids['group'], ids['consumer']])

    # foreach + item + reduce: [1,2,3] -> +10 each -> [11,12,13] -> sum 36
    ids['lst'] = s.add('value', 'list', floor={'op': 'value', 'value': [1, 2, 3]})
    ids['item'] = s.add('op', 'item', floor={'op': 'item'})
    ids['c10'] = s.add('value', 'c10', floor={'op': 'value', 'value': 10})
    ids['subadd'] = s.add('op', 'item+10', floor={'op': 'math', 'fn': '+'})
    s.wire(ids['item'], ids['subadd'])
    s.wire(ids['c10'], ids['subadd'])
    ids['fe'] = s.add('op', 'foreach', floor={'op': 'foreach', 'sub': ids['subadd']})
    s.wire(ids['lst'], ids['fe'])
    ids['red'] = s.add('op', 'sum', floor={'op': 'reduce', 'mode': 'sum'})
    s.wire(ids['fe'], ids['red'])
    ids['col'] = s.add('op', 'collect', floor={'op': 'reduce', 'mode': 'collect'})
    s.wire(ids['fe'], ids['col'])

    # reference (the section 6 gap): reads another node's value by id
    ids['ref'] = s.add('op', 'ref->add', floor={'op': 'reference', 'target': ids['add']})

    # ui: a ui-element node whose body reads the graph (kind is DATA)
    ids['ui'] = s.add('ui', 'label-bound-to-add',
                      floor={'op': 'reference', 'target': ids['add']})

    # decision: TOPSIS as an OPENABLE GROUP of generic nodes -- no hidden op.
    # From outside it is one node; open it and the steps (normalize/weight/best/
    # worst/distance/rank) are real generic nodes wired in the same table.
    ids['topsis'] = build_topsis_group(s, [[1, 0], [0, 1]], [0.7, 0.3], [True, True])
    ids['w0'] = next(nid for nid, n in s.nodes.items() if n['title'] == 'w[0]')
    ids['w1'] = next(nid for nid, n in s.nodes.items() if n['title'] == 'w[1]')

    # proposal (frozen by default -- AI never silently mutates)
    ids['prop'] = s.add('proposal', 'ai-proposal',
                        floor={'op': 'value',
                               'value': {'proposes': 'set', 'note': 'raise a to 12'}},
                        frozen=True)

    # secret_ref: op:// reference only, never a resolved value
    ids['secret'] = s.add('secret_ref', 'api-key',
                          floor={'op': 'secret_ref', 'ref': 'op://vault/api-key'})
    return s, ids


# --------------------------------------------------------------- (a) the law

def test_every_kind_lives_in_the_one_table_and_computes():
    s, ids = build_full_graph()

    # every single object the engine created lives in THE one table
    for name, nid in ids.items():
        assert nid in s.nodes, '%s (%s) missing from the one table' % (name, nid)
    # ALL ten kinds present as DATA on the one primitive (history auto-appended)
    assert {n['kind'] for n in s.nodes.values()} == set(KINDS)
    # one-shape validator passes on the WHOLE table (wires, history included)
    assert validate_store(s) is True

    # real computed values (hand-derived -- these can fail)
    assert s.pull(ids['add']) == 13
    assert s.pull(ids['sub']) == 7          # order-deterministic: 10 - 3
    assert s.pull(ids['div']) == 5.0        # 20 / 4
    assert s.pull(ids['mn']) == 4
    assert s.pull(ids['mx']) == 10
    assert s.pull(ids['av']) == pytest.approx((4 + 10 + 8) / 3)
    assert s.pull(ids['group']) == 5        # group runs its inner subgraph
    assert s.pull(ids['consumer']) == 105
    # session = group at scale. Its boundary is TRANSITIVE (slice 4, SPEC
    # section 19 regroup-invariance): gsum feeds consumer INSIDE the session,
    # so the session's sole sink -- its live result -- is the consumer.
    assert s.pull(ids['session']) == 105
    assert s.pull(ids['fe']) == [11, 12, 13]    # foreach maps sub over list
    assert s.pull(ids['red']) == 36
    assert s.pull(ids['col']) == [11, 12, 13]
    assert s.pull(ids['ref']) == 13             # reference reads by id
    assert s.pull(ids['ui']) == 13              # ui is the same primitive
    assert [s.pull(ids['w0']), s.pull(ids['w1'])] == [0.7, 0.3]   # weights ARE nodes
    # TOPSIS (openable group of generic nodes): A=[1,0],B=[0,1],w=[.7,.3] -> [0.7,0.3]
    assert s.pull(ids['topsis']) == pytest.approx([0.7, 0.3])
    assert s.pull(ids['secret']) == 'op://vault/api-key'  # never resolved

    # a WIRE conducts its from-node's value (skip wires whose source sits in
    # the foreach sub-graph -- 'item' is unbound outside foreach BY DESIGN)
    unbound_upstream = {ids['item'], ids['subadd']}
    wire_ids = [nid for nid, n in s.nodes.items() if n['kind'] == 'wire']
    assert wire_ids, 'no wire nodes created'
    checked = 0
    for wid in wire_ids:
        sources = relation_sources(s.nodes, s.nodes[wid])
        assert sources
        src = sources[0]['node_id']
        if src in unbound_upstream:
            continue
        assert s.pull(wid) == s.pull(src)
        checked += 1
    assert checked >= 15  # the conduction law was actually exercised

    # EVERY kind answers open(): inner ids for group-ish, floor otherwise
    assert set(s.open(ids['group'])) == {ids['g2'], ids['g3'], ids['gsum']}
    assert set(s.open(ids['session'])) == {ids['group'], ids['consumer']}
    for name in ('a', 'add', 'ref', 'ui', 'w0', 'prop', 'secret'):
        floor = s.open(ids[name])
        assert isinstance(floor, dict) and 'op' in floor
    hist = [nid for nid, n in s.nodes.items() if n['kind'] == 'history']
    assert isinstance(s.open(hist[0]), dict)
    opened_relation = s.open(wire_ids[0])
    assert isinstance(opened_relation, list) and len(opened_relation) >= 2
    assert all(s.nodes[nid]['kind'] == 'param' for nid in opened_relation[:2])

    # adversarial: TOPSIS with a COST criterion (benefit=[T,F]).
    # matrix [[2,1],[1,2]], w=[.5,.5]: A dominates -> scores [1.0, 0.0]
    t2 = build_topsis_group(s, [[2, 1], [1, 2]], [0.5, 0.5], [True, False],
                            title='rank-with-cost')
    assert s.pull(t2) == pytest.approx([1.0, 0.0])

    # 'item' outside a foreach is an ERROR, not a silent default
    with pytest.raises(RuntimeError):
        s.pull(ids['item'])


# --------------------------------------------------- (b) the reflection sweep

def _is_node_like(x):
    return isinstance(x, dict) and {'id', 'kind', 'body'} <= set(x.keys())


def _node_holding_containers(obj):
    """Names of attributes on obj that are containers holding node-like state."""
    hits = []
    for name, val in vars(obj).items():
        if isinstance(val, dict):
            members = list(val.values())
        elif isinstance(val, (list, tuple, set)):
            members = list(val)
        else:
            continue
        if any(_is_node_like(m) for m in members):
            hits.append(name)
    return hits


def test_reflection_sweep_no_second_container():
    s, ids = build_full_graph()
    s.pull(ids['session'])
    s.pull(ids['red'])
    s.pull(ids['topsis'])

    # instance sweep: the ONLY container holding node-like state is the table
    assert _node_holding_containers(s) == ['nodes']

    # the memo cache holds VALUES, never nodes
    assert s._memo, 'memo cache unexpectedly empty after pulls'
    for nid, val in s._memo.items():
        assert not _is_node_like(val), 'memo holds a node-shaped object for %s' % nid

    # module sweep: no module-level dict/list stashes node-like state
    for name, val in vars(core).items():
        if name.startswith('__'):
            continue
        if isinstance(val, dict):
            assert not any(_is_node_like(v) for v in val.values()), \
                'module container %r holds node-like state' % name
        elif isinstance(val, (list, tuple, set, frozenset)):
            assert not any(_is_node_like(v) for v in val), \
                'module container %r holds node-like state' % name

    # class-attr sweep: Store defines no class-level container (the banned
    # "class per kind with its own storage" would show up here)
    for name, val in vars(Store).items():
        if name.startswith('__'):
            continue  # interpreter-injected dunders (e.g. __static_attributes__)
        assert not isinstance(val, (dict, list, set, tuple)), \
            'Store class attribute %r is a container -- second storage' % name


# ------------------------------------------- (c) the MUTANT proves catchability

class MutantStore(Store):
    """VIOLATES the law on purpose: keeps wires in a side list instead of the
    one table. The validator and the sweep MUST both catch this."""

    def __init__(self):
        super().__init__()
        self._side_wires = []   # the banned second container

    def apply_op(self, op):
        if op.get('op') == 'add_wire':
            endpoints = op['endpoints']
            endpoint_ids = []
            endpoint_params = {}
            for index, spec in enumerate(endpoints):
                param = self._blank('param', 'endpoint:%03d' % index, None,
                                    {'floor': {'op': 'value', 'value': copy.deepcopy(spec)}},
                                    False)
                param['meta']['role'] = 'relation_endpoint'
                self.nodes[param['id']] = param
                endpoint_ids.append(param['id'])
                endpoint_params['endpoint:%03d' % index] = param['id']
            wire = self._blank('wire', '', endpoint_params,
                               {'inner': endpoint_ids}, False)
            self._side_wires.append(wire)              # NOT in self.nodes
            for spec in endpoints:
                self.nodes[spec['node_id']]['relations'].append(wire['id'])
            return wire['id']
        return super().apply_op(op)


def test_mutant_store_fails_the_validator_and_the_sweep():
    m = MutantStore()
    a = m.add('value', 'a', floor={'op': 'value', 'value': 1})
    b = m.add('op', 'sum', floor={'op': 'math', 'fn': '+'})
    m.wire(a, b)

    # the one-shape validator FAILS: relations point outside the one table
    with pytest.raises(OneTableViolation):
        validate_store(m)

    # and the reflection sweep flags the side list as a second container
    assert '_side_wires' in _node_holding_containers(m)

    # sanity: the same graph built on the REAL store passes both
    s = Store()
    a2 = s.add('value', 'a', floor={'op': 'value', 'value': 1})
    b2 = s.add('op', 'sum', floor={'op': 'math', 'fn': '+'})
    s.wire(a2, b2)
    assert validate_store(s) is True
    assert _node_holding_containers(s) == ['nodes']


# ------------------------------------------------- (d) serialize -> reload

def test_serialize_flat_list_reload_identical_values():
    s, ids = build_full_graph()
    unbound = ('item', 'subadd')  # unbound outside a foreach by design
    before = {name: s.pull(nid) for name, nid in ids.items()
              if name not in unbound}

    flat = s.dump()
    # ONE flat list of one-shape nodes, json-serializable
    assert isinstance(flat, list)
    for node in flat:
        assert set(node.keys()) == set(NODE_KEYS)
    wire_json = json.dumps(flat)

    s2 = Store.load(json.loads(wire_json))
    assert validate_store(s2) is True
    assert set(s2.nodes) == set(s.nodes)
    after = {name: s2.pull(nid) for name, nid in ids.items()
             if name not in unbound}
    for name in before:
        if isinstance(before[name], float) or (
                isinstance(before[name], list)
                and any(isinstance(x, float) for x in before[name])):
            assert after[name] == pytest.approx(before[name]), name
        else:
            assert after[name] == before[name], name
    # loading is not a fresh build: reloaded store starts with an empty memo
    # and still computes the same values -> deterministic run
    assert s2.pull(ids['topsis']) == pytest.approx([0.7, 0.3])


# ---------------------------------------- history: ONE edit path, append-only

def test_every_edit_appends_history_and_history_is_immutable():
    s = Store()
    a = s.add('value', 'a', floor={'op': 'value', 'value': 8})
    b = s.add('value', 'b', floor={'op': 'value', 'value': 5})
    add = s.add('op', 'a+b', floor={'op': 'math', 'fn': '+'})
    s.wire(a, add)
    s.wire(b, add)
    assert s.pull(add) == 13

    hist_before = [n for n in s.nodes.values() if n['kind'] == 'history']
    # 3 add_node + 2 add_wire so far
    assert len(hist_before) == 5

    s.edit(a, ['body', 'floor', 'value'], 12)
    hist_after = [n for n in s.nodes.values() if n['kind'] == 'history']
    assert len(hist_after) == 6
    # the newest history node's body IS the op
    newest = max(hist_after, key=lambda n: n['meta']['seq'])
    assert newest['body']['floor']['entry'] == {
        'op': 'set', 'id': a, 'path': ['body', 'floor', 'value'],
        'value': 12, 'before': 8}
    # history nodes ARE nodes in the same table, and validate as the one shape
    assert validate_store(s) is True

    # append-only: modifying a history node raises
    with pytest.raises(HistoryImmutable):
        s.edit(newest['id'], ['title'], 'rewritten past')
    # and clients cannot inject fake history through apply_op either
    fake = s._blank('history', 'fake', None,
                    {'floor': {'op': 'history', 'entry': {'op': 'set'}}}, False)
    with pytest.raises(HistoryImmutable):
        s.apply_op({'op': 'add_node', 'node': fake})


def test_frozen_node_refuses_edit():
    s = Store()
    prop = s.add('proposal', 'p', floor={'op': 'value', 'value': {'x': 1}}, frozen=True)
    with pytest.raises(FrozenNode):
        s.edit(prop, ['body', 'floor', 'value'], {'x': 2})


# ------------------------------------------------ dirty propagation + memo

def test_dirty_propagation_recomputes_only_dependents():
    s, ids = build_full_graph()
    assert s.pull(ids['add']) == 13
    assert s.pull(ids['add']) == 13
    assert s._computes[ids['add']] == 1          # memoized: computed once
    assert s.pull(ids['topsis']) == pytest.approx([0.7, 0.3])
    topsis_computes = s._computes[ids['topsis']]

    # edit a: 8 -> 12; dependents recompute, unrelated stays memoized
    s.edit(ids['a'], ['body', 'floor', 'value'], 12)
    assert s.pull(ids['add']) == 17
    assert s._computes[ids['add']] == 2
    assert s.pull(ids['ref']) == 17              # reference sees the edit
    assert s.pull(ids['ui']) == 17
    assert s.pull(ids['topsis']) == pytest.approx([0.7, 0.3])
    assert s._computes[ids['topsis']] == topsis_computes  # untouched

    # group chain: edit g2 2 -> 7; group 5 -> 10; consumer 105 -> 110; session follows
    assert s.pull(ids['group']) == 5
    s.edit(ids['g2'], ['body', 'floor', 'value'], 7)
    assert s.pull(ids['group']) == 10
    assert s.pull(ids['consumer']) == 110
    assert s.pull(ids['session']) == 110  # transitive boundary: consumer is the sink

    # foreach chain: edit list -> foreach + reduce follow
    s.edit(ids['lst'], ['body', 'floor', 'value'], [5, 6])
    assert s.pull(ids['fe']) == [15, 16]
    assert s.pull(ids['red']) == 31

    # edit the weight NODES inside the topsis group -> ranking recomputes (dirty)
    s.edit(ids['w0'], ['body', 'floor', 'value'], 0.5)
    s.edit(ids['w1'], ['body', 'floor', 'value'], 0.5)
    assert s.pull(ids['topsis']) == pytest.approx([0.5, 0.5])
    assert s._computes[ids['topsis']] == topsis_computes + 1
