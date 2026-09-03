"""Brain #32 · dataset export — tests.

Pins:
  - list_fragments enumerates without FTS
  - export_fragments writes JSONL + manifest
  - parquet emitted when pyarrow available, skipped otherwise
  - filter respected (scope / kinds / since / limit)
  - default scope = USER (privacy default · never escalates)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from personal_brain.dataset_export import (
    export_fragments,
)
from personal_brain.models import Fragment, FragmentKind, Provenance, Scope
from personal_brain.storage import BrainStore as Store


def _make_fragment(
    fid: str = "f_test",
    kind: FragmentKind = FragmentKind.FACT,
    scope: Scope = Scope.USER,
    text: str = "hello world",
    owner_user: str = "founder",
    when=None,
) -> Fragment:
    """Construct a minimal Fragment for write tests."""
    ts = when or datetime.now(timezone.utc)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return Fragment(
        id=fid,
        kind=kind,
        scope=scope,
        text=text,
        owner_user=owner_user,
        provenance=Provenance(
            contributing_agent="test",
            contributing_user=owner_user,
            created_at=ts,
        ),
    )


@pytest.fixture
def store(tmp_path) -> Store:
    db = tmp_path / "test.db"
    s = Store.open(db)
    return s


def test_list_fragments_returns_all_without_query(store, tmp_path):
    """No FTS query needed — `list_fragments` enumerates by filter."""
    for i in range(3):
        store.write_fragment(_make_fragment(
            fid=f"f_{i}",
            text=f"item {i}",
        ))
    rows = store.list_fragments()
    assert len(rows) == 3
    ids = {r.id for r in rows}
    assert ids == {"f_0", "f_1", "f_2"}


def test_list_fragments_scope_filter(store):
    store.write_fragment(_make_fragment("f_u", scope=Scope.USER))
    store.write_fragment(_make_fragment("f_p", scope=Scope.PROJECT,
                                          owner_user="founder"))
    # USER-only filter excludes the PROJECT row
    user_rows = store.list_fragments(scope_filter=[Scope.USER])
    assert {r.id for r in user_rows} == {"f_u"}
    # Both scopes
    both = store.list_fragments(scope_filter=[Scope.USER, Scope.PROJECT])
    assert {r.id for r in both} == {"f_u", "f_p"}


def test_list_fragments_since(store):
    """`since` filters by the row's `created_at` column (set at insert
    time via DB default). To exercise the filter we have to backdate
    via raw SQL — the high-level write_fragment uses 'now' regardless."""
    store.write_fragment(_make_fragment("f_old"))
    store.write_fragment(_make_fragment("f_new"))
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    with store._lock:
        store._conn.execute(
            "UPDATE fragments SET created_at = ? WHERE id = ?",
            (old_ts, "f_old"),
        )
        store._conn.commit()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rows = store.list_fragments(since=cutoff)
    assert {r.id for r in rows} == {"f_new"}


def test_export_writes_jsonl_and_manifest(store, tmp_path):
    store.write_fragment(_make_fragment("f_1", text="alpha"))
    store.write_fragment(_make_fragment("f_2", text="beta"))
    out = tmp_path / "export"
    manifest = export_fragments(
        store, out_dir=out, dataset_name="ds1",
    )
    assert manifest["ok"] is True
    assert manifest["row_count"] == 2
    jsonl = Path(manifest["files"]["jsonl"]["path"])
    assert jsonl.exists()
    lines = jsonl.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["text"] in {"alpha", "beta"}
    mf = Path(manifest["manifest_path"])
    assert mf.exists()
    parsed = json.loads(mf.read_text(encoding="utf-8"))
    assert parsed["row_count"] == 2
    assert parsed["filter"]["scopes"] == ["user"]


def test_export_default_scope_is_user_only(store, tmp_path):
    """Privacy default — caller must opt in to higher scopes explicitly."""
    store.write_fragment(_make_fragment("f_u", scope=Scope.USER))
    store.write_fragment(_make_fragment("f_p", scope=Scope.PROJECT))
    manifest = export_fragments(
        store, out_dir=tmp_path / "export", dataset_name="ds-default",
    )
    assert manifest["row_count"] == 1
    assert manifest["scope_distribution"] == {"user": 1}


def test_export_explicit_scope_filter(store, tmp_path):
    store.write_fragment(_make_fragment("f_u", scope=Scope.USER))
    store.write_fragment(_make_fragment("f_p", scope=Scope.PROJECT))
    manifest = export_fragments(
        store, out_dir=tmp_path / "export", dataset_name="ds-both",
        scope_filter=[Scope.USER, Scope.PROJECT],
    )
    assert manifest["row_count"] == 2


def test_export_empty_when_no_fragments(store, tmp_path):
    manifest = export_fragments(
        store, out_dir=tmp_path / "export", dataset_name="ds-empty",
    )
    assert manifest["row_count"] == 0
    assert manifest["files"]["jsonl"]["bytes"] == 0


def test_export_parquet_emitted_or_skipped_cleanly(store, tmp_path):
    store.write_fragment(_make_fragment("f_pq"))
    manifest = export_fragments(
        store, out_dir=tmp_path / "export", dataset_name="ds-pq",
    )
    pq = manifest["files"]["parquet"]
    # Either pyarrow is installed (path + bytes) OR a graceful note.
    if pq["path"] is None:
        assert "note" in pq
    else:
        assert Path(pq["path"]).exists()


def test_manifest_carries_schema_version(store, tmp_path):
    store.write_fragment(_make_fragment("f"))
    manifest = export_fragments(
        store, out_dir=tmp_path / "export", dataset_name="ds-v",
    )
    assert manifest["schema_version"] == "1.0"
    assert "exported_at" in manifest
