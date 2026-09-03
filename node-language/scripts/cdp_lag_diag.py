"""Lag diagnostics — capture DOM size, React component count proxy,
listener accumulation, and a 2s frame-rate sample."""
from __future__ import annotations

import json
import sys
import time
import urllib.request

import websocket  # type: ignore


def _ws():
    data = json.loads(urllib.request.urlopen(
        "http://localhost:9223/json", timeout=10).read().decode("utf-8"))
    for p in data:
        if p.get("type") == "page": return p["webSocketDebuggerUrl"]
    raise SystemExit("no page")


def _send(ws, _id, method, params=None):
    msg = {"id": _id, "method": method}
    if params: msg["params"] = params
    ws.send(json.dumps(msg))
    deadline = time.time() + 30
    while time.time() < deadline:
        try: raw = ws.recv()
        except Exception: continue
        try: d = json.loads(raw)
        except Exception: continue
        if d.get("id") == _id: return d
    raise TimeoutError(method)


def _eval(ws, _id, expr):
    return _send(ws, _id, "Runtime.evaluate",
                 {"expression": expr, "returnByValue": True,
                  "awaitPromise": True})


def main():
    ws = websocket.create_connection(_ws(), timeout=10)
    _send(ws, 1, "Runtime.enable")

    # Snapshot 1 — DOM + graph + handler counts.
    snap = """
    (function(){
      function countListeners(){
        // No public API; approximate via known node-listener attrs.
        var nodes = document.querySelectorAll('[onclick],[onmousedown],[onmouseup],[onmousemove]');
        return nodes.length;
      }
      var graph = window.__archhub_LM_GRAPH || {};
      var sess  = window.__archhub_LM_SESSIONS || [];
      var hosts = window.__archhub_LM_HOSTS || [];
      var conn  = window.__archhub_LM_CONNECTORS || [];
      var skills = window.__archhub_LM_SAVED_SKILLS || [];
      var custom = window.__archhub_LM_CUSTOM_NODES || [];
      return JSON.stringify({
        dom_total_nodes: document.getElementsByTagName('*').length,
        dom_with_inline_listeners: countListeners(),
        graph_nodes: (graph.nodes || []).length,
        graph_wires: (graph.wires || []).length,
        sessions: sess.length,
        hosts: hosts.length,
        connectors: conn.length,
        saved_skills: skills.length,
        custom_nodes: custom.length,
        body_inner_text_len: document.body.innerText.length,
        bridge_ready: window.__archhub_ready === true,
        bump_ready: typeof window.__archhubBumpGraph === 'function',
        canvas_class: !!document.querySelector('.lm-node'),
        active_modal: !!document.querySelector('[data-modal="1"]'),
        last_pull_count: window.__archhub_last_pull_count || null
      });
    })()
    """
    r = _eval(ws, 2, snap)
    snapshot = json.loads(r["result"]["result"]["value"])
    print("snapshot:", json.dumps(snapshot, indent=2))

    # 2s frame-rate sample using requestAnimationFrame.
    rafs = """
    new Promise(function(resolve){
      var frames = 0;
      var t0 = performance.now();
      function loop(){
        frames++;
        if (performance.now() - t0 < 2000) requestAnimationFrame(loop);
        else resolve(JSON.stringify({frames: frames, elapsed_ms: Math.round(performance.now() - t0)}));
      }
      requestAnimationFrame(loop);
    })
    """
    r = _eval(ws, 3, rafs)
    print("2s frame sample:", r["result"]["result"]["value"])

    # Detect long-tasks via PerformanceObserver — install briefly + collect.
    longtask = """
    new Promise(function(resolve){
      var entries = [];
      try {
        var po = new PerformanceObserver(function(list){
          list.getEntries().forEach(function(e){
            entries.push({name: e.name, duration_ms: Math.round(e.duration),
                          startTime: Math.round(e.startTime)});
          });
        });
        po.observe({entryTypes: ['longtask']});
        setTimeout(function(){
          po.disconnect();
          resolve(JSON.stringify({longtasks: entries.slice(-20),
                                   total_longtasks: entries.length}));
        }, 2500);
      } catch(e) { resolve(JSON.stringify({error: e.message})); }
    })
    """
    r = _eval(ws, 4, longtask)
    print("longtasks:", r["result"]["result"]["value"])

    ws.close()


if __name__ == "__main__": main()
