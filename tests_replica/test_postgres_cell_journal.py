"""PostgreSQL physical-authority courts for the Universal Cell floor."""
from __future__ import annotations

import os
import traceback
import uuid

import pytest

from nodelang.postgres_cell_journal import (
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
