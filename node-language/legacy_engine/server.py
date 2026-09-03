# -*- coding: utf-8 -*-
"""The ONE graph, in a process. The engine runs it. The web UI is a VIEW of it.
The AI (me) reads/writes the SAME graph over HTTP. Both drive one graph — it runs."""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .node_lang import Graph

HERE = os.path.dirname(os.path.abspath(__file__))
G = Graph()
# seed = a tiny LIVE PROGRAM (the language in use, not a product dashboard):
#   const 5, const 3  ->  sum = 8 . it RUNS.
G.add("n_a", "const", params={"value": 5, "_x": 70, "_y": 110})
G.add("n_b", "const", params={"value": 3, "_x": 70, "_y": 240})
G.add("n_sum", "sum", inputs=["n_a", "n_b"], params={"_x": 340, "_y": 175})
_ctr = [0]
def nid(pfx="n"):
    _ctr[0] += 1; return pfx + str(_ctr[0])

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, open(os.path.join(HERE, "index.html"), encoding="utf-8").read(), "text/html; charset=utf-8")
        elif self.path == "/graph":
            self._send(200, json.dumps(G.state()))
        else:
            self._send(404, "{}")
    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(ln) or "{}")
        p = self.path
        if p == "/add":
            i = data.get("id") or nid()
            G.add(i, data.get("kind", "const"),
                  params=dict(data.get("params", {}), _x=data.get("x", 120), _y=data.get("y", 120)),
                  inputs=data.get("inputs", []))
            self._send(200, json.dumps({"id": i}))
        elif p == "/set":
            G.set_param(data["id"], data["key"], data["val"]); self._send(200, "{}")
        elif p == "/wire":
            G.wire(data["dst"], data["src"]); self._send(200, "{}")
        elif p == "/group":
            ids = data["ids"]; G.group(nid("g"), ids, data.get("out", ids[-1] if ids else None),
                                       data.get("x", 220), data.get("y", 60)); self._send(200, "{}")
        elif p == "/del":
            G.remove(data["id"]); self._send(200, "{}")
        else:
            self._send(404, "{}")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    print("node-language server (the ONE graph) on http://localhost:%d" % port, flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
