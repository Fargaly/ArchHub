from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
ARCHIVE = (
    WORKSPACE
    / "90.ARCHIVE"
    / "10.PRODUCT"
    / "2026-07-17-separate-cockpit-superseded"
)
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import authority_wip_classify as awc  # noqa: E402


def _imports_module(source: str, module_name: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
    return False


def test_separate_cockpit_router_is_not_mounted_by_cloud_app():
    main = (ROOT / "cloud_backend" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main)
    mounted_routers: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "include_router"
            and node.args
        ):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Attribute) and arg.attr == "router":
            if isinstance(arg.value, ast.Name):
                mounted_routers.append(arg.value.id)

    assert not _imports_module(main, "cockpit")
    assert "cockpit" not in mounted_routers
    assert "founder_cockpit" in mounted_routers


def test_separate_cockpit_paths_are_absent_from_public_product_tree():
    paths = [
        "cloud_backend/cockpit.py",
        "cloud_backend/cockpit_app",
        "cloud_backend/cockpit_executor.py",
        "cloud_backend/cockpit_app/index.html",
        "cloud_backend/cockpit_page.html",
        "cloud_backend/cockpit_real",
        "cloud_backend/cockpit_real/index.html",
        "cloud_backend/cockpit_seed.json",
    ]

    for path in paths:
        assert not (ROOT / path).exists()


def test_separate_cockpit_paths_remain_non_promotable_if_reintroduced():
    paths = [
        "cloud_backend/cockpit.py",
        "cloud_backend/cockpit_executor.py",
        "cloud_backend/cockpit_app/index.html",
        "cloud_backend/cockpit_page.html",
        "cloud_backend/cockpit_real/index.html",
        "cloud_backend/cockpit_seed.json",
    ]

    for path in paths:
        assert (
            awc.classify_path(path)
            == "separate_cockpit_backend_to_consume_or_archive"
        )
        report = awc.classify_entries([{"code": "??", "path": path}])
        entry = report["entries"][0]
        assert entry["promotion_allowed"] == "false"
        assert "consume" in entry["required_action"]
        assert "archive" in entry["required_action"]


def test_archived_cockpit_evidence_has_manifest_and_boundaries():
    manifest = (ARCHIVE / "MANIFEST.md").read_text(encoding="utf-8")
    assert "Separate Cockpit Superseded Evidence" in manifest
    assert "Universal Cell" in manifest
    assert "not product authority" in manifest
    assert (ARCHIVE / "cockpit.py").is_file()
    assert (ARCHIVE / "cockpit_executor.py").is_file()
    assert (ARCHIVE / "cockpit_app").is_dir()
    assert (ARCHIVE / "cockpit_real").is_dir()

    for name in ("cockpit.py", "cockpit_executor.py"):
        text = (ARCHIVE / name).read_text(encoding="utf-8")
        assert "MIGRATION EVIDENCE" in text
        assert "Universal Cell" in text
        assert "MUST NOT" in text
