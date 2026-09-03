"""SLICE 4 -- ONE GRAPH TWO DRIVERS + THE GRAND MAP AS THE LIVING PROGRAM
(SPEC sections 12, 13, 14, 5b, 9).

Adversarial by construction:
  * every percentage is cross-checked against an INDEPENDENT python oracle
    computed straight from the json (if the graph scoring drifts, these fail);
  * the frozen two-step is tested to REFUSE first (graph untouched), then
    succeed only with the explicit unfreeze op;
  * memo-hit assertions use the engine's compute counters -- a wrong dirty
    propagation (over- or under-invalidating) fails them;
  * the forcing sweep re-runs on the fully imported store: one table, one
    shape, no second container -- including this test's own modules.

Runs on the REAL grand map file (282 nodes / 15 domains at time of writing;
all counts asserted DYNAMICALLY against the json -- the hardcoded-count rot
of 2026-07-02 is exactly what we refuse to repeat).
"""
import statistics
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import relation_sources, relation_targets

from nodelang import KINDS, Store, validate_store
from nodelang.core import FrozenNode
from nodelang import drivers as drv
from nodelang import map_import as mi

# Independent oracle for the status weights -- deliberately NOT read from the
# graph, so the graph-built scoring (reference + avg + mul floor nodes) is
# checked against a second source of truth.
W = {'live': 1.0, 'partial': 0.5, 'planned': 0.25, 'vision': 0.0}


def expected_domain_pct(dom, weights=W, override=None):
    vals = []
    for n in dom['nodes']:
        status = override.get(n['id'], n['status']) if override else n['status']
        vals.append(weights[status])
    return statistics.mean(vals) * 100.0


# ==================================================================== drivers

def _small_graph():
    s = Store()
    a = s.add('value', 'a', floor={'op': 'value', 'value': 8}, actor='user')
    b = s.add('value', 'b', floor={'op': 'value', 'value': 5}, actor='user')
    add = s.add('op', 'a+b', floor={'op': 'math', 'fn': '+'}, actor='user')
    s.wire(a, add, actor='user')
    s.wire(b, add, actor='user')
    return s, a, b, add


def test_ai_proposal_lands_without_change_then_approve_applies():
    s, a, b, add = _small_graph()
    assert s.pull(add) == 13

    pid = drv.ai_propose(s, {'op': 'set', 'id': a,
                             'path': ['body', 'floor', 'value'], 'value': 12},
                         note='raise a to 12')
    # the proposal IS a node in the one table, frozen, pending, openable
    prop = s.nodes[pid]
    assert prop['kind'] == 'proposal'
    assert prop['meta']['frozen'] is True
    assert drv.proposal_state(s, pid) == 'pending'
    assert s.open(pid)['value']['proposed_op']['value'] == 12
    # and the graph DID NOT change
    assert s.pull(add) == 13
    assert s.pull(a) == 8

    # tampering with a pending proposal is refused (frozen)
    with pytest.raises(FrozenNode):
        s.edit(pid, ['body', 'floor', 'value', 'proposed_op', 'value'], 999,
               actor='ai')

    out = drv.approve(s, pid)
    assert out == a
    assert s.pull(add) == 17            # 12 + 5: the approval applied it
    assert drv.proposal_state(s, pid) == 'approved'

    # history shows the proposal -> apply chain, with actors
    entries = drv.history_entries(s)
    i_prop = next(i for i, e in enumerate(entries)
                  if e['op'] == 'add_node' and e['node']['id'] == pid)
    i_apply = next(i for i, e in enumerate(entries)
                   if e.get('via_proposal') == pid and e['op'] == 'set'
                   and e['id'] == a)
    assert i_prop < i_apply
    assert entries[i_prop]['actor'] == 'ai'
    assert entries[i_apply]['actor'] == 'user'

    # approving twice is refused
    with pytest.raises(ValueError):
        drv.approve(s, pid)


