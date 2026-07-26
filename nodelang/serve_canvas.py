"""nodelang.serve_canvas -- THE VISUAL NODE LANGUAGE over the one-table engine.

Serves an interactive canvas (canvas.html) that draws the running graph as node
cards + wires, drills one level at a time into groups/sessions (SPEC section 8:
scale = grouping, one level rendered), and edits a node's value in place -> the
watcher POST -> apply_op -> dirty -> the number recomputes on the canvas. The
page is not a picture of the graph; it drives the real engine over HTTP.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .graph_api import level_view

_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'canvas.html')


class CanvasServer:
    def __init__(self, store, root_id, reg=None, host='127.0.0.1', port=0):
        self.store = store
        self.root_id = root_id
        self.reg = reg                # optional grand-map registry (status edits)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, ctype, data):
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json(self, obj, code=200):
                self._send(code, 'application/json', json.dumps(obj).encode('utf-8'))

            def do_GET(self):
                path = self.path.split('?', 1)[0]
                if path in ('/', ''):
                    with open(_HTML, 'rb') as fh:
                        return self._send(200, 'text/html; charset=utf-8', fh.read())
                if path == '/api/root':
                    n = outer.store.nodes[outer.root_id]
                    return self._json({'root': outer.root_id,
                                       'title': n['title'] or outer.root_id})
                if path == '/api/level':
                    q = self.path.split('?', 1)[1] if '?' in self.path else ''
                    params = dict(p.split('=', 1) for p in q.split('&') if '=' in p)
                    from urllib.parse import unquote
                    cid = unquote(params.get('id', outer.root_id))
                    try:
                        return self._json(level_view(outer.store, cid))
                    except Exception as exc:
                        return self._json({'error': repr(exc)}, 400)
                return self._json({'error': 'not found'}, 404)

            def do_POST(self):
                # Always DRAIN the request body first -- replying (esp. a 404)
                # before reading the sent bytes aborts the connection on Windows.
                n = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(n)
                path = self.path.split('?', 1)[0]
                handler = {
                    '/edit': outer.edit,
                    '/wire': outer.wire,
                    '/group': outer.group,
                    '/add': outer.add,
                    '/gate': outer.gate,
                    '/pos': outer.pos,
                }.get(path)
                if handler is None:
                    return self._json({'error': 'not found'}, 404)
                try:
                    payload = json.loads(raw.decode('utf-8'))
                except Exception as exc:                # malformed body -> 400
                    return self._json({'ok': False, 'error': repr(exc)}, 400)
                try:
                    out = handler(payload)
                except Exception as exc:                # engine refusal -> 400 with the repr
                    return self._json({'ok': False, 'error': repr(exc)}, 400)
                resp = {'ok': True}
                if out is not None:
                    resp['id'] = out
                return self._json(resp)

        self.httpd = ThreadingHTTPServer((host, port), H)
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def edit(self, payload):
        """Watcher edit through the ONE edit path. If the node is a grand-map
        status value node and we hold the registry, use set_status (re-points
        the weight reference too); else set the node's floor value directly."""
        nid = payload['node_id']
        val = payload['value']
        if self.reg is not None:
            inv = {v: k for k, v in self.reg.get('values', {}).items()}
            if nid in inv and val in self.reg.get('scale', {}):
                from . import map_import
                return map_import.set_status(self.store, self.reg, inv[nid], val,
                                             actor='canvas')
        return self.store.apply_op({'op': 'set', 'id': nid,
                                    'path': ['body', 'floor', 'value'],
                                    'value': val, 'actor': 'canvas'})

    # -- canvas mutations: each routes through an EXISTING public engine op,
    #    so every move lands in the one table + append-only history. --------

    def wire(self, payload):
        """Draw a wire between two existing nodes (store.wire -> add_wire op).
        Both endpoints are checked FIRST: core's add_wire appends the wire node
        before touching endpoint.relations, so a missing endpoint would leave a
        dangling wire in the one table. Refuse cleanly instead (400)."""
        src, dst = payload['from'], payload['to']
        for end in (src, dst):
            if end not in self.store.nodes:
                raise KeyError('wire endpoint %r not in the one table' % (end,))
        return self.store.wire(src, dst, actor='canvas')

    def group(self, payload):
        """Lasso existing nodes into ONE group node (laws_structure.group)."""
        from . import laws_structure
        return laws_structure.group(self.store, payload['ids'],
                                    payload.get('title', 'group'))

    def add(self, payload):
        """Spawn a node from the palette (store.apply_op add_node via store.add).
        The palette supplies the floor spec; kind is DATA on the one shape."""
        return self.store.add(payload['kind'], payload.get('title', ''),
                              floor=payload['floor'], actor='canvas')

    def gate(self, payload):
        """Set or clear a wire's gate (laws_structure.set_gate/clear_gate).
        gate_id=None clears; the gate is any node in the one table (section 7)."""
        from . import laws_structure
        gid = payload.get('gate_id')
        if gid is None:
            return laws_structure.clear_gate(self.store, payload['wire_id'])
        return laws_structure.set_gate(self.store, payload['wire_id'], gid)

    def pos(self, payload):
        """Persist a node's canvas position (hand-layout) as an AUDITED 'set'
        op on path ['meta','pos'] -> it lives in the one table + history, NOT a
        side dict. level_view surfaces it back as node['pos']."""
        return self.store.apply_op(
            {'op': 'set', 'id': payload['id'],
             'path': ['meta', 'pos'],
             'value': {'x': payload['x'], 'y': payload['y']},
             'actor': 'canvas'})

    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def url(self):
        h, p = self.httpd.server_address[:2]
        return 'http://%s:%d' % (h, p)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=10)


def _grandmap_server(port=8478):
    from .core import Store, validate_store
    from . import map_import
    s = Store()
    reg = map_import.import_grand_map(s)
    validate_store(s)
    return CanvasServer(s, reg['session'], reg=reg, port=port)


if __name__ == '__main__':
    srv = _grandmap_server().start()
    print('CANVAS (visual node language) serving the grand map at', srv.url)
    print('nodes in the one table:', len(srv.store.nodes))
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()
