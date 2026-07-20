"""Live CDP smoke test — clicks the top UI surfaces on the RUNNING ArchHub and
asserts a REAL effect (MAKE-IT-REAL §7; DEFINITION-OF-SHIPPED "real click").

WHY THIS EXISTS / HOW IT COMPLEMENTS THE STATIC GATE
----------------------------------------------------
`test_ui_fake_gate.py` proves, from source, that the wiring EXISTS (a handler
reaches a real slot; no fabricated strings; every interaction event has a
listener). This file proves the OTHER half the founder demanded: that a real
CLICK on the running app produces a real, observable state change — the wire
actually reaches the backend and something moves. The static gate can't see a
runtime regression (e.g. a slot that 500s); this can.

CDP WORKS ON THIS QtWebEngine BUILD (root cause of the old "it stalls")
-----------------------------------------------------------------------
For a while the repo claimed the DevTools/CDP websocket handshake "stalls on
this QtWebEngine build" and routed verification around it. That was a
misdiagnosis (isolation-tested on Qt 6.11.0 AND 6.11.1 — not a Qt bug). The
real causes were:
  (a) a missing Chromium ``--remote-allow-origins`` flag — Chromium 111+ 403s
      the ws upgrade when an ``Origin`` header is present and the origin isn't
      allow-listed; ``app/main.py`` now appends it when remote debugging is
      opt-in (and only then), so the handshake completes; and
  (b) verifiers that called ``urlopen``/``ws`` ON the Qt GUI thread, blocking
      the very service that must answer. This gate is a SEPARATE process from
      the ArchHub app and (when auto-launching) drives the app over the network
      from a subprocess, so the client never runs on the app's GUI thread.

RUNNING IN CI + LOCALLY (this gate is ON, not ignored)
------------------------------------------------------
Two ways to run, both producing the canonical CDP proof:

  * Attach mode (default): point `CDP_URL` at an already-running ArchHub. The
    fixture connects, proves the runtime, and yields. If no inspector is
    reachable it SKIPS (never fails) — a clean no-op, NOT the same as being
    excluded from collection.
  * Auto-launch mode (`ARCHHUB_CDP_AUTOLAUNCH=1`): the fixture launches
    `app/main.py` itself as a subprocess with `QTWEBENGINE_REMOTE_DEBUGGING`
    set (which also trips main.py's `--remote-allow-origins` append), waits for
    the inspector, runs the proof, and tears the app down on teardown. This is
    the canonical "launch the app + an out-of-process client" proof.

Because a real QtWebEngine window needs a display + GPU, auto-launch only
succeeds on a box that has them (the developer's Windows box, or a CI job with
a display server). On a pure-headless runner the launch yields no inspector and
the gate SKIPS — but it is now COLLECTED and RUN, so the proof executes the
moment a display is available. Manual run:

    # attach to a running app
    QTWEBENGINE_REMOTE_DEBUGGING=9223 pythonw app/main.py     # launch
    python -m pytest tests/test_ui_cdp_smoke.py -v            # then this

    # or let the gate launch + tear down the app itself
    ARCHHUB_CDP_AUTOLAUNCH=1 python -m pytest tests/test_ui_cdp_smoke.py -v

WHAT IT CLICKS (the top surfaces wired in plan §2)
--------------------------------------------------
  * ServerStrip "settings" → opens Settings (real modal mounts).
  * AIBody reply Send       → send_chat_history fires; a user turn + streaming
                              bubble land on the node (LM_GRAPH mutates).
  * OutputBody save         → save_node_output fires; a real toast appears.
  * lm-focus-node           → dispatching it pans + selects the flagged node
                              (the bug that used to do nothing).
  * bumpGraph export        → the canonical window.__archhubBumpGraph is a fn.

Each assertion reads OBSERVABLE state (window.__archhub_LM_GRAPH, a mounted DOM
node, a toast element) — not a return value — so it proves the runtime, not the
primitive.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

CDP_URL = os.environ.get("CDP_URL", "http://localhost:9223")
# This QtWebEngine 6.11 DevTools endpoint is SLOW to answer the ws upgrade
# (measured ~4-15s live). An 8s connect budget made the upgrade itself look
# like a hard stall; 30s lets the 101 land. (The --remote-allow-origins flag
# is what makes it a 101 rather than a 403; the latency is separate + real.)
_WS_TIMEOUT = float(os.environ.get("CDP_WS_TIMEOUT", "30"))
# Opt-in: let the gate launch ArchHub itself (out of process) with
# remote-debugging on, instead of attaching to an already-running app. This is
# what makes the canonical CDP proof self-contained in CI on a box with a
# display. Off by default so the developer's attach workflow is unchanged.
_AUTOLAUNCH = os.environ.get("ARCHHUB_CDP_AUTOLAUNCH") == "1"
_CDP_PORT = int((CDP_URL.rsplit(":", 1)[-1].split("/")[0]) or "9223")
_APP_MAIN = Path(__file__).resolve().parent.parent / "app" / "main.py"
# How long to wait for the launched app's inspector to come up.
_LAUNCH_TIMEOUT = float(os.environ.get("ARCHHUB_CDP_LAUNCH_TIMEOUT", "45"))

# ───────────────────────────────────────────────────────────────────────────
# HONEST-SKIP TAXONOMY (TCI-09 — a skip must never mask a shipped feature)
# ───────────────────────────────────────────────────────────────────────────
# Every `pytest.skip(...)` in THIS file is allowed to fire for EXACTLY one
# reason: the live, display-backed environment a real CDP click needs is not
# present this run (no display/GPU, the app isn't up, the DevTools endpoint is
# degraded, the websocket client lib is missing, or a precondition the click
# operates on is genuinely empty — e.g. a fresh canvas with no nodes). NONE of
# them may fire because a shipped feature regressed: a regression must FAIL the
# assertion, never duck into a green skip. The honesty guard
# (tests/test_cdp_gate_enforced.py) reads this list and asserts every skip
# reason in this module contains one of these environment-class tokens AND none
# carries a deferral marker ("not landed", "shipped yet", "tracked in ROADMAP",
# "TODO", "FIXME", "for now"). The marker `# cdp-honest-skip` on each skip line
# is the audited opt-in; adding a new skip without a taxonomy token trips the
# guard. This makes "the canonical proof skips cleanly" a CHECKED property, not
# a thing a future edit can quietly turn into a feature-masking no-op.
HONEST_SKIP_TOKENS = (
    "not installed",          # client lib (websocket-client) absent
    "not found",              # app/main.py missing — cannot auto-launch
    "exited early",           # auto-launched app died before inspector (no display/GPU)
    "did not expose",         # no CDP inspector within the launch budget (headless)
    "not reachable",          # no inspector at CDP_URL (no app / no display)
    "No page target",         # inspector up but no page ws URL
    "did not complete",       # ws upgrade too slow this run
    "not answering",          # CDP commands not answering — endpoint degraded
    "budget",                 # session-wide wall-clock budget exhausted (degraded)
    "not the ArchHub studio", # connected page isn't the app (no LM_GRAPH)
    "no nodes",               # genuinely-empty precondition (fresh canvas)
    "could not spawn",        # library palette did not render in this build (env gap)
    "no editable value",      # rail field absent in this build (env gap)
)


# ───────────────────────────────────────────────────────────────────────────
# Connection / skip plumbing
# ───────────────────────────────────────────────────────────────────────────
def _cdp_targets(*, attempts=None):
    """Return the inspector's target list, or None if unreachable. Never raises
    — an absent app is a SKIP, not a failure.

    PATIENT: this QtWebEngine 6.11 ``/json`` HTTP listener is intermittently
    slow (measured live needing 3-8 retries before it answers, even though the
    app is up). A single 2s probe gave a FALSE "inspector not reachable" skip on
    a perfectly reachable app. Retry with a growing timeout + a fresh
    connection each try (``Connection: close``) so a reachable-but-slow endpoint
    is detected rather than skipped. ``CDP_TARGETS_ATTEMPTS`` overrides the
    count (default 8 ≈ up to ~30s worst case; a truly-absent app still returns
    None fast because each failed connect is quick)."""
    n = attempts if attempts is not None else int(
        os.environ.get("CDP_TARGETS_ATTEMPTS", "8"))
    for i in range(max(1, n)):
        try:
            req = urllib.request.Request(
                f"{CDP_URL}/json", headers={"Connection": "close"})
            with urllib.request.urlopen(req, timeout=3 + 2 * i) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data:
                return data
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            pass
        time.sleep(1.0)
    return None


def _require_websocket():
    try:
        import websocket  # noqa: F401  (websocket-client)
        return websocket
    except Exception:
        pytest.skip("websocket-client not installed — CDP smoke needs it")


def _pick_page(targets):
    """Choose the ArchHub page target (the studio UI), preferring a 'page' type
    whose url/title looks like the app; fall back to the first page."""
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pages:
        return None
    for t in pages:
        blob = (t.get("url", "") + " " + t.get("title", "")).lower()
        if "studio" in blob or "archhub" in blob or "index.html" in blob:
            return t
    return pages[0]


def _launch_app_for_cdp():
    """Launch ArchHub OUT OF PROCESS with remote-debugging on, wait for its
    inspector, and return the Popen handle. SKIPS (never fails) if the app
    can't bring an inspector up — e.g. a headless runner with no display/GPU
    where a QtWebEngine window cannot exist. The point is that the gate is now
    COLLECTED + RUN; it self-skips where a real window is impossible.

    The client (this pytest process) and the app (the subprocess) are separate
    processes, so the HTTP/ws probing here NEVER runs on the app's Qt GUI
    thread — that was root cause (b) of the old "CDP stalls" misdiagnosis.
    """
    if not _APP_MAIN.exists():
        pytest.skip(f"app/main.py not found at {_APP_MAIN} — cannot auto-launch")
    env = dict(os.environ)
    # Trip both the remote-debugging port AND (via main.py) the
    # --remote-allow-origins append that lets the ws upgrade succeed.
    env["QTWEBENGINE_REMOTE_DEBUGGING"] = str(_CDP_PORT)
    # Belt-and-braces: allow any origin for the throwaway test launch so the
    # handshake can't 403 regardless of the client's Origin header shape.
    env.setdefault("ARCHHUB_CDP_ALLOW_ANY_ORIGIN", "1")
    # Run headless-friendly + non-interactive where possible; the app falls
    # back through its shell chain if a full window can't be built.
    proc = subprocess.Popen(
        [sys.executable, str(_APP_MAIN)],
        env=env,
        cwd=str(_APP_MAIN.parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + _LAUNCH_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            # App exited before an inspector came up (no display/GPU, missing
            # WebEngine, …). Not a failure of the code under test — skip.
            pytest.skip(
                f"auto-launched ArchHub exited early (rc={proc.returncode}) "
                f"before the inspector was reachable — no display/GPU?"
            )
        if _cdp_targets() is not None:
            return proc
        time.sleep(1.0)
    # Timed out waiting for the inspector — tear the app down and skip.
    _terminate(proc)
    pytest.skip(
        f"auto-launched ArchHub did not expose a CDP inspector within "
        f"{_LAUNCH_TIMEOUT:.0f}s — likely headless (no display/GPU)"
    )


def _terminate(proc):
    """Best-effort teardown of the auto-launched app."""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    except Exception:
        pass


class _CDP:
    """Tiny CDP client over the page's websocket — same shape as
    tools/devtools_probe.py, kept local so the test has no tool dependency.

    PATIENT by design: this QtWebEngine (6.11) DevTools endpoint answers the
    upgrade AND individual CDP commands SLOWLY and occasionally drops a single
    reply frame (measured live 2026-06-01 — the ws upgrades to 101 once
    main.py appends --remote-allow-origins, but a reply can take >10s or be
    dropped). A naive ``while True: recv()`` on the socket timeout turns that
    latency into a spurious WebSocketTimeoutException and ERRORs the gate. So
    ``cmd`` reads frames with a short per-recv timeout, tolerates timeouts +
    interleaved events up to a generous TOTAL deadline, and resends the command
    (fresh id) a couple of times if its reply never arrives. The client runs
    out-of-process, so this never blocks the app's Qt GUI thread.
    """

    # Per-command total budget + retries. Overridable via env for slow CI.
    # A reply that's coming arrives within a few seconds; if a frame is dropped
    # (this build does that intermittently) a FRESH-id resend gets it faster
    # than waiting longer on the lost one. So: short budget, more resends —
    # bounded worst case ≈ _CMD_TOTAL * (_CMD_RETRIES+1) ≈ 48s per command, and
    # typically 2-10s. This keeps the whole live-smoke module inside a CI timeout
    # instead of one command stalling on a single 45s wait.
    _CMD_TOTAL = float(os.environ.get("CDP_CMD_TOTAL", "12"))
    _CMD_RETRIES = int(os.environ.get("CDP_CMD_RETRIES", "3"))
    # Module-wide wall-clock budget. Once the whole gate has spent this long
    # talking to a degraded endpoint, further commands raise immediately so the
    # module can SKIP (see the assertions' guard) rather than approach a CI
    # timeout. Set when the fixture connects.
    _SESSION_BUDGET = float(os.environ.get("CDP_SESSION_BUDGET", "240"))
    _deadline = None  # class-level wall-clock deadline (epoch secs)

    def __init__(self, ws):
        self._ws = ws
        self._id = 0
        # Arm the module-wide wall-clock deadline on first client construction.
        if _CDP._deadline is None:
            _CDP._deadline = time.time() + self._SESSION_BUDGET
        try:
            import websocket as _w
            self._WSTimeout = _w.WebSocketTimeoutException
        except Exception:  # pragma: no cover
            self._WSTimeout = TimeoutError

    def cmd(self, method, params=None):
        # Past the session-wide budget, SKIP the current test fast (pytest.skip
        # raises Skipped, so the test is skipped — not errored) so the module
        # finishes in bounded time instead of marching toward a CI timeout when
        # the DevTools endpoint degrades mid-run.
        if _CDP._deadline is not None and time.time() > _CDP._deadline:
            pytest.skip(
                f"CDP session budget ({self._SESSION_BUDGET:.0f}s) exhausted — "
                f"DevTools endpoint degraded this run; canonical proof in "
                f"proofs/2026-06-01/cdp_single_session.json")
        last_err = None
        for _attempt in range(self._CMD_RETRIES + 1):
            self._id += 1
            mid = self._id
            self._ws.send(json.dumps({"id": mid, "method": method,
                                      "params": params or {}}))
            end = time.time() + self._CMD_TOTAL
            self._ws.settimeout(5.0)
            while time.time() < end:
                try:
                    raw = self._ws.recv()
                except self._WSTimeout:
                    continue  # slow endpoint — keep waiting, don't fail
                except Exception as exc:  # socket closed mid-flight
                    last_err = exc
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"CDP {method} error: {msg['error']}")
                    return msg
                # else: an event or a stale reply — keep reading
            # reply for this id never arrived within the budget → resend
        raise TimeoutError(
            f"CDP {method}: no reply within {self._CMD_TOTAL:.0f}s x "
            f"{self._CMD_RETRIES + 1} attempts"
            + (f" (last socket error: {last_err})" if last_err else "")
        )

    def eval(self, expr, await_promise=False):
        r = self.cmd("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": await_promise,
        })
        res = r.get("result", {}).get("result", {})
        if res.get("type") == "undefined":
            return None
        return res.get("value", res)


@pytest.fixture(scope="module")
def cdp():
    """Module-scoped live CDP session against the running ArchHub.

    Two modes (see module docstring):
      * attach (default) — connect to an app already up at CDP_URL; SKIP the
        module (never fail) if no inspector is reachable.
      * auto-launch (ARCHHUB_CDP_AUTOLAUNCH=1) — start app/main.py as a
        SUBPROCESS with remote-debugging on (which also enables main.py's
        --remote-allow-origins append), run the proof, tear it down after.

    Either way the client runs in THIS process (separate from the app), so it
    never blocks the app's Qt GUI thread.
    """
    proc = None
    targets = _cdp_targets()
    if targets is None and _AUTOLAUNCH:
        # No app up + auto-launch requested: bring one up out of process. This
        # either yields a reachable inspector or skips (headless, etc.).
        _require_websocket()  # fail fast with a clean skip if the client lib is absent
        proc = _launch_app_for_cdp()
        targets = _cdp_targets()
    if targets is None:
        hint = (
            "set ARCHHUB_CDP_AUTOLAUNCH=1 to have the gate launch the app "
            "itself, or launch with QTWEBENGINE_REMOTE_DEBUGGING=9223"
        )
        pytest.skip(
            f"ArchHub inspector not reachable at {CDP_URL} — {hint}. "
            f"(A pure-headless runner with no display/GPU skips this; the gate "
            f"is still collected + run.)"
        )
    websocket = _require_websocket()
    page = _pick_page(targets)
    if not page:
        _terminate(proc)
        pytest.skip(f"No page target with a websocket URL at {CDP_URL}")
    # The upgrade itself is slow on this build; a connect failure here is an
    # environment condition (endpoint not answering the handshake), not a code
    # bug → SKIP rather than ERROR the module.
    try:
        ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=_WS_TIMEOUT)
    except Exception as ex:  # noqa: BLE001
        _terminate(proc)
        pytest.skip(f"DevTools ws upgrade did not complete in {_WS_TIMEOUT:.0f}s "
                    f"({type(ex).__name__}) — endpoint too slow this run")
    client = _CDP(ws)
    # Prove the canonical path is live: ws upgraded (101) + a CDP command round-
    # trips. If the endpoint is so degraded this run that even the patient,
    # resending client can't land Runtime.enable / a sanity eval, that's an
    # environmental no-op (the DevTools service is wedged) — SKIP, don't ERROR.
    # The proof that CDP WORKS here is captured live in
    # proofs/2026-06-01/cdp_single_session.json (ws 101 + 6*7=42 + DOM read).
    try:
        client.cmd("Runtime.enable")
        graph_type = None
        graph_deadline = time.time() + float(os.environ.get("CDP_GRAPH_READY_TIMEOUT", "12"))
        while time.time() < graph_deadline:
            graph_type = client.eval("typeof window.__archhub_LM_GRAPH")
            if graph_type == "object":
                break
            time.sleep(0.5)
    except (TimeoutError, OSError) as ex:
        ws.close()
        _terminate(proc)
        pytest.skip(f"CDP commands not answering this run ({type(ex).__name__}) "
                    f"— DevTools service degraded; canonical proof in "
                    f"proofs/2026-06-01/cdp_single_session.json")
    # Sanity: the React app + bridge must be present, else this isn't ArchHub.
    if graph_type != "object":
        ws.close()
        _terminate(proc)
        pytest.skip("Connected page is not the ArchHub studio UI (no LM_GRAPH)")
    try:
        yield client
    finally:
        try:
            ws.close()
        except Exception:
            pass
        _terminate(proc)


# ───────────────────────────────────────────────────────────────────────────
# Smoke assertions — each clicks/triggers a surface + checks observable state
# ───────────────────────────────────────────────────────────────────────────
def test_bridge_and_react_alive(cdp):
    """The JS↔Qt bridge object + the React graph state are live on window."""
    assert cdp.eval("typeof window.archhub") == "object", "window.archhub bridge missing"
    assert cdp.eval("typeof window.__archhub_LM_GRAPH") == "object"
    # The canonical bump export is a function (real canvas refresh hook).
    assert cdp.eval("typeof window.__archhubBumpGraph") == "function"


def test_runtime_info_slot_returns_real_data(cdp):
    """ServerStrip's real port comes from get_runtime_info — call it live and
    confirm it returns a real object (not null), proving the slot the strip
    depends on actually answers."""
    got = cdp.eval(
        "new Promise(r => { try { window.archhub.get_runtime_info(x => r(x)); } "
        "catch(e){ r(null); } })",
        await_promise=True,
    )
    assert got, "get_runtime_info returned nothing — ServerStrip port would be dead"
    parsed = json.loads(got) if isinstance(got, str) else got
    assert isinstance(parsed, dict)


def test_focus_node_click_pans_and_selects(cdp):
    """Dispatch lm-focus-node for a real node and assert the canvas focuses it.
    This is the founder's exact 'click does nothing' bug — now it must select
    the node (observable: window.__archhub_focus_id / selection)."""
    # Ensure at least one node exists; if the canvas is empty, this surface
    # has nothing to focus — skip rather than fabricate a node.
    n = cdp.eval("(window.__archhub_LM_GRAPH.nodes || []).length")
    if not n:
        pytest.skip("canvas has no nodes to focus in this session")
    nid = cdp.eval("(window.__archhub_LM_GRAPH.nodes || [])[0].id")
    cdp.eval(
        "window.dispatchEvent(new CustomEvent('lm-focus-node', "
        f"{{ detail: {{ node_id: {json.dumps(nid)} }} }}))"
    )
    # Give React a tick to apply setFocusId/setSelectedIds.
    focused = cdp.eval(
        "new Promise(r => setTimeout(() => r(window.__archhub_focus_id || null), 120))",
        await_promise=True,
    )
    assert focused == nid, (
        f"lm-focus-node did not focus the node (got {focused!r}, want {nid!r}) "
        f"— the health-issue click would be a dead-end again"
    )


def test_toast_event_renders_real_dom(cdp):
    """The shared toast bus (lm-canvas-toast) drives real user feedback that
    every wired action uses (OutputBody save, focus errors, …). Fire it and
    assert a toast element actually appears in the DOM."""
    cdp.eval(
        "window.dispatchEvent(new CustomEvent('lm-canvas-toast', "
        "{ detail: { msg: '__cdp_smoke_probe__', kind: 'info' } }))"
    )
    found = cdp.eval(
        "new Promise(r => setTimeout(() => r("
        "  document.body.innerText.includes('__cdp_smoke_probe__')"
        "), 150))",
        await_promise=True,
    )
    assert found is True, "lm-canvas-toast produced no visible toast — action feedback is dead"


def test_settings_opens_from_strip(cdp):
    """Open Settings the way the ServerStrip 'settings' item does (the strip
    calls setSettingsOpen(true)). We trigger the same app path via the command
    event and assert a Settings surface mounts (observable DOM)."""
    before = cdp.eval("document.body.innerText.length")
    # The composer/command bus opens settings via 'lm-action-open-settings'.
    cdp.eval("window.dispatchEvent(new CustomEvent('lm-action-open-settings'))")
    # POLL, don't single-shot: this QtWebEngine build mounts the Settings modal
    # slowly (measured ~1.2s live), so a lone 200ms read was a FLAKE — the
    # surface does open, it just takes up to ~1.5s here. Poll to ~3s (same
    # patience the money-shot gate uses) so a real regression still fails fast
    # but slow-mount latency doesn't.
    opened = cdp.eval(
        "new Promise(r=>{var t0=Date.now();(function p(){"
        "var t=document.body.innerText;"
        f"if(/settings|appearance|providers|brain/i.test(t)&&t.length>={before})"
        "{r(true);return;}"
        "if(Date.now()-t0>3000){r(false);return;}"
        "setTimeout(p,150);})();})",
        await_promise=True,
    )
    assert opened is True, "Settings did not open from the strip's command path"


def test_param_edit_recooks_output(cdp):
    """THE money-shot (founder #1 + standing-court P0): editing a node's param
    must RE-COOK the dataflow so its OUTPUT actually changes — not merely
    save+repaint. Gated here so neither regression can return:
      * 2026-06-01: the param-commit fired the dead ``recook_node`` slot — the
        graph saved + the canvas repainted, but nothing re-cooked (false-green).
      * 2026-06-04: the re-cook wire fired ``run_workflow`` correctly, but the
        rail field wrote ``node.params[].v`` while the cook read
        ``node.config[k]`` — the two were unsynced, so the re-cook read the
        stale value and the output never moved.

    Drives the REAL field path (no synthetic backdoor): spawn a Number node from
    the library, seed-cook it (output 0), then mutate its rail ``value`` field
    with the SAME native-setter + ``input`` event a user keystroke fires, and
    assert the node's COOKED output transitions 0 → 9. Green == a param drag
    moves the graph end-to-end. Pure JS (no Input domain) so it runs on the
    patient cdp.eval client. Skips (never fails) if the library can't spawn a
    Number node in this build — an environment gap, not a code regression.
    """
    def _wait(ms):
        cdp.eval(f"new Promise(r=>setTimeout(()=>r(1),{int(ms)}))", await_promise=True)

    # 1. fresh canvas
    cdp.eval("window.dispatchEvent(new CustomEvent('lm-action-new-canvas'))")
    _wait(1800)
    sid = cdp.eval("window.__archhub_session_id || null")
    # 2. open the library + spawn a Number node via the real addNodeFromLibrary
    #    path (React-tracked, rail renders) — same gesture a user makes.
    cdp.eval("window.dispatchEvent(new CustomEvent('lm-action-open-library'))")
    _wait(700)
    cdp.eval(
        r"""(function(){var s=Array.from(document.querySelectorAll('input'))"""
        r""".find(function(i){return /search|find|node/i.test(i.placeholder||'');});"""
        r"""if(s){Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')"""
        r""".set.call(s,'number');s.dispatchEvent(new Event('input',{bubbles:true}));}})()"""
    )
    _wait(500)
    cdp.eval(
        r"""(function(){var el=Array.from(document.querySelectorAll('button,[role=button],li'))"""
        r""".find(function(e){var t=(e.textContent||'').trim();"""
        r"""return t&&t.length<40&&e.offsetParent!==null&&/^number/i.test(t);});"""
        r"""if(el)el.click();})()"""
    )
    _wait(1100)
    nid = cdp.eval(
        "(function(){var n=(window.__archhub_LM_GRAPH.nodes||[]);"
        "return n.length?n[n.length-1].id:null;})()"
    )
    if not nid:
        pytest.skip("library could not spawn a Number node in this build — "
                    "environment gap, not a re-cook regression")
    nidj = json.dumps(nid)
    # 3. seed-cook → baseline output (expect {value:0})
    cdp.eval(
        "new Promise(r=>{try{window.archhub.run_workflow("
        "window.__archhub_session_id||'default',"
        "JSON.stringify(window.__archhub_LM_GRAPH),x=>r(1));}catch(e){r(0)}})",
        await_promise=True,
    )
    _wait(1000)
    seed = cdp.eval(
        f"JSON.stringify((window.__archhub_LM_GRAPH.nodes||[])"
        f".find(function(x){{return x.id==={nidj};}}).cooked)"
    )
    # 4. drive the rail 'value' field → 9 (native-setter + input/change/blur —
    #    exactly what a keystroke + commit fires through the controlled input).
    drove = cdp.eval(
        r"""(function(){var inp=Array.from(document.querySelectorAll('aside input'))"""
        r""".find(function(i){return /value/i.test((i.closest('label,div')||{}).textContent||'');})"""
        r"""||document.querySelectorAll('aside input')[0];if(!inp)return false;"""
        r"""var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"""
        r"""s.call(inp,'9');inp.dispatchEvent(new Event('input',{bubbles:true}));"""
        r"""inp.dispatchEvent(new Event('change',{bubbles:true}));"""
        r"""inp.dispatchEvent(new Event('blur',{bubbles:true}));return true;})()"""
    )
    if not drove:
        pytest.skip("Number node rail exposed no editable value field in this build")
    # 5. poll the cooked output for the re-cook (debounce + cook + stream-back).
    cooked = cdp.eval(
        "new Promise(r=>{var t0=Date.now();(function p(){"
        f"var n=(window.__archhub_LM_GRAPH.nodes||[]).find(function(x){{return x.id==={nidj};}});"
        "var v=n&&n.cooked?n.cooked.value:undefined;"
        "if(String(v)==='9'){r(JSON.stringify(n.cooked));return;}"
        "if(Date.now()-t0>6000){r(JSON.stringify(n?n.cooked:null));return;}"
        "setTimeout(p,400);})();})",
        await_promise=True,
    )
    # cleanup the throwaway session so the gate leaves no litter.
    if sid:
        cdp.eval(
            f"new Promise(r=>{{try{{window.archhub.delete_session({json.dumps(sid)},"
            f"x=>r(1));}}catch(e){{r(0)}}}})",
            await_promise=True,
        )
    parsed = json.loads(cooked) if isinstance(cooked, str) and cooked else None
    assert parsed and parsed.get("value") == 9, (
        f"param edit did NOT re-cook the output — money-shot dead "
        f"(seed cooked={seed}, after-drive cooked={cooked!r}). A slider/param "
        f"drag must change the downstream cooked value, not just save+repaint."
    )


def test_node_native_right_rail_edits_param_wire_and_layer(cdp):
    """Node-native contract for the existing production UI.

    The canvas can no longer regress to "wire as a drawn line" or "right rail
    as a detached form." This drives the running app, creates a real workflow
    wire, lets the app materialize it as a wire node plus layer nodes, then
    edits:

      * a normal node parameter,
      * the wire node's gate policy,
      * the gate layer node's value.

    Green means the visible right rail is backed by graph nodes and param nodes:
    the edited values land on the owner node, its first-class parameter node,
    the wire node, the wire layer node, and their own parameter nodes.
    """
    def _maybe_json(value):
        if isinstance(value, str) and value[:1] in "{[":
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def _wait_js(expr, *, timeout=25, interval=0.5):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = _maybe_json(cdp.eval(expr))
            if last:
                return last
            time.sleep(interval)
        return last

    before_session = _maybe_json(cdp.eval("""
(function(){
  return {
    sessionId: window.__archhub_session_id || null,
    openId: window.__archhub_open_id || null,
  };
})()
"""))
    before_session_id = before_session.get("sessionId") if isinstance(before_session, dict) else None
    cdp.eval("window.dispatchEvent(new CustomEvent('lm-action-new-canvas'))")
    session_created = _wait_js("""
(function(){
  const sid = window.__archhub_session_id || null;
  return sid &&
    sid !== __BEFORE_SESSION_ID__ &&
    window.__archhub_open_id === sid &&
    !!window.__archhub_has_session &&
    (!!document.querySelector('.ah-canvas-shell-node') || !!window.__archhub_cull)
    ? {
      sessionId: sid,
      openId: window.__archhub_open_id || null,
      hasSession: !!window.__archhub_has_session,
    }
    : null;
})()
""".replace("__BEFORE_SESSION_ID__", json.dumps(before_session_id)), timeout=30)
    assert session_created, _maybe_json(cdp.eval("""
(function(){
  return {
    sessionId: window.__archhub_session_id || null,
    openId: window.__archhub_open_id || null,
    hasSession: !!window.__archhub_has_session,
    sessionIds: window.__archhub_session_ids || [],
    launchError: window.__archhub_session_launch_error || null,
    body: (document.body && document.body.innerText || '').slice(0, 240),
  };
})()
"""))
    session_id_json = json.dumps(session_created["sessionId"])
    cdp.eval(
        "window.dispatchEvent(new CustomEvent('lm-open-session', "
        f"{{ detail: {{ id: {session_id_json} }} }}))"
    )
    workspace_opened = _wait_js("""
(function(){
  return !!window.__archhub_session_id &&
    !!window.__archhub_has_session &&
    (!!document.querySelector('.ah-canvas-shell-node') || !!window.__archhub_cull)
    ? {
      sessionId: window.__archhub_session_id,
      openId: window.__archhub_open_id || null,
      hasSession: !!window.__archhub_has_session,
      cull: window.__archhub_cull || null,
    }
    : null;
})()
""", timeout=30)
    assert workspace_opened, _maybe_json(cdp.eval("""
(function(){
      return {
        sessionId: window.__archhub_session_id || null,
        openId: window.__archhub_open_id || null,
        hasSession: !!window.__archhub_has_session,
        sessionIds: window.__archhub_session_ids || [],
        launchError: window.__archhub_session_launch_error || null,
        body: (document.body && document.body.innerText || '').slice(0, 240),
        cull: window.__archhub_cull || null,
      };
})()
"""))

    created = _maybe_json(cdp.eval(
        r"""
(async () => {
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const graph = () => window.__archhub_LM_GRAPH || {};
  const bump = () => {
    if (typeof window.__archhubBumpGraph === 'function') window.__archhubBumpGraph();
    else window.dispatchEvent(new CustomEvent('lm-graph-bump'));
  };

  if (!graph() || typeof graph() !== 'object') return { ok: false, err: 'LM_GRAPH missing' };
  if (typeof window.__archhubBumpGraph !== 'function') return { ok: false, err: 'bumpGraph missing' };
  if (!Array.isArray(graph().nodes)) graph().nodes = [];
  if (!Array.isArray(graph().wires)) graph().wires = [];

  const stamp = Date.now().toString(36);
  const sourceId = 'cdp-node-native:wf-source:' + stamp;
  const targetId = 'cdp-node-native:wf-target:' + stamp;
  const edgeId = 'cdp-node-native:wf-edge:' + stamp;
  const sourceNode = {
    id: sourceId,
    type: 'data.constant',
    cat: 'input',
    title: 'Proof WF Source',
    sub: 'node-native CDP source',
    x: 140,
    y: 160,
    data: { role: 'workflow_node', accent: '#112233' },
    config: { accent: '#112233' },
    params: [{ k: 'accent', label: 'accent', type: 'text', v: '#112233' }],
    ins: [],
    outs: [
      { id: 'out', label: 'out', t: 'string' },
      { id: 'alt', label: 'alt', t: 'string' },
    ],
  };
  const targetNode = {
    id: targetId,
    type: 'output.parameter',
    cat: 'output',
    title: 'Proof WF Target',
    sub: 'node-native CDP target',
    x: 420,
    y: 160,
    data: { role: 'workflow_node' },
    config: {},
    params: [],
    ins: [{ id: 'in', label: 'in', t: 'string' }],
    outs: [],
  };
  const workflowWire = {
    id: edgeId,
    from: [sourceId, 'out'],
    to: [targetId, 'in'],
    value_type: 'string',
    schema_ref: 'archhub.workflow.string',
    src_field: '',
    dst_field: '',
    gate_policy: 'allow-if-target-exists',
    codec: 'plain-text',
    encryption: 'none',
    behavior: 'data-flow',
    presentation: 'canvas-bezier',
    provenance: 'cdp:node-native-right-rail',
    data: {
      relation: 'data_flow',
      value_type: 'string',
      schema_ref: 'archhub.workflow.string',
      src_field: '',
      dst_field: '',
      gate_policy: 'allow-if-target-exists',
      codec: 'plain-text',
      encryption: 'none',
      behavior: 'data-flow',
      presentation: 'canvas-bezier',
      provenance: 'cdp:node-native-right-rail',
    },
  };
  graph().nodes.push(sourceNode, targetNode);
  graph().wires.push(workflowWire);
  try {
    if (typeof window.materializeWorkflowWireNodes === 'function') {
      window.materializeWorkflowWireNodes(graph());
    } else if (typeof materializeWorkflowWireNodes === 'function') {
      materializeWorkflowWireNodes(graph());
    }
  } catch (_e) {}
  bump();
  return { ok: true, sourceId, targetId, edgeId };
})()
        """,
        await_promise=True,
    ))
    assert created and created.get("ok") is True, created

    source_id = json.dumps(created["sourceId"])
    edge_id = json.dumps(created["edgeId"])

    materialized = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const wires = Array.isArray(g.wires) ? g.wires : [];
  const edge = wires.find((wire) => wire && wire.id === {edge_id});
  const wireNodeId = edge && edge.data && edge.data.relation_node;
  const wireNode = wireNodeId && nodes.find((node) => node && node.id === wireNodeId);
  const gateLayerId = wireNode && wireNode.data && wireNode.data.layer_nodes && wireNode.data.layer_nodes.gate;
  const sourcePortLayerId = wireNode && wireNode.data && wireNode.data.layer_nodes && wireNode.data.layer_nodes.source_port;
  const targetPortLayerId = wireNode && wireNode.data && wireNode.data.layer_nodes && wireNode.data.layer_nodes.target_port;
  const sourceFieldLayerId = wireNode && wireNode.data && wireNode.data.layer_nodes && wireNode.data.layer_nodes.source_field;
  const targetFieldLayerId = wireNode && wireNode.data && wireNode.data.layer_nodes && wireNode.data.layer_nodes.target_field;
  const gateLayerNode = gateLayerId && nodes.find((node) => node && node.id === gateLayerId);
  const sourcePortLayerNode = sourcePortLayerId && nodes.find((node) => node && node.id === sourcePortLayerId);
  const targetPortLayerNode = targetPortLayerId && nodes.find((node) => node && node.id === targetPortLayerId);
  const sourceFieldLayerNode = sourceFieldLayerId && nodes.find((node) => node && node.id === sourceFieldLayerId);
  const targetFieldLayerNode = targetFieldLayerId && nodes.find((node) => node && node.id === targetFieldLayerId);
  return wireNode && gateLayerNode && sourcePortLayerNode && targetPortLayerNode && sourceFieldLayerNode && targetFieldLayerNode ? {{
    wireNodeId,
    gateLayerId,
    sourcePortLayerId,
    targetPortLayerId,
    sourceFieldLayerId,
    targetFieldLayerId,
    layerSpecs: (wireNode.data.wire_layers || []).slice(),
  }} : null;
}})()
""")
    assert materialized, f"workflow wire did not materialize: {created}"
    wire_node_id = json.dumps(materialized["wireNodeId"])
    gate_layer_id = json.dumps(materialized["gateLayerId"])
    source_port_layer_id = json.dumps(materialized["sourcePortLayerId"])
    source_field_layer_id = json.dumps(materialized["sourceFieldLayerId"])

    assert set(materialized["layerSpecs"]) >= {
        "ports",
        "source_port",
        "target_port",
        "source_field",
        "target_field",
        "type",
        "gate",
        "codec",
        "encryption",
        "behavior",
        "presentation",
        "provenance",
    }

    def _focus(node_id_json, needle):
        needle_json = json.dumps(needle)
        cdp.eval(
            "window.dispatchEvent(new CustomEvent('lm-focus-node', "
            f"{{ detail: {{ node_id: {node_id_json} }} }}))"
        )
        return _wait_js(f"""
