"""PostgreSQL physical-authority courts for the Universal Cell floor."""
from __future__ import annotations

import os
import traceback
import uuid

import pytest

from nodelang.postgres_cell_journal import (
    _HISTORY_INDEX_DDL,
    PostgresAuthorityUnavailable,
    PostgresCellJournal,
    _DDL,
    postgres_authority_identity,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    DatabaseOwnerConflict,
    InvalidCell,
    migrate_cell_history,
)


def _leaf(root_id: str, atom: bytes) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _normalise_sql(statement: str) -> str:
    return " ".join(statement.split()).casefold()


class _HistoryFixture:
    def __init__(self, authority: CellStore) -> None:
        self.authority_id = "court-history"
        self.version_rows: list[tuple[int, str, str, str, bytes]] = []
        self.current_rows: dict[str, tuple[int, str, str, bytes]] = {}
        for revision in authority.revisions():
            changed_ids = authority.revision_changes(revision)
            changed = authority.cells_at(revision, changed_ids)
            for cell_id in changed_ids:
                cell = changed[cell_id]
                row = (
                    revision,
                    cell.id,
                    cell.link0,
                    cell.link1,
                    cell.atom,
                )
                self.version_rows.append(row)
                self.current_rows[cell.id] = (
                    revision,
                    cell.link0,
                    cell.link1,
                    cell.atom,
                )
        self.version_rows.sort(key=lambda row: (row[0], row[1]))

    @property
    def head_revision(self) -> int:
        return max(row[0] for row in self.version_rows)

    def append(self, *cells: Cell) -> int:
        revision = self.head_revision + 1
        for cell in sorted(cells, key=lambda candidate: candidate.id):
            self.version_rows.append(
                (
                    revision,
                    cell.id,
                    cell.link0,
                    cell.link1,
                    cell.atom,
                )
            )
            self.current_rows[cell.id] = (
                revision,
                cell.link0,
                cell.link1,
                cell.atom,
            )
        return revision


class _ObservingPostgresCursor:
    def __init__(self, connection: "_ObservingPostgresConnection") -> None:
        self.connection = connection
        self.rows: list[tuple] = []
        self.index = 0
        self.statement = ""
        self.rowcount = 0

    def execute(self, statement, parameters=None):
        self.statement = _normalise_sql(str(statement))
        parameters = tuple(parameters or ())
        self.connection.calls.append((self.statement, parameters))
        self.rows = self.connection.rows_for(self.statement, parameters)
        self.index = 0
        self.rowcount = len(self.rows)
        return self

    def executemany(self, statement, rows):
        materialised = tuple(tuple(row) for row in rows)
        self.statement = _normalise_sql(str(statement))
        self.connection.calls.append((self.statement, materialised))
        self.rows = []
        self.index = 0
        self.rowcount = len(materialised)
        return self

    def fetchone(self):
        self._record_stream_read()
        if self.index >= len(self.rows):
            return None
        row = self.rows[self.index]
        self.index += 1
        return row

    def fetchmany(self, size=1):
        self._record_stream_read()
        start = self.index
        self.index = min(len(self.rows), self.index + size)
        return self.rows[start:self.index]

    def fetchall(self):
        self.connection.fetchall_calls.append(self.statement)
        remaining = self.rows[self.index:]
        self.index = len(self.rows)
        return remaining

    def __iter__(self):
        self._record_stream_read()
        while self.index < len(self.rows):
            row = self.rows[self.index]
            self.index += 1
            yield row

    def _record_stream_read(self) -> None:
        if self.statement not in self.connection.stream_reads:
            self.connection.stream_reads.append(self.statement)

    def close(self) -> None:
        return None


