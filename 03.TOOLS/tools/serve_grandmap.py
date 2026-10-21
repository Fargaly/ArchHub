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
import json
import threading
from http.server import BaseHTTPRequestHandler

from nodelang.http_server import create_http_server
from nodelang.laws_surface import render

_PAGE = ('<!doctype html><html><head><meta charset="utf-8">'
         '<title>nodelang</title></head><body>%s</body></html>')


class NodeServer:
    """Serve the ui-domain root of a Store on a real TCP port (0 = free port)."""

    def __init__(self, store, ui_root, host='127.0.0.1', port=0):
        self.store = store
        self.ui_root = ui_root
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):   # keep pytest output clean
                pass

            def _send(self, code, ctype, data):
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _err(self, code, msg):
                self._send(code, 'application/json',
                           json.dumps({'ok': False, 'error': msg}).encode('utf-8'))

            def do_GET(self):
                if self.path not in ('/', ''):
                    return self._err(404, 'not found')
                try:
                    page = _PAGE % render(outer.store, outer.ui_root)
                except Exception as exc:                # pragma: no cover
                    return self._err(500, repr(exc))
                return self._send(200, 'text/html; charset=utf-8', page.encode('utf-8'))

            def do_POST(self):
                if self.path != '/edit':
                    return self._err(404, 'not found')
                try:
                    n = int(self.headers.get('Content-Length') or 0)
                    payload = json.loads(self.rfile.read(n).decode('utf-8'))
                    out = outer.edit(payload)
                except Exception as exc:
                    return self._err(400, repr(exc))
                return self._send(200, 'application/json',
                           json.dumps({'ok': True, 'id': out}).encode('utf-8'))

        self.httpd = create_http_server((host, port), Handler, threaded=True)
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return 'http://%s:%d' % (host, port)

    def edit(self, payload):
        """The watcher edit -- everything routes through Store.apply_op."""
        node_id = payload['node_id']
        param = payload.get('param')
        if param:
            target = self.store.nodes[node_id]['params'][param]
        else:
            target = node_id
        return self.store.apply_op({'op': 'set', 'id': target,
                                    'path': ['body', 'floor', 'value'],
                                    'value': payload['value']})

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join()


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
