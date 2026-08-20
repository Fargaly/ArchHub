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
    return Path(local) / "ArchHub" / "unified-authority"


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
    """Remember that this exact history already proved its bootstrap digest.

    Opening the authority rebuilt the accepted snapshot from every stored
    version and hashed all of it -- three hundred and fifty thousand cells
    on the founder's graph, minutes of work, on every single start, to
    re-confirm a fact about a revision that can never change.

    The store is append-only, so the accepted prefix is immutable: if the
    rows that compose it are the same rows, the digest is the same digest.
    The proof therefore records the digest together with a fingerprint of
    that prefix -- how many versions exist at or before the accepted
    revision, and the newest row among them. Any rewrite of history moves
    those numbers and the full verification runs again. Nothing is skipped
    on a graph that has changed underneath us.
    """

    def __init__(self, generation: Path) -> None:
        self._path = generation / "accepted-proof.json"

    # Proof strings carry which prefix formula made them: "v2-" marks the
    # chained digest (only the rows of the revisions since the last
    # recorded link are hashed); a bare digest is the v1 fold over every
    # row, kept verifiable so a proof recorded before the change still
    # stands once -- after which the chained form is recorded instead.
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
        rows, newest, content = self._content(
            store, accepted_revision, self._recorded("fingerprint")
        )
        return "%d:%d:%d:%s" % (accepted_revision, rows, newest, content)

    def proven(self, fingerprint: str, digest: str) -> bool:
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
        """The revision whose head this generation already audited whole.

        Re-auditing rebuilds one full snapshot per revision back to the
        beginning, so a graph that has been worked on pays its entire
        history again on every start to re-prove revisions it proved
        yesterday. The recorded head says which revision was audited over
        which append-only prefix; if that prefix still has the same row
        count and the same newest row, the audit below it still stands and
        the walk only has to cover what was appended since.
        """
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
                "(cells=%d rev=%s)" % (
                    _time.strftime("%Y-%m-%d %H:%M:%S"), _t1 - _t0, _t2 - _t1,
                    len(store.snapshot().cells), store.revision,
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
    "default_runtime_root",
    "open_current_authority",
    "provision_unified_authority",
]
