"""stem-rebuild Phase-0 — `fs.list`, the READ-ONLY directory-listing cell.

`fs.list` lists a directory and emits typed file-rows
`{path, name, ext, size, is_dir, mtime}` plus a `count`. It turns the raw
os.walk/glob blob that file-walk jobs (BBC4 submittal QC, dated-folder
reconcile) dropped to into a composable stem cell — a pure primitive (no fs
host: scandir is in-process, needs no probe/auth).

What's pinned here:
  * flat (os.scandir) lists only the top level; files only by default;
  * `include_dirs` adds directory rows (size=0, ext="", is_dir=True);
  * `recursive` (os.walk) descends sub-directories;
  * `pattern` is a glob filter on the basename (e.g. '*.dwg');
  * a wired `path`/`pattern` input beats config (data.join "wired key wins");
  * each row is flat + complete + JSON-serializable; `ext` is lowercased and
    dotless; `size` is int bytes; `mtime` is an epoch float;
  * rows are sorted by `path` — a deterministic, parity-gateable cook;
  * a missing / non-dir / empty path is a typed error with outputs present +
    empty, NEVER a crash;
  * READ-ONLY — the cell mutates nothing; tests build fixtures in `tmp_path`
    ONLY and assert the tree is untouched after a listing;
  * the cell cooks end-to-end through a real WorkflowRunner and its typed
    outputs (rows / count) are read off the registered output ports — the
    canvas cook path, not just the executor.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.fs import _list_executor  # noqa: E402


# ─── fixtures (tmp_path ONLY — never the real FS) ────────────────────
#
# NOTE: conftest.py's autouse `_isolate_secrets_store` creates an `ArchHub`
# sub-directory inside EVERY test's `tmp_path`. So `tmp_path` is NOT empty.
# Every helper below carves a DEDICATED, fully-owned sub-directory under
# `tmp_path` and lists THAT — hermetic against the conftest dir (and any
# future autouse additions), so directory-content assertions are exact.


def _iso(tmp_path: Path, name: str = "listroot") -> Path:
    """A fresh, empty, test-owned directory under `tmp_path`."""
    root = tmp_path / name
    root.mkdir()
    return root


def _make_tree(tmp_path: Path) -> Path:
    """Build + return an isolated tree:
        <root>/A-101.dwg
        <root>/A-102.dwg
        <root>/sheet.xlsx
        <root>/readme            (no extension)
        <root>/sub/              (sub-directory)
        <root>/sub/B-201.dwg
        <root>/sub/notes.txt
    """
    root = _iso(tmp_path)
    (root / "A-101.dwg").write_text("d1", encoding="utf-8")
    (root / "A-102.dwg").write_text("d2", encoding="utf-8")
    (root / "sheet.xlsx").write_text("x", encoding="utf-8")
    (root / "readme").write_text("hello", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "B-201.dwg").write_text("d3", encoding="utf-8")
    (sub / "notes.txt").write_text("n", encoding="utf-8")
    return root


# ─── flat listing (default) ─────────────────────────────────────────


def test_flat_lists_top_level_files_only(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root)}, {}, None)
    assert out["status"] == "ok"
    names = [r["name"] for r in out["rows"]]
    # Top-level files only; the `sub` directory is NOT included by default.
    assert names == ["A-101.dwg", "A-102.dwg", "readme", "sheet.xlsx"]
    assert "sub" not in names
    assert out["count"] == 4
    assert all(r["is_dir"] is False for r in out["rows"])


def test_count_equals_len_rows(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root)}, {}, None)
    assert out["count"] == len(out["rows"])


# ─── typed row shape ────────────────────────────────────────────────


def test_row_fields_are_complete_and_typed(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root), "pattern": "A-101.dwg"}, {}, None)
    assert out["count"] == 1
    row = out["rows"][0]
    # Every field present.
    assert set(row.keys()) == {"path", "name", "ext", "size", "is_dir", "mtime"}
    assert row["name"] == "A-101.dwg"
    assert row["ext"] == "dwg"                      # lowercased + dotless
    assert row["path"] == os.path.abspath(str(root / "A-101.dwg"))
    assert isinstance(row["size"], int) and row["size"] == 2   # "d1"
    assert row["is_dir"] is False
    assert isinstance(row["mtime"], float) and row["mtime"] > 0


def test_ext_is_lowercased_and_dotless(tmp_path):
    root = _iso(tmp_path)
    (root / "DRAWING.DWG").write_text("x", encoding="utf-8")
    out = _list_executor({"path": str(root)}, {}, None)
    assert out["rows"][0]["ext"] == "dwg"


def test_no_extension_file_has_empty_ext(tmp_path):
    root = _iso(tmp_path)
    (root / "Makefile").write_text("x", encoding="utf-8")
    out = _list_executor({"path": str(root)}, {}, None)
    assert out["rows"][0]["ext"] == ""


def test_dotfile_has_empty_ext(tmp_path):
    # `.gitignore` is a name, not an extension → ext "".
    root = _iso(tmp_path)
    (root / ".gitignore").write_text("x", encoding="utf-8")
    out = _list_executor({"path": str(root)}, {}, None)
    assert out["rows"][0]["name"] == ".gitignore"
    assert out["rows"][0]["ext"] == ""


def test_rows_are_json_serializable(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root)}, {}, None)
    json.dumps(out["rows"])  # must not raise (survives disk-transport wires)


# ─── glob filter ────────────────────────────────────────────────────


def test_glob_pattern_filters_by_extension(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root), "pattern": "*.dwg"}, {}, None)
    assert [r["name"] for r in out["rows"]] == ["A-101.dwg", "A-102.dwg"]
    assert out["count"] == 2


def test_empty_pattern_keeps_everything(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root), "pattern": ""}, {}, None)
    assert out["count"] == 4   # same as no pattern


def test_glob_pattern_matches_prefix(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root), "pattern": "A-*"}, {}, None)
    assert [r["name"] for r in out["rows"]] == ["A-101.dwg", "A-102.dwg"]


# ─── include_dirs ───────────────────────────────────────────────────


def test_include_dirs_adds_directory_rows(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root), "include_dirs": True}, {}, None)
    by_name = {r["name"]: r for r in out["rows"]}
    assert "sub" in by_name
    sub = by_name["sub"]
    assert sub["is_dir"] is True
    assert sub["ext"] == ""       # a dir has no extension
    assert sub["size"] == 0       # dirs report size 0


def test_dir_row_subject_to_pattern_filter(tmp_path):
    root = _make_tree(tmp_path)
    # `sub` does not match *.dwg, so even with include_dirs it is filtered out.
    out = _list_executor(
        {"path": str(root), "include_dirs": True, "pattern": "*.dwg"},
        {}, None)
    assert all(not r["is_dir"] for r in out["rows"])
    assert [r["name"] for r in out["rows"]] == ["A-101.dwg", "A-102.dwg"]


# ─── recursive (os.walk) ────────────────────────────────────────────


def test_recursive_descends_subdirectories(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor({"path": str(root), "recursive": True}, {}, None)
    names = sorted(r["name"] for r in out["rows"])
    # All files at every depth; dirs excluded (include_dirs False).
    assert names == ["A-101.dwg", "A-102.dwg", "B-201.dwg",
                     "notes.txt", "readme", "sheet.xlsx"]
    assert all(r["is_dir"] is False for r in out["rows"])


def test_recursive_with_glob_finds_nested_matches(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor(
        {"path": str(root), "recursive": True, "pattern": "*.dwg"},
        {}, None)
    names = sorted(r["name"] for r in out["rows"])
    assert names == ["A-101.dwg", "A-102.dwg", "B-201.dwg"]   # incl. nested


def test_recursive_include_dirs_emits_subdir_rows(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor(
        {"path": str(root), "recursive": True, "include_dirs": True},
        {}, None)
    dir_rows = [r for r in out["rows"] if r["is_dir"]]
    assert [r["name"] for r in dir_rows] == ["sub"]


# ─── deterministic order ────────────────────────────────────────────


def test_rows_sorted_by_path_deterministic(tmp_path):
    # Create in non-sorted order; the cell must still return sorted-by-path.
    root = _iso(tmp_path)
    for n in ("zebra.txt", "alpha.txt", "mike.txt"):
        (root / n).write_text("x", encoding="utf-8")
    out = _list_executor({"path": str(root)}, {}, None)
    paths = [r["path"] for r in out["rows"]]
    assert paths == sorted(paths)
    assert [r["name"] for r in out["rows"]] == ["alpha.txt", "mike.txt", "zebra.txt"]


# ─── empty directory ────────────────────────────────────────────────


def test_empty_directory_is_ok_with_empty_rows(tmp_path):
    root = _iso(tmp_path)   # a fresh, genuinely empty dir
    out = _list_executor({"path": str(root)}, {}, None)
    assert out["status"] == "ok"
    assert out["rows"] == []
    assert out["count"] == 0


# ─── wired input beats config (data.join parity) ────────────────────


def test_wired_path_overrides_config(tmp_path):
    root = _make_tree(tmp_path)
    # config path is bogus; the wired input path wins.
    out = _list_executor(
        {"path": "C:/nonexistent-config-path"},
        {"path": str(root)}, None)
    assert out["status"] == "ok"
    assert out["count"] == 4


def test_wired_pattern_overrides_config(tmp_path):
    root = _make_tree(tmp_path)
    out = _list_executor(
        {"path": str(root), "pattern": "*.xlsx"},
        {"pattern": "*.dwg"}, None)
    # wired *.dwg wins over config *.xlsx
    assert [r["name"] for r in out["rows"]] == ["A-101.dwg", "A-102.dwg"]


# ─── missing / inaccessible path → typed error, never a crash ───────


def test_missing_path_is_typed_error(tmp_path):
    out = _list_executor({"path": str(tmp_path / "does-not-exist")}, {}, None)
    assert out["status"] == "error"
    assert "not found" in out["error"]
    # Outputs still present + empty (upstream_error propagation stays typed).
    assert out["rows"] == []
    assert out["count"] == 0


def test_no_path_is_typed_error():
    out = _list_executor({}, {}, None)
    assert out["status"] == "error"
    assert "no path" in out["error"]
    assert out["rows"] == []
    assert out["count"] == 0


def test_path_that_is_a_file_is_typed_error(tmp_path):
    root = _iso(tmp_path)
    f = root / "afile.txt"
    f.write_text("x", encoding="utf-8")
    out = _list_executor({"path": str(f)}, {}, None)
    assert out["status"] == "error"
    assert "not a directory" in out["error"]
    assert out["rows"] == []


def test_empty_string_path_is_typed_error():
    out = _list_executor({"path": "   "}, {}, None)
    assert out["status"] == "error"
    assert "no path" in out["error"]


# ─── READ-ONLY contract — the tree is untouched after a listing ─────


def test_listing_mutates_nothing(tmp_path):
    root = _make_tree(tmp_path)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    before_bytes = (root / "A-101.dwg").read_text(encoding="utf-8")

    # Run every mode — flat, recursive, glob, include_dirs.
    _list_executor({"path": str(root)}, {}, None)
    _list_executor({"path": str(root), "recursive": True}, {}, None)
    _list_executor({"path": str(root), "pattern": "*.dwg"}, {}, None)
    _list_executor({"path": str(root), "include_dirs": True}, {}, None)

    after = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    after_bytes = (root / "A-101.dwg").read_text(encoding="utf-8")
    assert before == after            # no file created / moved / deleted
    assert before_bytes == after_bytes  # no content mutated


# ─── registration ───────────────────────────────────────────────────


def test_fs_list_registered():
    import workflows.nodes.fs  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("fs.list") is not None


def test_fs_list_ports_are_typed():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.list")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"rows": "list", "count": "number"}
    in_ports = {p.name for p in spec.inputs}
    assert {"path", "pattern"} <= in_ports
    # `path` is the only required input.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"path"}


def test_fs_list_category_is_io():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.list")
    assert spec.category == "io"


def test_fs_list_in_grammar_resolves_to_engine_type():
    import workflows  # noqa: F401  registers built-ins
    from workflows import node_grammar as ng
    assert ng.engine_type("list_files") == "fs.list"


# ─── end-to-end: cook the cell through a real WorkflowRunner ────────


def test_fs_list_cooks_through_real_runner_and_reads_typed_outputs(tmp_path):
    """path source → fs.list → assert rows / count come off the registered
    output ports, driven through a real outer WorkflowRunner (the canvas cook
    path, not just the executor)."""
    import workflows.nodes.fs  # noqa: F401  registers fs.list
    from workflows.runner import WorkflowRunner
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType

    root = _make_tree(tmp_path)

    # Minimal const source node feeding the path string (registered once).
    if _get_spec("_test.const_fspath") is None:
        register(NodeSpec(
            type="_test.const_fspath", category="_test",
            display_name="Test Const FS Path",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.STRING)],
            config_schema={}, icon="/"),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})

    graph = {
        "nodes": [
            {"id": "src", "type": "_test.const_fspath",
             "config": {"value": str(root)},
             "outs": [{"id": "value", "t": "string"}]},
            {"id": "ls", "type": "fs.list", "config": {"pattern": "*.dwg"},
             "ins":  [{"id": "path", "t": "string"}],
             "outs": [{"id": "rows",  "t": "list"},
                      {"id": "count", "t": "number"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["ls", "path"]},
        ],
    }
    out = WorkflowRunner(graph).pull("ls")

    assert out.get("status") == "ok"
    assert out["count"] == 2
    assert [r["name"] for r in out["rows"]] == ["A-101.dwg", "A-102.dwg"]
    assert all(r["ext"] == "dwg" for r in out["rows"])
