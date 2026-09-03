"""stem-rebuild Phase-0 — `fs.write`, the IO-WRITE text-to-file cell.

`fs.write` is the write half of the fs stem family (fs.list finds files,
fs.read reads one, fs.write writes one). Give it a path + `text`; it encodes
the text with `encoding` and writes the bytes, returning the absolute `path`
written, `bytes_written`, and `created` (True if the file was new). A pure
stem cell (no fs host: open() is in-process, needs no probe/auth) that is
SIDE-EFFECTING by design — writing bytes is its job, like any IO function.

What's pinned here:
  * a successful write to a NEW file returns created=True, the byte count,
    the abspath, and the file on disk holds exactly the encoded text;
  * overwrite — overwrite=True replaces an existing file (created=False);
    overwrite=False on an existing file is a TYPED ERROR and the original is
    left BYTE-IDENTICAL (no clobber, not even truncated);
  * make_dirs=True creates missing parent dirs; make_dirs=False on a missing
    parent is a typed error (no auto-create);
  * a directory path is a typed error (can't write bytes to a dir);
  * a bad encoding name / non-str encoding is a typed error, NEVER a raise,
    and nothing is written (no partial file);
  * a wired `text` / `path` input beats config (data.join "wired key wins");
  * an empty / missing path is a typed error with outputs present + empty;
  * every error path returns the SAME complete, typed output shape;
  * TOTAL-TOLERANT — never raises; deterministic (same inputs → same bytes);
  * tests build + write fixtures under `tmp_path` ONLY — never the real FS;
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

from workflows.nodes.fs import _write_executor  # noqa: E402


# ─── fixtures (tmp_path ONLY — never the real FS) ────────────────────
#
# NOTE: conftest.py's autouse `_isolate_secrets_store` creates an `ArchHub`
# sub-directory inside EVERY test's `tmp_path`. So `tmp_path` is NOT empty.
# Every helper below carves a DEDICATED, fully-owned dir/file under tmp_path.


def _iso(tmp_path: Path, name: str = "writeroot") -> Path:
    """A fresh, empty, test-owned directory under `tmp_path`."""
    root = tmp_path / name
    root.mkdir()
    return root


def _existing_file(tmp_path: Path, name: str, content: str,
                   encoding: str = "utf-8") -> Path:
    """Build + return a test-owned file pre-populated with `content`.

    Writes via `write_bytes` so the on-disk bytes are EXACTLY
    `content.encode(encoding)` — no platform newline translation (Windows
    `write_text` would rewrite '\\n' → '\\r\\n', desyncing byte assertions)."""
    root = _iso(tmp_path)
    p = root / name
    p.write_bytes(content.encode(encoding))
    return p


# ─── success write (new file) ────────────────────────────────────────


def test_write_new_file_returns_created_and_metrics(tmp_path):
    target = _iso(tmp_path) / "out.txt"
    out = _write_executor({"path": str(target)},
                          {"text": "hello\nworld"}, None)
    assert out["status"] == "ok"
    assert out["created"] is True                 # file did not exist before
    assert out["path"] == os.path.abspath(str(target))
    assert out["bytes_written"] == len("hello\nworld".encode("utf-8"))
    # The bytes really landed on disk.
    assert target.read_bytes() == "hello\nworld".encode("utf-8")


def test_write_text_via_config_value(tmp_path):
    # `text` may come from config too (not only a wire).
    target = _iso(tmp_path) / "cfg.txt"
    out = _write_executor({"path": str(target), "text": "from-config"},
                          {}, None)
    assert out["status"] == "ok"
    assert target.read_text(encoding="utf-8") == "from-config"


def test_write_empty_text_creates_empty_file(tmp_path):
    target = _iso(tmp_path) / "empty.txt"
    out = _write_executor({"path": str(target)}, {}, None)
    assert out["status"] == "ok"
    assert out["created"] is True
    assert out["bytes_written"] == 0
    assert target.exists()
    assert target.read_bytes() == b""


def test_write_output_fields_are_complete_and_typed(tmp_path):
    target = _iso(tmp_path) / "typed.txt"
    out = _write_executor({"path": str(target)}, {"text": "x"}, None)
    assert set(out.keys()) >= {"status", "path", "bytes_written", "created"}
    assert isinstance(out["path"], str)
    assert isinstance(out["bytes_written"], int)
    assert isinstance(out["created"], bool)


def test_write_output_is_json_serializable(tmp_path):
    target = _iso(tmp_path) / "j.txt"
    out = _write_executor({"path": str(target)}, {"text": "data"}, None)
    json.dumps(out)        # must not raise (survives disk-transport wires)


def test_write_honours_explicit_encoding(tmp_path):
    # résumé encoded latin-1 → the on-disk bytes are the latin-1 bytes.
    target = _iso(tmp_path) / "latin.txt"
    out = _write_executor({"path": str(target), "encoding": "latin-1"},
                          {"text": "résumé"}, None)
    assert out["status"] == "ok"
    assert target.read_bytes() == "résumé".encode("latin-1")
    assert out["bytes_written"] == len("résumé".encode("latin-1"))


# ─── overwrite guard (the clobber contract) ──────────────────────────


def test_write_overwrite_true_replaces_existing(tmp_path):
    p = _existing_file(tmp_path, "doc.txt", "OLD CONTENT")
    out = _write_executor({"path": str(p), "overwrite": True},
                          {"text": "NEW CONTENT"}, None)
    assert out["status"] == "ok"
    assert out["created"] is False                 # existed before → replaced
    assert p.read_text(encoding="utf-8") == "NEW CONTENT"


def test_write_overwrite_false_on_existing_is_typed_error_and_unchanged(tmp_path):
    p = _existing_file(tmp_path, "keep.txt", "DO NOT TOUCH")
    before = p.read_bytes()
    out = _write_executor({"path": str(p), "overwrite": False},
                          {"text": "should not be written"}, None)
    assert out["status"] == "error"
    assert "exists" in out["error"]
    # The original file is BYTE-IDENTICAL — not clobbered, not even truncated.
    assert p.read_bytes() == before
    # Error outputs present + empty.
    assert out["path"] == ""
    assert out["bytes_written"] == 0
    assert out["created"] is False


def test_write_default_overwrite_is_false(tmp_path):
    # No overwrite key → defaults to False → existing file is protected.
    p = _existing_file(tmp_path, "default.txt", "ORIGINAL")
    out = _write_executor({"path": str(p)}, {"text": "nope"}, None)
    assert out["status"] == "error"
    assert p.read_text(encoding="utf-8") == "ORIGINAL"


# ─── make_dirs (parent creation) ─────────────────────────────────────


def test_write_make_dirs_true_creates_missing_parents(tmp_path):
    # Nested parents that do NOT exist yet — make_dirs True builds the chain.
    target = _iso(tmp_path) / "a" / "b" / "c" / "deep.txt"
    assert not target.parent.exists()
    out = _write_executor({"path": str(target), "make_dirs": True},
                          {"text": "deep"}, None)
    assert out["status"] == "ok"
    assert out["created"] is True
    assert target.read_text(encoding="utf-8") == "deep"


def test_write_make_dirs_default_is_true(tmp_path):
    # No make_dirs key → defaults True → missing parents are created.
    target = _iso(tmp_path) / "x" / "y" / "f.txt"
    out = _write_executor({"path": str(target)}, {"text": "hi"}, None)
    assert out["status"] == "ok"
    assert target.exists()


def test_write_make_dirs_false_missing_parent_is_typed_error(tmp_path):
    target = _iso(tmp_path) / "no" / "such" / "parent.txt"
    assert not target.parent.exists()
    out = _write_executor({"path": str(target), "make_dirs": False},
                          {"text": "x"}, None)
    assert out["status"] == "error"
    assert "make_dirs" in out["error"]
    # Nothing was created.
    assert not target.exists()
    assert not target.parent.exists()
    assert out["bytes_written"] == 0


def test_write_make_dirs_false_existing_parent_succeeds(tmp_path):
    # make_dirs False is fine when the parent already exists.
    root = _iso(tmp_path)
    target = root / "f.txt"
    out = _write_executor({"path": str(target), "make_dirs": False},
                          {"text": "ok"}, None)
    assert out["status"] == "ok"
    assert target.read_text(encoding="utf-8") == "ok"


# ─── directory path → typed error ────────────────────────────────────


def test_write_directory_path_is_typed_error(tmp_path):
    d = _iso(tmp_path)        # a real directory, not a file
    out = _write_executor({"path": str(d)}, {"text": "nope"}, None)
    assert out["status"] == "error"
    assert "directory" in out["error"]
    assert out["path"] == ""
    assert out["bytes_written"] == 0
    assert out["created"] is False


# ─── bad encoding → typed error, never a crash, nothing written ──────


def test_write_bad_encoding_name_is_typed_error_not_a_crash(tmp_path):
    # An unknown codec NAME raises LookupError on encode BEFORE any write.
    # Total tolerance requires a TYPED ERROR + no partial file.
    target = _iso(tmp_path) / "be.txt"
    out = _write_executor({"path": str(target), "encoding": "bogus-codec"},
                          {"text": "hello"}, None)
    assert out["status"] == "error"
    assert "encoding" in out["error"]
    # Nothing written — no partial / truncated file left behind.
    assert not target.exists()
    assert out["path"] == ""
    assert out["bytes_written"] == 0
    assert out["created"] is False


def test_write_unencodable_char_is_typed_error_no_partial_file(tmp_path):
    # '€' cannot be encoded in latin-1 → typed error, no file created.
    target = _iso(tmp_path) / "ue.txt"
    out = _write_executor({"path": str(target), "encoding": "latin-1"},
                          {"text": "price: €5"}, None)
    assert out["status"] == "error"
    assert "encoding" in out["error"]
    assert not target.exists()


def test_write_none_encoding_falls_back_or_errors_never_raises(tmp_path):
    # A non-str encoding (e.g. wired None) must degrade gracefully — either
    # fall back to the utf-8 default (ok) or a typed error; NEVER a raise.
    target = _iso(tmp_path) / "ne.txt"
    out = _write_executor({"path": str(target), "encoding": None},
                          {"text": "data"}, None)
    assert out["status"] in ("ok", "error")
    assert set(out.keys()) >= {"status", "path", "bytes_written", "created"}


# ─── wired input beats config ────────────────────────────────────────


def test_write_wired_path_overrides_config(tmp_path):
    real = _iso(tmp_path) / "real.txt"
    out = _write_executor(
        {"path": str(tmp_path / "config-target.txt")},   # config path
        {"path": str(real), "text": "wired wins"}, None)  # wired path
    assert out["status"] == "ok"
    assert real.read_text(encoding="utf-8") == "wired wins"
    assert not (tmp_path / "config-target.txt").exists()  # config path unused


def test_write_wired_text_overrides_config_text(tmp_path):
    target = _iso(tmp_path) / "t.txt"
    out = _write_executor(
        {"path": str(target), "text": "config-text"},
        {"text": "wired-text"}, None)
    assert out["status"] == "ok"
    assert target.read_text(encoding="utf-8") == "wired-text"


# ─── missing / empty path → typed error ──────────────────────────────


def test_write_no_path_is_typed_error():
    out = _write_executor({}, {"text": "data"}, None)
    assert out["status"] == "error"
    assert "no path" in out["error"]
    assert out["path"] == ""
    assert out["bytes_written"] == 0
    assert out["created"] is False


def test_write_empty_string_path_is_typed_error():
    out = _write_executor({"path": "   "}, {"text": "data"}, None)
    assert out["status"] == "error"
    assert "no path" in out["error"]
    assert out["path"] == ""


def test_write_error_outputs_are_fully_present_and_typed():
    # Every error path returns the SAME complete, typed output shape.
    out = _write_executor({}, {}, None)
    assert set(out.keys()) == {"status", "path", "bytes_written",
                               "created", "error"}
    assert isinstance(out["path"], str)
    assert isinstance(out["bytes_written"], int)
    assert isinstance(out["created"], bool)
    assert isinstance(out["error"], str)


# ─── deterministic output ────────────────────────────────────────────


def test_write_is_deterministic(tmp_path):
    # Determinism = same input STATE → same output. A repeat write to the
    # SAME path is NOT the same input state (the file now exists, so the
    # honest `created` flips True→False — that is correct, not flaky). To
    # pin determinism we write from an identical starting state twice: two
    # fresh, never-existed targets in sibling dirs with identical content.
    # Outputs match modulo the path prefix → assert the path-independent
    # fields plus identical key sets (byte-stable cook for the parity gate).
    root = _iso(tmp_path)
    a = _write_executor({"path": str(root / "da" / "det.txt")},
                        {"text": "stable"}, None)
    b = _write_executor({"path": str(root / "db" / "det.txt")},
                        {"text": "stable"}, None)
    assert a["status"] == b["status"] == "ok"
    assert a["created"] is b["created"] is True
    assert a["bytes_written"] == b["bytes_written"]
    assert set(a.keys()) == set(b.keys())


# ─── registration ────────────────────────────────────────────────────


def test_fs_write_registered():
    import workflows.nodes.fs  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("fs.write") is not None


def test_fs_write_ports_are_typed():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.write")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"path": "string", "bytes_written": "number",
                         "created": "boolean"}
    in_ports = {p.name for p in spec.inputs}
    assert in_ports == {"path", "text"}
    # `path` is the only REQUIRED input.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"path"}


def test_fs_write_category_is_io():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.write")
    assert spec.category == "io"


def test_fs_write_config_schema_is_modular():
    # config_schema declares path / encoding / overwrite / make_dirs with
    # defaults — no hard-coded literals buried in the body.
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.write")
    assert set(spec.config_schema.keys()) == {"path", "encoding",
                                              "overwrite", "make_dirs"}
    assert spec.config_schema["encoding"]["default"] == "utf-8"
    assert spec.config_schema["overwrite"]["default"] is False
    assert spec.config_schema["make_dirs"]["default"] is True


# ─── end-to-end: cook the cell through a real WorkflowRunner ─────────


def test_fs_write_cooks_through_real_runner_and_reads_typed_outputs(tmp_path):
    """path source → fs.write → assert path / bytes_written / created come
    off the registered output ports, driven through a real WorkflowRunner
    (the canvas cook path, not just the executor). The file lands on disk."""
    import workflows.nodes.fs  # noqa: F401  registers fs.write
    from workflows.runner import WorkflowRunner
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType

    target = _iso(tmp_path) / "cooked.txt"

    # Minimal const source nodes feeding path + text (registered once).
    if _get_spec("_test.const_fswritepath") is None:
        register(NodeSpec(
            type="_test.const_fswritepath", category="_test",
            display_name="Test Const FS Write Path",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.STRING)],
            config_schema={}, icon="/"),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})

    graph = {
        "nodes": [
            {"id": "psrc", "type": "_test.const_fswritepath",
             "config": {"value": str(target)},
             "outs": [{"id": "value", "t": "string"}]},
            {"id": "tsrc", "type": "_test.const_fswritepath",
             "config": {"value": "cooked-content"},
             "outs": [{"id": "value", "t": "string"}]},
            {"id": "wr", "type": "fs.write", "config": {},
             "ins":  [{"id": "path", "t": "string"},
                      {"id": "text", "t": "string"}],
             "outs": [{"id": "path",          "t": "string"},
                      {"id": "bytes_written", "t": "number"},
                      {"id": "created",       "t": "boolean"}]},
        ],
        "wires": [
            {"from": ["psrc", "value"], "to": ["wr", "path"]},
            {"from": ["tsrc", "value"], "to": ["wr", "text"]},
        ],
    }
    out = WorkflowRunner(graph).pull("wr")

    assert out.get("status") == "ok"
    assert out["created"] is True
    assert out["path"] == os.path.abspath(str(target))
    assert out["bytes_written"] == len("cooked-content".encode("utf-8"))
    # The bytes really landed on disk via the cook path.
    assert target.read_text(encoding="utf-8") == "cooked-content"
