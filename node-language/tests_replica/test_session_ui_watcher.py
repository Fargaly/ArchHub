"""SLICE 3 tests -- session-as-node + ui-from-nodes + the watcher mechanic +
secret-ref (SPEC sections 2, 5, 5b, 9, 10, 11).

Adversarial by construction: real computed values (hand-derived), real HTTP
against a live stdlib server, direction-locked sync that is proven to REFUSE
the wrong direction, a mutant secret node that the forcing validator must
catch, and byte-level scans of serialized output for the sentinel secret.

Every test re-asserts the forcing validator from core (validate_store) at the
end: the one table, one shape, no meta-layer -- after everything this slice
did to it.
"""
import copy
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import Store, OneTableViolation, validate_store
from nodelang.laws_surface import (
    SyncError, closure, import_session, make_session, make_wip, render,
    resolve_secret, stage, sync, ui_element,
)
from nodelang.serve import NodeServer


def history_count(store):
    return sum(1 for n in store.nodes.values() if n['kind'] == 'history')


def build_central():
    """Central store: session over a=800, b=50, add -> 850. Hand-derived."""
    s = Store()
    a = s.add('value', 'a', floor={'op': 'value', 'value': 800})
    b = s.add('value', 'b', floor={'op': 'value', 'value': 50})
    add = s.add('op', 'a+b', floor={'op': 'math', 'fn': '+'})
    s.wire(a, add)
    s.wire(b, add)
    sid = make_session(s, 'model', [a, b, add], stage='central')
    return s, {'a': a, 'b': b, 'add': add, 'sid': sid}


# ---------------------------------------------------------- 1. session-as-node

def test_session_is_a_node_and_body_is_root_ids():
    s, ids = build_central()
    sess = s.nodes[ids['sid']]
    # the session IS the one primitive: same shape, kind is data
    assert sess['kind'] == 'session'
    assert s.open(ids['sid']) == [ids['a'], ids['b'], ids['add']]
    # its stage param is ITSELF a node in the one table
    pid = sess['params']['stage']
    assert s.nodes[pid]['kind'] == 'param'
    assert stage(s, ids['sid']) == 'central'
    # a session runs as a group: value = live result (single output add=850)
    assert s.pull(ids['sid']) == 850
    validate_store(s)


def test_grand_session_import_wires_session_in_as_group():
    s = Store()
    # session A: 2 * 3 = 6
    a2 = s.add('value', 'a2', floor={'op': 'value', 'value': 2})
    a3 = s.add('value', 'a3', floor={'op': 'value', 'value': 3})
    mul = s.add('op', '2*3', floor={'op': 'math', 'fn': '*'})
    s.wire(a2, mul)
    s.wire(a3, mul)
    sess_a = make_session(s, 'A', [a2, a3, mul])
    # grand session B: consumer = A + 10
    c10 = s.add('value', 'c10', floor={'op': 'value', 'value': 10})
    consumer = s.add('op', 'A+10', floor={'op': 'math', 'fn': '+'})
    s.wire(c10, consumer)
    grand = make_session(s, 'GRAND', [c10, consumer])

    before = history_count(s)
    import_session(s, grand, sess_a)
    assert history_count(s) == before + 1          # the import IS a recorded op
    assert sess_a in s.open(grand)                  # A is now inside B

    s.wire(sess_a, consumer)                        # wire the session like any group
    assert s.pull(consumer) == 16                   # 2*3 + 10
    assert s.pull(grand) == 16                      # grand session's live value

    # LIVE propagation across the imported session: edit deep inside A
    s.edit(a2, ['body', 'floor', 'value'], 5)
    assert s.pull(grand) == 25                      # 5*3 + 10

    # adversarial: refuse duplicates, self-import, non-sessions
    with pytest.raises(ValueError):
        import_session(s, grand, sess_a)
    with pytest.raises(ValueError):
        import_session(s, grand, grand)
    with pytest.raises(ValueError):
        import_session(s, grand, a2)                # a value node is not a session
    validate_store(s)


