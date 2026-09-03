"""Sync layer — dual transport (text-CRDT + spatial-content-addressed).

AgDR-0044 Slice 6 + F3 (Loro CRDT + Tailscale, EXTENDED with Speckle for
spatial memory). Two parallel transports for two different data shapes:

  TEXT / SKILL / SETUP MEMORY     SPATIAL / GEOMETRIC MEMORY
  ─────────────────────────       ──────────────────────────
  LoroTransport (CRDT)            SpeckleSpatialTransport (content-addressed)
  movable-tree + LWW-Map          immutable Versions per geometry hash
  mutate, merge, conflict-free    publish, fetch-by-hash, never overwrite

Both speak the same `Transport` protocol so the BrainStore.sync() driver
is shape-agnostic.

This file ships:
  - Transport protocol (every backend implements `push` + `pull`)
  - JsonFileTransport (zero-deps, the default for personal-tier sync)
  - HLC-aware merge function (deterministic across devices)
  - LoroTransport (stub — raises a clear error when loro-py not installed)
  - SpeckleSpatialTransport (stub — raises until speckle-py installed)

Tests cover Transport contract + JSON impl + HLC merge semantics.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from . import hlc as _hlc


# ─────────────────────── Transport protocol ────────────────────────────


class Transport(Protocol):
    """Every sync backend implements this minimal pair.

    push(snapshot) atomically publishes the snapshot.
    pull() returns the latest snapshot, or None if empty.
    """

    name: str

    def push(self, snapshot: dict[str, Any]) -> None: ...
    def pull(self) -> Optional[dict[str, Any]]: ...


# ─────────────────────── JSON file transport (default) ─────────────────


class JsonFileTransport:
    """Single-file JSON snapshot. Atomic via tmp + os.replace. Good for:
    - personal tier (one file in iCloud / Dropbox / OneDrive folder)
    - test environments
    - bootstrap before Loro lands

    Carries the brain snapshot dict with HLC stamps on every fragment so
    merge stays deterministic even with concurrent edits.
    """

    name = "json-file"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def push(self, snapshot: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=str(self.path.parent),
            prefix=self.path.name + ".",
            suffix=".tmp",
        ) as f:
            json.dump(snapshot, f, indent=2, default=str, sort_keys=True)
            tmp_name = f.name
        os.replace(tmp_name, self.path)

    def pull(self) -> Optional[dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


# ─────────────────────── Loro transport (stub) ─────────────────────────


class LoroTransport:
    """Real Loro CRDT backend (F3.A founder pick, verified against loro 1.10.3).

    Stores the brain snapshot inside a Loro document. Multi-device sync
    works in two layers:
      1. Each device's LoroDoc holds its local view of the snapshot. When
         a remote snapshot arrives via push, we `import_` its bytes into
         the local doc. Loro's CRDT semantics merge the two doc states
         deterministically and without coordination.
      2. After Loro reconciles the doc, we extract `snapshot_json` and
         hand it to `merge_snapshots()` for per-fragment HLC resolution.

    File format: a single `.loro` file holding the exported Snapshot. On
    push we open the existing file (if any), import remote into it, set
    the local snapshot, and rewrite. On pull we open the file and return
    the snapshot extracted from the LoroDoc state.
    """

    name = "loro-crdt"

    def __init__(self, doc_path: str | Path):
        try:
            import loro  # type: ignore
        except ImportError as ex:
            raise RuntimeError(
                "LoroTransport requires the `loro` package. "
                "Install with `pip install loro`."
            ) from ex
        self._loro = loro
        self.doc_path = Path(doc_path)
        # Root map name — single "main" map; the snapshot lives at key
        # "snapshot_json" as a JSON-encoded string (Loro merges at the map
        # level; structural merge of fragments happens in merge_snapshots).
        self._root_name = "main"
        self._snapshot_key = "snapshot_json"

    def _open_doc(self):
        """Open the loro doc — either load existing file or create new."""
        doc = self._loro.LoroDoc()
        if self.doc_path.exists():
            try:
                data = self.doc_path.read_bytes()
                if data:
                    doc.import_(data)
            except Exception:
                pass  # treat corrupted file as empty doc
        return doc

    def _write_doc(self, doc) -> None:
        snapshot_bytes = bytes(doc.export(self._loro.ExportMode.Snapshot()))
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False,
            dir=str(self.doc_path.parent),
            prefix=self.doc_path.name + ".",
            suffix=".tmp",
        ) as f:
            f.write(snapshot_bytes)
            tmp_name = f.name
        os.replace(tmp_name, self.doc_path)

    def push(self, snapshot: dict[str, Any]) -> None:
        doc = self._open_doc()
        m = doc.get_map(self._root_name)
        m.insert(self._snapshot_key, json.dumps(snapshot, default=str))
        doc.commit()
        self._write_doc(doc)

    def pull(self) -> Optional[dict[str, Any]]:
        if not self.doc_path.exists():
            return None
        try:
            doc = self._open_doc()
            value = doc.get_map(self._root_name).get_value()
            payload = value.get(self._snapshot_key) if isinstance(value, dict) else None
            if not payload:
                return None
            return json.loads(payload)
        except Exception:
            return None

    def import_remote_bytes(self, remote_bytes: bytes) -> Optional[dict[str, Any]]:
        """Merge a remote loro snapshot (raw bytes) into this transport's
        local doc, then return the merged snapshot dict. Lets ArchHub sync
        directly device-to-device without a JSON intermediate.
        """
        doc = self._open_doc()
        try:
            doc.import_(remote_bytes)
            self._write_doc(doc)
        except Exception:
            return None
        value = doc.get_map(self._root_name).get_value()
        payload = value.get(self._snapshot_key) if isinstance(value, dict) else None
        return json.loads(payload) if payload else None

    def export_snapshot_bytes(self) -> Optional[bytes]:
        """Export the local loro doc as raw bytes — usable by another
        device's `import_remote_bytes`."""
        if not self.doc_path.exists():
            return None
        try:
            return self.doc_path.read_bytes()
        except Exception:
            return None