class _ObservingPostgresConnection:
    def __init__(self, fixture: _HistoryFixture) -> None:
        self.fixture = fixture
        self.calls: list[tuple[str, tuple]] = []
        self.fetchall_calls: list[str] = []
        self.stream_reads: list[str] = []
        self.server_cursor_names: list[str] = []
        self.history_index_valid = True
        self.history_index_ready = True
        self.history_index_definition = (
            "CREATE INDEX archhub_cell_versions_cell_revision_idx "
            "ON public.archhub_cell_versions USING btree "
            "(authority_id, cell_id, revision DESC)"
        )
        self.closed = False

    def cursor(self, *args, **kwargs):
        name = kwargs.get("name")
        if isinstance(name, str):
            self.server_cursor_names.append(name)
        return _ObservingPostgresCursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def rows_for(self, statement: str, parameters: tuple) -> list[tuple]:
        if statement.startswith(("begin ", "set transaction ")):
            return []
        if statement.startswith(
            ("create ", "insert ", "update ", "alter ")
        ):
            return []
        if "pg_get_indexdef" in statement and "from pg_class" in statement:
            return [(
                self.history_index_valid,
                self.history_index_ready,
                self.history_index_definition,
            )]
        if "from archhub_cell_authorities" in statement:
            return [(self.fixture.head_revision,)]
        if (
            "count(*)" in statement
            and "from archhub_cell_revisions" in statement
        ):
            head = self.fixture.head_revision
            return [(head + 1, 0, head)]
        if (
            statement.startswith("select revision")
            and "from archhub_cell_revisions" in statement
        ):
            return [
                (revision,)
                for revision in range(self.fixture.head_revision + 1)
            ]
        if "from archhub_current_cells" in statement:
            return self._current_rows(statement)
        if "from archhub_cell_versions" in statement:
            return self._version_rows(statement, parameters)
        return []

    def _current_rows(self, statement: str) -> list[tuple]:
        if "count(*)" in statement:
            return [(len(self.fixture.current_rows),)]
        return [
            (cell_id, revision, link0, link1, atom)
            for cell_id, (revision, link0, link1, atom)
            in sorted(self.fixture.current_rows.items())
        ]

    def _version_rows(
        self,
        statement: str,
        parameters: tuple,
    ) -> list[tuple]:
        logical = tuple(
            value
            for value in parameters
            if value != self.fixture.authority_id
        )
        revisions = tuple(
            value for value in logical
            if type(value) is int
        )
        cell_ids = tuple(
            value for value in logical
            if isinstance(value, str)
        )
        target = revisions[0] if revisions else self.fixture.head_revision
        rows = [
            row for row in self.fixture.version_rows
            if row[0] <= target
        ]
        if "min(revision)" in statement:
            matching = [row[0] for row in rows if row[1] in cell_ids]
            return [(min(matching) if matching else None,)]
        if "count(*)" in statement:
            return [(len(rows),)]
        if " revision=%s" in statement or " revision = %s" in statement:
            rows = [row for row in rows if row[0] == target]
        if "cell_id in (" in statement:
            rows = [row for row in rows if row[1] in cell_ids]
        if " join (" in statement:
            latest: dict[str, tuple[int, str, str, str, bytes]] = {}
            for row in rows:
                latest[row[1]] = row
            rows = [latest[cell_id] for cell_id in sorted(latest)]
            return [
                (cell_id, link0, link1, atom)
                for _revision, cell_id, link0, link1, atom in rows
            ]
        if statement.startswith(
            "select cell_id, link0, link1, atom"
        ):
            return [
                (cell_id, link0, link1, atom)
                for _revision, cell_id, link0, link1, atom in rows
            ]
        return list(rows)


def _history_authority() -> CellStore:
    authority = CellStore()
    authority.commit(
        0,
        create=(
            _leaf("postgres:alpha", b"alpha-v1"),
            Cell(
                "postgres:beta",
                "postgres:alpha",
                NULL_CELL_ID,
                b"beta-v1",
            ),
        ),
    )
    authority.commit(
        1,
        replace=(_leaf("postgres:alpha", b"alpha-v2"),),
    )
    authority.commit(
        2,
        create=(
            Cell(
                "postgres:gamma",
                "postgres:alpha",
                "postgres:beta",
                b"gamma-v1",
            ),
        ),
    )
    return authority


def _fake_postgres_journal(
    authority: CellStore,
) -> tuple[PostgresCellJournal, _HistoryFixture, _ObservingPostgresConnection]:
    fixture = _HistoryFixture(authority)
    connection = _ObservingPostgresConnection(fixture)
    journal = PostgresCellJournal(
        "fixture-dsn",
        authority_id=fixture.authority_id,
        connection_factory=lambda _dsn: connection,
    )
    return journal, fixture, connection


def _is_full_history_query(statement: str) -> bool:
    return (
        "from archhub_cell_versions" in statement
        and "order by revision, cell_id" in statement
        and "revision=%s" not in statement
        and "revision = %s" not in statement
        and "cell_id in (" not in statement
    )


def test_postgres_builtin_journal_uses_load_head_not_legacy_eager_load():
    authority = _history_authority()
    journal, _fixture, _connection = _fake_postgres_journal(authority)

    def reject_eager_load():
        raise AssertionError(
            "built-in PostgreSQL journal selected the eager history adapter"
        )

    journal.load = reject_eager_load
    durable = CellStore(journal=journal)

    assert durable.revision == authority.revision
    assert dict(durable.snapshot().cells) == dict(authority.snapshot().cells)
    assert durable.revision_chain_digest() == authority.revision_chain_digest()


