"""Capture console messages from the running page."""
from __future__ import annotations

import json
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


def main():
    ws = websocket.create_connection(_ws(), timeout=10)
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Log.enable"}))
    # Poll for console events for 3s.
    deadline = time.time() + 3
    msgs = []
    while time.time() < deadline:
        try: ws.settimeout(0.5); raw = ws.recv()
        except Exception: continue
        try: d = json.loads(raw)
        except Exception: continue
        m = d.get("method", "")
        if m == "Runtime.consoleAPICalled":
            ps = d.get("params", {})
            text = " ".join(str(a.get("value", "")) for a in ps.get("args", []))
            msgs.append(f"[{ps.get('type')}] {text}")
        elif m == "Runtime.exceptionThrown":
            ex = d.get("params", {}).get("exceptionDetails", {})
            msgs.append(f"[exc] {ex.get('text','')} :: {ex.get('exception',{}).get('description','')}")
    # Replay the buffer.
    ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate",
        "params": {"expression":
                   "JSON.stringify({hasStudio: typeof StudioLM, hasReact: typeof React, jsxBoot: !!window.__archhub_jsx_boot})"}}))
    while True:
        try: raw = ws.recv()
        except Exception: break
        try: d = json.loads(raw)
        except Exception: continue
        if d.get("id") == 3:
            print("state:", d.get("result", {}).get("result", {}).get("value"))
            break
    ws.close()
    print(f"--- {len(msgs)} console msgs:")
    for m in msgs[-40:]:
        print(m)


if __name__ == "__main__":
    main()
