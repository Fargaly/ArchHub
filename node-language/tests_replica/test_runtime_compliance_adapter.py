from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from nodelang.runtime_compliance_adapter import (
    RUNTIME_COMPLIANCE_CHECKS,
    run_physical_runtime_compliance_court,
)


def _install_observer(monkeypatch, observation):
    package = ModuleType("personal_brain")
    package.__path__ = []
    module = ModuleType("personal_brain.hook_coverage")
    module.observe_runtime_compliance = lambda _runtime: observation
    monkeypatch.setitem(sys.modules, "personal_brain", package)
    monkeypatch.setitem(sys.modules, "personal_brain.hook_coverage", module)


def test_physical_adapter_projects_exact_checks_without_granting_authority(
    monkeypatch,
):
    checks = {name: True for name in RUNTIME_COMPLIANCE_CHECKS}
    _install_observer(monkeypatch, {
        "client": "codex",
        "status": "green",
        "checks": checks,
        "issue_count": 0,
    })

    result = run_physical_runtime_compliance_court(
        SimpleNamespace(external_parameters={"runtime": "codex-desktop"})
    )

    assert result.passed is True
    assert result.checks == checks
    assert result.details["client"] == "codex"


def test_physical_adapter_fails_closed_on_invalid_observation(monkeypatch):
    _install_observer(monkeypatch, {"checks": {"runtime-detected": True}})

    result = run_physical_runtime_compliance_court(
        SimpleNamespace(external_parameters={"runtime": "codex-desktop"})
    )

    assert result.passed is False
    assert result.checks == {
        name: False for name in RUNTIME_COMPLIANCE_CHECKS
    }
    assert result.details["status"] == "red"
