"""Diagnose why ArchHub boots into a session instead of Home.

Probes the live renderer: what studio-lm.jsx the browser actually
fetched, the jsx-boot cache results, the current DOM, and the
session-id global.
"""
from __future__ import annotations

import json
import sys
import urllib.request

import websocket  # type: ignore

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _ws():
    data = json.loads(urllib.request.urlopen(
        "http://localhost:9223/json", timeout=10).read().decode("utf-8"))
    for p in data:
        if p.get("type") == "page":
            return p["webSocketDebuggerUrl"]
    raise SystemExit("no page")


PROBE = r"""
(async () => {
  const out = {};
  out.session_id = window.__archhub_session_id || null;
  out.jsx_boot = window.__archhub_jsx_boot || null;
  const root = document.getElementById('root');
  out.root_text = root ? (root.innerText || '').slice(0, 240) : '(no root)';
  out.splash_present = !!document.getElementById('__archhub_splash');
  // Tabs only exist inside Workspace -> WsHeader.
  out.tab_count = document.querySelectorAll('[data-wstab]').length;
  try {
    const r = await fetch('studio-lm.jsx', { cache: 'no-store' });
    const txt = await r.text();
    out.studio_len = txt.length;
    const m = txt.match(/const \[openId, setOpenId\] = React\.useState\([^)]*\)/);
    out.openId_decl = m ? m[0] : '(NOT FOUND)';
    out.has_didAutoOpen = txt.indexOf('didAutoOpenRef') !== -1;
    out.has_initialId = txt.indexOf('initialId') !== -1;
    out.has_no_autoopen_comment =
      txt.indexOf('NO auto-open of the most recent') !== -1;
  } catch (e) { out.fetch_err = String(e); }
  return JSON.stringify(out, null, 1);
})()
"""


def main():
    ws = websocket.create_connection(_ws(), timeout=15)
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
        "params": {"expression": PROBE,
                   "awaitPromise": True, "returnByValue": True}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == 2:
            res = d.get("result", {})
            if res.get("exceptionDetails"):
                print("EXCEPTION:", json.dumps(res["exceptionDetails"], indent=1))
            else:
                print(res.get("result", {}).get("value"))
            break
    ws.close()


if __name__ == "__main__":
    main()
