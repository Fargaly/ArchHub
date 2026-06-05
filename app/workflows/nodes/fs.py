"""Filesystem primitive — stem-rebuild Phase-0 (in-place plan IO cell-family).

`fs.list` is a READ-ONLY directory listing → typed file-rows. It turns the
raw `os.walk` / `glob` blob that 3 of the last 5 file-walk jobs dropped to
(BBC4 submittal QC, dated-folder reconcile, DD↔DWG match) into a composable
stem cell: point it at a directory, get back a list of typed rows
`{path, name, ext, size, is_dir, mtime}` plus a `count`.

DECISION — a PURE PRIMITIVE, not a registered fs host. Every `app/connectors/`
entry is a stateful adapter to an *external running application* — it probes
reachability, surfaces "host unreachable", exists because Revit/Excel/etc. are
out-of-process. The local filesystem is none of that: `os.scandir` is
in-process, synchronous, always reachable, needs no probe / auth / session.
Wrapping a local read in a connector would mint ceremony with zero payload
(a LIBRARY-FIRST / ONE-SYSTEM violation). So `fs.list` is modeled 1:1 on
`data.join` / `aggregate.py`: a pure executor over typed ports with a
`config_schema`, registered via `register(NodeSpec(...), _list_executor)`,
status-tagged, total-tolerant (never raises).

READ-ONLY pair — `fs.list` + `fs.read`. Those two cells perform ZERO
filesystem mutation: only `os.scandir` / `os.walk` / `os.stat` / `open(rb)`.
Their per-cell READ-ONLY contracts (documented on each executor) remain
load-bearing and are exercised by their tests.

IO-WRITE pair — `fs.write` + `fs.move` (this module's later half, the cells
the read-only pair deferred). They ARE side-effecting — that is their job, the
way any IO function writes bytes or renames a path. They perform the IO
honestly, total-tolerantly (a bad input is a typed error, never a raise), and
deterministically, and they guard against accidental clobber with an explicit
`overwrite` flag (an existing destination is a typed error unless `overwrite`
is set). RUNTIME SAFETY of AI-driven writes is handled UPSTREAM by the
already-shipped plan-mode approval gate on the composer / agent path
(USER-AGENCY: every AI write to a host is approval-gated by default); a user
who places + runs one of these nodes is taking their own action, exactly like
calling `open(path, "w")`.

No host, no LLM — the local filesystem is in-process, synchronous, always
reachable, needs no probe / auth / session, so these stay pure stem cells
(not stateful connectors). Lives alongside relate.py (data.join) and
aggregate.py (reduce / group_by / sort) as a keep-as-cell stem family.

CONFIRMED (Phase-0, ONE-SYSTEM): there is intentionally NO
`app/connectors/fs_connector.py`, and none should ever be minted —
fs.list/read/write/move are PURE CELLS registered into the one node-type
registry (`app/workflows/registry.py`'s `_REGISTRY`, the registry the
runner cooks from), NOT a stateful connector host. A connector exists
only for an out-of-process app that needs a reachability probe + session;
the local FS has neither, so a connector would be pure ceremony (a
LIBRARY-FIRST / ONE-SYSTEM violation). See `docs/NODE_GRAMMAR.md`
("`fs` is a CELL family, not a connector host") for the full rationale.
"""
from __future__ import annotations

import fnmatch
import os
import shutil

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ── shared helpers ────────────────────────────────────────────────────

# fs.read default cap — modular config default (no hard-coded literal in the
# executor body). 5 MB: large enough for any normal text/source/CSV/DWG-meta
# file, small enough that a runaway read can't OOM the cook.
_READ_DEFAULT_MAX_BYTES = 5_000_000


def _read_error(message: str) -> dict:
    """A typed fs.read error with EVERY output present + empty (total
    tolerance: a bad path / read never raises and never drops an output, so
    runner.py's upstream_error propagation stays well-typed). Mirrors
    fs.list's `{"status": "error", <all-outputs-empty>, "error": ...}`."""
    return {"status": "error", "text": "", "size": 0, "bytes_read": 0,
            "truncated": False, "lines": 0, "ext": "", "error": message}


def _ext_of(name: str) -> str:
    """Lowercased extension WITHOUT the dot — the form a file-walk filters
    on (`row["ext"] == "dwg"`). "" for a no-extension name or a dotfile
    (`os.path.splitext('.gitignore')` → ('.gitignore', ''), already '')."""
    return os.path.splitext(name)[1].lstrip(".").lower()