def test_postgres_history_reader_is_bound_to_its_captured_head():
    authority = _history_authority()
    journal, fixture, _connection = _fake_postgres_journal(authority)
    loaded = journal.load_head()
    captured = loaded.history

    assert captured.head_revision == authority.revision
    assert captured.head_digest == authority.revision_chain_digest()

    later_revision = fixture.append(
        _leaf("postgres:later", b"must-stay-invisible")
    )

    assert later_revision == authority.revision + 1
    assert captured.head_revision == authority.revision
    assert "postgres:later" not in captured.snapshot_at(
        authority.revision
    ).cells
    assert captured.version_count() == authority.retention_stats()[
        "version_cell_count"
    ]
    with pytest.raises(InvalidCell, match="unknown revision"):
        captured.snapshot_at(later_revision)
    with pytest.raises(InvalidCell, match="unknown revision"):
        captured.chain_digest(later_revision)


def test_postgres_history_reader_matches_exact_eager_history_behavior():
    authority = _history_authority()
    journal, _fixture, connection = _fake_postgres_journal(authority)
    loaded = journal.load_head()
    history = loaded.history

    assert loaded.revision == authority.revision
    assert dict(loaded.cells) == dict(authority.snapshot().cells)
    assert loaded.revision_chain_digest == authority.revision_chain_digest()
    for revision in authority.revisions():
        expected_ids = authority.revision_changes(revision)
        changed = history.revision_cells(revision)
        assert tuple(cell.id for cell in changed) == expected_ids
        assert {
            cell.id: cell for cell in changed
        } == dict(authority.cells_at(revision, expected_ids))
        assert dict(history.snapshot_at(revision).cells) == dict(
            authority.at(revision).cells
        )
        assert history.chain_digest(revision) == (
            authority.revision_chain_digest(revision)
        )

    selected = ("postgres:alpha", "postgres:beta")
    assert dict(history.cells_at(1, selected)) == dict(
        authority.cells_at(1, selected)
    )
    for cell_id in authority.snapshot().cells:
        assert history.created_revision(cell_id) == (
            authority.cell_created_revision(cell_id)
        )
    assert history.version_count() == authority.retention_stats()[
        "version_cell_count"
    ]
    assert "archhub_history_digest" in connection.server_cursor_names


def test_postgres_load_head_streams_full_history_without_fetchall():
    authority = _history_authority()
    journal, _fixture, connection = _fake_postgres_journal(authority)

    loaded = journal.load_head()

    full_history_fetchalls = tuple(
        statement
        for statement in connection.fetchall_calls
        if _is_full_history_query(statement)
    )
    full_history_streams = tuple(
        statement
        for statement in connection.stream_reads
        if _is_full_history_query(statement)
    )
    assert loaded.revision == authority.revision
    assert full_history_fetchalls == ()
    assert full_history_streams
    assert "archhub_load_head_history" in connection.server_cursor_names


def test_postgres_load_head_denies_a_forged_genesis():
    authority = _history_authority()
    journal, fixture, _connection = _fake_postgres_journal(authority)
    revision, cell_id, link0, link1, _atom = fixture.version_rows[0]
    fixture.version_rows[0] = (
        revision,
        cell_id,
        link0,
        link1,
        b"forged",
    )
    fixture.current_rows[cell_id] = (
        revision,
        link0,
        link1,
        b"forged",
    )

    with pytest.raises(InvalidCell, match="genesis"):
        journal.load_head()


def test_postgres_authority_identity_is_stable_and_contains_no_dsn_secret():
    dsn = "dbname=archhub host=db.example user=fixture"
    identity = postgres_authority_identity("archhub-production")

    assert identity == postgres_authority_identity("archhub-production")
    assert identity != postgres_authority_identity("archhub-staging")
    assert identity.startswith("postgresql:sha256:")
    assert "founder" not in identity
    assert "never-print-this" not in identity
    assert dsn not in identity


def test_postgres_configuration_rejects_invalid_physical_authority_names():
    with pytest.raises(InvalidCell, match="authority identifier"):
        postgres_authority_identity("")
    with pytest.raises(InvalidCell, match="authority identifier"):
        postgres_authority_identity("not allowed/authority")


