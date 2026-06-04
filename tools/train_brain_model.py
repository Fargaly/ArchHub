#!/usr/bin/env python
"""Brain #33 · the single-user model TRAINING HARNESS (MAKE-IT-REAL).

The founder's north star (ROADMAP #33, founder ask 2026-05-26):

    "this brain should be able to produce training data sets for models and
     used to produce our own hosted models in the future AFTER multiple users
     form a collective memory enough to do that."

The plumbing for that north star already exists:

  * ``personal_brain.dataset_export.export_fragments`` — turns a real
    ``BrainStore`` into a HuggingFace-style JSONL dataset (one fragment per
    line: id / kind / scope / subject / predicate / object / text / counts /
    ...). See ``personal-brain-mcp/src/personal_brain/dataset_export.py``.
  * ``personal_brain.privacy.privatize_for_collective`` — the DP gate that
    lets many users' datasets aggregate into a COLLECTIVE pool WITHOUT leaking
    any raw fragment. See ``.../personal_brain/privacy.py``.
  * ``personal_brain.cloud_archive`` — uploads exported datasets off-box.

The piece that was MISSING — and that this module supplies — is the
**training harness**: the thing that consumes one of those datasets and
produces a REAL model artifact on disk that supports REAL inference. Without
it, #33 has data pipes and an upload path but nothing that actually *trains*.

────────────────────────────────────────────────────────────────────────────
What this trains (and why this exact model)
────────────────────────────────────────────────────────────────────────────
It fits a real **embedding-index retriever + centroid classifier** over the
brain's fragment text:

  1. EMBED every fragment's text with ``personal_brain.embeddings`` — the
     repo's own embedder. The default backend is the dep-light, deterministic
     ``LexicalEmbedder`` (FNV-1a hashing-trick TF-IDF, 2048-dim, sub-ms,
     already used in production for skill/fact retrieval). If the optional
     ``fastembed`` extra is installed, ``--backend fastembed`` continue-uses
     the real ONNX transformer embeddings instead — same artifact shape, just
     a stronger vector space. Either way the embeddings are REAL.
  2. STACK them into a real dense ``numpy`` matrix (the retrieval index) that
     is L2-normalised so cosine == dot product — a real nearest-neighbour
     retriever over the brain's domain text.
  3. FIT real per-kind and per-scope **centroids** (the mean unit vector of
     every fragment in a class). This is a genuine nearest-centroid
     classifier (Rocchio): a trained model whose parameters (the centroids)
     are LEARNED from the corpus, not hand-written. Predicting a query's kind
     == argmax cosine(query, kind_centroid).

Why this model and not a full LLM fine-tune: ``sentence-transformers`` /
``sklearn`` are NOT installed on this box, and a full transformer fine-tune
needs a GPU-class machine + hours. A nearest-centroid classifier over a real
embedding index is a *bona fide* trained model (it has fitted parameters, it
generalises to unseen queries, it supports real inference), it RUNS here today
with only ``numpy`` (already installed), and it is the same retrieval substrate
the brain already trusts. It is the most-real option that actually runs on
this hardware and produces a real, loadable, inferable artifact. When a beefier
box + ``fastembed``/``sentence-transformers`` are available, the SAME harness
upgrades the vector space by flag — no rewrite.

────────────────────────────────────────────────────────────────────────────
The artifact (real, on disk, loadable)
────────────────────────────────────────────────────────────────────────────
``exports/brain-models/<name>/``
    embeddings.npy      float32 [n_fragments, dim] — the L2-normed index
    kind_centroids.npy  float32 [n_kinds, dim]     — fitted classifier params
    scope_centroids.npy float32 [n_scopes, dim]    — fitted classifier params
    fragments.jsonl     the rows the model was trained on (provenance + the
                        retrieval payload inference returns)
    model.json          labels, dim, backend, normalisation, label maps
    manifest.json       source dataset, fragment count, train params,
                        created-at, train wall-time, accuracy on the corpus

────────────────────────────────────────────────────────────────────────────
Real inference (proves the model WORKS, not just saved)
────────────────────────────────────────────────────────────────────────────
``BrainModel.load(<artifact_dir>).query("wall takeoff timeout", k=5)`` →
embeds the query in the trained space, returns the top-k most-similar
fragments (real cosine retrieval) AND the predicted kind/scope (real centroid
classification). CLI: ``python tools/train_brain_model.py infer --query ...``.

────────────────────────────────────────────────────────────────────────────
HONEST collective-gating caveat (single-user mechanism NOW)
────────────────────────────────────────────────────────────────────────────
This is the SINGLE-USER training mechanism — the prerequisite for #33, not the
finished "collective hosted model." Today it trains on ONE brain
(``BrainStore`` → ``export_fragments``). "Collective hosted models" = running
this SAME harness over the privacy-filtered AGGREGATE of MANY users' datasets.
That step is gated on (a) real users producing real cross-firm memory and
(b) the cross-user pull that feeds ``privacy.privatize_for_collective`` into a
combined corpus. Both await real adoption. The mechanism is real now; the
"collective" qualifier is the part that needs more users — exactly as the
founder framed it ("after multiple users form a collective memory enough").

Usage
-----
    # train on the live brain (default), writing the real artifact:
    python tools/train_brain_model.py train

    # or train on a pre-exported JSONL produced by dataset_export:
    python tools/train_brain_model.py train --dataset path/to/fragments.jsonl

    # real inference against the trained artifact:
    python tools/train_brain_model.py infer --query "door schedule export"

NEW file — additive only (Brain #33). Edits no existing source.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

# numpy is the only hard dep beyond the brain package, and it IS installed on
# this box (verified). It powers the real embedding matrix + centroid maths.
import numpy as np


# ── make the brain package importable (its src/ layout) ─────────────────────
#
# This tool lives in ArchHub/tools/. The brain package is
# ArchHub/personal-brain-mcp/src/personal_brain. Add that src/ to sys.path so
# `import personal_brain...` resolves whether or not the package was pip-
# installed. We DO NOT mutate any source — just our own import path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BRAIN_SRC = _REPO_ROOT / "personal-brain-mcp" / "src"
if _BRAIN_SRC.is_dir() and str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))

from personal_brain import embeddings as brain_embeddings  # noqa: E402
from personal_brain.dataset_export import export_fragments  # noqa: E402
from personal_brain.models import Scope  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


_ARTIFACT_SCHEMA_VERSION = "1.0"
_DEFAULT_OUT_ROOT = _REPO_ROOT / "exports" / "brain-models"


# ════════════════════════════════════════════════════════════════════════════
# Dataset loading — real fragments in, via the export plumbing or a JSONL path
# ════════════════════════════════════════════════════════════════════════════


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a dataset_export-shaped JSONL file into a list of row dicts."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def load_dataset(
    *,
    dataset: Optional[Path] = None,
    brain_db: Optional[Path] = None,
    scopes: Optional[list[Scope]] = None,
    limit: int = 100_000,
    out_root: Path = _DEFAULT_OUT_ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Produce the real training rows + a source descriptor.

    Two real sources, in priority order:

      1. ``dataset`` — a JSONL file already produced by
         ``dataset_export.export_fragments``. Used verbatim.
      2. otherwise — open the real ``BrainStore`` (``brain_db`` or the OS
         default) and call ``export_fragments`` to materialise a fresh JSONL,
         then read it back. This is the real export plumbing, not a shortcut.

    Returns ``(rows, source_descriptor)``.
    """
    if dataset is not None:
        dataset = Path(dataset)
        if not dataset.exists():
            raise FileNotFoundError(f"dataset JSONL not found: {dataset}")
        rows = _read_jsonl(dataset)
        return rows, {
            "kind": "jsonl",
            "path": str(dataset),
            "row_count": len(rows),
        }

    # Source from the live brain via the real export path.
    store = BrainStore.open(brain_db)  # None → OS-default per-user brain.db
    try:
        # Default to ALL non-leaking scopes the single user owns so the model
        # learns from the whole personal brain. (USER/PROJECT/FIRM are raw-row
        # exportable; COMMUNITY/GLOBAL would route to DP aggregates instead —
        # see dataset_export + privacy. We deliberately stay below that line:
        # this is the SINGLE-user mechanism.)
        scope_filter = scopes or [Scope.USER, Scope.PROJECT, Scope.FIRM]
        export_root = out_root / "_datasets"
        manifest = export_fragments(
            store,
            out_dir=export_root,
            dataset_name="brain-train-source",
            scope_filter=scope_filter,
            limit=limit,
        )
    finally:
        store.close()

    jsonl_path = manifest.get("files", {}).get("jsonl", {}).get("path")
    if not jsonl_path or not Path(jsonl_path).exists():
        raise RuntimeError(
            "export_fragments did not produce a JSONL — cannot train. "
            f"manifest={manifest}"
        )
    rows = _read_jsonl(Path(jsonl_path))
    return rows, {
        "kind": "brain_store",
        "brain_db": str(store.path),
        "export_manifest": jsonl_path,
        "scopes": [s.value for s in scope_filter],
        "row_count": len(rows),
    }