def _row(full_path: str, name: str, is_dir: bool, stat_result) -> dict:
    """A flat, always-complete, JSON-serializable row.

    Every field is always present so the row survives Speckle disk-transport
    wires and renders in `watch.preview as=table`. `size`/`mtime` come from a
    pre-fetched `stat_result` (None when the stat failed — total tolerance:
    an unreadable entry is emitted with size=0, mtime=0.0, never dropped on
    its own account and never aborting the listing)."""
    size = 0
    mtime = 0.0
    if stat_result is not None:
        try:
            size = 0 if is_dir else int(stat_result.st_size)
            mtime = float(stat_result.st_mtime)
        except Exception:
            size, mtime = 0, 0.0
    return {
        "path": os.path.abspath(full_path),
        "name": name,
        "ext": "" if is_dir else _ext_of(name),
        "size": size,
        "is_dir": bool(is_dir),
        "mtime": mtime,
    }


def _matches(name: str, pattern: str) -> bool:
    """Glob filter on the basename. Empty / None pattern = keep everything.
    `fnmatch` is case-insensitive on case-insensitive platforms (Windows),
    matching how a BBC4-style walk filters `*.dwg` / `*.xlsx`."""
    if not pattern:
        return True
    return fnmatch.fnmatch(name, pattern)


def _safe_stat_entry(entry) -> object:
    """`entry.stat()` wrapped in try/except — a single unreadable entry
    (permission, broken symlink, race-deleted mid-scan) yields None, which
    `_row` renders as size=0/mtime=0.0. Never raises (the aggregate._sortable
    'total tolerance — never raise on exotic input' stance applied to the FS).
    `follow_symlinks=False` so a dangling symlink doesn't raise here."""
    try:
        return entry.stat(follow_symlinks=False)
    except Exception:
        return None


def _safe_stat_path(path: str) -> object:
    """`os.stat` wrapped in try/except (the os.walk path, which yields names
    not DirEntry objects). None on any failure — same total tolerance."""
    try:
        return os.stat(path)
    except Exception:
        return None


# ── fs.list ───────────────────────────────────────────────────────────

def _list_executor(config: dict, inputs: dict, ctx) -> dict:
    """READ-ONLY directory listing → typed file-rows.

    Flat (`os.scandir`) by default; `recursive` descends via `os.walk`.
    `pattern` is a glob filter on the basename; `include_dirs` emits
    directory rows too. A missing / inaccessible `path` is a typed error
    with outputs still present + empty (so `upstream_error` propagation in
    runner.py stays well-typed), NEVER a crash. Rows are sorted by `path`
    for a stable, parity-gateable cook (os.scandir order is not guaranteed).
    """
    cfg = config or {}
    ins = inputs or {}

    # wired input beats config (mirrors data.join "wired key beats config").
    path = ins.get("path") if ins.get("path") is not None else cfg.get("path")
    pattern = ins.get("pattern") if ins.get("pattern") is not None else cfg.get("pattern")
    recursive = bool(cfg.get("recursive", False))
    include_dirs = bool(cfg.get("include_dirs", False))

    path = "" if path is None else str(path)
    pattern = "" if pattern is None else str(pattern)

    # ── missing / inaccessible path → typed error (outputs present + empty).
    if not path.strip():
        return {"status": "error", "rows": [], "count": 0,
                "error": "fs.list: no path — set `path` (config) or wire it"}
    if not os.path.exists(path):
        return {"status": "error", "rows": [], "count": 0,
                "error": f"fs.list: path not found: {path!r}"}
    if not os.path.isdir(path):
        return {"status": "error", "rows": [], "count": 0,
                "error": f"fs.list: not a directory: {path!r}"}

    rows: list = []
    try:
        if recursive:
            # os.walk — emit a file row per file; if include_dirs, a row per
            # sub-directory too. Root-relative full paths via os.path.join.
            for dirpath, dirnames, filenames in os.walk(path):
                if include_dirs:
                    for dname in dirnames:
                        if not _matches(dname, pattern):
                            continue
                        full = os.path.join(dirpath, dname)
                        rows.append(_row(full, dname, True, _safe_stat_path(full)))
                for fname in filenames:
                    if not _matches(fname, pattern):
                        continue
                    full = os.path.join(dirpath, fname)
                    rows.append(_row(full, fname, False, _safe_stat_path(full)))
        else:
            # Flat — os.scandir; cheap is_dir() + stat() per DirEntry.
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except Exception:
                        # A racing/exotic entry whose type can't be read:
                        # treat as a file so it is still surfaced (tolerant).
                        is_dir = False
                    if is_dir and not include_dirs:
                        continue
                    if not _matches(entry.name, pattern):
                        continue
                    rows.append(_row(entry.path, entry.name, is_dir,
                                     _safe_stat_entry(entry)))
    except Exception as ex:
        # A failure that escapes the per-entry guards (e.g. the dir was
        # deleted between the isdir check and the scan) → typed error, not a
        # crash. Outputs stay present + empty.
        return {"status": "error", "rows": [], "count": 0,
                "error": f"{type(ex).__name__}: {ex}"}

    # Deterministic order — sort by path so the golden-oracle parity gate
    # (byte-identical cook) is stable across OS/filesystem enumeration order.
    rows.sort(key=lambda r: r["path"])
    return {"status": "ok", "rows": rows, "count": len(rows)}


