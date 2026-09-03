"""stem-rebuild Phase-0 — `fs.move`, the IO-WRITE move/rename cell.

`fs.move` is the move half of the fs stem family (fs.list finds, fs.read
reads, fs.write writes, fs.move relocates). Give it `src` + `dst`; it renames
/ moves src to dst (shutil.move semantics — files and whole directory trees,
across filesystems), returning the absolute `src` and `dst` paths and `moved`
True. A pure stem cell (no fs host) that is SIDE-EFFECTING by design — moving
a path is its job, like any IO function.

What's pinned here:
  * a successful move returns moved=True, the abspaths, the file is at `dst`
    and GONE from `src`;
  * a whole directory tree moves intact;
  * overwrite — overwrite=False on an existing dst is a TYPED ERROR and BOTH
    paths are left untouched; overwrite=True replaces an existing dst;
  * make_dirs=True creates a missing dst parent chain; make_dirs=False on a
    missing dst parent is a typed error (no auto-create);
  * a missing src is a typed error; missing / empty src or dst is a typed
    error with outputs present + empty;
  * a wired `src` / `dst` input beats config (data.join "wired key wins");
  * every error path returns the SAME complete, typed output shape;
  * TOTAL-TOLERANT — never raises; deterministic;
  * tests build + move fixtures under `tmp_path` ONLY — never the real FS;
  * the cell cooks end-to-end through a real WorkflowRunner and its typed
    outputs are read off the registered output ports — the canvas cook path.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.fs import _move_executor  # noqa: E402


# ─── fixtures (tmp_path ONLY — never the real FS) ────────────────────
#
# NOTE: conftest.py's autouse `_isolate_secrets_store` creates an `ArchHub`
# sub-directory inside EVERY test's `tmp_path`. So `tmp_path` is NOT empty.
# Every helper below carves a DEDICATED, fully-owned dir/file under tmp_path.


def _iso(tmp_path: Path, name: str = "moveroot") -> Path:
    """A fresh, empty, test-owned directory under `tmp_path`."""
    root = tmp_path / name
    root.mkdir()
    return root


def _src_file(tmp_path: Path, name: str, content: str) -> Path:
    """Build + return a test-owned source file with text `content`.

    Writes via `write_bytes` so the on-disk bytes are EXACTLY
    `content.encode('utf-8')` — no platform newline translation."""
    root = _iso(tmp_path)
    p = root / name
    p.write_bytes(content.encode("utf-8"))
    return p


# ─── success move (file) ─────────────────────────────────────────────


def test_move_file_relocates_and_reports(tmp_path):
    src = _src_file(tmp_path, "from.txt", "payload\nhere")
    dst = src.parent / "to.txt"
    out = _move_executor({"src": str(src), "dst": str(dst)}, {}, None)
    assert out["status"] == "ok"
    assert out["moved"] is True
    assert out["src"] == os.path.abspath(str(src))
    assert out["dst"] == os.path.abspath(str(dst))
    # File is at dst with the same content, and GONE from src.
    assert dst.read_text(encoding="utf-8") == "payload\nhere"
    assert not src.exists()


def test_move_rename_within_same_dir(tmp_path):
    src = _src_file(tmp_path, "old-name.txt", "x")
    dst = src.parent / "new-name.txt"
    out = _move_executor({"src": str(src), "dst": str(dst)}, {}, None)
    assert out["status"] == "ok"
    assert dst.exists()
    assert not src.exists()


def test_move_directory_tree_moves_intact(tmp_path):
    # A whole directory with a nested file moves as a unit.
    root = _iso(tmp_path)
    srcdir = root / "srcdir"
    srcdir.mkdir()
    (srcdir / "inner.txt").write_bytes(b"nested")
    dstdir = root / "dstdir"
    out = _move_executor({"src": str(srcdir), "dst": str(dstdir)}, {}, None)
    assert out["status"] == "ok"
    assert out["moved"] is True
    assert (dstdir / "inner.txt").read_text(encoding="utf-8") == "nested"
    assert not srcdir.exists()


def test_move_output_fields_are_complete_and_typed(tmp_path):
    src = _src_file(tmp_path, "a.txt", "data")
    dst = src.parent / "b.txt"
    out = _move_executor({"src": str(src), "dst": str(dst)}, {}, None)
    assert set(out.keys()) >= {"status", "src", "dst", "moved"}
    assert isinstance(out["src"], str)
    assert isinstance(out["dst"], str)
    assert isinstance(out["moved"], bool)


def test_move_output_is_json_serializable(tmp_path):
    src = _src_file(tmp_path, "j.txt", "data")
    dst = src.parent / "j2.txt"
    out = _move_executor({"src": str(src), "dst": str(dst)}, {}, None)
    json.dumps(out)        # must not raise (survives disk-transport wires)


# ─── overwrite guard (the clobber contract) ──────────────────────────


def test_move_dst_exists_overwrite_false_is_error_and_both_unchanged(tmp_path):
    root = _iso(tmp_path)
    src = root / "src.txt"
    src.write_bytes(b"SOURCE")
    dst = root / "dst.txt"
    dst.write_bytes(b"EXISTING DEST")
    out = _move_executor({"src": str(src), "dst": str(dst),
                          "overwrite": False}, {}, None)
    assert out["status"] == "error"
    assert "exists" in out["error"]
    # BOTH files are untouched — src still there, dst content unchanged.
    assert src.read_bytes() == b"SOURCE"
    assert dst.read_bytes() == b"EXISTING DEST"
    # Error outputs present + empty.
    assert out["src"] == ""
    assert out["dst"] == ""
    assert out["moved"] is False


def test_move_default_overwrite_is_false(tmp_path):
    root = _iso(tmp_path)
    src = root / "s.txt"
    src.write_bytes(b"S")
    dst = root / "d.txt"
    dst.write_bytes(b"D")
    out = _move_executor({"src": str(src), "dst": str(dst)}, {}, None)
    assert out["status"] == "error"             # default protects dst
    assert src.exists() and dst.read_bytes() == b"D"


def test_move_overwrite_true_replaces_existing_dst(tmp_path):
    root = _iso(tmp_path)
    src = root / "src.txt"
    src.write_bytes(b"NEW")
    dst = root / "dst.txt"
    dst.write_bytes(b"OLD")
    out = _move_executor({"src": str(src), "dst": str(dst),
                          "overwrite": True}, {}, None)
    assert out["status"] == "ok"
    assert out["moved"] is True
    assert dst.read_bytes() == b"NEW"           # replaced
    assert not src.exists()


def test_move_overwrite_true_replaces_existing_dst_directory(tmp_path):
    # overwrite True must clear an existing dst DIRECTORY first, so the moved
    # tree lands exactly at dst (not nested inside it).
    root = _iso(tmp_path)
    srcdir = root / "srcdir"
    srcdir.mkdir()
    (srcdir / "f.txt").write_bytes(b"new-tree")
    dstdir = root / "dstdir"
    dstdir.mkdir()
    (dstdir / "stale.txt").write_bytes(b"old-tree")
    out = _move_executor({"src": str(srcdir), "dst": str(dstdir),
                          "overwrite": True}, {}, None)
    assert out["status"] == "ok"
    assert (dstdir / "f.txt").read_text(encoding="utf-8") == "new-tree"
    assert not (dstdir / "stale.txt").exists()   # old dst tree was replaced
    assert not srcdir.exists()


# ─── make_dirs (dst parent creation) ─────────────────────────────────


def test_move_make_dirs_true_creates_missing_dst_parents(tmp_path):
    src = _src_file(tmp_path, "src.txt", "data")
    dst = src.parent / "a" / "b" / "c" / "moved.txt"
    assert not dst.parent.exists()
    out = _move_executor({"src": str(src), "dst": str(dst),
                          "make_dirs": True}, {}, None)
    assert out["status"] == "ok"
    assert dst.read_text(encoding="utf-8") == "data"
    assert not src.exists()


def test_move_make_dirs_default_is_true(tmp_path):
    src = _src_file(tmp_path, "src.txt", "data")
    dst = src.parent / "x" / "y" / "f.txt"
    out = _move_executor({"src": str(src), "dst": str(dst)}, {}, None)
    assert out["status"] == "ok"
    assert dst.exists()


def test_move_make_dirs_false_missing_dst_parent_is_typed_error(tmp_path):
    src = _src_file(tmp_path, "src.txt", "data")
    dst = src.parent / "no" / "such" / "parent.txt"
    assert not dst.parent.exists()
    out = _move_executor({"src": str(src), "dst": str(dst),
                          "make_dirs": False}, {}, None)
    assert out["status"] == "error"
    assert "make_dirs" in out["error"]
    # src is untouched (move never happened); dst parent not created.
    assert src.exists()
    assert not dst.parent.exists()
    assert out["moved"] is False


# ─── missing src → typed error ───────────────────────────────────────


def test_move_missing_src_is_typed_error(tmp_path):
    root = _iso(tmp_path)
    out = _move_executor({"src": str(root / "ghost.txt"),
                          "dst": str(root / "dest.txt")}, {}, None)
    assert out["status"] == "error"
    assert "not found" in out["error"]
    assert out["src"] == ""
    assert out["dst"] == ""
    assert out["moved"] is False
    # No dst was created.
    assert not (root / "dest.txt").exists()


# ─── missing / empty src or dst → typed error ────────────────────────


def test_move_no_src_is_typed_error(tmp_path):
    out = _move_executor({"dst": str(tmp_path / "d.txt")}, {}, None)
    assert out["status"] == "error"
    assert "no src" in out["error"]
    assert out["moved"] is False


def test_move_no_dst_is_typed_error(tmp_path):
    src = _src_file(tmp_path, "s.txt", "data")
    out = _move_executor({"src": str(src)}, {}, None)
    assert out["status"] == "error"
    assert "no dst" in out["error"]
    assert out["moved"] is False
    # src untouched — the move never started.
    assert src.exists()


def test_move_empty_string_src_is_typed_error():
    out = _move_executor({"src": "   ", "dst": "x"}, {}, None)
    assert out["status"] == "error"
    assert "no src" in out["error"]


def test_move_error_outputs_are_fully_present_and_typed():
    # Every error path returns the SAME complete, typed output shape.
    out = _move_executor({}, {}, None)
    assert set(out.keys()) == {"status", "src", "dst", "moved", "error"}
    assert isinstance(out["src"], str)
    assert isinstance(out["dst"], str)
    assert isinstance(out["moved"], bool)
    assert isinstance(out["error"], str)


# ─── wired input beats config ────────────────────────────────────────


def test_move_wired_src_dst_override_config(tmp_path):
    real_src = _src_file(tmp_path, "real-src.txt", "wired payload")
    real_dst = real_src.parent / "real-dst.txt"
    out = _move_executor(
        {"src": str(tmp_path / "config-src.txt"),         # bogus config src
         "dst": str(tmp_path / "config-dst.txt")},
        {"src": str(real_src), "dst": str(real_dst)}, None)  # wired wins
    assert out["status"] == "ok"
    assert real_dst.read_text(encoding="utf-8") == "wired payload"
    assert not real_src.exists()


# ─── deterministic output ────────────────────────────────────────────


def test_move_is_deterministic(tmp_path):
    # Two independent moves with identical relative shapes yield identical
    # outputs MODULO the tmp_path prefix — assert the structural fields.
    root_a = tmp_path / "a"
    root_a.mkdir()
    (root_a / "s.txt").write_bytes(b"x")
    out_a = _move_executor({"src": str(root_a / "s.txt"),
                            "dst": str(root_a / "d.txt")}, {}, None)

    root_b = tmp_path / "b"
    root_b.mkdir()
    (root_b / "s.txt").write_bytes(b"x")
    out_b = _move_executor({"src": str(root_b / "s.txt"),
                            "dst": str(root_b / "d.txt")}, {}, None)

    assert out_a["status"] == out_b["status"] == "ok"
    assert out_a["moved"] == out_b["moved"] is True
    assert set(out_a.keys()) == set(out_b.keys())


# ─── registration ────────────────────────────────────────────────────


def test_fs_move_registered():
    import workflows.nodes.fs  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("fs.move") is not None


def test_fs_move_ports_are_typed():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.move")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"src": "string", "dst": "string", "moved": "boolean"}
    in_ports = {p.name for p in spec.inputs}
    assert in_ports == {"src", "dst"}
    # `src` is the only REQUIRED input.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"src"}


def test_fs_move_category_is_io():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.move")
    assert spec.category == "io"


def test_fs_move_config_schema_is_modular():
    # config_schema declares src / dst / overwrite / make_dirs with defaults —
    # no hard-coded literals buried in the body.
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.move")
    assert set(spec.config_schema.keys()) == {"src", "dst",
                                             "overwrite", "make_dirs"}
    assert spec.config_schema["overwrite"]["default"] is False
    assert spec.config_schema["make_dirs"]["default"] is True


# ─── end-to-end: cook the cell through a real WorkflowRunner ─────────


def test_fs_move_cooks_through_real_runner_and_reads_typed_outputs(tmp_path):
    """src/dst sources → fs.move → assert src / dst / moved come off the
    registered output ports, driven through a real WorkflowRunner (the canvas
    cook path). The file really relocates on disk."""
    import workflows.nodes.fs  # noqa: F401  registers fs.move
    from workflows.runner import WorkflowRunner
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType

    root = _iso(tmp_path)
    src = root / "cooked-src.txt"
    src.write_bytes(b"relocate me")
    dst = root / "cooked-dst.txt"

    # Minimal const source nodes feeding src + dst (registered once).
    if _get_spec("_test.const_fsmovepath") is None:
        register(NodeSpec(
            type="_test.const_fsmovepath", category="_test",
            display_name="Test Const FS Move Path",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.STRING)],
            config_schema={}, icon="/"),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})

    graph = {
        "nodes": [
            {"id": "ssrc", "type": "_test.const_fsmovepath",
             "config": {"value": str(src)},
             "outs": [{"id": "value", "t": "string"}]},
            {"id": "dsrc", "type": "_test.const_fsmovepath",
             "config": {"value": str(dst)},
             "outs": [{"id": "value", "t": "string"}]},
            {"id": "mv", "type": "fs.move", "config": {},
             "ins":  [{"id": "src", "t": "string"},
                      {"id": "dst", "t": "string"}],
             "outs": [{"id": "src",   "t": "string"},
                      {"id": "dst",   "t": "string"},
                      {"id": "moved", "t": "boolean"}]},
        ],
        "wires": [
            {"from": ["ssrc", "value"], "to": ["mv", "src"]},
            {"from": ["dsrc", "value"], "to": ["mv", "dst"]},
        ],
    }
    out = WorkflowRunner(graph).pull("mv")

    assert out.get("status") == "ok"
    assert out["moved"] is True
    assert out["src"] == os.path.abspath(str(src))
    assert out["dst"] == os.path.abspath(str(dst))
    # The file really relocated via the cook path.
    assert dst.read_text(encoding="utf-8") == "relocate me"
    assert not src.exists()