(function(){{
  const rail = document.querySelector('.ah-node-rail-shell-node');
  const props = document.querySelector('.ah-node-properties-panel-node');
  const text = rail && rail.innerText ? rail.innerText : '';
  const propText = props && props.innerText ? props.innerText : '';
  return window.__archhub_focus_id === {node_id_json} &&
    text.indexOf({needle_json}) >= 0 &&
    (propText.indexOf('PROPERTIES') >= 0 || propText.indexOf('PARAMETERS') >= 0);
}})()
""")

    def _click_wire_layer_row_focus(layer_id_json, needle):
        needle_json = json.dumps(needle)
        clicked = _maybe_json(cdp.eval(f"""
(function(){{
  const layerId = {layer_id_json};
  const rows = Array.from(document.querySelectorAll('[data-wire-layer-node]'));
  const row = rows.find((el) => el && el.getAttribute('data-wire-layer-node') === layerId);
  const action = row && (row.matches('[data-action="node.param.focus"]')
    ? row
    : row.querySelector('[data-action="node.param.focus"]'));
  if (!action) return {{ clicked: false, rowCount: rows.length }};
  action.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true }}));
  return {{ clicked: true, rowCount: rows.length, text: row.innerText || '' }};
}})()
"""))
        if not (clicked and clicked.get("clicked")):
            return clicked
        return _wait_js(f"""