register(NodeSpec(
    type="fs.list", category="io", display_name="List Files",
    description="READ-ONLY directory listing → typed file-rows "
                "{path, name, ext, size, is_dir, mtime}. Point it at a "
                "folder; get back the files (and dirs, if `include_dirs`) "
                "as rows plus a `count`. `pattern` is an optional glob "
                "filter (e.g. '*.dwg'); `recursive` descends sub-folders. "
                "A wired `path`/`pattern` input overrides config. A missing "
                "or unreadable path is a typed error, never a crash. Lists "
                "only — no write / move / delete.",
    inputs=[Port(name="path",    type=PortType.STRING, required=True),
            Port(name="pattern", type=PortType.STRING)],
    outputs=[Port(name="rows",  type=PortType.LIST),
             Port(name="count", type=PortType.NUMBER)],
    config_schema={
        "path":         {"type": "string",
                         "description": "Directory to list (wired `path` "
                                        "input overrides)."},
        "pattern":      {"type": "string",
                         "description": "Optional glob filter, e.g. '*.dwg' "
                                        "(empty = all)."},
        "recursive":    {"type": "boolean", "default": False,
                         "description": "Descend into sub-directories "
                                        "(os.walk) vs flat (os.scandir)."},
        "include_dirs": {"type": "boolean", "default": False,
                         "description": "Include directory rows, not just "
                                        "files."},
    },
    icon="📁"), _list_executor)


# ── fs.read ───────────────────────────────────────────────────────────

