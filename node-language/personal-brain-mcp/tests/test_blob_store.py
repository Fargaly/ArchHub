"""Brain #31 day-2 · blob storage helper tests.

Pins:
- write_blob places payload under blobs/<sha[:2]>/<sha>.<ext>
- Idempotent: same payload → same path; second write is no-op
- read_blob round-trips bytes
- delete_blob removes the file
- Path traversal guard rejects ../escape
- Extension whitelist + fallback to .bin
"""
from __future__ import annotations

from pathlib import Path

import pytest

from personal_brain.blob_store import (
    blob_exists,
    blob_path_for,
    delete_blob,
    read_blob,
    write_blob,
)


@pytest.fixture
def brain_root(tmp_path) -> Path:
    return tmp_path / "brain"


# ── write_blob ─────────────────────────────────────────────────────

def test_write_blob_returns_sha_path_and_bytes(brain_root):
    payload = b"hello world"
    sha, rel, n = write_blob(brain_root, payload, ext="txt")
    assert len(sha) == 64  # sha256 hex
    assert n == len(payload)
    assert rel.startswith("blobs/")
    assert rel.endswith(".txt")


def test_write_blob_creates_sharded_directory(brain_root):
    payload = b"x" * 100
    sha, rel, _ = write_blob(brain_root, payload, ext="bin")
    full = brain_root / rel
    assert full.exists()
    # path shape: blobs/<sha[:2]>/<sha>.bin
    parts = Path(rel).parts
    assert parts[0] == "blobs"
    assert parts[1] == sha[:2]
    assert parts[2] == f"{sha}.bin"


def test_write_blob_idempotent(brain_root):
    payload = b"same content"
    sha1, rel1, n1 = write_blob(brain_root, payload, ext="bin")
    sha2, rel2, n2 = write_blob(brain_root, payload, ext="bin")
    assert sha1 == sha2
    assert rel1 == rel2
    assert n1 == n2


def test_write_blob_normalises_extension(brain_root):
    # Uppercase + leading dot
    sha, rel, _ = write_blob(brain_root, b"png-bytes", ext=".PNG")
    assert rel.endswith(".png")


def test_write_blob_unrecognised_ext_falls_back_to_bin(brain_root):
    sha, rel, _ = write_blob(brain_root, b"weird", ext="xyz123")
    assert rel.endswith(".bin")


def test_write_blob_handles_geometry_extensions(brain_root):
    for ext in ("glb", "gltf", "obj", "stl", "ply", "ifc", "dxf"):
        sha, rel, _ = write_blob(brain_root, b"geom-" + ext.encode(), ext=ext)
        assert rel.endswith(f".{ext}")


# ── read_blob ──────────────────────────────────────────────────────

def test_read_blob_round_trip(brain_root):
    payload = b"binary\x00\xff\xfecontent"
    sha, rel, _ = write_blob(brain_root, payload, ext="bin")
    assert read_blob(brain_root, rel) == payload


def test_read_blob_missing_returns_none(brain_root):
    brain_root.mkdir(parents=True, exist_ok=True)
    assert read_blob(brain_root, "blobs/ab/abcdef.bin") is None


def test_read_blob_path_traversal_rejected(brain_root):
    brain_root.mkdir(parents=True, exist_ok=True)
    # Write a "secret" outside the brain root
    secret = brain_root.parent / "secret.txt"
    secret.write_text("nope")
    # Attempt traversal
    assert read_blob(brain_root, "../secret.txt") is None


# ── delete_blob ────────────────────────────────────────────────────

def test_delete_blob_removes_existing(brain_root):
    sha, rel, _ = write_blob(brain_root, b"to-delete", ext="bin")
    assert blob_exists(brain_root, rel) is True
    assert delete_blob(brain_root, rel) is True
    assert blob_exists(brain_root, rel) is False


def test_delete_blob_missing_returns_false(brain_root):
    brain_root.mkdir(parents=True, exist_ok=True)
    assert delete_blob(brain_root, "blobs/zz/notfound.bin") is False


def test_delete_blob_path_traversal_rejected(brain_root):
    brain_root.mkdir(parents=True, exist_ok=True)
    target = brain_root.parent / "outside.txt"
    target.write_text("alive")
    assert delete_blob(brain_root, "../outside.txt") is False
    assert target.exists()  # not deleted


# ── blob_exists / blob_path_for ────────────────────────────────────

def test_blob_path_for_predicts_write_target(brain_root):
    payload = b"predict me"
    predicted = blob_path_for(brain_root, payload, ext="bin")
    sha, actual_rel, _ = write_blob(brain_root, payload, ext="bin")
    assert predicted == actual_rel


def test_blob_exists_before_and_after_write(brain_root):
    payload = b"existence check"
    predicted = blob_path_for(brain_root, payload, ext="bin")
    brain_root.mkdir(parents=True, exist_ok=True)
    assert blob_exists(brain_root, predicted) is False
    write_blob(brain_root, payload, ext="bin")
    assert blob_exists(brain_root, predicted) is True
