"""THE grand map running AS the node language — poured INTO a live surface.

Imports the real grand_domains.json into the ONE node table, builds a node-UI
(kind='ui' nodes) over the domain group %% ports, and serves it. Every number
on the page is pulled live from the running graph. Edit a node's status via the
watcher POST and the domain %% recomputes — the page changed because a NODE
changed (SPEC 5/10/11). Nothing here is hand-computed; the whole page is a walk
of the same table the map lives in.
"""
import sys, os, webbrowser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nodelang.core import Store, validate_store
from nodelang.laws_surface import ui_element
from nodelang import map_import
from nodelang.serve import NodeServer


def _grand_map_path(path=None):
    candidate = path or os.environ.get('ARCHHUB_GRAND_MAP_PATH')
    if not candidate:
        raise RuntimeError(
            'ARCHHUB_GRAND_MAP_PATH is required; private Grand Map data is '
            'never embedded in the public product tree')
    return os.path.abspath(candidate)


def build(path=None):
    s = Store()
    reg = map_import.import_grand_map(s, path=_grand_map_path(path))
    validate_store(s)
    # a node-UI over the map: title + one row per domain bound to its %% port,
    # + the grand total. All ui nodes, all in the one table.
    rows = [ui_element(s, 'h1', text='ArchHub Grand Map — running as the node language')]
    rows.append(ui_element(s, 'h2', text='Overall %: ', bind=reg['grand']))
    for key in reg['domain_keys']:
        rows.append(ui_element(s, 'div', text='%s: ' % key, bind=reg['muls'][key]))
    root = ui_element(s, 'div', children=rows, title='grand-map-page')
    return s, reg, root


if __name__ == '__main__':
    s, reg, root = build()
    srv = NodeServer(s, root, port=8477).start()
    print('grand map imported into ONE table:', len(s.nodes), 'nodes')
    print('SERVING (live, node-rendered):', srv.url)
    print('Every %% is pulled from the running graph. Edit a node status ->')
    print('  POST', srv.url + '/edit  {node_id, value}  -> its domain %% recomputes.')
    try:
        webbrowser.open(srv.url)
    except Exception:
        pass
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()
