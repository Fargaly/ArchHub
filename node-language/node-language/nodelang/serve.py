"""nodelang.serve -- THE WATCHER MECHANIC over stdlib http.server (SPEC
sections 10/11, section 5 'save is just the graph changing').

GET  /      -> render(store, ui_root): the served page is rendered LIVE from
               the ui nodes in the one table. No template file, no cache of
               the page -- every GET walks the table again.
POST /edit  -> {node_id, param, value}: the watcher edit. Resolves the target
               (the named param node of node_id, or node_id's own floor value
               when param is null/absent) and routes it through
               Store.apply_op -- so a HISTORY node is appended, dirty
               propagation clears the memo, and the NEXT GET / shows the
               change because a NODE changed. That is section 5: save = the
               graph changing; the app has already changed.

No second engine: the server holds a Store and a ui root id, nothing else.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .laws_surface import render

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
                self._send(200, 'text/html; charset=utf-8', page.encode('utf-8'))

            def do_POST(self):
                if self.path != '/edit':
                    return self._err(404, 'not found')
                try:
                    n = int(self.headers.get('Content-Length') or 0)
                    payload = json.loads(self.rfile.read(n).decode('utf-8'))
                    out = outer.edit(payload)
                except Exception as exc:
                    return self._err(400, repr(exc))
                self._send(200, 'application/json',
                           json.dumps({'ok': True, 'id': out}).encode('utf-8'))

        self.httpd = ThreadingHTTPServer((host, port), Handler)
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
        self._thread.join(timeout=10)
