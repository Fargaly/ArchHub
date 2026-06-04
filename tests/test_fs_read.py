"""stem-rebuild Phase-0 — `fs.read`, the READ-ONLY single-file read cell.

`fs.read` is the natural pair to `fs.list` (fs.list finds files, fs.read reads
one). Point it at a file path; get back the decoded `text` plus metrics
`{size, bytes_read, truncated, lines, ext}`. A pure primitive (no fs host:
os.stat + open are in-process, need no probe/auth).

What's pinned here:
  * a successful read returns the file's text + correct size / lines / ext;
  * `size` is the os.stat byte size; `bytes_read` is how much we read
    (≤ max_bytes); `lines` is newline-count + 1 (0 for empty);
  * an empty file reads as text "" with lines 0;
  * `max_bytes` caps the read — a file bigger than the cap sets truncated=True
    and bytes_read == max_bytes;
  * a wired `path` input beats config (data.join "wired key wins");
  * non-utf8 / binary bytes decode WITH replacement and NEVER raise;
  * a missing / directory / empty path is a typed error with outputs present +
    empty, NEVER a crash;
  * READ-ONLY — the cell mutates nothing; tests build fixtures in `tmp_path`
    ONLY and assert the file is byte-identical after a read;
  * the cell cooks end-to-end through a real WorkflowRunner and its typed
    outputs are read off the registered output ports — the canvas cook path,
    not just the executor.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.fs import _read_executor  # noqa: E402


# ─── fixtures (tmp_path ONLY — never the real FS) ────────────────────
#
# NOTE: conftest.py's autouse `_isolate_secrets_store` creates an `ArchHub`
# sub-directory inside EVERY test's `tmp_path`. So `tmp_path` is NOT empty.
# Every helper below carves a DEDICATED, fully-owned file under `tmp_path`.


def _iso(tmp_path: Path, name: str = "readroot") -> Path:
    """A fresh, empty, test-owned directory under `tmp_path`."""
    root = tmp_path / name
    root.mkdir()
    return root


def _file(tmp_path: Path, name: str, content: str,
          encoding: str = "utf-8") -> Path:
    """Build + return a test-owned file with text `content`.

    Writes via `write_bytes` (NOT `write_text`) so the on-disk bytes are
    EXACTLY `content.encode(encoding)` — no platform newline translation
    (Windows `write_text` would rewrite '\\n' → '\\r\\n', desyncing the
    byte/line assertions from what was written). fs.read reads the real
    bytes back, so the fixture and the assertion stay in lockstep on every
    OS — the parity gate's whole point."""
    root = _iso(tmp_path)
    p = root / name
    p.write_bytes(content.encode(encoding))
    return p


# ─── success read ────────────────────────────────────────────────────


def test_read_returns_text_and_metrics(tmp_path):
    p = _file(tmp_path, "notes.txt", "line one\nline two\nline three")
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["status"] == "ok"
    assert out["text"] == "line one\nline two\nline three"
    # 2 newlines → 3 lines.
    assert out["lines"] == 3
    assert out["ext"] == "txt"
    # size is the on-disk byte count (ascii: 1 byte/char).
    assert out["size"] == len("line one\nline two\nline three".encode("utf-8"))
    assert out["bytes_read"] == out["size"]
    assert out["truncated"] is False


def test_read_output_fields_are_complete_and_typed(tmp_path):
    p = _file(tmp_path, "a.csv", "x,y\n1,2\n")
    out = _read_executor({"path": str(p)}, {}, None)
    # Every output present on success.
    assert set(out.keys()) >= {"status", "text", "size", "bytes_read",
                               "truncated", "lines", "ext"}
    assert isinstance(out["text"], str)
    assert isinstance(out["size"], int)
    assert isinstance(out["bytes_read"], int)
    assert isinstance(out["truncated"], bool)
    assert isinstance(out["lines"], int)
    assert out["ext"] == "csv"


def test_read_single_line_no_trailing_newline_is_one_line(tmp_path):
    p = _file(tmp_path, "oneline.txt", "just one line")
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["lines"] == 1
    assert out["text"] == "just one line"


def test_read_trailing_newline_counts_correctly(tmp_path):
    # "a\nb\n" → 2 newlines → count+1 == 3 (the trailing "" segment counts).
    p = _file(tmp_path, "tn.txt", "a\nb\n")
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["lines"] == 3


