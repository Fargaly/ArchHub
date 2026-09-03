"""base.py-contract connector scaffolder — the REAL artifact writer for the
self-extension loop's `create_connector` build tool (SEAM 1).

ONE-SYSTEM (ONE-SYSTEM-PLAN-BEFORE-BUILD): this does NOT mint a new connector
engine. It writes a connector module that subclasses the EXISTING uniform
`connectors.base.Connector` ABC (the same ABC the 16 hand-written connectors
subclass) and registers via the SAME `connectors.base.register(Xxx())` call at
import. The output is a real, importable `*_connector.py` under `app/connectors/`
that `connectors.registry` + the workflow runner pick up like any other
connector — no parallel path.

The ABC makes `probe()` + `build_ops()` `@abstractmethod`, so a generated class
that did not implement BOTH could not even instantiate (it would fail loud at
import). The scaffold therefore renders BOTH: an honest `probe()` (status
"missing" until wired to a real reachability check — never a faked "live") and
`build_ops()` returning the typed ops. Each op body is a clearly-marked honest
stub (`OpResult.fail("... not implemented yet")`) so the connector reports
HONEST status and never fabricates data until its ops are filled in — matching
the connector-contract mandate in base.py.

SAFETY:
  * Writes ONLY under `app/connectors/` (path derived from the host id, never
    from raw caller input) — it cannot escape the connectors package.
  * py_compile-clean output is the court's gate downstream; a scaffold that does
    not compile is refused a GREEN by the ROMA court.
  * Idempotent refusal: an existing target file is NOT overwritten (returns
    {ok: False, exists: True}) — LIBRARY-FIRST: reuse, don't clobber.
"""
from __future__ import annotations

import keyword
import re
from pathlib import Path
from typing import Any


CONNECTORS_DIR = Path(__file__).resolve().parent


def _safe_host_id(raw: str) -> str:
    """Coerce a host id to a safe lowercase identifier stem (a-z0-9_).

    The file path is derived ONLY from this — the scaffold can never be made to
    write outside app/connectors/ by a crafted host id."""
    h = re.sub(r"[^a-z0-9_]", "_", (raw or "").strip().lower())
    h = re.sub(r"_+", "_", h).strip("_")
    return h


