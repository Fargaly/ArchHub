import json
from pathlib import Path

import pytest

from nodelang.universal_cell import CellStore
from nodelang.domains.selfext import (
    install_mod_package,
    merge_mod_library,
    mods_rows,
    remove_mod_package,
    review_mod_package,
    run_mod_node,
    set_mod_enabled,
    set_mod_param,
)


def _store(tmp_path: Path) -> CellStore:
    return CellStore(tmp_path / "mods.db")


def _mod(folder: Path, *, permission="read.model"):
    folder.mkdir()
    (folder / "archhub.mod.json").write_text(
        json.dumps(
            {
                "identity": {"id": "qc-pack", "name": "QC Pack", "author": "firm"},
                "version": "1.2",
                "permissions": [permission],
                "contents": {
                    "node_kinds": [
                        {
                            "id": "fire-rating-check",
                            "title": "Fire rating check",
                            "category": "Change",
                            "summary": "checks fire ratings",
                            "params": {"Element limit": 100},
                            "behavior": {"result": "checked"},
                        }
                    ],
                    "tutorials": ["Check fire ratings in 3 steps"],
                },
            }
        ),
        encoding="utf-8",
    )


def test_built_in_mod_settings_persist_without_claiming_write_hooks(tmp_path):
    root = _store(tmp_path)
    state = mods_rows(root)
    assert state["installed"] == 0
    assert state["built_in"] == 2

    element = next(row for row in state["rows"] if row["id"] == "element-limit")
    assert element["enabled"] is True
    assert element["hooks"] == ["before_write"]
    assert "blocks governed writes" in element["description"]

    set_mod_enabled(root, "element-limit", False)
    set_mod_param(root, "element-limit", "Limit", "75")
    changed = next(row for row in mods_rows(root)["rows"] if row["id"] == "element-limit")
    assert changed["enabled"] is False
    assert changed["status"] == "off"
    assert changed["nodes"][0]["params"]["Limit"] == 75
    assert not (Path(root.database_path).with_suffix(".db.mods") / "owner-params.json").exists()
    assert root.read("app:archhub:mods:owner:element-limit") is not None


def test_mod_packages_do_not_merge_into_the_graph_library(tmp_path):
    groups = [{"cat": "Change", "items": [{"id": "core", "title": "Core"}]}]
    merged = merge_mod_library(groups, tmp_path / "owner-mods")
    assert merged is groups
    assert all(not item["id"].startswith("mod:") for group in merged for item in group["items"])


def test_package_install_rejects_client_grants_and_writes_nothing(tmp_path):
    source = tmp_path / "write-mod"
    root = _store(tmp_path)
    _mod(source, permission="host.write")

    with pytest.raises(PermissionError, match="not available"):
        install_mod_package(root, source, granted=True)

    assert mods_rows(root)["installed"] == 0
    legacy_root = Path(root.database_path).with_suffix(".db.mods")
    assert not (legacy_root / "owner-params.json").exists()
    assert not (legacy_root / "packages").exists()


def test_read_only_package_install_still_needs_governed_library_writer(tmp_path):
    source = tmp_path / "read-mod"
    root = _store(tmp_path)
    _mod(source)

    with pytest.raises(PermissionError, match="not available"):
        install_mod_package(root, source)

    assert mods_rows(root)["installed"] == 0


def test_remove_ignores_tampered_legacy_package_paths(tmp_path):
    root = _store(tmp_path)
    outside = tmp_path / "outside-owned-root"
    outside.mkdir()
    (outside / "keep.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(PermissionError, match="Mod package removal is not available"):
        remove_mod_package(root, "evil")

    assert (outside / "keep.txt").exists()


def test_package_review_is_hidden_and_does_not_echo_caller_path(tmp_path):
    source = tmp_path / "read-mod"
    _mod(source)
    with pytest.raises(PermissionError) as error:
        review_mod_package(source)
    assert "Mod package review is not available" in str(error.value)
    assert str(source) not in str(error.value)


def test_package_install_capability_is_hidden_from_catalogue(tmp_path):
    source = tmp_path / "read-mod"
    root = tmp_path / "owner-mods"
    _mod(source)
    with pytest.raises(PermissionError, match="Mod package installation is not available"):
        install_mod_package(root, source)
    state = mods_rows(_store(tmp_path))
    groups = [{"cat": "Change", "items": [{"id": "core", "title": "Core"}]}]
    merged = merge_mod_library(groups, root)
    assert state["installed"] == 0
    assert "qc-pack" not in {row["id"] for row in state["rows"]}
    assert merged is groups


def test_mod_node_runner_is_pure_projection():
    produced, shown = run_mod_node({"behavior": {"result": "checked"}}, {})
    assert produced["out"] == "checked"
    assert shown == "checked"
