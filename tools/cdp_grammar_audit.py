"""CDP grammar audit — verify the LIVE palette matches founder mandate.

Connects to ArchHub's QtWebEngine CDP on port 9223 + queries
`bridge.get_node_grammar()` + DOM `<select>` elements. Reports:

  • total visible primitive count
  • zero-dropdown invariant (founder mandate 2026-05-21)
  • code/ai master back-compat (hidden in palette, kept for engine)
  • adapter coverage
  • live DOM <select> count (must be 0 unless welcome modal / connector
    op picker are open)

Exit code 0 on PASS, 1 on FAIL. Useful for:
  • Manual founder verification ("show me dropdowns are gone")
  • CI smoke test (launch ArchHub headless + run this)
  • Regression triage when the in-process grammar-health tests pass
    but the live UX still looks wrong

Run:
  $ QTWEBENGINE_REMOTE_DEBUGGING=9223 pythonw app/main.py &
  $ python tools/cdp_grammar_audit.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


def _cdp_url(port: int = 9223) -> str | None:
    """Pull the page WS URL from CDP /json/list. Returns None if CDP
    not listening (ArchHub not launched with the env var)."""
    try:
        data = json.load(urllib.request.urlopen(
            f"http://localhost:{port}/json/list", timeout=5))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    for t in data:
        if t.get("type") == "page":
            return t.get("webSocketDebuggerUrl")
    return None


def _make_evaluator(ws):
    """Returns an `evalJS(expr, await_promise=False)` helper closed
    over the given websocket. Filters Runtime.* events out — only
    returns the response keyed by id."""
    mid = [0]

    def evalJS(expr: str, *, await_promise: bool = False,
                timeout: float = 12.0) -> object:
        mid[0] += 1
        my_id = mid[0]
        ws.send(json.dumps({"id": my_id, "method": "Runtime.evaluate",
                              "params": {"expression": expr,
                                          "returnByValue": True,
                                          "awaitPromise": await_promise}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                break
            if msg.get("id") == my_id:
                res = msg.get("result", {}).get("result", {})
                return res.get("value", res)
        return None

    return evalJS


# ── Audit primitives ─────────────────────────────────────────────────


def _audit_grammar_payload(evalJS) -> dict:
    """Pull the bridge-exposed grammar payload + classify."""
    raw = evalJS('''
window.bridgeJson('get_node_grammar').then(payload => {
  const kinds = payload.map(p => p.kind);
  return JSON.stringify({
    total_visible:           payload.length,
    masters_with_selector:   payload.filter(p => p.selector && p.selector !== '')
                                    .map(p => p.kind + '/' + p.selector),
    params_render_dropdown:  payload.flatMap(p =>
      (p.params || []).filter(pp =>
        ['choice','enum','select'].includes(pp.type)
        || (pp.options && pp.options.length)
      ).map(pp => p.kind + '/' + pp.k)
    ),
    code_visible:            kinds.filter(k => k.startsWith('code')),
    ai_visible:              kinds.filter(k => k.startsWith('ai')),
    adapter_visible:         kinds.filter(k =>
                                payload.find(p => p.kind === k
                                              && p.cat === 'adapter')),
    has_code_master:         kinds.includes('code'),
    has_ai_master:           kinds.includes('ai'),
  });
})
''', await_promise=True)
    if not raw:
        return {"_error": "empty grammar payload"}
    try:
        return json.loads(raw)
    except Exception as ex:
        return {"_error": f"bad payload JSON: {ex}"}


def _audit_live_selects(evalJS) -> dict:
    """Count visible <select> elements in the current DOM."""
    raw = evalJS('''
JSON.stringify((() => {
  const sels = Array.from(document.querySelectorAll('select'));
  const visible = sels.filter(s => s.offsetParent !== null);
  return {
    total:    sels.length,
    visible:  visible.length,
    samples:  visible.slice(0, 5).map(s => ({
      value:    s.value,
      options:  s.options.length,
      parent_id: (s.parentElement && s.parentElement.id) || '',
    })),
  };
})())
''')
    if not raw:
        return {"_error": "empty DOM audit"}
    try:
        return json.loads(raw)
    except Exception as ex:
        return {"_error": f"bad DOM JSON: {ex}"}


# ── Report ───────────────────────────────────────────────────────────


def run_audit(port: int = 9223) -> int:
    """Returns process exit code: 0 PASS, 1 FAIL."""
    import websocket  # noqa: F401 — third-party
    ws_url = _cdp_url(port)
    if not ws_url:
        print(f"[FAIL] CDP not reachable on port {port}; "
              f"launch ArchHub with "
              f"`QTWEBENGINE_REMOTE_DEBUGGING={port} pythonw app/main.py`")
        return 1
    print(f"connecting to {ws_url}")
    ws = websocket.create_connection(ws_url, timeout=15)
    evalJS = _make_evaluator(ws)
    # Light enable.
    ws.send(json.dumps({"id": 0, "method": "Runtime.enable"}))
    ws.recv()

    grammar = _audit_grammar_payload(evalJS)
    dom = _audit_live_selects(evalJS)
    ws.close()

    print()
    print("=== GRAMMAR PAYLOAD ===")
    print(json.dumps(grammar, indent=2))
    print()
    print("=== LIVE DOM <select> ===")
    print(json.dumps(dom, indent=2))
    print()

    failures: list[str] = []
    if "_error" in grammar:
        failures.append(f"grammar payload error: {grammar['_error']}")
    else:
        if grammar.get("masters_with_selector"):
            failures.append(
                "founder gripe — visible masters with selector "
                f"dropdowns: {grammar['masters_with_selector']}")
        if grammar.get("params_render_dropdown"):
            failures.append(
                "visible primitive params would render as <select>: "
                f"{grammar['params_render_dropdown']}")
        if grammar.get("has_code_master"):
            failures.append("`code` master visible (must be hidden)")
        if grammar.get("has_ai_master"):
            failures.append("`ai` master visible (must be hidden)")

    if failures:
        print("=== FAIL ===")
        for f in failures:
            print(f"  [X] {f}")
        return 1
    print("=== PASS ===")
    print(f"  [OK] {grammar.get('total_visible')} visible primitives")
    print(f"  [OK] 0 masters with selector dropdowns")
    print(f"  [OK] 0 visible params render as <select>")
    print(f"  [OK] `code` master hidden + "
          f"{len(grammar.get('code_visible') or [])} typed code nodes "
          f"surfaced: {grammar.get('code_visible')}")
    print(f"  [OK] `ai` master hidden + "
          f"{len(grammar.get('ai_visible') or [])} typed AI nodes "
          f"surfaced: {grammar.get('ai_visible')}")
    return 0


def main() -> None:
    sys.exit(run_audit())


if __name__ == "__main__":
    main()