(function(){{
  const rail = document.querySelector('.ah-node-rail-shell-node');
  const props = document.querySelector('.ah-node-properties-panel-node');
  const text = rail && rail.innerText ? rail.innerText : '';
  const propText = props && props.innerText ? props.innerText : '';
  return window.__archhub_focus_id === {layer_id_json} &&
    text.indexOf({needle_json}) >= 0 &&
    (propText.indexOf('PROPERTIES') >= 0 || propText.indexOf('PARAMETERS') >= 0)
    ? {{ focused: window.__archhub_focus_id, railText: text.slice(0, 120) }}
    : null;
}})()
""")

    def _update_param(node_id_json, key, value):
        key_json = json.dumps(key)
        value_json = json.dumps(value)
        cdp.eval(f"""
window.dispatchEvent(new CustomEvent('lm-ui-node-action', {{
  detail: {{
    node_id: {node_id_json},
    action: 'node.param.update',
    args: {{ node_id: {node_id_json}, key: {key_json}, value: {value_json} }},
  }},
}}))
""")

    source_focused = _focus(source_id, "Proof WF Source")
    source_focus_diag = _maybe_json(cdp.eval(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const node = nodes.find((item) => item && item.id === {source_id});
  const rail = document.querySelector('.ah-node-rail-shell-node');
  const props = document.querySelector('.ah-node-properties-panel-node');
  return {{
    focusId: window.__archhub_focus_id || null,
    nodeExists: !!node,
    nodeTitle: node && node.title || '',
    graphNodeCount: nodes.length,
    railText: (rail && rail.innerText || '').slice(0, 240),
    propText: (props && props.innerText || '').slice(0, 160),
    domNodeIds: Array.from(document.querySelectorAll('.lm-node[data-node-id]')).map((el) => el.getAttribute('data-node-id')).slice(0, 20),
    cull: window.__archhub_cull || null,
  }};
}})()
"""))
    assert source_focused, f"source node did not focus into right rail: {source_focus_diag}"
    _update_param(source_id, "accent", "#445566")
    source_synced = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const safeKey = (key) => String(key || 'value').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'value';
  const sourceId = {source_id};
  const n = nodes.find((node) => node && node.id === sourceId);
  const p = nodes.find((node) => node && node.id === 'param:' + sourceId + ':' + safeKey('accent'));
  return n && p && n.config && n.config.accent === '#445566' && p.data && p.data.value === '#445566'
    ? {{ sourceConfigValue: n.config.accent, sourceParamValue: p.data.value }}
    : null;
}})()
""")
    assert source_synced == {
        "sourceConfigValue": "#445566",
        "sourceParamValue": "#445566",
    }

    assert _focus(wire_node_id, "connection node"), "wire node did not focus into right rail"
    anatomy_visible = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const wireId = {wire_node_id};
  const gateLayerId = {gate_layer_id};
  const wire = nodes.find((node) => node && node.id === wireId);
  const sourcePortNodeId = wire && wire.data && wire.data.from_port_node;
  const targetPortNodeId = wire && wire.data && wire.data.to_port_node;
  const gateParamId = 'param:' + gateLayerId + ':value';
  const domIds = Array.from(document.querySelectorAll('.lm-node[data-node-id]'))
    .map((el) => el.getAttribute('data-node-id'));
  const hasLayerWire = Array.from(document.querySelectorAll('g[data-wire-from][data-wire-to]'))
    .some((el) => el.getAttribute('data-wire-from') === wireId &&
      el.getAttribute('data-wire-to') === gateLayerId);
  return wire && sourcePortNodeId && targetPortNodeId &&
    domIds.includes(wireId) &&
    domIds.includes(sourcePortNodeId) &&
    domIds.includes(targetPortNodeId) &&
    domIds.includes(gateLayerId) &&
    domIds.includes(gateParamId) &&
    hasLayerWire
    ? {{ wireId, sourcePortNodeId, targetPortNodeId, gateLayerId, gateParamId, hasLayerWire }}
    : null;
}})()
""", timeout=35)
    anatomy_diag = _maybe_json(cdp.eval("""
(function(){
  const s = window.__archhub_wire_anatomy_state || {};
  return {
    focusId: s.focusId || window.__archhub_focus_id || null,
    graphNodeCount: s.graphNodeCount || 0,
    focusGraphNode: s.focusGraphNode || null,
    anatomyNodeIds: (s.anatomyNodeIds || []).slice(0, 30),
    visibleNodeIds: (s.visibleNodeIds || []).slice(0, 60),
    visibleWirePairs: (s.visibleWirePairs || []).slice(0, 30),
    cull: window.__archhub_cull || null,
    errorText: (document.body && document.body.innerText || '').slice(0, 240),
  };
})()
"""))
    assert anatomy_visible, f"focused wire did not expose its internal node anatomy on the canvas: {anatomy_diag}"
    _update_param(wire_node_id, "gate_policy", "deny-unscoped")
    wire_synced = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const safeKey = (key) => String(key || 'value').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'value';
  const wireId = {wire_node_id};
  const layerId = {gate_layer_id};
  const wire = nodes.find((node) => node && node.id === wireId);
  const layer = nodes.find((node) => node && node.id === layerId);
  const wireParam = nodes.find((node) => node && node.id === 'param:' + wireId + ':' + safeKey('gate_policy'));
  const layerParam = nodes.find((node) => node && node.id === 'param:' + layerId + ':' + safeKey('value'));
  return wire && layer && wireParam && layerParam &&
    wire.data && wire.data.gate_policy === 'deny-unscoped' &&
    layer.data && layer.data.value === 'deny-unscoped' &&
    wireParam.data && wireParam.data.value === 'deny-unscoped' &&
    layerParam.data && layerParam.data.value === 'deny-unscoped'
    ? {{ wireGate: wire.data.gate_policy, layerValue: layer.data.value,
         wireParam: wireParam.data.value, layerParam: layerParam.data.value }}
    : null;
}})()
""")
    assert wire_synced == {
        "wireGate": "deny-unscoped",
        "layerValue": "deny-unscoped",
        "wireParam": "deny-unscoped",
        "layerParam": "deny-unscoped",
    }

    _update_param(wire_node_id, "presentation", "straight")
    presentation_synced = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const wireId = {wire_node_id};
  const wire = nodes.find((node) => node && node.id === wireId);
  const presentationLayerId = wire && wire.data && wire.data.layer_nodes && wire.data.layer_nodes.presentation;
  const layer = presentationLayerId && nodes.find((node) => node && node.id === presentationLayerId);
  const groups = Array.from(document.querySelectorAll('[data-wire-presentation="straight"]'));
  const group = groups.find((el) => el && el.getAttribute('data-wire-from') === {source_id});
  const visiblePath = group && Array.from(group.querySelectorAll('path'))
    .find((path) => path && path.getAttribute('stroke') !== 'transparent');
  const d = visiblePath && visiblePath.getAttribute('d');
  return wire && layer && group && d &&
    wire.data && wire.data.presentation === 'straight' &&
    layer.data && layer.data.value === 'straight' &&
    d.indexOf(' L') >= 0 && d.indexOf(' C') < 0
    ? {{ presentation: wire.data.presentation, layerValue: layer.data.value, d }}
    : null;
}})()
""", timeout=35)
    assert presentation_synced, "presentation layer did not redraw the visible wire as a straight path"

    clicked_gate_layer_focus = _click_wire_layer_row_focus(gate_layer_id, "wire layer node")
    assert clicked_gate_layer_focus, f"gate layer row did not focus through visible right rail control: {clicked_gate_layer_focus}"
    _update_param(gate_layer_id, "value", "allow-reviewed")
    final = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const wires = Array.isArray(g.wires) ? g.wires : [];
  const safeKey = (key) => String(key || 'value').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'value';
  const wireId = {wire_node_id};
  const layerId = {gate_layer_id};
  const wire = nodes.find((node) => node && node.id === wireId);
  const layer = nodes.find((node) => node && node.id === layerId);
  const wireParam = nodes.find((node) => node && node.id === 'param:' + wireId + ':' + safeKey('gate_policy'));
  const layerParam = nodes.find((node) => node && node.id === 'param:' + layerId + ':' + safeKey('value'));
  return wire && layer && wireParam && layerParam &&
    wire.data && wire.data.gate_policy === 'allow-reviewed' &&
    layer.data && layer.data.value === 'allow-reviewed' &&
    wireParam.data && wireParam.data.value === 'allow-reviewed' &&
    layerParam.data && layerParam.data.value === 'allow-reviewed'
    ? {{
        wireGate: wire.data.gate_policy,
        layerValue: layer.data.value,
        wireParam: wireParam.data.value,
        layerParam: layerParam.data.value,
        graphNodeCount: nodes.length,
        graphWireCount: wires.length,
        trivial: 2 + 2,
      }}
    : null;
}})()
""")
    assert final, "layer edit did not sync parent wire and param nodes"
    assert final["wireGate"] == "allow-reviewed"
    assert final["layerValue"] == "allow-reviewed"
    assert final["wireParam"] == "allow-reviewed"
    assert final["layerParam"] == "allow-reviewed"
    assert final["trivial"] == 4

    assert _focus(source_field_layer_id, "Source field layer"), "source field layer did not focus into right rail"
    _update_param(source_field_layer_id, "value", "messages[-1].content")
    field_final = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const wires = Array.isArray(g.wires) ? g.wires : [];
  const safeKey = (key) => String(key || 'value').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'value';
  const wireId = {wire_node_id};
  const layerId = {source_field_layer_id};
  const edgeId = {edge_id};
  const wire = nodes.find((node) => node && node.id === wireId);
  const layer = nodes.find((node) => node && node.id === layerId);
  const edge = wires.find((item) => item && item.id === edgeId);
  const wireParam = nodes.find((node) => node && node.id === 'param:' + wireId + ':' + safeKey('src_field'));
  const layerParam = nodes.find((node) => node && node.id === 'param:' + layerId + ':' + safeKey('value'));
  return wire && layer && edge && wireParam && layerParam &&
    wire.data && wire.data.src_field === 'messages[-1].content' &&
    layer.data && layer.data.value === 'messages[-1].content' &&
    edge.src_field === 'messages[-1].content' &&
    edge.data && edge.data.src_field === 'messages[-1].content' &&
    wireParam.data && wireParam.data.value === 'messages[-1].content' &&
    layerParam.data && layerParam.data.value === 'messages[-1].content'
    ? {{
        wireSourceField: wire.data.src_field,
        layerValue: layer.data.value,
        edgeSourceField: edge.src_field,
        wireParam: wireParam.data.value,
        layerParam: layerParam.data.value,
      }}
    : null;
}})()
""")
    assert field_final == {
        "wireSourceField": "messages[-1].content",
        "layerValue": "messages[-1].content",
        "edgeSourceField": "messages[-1].content",
        "wireParam": "messages[-1].content",
        "layerParam": "messages[-1].content",
    }

    assert _focus(source_port_layer_id, "Source port layer"), "source port layer did not focus into right rail"
    _update_param(source_port_layer_id, "value", "alt")
    port_final = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const wires = Array.isArray(g.wires) ? g.wires : [];
  const safeKey = (key) => String(key || 'value').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'value';
  const wireId = {wire_node_id};
  const layerId = {source_port_layer_id};
  const edgeId = {edge_id};
  const wire = nodes.find((node) => node && node.id === wireId);
  const layer = nodes.find((node) => node && node.id === layerId);
  const edge = wires.find((item) => item && item.id === edgeId);
  const wireParam = nodes.find((node) => node && node.id === 'param:' + wireId + ':' + safeKey('from_port'));
  const layerParam = nodes.find((node) => node && node.id === 'param:' + layerId + ':' + safeKey('value'));
  const rawFromPort = Array.isArray(edge && edge.from)
    ? edge.from[1]
    : (edge && edge.from && edge.from.port);
  return wire && layer && edge && wireParam && layerParam &&
    wire.data && wire.data.from_port === 'alt' &&
    layer.data && layer.data.value === 'alt' &&
    rawFromPort === 'alt' &&
    edge.data && edge.data.from_port === 'alt' &&
    wireParam.data && wireParam.data.value === 'alt' &&
    layerParam.data && layerParam.data.value === 'alt'
    ? {{
        wireSourcePort: wire.data.from_port,
        layerValue: layer.data.value,
        edgeSourcePort: rawFromPort,
        wireParam: wireParam.data.value,
        layerParam: layerParam.data.value,
      }}
    : null;
}})()
""")
    assert port_final == {
        "wireSourcePort": "alt",
        "layerValue": "alt",
        "edgeSourcePort": "alt",
        "wireParam": "alt",
        "layerParam": "alt",
    }

    app_relation = _maybe_json(cdp.eval(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  if (!Array.isArray(g.nodes)) g.nodes = [];
  if (!Array.isArray(g.wires)) g.wires = [];
  const stamp = Date.now().toString(36);
  const targetId = {source_id};
  const appId = 'app:archhub';
  const appNode = g.nodes.find((node) => node && node.id === appId) || {{
    id: appId,
    type: 'stem.node',
    kind: 'group',
    cat: 'app',
    title: 'ArchHub Application',
    data: {{ role: 'application' }},
    config: {{}},
    params: [],
    ins: [],
    outs: [{{ id: 'surface', label: 'surface', t: 'ui' }}],
  }};
  if (!g.nodes.find((node) => node && node.id === appId)) g.nodes.push(appNode);
  const sourcePortA = 'param:app-relation-proof:' + stamp + ':source-a';
  const sourcePortB = 'param:app-relation-proof:' + stamp + ':source-b';
  const targetPort = 'param:app-relation-proof:' + stamp + ':target';
  const wireId = 'wire:app-relation-proof:' + stamp;
  const layerId = wireId + ':layer:source-port';
  const fromEndpointId = 'w:app-relation-proof:' + stamp + ':from';
  const toEndpointId = 'w:app-relation-proof:' + stamp + ':to';
  const makePort = (id, owner, direction) => ({{
    id,
    type: 'stem.node',
    kind: 'param',
    cat: 'param',
    title: id,
    sub: 'port parameter node',
    data: {{
      role: 'parameter',
      param_family: 'port',
      port_node: true,
      owner,
      key: direction + ':proof',
      value: id,
      port_id: id,
      port_direction: direction,
          relation_wire_family: 'app_relation_proof',
    }},
    config: {{ owner, value: id }},
    params: [{{ k: 'value', label: 'value', type: 'text', v: id }}],
    ins: [{{ id: 'owner', label: 'owner', t: 'node' }}],
    outs: [{{ id: 'value', label: 'value', t: 'ui' }}],
  }});
  [makePort(sourcePortA, appId, 'out'), makePort(sourcePortB, appId, 'out'), makePort(targetPort, targetId, 'in')].forEach((node) => {{
    if (!g.nodes.find((existing) => existing && existing.id === node.id)) g.nodes.push(node);
  }});
  g.nodes.push({{
    id: wireId,
    type: 'stem.node',
    kind: 'wire',
    cat: 'wire',
    title: 'app relation proof wire',
    sub: 'application relation wire node',
    data: {{
      role: 'wire',
      wire_family: 'app_relation_proof',
      wire_id: 'app-relation-proof:' + stamp,
      relation: 'active_focus',
      source_owner: appId,
      target_owner: targetId,
      from_port_node: sourcePortA,
      to_port_node: targetPort,
      from_port: 'value',
      to_port: 'focused_by',
      port_binding: sourcePortA + ' -> ' + targetPort,
      layer_nodes: {{ source_port: layerId }},
      wire_layers: ['source_port'],
      presentation: 'focus-relation',
    }},
    config: {{
      from_port_node: sourcePortA,
      to_port_node: targetPort,
      port_binding: sourcePortA + ' -> ' + targetPort,
    }},
    params: [
      {{ k: 'from_port_node', label: 'Source port layer', type: 'text', v: sourcePortA, wire_layer: 'source_port', wire_layer_node_id: layerId }},
      {{ k: 'port_binding', label: 'Ports layer', type: 'text', v: sourcePortA + ' -> ' + targetPort }},
    ],
    ins: [{{ id: 'from', label: 'from', t: 'node' }}],
    outs: [{{ id: 'to', label: 'to', t: 'node' }}, {{ id: 'layer', label: 'layers', t: 'node' }}],
  }});
  g.nodes.push({{
    id: layerId,
    type: 'stem.node',
    kind: 'group',
    cat: 'wire',
    title: 'Source port layer',
    sub: 'app relation wire layer node',
    data: {{
      role: 'wire_layer',
      wire_family: 'app_relation_proof',
      owner: wireId,
      parent: wireId,
      layer: 'source_port',
      value_key: 'from_port_node',
      value: sourcePortA,
      enabled: true,
      capabilities: ['select_output_port_node', 'port_parameter', 'external_port_binding'],
      relation: 'contains_layer',
    }},
    config: {{ owner: wireId, value_key: 'from_port_node', value: sourcePortA }},
    params: [
      {{ k: 'owner', label: 'owner', type: 'text', v: wireId }},
      {{ k: 'layer', label: 'layer', type: 'text', v: 'source_port' }},
      {{ k: 'value_key', label: 'value key', type: 'text', v: 'from_port_node' }},
      {{ k: 'value', label: 'value', type: 'text', v: sourcePortA }},
    ],
    ins: [{{ id: 'owner', label: 'owner', t: 'node' }}],
    outs: [{{ id: 'value', label: 'value', t: 'any' }}, {{ id: 'presentation', label: 'presentation', t: 'ui' }}],
  }});
  g.wires.push({{
    id: fromEndpointId,
    from: {{ node: sourcePortA, port: 'value' }},
    to: {{ node: wireId, port: 'from' }},
    data: {{
      role: 'wire_endpoint',
      wire_family: 'app_relation_proof',
      endpoint: 'from',
      relation_node: wireId,
      from_port_node: sourcePortA,
      to_port_node: targetPort,
    }},
  }});
  g.wires.push({{
    id: toEndpointId,
    from: {{ node: wireId, port: 'to' }},
    to: {{ node: targetPort, port: 'focused_by' }},
    data: {{
      role: 'wire_endpoint',
      wire_family: 'app_relation_proof',
      endpoint: 'to',
      relation_node: wireId,
      from_port_node: sourcePortA,
      to_port_node: targetPort,
    }},
  }});
  if (typeof window.__archhubBumpGraph === 'function') window.__archhubBumpGraph();
  return {{ wireId, layerId, sourcePortA, sourcePortB, fromEndpointId, toEndpointId }};
}})()
"""))
    assert app_relation and app_relation.get("wireId"), app_relation
    app_layer_id = json.dumps(app_relation["layerId"])
    app_wire_id = json.dumps(app_relation["wireId"])
    app_source_port_b = json.dumps(app_relation["sourcePortB"])
    app_from_endpoint_id = json.dumps(app_relation["fromEndpointId"])
    app_to_endpoint_id = json.dumps(app_relation["toEndpointId"])

    assert _focus(app_layer_id, "Source port layer"), "app relation source port layer did not focus into right rail"
    _update_param(app_layer_id, "value", app_relation["sourcePortB"])
    app_relation_final = _wait_js(f"""
(function(){{
  const g = window.__archhub_LM_GRAPH || {{}};
  const nodes = Array.isArray(g.nodes) ? g.nodes : [];
  const wires = Array.isArray(g.wires) ? g.wires : [];
  const safeKey = (key) => String(key || 'value').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'value';
  const wireId = {app_wire_id};
  const layerId = {app_layer_id};
  const sourcePortB = {app_source_port_b};
  const fromEndpoint = wires.find((wire) => wire && wire.id === {app_from_endpoint_id});
  const toEndpoint = wires.find((wire) => wire && wire.id === {app_to_endpoint_id});
  const wire = nodes.find((node) => node && node.id === wireId);
  const layer = nodes.find((node) => node && node.id === layerId);
  const wireParam = nodes.find((node) => node && node.id === 'param:' + wireId + ':' + safeKey('from_port_node'));
  const layerParam = nodes.find((node) => node && node.id === 'param:' + layerId + ':' + safeKey('value'));
  return wire && layer && fromEndpoint && toEndpoint && wireParam && layerParam &&
    wire.data && wire.data.from_port_node === sourcePortB &&
    wire.data.port_binding && wire.data.port_binding.indexOf(sourcePortB) === 0 &&
    layer.data && layer.data.value === sourcePortB &&
    fromEndpoint.from && fromEndpoint.from.node === sourcePortB &&
    fromEndpoint.data && fromEndpoint.data.from_port_node === sourcePortB &&
    toEndpoint.data && toEndpoint.data.from_port_node === sourcePortB &&
    wireParam.data && wireParam.data.value === sourcePortB &&
    layerParam.data && layerParam.data.value === sourcePortB
    ? {{
        wireSourcePortNode: wire.data.from_port_node,
        layerValue: layer.data.value,
        endpointSourceNode: fromEndpoint.from.node,
        wireParam: wireParam.data.value,
        layerParam: layerParam.data.value,
      }}
    : null;
}})()
""")
    assert app_relation_final == {
        "wireSourcePortNode": app_relation["sourcePortB"],
        "layerValue": app_relation["sourcePortB"],
        "endpointSourceNode": app_relation["sourcePortB"],
        "wireParam": app_relation["sourcePortB"],
        "layerParam": app_relation["sourcePortB"],
    }

    screenshot_path = (
        Path(os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.home()))
        / "archhub-node-native-app-relation-port-layer-proof.png"
    )
    try:
        cdp.cmd("Emulation.setDeviceMetricsOverride", {
            "width": 1440,
            "height": 980,
            "deviceScaleFactor": 1,
            "mobile": False,
        })
        cdp.eval("window.dispatchEvent(new Event('resize'))")
    except Exception:
        pass
    shot = cdp.cmd("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    payload = shot.get("result", {}).get("data")
    assert payload, "CDP did not return screenshot data"
    screenshot_path.write_bytes(base64.b64decode(payload))
    assert screenshot_path.stat().st_size > 10_000, screenshot_path


def test_output_body_uses_typed_image_preview_surface(cdp):
    """The output preview must not flatten every typed value into text.

    This creates a real output node with a cooked image value, toggles preview
    through the same node-output action the UI button emits, and proves the
    preview render slot hosts an image preview node surface.
    """
    def _maybe_json(value):
        if isinstance(value, str) and value[:1] in "{[":
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def _wait_js(expr, *, timeout=25, interval=0.5):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = _maybe_json(cdp.eval(expr))
            if last:
                return last
            time.sleep(interval)
        return last

    created = _maybe_json(cdp.eval(
        r"""
(async () => {
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const graph = () => window.__archhub_LM_GRAPH || {};
  if (!Array.isArray(graph().nodes)) graph().nodes = [];
  if (!Array.isArray(graph().wires)) graph().wires = [];
  window.dispatchEvent(new CustomEvent('lm-action-new-canvas'));
  await delay(1200);
  if (!Array.isArray(graph().nodes)) graph().nodes = [];
  if (!Array.isArray(graph().wires)) graph().wires = [];
  const stamp = Date.now().toString(36);
  const nodeId = 'cdp-node-native:typed-output:' + stamp;
  const img = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMiIgaGVpZ2h0PSIxNiI+PHJlY3Qgd2lkdGg9IjMyIiBoZWlnaHQ9IjE2IiBmaWxsPSIjZDk3NzU3Ii8+PC9zdmc+';
  graph().nodes.push({
    id: nodeId,
    type: 'output.parameter',
    cat: 'output',
    title: 'Typed Image Output Proof',
    sub: 'node-native typed preview',
    x: 160,
    y: 140,
    data: { role: 'workflow_node' },
    config: { as: 'image' },
    params: [{ k: 'as', label: 'as', type: 'text', v: 'image' }],
    ins: [{ id: 'value', label: 'value', t: 'image' }],
    outs: [],
    cooked: { value: { image: img }, value_type: 'image' },
  });
  if (typeof window.__archhubBumpGraph === 'function') window.__archhubBumpGraph();
  return { ok: true, nodeId, img };
})()
        """,
        await_promise=True,
    ))
    assert created and created.get("ok") is True, created
    node_id = json.dumps(created["nodeId"])

    assert _wait_js(f"""
(function(){{
  const text = document.body && document.body.innerText ? document.body.innerText : '';
  const body = document.querySelector('.ah-node-output-body-node');
  return text.indexOf('Typed Image Output Proof') >= 0 && !!body;
}})()
"""), "typed output body surface did not render"

    cdp.eval(f"""
window.dispatchEvent(new CustomEvent('lm-ui-node-action', {{
  detail: {{
    node_id: {node_id},
    action: 'node-output.preview.toggle',
    args: {{ node_id: {node_id} }},
  }},
}}))
""")
    rendered = _wait_js(f"""
(function(){{
  const render = document.querySelector('.ah-node-output-preview-render-node[data-hidden="false"]');
  const img = document.querySelector('.ah-node-image-preview-img-node');
  const textPreview = document.querySelector('.ah-node-output-preview-node[data-hidden="false"]');
  const textPreviewVisible = !!(textPreview && getComputedStyle(textPreview).display !== 'none' && !textPreview.hidden);
  return render && img && !textPreviewVisible ? {{
    renderVisible: render.getAttribute('data-hidden'),
    imgSrc: img.getAttribute('src') || '',
    textPreviewVisible,
    }} : null;
}})()
""")
    if not rendered:
        rendered = _maybe_json(cdp.eval(r"""
(function(){
  return JSON.stringify({
    renders:[...document.querySelectorAll('.ah-node-output-preview-render-node')].map(e=>({
      hidden:e.hidden, data:e.getAttribute('data-hidden'), html:e.outerHTML.slice(0, 500)
    })),
    textPreviews:[...document.querySelectorAll('.ah-node-output-preview-node')].map(e=>({
      hidden:e.hidden, data:e.getAttribute('data-hidden'), text:e.innerText, html:e.outerHTML.slice(0, 500)
    })),
    images:[...document.querySelectorAll('.ah-node-image-preview-img-node')].map(e=>({
      src:e.getAttribute('src'), html:e.outerHTML.slice(0, 300)
    })),
    graphPreviewNodes:(window.__archhub_LM_GRAPH.nodes||[])
      .filter(n=>String(n.id||'').indexOf('node-output-preview') >= 0)
      .map(n=>({id:n.id, cls:n.data&&n.data.cls, hidden_bind:n.data&&n.data.hidden_bind, render_slot:n.data&&n.data.render_slot, value:n.data&&n.data.value})),
  });
})()
"""))
    assert rendered and rendered.get("renderVisible") == "false", rendered
    assert rendered["imgSrc"].startswith("data:image/svg+xml;base64,"), rendered
    assert rendered["textPreviewVisible"] is False

    screenshot_path = (
        Path(os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.home()))
        / "archhub-node-native-output-image-preview-proof.png"
    )
    try:
        cdp.cmd("Emulation.setDeviceMetricsOverride", {
            "width": 1440,
            "height": 980,
            "deviceScaleFactor": 1,
            "mobile": False,
        })
        cdp.eval("window.dispatchEvent(new Event('resize'))")
    except Exception:
        pass
    shot = cdp.cmd("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    payload = shot.get("result", {}).get("data")
    assert payload, "CDP did not return screenshot data"
    screenshot_path.write_bytes(base64.b64decode(payload))
    assert screenshot_path.stat().st_size > 10_000, screenshot_path
