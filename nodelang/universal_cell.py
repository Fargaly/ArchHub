"""Uniform physical substrate for the universal-cell migration.

This module is intentionally parallel to ``nodelang.core``.  It contains no
product concepts and assigns no semantic meaning to atom bytes or link
position.  Higher-level protocols must be represented by connected Cells.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
from types import MappingProxyType
import threading
import time
from typing import Callable, Iterable, Iterator, Mapping, Protocol
import uuid


NULL_CELL_ID = "00000000-0000-0000-0000-000000000000"
_JOURNAL_REVISIONS_COLUMNS = frozenset(("revision", "committed_at"))
_JOURNAL_CELL_VERSION_COLUMNS = frozenset(
    ("revision", "cell_id", "link0", "link1", "atom")
)
_JOURNAL_CURRENT_CELL_COUNT_QUERY = "SELECT COUNT(*) FROM current_cells"


@dataclass(frozen=True, slots=True)
class Cell:
    """The only persisted semantic record in the V0 kernel."""

    id: str
    link0: str
    link1: str
    atom: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.atom, bytes):
            raise TypeError("terminal atom must be opaque bytes")


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Immutable process view of a committed cell graph."""

    revision: int
    cells: Mapping[str, Cell]


@dataclass(frozen=True, slots=True)
class ReadOnlyJournalRevision:
    """A bounded, non-owning view of one durable Cell journal revision.

    This record deliberately says nothing about graph semantics.  It exists
    for recovery preflights that must inspect a stopped journal without
    opening ``CellStore`` and therefore without acquiring its owner fence.
    """

    revision: int
    revision_count: int
    latest_revision_change_count: int


@dataclass(frozen=True, slots=True)
class RewriteResult:
    """Published identities from one generic structural rewrite."""

    root_id: str
    revision: int
    bindings: Mapping[str, str]
    materialized: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PreparedRewrite:
    """Unpublished Cells materialized from one generic structural rule."""

    root_id: str
    expected_revision: int
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]
    bindings: Mapping[str, str]
    materialized: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CommitEvent:
    """Post-commit notification; the graph revision is already durable."""

    revision: int
    touched: frozenset[str]


@dataclass(frozen=True, slots=True)
class CellHistoryMigrationEvidence:
    """Exact physical evidence for one quiesced journal migration."""

    source_identity: str
    destination_identity: str
    source_revision: int
    destination_revision: int
    revision_chain_digest: str


class CellKernelError(ValueError):
    """Base class for rejected physical-kernel operations."""


class Conflict(CellKernelError):
    """The caller attempted to commit against an obsolete revision."""


class InvalidCell(CellKernelError):
    """A cell or commit would violate the physical substrate invariants."""


class ReadOnlyJournalError(CellKernelError):
    """A durable journal cannot supply a bounded, read-only revision view."""


class NoMatch(CellKernelError):
    """A target graph does not have the supplied physical pattern shape."""


class MatchBudgetExceeded(CellKernelError):
    """Generic graph matching exhausted its explicit work budget."""


class DatabaseOwnerConflict(Conflict):
    """Another live CellStore already owns the durable database."""


class CellJournal(Protocol):
    """Storage-neutral physical journal below the four-field Cell floor."""

    identity: str
    backend: str
    local_path: str | None
    exclusive_owner: bool
    shared_writers: bool

    def load(
        self,
    ) -> tuple[
        Mapping[str, Cell],
        int,
        dict[int, tuple[Cell, ...]],
        dict[int, tuple[str, ...]],
    ]: ...

    def append(
        self,
        expected_revision: int,
        next_revision: int,
        changed: Iterable[Cell],
    ) -> None: ...

    def close(self) -> None: ...

    def backup_to(self, destination: str | os.PathLike[str]) -> str: ...

    def acquire_runtime_fence(
        self, resource_id: str
    ) -> Callable[[], None]: ...


def _frozen_cells(cells: Mapping[str, Cell]) -> Mapping[str, Cell]:
    return MappingProxyType(dict(cells))


_MAX_OVERLAY_DEPTH = 32


class _OverlayCellMap(Mapping[str, Cell]):
    """Immutable mapping overlay used to publish small commits cheaply."""

    __slots__ = ("_base", "_delta", "_created_count", "_depth")

    def __init__(self, base: Mapping[str, Cell], delta: Mapping[str, Cell]) -> None:
        self._base = base
        self._delta = MappingProxyType(dict(delta))
        self._created_count = sum(1 for key in self._delta if key not in base)
        self._depth = (
            base._depth + 1 if isinstance(base, _OverlayCellMap) else 1
        )

    def __getitem__(self, key: str) -> Cell:
        source: Mapping[str, Cell] = self
        while isinstance(source, _OverlayCellMap):
            try:
                return source._delta[key]
            except KeyError:
                source = source._base
        return source[key]

    def __iter__(self) -> Iterator[str]:
        layers: list[_OverlayCellMap] = []
        source: Mapping[str, Cell] = self
        while isinstance(source, _OverlayCellMap):
            layers.append(source)
            source = source._base
        yielded: set[str] = set()
        for key in source:
            yielded.add(key)
            yield key
        for layer in reversed(layers):
            for key in layer._delta:
                if key in yielded:
                    continue
                yielded.add(key)
                yield key

    def __len__(self) -> int:
        return len(self._base) + self._created_count

    def __contains__(self, key: object) -> bool:
        source: Mapping[str, Cell] = self
        while isinstance(source, _OverlayCellMap):
            if key in source._delta:
                return True
            source = source._base
        return key in source


def _compact_cell_map(cells: Mapping[str, Cell]) -> Mapping[str, Cell]:
    """Flatten overlays without changing any previously published snapshot."""
    layers: list[_OverlayCellMap] = []
    source = cells
    while isinstance(source, _OverlayCellMap):
        layers.append(source)
        source = source._base
    compacted = dict(source)
    for layer in reversed(layers):
        compacted.update(layer._delta)
    return MappingProxyType(compacted)


def dense_read_snapshot(snapshot: Snapshot) -> Snapshot:
    """Flatten an immutable overlay only for one dense interpreter read."""
    if type(snapshot) is not Snapshot:
        raise TypeError("dense read requires an exact Snapshot")
    if not isinstance(snapshot.cells, _OverlayCellMap):
        return snapshot
    return Snapshot(snapshot.revision, _compact_cell_map(snapshot.cells))


def overlay_read_snapshot(
    snapshot: Snapshot,
    *,
    create: Iterable[Cell] = (),
    replace: Iterable[Cell] = (),
) -> Snapshot:
    """Project one immutable candidate revision without copying its base graph."""
    if type(snapshot) is not Snapshot:
        raise TypeError("overlay read requires an exact Snapshot")
    created = tuple(create)
    replaced = tuple(replace)
    for cell in created + replaced:
        _validate_cell(cell)
    create_ids = tuple(cell.id for cell in created)
    replace_ids = tuple(cell.id for cell in replaced)
    if (
        len(create_ids) != len(set(create_ids))
        or len(replace_ids) != len(set(replace_ids))
        or any(cell_id in snapshot.cells for cell_id in create_ids)
        or any(cell_id not in snapshot.cells for cell_id in replace_ids)
        or set(create_ids).intersection(replace_ids)
    ):
        raise InvalidCell("candidate patch has invalid Cell identities")
    if not created and not replaced:
        return Snapshot(snapshot.revision + 1, snapshot.cells)
    delta = {cell.id: cell for cell in created + replaced}
    return Snapshot(
        snapshot.revision + 1,
        _OverlayCellMap(snapshot.cells, delta),
    )


