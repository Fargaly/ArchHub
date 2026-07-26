"""Signed external revision checkpoints for the durable Cell journal.

This detects database rollback or same-revision tampering while the checkpoint
file and signing-key custody remain intact. It is not a remote transparency log
and cannot detect coordinated rollback of every local copy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
import secrets
import threading
from typing import Mapping
import uuid

from .cell_secret_keys import SigningKeyProvider
from .cell_signing_authority import (
    SigningAuthorityProtocol,
    SigningAuthorityProvider,
    sign_statement,
    verify_signing_key_descriptor,
    verify_signature_envelope,
)
from .universal_cell import CellStore, Snapshot


class RevisionCheckpointDenied(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RevisionCheckpointSigningAuthority:
    """A separate universal-Cell authority graph and non-exporting signer."""

    store: CellStore
    protocol: SigningAuthorityProtocol
    provider: SigningAuthorityProvider
    descriptor_root: str
    authorization_evidence: str


def _field(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def snapshot_digest(snapshot: Snapshot) -> str:
    """Commit to one complete immutable Cell snapshot deterministically."""
    digest = hashlib.sha256()
    _field(digest, b"ArchHub/universal-cell-snapshot/v1")
    _field(digest, str(snapshot.revision).encode("ascii"))
    for root_id in sorted(snapshot.cells):
        cell = snapshot.cells[root_id]
        _field(digest, cell.id.encode("utf-8"))
        _field(digest, cell.link0.encode("utf-8"))
        _field(digest, cell.link1.encode("utf-8"))
        _field(digest, cell.atom)
    return digest.hexdigest()


def _canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


class RevisionCheckpointGuard:
    FORMAT = "archhub.universal-revision-checkpoint"
    LEGACY_VERSION = 1
    VERSION = 2
    STATEMENT_PROTOCOL = "application/vnd.archhub.revision-checkpoint.v2"
    STATEMENT_CONTEXT = "universal-revision-checkpoint"
    SIGNING_PURPOSE = "universal-revision-checkpoint"

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        database_identity: str,
        key_provider: SigningKeyProvider | None = None,
        key_id: str = "archhub.local.universal-checkpoint",
        signing_authority: RevisionCheckpointSigningAuthority | None = None,
    ) -> None:
        if key_provider is None and signing_authority is None:
            raise ValueError("revision checkpoint requires a signing authority")
        self.path = Path(path).expanduser().resolve()
        self.database_identity = hashlib.sha256(
            str(database_identity).casefold().encode("utf-8")
        ).hexdigest()
        self._key_provider = key_provider
        self._key_id = key_id
        self._signing_authority = signing_authority
        self._lock = threading.RLock()
        self._initialized = False
        self._fault: str | None = None
        self._unsubscribe = None

    @staticmethod
    def default_path(database_path: str | os.PathLike[str]) -> Path:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise RevisionCheckpointDenied("LOCALAPPDATA is unavailable")
        identity = hashlib.sha256(
            str(Path(database_path).expanduser().resolve()).casefold().encode("utf-8")
        ).hexdigest()
        return Path(local) / "ArchHub" / "checkpoints" / (identity + ".json")

    def _read(self) -> dict[str, object] | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RevisionCheckpointDenied("revision checkpoint is unreadable") from exc
        legacy = {
            "format", "format_version", "database", "revision", "digest",
            "issued_at", "key_reference", "key_version", "signature",
        }
        current = {
            "format", "format_version", "database", "revision", "digest",
            "issued_at", "envelope_root",
        }
        if (
            not isinstance(value, dict)
            or set(value) not in (legacy, current)
            or value.get("format_version") not in (
                self.LEGACY_VERSION, self.VERSION
            )
        ):
            raise RevisionCheckpointDenied("revision checkpoint shape is invalid")
        return value

    def _verify_record(self, value: Mapping[str, object]) -> tuple[int, str]:
        if (
            value.get("format") != self.FORMAT
            or value.get("database") != self.database_identity
        ):
            raise RevisionCheckpointDenied("revision checkpoint identity is invalid")
        if value.get("format_version") == self.LEGACY_VERSION:
            return self._verify_legacy_record(value)
        if value.get("format_version") == self.VERSION:
            return self._verify_current_record(value)
        raise RevisionCheckpointDenied("revision checkpoint version is unsupported")

    def _verify_legacy_record(
        self, value: Mapping[str, object]
    ) -> tuple[int, str]:
        if self._key_provider is None:
            raise RevisionCheckpointDenied(
                "legacy revision checkpoint verifier is unavailable"
            )
        try:
            revision = int(value["revision"])
            key_version = int(value["key_version"])
            key_reference = str(value["key_reference"])
            signature = str(value["signature"])
            committed_digest = str(value["digest"])
            unsigned = {key: item for key, item in value.items() if key != "signature"}
        except Exception as exc:
            raise RevisionCheckpointDenied(
                "revision checkpoint signing key is unavailable"
            ) from exc
        if not self._key_provider.verify(
            key_reference,
            key_version,
            _canonical(unsigned),
            signature,
        ):
            raise RevisionCheckpointDenied("revision checkpoint signature is invalid")
        if revision < 0 or len(committed_digest) != 64:
            raise RevisionCheckpointDenied("revision checkpoint values are invalid")
        return revision, committed_digest

    def _verify_current_record(
        self, value: Mapping[str, object]
    ) -> tuple[int, str]:
        authority = self._signing_authority
        if authority is None:
            raise RevisionCheckpointDenied(
                "v2 revision checkpoint authority is unavailable"
            )
        try:
            revision = int(value["revision"])
            committed_digest = str(value["digest"])
            issued_at = str(value["issued_at"])
            envelope_root = str(value["envelope_root"])
            datetime.fromisoformat(issued_at[:-1] + "+00:00")
        except Exception as exc:
            raise RevisionCheckpointDenied(
                "v2 revision checkpoint values are invalid"
            ) from exc
        if (
            revision < 0
            or len(committed_digest) != 64
            or not issued_at.endswith("Z")
            or not envelope_root
        ):
            raise RevisionCheckpointDenied(
                "v2 revision checkpoint values are invalid"
            )
        try:
            descriptor = verify_signing_key_descriptor(
                authority.store.snapshot(),
                authority.protocol,
                authority.provider,
                authority.descriptor_root,
            )
            if descriptor.values["purpose"] != self.SIGNING_PURPOSE:
                raise RevisionCheckpointDenied(
                    "v2 revision checkpoint signing purpose is invalid"
                )
            envelope = verify_signature_envelope(
                authority.store.snapshot(),
                authority.protocol,
                authority.provider,
                envelope_root,
                payload=_canonical(value),
                expected_statement_protocol=self.STATEMENT_PROTOCOL,
                expected_context=self.STATEMENT_CONTEXT,
            )
            if envelope.values["key-descriptor"] != authority.descriptor_root:
                raise RevisionCheckpointDenied(
                    "v2 revision checkpoint signing descriptor is invalid"
                )
        except Exception as exc:
            raise RevisionCheckpointDenied(
                "v2 revision checkpoint signature is invalid"
            ) from exc
        return revision, committed_digest

    def _write_legacy(self, store: CellStore, snapshot: Snapshot) -> bytes:
        if self._key_provider is None:
            raise RevisionCheckpointDenied(
                "legacy revision checkpoint signer is unavailable"
            )
        material = self._key_provider.current_reference(self._key_id)
        unsigned = {
            "format": self.FORMAT,
            "format_version": self.LEGACY_VERSION,
            "database": self.database_identity,
            "revision": snapshot.revision,
            "digest": store.revision_chain_digest(snapshot.revision),
            "issued_at": time.time_ns(),
            "key_reference": material.key_id,
            "key_version": material.version,
        }
        value = {
            **unsigned,
            "signature": self._key_provider.sign(
                material.key_id,
                material.version,
                _canonical(unsigned),
            ),
        }
        return _canonical(value)

    def _write_current(self, store: CellStore, snapshot: Snapshot) -> bytes:
        authority = self._signing_authority
        if authority is None:
            raise RevisionCheckpointDenied(
                "v2 revision checkpoint signer is unavailable"
            )
        if authority.store is store:
            raise RevisionCheckpointDenied(
                "revision checkpoint authority must use a separate Cell store"
            )
        descriptor = verify_signing_key_descriptor(
            authority.store.snapshot(),
            authority.protocol,
            authority.provider,
            authority.descriptor_root,
            require_signing=True,
        )
        if descriptor.values["purpose"] != self.SIGNING_PURPOSE:
            raise RevisionCheckpointDenied(
                "v2 revision checkpoint signing purpose is invalid"
            )
        issued_at = datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        envelope_root = "%s:checkpoint:%s:%s" % (
            authority.descriptor_root,
            snapshot.revision,
            uuid.uuid4(),
        )
        unsigned = {
            "format": self.FORMAT,
            "format_version": self.VERSION,
            "database": self.database_identity,
            "revision": snapshot.revision,
            "digest": store.revision_chain_digest(snapshot.revision),
            "issued_at": issued_at,
            "envelope_root": envelope_root,
        }
        sign_statement(
            authority.store,
            authority.protocol,
            authority.provider,
            authority.descriptor_root,
            envelope_id=envelope_root,
            statement_protocol=self.STATEMENT_PROTOCOL,
            context=self.STATEMENT_CONTEXT,
            payload=_canonical(unsigned),
            authorization_evidence=authority.authorization_evidence,
            issued_at=issued_at,
        )
        return _canonical(unsigned)

    def _write(self, store: CellStore, snapshot: Snapshot) -> None:
        encoded = (
            self._write_current(store, snapshot)
            if self._signing_authority is not None
            else self._write_legacy(store, snapshot)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            ".%s.%s.tmp" % (self.path.name, secrets.token_hex(8))
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def verify_or_initialize(self, store: CellStore) -> None:
        with self._lock:
            record = self._read()
            current = store.snapshot()
            if record is None:
                if self._initialized:
                    raise RevisionCheckpointDenied(
                        "revision checkpoint disappeared after initialization"
                    )
                self._write(store, current)
                self._initialized = True
                self._fault = None
                return
            anchored_revision, _anchored_digest = self._verify_trusted_prefix(
                store, record, current
            )
            if current.revision > anchored_revision:
                self._write(store, current)
            self._initialized = True
            self._fault = None

    def _verify_trusted_prefix(
        self,
        store: CellStore,
        record: Mapping[str, object],
        current: Snapshot,
    ) -> tuple[int, str]:
        anchored_revision, anchored_digest = self._verify_record(record)
        if anchored_revision > current.revision:
            raise RevisionCheckpointDenied(
                "durable Cell database was rolled back behind its checkpoint"
            )
        try:
            store.at(anchored_revision)
        except Exception as exc:
            raise RevisionCheckpointDenied(
                "checkpointed Cell revision is missing"
            ) from exc
        if not hmac.compare_digest(
            store.revision_chain_digest(anchored_revision), anchored_digest
        ):
            raise RevisionCheckpointDenied(
                "checkpointed Cell revision digest does not match"
            )
        return anchored_revision, anchored_digest

    def verify_trusted_prefix(self, store: CellStore) -> None:
        """Verify the persisted anchor without signing a newer graph head."""
        with self._lock:
            record = self._read()
            if record is None:
                raise RevisionCheckpointDenied(
                    "persisted Cell database has no revision checkpoint"
                )
            self._verify_trusted_prefix(store, record, store.snapshot())
            self._fault = None

    def bind(self, store: CellStore) -> None:
        with self._lock:
            if self._unsubscribe is not None:
                raise RevisionCheckpointDenied("revision checkpoint is already bound")
            self.verify_or_initialize(store)

            def committed(_event) -> None:
                try:
                    self.verify_or_initialize(store)
                except Exception as exc:
                    with self._lock:
                        self._fault = "%s: %s" % (type(exc).__name__, exc)

            self._unsubscribe = store.subscribe(committed)

    def require_healthy(self) -> None:
        with self._lock:
            if not self._initialized:
                raise RevisionCheckpointDenied("revision checkpoint is not initialized")
            if self._fault is not None:
                raise RevisionCheckpointDenied(
                    "revision checkpoint is unhealthy: " + self._fault
                )

    def close(self) -> None:
        with self._lock:
            unsubscribe = self._unsubscribe
            self._unsubscribe = None
        if unsubscribe is not None:
            unsubscribe()


__all__ = [
    "RevisionCheckpointDenied",
    "RevisionCheckpointGuard",
    "RevisionCheckpointSigningAuthority",
    "snapshot_digest",
]