def test_wip_edit_does_not_touch_central_until_deliberate_sync():
    central, ids = build_central()
    wip = make_wip(central, ids['sid'])

    # same node ids (node-id = element-id), separate tables
    assert set(closure(central, ids['sid'])) <= set(central.nodes)
    assert ids['a'] in wip.nodes and wip.nodes[ids['a']] is not central.nodes[ids['a']]
    assert stage(wip, ids['sid']) == 'wip'
    assert stage(central, ids['sid']) == 'central'  # central stage untouched

    # edit in WIP: 800 -> 900
    wip.edit(ids['a'], ['body', 'floor', 'value'], 900)
    assert wip.pull(ids['add']) == 950
    # central is NOT touched -- not the value, not the raw node
    assert central.pull(ids['add']) == 850
    assert central.nodes[ids['a']]['body']['floor']['value'] == 800

    # sync is DELIBERATE: nothing happened until this call
    hist_before = history_count(central)
    synced = sync(wip, central, ids['sid'])
    assert ids['a'] in synced
    assert central.pull(ids['add']) == 950          # by-id copy landed + recomputed
    assert history_count(central) > hist_before     # sync went through apply_op
    # governance metadata never syncs: central stays central
    assert stage(central, ids['sid']) == 'central'

    # adversarial: the REVERSE direction is refused (central is not a wip)
    with pytest.raises(SyncError):
        sync(central, wip, ids['sid'])
    # adversarial: a wip that lies about its stage is refused
    liar = make_wip(central, ids['sid'])
    liar.edit(liar.nodes[ids['sid']]['params']['stage'],
              ['body', 'floor', 'value'], 'central')
    with pytest.raises(SyncError):
        sync(liar, central, ids['sid'])
    validate_store(central)
    validate_store(wip)


def test_sync_carries_new_nodes_by_id():
    central, ids = build_central()
    wip = make_wip(central, ids['sid'])
    # grow the WIP: new value 7 wired into add -> 800+50+7 = 857
    extra = wip.add('value', 'extra', floor={'op': 'value', 'value': 7})
    wip.wire(extra, ids['add'])
    wip.edit(ids['sid'], ['body', 'inner'],
             wip.nodes[ids['sid']]['body']['inner'] + [extra])
    assert wip.pull(ids['add']) == 857
    assert extra not in central.nodes               # central untouched
    sync(wip, central, ids['sid'])
    assert extra in central.nodes                   # arrived under the SAME id
    assert central.pull(ids['add']) == 857
    validate_store(central)
    validate_store(wip)


# ---------------------------------------------------------- 2+3. ui + watcher

def build_ui(s, ids):
    h1 = ui_element(s, 'h1', text='Total')
    span = ui_element(s, 'span', bind=ids['add'])
    root = ui_element(s, 'div', children=[h1, span], title='page')
    return root, h1, span


def test_render_is_pure_walk_of_the_table():
    s, ids = build_central()
    root, h1, span = build_ui(s, ids)
    page = render(s, root)
    assert page == ('<div data-node="%s">'
                    '<h1 data-node="%s">Total</h1>'
                    '<span data-node="%s">850</span>'
                    '</div>' % (root, h1, span))
    # pure: rendering twice with no edit is identical
    assert render(s, root) == page
    # the binding is LIVE graph logic: edit b -> the render changes
    s.edit(ids['b'], ['body', 'floor', 'value'], 150)
    assert '>950</span>' in render(s, root)
    # escaping: node text cannot inject markup into the page
    s.edit(s.nodes[h1]['params']['text'], ['body', 'floor', 'value'],
           '<script>alert(1)</script>')
    assert '<script>' not in render(s, root)
    assert '&lt;script&gt;' in render(s, root)
    # adversarial: render refuses a non-ui root
    with pytest.raises(ValueError):
        render(s, ids['a'])
    validate_store(s)