def test_reject_leaves_graph_untouched():
    s, a, b, add = _small_graph()
    assert s.pull(add) == 13
    pid = drv.ai_propose(s, {'op': 'set', 'id': b,
                             'path': ['body', 'floor', 'value'], 'value': 99})
    drv.reject(s, pid)
    assert s.pull(add) == 13
    assert s.pull(b) == 5
    assert drv.proposal_state(s, pid) == 'rejected'
    # no 'set' on b was ever applied
    assert not any(e['op'] == 'set' and e.get('id') == b
                   for e in drv.history_entries(s))
    with pytest.raises(ValueError):
        drv.approve(s, pid)


def test_frozen_effect_requires_explicit_unfreeze_two_step():
    s = Store()
    eff = drv.add_effect(s, 'deploy-to-host', {'target': 'prod', 'n': 1})
    # frozen effectful node REFUSES pull-side effects: dry-run marker only
    v = s.pull(eff)
    assert v == {'fired': False, 'dry_run': True,
                 'payload': {'target': 'prod', 'n': 1}}

    pid = drv.ai_propose(s, {'op': 'set', 'id': eff,
                             'path': ['body', 'floor', 'payload', 'n'],
                             'value': 2})
    # step 0: plain approve REFUSES -- graph untouched, proposal still pending
    with pytest.raises(FrozenNode):
        drv.approve(s, pid)
    assert s.nodes[eff]['body']['floor']['payload'] == {'target': 'prod', 'n': 1}
    assert s.nodes[eff]['meta']['frozen'] is True
    assert drv.proposal_state(s, pid) == 'pending'

    # the two-step: explicit unfreeze op + the edit, both audited via the pid
    drv.approve(s, pid, unfreeze_target=True)
    entries = drv.history_entries(s)
    chain = [e for e in entries if e.get('via_proposal') == pid]
    assert [e['op'] for e in chain] == ['unfreeze', 'set']
    assert s.nodes[eff]['meta']['frozen'] is False
    assert s.pull(eff) == {'fired': True, 'payload': {'target': 'prod', 'n': 2}}

    # refreezing flips it straight back to refusing (dirty on freeze works)
    s.apply_op({'op': 'freeze', 'id': eff, 'actor': 'user'})
    assert s.pull(eff) == {'fired': False, 'dry_run': True,
                           'payload': {'target': 'prod', 'n': 2}}


def test_two_drivers_interleave_one_graph_full_audit():
    s = Store()
    x = s.add('value', 'x', floor={'op': 'value', 'value': 10}, actor='user')
    y = s.add('value', 'y', floor={'op': 'value', 'value': 2}, actor='user')
    m = s.add('op', 'x*y', floor={'op': 'math', 'fn': '*'}, actor='user')
    s.wire(x, m, actor='user')
    s.wire(y, m, actor='user')
    assert s.pull(m) == 20

    drv.user_edit(s, x, ['body', 'floor', 'value'], 3)       # user drives
    assert s.pull(m) == 6
    pid = drv.ai_propose(s, {'op': 'set', 'id': y,                # ai proposes
                             'path': ['body', 'floor', 'value'], 'value': 5})
    assert s.pull(m) == 6                                    # nothing applied
    drv.user_edit(s, x, ['body', 'floor', 'value'], 4)       # user again
    assert s.pull(m) == 8                                    # y still 2
    drv.approve(s, pid)                                      # user approves ai
    assert s.pull(m) == 20                                   # 4 * 5 -- deterministic

    # the history nodes ARE the complete audit: every op, every actor, in order
    entries = drv.history_entries(s)
    assert all('actor' in e for e in entries)
    assert [e['op'] for e in entries] == [
        'add_node', 'add_node', 'add_node', 'add_wire', 'add_wire',  # build
        'set',                     # user: x=3
        'add_node',                # ai: proposal lands as a NODE
        'set',                     # user: x=4
        'set',                     # user approves -> ai's op applied
        'unfreeze', 'set', 'freeze',  # proposal state -> approved (audited)
    ]
    assert [e['actor'] for e in entries] == [
        'user', 'user', 'user', 'user', 'user',
        'user', 'ai', 'user', 'user', 'user', 'user', 'user']
    # the applied op is linked to its proposal
    applied = entries[8]
    assert applied['via_proposal'] == pid and applied['id'] == y

    # determinism across serialize -> reload: same graph, same value
    s2 = Store.load(s.dump())
    assert s2.pull(m) == 20


