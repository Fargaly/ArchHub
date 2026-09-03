"""Simulate a real node drag via CDP Input domain. Reports whether
the node's screen position changed after a press-move-release."""
import json, sys, time, urllib.request
import websocket  # type: ignore
sys.stdout.reconfigure(encoding="utf-8")

data = json.loads(urllib.request.urlopen("http://localhost:9223/json", timeout=10).read())
ws_url = [p["webSocketDebuggerUrl"] for p in data if p.get("type") == "page"][0]
ws = websocket.create_connection(ws_url, timeout=10)
_id = [0]


def send(method, params=None):
    _id[0] += 1
    i = _id[0]
    ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == i:
            return d.get("result", {})


def ev(expr):
    r = send("Runtime.evaluate",
             {"expression": expr, "returnByValue": True, "awaitPromise": True})
    return r.get("result", {}).get("value")


send("Runtime.enable")
send("Input.enable") if False else None  # Input domain needs no enable

# 1. Title-bar centre of the first node.
box = ev("""(function(){
  var el = document.querySelector('.lm-node');
  if (!el) return null;
  var r = el.getBoundingClientRect();
  return JSON.stringify({
    id: el.getAttribute('data-node-id'),
    x: r.left + r.width/2,
    y: r.top + 14,            // title bar strip
    left: r.left, top: r.top
  });
})()""")
if not box:
    print("NO NODE"); sys.exit(1)
b = json.loads(box)
print("node:", b["id"], "start", round(b["left"], 1), round(b["top"], 1))

x0, y0 = b["x"], b["y"]
x1, y1 = x0 + 120, y0 + 80   # drag 120,80 px

# 2. Press → move (several steps) → release.
send("Input.dispatchMouseEvent", {
    "type": "mousePressed", "x": x0, "y": y0,
    "button": "left", "buttons": 1, "clickCount": 1})
for k in range(1, 9):
    send("Input.dispatchMouseEvent", {
        "type": "mouseMoved",
        "x": x0 + (x1 - x0) * k / 8,
        "y": y0 + (y1 - y0) * k / 8,
        "button": "left", "buttons": 1})
    time.sleep(0.02)
send("Input.dispatchMouseEvent", {
    "type": "mouseReleased", "x": x1, "y": y1,
    "button": "left", "buttons": 0, "clickCount": 1})
time.sleep(0.3)

# 3. Re-read node position.
after = ev("""(function(){
  var el = document.querySelector('[data-node-id="%s"]');
  if (!el) return null;
  var r = el.getBoundingClientRect();
  return JSON.stringify({left: r.left, top: r.top});
})()""" % b["id"])
if not after:
    print("NODE GONE AFTER DRAG"); sys.exit(1)
a = json.loads(after)
dx = a["left"] - b["left"]
dy = a["top"] - b["top"]
print("after drag  ", round(a["left"], 1), round(a["top"], 1))
print("delta       ", round(dx, 1), round(dy, 1))
print("DRAG WORKS" if (abs(dx) > 20 or abs(dy) > 20) else "DRAG BROKEN — node did not move")
ws.close()