def _read_executor(config: dict, inputs: dict, ctx) -> dict:
    """READ-ONLY single-file read → decoded text + byte/line metrics.

    The natural pair to `fs.list`: `fs.list` finds files, `fs.read` reads
    one. Point it at a file path; get back its `text` (decoded with
    `encoding`, `errors="replace"` so binary / mis-encoded bytes can never
    raise), the file's actual byte `size` (os.stat), how many `bytes_read`
    (≤ `max_bytes`), whether it was `truncated` (file bigger than the cap),
    a `lines` count, and the dotless lowercased `ext` (reuses `_ext_of`).

    READ-ONLY contract — load-bearing. Only `os.stat` + `open(..., "rb")`
    + a bounded `.read(max_bytes)`. ZERO mutation: no write, move, create,
    delete, truncate, or mode change anywhere. A wired `path` input beats
    config (mirrors `fs.list` / data.join "wired key wins").

    TOTAL-TOLERANT — never raises. A missing / empty / directory / unreadable
    path, or any read exception, is a typed error dict with EVERY output
    present and empty (so `upstream_error` propagation in runner.py stays
    well-typed). On success `status` is "ok" with all fields populated.
    Deterministic: the same file yields the same outputs every cook, so the
    golden-oracle parity gate is byte-stable.
    """
    cfg = config or {}
    ins = inputs or {}

    # wired input beats config (mirrors fs.list "wired key beats config").
    path = ins.get("path") if ins.get("path") is not None else cfg.get("path")
    path = "" if path is None else str(path)

    encoding = cfg.get("encoding")
    encoding = "utf-8" if encoding is None else str(encoding)

    # `max_bytes` — a cap so a huge file can't OOM the cook. Coerce
    # tolerantly; a bogus / non-numeric / negative value falls back to the
    # default rather than raising (total tolerance on config too).
    try:
        max_bytes = int(cfg.get("max_bytes", _READ_DEFAULT_MAX_BYTES))
        if max_bytes < 0:
            max_bytes = _READ_DEFAULT_MAX_BYTES
    except (TypeError, ValueError):
        max_bytes = _READ_DEFAULT_MAX_BYTES

    # ── missing / inaccessible path → typed error (outputs present + empty).
    if not path.strip():
        return _read_error("fs.read: no path — set `path` (config) or wire it")
    if not os.path.exists(path):
        return _read_error(f"fs.read: path not found: {path!r}")
    if os.path.isdir(path):
        return _read_error(f"fs.read: is a directory, not a file: {path!r}")

    # Actual on-disk byte size via os.stat (independent of how much we read).
    try:
        size = int(os.stat(path).st_size)
    except Exception as ex:
        return _read_error(f"fs.read: stat failed: {type(ex).__name__}: {ex}")

    # Bounded binary read, then decode-with-replacement (never raises on
    # non-text / wrong-encoding bytes). Reading max_bytes+1 lets us detect
    # truncation precisely even when os.stat and the read disagree (e.g. a
    # growing file / a special file whose stat size is 0).
    try:
        with open(path, "rb") as fh:
            raw = fh.read(max_bytes + 1)
    except Exception as ex:
        return _read_error(f"fs.read: {type(ex).__name__}: {ex}")

    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    bytes_read = len(raw)

    # `encoding` is a user-settable config knob, so a bad value must be a
    # TYPED ERROR, not a crash — total-tolerance contract. errors="replace"
    # only tames bad BYTES; an unknown codec NAME (LookupError) or a non-str
    # encoding (TypeError) raises BEFORE replacement, so the decode itself is
    # guarded. Broad catch: any decode failure becomes a typed error with
    # every output present + empty, never a raise (matches the docstring).
    try:
        text = raw.decode(encoding, errors="replace")
    except Exception as ex:
        return _read_error(
            f"fs.read: cannot decode with encoding {encoding!r}: "
            f"{type(ex).__name__}: {ex}")
    # `lines` — newline count + 1 for non-empty content; 0 for empty (an
    # empty file / empty read has no lines). Counts on the decoded text so
    # the metric matches what a reader sees.
    lines = (text.count("\n") + 1) if text else 0

    return {"status": "ok", "text": text, "size": size,
            "bytes_read": bytes_read, "truncated": bool(truncated),
            "lines": lines, "ext": _ext_of(os.path.basename(path))}


register(NodeSpec(
    type="fs.read", category="io", display_name="Read File",
    description="READ-ONLY single-file read → decoded `text` plus metrics "
                "{size, bytes_read, truncated, lines, ext}. The pair to "
                "fs.list (which finds files): point it at one file path and "
                "get its text back, decoded with `encoding` (binary / "
                "mis-encoded bytes are replaced, never crash). `max_bytes` "
                "caps the read so a huge file can't OOM; `truncated` is True "
                "when the file is bigger than the cap. A wired `path` input "
                "overrides config. A missing / directory / unreadable path "
                "is a typed error, never a crash. Reads only — no write / "
                "move / delete.",
    inputs=[Port(name="path", type=PortType.STRING, required=True)],
    outputs=[Port(name="text",       type=PortType.STRING),
             Port(name="size",       type=PortType.NUMBER),
             Port(name="bytes_read", type=PortType.NUMBER),
             Port(name="truncated",  type=PortType.BOOLEAN),
             Port(name="lines",      type=PortType.NUMBER),
             Port(name="ext",        type=PortType.STRING)],
    config_schema={
        "path":      {"type": "string",
                      "description": "File to read (wired `path` input "
                                     "overrides)."},
        "encoding":  {"type": "string", "default": "utf-8",
                      "description": "Text decode codec; bytes that don't "
                                     "decode are replaced (never crash)."},
        "max_bytes": {"type": "number", "default": _READ_DEFAULT_MAX_BYTES,
                      "description": "Cap on bytes read to avoid OOM on huge "
                                     "files; `truncated` is True past it."},
    },
    icon="📄"), _read_executor)


# ── fs.write ──────────────────────────────────────────────────────────

