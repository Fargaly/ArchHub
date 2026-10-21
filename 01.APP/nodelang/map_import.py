"""nodelang.map_import -- THE GRAND MAP AS THE LIVING PROGRAM (SPEC section 14).

"The grand map evolves into the node language": this imports the configured
authority map into the ONE node table as a RUNNING program, not an inventory.
Packaged/public runtimes use the bundled public seed. Founder installations
may point at a private authority through a local capability configuration;
private paths and map content are never embedded in the public package.

What each map thing becomes (everything the ONE shape, ONE table):

  map node          -> a kind='value' node; its VALUE is the node's status
                       string ('live'|'partial'|'planned'|'vision').
  each param row    -> a kind='param' NODE (all rows in the current authority), held by the
                       value node's params dict by name -- params ARE nodes
                       (SPEC section 2), openable + editable through apply_op.
  visible label     -> one additional presentation-label PARAM NODE per map
                       value; every UI lens binds to it instead of copying text.
  status weight     -> NOT hardcoded scoring. The four weights live as VALUE
                       NODES in the graph (the 'status-scale' group:
                       live=1.0, partial=0.5, planned=0.25, vision=0.0).
                       Each map node gets a weight node whose floor is a
                       REFERENCE to the scale node for its current status.
                       Edit a scale node -> every domain %% moves live.
  domain            -> a kind='group' node whose VALUE = avg(weights) * 100,
                       built from FLOOR nodes inside it: the weight
                       references feed an AVG node, the avg and a literal
                       100 feed a MUL node, and the mul is the group's one
                       computed output port (its wire crosses OUT to the
                       grand total -- SPEC section 3 computed ports).
  map wires         -> kind='wire' NODES between the imported value nodes
                       (one per pair in each domain's 'wires' array).
  the whole map     -> ONE kind='session' node 'grand-map' whose inner is
                       the 15 domain groups + the grand-total node; its value
                       computes to the overall %% (avg of the domain %%s).

Status is EDITABLE data: set_status() re-points the weight node's reference
at a different scale node and rewrites the status string -- two audited ops
through apply_op, dirty-propagating into exactly that domain's %% and the
grand total (everything else stays memoized).

No node-shaped state lives in this module: import_grand_map returns a plain
registry of IDS (strings) so tests can find things; the nodes themselves
live only in the one table.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PUBLIC_MAP_PATH = Path(__file__).resolve().parent / "data" / "public_runtime_map.json"
AUTHORITY_ENV = "ARCHHUB_GRAND_MAP_PATH"
AUTHORITY_CONFIG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ArchHub" / "authority.json"

# Seed DATA for the scale nodes (graph data, written once as nodes -- the
# live scoring authority is the NODES, not this dict; tests prove it by
# editing a scale node and watching every domain %% move).
STATUS_SCALE = (('live', 1.0), ('partial', 0.5), ('planned', 0.25), ('vision', 0.0))

IMPORT_ACTOR = 'import'


def load_local_authority_config(path=None):
    """Read optional machine-local authority pointers, never authority data."""
    config_path = Path(path) if path else AUTHORITY_CONFIG
    if not config_path.is_file():
        return {}
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def resolve_map_path(path=None):
    if path:
        return Path(path).expanduser().resolve()
    configured = os.environ.get(AUTHORITY_ENV, "").strip()
    if not configured:
        configured = str(load_local_authority_config().get("grand_map_path") or "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file():
            return candidate
    return PUBLIC_MAP_PATH


def load_map(path=None):
    p = resolve_map_path(path)
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def import_grand_map(store, path=None, actor=IMPORT_ACTOR):
    """Import the grand map into ``store``'s ONE table. Returns a registry of
    ids (plain strings): scale, values, weights, domains, avgs, muls,
    map_wires, grand, report, session."""
    data = load_map(path)

    reg = {
        'scale': {},        # status -> scale value-node id
        'scale_group': None,
        'values': {},       # map node id -> value-node id (status as value)
        'params': {},       # map node id -> {param name -> param-node id}
        'labels': {},       # map node id -> editable presentation label param
        'weights': {},      # map node id -> weight (reference) node id
        'domains': {},      # domain key -> group node id
        'avgs': {},         # domain key -> avg node id
        'hundreds': {},     # domain key -> literal-100 node id
        'muls': {},         # domain key -> mul node id (the domain's %% port)
        'map_wires': [],    # wire node ids minted from the map's wires arrays
        'grand': None,      # grand-total avg node id
        'report': None,     # ui node bound to the grand total
        'session': None,    # THE 'grand-map' session node id
        'domain_keys': [d['key'] for d in data],
    }

    # -- the status scale: weights are GRAPH DATA, not code -----------------
    for status, weight in STATUS_SCALE:
        reg['scale'][status] = store.add(
            'value', 'scale:%s' % status,
            floor={'op': 'value', 'value': weight}, actor=actor)
    reg['scale_group'] = store.add(
        'group', 'status-scale', inner=list(reg['scale'].values()), actor=actor)

    # -- the grand total: avg over the 15 domain %% ports --------------------
    grand = store.add('op', 'grand-total',
                      floor={'op': 'math', 'fn': 'avg'}, actor=actor)
    reg['grand'] = grand

    # -- each domain ---------------------------------------------------------
    for dom in data:
        key = dom['key']
        inner = []
        for n in dom['nodes']:
            status = n['status']
            if status not in reg['scale']:
                raise ValueError('map node %s has unknown status %r'
                                 % (n['id'], status))
            # each param row -> a first-class PARAM NODE (SPEC section 2:
            # "pull any param out, see its logic, edit it"). The value node
            # carries them by name in its params dict; edit a param node
            # through apply_op and it dirty-propagates like any other node.
            pdict = {}
            pids = []
            for p in n.get('params', ()):
                pid = store.add('param', 'p:%s.%s' % (n['id'], p['k']),
                                floor={'op': 'value', 'value': p.get('v')},
                                actor=actor)
                pdict[p['k']] = pid
                pids.append(pid)
            label = store.add('param', 'label:%s' % n['id'],
                              floor={'op': 'value', 'value': n['title']},
                              actor=actor)
            store.nodes[label]['meta']['role'] = 'presentation_label'
            node_params = dict(pdict)
            node_params['label'] = label
            vid = store.add('value', n['id'],
                            floor={'op': 'value', 'value': status},
                            params=node_params, actor=actor)
            wid = store.add('op', 'w:%s' % n['id'],
                            floor={'op': 'reference',
                                   'target': reg['scale'][status]},
                            actor=actor)
            # dataflow mark: the status node feeds its weight node
            store.wire(vid, wid, title='status->weight', actor=actor)
            reg['values'][n['id']] = vid
            reg['weights'][n['id']] = wid
            reg['params'][n['id']] = pdict
            reg['labels'][n['id']] = label
            inner.extend((vid, wid))
            inner.extend(pids + [label])

        # avg(weights) * 100 -- built from FLOOR nodes, not python scoring
        avg = store.add('op', 'avg:%s' % key,
                        floor={'op': 'math', 'fn': 'avg'}, actor=actor)
        hundred = store.add('value', '100:%s' % key,
                            floor={'op': 'value', 'value': 100}, actor=actor)
        mul = store.add('op', 'pct:%s' % key,
                        floor={'op': 'math', 'fn': '*'}, actor=actor)
        for n in dom['nodes']:
            store.wire(reg['weights'][n['id']], avg, title='weight->avg', actor=actor)
        store.wire(avg, mul, title='avg->pct', actor=actor)
        store.wire(hundred, mul, title='x100', actor=actor)

        # the map's OWN wires -> wire NODES between the imported value nodes
        for a, b in dom.get('wires', ()):
            reg['map_wires'].append(
                store.wire(reg['values'][a], reg['values'][b],
                           title='map:%s->%s' % (a, b), actor=actor))

        # the domain group: mul's wire OUT to the grand total is the group's
        # single computed output port -> group value = avg*100 (a scalar)
        store.wire(mul, grand, title='%s->grand' % key, actor=actor)
        inner.extend((avg, hundred, mul))
        gid = store.add('group', key, inner=inner, actor=actor)
        reg['domains'][key] = gid
        reg['avgs'][key] = avg
        reg['hundreds'][key] = hundred
        reg['muls'][key] = mul

    # -- a ui node bound to the grand total (also gives the session its
    #    computed output port: grand's wire to it crosses OUT of the session)
    report = store.add('ui', 'grand-report',
                       floor={'op': 'reference', 'target': grand}, actor=actor)
    store.wire(grand, report, title='grand->report', actor=actor)
    reg['report'] = report

    # -- THE session: the whole map is ONE node ------------------------------
    reg['session'] = store.add(
        'session', 'grand-map',
        inner=list(reg['domains'].values()) + [grand], actor=actor)
    return reg


def set_status(store, reg, map_id, new_status, actor='user'):
    """Edit a map node's status -- TWO audited ops through the one edit path:
    rewrite the status string (the node's value) and re-point its weight
    reference at the scale node for the new status. Dirty propagation does
    the rest (its domain %% + the grand total recompute on next pull)."""
    if new_status not in reg['scale']:
        raise ValueError('unknown status %r' % (new_status,))
    store.apply_op({'op': 'set', 'id': reg['values'][map_id],
                    'path': ['body', 'floor', 'value'], 'value': new_status,
                    'actor': actor})
    store.apply_op({'op': 'set', 'id': reg['weights'][map_id],
                    'path': ['body', 'floor', 'target'],
                    'value': reg['scale'][new_status], 'actor': actor})
    return reg['values'][map_id]


# ---------------------------------------------------------------------------
# REALITY-BACKED import (SPEC section 16 as the map): a node's value is a LIVE
# CHECK on its real artifact, not a typed label. No evidence -> not proven.
# ---------------------------------------------------------------------------

import os as _os


def _workspace_root():
    configured = str(load_local_authority_config().get("workspace_root") or "").strip()
    return Path(configured).expanduser().resolve() if configured else Path.cwd().resolve()


def _reality_probe_floor(evidence_ref):
    """Derive a probe floor from a map node's evidence_ref, or None when the
    node names no checkable artifact (then it is UNVERIFIABLE = not proven)."""
    ev = (evidence_ref or '').strip()
    if ev.startswith('file:'):
        p = _os.path.join(str(_workspace_root()), ev[5:].replace('/', _os.sep))
        return {'op': 'probe', 'kind': 'file_exists', 'spec': {'path': p}}
    if ev.startswith('http'):
        return {'op': 'probe', 'kind': 'http_ok', 'spec': {'url': ev}}
    return None


def import_grand_map_reality(store, path=None, actor='reality'):
    """Import the map where every node's value is a LIVE probe of its artifact.
    Returns a registry: probes (map_id -> probe node id), scores (map_id ->
    0/1 score node), domains (key -> group), pcts (key -> %% node), grand,
    session, unverified (list of map_ids with no checkable artifact).
    A node with no evidence gets a constant-0 score (anti-false-green: no
    evidence is not 'done'). Domain %% = avg(scores)*100; grand = avg(domain %%)."""
    data = load_map(path)
    reg = {'probes': {}, 'scores': {}, 'domains': {}, 'pcts': {},
           'grand': None, 'session': None, 'unverified': [],
           'domain_keys': [d['key'] for d in data]}
    grand = store.add('op', 'grand-real', floor={'op': 'math', 'fn': 'avg'}, actor=actor)
    reg['grand'] = grand
    for dom in data:
        key = dom['key']
        inner = []
        for n in dom['nodes']:
            floor = _reality_probe_floor(n.get('evidence_ref'))
            if floor is None:
                reg['unverified'].append(n['id'])
                score = store.add('value', 'unproven:%s' % n['id'],
                                  floor={'op': 'value', 'value': 0}, actor=actor)
            else:
                probe = store.add('op', 'probe:%s' % n['id'], floor=floor, actor=actor)
                reg['probes'][n['id']] = probe
                # score = 1.0 when the live probe is ok, else 0.0 (volatile)
                score = store.add('op', 'ok?:%s' % n['id'],
                                  floor={'op': 'probe_ok', 'probe': probe}, actor=actor)
            reg['scores'][n['id']] = score
            inner.append(score)
        avg = store.add('op', 'avg:%s' % key, floor={'op': 'math', 'fn': 'avg'}, actor=actor)
        hundred = store.add('value', '100', floor={'op': 'value', 'value': 100}, actor=actor)
        mul = store.add('op', 'real%%:%s' % key, floor={'op': 'math', 'fn': '*'}, actor=actor)
        for n in dom['nodes']:
            store.wire(reg['scores'][n['id']], avg, actor=actor)
        store.wire(avg, mul, actor=actor)
        store.wire(hundred, mul, actor=actor)
        store.wire(mul, grand, actor=actor)
        inner.extend((avg, hundred, mul))
        gid = store.add('group', key, inner=inner, actor=actor)
        reg['domains'][key] = gid
        reg['pcts'][key] = mul
    reg['session'] = store.add('session', 'grand-map-reality',
                               inner=list(reg['domains'].values()) + [grand], actor=actor)
    return reg
