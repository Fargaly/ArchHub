"""Courts for the external two-phase physical revision witness."""
from __future__ import annotations

import os
from types import MappingProxyType
import uuid

import pytest

from nodelang.external_revision_witness import (
    DynamoDbRevisionWitnessProvider,
    ExternalRevisionWitnessConflict,
    ExternalRevisionWitnessDenied,
    ExternalRevisionWitnessState,
    WitnessedCellJournal,
    revision_history_chain_digest,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    LoadedJournalHead,
    _SqliteJournal,
)


def _leaf(cell_id: str, atom: bytes) -> Cell:
    return Cell(cell_id, NULL_CELL_ID, NULL_CELL_ID, atom)


class FakeJournal:
    identity = "fake:journal:authority"
    backend = "fake"
    local_path = None
    exclusive_owner = False
    shared_writers = True

    def __init__(self, events=None):
        null = Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
        self.events = events if events is not None else []
        self.current = {null.id: null}
        self.revision = 0
        self.versions = {0: (null,)}
        self.changes = {0: (null.id,)}
        self.fault = None
        self.closed = False

    def load(self):
        return (
            MappingProxyType(dict(self.current)),
            self.revision,
            dict(self.versions),
            dict(self.changes),
        )

    def append(self, expected_revision, next_revision, changed):
        changed = tuple(changed)
        self.events.append(("journal", next_revision))
        if self.fault == "before":
            self.fault = None
            raise RuntimeError("injected journal interruption")
        if expected_revision != self.revision:
            raise InvalidCell("fake journal revision conflict")
        self.revision = next_revision
        self.versions[next_revision] = changed
        self.changes[next_revision] = tuple(
            sorted(cell.id for cell in changed)
        )
        self.current.update({cell.id: cell for cell in changed})
        if self.fault == "after":
            self.fault = None
            raise RuntimeError("injected journal interruption")

    def close(self):
        self.closed = True

    def backup_to(self, destination):
        raise InvalidCell("fake journal has no backup")

    def acquire_runtime_fence(self, resource_id):
        return lambda: None


class HeadBoundFakeHistory:
    def __init__(self, versions, head_revision):
        self._versions = {
            revision: tuple(changed)
            for revision, changed in versions.items()
            if revision <= head_revision
        }
        self._head_revision = head_revision
        self._head_digest = revision_history_chain_digest(
            self._versions,
            target_revision=head_revision,
        )

    @property
    def head_revision(self):
        return self._head_revision

    @property
    def head_digest(self):
        return self._head_digest

    def chain_digest(self, revision):
        if revision > self._head_revision:
            raise InvalidCell("history read exceeds captured head")
        return revision_history_chain_digest(
            self._versions,
            target_revision=revision,
        )


def _head_from_versions(versions, head_revision):
    current = {}
    for revision in range(head_revision + 1):
        for cell in versions[revision]:
            current[cell.id] = cell
    history = HeadBoundFakeHistory(versions, head_revision)
    return LoadedJournalHead(
        cells=MappingProxyType(current),
        revision=head_revision,
        revision_chain_digest=history.head_digest,
        history=history,
    )


class HeadBoundFakeJournal(FakeJournal):
    backend = "sqlite"
    exclusive_owner = True
    shared_writers = False

    def __init__(self, events=None):
        super().__init__(events)
        self.eager_load_calls = 0
        self.load_head_calls = 0
        self.next_head_override = None

    def load(self):
        self.eager_load_calls += 1
        raise AssertionError("built-in witnessed journal used eager load")

    def load_head(self):
        self.load_head_calls += 1
        if self.next_head_override is not None:
            loaded = self.next_head_override
            self.next_head_override = None
            return loaded
        return _head_from_versions(self.versions, self.revision)