def _write_error(message: str) -> dict:
    """A typed fs.write error with EVERY output present + empty (total
    tolerance: a bad path / write never raises and never drops an output, so
    runner.py's upstream_error propagation stays well-typed). Mirrors
    fs.read's `_read_error` `{"status": "error", <all-outputs-empty>, ...}`.
    `path` is "" (nothing written), `bytes_written` 0, `created` False."""
    return {"status": "error", "path": "", "bytes_written": 0,
            "created": False, "error": message}


def _write_executor(config: dict, inputs: dict, ctx) -> dict:
    """WRITE text to a file → the abspath written + byte/created metrics.

    The write half of the fs stem family (fs.list finds, fs.read reads,
    fs.write writes). Point it at a path and give it `text`; it encodes the
    text with `encoding` and writes those bytes, returning the absolute
    `path` written, how many `bytes_written`, and whether the file was
    `created` (True if it did not exist before, False if it was overwritten).

    SIDE-EFFECTING by design — it writes bytes to disk, the way any IO
    function does. It guards against accidental clobber: if the path EXISTS
    and `overwrite` is False, it is a TYPED ERROR and the existing file is
    left byte-identical (never truncated). `make_dirs` (default True) creates
    missing parent directories; with `make_dirs` False a missing parent is a
    typed error rather than an auto-create. A wired `text` / `path` input
    beats config (mirrors fs.list / fs.read / data.join "wired key wins").

    TOTAL-TOLERANT — never raises. A missing / empty path, a path that is an
    existing directory, an existing file with `overwrite` False, a bad
    `encoding` (guarded exactly like fs.read guards decode — an unknown codec
    NAME or non-str encoding raises on encode BEFORE any write, so the encode
    is wrapped), `make_dirs` False with a missing parent, or any OSError is a
    typed error dict with EVERY output present + empty. Deterministic: the
    same inputs produce the same bytes + the same outputs every cook.
    """
    cfg = config or {}
    ins = inputs or {}

    # wired input beats config (mirrors fs.read "wired key beats config").
    path = ins.get("path") if ins.get("path") is not None else cfg.get("path")
    path = "" if path is None else str(path)

    text = ins.get("text") if ins.get("text") is not None else cfg.get("text")
    text = "" if text is None else str(text)

    encoding = cfg.get("encoding")
    encoding = "utf-8" if encoding is None else str(encoding)

    overwrite = bool(cfg.get("overwrite", False))
    make_dirs = bool(cfg.get("make_dirs", True))

    # ── missing / inaccessible path → typed error (outputs present + empty).
    if not path.strip():
        return _write_error(
            "fs.write: no path — set `path` (config) or wire it")

    abspath = os.path.abspath(path)

    # An existing directory can never be a write target (writing bytes to a
    # directory path is nonsensical) — typed error, not a crash.
    if os.path.isdir(abspath):
        return _write_error(
            f"fs.write: is a directory, not a file: {abspath!r}")

    # Clobber guard — the whole point of `overwrite`. An existing file with
    # overwrite False is a typed error and is left UNTOUCHED (we never open
    # it for writing, so it is not truncated). `exists` is checked once here.
    exists = os.path.exists(abspath)
    if exists and not overwrite:
        return _write_error(
            f"fs.write: file exists and overwrite is False: {abspath!r}")
    created = not exists

    # `encoding` is a user-settable config knob, so a bad value must be a
    # TYPED ERROR, not a crash — total-tolerance contract (mirrors fs.read's
    # guarded decode). Encode BEFORE touching the filesystem so a bogus codec
    # NAME (LookupError) or non-str encoding (TypeError) fails cleanly with
    # nothing written — no partial / truncated file. errors="strict" (the
    # default) is intentional on write: silently mangling the user's text
    # with replacement chars would be dishonest; an un-encodable char in the
    # chosen codec is surfaced as a typed error.
    try:
        data = text.encode(encoding)
    except Exception as ex:
        return _write_error(
            f"fs.write: cannot encode with encoding {encoding!r}: "
            f"{type(ex).__name__}: {ex}")

    # Parent-directory handling. make_dirs True → create the parent chain
    # (os.makedirs(exist_ok=True) is idempotent + tolerant of an existing
    # tree). make_dirs False with a missing parent → typed error, not an
    # auto-create (the user opted out of directory creation).
    parent = os.path.dirname(abspath)
    if parent:
        if make_dirs:
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception as ex:
                return _write_error(
                    f"fs.write: cannot create parent dir {parent!r}: "
                    f"{type(ex).__name__}: {ex}")
        elif not os.path.isdir(parent):
            return _write_error(
                f"fs.write: parent dir missing and make_dirs is False: "
                f"{parent!r}")

    # The write itself — bounded to a single open()/write() of the encoded
    # bytes. Any OSError (permission, read-only FS, disk full, a path
    # component that is a file, a race that turned the path into a dir) is a
    # typed error, never a crash. Outputs stay present + empty.
    try:
        with open(abspath, "wb") as fh:
            fh.write(data)
    except Exception as ex:
        return _write_error(
            f"fs.write: {type(ex).__name__}: {ex}")

    return {"status": "ok", "path": abspath,
            "bytes_written": len(data), "created": bool(created)}


