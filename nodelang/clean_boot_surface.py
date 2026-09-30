"""The screen the founder sees while the graph is opening.

A start that shows nothing is indistinguishable from a start that failed.
This stands a socket on the canvas port before the authority opens, answers
every request with one honest progress page, and steps aside the moment the
real canvas is ready to take the port.

It holds no graph, no keys, and no authority: it can only report phases the
boot itself published, so nothing here can serve product state.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .application import THEME

# The phases clean_coordination_service begins, in order. A court reads that
# file's _begin(...) calls and holds this list equal to them, so the page's
# "phase k of n" cannot drift from what the boot actually runs.
BOOT_PHASES: tuple[str, ...] = (
    "open authority and bind coordination",
    "stand the canvas surface",
)


class BootProgress:
    """Phases the boot has entered, how long each took, and what it is doing now.

    ``expected`` holds the seconds each phase took at the last start, so the
    page can move within a long phase instead of sitting on one mark;
    ``detail`` is the restore step the boot is in, read from its own stack.
    """

    def __init__(self, expected: dict[str, float] | None = None) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._phases: list[dict[str, object]] = []
        self._done = False
        self._detail = ""
        self._expected = {
            str(label): float(seconds) for label, seconds in (expected or {}).items()
            if label in BOOT_PHASES and isinstance(seconds, (int, float)) and seconds > 0
        }

    def begin(self, label: str) -> None:
        with self._lock:
            self._detail = ""
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

    def detail(self, text: str) -> None:
        with self._lock:
            self._detail = str(text or "")[:80]

    def complete(self) -> None:
        with self._lock:
            self._done = True

    def durations(self) -> dict[str, float]:
        """The seconds each finished phase took: the next start's expectation."""
        with self._lock:
            return {str(p["label"]): float(p["seconds"]) for p in self._phases if p["seconds"] is not None}

    def payload(self) -> dict[str, object]:
        with self._lock:
            return {
                "ok": True,
                "done": self._done,
                "elapsed": round(time.monotonic() - self._started, 1),
                "phases": [dict(phase) for phase in self._phases],
                "total": len(BOOT_PHASES),
                "detail": self._detail,
                "expected": dict(self._expected),
            }


def load_expected_phases(state_dir: Path) -> dict[str, float]:
    """Last start's phase seconds: boot-phases.json, else boot-profile.log's header."""
    try:
        held = json.loads((Path(state_dir) / "boot-phases.json").read_text(encoding="utf-8"))
        if isinstance(held, dict):
            return {str(k): float(v) for k, v in held.items() if isinstance(v, (int, float))}
    except (OSError, ValueError):
        pass
    try:
        head = (Path(state_dir) / "boot-profile.log").read_text(encoding="utf-8")[:400]
        found = re.search(r"^boot (\d+)s,", head, re.MULTILINE)
        if found:
            return {BOOT_PHASES[0]: float(found.group(1))}
    except OSError:
        pass
    return {}


def save_phase_durations(progress: BootProgress, state_dir: Path) -> None:
    """Keep this start's phase seconds for the next start's page. Never raises."""
    measured = progress.durations()
    if not measured:
        return
    try:
        (Path(state_dir) / "boot-phases.json").write_text(json.dumps(measured), encoding="utf-8")
    except OSError:
        pass


# The boot's own steps, read from its sampled stack, in words. The step is the
# frame directly below restore_universal_application; before restore, the
# journal read. Words only: no graph content ever reaches this page.
_STEP_PREFIXES = ("_ensure_", "ensure_", "_project_", "project_", "_migrate_", "migrate_", "_restore_", "_")


def boot_step_label(stack: list[str]) -> str:
    """``stack`` is outermost-first function names; returns what the boot is doing."""
    for index, name in enumerate(stack):
        if name == "restore_universal_application" and index + 1 < len(stack):
            step = stack[index + 1]
            for prefix in _STEP_PREFIXES:
                if step.startswith(prefix):
                    step = step[len(prefix):]
                    break
            return "restoring " + step.replace("_", " ").strip()
    if "restore_universal_application" in stack:
        return "restoring the application"
    if any(name in ("load_head", "_load_head_unlocked", "_load_head_in_transaction") for name in stack):
        return "reading the saved graph"
    return ""


def _data_font(name: str) -> str:
    raw = (Path(__file__).resolve().parent / "data" / "website" / "fonts" / name).read_bytes()
    return "data:font/woff2;base64," + base64.b64encode(raw).decode("ascii")


# The boot port serves nothing but this page, so the brand faces travel inside
# it: the same woff2 files the website and the Studio serve (site_export.FONT_FACES).
_BRAND_FACES = "".join(
    '@font-face{font-family:"%s";font-style:%s;font-weight:%s;font-display:block;src:url(%s) format("woff2")}'
    % (family, style, weight, _data_font(name))
    for name, family, style, weight in (
        ("instrument-serif-regular.woff2", "Instrument Serif", "normal", "400"),
        ("instrument-serif-italic.woff2", "Instrument Serif", "italic", "400"),
        ("inter-variable.woff2", "Inter", "normal", "400 600"),
    )
)


