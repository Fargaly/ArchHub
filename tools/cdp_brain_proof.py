"""CDP-driven screenshot proof of Settings → Brain panel.

Connects to ArchHub QtWebEngine via DevTools Protocol on :9223,
opens Settings panel, scrolls to BRAIN section, screenshots the page,
saves it to proofs/<date>/.

Used to satisfy CLAUDE.md DEFINITION-OF-SHIPPED MANDATE for AgDR-0044/0045.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import websocket  # websocket-client
except ImportError:
    print("websocket-client not installed", file=sys.stderr)
    sys.exit(2)


def _get_tab(cdp_url: str = "http://127.0.0.1:9223") -> dict:
    """Return the first ArchHub-page tab from CDP /json.

    QtWebEngine's /json endpoint occasionally hangs — retry with
    increasing timeouts up to 90s before giving up.
    """
    last_err = None
    for attempt in range(6):
        try:
            timeout = 5 + 5 * attempt
            with urllib.request.urlopen(
                f"{cdp_url}/json", timeout=timeout,
            ) as r:
                tabs = json.loads(r.read())
            for t in tabs:
                title = t.get("title", "")
                if "ArchHub" in title or t.get("type") == "page":
                    return t
            if tabs:
                return tabs[0]
            raise RuntimeError("no CDP tabs found")
        except Exception as ex:
            last_err = ex
            print(f"      /json attempt {attempt + 1} failed ({type(ex).__name__}); retrying…")
            time.sleep(3)
    raise RuntimeError(f"CDP /json never responded: {last_err}")


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(
            ws_url, timeout=15,
            skip_utf8_validation=True,
        )
        self._id = 0
        # Drain any unsolicited events before first call
        self.ws.settimeout(0.5)
        for _ in range(50):
            try:
                self.ws.recv()
            except Exception:
                break

    def call(self, method: str, params: dict = None, *, timeout: float = 30.0):
        self._id += 1
        msg_id = self._id
        msg = {"id": msg_id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(msg))
        self.ws.settimeout(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            # Skip notifications/events (they have no "id")
            if obj.get("id") != msg_id:
                continue
            if "error" in obj:
                raise RuntimeError(f"{method} → {obj['error']}")
            return obj.get("result", {})
        raise TimeoutError(f"{method} no reply in {timeout}s")

    def evaluate(self, expr: str, await_promise: bool = False,
                 timeout: float = 20.0):
        result = self.call("Runtime.evaluate", {
            "expression": expr, "awaitPromise": await_promise,
            "returnByValue": True,
        }, timeout=timeout)
        if result.get("exceptionDetails"):
            raise RuntimeError(
                f"JS exception: {result['exceptionDetails']}"
            )
        return result.get("result", {}).get("value")

    def screenshot(self) -> bytes:
        # fromSurface=False uses BitmapEncoder path which works even
        # when the compositor surface isn't directly available (Qt
        # WebEngine on Windows sometimes can't expose surface).
        # Try fromSurface=True first, fall back to False.
        for from_surface in (True, False):
            try:
                r = self.call("Page.captureScreenshot",
                              {"format": "png",
                               "fromSurface": from_surface},
                              timeout=30)
                return base64.b64decode(r["data"])
            except TimeoutError:
                continue
        raise TimeoutError("Page.captureScreenshot failed both modes")

    def close(self):
        try: self.ws.close()
        except Exception: pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--cdp", type=str, default="http://127.0.0.1:9223")
    p.add_argument("--label", type=str, default="brain-section")
    args = p.parse_args()

    print(f"[1/6] Locating ArchHub CDP tab via {args.cdp}/json …")
    tab = _get_tab(args.cdp)
    print(f"      tab: {tab.get('title','?')[:60]}")
    ws_url = tab["webSocketDebuggerUrl"]

    print("[2/6] Connecting DevTools WebSocket …")
    cdp = CDP(ws_url)

    try:
        # Required by some CDP servers before evaluate works.
        # QtWebEngine sometimes needs > 5s on first enable.
        try:
            cdp.call("Runtime.enable", timeout=15.0)
            cdp.call("Page.enable", timeout=15.0)
        except TimeoutError as ex:
            print(f"      WARN: domain enable timed out ({ex}); continuing")
        # Clear cached JSX so the latest BrainSection compiles fresh
        try:
            cdp.evaluate("""
            (function() {
                try {
                    let n = 0;
                    for (let i = localStorage.length - 1; i >= 0; i--) {
                        const k = localStorage.key(i);
                        if (k && k.indexOf('jsx_cache_v1_') === 0) {
                            localStorage.removeItem(k); n++;
                        }
                    }
                    return 'cleared ' + n + ' jsx cache entries';
                } catch (e) { return 'clear failed: ' + e.message; }
            })()
            """, await_promise=False, timeout=10.0)
            print("      cleared JSX cache (forces fresh transpile next reload)")
        except Exception as ex:
            print(f"      cache-clear skipped: {ex}")

        print("[3/6] Waiting for JSX boot (window.archhub present) …")
        for i in range(40):
            try:
                ok = cdp.evaluate(
                    "(typeof window !== 'undefined' "
                    " && !!window.archhub "
                    " && typeof window.archhub.brain_status === 'function')",
                    await_promise=False,
                )
                if ok:
                    print(f"      ready after {i+1} polls")
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            print("      WARN: window.archhub.brain_status missing — proceeding anyway")

        print("[4/6] Opening Settings panel via `lm-action-open-settings` event …")
        # Verified in studio-lm.jsx line 2074 — Settings listens for this event.
        opened = cdp.evaluate("""
        (function() {
            try {
                window.dispatchEvent(new CustomEvent('lm-action-open-settings'));
                return 'dispatched lm-action-open-settings';
            } catch (e) {
                return 'dispatch failed: ' + e.message;
            }
        })()
        """, await_promise=False, timeout=15.0)
        print(f"      {opened}")

        # Give the Settings panel time to mount + BrainSection polls
        # brain_status on first render (one bridge round-trip).
        print("      waiting 4s for panel + BrainSection async polls …")
        time.sleep(4.0)

        print("[5/6] Scrolling to BRAIN section …")
        try:
            scrolled = cdp.evaluate("""
            (function() {
                const all = [...document.querySelectorAll('div')];
                for (const el of all) {
                    const t = (el.textContent || '').trim();
                    if (t.startsWith('BRAIN') && t.length < 80
                        && el.children.length <= 6) {
                        el.scrollIntoView({block:'center'});
                        return 'BRAIN section scrolled into view';
                    }
                }
                return 'BRAIN header not in DOM (Settings may not be open)';
            })()
            """, await_promise=False, timeout=45.0)
            print(f"      {scrolled}")
        except TimeoutError:
            print("      WARN: scroll evaluate timed out — capturing anyway")
        time.sleep(1.0)

        print("[6/6] Capturing screenshot …")
        png = cdp.screenshot()

        # Save
        date = datetime.now().strftime("%Y-%m-%d")
        ts = datetime.now().strftime("%H%M%S")
        out_dir = Path(args.out) if args.out else (
            Path(__file__).resolve().parent.parent / "proofs" / date
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = out_dir / f"proof_{args.label}_{ts}.png"
        fname.write_bytes(png)
        print(f"\n      ✓ saved {len(png):,} bytes → {fname}")
        return 0
    finally:
        cdp.close()


if __name__ == "__main__":
    sys.exit(main())