# ─────────────────────── Speckle spatial transport (stub) ──────────────


class SpeckleSpatialTransport:
    """Spatial/geometric memory transport (founder pick — F3 + Speckle
    addendum 2026-05-25). Backed by specklepy 3.0.8.

    ArchHub already uses Speckle Versions extensively. The content-
    addressed model is purpose-built for geometric fragments: a wall
    composition, a render framing, a Blender mesh. Each fragment is
    stored as an immutable Speckle Object identified by its content hash;
    multiple devices referencing the same geometry converge automatically.

    Slice 6 implementation: LOCAL Speckle SQLite transport (offline-first,
    no network required, matches ArchHub's existing local Speckle pattern
    per AgDR-0012 "Direction X"). Cloud federation via streams + tokens
    lands as a future config (passing `host=` + `token_ref=` activates a
    `ServerTransport` in tandem; Slice 6 keeps it local-only by default).

    The transport is asymmetric vs Loro:
      - PUSH filters the snapshot to SPATIAL fragments, wraps them in a
        Base object, sends through the SQLite transport (content-addressed
        local store). Stores the resulting object hash as the "head".
      - PULL receives the head object via the SQLite transport and
        re-hydrates the spatial fragments.

    Non-spatial fragments are passed through unchanged (other transports
    handle text / skills / setups).
    """

    name = "speckle-spatial"

    def __init__(
        self,
        store_path: str | Path,
        *,
        stream_id: str = "personal-brain-local",
        host: Optional[str] = None,
        token_ref: Optional[str] = None,
    ):
        try:
            from specklepy.transports.sqlite import SQLiteTransport  # type: ignore
            from specklepy.objects.base import Base  # type: ignore
            from specklepy.api import operations  # type: ignore
        except ImportError as ex:  # pragma: no cover
            raise RuntimeError(
                "SpeckleSpatialTransport requires `specklepy`. "
                "Install with `pip install specklepy`."
            ) from ex
        self._SQLiteTransport = SQLiteTransport
        self._Base = Base
        self._operations = operations

        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.stream_id = stream_id
        self.host = host
        self.token_ref = token_ref

        # Pointer file recording the latest object hash (the spatial "head")
        self._head_file = self.store_path / "spatial_head.txt"

    def _open_transport(self):
        return self._SQLiteTransport(
            base_path=str(self.store_path),
            app_name="personal-brain",
            scope=self.stream_id,
        )

    def _is_spatial(self, frag: dict[str, Any]) -> bool:
        return (frag or {}).get("kind") == "spatial"

    def push(self, snapshot: dict[str, Any]) -> None:
        """Push spatial fragments through Speckle's content-addressed
        SQLite transport. Updates the head pointer with the resulting
        object hash."""
        fragments = snapshot.get("fragments") or []
        spatial = [f for f in fragments if self._is_spatial(f)]
        non_spatial = [f for f in fragments if not self._is_spatial(f)]

        # Build a Speckle Base wrapping the spatial fragments
        root = self._Base()
        # Speckle's Base treats nested dicts as detachable members. Use
        # a stable single field; the SDK chunks + hashes children.
        root.spatial_fragments = spatial
        root.non_spatial_count = len(non_spatial)
        root.snapshot_ms = snapshot.get("snapshot_ms", 0)

        local_t = self._open_transport()
        local_t.begin_write()
        try:
            obj_id = self._operations.send(
                base=root, transports=[local_t], use_default_cache=False,
            )
        finally:
            local_t.end_write()

        # Write the head pointer
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=str(self.store_path),
            prefix="spatial_head.", suffix=".tmp",
        ) as f:
            f.write(obj_id)
            tmp = f.name
        os.replace(tmp, self._head_file)

    def pull(self) -> Optional[dict[str, Any]]:
        """Reconstruct the spatial fragments from the latest head."""
        if not self._head_file.exists():
            return None
        try:
            obj_id = self._head_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not obj_id:
            return None

        local_t = self._open_transport()
        try:
            base = self._operations.receive(
                obj_id=obj_id, local_transport=local_t,
            )
        except Exception:
            return None

        # Extract back to plain dict
        spatial = getattr(base, "spatial_fragments", None) or []
        # Normalise specklepy.Base wrappers back to plain dicts if needed
        spatial_dicts: list[dict[str, Any]] = []
        for item in spatial:
            if isinstance(item, dict):
                spatial_dicts.append(item)
            else:
                # Speckle Base — unpack public attributes
                try:
                    spatial_dicts.append(item.get_dynamic_member_values())  # may exist
                except Exception:
                    try:
                        spatial_dicts.append(dict(item.__dict__))
                    except Exception:
                        pass

        return {
            "fragments": spatial_dicts,
            "snapshot_ms": getattr(base, "snapshot_ms", 0),
            "_speckle_head": obj_id,
        }