# Colours are THEME's, the wordmark is the website's: cell_website.py:135
# (.site-brand: Instrument Serif, uppercase, .02em; .site-brand-mark: accent,
# italic), :297-299 (.site-logo arch) and :631-634 (Arch + Hub), at boot size.
# The bar is determinate from the first phase the boot reports; within a phase
# it moves toward the time that phase took at the last start, and never reaches
# the next phase's mark until the phase really ends.
PAGE = """<!doctype html>
<meta charset="utf-8"><title>ArchHub is opening</title>
<style>
%(brand_faces)s
:root{color-scheme:dark}
body{margin:0;height:100vh;background:%(bg)s;color:%(ink)s;
font-family:"Inter",system-ui,sans-serif;display:grid;
grid-template-rows:1fr auto;overflow:hidden}
.mark{display:flex;align-items:center;justify-content:center;gap:26px}
.site-brand-word{font-family:"Instrument Serif",Georgia,serif;font-weight:400;
font-size:52px;letter-spacing:.02em;text-transform:uppercase;white-space:nowrap}
.site-brand-mark{color:%(accent)s;font-style:italic}
.site-logo{position:relative;display:inline-block;width:26px;height:26px;flex:none;transform:scale(2.2)}
.site-logo::before{content:"";position:absolute;left:3.2px;top:3.2px;box-sizing:border-box;
width:19.7px;height:19.6px;border:1.8px solid %(accent)s;border-bottom:0;border-radius:10px 10px 0 0}
.site-logo::after{content:"";position:absolute;left:2.4px;top:23.3px;width:21.2px;height:.7px;
background:%(accent)s;border-radius:1px}
.site-logo-eye{position:absolute;left:10.9px;top:6.8px;box-sizing:border-box;width:4.3px;height:4.3px;
border:1px solid %(accent)s;border-radius:50%%;background:radial-gradient(circle,%(accent)s 0 .7px,%(bg)s .9px)}
.foot{padding:0 26px 26px}
.bar{height:2px;background:%(line)s;border-radius:1px;overflow:hidden}
.fill{height:100%%;width:0;background:%(accent)s;transition:width .3s ease-out}
.bar[data-determinate="false"] .fill{width:30%%;
animation:slide 1.4s ease-in-out infinite}
@keyframes slide{0%%{transform:translateX(-110%%)}100%%{transform:translateX(440%%)}}
.line{display:flex;justify-content:space-between;margin-top:10px;
font-size:11px;color:%(ink_muted)s;font-variant-numeric:tabular-nums}
</style>
<div class="mark"><span class="site-logo" aria-hidden="true"><span class="site-logo-eye"></span></span><span class="site-brand-word"><span>Arch</span><span class="site-brand-mark">Hub</span></span></div>
<div class="foot">
  <div class="bar" data-determinate="false"><div class="fill"></div></div>
  <div class="line"><span><span id="phase">opening the graph</span><span id="detail"></span></span><span id="elapsed"></span></div>
</div>
<script>
// Within a phase the fill moves toward the time that phase took at the last
// start (state.expected); without one it eases over a default. Either way it
// stops at 90%% of the phase's share, so the next mark is reached only when
// the phase really ends.
function progressView(state){
  const DEFAULT_PHASE_SECONDS=30;
  const phases=state.phases||[];
  const total=Math.max(Number(state.total)||0,phases.length);
  if(!phases.length||!total){return {determinate:false,fraction:0,text:'opening the graph',detail:'',estimate:''};}
  const finished=phases.filter(p=>p.seconds!==null).length;
  const live=phases.filter(p=>p.seconds===null).at(-1)||phases.at(-1);
  const k=phases.indexOf(live)+1;
  const known=Number((state.expected||{})[live.label]);
  let within=0;
  if(live.seconds===null){
    const expected=known>0?known:DEFAULT_PHASE_SECONDS;
    const spent=Math.max(0,(Number(state.elapsed)||0)-(Number(live.started)||0));
    within=0.9*(1-Math.exp(-spent/expected));
  }
  return {determinate:true,fraction:(finished+within)/total,
    text:'phase '+k+' of '+total+' \\u00b7 '+live.label,
    detail:state.detail?' \\u2014 '+state.detail:'',
    estimate:known>0?' of about '+Math.round(known)+'s':''};
}

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
    if(state.done){setTimeout(()=>location.reload(),250);return;}
    const view=progressView(state);
    const bar=document.querySelector('.bar');
    bar.dataset.determinate=String(view.determinate);
    bar.querySelector('.fill').style.width=view.determinate?(view.fraction*100)+'%%':'';
    document.getElementById('phase').textContent=view.text;
    document.getElementById('detail').textContent=view.detail||'';
    document.getElementById('elapsed').textContent=state.elapsed+'s'+(view.estimate||'');
  }catch(error){
    missed+=1;
    if(missed>=3){setTimeout(()=>location.reload(),250);return;}
  }
  setTimeout(tick,500);
}
tick();
</script>
""" % {**THEME, "brand_faces": _BRAND_FACES}


class _BootHandler(BaseHTTPRequestHandler):
    # HTTP/1.1 so a browser gets a Content-Length and does not wait, but
    # never a kept-alive connection. Handing the port over closes the
    # LISTENING socket; a connection already open outlives it, and the
    # boot page went on being answered by a server that no longer owned
    # the port -- measured at 9,711 polls over 302 seconds, reloading
    # itself every twelve milliseconds and never once reaching the canvas.
    # A connection that ends with its answer cannot outlive the handover.
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
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

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

    def __init__(self, host: str, port: int, *, expected: dict[str, float] | None = None) -> None:
        self.progress = BootProgress(expected)
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
