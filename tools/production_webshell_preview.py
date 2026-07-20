"""Serve the production WebShell with a local node-backed bridge.

This is a verification harness for the real app surface in ``app/web_ui``.
It is not the standalone ``13.NODE-LANGUAGE`` canvas. The injected bridge
implements the same ``get_grand_map_ui_surface`` contract as ``ArchHubBridge``
so browser-visible UI proof can pull the production Grand Map UI fragments.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = ROOT / "app"
WEB_UI_DIR = APP_ROOT / "web_ui"
BRIDGE_SCRIPT_PATH = "/__archhub_preview_bridge.js"


if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def preview_bridge_source() -> str:
    """Return the browser-side QWebChannel-compatible preview bridge."""
    return r"""(function() {
  'use strict';
  if (window.__archhub_preview_bridge) return;
  window.__archhub_preview_bridge = true;

  function getJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function(response) {
      if (!response.ok) {
        return { ok: false, error: 'HTTP ' + response.status };
      }
      return response.json();
    });
  }

  function postJson(url, payloadJson) {
    return fetch(url, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: typeof payloadJson === 'string'
        ? payloadJson
        : JSON.stringify(payloadJson || {})
    }).then(function(response) {
      if (!response.ok) {
        return { ok: false, error: 'HTTP ' + response.status };
      }
      return response.json();
    });
  }

    window.archhub = {
    get_version: function() {
      return 'production-webshell-preview';
    },
    get_node_grammar: function(done) {
      return getJson('/__archhub/node-grammar').then(function(payload) {
        var text = JSON.stringify(payload);
        if (typeof done === 'function') done(text);
        return text;
      });
    },
    get_grand_map_ui_surface: function(surface, done) {
      return getJson(
        '/__archhub/grand-map-ui-surface?surface=' +
        encodeURIComponent(surface || 'home-top')
      ).then(function(payload) {
        var text = JSON.stringify(payload);
        if (typeof done === 'function') done(text);
        return text;
      });
    },
    submit_universal_interaction: function(payloadJson, done) {
      return postJson('/__archhub/universal-interaction', payloadJson)
        .then(function(payload) {
          var text = JSON.stringify(payload);
          if (typeof done === 'function') done(text);
          return text;
        });
    }
  };

  window.__archhub_ready = true;
  window.archhubReady = Promise.resolve(window.archhub);
  try {
    console.log('[archhub] preview bridge ready');
  } catch (e) {}
})();"""


def inject_preview_bridge(index_html: str) -> str:
    """Inject the preview bridge before React/app boot scripts execute."""
    script = f'<script src="{BRIDGE_SCRIPT_PATH}"></script>'
    if BRIDGE_SCRIPT_PATH in index_html:
        return index_html

    marker = '<script src="vendor/react.production.min.js"></script>'
    if marker in index_html:
        return index_html.replace(marker, script + "\n" + marker, 1)
    if "</body>" in index_html:
        return index_html.replace("</body>", script + "\n</body>", 1)
    return index_html + "\n" + script + "\n"


def _surface_payload(surface: str, grand_map_path: Path | None) -> dict[str, Any]:
    try:
        if (surface or "").strip() == "universal-canvas":
            from workflows.universal_grand_map_surface import (
                universal_grand_map_surface,
            )

            return universal_grand_map_surface(surface)
        from workflows.grand_map_ui import grand_map_ui_surface

        kwargs: dict[str, Any] = {}
        if grand_map_path is not None:
            kwargs["grand_map_path"] = grand_map_path
        return grand_map_ui_surface(surface or "home-top", **kwargs)
    except Exception as ex:
        return {
            "ok": False,
            "surface": surface or "home-top",
            "error": f"{type(ex).__name__}: {ex}",
        }


def _node_grammar_payload() -> Any:
    try:
        from workflows.node_grammar import grammar_payload

        return grammar_payload()
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def _universal_interaction_payload(payload: dict[str, Any]) -> Any:
    try:
        from workflows.universal_grand_map_surface import (
            universal_canvas_interaction,
        )

        return universal_canvas_interaction(payload)
    except Exception as ex:
        return {
            "ok": False,
            "authority": "10.PRODUCT/13.NODE-LANGUAGE",
            "error": f"{type(ex).__name__}: {ex}",
        }


def make_server(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    web_ui_dir: str | Path = WEB_UI_DIR,
    grand_map_path: str | Path | None = None,
) -> ThreadingHTTPServer:
    """Create a WebShell preview server without starting its serving loop."""
    web_root = Path(web_ui_dir).resolve()
    map_path = Path(grand_map_path).resolve() if grand_map_path is not None else None

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(web_root), **kwargs)

        def log_message(self, *_args: Any) -> None:
            pass

        def _send_bytes(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: Any, code: int = 200) -> None:
            self._send_bytes(
                code,
                "application/json; charset=utf-8",
                json.dumps(payload).encode("utf-8"),
            )

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            path = parsed.path

            if path in ("", "/"):
                index_path = web_root / "index.html"
                try:
                    html = index_path.read_text(encoding="utf-8")
                except Exception as ex:
                    return self._send_json(
                        {"ok": False, "error": f"{type(ex).__name__}: {ex}"},
                        code=500,
                    )
                body = inject_preview_bridge(html).encode("utf-8")
                return self._send_bytes(200, "text/html; charset=utf-8", body)

            if path == BRIDGE_SCRIPT_PATH:
                return self._send_bytes(
                    200,
                    "application/javascript; charset=utf-8",
                    preview_bridge_source().encode("utf-8"),
                )

            if path == "/__archhub/node-grammar":
                return self._send_json(_node_grammar_payload())

            if path == "/__archhub/grand-map-ui-surface":
                params = parse_qs(parsed.query)
                surface = (params.get("surface") or ["home-top"])[0]
                return self._send_json(_surface_payload(surface, map_path))

            return super().do_GET()

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            if parsed.path != "/__archhub/universal-interaction":
                return self._send_json(
                    {"ok": False, "error": "not found"},
                    code=404,
                )
            try:
                size = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                return self._send_json(
                    {"ok": False, "error": "invalid content length"},
                    code=400,
                )
            if size > 1_048_576:
                return self._send_json(
                    {"ok": False, "error": "request body too large"},
                    code=413,
                )
            try:
                raw = self.rfile.read(size)
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception as ex:
                return self._send_json(
                    {"ok": False, "error": f"{type(ex).__name__}: {ex}"},
                    code=400,
                )
            if type(payload) is not dict:
                return self._send_json(
                    {
                        "ok": False,
                        "authority": "10.PRODUCT/13.NODE-LANGUAGE",
                        "error": "universal interaction payload must be a JSON object",
                    },
                    code=400,
                )
            return self._send_json(_universal_interaction_payload(payload))

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the production WebShell with a node-backed preview bridge."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8480)
    parser.add_argument("--web-ui-dir", default=str(WEB_UI_DIR))
    parser.add_argument("--grand-map-path")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)

    server = make_server(
        host=args.host,
        port=args.port,
        web_ui_dir=args.web_ui_dir,
        grand_map_path=args.grand_map_path,
    )
    url = f"http://{server.server_address[0]}:{server.server_address[1]}/"
    print("ArchHub production WebShell preview:", url, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
