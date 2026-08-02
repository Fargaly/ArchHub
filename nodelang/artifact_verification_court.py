"""Allowlisted physical-artifact verification for graph-declared courts.

The work graph supplies the gate and CDE boundary.  This module is the narrow
physical adapter that reads files or invokes an admitted test runner.  It does
not accept free-form commands and never invokes a shell.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import MappingProxyType

from .cell_attestations import CourtInvocation, CourtResult


ARTIFACT_VERIFICATION_CHECKS = (
    "subject-digest",
    "work-binding",
    "workspace-boundary",
    "gate-schema",
    "gate-execution",
)

_GATE_KINDS = frozenset((
    "file_exists", "grep_clean", "pytest", "py_compile",
))
_PYTEST_FLAGS = frozenset((
    "-q", "-x", "--disable-warnings", "--strict-config", "--strict-markers",
))
_SELECTOR = re.compile(r"^[A-Za-z0-9_./\\:-]+$")


class ArtifactVerificationCourt:
    """Execute one bounded gate beneath one fixed workspace root."""

    def __init__(self, workspace_root: str | os.PathLike[str]) -> None:
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("artifact court workspace root is unavailable")
        self.workspace_root = root

    @staticmethod
    def _document(invocation: CourtInvocation) -> dict[str, object] | None:
        try:
            value = json.loads(invocation.subject_content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if type(value) is dict else None

    def _scope_roots(self, cde: object) -> tuple[Path, ...]:
        if type(cde) is not dict:
            raise ValueError("CDE scope is missing")
        allowed = cde.get("allowed_paths")
        if type(allowed) is not list or not allowed or len(allowed) > 128:
            raise ValueError("CDE allowed paths are missing or unbounded")
        roots = []
        for raw in allowed:
            if type(raw) is not str or not raw or len(raw) > 512:
                raise ValueError("CDE path is invalid")
            relative = Path(raw.replace("/", os.sep))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("CDE path escapes the workspace")
            resolved = (self.workspace_root / relative).resolve()
            if not resolved.is_relative_to(self.workspace_root):
                raise ValueError("CDE path escapes the workspace")
            roots.append(resolved)
        return tuple(dict.fromkeys(roots))

    def _target(
        self,
        raw: object,
        scope_roots: tuple[Path, ...],
        *,
        selector: bool = False,
    ) -> tuple[Path, str]:
        if type(raw) is not str or not raw or len(raw) > 1024:
            raise ValueError("gate path is invalid")
        path_text, marker, suffix = raw.partition("::") if selector else (raw, "", "")
        if not _SELECTOR.fullmatch(raw):
            raise ValueError("gate path contains unadmitted characters")
        relative = Path(path_text.replace("/", os.sep))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("gate path escapes the workspace")
        resolved = (self.workspace_root / relative).resolve()
        if not resolved.is_relative_to(self.workspace_root):
            raise ValueError("gate path escapes the workspace")
        if not any(resolved.is_relative_to(root) for root in scope_roots):
            raise ValueError("gate path is outside the work CDE")
        normalized = resolved.relative_to(self.workspace_root).as_posix()
        if marker:
            normalized += "::" + suffix
        return resolved, normalized

    @staticmethod
    def _subprocess_environment() -> dict[str, str]:
        admitted = {
            "LOCALAPPDATA", "PATH", "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT",
            "TEMP", "TMP", "USERPROFILE", "WINDIR",
        }
        environment = {
            key: value for key, value in os.environ.items()
            if key.upper() in admitted
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONSAFEPATH"] = "1"
        return environment

    def _execute(
        self,
        gate: dict[str, object],
        scope_roots: tuple[Path, ...],
    ) -> tuple[bool, str]:
        kind = gate["kind"]
        spec = gate["spec"]
        if kind == "file_exists":
            target, _ = self._target(spec.get("path"), scope_roots)
            return target.exists(), "file_exists"
        if kind == "grep_clean":
            pattern = spec.get("pattern")
            paths = spec.get("paths")
            if (
                type(pattern) is not str
                or not pattern
                or len(pattern) > 4096
                or type(paths) is not list
                or not paths
                or len(paths) > 256
            ):
                raise ValueError("grep gate schema is invalid")
            expression = re.compile(pattern)
            for raw in paths:
                target, _ = self._target(raw, scope_roots)
                if not target.is_file() or target.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("grep target is missing or too large")
                if expression.search(
                    target.read_text(encoding="utf-8", errors="ignore")
                ):
                    return False, "grep_clean"
            return True, "grep_clean"
        if kind == "py_compile":
            target, _ = self._target(spec.get("path"), scope_roots)
            if target.suffix.casefold() != ".py" or not target.is_file():
                raise ValueError("compile target is not a Python file")
            try:
                compile(
                    target.read_text(encoding="utf-8"),
                    str(target),
                    "exec",
                    dont_inherit=True,
                )
            except (SyntaxError, UnicodeDecodeError):
                return False, "py_compile"
            return True, "py_compile"
        if kind == "pytest":
            target, selector = self._target(
                spec.get("path"), scope_roots, selector=True
            )
            if not target.exists():
                raise ValueError("pytest target is missing")
            raw_args = spec.get("args", [])
            if type(raw_args) is not list or len(raw_args) > 8:
                raise ValueError("pytest arguments are invalid")
            args = []
            for value in raw_args:
                if type(value) is not str or (
                    value not in _PYTEST_FLAGS
                    and not re.fullmatch(r"--maxfail=[1-9][0-9]?", value)
                ):
                    raise ValueError("pytest argument is outside the allowlist")
                args.append(value)
            timeout = spec.get("timeout_seconds", 300)
            if type(timeout) not in (int, float) or not 1 <= float(timeout) <= 600:
                raise ValueError("pytest timeout is outside the admitted bound")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", selector, *args],
                    cwd=str(self.workspace_root),
                    env=self._subprocess_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=float(timeout),
                    shell=False,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return False, "pytest-timeout"
            return result.returncode == 0, "pytest"
        raise ValueError("gate kind is outside the allowlist")

    def run(self, invocation: CourtInvocation) -> CourtResult:
        document = self._document(invocation)
        checks = {name: False for name in ARTIFACT_VERIFICATION_CHECKS}
        detail = "invalid-subject"
        checks["subject-digest"] = hashlib.sha256(
            invocation.subject_content
        ).hexdigest() == invocation.subject_digest
        if document is not None:
            checks["work-binding"] = all(
                document.get(field) == invocation.external_parameters.get(parameter)
                for field, parameter in (
                    ("work_root", "workRoot"),
                    ("agent_session", "agentSession"),
                    ("submit_event", "submitEvent"),
                    ("artifact_evidence_digest", "artifactEvidenceDigest"),
                    ("workspace_digest", "workspaceDigest"),
                )
            )
            try:
                scope_roots = self._scope_roots(document.get("cde"))
                expected_workspace_digest = hashlib.sha256(
                    str(self.workspace_root).casefold().encode("utf-8")
                ).hexdigest()
                checks["workspace-boundary"] = (
                    document.get("workspace_digest")
                    == expected_workspace_digest
                    == invocation.external_parameters.get("workspaceDigest")
                )
                requirements = document.get("requirements")
                gate = requirements.get("gate") if type(requirements) is dict else None
                if (
                    type(gate) is dict
                    and set(gate) == {"kind", "spec"}
                    and gate.get("kind") in _GATE_KINDS
                    and type(gate.get("spec")) is dict
                ):
                    checks["gate-schema"] = True
                    passed, detail = self._execute(gate, scope_roots)
                    checks["gate-execution"] = passed
            except (OSError, re.error, ValueError) as exc:
                detail = type(exc).__name__
        return CourtResult(
            all(checks.values()),
            MappingProxyType(checks),
            MappingProxyType({
                "gate": detail,
                "subjectDigest": invocation.subject_digest,
            }),
        )


__all__ = ["ARTIFACT_VERIFICATION_CHECKS", "ArtifactVerificationCourt"]
