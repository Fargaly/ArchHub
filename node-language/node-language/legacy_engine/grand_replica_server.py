"""Serve the running grand-map replica as a small stdlib web app.

The server owns one Graph returned by grand_replica.build_replica(). Every
surface is rendered by walking that live graph and evaluating node ids.
"""
from __future__ import annotations

import html
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .grand_replica import build_replica


HOST = "127.0.0.1"
PORT = 8482


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _safe_eval(graph, node_id):
    try:
        return _jsonable(graph.eval(node_id))
    except Exception as exc:
        return {"eval_error": repr(exc)}


def _domain_ids(graph):
    return [node_id for node_id in graph.nodes if node_id.startswith("domain:")]


def _real_node_ids(real_nodes):
    return [node_id for node_id, _kind in real_nodes]


def _domain_for_node(graph, node_id):
    # domains run as group nodes whose out is a live_count node ending ':live'
    for lc_id, node in graph.nodes.items():
        if node.get("kind") != "live_count":
            continue
        if node_id not in node.get("inputs", []):
            continue
        if lc_id.endswith(":live"):
            domain_id = "domain:" + lc_id[:-5]
            if domain_id in graph.nodes:
                return domain_id
    return None


def _domain_score(graph, domain_id):
    if not domain_id or domain_id not in graph.nodes:
        return None
    node = graph.nodes[domain_id]
    out_id = node.get("params", {}).get("out")
    if out_id not in graph.nodes:
        return _safe_eval(graph, domain_id)
    value = _safe_eval(graph, out_id)
    # live_count returns {live_nodes, total} — the REAL domain metric is how many
    # of its nodes are live NOW; expose that count (comparable) as the score.
    if isinstance(value, dict) and "live_nodes" in value:
        return value["live_nodes"]
    return value


def _state_dict(graph):
    state = {}
    for node_id, node in graph.nodes.items():
        domain_id = _domain_for_node(graph, node_id)
        item = {
            "kind": node["kind"],
            "value": _safe_eval(graph, node_id),
            "params": dict(node.get("params", {})),
            "inputs": list(node.get("inputs", [])),
        }
        if domain_id:
            item["domain"] = domain_id
            item["domain_value"] = _domain_score(graph, domain_id)
        state[node_id] = item
    return state


def _value_text(value):
    return html.escape(json.dumps(value, ensure_ascii=True, sort_keys=True))


def _render_status_nodes(graph, state, domain_id):
    rows = []
    for node_id, item in state.items():
        if item.get("domain") != domain_id or item["kind"] != "status_score":
            continue
        status = item["params"].get("status", "")
        rows.append(
            '<button class="node" data-node-id="%s" data-key="status" '
            'data-val="%s"><span>%s</span><b>%s</b></button>'
            % (
                html.escape(node_id),
                "live" if status != "live" else "vision",
                html.escape(node_id),
                html.escape(status),
            )
        )
    return "\n".join(rows)


def render_page(graph, real_nodes, port):
    state = _state_dict(graph)
    domain_cards = []
    for domain_id in _domain_ids(graph):
        item = state[domain_id]
        score = _domain_score(graph, domain_id)
        domain_cards.append(
            '<section class="domain" data-node-id="%s">'
            '<div class="domain-head"><h2>%s</h2>'
            '<div class="score"><span>group</span><strong>%s</strong></div>'
            '<div class="score"><span>score</span><strong>%s</strong></div>'
            "</div><div class=\"nodes\">%s</div></section>"
            % (
                html.escape(domain_id),
                html.escape(domain_id),
                _value_text(item["value"]),
                _value_text(score),
                _render_status_nodes(graph, state, domain_id),
            )
        )

    real_rows = []
    for node_id in _real_node_ids(real_nodes):
        item = state[node_id]
        real_rows.append(
            '<tr><td>%s</td><td>%s</td><td><code>%s</code></td></tr>'
            % (
                html.escape(node_id),
                html.escape(item["kind"]),
                _value_text(item["value"]),
            )
        )

    page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ARCH Grand Replica</title>
