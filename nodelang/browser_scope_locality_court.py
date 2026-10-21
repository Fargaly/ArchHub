"""Trusted real-browser court for bounded session-scope locality."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from types import MappingProxyType

from .browser_publish_court import (
    _admitted_playwright_module_path,
    _run_pinned_node_script,
)
from .cell_attestations import CourtEvidenceDenied, CourtResult


BROWSER_SCOPE_LOCALITY_CHECKS = (
    "scope-entry-functional",
    "scope-entry-does-not-request-full-canvas",
    "scope-entry-does-not-submit-noop-gesture",
    "scope-interaction-is-not-blocked-by-pointerup-mutations",
    "scope-response-carries-exact-authorised-revision",
)


class BrowserScopeLocalityCourt:
    """Trace one isolated double-click through the real application artifact."""

    def __init__(self) -> None:
        self.script_path = Path(__file__).with_name(
            "browser_scope_locality_court.cjs"
        ).resolve()
        self.script_digest = hashlib.sha256(self.script_path.read_bytes()).hexdigest()
        self._endpoint: str | None = None
        self._session_token: str | None = None
        self._lock = threading.RLock()

    def configure(self, endpoint: str, session_token: str) -> None:
        endpoint = str(endpoint).rstrip("/") + "/"
        if not endpoint.startswith("http://127.0.0.1:"):
            raise CourtEvidenceDenied("scope locality court requires loopback HTTP")
        if not session_token:
            raise CourtEvidenceDenied("scope locality court session token is missing")
        with self._lock:
            self._endpoint = endpoint
            self._session_token = str(session_token)

    def run(self) -> CourtResult:
        if hashlib.sha256(self.script_path.read_bytes()).hexdigest() != (
            self.script_digest
        ):
            raise CourtEvidenceDenied("scope locality court script has drifted")
        with self._lock:
            endpoint = self._endpoint
            session_token = self._session_token
        if endpoint is None or session_token is None:
            raise CourtEvidenceDenied("scope locality court is not configured")
        node = os.environ.get("ARCHHUB_NODE_EXECUTABLE") or shutil.which("node")
        module_path = _admitted_playwright_module_path(
            os.environ.get("ARCHHUB_NODE_MODULE_PATH")
            or str(Path(__file__).resolve().parents[1] / "node_modules")
        )
        if not node or not Path(node).is_file() or not module_path:
            raise CourtEvidenceDenied("scope locality court runtime is unavailable")
        env = os.environ.copy()
        env.update({
            "NODE_PATH": module_path,
            "ARCHHUB_COURT_URL": endpoint,
            "ARCHHUB_COURT_SESSION": session_token,
        })
        returncode, stdout, stderr = _run_pinned_node_script(
            str(Path(node).resolve()),
            self.script_path,
            env=env,
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if returncode != 0:
            raise CourtEvidenceDenied(
                "scope locality court runner failed: "
                + stderr.decode("utf-8", "replace")[-1500:]
            )
        try:
            report = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CourtEvidenceDenied(
                "scope locality court returned invalid evidence"
            ) from exc
        checks = report.get("checks")
        details = report.get("details")
        if (
            not isinstance(checks, dict)
            or set(checks) != set(BROWSER_SCOPE_LOCALITY_CHECKS)
            or not isinstance(details, dict)
        ):
            raise CourtEvidenceDenied("scope locality court evidence is malformed")
        normalized = {
            name: checks[name] is True for name in BROWSER_SCOPE_LOCALITY_CHECKS
        }
        return CourtResult(
            all(normalized.values()),
            MappingProxyType(normalized),
            MappingProxyType({
                str(key): value if isinstance(value, str)
                else json.dumps(value, sort_keys=True)
                for key, value in sorted(details.items())
            }),
        )


__all__ = ["BROWSER_SCOPE_LOCALITY_CHECKS", "BrowserScopeLocalityCourt"]
