"""CDP verifier for AgDR-0024 S1 — flip flag, splice a Revit master node
into LM_GRAPH, bumpGraph, confirm v2 body renders. No screenshots; only
Runtime.evaluate calls into the live ArchHub.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

import websocket  # type: ignore


def _ws_url():
    # Retry — CDP HTTP endpoint can stall briefly while the page is busy.
    last_err = None
    for _ in range(15):
        try:
            data = json.loads(urllib.request.urlopen(
                "http://localhost:9223/json", timeout=20).read().decode("utf-8"))
            for p in data:
                if p.get("type") == "page":
                    return p["webSocketDebuggerUrl"]
            raise SystemExit("no page in CDP /json")
        except Exception as e:
            last_err = e
            time.sleep(1.5)
    raise SystemExit(f"CDP /json never responded: {last_err}")


def _send(ws, _id, method, params=None):
    msg = {"id": _id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    deadline = time.time() + 30
    while time.time() < deadline:
        raw = ws.recv()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if data.get("id") == _id:
            return data
    raise TimeoutError(f"no reply id={_id} method={method}")


def _eval(ws, _id, expr):
    return _send(ws, _id, "Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True,
    })


def main():
    ws_url = _ws_url()
    print("CDP    :", ws_url)
    ws = websocket.create_connection(ws_url, timeout=10)
    try:
        _send(ws, 1, "Runtime.enable")

        # Wait until React has mounted and exposed __archhubBumpGraph.
        deadline = time.time() + 20
        bump_ready = False
        while time.time() < deadline:
            r = _eval(ws, 2, "typeof window.__archhubBumpGraph")
            if r["result"]["result"]["value"] == "function":
                bump_ready = True
                break
            time.sleep(0.4)
        print("bump ready:", bump_ready)
        if not bump_ready:
            print("ERROR: __archhubBumpGraph never appeared")
            return 1

        # Flip flag ON.
        r = _eval(ws, 3, "window.__archhubSetHostNodeV2(true)")
        print("flag on  :", r["result"]["result"]["value"])

        # Splice a Revit master node into LM_GRAPH, then bumpGraph.
        # Shape mirrors what `addNodeFromLibrary` produces for a per-host
        # connector entry: top-level x/y/w/h + ins/outs + host + config.
        place = """
        (function(){
          try {
            var g = window.__archhub_LM_GRAPH || (window.__archhub_LM_GRAPH = {nodes:[], wires:[], groups:[]});
            if (!Array.isArray(g.nodes)) g.nodes = [];
            g.nodes = g.nodes.filter(function(n){return n && n.id !== 'cdp-revit-master';});
            var node = {
              id: 'cdp-revit-master',
              kind: 'connector',
              cat: 'connector',
              host: 'revit',
              op_id: 'revit.list_walls',
              title: 'Revit · ops',
              sub: 'connector · revit',
              x: 240, y: 240, w: 260, h: 160,
              ins: [],
              outs: [{id: 'result', label: 'result', t: 'any'}],
              params: [],
              config: { host: 'revit', op: 'revit.list_walls' },
              _user: true
            };
            g.nodes.push(node);
            try { window.__archhubBumpGraph(); } catch(e){}
            return 'placed; count=' + g.nodes.length + ' kind=' + node.kind + ' cat=' + node.cat;
          } catch(e) { return 'err: ' + e.message; }
        })()
        """
        r = _eval(ws, 4, place)
        print("place    :", r["result"]["result"]["value"])

        # Allow React paint.
        time.sleep(0.8)

        # Diag 0 — what screen are we on?  Check for canvas vs. home.
        d0 = """
        (function(){
          return JSON.stringify({
            sessions: ((window.LM_SESSIONS || []).map(function(s){return {id:s.id, title:s.title};})).slice(0,5),
            openSessionId: window.__archhub_session_id || null,
            hasCanvas: !!document.querySelector('.lm-node'),
            hasNodeBody: document.body.innerText.indexOf('NODES') >= 0
              || document.body.innerText.indexOf('PRIMITIVES') >= 0,
            url: location.href
          });
        })()
        """
        r = _eval(ws, 35, d0)
        print("screen   :", r["result"]["result"]["value"])

        # Diagnostic — dump what's actually rendered vs. what's in graph.
        diag = """
        (function(){
          var nodes = (window.__archhub_LM_GRAPH && window.__archhub_LM_GRAPH.nodes) || [];
          var dom = Array.from(document.querySelectorAll('[data-node-id]'))
            .map(function(e){return e.getAttribute('data-node-id');});
          var hidden = window.__archhubHiddenMemberIds ? Array.from(window.__archhubHiddenMemberIds) : null;
          return JSON.stringify({
            graphIds: nodes.map(function(n){return [n.id, n.cat, n.kind, n.host];}),
            domIds: dom,
            allNodes_seen_by_canvas: typeof window.__archhubAllNodes === 'function'
              ? window.__archhubAllNodes().map(function(n){return n.id;}) : 'n/a',
          });
        })()
        """
        r = _eval(ws, 45, diag)
        print("diag     :", r["result"]["result"]["value"])

        # Probe DOM for v2 marker, active tile, MAIN INPUTS, brand stripe.
        probe = """
        (function(){
          var v2 = document.querySelectorAll('[data-host-node-v2="s1"]').length;
          var act = document.querySelectorAll('[data-active-tile="1"]').length;
          var mainInputs = document.body.innerText.indexOf('MAIN INPUTS') >= 0;
          var first = document.querySelector('[data-host-node-v2="s1"]');
          var stripe = '';
          if (first) {
            // The component sets border via inline JSX style on the
            // active-tile inner div; the outer wrapper holds the marker.
            var inner = first.querySelector('[data-active-tile="1"]');
            stripe = inner ? (inner.style.border || '') : '';
          }
          var nodes = document.querySelectorAll('[data-node-id]').length;
          return JSON.stringify({
            v2body: v2, activeTile: act, mainInputs: mainInputs,
            activeTileBorder: stripe, anyNodeCount: nodes
          });
        })()
        """
        r = _eval(ws, 5, probe)
        print("DOM      :", r["result"]["result"]["value"])

        # Flip back OFF and re-probe to confirm dispatch reverts to v1.
        _eval(ws, 6, "window.__archhubSetHostNodeV2(false); window.__archhubBumpGraph();")
        time.sleep(0.5)
        r = _eval(ws, 7,
                  "JSON.stringify({v2: "
                  "document.querySelectorAll('[data-host-node-v2=\"s1\"]').length})")
        print("flag off :", r["result"]["result"]["value"])

        # Final state: leave OFF so the next session starts clean.
        return 0
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main())
