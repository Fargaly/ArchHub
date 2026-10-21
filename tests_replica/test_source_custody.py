"""Public-source custody courts for the Node Language authority."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "evidence" / "build_source_custody_manifest.py"

SPEC = importlib.util.spec_from_file_location("source_custody_manifest", BUILDER_PATH)
assert SPEC and SPEC.loader
custody = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(custody)


def test_public_source_manifest_regenerates_from_portable_source(tmp_path, monkeypatch):
    monkeypatch.setattr(custody, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text("# Public source\n", encoding="utf-8")
    recorded = custody.build_manifest()
    assert recorded == custody.build_manifest()
    assert recorded["authority"] == "evidence-only"
    assert recorded["custody"] == "T0_PUBLIC"
    assert recorded["file_count"] == len(recorded["files"])
    assert len(recorded["tree_sha256"]) == 64


def test_private_grand_map_input_is_explicit_and_machine_portable(monkeypatch):
    monkeypatch.delenv("ARCHHUB_GRAND_MAP_PATH", raising=False)
    monkeypatch.delenv("ARCHHUB_WORKSPACE_ROOT", raising=False)

    from tools import reality_grade, serve_grandmap

    with pytest.raises(RuntimeError, match="ARCHHUB_GRAND_MAP_PATH"):
        serve_grandmap._grand_map_path()
    with pytest.raises(RuntimeError, match="ARCHHUB_WORKSPACE_ROOT"):
        reality_grade._private_inputs()


def test_nested_repository_and_generated_outputs_are_not_admitted(tmp_path, monkeypatch):
    monkeypatch.setattr(custody, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text("# Public source\n", encoding="utf-8")
    for folder in (".git", "build", "node_modules"):
        target = tmp_path / folder
        target.mkdir()
        (target / "generated.txt").write_text("excluded\n", encoding="utf-8")
    admitted = {
        entry["path"]
        for entry in custody.build_manifest()["files"]
    }
    assert not any("/.git/" in f"/{path}/" for path in admitted)
    assert not any(
        part in custody.EXCLUDED_PARTS
        for path in admitted
        for part in Path(path).parts
    )


def test_explicit_local_only_exclusions_match_git_custody():
    ignored = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert custody.EXCLUDED_RELATIVE_PATHS <= ignored
    assert custody.EXCLUDED_PREFIXES <= ignored


def test_cross_device_git_normalization_is_pinned():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert attributes[:2] == [
        "* text=auto eol=lf",
        "*.png binary",
    ]