class FakeWitness:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.state = None
        self.fail_confirm_once = False

    def read(self, authority_id):
        return self.state

    def initialize(self, authority_id, revision, digest):
        if self.state is not None:
            raise ExternalRevisionWitnessConflict("witness already exists")
        self.state = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=revision,
            confirmed_digest=digest,
        )
        self.events.append(("initialize", revision))
        return self.state

    def prepare(
        self,
        authority_id,
        expected_revision,
        expected_digest,
        next_revision,
        next_digest,
        token,
    ):
        state = self.state
        if (
            state is None
            or state.authority_id != authority_id
            or state.confirmed_revision != expected_revision
            or state.confirmed_digest != expected_digest
            or state.pending_token is not None
        ):
            raise ExternalRevisionWitnessConflict("witness prepare conflict")
        self.state = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=expected_revision,
            confirmed_digest=expected_digest,
            pending_revision=next_revision,
            pending_digest=next_digest,
            pending_token=token,
        )
        self.events.append(("prepare", next_revision))
        return self.state

    def confirm(self, authority_id, token):
        state = self.state
        if (
            state is None
            or state.authority_id != authority_id
            or state.pending_token != token
        ):
            raise ExternalRevisionWitnessConflict("witness confirm conflict")
        if self.fail_confirm_once:
            self.fail_confirm_once = False
            raise RuntimeError("injected witness interruption")
        self.state = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=state.pending_revision,
            confirmed_digest=state.pending_digest,
        )
        self.events.append(("confirm", self.state.confirmed_revision))
        return self.state

    def abort(self, authority_id, token):
        state = self.state
        if (
            state is None
            or state.authority_id != authority_id
            or state.pending_token != token
        ):
            raise ExternalRevisionWitnessConflict("witness abort conflict")
        self.state = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=state.confirmed_revision,
            confirmed_digest=state.confirmed_digest,
        )
        self.events.append(("abort", state.pending_revision))
        return self.state


def _wrapped(delegate=None, provider=None, *, provision=True, events=None):
    delegate = delegate or FakeJournal(events)
    provider = provider or FakeWitness(events)
    wrapper = WitnessedCellJournal(
        delegate,
        provider,
        authority_id="archhub-court",
        provision_genesis=provision,
    )
    return wrapper, delegate, provider


def test_witnessed_builtin_loads_and_reconciles_one_head_bound_digest():
    delegate = HeadBoundFakeJournal()
    provider = FakeWitness()
    wrapper = WitnessedCellJournal(
        delegate,
        provider,
        authority_id="archhub-court",
        provision_genesis=True,
    )

    loaded = wrapper.load_head()

    assert loaded.revision == 0
    assert loaded.revision_chain_digest == loaded.history.head_digest
    assert (
        loaded.revision_chain_digest
        == loaded.history.chain_digest(loaded.revision)
    )
    assert provider.state.confirmed_revision == loaded.revision
    assert provider.state.confirmed_digest == loaded.revision_chain_digest
    assert delegate.load_head_calls == 1
    assert delegate.eager_load_calls == 0


def test_witnessed_builtin_path_denies_eager_load_fallback():
    delegate = HeadBoundFakeJournal()
    wrapper = WitnessedCellJournal(
        delegate,
        FakeWitness(),
        authority_id="archhub-court",
        provision_genesis=True,
    )

    with pytest.raises(ExternalRevisionWitnessDenied, match="eager"):
        wrapper.load()

    assert delegate.eager_load_calls == 0


def test_ambiguous_append_reconciles_the_same_head_bound_commit():
    delegate = HeadBoundFakeJournal()
    provider = FakeWitness()
    wrapper = WitnessedCellJournal(
        delegate,
        provider,
        authority_id="archhub-court",
        provision_genesis=True,
    )
    wrapper.load_head()
    delegate.fault = "after"

    with pytest.raises(ExternalRevisionWitnessDenied, match="restart"):
        wrapper.append(0, 1, (_leaf("root", b"one"),))

    assert delegate.revision == 1
    assert provider.state.confirmed_revision == 1
    assert provider.state.pending_token is None
    assert delegate.load_head_calls == 2
    assert delegate.eager_load_calls == 0


