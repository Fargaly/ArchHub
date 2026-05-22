"""SHARE category engine nodes — M1.5.

Reference: founder decision 2026-05-21. "DiskTransport default · server
opt-in via typed nodes the user wires into their graph."

Three typed nodes, three engines:

  share.publish   — push a value through Speckle, emit model URL
                    side-effect: ensures localhost Speckle Server up
  share.subscribe — pull a Base from a Speckle URL (local or remote)
  share.server    — ensure localhost Speckle Server running
                    output: server URL + status

All three back onto:
  • `app/speckle_wire.py` for the DiskTransport substrate (every send
    writes locally regardless of server)
  • `app/speckle_server.py` for the lifecycle (start/stop Docker stack)

Wiring contract (per founder's "node ≠ wire" note):
  • share.publish:    in `value`              → out `model_url`, `status`
  • share.subscribe:  in `source_url`         → out `value`, `status`
  • share.server:                              → out `server_url`, `status`
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


# ---------------------------------------------------------------------------
# share.server — ensure localhost Speckle Server reachable
#
# Pure side-effect node. No input. Outputs the server URL + status dict.
# Other nodes can wire `server_url` in as their server target.


def _share_server_executor(config: dict, inputs: dict, ctx) -> dict:
    import speckle_server
    port = int(config.get("port", 3000))
    auto_start = bool(config.get("auto_start", True))
    url = f"http://localhost:{port}"

    # Fast probe first — if already up, return immediately (no Docker
    # touch needed).
    probe = speckle_server.is_running(url)
    if probe["running"]:
        return {
            "server_url": url,
            "status": {"running": True, "started_now": False,
                        "version": probe.get("version")},
        }

    if not auto_start:
        return {
            "server_url": url,
            "status": {"running": False,
                        "error": "server not running; auto_start=False"},
        }

    # Start it — speckle_server.start_local handles docker + compose +
    # health poll. Long-running (up to ~90s cold-start).
    result = speckle_server.start_local(port=port, wait=True)
    return {
        "server_url": result.get("url") or url,
        "status": {
            "running": result.get("status") == "running",
            "started_now": result.get("status") == "running",
            "error": result.get("error"),
            "code": result.get("code"),
            "version": result.get("version"),
            "compose_path": result.get("compose_path"),
        },
    }


register(
    NodeSpec(
        type="share.server",
        category="share",
        display_name="Speckle Server",
        description=(
            "Ensure the localhost Speckle Server is running. Starts a "
            "Docker Compose stack on first use; idempotent afterwards. "
            "Output server_url is the entry-point other SHARE nodes wire to."
        ),
        inputs=[],
        outputs=[
            Port(name="server_url", type=PortType.STRING),
            Port(name="status",     type=PortType.OBJECT),
        ],
        config_schema={
            "port": {"type": "integer", "default": 3000,
                     "description": "Localhost port the Speckle Server binds."},
            "auto_start": {"type": "boolean", "default": True,
                           "description": "Start the server if not already up."},
        },
        icon="⌬",
    ),
    _share_server_executor,
)


# ---------------------------------------------------------------------------
# share.publish — publish the input value through Speckle
#
# Always writes through `SpeckleWire` (DiskTransport) so the value is
# locally addressable. When a server_url is supplied (wired in from
# share.server or hardcoded), the executor also pushes to that server
# via ServerTransport — that turns the local hash into a globally
# shareable URL on the Speckle Server.


def _share_publish_executor(config: dict, inputs: dict, ctx) -> dict:
    from speckle_wire import SpeckleWire, _coerce_to_base

    value = inputs.get("value")
    server_url = (config.get("server_url") or "").strip() or None
    model_name = (config.get("model_name") or "").strip() or "default"

    # 1) Always write to disk first — local hash is the foundation.
    wire = SpeckleWire()  # default per-user project dir
    try:
        local_hash = wire.send(value)
    except Exception as ex:
        return {"model_url": "", "status": {
            "ok": False, "error": f"local send failed: {ex}",
            "code": "local_send_failed",
        }}

    # 2) If a server URL was supplied, attempt a server push too.
    # Delegated to the canonical `speckle_server.push_to_server`
    # entry-point (M2-Python / AgDR-0017 — single implementation
    # for both share.publish AND revit.send_to_speckle).
    server_pushed = False
    server_error = None
    if server_url:
        try:
            from speckle_server import push_to_server
            push_to_server(value, server_url, model_name)
            server_pushed = True
        except Exception as ex:
            server_error = f"{type(ex).__name__}: {ex}"

    model_url = (
        f"{server_url.rstrip('/')}/streams/{model_name}/objects/{local_hash}"
        if server_url else
        f"speckle://local/{local_hash}"  # disk-only addressable scheme
    )
    return {
        "model_url": model_url,
        "status": {
            "ok": True,
            "local_hash": local_hash,
            "server_pushed": server_pushed,
            "server_error": server_error,
        },
    }


register(
    NodeSpec(
        type="share.publish",
        category="share",
        display_name="Publish to Speckle",
        description=(
            "Publish the upstream value to Speckle. Writes locally via "
            "DiskTransport (always); pushes to a Speckle Server when "
            "server_url is wired in (optional). Output model_url is the "
            "permalink other graphs can subscribe to."
        ),
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[
            Port(name="model_url", type=PortType.STRING),
            Port(name="status",    type=PortType.OBJECT),
        ],
        config_schema={
            "model_name": {"type": "string", "default": "default",
                            "description": "Speckle Model / Stream id."},
            "server_url": {"type": "string", "default": "",
                            "description": "Optional remote Speckle Server URL (overrides wire-in)."},
        },
        icon="↑",
    ),
    _share_publish_executor,
)


# ---------------------------------------------------------------------------
# share.subscribe — pull a Base from a Speckle URL
#
# Accepts either:
#   speckle://local/<hash>             → read from DiskTransport
#   http(s)://<server>/streams/<model>/objects/<hash>  → server pull
#   bare <hash>                        → DiskTransport (legacy)


def _share_subscribe_executor(config: dict, inputs: dict, ctx) -> dict:
    from speckle_wire import SpeckleWire, _coerce_from_base

    source_url = (inputs.get("source_url") or "").strip()
    if not source_url:
        return {"value": None, "status": {
            "ok": False, "error": "source_url is required",
            "code": "no_source",
        }}

    # Parse the URL shape.
    if source_url.startswith("speckle://local/"):
        hash_ = source_url.split("/")[-1]
        wire = SpeckleWire()
        try:
            value = wire.receive(hash_)
            return {"value": value, "status": {"ok": True,
                                                  "source": "local"}}
        except Exception as ex:
            return {"value": None, "status": {
                "ok": False, "error": f"local receive failed: {ex}",
                "code": "local_receive_failed",
            }}

    if source_url.startswith("http://") or source_url.startswith("https://"):
        # Parse /streams/<stream_id>/objects/<hash>
        try:
            parts = source_url.split("/")
            # ...streams/<stream_id>/objects/<hash>
            stream_id = parts[parts.index("streams") + 1]
            hash_ = parts[parts.index("objects") + 1]
            # Reconstruct server base URL.
            server_base = source_url.split("/streams/")[0]
        except (ValueError, IndexError):
            return {"value": None, "status": {
                "ok": False,
                "error": "URL must look like <server>/streams/<id>/objects/<hash>",
                "code": "bad_url_shape",
            }}
        try:
            from specklepy.api.client import SpeckleClient
            from specklepy.transports.server import ServerTransport
            from specklepy.api import operations

            client = SpeckleClient(host=server_base,
                                    use_ssl=server_base.startswith("https"))
            transport = ServerTransport(client=client, stream_id=stream_id)
            base = operations.receive(hash_, remote_transport=transport)
            return {
                "value": _coerce_from_base(base),
                "status": {"ok": True, "source": "server",
                           "server": server_base},
            }
        except Exception as ex:
            return {"value": None, "status": {
                "ok": False,
                "error": f"server receive failed: {type(ex).__name__}: {ex}",
                "code": "server_receive_failed",
            }}

    # Bare hash — try local.
    wire = SpeckleWire()
    try:
        value = wire.receive(source_url)
        return {"value": value, "status": {"ok": True,
                                              "source": "local"}}
    except Exception as ex:
        return {"value": None, "status": {
            "ok": False,
            "error": f"URL not recognised: {source_url!r}. Use speckle://local/<hash>, an http(s) URL, or a bare hash. ({ex})",
            "code": "bad_url",
        }}


register(
    NodeSpec(
        type="share.subscribe",
        category="share",
        display_name="Subscribe to Speckle",
        description=(
            "Pull a value from a Speckle URL. Accepts speckle://local/<hash> "
            "for DiskTransport, or http(s) URLs for Speckle Server. Output "
            "value is the deserialised Base / dict / list / scalar."
        ),
        inputs=[
            Port(name="source_url", type=PortType.STRING, required=True),
        ],
        outputs=[
            Port(name="value",  type=PortType.ANY),
            Port(name="status", type=PortType.OBJECT),
        ],
        config_schema={
            "refresh_interval": {"type": "integer", "default": 0,
                                  "description": "Polling interval in seconds (0 = manual only)."},
        },
        icon="↓",
    ),
    _share_subscribe_executor,
)
