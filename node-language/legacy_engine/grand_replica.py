"""SUPERSEDED 2026-07-09. This built the map on the LOOSE engine
(`node_lang.py`) and NEVER called validate_store -- so it tolerated bespoke-kind
shells (status_score/live_count), the exact thing the one-table kernel forbids.

THE MAP OF RECORD is now `nodelang/map_import.py` (`import_grand_map`) on the
STRICT kernel (`nodelang.core`, closed KINDS + OneTableViolation): 282 value
nodes + 855 param-nodes + 309 wire-nodes + 15 domain groups + one session,
`validate_store` True. Gated by `tests_replica/test_map_import_full.py`.
Kept only because the `leaf_*.py` court leaves still import `node_lang`; do NOT
build new work here.

THE REPLICA (SPEC §13/§14): the grand map, grown IN PLACE into the running
node language, wired to the REAL systems. Not a %-score dashboard (§15 toy) —
the map's nodes RUN real work: connector/host nodes drive the real Revit model,
brain nodes hit the real brain daemon, cloud nodes check the real cloud. One
living node program on the node_lang engine.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .node_lang import Graph

REVIT_PORTS = [48885, 48884, 48886]   # live revit-mcp brokers


def _grand_map_path(path=None):
    candidate = path or os.environ.get('ARCHHUB_GRAND_MAP_PATH')
    if not candidate:
        raise RuntimeError(
            'ARCHHUB_GRAND_MAP_PATH is required; private Grand Map data is '
            'never embedded in the public product tree')
    return os.path.abspath(candidate)


def _live_revit_port():
    import urllib.request
    for p in REVIT_PORTS:
        try:
            with urllib.request.urlopen('http://localhost:%s/ping' % p, timeout=3) as r:
                if r.getcode() == 200:
                    return p
        except Exception:
            pass
    return REVIT_PORTS[0]


# which map-node ids get REAL effectful executors (drive real systems), by
# domain/keyword — the rest keep their documentation status until built.
def _real_kind_for(node, revit_port):
    nid = node['id']; title = (node.get('title') or '').lower(); sub = (node.get('sub') or '').lower()
    text = nid + ' ' + title + ' ' + sub
    if 'revit' in text or ('connector' in nid and 'revit' in text) or nid.startswith('connectors_revit'):
        return ('host_read', {'port': revit_port,
                'code': 'var c=new FilteredElementCollector(Doc).WhereElementIsNotElementType().ToElementIds().Count; result=c;'})
    if nid.startswith('brain_') and ('recall' in text or 'context' in text or 'memory' in text or 'find' in text):
        return ('brain_read', {'prompt': title or nid})
    if nid.startswith('cloud_') or 'cloud' in title:
        return ('probe', {'kind': 'http_ok', 'spec': {'url': 'https://archhub-cloud.fly.dev/healthz', 'status': 200}})
    return None


def build_replica(path=None):
    doms = json.load(open(_grand_map_path(path), encoding='utf-8'))
    g = Graph()
    port = _live_revit_port()
    real_nodes = []
    for d in doms:
        member_ids = []
        for n in d['nodes']:
            rk = _real_kind_for(n, port)
            if rk:
                kind, params = rk
                g.add(n['id'], kind, params=params)
                real_nodes.append((n['id'], kind))
            else:
                # documentation node: its live value = its status score (until built real)
                g.add(n['id'], 'status_score', params={'status': n.get('status', 'vision')})
            member_ids.append(n['id'])
        # DOMAIN RUNS AS A GROUP NODE (§3): value = how many of its member
        # nodes are actually LIVE/working NOW (real, not toy arithmetic).
        lc_id = d['key'] + ':live'
        g.add(lc_id, 'live_count', inputs=member_ids)
        g.add('domain:' + d['key'], 'group', params={'out': lc_id})
    return g, real_nodes, port


if __name__ == '__main__':
    g, real_nodes, port = build_replica()
    print('grand map loaded as a running node program:', len(g.nodes), 'nodes | live Revit port', port)
    print('REAL effectful nodes (drive live systems), evaluated NOW:')
    for nid, kind in real_nodes:
        val = g.eval(nid)
        print('  %-28s [%s] -> %r' % (nid, kind, val))
    print('engine evals:', g.evals)
