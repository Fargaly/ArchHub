"""Crash-safe physical generation selection for one unified Cell authority.

Each generation is complete before an atomic ``CURRENT`` pointer selects it.
The pointer is only a physical locator; the signed bootstrap manifest and Cell
graph remain the authority and are verified on every open.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterable
import uuid

from .cell_secret_keys import SigningKeyProvider, WindowsDpapiSigningKeyProvider
from .unified_authority import (
    BootstrapManifest,
    UnifiedAuthority,
    create_unified_authority,
    open_unified_authority,
)
from .universal_cell import (
    CellStore,
    DatabaseOwnerConflict,
    InterprocessOwnerFence,
    InvalidCell,
)


DATABASE_NAME = "authority.sqlite3"
MANIFEST_NAME = "bootstrap.json"
CURRENT_NAME = "CURRENT"
GENERATIONS_NAME = "generations"
DEFAULT_KEY_ID = "archhub.unified.bootstrap"


@dataclass(frozen=True, slots=True)
class AuthorityLocation:
    root: Path
    generation_root: Path
    database_path: Path
    manifest_path: Path
    authority: UnifiedAuthority


def default_runtime_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise InvalidCell("LOCALAPPDATA is unavailable")
    declared = os.environ.get('ARCHHUB_TEST_STATE_DIR')
    state = Path(declared) if declared else Path(local) / 'ArchHub'
    return state / 'unified-authority'


def _canonical_root(path: str | os.PathLike[str]) -> Path:
    root = Path(path).expanduser().resolve()
    if root == root.anchor or root.parent == root:
        raise InvalidCell("unified authority runtime root is unsafe")
    return root


def _generation_id(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = str(uuid.UUID(candidate))
    except (ValueError, AttributeError) as exc:
        raise InvalidCell("authority generation pointer is invalid") from exc
    if parsed != candidate:
        raise InvalidCell("authority generation pointer is not canonical")
    return candidate


def _generation_paths(root: Path, generation_id: str) -> tuple[Path, Path, Path]:
    generations = (root / GENERATIONS_NAME).resolve()
    generation = (generations / _generation_id(generation_id)).resolve()
    if generation.parent != generations:
        raise InvalidCell("authority generation escapes its runtime root")
    return generation, generation / DATABASE_NAME, generation / MANIFEST_NAME


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class _AcceptedSnapshotProof:
    """Cache verified prefix digests; any changed row fingerprint re-verifies."""

    def __init__(self, generation: Path) -> None:
        self._path = generation / "accepted-proof.json"

    # v2 chains appended revisions; legacy bare digests remain verifiable.
    @staticmethod
    def _content(store, revision: int, like):
        if like is not None and like.split(":")[-1].startswith("v2-"):
            rows, newest, content = store.chained_prefix_fingerprint(revision)
            return rows, newest, "v2-" + content
        if like is not None:
            rows, newest, content = store.accepted_prefix_fingerprint(revision)
            return rows, newest, content
        rows, newest, content = store.chained_prefix_fingerprint(revision)
        return rows, newest, "v2-" + content
    def _recorded(self, key: str):
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = held.get(key)
        return value if type(value) is str else None
    def fingerprint(self, store, accepted_revision: int) -> str:
        self._archived_accepted = store.archived_snapshot_proof(accepted_revision)
        if self._archived_accepted is not None:
            return self._archived_accepted[0]
        rows, newest, content = self._content(
            store, accepted_revision, self._recorded("fingerprint")
        )
        return "%d:%d:%d:%s" % (accepted_revision, rows, newest, content)

    def proven(self, fingerprint: str, digest: str) -> bool:
        if getattr(self, '_archived_accepted', None) == (fingerprint, digest):
            return True
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (
            held.get("fingerprint") == fingerprint
            and held.get("digest") == digest
        )

    def head_fingerprint(self, store, revision: int) -> str | None:
        rows, newest, content = self._content(store, revision, None)
        if rows == 0:
            return None
        return "head:%d:%d:%d:%s" % (revision, rows, newest, content)

    def head_proven(self, fingerprint: str) -> bool:
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return held.get("head") == fingerprint

    def record_head(self, fingerprint: str) -> None:
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            held = {}
        held["head"] = fingerprint
        try:
            self._path.write_text(json.dumps(held), encoding="utf-8")
        except OSError:
            pass

    def head_floor_revision(self, store) -> int | None:
        """Reuse an audited head only while its full prefix fingerprint matches."""
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        recorded = held.get("head")
        if type(recorded) is not str:
            return None
        parts = recorded.split(":")
        if len(parts) != 5 or parts[0] != "head":
            return None
        try:
            revision = int(parts[1])
        except ValueError:
            return None
        rows, newest, content = self._content(store, revision, recorded)
        if recorded != "head:%d:%d:%d:%s" % (revision, rows, newest, content):
            return None
        return revision

    def record(self, fingerprint: str, digest: str) -> None:
        try:
            try:
                held = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            held.update({"fingerprint": fingerprint, "digest": digest})
            self._path.write_text(json.dumps(held), encoding="utf-8")
        except OSError:
            pass


def _open_generation(
    root: Path,
    generation_id: str,
    key_provider: SigningKeyProvider,
) -> AuthorityLocation:
    generation, database, manifest_path = _generation_paths(root, generation_id)
    if not generation.is_dir() or not database.is_file() or not manifest_path.is_file():
        raise InvalidCell("selected authority generation is incomplete")
    try:
        manifest = BootstrapManifest.from_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError) as exc:
        raise InvalidCell("selected bootstrap manifest is unreadable") from exc
    if manifest.graph_id != generation_id:
        raise InvalidCell("generation folder and signed graph identity differ")
    import time as _time
    _t0 = _time.perf_counter()
    store = CellStore(database)
    _t1 = _time.perf_counter()
    try:
        authority = open_unified_authority(
            store,
            manifest,
            key_provider,
            accepted_proof=_AcceptedSnapshotProof(generation),
        )
    except Exception:
        store.close()
        raise
    _t2 = _time.perf_counter()
    # What an open actually costs, phase by phase, beside the boot log the
    # owner keeps: the store load (rows -> cells) and the authority open
    # (accepted proof, head audit, accumulator seed). Measured, so the
    # next cut is aimed at a number rather than a guess.
    try:
        with (root / "boot-timing.log").open("a", encoding="utf-8") as log:
            log.write(
                "%s  open phases: store load %.1fs  authority open %.1fs  "
                "(cells=%d rev=%s head=%s)" % (
                    _time.strftime("%Y-%m-%d %H:%M:%S"), _t1 - _t0, _t2 - _t1,
                    len(store.snapshot().cells), store.revision,
                    type(store.snapshot().cells).__name__,
                ) + chr(10)
            )
    except OSError:
        pass
    return AuthorityLocation(root, generation, database, manifest_path, authority)


def open_current_authority(
    root: str | os.PathLike[str],
    key_provider: SigningKeyProvider,
) -> AuthorityLocation:
    runtime_root = _canonical_root(root)
    current = runtime_root / CURRENT_NAME
    try:
        generation_id = _generation_id(current.read_text(encoding="ascii"))
    except FileNotFoundError as exc:
        raise InvalidCell("unified authority has no selected generation") from exc
    except (OSError, UnicodeError) as exc:
        raise InvalidCell("unified authority pointer is unreadable") from exc
    return _open_generation(runtime_root, generation_id, key_provider)


def authority_generation_census(location: AuthorityLocation) -> dict[str, object]:
    """Offline SQL census, without materializing the current or historical graph.

    Cells have no physical kind column. Role incidences and declared shapes are
    graph-derived categories; atom shapes cover all physical current Cells.
    This intentionally expensive diagnostic is never called by boot.
    """
    connection = sqlite3.connect(location.database_path.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")
        atom_shapes = dict(connection.execute(
            "SELECT CASE WHEN length(atom) = 0 THEN 'empty' ELSE 'payload' END, "
            "COUNT(*) FROM current_cells GROUP BY 1"
        ))
        roles = {root: name for name, root in location.authority.roles.items()}
        placeholders = ",".join("?" for _ in roles)
        role_counts = {
            roles[root]: count for root, count in connection.execute(
                "SELECT link0, COUNT(*) FROM current_cells WHERE link0 IN ("
                + placeholders + ") GROUP BY link0", tuple(roles),
            )
        }
        shapes = {root: name for name, root in location.authority.shapes.items()}
        shape_counts = {
            shapes.get(root, root): count for root, count in connection.execute(
                "SELECT link1, COUNT(*) FROM current_cells WHERE link0 = ? GROUP BY link1",
                (location.authority.role("conforms-to"),),
            )
        }
        return {
            "cell_count": sum(atom_shapes.values()),
            "version_cell_count": connection.execute("SELECT COUNT(*) FROM cell_versions").fetchone()[0],
            "revision_count": connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0],
            "page_count": connection.execute("PRAGMA page_count").fetchone()[0],
            "free_pages": connection.execute("PRAGMA freelist_count").fetchone()[0],
            "atom_shapes": atom_shapes, "role_counts": role_counts, "shape_counts": shape_counts,
        }
    finally:
        connection.close()


def vacuum_authority_fixture(
    source_root: str | os.PathLike[str],
    destination_root: str | os.PathLike[str],
    key_provider: SigningKeyProvider,
) -> AuthorityLocation:
    """Verify/select a compacted *offline fixture copy*, preserving all history.

    The empty destination is a new physical runtime with the same signed graph
    UUID, not a new graph. No source selection or data is rewritten. Proof and
    accelerator sidecars are regenerated: VACUUM may renumber implicit rowids.
    This is explicit maintenance only, never part of opening the application.
    """
    source, destination = _canonical_root(source_root), _canonical_root(destination_root)
    if source == destination or source in destination.parents or destination in source.parents:
        raise InvalidCell("fixture source and destination must be disjoint")
    live = default_runtime_root().resolve()
    if any(path == live or live in path.parents or path in live.parents for path in (source, destination)):
        raise InvalidCell("fixture maintenance refuses the live runtime")
    if destination.exists():
        raise InvalidCell("fixture destination must not already exist")
    # Serialize CURRENT with existing provisioning and refuse a running source
    # CellStore. Both fences are released on every interrupted maintenance path.
    provisioning_fence = InterprocessOwnerFence(str(source / ".provision"))
    try:
        generation_id = _generation_id((source / CURRENT_NAME).read_text(encoding="ascii"))
        _generation, database, manifest_path = _generation_paths(source, generation_id)
        source_fence = InterprocessOwnerFence(str(database))
        try:
            manifest_text = manifest_path.read_text(encoding="utf-8")
            manifest = BootstrapManifest.from_json(manifest_text)
            if manifest.graph_id != generation_id:
                raise InvalidCell("generation folder and signed graph identity differ")
            destination.mkdir(parents=True, exist_ok=False)
            generation, copied_database, copied_manifest = _generation_paths(destination, generation_id)
            generation.mkdir(parents=True, exist_ok=False)
            connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            try:
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("VACUUM INTO ?", (str(copied_database),))
            finally:
                connection.close()
            _atomic_text(copied_manifest, manifest_text)
            verified = _open_generation(destination, generation_id, key_provider)
            try:
                _atomic_text(destination / CURRENT_NAME, generation_id)
            except Exception:
                verified.authority.store.close()
                raise
            return verified
        finally:
            source_fence.close()
    finally:
        provisioning_fence.close()


def _complete_unselected_generations(
    root: Path,
    key_provider: SigningKeyProvider,
) -> tuple[AuthorityLocation, ...]:
    generations = root / GENERATIONS_NAME
    if not generations.exists():
        return ()
    found: list[AuthorityLocation] = []
    for candidate in sorted(generations.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or candidate.name.startswith("."):
            continue
        try:
            found.append(_open_generation(root, candidate.name, key_provider))
        except InvalidCell:
            continue
    return tuple(found)


def _provision_unified_authority_locked(
    root: str | os.PathLike[str],
    key_provider: SigningKeyProvider,
    *,
    key_id: str,
    application_label: str,
    principal_label: str,
    bootstrap_session_label: str,
    bootstrap_session_public_key: bytes,
    composition_labels: Iterable[str],
    replace_invalid_current: str | None = None,
    initialize: Callable[[UnifiedAuthority], None] | None = None,
) -> AuthorityLocation:
    """Select an existing valid generation or atomically create one complete generation."""
    runtime_root = _canonical_root(root)
    current = runtime_root / CURRENT_NAME
    if current.exists():
        try:
            selected = open_current_authority(runtime_root, key_provider)
            if initialize is not None:
                try:
                    initialize(selected.authority)
                except Exception:
                    selected.authority.store.close()
                    raise
            return selected
        except InvalidCell:
            if replace_invalid_current is None:
                raise
            try:
                selected = _generation_id(current.read_text(encoding="ascii"))
            except (OSError, UnicodeError) as exc:
                raise InvalidCell("invalid current generation cannot be identified") from exc
            if selected != _generation_id(replace_invalid_current):
                raise InvalidCell("invalid current generation changed before replacement")
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / GENERATIONS_NAME).mkdir(parents=True, exist_ok=True)

    recovered = _complete_unselected_generations(runtime_root, key_provider)
    if len(recovered) > 1:
        for location in recovered:
            location.authority.store.close()
        raise InvalidCell("multiple complete unselected authority generations require adjudication")
    if len(recovered) == 1:
        location = recovered[0]
        if initialize is not None:
            try:
                initialize(location.authority)
            except Exception:
                location.authority.store.close()
                raise
        _atomic_text(current, location.authority.manifest.graph_id)
        return location

    staging = (
        runtime_root
        / GENERATIONS_NAME
        / (".staging-" + uuid.uuid4().hex)
    ).resolve()
    if staging.parent != (runtime_root / GENERATIONS_NAME).resolve():
        raise InvalidCell("authority staging path escapes its runtime root")
    staging.mkdir(parents=False, exist_ok=False)
    database = staging / DATABASE_NAME
    manifest_path = staging / MANIFEST_NAME
    store = CellStore(database)
    try:
        authority = create_unified_authority(
            store,
            key_provider,
            key_id=key_id,
            application_label=application_label,
            principal_label=principal_label,
            bootstrap_session_label=bootstrap_session_label,
            bootstrap_session_public_key=bootstrap_session_public_key,
            composition_labels=composition_labels,
        )
        if initialize is not None:
            initialize(authority)
        manifest_text = authority.manifest.to_json()
        _atomic_text(manifest_path, manifest_text)
        generation_id = authority.manifest.graph_id
    finally:
        store.close()

    verification_store = CellStore(database)
    try:
        verified = open_unified_authority(
            verification_store,
            BootstrapManifest.from_json(manifest_text),
            key_provider,
        )
        if verified.manifest.graph_id != generation_id:
            raise InvalidCell("staged authority verification changed graph identity")
    finally:
        verification_store.close()

    final, _, _ = _generation_paths(runtime_root, generation_id)
    if final.exists():
        raise InvalidCell("authority generation identity already exists")
    os.replace(staging, final)
    _atomic_text(current, generation_id)
    return open_current_authority(runtime_root, key_provider)


def provision_unified_authority(
    root: str | os.PathLike[str],
    key_provider: SigningKeyProvider,
    *,
    key_id: str,
    application_label: str,
    principal_label: str,
    bootstrap_session_label: str,
    bootstrap_session_public_key: bytes,
    composition_labels: Iterable[str],
    replace_invalid_current: str | None = None,
    initialize: Callable[[UnifiedAuthority], None] | None = None,
) -> AuthorityLocation:
    """Serialize first provisioning so concurrent callers cannot mint two roots."""
    runtime_root = _canonical_root(root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 30.0
    fence: InterprocessOwnerFence | None = None
    while fence is None:
        try:
            fence = InterprocessOwnerFence(str(runtime_root / ".provision"))
        except DatabaseOwnerConflict:
            if time.monotonic() >= deadline:
                raise InvalidCell("unified authority provisioning fence timed out")
            time.sleep(0.02)
    try:
        return _provision_unified_authority_locked(
            runtime_root,
            key_provider,
            key_id=key_id,
            application_label=application_label,
            principal_label=principal_label,
            bootstrap_session_label=bootstrap_session_label,
            bootstrap_session_public_key=bootstrap_session_public_key,
            composition_labels=composition_labels,
            replace_invalid_current=replace_invalid_current,
            initialize=initialize,
        )
    finally:
        fence.close()


def _status(location: AuthorityLocation) -> dict[str, object]:
    manifest = location.authority.manifest
    return {
        "ok": True,
        "graph_id": manifest.graph_id,
        "revision": location.authority.store.revision,
        "cell_count": len(location.authority.store.snapshot().cells),
        "database": str(location.database_path),
        "manifest": str(location.manifest_path),
        "accepted_snapshot_digest": manifest.accepted_snapshot_digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision or verify one unified authority")
    parser.add_argument(
        "command", choices=("provision", "verify"), help="requested physical action"
    )
    parser.add_argument("--root", default=str(default_runtime_root()))
    parser.add_argument("--key-id", default=DEFAULT_KEY_ID)
    parser.add_argument("--application-label", default="ArchHub")
    parser.add_argument("--principal-label", default="Founder")
    parser.add_argument("--session-label", default="Bootstrap session")
    parser.add_argument(
        "--session-public-key",
        help="base64 Ed25519 public key for the bootstrap session",
    )
    parser.add_argument("--composition", action="append", default=[])
    parser.add_argument(
        "--replace-invalid-current",
        help="exact currently selected graph id permitted to be superseded",
    )
    args = parser.parse_args(argv)
    provider = WindowsDpapiSigningKeyProvider(
        WindowsDpapiSigningKeyProvider.default_path()
    )
    if args.command == "provision":
        if not args.composition:
            parser.error("provision requires at least one --composition")
        if not args.session_public_key:
            parser.error("provision requires --session-public-key")
        try:
            session_public_key = base64.b64decode(
                args.session_public_key, validate=True
            )
        except ValueError:
            parser.error("--session-public-key is not valid base64")
        location = provision_unified_authority(
            args.root,
            provider,
            key_id=args.key_id,
            application_label=args.application_label,
            principal_label=args.principal_label,
            bootstrap_session_label=args.session_label,
            bootstrap_session_public_key=session_public_key,
            composition_labels=args.composition,
            replace_invalid_current=args.replace_invalid_current,
        )
    else:
        location = open_current_authority(args.root, provider)
    try:
        print(json.dumps(_status(location), sort_keys=True))
    finally:
        location.authority.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuthorityLocation",
    "authority_generation_census",
    "default_runtime_root",
    "open_current_authority",
    "provision_unified_authority",
    "vacuum_authority_fixture",
]
