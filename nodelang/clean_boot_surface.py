"""The screen the founder sees while the graph is opening.

A start that shows nothing is indistinguishable from a start that failed.
This stands a socket on the canvas port before the authority opens, answers
every request with one honest progress page, and steps aside the moment the
real canvas is ready to take the port.

It holds no graph, no keys, and no authority: it can only report phases the
boot itself published, so nothing here can serve product state.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class BootProgress:
    """Phases the boot has entered, and how long each took."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._phases: list[dict[str, object]] = []
        self._done = False

    def begin(self, label: str) -> None:
        with self._lock:
            self._phases.append({
                "label": label,
                "started": round(time.monotonic() - self._started, 1),
                "seconds": None,
            })

    def finish(self, label: str) -> None:
        with self._lock:
            for phase in reversed(self._phases):
                if phase["label"] == label and phase["seconds"] is None:
                    phase["seconds"] = round(
                        time.monotonic() - self._started - float(phase["started"]), 1
                    )
                    return

    def complete(self) -> None:
        with self._lock:
            self._done = True

    def payload(self) -> dict[str, object]:
        with self._lock:
            return {
                "ok": True,
                "done": self._done,
                "elapsed": round(time.monotonic() - self._started, 1),
                "phases": [dict(phase) for phase in self._phases],
            }


PAGE = """<!doctype html>
<meta charset="utf-8"><title>ArchHub is opening</title>
<style>
:root{color-scheme:dark}
body{margin:0;height:100vh;background:#111312;color:#e8e6e3;
font-family:Inter,system-ui,sans-serif;display:grid;
grid-template-rows:1fr auto;overflow:hidden}
.mark{display:flex;align-items:center;justify-content:center;font-size:46px;
font-weight:650;letter-spacing:-.02em}
.mark b{color:#d97757;font-weight:650}
.foot{padding:0 26px 26px}
.bar{height:2px;background:#22261f;border-radius:1px;overflow:hidden}
.fill{height:100%;width:30%;background:#d97757;
animation:slide 1.4s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-110%)}100%{transform:translateX(440%)}}
.line{display:flex;justify-content:space-between;margin-top:10px;
font-size:11px;color:#8b8f8c;font-variant-numeric:tabular-nums}
</style>
<div class="mark">ARCH<b>HUB</b></div>
<div class="foot">
  <div class="bar"><div class="fill"></div></div>
  <div class="line"><span id="phase">opening the graph</span><span id="elapsed"></span></div>
</div>
<script>
// The port changes hands when the canvas stands: this page stops being
// served and /api/universal/boot stops answering. Treating that only as
// "try again" left the founder looking at the boot screen forever after
// the graph was already open, so a run of failures IS the handover.
let missed=0;
async function tick(){
  try{
    const answer=await fetch('/api/universal/boot',{cache:'no-store'});
    if(!answer.ok){throw new Error('boot surface has handed over');}
    const state=await answer.json();
    missed=0;
    if(state.done){location.reload();return;}
    const live=state.phases.filter(p=>p.seconds===null).at(-1);
    document.getElementById('phase').textContent=live?live.label:'opening the graph';
    document.getElementById('elapsed').textContent=state.elapsed+'s';
  }catch(error){
    missed+=1;
    if(missed>=3){location.reload();return;}
  }
  setTimeout(tick,500);
}
tick();
</script>
"""


class _BootHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/universal/boot"):
            body = json.dumps(self.server.progress.payload()).encode("utf-8")
            content = "application/json"
        elif self.path.startswith("/api/"):
            body = json.dumps({
                "ok": False, "error": "the graph is still opening",
            }).encode("utf-8")
            content = "application/json"
        else:
            body = PAGE.encode("utf-8")
            content = "text/html; charset=utf-8"
        self.send_response(200 if content == "text/html; charset=utf-8" else 200)
        self.send_header("Content-Type", content)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        self.do_GET()


class _BootServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, progress: BootProgress) -> None:
        super().__init__(address, _BootHandler)
        self.progress = progress


class BootSurface:
    """A progress page on the canvas port until the canvas itself is ready."""

    def __init__(self, host: str, port: int) -> None:
        self.progress = BootProgress()
        self._server = _BootServer((host, port), self.progress)
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.2),
            name="archhub-boot-surface",
            daemon=True,
        )

    def start(self) -> "BootSurface":
        self._thread.start()
        return self

    def hand_over(self) -> None:
        """Release the port so the real canvas can take it."""
        self.progress.complete()
        # The page polls twice a second; one beat lets a waiting browser
        # learn the boot finished before its socket closes under it.
        time.sleep(0.6)
        self._server.shutdown()
        self._server.server_close()


__all__ = ["BootProgress", "BootSurface"]