@pytest.mark.parametrize("divergence", ("rollback", "split"))
def test_ambiguous_append_keeps_rollback_and_split_history_denied(divergence):
    delegate = HeadBoundFakeJournal()
    delegate.append(0, 1, (_leaf("root", b"one"),))
    accepted = _head_from_versions(delegate.versions, delegate.revision)
    provider = FakeWitness()
    provider.state = ExternalRevisionWitnessState(
        authority_id="archhub-court",
        confirmed_revision=accepted.revision,
        confirmed_digest=accepted.revision_chain_digest,
    )
    wrapper = WitnessedCellJournal(
        delegate,
        provider,
        authority_id="archhub-court",
    )
    wrapper.load_head()

    if divergence == "rollback":
        delegate.next_head_override = _head_from_versions(
            delegate.versions,
            0,
        )
    else:
        alternate = dict(delegate.versions)
        alternate[2] = (_leaf("root", b"split"),)
        delegate.next_head_override = _head_from_versions(alternate, 2)
    delegate.fault = "after"

    with pytest.raises(ExternalRevisionWitnessDenied):
        wrapper.append(1, 2, (_leaf("root", b"two"),))

    assert provider.state.confirmed_revision == 1
    assert provider.state.pending_revision == 2
    assert provider.state.pending_token is not None
    assert delegate.load_head_calls == 2
    assert delegate.eager_load_calls == 0


def test_witnessed_sqlite_reopens_with_lazy_history_and_exact_old_revision(
    tmp_path,
):
    path = tmp_path / "witnessed-lazy.sqlite3"
    provider = FakeWitness()
    first = CellStore(
        journal=WitnessedCellJournal(
            _SqliteJournal(path, None),
            provider,
            authority_id="archhub-sqlite-court",
            provision_genesis=True,
        )
    )
    first.commit(0, create=(_leaf("root", b"before"),))
    first_revision = first.revision
    first.commit(first_revision, replace=(_leaf("root", b"after"),))
    expected_digest = first.revision_chain_digest()
    first.close()

    reopened = CellStore(
        journal=WitnessedCellJournal(
            _SqliteJournal(path, None),
            provider,
            authority_id="archhub-sqlite-court",
        )
    )
    try:
        assert reopened.read("root").atom == b"after"
        assert reopened.at(first_revision).cells["root"].atom == b"before"
        assert reopened.revision_chain_digest() == expected_digest
        assert reopened.retention_stats()[
            "resident_history_version_cell_count"
        ] == 0
        assert not reopened._versions
    finally:
        reopened.close()


def test_witness_digest_matches_canonical_chain_and_orders_commit():
    events = []
    wrapper, _delegate, provider = _wrapped(events=events)
    store = CellStore(journal=wrapper)
    store.commit(store.revision, create=(_leaf("root", b"one"),))

    assert provider.state.confirmed_revision == store.revision == 1
    assert (
        provider.state.confirmed_digest
        == store.revision_chain_digest()
    )
    assert events[-3:] == [
        ("prepare", 1),
        ("journal", 1),
        ("confirm", 1),
    ]


def test_precommit_failure_aborts_exact_pending_and_can_retry():
    events = []
    wrapper, delegate, provider = _wrapped(events=events)
    store = CellStore(journal=wrapper)
    delegate.fault = "before"

    with pytest.raises(RuntimeError, match="journal interruption"):
        store.commit(store.revision, create=(_leaf("root", b"one"),))

    assert store.revision == 0
    assert provider.state.confirmed_revision == 0
    assert provider.state.pending_token is None
    assert events[-3:] == [
        ("prepare", 1),
        ("journal", 1),
        ("abort", 1),
    ]
    store.commit(store.revision, create=(_leaf("root", b"retry"),))
    assert store.revision == 1


def test_postcommit_ambiguity_is_reconciled_but_requires_restart():
    wrapper, delegate, provider = _wrapped()
    store = CellStore(journal=wrapper)
    delegate.fault = "after"

    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="restart",
    ):
        store.commit(store.revision, create=(_leaf("root", b"one"),))

    assert store.revision == 0
    assert delegate.revision == 1
    assert provider.state.confirmed_revision == 1
    with pytest.raises(ExternalRevisionWitnessDenied, match="faulted"):
        wrapper.load()

    reopened = CellStore(
        journal=WitnessedCellJournal(
            delegate,
            provider,
            authority_id="archhub-court",
        )
    )
    assert reopened.revision == 1
    assert reopened.read("root").atom == b"one"


