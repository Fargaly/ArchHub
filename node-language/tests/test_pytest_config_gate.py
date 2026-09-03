"""TCI-03 gate — a root pytest config exists and encodes the blessed contract.

Before this gate, the repo had NO root pytest.ini / pyproject / setup.cfg /
tox.ini, so the ignore-set + testpaths + asyncio mode + marker policy were
passed ad-hoc on every CI command. That let the required gate and the blessed
dev command drift apart (REPO-MAP 2026-05-28 §8) and let a typo'd
`@pytest.mark.<typo>` silently no-op (no --strict-markers anywhere), so a test
could mark itself out of the run and still look green.

This test pins the fix: `pyproject.toml` at the repo root carries
`[tool.pytest.ini_options]` whose `addopts` encodes the ignore-set AND
`--strict-markers`, with `testpaths` naming the two app suites. It is RED on
origin/main (the file does not exist) and GREEN once the config is committed.

It loads the TOML directly (no pytest internals) so it asserts the on-disk
contract, not whatever config the current session happens to have resolved.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# tomllib is stdlib on 3.11+; the repo's CI + dev interpreters are 3.13/3.14.
try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - only on <3.11
    tomllib = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"
BRAIN_PYPROJECT = REPO_ROOT / "personal-brain-mcp" / "pyproject.toml"


def _load_pytest_config(path: Path) -> dict:
    assert tomllib is not None, "tomllib unavailable — interpreter older than 3.11"
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tool", {}).get("pytest", {}).get("ini_options", {})


def _addopts_str(cfg: dict) -> str:
    """addopts may be a string or a list of strings; normalise to one string."""
    addopts = cfg.get("addopts", "")
    if isinstance(addopts, (list, tuple)):
        return " ".join(str(x) for x in addopts)
    return str(addopts)


def test_root_pytest_config_file_exists():
    """A single root pytest config exists (this is the whole point of TCI-03)."""
    assert ROOT_PYPROJECT.is_file(), (
        "no root pyproject.toml — pytest config is passed ad-hoc per CI command; "
        "TCI-03 requires one blessed root config"
    )
    cfg = _load_pytest_config(ROOT_PYPROJECT)
    assert cfg, (
        "root pyproject.toml has no [tool.pytest.ini_options] table — the "
        "ignore-set / markers / testpaths are still not pinned in one place"
    )


def test_root_addopts_has_strict_markers():
    """--strict-markers must be in addopts so a typo'd mark ERRORS, not no-ops."""
    cfg = _load_pytest_config(ROOT_PYPROJECT)
    assert "--strict-markers" in _addopts_str(cfg), (
        "addopts lacks --strict-markers — a typo'd @pytest.mark.<x> would "
        "silently skip the test and still look green (the TCI-03 failure mode)"
    )


def test_root_addopts_encodes_ignore_set():
    """addopts encodes the blessed live-Qt ignore-set (matches CLAUDE.md +
    daily-audit.yml) so bare `pytest` runs the same set CI runs."""
    addopts = _addopts_str(_load_pytest_config(ROOT_PYPROJECT))
    for ignored in ("tests/test_bridge_qt.py", "tests/test_ui_smoke.py"):
        assert f"--ignore={ignored}" in addopts, (
            f"addopts is missing --ignore={ignored}; the root config must carry "
            f"the blessed ignore-set so the gate and the dev command can't drift"
        )


def test_root_testpaths_cover_app_and_cloud_suites():
    """testpaths names the two suites the cross-platform gate runs, so a bare
    `pytest` collects exactly the CI set."""
    cfg = _load_pytest_config(ROOT_PYPROJECT)
    testpaths = cfg.get("testpaths", [])
    assert "tests" in testpaths, "testpaths must include the app 'tests' suite"
    assert "cloud_backend/tests" in testpaths, (
        "testpaths must include the cloud_backend/tests suite"
    )


def test_brain_pyproject_has_strict_markers_too():
    """The brain suite carries its OWN strict-markers contract so
    `cd personal-brain-mcp && pytest` is self-describing and doesn't depend on
    ad-hoc flags either."""
    cfg = _load_pytest_config(BRAIN_PYPROJECT)
    assert cfg, (
        "personal-brain-mcp/pyproject.toml has no [tool.pytest.ini_options] — "
        "the brain CI command still relies on ad-hoc flags"
    )
    assert "--strict-markers" in _addopts_str(cfg), (
        "brain pyproject addopts lacks --strict-markers"
    )
