"""nodelang.graph_api -- read the ONE table as a drawable LEVEL for the canvas.

A "level" = the direct inner nodes of a container (session/group) + the wires
whose endpoints are both in that level. Every value is PULLED from the running
graph (SPEC section 4) -- nothing here is stored or hand-computed. This is the
read side of the visual language: the canvas draws exactly what the engine says.
"""
from __future__ import annotations

from .core import relation_sources, relation_stages, relation_targets

CONTAINER_KINDS = ('session', 'group')


def _is_container(store, nid):
    n = store.nodes[nid]
    return n['kind'] in CONTAINER_KINDS or 'inner' in n['body']


def _safe_pull(store, nid):
    try:
        v = store.pull(nid)
    except Exception as exc:                      # a half-wired node still draws
        return None, repr(exc)
    if isinstance(v, float):
        v = round(v, 3)
    return v, None


def _param_summary(store, node):
    out = {}
    for name, pid in (node.get('params') or {}).items():
        if pid in store.nodes:
            v, _ = _safe_pull(store, pid)
            out[name] = v
    return out


def level_view(store, container_id, pull_values=True):
    """Return {container, nodes[], wires[]} for ONE level under container_id."""
    if container_id not in store.nodes:
        raise KeyError(container_id)
    inner = store.open(container_id)
    if not isinstance(inner, list):
        inner = []                                 # a floor node has no level
    level = set(inner)
    nodes = []
    for nid in inner:
        n = store.nodes[nid]
        if n['kind'] == 'wire':
            continue                               # wires drawn as edges, not cards
        val, err = _safe_pull(store, nid) if pull_values else (None, None)
        nodes.append({
            'id': nid,
            'kind': n['kind'],
            'title': n['title'] or nid,
            'value': val,
            'error': err,
            'container': _is_container(store, nid),
            'frozen': bool(n['meta'].get('frozen')),
            'params': _param_summary(store, n),
            'pos': n['meta'].get('pos'),   # hand-layout {x,y} or None (SPEC section: hand-layout)
        })
    # Map every node to its representative AT THIS LEVEL: a node directly in the
    # level maps to itself; a node nested inside a level container maps to that
    # container (SPEC section 3 -- a wire crossing a group boundary is the
    # group's port). So a wire from an inner mul to the grand total renders as
    # domain-group -> grand at the top level.
    rep = {}
    for nid in inner:
        rep[nid] = nid
        if _is_container(store, nid):
            stack = [nid]
            while stack:
                cur = stack.pop()
                body = store.nodes[cur]['body']
                for cid in body.get('inner', ()):
                    if cid not in rep:
                        rep[cid] = nid
                        if 'inner' in store.nodes[cid]['body']:
                            stack.append(cid)
    wires = []
    for wid, w in store.nodes.items():
        if w['kind'] != 'wire':
            continue
        sources = relation_sources(store.nodes, w)
        targets = relation_targets(store.nodes, w)
        branch = 0
        for source in sources:
            for target in targets:
                src = rep.get(source.get('node_id'))
                dst = rep.get(target.get('node_id'))
                if src in level and dst in level and src != dst:
                    projection_id = wid if len(sources) == len(targets) == 1 \
                        else '%s:branch:%03d' % (wid, branch)
                    wires.append({
                        'id': projection_id,
                        'relation': wid,
                        'from': src,
                        'to': dst,
                        'source_port': source.get('port_id'),
                        'target_port': target.get('port_id'),
                        'gated': any(stage.get('role') == 'gate'
                                     for stage in relation_stages(store.nodes, w)),
                    })
                    branch += 1
    cont = store.nodes[container_id]
    return {
        'container': {'id': container_id, 'kind': cont['kind'],
                      'title': cont['title'] or container_id},
        'nodes': nodes,
        'wires': wires,
    }
