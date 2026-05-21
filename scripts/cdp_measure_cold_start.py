"""Measure ArchHub cold-start timings via CDP — pin AgDR-0026 Phase 1.

Reports:
  - navigationStart → loadEventEnd  (app boot total)
  - DOMContentLoaded delta
  - resourceTiming for vendor + JSX assets
  - whether `window.archhubReady` resolved + when StudioLm mounted
"""
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
        if p.get("type") == "page":
            return p["webSocketDebuggerUrl"]
    raise SystemExit("no page")


def _send(ws, _id, method, params=None):
    msg = {"id": _id, "method": method}
    if params: msg["params"] = params
    ws.send(json.dumps(msg))
    deadline = time.time() + 30
    while time.time() < deadline:
        raw = ws.recv()
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
    try:
        _send(ws, 1, "Runtime.enable")
        # Wait for fully loaded.
        deadline = time.time() + 30
        while time.time() < deadline:
            r = _eval(ws, 2, "document.readyState")
            if r["result"]["result"]["value"] == "complete": break
            time.sleep(0.3)

        # Get raw perf-timing numbers.
        expr = """
        (function(){
          var t = performance.timing;
          var all = performance.getEntriesByType('resource');
          var entries = all.map(function(e){
            return {name: e.name.split('/').slice(-1)[0] || e.name,
                    duration_ms: Math.round(e.duration),
                    size_bytes: e.transferSize || e.encodedBodySize || 0,
                    startTime_ms: Math.round(e.startTime)};});
          var nav = performance.getEntriesByType('navigation')[0];
          // localStorage cache state — show which entries jsx-boot wrote.
          var cacheKeys = [];
          for (var i = 0; i < localStorage.length; i++) {
            var k = localStorage.key(i);
            if (k && k.indexOf('jsx_cache_v1_') === 0) {
              cacheKeys.push({key: k, size: (localStorage.getItem(k) || '').length});
            }
          }
          return JSON.stringify({
            domContentLoaded_ms: t.domContentLoadedEventEnd - t.navigationStart,
            loadEventEnd_ms: t.loadEventEnd - t.navigationStart,
            bridgeReady: window.__archhub_ready,
            bumpReady: typeof window.__archhubBumpGraph === 'function',
            jsx_boot: window.__archhub_jsx_boot || null,
            jsx_cache_entries: cacheKeys,
            allResourceCount: all.length,
            resources: entries
          });
        })()
        """
        r = _eval(ws, 3, expr)
        print(r["result"]["result"]["value"])
        return 0
    finally:
        ws.close()


if __name__ == "__main__":
    sys.exit(main())