register(NodeSpec(
    type="fs.write", category="io", display_name="Write File",
    description="WRITE text to a file → the absolute `path` written plus "
                "{bytes_written, created}. The write half of the fs stem "
                "family (fs.list finds, fs.read reads, fs.write writes): give "
                "it a path and `text`; it encodes with `encoding` and writes "
                "the bytes. `created` is True when the file was new. SIDE-"
                "EFFECTING by design — it writes to disk. It will NOT clobber: "
                "if the path exists and `overwrite` is False it is a typed "
                "error and the file is left untouched. `make_dirs` (default "
                "True) creates missing parent folders. A wired `text` / `path` "
                "input overrides config. A missing / directory path, an "
                "existing file without overwrite, a bad encoding, or any IO "
                "error is a typed error, never a crash.",
    inputs=[Port(name="path", type=PortType.STRING, required=True),
            Port(name="text", type=PortType.STRING)],
    outputs=[Port(name="path",          type=PortType.STRING),
             Port(name="bytes_written", type=PortType.NUMBER),
             Port(name="created",       type=PortType.BOOLEAN)],
    config_schema={
        "path":      {"type": "string",
                      "description": "File to write (wired `path` input "
                                     "overrides)."},
        "encoding":  {"type": "string", "default": "utf-8",
                      "description": "Text encode codec; an un-encodable char "
                                     "/ bad codec is a typed error (no "
                                     "partial write)."},
        "overwrite": {"type": "boolean", "default": False,
                      "description": "If the file exists: True replaces it, "
                                     "False is a typed error (no clobber)."},
        "make_dirs": {"type": "boolean", "default": True,
                      "description": "Create missing parent directories; "
                                     "False errors on a missing parent."},
    },
    icon="📝"), _write_executor)


# ── fs.move ───────────────────────────────────────────────────────────

def _move_error(message: str) -> dict:
    """A typed fs.move error with EVERY output present + empty (total
    tolerance: a bad src / dst never raises and never drops an output, so
    runner.py's upstream_error propagation stays well-typed). Mirrors the
    `_read_error` / `_write_error` shape. `src` / `dst` are "" (nothing
    moved), `moved` False."""
    return {"status": "error", "src": "", "dst": "", "moved": False,
            "error": message}