def _ident(raw: str) -> str:
    """A python-identifier-safe op-method suffix."""
    s = re.sub(r"[^a-z0-9_]", "_", (raw or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or s[0].isdigit():
        s = "op_" + s
    if keyword.iskeyword(s):
        s += "_op"
    return s


def _op_suffix(o: dict[str, Any]) -> str:
    raw = str(o.get("op_id") or o.get("id") or "").strip()
    return raw.split(".", 1)[1] if "." in raw else raw


def connector_path(host_id: str) -> Path:
    """Where the scaffold for `host_id` would be written."""
    return CONNECTORS_DIR / f"{_safe_host_id(host_id)}_connector.py"


def render_connector(spec: dict[str, Any]) -> tuple[str, str]:
    """Render the connector module source from a spec.

    spec = {
      "host": "<host id>",                # required → <host>_connector.py
      "label": "<Human Name>",            # optional (defaults from host)
      "mechanism": "rest"|"com"|...,      # optional (defaults 'rest')
      "description": "<one line>",        # optional
      "operations": [                     # optional; defaults to one read stub
         {"op_id": "list_things"|"<host>.list_things",
          "kind": "read"|"action", "label": "...", "description": "..."},
      ],
    }

    Returns (host_id, source_text). Raises ValueError on a missing host.
    """
    host = _safe_host_id(spec.get("host") or spec.get("family") or "")
    if not host:
        raise ValueError("connector spec needs a 'host' id")
    label = spec.get("label") or spec.get("display_name") or host.replace("_", " ").title()
    mechanism = (spec.get("mechanism") or "rest").strip().lower()
    desc = (spec.get("description") or f"{label} connector (scaffolded).").strip()
    cls = "".join(p.capitalize() for p in host.split("_")) + "Connector"

    ops = spec.get("operations") or spec.get("ops") or []
    if not isinstance(ops, list) or not ops:
        ops = [{"op_id": "ping", "kind": "read", "label": "Ping",
                "description": f"Probe whether {label} is reachable."}]

    op_defs: list[str] = []
    op_methods: list[str] = []
    dispatch_lines: list[str] = []
    seen: set[str] = set()
    for o in ops:
        if not isinstance(o, dict):
            continue
        suffix = _op_suffix(o)
        if not suffix:
            continue
        method = _ident(suffix)
        if method in seen:
            continue
        seen.add(method)
        kind = "action" if str(o.get("kind", "read")).lower() == "action" else "read"
        oplabel = (o.get("label") or suffix.replace("_", " ").title()).replace('"', "'")
        opdesc = (o.get("description") or "").replace('"', "'")
        full_id = f"{host}.{suffix}"
        op_defs.append(
            f'            ConnectorOp(\n'
            f'                op_id="{full_id}", host="{host}", kind="{kind}",\n'
            f'                label="{oplabel}", description="{opdesc}",\n'
            f'                inputs=[],\n'
            f'            ),'
        )
        op_methods.append(
            f'    def {method}(self, **params) -> OpResult:\n'
            f'        """{oplabel}. HONEST STUB — fill this in to talk to {label}.\n'
            f'        Returns an honest failure until implemented, never fabricated\n'
            f'        data (connectors.base contract)."""\n'
            f'        return OpResult.fail("{full_id} not implemented yet",'
            f' op_id="{full_id}")\n'
        )
        dispatch_lines.append(
            f'        if op_id in ("{full_id}", "{suffix}"):\n'
            f'            return self.{method}(**params)'
        )

    dispatch = "\n".join(dispatch_lines) or "        pass"

    src = f'''"""{label} connector — SCAFFOLDED by the self-extension loop.

{desc}

Subclasses the uniform `connectors.base.Connector` ABC. `probe()` reports HONEST
status (it starts "missing" — wire it to a real reachability check; it must
NEVER fake "live") and `build_ops()` lists the typed operations. Until an op's
body is filled in it returns an honest `OpResult.fail(...)` rather than
fabricated data (the connector-contract mandate). Registered via the SAME
`register(...)` call every other connector uses — `connectors.registry` + the
workflow runner pick it up with no special-casing.
"""
from __future__ import annotations

from typing import Optional

from connectors.base import (
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
    register,
)


class {cls}(Connector):
    host = "{host}"
    display_name = "{label}"
    mechanism = "{mechanism}"

    def probe(self) -> dict:
        """Honest reachability status. SCAFFOLD DEFAULT: 'missing' — replace
        with a real probe (TCP/HTTP/COM) once the host is wired. Never fake
        'live' (connectors.base honest-status rule)."""
        return {{"status": "missing",
                "note": "{label} connector scaffolded — probe not implemented yet",
                "detail": {{}}}}

    def build_ops(self) -> list:
        """The typed operations this connector exposes."""
        return [
{chr(10).join(op_defs)}
        ]

    def run(self, op_id: str, **params) -> OpResult:
        """Dispatch an op by id. Unknown op → honest failure."""
{dispatch}
        return OpResult.fail(f"unknown op '{{op_id}}' on {host}", op_id=op_id)

{chr(10).join(op_methods)}

# ── register at import time (same as every hand-written connector) ──────
register({cls}())
'''
    return host, src


def create_connector(spec: dict[str, Any], *, overwrite: bool = False) -> dict[str, Any]:
    """Write a base.py-contract connector module to app/connectors/ from `spec`.

    The REAL artifact writer the self-extension loop's `create_connector` build
    tool calls. Returns:
      {ok: True, host, path, class_name, op_count}                     on write
      {ok: False, exists: True, path, error}                           if present (no overwrite)
      {ok: False, error: <reason>}                                     on bad spec
    """
    try:
        host, src = render_connector(spec)
    except ValueError as ex:
        return {"ok": False, "error": str(ex)}
    path = connector_path(host)
    if path.exists() and not overwrite:
        return {"ok": False, "exists": True, "path": str(path),
                "error": f"connector for '{host}' already exists at {path.name}"}
    path.write_text(src, encoding="utf-8")
    cls = "".join(p.capitalize() for p in host.split("_")) + "Connector"
    return {"ok": True, "host": host, "path": str(path),
            "class_name": cls, "op_count": src.count("ConnectorOp(")}
