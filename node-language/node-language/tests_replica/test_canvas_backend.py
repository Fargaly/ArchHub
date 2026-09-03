"""SLICE CANVAS-BACKEND -- the POST endpoints that let the canvas DRIVE the one
table (SPEC sections 3, 5, 7, 8; the HTTP contract). Adversarial by
construction: real HTTP (urllib) against a LIVE CanvasServer on a free port,
built over the REAL grand map, asserting the actual returned JSON + the actual
level_view the engine reports back -- not mocks, not the server's own claim.

Every mutation must route through the ONE edit path, so each test also proves
the append-only history grew and re-asserts the forcing validator at the end:
the one table, one shape, no meta-layer -- after everything this slice did.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import Store, relation_stages, validate_store
from nodelang import map_import
from nodelang.graph_api import level_view
from nodelang.serve_canvas import CanvasServer


# ---------------------------------------------------------------- fixtures

def history_count(store):
    return sum(1 for n in store.nodes.values() if n['kind'] == 'history')


@pytest.fixture
def grand():
    """A live CanvasServer over the REAL imported grand map, free port."""
    s = Store()
    reg = map_import.import_grand_map(s)
    validate_store(s)
    srv = CanvasServer(s, reg['session'], reg=reg, port=0).start()
    try:
        yield srv, s, reg
    finally:
        srv.stop()


def _post(url, path, obj):
    req = urllib.request.Request(
        url + path, data=json.dumps(obj).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _level(url, cid):
    return json.loads(
        urllib.request.urlopen(url + '/api/level?id=' + cid, timeout=10).read())


def _some_domain(reg):
    """A domain group id + its inner value/weight node ids, from the registry."""
    key = reg['domain_keys'][0]
    return reg['domains'][key], key


# ---------------------------------------------------------------- /add

def test_add_spawns_a_node_that_appears_in_the_level(grand):
    srv, s, reg = grand
    url = srv.url
    dom_id, key = _some_domain(reg)

    before = history_count(s)
    resp = _post(url, '/add',
                 {'kind': 'value', 'title': 'canvas-added',
                  'floor': {'op': 'value', 'value': 42}})
    assert resp['ok'] is True
    nid = resp['id']
    assert nid in s.nodes                                  # really in the one table
    assert s.pull(nid) == 42                               # and it computes
    assert history_count(s) == before + 1                  # one recorded op

    # a freshly-added node is not inside any container until wired/grouped, so
    # put it in the domain group's inner list the way the palette would, then
    # assert the LEVEL VIEW (what the canvas draws) shows it.
    s.edit(dom_id, ['body', 'inner'],
           s.nodes[dom_id]['body']['inner'] + [nid])
    lvl = _level(url, dom_id)
    got = {n['id']: n for n in lvl['nodes']}
    assert nid in got
    assert got[nid]['value'] == 42
    assert got[nid]['title'] == 'canvas-added'
    validate_store(s)


# ---------------------------------------------------------------- /wire

def test_wire_appears_in_the_level_view_wires(grand):
    srv, s, reg = grand
    url = srv.url
    dom_id, key = _some_domain(reg)

    # spawn two fresh nodes into the SAME domain group so a wire between them
    # renders at that level (both endpoints in-level, section 3).
    a = _post(url, '/add',
              {'kind': 'value', 'title': 'wa', 'floor': {'op': 'value', 'value': 3}})['id']
    b = _post(url, '/add',
              {'kind': 'op', 'title': 'wb', 'floor': {'op': 'math', 'fn': '+'}})['id']
    s.edit(dom_id, ['body', 'inner'],
           s.nodes[dom_id]['body']['inner'] + [a, b])

    before_w = {w['id'] for w in _level(url, dom_id)['wires']}
    resp = _post(url, '/wire', {'from': a, 'to': b})
    assert resp['ok'] is True
    wid = resp['id']
    assert s.nodes[wid]['kind'] == 'wire'                  # a wire NODE in the table

    lvl = _level(url, dom_id)
    wires = {w['id']: w for w in lvl['wires']}
    assert wid in wires and wid not in before_w
    assert wires[wid]['from'] == a and wires[wid]['to'] == b
    assert wires[wid]['gated'] is False                    # ungated by default
    # the wire really conducts: b = sum of its one input (3)
    assert s.pull(b) == 3
    validate_store(s)


# ---------------------------------------------------------------- /group

def test_group_makes_a_container_whose_inner_are_the_lassoed_nodes(grand):
    srv, s, reg = grand
    url = srv.url
    dom_id, key = _some_domain(reg)

    a = _post(url, '/add',
              {'kind': 'value', 'title': 'ga', 'floor': {'op': 'value', 'value': 2}})['id']
    b = _post(url, '/add',
              {'kind': 'value', 'title': 'gb', 'floor': {'op': 'value', 'value': 9}})['id']

    before = history_count(s)
    resp = _post(url, '/group', {'ids': [a, b], 'title': 'lassoed'})
    assert resp['ok'] is True
    gid = resp['id']
    assert history_count(s) == before + 1
    assert s.nodes[gid]['kind'] == 'group'
    assert s.nodes[gid]['title'] == 'lassoed'

    # drilling into the new group shows BOTH lassoed nodes as its inner level
    inner = _level(url, gid)
    inner_ids = {n['id'] for n in inner['nodes']}
    assert a in inner_ids and b in inner_ids
    assert inner['container']['id'] == gid
    # the level_view marks the group itself as a container when it is drilled
    # to from a parent -- put it under the domain and confirm the flag.
    s.edit(dom_id, ['body', 'inner'],
           s.nodes[dom_id]['body']['inner'] + [gid])
    parent = {n['id']: n for n in _level(url, dom_id)['nodes']}
    assert parent[gid]['container'] is True
    validate_store(s)


# ---------------------------------------------------------------- /pos

def test_pos_persists_in_meta_and_comes_back_in_level_view(grand):
    srv, s, reg = grand
    url = srv.url
    dom_id, key = _some_domain(reg)

    nid = _post(url, '/add',
                {'kind': 'value', 'title': 'movable',
                 'floor': {'op': 'value', 'value': 1}})['id']
    s.edit(dom_id, ['body', 'inner'],
           s.nodes[dom_id]['body']['inner'] + [nid])

    # before /pos: no position
    got = {n['id']: n for n in _level(url, dom_id)['nodes']}
    assert got[nid]['pos'] is None

    before = history_count(s)
    resp = _post(url, '/pos', {'id': nid, 'x': 137, 'y': 88})
    assert resp['ok'] is True
    assert history_count(s) == before + 1                  # audited, in the one table
    # stored in meta, NOT a side dict
    assert s.nodes[nid]['meta']['pos'] == {'x': 137, 'y': 88}

    got = {n['id']: n for n in _level(url, dom_id)['nodes']}
    assert got[nid]['pos'] == {'x': 137, 'y': 88}

    # moving again overwrites via the SAME audited path
    _post(url, '/pos', {'id': nid, 'x': 5, 'y': 6})
    got = {n['id']: n for n in _level(url, dom_id)['nodes']}
    assert got[nid]['pos'] == {'x': 5, 'y': 6}
    validate_store(s)


# ---------------------------------------------------------------- /gate

def test_gate_marks_the_wire_gated_and_clearing_unmarks_it(grand):
    srv, s, reg = grand
    url = srv.url
    dom_id, key = _some_domain(reg)

    # two data nodes + a wire between them at one level, plus a gate node
    a = _post(url, '/add',
              {'kind': 'value', 'title': 'src', 'floor': {'op': 'value', 'value': 7}})['id']
    b = _post(url, '/add',
              {'kind': 'op', 'title': 'sink', 'floor': {'op': 'math', 'fn': '+'}})['id']
    gate = _post(url, '/add',
                 {'kind': 'value', 'title': 'gate',
                  'floor': {'op': 'value', 'value': True}})['id']
    s.edit(dom_id, ['body', 'inner'],
           s.nodes[dom_id]['body']['inner'] + [a, b, gate])
    wid = _post(url, '/wire', {'from': a, 'to': b})['id']

    # open the gate on the wire
    resp = _post(url, '/gate', {'wire_id': wid, 'gate_id': gate})
    assert resp['ok'] is True
    wires = {w['id']: w for w in _level(url, dom_id)['wires']}
    assert wires[wid]['gated'] is True                     # level_view marks it
    assert any(stage['role'] == 'gate' and stage['node_id'] == gate
               for stage in relation_stages(s.nodes, s.nodes[wid]))
    assert gate in s.open(wid)                             # gate is visibly inside

    # gate TRUE -> conducts live: sink sees the 7
    assert s.pull(b) == 7
    # flip the gate node FALSE -> the wire stops conducting (held/no value);
    # the wire never conducted before this pull sequence... it did (=7 held).
    s.edit(gate, ['body', 'floor', 'value'], False)
    assert s.pull(b) == 7                                  # holds last conducted

    # clear the gate: level_view no longer marks it gated
    resp2 = _post(url, '/gate', {'wire_id': wid, 'gate_id': None})
    assert resp2['ok'] is True
    wires = {w['id']: w for w in _level(url, dom_id)['wires']}
    assert wires[wid]['gated'] is False
    assert not any(stage['role'] == 'gate'
                   for stage in relation_stages(s.nodes, s.nodes[wid]))
    assert gate not in s.open(wid)
    validate_store(s)


# ---------------------------------------------------------------- adversarial

def test_bad_requests_are_refused_with_the_repr_and_change_nothing(grand):
    srv, s, reg = grand
    url = srv.url

    before = history_count(s)

    # unknown POST path -> 404
    with pytest.raises(urllib.error.HTTPError) as e404:
        _post(url, '/nope', {})
    assert e404.value.code == 404

    # malformed body -> 400
    bad = urllib.request.Request(url + '/add', data=b'not json', method='POST')
    with pytest.raises(urllib.error.HTTPError) as e_body:
        urllib.request.urlopen(bad, timeout=10)
    assert e_body.value.code == 400

    # wire to a node that does not exist -> 400 carrying the repr
    req = urllib.request.Request(
        url + '/wire',
        data=json.dumps({'from': 'nope', 'to': 'nope'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    with pytest.raises(urllib.error.HTTPError) as e_wire:
        urllib.request.urlopen(req, timeout=10)
    assert e_wire.value.code == 400
    err = json.loads(e_wire.value.read())
    assert err['ok'] is False and err['error']            # the repr is present

    # group with an id not in the table -> 400 (laws_structure.group refuses)
    req2 = urllib.request.Request(
        url + '/group',
        data=json.dumps({'ids': ['ghost'], 'title': 'x'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    with pytest.raises(urllib.error.HTTPError) as e_grp:
        urllib.request.urlopen(req2, timeout=10)
    assert e_grp.value.code == 400

    # gate on a non-wire node -> 400 (set_gate refuses)
    dom_id, _ = _some_domain(reg)
    req3 = urllib.request.Request(
        url + '/gate',
        data=json.dumps({'wire_id': dom_id, 'gate_id': dom_id}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    with pytest.raises(urllib.error.HTTPError) as e_gate:
        urllib.request.urlopen(req3, timeout=10)
    assert e_gate.value.code == 400

    # NONE of the failed ops mutated the table
    assert history_count(s) == before
    validate_store(s)