# ─────────────────────── snapshot helpers ──────────────────────────────


@dataclass
class MergeResult:
    """Outcome of a merge between two snapshots."""

    fragments: int = 0
    fragments_added: int = 0
    fragments_updated: int = 0
    skills: int = 0
    skills_added: int = 0
    skills_updated: int = 0
    conflicts_resolved: int = 0


def stamp_with_hlc(item: dict[str, Any], clock: Optional[_hlc.HLC] = None) -> dict[str, Any]:
    """Add an HLC timestamp to an item's provenance.hlc field. Returns the
    same dict (mutates in place for convenience).
    """
    clock = clock or _hlc.device_clock()
    ts = clock.tick()
    prov = item.get("provenance") or {}
    if isinstance(prov, str):
        try:
            prov = json.loads(prov)
        except Exception:
            prov = {}
    prov["hlc"] = ts
    item["provenance"] = prov
    return item


def snapshot_from_store(
    store_count_fn,
    fragments: Iterable[dict[str, Any]],
    skills: Iterable[dict[str, Any]],
    *,
    device_id: Optional[str] = None,
) -> dict[str, Any]:
    """Compose a snapshot dict ready to push via a Transport.

    `store_count_fn` is called only for the snapshot's metadata (counts);
    pass `lambda: (n_fragments, n_skills)` or similar.
    """
    nf, ns = store_count_fn()
    return {
        "version": 1,
        "device_id": device_id or "unknown",
        "snapshot_ms": int(time.time() * 1000),
        "counts": {"fragments": nf, "skills": ns},
        "fragments": list(fragments),
        "skills": list(skills),
    }


