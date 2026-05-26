"""Brain #31 multimodal · day-1 tests.

Per founder ask 2026-05-26: "this brain should have a way to understand
geometry & pictures."

Day-1 scope:
- GEOMETRY + IMAGE fragment kinds writable + readable
- perceptual_hash + blob_path + blob_mime + blob_bytes round-trip
- Idempotent schema migration on a pre-existing DB

Day-2+ (separate slices):
- Blob storage helper (sidecar files under <brain_root>/blobs/<sha[:2]>/...)
- Perceptual-hash helpers (phash for images · geometry-derived hash)
- CLIP-style vision embedding helper
- brain.find_similar query API
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
)
from personal_brain.storage import BrainStore


def _make_fragment(
    fid: str,
    kind: FragmentKind = FragmentKind.GEOMETRY,
    text: str = "wall · 12.5m × 3m × 0.2m",
    perceptual_hash: str = None,
    blob_path: str = None,
    blob_mime: str = None,
    blob_bytes: int = 0,
) -> Fragment:
    return Fragment(
        id=fid,
        kind=kind,
        text=text,
        scope=Scope.USER,
        owner_user="founder",
        provenance=Provenance(
            contributing_agent="test",
            contributing_user="founder",
        ),
        perceptual_hash=perceptual_hash,
        blob_path=blob_path,
        blob_mime=blob_mime,
        blob_bytes=blob_bytes,
    )


@pytest.fixture
def store(tmp_path) -> BrainStore:
    return BrainStore.open(tmp_path / "test.db")


# ── New fragment kinds ─────────────────────────────────────────────

def test_geometry_kind_writable_readable(store):
    frag = _make_fragment("g_wall_1", kind=FragmentKind.GEOMETRY,
                          text="wall L=12.5m · vertices=8")
    assert store.write_fragment(frag) is True
    back = store.get_fragment("g_wall_1")
    assert back is not None
    assert back.kind is FragmentKind.GEOMETRY


def test_image_kind_writable_readable(store):
    frag = _make_fragment("img_render_1", kind=FragmentKind.IMAGE,
                          text="south facade render · 1024x768")
    assert store.write_fragment(frag) is True
    back = store.get_fragment("img_render_1")
    assert back is not None
    assert back.kind is FragmentKind.IMAGE


# ── Perceptual hash round-trip ─────────────────────────────────────

def test_perceptual_hash_round_trip(store):
    frag = _make_fragment(
        "img_phash_1", kind=FragmentKind.IMAGE,
        perceptual_hash="0xf3e7c1b2a4d5e6f7",
    )
    store.write_fragment(frag)
    back = store.get_fragment("img_phash_1")
    assert back.perceptual_hash == "0xf3e7c1b2a4d5e6f7"


def test_perceptual_hash_optional(store):
    """Non-multimodal kinds don't need a perceptual_hash."""
    frag = Fragment(
        id="fact_no_phash", kind=FragmentKind.FACT, text="plain fact",
        owner_user="founder",
        provenance=Provenance(contributing_agent="test",
                              contributing_user="founder"),
    )
    store.write_fragment(frag)
    back = store.get_fragment("fact_no_phash")
    assert back.perceptual_hash is None


# ── Blob pointer round-trip ────────────────────────────────────────

def test_blob_pointer_round_trip(store):
    frag = _make_fragment(
        "img_blob_1", kind=FragmentKind.IMAGE,
        blob_path="blobs/ab/abcdef0123.png",
        blob_mime="image/png",
        blob_bytes=132_456,
    )
    store.write_fragment(frag)
    back = store.get_fragment("img_blob_1")
    assert back.blob_path == "blobs/ab/abcdef0123.png"
    assert back.blob_mime == "image/png"
    assert back.blob_bytes == 132_456


def test_blob_bytes_defaults_to_zero(store):
    frag = _make_fragment("g_no_blob")
    store.write_fragment(frag)
    back = store.get_fragment("g_no_blob")
    assert back.blob_bytes == 0
    assert back.blob_path is None


# ── Idempotent migration on pre-existing DB ────────────────────────

def test_migration_idempotent_on_existing_db(tmp_path):
    """Opening a DB twice (second time after a re-open from disk)
    doesn't error on the ALTER TABLE ADD COLUMN — the migration
    catches `duplicate column name` and continues."""
    db_path = tmp_path / "existing.db"
    # First open creates the schema with new columns
    s1 = BrainStore.open(db_path)
    s1.close()
    # Second open should be a no-op for the migration
    s2 = BrainStore.open(db_path)
    # Verify the schema has the columns
    cols = {row["name"] for row in
            s2._conn.execute("PRAGMA table_info(fragments)").fetchall()}
    assert "perceptual_hash" in cols
    assert "blob_path" in cols
    assert "blob_mime" in cols
    assert "blob_bytes" in cols
    s2.close()


def test_phash_index_exists(tmp_path):
    """Brain #31 slice 2 similarity query depends on the partial index
    over perceptual_hash for cheap lookup."""
    db_path = tmp_path / "idx.db"
    s = BrainStore.open(db_path)
    indexes = {row["name"] for row in
               s._conn.execute(
                   "SELECT name FROM sqlite_master "
                   "WHERE type='index' AND tbl_name='fragments'"
               ).fetchall()}
    assert "idx_fragments_phash" in indexes
    s.close()


# ── List + filter multimodal ───────────────────────────────────────

def test_list_fragments_filter_by_geometry_kind(store):
    store.write_fragment(_make_fragment("g1", kind=FragmentKind.GEOMETRY))
    store.write_fragment(_make_fragment("g2", kind=FragmentKind.GEOMETRY))
    store.write_fragment(_make_fragment("i1", kind=FragmentKind.IMAGE))
    store.write_fragment(_make_fragment("f1", kind=FragmentKind.FACT,
                                          text="fact text"))
    rows = store.list_fragments(kinds=[FragmentKind.GEOMETRY])
    assert {r.id for r in rows} == {"g1", "g2"}


def test_list_fragments_filter_by_image_kind(store):
    store.write_fragment(_make_fragment("g1", kind=FragmentKind.GEOMETRY))
    store.write_fragment(_make_fragment("i1", kind=FragmentKind.IMAGE))
    store.write_fragment(_make_fragment("i2", kind=FragmentKind.IMAGE))
    rows = store.list_fragments(kinds=[FragmentKind.IMAGE])
    assert {r.id for r in rows} == {"i1", "i2"}