def test_read_ext_is_lowercased_and_dotless(tmp_path):
    p = _file(tmp_path, "DRAWING.DWG", "header-bytes")
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["ext"] == "dwg"      # lowercased + dotless, via _ext_of


def test_read_no_extension_file_has_empty_ext(tmp_path):
    p = _file(tmp_path, "Makefile", "all:\n\techo hi\n")
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["ext"] == ""


def test_read_output_is_json_serializable(tmp_path):
    p = _file(tmp_path, "j.txt", "some text\nmore")
    out = _read_executor({"path": str(p)}, {}, None)
    json.dumps(out)   # must not raise (survives disk-transport wires)


# ─── empty file ──────────────────────────────────────────────────────


def test_read_empty_file_has_zero_lines(tmp_path):
    p = _file(tmp_path, "empty.txt", "")
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["status"] == "ok"
    assert out["text"] == ""
    assert out["lines"] == 0          # empty content has no lines
    assert out["size"] == 0
    assert out["bytes_read"] == 0
    assert out["truncated"] is False


# ─── max_bytes truncation ────────────────────────────────────────────


def test_read_truncates_when_file_exceeds_max_bytes(tmp_path):
    p = _file(tmp_path, "big.txt", "0123456789" * 100)   # 1000 bytes
    out = _read_executor({"path": str(p), "max_bytes": 50}, {}, None)
    assert out["status"] == "ok"
    assert out["truncated"] is True
    assert out["bytes_read"] == 50
    assert out["text"] == ("0123456789" * 100)[:50]
    # `size` is still the FULL on-disk size, independent of the read cap.
    assert out["size"] == 1000


def test_read_not_truncated_when_within_max_bytes(tmp_path):
    p = _file(tmp_path, "small.txt", "abcdef")     # 6 bytes
    out = _read_executor({"path": str(p), "max_bytes": 1000}, {}, None)
    assert out["truncated"] is False
    assert out["bytes_read"] == 6
    assert out["text"] == "abcdef"


def test_read_max_bytes_exactly_file_size_is_not_truncated(tmp_path):
    # Boundary: cap == size → fully read, NOT truncated (cap is inclusive).
    p = _file(tmp_path, "exact.txt", "abcde")      # 5 bytes
    out = _read_executor({"path": str(p), "max_bytes": 5}, {}, None)
    assert out["truncated"] is False
    assert out["bytes_read"] == 5
    assert out["text"] == "abcde"


def test_read_bogus_max_bytes_falls_back_to_default(tmp_path):
    # A non-numeric max_bytes must not raise — it falls back to the default.
    p = _file(tmp_path, "f.txt", "hello world")
    out = _read_executor({"path": str(p), "max_bytes": "not-a-number"},
                         {}, None)
    assert out["status"] == "ok"
    assert out["truncated"] is False
    assert out["text"] == "hello world"


# ─── wired input beats config (data.join parity) ────────────────────


def test_read_wired_path_overrides_config(tmp_path):
    p = _file(tmp_path, "real.txt", "the real content")
    # config path is bogus; the wired input path wins.
    out = _read_executor(
        {"path": "C:/nonexistent-config-path.txt"},
        {"path": str(p)}, None)
    assert out["status"] == "ok"
    assert out["text"] == "the real content"


# ─── non-utf8 / binary bytes decode-with-replacement (never raises) ──


def test_read_non_utf8_bytes_decode_with_replacement(tmp_path):
    # Raw bytes that are NOT valid UTF-8 (0xff 0xfe) must decode without
    # raising — errors="replace" turns them into the U+FFFD replacement char.
    root = _iso(tmp_path)
    p = root / "binary.bin"
    p.write_bytes(b"\xff\xfe\x00bad-bytes\xc3\x28")
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["status"] == "ok"           # did NOT raise
    assert "�" in out["text"]          # replacement char present
    assert out["bytes_read"] == len(b"\xff\xfe\x00bad-bytes\xc3\x28")