def _row_text(row: dict[str, Any]) -> str:
    """The text the model learns / retrieves on. Prefer the human-readable
    ``text``; fall back to the subject/predicate/object triple so triple-only
    fragments still contribute a real signal."""
    t = (row.get("text") or "").strip()
    if t:
        return t
    triple = " ".join(
        str(row.get(k, "") or "") for k in ("subject", "predicate", "object")
    ).strip()
    return triple


# ════════════════════════════════════════════════════════════════════════════
# The model — a REAL embedding-index retriever + fitted centroid classifier
# ════════════════════════════════════════════════════════════════════════════


def _l2_normalise(mat: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalise so cosine similarity == dot product. Zero rows
    stay zero (no divide-by-zero)."""
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return mat / norms


def _fit_centroids(
    vectors: np.ndarray,
    labels: list[str],
) -> tuple[list[str], np.ndarray]:
    """Fit one unit centroid per distinct label (nearest-centroid / Rocchio).

    Returns ``(ordered_labels, centroid_matrix)`` where row i is the mean unit
    vector of every training row whose label == ordered_labels[i], itself
    re-normalised to unit length. These centroids ARE the learned classifier
    parameters.
    """
    ordered = sorted(set(labels))
    idx_of = {lab: i for i, lab in enumerate(ordered)}
    dim = vectors.shape[1]
    sums = np.zeros((len(ordered), dim), dtype=np.float64)
    counts = np.zeros(len(ordered), dtype=np.float64)
    for vec, lab in zip(vectors, labels):
        i = idx_of[lab]
        sums[i] += vec
        counts[i] += 1.0
    counts[counts == 0.0] = 1.0
    centroids = sums / counts[:, None]
    centroids = _l2_normalise(centroids.astype(np.float32))
    return ordered, centroids


class BrainModel:
    """A trained brain model: a real embedding index + fitted centroid
    classifiers, with real top-k retrieval + kind/scope prediction.

    Construct via :meth:`train` (fits + holds it in memory) or :meth:`load`
    (reads a persisted artifact). :meth:`query` runs real inference.
    """

    def __init__(
        self,
        *,
        backend: str,
        dim: int,
        rows: list[dict[str, Any]],
        embeddings: np.ndarray,
        kind_labels: list[str],
        kind_centroids: np.ndarray,
        scope_labels: list[str],
        scope_centroids: np.ndarray,
    ) -> None:
        self.backend = backend
        self.dim = dim
        self.rows = rows
        self.embeddings = embeddings  # [n, dim], L2-normed
        self.kind_labels = kind_labels
        self.kind_centroids = kind_centroids  # [n_kinds, dim], L2-normed
        self.scope_labels = scope_labels
        self.scope_centroids = scope_centroids  # [n_scopes, dim], L2-normed
        # The embedder is reconstructed from the backend name so a loaded
        # model embeds queries in the SAME space it was trained in.
        self._embedder = brain_embeddings.get_embedder(prefer=backend)

    # ── training ────────────────────────────────────────────────────────────

    @classmethod
    def train(
        cls,
        rows: list[dict[str, Any]],
        *,
        backend: str = "lexical",
    ) -> "BrainModel":
        """Fit the model on real fragment rows. ``backend`` selects the real
        embedder: ``"lexical"`` (default, zero-dep, deterministic) or
        ``"fastembed"`` (real ONNX transformer, only if the extra is
        installed)."""
        usable = [r for r in rows if _row_text(r)]
        if not usable:
            raise ValueError(
                "no fragment rows with text/triple content — nothing to train"
            )

        embedder = brain_embeddings.get_embedder(prefer=backend)
        texts = [_row_text(r) for r in usable]
        # Real embeddings for every fragment (batch path for the transformer
        # backend; lexical encode_batch is a deterministic loop).
        vecs = embedder.encode_batch(texts)
        mat = np.asarray(vecs, dtype=np.float32)
        if mat.ndim != 2:
            raise RuntimeError(f"embedder returned non-2D batch: shape={mat.shape}")
        mat = _l2_normalise(mat)
        dim = mat.shape[1]

        kind_of = [str(r.get("kind") or "unknown") for r in usable]
        scope_of = [str(r.get("scope") or "unknown") for r in usable]
        kind_labels, kind_centroids = _fit_centroids(mat, kind_of)
        scope_labels, scope_centroids = _fit_centroids(mat, scope_of)

        return cls(
            backend=embedder.backend_name,
            dim=dim,
            rows=usable,
            embeddings=mat,
            kind_labels=kind_labels,
            kind_centroids=kind_centroids,
            scope_labels=scope_labels,
            scope_centroids=scope_centroids,
        )

    # ── inference ─────────────────────────────────────────────────────────--

    def _embed_query(self, text: str) -> np.ndarray:
        v = np.asarray(self._embedder.encode(text), dtype=np.float32)
        n = float(np.linalg.norm(v))
        if n > 0:
            v = v / n
        return v

    def _classify(
        self, qvec: np.ndarray, labels: list[str], centroids: np.ndarray
    ) -> list[tuple[str, float]]:
        if not labels:
            return []
        sims = centroids @ qvec  # cosine (both unit-normed)
        order = np.argsort(-sims)
        return [(labels[i], float(sims[i])) for i in order]

    def query(self, text: str, *, k: int = 5) -> dict[str, Any]:
        """Real inference. Embeds ``text`` in the trained space and returns:

          * ``retrieved`` — the top-``k`` most-similar fragments (real cosine
            NN over the embedding index), each with its id / kind / scope /
            text + similarity score.
          * ``predicted_kind`` / ``predicted_scope`` — the nearest-centroid
            classification (the trained classifier's output) + the full ranked
            label→score lists.
        """
        if not text or not text.strip():
            raise ValueError("query text is empty")
        qvec = self._embed_query(text)

        sims = self.embeddings @ qvec  # [n] cosine scores
        k = max(1, min(k, len(self.rows)))
        # argpartition for the top-k, then sort just those k.
        top_idx = np.argpartition(-sims, k - 1)[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        retrieved = []
        for i in top_idx:
            r = self.rows[int(i)]
            retrieved.append(
                {
                    "id": r.get("id"),
                    "kind": r.get("kind"),
                    "scope": r.get("scope"),
                    "score": round(float(sims[int(i)]), 4),
                    "text": _row_text(r)[:200],
                }
            )

        kind_ranked = self._classify(qvec, self.kind_labels, self.kind_centroids)
        scope_ranked = self._classify(qvec, self.scope_labels, self.scope_centroids)
        return {
            "query": text,
            "backend": self.backend,
            "predicted_kind": kind_ranked[0][0] if kind_ranked else None,
            "predicted_scope": scope_ranked[0][0] if scope_ranked else None,
            "kind_scores": [{"label": l, "score": round(s, 4)} for l, s in kind_ranked],
            "scope_scores": [{"label": l, "score": round(s, 4)} for l, s in scope_ranked],
            "retrieved": retrieved,
        }

    def self_accuracy(self) -> dict[str, float]:
        """Training-set accuracy of the centroid classifier — for each
        fragment, does its own embedding's nearest kind/scope centroid match
        its true label? A real (in-sample) quality signal recorded in the
        manifest. Not held-out, but it proves the centroids actually separate
        the classes rather than collapsing."""
        if not self.rows:
            return {"kind": 0.0, "scope": 0.0}
        kind_idx = {lab: i for i, lab in enumerate(self.kind_labels)}
        scope_idx = {lab: i for i, lab in enumerate(self.scope_labels)}
        # cosine of every fragment to every centroid → argmax.
        kind_sims = self.embeddings @ self.kind_centroids.T  # [n, n_kinds]
        scope_sims = self.embeddings @ self.scope_centroids.T
        kind_pred = np.argmax(kind_sims, axis=1)
        scope_pred = np.argmax(scope_sims, axis=1)
        kind_hits = scope_hits = 0
        for j, r in enumerate(self.rows):
            if kind_pred[j] == kind_idx.get(str(r.get("kind") or "unknown"), -1):
                kind_hits += 1
            if scope_pred[j] == scope_idx.get(str(r.get("scope") or "unknown"), -1):
                scope_hits += 1
        n = len(self.rows)
        return {"kind": round(kind_hits / n, 4), "scope": round(scope_hits / n, 4)}

    # ── persistence ───────────────────────────────────────────────────────--

    def save(
        self,
        out_dir: Path,
        *,
        source: dict[str, Any],
        train_seconds: float,
    ) -> dict[str, Any]:
        """Persist the real artifact to ``out_dir`` and return the manifest."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        np.save(out_dir / "embeddings.npy", self.embeddings)
        np.save(out_dir / "kind_centroids.npy", self.kind_centroids)
        np.save(out_dir / "scope_centroids.npy", self.scope_centroids)

        # The rows the model trained on — provenance + the payload inference
        # returns. Written as JSONL to mirror dataset_export's format.
        frag_path = out_dir / "fragments.jsonl"
        with frag_path.open("w", encoding="utf-8", newline="\n") as f:
            for r in self.rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        model_json = {
            "schema_version": _ARTIFACT_SCHEMA_VERSION,
            "backend": self.backend,
            "dim": self.dim,
            "normalised": "l2",
            "n_fragments": len(self.rows),
            "kind_labels": self.kind_labels,
            "scope_labels": self.scope_labels,
            "files": {
                "embeddings": "embeddings.npy",
                "kind_centroids": "kind_centroids.npy",
                "scope_centroids": "scope_centroids.npy",
                "fragments": "fragments.jsonl",
            },
        }
        (out_dir / "model.json").write_text(
            json.dumps(model_json, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        acc = self.self_accuracy()
        manifest = {
            "ok": True,
            "schema_version": _ARTIFACT_SCHEMA_VERSION,
            "model_type": "embedding-index + nearest-centroid classifier",
            "task_ref": "ROADMAP #33 (collective hosted models — single-user prerequisite)",
            "backend": self.backend,
            "dim": self.dim,
            "n_fragments": len(self.rows),
            "n_kinds": len(self.kind_labels),
            "n_scopes": len(self.scope_labels),
            "kind_labels": self.kind_labels,
            "scope_labels": self.scope_labels,
            "train_self_accuracy": acc,
            "source": source,
            "train_seconds": round(train_seconds, 3),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "collective_caveat": (
                "SINGLE-USER training mechanism. 'Collective hosted models' "
                "(#33) = this same harness over the privacy-filtered AGGREGATE "
                "of many users' datasets via privacy.privatize_for_collective; "
                "that step awaits real users + the cross-user pull."
            ),
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        manifest["artifact_dir"] = str(out_dir)
        return manifest

    @classmethod
    def load(cls, artifact_dir: Path) -> "BrainModel":
        """Load a persisted artifact for real inference."""
        artifact_dir = Path(artifact_dir)
        model_json = json.loads(
            (artifact_dir / "model.json").read_text(encoding="utf-8")
        )
        embeddings = np.load(artifact_dir / "embeddings.npy")
        kind_centroids = np.load(artifact_dir / "kind_centroids.npy")
        scope_centroids = np.load(artifact_dir / "scope_centroids.npy")
        rows = _read_jsonl(artifact_dir / "fragments.jsonl")

        # Reconstruct the embedder from the persisted backend name. A backend
        # string like "lexical-hash-tfidf" / "fastembed:..." maps back to the
        # right `prefer=`; default to lexical (always available + deterministic).
        backend_name = model_json.get("backend", "lexical-hash-tfidf")
        prefer = "fastembed" if backend_name.startswith("fastembed") else "lexical"
        inst = cls.__new__(cls)
        inst.backend = backend_name
        inst.dim = int(model_json["dim"])
        inst.rows = rows
        inst.embeddings = embeddings
        inst.kind_labels = list(model_json["kind_labels"])
        inst.kind_centroids = kind_centroids
        inst.scope_labels = list(model_json["scope_labels"])
        inst.scope_centroids = scope_centroids
        inst._embedder = brain_embeddings.get_embedder(prefer=prefer)
        return inst


# ════════════════════════════════════════════════════════════════════════════
# High-level train() — load real data → fit → persist → return manifest
# ════════════════════════════════════════════════════════════════════════════


def train_model(
    *,
    name: str = "brain-model",
    dataset: Optional[Path] = None,
    brain_db: Optional[Path] = None,
    backend: str = "lexical",
    out_root: Path = _DEFAULT_OUT_ROOT,
    limit: int = 100_000,
    scopes: Optional[list[Scope]] = None,
) -> dict[str, Any]:
    """End-to-end: real dataset → real trained model → real artifact on disk.

    Returns the manifest dict (also written to ``manifest.json``).
    """
    t0 = time.perf_counter()
    rows, source = load_dataset(
        dataset=dataset,
        brain_db=brain_db,
        scopes=scopes,
        limit=limit,
        out_root=out_root,
    )
    model = BrainModel.train(rows, backend=backend)
    train_seconds = time.perf_counter() - t0
    out_dir = Path(out_root) / name
    manifest = model.save(out_dir, source=source, train_seconds=train_seconds)
    return manifest


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════


def _cmd_train(args: argparse.Namespace) -> int:
    scopes = None
    if args.scopes:
        scopes = [Scope(s.strip()) for s in args.scopes.split(",") if s.strip()]
    manifest = train_model(
        name=args.name,
        dataset=Path(args.dataset) if args.dataset else None,
        brain_db=Path(args.brain_db) if args.brain_db else None,
        backend=args.backend,
        out_root=Path(args.out_root) if args.out_root else _DEFAULT_OUT_ROOT,
        limit=args.limit,
        scopes=scopes,
    )
    art = Path(manifest["artifact_dir"])
    total_bytes = sum(p.stat().st_size for p in art.glob("*") if p.is_file())
    print("-- trained brain model -----------------------------------")
    print(f"artifact:        {art}")
    print(f"backend:         {manifest['backend']}  (dim={manifest['dim']})")
    print(f"fragments:       {manifest['n_fragments']}")
    print(f"kinds:           {manifest['n_kinds']} {manifest['kind_labels']}")
    print(f"scopes:          {manifest['n_scopes']} {manifest['scope_labels']}")
    print(f"self-accuracy:   {manifest['train_self_accuracy']}")
    print(f"train_seconds:   {manifest['train_seconds']}")
    print(f"artifact bytes:  {total_bytes:,}")
    print(f"source:          {manifest['source'].get('kind')}")
    if not args.no_demo:
        # Prove it works immediately: a real inference on a domain query.
        demo_q = args.query or "wall takeoff door schedule export"
        model = BrainModel.load(art)
        res = model.query(demo_q, k=min(5, manifest["n_fragments"]))
        print("\n-- demo inference ----------------------------------------")
        print(f"query:           {res['query']!r}")
        print(f"predicted kind:  {res['predicted_kind']}")
        print(f"predicted scope: {res['predicted_scope']}")
        print("top retrieved:")
        for hit in res["retrieved"]:
            print(f"  [{hit['score']:+.3f}] ({hit['kind']}) {hit['text'][:72]!r}")
    return 0


def _cmd_infer(args: argparse.Namespace) -> int:
    art = Path(args.artifact) if args.artifact else (_DEFAULT_OUT_ROOT / args.name)
    if not (art / "model.json").exists():
        print(
            f"no trained artifact at {art} — run `train` first "
            f"(or pass --artifact / --name).",
            file=sys.stderr,
        )
        return 2
    model = BrainModel.load(art)
    res = model.query(args.query, k=args.k)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    print(f"query:           {res['query']!r}")
    print(f"backend:         {res['backend']}")
    print(f"predicted kind:  {res['predicted_kind']}")
    print(f"predicted scope: {res['predicted_scope']}")
    print("top retrieved:")
    for hit in res["retrieved"]:
        print(f"  [{hit['score']:+.3f}] ({hit['kind']}/{hit['scope']}) "
              f"{hit['text'][:80]!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="train_brain_model",
        description="Brain #33 single-user training harness: brain dataset → "
                    "real embedding-index + centroid model → real inference.",
    )
    sub = p.add_subparsers(dest="cmd", required=False)

    pt = sub.add_parser("train", help="train a model on the brain / a JSONL")
    pt.add_argument("--name", default="brain-model", help="artifact dir name")
    pt.add_argument("--dataset", default=None,
                    help="JSONL produced by dataset_export (skips brain read)")
    pt.add_argument("--brain-db", default=None,
                    help="path to brain.db (default: OS per-user location)")
    pt.add_argument("--backend", default="lexical", choices=["lexical", "fastembed"],
                    help="embedder backend (default lexical, zero-dep)")
    pt.add_argument("--out-root", default=None, help="artifact root dir")
    pt.add_argument("--limit", type=int, default=100_000, help="max fragments")
    pt.add_argument("--scopes", default=None,
                    help="comma scopes e.g. user,project,firm (default those 3)")
    pt.add_argument("--query", default=None, help="demo inference query")
    pt.add_argument("--no-demo", action="store_true", help="skip demo inference")
    pt.set_defaults(func=_cmd_train)

    pi = sub.add_parser("infer", help="run inference against a trained artifact")
    pi.add_argument("--query", required=True, help="the query to answer")
    pi.add_argument("--artifact", default=None, help="artifact dir")
    pi.add_argument("--name", default="brain-model", help="artifact name under out-root")
    pi.add_argument("--k", type=int, default=5, help="top-k to retrieve")
    pi.add_argument("--json", action="store_true", help="emit JSON")
    pi.set_defaults(func=_cmd_infer)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    # Windows consoles default to cp1252, which can't encode fragment text that
    # carries non-Latin-1 glyphs (and trips on box-drawing). Make our own stdout
    # tolerant so a print never crashes the run; never mutates global state.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        # Default action: train on the live brain (the real, runs-here path).
        args = parser.parse_args(["train"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