def test_confirmation_failure_leaves_recoverable_pending_and_no_publication():
    wrapper, delegate, provider = _wrapped()
    store = CellStore(journal=wrapper)
    provider.fail_confirm_once = True

    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="restart",
    ):
        store.commit(store.revision, create=(_leaf("root", b"one"),))

    assert store.revision == 0
    assert delegate.revision == 1
    assert provider.state.confirmed_revision == 0
    assert provider.state.pending_revision == 1

    reopened = CellStore(
        journal=WitnessedCellJournal(
            delegate,
            provider,
            authority_id="archhub-court",
        )
    )
    assert reopened.revision == 1
    assert provider.state.confirmed_revision == 1
    assert provider.state.pending_token is None


def test_restart_aborts_an_exact_uncommitted_pending_revision():
    wrapper, delegate, provider = _wrapped()
    CellStore(journal=wrapper)
    provider.prepare(
        "archhub-court",
        provider.state.confirmed_revision,
        provider.state.confirmed_digest,
        1,
        "a" * 64,
        "pending-token",
    )

    reopened = CellStore(
        journal=WitnessedCellJournal(
            delegate,
            provider,
            authority_id="archhub-court",
        )
    )
    assert reopened.revision == 0
    assert provider.state.confirmed_revision == 0
    assert provider.state.pending_token is None


def test_missing_witness_requires_explicit_genesis_provisioning():
    delegate = FakeJournal()
    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="missing",
    ):
        CellStore(
            journal=WitnessedCellJournal(
                delegate,
                FakeWitness(),
                authority_id="archhub-court",
            )
        )

    store = CellStore(
        journal=WitnessedCellJournal(
            delegate,
            FakeWitness(),
            authority_id="archhub-court",
            provision_genesis=True,
        )
    )
    assert store.revision == 0

    established = FakeJournal()
    established.append(0, 1, (_leaf("root", b"one"),))
    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="established",
    ):
        CellStore(
            journal=WitnessedCellJournal(
                established,
                FakeWitness(),
                authority_id="archhub-court",
                provision_genesis=True,
            )
        )


def test_rollback_split_history_and_unexplained_forward_state_fail_closed():
    wrapper, current, provider = _wrapped()
    store = CellStore(journal=wrapper)
    store.commit(store.revision, create=(_leaf("root", b"one"),))

    old = FakeJournal()
    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="rolled back",
    ):
        CellStore(
            journal=WitnessedCellJournal(
                old,
                provider,
                authority_id="archhub-court",
            )
        )

    alternate = FakeJournal()
    alternate.append(0, 1, (_leaf("root", b"different"),))
    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="digest",
    ):
        CellStore(
            journal=WitnessedCellJournal(
                alternate,
                provider,
                authority_id="archhub-court",
            )
        )

    provider_without_pending = FakeWitness()
    genesis = WitnessedCellJournal(
        FakeJournal(),
        provider_without_pending,
        authority_id="archhub-court",
        provision_genesis=True,
    )
    CellStore(journal=genesis)
    ahead = FakeJournal()
    ahead.append(0, 1, (_leaf("root", b"unexplained"),))
    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="ahead",
    ):
        CellStore(
            journal=WitnessedCellJournal(
                ahead,
                provider_without_pending,
                authority_id="archhub-court",
            )
        )


def test_malformed_or_competing_pending_state_fails_closed():
    delegate = FakeJournal()
    provider = FakeWitness()
    malformed = object.__new__(ExternalRevisionWitnessState)
    object.__setattr__(malformed, "authority_id", "archhub-court")
    object.__setattr__(malformed, "confirmed_revision", 0)
    object.__setattr__(malformed, "confirmed_digest", "0" * 64)
    object.__setattr__(malformed, "pending_revision", 2)
    object.__setattr__(malformed, "pending_digest", "1" * 64)
    object.__setattr__(malformed, "pending_token", "bad")
    provider.state = malformed
    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="pending",
    ):
        CellStore(
            journal=WitnessedCellJournal(
                delegate,
                provider,
                authority_id="archhub-court",
            )
        )