def test_postgres_connection_failure_does_not_render_the_secret_dsn():
    dsn = "dbname=archhub host=db.example user=fixture"

    def fail(value):
        raise RuntimeError("could not connect using " + value)

    with pytest.raises(PostgresAuthorityUnavailable) as captured:
        PostgresCellJournal(
            dsn,
            authority_id="archhub-production",
            connection_factory=fail,
        )

    rendered = "".join(
        traceback.format_exception(
            type(captured.value),
            captured.value,
            captured.value.__traceback__,
        )
    )
    assert dsn not in rendered
    assert "do-not-render" not in rendered


def test_postgres_schema_contains_only_physical_journal_tables_and_columns():
    ddl = "\n".join(_DDL).casefold()
    expected_tables = {
        "archhub_cell_authorities",
        "archhub_cell_revisions",
        "archhub_cell_versions",
        "archhub_current_cells",
    }
    declared = {
        line.split()[5]
        for line in ddl.splitlines()
        if line.strip().startswith("create table if not exists")
    }
    assert declared == expected_tables
    for forbidden_semantic_column in (
        " kind ",
        " role ",
        " lifecycle ",
        " permission ",
        " user_id ",
        " session_id ",
        " domain ",
        " product ",
    ):
        assert forbidden_semantic_column not in ddl
    for required_physical_column in (
        "authority_id",
        "current_revision",
        "revision",
        "cell_id",
        "link0",
        "link1",
        "atom",
    ):
        assert required_physical_column in ddl


def test_postgres_history_index_is_disposable_and_created_concurrently():
    ddl = _normalise_sql(_HISTORY_INDEX_DDL)
    assert ddl.startswith("create index concurrently if not exists ")
    assert (
        "on archhub_cell_versions(authority_id, cell_id, revision desc)"
        in ddl
    )
    for forbidden_semantic_column in (
        "kind",
        "role",
        "lifecycle",
        "permission",
        "session_id",
        "atom",
    ):
        assert forbidden_semantic_column not in ddl


@pytest.mark.parametrize(
    ("valid", "ready", "definition"),
    (
        (
            False,
            True,
            "CREATE INDEX archhub_cell_versions_cell_revision_idx "
            "ON archhub_cell_versions(authority_id, cell_id, revision DESC)",
        ),
        (
            True,
            False,
            "CREATE INDEX archhub_cell_versions_cell_revision_idx "
            "ON archhub_cell_versions(authority_id, cell_id, revision DESC)",
        ),
        (
            True,
            True,
            "CREATE INDEX archhub_cell_versions_cell_revision_idx "
            "ON archhub_cell_versions(authority_id, revision DESC)",
        ),
    ),
)
def test_postgres_rejects_an_invalid_or_wrong_same_name_history_index(
    valid,
    ready,
    definition,
):
    authority = _history_authority()
    fixture = _HistoryFixture(authority)
    connection = _ObservingPostgresConnection(fixture)
    connection.history_index_valid = valid
    connection.history_index_ready = ready
    connection.history_index_definition = definition

    with pytest.raises(
        InvalidCell,
        match="history index is invalid",
    ):
        PostgresCellJournal(
            "fixture-dsn",
            authority_id=fixture.authority_id,
            connection_factory=lambda _dsn: connection,
        )


@pytest.mark.skipif(
    not os.environ.get("ARCHHUB_TEST_POSTGRES_DSN"),
    reason="real PostgreSQL authority DSN is not configured",
)
def test_real_postgres_roundtrip_conflict_reopen_and_opaque_bytes():
    dsn = os.environ["ARCHHUB_TEST_POSTGRES_DSN"]
    authority_id = "court-" + uuid.uuid4().hex
    first = CellStore(journal=PostgresCellJournal(dsn, authority_id=authority_id))
    stale = CellStore(journal=PostgresCellJournal(dsn, authority_id=authority_id))
    try:
        first.commit(0, create=(_leaf("postgres:root", bytes(range(256))),))
        with pytest.raises(Conflict):
            stale.commit(0, create=(_leaf("postgres:stale", b"rejected"),))
        assert stale.revision == 1
        assert stale.read("postgres:root").atom == bytes(range(256))
        stale.commit(1, replace=(_leaf("postgres:root", b"accepted"),))
        assert first.refresh() == 2
        assert first.read("postgres:root").atom == b"accepted"
        first.commit(
            2,
            create=(
                Cell("postgres:cycle:a", "postgres:cycle:b", NULL_CELL_ID, b"a"),
                Cell("postgres:cycle:b", "postgres:cycle:a", NULL_CELL_ID, b"b"),
            ),
        )
        expected_digest = first.revision_chain_digest()
    finally:
        first.close()
        stale.close()

    reopened = CellStore(
        journal=PostgresCellJournal(dsn, authority_id=authority_id)
    )
    try:
        assert reopened.revision == 3
        assert reopened.at(1).cells["postgres:root"].atom == bytes(range(256))
        assert reopened.read("postgres:cycle:a").link0 == "postgres:cycle:b"
        assert reopened.read("postgres:cycle:b").link0 == "postgres:cycle:a"
        assert reopened.revision_chain_digest() == expected_digest
        with pytest.raises(InvalidCell, match="provider restore drill"):
            reopened.backup_to("not-a-postgres-backup.sqlite3")
    finally:
        reopened.close()


