"""Seed a deterministic valid application graph into a supplied temporary directory.

No installed store is accepted. Shape defaults come from aggregate-only STEP 1
evidence; --target-gb scales row counts, history amplification and payload bytes.
All graph/revision writes use CellStore.commit (no fabricated history rows).
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "01.APP") not in sys.path:
    sys.path.insert(0, str(ROOT / "01.APP"))

FIXTURE_EPOCH = 1791984000.0
DEFAULT_SHAPE = ROOT / "05.EVIDENCE" / "lazyboot" / "real-store-shape.json"


def fixture_key_provider():
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    provider = MemorySigningKeyProvider("archhub.local.relationship-authority", b"L" * 32)
    provider.add_key("archhub.local.court-attestation", b"B" * 32)
    return provider


def _padded_identifier(prefix: str, index: int, length: int) -> str:
    base = "%s:%08d" % (prefix, index)
    if len(base) >= length:
        return base
    suffix = hashlib.sha256(base.encode("ascii")).hexdigest()
    return base + ":" + (suffix * ((length - len(base)) // len(suffix) + 1))[:length - len(base) - 1]


class _FixtureDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(FIXTURE_EPOCH, tz)

    @classmethod
    def utcnow(cls):
        return cls.fromtimestamp(FIXTURE_EPOCH, timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()


class _FixtureDate(date):
    @classmethod
    def today(cls):
        return cls.fromtimestamp(FIXTURE_EPOCH)


def _restore_late_clock_bindings() -> None:
    for module in tuple(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("nodelang."):
            for name, value in tuple(vars(module).items()):
                if value is _FixtureDateTime:
                    setattr(module, name, datetime)
                elif value is _FixtureDate:
                    setattr(module, name, date)


def _validate_temp_destination(path: Path) -> Path:
    destination = path.resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if destination == temporary or not destination.is_relative_to(temporary):
        raise ValueError("fixture destination must be a child of the OS temporary directory")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("fixture destination must be empty; existing files are never overwritten")
    return destination


def _temp_destination(path: Path) -> Path:
    destination = _validate_temp_destination(path)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "README.md").write_text(
        "# LAZYBOOT synthetic store fixture\n\nPurpose: boot performance and verified lazy-read courts.\n"
        "Owner: LAZYBOOT court / release PERF gate.\nTier: T1 INTERNAL.\n"
        "Scope: deterministic synthetic graph only; no installed or private store content.\n"
        "Files remain in 01.WIP; register is generated from disk; caller deletes this temporary fixture after the court.\n",
        encoding="utf-8")
    for state in ("01.WIP", "02.SHARED", "03.PUBLISHED", "04.ARCHIVE"):
        (destination / state).mkdir()
    return destination


def _seed_large_store_in_process(temp_dir: str | Path, target_gb: float = 0.08, shape: dict | Path | None = None, *, reachable_cells: int | None = None) -> dict:
    from nodelang.cell_protocols import compose_relation_cells, prepare_append_relation_members
    from nodelang.universal_application import build_universal_application
    from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID
    import nodelang.cell_attestations as attestation_module

    if not 0 < target_gb <= 32:
        raise ValueError("target_gb must be positive and at most 32")
    destination = _temp_destination(Path(temp_dir))
    if shape is None:
        shape = json.loads(DEFAULT_SHAPE.read_text(encoding="utf-8")) if DEFAULT_SHAPE.exists() else {}
    elif isinstance(shape, (str, Path)):
        shape = json.loads(Path(shape).read_text(encoding="utf-8"))
    stores = shape.get("stores", {})
    real = next((value for name, value in stores.items() if name.endswith("universal.sqlite3")), {})
    structure = real.get("current_structure", {})
    current = structure.get("cells", real.get("tables", {}).get("current_cells", {}).get("rows", 6_959_711))
    history = real.get("history", {})
    versions = history.get("version_rows", real.get("tables", {}).get("cell_versions", {}).get("rows", 7_308_761))
    real_revisions = real.get("tables", {}).get("revisions", {}).get("rows", 134_873)
    real_bytes = real.get("file_bytes", 7_572_131_840)
    ratio = target_gb * (1024 ** 3) / real_bytes
    # Smaller courts can hold the measured walk shape while reducing byte size.
    wanted_cells = max(3000, round(current * ratio)) if reachable_cells is None else max(3000, reachable_cells)
    history_ratio = max(0.0, history.get("superseded_rows", versions - current) / max(1, history.get("current_cell_ids", current)))
    empty_ratio = structure.get("empty_atoms", 6_239_993) / current
    chain_ratio = structure.get("relation_chain_cells", 3_008_150) / current
    atom_ratio = structure.get("atom_bytes", 25_314_931) / current
    identifier_ratio = structure.get("identifier_bytes", 1_808_340_729) / current
    path = destination / "01.WIP" / "fixture.universal.sqlite3"
    map_path = ROOT / "01.APP/nodelang" / "data" / "public_runtime_map.json"
    provider = fixture_key_provider()
    random_source = random.Random(71743447)
    started = time.perf_counter()
    with ExitStack() as deterministic:
        deterministic.callback(_restore_late_clock_bindings)
        deterministic.enter_context(patch("uuid.uuid4", lambda: uuid.UUID(int=random_source.getrandbits(128), version=4)))
        deterministic.enter_context(patch("time.time", lambda: FIXTURE_EPOCH))
        # Signed evidence records include durationMs. Freeze only generation's
        # attestation telemetry clock; the checks and signatures execute fully.
        deterministic.enter_context(patch.object(attestation_module, "time",
            SimpleNamespace(time=lambda: FIXTURE_EPOCH, monotonic=lambda: 0.0)))
        deterministic.enter_context(patch("secrets.token_bytes", lambda size=32: random_source.randbytes(size)))
        deterministic.enter_context(patch("secrets.token_hex", lambda size=32: random_source.randbytes(size).hex()))
        for module in tuple(sys.modules.values()):
            if getattr(module, "__name__", "").startswith("nodelang."):
                for name, value in tuple(vars(module).items()):
                    if value is datetime:
                        deterministic.enter_context(patch.object(module, name, _FixtureDateTime))
                    elif value is date:
                        deterministic.enter_context(patch.object(module, name, _FixtureDate))
        # Modules imported during the first build must see the same fixed clock
        # as modules already loaded before subsequent builds.
        deterministic.enter_context(patch("datetime.datetime", _FixtureDateTime))
        deterministic.enter_context(patch("datetime.date", _FixtureDate))
        store = CellStore(path)
        try:
            store, registry = build_universal_application(map_path, store, key_provider=provider, court_workspace_root=ROOT)
            base_cells = len(store.snapshot().cells)
            base_versions = store._journal._connection.execute("SELECT count(*) FROM cell_versions").fetchone()[0]
            base_atoms, base_nonempty, base_chains, base_identifier_bytes = store._journal._connection.execute(
                "SELECT sum(length(atom)),sum(length(atom)>0),sum(instr(link0,':incidence:')>0),"
                "sum(length(CAST(cell_id AS BLOB))+length(CAST(link0 AS BLOB))+length(CAST(link1 AS BLOB))) FROM current_cells").fetchone()
            print("fixed application seed: %d cells, %d versions, %d revisions" % (base_cells, base_versions, store.snapshot().revision + 1), flush=True)
            # This is a disposable court fixture, not an installed store or a
            # durability court. WAL/validated commits remain; NORMAL avoids one
            # fsync for every tiny historical revision during synthetic seeding.
            store._journal._connection.execute("PRAGMA synchronous=NORMAL")
            # Every synthetic relation is an ordinary application member, as
            # live ledgers/catalogues are. Eager view discovery walks each;
            # Home's deferred discovery reads these only on explicit open.
            target_total_cells = max(base_cells + 64, wanted_cells)
            added_target = target_total_cells - base_cells
            payload_count = max(16, round(added_target * (1 - empty_ratio)))
            relation_members = max(16, round(added_target * chain_ratio))
            pair_count = max(0, target_total_cells - base_cells - payload_count - 2 * relation_members)
            added_cells = payload_count + pair_count + 2 * relation_members
            payload_atom_total = max(0, round((base_cells + added_cells) * atom_ratio) - base_atoms)
            payload_bytes, payload_extra = divmod(payload_atom_total, payload_count)
            identifier_total = max(0, round((base_cells + added_cells) * identifier_ratio) - base_identifier_bytes)
            added_identifier_average = identifier_total / max(1, added_cells)
            payload_id_length = max(48, min(256, round(identifier_ratio / 3)))
            # A chain has three relation IDs; an incidence one relation ID,
            # a role and one participant; other binary cells have three IDs.
            leaf_fraction = payload_count / added_cells
            pair_fraction = pair_count / added_cells
            incidence_fraction = relation_members / added_cells
            relation_id_length = max(48, min(4096, round((added_identifier_average
                - (incidence_fraction + leaf_fraction + 3 * pair_fraction) * payload_id_length
                - 62 * incidence_fraction - 72 * leaf_fraction) / max(0.001, 4 * incidence_fraction))))
            def payload_id(index):
                return _padded_identifier("fixture:ledger:payload", index, payload_id_length)
            def pair_id(index):
                return _padded_identifier("fixture:ledger:binary", index, payload_id_length)
            def participant_id(index):
                return payload_id(index) if index < payload_count else pair_id(index - payload_count)
            # Keep only one bounded commit batch, never millions of Cells or
            # participant-ID strings. The relation tails share the leaf pool.
            for offset in range(0, payload_count, 4096):
                end = min(payload_count, offset + 4096)
                store.commit(store.snapshot().revision, create=(Cell(payload_id(index), NULL_CELL_ID, NULL_CELL_ID,
                    b"s" * (payload_bytes + (index < payload_extra))) for index in range(offset, end)))
            for offset in range(0, pair_count, 4096):
                end = min(pair_count, offset + 4096)
                store.commit(store.snapshot().revision, create=(Cell(pair_id(index), payload_id(index % payload_count),
                    payload_id((index + 1) % payload_count), b"") for index in range(offset, end)))
            synthetic_roots = []
            participant_count = payload_count + pair_count
            for offset in range(0, relation_members, 4096):
                end = min(relation_members, offset + 4096)
                root = _padded_identifier("fixture:ledger:relation", offset, relation_id_length)
                relation = compose_relation_cells(((registry.roles["member"], participant_id(index % participant_count))
                    for index in range(offset, end)), relation_id=root)
                snapshot = store.snapshot()
                registration = prepare_append_relation_members(snapshot, registry.application_root,
                    ((registry.roles["member"], root),), budget=100_000)
                store.commit(snapshot.revision, create=(*relation.cells, *registration.create), replace=registration.replace)
                synthetic_roots.append(root)
                if len(synthetic_roots) % 100 == 0:
                    print("registered relation tail cells: %d" % (2 * end), flush=True)
            # Preserve every historical version through the real journal path.
            target_history = round(len(store.snapshot().cells) * history_ratio)
            remaining = max(0, target_history - (base_versions - base_cells))
            target_revisions = max(store.snapshot().revision + 1, round(len(store.snapshot().cells) * real_revisions / current))
            commits_remaining = min(remaining, target_revisions - (store.snapshot().revision + 1))
            commits_remaining = max(1, commits_remaining)
            round_number, cursor = 0, 0
            history_toggle = bytearray(payload_count)
            while remaining:
                round_number += 1
                amount = min(remaining, max(1, (remaining + commits_remaining - 1) // commits_remaining), 4096, payload_count)
                indexes = tuple((cursor + offset) % payload_count for offset in range(amount))
                cursor = (cursor + amount) % payload_count
                for index in indexes:
                    history_toggle[index] ^= 1
                store.commit(store.snapshot().revision, replace=(
                    Cell(payload_id(index), NULL_CELL_ID, NULL_CELL_ID,
                         bytes((65 + history_toggle[index],)) * max(1, payload_bytes + (index < payload_extra)))
                    for index in indexes))
                remaining -= amount
                commits_remaining = max(1, commits_remaining - 1)
                if round_number % 10_000 == 0:
                    print("history commits: %d; remaining version rows: %d" % (round_number, remaining), flush=True)
            count = len(store.snapshot().cells)
            revision = store.snapshot().revision
        finally:
            for name in ("_runtime_presence_lease_storage", "_cde_operational_storage"):
                operational = getattr(store, name, None)
                if operational is not None:
                    operational.close()
            store.close()
    # Checkpoint fixture-owned WAL only; this never accesses an installed store.
    import sqlite3
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        history_rows = db.execute("SELECT count(*) FROM cell_versions").fetchone()[0]
        generated_empty, generated_atoms, generated_chains, generated_identifiers = db.execute(
            "SELECT sum(length(atom)=0),sum(length(atom)),sum(instr(link0,':incidence:')>0),"
            "sum(length(CAST(cell_id AS BLOB))+length(CAST(link0 AS BLOB))+length(CAST(link1 AS BLOB))) FROM current_cells").fetchone()
    manifest = {"path": str(path), "map_path": str(map_path), "target_gb": target_gb,
                "shape_source": "aggregate STEP 1" if real else "fallback shape (measurement unavailable)",
                "real_current_cells": current, "real_version_rows": versions, "total_cells": count,
                "history_rows": history_rows, "history_amplification": history_ratio,
                "revision": revision, "revision_rows": revision + 1,
                "real_revision_rows": real_revisions, "target_revision_rows": target_revisions,
                "target_superseded_rows": target_history, "database_bytes": path.stat().st_size,
                "target_semantics": "requested GiB scales measured live row/byte shape; physical size is approximate and cannot be below the fixed valid application seed floor",
                "generation_settings": {"fixture_only": True, "journal_mode": "WAL", "synchronous": "NORMAL after fixed seed", "crash_durability_claim": False},
                "fixed_seed_cells": base_cells, "fixed_seed_atom_bytes": base_atoms,
                "fixed_seed_nonempty_atoms": base_nonempty,
                "fixed_seed_identifier_bytes": base_identifier_bytes, "fixed_seed_chain_cells": base_chains,
                "generated_empty_atoms": generated_empty, "generated_atom_bytes": generated_atoms,
                "generated_relation_chain_cells": generated_chains, "generated_identifier_bytes": generated_identifiers,
                "generated_empty_atom_ratio": generated_empty / count, "reference_empty_atom_ratio": empty_ratio,
                "generated_chain_ratio": generated_chains / count, "reference_chain_ratio": chain_ratio,
                "payload_bytes": payload_bytes, "payload_pool_cells": payload_count,
                "other_binary_cells": pair_count, "relation_id_length": relation_id_length,
                "target_relation_root": synthetic_roots[0],
                "target_member_roots": [participant_id(index % participant_count) for index in range(min(4096, relation_members))],
                "synthetic_relation_roots": synthetic_roots}
    disk_manifest = {**manifest, "path": path.relative_to(destination).as_posix(), "map_path": map_path.relative_to(ROOT).as_posix()}
    (destination / "01.WIP" / "fixture-manifest.json").write_text(json.dumps(disk_manifest, indent=2) + "\n", encoding="utf-8")
    register = ["| No | Title | Rev | State | Date | File | SHA-256 |", "|---:|---|---|---|---|---|---|"]
    for number, item in enumerate(sorted((destination / "01.WIP").rglob("*")), 1):
        if item.is_file():
            digest = hashlib.sha256()
            with item.open("rb") as source:
                while block := source.read(1024 * 1024):
                    digest.update(block)
            register.append("| %d | %s | 1 | WIP | %s | %s | %s |" %
                            (number, item.name, datetime.fromtimestamp(item.stat().st_mtime).date().isoformat(), item.relative_to(destination).as_posix(), digest.hexdigest()))
    (destination / "REGISTER.md").write_text("\n".join(register) + "\n", encoding="utf-8")
    return {**manifest, "path": path, "map_path": map_path, "key_provider": provider,
            "generation_seconds": round(time.perf_counter() - started, 6)}


def seed_large_store(temp_dir: str | Path, target_gb: float = 0.08, shape: dict | Path | None = None, *, reachable_cells: int | None = None) -> dict:
    """Create in one owned child process; exit releases every fixture handle.

    The benchmark caller's clock and imports are never frozen. CLI and API share
    the same in-process writer; all subprocesses inherit the run-heavy job.
    """
    destination = _validate_temp_destination(Path(temp_dir))
    command = [sys.executable, str(Path(__file__).resolve()), "--temp-dir", str(destination), "--target-gb", str(target_gb)]
    source = None
    if isinstance(shape, dict):
        command.append("--shape-stdin")
        source = json.dumps(shape)
    elif shape is not None:
        command.extend(("--shape", str(shape)))
    if reachable_cells is not None:
        command.extend(("--reachable-cells", str(reachable_cells)))
    started = time.perf_counter()
    result = subprocess.run(command, input=source, capture_output=True, text=True, cwd=ROOT)
    for line in result.stdout.splitlines():
        if line.startswith(("fixed application seed:", "registered relation tail cells:", "history commits:")):
            print(line, flush=True)
    if result.returncode:
        raise RuntimeError("fixture generator child failed: " + result.stderr[-4000:])
    manifest = json.loads((destination / "01.WIP" / "fixture-manifest.json").read_text(encoding="utf-8"))
    return {**manifest, "path": destination / manifest["path"], "map_path": ROOT / manifest["map_path"],
            "key_provider": fixture_key_provider(), "generation_seconds": round(time.perf_counter() - started, 6)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("--target-gb", type=float, required=True, help="target binary gigabytes (GiB); row shape scales from STEP 1")
    parser.add_argument("--shape", type=Path, default=DEFAULT_SHAPE)
    parser.add_argument("--reachable-cells", type=int)
    parser.add_argument("--shape-stdin", action="store_true", help="receive aggregate shape JSON on standard input")
    args = parser.parse_args()
    source_shape = json.loads(sys.stdin.read()) if args.shape_stdin else args.shape if args.shape.exists() else None
    result = _seed_large_store_in_process(args.temp_dir, args.target_gb, source_shape,
                              reachable_cells=args.reachable_cells)
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()
                      if key not in ("key_provider", "target_member_roots")}, indent=2))


if __name__ == "__main__":
    main()
