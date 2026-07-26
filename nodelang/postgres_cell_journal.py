"""PostgreSQL durability for the four-field Universal Cell authority.

The tables in this module are physical journal machinery only.  They retain
Cell versions and revision ordering; they do not assign semantic kinds, roles,
tenants, lifecycle states, permissions, or product meaning.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import re
import threading
from types import MappingProxyType
from typing import Callable, Iterable

from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    Conflict,
    DatabaseOwnerConflict,
    InvalidCell,
    _validate_cell,
)


_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RETRYABLE_SQLSTATES = frozenset(("23505", "40001", "40P01"))

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS archhub_cell_authorities (
        authority_id TEXT PRIMARY KEY,
        current_revision BIGINT NOT NULL CHECK (current_revision >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archhub_cell_revisions (
        authority_id TEXT NOT NULL,
        revision BIGINT NOT NULL CHECK (revision >= 0),
        committed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (authority_id, revision),
        FOREIGN KEY (authority_id)
            REFERENCES archhub_cell_authorities(authority_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archhub_cell_versions (
        authority_id TEXT NOT NULL,
        revision BIGINT NOT NULL,
        cell_id TEXT NOT NULL,
        link0 TEXT NOT NULL,
        link1 TEXT NOT NULL,
        atom BYTEA NOT NULL,
        PRIMARY KEY (authority_id, revision, cell_id),
        FOREIGN KEY (authority_id, revision)
            REFERENCES archhub_cell_revisions(authority_id, revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archhub_current_cells (
        authority_id TEXT NOT NULL,
        cell_id TEXT NOT NULL,
        revision BIGINT NOT NULL,
        link0 TEXT NOT NULL,
        link1 TEXT NOT NULL,
        atom BYTEA NOT NULL,
        PRIMARY KEY (authority_id, cell_id),
        FOREIGN KEY (authority_id, revision)
            REFERENCES archhub_cell_revisions(authority_id, revision)
    )
    """,
)


class PostgresAuthorityUnavailable(InvalidCell):
    """The admitted PostgreSQL physical authority cannot be reached."""


class _InjectedJournalFault(RuntimeError):
    """A deterministic court interruption, never a provider failure."""


def _validate_authority_id(authority_id: str) -> str:
    if not isinstance(authority_id, str) or not _AUTHORITY_ID.fullmatch(
        authority_id
    ):
        raise InvalidCell("PostgreSQL authority identifier is invalid")
    return authority_id


def postgres_authority_identity(authority_id: str) -> str:
    """Return a stable physical identity without including a DSN or secret."""
    admitted = _validate_authority_id(authority_id)
    digest = hashlib.sha256(
        ("ArchHub/postgresql-cell-authority/v1\n" + admitted).encode("utf-8")
    ).hexdigest()
    return "postgresql:sha256:" + digest


def _sqlstate(exc: BaseException) -> str | None:
    value = getattr(exc, "sqlstate", None)
    if isinstance(value, str):
        return value
    diagnostic = getattr(exc, "diag", None)
    value = getattr(diagnostic, "sqlstate", None)
    return value if isinstance(value, str) else None