def _validate_cell(cell: Cell) -> None:
    if type(cell) is not Cell:
        raise InvalidCell("every persisted semantic record must be a Cell")
    if not isinstance(cell.id, str) or not cell.id:
        raise InvalidCell("cell identity must be a non-empty string")
    if not isinstance(cell.link0, str) or not isinstance(cell.link1, str):
        raise InvalidCell("physical links must be cell identities")
    if not isinstance(cell.atom, bytes):
        raise InvalidCell("terminal atom must be opaque bytes")


class _DatabaseOwnerFence:
    """Process-fatal-safe exclusive ownership of one SQLite authority."""

    _process_guard = threading.Lock()
    _process_paths: set[str] = set()

    def __init__(self, database_path: str) -> None:
        self._database_path = os.path.normcase(
            os.path.realpath(os.path.abspath(database_path))
        )
        self._lock_path = self._database_path + ".owner.lock"
        self._stream = None
        self._released = False
        with self._process_guard:
            if self._database_path in self._process_paths:
                raise DatabaseOwnerConflict(
                    "Cell database already has an active owner: %s"
                    % self._database_path
                )
            self._process_paths.add(self._database_path)
        try:
            self._stream = open(self._lock_path, "a+b", buffering=0)
            self._ensure_lock_byte()
            self._acquire_os_lock()
        except Exception as exc:
            self._release_process_path()
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            if isinstance(exc, DatabaseOwnerConflict):
                raise
            raise DatabaseOwnerConflict(
                "Cell database already has an active owner: %s"
                % self._database_path
            ) from exc

    def _ensure_lock_byte(self) -> None:
        self._stream.seek(0, os.SEEK_END)
        if self._stream.tell() == 0:
            self._stream.write(b"\0")
        self._stream.seek(0)

    def _acquire_os_lock(self) -> None:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise DatabaseOwnerConflict(
                    "Cell database already has an active owner: %s"
                    % self._database_path
                ) from exc
            return
        import fcntl

        try:
            fcntl.flock(
                self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except OSError as exc:
            raise DatabaseOwnerConflict(
                "Cell database already has an active owner: %s"
                % self._database_path
            ) from exc

    def _release_process_path(self) -> None:
        with self._process_guard:
            self._process_paths.discard(self._database_path)

    def close(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            if self._stream is not None:
                if os.name == "nt":
                    import msvcrt

                    self._stream.seek(0)
                    msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._release_process_path()


class _SqliteJournal:
    """Durable implementation machinery; rows contain only Cell versions."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        fault_injector: Callable[[str], None] | None,
    ) -> None:
        self._path = os.path.abspath(os.fspath(path))
        self._fault_injector = fault_injector
        self._owner_fence = _DatabaseOwnerFence(self._path)
        self._connection = None
        try:
            self._connection = sqlite3.connect(
                self._path,
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS revisions ("
                "revision INTEGER PRIMARY KEY, committed_at REAL NOT NULL)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS cell_versions ("
                "revision INTEGER NOT NULL, cell_id TEXT NOT NULL, "
                "link0 TEXT NOT NULL, link1 TEXT NOT NULL, atom BLOB NOT NULL, "
                "PRIMARY KEY (revision, cell_id), "
                "FOREIGN KEY (revision) REFERENCES revisions(revision))"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS current_cells ("
                "cell_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
                "link0 TEXT NOT NULL, link1 TEXT NOT NULL, atom BLOB NOT NULL, "
                "FOREIGN KEY (revision) REFERENCES revisions(revision))"
            )
            count = self._connection.execute(
                "SELECT COUNT(*) FROM revisions"
            ).fetchone()[0]
            if count == 0:
                null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    self._connection.execute(
                        "INSERT INTO revisions(revision, committed_at) "
                        "VALUES(0, ?)",
                        (time.time(),),
                    )
                    self._insert_versions(0, (null,))
                    self._upsert_current(0, (null,))
                    self._connection.commit()
                except Exception:
                    self._connection.rollback()
                    raise
            elif self._connection.execute(
                _JOURNAL_CURRENT_CELL_COUNT_QUERY
            ).fetchone()[0] == 0:
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    self._connection.execute(
                        "INSERT INTO current_cells(cell_id, revision, link0, link1, atom) "
                        "SELECT versions.cell_id, versions.revision, versions.link0, "
                        "versions.link1, versions.atom FROM cell_versions AS versions JOIN ("
                        "SELECT cell_id, MAX(revision) AS revision FROM cell_versions "
                        "GROUP BY cell_id) AS selected ON selected.cell_id = versions.cell_id "
                        "AND selected.revision = versions.revision"
                    )
                    self._connection.commit()
                except Exception:
                    self._connection.rollback()
                    raise
        except Exception:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._owner_fence.close()
            raise

    def _fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)

    def _insert_versions(self, revision: int, cells: Iterable[Cell]) -> None:
        self._connection.executemany(
            "INSERT INTO cell_versions"
            "(revision, cell_id, link0, link1, atom) VALUES(?, ?, ?, ?, ?)",
            (
                (revision, cell.id, cell.link0, cell.link1, cell.atom)
                for cell in cells
            ),
        )

    def _upsert_current(self, revision: int, cells: Iterable[Cell]) -> None:
        self._connection.executemany(
            "INSERT INTO current_cells(cell_id, revision, link0, link1, atom) "
            "VALUES(?, ?, ?, ?, ?) ON CONFLICT(cell_id) DO UPDATE SET "
            "revision=excluded.revision, link0=excluded.link0, "
            "link1=excluded.link1, atom=excluded.atom",
            (
                (cell.id, revision, cell.link0, cell.link1, cell.atom)
                for cell in cells
            ),
        )

    def load(
        self,
    ) -> tuple[
        Mapping[str, Cell],
        int,
        dict[int, tuple[Cell, ...]],
        dict[int, tuple[str, ...]],
    ]:
        current: dict[str, Cell] = {}
        versions: dict[int, tuple[Cell, ...]] = {}
        changes: dict[int, tuple[str, ...]] = {}
        revisions = self._connection.execute(
            "SELECT revision FROM revisions ORDER BY revision"
        ).fetchall()
        for (revision,) in revisions:
            rows = self._connection.execute(
                "SELECT cell_id, link0, link1, atom FROM cell_versions "
                "WHERE revision=? ORDER BY cell_id",
                (revision,),
            ).fetchall()
            changed = []
            for cell_id, link0, link1, atom in rows:
                cell = Cell(cell_id, link0, link1, bytes(atom))
                _validate_cell(cell)
                current[cell_id] = cell
                changed.append(cell)
            changes[revision] = tuple(row[0] for row in rows)
            versions[revision] = tuple(changed)
            for cell in changed:
                if cell.link0 not in current or cell.link1 not in current:
                    raise InvalidCell(
                        "durable revision %s has dangling incidence" % revision
                    )
        if not versions:
            raise InvalidCell("durable Cell journal has no revisions")
        latest = max(versions)
        return MappingProxyType(current), latest, versions, changes

    def append(
        self,
        expected_revision: int,
        next_revision: int,
        changed: Iterable[Cell],
    ) -> None:
        changed = tuple(changed)
        committed = False
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT MAX(revision) FROM revisions"
            ).fetchone()
            durable_revision = int(row[0])
            if durable_revision != expected_revision:
                raise Conflict(
                    "expected durable revision %s, current revision is %s"
                    % (expected_revision, durable_revision)
                )
            self._connection.execute(
                "INSERT INTO revisions(revision, committed_at) VALUES(?, ?)",
                (next_revision, time.time()),
            )
            self._insert_versions(next_revision, changed)
            self._upsert_current(next_revision, changed)
            self._fault("before_commit")
            self._connection.commit()
            committed = True
            self._fault("after_commit")
        except Exception:
            if not committed:
                self._connection.rollback()
            raise

    def close(self) -> None:
        try:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
        finally:
            self._owner_fence.close()

    @property
    def path(self) -> str:
        return self._path

    @property
    def identity(self) -> str:
        canonical = os.path.normcase(self._path).encode("utf-8")
        return "sqlite:sha256:" + hashlib.sha256(canonical).hexdigest()

    @property
    def backend(self) -> str:
        return "sqlite"

    @property
    def local_path(self) -> str:
        return self._path

    @property
    def exclusive_owner(self) -> bool:
        return True

    @property
    def shared_writers(self) -> bool:
        return False

    def backup_to(self, destination: str | os.PathLike[str]) -> str:
        """Create one transactionally consistent online SQLite backup."""
        target = os.path.abspath(os.fspath(destination))
        if target == self._path:
            raise InvalidCell("Cell backup destination equals its source")
        if os.path.exists(target):
            raise InvalidCell("Cell backup destination already exists")
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        backup = sqlite3.connect(target, isolation_level=None)
        try:
            self._connection.backup(backup)
            integrity = backup.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise InvalidCell("Cell backup failed SQLite integrity check")
        finally:
            backup.close()
        return target

    def acquire_runtime_fence(
        self, resource_id: str
    ) -> Callable[[], None]:
        """SQLite's process owner fence already covers every graph resource."""
        if not isinstance(resource_id, str) or not resource_id:
            raise InvalidCell("runtime fence resource identity is invalid")

        def release() -> None:
            return None

        return release


def inspect_read_only_cell_journal(
    path: str | os.PathLike[str],
    *,
    max_revisions: int = 100_000,
    max_latest_revision_changes: int = 100_000,
) -> ReadOnlyJournalRevision:
    """Inspect one durable Cell revision without creating a CellStore owner.

    The SQLite connection is opened with ``mode=ro`` and ``query_only`` before
    a bounded read transaction.  This is intentionally a physical journal
    inspection, not a graph restore: callers receive only revision counts and
    cannot treat it as proof of Work, sessions, or authorization state.
    """
    if (
        type(max_revisions) is not int
        or max_revisions < 1
        or type(max_latest_revision_changes) is not int
        or max_latest_revision_changes < 1
    ):
        raise ReadOnlyJournalError("read-only journal inspection budget is invalid")
    connection = None
    try:
        database = Path(path).expanduser().resolve(strict=True)
        if not database.is_file():
            raise ReadOnlyJournalError("read-only journal path is not a file")
        connection = sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        revisions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(revisions)")
        }
        cell_versions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(cell_versions)")
        }
        if revisions_columns != _JOURNAL_REVISIONS_COLUMNS or (
            cell_versions_columns != _JOURNAL_CELL_VERSION_COLUMNS
        ):
            raise ReadOnlyJournalError("read-only journal schema is unsupported")
        count, first_revision, latest_revision = connection.execute(
            "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revisions"
        ).fetchone()
        if type(count) is not int or count > max_revisions:
            raise ReadOnlyJournalError(
                "read-only journal revision history exceeds the inspection budget"
            )
        if (
            type(first_revision) is not int
            or type(latest_revision) is not int
            or count < 1
            or first_revision != 0
            or latest_revision != count - 1
        ):
            raise ReadOnlyJournalError("read-only journal revision history is invalid")
        null_count = connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision=0 AND cell_id=?",
            (NULL_CELL_ID,),
        ).fetchone()[0]
        latest_changes = connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision=?",
            (latest_revision,),
        ).fetchone()[0]
        if (
            type(latest_changes) is not int
            or latest_changes > max_latest_revision_changes
        ):
            raise ReadOnlyJournalError(
                "read-only journal latest revision exceeds the inspection budget"
            )
        if (
            type(null_count) is not int
            or null_count != 1
            or latest_changes < 1
        ):
            raise ReadOnlyJournalError("read-only journal Cell history is invalid")
        return ReadOnlyJournalRevision(
            revision=latest_revision,
            revision_count=count,
            latest_revision_change_count=latest_changes,
        )
    except ReadOnlyJournalError:
        raise
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        raise ReadOnlyJournalError("read-only journal inspection is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


def load_bounded_read_only_cell_snapshot(
    path: str | os.PathLike[str],
    *,
    max_revisions: int = 10_000,
    max_current_cells: int = 250_000,
    max_version_cells: int = 500_000,
) -> Snapshot:
    """Load one small durable graph without opening a ``CellStore`` owner.

    This is for independent authority artifacts such as a signing graph, never
    for the main application journal.  Callers must choose explicit caps; an
    oversized or malformed journal fails closed before Cells are materialized.
    """
    if any(
        type(value) is not int or value < 1
        for value in (max_revisions, max_current_cells, max_version_cells)
    ):
        raise ReadOnlyJournalError("read-only snapshot budget is invalid")
    connection = None
    try:
        database = Path(path).expanduser().resolve(strict=True)
        if not database.is_file():
            raise ReadOnlyJournalError("read-only journal path is not a file")
        connection = sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        revisions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(revisions)")
        }
        cell_versions_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(cell_versions)")
        }
        if revisions_columns != _JOURNAL_REVISIONS_COLUMNS or (
            cell_versions_columns != _JOURNAL_CELL_VERSION_COLUMNS
        ):
            raise ReadOnlyJournalError("read-only journal schema is unsupported")
        revision_count, first_revision, revision = connection.execute(
            "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revisions"
        ).fetchone()
        version_count = connection.execute(
            "SELECT COUNT(*) FROM cell_versions"
        ).fetchone()[0]
        if (
            type(revision_count) is not int
            or type(version_count) is not int
            or revision_count > max_revisions
            or version_count > max_version_cells
        ):
            raise ReadOnlyJournalError(
                "read-only snapshot exceeds the inspection budget"
            )
        if (
            type(first_revision) is not int
            or type(revision) is not int
            or revision_count < 1
            or first_revision != 0
            or revision != revision_count - 1
        ):
            raise ReadOnlyJournalError("read-only journal revision history is invalid")
        current_count = connection.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT cell_id, MAX(revision) FROM cell_versions GROUP BY cell_id"
            ")"
        ).fetchone()[0]
        if type(current_count) is not int or current_count > max_current_cells:
            raise ReadOnlyJournalError(
                "read-only snapshot exceeds the current-Cell budget"
            )
        rows = connection.execute(
            "SELECT versions.cell_id, versions.link0, versions.link1, versions.atom "
            "FROM cell_versions AS versions JOIN ("
            "SELECT cell_id, MAX(revision) AS revision "
            "FROM cell_versions GROUP BY cell_id"
            ") AS selected ON selected.cell_id = versions.cell_id "
            "AND selected.revision = versions.revision ORDER BY versions.cell_id"
        )
        cells: dict[str, Cell] = {}
        for cell_id, link0, link1, atom in rows:
            cell = Cell(str(cell_id), str(link0), str(link1), bytes(atom))
            _validate_cell(cell)
            cells[cell.id] = cell
        if len(cells) != current_count or NULL_CELL_ID not in cells:
            raise ReadOnlyJournalError("read-only snapshot Cell set is invalid")
        if any(
            cell.link0 not in cells or cell.link1 not in cells
            for cell in cells.values()
        ):
            raise ReadOnlyJournalError("read-only snapshot contains a dangling Cell")
        return Snapshot(revision, _frozen_cells(cells))
    except ReadOnlyJournalError:
        raise
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        raise ReadOnlyJournalError("read-only snapshot is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


def read_only_revision_chain_digest(
    path: str | os.PathLike[str],
    revision: int,
    *,
    max_revision_cells: int = 5_000_000,
) -> str:
    """Stream one durable revision-chain digest without opening ``CellStore``.

    The framing is exactly the normal journal digest.  Rows are streamed in
    primary-key order inside one read-only transaction, keeping memory bounded
    even when a trusted checkpoint covers many revisions.
    """
    if (
        type(revision) is not int
        or revision < 0
        or type(max_revision_cells) is not int
        or max_revision_cells < 1
    ):
        raise ReadOnlyJournalError("read-only digest request is invalid")
    connection = None
    try:
        database = Path(path).expanduser().resolve(strict=True)
        if not database.is_file():
            raise ReadOnlyJournalError("read-only journal path is not a file")
        connection = sqlite3.connect(
            database.as_uri() + "?mode=ro",
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        revision_count, first_revision, latest_revision = connection.execute(
            "SELECT COUNT(*), MIN(revision), MAX(revision) FROM revisions"
        ).fetchone()
        if (
            type(revision_count) is not int
            or type(first_revision) is not int
            or type(latest_revision) is not int
            or revision_count < 1
            or first_revision != 0
            or latest_revision != revision_count - 1
            or revision > latest_revision
        ):
            raise ReadOnlyJournalError("read-only journal revision history is invalid")
        cell_count = connection.execute(
            "SELECT COUNT(*) FROM cell_versions WHERE revision<=?", (revision,)
        ).fetchone()[0]
        if type(cell_count) is not int or cell_count > max_revision_cells:
            raise ReadOnlyJournalError(
                "read-only digest exceeds the revision-Cell budget"
            )
        previous = b"\x00" * 32
        current_revision = -1
        digest = None
        rows = connection.execute(
            "SELECT revision, cell_id, link0, link1, atom FROM cell_versions "
            "WHERE revision<=? ORDER BY revision, cell_id",
            (revision,),
        )
        for row_revision, cell_id, link0, link1, atom in rows:
            if type(row_revision) is not int:
                raise ReadOnlyJournalError("read-only journal revision is invalid")
            if row_revision != current_revision:
                if row_revision != current_revision + 1:
                    raise ReadOnlyJournalError(
                        "read-only journal revision history is incomplete"
                    )
                if digest is not None:
                    previous = digest.digest()
                digest = hashlib.sha256()
                domain = b"ArchHub/universal-cell-revision-chain/v1"
                digest.update(len(domain).to_bytes(8, "big"))
                digest.update(domain)
                digest.update(previous)
                raw_revision = str(row_revision).encode("ascii")
                digest.update(len(raw_revision).to_bytes(8, "big"))
                digest.update(raw_revision)
                current_revision = row_revision
            for raw in (
                str(cell_id).encode("utf-8"),
                str(link0).encode("utf-8"),
                str(link1).encode("utf-8"),
                bytes(atom),
            ):
                digest.update(len(raw).to_bytes(8, "big"))
                digest.update(raw)
        if digest is None or current_revision != revision:
            raise ReadOnlyJournalError("read-only journal revision is missing")
        return digest.digest().hex()
    except ReadOnlyJournalError:
        raise
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        raise ReadOnlyJournalError("read-only digest is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


_RUNTIME_FENCE_LEASE_TOKEN = object()


class RuntimeFenceLease:
    """Opaque, process-local handoff for one already-held runtime fence."""

    __slots__ = (
        "_store",
        "_resource_id",
        "_release",
        "_consumed",
        "_released",
        "_lock",
    )

    def __init__(
        self,
        store: "CellStore",
        resource_id: str,
        release: Callable[[], None],
        *,
        _token: object,
    ) -> None:
        if _token is not _RUNTIME_FENCE_LEASE_TOKEN:
            raise InvalidCell("runtime fence lease cannot be constructed directly")
        self._store = store
        self._resource_id = resource_id
        self._release = release
        self._consumed = False
        self._released = False
        self._lock = threading.Lock()

    def consume(
        self,
        store: "CellStore",
        resource_id: str,
    ) -> Callable[[], None]:
        """Transfer this exact active fence to one runtime owner."""
        with self._lock:
            if self._consumed:
                raise InvalidCell("runtime fence lease was already consumed")
            if self._released:
                raise InvalidCell("runtime fence lease was already released")
            if store is not self._store:
                raise InvalidCell(
                    "runtime fence lease belongs to another CellStore"
                )
            if resource_id != self._resource_id:
                raise InvalidCell(
                    "runtime fence lease belongs to another resource"
                )
            self._consumed = True
            return self.close

    def close(self) -> None:
        """Release the physical fence once, before or after handoff."""
        with self._lock:
            if self._released:
                return
            self._released = True
            release = self._release
        release()


class CellStore:
    """Transactional Cell authority with immutable snapshots and journaling.

    Commits construct and validate a complete next mapping before one pointer
    swap publishes it. An optional SQLite journal preserves every committed
    revision and its incremental revision-chain digest across process restarts.
    """

    _HISTORICAL_CACHE_SIZE = 2
    _COPY_ON_COMMIT_CELL_LIMIT = 100_000

    def __init__(
        self,
        database_path: str | os.PathLike[str] | None = None,
        *,
        fault_injector: Callable[[str], None] | None = None,
        journal: CellJournal | None = None,
    ) -> None:
        if database_path is not None and journal is not None:
            raise InvalidCell(
                "CellStore accepts either database_path or journal, not both"
            )
        if journal is not None and fault_injector is not None:
            raise InvalidCell(
                "an injected Cell journal owns its own fault boundary"
            )
        self._lock = threading.RLock()
        self._journal: CellJournal | None = journal
        if self._journal is None and database_path is not None:
            self._journal = _SqliteJournal(database_path, fault_injector)
        if self._journal is None:
            null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
            self._cells: Mapping[str, Cell] = _frozen_cells({NULL_CELL_ID: null})
            self._revision = 0
            self._versions: dict[int, tuple[Cell, ...]] = {0: (null,)}
            self._changes: dict[int, tuple[str, ...]] = {
                0: (NULL_CELL_ID,),
            }
        else:
            (
                self._cells,
                self._revision,
                self._versions,
                self._changes,
            ) = self._journal.load()
        self._authority_identity = (
            self._journal.identity
            if self._journal is not None
            else "memory:" + uuid.uuid4().hex
        )
        self._historical_snapshots: OrderedDict[int, Snapshot] = OrderedDict()
        self._dense_snapshot_cache: Snapshot | None = None
        self._cell_history_index: dict[str, tuple[tuple[int, Cell], ...]] | None = None
        self._fingerprints: dict[tuple[str, frozenset[str]], str] = {}
        self._fingerprint_dependencies: dict[
            tuple[str, frozenset[str]], frozenset[str]
        ] = {}
        self._fingerprint_compute_counts: dict[
            tuple[str, frozenset[str]], int
        ] = {}
        self._listeners: set[Callable[[CommitEvent], None]] = set()
        self._listener_failures: list[str] = []
        self._revision_chain_digests: dict[int, bytes] = {}

    def close(self) -> None:
        with self._lock:
            if self._journal is not None:
                self._journal.close()
                self._journal = None

    @property
    def database_path(self) -> str | None:
        """Local SQLite path, or None for memory and remote authorities."""
        with self._lock:
            return (
                self._journal.local_path
                if self._journal is not None
                else None
            )

    @property
    def authority_identity(self) -> str:
        """Secret-free stable identity of this physical graph authority."""
        return self._authority_identity

    @property
    def durability_backend(self) -> str:
        """Physical persistence backend without semantic interpretation."""
        with self._lock:
            return (
                self._journal.backend
                if self._journal is not None
                else "memory"
            )

    @property
    def is_durable(self) -> bool:
        with self._lock:
            return self._journal is not None

    @property
    def has_exclusive_database_owner(self) -> bool:
        """Whether this live store holds the process-fatal-safe OS fence."""
        with self._lock:
            return bool(
                self._journal is not None
                and self._journal.exclusive_owner
            )

    @property
    def supports_shared_writers(self) -> bool:
        """Whether durable conflicts can originate in another process."""
        with self._lock:
            return bool(
                self._journal is not None
                and self._journal.shared_writers
            )

    def _adopt_journal_state(
        self,
        loaded: tuple[
            Mapping[str, Cell],
            int,
            dict[int, tuple[Cell, ...]],
            dict[int, tuple[str, ...]],
        ],
    ) -> None:
        cells, revision, versions, changes = loaded
        if revision < self._revision:
            raise InvalidCell("durable Cell authority moved backwards")
        self._cells = cells
        self._revision = revision
        self._versions = versions
        self._changes = changes
        self._historical_snapshots.clear()
        self._dense_snapshot_cache = None
        self._cell_history_index = None
        self._fingerprints.clear()
        self._fingerprint_dependencies.clear()
        self._fingerprint_compute_counts.clear()
        self._revision_chain_digests.clear()

    def refresh(self) -> int:
        """Adopt the latest accepted revision from a shared authority."""
        with self._lock:
            if self._journal is None:
                return self._revision
            self._adopt_journal_state(self._journal.load())
            return self._revision

    def acquire_runtime_fence(
        self, resource_id: str
    ) -> Callable[[], None]:
        """Hold one physical runtime fence while graph ownership is active."""
        if not isinstance(resource_id, str) or not resource_id:
            raise InvalidCell("runtime fence resource identity is invalid")

        def no_op_release() -> None:
            return None

        with self._lock:
            if self._journal is None:
                return no_op_release
            if not self._journal.shared_writers:
                if not self._journal.exclusive_owner:
                    raise InvalidCell(
                        "durable authority has no admitted ownership fence"
                    )
                return no_op_release
            acquire = getattr(self._journal, "acquire_runtime_fence", None)
            if not callable(acquire):
                raise InvalidCell(
                    "shared durable authority has no runtime fence"
                )
            release = acquire(resource_id)
            if not callable(release):
                raise InvalidCell("runtime fence did not return a release")
            return release

    def prepare_runtime_fence(self, resource_id: str) -> RuntimeFenceLease:
        """Acquire one physical fence for an exact startup handoff."""
        return RuntimeFenceLease(
            self,
            resource_id,
            self.acquire_runtime_fence(resource_id),
            _token=_RUNTIME_FENCE_LEASE_TOKEN,
        )

    def backup_to(self, destination: str | os.PathLike[str]) -> str:
        """Invoke the physical backend's explicit recovery operation."""
        with self._lock:
            if self._journal is None:
                raise InvalidCell("an in-memory CellStore has no SQLite backup")
            return self._journal.backup_to(destination)

    def __enter__(self) -> "CellStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def read(self, cell_id: str, *, revision: int | None = None) -> Cell:
        with self._lock:
            source = self._cells if revision is None else self.at(revision).cells
            return source[cell_id]

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(self._revision, self._cells)

    def dense_snapshot(self) -> Snapshot:
        """Return the current revision in a flat immutable read mapping.

        Small commits remain cheap through persistent overlays. Interpreters
        that deliberately walk a large part of the graph can request this
        disposable dense view so each physical identity lookup stays O(1).
        The Store and every previously published Snapshot remain unchanged.
        """
        with self._lock:
            cached = self._dense_snapshot_cache
            if cached is not None and cached.revision == self._revision:
                return cached
            snapshot = dense_read_snapshot(Snapshot(self._revision, self._cells))
            self._dense_snapshot_cache = snapshot
            return snapshot

    def at(self, revision: int) -> Snapshot:
        with self._lock:
            if revision == self._revision:
                return Snapshot(self._revision, self._cells)
            cached = self._historical_snapshots.get(revision)
            if cached is not None:
                self._historical_snapshots.move_to_end(revision)
                return cached
            if revision not in self._versions:
                raise InvalidCell("unknown revision %r" % revision)
            previous_cached_revision = None
            for candidate in self._historical_snapshots:
                if candidate < revision and (
                    previous_cached_revision is None
                    or candidate > previous_cached_revision
                ):
                    previous_cached_revision = candidate
            if previous_cached_revision is None:
                reconstructed: dict[str, Cell] = {}
                start_revision = 0
            else:
                previous = self._historical_snapshots[previous_cached_revision]
                self._historical_snapshots.move_to_end(previous_cached_revision)
                reconstructed = dict(previous.cells)
                start_revision = previous_cached_revision + 1
            touched_since_base: set[str] = set()
            for current_revision in range(start_revision, revision + 1):
                try:
                    changed = self._versions[current_revision]
                except KeyError as exc:
                    raise InvalidCell(
                        "revision history is discontinuous at %r"
                        % current_revision
                    ) from exc
                for cell in changed:
                    reconstructed[cell.id] = cell
                    touched_since_base.add(cell.id)
            frozen = MappingProxyType(reconstructed)
            for cell_id in touched_since_base:
                cell = frozen[cell_id]
                if cell.link0 not in frozen or cell.link1 not in frozen:
                    raise InvalidCell(
                        "revision %s has dangling incidence" % revision
                    )
            snapshot = Snapshot(revision, frozen)
            self._historical_snapshots[revision] = snapshot
            while (
                len(self._historical_snapshots)
                > self._HISTORICAL_CACHE_SIZE
            ):
                self._historical_snapshots.popitem(last=False)
            return snapshot

    def revisions(self) -> tuple[int, ...]:
        """Return every retained immutable revision in journal order."""
        with self._lock:
            return tuple(sorted(self._versions))

    def revision_changes(self, revision: int) -> tuple[str, ...]:
        """Return the exact Cell identities changed by one retained revision."""
        with self._lock:
            try:
                return self._changes[revision]
            except KeyError as exc:
                raise InvalidCell("unknown revision %r" % revision) from exc

    def cells_at(
        self, revision: int, cell_ids: Iterable[str]
    ) -> Mapping[str, Cell]:
        """Return selected Cell versions at a revision without a full snapshot."""
        requested = tuple(dict.fromkeys(cell_ids))
        with self._lock:
            if revision == self._revision:
                try:
                    return MappingProxyType({
                        cell_id: self._cells[cell_id]
                        for cell_id in requested
                    })
                except KeyError as exc:
                    raise InvalidCell("unknown cell %r" % (exc.args[0],)) from exc
            if revision not in self._versions:
                raise InvalidCell("unknown revision %r" % revision)
            if self._cell_history_index is None:
                history: dict[str, list[tuple[int, Cell]]] = {}
                for rev in sorted(self._versions):
                    for cell in self._versions[rev]:
                        history.setdefault(cell.id, []).append((rev, cell))
                self._cell_history_index = {
                    cell_id: tuple(entries)
                    for cell_id, entries in history.items()
                }
            out: dict[str, Cell] = {}
            for cell_id in requested:
                entries = self._cell_history_index.get(cell_id)
                if not entries:
                    raise InvalidCell("unknown cell %r" % cell_id)
                revisions = tuple(rev for rev, _cell in entries)
                index = bisect_right(revisions, revision) - 1
                if index < 0:
                    raise InvalidCell(
                        "cell %r did not exist at revision %r"
                        % (cell_id, revision)
                    )
                out[cell_id] = entries[index][1]
            return MappingProxyType(out)

    def cell_created_revision(self, cell_id: str) -> int:
        """Return the immutable journal revision that first created a Cell."""
        with self._lock:
            if cell_id not in self._cells:
                raise InvalidCell("unknown cell %r" % cell_id)
            for revision in sorted(self._versions):
                if any(
                    cell.id == cell_id
                    for cell in self._versions[revision]
                ):
                    return revision
            raise InvalidCell("cell creation revision is missing")

    def retention_stats(self) -> Mapping[str, int]:
        """Expose bounded physical retention without interpreting the graph."""
        with self._lock:
            return MappingProxyType({
                "revision_count": len(self._versions),
                "current_cell_count": len(self._cells),
                "version_cell_count": sum(
                    len(changed) for changed in self._versions.values()
                ),
                "historical_snapshot_count": len(
                    self._historical_snapshots
                ),
                "historical_snapshot_cell_count": sum(
                    len(snapshot.cells)
                    for snapshot in self._historical_snapshots.values()
                ),
            })

    def revision_chain_digest(self, revision: int | None = None) -> str:
        """Commit to every changed Cell record from genesis through revision."""
        with self._lock:
            target = self._revision if revision is None else revision
            if target not in self._versions:
                raise InvalidCell("unknown revision %r" % target)
            previous = b"\x00" * 32
            start = 0
            cached = tuple(
                value for value in self._revision_chain_digests if value <= target
            )
            if cached:
                last = max(cached)
                previous = self._revision_chain_digests[last]
                start = last + 1
            for current_revision in range(start, target + 1):
                digest = hashlib.sha256()
                raw_domain = b"ArchHub/universal-cell-revision-chain/v1"
                digest.update(len(raw_domain).to_bytes(8, "big"))
                digest.update(raw_domain)
                digest.update(previous)
                raw_revision = str(current_revision).encode("ascii")
                digest.update(len(raw_revision).to_bytes(8, "big"))
                digest.update(raw_revision)
                changed = {
                    cell.id: cell for cell in self._versions[current_revision]
                }
                for root_id in sorted(self._changes[current_revision]):
                    cell = changed[root_id]
                    for raw in (
                        cell.id.encode("utf-8"),
                        cell.link0.encode("utf-8"),
                        cell.link1.encode("utf-8"),
                        cell.atom,
                    ):
                        digest.update(len(raw).to_bytes(8, "big"))
                        digest.update(raw)
                previous = digest.digest()
                self._revision_chain_digests[current_revision] = previous
            return previous.hex()

    def subscribe(
        self,
        listener: Callable[[CommitEvent], None],
    ) -> Callable[[], None]:
        """Register a post-commit listener and return an idempotent remover."""
        if not callable(listener):
            raise TypeError("commit listener must be callable")
        with self._lock:
            self._listeners.add(listener)

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.discard(listener)

        return unsubscribe

    def listener_failures(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._listener_failures)

    def commit(
        self,
        expected_revision: int,
        *,
        create: Iterable[Cell] = (),
        replace: Iterable[Cell] = (),
        precommit_guard: Callable[[], None] | None = None,
    ) -> int:
        created = tuple(create)
        replaced = tuple(replace)
        listeners: tuple[Callable[[CommitEvent], None], ...]
        event: CommitEvent
        with self._lock:
            if expected_revision != self._revision:
                raise Conflict(
                    "expected revision %s, current revision is %s"
                    % (expected_revision, self._revision)
                )

            base = self._cells
            if (
                isinstance(base, _OverlayCellMap)
                and base._depth >= _MAX_OVERLAY_DEPTH
            ):
                base = _compact_cell_map(base)
            delta: dict[str, Cell] = {}
            touched: set[str] = set()

            for cell in created:
                _validate_cell(cell)
                if cell.id in base or cell.id in touched:
                    raise InvalidCell("cannot create existing cell %r" % cell.id)
                touched.add(cell.id)
                delta[cell.id] = cell

            for cell in replaced:
                _validate_cell(cell)
                if cell.id == NULL_CELL_ID:
                    raise InvalidCell("the distinguished null cell is immutable")
                if cell.id not in base:
                    raise InvalidCell("cannot replace missing cell %r" % cell.id)
                if cell.id in touched:
                    raise InvalidCell("cell %r is changed twice in one commit" % cell.id)
                touched.add(cell.id)
                delta[cell.id] = cell

            if not touched:
                raise InvalidCell("empty commits are not transactions")

            for cell_id in touched:
                cell = delta[cell_id]
                if (
                    cell.link0 not in delta and cell.link0 not in base
                ) or (
                    cell.link1 not in delta and cell.link1 not in base
                ):
                    raise InvalidCell("cell %r contains a dangling physical link" % cell.id)

            next_revision = self._revision + 1
            if len(base) <= self._COPY_ON_COMMIT_CELL_LIMIT:
                candidate = dict(base)
                candidate.update(delta)
                published = MappingProxyType(candidate)
            else:
                published = _OverlayCellMap(base, delta)
            if precommit_guard is not None:
                if not callable(precommit_guard):
                    raise TypeError("Cell commit guard must be callable")
                precommit_guard()
            snapshot = Snapshot(next_revision, published)
            if self._journal is not None:
                try:
                    self._journal.append(
                        expected_revision,
                        next_revision,
                        tuple(created) + tuple(replaced),
                    )
                except Conflict:
                    self._adopt_journal_state(self._journal.load())
                    raise
            self._cells = published
            self._revision = next_revision
            self._dense_snapshot_cache = None
            self._versions[next_revision] = tuple(created) + tuple(replaced)
            self._changes[next_revision] = tuple(sorted(touched))
            self._cell_history_index = None
            for cache_key, dependencies in tuple(
                self._fingerprint_dependencies.items()
            ):
                if touched.intersection(dependencies):
                    self._fingerprints.pop(cache_key, None)
                    self._fingerprint_dependencies.pop(cache_key, None)
            event = CommitEvent(next_revision, frozenset(touched))
            listeners = tuple(self._listeners)

        for listener in listeners:
            try:
                listener(event)
            except Exception as exc:
                with self._lock:
                    self._listener_failures.append(
                        "%s: %s" % (type(exc).__name__, exc)
                    )
                    if len(self._listener_failures) > 100:
                        del self._listener_failures[:-100]
        return next_revision

    def fingerprint(
        self,
        root_id: str,
        *,
        budget: int = 100_000,
        excluded_roots: Iterable[str] = (),
    ) -> str:
        """Hash one reachable cell region without interpreting terminal data."""
        if budget < 1:
            raise MatchBudgetExceeded("fingerprint budget must be positive")
        with self._lock:
            excluded = frozenset(excluded_roots)
            if any(
                not isinstance(root, str) or not root
                for root in excluded
            ):
                raise InvalidCell("fingerprint exclusion root is invalid")
            if root_id in excluded:
                raise InvalidCell("fingerprint root cannot exclude itself")
            cache_key = (root_id, excluded)
            cached = self._fingerprints.get(cache_key)
            if cached is not None:
                return cached
            if root_id not in self._cells:
                raise InvalidCell("fingerprint root is missing")

            reachable: set[str] = set()
            pending = [root_id]
            steps = 0
            while pending:
                cell_id = pending.pop()
                if cell_id in reachable or cell_id in excluded:
                    continue
                steps += 1
                if steps > budget:
                    raise MatchBudgetExceeded(
                        "fingerprint exceeded %s reachable cells" % budget
                    )
                cell = self._cells[cell_id]
                reachable.add(cell_id)
                pending.append(cell.link0)
                pending.append(cell.link1)

            digest = hashlib.blake2b(digest_size=32)

            def add_field(data: bytes) -> None:
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)

            for cell_id in sorted(reachable):
                cell = self._cells[cell_id]
                add_field(cell.id.encode("utf-8"))
                add_field(cell.link0.encode("utf-8"))
                add_field(cell.link1.encode("utf-8"))
                add_field(cell.atom)

            value = digest.hexdigest()
            self._fingerprints[cache_key] = value
            self._fingerprint_dependencies[cache_key] = frozenset(reachable)
            self._fingerprint_compute_counts[cache_key] = (
                self._fingerprint_compute_counts.get(cache_key, 0) + 1
            )
            return value

    def fingerprint_computes(self, root_id: str) -> int:
        with self._lock:
            return sum(
                count
                for (candidate, _excluded), count
                in self._fingerprint_compute_counts.items()
                if candidate == root_id
            )

    def match(
        self,
        pattern: Mapping[str, Cell],
        *,
        pattern_root: str,
        target_root: str,
        variables: Iterable[str] = (),
        budget: int = 10_000,
        revision: int | None = None,
    ) -> dict[str, str]:
        """Unify a cell graph with a target graph using explicit variables.

        Atom bytes are tested only for exact opaque equality. They are never
        decoded or interpreted. The matcher knows graph structure, the null
        identity, and which pattern identities the caller supplied as
        variables; it knows no protocol or product vocabulary.
        """
        if budget < 1:
            raise MatchBudgetExceeded("match budget must be positive")
        variable_ids = frozenset(variables)
        with self._lock:
            stored_pattern = pattern is self._cells
            pattern_cells = pattern if stored_pattern else dict(pattern)
            if not stored_pattern:
                for cell in pattern_cells.values():
                    _validate_cell(cell)
            if pattern_root not in pattern_cells:
                raise InvalidCell("pattern root is missing")
            if NULL_CELL_ID not in pattern_cells:
                raise InvalidCell(
                    "pattern must contain the distinguished null cell"
                )
            if not all(root_id in pattern_cells for root_id in variable_ids):
                raise InvalidCell("every match variable must be a pattern cell")
            if NULL_CELL_ID in variable_ids:
                raise InvalidCell(
                    "the distinguished null cell cannot be a variable"
                )
            if not stored_pattern:
                for cell in pattern_cells.values():
                    if cell.id in variable_ids:
                        continue
                    if (
                        cell.link0 not in pattern_cells
                        or cell.link1 not in pattern_cells
                    ):
                        raise InvalidCell(
                            "pattern cell %r has a dangling link" % cell.id
                        )
            target_cells = self._cells if revision is None else self.at(revision).cells
            if target_root not in target_cells:
                raise NoMatch("target root is missing")

            bindings: dict[str, str] = {}
            concrete: dict[str, str] = {}
            pending = [(pattern_root, target_root)]
            steps = 0

            while pending:
                steps += 1
                if steps > budget:
                    raise MatchBudgetExceeded(
                        "graph match exceeded %s visited pairs" % budget
                    )
                pattern_id, target_id = pending.pop()

                if pattern_id in variable_ids:
                    previous = bindings.get(pattern_id)
                    if previous is not None and previous != target_id:
                        raise NoMatch("one variable matched two target cells")
                    bindings[pattern_id] = target_id
                    continue

                previous = concrete.get(pattern_id)
                if previous is not None:
                    if previous != target_id:
                        raise NoMatch("shared pattern structure was not preserved")
                    continue

                if pattern_id == NULL_CELL_ID:
                    if target_id != NULL_CELL_ID:
                        raise NoMatch("null incidence did not match")
                    concrete[pattern_id] = target_id
                    continue

                target_cell = target_cells.get(target_id)
                if target_cell is None:
                    raise NoMatch("target incidence is missing")
                pattern_cell = pattern_cells[pattern_id]
                if not hmac.compare_digest(pattern_cell.atom, target_cell.atom):
                    raise NoMatch("opaque terminal atoms differ")

                concrete[pattern_id] = target_id
                pending.append((pattern_cell.link0, target_cell.link0))
                pending.append((pattern_cell.link1, target_cell.link1))

            return bindings

    def _prepare_rewrite_locked(
        self,
        *,
        expected_revision: int,
        pattern_root: str,
        target_root: str,
        pattern_variables: Iterable[str],
        replacement_root: str,
        replacement_variables: Mapping[str, str],
        replacement_constants: Mapping[str, str] | None = None,
        budget: int = 10_000,
    ) -> PreparedRewrite:
        """Match one stored graph and materialize an unpublished replacement.

        Both sides of the rule are ordinary cells already in this store. The
        caller explicitly maps replacement placeholders to pattern variables.
        All other replacement cells are copied to fresh identities, except the
        replacement root, which preserves the target root's stable identity.
        """
        pattern_variable_ids = frozenset(pattern_variables)
        replacement_variable_map = dict(replacement_variables)
        replacement_constant_map = dict(replacement_constants or {})
        if expected_revision != self._revision:
            raise Conflict(
                "expected revision %s, current revision is %s"
                % (expected_revision, self._revision)
            )
        if target_root == NULL_CELL_ID:
            raise InvalidCell("the distinguished null cell cannot be rewritten")
        if replacement_root in replacement_variable_map:
            raise InvalidCell("replacement root cannot be a variable")
        if replacement_root in replacement_constant_map:
            raise InvalidCell("replacement root cannot be a constant binding")
        if set(replacement_variable_map).intersection(replacement_constant_map):
            raise InvalidCell("replacement placeholder has conflicting bindings")
        if not set(replacement_variable_map.values()).issubset(pattern_variable_ids):
            raise InvalidCell(
                "replacement variables must map to declared pattern variables"
            )
        if not all(root_id in self._cells for root_id in replacement_variable_map):
            raise InvalidCell("replacement variable cell is missing")
        if not all(root_id in self._cells for root_id in replacement_constant_map):
            raise InvalidCell("replacement constant placeholder is missing")
        if not all(
            root_id in self._cells for root_id in replacement_constant_map.values()
        ):
            raise InvalidCell("replacement constant target is missing")
        if replacement_root not in self._cells:
            raise InvalidCell("replacement root is missing")

        bindings = self.match(
            self._cells,
            pattern_root=pattern_root,
            target_root=target_root,
            variables=pattern_variable_ids,
            budget=budget,
            revision=expected_revision,
        )

        concrete_templates: set[str] = set()
        pending = [replacement_root]
        steps = 0
        while pending:
            steps += 1
            if steps > budget:
                raise MatchBudgetExceeded(
                    "replacement traversal exceeded %s cells" % budget
                )
            template_id = pending.pop()
            if (
                template_id == NULL_CELL_ID
                or template_id in replacement_variable_map
                or template_id in replacement_constant_map
                or template_id in concrete_templates
            ):
                continue
            template = self._cells.get(template_id)
            if template is None:
                raise InvalidCell("replacement contains a dangling link")
            concrete_templates.add(template_id)
            pending.append(template.link0)
            pending.append(template.link1)

        materialized: dict[str, str] = {replacement_root: target_root}
        occupied = {target_root}
        for template_id in sorted(concrete_templates):
            if template_id == replacement_root:
                continue
            fresh = str(uuid.uuid4())
            while fresh in self._cells or fresh in occupied:
                fresh = str(uuid.uuid4())
            occupied.add(fresh)
            materialized[template_id] = fresh

        def translated(template_id: str) -> str:
            if template_id == NULL_CELL_ID:
                return NULL_CELL_ID
            pattern_variable = replacement_variable_map.get(template_id)
            if pattern_variable is not None:
                return bindings[pattern_variable]
            constant_root = replacement_constant_map.get(template_id)
            if constant_root is not None:
                return constant_root
            try:
                return materialized[template_id]
            except KeyError as exc:
                raise InvalidCell(
                    "replacement reference was not materialized"
                ) from exc

        created: list[Cell] = []
        replaced: list[Cell] = []
        for template_id in sorted(concrete_templates):
            template = self._cells[template_id]
            instance = Cell(
                materialized[template_id],
                translated(template.link0),
                translated(template.link1),
                template.atom,
            )
            if template_id == replacement_root:
                replaced.append(instance)
            else:
                created.append(instance)

        return PreparedRewrite(
            root_id=target_root,
            expected_revision=expected_revision,
            create=tuple(created),
            replace=tuple(replaced),
            bindings=MappingProxyType(dict(bindings)),
            materialized=MappingProxyType(dict(materialized)),
        )

    def prepare_rewrite(
        self,
        *,
        expected_revision: int,
        pattern_root: str,
        target_root: str,
        pattern_variables: Iterable[str],
        replacement_root: str,
        replacement_variables: Mapping[str, str],
        replacement_constants: Mapping[str, str] | None = None,
        budget: int = 10_000,
    ) -> PreparedRewrite:
        """Materialize a rewrite without publishing it, for one atomic set."""
        with self._lock:
            return self._prepare_rewrite_locked(
                expected_revision=expected_revision,
                pattern_root=pattern_root,
                target_root=target_root,
                pattern_variables=pattern_variables,
                replacement_root=replacement_root,
                replacement_variables=replacement_variables,
                replacement_constants=replacement_constants,
                budget=budget,
            )

    def rewrite(
        self,
        *,
        expected_revision: int,
        pattern_root: str,
        target_root: str,
        pattern_variables: Iterable[str],
        replacement_root: str,
        replacement_variables: Mapping[str, str],
        replacement_constants: Mapping[str, str] | None = None,
        budget: int = 10_000,
    ) -> RewriteResult:
        """Match one stored graph and atomically publish its replacement."""
        with self._lock:
            prepared = self._prepare_rewrite_locked(
                expected_revision=expected_revision,
                pattern_root=pattern_root,
                target_root=target_root,
                pattern_variables=pattern_variables,
                replacement_root=replacement_root,
                replacement_variables=replacement_variables,
                replacement_constants=replacement_constants,
                budget=budget,
            )
            revision = self.commit(
                expected_revision,
                create=prepared.create,
                replace=prepared.replace,
            )
            return RewriteResult(
                root_id=target_root,
                revision=revision,
                bindings=prepared.bindings,
                materialized=prepared.materialized,
            )


def migrate_cell_history(
    source: CellStore,
    destination: CellStore,
) -> CellHistoryMigrationEvidence:
    """Copy one quiesced Cell history and prove exact revision equivalence.

    The destination is never promoted here. Callers must keep the source
    write-frozen, inspect this evidence, run provider restore courts, and only
    then change the runtime authority pointer.
    """
    if source.authority_identity == destination.authority_identity:
        raise InvalidCell("Cell migration requires distinct authorities")
    if destination.revision != 0 or set(destination.snapshot().cells) != {
        NULL_CELL_ID
    }:
        raise InvalidCell("Cell migration destination must be at genesis")

    source_revision = source.revision
    source_digest = source.revision_chain_digest(source_revision)
    for revision in range(1, source_revision + 1):
        changed_ids = source.revision_changes(revision)
        changed = source.cells_at(revision, changed_ids)
        destination_snapshot = destination.snapshot()
        create = tuple(
            changed[cell_id]
            for cell_id in changed_ids
            if cell_id not in destination_snapshot.cells
        )
        replace = tuple(
            changed[cell_id]
            for cell_id in changed_ids
            if cell_id in destination_snapshot.cells
        )
        destination.commit(
            destination_snapshot.revision,
            create=create,
            replace=replace,
        )

    if source.revision != source_revision:
        raise Conflict("Cell migration source changed during history copy")
    destination_digest = destination.revision_chain_digest()
    if (
        destination.revision != source_revision
        or destination_digest != source_digest
    ):
        raise InvalidCell("Cell migration history proof does not match")
    return CellHistoryMigrationEvidence(
        source_identity=source.authority_identity,
        destination_identity=destination.authority_identity,
        source_revision=source_revision,
        destination_revision=destination.revision,
        revision_chain_digest=source_digest,
    )


__all__ = [
    "NULL_CELL_ID",
    "Cell",
    "Snapshot",
    "ReadOnlyJournalRevision",
    "RewriteResult",
    "PreparedRewrite",
    "CommitEvent",
    "CellHistoryMigrationEvidence",
    "CellJournal",
    "RuntimeFenceLease",
    "CellStore",
    "CellKernelError",
    "Conflict",
    "InvalidCell",
    "ReadOnlyJournalError",
    "NoMatch",
    "MatchBudgetExceeded",
    "dense_read_snapshot",
    "overlay_read_snapshot",
    "inspect_read_only_cell_journal",
    "load_bounded_read_only_cell_snapshot",
    "read_only_revision_chain_digest",
    "migrate_cell_history",
]