# ============================================================== the grand map

@pytest.fixture(scope='module')
def grand():
    data = mi.load_map()
    store = Store()
    reg = mi.import_grand_map(store)
    return store, reg, data


def test_import_counts_match_the_json_dynamically(grand):
    store, reg, data = grand
    n_domains = len(data)
    total = sum(len(d['nodes']) for d in data)
    total_wires = sum(len(d['wires']) for d in data)
    # the real map is non-trivial (no hardcoded 282 -- dynamic against json)
    assert n_domains >= 10 and total > 100 and total_wires > 100

    # every map node -> exactly one value node + one weight node, one table
    assert len(reg['values']) == total
    assert len(reg['weights']) == total
    for map_id, vid in reg['values'].items():
        assert store.nodes[vid]['kind'] == 'value'
        assert store.nodes[vid]['title'] == map_id
    for wid in reg['weights'].values():
        assert store.nodes[wid]['kind'] == 'op'
        assert store.nodes[wid]['body']['floor']['op'] == 'reference'

    # each domain -> a GROUP node; the whole map -> ONE session node
    assert len(reg['domains']) == n_domains
    for key, gid in reg['domains'].items():
        assert store.nodes[gid]['kind'] == 'group'
        assert store.nodes[gid]['title'] == key
    sess = store.nodes[reg['session']]
    assert sess['kind'] == 'session' and sess['title'] == 'grand-map'
    assert len(sess['body']['inner']) == n_domains + 1  # domains + grand total

    # the map's wires arrays -> wire NODES, endpoint-exact, in order
    assert len(reg['map_wires']) == total_wires
    expected_pairs = [(reg['values'][a], reg['values'][b])
                      for d in data for a, b in d['wires']]
    got_pairs = []
    for wid in reg['map_wires']:
        w = store.nodes[wid]
        assert w['kind'] == 'wire'
        got_pairs.append((relation_sources(store.nodes, w)[0]['node_id'],
                          relation_targets(store.nodes, w)[0]['node_id']))
    assert got_pairs == expected_pairs

    # each map node's value IS its status string
    for d in data:
        for n in d['nodes']:
            assert store.pull(reg['values'][n['id']]) == n['status']


def test_domain_and_grand_values_match_independent_oracle(grand):
    store, reg, data = grand
    per_dom = {}
    for d in data:
        exp = expected_domain_pct(d)
        got = store.pull(reg['domains'][d['key']])
        assert got == pytest.approx(exp), d['key']
        assert 0.0 <= got <= 100.0
        per_dom[d['key']] = exp
    # the real map is not flat -- domains genuinely differ
    assert len({round(v, 9) for v in per_dom.values()}) > 1

    grand_exp = statistics.mean(per_dom.values())
    assert store.pull(reg['grand']) == pytest.approx(grand_exp)
    # THE session node's value = the overall % (a scalar, not an inventory)
    assert store.pull(reg['session']) == pytest.approx(grand_exp)
    # and the ui report node is bound to the same live number
    assert store.pull(reg['report']) == pytest.approx(grand_exp)


