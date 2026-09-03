"""A map with no governance tree above it still yields a workspace root."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nodelang.universal_application import _workspace_root_for_map
from nodelang.map_import import PUBLIC_MAP_PATH


def test_founder_tree_wins_when_present():
    root = _workspace_root_for_map(PUBLIC_MAP_PATH)
    assert (root / "nodelang" / "__init__.py").is_file() or (root / "00.GOVERNANCE").is_dir()


def test_colleague_install_without_governance_tree_still_boots(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCHHUB_WORKSPACE_ROOT", raising=False)
    install = tmp_path / "ArchHub"
    (install / "nodelang" / "data").mkdir(parents=True)
    (install / "nodelang" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copyfile(PUBLIC_MAP_PATH, install / "nodelang" / "data" / "public_runtime_map.json")
    assert _workspace_root_for_map(install / "nodelang" / "data" / "public_runtime_map.json") == install.resolve()


def test_named_root_is_honoured(tmp_path, monkeypatch):
    named = tmp_path / "named"; named.mkdir()
    monkeypatch.setenv("ARCHHUB_WORKSPACE_ROOT", str(named))
    lone = tmp_path / "lone" / "map.json"; lone.parent.mkdir(); lone.write_text("{}", encoding="utf-8")
    assert _workspace_root_for_map(lone) == named.resolve()


def test_no_root_at_all_still_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCHHUB_WORKSPACE_ROOT", raising=False)
    lone = tmp_path / "lone" / "map.json"; lone.parent.mkdir(); lone.write_text("{}", encoding="utf-8")
    from nodelang.universal_cell import InvalidCell
    with pytest.raises(InvalidCell):
        _workspace_root_for_map(lone)
