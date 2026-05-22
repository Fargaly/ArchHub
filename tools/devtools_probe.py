"""Live runtime probe — connects to ArchHub's QtWebEngine inspector on
port 9223 and runs a battery of diagnostic JS snippets to verify the
composer dispatch path actually works end-to-end.

Run after launching ArchHub with `QTWEBENGINE_REMOTE_DEBUGGING=9223`.
"""
from __future__ import annotations

import json
import urllib.request
import websocket  # type: ignore


def main() -> None:
    data = json.load(urllib.request.urlopen("http://localhost:9223/json"))
    ws_url = data[0]["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=10)
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
        return res.get("value", res)

    def section(name: str) -> None:
        print(f"\n=== {name} ===")

    section("BRIDGE PRESENCE")
    print("window.archhub type:", evalJS("typeof window.archhub"))
    print("window.bridgeJson type:", evalJS("typeof window.bridgeJson"))
    print("module bridgeAsync type:",
          evalJS("typeof bridgeAsync !== 'undefined' ? typeof bridgeAsync : '<scoped>'"))
    print("parse_composer_command type:",
          evalJS("typeof (window.archhub && window.archhub.parse_composer_command)"))

    section("WHAT DOES SYNC CALL RETURN?")
    sync_r = evalJS("""(() => {
      const b = window.archhub;
      if (!b) return 'NO_BRIDGE';
      try {
        const r = b.parse_composer_command('/ping outlook', '');
        if (r === undefined) return 'sync→undefined';
        if (r === null) return 'sync→null';
        if (typeof r === 'object' && typeof r.then === 'function') return 'sync→Promise';
        return 'sync→' + typeof r + ' value=' + JSON.stringify(r).slice(0,200);
      } catch (e) { return 'EXC: ' + (e && e.message); }
    })()""")
    print("result:", sync_r)

    section("WHAT DOES CALLBACK STYLE RETURN?")
    cb_r = evalJS("""new Promise((resolve)=>{
      const b = window.archhub;
      if (!b) { resolve('NO_BRIDGE'); return; }
      setTimeout(()=>resolve('TIMEOUT_2s'), 2000);
      try {
        b.parse_composer_command('/ping outlook', '', (raw)=>{
          resolve('cb_arg: type=' + typeof raw + ' val=' +
                  (typeof raw==='string' ? raw.slice(0,200) :
                   JSON.stringify(raw).slice(0,200)));
        });
      } catch (e) { resolve('CB_EXC: ' + (e && e.message)); }
    })""", await_promise=True)
    print("result:", cb_r)

    section("LISTENER ATTACHED?")
    listener_r = evalJS("""(() => {
      // Count listeners — we can't introspect window listeners directly,
      // but we can dispatch a sentinel event and see if our test handler
      // received the lm-composer-action AFTER our root listener.
      let caught = null;
      const probe = (e) => { caught = (e.detail && e.detail.action) || 'NO_DETAIL'; };
      window.addEventListener('lm-composer-action', probe);
      window.dispatchEvent(new CustomEvent('lm-composer-action', {
        detail: { action: { command:'__probe__', summary:'probe' }, raw:'__probe__', focusId:'' },
      }));
      window.removeEventListener('lm-composer-action', probe);
      return 'probe caught: ' + JSON.stringify(caught);
    })()""")
    print("result:", listener_r)

    section("window.__archhub_LM_GRAPH STATE")
    print("window.__archhub_LM_GRAPH:",
          evalJS("JSON.stringify({nodes:(window.__archhub_LM_GRAPH.nodes||[]).length, wires:(window.__archhub_LM_GRAPH.wires||[]).length})"))
    print("LM_SESSIONS count:",
          evalJS("(window.__archhub_LM_SESSIONS||[]).length"))

    section("FORCE-FIRE spawn_host_chat")
    spawn_r = evalJS("""(() => {
      const before = (window.__archhub_LM_GRAPH.nodes||[]).length;
      try {
        window.dispatchEvent(new CustomEvent('lm-composer-action', {
          detail: { action: { command:'spawn_host_chat', family:'outlook',
                              verb:'ping', text:'probe',
                              summary:'PROBE spawn outlook' },
                    raw:'probe', focusId:'' },
        }));
      } catch (e) { return 'DISPATCH_EXC: ' + e.message; }
      return 'before=' + before + ' after=' + (window.__archhub_LM_GRAPH.nodes||[]).length;
    })()""")
    print("result:", spawn_r)

    section("WAIT 200ms + RECHECK")
    wait_r = evalJS("""new Promise((r)=>setTimeout(()=>{
      r('nodes=' + (window.__archhub_LM_GRAPH.nodes||[]).length +
         ' wires=' + (window.__archhub_LM_GRAPH.wires||[]).length +
         ' titles=' + JSON.stringify((window.__archhub_LM_GRAPH.nodes||[]).map(n=>n.title)));
    }, 250))""", await_promise=True)
    print("result:", wait_r)

    section("CHECK SHADOWING OF bridgeJson")
    sb_r = evalJS("""(() => {
      // Does the JSX module redefine bridgeJson? In babel-transpiled
      // <script type='text/babel'>, top-level `const` becomes module-
      // scoped — should NOT leak to window. So window.bridgeJson should
      // still be the async one from index.html.
      const sync = window.bridgeJson.toString().slice(0,200);
      return 'window.bridgeJson source: ' + sync;
    })()""")
    print("result:", sb_r)

    section("FOCUSED NODE")
    print("focusId:",
          evalJS("(window.__archhub_focus_id) || '<unset>'"))
    print("openId:",
          evalJS("(window.__archhub_session_id) || '<unset>'"))

    ws.close()


if __name__ == "__main__":
    main()