@pytest.mark.skipif(
    not os.environ.get("ARCHHUB_TEST_POSTGRES_DSN"),
    reason="real PostgreSQL authority DSN is not configured",
)
def test_real_postgres_transaction_interruption_has_no_partial_revision():
    dsn = os.environ["ARCHHUB_TEST_POSTGRES_DSN"]
    authority_id = "court-" + uuid.uuid4().hex

    def fail(stage):
        if stage == "before_commit":
            raise RuntimeError("injected pre-commit interruption")

    store = CellStore(
        journal=PostgresCellJournal(
            dsn,
            authority_id=authority_id,
            fault_injector=fail,
        )
    )
    with pytest.raises(RuntimeError, match="before_commit"):
        store.commit(0, create=(_leaf("postgres:rollback", b"no"),))
    store.close()

    reopened = CellStore(
        journal=PostgresCellJournal(dsn, authority_id=authority_id)
    )
    try:
        assert reopened.revision == 0
        assert "postgres:rollback" not in reopened.snapshot().cells
    finally:
        reopened.close()


@pytest.mark.skipif(
    not os.environ.get("ARCHHUB_TEST_POSTGRES_DSN"),
    reason="real PostgreSQL authority DSN is not configured",
)
def test_real_postgres_post_commit_interruption_recovers_complete_revision():
    dsn = os.environ["ARCHHUB_TEST_POSTGRES_DSN"]
    authority_id = "court-" + uuid.uuid4().hex

    def fail(stage):
        if stage == "after_commit":
            raise RuntimeError("injected post-commit interruption")

    store = CellStore(
        journal=PostgresCellJournal(
            dsn,
            authority_id=authority_id,
            fault_injector=fail,
        )
    )
    with pytest.raises(RuntimeError, match="after_commit"):
        store.commit(0, create=(_leaf("postgres:committed", b"yes"),))
    store.close()

    reopened = CellStore(
        journal=PostgresCellJournal(dsn, authority_id=authority_id)
    )
    try:
        assert reopened.revision == 1
        assert reopened.read("postgres:committed").atom == b"yes"
    finally:
        reopened.close()


@pytest.mark.skipif(
    not os.environ.get("ARCHHUB_TEST_POSTGRES_DSN"),
    reason="real PostgreSQL authority DSN is not configured",
)
def test_real_postgres_runtime_fence_and_exact_history_migration():
    dsn = os.environ["ARCHHUB_TEST_POSTGRES_DSN"]
    authority_id = "court-" + uuid.uuid4().hex
    first = CellStore(journal=PostgresCellJournal(dsn, authority_id=authority_id))
    second = CellStore(journal=PostgresCellJournal(dsn, authority_id=authority_id))
    release = first.acquire_runtime_fence("app:archhub")
    try:
        with pytest.raises(DatabaseOwnerConflict, match="active runtime owner"):
            second.acquire_runtime_fence("app:archhub")
    finally:
        release()
        first.close()
        second.close()

    source = CellStore()
    source.commit(0, create=(_leaf("postgres:migrate", b"before"),))
    source.commit(1, replace=(_leaf("postgres:migrate", b"after"),))
    destination_id = "court-" + uuid.uuid4().hex
    destination = CellStore(
        journal=PostgresCellJournal(dsn, authority_id=destination_id)
    )
    evidence = migrate_cell_history(source, destination)
    destination.close()

    restored = CellStore(
        journal=PostgresCellJournal(dsn, authority_id=destination_id)
    )
    try:
        assert restored.revision == evidence.destination_revision == 2
        assert restored.at(1).cells["postgres:migrate"].atom == b"before"
        assert restored.read("postgres:migrate").atom == b"after"
        assert restored.revision_chain_digest() == (
            evidence.revision_chain_digest
        )
    finally:
        restored.close()
