"""A court never writes into a real workspace to open the Workshop gate.

2026-10-01: six application_machine_transport courts, run out of tree, tried to
write court-gate-source-*.txt into the root of the founder's workspace (the
server's default universal_workspace_root, resolve_map_path().parents[3]) and
failed only because that root denies writes. _court_source now writes only
inside a temporary directory and otherwise stops, naming the fix.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import nodelang.universal_application as app
from tests_replica.workshop_gate_support import _court_source


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def test_a_temporary_workspace_gets_the_small_source_file_and_nothing_else(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    name = _court_source(workspace, "temp-court")
    assert name == "court-gate-source-temp-court.txt"
    assert listing(tmp_path) == {"ws", "ws/court-gate-source-temp-court.txt"}


def test_a_workspace_that_is_not_temporary_is_refused_and_left_untouched(tmp_path, monkeypatch):
    # A stand-in for the founder's tree: real, outside the temp dir, not holding the code.
    other_temp = tmp_path / "the-temp-dir"
    real_tree = tmp_path / "founder-workspace"
    other_temp.mkdir()
    real_tree.mkdir()
    (real_tree / "keep.txt").write_text("founder file", encoding="utf-8")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(other_temp))
    before = listing(real_tree)
    with pytest.raises(AssertionError, match="universal_workspace_root=tmp_path"):
        _court_source(real_tree, "must-not-write")
    assert listing(real_tree) == before == {"keep.txt"}


def test_an_in_tree_workspace_reads_the_module_and_writes_nothing(tmp_path, monkeypatch):
    repo = Path(app.__file__).resolve().parents[1]
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    before = sorted(p.name for p in repo.iterdir())
    assert _court_source(repo, "in-tree") == "nodelang/universal_application.py"
    assert sorted(p.name for p in repo.iterdir()) == before
