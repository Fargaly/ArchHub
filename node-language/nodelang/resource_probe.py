"""Read-only host-boundary probes for generic external resources.

The graph owns resource identity, policy, ports, lineage, and control. This
module only resolves machine-local aliases and observes the external payload
host. Resolved private paths and response bodies never enter graph values.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def _workspace_root() -> Path:
    configured = os.environ.get("ARCHHUB_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _resolve_alias(locator: str) -> Path | None:
    if locator.startswith("workspace://"):
        relative = locator[len("workspace://"):].replace("/", os.sep)
        root = _workspace_root()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate
    if locator == "authority://grand-map":
        from .map_import import resolve_map_path
        return resolve_map_path()
    if locator == "authority://private-knowledge":
        from .map_import import load_local_authority_config
        configured = str(load_local_authority_config().get("private_knowledge_path") or "").strip()
        return Path(configured).expanduser().resolve() if configured else None
    return None


def _result(ok: bool, locator: str, detail: str, **extra):
    value = {
        "ok": bool(ok),
        "kind": "resource",
        "locator": locator,
        "detail": detail,
    }
    value.update(extra)
    return value


def run_resource_probe(spec):
    """Observe one resource without returning payload data or private paths."""
    spec = dict(spec or {})
    locator = str(spec.get("locator") or "").strip()
    if not locator:
        return _result(False, locator, "resource locator is missing")

    alias = _resolve_alias(locator)
    if alias is not None:
        exists = alias.exists()
        expected = str(spec.get("expected") or "any")
        if exists and expected == "file":
            exists = alias.is_file()
        elif exists and expected == "directory":
            exists = alias.is_dir()
        elif exists and expected == "repository":
            exists = alias.is_dir() and (alias / ".git").exists()
        return _result(exists, locator, "resource exists" if exists else "resource is missing",
                       expected=expected)

    parsed = urlparse(locator)
    if parsed.scheme in ("http", "https"):
        try:
            payload = spec.get("json")
            data = (json.dumps(payload, separators=(",", ":")).encode("utf-8")
                    if payload is not None else None)
            headers = dict(spec.get("headers") or {})
            if data is not None:
                headers.setdefault("Content-Type", "application/json")
            request = urllib.request.Request(
                locator, data=data, method=str(spec.get("method") or "GET"),
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=float(spec.get("timeout") or 3.0)) as response:
                code = int(response.getcode())
                body = response.read(16384).decode("utf-8", "replace")
            wanted = int(spec.get("status") or 200)
            marker = str(spec.get("contains") or "")
            marker_ok = not marker or marker in body
            response_path = spec.get("response_path")
            path_ok = True
            if response_path is not None:
                path_ok = False
                try:
                    value = json.loads(body)
                    for key in response_path:
                        value = value[key] if isinstance(value, dict) else value[int(key)]
                    path_ok = value == spec.get("expected_value")
                except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
                    path_ok = False
            return _result(code == wanted and marker_ok and path_ok, locator,
                           "HTTP %d%s" % (code, " with marker" if marker_ok and marker else ""),
                           observed_status=code, expected_status=wanted,
                           marker_required=bool(marker), marker_observed=marker_ok,
                           response_predicate_required=response_path is not None,
                           response_predicate_observed=path_ok)
        except urllib.error.HTTPError as error:
            wanted = int(spec.get("status") or 200)
            return _result(error.code == wanted, locator, "HTTP %d" % error.code,
                           observed_status=error.code, expected_status=wanted)
        except Exception as error:
            return _result(False, locator, "unreachable: %s" % type(error).__name__)

    if parsed.scheme in ("service", "provider", "database", "storage"):
        configured = bool(spec.get("configured"))
        evidence = str(spec.get("evidence") or "").strip()
        ok = configured and bool(evidence)
        return _result(ok, locator,
                       "configured with evidence" if ok else "external adapter not connected")

    if parsed.scheme == "authority":
        return _result(False, locator, "machine-local authority alias is not configured")
    return _result(False, locator, "unsupported resource locator scheme")


__all__ = ["run_resource_probe"]
