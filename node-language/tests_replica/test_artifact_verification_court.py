from pathlib import Path
import tomllib

import pytest

from nodelang.artifact_verification_court import ArtifactVerificationCourt


def test_court_subprocess_preserves_only_required_windows_local_app_data(
    monkeypatch, tmp_path
):
    local_app_data = str(tmp_path / "LocalAppData")
    monkeypatch.setenv("LOCALAPPDATA", local_app_data)
    monkeypatch.setenv("ARCHHUB_UNADMITTED_ENVIRONMENT", "must-not-cross")

    environment = ArtifactVerificationCourt._subprocess_environment()

    assert environment["LOCALAPPDATA"] == local_app_data
    assert "ARCHHUB_UNADMITTED_ENVIRONMENT" not in environment
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONSAFEPATH"] == "1"


def test_node_language_declares_its_pytest_import_root():
    project_root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["tool"]["pytest"]["ini_options"]["pythonpath"] == [
        "."
    ]


def test_restricted_court_runs_a_nested_project_from_governed_configuration(
    monkeypatch, tmp_path
):
    project = tmp_path / "product" / "node-language"
    package = project / "sample_nodes"
    tests = project / "tests"
    package.mkdir(parents=True)
    tests.mkdir()
    (project / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["."]\n',
        encoding="utf-8",
    )
    (package / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    target = tests / "test_nodes.py"
    target.write_text(
        "from sample_nodes import VALUE\n\n"
        "def test_current_project_package_is_loaded():\n"
        "    assert VALUE == 42\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PYTHONPATH", raising=False)
    court = ArtifactVerificationCourt(tmp_path)
    scope = court._scope_roots({
        "allowed_paths": ["product/node-language/tests/test_nodes.py"]
    })

    passed, detail = court._execute(
        {
            "kind": "pytest",
            "spec": {
                "path": "product/node-language/tests/test_nodes.py",
                "args": [],
                "timeout_seconds": 30,
            },
        },
        scope,
    )

    assert passed is True
    assert detail == "pytest"


def _multi_selector_project(tmp_path):
    project = tmp_path / "product" / "node-language"
    package = project / "sample_nodes"
    tests = project / "tests"
    package.mkdir(parents=True)
    tests.mkdir()
    (project / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["."]\n',
        encoding="utf-8",
    )
    (package / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    first = tests / "test_first.py"
    second = tests / "test_second.py"
    first.write_text(
        "from sample_nodes import VALUE\n\n"
        "def test_first_value():\n"
        "    assert VALUE == 42\n",
        encoding="utf-8",
    )
    second.write_text(
        "from sample_nodes import VALUE\n\n"
        "def test_second_value():\n"
        "    assert VALUE * 2 == 84\n",
        encoding="utf-8",
    )
    return project, first, second


def test_restricted_court_runs_every_graph_declared_pytest_selector(tmp_path):
    _project, first, second = _multi_selector_project(tmp_path)
    court = ArtifactVerificationCourt(tmp_path)
    scope = court._scope_roots({
        "allowed_paths": [
            first.relative_to(tmp_path).as_posix(),
            second.relative_to(tmp_path).as_posix(),
        ]
    })

    passed, detail = court._execute(
        {
            "kind": "pytest",
            "spec": {
                "path": "product/node-language",
                "selectors": ["tests/test_first.py", "tests/test_second.py"],
                "args": [],
                "timeout_seconds": 30,
            },
        },
        scope,
    )

    assert passed is True
    assert detail == "pytest"


@pytest.mark.parametrize("selectors", [[], ["../outside.py"]])
def test_multi_selector_pytest_gate_rejects_empty_or_escaping_targets(
    tmp_path, selectors
):
    _project, first, second = _multi_selector_project(tmp_path)
    court = ArtifactVerificationCourt(tmp_path)
    scope = court._scope_roots({
        "allowed_paths": [
            first.relative_to(tmp_path).as_posix(),
            second.relative_to(tmp_path).as_posix(),
        ]
    })

    with pytest.raises(ValueError):
        court._execute(
            {
                "kind": "pytest",
                "spec": {
                    "path": "product/node-language",
                    "selectors": selectors,
                    "args": [],
                },
            },
            scope,
        )


def test_multi_selector_pytest_gate_rejects_a_single_unscoped_target(tmp_path):
    project, first, second = _multi_selector_project(tmp_path)
    unscoped = project / "tests" / "test_unscoped.py"
    unscoped.write_text("def test_unscoped():\n    assert True\n", encoding="utf-8")
    court = ArtifactVerificationCourt(tmp_path)
    scope = court._scope_roots({
        "allowed_paths": [
            first.relative_to(tmp_path).as_posix(),
            second.relative_to(tmp_path).as_posix(),
        ]
    })

    with pytest.raises(ValueError, match="outside the work CDE"):
        court._execute(
            {
                "kind": "pytest",
                "spec": {
                    "path": "product/node-language",
                    "selectors": ["tests/test_first.py", "tests/test_unscoped.py"],
                    "args": [],
                },
            },
            scope,
        )
