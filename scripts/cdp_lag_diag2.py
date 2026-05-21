"""Time each bridge slot pullAll calls.  Identifies which slot is the
bottleneck so we know where to optimise."""
from __future__ import annotations
import json, time, urllib.request
import websocket  # type: ignore


def _ws():
    data = json.loads(urllib.request.urlopen("http://localhost:9223/json", timeout=10).read().decode("utf-8"))
    for p in data:
        if p.get("type") == "page": return p["webSocketDebuggerUrl"]
    raise SystemExit("no page")


def _send(ws, _id, method, params=None):
    msg = {"id": _id, "method": method}
    if params: msg["params"] = params
    ws.send(json.dumps(msg))
    while True:
        raw = ws.recv()
        try: d = json.loads(raw)
        except: continue
        if d.get("id") == _id: return d


def _eval(ws, _id, expr):
    return _send(ws, _id, "Runtime.evaluate",
                 {"expression": expr, "returnByValue": True, "awaitPromise": True})


def main():
    ws = websocket.create_connection(_ws(), timeout=10)
    _send(ws, 1, "Runtime.enable")

    expr = """
    (async function(){
      var slots = [
        'get_sessions','get_hosts','get_models','get_memory_stats',
        'get_saved_skills','get_permissions','get_providers',
        'list_memory_facts','get_connectors','get_node_grammar',
        'get_custom_nodes'
      ];
      var out = [];
      for (var i=0;i<slots.length;i++){
        var s = slots[i];
        var t0 = performance.now();
        try {
          var r = await window.bridgeJson(s);
          var ms = Math.round(performance.now() - t0);
          var size = r ? JSON.stringify(r).length : 0;
          out.push({slot: s, ms: ms, ok: true, response_chars: size});
        } catch(e) {
          out.push({slot: s, ms: Math.round(performance.now() - t0),
                    ok: false, error: e.message});
        }
      }
      var total = out.reduce(function(a,x){return a+x.ms;}, 0);
      return JSON.stringify({total_ms: total, slots: out});
    })()
    """
    r = _eval(ws, 2, expr)
    print(r["result"]["result"]["value"])

    # Re-trigger to see steady-state (cache warm).
    print("\n--- second pass (warm) ---")
    r = _eval(ws, 3, expr)
    print(r["result"]["result"]["value"])

    ws.close()


if __name__ == "__main__": main()