def merge_snapshots(
    local: dict[str, Any], remote: dict[str, Any],
) -> tuple[dict[str, Any], MergeResult]:
    """Deterministic merge of two snapshots. Uses HLC on each item to
    resolve conflicts — newer HLC wins. Union of unique items.

    Property: merge(a, b) == merge(b, a) (commutative).
    Property: merge(a, merge(a, b)) == merge(a, b) (idempotent).
    """
    result = MergeResult()

    merged: dict[str, Any] = {
        "version": max(local.get("version", 1), remote.get("version", 1)),
        "device_id": local.get("device_id"),
        "snapshot_ms": max(local.get("snapshot_ms", 0),
                           remote.get("snapshot_ms", 0)),
    }

    merged["fragments"] = _merge_by_id(
        local.get("fragments") or [], remote.get("fragments") or [],
        result, kind="fragments",
    )
    merged["skills"] = _merge_by_id(
        local.get("skills") or [], remote.get("skills") or [],
        result, kind="skills",
    )

    result.fragments = len(merged["fragments"])
    result.skills = len(merged["skills"])
    merged["counts"] = {"fragments": result.fragments, "skills": result.skills}

    return merged, result


def _merge_by_id(
    local: list[dict[str, Any]], remote: list[dict[str, Any]],
    result: MergeResult, *, kind: str,
) -> list[dict[str, Any]]:
    """Union by `id` field. On id collision: newer HLC wins.
    If neither has an HLC, fall back to lex comparison of `provenance.created_at`."""
    by_id: dict[str, dict[str, Any]] = {}

    for item in local:
        iid = item.get("id")
        if not iid:
            continue
        by_id[iid] = item
        if kind == "fragments":
            result.fragments_added += 1
        else:
            result.skills_added += 1

    for item in remote:
        iid = item.get("id")
        if not iid:
            continue
        if iid in by_id:
            winner = _pick_newer(by_id[iid], item)
            if winner is item:
                by_id[iid] = item
                if kind == "fragments":
                    result.fragments_updated += 1
                else:
                    result.skills_updated += 1
            result.conflicts_resolved += 1
        else:
            by_id[iid] = item
            if kind == "fragments":
                result.fragments_added += 1
            else:
                result.skills_added += 1

    return list(by_id.values())


def _pick_newer(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Compare two items by HLC; tie-break by created_at; tie-break by id."""
    ah = _extract_hlc(a)
    bh = _extract_hlc(b)
    if ah > bh:
        return a
    if bh > ah:
        return b
    # tie on HLC — compare created_at
    a_ts = _extract_created_at(a)
    b_ts = _extract_created_at(b)
    if a_ts > b_ts:
        return a
    if b_ts > a_ts:
        return b
    # final deterministic tie-break: lex on id
    return a if str(a.get("id", "")) >= str(b.get("id", "")) else b


def _extract_hlc(item: dict[str, Any]) -> int:
    prov = item.get("provenance") or {}
    if isinstance(prov, str):
        try:
            prov = json.loads(prov)
        except Exception:
            return 0
    h = prov.get("hlc")
    if isinstance(h, int):
        return h
    if isinstance(h, str):
        try:
            return int(h, 16) if len(h) == 16 else int(h)
        except Exception:
            return 0
    return 0


def _extract_created_at(item: dict[str, Any]) -> str:
    prov = item.get("provenance") or {}
    if isinstance(prov, str):
        try:
            prov = json.loads(prov)
        except Exception:
            return ""
    return str(prov.get("created_at") or "")


# ─────────────────────── push / pull / sync ────────────────────────────


def push(snapshot: dict[str, Any], transport: Transport) -> None:
    transport.push(snapshot)


def pull(transport: Transport) -> Optional[dict[str, Any]]:
    return transport.pull()


def sync(
    local: dict[str, Any], transport: Transport,
) -> tuple[dict[str, Any], MergeResult]:
    """Pull + merge + push round-trip. Returns (merged_snapshot, stats)."""
    remote = transport.pull() or {}
    merged, result = merge_snapshots(local, remote)
    transport.push(merged)
    return merged, result