def test_active_commit_conflict_never_aborts_a_foreign_pending_operation():
    wrapper, _delegate, provider = _wrapped()
    store = CellStore(journal=wrapper)
    provider.prepare(
        "archhub-court",
        provider.state.confirmed_revision,
        provider.state.confirmed_digest,
        1,
        "a" * 64,
        "foreign-token",
    )

    with pytest.raises(
        ExternalRevisionWitnessConflict,
        match="prepare",
    ):
        store.commit(
            store.revision,
            create=(_leaf("root", b"must-not-commit"),),
        )

    assert provider.state.pending_token == "foreign-token"
    assert provider.state.pending_revision == 1


class FakeDynamoError(RuntimeError):
    def __init__(self, code, message="provider-secret-message"):
        super().__init__(message)
        self.response = {
            "Error": {
                "Code": code,
                "Message": message,
            }
        }


class FakeDynamoClient:
    def __init__(self):
        self.calls = []
        self.item = None
        self.fail = None

    def _record(self, operation, kwargs):
        self.calls.append((operation, kwargs))
        if self.fail is not None:
            failure = self.fail
            self.fail = None
            raise failure

    def get_item(self, **kwargs):
        self._record("get_item", kwargs)
        return {} if self.item is None else {"Item": dict(self.item)}

    def put_item(self, **kwargs):
        self._record("put_item", kwargs)
        self.item = dict(kwargs["Item"])
        return {}

    def update_item(self, **kwargs):
        self._record("update_item", kwargs)
        values = kwargs["ExpressionAttributeValues"]
        expression = kwargs["UpdateExpression"]
        if expression.startswith("SET #pending_revision"):
            self.item["pending_revision"] = values[":next_revision"]
            self.item["pending_digest"] = values[":next_digest"]
            self.item["pending_token"] = values[":token"]
        elif expression.startswith("SET #confirmed_revision"):
            self.item["confirmed_revision"] = self.item["pending_revision"]
            self.item["confirmed_digest"] = self.item["pending_digest"]
            self.item.pop("pending_revision")
            self.item.pop("pending_digest")
            self.item.pop("pending_token")
        elif expression.startswith("REMOVE #pending_revision"):
            self.item.pop("pending_revision")
            self.item.pop("pending_digest")
            self.item.pop("pending_token")
        return {"Attributes": dict(self.item)}


def _dynamo_item(
    *,
    authority="archhub-court",
    confirmed_revision=0,
    confirmed_digest="a" * 64,
    pending=None,
):
    item = {
        "authority_id": {"S": authority},
        "confirmed_revision": {"N": str(confirmed_revision)},
        "confirmed_digest": {"S": confirmed_digest},
    }
    if pending is not None:
        revision, digest, token = pending
        item.update(
            {
                "pending_revision": {"N": str(revision)},
                "pending_digest": {"S": digest},
                "pending_token": {"S": token},
            }
        )
    return item


def test_dynamodb_witness_reads_the_exact_item_strongly_consistently():
    client = FakeDynamoClient()
    client.item = _dynamo_item()
    provider = DynamoDbRevisionWitnessProvider(
        "archhub-revision-witness",
        client=client,
    )

    state = provider.read("archhub-court")

    assert state.confirmed_revision == 0
    assert client.calls == [
        (
            "get_item",
            {
                "TableName": "archhub-revision-witness",
                "Key": {"authority_id": {"S": "archhub-court"}},
                "ConsistentRead": True,
            },
        )
    ]


def test_dynamodb_witness_initializes_only_an_absent_exact_identity():
    client = FakeDynamoClient()
    provider = DynamoDbRevisionWitnessProvider(
        "archhub-revision-witness",
        client=client,
    )

    state = provider.initialize("archhub-court", 0, "a" * 64)

    operation, kwargs = client.calls[-1]
    assert operation == "put_item"
    assert kwargs["ConditionExpression"] == "attribute_not_exists(#authority)"
    assert kwargs["ExpressionAttributeNames"] == {
        "#authority": "authority_id",
    }
    assert state == ExternalRevisionWitnessState(
        authority_id="archhub-court",
        confirmed_revision=0,
        confirmed_digest="a" * 64,
    )


