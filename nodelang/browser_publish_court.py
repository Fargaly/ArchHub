"""Trusted subprocess boundary for the theme publication browser court."""
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

from .cell_attestations import CourtEvidenceDenied, CourtInvocation, CourtResult


BROWSER_PUBLISH_CHECKS = (
    "page-identity",
    "meaningful-app-visible",
    "exact-theme-applied",
    "no-console-or-page-errors",
    "desktop-no-overflow",
    "mobile-no-overflow",
    "navigation-budget",
    "keyboard-focus",
    "accessible-control-names",
    "minimum-text-contrast",
)


def _admitted_playwright_module_path(raw_path: str) -> str | None:
    """Return a declared Playwright module root only when its manifest is valid."""
    for candidate in (item for item in raw_path.split(os.pathsep) if item):
        manifest = Path(candidate) / "playwright" / "package.json"
        try:
            package = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        entry = Path(candidate) / "playwright" / str(
            package.get("main", "index.js")
        )
        if (
            package.get("name") == "playwright"
            and isinstance(package.get("version"), str)
            and package["version"]
            and entry.is_file()
            and entry.stat().st_size > 0
        ):
            return str(Path(candidate).resolve())
    return None


def _run_pinned_node_script(
    node: str,
    script_path: Path,
    *,
    env: dict[str, str],
    timeout: int,
    creationflags: int,
) -> tuple[int, bytes, bytes]:
    """Run a court script without inherited capture pipes on Windows hosts."""
    with tempfile.TemporaryDirectory(prefix="archhub-browser-court-") as raw_dir:
        directory = Path(raw_dir)
        stdout_path = directory / "stdout.json"
        stderr_path = directory / "stderr.log"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(
                (node, str(script_path)),
                cwd=str(script_path.parent.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
                creationflags=creationflags,
            )
        return (
            completed.returncode,
            stdout_path.read_bytes(),
            stderr_path.read_bytes(),
        )


class BrowserPublishCourt:
    """Runs one pinned browser script against the configured local app."""

    def __init__(self) -> None:
        self.script_path = Path(__file__).with_name(
            "browser_publish_court.cjs"
        ).resolve()
        self.script_digest = hashlib.sha256(
            self.script_path.read_bytes()
        ).hexdigest()
        self._endpoint: str | None = None
        self._session_token: str | None = None
        self._lock = threading.RLock()

    @property
    def runner_version(self) -> str:
        return "1.0.0+sha256." + self.script_digest

    @property
    def endpoint(self) -> str | None:
        with self._lock:
            return self._endpoint

    def configure(self, endpoint: str, session_token: str) -> None:
        endpoint = str(endpoint).rstrip("/") + "/"
        if not endpoint.startswith("http://127.0.0.1:"):
            raise CourtEvidenceDenied(
                "browser publication court requires loopback HTTP"
            )
        if not session_token:
            raise CourtEvidenceDenied("browser court session token is missing")
        with self._lock:
            self._endpoint = endpoint
            self._session_token = str(session_token)

    def _runtime(self) -> tuple[str, str]:
        node = os.environ.get("ARCHHUB_NODE_EXECUTABLE") or shutil.which("node")
        project_modules = Path(__file__).resolve().parents[1] / "node_modules"
        module_path = _admitted_playwright_module_path(
            os.environ.get("ARCHHUB_NODE_MODULE_PATH")
            or str(project_modules)
        )
        if not node or not Path(node).is_file():
            raise CourtEvidenceDenied(
                "browser publication court has no admitted Node runtime"
            )
        if not module_path:
            raise CourtEvidenceDenied(
                "browser publication court has no valid declared Playwright dependency"
            )
        return str(Path(node).resolve()), module_path

    def run(self, invocation: CourtInvocation) -> CourtResult:
        current_script_digest = hashlib.sha256(
            self.script_path.read_bytes()
        ).hexdigest()
        if current_script_digest != self.script_digest:
            raise CourtEvidenceDenied(
                "browser publication court script has drifted"
            )
        with self._lock:
            endpoint = self._endpoint
            session_token = self._session_token
        if endpoint is None or session_token is None:
            raise CourtEvidenceDenied(
                "browser publication court is not attached to a running app"
            )
        if invocation.external_parameters.get("endpoint") != endpoint:
            raise CourtEvidenceDenied(
                "browser court invocation does not match its configured app"
            )
        try:
            theme = json.loads(invocation.subject_content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CourtEvidenceDenied(
                "browser court subject is not valid theme JSON"
            ) from exc
        if not isinstance(theme, dict):
            raise CourtEvidenceDenied("browser court theme is not an object")
        node, module_path = self._runtime()
        env = os.environ.copy()
        env.update({
            "NODE_PATH": module_path,
            "ARCHHUB_COURT_URL": endpoint,
            "ARCHHUB_COURT_SESSION": session_token,
            "ARCHHUB_COURT_THEME": json.dumps(
                theme, sort_keys=True, separators=(",", ":")
            ),
            "ARCHHUB_COURT_SUBJECT_DIGEST": invocation.subject_digest,
        })
        chrome = os.environ.get("ARCHHUB_CHROME_EXECUTABLE")
        if chrome:
            env["ARCHHUB_CHROME_EXECUTABLE"] = chrome
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        returncode, stdout, stderr = _run_pinned_node_script(
            node,
            self.script_path,
            env=env,
            timeout=60,
            creationflags=flags,
        )
        if returncode != 0:
            message = stderr.decode("utf-8", "replace")[-1000:]
            raise CourtEvidenceDenied(
                "browser publication court runner failed: " + message
            )
        try:
            report = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CourtEvidenceDenied(
                "browser publication court returned invalid evidence"
            ) from exc
        checks = report.get("checks")
        details = report.get("details")
        if not isinstance(checks, dict) or set(checks) != set(
            BROWSER_PUBLISH_CHECKS
        ):
            raise CourtEvidenceDenied(
                "browser publication court returned the wrong check set"
            )
        if not isinstance(details, dict):
            raise CourtEvidenceDenied(
                "browser publication court returned invalid details"
            )
        normalized_checks = {
            name: checks[name] is True for name in BROWSER_PUBLISH_CHECKS
        }
        return CourtResult(
            all(normalized_checks.values()),
            MappingProxyType(normalized_checks),
            MappingProxyType({
                str(key): json.dumps(value, sort_keys=True)
                if not isinstance(value, str) else value
                for key, value in sorted(details.items())
            }),
        )


__all__ = ["BROWSER_PUBLISH_CHECKS", "BrowserPublishCourt"]
