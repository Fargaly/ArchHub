"""Brain #33 · single-user training harness — tests.

Pins (all against REAL fitted models, no mocks):
  - train on a tiny real fixture dataset → a real artifact lands on disk
    (embeddings.npy + centroids + model.json + manifest.json + fragments.jsonl)
  - the trained classifier separates the fixture's kinds (real fitted centroids)
  - real inference: a domain query retrieves the topically-correct fragment AND
    predicts a sensible kind/scope
  - load-from-disk round-trips: a freshly loaded artifact answers the same query
  - training direct from a real BrainStore (the export-plumbing path) works
  - empty / text-less input fails loudly rather than fabricating a model

The harness module lives in ArchHub/tools/train_brain_model.py (it owns the
exports/brain-models artifacts). We import it by path so this test runs under
`cd personal-brain-mcp; python -m pytest tests/ -q` without packaging changes.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from personal_brain.models import Fragment, FragmentKind, Provenance, Scope
from personal_brain.storage import BrainStore


# ── import the tool module (ArchHub/tools/train_brain_model.py) by path ──────
_THIS = Path(__file__).resolve()
# tests/ -> personal-brain-mcp/ -> ArchHub/
_ARCHHUB_ROOT = _THIS.parent.parent.parent
_TOOL_PATH = _ARCHHUB_ROOT / "tools" / "train_brain_model.py"


def _load_tool_module():
    if not _TOOL_PATH.exists():
        pytest.skip(f"train_brain_model.py not found at {_TOOL_PATH}")
    spec = importlib.util.spec_from_file_location("train_brain_model", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["train_brain_model"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


tbm = _load_tool_module()


# ── tiny REAL fixture dataset (dataset_export row shape) ─────────────────────
#
# Two clearly-separable topical clusters so a real classifier has signal:
#   - FACTs about Revit walls / quantity takeoff
#   - TRACEs about privacy / differential privacy
def _fixture_rows() -> list[dict]:
    return [
        {"id": "f1", "kind": "fact", "scope": "project",
         "text": "Revit wall classify quantity takeoff for Tower-A core walls"},
        {"id": "f2", "kind": "fact", "scope": "project",
         "text": "wall area schedule export from the active Revit model"},
        {"id": "f3", "kind": "fact", "scope": "project",
         "text": "concrete wall volume takeoff grouped by level"},
        {"id": "t1", "kind": "trace", "scope": "user",
         "text": "trace privacy layer differential privacy Laplace noise scope gate"},
        {"id": "t2", "kind": "trace", "scope": "user",
         "text": "trace privatize for collective aggregate counts epsilon budget"},
        {"id": "t3", "kind": "trace", "scope": "user",
         "text": "trace dp count noised by kind and scope no raw fragments leak"},
    ]


def test_train_writes_real_artifact(tmp_path):
    rows = _fixture_rows()
    # Write the fixture as a real JSONL and train from it (real loader path).
    ds = tmp_path / "fixture.jsonl"
    ds.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    manifest = tbm.train_model(
        name="fixture-model", dataset=ds, out_root=tmp_path, backend="lexical",
    )

    art = Path(manifest["artifact_dir"])
    # every artifact file is real + non-trivially sized
    for fn in ("embeddings.npy", "kind_centroids.npy", "scope_centroids.npy",
               "fragments.jsonl", "model.json", "manifest.json"):
        p = art / fn
        assert p.exists(), f"missing artifact file {fn}"
        assert p.stat().st_size > 0, f"empty artifact file {fn}"

    assert manifest["ok"] is True
    assert manifest["n_fragments"] == 6
    assert set(manifest["kind_labels"]) == {"fact", "trace"}
    assert set(manifest["scope_labels"]) == {"project", "user"}
    # the fitted classifier must actually separate these two clean clusters
    assert manifest["train_self_accuracy"]["kind"] == pytest.approx(1.0)
    assert manifest["train_self_accuracy"]["scope"] == pytest.approx(1.0)
    # honest single-user caveat is recorded in the artifact
    assert "SINGLE-USER" in manifest["collective_caveat"]
    assert "#33" in manifest["task_ref"]


def test_real_inference_retrieves_and_classifies(tmp_path):
    ds = tmp_path / "fixture.jsonl"
    ds.write_text(
        "\n".join(json.dumps(r) for r in _fixture_rows()) + "\n", encoding="utf-8"
    )
    manifest = tbm.train_model(
        name="m", dataset=ds, out_root=tmp_path, backend="lexical",
    )
    model = tbm.BrainModel.load(Path(manifest["artifact_dir"]))

    # A wall/takeoff query must retrieve a FACT about walls, not a privacy trace.
    res = model.query("Revit wall area takeoff schedule", k=3)
    assert res["retrieved"], "no retrieval results"
    top = res["retrieved"][0]
    assert top["kind"] == "fact"
    assert top["score"] > 0.0
    assert "wall" in top["text"].lower()
    assert res["predicted_kind"] == "fact"

    # A privacy query must retrieve a TRACE about privacy.
    res2 = model.query("differential privacy collective aggregate epsilon", k=3)
    assert res2["retrieved"][0]["kind"] == "trace"
    assert res2["predicted_kind"] == "trace"
    # ranked label scores are present + well-formed
    labels = {d["label"] for d in res2["kind_scores"]}
    assert labels == {"fact", "trace"}


def test_load_roundtrips_from_disk(tmp_path):
    ds = tmp_path / "fixture.jsonl"
    ds.write_text(
        "\n".join(json.dumps(r) for r in _fixture_rows()) + "\n", encoding="utf-8"
    )
    manifest = tbm.train_model(
        name="rt", dataset=ds, out_root=tmp_path, backend="lexical",
    )
    art = Path(manifest["artifact_dir"])

    # Two independently-loaded instances must agree (deterministic lexical path).
    a = tbm.BrainModel.load(art).query("wall takeoff", k=2)
    b = tbm.BrainModel.load(art).query("wall takeoff", k=2)
    assert [h["id"] for h in a["retrieved"]] == [h["id"] for h in b["retrieved"]]
    assert a["predicted_kind"] == b["predicted_kind"]


def test_train_from_real_brainstore(tmp_path):
    """The export-plumbing path: a real BrainStore → export_fragments → train."""
    db = tmp_path / "brain.db"
    store = BrainStore.open(db)
    now = datetime.now(timezone.utc)
    for r in _fixture_rows():
        store.write_fragment(Fragment(
            id=r["id"],
            kind=FragmentKind(r["kind"]),
            scope=Scope(r["scope"]),
            text=r["text"],
            owner_user="founder",
            provenance=Provenance(
                contributing_agent="test", contributing_user="founder",
                created_at=now,
            ),
        ))
    store.close()

    manifest = tbm.train_model(
        name="from-store", brain_db=db, out_root=tmp_path, backend="lexical",
        scopes=[Scope.USER, Scope.PROJECT, Scope.FIRM],
    )
    assert manifest["n_fragments"] == 6
    assert manifest["source"]["kind"] == "brain_store"
    # real inference off the store-trained model
    model = tbm.BrainModel.load(Path(manifest["artifact_dir"]))
    assert model.query("privacy epsilon", k=1)["retrieved"][0]["kind"] == "trace"


def test_empty_dataset_fails_loudly(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        tbm.train_model(name="boom", dataset=empty, out_root=tmp_path)
