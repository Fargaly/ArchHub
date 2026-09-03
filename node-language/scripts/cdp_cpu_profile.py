"""Deep CPU profile — capture a CDP Profiler trace while simulating
composer typing, then rank functions by self-time.  Finds the actual
hot path behind the lag instead of guessing."""
from __future__ import annotations
import json, sys, time, urllib.request
import websocket  # type: ignore
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

data = json.loads(urllib.request.urlopen("http://localhost:9223/json", timeout=10).read())
ws_url = [p["webSocketDebuggerUrl"] for p in data if p.get("type") == "page"][0]
ws = websocket.create_connection(ws_url, timeout=20)
_id = [0]


def send(method, params=None, want=True):
    _id[0] += 1
    i = _id[0]
    ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
    if not want:
        return None
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == i:
            return d.get("result", {})


def ev(expr, await_promise=False):
    r = send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                   "awaitPromise": await_promise})
    return r.get("result", {}).get("value")


send("Runtime.enable")
send("Profiler.enable")
send("Profiler.setSamplingInterval", {"interval": 100})  # 100us — fine grain

# Idle baseline — 2s profile with NO interaction.
send("Profiler.start")
time.sleep(2.0)
idle = send("Profiler.stop")["profile"]

# Now profile WHILE typing into the composer.  Focus the composer
# input, then dispatch a burst of real key events.
focus = ev("""(function(){
  var inp = document.querySelector('input[placeholder*="Reply"], input[placeholder*="ping"]');
  if (!inp) {
    var all = Array.from(document.querySelectorAll('input'));
    inp = all.find(function(x){return (x.placeholder||'').toLowerCase().indexOf('host')>=0
       || (x.placeholder||'').toLowerCase().indexOf('command')>=0;});
  }
  if (!inp) return 'NO COMPOSER INPUT';
  inp.focus();
  window.__prof_input = inp;
  return 'focused: '+(inp.placeholder||'').slice(0,40);
})()""")
print("composer:", focus)

send("Profiler.start")
# Type 30 characters via real input events on the composer.
for ch in "the quick brown fox jumps over x":
    ev("""(function(){
      var inp = window.__prof_input; if(!inp) return;
      var nv = inp.value + %s;
      var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      setter.call(inp, nv);
      inp.dispatchEvent(new Event('input', {bubbles:true}));
    })()""" % json.dumps(ch))
    time.sleep(0.06)
typing = send("Profiler.stop")["profile"]

# Clear the text this script typed — it is a measurement artifact,
# not a real composer message.  Leaving it made the founder think the
# app typed on its own (2026-05-22).
ev("""(function(){
  var inp = window.__prof_input; if(!inp) return;
  var setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, '');
  inp.dispatchEvent(new Event('input', {bubbles:true}));
  delete window.__prof_input;
})()""")


def hot(profile, label):
    """Rank nodes by self-sample count."""
    nodes = {n["id"]: n for n in profile["nodes"]}
    self_hits = {nid: n.get("hitCount", 0) for nid, n in nodes.items()}
    total = sum(self_hits.values()) or 1
    ranked = sorted(nodes.values(),
                    key=lambda n: n.get("hitCount", 0), reverse=True)
    print(f"\n=== {label} — {total} samples ===")
    for n in ranked[:14]:
        hc = n.get("hitCount", 0)
        if hc == 0:
            continue
        cf = n["callFrame"]
        loc = (cf.get("url", "").split("/")[-1] or "?")
        fn = cf.get("functionName") or "(anonymous)"
        ln = cf.get("lineNumber", -1)
        pct = 100.0 * hc / total
        print(f"  {pct:5.1f}%  {hc:5d}  {fn[:36]:36s} {loc}:{ln}")


hot(idle, "IDLE (no interaction, 2s)")
hot(typing, "TYPING in composer (~2s, 30 keystrokes)")
ws.close()