def _move_executor(config: dict, inputs: dict, ctx) -> dict:
    """MOVE / rename a file or directory → the abspaths + a `moved` flag.

    The move half of the fs stem family. Give it `src` and `dst`; it renames
    / relocates src to dst, returning the absolute `src` and `dst` paths and
    `moved` True. Uses `shutil.move` semantics (a same-filesystem rename, or
    a copy-then-delete across filesystems), so it handles files and whole
    directory trees.

    SIDE-EFFECTING by design — it moves a path on disk. It guards against
    accidental clobber: if `dst` EXISTS and `overwrite` is False it is a
    TYPED ERROR and BOTH paths are left untouched; with `overwrite` True an
    existing dst is replaced first. `make_dirs` (default True) creates the
    dst parent directory chain when missing. A wired `src` / `dst` input
    beats config (mirrors the rest of the fs family "wired key wins").

    TOTAL-TOLERANT — never raises. A missing / empty `src` or `dst`, a `src`
    that does not exist, a `dst` that exists with `overwrite` False, a
    `make_dirs` False with a missing dst parent, or any OSError / shutil
    error is a typed error dict with EVERY output present + empty.
    Deterministic.
    """
    cfg = config or {}
    ins = inputs or {}

    # wired input beats config (mirrors the rest of the fs family).
    src = ins.get("src") if ins.get("src") is not None else cfg.get("src")
    src = "" if src is None else str(src)

    dst = ins.get("dst") if ins.get("dst") is not None else cfg.get("dst")
    dst = "" if dst is None else str(dst)

    overwrite = bool(cfg.get("overwrite", False))
    make_dirs = bool(cfg.get("make_dirs", True))

    # ── missing src / dst → typed error (outputs present + empty).
    if not src.strip():
        return _move_error("fs.move: no src — set `src` (config) or wire it")
    if not dst.strip():
        return _move_error("fs.move: no dst — set `dst` (config) or wire it")

    abssrc = os.path.abspath(src)
    absdst = os.path.abspath(dst)

    if not os.path.exists(abssrc):
        return _move_error(f"fs.move: src not found: {abssrc!r}")

    # Clobber guard — an existing dst with overwrite False is a typed error
    # and BOTH paths are left untouched (we return before any move). With
    # overwrite True, remove the existing dst first so the move always lands
    # on a clear target (shutil.move would otherwise move src INTO an
    # existing dst directory rather than replacing it — surprising). os.path
    # .lexists catches a dangling symlink at dst too.
    if os.path.lexists(absdst):
        if not overwrite:
            return _move_error(
                f"fs.move: dst exists and overwrite is False: {absdst!r}")
        try:
            if os.path.isdir(absdst) and not os.path.islink(absdst):
                shutil.rmtree(absdst)
            else:
                os.remove(absdst)
        except Exception as ex:
            return _move_error(
                f"fs.move: cannot replace existing dst {absdst!r}: "
                f"{type(ex).__name__}: {ex}")

    # Parent-directory handling for dst — same contract as fs.write.
    parent = os.path.dirname(absdst)
    if parent:
        if make_dirs:
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception as ex:
                return _move_error(
                    f"fs.move: cannot create dst parent dir {parent!r}: "
                    f"{type(ex).__name__}: {ex}")
        elif not os.path.isdir(parent):
            return _move_error(
                f"fs.move: dst parent dir missing and make_dirs is False: "
                f"{parent!r}")

    # The move itself. shutil.move handles cross-filesystem moves (copy +
    # delete) and directory trees; passing the absolute dst PATH (not a
    # directory) means the result lands exactly at absdst. Any OSError /
    # shutil.Error is a typed error, never a crash.
    try:
        shutil.move(abssrc, absdst)
    except Exception as ex:
        return _move_error(f"fs.move: {type(ex).__name__}: {ex}")

    return {"status": "ok", "src": abssrc, "dst": absdst, "moved": True}


register(NodeSpec(
    type="fs.move", category="io", display_name="Move File",
    description="MOVE / rename a file or directory → the absolute `src` + "
                "`dst` paths plus a `moved` flag. The move half of the fs "
                "stem family: give it `src` and `dst`; it relocates src to "
                "dst (shutil.move semantics — handles files and whole "
                "folders, across filesystems). SIDE-EFFECTING by design. It "
                "will NOT clobber: if `dst` exists and `overwrite` is False it "
                "is a typed error and both paths are left untouched; "
                "`overwrite` True replaces dst. `make_dirs` (default True) "
                "creates the dst parent folders. A wired `src` / `dst` input "
                "overrides config. A missing src, an existing dst without "
                "overwrite, or any IO error is a typed error, never a crash.",
    inputs=[Port(name="src", type=PortType.STRING, required=True),
            Port(name="dst", type=PortType.STRING)],
    outputs=[Port(name="src",   type=PortType.STRING),
             Port(name="dst",   type=PortType.STRING),
             Port(name="moved", type=PortType.BOOLEAN)],
    config_schema={
        "src":       {"type": "string",
                      "description": "Source path to move (wired `src` input "
                                     "overrides)."},
        "dst":       {"type": "string",
                      "description": "Destination path (wired `dst` input "
                                     "overrides)."},
        "overwrite": {"type": "boolean", "default": False,
                      "description": "If dst exists: True replaces it, False "
                                     "is a typed error (no clobber)."},
        "make_dirs": {"type": "boolean", "default": True,
                      "description": "Create missing dst parent directories; "
                                     "False errors on a missing parent."},
    },
    icon="🚚"), _move_executor)