<style>
:root { color-scheme: dark; --bg: #0e0e11; --panel: #17171c; --line: #2a2a31; --text: #f6efe9; --muted: #b8aca5; --accent: #d97757; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: Inter, Arial, sans-serif; }
header { padding: 28px 32px 16px; border-bottom: 1px solid var(--line); }
h1, h2 { font-family: "Instrument Serif", Georgia, serif; font-weight: 400; letter-spacing: 0; margin: 0; }
h1 { font-size: 42px; color: var(--accent); }
.meta { margin-top: 8px; color: var(--muted); font-size: 13px; }
main { padding: 22px 32px 36px; display: grid; gap: 24px; }
.domains { display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); gap: 14px; align-items: start; }
.domain { border: 1px solid var(--line); background: var(--panel); border-radius: 8px; overflow: hidden; }
.domain-head { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 14px; border-bottom: 1px solid var(--line); }
h2 { font-size: 25px; min-width: 0; overflow-wrap: anywhere; }
.score { min-width: 72px; text-align: right; }
.score span { display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; }
.score strong { font-size: 15px; color: var(--text); overflow-wrap: anywhere; }
.nodes { display: grid; grid-template-columns: 1fr; max-height: 230px; overflow: auto; }
.node { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 8px 12px; border: 0; border-bottom: 1px solid #222229; background: transparent; color: var(--text); text-align: left; font: inherit; cursor: pointer; }
.node:hover { background: #202027; }
.node span { overflow-wrap: anywhere; }
.node b { color: var(--accent); font-size: 12px; }
table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
th, td { padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; font-size: 13px; }
th { color: var(--accent); font-weight: 600; }
code { white-space: pre-wrap; overflow-wrap: anywhere; color: #f7d7c8; }
#toast { position: fixed; right: 16px; bottom: 16px; background: var(--accent); color: #21100a; padding: 10px 12px; border-radius: 6px; font-weight: 700; opacity: 0; transform: translateY(8px); transition: opacity .16s, transform .16s; }
#toast.show { opacity: 1; transform: translateY(0); }
</style>
</head>
<body>
<header>
  <h1>ARCH Grand Replica</h1>
  <div class="meta">Live node graph on 127.0.0.1:__PORT__ - click a status node to POST /edit and recook its domain.</div>
</header>
<main>
  <section class="domains">__DOMAINS__</section>
  <section>
    <h2>REAL nodes</h2>
    <table><thead><tr><th>id</th><th>kind</th><th>live value</th></tr></thead><tbody>__REAL_ROWS__</tbody></table>
  </section>
</main>
<div id="toast"></div>
<script>
const toast = document.getElementById("toast");
function flash(text) {
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1400);
}
document.addEventListener("click", async (event) => {
  const node = event.target.closest("[data-node-id][data-key]");
  if (!node) return;
  const payload = { id: node.dataset.nodeId, key: node.dataset.key, val: node.dataset.val };
  const resp = await fetch("/edit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const data = await resp.json();
  if (!resp.ok || !data.ok) {
    flash("edit failed");
    return;
  }
  flash(data.id + " -> " + JSON.stringify(data.value));
  setTimeout(() => location.reload(), 250);
});
</script>
</body>
</html>"""
    return (
        page.replace("__PORT__", str(port))
        .replace("__DOMAINS__", "\n".join(domain_cards))
        .replace("__REAL_ROWS__", "\n".join(real_rows))
    )


class ReplicaServer:
    """ThreadingHTTPServer wrapper for tests and the CLI."""

    def __init__(self, graph=None, real_nodes=None, replica_port=None, host=HOST, port=PORT):
        if graph is None or real_nodes is None:
            graph, real_nodes, replica_port = build_replica()
        self.graph = graph
        self.real_nodes = list(real_nodes)
        self.replica_port = replica_port
        self._lock = threading.RLock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, ctype, data):
                if isinstance(data, str):
                    data = data.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json(self, code, data):
                self._send(code, "application/json", json.dumps(data).encode("utf-8"))

            def _err(self, code, message):
                self._json(code, {"ok": False, "error": message})

            def do_GET(self):
                path = urlsplit(self.path).path
                if path in ("", "/"):
                    with outer._lock:
                        page = render_page(outer.graph, outer.real_nodes, outer.port)
                    self._send(200, "text/html; charset=utf-8", page)
                    return
                if path == "/api/state":
                    with outer._lock:
                        state = _state_dict(outer.graph)
                    self._json(200, state)
                    return
                self._err(404, "not found")

            def do_POST(self):
                path = urlsplit(self.path).path
                if path != "/edit":
                    self._err(404, "not found")
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                    with outer._lock:
                        result = outer.edit(payload)
                except Exception as exc:
                    self._err(400, repr(exc))
                    return
                self._json(200, result)

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=10)

    def edit(self, payload):
        node_id = payload["id"]
        key = payload["key"]
        value = payload["val"]
        if node_id not in self.graph.nodes:
            raise KeyError(node_id)
        if key not in self.graph.nodes[node_id].get("params", {}):
            raise KeyError(key)

        domain_id = _domain_for_node(self.graph, node_id)
        before = _safe_eval(self.graph, node_id)
        domain_before = _domain_score(self.graph, domain_id)
        group_before = _safe_eval(self.graph, domain_id) if domain_id else None

        self.graph.set_param(node_id, key, value)

        after = _safe_eval(self.graph, node_id)
        domain_after = _domain_score(self.graph, domain_id)
        group_after = _safe_eval(self.graph, domain_id) if domain_id else None
        return {
            "ok": True,
            "id": node_id,
            "key": key,
            "value": after,
            "before": before,
            "domain": {
                "id": domain_id,
                "value": domain_after,
                "before": domain_before,
                "group_value": group_after,
                "group_before": group_before,
            },
        }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = int(argv[0]) if argv else PORT
    server = ReplicaServer(host=HOST, port=port).start()
    print("grand replica server:", server.url, flush=True)
    try:
        webbrowser.open(server.url)
    except Exception:
        pass
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
