"""Live smoke test — simulates a real user typing 'ping outlook' on Home
and verifies the canvas spawns host + conversation nodes correctly.

Requires ArchHub launched with QTWEBENGINE_REMOTE_DEBUGGING=9223.
"""
from __future__ import annotations

import json
import urllib.request
import time
import websocket  # type: ignore


def main() -> None:
    data = json.load(urllib.request.urlopen("http://localhost:9223/json"))
    ws_url = data[0]["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=20)
    mid = [0]

    def cmd(method: str, params: dict | None = None) -> dict:
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method,
                              "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid[0]:
                return msg

    def evalJS(expr: str, await_promise: bool = False) -> object:
        r = cmd("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": await_promise,
        })
        res = r.get("result", {}).get("result", {})
        if res.get("type") == "undefined":
            return "<undefined>"
        if res.get("subtype") == "error":
            return f"<JS error> {res.get('description','')[:200]}"
        return res.get("value", res)

    def section(name: str) -> None:
        print(f"\n=== {name} ===")

    section("BASELINE GRAPH STATE")
    print(evalJS("JSON.stringify({"
                  "nodes:(window.__archhub_LM_GRAPH.nodes||[]).length,"
                  "wires:(window.__archhub_LM_GRAPH.wires||[]).length,"
                  "sessions:(window.__archhub_LM_SESSIONS||[]).length,"
                  "openId:window.__archhub_session_id||'<none>'"
                  "})"))

    section("SIMULATE: type 'ping outlook' on Home composer + submit")
    # We can't truly fire a keyboard event into a React-controlled input
    # without focus + Input.dispatchKeyEvent. Use DOM-level approach: find
    # the Home input, set its value via React's tracker hack, dispatch
    # input + keydown events.
    result = evalJS("""(async () => {
      // Find the Home composer input by its placeholder.
      const inp = document.querySelector(
        'input[placeholder*="new session"], input[placeholder*="Start a new"]'
      ) || document.querySelector(
        'input[placeholder*="ping a host"]'
      );
      if (!inp) return 'NO_INPUT_FOUND';

      // React owns the value setter. Use the native one + tell React.
      const proto = Object.getPrototypeOf(inp);
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(inp, 'ping outlook');
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise(r=>setTimeout(r,50));

      // Press Enter
      inp.dispatchEvent(new KeyboardEvent('keydown', {
        key:'Enter', code:'Enter', which:13, bubbles:true,
      }));

      // Wait for createSession bridge round-trip + 80ms dispatch defer
      await new Promise(r=>setTimeout(r,600));

      return JSON.stringify({
        placeholder: inp.placeholder,
        currentValue: inp.value,
        graph: {
          nodes:(window.__archhub_LM_GRAPH.nodes||[]).length,
          wires:(window.__archhub_LM_GRAPH.wires||[]).length,
          titles:(window.__archhub_LM_GRAPH.nodes||[]).map(n=>n.title),
        },
        sessions: (window.__archhub_LM_SESSIONS||[]).length,
        openId: window.__archhub_session_id||'<none>',
      });
    })()""", await_promise=True)
    print(result)

    section("WAIT 1.5s + RECHECK (in case async createSession is still in flight)")
    time.sleep(1.5)
    print(evalJS("JSON.stringify({"
                  "nodes:(window.__archhub_LM_GRAPH.nodes||[]).length,"
                  "wires:(window.__archhub_LM_GRAPH.wires||[]).length,"
                  "titles:(window.__archhub_LM_GRAPH.nodes||[]).map(n=>n.title),"
                  "sessions:(window.__archhub_LM_SESSIONS||[]).length,"
                  "openId:window.__archhub_session_id||'<none>'"
                  "})"))

    section("CONSOLE LOG TAIL (errors only)")
    cmd("Log.enable")
    cmd("Runtime.enable")
    # Drain pending console messages — re-emit by triggering a log
    result = evalJS("""(() => {
      // Print last 10 entries from a custom tracking ring.
      window.__archhub_log_ring = window.__archhub_log_ring || [];
      return JSON.stringify(window.__archhub_log_ring.slice(-20));
    })()""")
    print(result)

    ws.close()


if __name__ == "__main__":
    main()