def test_read_latin1_content_with_utf8_decoder_does_not_raise(tmp_path):
    # café written as latin-1 (the é is 0xe9) is invalid UTF-8 — decoding it
    # with the default utf-8 + replace must still succeed.
    root = _iso(tmp_path)
    p = root / "latin.txt"
    p.write_bytes("café".encode("latin-1"))
    out = _read_executor({"path": str(p)}, {}, None)
    assert out["status"] == "ok"
    assert out["text"].startswith("caf")


def test_read_honours_explicit_encoding(tmp_path):
    # Same latin-1 bytes, read WITH encoding=latin-1, round-trips cleanly.
    root = _iso(tmp_path)
    p = root / "latin2.txt"
    p.write_bytes("résumé".encode("latin-1"))
    out = _read_executor({"path": str(p), "encoding": "latin-1"}, {}, None)
    assert out["status"] == "ok"
    assert out["text"] == "résumé"


# ─── missing / directory / empty path → typed error, never a crash ──


def test_read_missing_path_is_typed_error(tmp_path):
    out = _read_executor({"path": str(tmp_path / "does-not-exist.txt")},
                         {}, None)
    assert out["status"] == "error"
    assert "not found" in out["error"]
    # Outputs still present + empty (upstream_error propagation stays typed).
    assert out["text"] == ""
    assert out["size"] == 0
    assert out["bytes_read"] == 0
    assert out["truncated"] is False
    assert out["lines"] == 0
    assert out["ext"] == ""


def test_read_no_path_is_typed_error():
    out = _read_executor({}, {}, None)
    assert out["status"] == "error"
    assert "no path" in out["error"]
    assert out["text"] == ""
    assert out["lines"] == 0


def test_read_empty_string_path_is_typed_error():
    out = _read_executor({"path": "   "}, {}, None)
    assert out["status"] == "error"
    assert "no path" in out["error"]
    assert out["text"] == ""


def test_read_directory_path_is_typed_error(tmp_path):
    d = _iso(tmp_path)        # a real directory, not a file
    out = _read_executor({"path": str(d)}, {}, None)
    assert out["status"] == "error"
    assert "directory" in out["error"]
    assert out["text"] == ""
    assert out["size"] == 0


def test_read_bad_encoding_name_is_typed_error_not_a_crash(tmp_path):
    # REGRESSION (jury LENS independence-diligence, 2026-06-04): `encoding` is
    # a user-settable config knob. errors="replace" only tames bad BYTES — an
    # unknown codec NAME raises LookupError BEFORE replacement. The total-
    # tolerance contract requires a TYPED ERROR, never a raise. This asserts
    # the decode is guarded: a bogus codec yields status=error with every
    # output present + empty, and does NOT propagate an exception.
    p = _iso(tmp_path) / "x.txt"
    p.write_bytes(b"hello world")
    out = _read_executor({"path": str(p), "encoding": "bogus-codec-name"},
                         {}, None)
    assert out["status"] == "error"
    assert "encoding" in out["error"]
    assert out["text"] == ""
    assert out["size"] == 0
    assert out["bytes_read"] == 0
    assert out["truncated"] is False
    assert out["lines"] == 0
    assert out["ext"] == ""


def test_read_none_encoding_is_typed_error_not_a_crash(tmp_path):
    # A non-str encoding (e.g. wired None) must also degrade to a typed error,
    # never a TypeError crash — same total-tolerance guarantee.
    p = _iso(tmp_path) / "x.txt"
    p.write_bytes(b"hello")
    out = _read_executor({"path": str(p), "encoding": None}, {}, None)
    # Either it falls back to the utf-8 default (ok) or it is a typed error;
    # the ONLY unacceptable outcome is a raised exception. Both are tolerant.
    assert out["status"] in ("ok", "error")
    assert set(out.keys()) >= {"status", "text", "size", "bytes_read",
                               "truncated", "lines", "ext"}


def test_read_error_outputs_are_fully_present_and_typed():
    # Every error path returns the SAME complete, typed output shape.
    out = _read_executor({}, {}, None)
    assert set(out.keys()) == {"status", "text", "size", "bytes_read",
                               "truncated", "lines", "ext", "error"}
    assert isinstance(out["text"], str)
    assert isinstance(out["size"], int)
    assert isinstance(out["bytes_read"], int)
    assert isinstance(out["truncated"], bool)
    assert isinstance(out["lines"], int)
    assert isinstance(out["ext"], str)