class PostgresCellJournal:
    """Shared-writer PostgreSQL implementation of ``CellJournal``."""

    backend = "postgresql"
    local_path = None
    exclusive_owner = False
    shared_writers = True

    def __init__(
        self,
        dsn: str,
        *,
        authority_id: str,
        connection_factory=None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise InvalidCell("PostgreSQL Cell authority DSN is missing")
        self._authority_id = _validate_authority_id(authority_id)
        self.identity = postgres_authority_identity(self._authority_id)
        self._fault_injector = fault_injector
        self._connection = None
        self._connection_lock = threading.RLock()
        self._runtime_fences: set[int] = set()
        try:
            factory = connection_factory or self._default_connection_factory()
            self._connection = factory(dsn)
            self._ensure_schema()
            self._ensure_genesis()
        except (InvalidCell, Conflict):
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise PostgresAuthorityUnavailable(
                "PostgreSQL Cell authority connection failed (%s)"
                % type(exc).__name__
            ) from None

    @staticmethod
    def _default_connection_factory():
        try:
            import psycopg
        except ImportError:
            raise PostgresAuthorityUnavailable(
                "psycopg is required for PostgreSQL Cell authority"
            ) from None

        def connect(dsn: str):
            return psycopg.connect(
                dsn,
                autocommit=False,
                connect_timeout=10,
                application_name="archhub-universal-cell",
            )

        return connect

    def _fault(self, stage: str) -> None:
        if self._fault_injector is None:
            return
        try:
            self._fault_injector(stage)
        except Exception:
            raise _InjectedJournalFault(
                "injected PostgreSQL journal fault at " + stage
            ) from None

    @contextmanager
    def _transaction(self, isolation: str, *, read_only: bool = False):
        with self._connection_lock:
            cursor = self._connection.cursor()
            mode = " READ ONLY" if read_only else ""
            cursor.execute("BEGIN ISOLATION LEVEL " + isolation + mode)
            try:
                yield cursor
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()

    def _ensure_schema(self) -> None:
        with self._connection_lock:
            cursor = self._connection.cursor()
            try:
                for statement in _DDL:
                    cursor.execute(statement)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()

    def _ensure_genesis(self) -> None:
        null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
        with self._transaction("SERIALIZABLE") as cursor:
            cursor.execute(
                "INSERT INTO archhub_cell_authorities"
                "(authority_id, current_revision) VALUES(%s, 0) "
                "ON CONFLICT(authority_id) DO NOTHING",
                (self._authority_id,),
            )
            cursor.execute(
                "SELECT current_revision FROM archhub_cell_authorities "
                "WHERE authority_id=%s FOR UPDATE",
                (self._authority_id,),
            )
            head = cursor.fetchone()
            if head is None:
                raise InvalidCell("PostgreSQL Cell authority head is missing")
            cursor.execute(
                "SELECT COUNT(*), MIN(revision), MAX(revision) "
                "FROM archhub_cell_revisions WHERE authority_id=%s",
                (self._authority_id,),
            )
            count, first, latest = cursor.fetchone()
            if count == 0:
                cursor.execute(
                    "INSERT INTO archhub_cell_revisions"
                    "(authority_id, revision) VALUES(%s, 0)",
                    (self._authority_id,),
                )
                cursor.execute(
                    "INSERT INTO archhub_cell_versions"
                    "(authority_id, revision, cell_id, link0, link1, atom) "
                    "VALUES(%s, 0, %s, %s, %s, %s)",
                    (
                        self._authority_id,
                        null.id,
                        null.link0,
                        null.link1,
                        null.atom,
                    ),
                )
                cursor.execute(
                    "INSERT INTO archhub_current_cells"
                    "(authority_id, cell_id, revision, link0, link1, atom) "
                    "VALUES(%s, %s, 0, %s, %s, %s)",
                    (
                        self._authority_id,
                        null.id,
                        null.link0,
                        null.link1,
                        null.atom,
                    ),
                )
            elif (
                first != 0
                or latest != int(head[0])
                or count != int(latest) + 1
            ):
                raise InvalidCell(
                    "PostgreSQL Cell revision history is discontinuous"
                )

    def load(self):
        try:
            with self._transaction("REPEATABLE READ", read_only=True) as cursor:
                cursor.execute(
                    "SELECT current_revision FROM archhub_cell_authorities "
                    "WHERE authority_id=%s",
                    (self._authority_id,),
                )
                head = cursor.fetchone()
                if head is None:
                    raise InvalidCell(
                        "PostgreSQL Cell authority head is missing"
                    )
                latest = int(head[0])
                cursor.execute(
                    "SELECT revision FROM archhub_cell_revisions "
                    "WHERE authority_id=%s ORDER BY revision",
                    (self._authority_id,),
                )
                revisions = tuple(int(row[0]) for row in cursor.fetchall())
                if revisions != tuple(range(latest + 1)):
                    raise InvalidCell(
                        "PostgreSQL Cell revision history is discontinuous"
                    )
                cursor.execute(
                    "SELECT revision, cell_id, link0, link1, atom "
                    "FROM archhub_cell_versions WHERE authority_id=%s "
                    "ORDER BY revision, cell_id",
                    (self._authority_id,),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT cell_id, revision, link0, link1, atom "
                    "FROM archhub_current_cells WHERE authority_id=%s "
                    "ORDER BY cell_id",
                    (self._authority_id,),
                )
                indexed_rows = cursor.fetchall()
        except InvalidCell:
            raise
        except Exception as exc:
            raise PostgresAuthorityUnavailable(
                "PostgreSQL Cell authority read failed (%s)"
                % type(exc).__name__
            ) from None

        current: dict[str, Cell] = {}
        versions: dict[int, list[Cell]] = {
            revision: [] for revision in revisions
        }
        changes: dict[int, list[str]] = {
            revision: [] for revision in revisions
        }
        expected_index: dict[str, tuple[int, str, str, bytes]] = {}
        for revision, cell_id, link0, link1, atom in rows:
            cell = Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            _validate_cell(cell)
            revision = int(revision)
            versions[revision].append(cell)
            changes[revision].append(cell.id)
            expected_index[cell.id] = (
                revision,
                cell.link0,
                cell.link1,
                cell.atom,
            )
        if any(not versions[revision] for revision in revisions):
            raise InvalidCell("PostgreSQL Cell revision has no changed Cells")
        null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
        if versions.get(0) != [null]:
            raise InvalidCell("PostgreSQL Cell genesis revision is invalid")
        for revision in revisions:
            changed = versions[revision]
            for cell in changed:
                current[cell.id] = cell
            for cell in changed:
                if cell.link0 in current and cell.link1 in current:
                    continue
                raise InvalidCell(
                    "PostgreSQL revision %s has dangling incidence" % revision
                )
        indexed = {
            str(cell_id): (int(revision), str(link0), str(link1), bytes(atom))
            for cell_id, revision, link0, link1, atom in indexed_rows
        }
        if indexed != expected_index:
            raise InvalidCell("PostgreSQL current Cell index is inconsistent")
        return (
            MappingProxyType(current),
            latest,
            {
                revision: tuple(versions[revision])
                for revision in revisions
            },
            {
                revision: tuple(changes[revision])
                for revision in revisions
            },
        )

    def append(
        self,
        expected_revision: int,
        next_revision: int,
        changed: Iterable[Cell],
    ) -> None:
        changed = tuple(changed)
        if next_revision != expected_revision + 1:
            raise InvalidCell("PostgreSQL Cell revision increment is invalid")
        try:
            with self._transaction("SERIALIZABLE") as cursor:
                cursor.execute(
                    "SELECT current_revision FROM archhub_cell_authorities "
                    "WHERE authority_id=%s FOR UPDATE",
                    (self._authority_id,),
                )
                head = cursor.fetchone()
                if head is None:
                    raise InvalidCell(
                        "PostgreSQL Cell authority head is missing"
                    )
                durable_revision = int(head[0])
                if durable_revision != expected_revision:
                    raise Conflict(
                        "expected durable revision %s, current revision is %s"
                        % (expected_revision, durable_revision)
                    )
                cursor.execute(
                    "INSERT INTO archhub_cell_revisions"
                    "(authority_id, revision) VALUES(%s, %s)",
                    (self._authority_id, next_revision),
                )
                cursor.executemany(
                    "INSERT INTO archhub_cell_versions"
                    "(authority_id, revision, cell_id, link0, link1, atom) "
                    "VALUES(%s, %s, %s, %s, %s, %s)",
                    (
                        (
                            self._authority_id,
                            next_revision,
                            cell.id,
                            cell.link0,
                            cell.link1,
                            cell.atom,
                        )
                        for cell in changed
                    ),
                )
                cursor.executemany(
                    "INSERT INTO archhub_current_cells"
                    "(authority_id, cell_id, revision, link0, link1, atom) "
                    "VALUES(%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT(authority_id, cell_id) DO UPDATE SET "
                    "revision=EXCLUDED.revision, link0=EXCLUDED.link0, "
                    "link1=EXCLUDED.link1, atom=EXCLUDED.atom",
                    (
                        (
                            self._authority_id,
                            cell.id,
                            next_revision,
                            cell.link0,
                            cell.link1,
                            cell.atom,
                        )
                        for cell in changed
                    ),
                )
                cursor.execute(
                    "UPDATE archhub_cell_authorities SET current_revision=%s "
                    "WHERE authority_id=%s AND current_revision=%s",
                    (
                        next_revision,
                        self._authority_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise Conflict(
                        "PostgreSQL Cell authority head changed during commit"
                    )
                self._fault("before_commit")
            self._fault("after_commit")
        except (Conflict, InvalidCell, _InjectedJournalFault):
            raise
        except Exception as exc:
            if _sqlstate(exc) in _RETRYABLE_SQLSTATES:
                raise Conflict(
                    "PostgreSQL Cell transaction must be retried"
                ) from None
            raise PostgresAuthorityUnavailable(
                "PostgreSQL Cell authority append failed (%s)"
                % type(exc).__name__
            ) from None

    def backup_to(self, _destination) -> str:
        raise InvalidCell(
            "PostgreSQL authority recovery requires a provider restore drill"
        )

    def acquire_runtime_fence(self, resource_id: str):
        if not isinstance(resource_id, str) or not resource_id:
            raise InvalidCell("runtime fence resource identity is invalid")
        raw = (
            "ArchHub/postgresql-runtime-fence/v1\n"
            + self._authority_id
            + "\n"
            + resource_id
        ).encode("utf-8")
        lock_key = int.from_bytes(
            hashlib.blake2b(raw, digest_size=8).digest(),
            "big",
            signed=True,
        )
        try:
            with self._connection_lock:
                if lock_key in self._runtime_fences:
                    raise DatabaseOwnerConflict(
                        "PostgreSQL runtime fence is already held locally"
                    )
                cursor = self._connection.cursor()
                try:
                    cursor.execute(
                        "SELECT pg_try_advisory_lock(%s)",
                        (lock_key,),
                    )
                    row = cursor.fetchone()
                    self._connection.commit()
                except Exception:
                    self._connection.rollback()
                    raise
                finally:
                    cursor.close()
                if row is None or row[0] is not True:
                    raise DatabaseOwnerConflict(
                        "PostgreSQL authority already has an active runtime owner"
                    )
                self._runtime_fences.add(lock_key)
        except DatabaseOwnerConflict:
            raise
        except Exception as exc:
            raise PostgresAuthorityUnavailable(
                "PostgreSQL runtime fence acquisition failed (%s)"
                % type(exc).__name__
            ) from None
        released = False

        def release() -> None:
            nonlocal released
            with self._connection_lock:
                if released or self._connection is None:
                    return
                cursor = self._connection.cursor()
                try:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (lock_key,),
                    )
                    unlocked = cursor.fetchone()
                    self._connection.commit()
                except Exception as exc:
                    self._connection.rollback()
                    raise PostgresAuthorityUnavailable(
                        "PostgreSQL runtime fence release failed (%s)"
                        % type(exc).__name__
                    ) from None
                finally:
                    cursor.close()
                if unlocked is None or unlocked[0] is not True:
                    raise InvalidCell(
                        "PostgreSQL runtime fence release was not held"
                    )
                self._runtime_fences.discard(lock_key)
                released = True

        return release

    def close(self) -> None:
        with self._connection_lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None
                    self._runtime_fences.clear()


__all__ = [
    "PostgresAuthorityUnavailable",
    "PostgresCellJournal",
    "postgres_authority_identity",
]
