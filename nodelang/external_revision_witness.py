"""Two-phase physical rollback witness for one Universal Cell journal.

The witness stores no semantic application facts. It commits only to the
existing physical revision-chain digest and wraps one admitted CellJournal.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import re
import secrets
from typing import Callable, Iterable, Mapping, Protocol

from .universal_cell import (
    Cell,
    CellJournal,
    InvalidCell,
    LoadedJournalHead,
    revision_chain_digest_step,
)


class ExternalRevisionWitnessDenied(InvalidCell):
    """Witness state cannot safely admit the physical journal."""


class ExternalRevisionWitnessConflict(ExternalRevisionWitnessDenied):
    """A conditional witness transition lost to another operation."""


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class ExternalRevisionWitnessState:
    """Exact physical head and optional one-step commit intent."""

    authority_id: str
    confirmed_revision: int
    confirmed_digest: str
    pending_revision: int | None = None
    pending_digest: str | None = None
    pending_token: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.authority_id, str)
            or not self.authority_id
            or len(self.authority_id.encode("utf-8")) > 256
        ):
            raise ExternalRevisionWitnessDenied(
                "external revision witness authority is invalid"
            )
        if (
            type(self.confirmed_revision) is not int
            or self.confirmed_revision < 0
            or not _is_digest(self.confirmed_digest)
        ):
            raise ExternalRevisionWitnessDenied(
                "external revision witness confirmed head is invalid"
            )
        pending = (
            self.pending_revision,
            self.pending_digest,
            self.pending_token,
        )
        if all(value is None for value in pending):
            return
        if any(value is None for value in pending):
            raise ExternalRevisionWitnessDenied(
                "external revision witness pending state is incomplete"
            )
        if (
            type(self.pending_revision) is not int
            or self.pending_revision != self.confirmed_revision + 1
            or not _is_digest(self.pending_digest)
            or not isinstance(self.pending_token, str)
            or not self.pending_token
            or len(self.pending_token.encode("utf-8")) > 256
        ):
            raise ExternalRevisionWitnessDenied(
                "external revision witness pending state is invalid"
            )


class ExternalRevisionWitnessProvider(Protocol):
    """Conditional physical custody below the Cell semantic floor."""

    def read(
        self, authority_id: str
    ) -> ExternalRevisionWitnessState | None: ...

    def initialize(
        self,
        authority_id: str,
        revision: int,
        digest: str,
    ) -> ExternalRevisionWitnessState: ...

    def prepare(
        self,
        authority_id: str,
        expected_revision: int,
        expected_digest: str,
        next_revision: int,
        next_digest: str,
        token: str,
    ) -> ExternalRevisionWitnessState: ...

    def confirm(
        self,
        authority_id: str,
        token: str,
    ) -> ExternalRevisionWitnessState: ...

    def abort(
        self,
        authority_id: str,
        token: str,
    ) -> ExternalRevisionWitnessState: ...


_DYNAMODB_TABLE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")
_DYNAMODB_BASE_FIELDS = frozenset(
    ("authority_id", "confirmed_revision", "confirmed_digest")
)
_DYNAMODB_PENDING_FIELDS = frozenset(
    ("pending_revision", "pending_digest", "pending_token")
)


class DynamoDbRevisionWitnessProvider:
    """AWS DynamoDB conditional custody for one physical witness item."""

    def __init__(self, table_name: str, *, client=None) -> None:
        if (
            not isinstance(table_name, str)
            or _DYNAMODB_TABLE_PATTERN.fullmatch(table_name) is None
        ):
            raise ExternalRevisionWitnessDenied(
                "external revision witness table identity is invalid"
            )
        self._table_name = table_name
        self._client = client

    def __repr__(self) -> str:
        return "DynamoDbRevisionWitnessProvider(<redacted>)"

    def _dynamodb(self):
        if self._client is None:
            try:
                import boto3

                self._client = boto3.client("dynamodb")
            except Exception as exc:
                raise ExternalRevisionWitnessDenied(
                    "external revision witness provider is unavailable"
                ) from exc
        return self._client

    @staticmethod
    def _error_code(exc: Exception) -> str:
        try:
            response = exc.response
            return str(response["Error"]["Code"])
        except Exception:
            return ""

    def _call(self, operation: str, **kwargs):
        try:
            return getattr(self._dynamodb(), operation)(**kwargs)
        except Exception as exc:
            if self._error_code(exc) in (
                "ConditionalCheckFailedException",
                "TransactionConflictException",
            ):
                raise ExternalRevisionWitnessConflict(
                    "external revision witness condition changed"
                ) from exc
            raise ExternalRevisionWitnessDenied(
                "external revision witness provider is unavailable"
            ) from exc

    @staticmethod
    def _key(authority_id: str) -> dict[str, dict[str, str]]:
        if (
            not isinstance(authority_id, str)
            or not authority_id
            or len(authority_id.encode("utf-8")) > 256
        ):
            raise ExternalRevisionWitnessDenied(
                "external revision witness authority is invalid"
            )
        return {"authority_id": {"S": authority_id}}

    @staticmethod
    def _number(value: int) -> dict[str, str]:
        return {"N": str(value)}

    @staticmethod
    def _string(value: str) -> dict[str, str]:
        return {"S": value}

    @staticmethod
    def _decode_scalar(
        item: Mapping[str, Mapping[str, str]],
        name: str,
        wire_type: str,
    ) -> str:
        try:
            wire = item[name]
            if set(wire) != {wire_type}:
                raise ValueError
            value = wire[wire_type]
        except Exception as exc:
            raise ExternalRevisionWitnessDenied(
                "external revision witness record shape is invalid"
            ) from exc
        if not isinstance(value, str):
            raise ExternalRevisionWitnessDenied(
                "external revision witness record shape is invalid"
            )
        return value

    def _decode(
        self,
        item: Mapping[str, Mapping[str, str]],
    ) -> ExternalRevisionWitnessState:
        if not isinstance(item, Mapping):
            raise ExternalRevisionWitnessDenied(
                "external revision witness record shape is invalid"
            )
        names = frozenset(item)
        if names not in (
            _DYNAMODB_BASE_FIELDS,
            _DYNAMODB_BASE_FIELDS | _DYNAMODB_PENDING_FIELDS,
        ):
            raise ExternalRevisionWitnessDenied(
                "external revision witness record shape is invalid"
            )
        raw_confirmed = self._decode_scalar(
            item, "confirmed_revision", "N"
        )
        if not raw_confirmed.isascii() or not raw_confirmed.isdecimal():
            raise ExternalRevisionWitnessDenied(
                "external revision witness record shape is invalid"
            )
        values = {
            "authority_id": self._decode_scalar(item, "authority_id", "S"),
            "confirmed_revision": int(raw_confirmed),
            "confirmed_digest": self._decode_scalar(
                item, "confirmed_digest", "S"
            ),
        }
        if names == _DYNAMODB_BASE_FIELDS | _DYNAMODB_PENDING_FIELDS:
            raw_pending = self._decode_scalar(
                item, "pending_revision", "N"
            )
            if not raw_pending.isascii() or not raw_pending.isdecimal():
                raise ExternalRevisionWitnessDenied(
                    "external revision witness record shape is invalid"
                )
            values.update(
                {
                    "pending_revision": int(raw_pending),
                    "pending_digest": self._decode_scalar(
                        item, "pending_digest", "S"
                    ),
                    "pending_token": self._decode_scalar(
                        item, "pending_token", "S"
                    ),
                }
            )
        return ExternalRevisionWitnessState(**values)

    def read(
        self,
        authority_id: str,
    ) -> ExternalRevisionWitnessState | None:
        response = self._call(
            "get_item",
            TableName=self._table_name,
            Key=self._key(authority_id),
            ConsistentRead=True,
        )
        if not isinstance(response, Mapping) or "Item" not in response:
            return None
        state = self._decode(response["Item"])
        if state.authority_id != authority_id:
            raise ExternalRevisionWitnessDenied(
                "external revision witness identity is invalid"
            )
        return state

    def initialize(
        self,
        authority_id: str,
        revision: int,
        digest: str,
    ) -> ExternalRevisionWitnessState:
        state = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=revision,
            confirmed_digest=digest,
        )
        if revision != 0:
            raise ExternalRevisionWitnessDenied(
                "external revision witness genesis revision is invalid"
            )
        self._call(
            "put_item",
            TableName=self._table_name,
            Item={
                **self._key(authority_id),
                "confirmed_revision": self._number(revision),
                "confirmed_digest": self._string(digest),
            },
            ConditionExpression="attribute_not_exists(#authority)",
            ExpressionAttributeNames={"#authority": "authority_id"},
        )
        return state

    def prepare(
        self,
        authority_id: str,
        expected_revision: int,
        expected_digest: str,
        next_revision: int,
        next_digest: str,
        token: str,
    ) -> ExternalRevisionWitnessState:
        state = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=expected_revision,
            confirmed_digest=expected_digest,
            pending_revision=next_revision,
            pending_digest=next_digest,
            pending_token=token,
        )
        response = self._call(
            "update_item",
            TableName=self._table_name,
            Key=self._key(authority_id),
            UpdateExpression=(
                "SET #pending_revision = :next_revision, "
                "#pending_digest = :next_digest, "
                "#pending_token = :token"
            ),
            ConditionExpression=(
                "#confirmed_revision = :expected_revision AND "
                "#confirmed_digest = :expected_digest AND "
                "attribute_not_exists(#pending_token)"
            ),
            ExpressionAttributeNames={
                "#confirmed_revision": "confirmed_revision",
                "#confirmed_digest": "confirmed_digest",
                "#pending_revision": "pending_revision",
                "#pending_digest": "pending_digest",
                "#pending_token": "pending_token",
            },
            ExpressionAttributeValues={
                ":expected_revision": self._number(expected_revision),
                ":expected_digest": self._string(expected_digest),
                ":next_revision": self._number(next_revision),
                ":next_digest": self._string(next_digest),
                ":token": self._string(token),
            },
            ReturnValues="ALL_NEW",
        )
        if isinstance(response, Mapping) and "Attributes" in response:
            returned = self._decode(response["Attributes"])
            if returned != state:
                raise ExternalRevisionWitnessDenied(
                    "external revision witness prepared the wrong head"
                )
        return state

    def _pending(
        self,
        authority_id: str,
        token: str,
    ) -> ExternalRevisionWitnessState:
        state = self.read(authority_id)
        if state is None or state.pending_token != token:
            raise ExternalRevisionWitnessConflict(
                "external revision witness pending operation changed"
            )
        return state

    def confirm(
        self,
        authority_id: str,
        token: str,
    ) -> ExternalRevisionWitnessState:
        state = self._pending(authority_id, token)
        response = self._call(
            "update_item",
            TableName=self._table_name,
            Key=self._key(authority_id),
            UpdateExpression=(
                "SET #confirmed_revision = :pending_revision, "
                "#confirmed_digest = :pending_digest "
                "REMOVE #pending_revision, #pending_digest, #pending_token"
            ),
            ConditionExpression=(
                "#pending_token = :token AND "
                "#pending_revision = :pending_revision AND "
                "#pending_digest = :pending_digest"
            ),
            ExpressionAttributeNames={
                "#confirmed_revision": "confirmed_revision",
                "#confirmed_digest": "confirmed_digest",
                "#pending_revision": "pending_revision",
                "#pending_digest": "pending_digest",
                "#pending_token": "pending_token",
            },
            ExpressionAttributeValues={
                ":pending_revision": self._number(state.pending_revision),
                ":pending_digest": self._string(state.pending_digest),
                ":token": self._string(token),
            },
            ReturnValues="ALL_NEW",
        )
        confirmed = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=state.pending_revision,
            confirmed_digest=state.pending_digest,
        )
        if isinstance(response, Mapping) and "Attributes" in response:
            returned = self._decode(response["Attributes"])
            if returned != confirmed:
                raise ExternalRevisionWitnessDenied(
                    "external revision witness confirmed the wrong head"
                )
        return confirmed

    def abort(
        self,
        authority_id: str,
        token: str,
    ) -> ExternalRevisionWitnessState:
        state = self._pending(authority_id, token)
        response = self._call(
            "update_item",
            TableName=self._table_name,
            Key=self._key(authority_id),
            UpdateExpression=(
                "REMOVE #pending_revision, #pending_digest, #pending_token"
            ),
            ConditionExpression=(
                "#pending_token = :token AND "
                "#confirmed_revision = :confirmed_revision AND "
                "#confirmed_digest = :confirmed_digest"
            ),
            ExpressionAttributeNames={
                "#confirmed_revision": "confirmed_revision",
                "#confirmed_digest": "confirmed_digest",
                "#pending_revision": "pending_revision",
                "#pending_digest": "pending_digest",
                "#pending_token": "pending_token",
            },
            ExpressionAttributeValues={
                ":confirmed_revision": self._number(
                    state.confirmed_revision
                ),
                ":confirmed_digest": self._string(
                    state.confirmed_digest
                ),
                ":token": self._string(token),
            },
            ReturnValues="ALL_NEW",
        )
        aborted = ExternalRevisionWitnessState(
            authority_id=authority_id,
            confirmed_revision=state.confirmed_revision,
            confirmed_digest=state.confirmed_digest,
        )
        if isinstance(response, Mapping) and "Attributes" in response:
            returned = self._decode(response["Attributes"])
            if returned != aborted:
                raise ExternalRevisionWitnessDenied(
                    "external revision witness aborted the wrong operation"
                )
        return aborted


def _advance_chain_digest(
    previous: bytes,
    revision: int,
    changed: Iterable[Cell],
) -> bytes:
    try:
        return revision_chain_digest_step(previous, revision, changed)
    except InvalidCell as exc:
        raise ExternalRevisionWitnessDenied(str(exc)) from exc


def revision_history_chain_digest(
    versions: Mapping[int, tuple[Cell, ...]],
    *,
    target_revision: int | None = None,
) -> str:
    """Compute the canonical physical chain digest from retained versions."""
    if not versions:
        raise ExternalRevisionWitnessDenied(
            "Cell revision history is empty"
        )
    target = max(versions) if target_revision is None else target_revision
    if (
        type(target) is not int
        or target < 0
        or set(versions).intersection(range(target + 1))
        != set(range(target + 1))
    ):
        raise ExternalRevisionWitnessDenied(
            "Cell revision history is discontinuous"
        )
    previous = b"\x00" * 32
    for revision in range(target + 1):
        previous = _advance_chain_digest(
            previous,
            revision,
            versions[revision],
        )
    return previous.hex()


def _same_digest(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


class WitnessedCellJournal:
    """CellJournal wrapper that externally witnesses every durable revision."""

    def __init__(
        self,
        journal: CellJournal,
        provider: ExternalRevisionWitnessProvider,
        *,
        authority_id: str,
        provision_genesis: bool = False,
    ) -> None:
        if not isinstance(authority_id, str) or not authority_id:
            raise ExternalRevisionWitnessDenied(
                "external revision witness authority is invalid"
            )
        self._journal = journal
        self._provider = provider
        self._authority_id = authority_id
        self._provision_genesis = bool(provision_genesis)
        self._loaded = False
        self._head_revision = -1
        self._head_digest = ""
        self._faulted = False

    @property
    def identity(self) -> str:
        return self._journal.identity

    @property
    def backend(self) -> str:
        return self._journal.backend

    @property
    def local_path(self) -> str | None:
        return self._journal.local_path

    @property
    def exclusive_owner(self) -> bool:
        return self._journal.exclusive_owner

    @property
    def shared_writers(self) -> bool:
        return self._journal.shared_writers

    @property
    def supports_lazy_history(self) -> bool:
        return callable(getattr(self._journal, "load_head", None))

    def _require_usable(self) -> None:
        if self._faulted:
            raise ExternalRevisionWitnessDenied(
                "external revision witness is faulted; restart is required"
            )

    def _provider_call(self, operation: str, *args):
        try:
            return getattr(self._provider, operation)(*args)
        except (
            ExternalRevisionWitnessDenied,
            ExternalRevisionWitnessConflict,
        ):
            raise
        except Exception as exc:
            raise ExternalRevisionWitnessDenied(
                "external revision witness provider is unavailable"
            ) from exc

    def _validate_state(
        self,
        state: ExternalRevisionWitnessState,
    ) -> ExternalRevisionWitnessState:
        if not isinstance(state, ExternalRevisionWitnessState):
            raise ExternalRevisionWitnessDenied(
                "external revision witness identity is invalid"
            )
        try:
            validated = ExternalRevisionWitnessState(
                authority_id=state.authority_id,
                confirmed_revision=state.confirmed_revision,
                confirmed_digest=state.confirmed_digest,
                pending_revision=state.pending_revision,
                pending_digest=state.pending_digest,
                pending_token=state.pending_token,
            )
        except ExternalRevisionWitnessDenied:
            raise
        except Exception as exc:
            raise ExternalRevisionWitnessDenied(
                "external revision witness state is invalid"
            ) from exc
        if validated.authority_id != self._authority_id:
            raise ExternalRevisionWitnessDenied(
                "external revision witness identity is invalid"
            )
        return validated

    def _reconcile(
        self,
        state: ExternalRevisionWitnessState,
        revision: int,
        digest: str,
    ) -> ExternalRevisionWitnessState:
        state = self._validate_state(state)
        if state.pending_token is not None:
            if (
                revision == state.confirmed_revision
                and _same_digest(digest, state.confirmed_digest)
            ):
                state = self._validate_state(
                    self._provider_call(
                        "abort",
                        self._authority_id,
                        state.pending_token,
                    )
                )
            elif (
                revision == state.pending_revision
                and _same_digest(digest, state.pending_digest)
            ):
                state = self._validate_state(
                    self._provider_call(
                        "confirm",
                        self._authority_id,
                        state.pending_token,
                    )
                )
            elif revision < state.confirmed_revision:
                raise ExternalRevisionWitnessDenied(
                    "durable Cell authority was rolled back behind its witness"
                )
            elif revision == state.confirmed_revision:
                raise ExternalRevisionWitnessDenied(
                    "durable Cell authority digest differs from its witness"
                )
            else:
                raise ExternalRevisionWitnessDenied(
                    "durable Cell authority does not match pending witness state"
                )
        if revision < state.confirmed_revision:
            raise ExternalRevisionWitnessDenied(
                "durable Cell authority was rolled back behind its witness"
            )
        if revision > state.confirmed_revision:
            raise ExternalRevisionWitnessDenied(
                "durable Cell authority is ahead of its witness"
            )
        if not _same_digest(digest, state.confirmed_digest):
            raise ExternalRevisionWitnessDenied(
                "durable Cell authority digest differs from its witness"
            )
        return state

    def load(self):
        if self.supports_lazy_history:
            raise ExternalRevisionWitnessDenied(
                "eager durable history loading is forbidden"
            )
        self._require_usable()
        loaded = self._journal.load()
        _cells, revision, versions, _changes = loaded
        digest = revision_history_chain_digest(
            versions,
            target_revision=revision,
        )
        state = self._provider_call("read", self._authority_id)
        if state is None:
            if not self._provision_genesis:
                raise ExternalRevisionWitnessDenied(
                    "external revision witness is missing"
                )
            if revision != 0:
                raise ExternalRevisionWitnessDenied(
                    "an established Cell authority has no external witness"
                )
            state = self._provider_call(
                "initialize",
                self._authority_id,
                revision,
                digest,
            )
            self._provision_genesis = False
        state = self._reconcile(state, revision, digest)
        self._head_revision = state.confirmed_revision
        self._head_digest = state.confirmed_digest
        self._loaded = True
        return loaded

    def load_head(self) -> LoadedJournalHead:
        """Reconcile one same-head lazy journal view with its witness."""
        self._require_usable()
        if not self.supports_lazy_history:
            raise ExternalRevisionWitnessDenied(
                "head-bound durable history is unavailable"
            )
        loaded = self._journal.load_head()
        if type(loaded) is not LoadedJournalHead:
            raise ExternalRevisionWitnessDenied(
                "head-bound durable history shape is invalid"
            )
        revision = loaded.revision
        digest = loaded.revision_chain_digest
        if (
            loaded.history.head_revision != revision
            or not _same_digest(loaded.history.head_digest, digest)
            or not _same_digest(
                loaded.history.chain_digest(revision),
                digest,
            )
        ):
            raise ExternalRevisionWitnessDenied(
                "head-bound durable history digest is inconsistent"
            )
        state = self._provider_call("read", self._authority_id)
        if state is None:
            if not self._provision_genesis:
                raise ExternalRevisionWitnessDenied(
                    "external revision witness is missing"
                )
            if revision != 0:
                raise ExternalRevisionWitnessDenied(
                    "an established Cell authority has no external witness"
                )
            state = self._provider_call(
                "initialize",
                self._authority_id,
                revision,
                digest,
            )
            self._provision_genesis = False
        state = self._reconcile(state, revision, digest)
        self._head_revision = state.confirmed_revision
        self._head_digest = state.confirmed_digest
        self._loaded = True
        return loaded

    def _abort_after_failed_append(
        self,
        token: str,
        expected_revision: int,
        expected_digest: str,
        next_revision: int,
        next_digest: str,
        original: Exception,
    ) -> None:
        try:
            if self.supports_lazy_history:
                loaded = self._journal.load_head()
                if type(loaded) is not LoadedJournalHead:
                    raise ExternalRevisionWitnessDenied(
                        "head-bound durable history shape is invalid"
                    )
                actual_revision = loaded.revision
                actual_digest = loaded.revision_chain_digest
                if (
                    loaded.history.head_revision != actual_revision
                    or not _same_digest(
                        loaded.history.chain_digest(actual_revision),
                        actual_digest,
                    )
                ):
                    raise ExternalRevisionWitnessDenied(
                        "head-bound durable history digest is inconsistent"
                    )
            else:
                loaded = self._journal.load()
                _cells, actual_revision, versions, _changes = loaded
                actual_digest = revision_history_chain_digest(
                    versions,
                    target_revision=actual_revision,
                )
            if (
                actual_revision == expected_revision
                and _same_digest(actual_digest, expected_digest)
            ):
                state = self._validate_state(
                    self._provider_call(
                        "abort",
                        self._authority_id,
                        token,
                    )
                )
                self._head_revision = state.confirmed_revision
                self._head_digest = state.confirmed_digest
                return
            if (
                actual_revision == next_revision
                and _same_digest(actual_digest, next_digest)
            ):
                self._provider_call(
                    "confirm",
                    self._authority_id,
                    token,
                )
                self._faulted = True
                raise ExternalRevisionWitnessDenied(
                    "journal commit outcome was reconciled; restart is required"
                ) from original
        except ExternalRevisionWitnessDenied:
            self._faulted = True
            raise
        except Exception:
            self._faulted = True
            raise ExternalRevisionWitnessDenied(
                "journal commit outcome is ambiguous; restart is required"
            ) from original
        self._faulted = True
        raise ExternalRevisionWitnessDenied(
            "journal commit outcome does not match its witness; restart is required"
        ) from original

    def append(
        self,
        expected_revision: int,
        next_revision: int,
        changed: Iterable[Cell],
    ) -> None:
        self._require_usable()
        if not self._loaded:
            raise ExternalRevisionWitnessDenied(
                "external revision witness was not reconciled"
            )
        if (
            expected_revision != self._head_revision
            or next_revision != expected_revision + 1
        ):
            raise ExternalRevisionWitnessConflict(
                "external revision witness head changed"
            )
        changed = tuple(changed)
        next_digest = _advance_chain_digest(
            bytes.fromhex(self._head_digest),
            next_revision,
            changed,
        ).hex()
        token = secrets.token_hex(32)
        pending = self._validate_state(
            self._provider_call(
                "prepare",
                self._authority_id,
                expected_revision,
                self._head_digest,
                next_revision,
                next_digest,
                token,
            )
        )
        if (
            pending.pending_token != token
            or pending.pending_revision != next_revision
            or not _same_digest(pending.pending_digest, next_digest)
        ):
            self._faulted = True
            raise ExternalRevisionWitnessDenied(
                "external revision witness prepared the wrong head"
            )
        try:
            self._journal.append(
                expected_revision,
                next_revision,
                changed,
            )
        except Exception as exc:
            self._abort_after_failed_append(
                token,
                expected_revision,
                self._head_digest,
                next_revision,
                next_digest,
                exc,
            )
            raise
        try:
            confirmed = self._validate_state(
                self._provider_call(
                    "confirm",
                    self._authority_id,
                    token,
                )
            )
        except Exception as exc:
            self._faulted = True
            raise ExternalRevisionWitnessDenied(
                "journal commit awaits witness confirmation; restart is required"
            ) from exc
        if (
            confirmed.pending_token is not None
            or confirmed.confirmed_revision != next_revision
            or not _same_digest(confirmed.confirmed_digest, next_digest)
        ):
            self._faulted = True
            raise ExternalRevisionWitnessDenied(
                "external revision witness confirmed the wrong head"
            )
        self._head_revision = next_revision
        self._head_digest = next_digest

    def close(self) -> None:
        self._journal.close()

    def backup_to(self, destination: str) -> str:
        self._require_usable()
        return self._journal.backup_to(destination)

    def acquire_runtime_fence(
        self,
        resource_id: str,
    ) -> Callable[[], None]:
        self._require_usable()
        return self._journal.acquire_runtime_fence(resource_id)


__all__ = [
    "DynamoDbRevisionWitnessProvider",
    "ExternalRevisionWitnessConflict",
    "ExternalRevisionWitnessDenied",
    "ExternalRevisionWitnessProvider",
    "ExternalRevisionWitnessState",
    "WitnessedCellJournal",
    "revision_history_chain_digest",
]
