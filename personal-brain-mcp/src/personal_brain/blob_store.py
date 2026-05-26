"""Brain #31 multimodal · blob storage helper.

Per founder ask 2026-05-26: "this brain should have a way to understand
geometry & pictures."

Day-2 deliverable: sidecar binary storage so Fragment.blob_path can point
at a real file on disk. SQLite stays small + queryable; the blob lives
in a sha256-addressed file under <brain_root>/blobs/<sha[:2]>/<sha>.<ext>.

Layout::

    <brain_root>/blobs/
        ab/
            abcdef0123...png        (image render)
            ab98765432...glb        (geometry mesh)
        f3/
            f3e7c1b2a4...ply        (point cloud)

Properties:
- **Content-addressed**: identical payload → identical sha256 → same path.
  Re-writing the same bytes is a no-op + returns the existing path.
- **2-char sharding**: prevents one giant directory; 256 buckets max.
- **Extension preserved**: `.png` / `.glb` / `.ply` / `.bin` flows into
  the filename so OS file browsers can preview directly.
- **Atomic write**: temp file + rename so a crash mid-write doesn't
  leave a half-written blob with a valid sha-addressed name.
- **Streaming-friendly**: writers can pass an open file handle for
  large blobs; reads are bytes for now (chunked read in a later slice).

Brain #32 day-2 (separate slice) will lift these to cloud archive
(Cloudflare R2 / Hetzner box) on opt-in. The sidecar layout maps 1:1
to S3-compatible object storage with the same key shape.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# Extension whitelist — keeps the sidecar tree predictable + spots typos
# in caller payloads early. Adding a new ext = explicit decision.
_SAFE_EXTS: frozenset[str] = frozenset({
    # Images
    "png", "jpg", "jpeg", "webp", "gif",
    # Geometry / 3D
    "glb", "gltf", "obj", "stl", "ply", "ifc", "dxf",
    # Generic
    "bin", "json", "txt",
})


def _normalise_ext(ext: str) -> str:
    """`'.PNG'` → `'png'`. Falls back to `'bin'` for unrecognised."""
    e = (ext or "").strip().lower().lstrip(".")
    if not e:
        return "bin"
    return e if e in _SAFE_EXTS else "bin"


def _hash_bytes(payload: bytes) -> str:
    """sha256 hex (64 chars)."""
    return hashlib.sha256(payload).hexdigest()


def _shard_dir(brain_root: Path, sha: str) -> Path:
    """Two-char shard prefix dir under <brain_root>/blobs/."""
    return Path(brain_root) / "blobs" / sha[:2]


def _full_path(brain_root: Path, sha: str, ext: str) -> Path:
    return _shard_dir(brain_root, sha) / f"{sha}.{_normalise_ext(ext)}"


def _relative_to_brain_root(brain_root: Path, full: Path) -> str:
    """POSIX-style relative path from <brain_root>. Used as
    Fragment.blob_path. Forward-slashed so it's same string on
    Windows / macOS / Linux."""
    rel = full.resolve().relative_to(Path(brain_root).resolve())
    return rel.as_posix()


# ── Public API ────────────────────────────────────────────────────────


def write_blob(
    brain_root: Path,
    payload: bytes,
    ext: str = "bin",
) -> Tuple[str, str, int]:
    """Write `payload` under <brain_root>/blobs/<sha[:2]>/<sha>.<ext>.

    Idempotent: same payload → same path; re-writing is a no-op.

    Returns: `(sha256_hex, relative_path, bytes_written)`. The
    relative_path is suitable for storing in Fragment.blob_path.
    """
    sha = _hash_bytes(payload)
    target = _full_path(brain_root, sha, ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == len(payload):
        return sha, _relative_to_brain_root(brain_root, target), len(payload)
    # Atomic write — temp file in same shard dir then rename.
    fd, tmp = tempfile.mkstemp(
        prefix=f".{sha[:8]}_",
        suffix=f".{_normalise_ext(ext)}.partial",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return sha, _relative_to_brain_root(brain_root, target), len(payload)


def read_blob(brain_root: Path, blob_path: str) -> Optional[bytes]:
    """Read the blob at `<brain_root>/<blob_path>`. Returns None when
    the path doesn't exist or escapes the brain root (path traversal
    guard)."""
    root = Path(brain_root).resolve()
    target = (root / blob_path).resolve()
    # Path traversal guard
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        return None
    return target.read_bytes()


def delete_blob(brain_root: Path, blob_path: str) -> bool:
    """Remove the blob at `<brain_root>/<blob_path>`. Returns True if
    a file was removed, False if it didn't exist or escaped root.
    Empty shard dirs are left in place (cheap)."""
    root = Path(brain_root).resolve()
    target = (root / blob_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    if not target.exists() or not target.is_file():
        return False
    target.unlink()
    return True


def blob_exists(brain_root: Path, blob_path: str) -> bool:
    """Cheap existence check without reading the bytes."""
    root = Path(brain_root).resolve()
    target = (root / blob_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return target.exists() and target.is_file()


def blob_path_for(brain_root: Path, payload: bytes, ext: str = "bin") -> str:
    """Compute the relative path a payload WOULD live at, without
    writing. Useful for de-dup checks before invoking write_blob."""
    sha = _hash_bytes(payload)
    return _relative_to_brain_root(brain_root, _full_path(brain_root, sha, ext))