def test_dynamodb_witness_uses_exact_prepare_confirm_and_abort_conditions():
    client = FakeDynamoClient()
    client.item = _dynamo_item()
    provider = DynamoDbRevisionWitnessProvider(
        "archhub-revision-witness",
        client=client,
    )

    pending = provider.prepare(
        "archhub-court",
        0,
        "a" * 64,
        1,
        "b" * 64,
        "token-one",
    )
    operation, prepare = client.calls[-1]
    assert operation == "update_item"
    assert prepare["ConditionExpression"] == (
        "#confirmed_revision = :expected_revision AND "
        "#confirmed_digest = :expected_digest AND "
        "attribute_not_exists(#pending_token)"
    )
    assert pending.pending_token == "token-one"

    confirmed = provider.confirm("archhub-court", "token-one")
    operation, confirm = client.calls[-1]
    assert operation == "update_item"
    assert confirm["ConditionExpression"] == (
        "#pending_token = :token AND "
        "#pending_revision = :pending_revision AND "
        "#pending_digest = :pending_digest"
    )
    assert confirmed.confirmed_revision == 1
    assert confirmed.pending_token is None

    provider.prepare(
        "archhub-court",
        1,
        "b" * 64,
        2,
        "c" * 64,
        "token-two",
    )
    aborted = provider.abort("archhub-court", "token-two")
    operation, abort = client.calls[-1]
    assert operation == "update_item"
    assert abort["ConditionExpression"] == (
        "#pending_token = :token AND "
        "#confirmed_revision = :confirmed_revision AND "
        "#confirmed_digest = :confirmed_digest"
    )
    assert aborted.confirmed_revision == 1
    assert aborted.pending_token is None


def test_dynamodb_witness_conflicts_and_failures_are_secret_safe():
    client = FakeDynamoClient()
    client.fail = FakeDynamoError("ConditionalCheckFailedException")
    provider = DynamoDbRevisionWitnessProvider(
        "archhub-revision-witness",
        client=client,
    )
    with pytest.raises(ExternalRevisionWitnessConflict):
        provider.initialize("archhub-court", 0, "a" * 64)

    client.fail = FakeDynamoError(
        "AccessDeniedException",
        "provider-secret-message archhub-revision-witness",
    )
    with pytest.raises(ExternalRevisionWitnessDenied) as captured:
        provider.read("archhub-court")
    rendered = str(captured.value)
    assert "provider-secret-message" not in rendered
    assert "archhub-revision-witness" not in rendered


def test_dynamodb_witness_rejects_malformed_or_extra_provider_records():
    client = FakeDynamoClient()
    provider = DynamoDbRevisionWitnessProvider(
        "archhub-revision-witness",
        client=client,
    )
    client.item = {
        **_dynamo_item(),
        "hidden_semantic_blob": {"S": "not-admitted"},
    }
    with pytest.raises(
        ExternalRevisionWitnessDenied,
        match="shape",
    ):
        provider.read("archhub-court")


def test_real_dynamodb_witness_has_pitr_and_conditional_round_trip():
    table = os.environ.get("ARCHHUB_TEST_DYNAMODB_WITNESS_TABLE")
    if not table:
        pytest.skip("real DynamoDB witness table is not admitted")
    try:
        import boto3
    except ImportError:
        pytest.skip("boto3 is unavailable")
    client = boto3.client("dynamodb")
    recovery = client.describe_continuous_backups(TableName=table)
    status = recovery["ContinuousBackupsDescription"][
        "PointInTimeRecoveryDescription"
    ]["PointInTimeRecoveryStatus"]
    assert status == "ENABLED"

    authority = "archhub-provider-court-" + uuid.uuid4().hex
    provider = DynamoDbRevisionWitnessProvider(table, client=client)
    created = False
    try:
        initialized = provider.initialize(authority, 0, "a" * 64)
        created = True
        assert provider.read(authority) == initialized
        pending = provider.prepare(
            authority,
            0,
            "a" * 64,
            1,
            "b" * 64,
            "provider-court-token",
        )
        assert pending.pending_revision == 1
        assert provider.abort(authority, "provider-court-token") == initialized
    finally:
        if created:
            client.delete_item(
                TableName=table,
                Key={"authority_id": {"S": authority}},
                ConditionExpression="attribute_exists(authority_id)",
            )