def test_watcher_over_real_http_edit_changes_served_page():
    s, ids = build_central()
    root, h1, span = build_ui(s, ids)
    server = NodeServer(s, root).start()
    url = server.url
    try:
        # fetch page: text A
        page = urllib.request.urlopen(url + '/', timeout=10).read().decode('utf-8')
        assert '>850</span>' in page
        assert '>Total</h1>' in page

        # THE WATCHER EDIT: POST /edit on the ui node's bound value node
        hist_before = history_count(s)
        req = urllib.request.Request(
            url + '/edit',
            data=json.dumps({'node_id': ids['a'], 'param': None,
                             'value': 900}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST')
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert resp['ok'] is True

        # a param-path edit too: rename the heading THROUGH its param node
        req2 = urllib.request.Request(
            url + '/edit',
            data=json.dumps({'node_id': h1, 'param': 'text',
                             'value': 'Grand Total'}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST')
        assert json.loads(urllib.request.urlopen(req2, timeout=10).read())['ok'] is True

        # each watcher edit appended a HISTORY node (append-only audit)
        assert history_count(s) == hist_before + 2

        # fetch again: text B. The served surface changed because a NODE
        # changed -- save IS the graph changing (SPEC section 5).
        page2 = urllib.request.urlopen(url + '/', timeout=10).read().decode('utf-8')
        assert '>950</span>' in page2               # 900 + 50
        assert '>850</span>' not in page2
        assert '>Grand Total</h1>' in page2
        assert '>Total</h1>' not in page2

        # adversarial: unknown path 404s, garbage body 400s
        with pytest.raises(urllib.error.HTTPError) as e404:
            urllib.request.urlopen(url + '/nope', timeout=10)
        assert e404.value.code == 404
        bad = urllib.request.Request(url + '/edit', data=b'not json',
                                     method='POST')
        with pytest.raises(urllib.error.HTTPError) as e400:
            urllib.request.urlopen(bad, timeout=10)
        assert e400.value.code == 400
        # a failed edit appended nothing
        assert history_count(s) == hist_before + 2
    finally:
        server.stop()
    validate_store(s)


# ---------------------------------------------------------- 4. secret-ref

SENTINEL = 'SWORDFISH-9000-THE-RESOLVED-SECRET'
REF = 'op://vault/deploy/token'


def test_secret_ref_resolves_at_pull_time_and_never_serializes():
    s, ids = build_central()
    sec = s.add('secret_ref', 'deploy token',
                floor={'op': 'secret_ref', 'ref': REF})

    resolved = resolve_secret(s, sec, {REF: SENTINEL}.__getitem__)
    assert resolved == SENTINEL                     # the caller got the value

    # pulling the node yields the REFERENCE, never the resolved value
    assert s.pull(sec) == REF

    # serialize the ENTIRE graph -- scan every byte for the sentinel
    blob = json.dumps(s.dump(), default=repr)
    assert SENTINEL not in blob
    assert REF in blob                              # proves we scanned the real dump
    # the memo cache holds no secret either
    assert SENTINEL not in json.dumps(list(s._memo.values()), default=repr)

    # serve a page BOUND to the secret node: the page shows the ref, not the value
    span = ui_element(s, 'span', bind=sec)
    root = ui_element(s, 'div', children=[span])
    server = NodeServer(s, root).start()
    try:
        page = urllib.request.urlopen(server.url + '/', timeout=10).read().decode('utf-8')
        assert SENTINEL not in page
        assert 'op://vault/deploy/token' in page
    finally:
        server.stop()

    # adversarial: resolver for an unknown ref must raise, not fabricate
    with pytest.raises(KeyError):
        resolve_secret(s, sec, {}.__getitem__)
    # adversarial: resolve_secret refuses non-secret nodes
    with pytest.raises(ValueError):
        resolve_secret(s, ids['a'], {REF: SENTINEL}.__getitem__)
    validate_store(s)


def test_forcing_validator_catches_a_secret_smuggled_into_the_graph():
    """MUTANT: physically write the resolved value into a secret node's floor
    -- the forcing validator must FAIL the whole store. Proves the validator
    can actually fail, and that 'value never lives in the graph' is enforced,
    not convention."""
    s = Store()
    sec = s.add('secret_ref', 'tok', floor={'op': 'secret_ref', 'ref': REF})
    validate_store(s)                               # green before the crime
    mutant = s.nodes[sec]
    mutant['body']['floor']['value'] = SENTINEL     # bypass apply_op on purpose
    with pytest.raises(OneTableViolation):
        validate_store(s)
    # and creating one through the front door is refused the same way
    s2 = Store()
    with pytest.raises(OneTableViolation):
        s2.add('secret_ref', 'tok',
               floor={'op': 'secret_ref', 'ref': REF, 'value': SENTINEL})
    validate_store(Store.load([n for n in s.dump() if n['id'] != sec]))


# ---------------------------------------------------------- forcing, always

def test_slice3_kinds_all_live_in_the_one_table():
    """Sessions, ui elements, their params, wires, secrets, history from the
    watcher edits: ONE dict, one shape. No side table appeared anywhere in
    this slice (server holds only the Store; render holds nothing)."""
    s, ids = build_central()
    root, h1, span = build_ui(s, ids)
    s.add('secret_ref', 'tok', floor={'op': 'secret_ref', 'ref': REF})
    kinds = {n['kind'] for n in s.nodes.values()}
    assert {'value', 'op', 'wire', 'session', 'param', 'ui',
            'secret_ref', 'history'} <= kinds
    # every one of them is IN the one table under its id, same shape
    validate_store(s)
    # and a wire stored outside the table is caught (the banned edge list)
    mutant = copy.deepcopy(s)
    some_node = mutant.nodes[ids['add']]
    some_node['relations'].append('w-not-in-table')
    with pytest.raises(OneTableViolation):
        validate_store(mutant)
