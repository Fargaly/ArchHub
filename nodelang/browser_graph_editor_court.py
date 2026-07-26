"""Trusted real-browser acceptance court for the Universal graph editor."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import MappingProxyType

from .browser_publish_court import (
    _admitted_playwright_module_path,
    _run_pinned_node_script,
)
from .cell_attestations import CourtEvidenceDenied, CourtResult


BROWSER_GRAPH_EDITOR_CHECKS = (
    "page-identity",
    "canvas-has-real-nodes-and-wires",
    "selection-projects-properties",
    "property-edit-updates-node",
    "keyboard-undo-redo",
    "presentation-color-updates-node",
    "multi-selection",
    "modifier-selection-and-deselection",
    "group-and-ungroup-preserve-members",
    "directional-marquee",
    "modifier-marquee-selection-and-deselection",
    "wheel-zoom",
    "space-pan",
    "wire-selects-relation",
    "scope-navigation",
    "library-search-is-local-and-usable",
    "library-placement",
    "visual-parameter-creation",
    "inspector-build-lens",
    "inspector-tabs-operational",
    "visual-interface-creation",
    "visual-input-interface-creation",
    "socket-wire-creation",
    "mutation-acknowledgements-within-budget",
    "scope-entry-within-budget",
    "no-failed-governed-responses",
    "no-console-or-page-errors",
)


def _admitted_editor_screenshot_directory(value: str) -> str:
    """Admit disposable screenshots only beneath the operating-system temp root."""
    target = Path(value).expanduser().resolve(strict=False)
    temp_root = Path(tempfile.gettempdir()).resolve()
    workspace_root = Path(__file__).resolve().parents[3]
    try:
        target.relative_to(temp_root)
    except ValueError as exc:
        raise CourtEvidenceDenied(
            "graph editor screenshots must stay beneath the OS temp directory"
        ) from exc
    if target == temp_root:
        raise CourtEvidenceDenied(
            "graph editor screenshots require a dedicated temp subdirectory"
        )
    try:
        target.relative_to(workspace_root)
    except ValueError:
        pass
    else:
        raise CourtEvidenceDenied(
            "graph editor screenshots must stay outside the workspace"
        )
    if target.exists() and not target.is_dir():
        raise CourtEvidenceDenied(
            "graph editor screenshot destination is not a directory"
        )
    return str(target)


class BrowserGraphEditorCourt:
    """Run the graph-editor acceptance suite against one isolated loopback app."""

    def __init__(self) -> None:
        self.script_path = Path(__file__).with_name(
            "browser_graph_editor_court.cjs"
        ).resolve()
        self.script_digest = hashlib.sha256(self.script_path.read_bytes()).hexdigest()
        self._endpoint: str | None = None
        self._session_token: str | None = None
        self._lock = threading.RLock()

    @property
    def runner_version(self) -> str:
        return "1.0.0+sha256." + self.script_digest

    def configure(self, endpoint: str, session_token: str) -> None:
        endpoint = str(endpoint).rstrip("/") + "/"
        if not endpoint.startswith("http://127.0.0.1:"):
            raise CourtEvidenceDenied("graph editor court requires loopback HTTP")
        if not session_token:
            raise CourtEvidenceDenied("graph editor court session token is missing")
        with self._lock:
            self._endpoint = endpoint
            self._session_token = str(session_token)

    def _runtime(self) -> tuple[str, str]:
        node = os.environ.get("ARCHHUB_NODE_EXECUTABLE") or shutil.which("node")
        project_modules = Path(__file__).resolve().parents[1] / "node_modules"
        module_path = _admitted_playwright_module_path(
            os.environ.get("ARCHHUB_NODE_MODULE_PATH") or str(project_modules)
        )
        if not node or not Path(node).is_file():
            raise CourtEvidenceDenied("graph editor court has no admitted Node runtime")
        if not module_path:
            raise CourtEvidenceDenied(
                "graph editor court has no valid declared Playwright dependency"
            )
        return str(Path(node).resolve()), module_path

    def run(self) -> CourtResult:
        digest = hashlib.sha256(self.script_path.read_bytes()).hexdigest()
        if digest != self.script_digest:
            raise CourtEvidenceDenied("graph editor court script has drifted")
        with self._lock:
            endpoint = self._endpoint
            session_token = self._session_token
        if endpoint is None or session_token is None:
            raise CourtEvidenceDenied("graph editor court is not attached to a running app")
        node, module_path = self._runtime()
        env = os.environ.copy()
        env.update({
            "NODE_PATH": module_path,
            "ARCHHUB_COURT_URL": endpoint,
            "ARCHHUB_COURT_SESSION": session_token,
        })
        screenshot_directory = env.get("ARCHHUB_EDITOR_COURT_SCREENSHOT_DIR")
        if screenshot_directory:
            env["ARCHHUB_EDITOR_COURT_SCREENSHOT_DIR"] = (
                _admitted_editor_screenshot_directory(screenshot_directory)
            )
        chrome = os.environ.get("ARCHHUB_CHROME_EXECUTABLE")
        if chrome:
            env["ARCHHUB_CHROME_EXECUTABLE"] = chrome
        returncode, stdout, stderr = _run_pinned_node_script(
            node,
            self.script_path,
            env=env,
            timeout=150,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if returncode != 0:
            message = stderr.decode("utf-8", "replace")[-1500:]
            raise CourtEvidenceDenied("graph editor court runner failed: " + message)
        try:
            report = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CourtEvidenceDenied("graph editor court returned invalid evidence") from exc
        checks = report.get("checks")
        details = report.get("details")
        if not isinstance(checks, dict) or set(checks) != set(BROWSER_GRAPH_EDITOR_CHECKS):
            raise CourtEvidenceDenied("graph editor court returned the wrong check set")
        if not isinstance(details, dict):
            raise CourtEvidenceDenied("graph editor court returned invalid details")
        normalized = {name: checks[name] is True for name in BROWSER_GRAPH_EDITOR_CHECKS}
        return CourtResult(
            all(normalized.values()),
            MappingProxyType(normalized),
            MappingProxyType({
                str(key): value if isinstance(value, str)
                else json.dumps(value, sort_keys=True)
                for key, value in sorted(details.items())
            }),
        )


__all__ = ["BROWSER_GRAPH_EDITOR_CHECKS", "BrowserGraphEditorCourt"]