# ─── deterministic output ────────────────────────────────────────────


def test_read_is_deterministic(tmp_path):
    p = _file(tmp_path, "det.txt", "stable\ncontent\nhere")
    a = _read_executor({"path": str(p)}, {}, None)
    b = _read_executor({"path": str(p)}, {}, None)
    assert a == b      # byte-stable cook for the parity gate


# ─── READ-ONLY contract — the file is untouched after a read ─────────


def test_read_mutates_nothing(tmp_path):
    p = _file(tmp_path, "immutable.txt", "do not change me\nsecond line\n")
    root = p.parent
    before_tree = sorted(str(q.relative_to(root)) for q in root.rglob("*"))
    before_bytes = p.read_bytes()
    before_mtime = os.stat(p).st_mtime

    # Run several modes — full read, truncated read, explicit encoding.
    _read_executor({"path": str(p)}, {}, None)
    _read_executor({"path": str(p), "max_bytes": 5}, {}, None)
    _read_executor({"path": str(p), "encoding": "latin-1"}, {}, None)

    after_tree = sorted(str(q.relative_to(root)) for q in root.rglob("*"))
    after_bytes = p.read_bytes()
    after_mtime = os.stat(p).st_mtime
    assert before_tree == after_tree        # no file created / moved / deleted
    assert before_bytes == after_bytes      # content byte-identical
    assert before_mtime == after_mtime      # not even mtime touched (no write)


# ─── registration ───────────────────────────────────────────────────


def test_fs_read_registered():
    import workflows.nodes.fs  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("fs.read") is not None


def test_fs_read_ports_are_typed():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.read")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"text": "string", "size": "number",
                         "bytes_read": "number", "truncated": "boolean",
                         "lines": "number", "ext": "string"}
    in_ports = {p.name for p in spec.inputs}
    assert in_ports == {"path"}
    # `path` is the only (and required) input.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"path"}


def test_fs_read_category_is_io():
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.read")
    assert spec.category == "io"


def test_fs_read_config_schema_is_modular(tmp_path):
    # config_schema declares path / encoding / max_bytes with defaults — no
    # hard-coded literals buried in the body.
    import workflows.nodes.fs  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("fs.read")
    assert set(spec.config_schema.keys()) == {"path", "encoding", "max_bytes"}
    assert spec.config_schema["encoding"]["default"] == "utf-8"
    assert isinstance(spec.config_schema["max_bytes"]["default"], int)


# ─── end-to-end: cook the cell through a real WorkflowRunner ────────


def test_fs_read_cooks_through_real_runner_and_reads_typed_outputs(tmp_path):
    """path source → fs.read → assert text / size / lines come off the
    registered output ports, driven through a real outer WorkflowRunner (the
    canvas cook path, not just the executor)."""
    import workflows.nodes.fs  # noqa: F401  registers fs.read
    from workflows.runner import WorkflowRunner
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType

    p = _file(tmp_path, "cooked.txt", "alpha\nbeta\ngamma")

    # Minimal const source node feeding the path string (registered once).
    if _get_spec("_test.const_fsreadpath") is None:
        register(NodeSpec(
            type="_test.const_fsreadpath", category="_test",
            display_name="Test Const FS Read Path",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.STRING)],
            config_schema={}, icon="/"),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})

    graph = {
        "nodes": [
            {"id": "src", "type": "_test.const_fsreadpath",
             "config": {"value": str(p)},
             "outs": [{"id": "value", "t": "string"}]},
            {"id": "rd", "type": "fs.read", "config": {},
             "ins":  [{"id": "path", "t": "string"}],
             "outs": [{"id": "text",       "t": "string"},
                      {"id": "size",       "t": "number"},
                      {"id": "bytes_read", "t": "number"},
                      {"id": "truncated",  "t": "boolean"},
                      {"id": "lines",      "t": "number"},
                      {"id": "ext",        "t": "string"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["rd", "path"]},
        ],
    }
    out = WorkflowRunner(graph).pull("rd")

    assert out.get("status") == "ok"
    assert out["text"] == "alpha\nbeta\ngamma"
    assert out["lines"] == 3
    assert out["ext"] == "txt"
    assert out["truncated"] is False