def test_edit_one_status_recomputes_its_domain_others_memo_hit(grand):
    store, reg, data = grand
    s = Store.load(store.dump())          # private copy; same ids
    key0 = data[0]['key']
    target = next(n for n in data[0]['nodes'] if n['status'] != 'live')

    base = s.pull(reg['session'])
    counts0 = {k: s._computes[mid] for k, mid in reg['muls'].items()}

    mi.set_status(s, reg, target['id'], 'live', actor='user')

    new_dom_exp = expected_domain_pct(data[0], override={target['id']: 'live'})
    old_dom_exp = expected_domain_pct(data[0])
    assert new_dom_exp != old_dom_exp

    new_grand = s.pull(reg['session'])
    exp_grand = statistics.mean(
        [new_dom_exp] + [expected_domain_pct(d) for d in data[1:]])
    assert new_grand == pytest.approx(exp_grand)
    assert new_grand != pytest.approx(base)

    # ONLY the edited domain's % port recomputed; the other 14 memo-hit
    counts1 = {k: s._computes[mid] for k, mid in reg['muls'].items()}
    assert counts1[key0] == counts0[key0] + 1
    for k in reg['muls']:
        if k != key0:
            assert counts1[k] == counts0[k], 'domain %s recomputed needlessly' % k

    # the edited domain's group value follows (memo-hits the fresh mul)
    assert s.pull(reg['domains'][key0]) == pytest.approx(new_dom_exp)
    assert s.pull(reg['values'][target['id']]) == 'live'
    # both ops of the status edit are in the audit with the actor
    tail = drv.history_entries(s)[-2:]
    assert [e['op'] for e in tail] == ['set', 'set']
    assert all(e['actor'] == 'user' for e in tail)


def test_scale_nodes_are_the_live_scoring_authority_not_code(grand):
    store, reg, data = grand
    s = Store.load(store.dump())
    s.pull(reg['session'])
    # edit ONE scale node (partial: 0.5 -> 0.6) -- every domain % must move
    # per the graph, matching the oracle re-run with the new weight table
    s.edit(reg['scale']['partial'], ['body', 'floor', 'value'], 0.6,
           actor='user')
    w2 = dict(W, partial=0.6)
    for d in data:
        assert s.pull(reg['domains'][d['key']]) == pytest.approx(
            expected_domain_pct(d, weights=w2)), d['key']
    exp_grand = statistics.mean(expected_domain_pct(d, weights=w2) for d in data)
    assert s.pull(reg['session']) == pytest.approx(exp_grand)
    # and it genuinely moved (the file has 'partial' nodes)
    assert exp_grand != pytest.approx(
        statistics.mean(expected_domain_pct(d) for d in data))


def test_regroup_invariance_on_a_real_domain(grand):
    store, reg, data = grand
    dom = data[0]
    key, gid = dom['key'], reg['domains'][dom['key']]
    before = store.pull(gid)
    grand_before = store.pull(reg['grand'])
    assert before == pytest.approx(expected_domain_pct(dom))

    def pair_ids(nodes):
        out = []
        for n in nodes:
            out.extend((reg['values'][n['id']], reg['weights'][n['id']]))
        return out

    # variant 1: fold the first 6 status+weight pairs into a sub-group
    c1 = Store.load(store.dump())
    sub = c1.add('group', 'sub:%s' % key, inner=pair_ids(dom['nodes'][:6]),
                 actor='user')
    inner1 = [sub] + [i for i in c1.nodes[gid]['body']['inner']
                      if i not in set(pair_ids(dom['nodes'][:6]))]
    c1.edit(gid, ['body', 'inner'], inner1, actor='user')
    assert c1.pull(gid) == pytest.approx(before)
    assert c1.pull(reg['grand']) == pytest.approx(grand_before)
    # the sub-group itself runs. Its ports, derived independently from the
    # json (SPEC section 3 computed ports): every weight wires out to the
    # domain avg, and any status with a map-wire leaving the chosen six is a
    # port too -- in inner order.
    chosen = dom['nodes'][:6]
    chosen_ids = {n['id'] for n in chosen}
    outgoing = {a for a, b in dom['wires']
                if a in chosen_ids and b not in chosen_ids}
    exp_ports = []
    for n in chosen:
        if n['id'] in outgoing:
            exp_ports.append(n['status'])       # the status node is a port
        exp_ports.append(W[n['status']])        # its weight always is
    got_ports = c1.pull(sub)
    assert len(got_ports) == len(exp_ports)
    for g, e in zip(got_ports, exp_ports):
        if isinstance(e, float):
            assert g == pytest.approx(e)
        else:
            assert g == e
    assert validate_store(c1) is True

    # variant 2: split ALL pairs across two sub-groups instead
    c2 = Store.load(store.dump())
    half = len(dom['nodes']) // 2
    sub_a = c2.add('group', 'a:%s' % key, inner=pair_ids(dom['nodes'][:half]),
                   actor='user')
    sub_b = c2.add('group', 'b:%s' % key, inner=pair_ids(dom['nodes'][half:]),
                   actor='user')
    kept = [reg['avgs'][key], reg['hundreds'][key], reg['muls'][key]]
    c2.edit(gid, ['body', 'inner'], [sub_a, sub_b] + kept, actor='user')
    assert c2.pull(gid) == pytest.approx(before)
    assert c2.pull(reg['session']) == pytest.approx(grand_before)

    # section 19 forcing: three different groupings, ONE composite value
    assert store.pull(gid) == pytest.approx(c1.pull(gid)) \
        == pytest.approx(c2.pull(gid))


def test_grand_session_pulls_into_a_fresh_session_as_a_group(grand):
    store, reg, data = grand
    grand_val = store.pull(reg['session'])
    fresh = Store.load(store.dump())
    ws = fresh.add('session', 'workspace', inner=[reg['session']], actor='user')
    assert fresh.pull(ws) == pytest.approx(grand_val)
    assert validate_store(fresh) is True
    # the wrapped session is still openable all the way down
    assert reg['session'] in fresh.open(ws)
    assert set(fresh.open(reg['session'])) \
        == set(reg['domains'].values()) | {reg['grand']}


# =========================================== forcing re-run on the full import

def _is_node_like(x):
    return isinstance(x, dict) and {'id', 'kind', 'body'} <= set(x.keys())


def _node_holding_containers(obj):
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


def test_forcing_after_full_import_one_table_one_shape(grand):
    store, reg, data = grand
    # every single imported thing is IN the one table
    flat_ids = list(reg['scale'].values()) + [reg['scale_group']] \
        + list(reg['values'].values()) + list(reg['weights'].values()) \
        + list(reg['domains'].values()) + list(reg['avgs'].values()) \
        + list(reg['hundreds'].values()) + list(reg['muls'].values()) \
        + reg['map_wires'] + [reg['grand'], reg['report'], reg['session']]
    for nid in flat_ids:
        assert nid in store.nodes, '%s escaped the one table' % nid
    assert len(flat_ids) == len(set(flat_ids))

    # ONE shape for all of it -- values, weights, wires, groups, session,
    # ui report, scale, history: the validator walks every node
    assert validate_store(store) is True
    assert all(n['kind'] in KINDS for n in store.nodes.values())
    kinds_present = {n['kind'] for n in store.nodes.values()}
    assert {'value', 'op', 'wire', 'group', 'session', 'ui', 'history'} \
        <= kinds_present

    # no second container anywhere: not on the store, not in the importer
    assert _node_holding_containers(store) == ['nodes']
    for name, val in vars(mi).items():
        if isinstance(val, dict):
            assert not any(_is_node_like(v) for v in val.values()), name
        elif isinstance(val, (list, tuple, set, frozenset)):
            assert not any(_is_node_like(v) for v in val), name

    # the import itself is fully audited: one history node per op, actor on all
    entries = drv.history_entries(store)
    assert all('actor' in e for e in entries)
    assert all(e['actor'] == mi.IMPORT_ACTOR for e in entries)
    n_hist = sum(1 for n in store.nodes.values() if n['kind'] == 'history')
    assert n_hist == len(entries)
    op_counts = Counter(e['op'] for e in entries)
    n_non_history = len(store.nodes) - n_hist
    # add_node creates one node. add_wire is one audited atomic operation that
    # creates one open relation plus its two endpoint parameter nodes.
    assert n_non_history == op_counts['add_node'] + 3 * op_counts['add_wire']
