"""One clean Universal Cell authority for the ArchHub replacement path.

The floor persists only ``Cell(id, link0, link1, atom)``.  Stable semantic
identities are random opaque Cell ids.  Content digests, catalogue meaning,
command intent, audit evidence, and product labels are separate graph data.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import MappingProxyType
from weakref import WeakKeyDictionary
from typing import Iterable, Mapping, Protocol
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .cell_logic import (
    LogicProof,
    LogicProofStep,
    LogicProtocol,
    PrimitiveFact,
    evaluate_logic,
)
from .cell_protocols import (
    RelationMember,
    prepare_append_relation_members,
    prepare_remove_relation_members,
    prepare_reorder_relation_members,
    read_relation,
)
from .cell_revision_checkpoint import snapshot_digest
from .cell_set_digest import (
    accumulator_add as _accumulator_add,
    accumulator_remove as _accumulator_remove,
    is_v2_digest as _is_v2_digest,
    snapshot_digest_v2 as _snapshot_digest_v2,
)
from .cell_sequence import build_cell_sequence, read_cell_sequence
from .cell_secret_keys import SigningKeyProvider
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    MatchBudgetExceeded,
    Snapshot,
    overlay_read_snapshot,
)


MANIFEST_FORMAT = "archhub-universal-bootstrap/v3"
FLOOR_VERSION = "universal-cell/v1"
CODEC_NAME = "canonical-json/v1"
COMMAND_BUDGET = 100_000

ROLE_NAMES = (
    "vocabulary-member",
    "protocol-definition",
    "conforms-to",
    "required-role",
    "optional-role",
    "repeated-role",
    "open-role",
    "codec",
    "payload",
    "composition",
    "member",
    "relation",
    "source",
    "target",
    "contract",
    "direction",
    "policy",
    "rule",
    "head",
    "body",
    "predicate",
    "argument",
    "variable",
    "constant",
    "proof",
    "read-set",
    "step",
    "decision",
    "object",
    "scope",
    "budget",
    "idempotency-key",
    "evidence",
    "label",
    "actor",
    "session",
    "credential",
    "definition",
    "definition-revision",
    "current-revision",
    "previous-revision",
    "property",
    "key",
    "name",
    "value",
    "owner",
    "constraints",
    "editor",
    "authority",
    "history",
    "item",
    "index",
    "override",
    "defaults",
    "parameters",
    "interfaces",
    "rules",
    "presentation",
    "courts",
    "provenance",
    "lifecycle",
    "version",
    "content-digest",
    "receipt",
    "command",
    "intent",
    "request-digest",
    "base-revision",
    "result-revision",
    "result",
    "current-head",
    "parent-head",
    "parent-head-digest",
    "head-revision",
    "snapshot-digest",
    "protocol-root",
    "policy-root",
    "catalogue-root",
    "constitution-root",
    "signature",
    "key-id",
    "key-version",
    "key-fingerprint",
    "algorithm",
    "audience",
    "issued-at",
    "expires-at",
    "accepted-at",
)

SHAPE_NAMES = (
    "protocol-definition",
    "composition",
    "value",
    "property",
    "map",
    "list",
    "item",
    "contract",
    "definition",
    "definition-revision",
    "instance",
    "relation",
    "receipt",
    "command",
    "logic-term",
    "logic-clause",
    "logic-rule",
    "logic-proof",
    "head-index",
    "authority-head",
)

LIFECYCLE_NAMES = ("wip", "shared", "published", "archived")
LOGIC_PREDICATE_NAMES = ("relation-member", "bound")
CONTRACT_NAMES = (
    "defaults",
    "parameters",
    "interfaces",
    "rules",
    "presentation",
    "courts",
    "provenance",
)


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidCell("value is not canonical JSON data") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _new_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_opaque_id(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _relation_cells(
    root_id: str,
    members: Iterable[tuple[str, str]],
) -> tuple[Cell, ...]:
    """Build one arbitrary-arity relation with opaque physical identities."""
    pairs = tuple(members)
    if not pairs:
        return (Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, b""),)
    incidences = tuple(_new_id() for _ in pairs)
    tails = tuple(_new_id() for _ in range(max(0, len(pairs) - 1)))
    chains = (root_id, *tails)
    cells: list[Cell] = []
    for index, ((role_id, participant_id), incidence_id) in enumerate(
        zip(pairs, incidences)
    ):
        next_chain = chains[index + 1] if index + 1 < len(chains) else NULL_CELL_ID
        cells.extend((
            Cell(incidence_id, role_id, participant_id, b""),
            Cell(chains[index], incidence_id, next_chain, b""),
        ))
    return tuple(cells)


@dataclass(frozen=True, slots=True)
class _AppendPatch:
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


def _append_relation_member(
    snapshot: Snapshot,
    relation_root: str,
    role_id: str,
    participant_id: str,
    *,
    budget: int = 100_000,
) -> _AppendPatch:
    if relation_root not in snapshot.cells:
        raise InvalidCell("relation root is missing")
    cursor = relation_root
    seen: set[str] = set()
    for _ in range(budget):
        if cursor in seen:
            raise InvalidCell("relation contains a cycle")
        seen.add(cursor)
        chain = snapshot.cells[cursor]
        incidence_id = _new_id()
        if chain.link0 == NULL_CELL_ID:
            if chain.link1 != NULL_CELL_ID:
                raise InvalidCell("empty relation has a tail")
            return _AppendPatch(
                (Cell(incidence_id, role_id, participant_id, b""),),
                (Cell(chain.id, incidence_id, NULL_CELL_ID, chain.atom),),
            )
        if chain.link1 == NULL_CELL_ID:
            tail_id = _new_id()
            return _AppendPatch(
                (
                    Cell(incidence_id, role_id, participant_id, b""),
                    Cell(tail_id, incidence_id, NULL_CELL_ID, b""),
                ),
                (Cell(chain.id, chain.link0, tail_id, chain.atom),),
            )
        cursor = chain.link1
    raise InvalidCell("relation append exceeded its traversal budget")


def _append_relation_members(
    snapshot: Snapshot,
    relation_root: str,
    members: Iterable[tuple[str, str]],
    *,
    budget: int = 100_000,
) -> _AppendPatch:
    additions = tuple(members)
    if not additions:
        return _AppendPatch((), ())
    if relation_root not in snapshot.cells:
        raise InvalidCell("relation root is missing")
    cursor = relation_root
    seen: set[str] = set()
    for _ in range(budget):
        if cursor in seen:
            raise InvalidCell("relation contains a cycle")
        seen.add(cursor)
        chain = snapshot.cells[cursor]
        if chain.link0 == NULL_CELL_ID:
            if chain.link1 != NULL_CELL_ID or cursor != relation_root:
                raise InvalidCell("empty relation shape is invalid")
            incidences = tuple(_new_id() for _ in additions)
            tails = tuple(_new_id() for _ in range(len(additions) - 1))
            chains = (relation_root, *tails)
            creates: list[Cell] = []
            for index, ((role_id, participant_id), incidence_id) in enumerate(
                zip(additions, incidences)
            ):
                next_chain = (
                    chains[index + 1]
                    if index + 1 < len(chains)
                    else NULL_CELL_ID
                )
                creates.append(Cell(incidence_id, role_id, participant_id, b""))
                if index > 0:
                    creates.append(
                        Cell(chains[index], incidence_id, next_chain, b"")
                    )
            replacement = Cell(
                relation_root,
                incidences[0],
                tails[0] if tails else NULL_CELL_ID,
                chain.atom,
            )
            return _AppendPatch(tuple(creates), (replacement,))
        if chain.link1 == NULL_CELL_ID:
            incidences = tuple(_new_id() for _ in additions)
            chains = tuple(_new_id() for _ in additions)
            creates = []
            for index, ((role_id, participant_id), incidence_id) in enumerate(
                zip(additions, incidences)
            ):
                next_chain = (
                    chains[index + 1]
                    if index + 1 < len(chains)
                    else NULL_CELL_ID
                )
                creates.extend((
                    Cell(incidence_id, role_id, participant_id, b""),
                    Cell(chains[index], incidence_id, next_chain, b""),
                ))
            replacement = Cell(
                chain.id,
                chain.link0,
                chains[0],
                chain.atom,
            )
            return _AppendPatch(tuple(creates), (replacement,))
        cursor = chain.link1
    raise InvalidCell("relation append exceeded its traversal budget")


@dataclass(frozen=True, slots=True)
class BootstrapManifest:
    format_version: str
    floor_version: str
    graph_id: str
    null_cell_id: str
    accepted_revision: int
    accepted_snapshot_digest: str
    application_root: str
    protocol_root: str
    policy_root: str
    catalogue_root: str
    constitution_root: str
    history_root: str
    head_index_root: str
    principal_root: str
    bootstrap_session_root: str
    key_id: str
    key_version: int
    key_fingerprint: str
    signature: str

    def unsigned(self) -> Mapping[str, object]:
        return {
            "accepted_revision": self.accepted_revision,
            "accepted_snapshot_digest": self.accepted_snapshot_digest,
            "application_root": self.application_root,
            "bootstrap_session_root": self.bootstrap_session_root,
            "catalogue_root": self.catalogue_root,
            "constitution_root": self.constitution_root,
            "floor_version": self.floor_version,
            "format_version": self.format_version,
            "graph_id": self.graph_id,
            "history_root": self.history_root,
            "head_index_root": self.head_index_root,
            "key_id": self.key_id,
            "key_fingerprint": self.key_fingerprint,
            "key_version": self.key_version,
            "null_cell_id": self.null_cell_id,
            "policy_root": self.policy_root,
            "principal_root": self.principal_root,
            "protocol_root": self.protocol_root,
        }

    def to_json(self) -> str:
        return json.dumps(
            {**self.unsigned(), "signature": self.signature},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> "BootstrapManifest":
        try:
            values = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise InvalidCell("bootstrap manifest is not valid JSON") from exc
        expected = {
            "format_version",
            "floor_version",
            "graph_id",
            "null_cell_id",
            "accepted_revision",
            "accepted_snapshot_digest",
            "application_root",
            "protocol_root",
            "policy_root",
            "catalogue_root",
            "constitution_root",
            "history_root",
            "head_index_root",
            "principal_root",
            "bootstrap_session_root",
            "key_id",
            "key_fingerprint",
            "key_version",
            "signature",
        }
        if type(values) is not dict or set(values) != expected:
            raise InvalidCell("bootstrap manifest fields are invalid")
        try:
            return cls(**values)
        except TypeError as exc:
            raise InvalidCell("bootstrap manifest field values are invalid") from exc

    def with_signature(self, signature: str) -> "BootstrapManifest":
        return replace(self, signature=signature)


class CallerCommandCapability(Protocol):
    """Unserializable host capability for one graph-bound caller key."""

    actor_root: str
    session_root: str
    public_key: bytes

    def sign(self, payload: bytes) -> bytes:
        ...


@dataclass(frozen=True, slots=True)
class UnifiedAuthority:
    store: CellStore
    manifest: BootstrapManifest
    roles: Mapping[str, str]
    states: Mapping[str, str]
    codecs: Mapping[str, str]
    shapes: Mapping[str, str]
    key_provider: SigningKeyProvider
    logic: LogicProtocol | None

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("authority role is not declared") from exc

    def state(self, name: str) -> str:
        try:
            return self.states[name]
        except KeyError as exc:
            raise InvalidCell("authority lifecycle state is not declared") from exc

    def shape(self, name: str) -> str:
        try:
            return self.shapes[name]
        except KeyError as exc:
            raise InvalidCell("authority structural protocol is not declared") from exc

    def logic_protocol(self) -> LogicProtocol:
        if self.logic is None:
            raise InvalidCell("authority logic protocol is not resolved")
        return self.logic


@dataclass(frozen=True, slots=True)
class CompositionProjection:
    root_id: str
    protocol_root: str
    members: tuple[RelationMember, ...]


def _typed_relation_cells(
    root_id: str,
    conforms_role: str,
    shape_root: str,
    members: Iterable[tuple[str, str]],
) -> tuple[Cell, ...]:
    return _relation_cells(
        root_id,
        ((conforms_role, shape_root), *tuple(members)),
    )


def _plain_value(cell_id: str, value: str) -> Cell:
    return Cell(cell_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _build_value(
    roles: Mapping[str, str],
    codec_root: str,
    value: object,
    *,
    shape_root: str | None = None,
) -> tuple[str, tuple[Cell, ...]]:
    if type(value) not in {type(None), bool, int, float, str}:
        raise InvalidCell("compound data must be expressed as openable compositions")
    payload_root = _new_id()
    value_root = _new_id()
    members = (
        (roles["codec"], codec_root),
        (roles["payload"], payload_root),
    )
    relation = (
        _typed_relation_cells(
            value_root,
            roles["conforms-to"],
            shape_root,
            members,
        )
        if shape_root is not None
        else _relation_cells(value_root, members)
    )
    cells = (Cell(payload_root, NULL_CELL_ID, NULL_CELL_ID, _canonical_json(value)), *relation)
    return value_root, cells


def _build_scalar_leaf(value: object) -> tuple[str, Cell]:
    if type(value) not in {type(None), bool, int, float, str}:
        raise InvalidCell("scalar leaves cannot hide compound data")
    root = _new_id()
    return root, Cell(root, NULL_CELL_ID, NULL_CELL_ID, _canonical_json(value))


def _decode_scalar_leaf(snapshot: Snapshot, root_id: str) -> object:
    cell = snapshot.cells.get(root_id)
    if (
        cell is None
        or cell.link0 != NULL_CELL_ID
        or cell.link1 != NULL_CELL_ID
        or not cell.atom
    ):
        raise InvalidCell("scalar leaf is invalid")
    try:
        value = json.loads(cell.atom.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCell("scalar leaf is invalid") from exc
    if (
        type(value) not in {type(None), bool, int, float, str}
        or _canonical_json(value) != cell.atom
    ):
        raise InvalidCell("scalar leaf is non-canonical or compound")
    return value


def _single_member(
    snapshot: Snapshot,
    relation_root: str,
    role_id: str,
    *,
    budget: int = 100_000,
) -> str:
    roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, relation_root, budget=budget)
        if member.role_id == role_id
    )
    if len(roots) != 1:
        raise InvalidCell("relation requires exactly one admitted participant")
    return roots[0]


def _decode_value(authority: UnifiedAuthority, snapshot: Snapshot, root_id: str) -> object:
    codec_root = _single_member(snapshot, root_id, authority.role("codec"))
    if codec_root != authority.codecs[CODEC_NAME]:
        raise InvalidCell("value codec is outside the bootstrap protocol")
    payload_root = _single_member(snapshot, root_id, authority.role("payload"))
    try:
        value = json.loads(snapshot.cells[payload_root].atom.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCell("value payload is invalid") from exc
    if type(value) not in {type(None), bool, int, float, str}:
        raise InvalidCell("value payload hides compound data")
    return value


def _label_for(authority: UnifiedAuthority, snapshot: Snapshot, root_id: str) -> str:
    value = _decode_value(
        authority,
        snapshot,
        _single_member(snapshot, root_id, authority.role("label")),
    )
    if type(value) is not str:
        raise InvalidCell("composition label is not text")
    return value


def _optional_label(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
) -> str | None:
    label_members = tuple(
        member.participant_id
        for member in read_relation(snapshot, root_id, budget=100_000)
        if member.role_id == authority.role("label")
    )
    if not label_members:
        return None
    if len(label_members) != 1:
        raise InvalidCell("composition label binding is duplicated")
    value = _decode_value(authority, snapshot, label_members[0])
    if type(value) is not str:
        raise InvalidCell("composition label is not text")
    return value


def _resolve_protocol(
    store: CellStore,
    manifest: BootstrapManifest,
    key_provider: SigningKeyProvider,
) -> UnifiedAuthority:
    snapshot = store.snapshot()
    members = read_relation(snapshot, manifest.protocol_root, budget=100_000)
    tokens: dict[str, str] = {}
    for member in members:
        participant = snapshot.cells.get(member.participant_id)
        if participant is None:
            raise InvalidCell("bootstrap protocol vocabulary is invalid")
        if participant.link0 != NULL_CELL_ID or participant.link1 != NULL_CELL_ID:
            continue
        try:
            token = participant.atom.decode("utf-8")
        except (KeyError, UnicodeDecodeError) as exc:
            raise InvalidCell("bootstrap protocol vocabulary is invalid") from exc
        if token in tokens:
            raise InvalidCell("bootstrap protocol vocabulary is duplicated")
        tokens[token] = member.participant_id
    roles = {name: tokens.get("role/" + name, "") for name in ROLE_NAMES}
    states = {name: tokens.get("state/" + name, "") for name in LIFECYCLE_NAMES}
    codecs = {CODEC_NAME: tokens.get("codec/" + CODEC_NAME, "")}
    predicates = {
        name: tokens.get("predicate/" + name, "")
        for name in LOGIC_PREDICATE_NAMES
    }
    if (
        not all(roles.values())
        or not all(states.values())
        or not all(codecs.values())
        or not all(predicates.values())
    ):
        raise InvalidCell("bootstrap protocol vocabulary is incomplete")
    vocabulary_role = roles["vocabulary-member"]
    definition_role = roles["protocol-definition"]
    if any(
        member.role_id not in {
            vocabulary_role,
            definition_role,
            roles["conforms-to"],
            roles["label"],
            roles["open-role"],
        }
        for member in members
    ):
        raise InvalidCell("bootstrap protocol has an invalid member role")
    base = UnifiedAuthority(
        store,
        manifest,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(codecs),
        MappingProxyType({}),
        key_provider,
        None,
    )
    shapes: dict[str, str] = {}
    for member in members:
        if member.role_id != definition_role:
            continue
        label = _label_for(base, snapshot, member.participant_id)
        if not label.startswith("shape/") or label[6:] in shapes:
            raise InvalidCell("structural protocol label is invalid or duplicated")
        shapes[label[6:]] = member.participant_id
    if any(name not in shapes for name in SHAPE_NAMES):
        raise InvalidCell("bootstrap structural protocol is incomplete")
    logic = LogicProtocol(
        conforms_to_role=roles["conforms-to"],
        rule_role=roles["rule"],
        head_role=roles["head"],
        body_role=roles["body"],
        predicate_role=roles["predicate"],
        argument_role=roles["argument"],
        variable_role=roles["variable"],
        constant_role=roles["constant"],
        term_shape=shapes["logic-term"],
        clause_shape=shapes["logic-clause"],
        rule_shape=shapes["logic-rule"],
        relation_member_predicate=predicates["relation-member"],
        bound_predicate=predicates["bound"],
    )
    return replace(base, shapes=MappingProxyType(shapes), logic=logic)


# One projection validates every member against the same released
# protocol; re-walking the protocol and shape relations per member made
# validation 0.53s of a 0.9s click (1,535 calls for 26 cards). The
# result is pure over (snapshot contents, root), so the latest
# snapshot's answers are kept and dropped wholesale when the snapshot
# changes. Only reads are cached; refusals are never cached, so a
# repaired graph is re-judged.
_VALIDATE_COMPOSITION_MEMOS: "WeakKeyDictionary" = WeakKeyDictionary()


def validate_composition(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
    *,
    budget: int = 10_000,
) -> CompositionProjection:
    """Validate one composition only from its graph-held structural protocol."""
    entry = _VALIDATE_COMPOSITION_MEMOS.get(authority.store)
    if entry is None or entry[0] != snapshot.revision:
        entry = (snapshot.revision, {})
        _VALIDATE_COMPOSITION_MEMOS[authority.store] = entry
    held = entry[1].get(root_id)
    if held is not None:
        return held
    projection = _validate_composition_uncached(
        authority, snapshot, root_id, budget=budget
    )
    entry[1][root_id] = projection
    return projection


def _validate_composition_uncached(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
    *,
    budget: int = 10_000,
) -> CompositionProjection:
    members = read_relation(snapshot, root_id, budget=budget)
    conforming = tuple(
        member.participant_id
        for member in members
        if member.role_id == authority.role("conforms-to")
    )
    if len(conforming) != 1:
        raise InvalidCell("composition requires exactly one structural protocol")
    shape_root = conforming[0]
    protocol_members = read_relation(
        snapshot, authority.manifest.protocol_root, budget=budget
    )
    if not any(
        member.role_id == authority.role("protocol-definition")
        and member.participant_id == shape_root
        for member in protocol_members
    ):
        raise InvalidCell("composition structural protocol is not released")
    shape_members = read_relation(snapshot, shape_root, budget=budget)
    required = {
        member.participant_id
        for member in shape_members
        if member.role_id == authority.role("required-role")
    }
    optional = {
        member.participant_id
        for member in shape_members
        if member.role_id == authority.role("optional-role")
    }
    repeated = {
        member.participant_id
        for member in shape_members
        if member.role_id == authority.role("repeated-role")
    }
    open_markers = tuple(
        member.participant_id
        for member in shape_members
        if member.role_id == authority.role("open-role")
    )
    if len(open_markers) > 1:
        raise InvalidCell("structural protocol repeats its open-role marker")
    allowed = required | optional | repeated
    by_role: dict[str, int] = {}
    for member in members:
        by_role[member.role_id] = by_role.get(member.role_id, 0) + 1
        if not open_markers and member.role_id not in allowed:
            raise InvalidCell("composition contains a role outside its protocol")
    if any(by_role.get(role, 0) != 1 for role in required):
        raise InvalidCell("composition is missing or repeats a required role")
    if any(by_role.get(role, 0) > 1 for role in optional):
        raise InvalidCell("composition repeats an optional role")
    return CompositionProjection(root_id, shape_root, members)


def _manifest_payload(manifest: BootstrapManifest) -> bytes:
    return _canonical_json(dict(manifest.unsigned()))


def sign_bootstrap_manifest(
    manifest: BootstrapManifest,
    key_provider: SigningKeyProvider,
) -> BootstrapManifest:
    """Sign an exact bootstrap payload through the admitted key provider."""
    reference = key_provider.current_reference(manifest.key_id)
    if reference.version != manifest.key_version:
        raise InvalidCell("bootstrap signing key version changed")
    if key_provider.key_fingerprint(reference.key_id, reference.version) != manifest.key_fingerprint:
        raise InvalidCell("bootstrap signing key fingerprint changed")
    unsigned = manifest.with_signature("0" * 64)
    return unsigned.with_signature(key_provider.sign(
        reference.key_id,
        reference.version,
        _manifest_payload(unsigned),
    ))


def _validate_manifest_shape(manifest: BootstrapManifest) -> None:
    if manifest.format_version != MANIFEST_FORMAT:
        raise InvalidCell("bootstrap manifest format is unsupported")
    if manifest.floor_version != FLOOR_VERSION:
        raise InvalidCell("bootstrap floor version is unsupported")
    if manifest.null_cell_id != NULL_CELL_ID:
        raise InvalidCell("bootstrap null identity is invalid")
    if manifest.accepted_revision < 1 or manifest.key_version < 1:
        raise InvalidCell("bootstrap revision or signing key version is invalid")
    if manifest.graph_id != manifest.application_root:
        raise InvalidCell("bootstrap graph identity is not the application root")
    roots = (
        manifest.application_root,
        manifest.protocol_root,
        manifest.policy_root,
        manifest.catalogue_root,
        manifest.constitution_root,
        manifest.history_root,
        manifest.head_index_root,
        manifest.principal_root,
        manifest.bootstrap_session_root,
    )
    if not all(_is_opaque_id(root) for root in roots) or len(set(roots)) != len(roots):
        raise InvalidCell("bootstrap identities are not unique opaque Cell ids")
    if (
        len(manifest.accepted_snapshot_digest) != 64
        or len(manifest.key_fingerprint) != 64
        or len(manifest.signature) != 64
    ):
        raise InvalidCell("bootstrap digest or signature is invalid")


# One normalized digest covers one immutable snapshot. Recomputing it per
# semantic read rebuilds and hashes the whole cell table every time -- on the
# live graph that is ~152k cells per template render, which turned the first
# canvas projection over the real generation into minutes of sha256 while
# every fixture court stayed fast enough to hide it.
#
# The cache HOLDS the mapping it keys on. Immutability makes an id stable
# while the object lives, not unique across time: an entry that stored only
# the integer would survive the mapping it described, the allocator would
# reuse the address, and a later snapshot sharing revision and blank set
# would read a digest that was never its own -- on the integrity path that
# head verification and receipts trust. Same-revision-different-content is
# ordinary here (overlay snapshots, candidate commits), so the entry keeps
# the mapping alive and a hit re-checks identity with `is`. No court can
# reach the failure deterministically -- it is allocation-timing dependent --
# which is exactly why the guarantee is structural instead of courted.
_SNAPSHOT_DIGEST_CACHE: dict[
    tuple[int, int, frozenset[str]],
    tuple[Mapping[str, Cell], str],
] = {}


def _normalized_snapshot_digest(
    snapshot: Snapshot,
    blank_atom_roots: Iterable[str],
) -> str:
    blank = frozenset(blank_atom_roots)
    key = (id(snapshot.cells), snapshot.revision, blank)
    cached = _SNAPSHOT_DIGEST_CACHE.get(key)
    if cached is not None:
        held, digest = cached
        if held is snapshot.cells:
            return digest
    cells = {
        root: (
            Cell(cell.id, cell.link0, cell.link1, b"")
            if root in blank
            else cell
        )
        for root, cell in snapshot.cells.items()
    }
    digest = snapshot_digest(Snapshot(snapshot.revision, MappingProxyType(cells)))
    if len(_SNAPSHOT_DIGEST_CACHE) >= 8:
        _SNAPSHOT_DIGEST_CACHE.pop(next(iter(_SNAPSHOT_DIGEST_CACHE)))
    _SNAPSHOT_DIGEST_CACHE[key] = (snapshot.cells, digest)
    return digest


def _committed_head_digest(
    authority: UnifiedAuthority,
    base: Snapshot,
    *,
    create: Iterable[Cell],
    replace: Iterable[Cell],
    blank_atom_roots: Iterable[str],
) -> str:
    """The v2 head digest of the snapshot this commit publishes.

    v1 hashed every cell of the projected snapshot in sorted order: on the
    founder's graph that was tens of seconds to sign a pan, and the same
    again to verify the head at the next open. v2 commits to the same set
    through the store's additive accumulator, so a commit's digest costs
    the cells it writes. The formula travels in the recorded value itself
    ("v2:" prefix); heads recorded before it still verify under v1.
    """
    accumulator = authority.store.set_accumulator_after(
        base,
        create=create,
        replace=replace,
        blank_atom_roots=blank_atom_roots,
    )
    return _snapshot_digest_v2(base.revision + 1, accumulator)


def _expected_head_digest(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    blank_atom_roots: Iterable[str],
    recorded: object,
) -> str:
    """Recompute a head's snapshot digest under the formula it recorded."""
    blank = tuple(blank_atom_roots)
    if not _is_v2_digest(recorded):
        return _normalized_snapshot_digest(snapshot, blank)
    accumulator = authority.store.set_accumulator(snapshot)
    held = tuple(snapshot.cells[root] for root in blank)
    accumulator = _accumulator_add(
        _accumulator_remove(accumulator, held),
        (Cell(cell.id, cell.link0, cell.link1, b"") for cell in held),
    )
    return _snapshot_digest_v2(snapshot.revision, accumulator)


def _value_payload_root(
    authority: UnifiedAuthority,
    cells: Iterable[Cell],
) -> str:
    matches = tuple(
        cell.link1
        for cell in cells
        if cell.link0 == authority.role("payload")
    )
    if len(matches) != 1:
        raise InvalidCell("constructed value has no unique payload")
    return matches[0]


def _head_payload(
    authority: UnifiedAuthority,
    *,
    head_root: str,
    parent_head: str | None,
    parent_head_digest: str,
    revision: int,
    committed_snapshot_digest: str,
) -> Mapping[str, object]:
    return {
        "catalogue_root": authority.manifest.catalogue_root,
        "constitution_root": authority.manifest.constitution_root,
        "graph_id": authority.manifest.graph_id,
        "head_root": head_root,
        "key_fingerprint": authority.manifest.key_fingerprint,
        "key_id": authority.manifest.key_id,
        "key_version": authority.manifest.key_version,
        "parent_head": parent_head,
        "parent_head_digest": parent_head_digest,
        "policy_root": authority.manifest.policy_root,
        "protocol_root": authority.manifest.protocol_root,
        "revision": revision,
        "snapshot_digest": committed_snapshot_digest,
    }


def _current_head_member(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
) -> RelationMember | None:
    members = tuple(
        member
        for member in read_relation(
            snapshot, authority.manifest.head_index_root, budget=10_000
        )
        if member.role_id == authority.role("current-head")
    )
    if len(members) > 1:
        raise InvalidCell("current authority head is duplicated")
    return members[0] if members else None


def _stored_head_record_digest(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    head_root: str,
) -> str:
    parent_members = tuple(
        member.participant_id
        for member in read_relation(snapshot, head_root, budget=512)
        if member.role_id == authority.role("parent-head")
    )
    if len(parent_members) > 1:
        raise InvalidCell("authority head repeats its parent")
    values = {
        role_name: _decode_value(
            authority,
            snapshot,
            _single_member(snapshot, head_root, authority.role(role_name), budget=512),
        )
        for role_name in (
            "parent-head-digest", "head-revision", "snapshot-digest",
            "key-id", "key-version", "key-fingerprint", "signature",
        )
    }
    payload = _head_payload(
        authority,
        head_root=head_root,
        parent_head=parent_members[0] if parent_members else None,
        parent_head_digest=str(values["parent-head-digest"]),
        revision=int(values["head-revision"]),
        committed_snapshot_digest=str(values["snapshot-digest"]),
    )
    return _digest({"payload": dict(payload), "signature": values["signature"]})


def _commit_signed_change(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    *,
    create: Iterable[Cell],
    replace_cells: Iterable[Cell],
    head_root: str | None = None,
) -> int:
    created = tuple(create)
    replaced = tuple(replace_cells)
    current = _current_head_member(authority, snapshot)
    parent_head = current.participant_id if current is not None else None
    parent_digest = (
        _stored_head_record_digest(authority, snapshot, parent_head)
        if parent_head is not None
        else "0" * 64
    )
    revision = snapshot.revision + 1
    head_root = _new_id() if head_root is None else head_root
    if not _is_opaque_id(head_root) or head_root in snapshot.cells:
        raise InvalidCell("authority head identity is invalid")
    head_cells: list[Cell] = []
    head_members: list[tuple[str, str]] = [
        (authority.role("protocol-root"), authority.manifest.protocol_root),
        (authority.role("policy-root"), authority.manifest.policy_root),
        (authority.role("catalogue-root"), authority.manifest.catalogue_root),
        (authority.role("constitution-root"), authority.manifest.constitution_root),
    ]
    if parent_head is not None:
        head_members.append((authority.role("parent-head"), parent_head))
    value_roots: dict[str, str] = {}
    payload_roots: dict[str, str] = {}
    for role_name, value in (
        ("parent-head-digest", parent_digest),
        ("head-revision", revision),
        ("snapshot-digest", ""),
        ("key-id", authority.manifest.key_id),
        ("key-version", authority.manifest.key_version),
        ("key-fingerprint", authority.manifest.key_fingerprint),
        ("signature", ""),
    ):
        value_root, value_cells = _build_value(
            authority.roles,
            authority.codecs[CODEC_NAME],
            value,
            shape_root=authority.shape("value"),
        )
        value_roots[role_name] = value_root
        payload_roots[role_name] = _value_payload_root(authority, value_cells)
        head_cells.extend(value_cells)
        head_members.append((authority.role(role_name), value_root))
    head_cells.extend(_typed_relation_cells(
        head_root,
        authority.role("conforms-to"),
        authority.shape("authority-head"),
        head_members,
    ))
    if current is None:
        index_patch = _append_relation_member(
            snapshot,
            authority.manifest.head_index_root,
            authority.role("current-head"),
            head_root,
            budget=10_000,
        )
    else:
        incidence = snapshot.cells[current.incidence_id]
        index_patch = _AppendPatch((), (
            Cell(incidence.id, incidence.link0, head_root, incidence.atom),
        ))
    all_create = (*created, *head_cells, *index_patch.create)
    all_replace = (*replaced, *index_patch.replace)
    normalized_digest = _committed_head_digest(
        authority,
        snapshot,
        create=all_create,
        replace=all_replace,
        blank_atom_roots=(
            payload_roots["snapshot-digest"], payload_roots["signature"],
        ),
    )
    payload = _head_payload(
        authority,
        head_root=head_root,
        parent_head=parent_head,
        parent_head_digest=parent_digest,
        revision=revision,
        committed_snapshot_digest=normalized_digest,
    )
    signature = authority.key_provider.sign(
        authority.manifest.key_id,
        authority.manifest.key_version,
        _canonical_json(payload),
    )
    replacements = {
        payload_roots["snapshot-digest"]: _canonical_json(normalized_digest),
        payload_roots["signature"]: _canonical_json(signature),
    }
    final_create = tuple(
        Cell(cell.id, cell.link0, cell.link1, replacements[cell.id])
        if cell.id in replacements
        else cell
        for cell in all_create
    )
    committed_revision = authority.store.commit(
        snapshot.revision,
        create=final_create,
        replace=all_replace,
    )
    # The digest this head signs was just computed over exactly the cells
    # the commit published (the two filled payload atoms are blanked on
    # both sides). Recomputing it on the next authenticated request walks
    # and hashes every cell in the graph again -- on the live graph that
    # is tens of seconds per command, and it is what made every canvas
    # gesture cost close to a minute. The memo holds the committed mapping
    # itself, so it can never answer for a snapshot that no longer exists;
    # everything else about head verification still runs for real.
    committed = authority.store.snapshot()
    if committed.revision == revision:
        blank = frozenset((
            payload_roots["snapshot-digest"], payload_roots["signature"],
        ))
        key = (id(committed.cells), committed.revision, blank)
        if len(_SNAPSHOT_DIGEST_CACHE) >= 8:
            _SNAPSHOT_DIGEST_CACHE.pop(next(iter(_SNAPSHOT_DIGEST_CACHE)))
        _SNAPSHOT_DIGEST_CACHE[key] = (committed.cells, normalized_digest)
    return committed_revision


def _verify_authority_head(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    head_root: str,
) -> None:
    projection = validate_composition(authority, snapshot, head_root)
    if projection.protocol_root != authority.shape("authority-head"):
        raise InvalidCell("current authority head has the wrong protocol")
    values: dict[str, object] = {}
    payload_roots: dict[str, str] = {}
    for role_name in (
        "parent-head-digest", "head-revision", "snapshot-digest",
        "key-id", "key-version", "key-fingerprint", "signature",
    ):
        value_root = _single_member(snapshot, head_root, authority.role(role_name))
        payload_roots[role_name] = _single_member(
            snapshot, value_root, authority.role("payload")
        )
        values[role_name] = _decode_value(authority, snapshot, value_root)
    parent_members = tuple(
        member.participant_id
        for member in projection.members
        if member.role_id == authority.role("parent-head")
    )
    if len(parent_members) > 1:
        raise InvalidCell("current authority head repeats its parent")
    parent_head = parent_members[0] if parent_members else None
    if values["head-revision"] != snapshot.revision:
        raise InvalidCell("current authority head revision does not match")
    if (
        values["key-id"] != authority.manifest.key_id
        or values["key-version"] != authority.manifest.key_version
        or values["key-fingerprint"] != authority.manifest.key_fingerprint
    ):
        raise InvalidCell("current authority head signing identity does not match")
    expected_digest = _expected_head_digest(
        authority,
        snapshot,
        (payload_roots["snapshot-digest"], payload_roots["signature"]),
        values["snapshot-digest"],
    )
    if values["snapshot-digest"] != expected_digest:
        raise InvalidCell("current authority head snapshot digest does not match")
    payload = _head_payload(
        authority,
        head_root=head_root,
        parent_head=parent_head,
        parent_head_digest=str(values["parent-head-digest"]),
        revision=snapshot.revision,
        committed_snapshot_digest=expected_digest,
    )
    signature = values["signature"]
    if type(signature) is not str or not authority.key_provider.verify(
        authority.manifest.key_id,
        authority.manifest.key_version,
        _canonical_json(payload),
        signature,
    ):
        raise InvalidCell("current authority head signature is invalid")


# Verifying a head is a pure function of the graph it verifies, and every
# authenticated request verified the same unchanged graph again -- which
# means hashing every cell again. The verdict is kept per snapshot, and the
# entry HOLDS the mapping it keys on: an id is stable while its object
# lives, not unique across time, so an entry keeping only the integer could
# answer for a graph that no longer exists. A write publishes a new mapping
# and the next verification runs for real.
_HEAD_VERDICT_CACHE: dict[tuple[int, int, str], Mapping[str, Cell]] = {}


def _verify_exact_snapshot_head(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
) -> None:
    """Verify the signed head for exactly one selected graph revision."""
    verdict_key = (
        id(snapshot.cells),
        snapshot.revision,
        authority.manifest.graph_id,
    )
    held = _HEAD_VERDICT_CACHE.get(verdict_key)
    if held is not None and held is snapshot.cells:
        return
    _verify_exact_snapshot_head_uncached(authority, snapshot)
    if len(_HEAD_VERDICT_CACHE) >= 8:
        _HEAD_VERDICT_CACHE.pop(next(iter(_HEAD_VERDICT_CACHE)))
    _HEAD_VERDICT_CACHE[verdict_key] = snapshot.cells


def _verify_exact_snapshot_head_uncached(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
) -> None:
    """Verify the signed head without consulting the per-snapshot verdict."""
    current = _current_head_member(authority, snapshot)
    if current is None:
        if (
            snapshot.revision == authority.manifest.accepted_revision
            and snapshot_digest(snapshot)
            == authority.manifest.accepted_snapshot_digest
        ):
            return
        raise InvalidCell("current authority head is missing")
    _verify_authority_head(authority, snapshot, current.participant_id)


def _verify_current_head(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    floor: tuple[int, str, str] | None = None,
) -> None:
    """Audit every signed revision from the selected head to bootstrap.

    A floor is a head this generation already audited to bootstrap: its
    revision, its root, and the digest of its stored record. Reaching it
    ends the walk, because the store is append-only and the caller has
    already confirmed the prefix under it is the same prefix. Passing no
    floor is the full audit, and that is what the explicit audit does.
    """
    current = _current_head_member(authority, snapshot)
    if current is None:
        if snapshot.revision == authority.manifest.accepted_revision:
            return
        raise InvalidCell("current authority head is missing")
    head_root = current.participant_id
    expected_revision = snapshot.revision
    seen: set[str] = set()
    # Rebuilding a snapshot is the whole cost of one step of this walk, and
    # the parent snapshot this step reads is, by construction, the snapshot
    # the next step audits. Building it twice made a restart read the graph
    # once per revision twice over.
    carried: Snapshot | None = None
    while True:
        if head_root in seen:
            raise InvalidCell("authority head ancestry contains a cycle")
        seen.add(head_root)
        historical = (
            carried if carried is not None
            else authority.store.at(expected_revision)
        )
        carried = None
        historical_current = _current_head_member(authority, historical)
        if (
            historical_current is None
            or historical_current.participant_id != head_root
        ):
            raise InvalidCell("authority head is not current at its claimed revision")
        _verify_authority_head(authority, historical, head_root)
        projection = validate_composition(authority, historical, head_root)
        parent_roots = tuple(
            member.participant_id
            for member in projection.members
            if member.role_id == authority.role("parent-head")
        )
        parent_digest = _decode_value(
            authority,
            historical,
            _single_member(
                historical,
                head_root,
                authority.role("parent-head-digest"),
            ),
        )
        if type(parent_digest) is not str:
            raise InvalidCell("authority head parent digest is invalid")
        if not parent_roots:
            if (
                expected_revision != authority.manifest.accepted_revision + 1
                or parent_digest != "0" * 64
            ):
                raise InvalidCell("authority head does not descend from bootstrap")
            return
        parent_root = parent_roots[0]
        parent_revision = _decode_value(
            authority,
            historical,
            _single_member(
                historical,
                parent_root,
                authority.role("head-revision"),
            ),
        )
        if type(parent_revision) is not int or parent_revision != expected_revision - 1:
            raise InvalidCell("authority head parent revision is not contiguous")
        parent_snapshot = authority.store.at(parent_revision)
        expected_parent_digest = _stored_head_record_digest(
            authority, parent_snapshot, parent_root
        )
        if parent_digest != expected_parent_digest:
            raise InvalidCell("authority head parent digest does not match")
        if (
            floor is not None
            and parent_revision == floor[0]
            and parent_root == floor[1]
            and expected_parent_digest == floor[2]
        ):
            return
        head_root = parent_root
        expected_revision = parent_revision
        carried = parent_snapshot


def audit_authority_history(authority: UnifiedAuthority) -> None:
    """Run the explicit full signed-history audit for the current graph."""
    _verify_current_head(authority, authority.store.snapshot())


def verify_exact_authority_head(
    authority: UnifiedAuthority,
    snapshot: Snapshot | None = None,
) -> None:
    """Verify only the signed head for one exact selected graph revision."""
    _verify_exact_snapshot_head(
        authority,
        authority.store.snapshot() if snapshot is None else snapshot,
    )


def create_unified_authority(
    store: CellStore,
    key_provider: SigningKeyProvider,
    *,
    key_id: str,
    application_label: str,
    principal_label: str,
    bootstrap_session_label: str,
    bootstrap_session_public_key: bytes,
    composition_labels: Iterable[str],
) -> UnifiedAuthority:
    """Create and sign one clean authority from an empty Universal Cell store."""
    snapshot = store.snapshot()
    if snapshot.revision != 0 or set(snapshot.cells) != {NULL_CELL_ID}:
        raise InvalidCell("clean authority creation requires an empty Cell store")
    labels = tuple(label.strip() for label in composition_labels)
    try:
        Ed25519PublicKey.from_public_bytes(bytes(bootstrap_session_public_key))
    except (TypeError, ValueError) as exc:
        raise InvalidCell("bootstrap session public key is invalid") from exc
    if (
        not application_label.strip()
        or not principal_label.strip()
        or not bootstrap_session_label.strip()
        or any(not label for label in labels)
        or len(set(labels)) != len(labels)
    ):
        raise InvalidCell("bootstrap labels are missing or duplicated")

    role_ids = {name: _new_id() for name in ROLE_NAMES}
    state_ids = {name: _new_id() for name in LIFECYCLE_NAMES}
    predicate_ids = {name: _new_id() for name in LOGIC_PREDICATE_NAMES}
    codec_root = _new_id()
    shape_ids = {name: _new_id() for name in SHAPE_NAMES}
    roots = {
        "application": _new_id(),
        "protocol": _new_id(),
        "policy": _new_id(),
        "catalogue": _new_id(),
        "constitution": _new_id(),
        "history": _new_id(),
        "head_index": _new_id(),
        "principal": _new_id(),
        "bootstrap_session": _new_id(),
    }
    cells: list[Cell] = []
    cells.extend(_plain_value(root, "role/" + name) for name, root in role_ids.items())
    cells.extend(_plain_value(root, "state/" + name) for name, root in state_ids.items())
    cells.extend(
        _plain_value(root, "predicate/" + name)
        for name, root in predicate_ids.items()
    )
    cells.append(_plain_value(codec_root, "codec/" + CODEC_NAME))
    shape_specs: dict[str, tuple[tuple[str, str], ...]] = {
        "protocol-definition": (
            ("required-role", "conforms-to"),
            ("required-role", "label"),
            ("repeated-role", "required-role"),
            ("repeated-role", "optional-role"),
            ("repeated-role", "repeated-role"),
            ("optional-role", "open-role"),
        ),
        "composition": (
            ("required-role", "conforms-to"),
            ("required-role", "label"),
            ("open-role", "open-role"),
        ),
        "value": (
            ("required-role", "conforms-to"),
            ("required-role", "codec"),
            ("required-role", "payload"),
        ),
        "property": (
            ("required-role", "conforms-to"),
            ("required-role", "owner"),
            ("required-role", "name"),
            ("required-role", "value"),
            ("optional-role", "constraints"),
            ("optional-role", "editor"),
            ("optional-role", "authority"),
            ("optional-role", "lifecycle"),
            ("optional-role", "history"),
        ),
        "map": (
            ("required-role", "conforms-to"),
            ("repeated-role", "property"),
        ),
        "list": (
            ("required-role", "conforms-to"),
            ("repeated-role", "item"),
        ),
        "item": (
            ("required-role", "conforms-to"),
            ("required-role", "owner"),
            ("required-role", "index"),
            ("required-role", "value"),
        ),
        "contract": (
            ("required-role", "conforms-to"),
            ("repeated-role", "property"),
        ),
        "definition": (
            ("required-role", "conforms-to"),
            ("required-role", "current-revision"),
        ),
        "definition-revision": (
            ("required-role", "conforms-to"),
            ("required-role", "label"),
            ("required-role", "version"),
            ("required-role", "lifecycle"),
            ("required-role", "content-digest"),
            *(("required-role", name) for name in CONTRACT_NAMES),
            ("optional-role", "previous-revision"),
            ("repeated-role", "evidence"),
        ),
        "instance": (
            ("required-role", "conforms-to"),
            ("required-role", "definition"),
            ("required-role", "definition-revision"),
            ("repeated-role", "override"),
            ("repeated-role", "composition"),
            ("repeated-role", "relation"),
        ),
        "relation": (
            ("required-role", "conforms-to"),
            ("open-role", "open-role"),
        ),
        "command": (
            ("required-role", "conforms-to"),
            *(('required-role', name) for name in (
                "actor", "session", "object", "scope", "intent",
                "idempotency-key", "request-digest", "base-revision",
                "budget", "credential", "head", "audience",
                "issued-at", "expires-at", "key-fingerprint", "signature",
                "receipt",
            )),
            ("optional-role", "policy"),
        ),
        "logic-term": (
            ("required-role", "conforms-to"),
            ("optional-role", "variable"),
            ("optional-role", "constant"),
        ),
        "logic-clause": (
            ("required-role", "conforms-to"),
            ("required-role", "predicate"),
            ("repeated-role", "argument"),
        ),
        "logic-rule": (
            ("required-role", "conforms-to"),
            ("required-role", "head"),
            ("repeated-role", "body"),
        ),
        "logic-proof": (
            ("required-role", "conforms-to"),
            ("required-role", "rule"),
            ("required-role", "base-revision"),
            ("required-role", "step"),
            ("required-role", "read-set"),
        ),
        "receipt": (
            ("required-role", "conforms-to"),
            *(("required-role", name) for name in (
                "result", "command", "head", "result-revision", "decision",
                "accepted-at",
            )),
        ),
        "head-index": (
            ("required-role", "conforms-to"),
            ("required-role", "label"),
            ("optional-role", "current-head"),
        ),
        "authority-head": (
            ("required-role", "conforms-to"),
            ("optional-role", "parent-head"),
            *(("required-role", name) for name in (
                "parent-head-digest", "head-revision", "snapshot-digest",
                "protocol-root", "policy-root", "catalogue-root",
                "constitution-root", "key-id", "key-version",
                "key-fingerprint", "signature",
            )),
        ),
    }

    for name, shape_root in shape_ids.items():
        label_root, label_cells = _build_value(
            role_ids,
            codec_root,
            "shape/" + name,
            shape_root=shape_ids["value"],
        )
        cells.extend(label_cells)
        shape_members: list[tuple[str, str]] = [(role_ids["label"], label_root)]
        for declaration_role, governed_role in shape_specs[name]:
            shape_members.append((role_ids[declaration_role], role_ids[governed_role]))
        cells.extend(_typed_relation_cells(
            shape_root,
            role_ids["conforms-to"],
            shape_ids["protocol-definition"],
            shape_members,
        ))

    protocol_label, protocol_label_cells = _build_value(
        role_ids,
        codec_root,
        "Protocol",
        shape_root=shape_ids["value"],
    )
    cells.extend(protocol_label_cells)
    cells.extend(_typed_relation_cells(
        roots["protocol"],
        role_ids["conforms-to"],
        shape_ids["composition"],
        (
            (role_ids["label"], protocol_label),
            *((role_ids["vocabulary-member"], root) for root in (
                *role_ids.values(), *state_ids.values(),
                *predicate_ids.values(), codec_root
            )),
            *((role_ids["protocol-definition"], root) for root in shape_ids.values()),
        ),
    ))

    def labelled_relation(root_id: str, label: str, extra=()) -> tuple[Cell, ...]:
        label_root, label_cells = _build_value(
            role_ids, codec_root, label, shape_root=shape_ids["value"]
        )
        return (*label_cells, *_typed_relation_cells(
            root_id,
            role_ids["conforms-to"],
            shape_ids["composition"],
            (
                (role_ids["label"], label_root),
                *tuple(extra),
            ),
        ))

    public_key = bytes(bootstrap_session_public_key)
    public_key_root, public_key_cells = _build_value(
        role_ids,
        codec_root,
        base64.b64encode(public_key).decode("ascii"),
        shape_root=shape_ids["value"],
    )
    algorithm_root, algorithm_cells = _build_value(
        role_ids,
        codec_root,
        "ed25519",
        shape_root=shape_ids["value"],
    )
    fingerprint_root, fingerprint_cells = _build_value(
        role_ids,
        codec_root,
        hashlib.sha256(
            b"ArchHub/caller-public-key/v1\x00" + public_key
        ).hexdigest(),
        shape_root=shape_ids["value"],
    )
    bootstrap_credential = _new_id()
    cells.extend(public_key_cells)
    cells.extend(algorithm_cells)
    cells.extend(fingerprint_cells)
    cells.extend(labelled_relation(
        bootstrap_credential,
        "Bootstrap session credential",
        (
            (role_ids["actor"], roots["principal"]),
            (role_ids["session"], roots["bootstrap_session"]),
            (role_ids["key"], public_key_root),
            (role_ids["algorithm"], algorithm_root),
            (role_ids["key-fingerprint"], fingerprint_root),
            (role_ids["lifecycle"], state_ids["published"]),
        ),
    ))
    cells.extend(labelled_relation(roots["principal"], principal_label))
    cells.extend(labelled_relation(
        roots["bootstrap_session"],
        bootstrap_session_label,
        (
            (role_ids["actor"], roots["principal"]),
            (role_ids["credential"], bootstrap_credential),
        ),
    ))
    cells.extend(labelled_relation(
        roots["constitution"],
        "Constitution",
        (
            (role_ids["actor"], roots["principal"]),
            (role_ids["session"], roots["bootstrap_session"]),
            (role_ids["credential"], bootstrap_credential),
        ),
    ))
    policy_predicates = {
        name: _new_id()
        for name in ("admit", "reachable", "contains", "accessible")
    }
    cells.extend(
        _plain_value(root, "policy-predicate/" + name)
        for name, root in policy_predicates.items()
    )

    def logic_term(*, variable: str | None = None, constant: str | None = None) -> str:
        if (variable is None) == (constant is None):
            raise InvalidCell("logic term requires one variable or constant")
        root = _new_id()
        cells.extend(_typed_relation_cells(
            root,
            role_ids["conforms-to"],
            shape_ids["logic-term"],
            (((role_ids["variable"], variable),) if variable is not None else (
                (role_ids["constant"], constant),
            )),
        ))
        return root

    def logic_clause(
        predicate: str,
        arguments: Iterable[tuple[str, str]],
    ) -> str:
        root = _new_id()
        terms = tuple(
            logic_term(**{term_kind: value})
            for term_kind, value in arguments
        )
        cells.extend(_typed_relation_cells(
            root,
            role_ids["conforms-to"],
            shape_ids["logic-clause"],
            (
                (role_ids["predicate"], predicate),
                *((role_ids["argument"], term) for term in terms),
            ),
        ))
        return root

    def logic_rule(
        head: str,
        body: Iterable[str] = (),
    ) -> str:
        root = _new_id()
        cells.extend(_typed_relation_cells(
            root,
            role_ids["conforms-to"],
            shape_ids["logic-rule"],
            (
                (role_ids["head"], head),
                *((role_ids["body"], clause) for clause in tuple(body)),
            ),
        ))
        return root

    rule_roots: list[str] = []

    containment_specs = (
        ("composition", "composition"),
        ("composition", "relation"),
        ("instance", "composition"),
        ("instance", "relation"),
        ("instance", "override"),
        ("map", "property"),
        ("list", "item"),
        ("item", "value"),
        ("property", "value"),
        ("property", "constraints"),
        ("property", "editor"),
        ("contract", "property"),
        ("relation", "property"),
        ("definition", "current-revision"),
        ("definition-revision", "defaults"),
        ("definition-revision", "parameters"),
        ("definition-revision", "interfaces"),
        ("definition-revision", "rules"),
        ("definition-revision", "presentation"),
        ("definition-revision", "courts"),
        ("definition-revision", "provenance"),
        ("definition-revision", "evidence"),
        ("logic-rule", "head"),
        ("logic-rule", "body"),
        ("logic-clause", "argument"),
        ("logic-term", "variable"),
        ("logic-term", "constant"),
        ("logic-proof", "step"),
        ("logic-proof", "read-set"),
    )
    for parent_shape, child_role in containment_specs:
        parent_var, child_var = _new_id(), _new_id()
        cells.extend((
            _plain_value(parent_var, "logic-variable"),
            _plain_value(child_var, "logic-variable"),
        ))
        rule_roots.append(logic_rule(
            logic_clause(
                policy_predicates["contains"],
                (("variable", parent_var), ("variable", child_var)),
            ),
            (
                logic_clause(
                    predicate_ids["relation-member"],
                    (
                        ("variable", parent_var),
                        ("constant", role_ids["conforms-to"]),
                        ("constant", shape_ids[parent_shape]),
                    ),
                ),
                logic_clause(
                    predicate_ids["relation-member"],
                    (
                        ("variable", parent_var),
                        ("constant", role_ids[child_role]),
                        ("variable", child_var),
                    ),
                ),
            ),
        ))
    for parent_name, child_role in (
        ("catalogue", "definition"),
        ("constitution", "actor"),
        ("constitution", "session"),
        ("constitution", "credential"),
        ("history", "receipt"),
        ("head_index", "current-head"),
        ("policy", "rule"),
    ):
        child_var = _new_id()
        cells.append(_plain_value(child_var, "logic-variable"))
        rule_roots.append(logic_rule(
            logic_clause(
                policy_predicates["contains"],
                (("constant", roots[parent_name]), ("variable", child_var)),
            ),
            (logic_clause(
                predicate_ids["relation-member"],
                (
                    ("constant", roots[parent_name]),
                    ("constant", role_ids[child_role]),
                    ("variable", child_var),
                ),
            ),),
        ))

    reach_x, reach_y = _new_id(), _new_id()
    cells.extend((_plain_value(reach_x, "logic-variable"), _plain_value(reach_y, "logic-variable")))
    rule_roots.append(logic_rule(logic_clause(
        policy_predicates["reachable"],
        (("variable", reach_x), ("variable", reach_x)),
    )))

    direct_x, direct_y = _new_id(), _new_id()
    cells.extend(
        _plain_value(root, "logic-variable")
        for root in (direct_x, direct_y)
    )
    rule_roots.append(logic_rule(
        logic_clause(
            policy_predicates["reachable"],
            (("variable", direct_x), ("variable", direct_y)),
        ),
        (
            logic_clause(
                policy_predicates["contains"],
                (
                    ("variable", direct_x),
                    ("variable", direct_y),
                ),
            ),
        ),
    ))

    global_scope, global_object = _new_id(), _new_id()
    cells.extend(
        _plain_value(root, "logic-variable")
        for root in (global_scope, global_object)
    )
    rule_roots.append(logic_rule(
        logic_clause(
            policy_predicates["accessible"],
            (("variable", global_scope), ("variable", global_object)),
        ),
        (
            logic_clause(
                predicate_ids["relation-member"],
                (
                    ("variable", global_object),
                    ("constant", role_ids["conforms-to"]),
                    ("constant", shape_ids["definition"]),
                ),
            ),
            logic_clause(
                policy_predicates["reachable"],
                (("constant", roots["catalogue"]), ("variable", global_object)),
            ),
        ),
    ))
    local_scope, local_object = _new_id(), _new_id()
    cells.extend(
        _plain_value(root, "logic-variable")
        for root in (local_scope, local_object)
    )
    rule_roots.append(logic_rule(
        logic_clause(
            policy_predicates["accessible"],
            (("variable", local_scope), ("variable", local_object)),
        ),
        (logic_clause(
            policy_predicates["reachable"],
            (("variable", local_scope), ("variable", local_object)),
        ),),
    ))

    recursive_x, recursive_z, recursive_y = (
        _new_id(), _new_id(), _new_id()
    )
    cells.extend(
        _plain_value(root, "logic-variable")
        for root in (recursive_x, recursive_z, recursive_y)
    )
    rule_roots.append(logic_rule(
        logic_clause(
            policy_predicates["reachable"],
            (("variable", recursive_x), ("variable", recursive_y)),
        ),
        (
            logic_clause(
                policy_predicates["contains"],
                (
                    ("variable", recursive_x),
                    ("variable", recursive_z),
                ),
            ),
            logic_clause(
                policy_predicates["reachable"],
                (("variable", recursive_z), ("variable", recursive_y)),
            ),
        ),
    ))

    actor_var, session_var, intent_var, scope_var, object_var = (
        _new_id(), _new_id(), _new_id(), _new_id(), _new_id()
    )
    cells.extend(
        _plain_value(root, "logic-variable")
        for root in (actor_var, session_var, intent_var, scope_var, object_var)
    )
    rule_roots.append(logic_rule(
        logic_clause(
            policy_predicates["admit"],
            (
                ("variable", actor_var),
                ("variable", session_var),
                ("variable", intent_var),
                ("variable", scope_var),
                ("variable", object_var),
            ),
        ),
        (
            logic_clause(
                predicate_ids["bound"],
                (("variable", intent_var),),
            ),
            logic_clause(
                predicate_ids["relation-member"],
                (
                    ("variable", session_var),
                    ("constant", role_ids["actor"]),
                    ("variable", actor_var),
                ),
            ),
            logic_clause(
                policy_predicates["reachable"],
                (("constant", roots["application"]), ("variable", session_var)),
            ),
            logic_clause(
                policy_predicates["reachable"],
                (("constant", roots["application"]), ("variable", scope_var)),
            ),
            logic_clause(
                policy_predicates["accessible"],
                (("variable", scope_var), ("variable", object_var)),
            ),
        ),
    ))
    cells.extend(labelled_relation(
        roots["policy"],
        "Policy",
        (
            (role_ids["predicate"], policy_predicates["admit"]),
            *((role_ids["rule"], rule_root) for rule_root in rule_roots),
        ),
    ))
    cells.extend(labelled_relation(roots["catalogue"], "Catalogue"))
    cells.extend(labelled_relation(roots["history"], "History"))
    head_label, head_label_cells = _build_value(
        role_ids,
        codec_root,
        "Authority Head",
        shape_root=shape_ids["value"],
    )
    cells.extend(head_label_cells)
    cells.extend(_typed_relation_cells(
        roots["head_index"],
        role_ids["conforms-to"],
        shape_ids["head-index"],
        ((role_ids["label"], head_label),),
    ))

    composition_roots: list[str] = []
    for label in labels:
        composition_root = _new_id()
        composition_roots.append(composition_root)
        cells.extend(labelled_relation(composition_root, label))
    app_label_root, app_label_cells = _build_value(
        role_ids,
        codec_root,
        application_label,
        shape_root=shape_ids["value"],
    )
    cells.extend(app_label_cells)
    cells.extend(_typed_relation_cells(
        roots["application"],
        role_ids["conforms-to"],
        shape_ids["composition"],
        (
            (role_ids["label"], app_label_root),
            *((role_ids["composition"], root) for root in (
                roots["constitution"],
                roots["catalogue"],
                roots["history"],
                roots["head_index"],
                *composition_roots,
                roots["protocol"],
                roots["policy"],
            )),
        ),
    ))

    ids = tuple(cell.id for cell in cells)
    if len(ids) != len(set(ids)) or set(ids).intersection(snapshot.cells):
        raise InvalidCell("bootstrap Cell identity collision")
    accepted_revision = snapshot.revision + 1
    expected_cells = dict(snapshot.cells)
    expected_cells.update((cell.id, cell) for cell in cells)
    expected = Snapshot(accepted_revision, MappingProxyType(expected_cells))
    reference = key_provider.current_reference(key_id)
    unsigned = BootstrapManifest(
        MANIFEST_FORMAT,
        FLOOR_VERSION,
        roots["application"],
        NULL_CELL_ID,
        accepted_revision,
        snapshot_digest(expected),
        roots["application"],
        roots["protocol"],
        roots["policy"],
        roots["catalogue"],
        roots["constitution"],
        roots["history"],
        roots["head_index"],
        roots["principal"],
        roots["bootstrap_session"],
        reference.key_id,
        reference.version,
        key_provider.key_fingerprint(reference.key_id, reference.version),
        "0" * 64,
    )
    manifest = unsigned.with_signature(key_provider.sign(
        reference.key_id,
        reference.version,
        _manifest_payload(unsigned),
    ))
    store.commit(snapshot.revision, create=tuple(cells))
    authority = open_unified_authority(store, manifest, key_provider)
    _commit_signed_change(
        authority,
        store.snapshot(),
        create=(),
        replace_cells=(),
    )
    return open_unified_authority(store, manifest, key_provider)


def open_unified_authority(
    store: CellStore,
    manifest: BootstrapManifest,
    key_provider: SigningKeyProvider,
    accepted_proof=None,
) -> UnifiedAuthority:
    """Verify a signed bootstrap and open the exact same persisted authority."""
    _validate_manifest_shape(manifest)
    if key_provider.key_fingerprint(
        manifest.key_id, manifest.key_version
    ) != manifest.key_fingerprint:
        raise InvalidCell("bootstrap signing key fingerprint is invalid")
    if not key_provider.verify(
        manifest.key_id,
        manifest.key_version,
        _manifest_payload(manifest),
        manifest.signature,
    ):
        raise InvalidCell("bootstrap manifest signature is invalid")
    if store.revision < manifest.accepted_revision:
        raise InvalidCell("Cell store predates the accepted bootstrap")
    # Rebuilding and hashing the accepted snapshot is the whole cost of
    # opening a large graph, and it re-proves a fact about a revision that
    # cannot change. A proof carried by the generation lets an unchanged
    # history skip it; a changed history does not match and pays in full.
    proof_key = None
    if accepted_proof is not None:
        proof_key = accepted_proof.fingerprint(
            store, manifest.accepted_revision
        )
        if accepted_proof.proven(
            proof_key, manifest.accepted_snapshot_digest
        ):
            proof_key = None
        else:
            accepted = store.at(manifest.accepted_revision)
            if snapshot_digest(accepted) != manifest.accepted_snapshot_digest:
                raise InvalidCell(
                    "accepted bootstrap snapshot digest does not match"
                )
            accepted_proof.record(
                proof_key, manifest.accepted_snapshot_digest
            )
            proof_key = None
    else:
        accepted = store.at(manifest.accepted_revision)
        if snapshot_digest(accepted) != manifest.accepted_snapshot_digest:
            raise InvalidCell(
                "accepted bootstrap snapshot digest does not match"
            )
    required = {
        manifest.application_root,
        manifest.protocol_root,
        manifest.policy_root,
        manifest.catalogue_root,
        manifest.constitution_root,
        manifest.history_root,
        manifest.head_index_root,
        manifest.principal_root,
        manifest.bootstrap_session_root,
    }
    if not required.issubset(store.snapshot().cells):
        raise InvalidCell("bootstrap root is missing from the current graph")
    authority = _resolve_protocol(store, manifest, key_provider)
    if not roots_are_reachable(
        store.snapshot(), manifest.application_root, required, store=store
    ):
        raise InvalidCell("bootstrap roots do not share one application root")
    # Verifying the current head hashes every cell in the graph. On a
    # large graph that is the entire cost of starting, and it re-proves a
    # head that has not moved since the last time it was proven. The proof
    # carried by the generation records which head, at which revision, over
    # which append-only prefix, was verified; anything different pays in
    # full.
    current = store.snapshot()
    head_key = None
    if accepted_proof is not None:
        head_key = accepted_proof.head_fingerprint(store, current.revision)
    if head_key is not None and accepted_proof.head_proven(head_key):
        return authority
    floor = None
    if accepted_proof is not None:
        proven_revision = accepted_proof.head_floor_revision(store)
        if proven_revision is not None and proven_revision < current.revision:
            historical = store.at(proven_revision)
            member = _current_head_member(authority, historical)
            if member is not None:
                floor = (
                    proven_revision,
                    member.participant_id,
                    _stored_head_record_digest(
                        authority, historical, member.participant_id
                    ),
                )
    _verify_current_head(authority, current, floor)
    if head_key is not None:
        accepted_proof.record_head(head_key)
    return authority


def composition_root(
    authority: UnifiedAuthority,
    label: str,
    *,
    caller: CallerCommandCapability,
    budget: int = 100_000,
) -> str:
    """Resolve a labelled composition through the one application graph."""
    snapshot = authority.store.snapshot()
    _authorize_semantic_read(
        authority,
        snapshot,
        caller,
        object_root=authority.manifest.application_root,
        scope_root=authority.manifest.application_root,
        budget=budget,
    )
    matches = tuple(
        member.participant_id
        for member in read_relation(
            snapshot, authority.manifest.application_root, budget=budget
        )
        if member.role_id == authority.role("composition")
        and _optional_label(authority, snapshot, member.participant_id) == label
    )
    if len(matches) != 1:
        raise InvalidCell("application requires one composition with that label")
    _validate_composition_scope(authority, snapshot, matches[0])
    _authorize_semantic_read(
        authority,
        snapshot,
        caller,
        object_root=matches[0],
        scope_root=authority.manifest.application_root,
        budget=budget,
    )
    return matches[0]


@dataclass(frozen=True, slots=True)
class DefinitionProjection:
    root_id: str
    revision_root: str
    name: str
    version: str
    lifecycle: str
    content_digest: str
    contracts: Mapping[str, Mapping[str, object]]
    evidence_roots: tuple[str, ...]
    # Root of each contract relation, kept so a consumer can name the cell a
    # contract was read from rather than only its decoded content.
    contract_roots: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class CommandResult:
    root_id: str
    revision: int
    replayed: bool
    created_cell_count: int
    receipt_cell_count: int
    receipt_root: str


class AuthorizationDenied(InvalidCell):
    """A valid caller request was denied and preserved as graph evidence."""

    def __init__(self, receipt_root: str, revision: int, *, replayed: bool):
        super().__init__("authenticated command was denied by graph policy")
        self.receipt_root = receipt_root
        self.revision = revision
        self.replayed = replayed


@dataclass(frozen=True, slots=True)
class ExplicitRelationProjection:
    root_id: str
    participants: tuple[tuple[str, str], ...]
    properties: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RelationRevisionMember:
    incidence_id: str | None
    role_root: str
    participant_root: str


@dataclass(frozen=True, slots=True)
class ContainedScopeProjection:
    root_id: str
    revision: int
    instances: Mapping[str, Mapping[str, object]]
    relations: Mapping[str, ExplicitRelationProjection]


@dataclass(frozen=True, slots=True)
class ScopeLevelProjection:
    """One authorized direct composition level at one accepted revision."""

    root_id: str
    revision: int
    label: str | None
    composition_roots: tuple[str, ...]
    composition_labels: Mapping[str, str | None]
    instances: Mapping[str, Mapping[str, object]]
    relations: Mapping[str, ExplicitRelationProjection]


@dataclass(frozen=True, slots=True)
class _ReceiptProjection:
    root_id: str
    request_digest: str
    result_root: str
    result_revision: int
    actor_root: str
    session_root: str
    idempotency_key: str
    decision: str
    policy_proof_root: str | None


@dataclass(frozen=True, slots=True)
class _CommandProjection:
    root_id: str
    idempotency_key: str
    intent: str
    request_digest: str
    base_revision: int
    object_root: str
    scope_root: str
    policy_proof_root: str | None
    budget: int
    issued_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class _AuthenticatedRequest:
    actor_root: str
    session_root: str
    credential_root: str
    command_id: str
    intent: str
    request_digest: str
    base_revision: int
    object_root: str
    scope_root: str
    budget: int
    challenge_head: str
    issued_at: str
    expires_at: str
    public_key_fingerprint: str
    signature: str


def _normalized_mapping(values: Mapping[str, object] | None) -> dict[str, object]:
    if values is None:
        return {}
    return {str(key): values[key] for key in sorted(values, key=str)}


def _build_data_value(
    authority: UnifiedAuthority,
    value: object,
) -> tuple[str, tuple[Cell, ...]]:
    """Encode data recursively so compound values remain openable graph structure."""
    if type(value) in {type(None), bool, int, float, str}:
        root, cell = _build_scalar_leaf(value)
        return root, (cell,)
    if isinstance(value, Mapping):
        root = _new_id()
        cells: list[Cell] = []
        members: list[tuple[str, str]] = []
        for key, nested in _normalized_mapping(value).items():
            property_root, property_cells = _build_property(
                authority,
                key,
                nested,
                owner_root=root,
            )
            cells.extend(property_cells)
            members.append((authority.role("property"), property_root))
        cells.extend(_typed_relation_cells(
            root,
            authority.role("conforms-to"),
            authority.shape("map"),
            members,
        ))
        return root, tuple(cells)
    if isinstance(value, (list, tuple)):
        root = _new_id()
        cells: list[Cell] = []
        members: list[tuple[str, str]] = []
        for index, nested in enumerate(value):
            index_root, index_cell = _build_scalar_leaf(index)
            value_root, value_cells = _build_data_value(authority, nested)
            item_root = _new_id()
            cells.append(index_cell)
            cells.extend(value_cells)
            cells.extend(_typed_relation_cells(
                item_root,
                authority.role("conforms-to"),
                authority.shape("item"),
                (
                    (authority.role("owner"), root),
                    (authority.role("index"), index_root),
                    (authority.role("value"), value_root),
                ),
            ))
            members.append((authority.role("item"), item_root))
        cells.extend(_typed_relation_cells(
            root,
            authority.role("conforms-to"),
            authority.shape("list"),
            members,
        ))
        return root, tuple(cells)
    raise InvalidCell("data value cannot be represented by the structural protocol")


def _build_property(
    authority: UnifiedAuthority,
    key: str,
    value: object,
    *,
    owner_root: str,
    constraints_value: object = None,
    editor_value: object = None,
    predecessor_root: str | None = None,
) -> tuple[str, tuple[Cell, ...]]:
    name_root, name_cell = _build_scalar_leaf(key)
    value_root, value_cells = _build_data_value(authority, value)
    optional_cells: list[Cell] = []
    optional_members: list[tuple[str, str]] = []
    if constraints_value is not None:
        constraints_root, constraints_cells = _build_data_value(
            authority, constraints_value
        )
        optional_cells.extend(constraints_cells)
        optional_members.append((authority.role("constraints"), constraints_root))
    if editor_value is not None:
        editor_root, editor_cells = _build_data_value(authority, editor_value)
        optional_cells.extend(editor_cells)
        optional_members.append((authority.role("editor"), editor_root))
    if predecessor_root is not None:
        # A revised property is a new cell. Naming the property it replaced
        # keeps the row walkable backwards; without it the old value is
        # still in the graph but nothing says the new one succeeded it.
        # Recorded under "history", which the released property shape already
        # declares optional. Adding a role to that shape would only exist in
        # newly bootstrapped graphs: validate_composition reads the shape from
        # the graph, and there is no protocol re-release path, so an
        # already-bootstrapped graph would reject every revised property.
        optional_members.append(
            (authority.role("history"), predecessor_root)
        )
    property_root = _new_id()
    if predecessor_root == property_root:
        # A property naming itself is how a reader learns it replaced
        # nothing. If a real predecessor edge could ever be a self-loop the
        # sentinel would be a lie, so it is refused at the one place every
        # property is born rather than trusted to callers. build_property is
        # published on the public seam and other modules already call it, so
        # a static check inside this file cannot cover every path; this can.
        raise InvalidCell("a property cannot be its own predecessor")
    return property_root, (
        name_cell,
        *value_cells,
        *optional_cells,
        *_typed_relation_cells(
            property_root,
            authority.role("conforms-to"),
            authority.shape("property"),
            (
                (authority.role("owner"), owner_root),
                (authority.role("name"), name_root),
                (authority.role("value"), value_root),
                *optional_members,
            ),
        ),
    )


def build_contract(*args, **kwargs):
    """Build the cells for a nested mapping, as a signed command would.

    A receipt for an effect carries what was asked and what came back,
    and both are nested. build_value takes scalars only, so an effect
    recorded through it could keep no detail of itself.
    """
    return _build_contract(*args, **kwargs)


def _build_contract(
    authority: UnifiedAuthority,
    values: Mapping[str, object],
) -> tuple[str, tuple[Cell, ...]]:
    root = _new_id()
    cells: list[Cell] = []
    members: list[tuple[str, str]] = []
    for key, value in _normalized_mapping(values).items():
        property_root, property_cells = _build_property(
            authority, key, value, owner_root=root
        )
        cells.extend(property_cells)
        members.append((authority.role("property"), property_root))
    cells.extend(_typed_relation_cells(
        root,
        authority.role("conforms-to"),
        authority.shape("contract"),
        members,
    ))
    return root, tuple(cells)


def _decode_data_value(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root_id: str,
) -> object:
    cell = snapshot.cells.get(root_id)
    if (
        cell is not None
        and cell.link0 == NULL_CELL_ID
        and cell.link1 == NULL_CELL_ID
    ):
        return _decode_scalar_leaf(snapshot, root_id)
    projection = validate_composition(authority, snapshot, root_id)
    if projection.protocol_root == authority.shape("value"):
        return _decode_value(authority, snapshot, root_id)
    if projection.protocol_root == authority.shape("map"):
        return _property_values(authority, snapshot, root_id)
    if projection.protocol_root != authority.shape("list"):
        raise InvalidCell("data value uses a non-data structural protocol")

    indexed: dict[int, object] = {}
    for member in projection.members:
        if member.role_id != authority.role("item"):
            continue
        item = validate_composition(authority, snapshot, member.participant_id)
        if item.protocol_root != authority.shape("item"):
            raise InvalidCell("list member is not an item composition")
        owner = _single_member(
            snapshot, item.root_id, authority.role("owner")
        )
        if owner != root_id:
            raise InvalidCell("list item owner does not match its list")
        index = _decode_scalar_leaf(
            snapshot,
            _single_member(snapshot, item.root_id, authority.role("index")),
        )
        if type(index) is not int or index < 0 or index in indexed:
            raise InvalidCell("list item index is invalid or duplicated")
        indexed[index] = _decode_data_value(
            authority,
            snapshot,
            _single_member(snapshot, item.root_id, authority.role("value")),
        )
    if set(indexed) != set(range(len(indexed))):
        raise InvalidCell("list item indexes are not contiguous")
    return [indexed[index] for index in range(len(indexed))]


def _property_values(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    relation_root: str,
) -> dict[str, object]:
    values: dict[str, object] = {}
    for member in read_relation(snapshot, relation_root, budget=100_000):
        if member.role_id not in {
            authority.role("property"),
            authority.role("override"),
        }:
            continue
        property_root = member.participant_id
        property_projection = validate_composition(
            authority, snapshot, property_root
        )
        if property_projection.protocol_root != authority.shape("property"):
            raise InvalidCell("property member has the wrong structural protocol")
        if _single_member(
            snapshot, property_root, authority.role("owner")
        ) != relation_root:
            raise InvalidCell("property owner does not match its container")
        key = _decode_scalar_leaf(
            snapshot,
            _single_member(snapshot, property_root, authority.role("name")),
        )
        if type(key) is not str or key in values:
            raise InvalidCell("property key is invalid or duplicated")
        values[key] = _decode_data_value(
            authority,
            snapshot,
            _single_member(snapshot, property_root, authority.role("value")),
        )
    return values


def _property_identities(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    relation_root: str,
) -> dict[str, dict[str, str]]:
    """Name the graph identities behind each property of one container.

    _property_values reads these roots to decode a value and then discards
    them, so nothing downstream can prove which cell a displayed value came
    from. This returns the identities themselves, leaving the decoding to
    _property_values.
    """
    identities: dict[str, dict[str, str]] = {}
    for member in read_relation(snapshot, relation_root, budget=100_000):
        if member.role_id not in {
            authority.role("property"),
            authority.role("override"),
        }:
            continue
        property_root = member.participant_id
        property_projection = validate_composition(
            authority, snapshot, property_root
        )
        if property_projection.protocol_root != authority.shape("property"):
            continue
        name_root = _single_member(snapshot, property_root, authority.role("name"))
        value_root = _single_member(
            snapshot, property_root, authority.role("value")
        )
        key = _decode_scalar_leaf(snapshot, name_root)
        if type(key) is not str:
            continue
        # A displayed value must be traceable to what it replaced, not only
        # to the cell it currently lives in. history_root anchors the row to
        # the graph's history spine; predecessor_root names the property this
        # one succeeded, so a reader can walk backwards. A property with no
        # predecessor yet names itself rather than None: the identity must
        # always resolve to a cell that exists.
        predecessor_root = _optional_single_member(
            snapshot, property_root, authority.role("history")
        ) or property_root
        identities[key] = {
            "property_root": property_root,
            "owner": relation_root,
            "name_root": name_root,
            "value_root": value_root,
            "history_root": authority.manifest.history_root,
            "predecessor_root": predecessor_root,
        }
    return identities


def _optional_single_member(
    snapshot: Snapshot,
    relation_root: str,
    role_id: str,
) -> str | None:
    """The one participant for a role, or None when the role is absent."""
    found = tuple(
        member.participant_id
        for member in read_relation(snapshot, relation_root, budget=1024)
        if member.role_id == role_id
    )
    return found[0] if len(found) == 1 else None


def _definition_revision_root(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    definition_root: str,
) -> str:
    definition = validate_composition(authority, snapshot, definition_root)
    if definition.protocol_root != authority.shape("definition"):
        raise InvalidCell("definition has the wrong structural protocol")
    return _single_member(
        snapshot, definition_root, authority.role("current-revision")
    )


def _validate_composition_scope(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    scope_root: str,
) -> None:
    scope = validate_composition(authority, snapshot, scope_root)
    if scope.protocol_root not in {
        authority.shape("composition"),
        authority.shape("instance"),
    }:
        raise InvalidCell("scope is not an openable composition")


_DEFINITION_CACHE: dict[tuple[int, str, str, str], tuple[object, object]] = {}


def read_definition(
    authority: UnifiedAuthority,
    definition_root: str,
    *,
    caller: CallerCommandCapability,
) -> DefinitionProjection:
    """Read one definition, authorized, as of now.

    A canvas asks for the same definitions again and again -- once for the
    library row, once for the node made from it, once for whether it may be
    placed -- and each ask re-authorized and re-walked the same unchanged
    cells. A definition cannot change while the graph does not, so the
    answer is remembered against the exact cell mapping it was read from
    and against the caller it was authorized for. A different caller asks
    again, because the authorization is theirs and not the graph's.
    """
    snapshot = authority.store.snapshot()
    key = (
        id(snapshot.cells),
        definition_root,
        getattr(caller, "actor_root", ""),
        getattr(caller, "session_root", ""),
    )
    held = _DEFINITION_CACHE.get(key)
    if held is not None:
        cells, projection = held
        # Identity, not equality: an id can be reused once its object is
        # gone, so the mapping itself has to still be the same object.
        if cells is snapshot.cells:
            return projection
    _authorize_semantic_read(
        authority,
        snapshot,
        caller,
        object_root=definition_root,
        scope_root=authority.manifest.catalogue_root,
        budget=COMMAND_BUDGET,
    )
    revision_root = _definition_revision_root(authority, snapshot, definition_root)
    revision = validate_composition(authority, snapshot, revision_root)
    if revision.protocol_root != authority.shape("definition-revision"):
        raise InvalidCell("definition revision has the wrong structural protocol")
    name = _decode_value(
        authority,
        snapshot,
        _single_member(snapshot, revision_root, authority.role("label")),
    )
    version = _decode_value(
        authority,
        snapshot,
        _single_member(snapshot, revision_root, authority.role("version")),
    )
    lifecycle_root = _single_member(
        snapshot, revision_root, authority.role("lifecycle")
    )
    lifecycle = next(
        (name for name, root in authority.states.items() if root == lifecycle_root),
        None,
    )
    digest = _decode_value(
        authority,
        snapshot,
        _single_member(snapshot, revision_root, authority.role("content-digest")),
    )
    if type(name) is not str or type(version) is not str or type(digest) is not str:
        raise InvalidCell("definition scalar metadata is invalid")
    if lifecycle is None:
        raise InvalidCell("definition lifecycle is outside the protocol")
    contracts: dict[str, Mapping[str, object]] = {}
    contract_roots: dict[str, str] = {}
    for contract_name in CONTRACT_NAMES:
        contract_root = _single_member(
            snapshot, revision_root, authority.role(contract_name)
        )
        contract_roots[contract_name] = contract_root
        contracts[contract_name] = MappingProxyType(
            _property_values(authority, snapshot, contract_root)
        )
    evidence_roots = tuple(sorted(
        member.participant_id
        for member in read_relation(snapshot, revision_root, budget=100_000)
        if member.role_id == authority.role("evidence")
    ))
    reconstructed = {
        "name": name,
        "version": version,
        "lifecycle": lifecycle,
        **{contract: dict(contracts[contract]) for contract in CONTRACT_NAMES},
        "evidence": evidence_roots,
    }
    if digest != _digest(reconstructed):
        raise InvalidCell("definition content digest does not match its graph")
    projection = DefinitionProjection(
        definition_root,
        revision_root,
        name,
        version,
        lifecycle,
        digest,
        MappingProxyType(contracts),
        evidence_roots,
        MappingProxyType(contract_roots),
    )
    if len(_DEFINITION_CACHE) >= 4096:
        # Bounded: a long-lived runtime reads many definitions across many
        # revisions, and a cache that only grows is a leak wearing a
        # cache's clothes.
        _DEFINITION_CACHE.clear()
    _DEFINITION_CACHE[key] = (snapshot.cells, projection)
    return projection


def _caller_key_fingerprint(public_key: bytes) -> str:
    return hashlib.sha256(
        b"ArchHub/caller-public-key/v1\x00" + bytes(public_key)
    ).hexdigest()


def _command_payload(
    authority: UnifiedAuthority,
    *,
    actor_root: str,
    session_root: str,
    credential_root: str,
    object_root: str,
    scope_root: str,
    intent: str,
    idempotency_key: str,
    request_digest: str,
    base_revision: int,
    budget: int,
    challenge_head: str,
    issued_at: str,
    expires_at: str,
    key_fingerprint: str,
) -> Mapping[str, object]:
    return {
        "actor": actor_root,
        "audience": authority.manifest.graph_id,
        "base_revision": base_revision,
        "budget": budget,
        "challenge_head": challenge_head,
        "constitution_root": authority.manifest.constitution_root,
        "credential": credential_root,
        "expires_at": expires_at,
        "idempotency_key": idempotency_key,
        "intent": intent,
        "issued_at": issued_at,
        "key_fingerprint": key_fingerprint,
        "object": object_root,
        "policy_root": authority.manifest.policy_root,
        "protocol_root": authority.manifest.protocol_root,
        "request_digest": request_digest,
        "scope": scope_root,
        "session": session_root,
    }


def _build_command(
    authority: UnifiedAuthority,
    request: _AuthenticatedRequest,
    *,
    policy_proof_root: str | None,
    receipt_root: str,
) -> tuple[str, tuple[Cell, ...]]:
    command_root = request.command_id
    cells: list[Cell] = []
    members: list[tuple[str, str]] = [
        (authority.role("actor"), request.actor_root),
        (authority.role("session"), request.session_root),
        (authority.role("credential"), request.credential_root),
        (authority.role("object"), request.object_root),
        (authority.role("scope"), request.scope_root),
        (authority.role("head"), request.challenge_head),
        (authority.role("receipt"), receipt_root),
    ]
    if policy_proof_root is not None:
        members.append((authority.role("policy"), policy_proof_root))
    for role_name, value in (
        ("intent", request.intent),
        ("idempotency-key", request.command_id),
        ("request-digest", request.request_digest),
        ("base-revision", request.base_revision),
        ("budget", request.budget),
        ("audience", authority.manifest.graph_id),
        ("issued-at", request.issued_at),
        ("expires-at", request.expires_at),
        ("key-fingerprint", request.public_key_fingerprint),
        ("signature", request.signature),
    ):
        value_root, value_cell = _build_scalar_leaf(value)
        cells.append(value_cell)
        members.append((authority.role(role_name), value_root))
    cells.extend(_typed_relation_cells(
        command_root,
        authority.role("conforms-to"),
        authority.shape("command"),
        members,
    ))
    return command_root, tuple(cells)


def _credential_public_key(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    credential_root: str,
    *,
    actor_root: str,
    session_root: str,
) -> tuple[bytes, str]:
    credential = validate_composition(authority, snapshot, credential_root)
    if credential.protocol_root != authority.shape("composition"):
        raise InvalidCell("caller credential has the wrong structural protocol")
    if (
        _single_member(snapshot, credential_root, authority.role("actor"))
        != actor_root
        or _single_member(snapshot, credential_root, authority.role("session"))
        != session_root
        or _single_member(snapshot, credential_root, authority.role("lifecycle"))
        != authority.state("published")
    ):
        raise InvalidCell("caller credential binding is invalid or revoked")
    algorithm = _decode_value(
        authority,
        snapshot,
        _single_member(snapshot, credential_root, authority.role("algorithm")),
    )
    encoded_key = _decode_value(
        authority,
        snapshot,
        _single_member(snapshot, credential_root, authority.role("key")),
    )
    fingerprint = _decode_value(
        authority,
        snapshot,
        _single_member(snapshot, credential_root, authority.role("key-fingerprint")),
    )
    if algorithm != "ed25519" or type(encoded_key) is not str or type(fingerprint) is not str:
        raise InvalidCell("caller credential key metadata is invalid")
    try:
        public_key = base64.b64decode(encoded_key, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key)
    except (ValueError, TypeError) as exc:
        raise InvalidCell("caller credential public key is invalid") from exc
    if fingerprint != _caller_key_fingerprint(public_key):
        raise InvalidCell("caller credential fingerprint does not match")
    return public_key, fingerprint


# The policy walk asks for the same relation's members thousands of times
# per evaluation and hundreds of evaluations per boot; a snapshot is
# immutable, so a relation's member facts are a pure function of
# (snapshot, relation root). The memo HOLDS the mapping it keys on -- an
# id is stable only while its object lives -- and a new snapshot starts a
# new memo. Bounded to a handful of snapshots; a write publishes a new
# mapping and the old memo falls away.
_POLICY_MEMBER_MEMO: dict[int, tuple[Mapping[str, Cell], dict]] = {}


def _policy_members(snapshot: Snapshot, relation_root: str, budget: int):
    key = id(snapshot.cells)
    held = _POLICY_MEMBER_MEMO.get(key)
    if held is None or held[0] is not snapshot.cells:
        if len(_POLICY_MEMBER_MEMO) >= 4:
            _POLICY_MEMBER_MEMO.pop(next(iter(_POLICY_MEMBER_MEMO)))
        held = (snapshot.cells, {})
        _POLICY_MEMBER_MEMO[key] = held
    memo = held[1]
    facts = memo.get(relation_root)
    if facts is None:
        facts = tuple(
            (
                member.incidence_id,
                member.role_id,
                member.participant_id,
            )
            for member in read_relation(snapshot, relation_root, budget=budget)
        )
        memo[relation_root] = facts
    return facts


def _policy_primitive_facts(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
):
    protocol = authority.logic_protocol()

    def provide(
        predicate_root: str,
        arguments: tuple[str | None, ...],
        budget: int,
    ) -> tuple[PrimitiveFact, ...]:
        if predicate_root == protocol.bound_predicate:
            if not arguments or any(value is None for value in arguments):
                return ()
            values = tuple(value for value in arguments if value is not None)
            return (PrimitiveFact(
                protocol.bound_predicate,
                values,
                (protocol.bound_predicate,),
            ),)
        if predicate_root != protocol.relation_member_predicate:
            return ()
        if len(arguments) != 3 or arguments[0] is None:
            return ()
        relation_root = arguments[0]
        if relation_root not in snapshot.cells:
            return ()
        facts: list[PrimitiveFact] = []
        want_role, want_participant = arguments[1], arguments[2]
        for incidence_id, role_id, participant_id in _policy_members(
            snapshot, relation_root, budget
        ):
            if want_role is not None and want_role != role_id:
                continue
            if want_participant is not None and want_participant != participant_id:
                continue
            facts.append(PrimitiveFact(
                incidence_id,
                (relation_root, role_id, participant_id),
                (relation_root, incidence_id, role_id, participant_id),
            ))
        return tuple(facts)

    return provide


def _matching_policy_proofs(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    *,
    actor_root: str,
    session_root: str,
    intent: str,
    scope_root: str,
    object_root: str,
    budget: int,
) -> tuple[LogicProof, ...]:
    policy = read_relation(
        snapshot, authority.manifest.policy_root, budget=budget
    )
    predicates = tuple(
        member.participant_id
        for member in policy
        if member.role_id == authority.role("predicate")
    )
    if len(predicates) != 1:
        raise InvalidCell("policy requires one graph-held decision predicate")
    return evaluate_logic(
        snapshot,
        authority.logic_protocol(),
        authority.manifest.policy_root,
        predicate_root=predicates[0],
        arguments=(actor_root, session_root, intent, scope_root, object_root),
        primitive_facts=_policy_primitive_facts(authority, snapshot),
        budget=budget,
        max_proofs=2,
    )


def _build_logic_binding(
    variable_root: str,
    value_root: str,
) -> tuple[str, Cell]:
    root = _new_id()
    return root, Cell(root, variable_root, value_root, b"")


def _build_logic_proof(
    authority: UnifiedAuthority,
    proof: LogicProof,
    *,
    base_revision: int,
) -> tuple[str, tuple[Cell, ...]]:
    cells: list[Cell] = []
    root = _new_id()
    base_snapshot = authority.store.at(base_revision)
    base_root, base_cell = _build_scalar_leaf(base_revision)
    cells.append(base_cell)
    literal_roots: dict[str, str] = {}
    binding_roots: dict[tuple[str, str], str] = {}

    def binding_for(variable: str, value: str) -> str:
        key = (variable, value)
        existing = binding_roots.get(key)
        if existing is not None:
            return existing
        if value in base_snapshot.cells:
            value_root = value
        else:
            if _is_opaque_id(value):
                raise InvalidCell("logic proof binding references an unknown identity")
            value_root = literal_roots.get(value, "")
            if not value_root:
                value_root, value_cell = _build_scalar_leaf(value)
                literal_roots[value] = value_root
                cells.append(value_cell)
        binding_root, binding_cell = _build_logic_binding(variable, value_root)
        cells.append(binding_cell)
        binding_roots[key] = binding_root
        return binding_root

    step_roots: list[str] = []
    for step in proof.steps:
        step_root = _new_id()
        step_bindings = [
            binding_for(variable, value)
            for variable, value in sorted(step.bindings.items())
        ]
        binding_sequence, binding_cells = build_cell_sequence(step_bindings)
        cells.extend(binding_cells)
        cells.append(Cell(step_root, step.rule_root, binding_sequence, b""))
        step_roots.append(step_root)
    step_sequence, step_cells = build_cell_sequence(step_roots)
    read_sequence, read_cells = build_cell_sequence(proof.read_roots)
    cells.extend((*step_cells, *read_cells))
    cells.extend(_typed_relation_cells(
        root,
        authority.role("conforms-to"),
        authority.shape("logic-proof"),
        (
            (authority.role("rule"), proof.top_rule_root),
            (authority.role("base-revision"), base_root),
            (authority.role("step"), step_sequence),
            (authority.role("read-set"), read_sequence),
        ),
    ))
    return root, tuple(cells)


def _read_logic_bindings(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    base_snapshot: Snapshot,
    roots: Iterable[str],
) -> Mapping[str, str]:
    values: dict[str, str] = {}
    for root in roots:
        binding = snapshot.cells.get(root)
        if (
            binding is None
            or binding.atom
            or binding.link0 == NULL_CELL_ID
            or binding.link1 == NULL_CELL_ID
            or binding.link0 not in base_snapshot.cells
            or root in base_snapshot.cells
        ):
            raise InvalidCell("logic proof binding relation is invalid")
        variable = binding.link0
        if binding.link1 in base_snapshot.cells:
            value = binding.link1
        else:
            literal = snapshot.cells.get(binding.link1)
            if (
                literal is None
                or literal.link0 != NULL_CELL_ID
                or literal.link1 != NULL_CELL_ID
                or not literal.atom
            ):
                raise InvalidCell("logic proof binding value is invalid")
            value = _decode_scalar_leaf(snapshot, binding.link1)
        if type(value) is not str or variable in values:
            raise InvalidCell("logic proof binding is invalid or duplicated")
        values[variable] = value
    return MappingProxyType(dict(sorted(values.items())))


def _read_logic_proof(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    root: str,
    *,
    expected_base_revision: int,
) -> LogicProof:
    projected = validate_composition(authority, snapshot, root)
    if projected.protocol_root != authority.shape("logic-proof"):
        raise InvalidCell("command policy evidence is not a logic proof")
    base_revision = _decode_scalar_leaf(
        snapshot,
        _single_member(snapshot, root, authority.role("base-revision")),
    )
    if base_revision != expected_base_revision:
        raise InvalidCell("logic proof base revision does not match its command")
    base_snapshot = authority.store.at(expected_base_revision)
    steps: list[LogicProofStep] = []
    step_roots = read_cell_sequence(
        snapshot,
        _single_member(snapshot, root, authority.role("step")),
    )
    for step_root in step_roots:
        step = snapshot.cells.get(step_root)
        if (
            step is None
            or step.atom
            or step.link0 not in base_snapshot.cells
            or step_root in base_snapshot.cells
        ):
            raise InvalidCell("logic proof step relation is invalid")
        binding_roots = read_cell_sequence(snapshot, step.link1)
        step_bindings = _read_logic_bindings(
            authority,
            snapshot,
            base_snapshot,
            binding_roots,
        )
        steps.append(LogicProofStep(
            step.link0,
            step_bindings,
            (),
        ))
    top_rule_root = _single_member(snapshot, root, authority.role("rule"))
    top_steps = tuple(step for step in steps if step.rule_root == top_rule_root)
    if len(top_steps) != 1:
        raise InvalidCell("logic proof requires one exact top-rule step")
    return LogicProof(
        top_rule_root,
        top_steps[0].bindings,
        tuple(steps),
        tuple(sorted(read_cell_sequence(
            snapshot,
            _single_member(snapshot, root, authority.role("read-set")),
        ))),
    )


def _authorize_semantic_read(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    caller: CallerCommandCapability,
    *,
    object_root: str,
    scope_root: str,
    budget: int,
) -> str:
    """Authenticate and authorize one semantic read at an exact graph head."""
    _verify_exact_snapshot_head(authority, snapshot)
    actor_root = getattr(caller, "actor_root", None)
    session_root = getattr(caller, "session_root", None)
    caller_public_key = getattr(caller, "public_key", None)
    if (
        type(actor_root) is not str
        or type(session_root) is not str
        or type(caller_public_key) is not bytes
        or object_root not in snapshot.cells
        or scope_root not in snapshot.cells
    ):
        raise InvalidCell("semantic read caller or target is invalid")
    session = validate_composition(authority, snapshot, session_root, budget=budget)
    if session.protocol_root != authority.shape("composition"):
        raise InvalidCell("semantic read session has the wrong protocol")
    if (
        _single_member(snapshot, session_root, authority.role("actor"), budget=budget)
        != actor_root
    ):
        raise InvalidCell("semantic read session actor is invalid")
    credential_root = _single_member(
        snapshot, session_root, authority.role("credential"), budget=budget
    )
    public_key, fingerprint = _credential_public_key(
        authority,
        snapshot,
        credential_root,
        actor_root=actor_root,
        session_root=session_root,
    )
    if caller_public_key != public_key:
        raise InvalidCell("semantic read capability key does not match")
    current = _current_head_member(authority, snapshot)
    if current is None:
        raise InvalidCell("semantic read has no signed graph challenge")
    payload = _canonical_json({
        "actor": actor_root,
        "audience": authority.manifest.graph_id,
        "credential": credential_root,
        "head": current.participant_id,
        "intent": "read",
        "object": object_root,
        "revision": snapshot.revision,
        "schema": "ArchHub/semantic-read/v1",
        "scope": scope_root,
        "session": session_root,
        "signing_key_fingerprint": fingerprint,
    })
    try:
        signature = caller.sign(payload)
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes(signature), payload
        )
    except (AttributeError, TypeError, ValueError, InvalidSignature) as exc:
        raise InvalidCell("semantic read caller signature is invalid") from exc
    try:
        matching = _matching_policy_proofs(
            authority,
            snapshot,
            actor_root=actor_root,
            session_root=session_root,
            intent="read",
            scope_root=scope_root,
            object_root=object_root,
            budget=budget,
        )
    except MatchBudgetExceeded as exc:
        raise InvalidCell(
            "semantic read authorization exceeded its budget"
        ) from exc
    if len(matching) != 1:
        raise InvalidCell("semantic read is not authorized by graph policy")
    return matching[0].top_rule_root


def _command_projection(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    command_root: str,
) -> _CommandProjection:
    command = validate_composition(authority, snapshot, command_root)
    if command.protocol_root != authority.shape("command"):
        raise InvalidCell("receipt command has the wrong structural protocol")
    actor_root = _single_member(snapshot, command_root, authority.role("actor"))
    session_root = _single_member(snapshot, command_root, authority.role("session"))
    credential_root = _single_member(
        snapshot, command_root, authority.role("credential")
    )
    object_root = _single_member(snapshot, command_root, authority.role("object"))
    scope_root = _single_member(snapshot, command_root, authority.role("scope"))
    challenge_head = _single_member(snapshot, command_root, authority.role("head"))
    policy_members = tuple(
        member.participant_id
        for member in command.members
        if member.role_id == authority.role("policy")
    )
    if len(policy_members) > 1:
        raise InvalidCell("command repeats its graph policy proof")
    policy_proof_root = policy_members[0] if policy_members else None
    values = {
        role_name: _decode_scalar_leaf(
            snapshot,
            _single_member(snapshot, command_root, authority.role(role_name)),
        )
        for role_name in (
            "intent", "idempotency-key", "request-digest", "base-revision",
            "budget", "audience", "issued-at", "expires-at",
            "key-fingerprint", "signature",
        )
    }
    if (
        type(values["intent"]) is not str
        or type(values["idempotency-key"]) is not str
        or type(values["request-digest"]) is not str
        or type(values["base-revision"]) is not int
        or type(values["budget"]) is not int
        or type(values["issued-at"]) is not str
        or type(values["expires-at"]) is not str
        or type(values["key-fingerprint"]) is not str
        or type(values["signature"]) is not str
        or values["audience"] != authority.manifest.graph_id
        or values["idempotency-key"] != command_root
    ):
        raise InvalidCell("command scalar fields are invalid")
    public_key, fingerprint = _credential_public_key(
        authority,
        snapshot,
        credential_root,
        actor_root=actor_root,
        session_root=session_root,
    )
    if values["key-fingerprint"] != fingerprint:
        raise InvalidCell("command signing identity is invalid")
    try:
        issued = datetime.fromisoformat(values["issued-at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(values["expires-at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidCell("command validity window is invalid") from exc
    if (
        issued.tzinfo is None
        or expires.tzinfo is None
        or expires <= issued
        or expires - issued > timedelta(minutes=2)
    ):
        raise InvalidCell("command validity window is invalid")
    base_snapshot = authority.store.at(values["base-revision"])
    challenged_head = _current_head_member(authority, base_snapshot)
    if challenged_head is None or challenged_head.participant_id != challenge_head:
        raise InvalidCell("command graph challenge does not match its base revision")
    _verify_authority_head(authority, base_snapshot, challenge_head)
    payload = _command_payload(
        authority,
        actor_root=actor_root,
        session_root=session_root,
        credential_root=credential_root,
        object_root=object_root,
        scope_root=scope_root,
        intent=values["intent"],
        idempotency_key=values["idempotency-key"],
        request_digest=values["request-digest"],
        base_revision=values["base-revision"],
        budget=values["budget"],
        challenge_head=challenge_head,
        issued_at=values["issued-at"],
        expires_at=values["expires-at"],
        key_fingerprint=fingerprint,
    )
    try:
        signature = base64.b64decode(values["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, _canonical_json(payload)
        )
    except (ValueError, InvalidSignature) as exc:
        raise InvalidCell("command caller signature is invalid") from exc
    matching_proofs = _matching_policy_proofs(
        authority,
        base_snapshot,
        actor_root=actor_root,
        session_root=session_root,
        intent=values["intent"],
        scope_root=scope_root,
        object_root=object_root,
        budget=values["budget"],
    )
    if policy_proof_root is None:
        if len(matching_proofs) == 1:
            raise InvalidCell("denied command omitted its graph policy proof")
    elif len(matching_proofs) != 1 or _read_logic_proof(
        authority,
        snapshot,
        policy_proof_root,
        expected_base_revision=values["base-revision"],
    ) != matching_proofs[0]:
        raise InvalidCell("command graph policy proof is not authoritative")
    return _CommandProjection(
        command_root,
        values["idempotency-key"],
        values["intent"],
        values["request-digest"],
        values["base-revision"],
        object_root,
        scope_root,
        policy_proof_root,
        values["budget"],
        values["issued-at"],
        values["expires-at"],
    )


def _receipt_projection(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    receipt_root: str,
) -> _ReceiptProjection:
    projection = validate_composition(authority, snapshot, receipt_root)
    if projection.protocol_root != authority.shape("receipt"):
        raise InvalidCell("history receipt has the wrong structural protocol")
    result_root = _single_member(snapshot, receipt_root, authority.role("result"))
    head_root = _single_member(snapshot, receipt_root, authority.role("head"))
    command_root = _single_member(
        snapshot, receipt_root, authority.role("command")
    )
    result_revision = _decode_scalar_leaf(
        snapshot,
        _single_member(snapshot, receipt_root, authority.role("result-revision")),
    )
    decision = _decode_scalar_leaf(
        snapshot,
        _single_member(snapshot, receipt_root, authority.role("decision")),
    )
    accepted_at = _decode_scalar_leaf(
        snapshot,
        _single_member(snapshot, receipt_root, authority.role("accepted-at")),
    )
    if (
        type(result_revision) is not int
        or decision not in {"allow", "deny"}
        or type(accepted_at) is not str
    ):
        raise InvalidCell("receipt request digest is invalid")
    committed_snapshot = authority.store.at(result_revision)
    command = _command_projection(authority, committed_snapshot, command_root)
    actor_root = _single_member(
        committed_snapshot, command.root_id, authority.role("actor")
    )
    session_root = _single_member(
        committed_snapshot, command.root_id, authority.role("session")
    )
    try:
        accepted = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
        issued = datetime.fromisoformat(command.issued_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(command.expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidCell("receipt acceptance time is invalid") from exc
    if (
        receipt_root
        != _single_member(
            committed_snapshot, command.root_id, authority.role("receipt")
        )
        or result_revision != command.base_revision + 1
        or accepted.tzinfo is None
        or issued.tzinfo is None
        or expires.tzinfo is None
        or accepted < issued
        or accepted >= expires
        or (decision == "allow") != (command.policy_proof_root is not None)
    ):
        raise InvalidCell("receipt does not match its signed command")
    committed_head = _current_head_member(authority, committed_snapshot)
    if committed_head is None or committed_head.participant_id != head_root:
        raise InvalidCell("receipt does not identify its committed authority head")
    _verify_authority_head(authority, committed_snapshot, head_root)
    return _ReceiptProjection(
        receipt_root,
        command.request_digest,
        result_root,
        result_revision,
        actor_root,
        session_root,
        command.idempotency_key,
        decision,
        command.policy_proof_root,
    )


def _find_receipt(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    actor_root: str,
    session_root: str,
    command_id: str,
) -> _ReceiptProjection | None:
    if command_id not in snapshot.cells:
        return None
    command = _command_projection(authority, snapshot, command_id)
    receipt_root = _single_member(
        snapshot, command.root_id, authority.role("receipt"), budget=512
    )
    receipt = _receipt_projection(authority, snapshot, receipt_root)
    if (
        receipt.actor_root != actor_root
        or receipt.session_root != session_root
        or receipt.idempotency_key != command_id
    ):
        raise InvalidCell("command identity is already owned by another caller")
    return receipt


def _validate_command_participants(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    caller: CallerCommandCapability,
    command_id: str,
    *,
    intent: str,
    request_digest: str,
    object_root: str,
    scope_root: str,
    budget: int,
) -> tuple[_AuthenticatedRequest, LogicProof | None]:
    _verify_exact_snapshot_head(authority, snapshot)
    actor_root = getattr(caller, "actor_root", None)
    session_root = getattr(caller, "session_root", None)
    caller_public_key = getattr(caller, "public_key", None)
    if (
        not _is_opaque_id(command_id)
        or not _is_opaque_id(actor_root)
        or not _is_opaque_id(session_root)
        or type(caller_public_key) is not bytes
    ):
        raise InvalidCell("command requires an authenticated caller capability")
    if type(budget) is not int or budget < 1:
        raise InvalidCell("command budget is invalid")
    if any(
        root not in snapshot.cells
        for root in (actor_root, session_root, object_root, scope_root)
    ):
        raise InvalidCell("command participant is missing")
    bound_actor = _single_member(
        snapshot, session_root, authority.role("actor")
    )
    if bound_actor != actor_root:
        raise InvalidCell("session is not bound to the command actor")
    constitution_members = read_relation(
        snapshot, authority.manifest.constitution_root, budget=100_000
    )
    admitted_actors = {
        member.participant_id
        for member in constitution_members
        if member.role_id == authority.role("actor")
    }
    admitted_sessions = {
        member.participant_id
        for member in constitution_members
        if member.role_id == authority.role("session")
    }
    if actor_root not in admitted_actors or session_root not in admitted_sessions:
        raise InvalidCell("command actor or session is outside the signed constitution")
    credential_root = _single_member(
        snapshot, session_root, authority.role("credential"), budget=budget
    )
    public_key, fingerprint = _credential_public_key(
        authority,
        snapshot,
        credential_root,
        actor_root=actor_root,
        session_root=session_root,
    )
    if public_key != caller_public_key:
        raise InvalidCell("caller capability key does not match the graph credential")
    current = _current_head_member(authority, snapshot)
    if current is None:
        raise InvalidCell("caller request has no signed graph challenge")
    issued = _utc_now()
    expires = issued + timedelta(minutes=2)
    issued_at = issued.isoformat(timespec="microseconds").replace("+00:00", "Z")
    expires_at = expires.isoformat(timespec="microseconds").replace("+00:00", "Z")
    request = _AuthenticatedRequest(
        actor_root,
        session_root,
        credential_root,
        command_id,
        intent,
        request_digest,
        snapshot.revision,
        object_root,
        scope_root,
        budget,
        current.participant_id,
        issued_at,
        expires_at,
        fingerprint,
        "",
    )
    payload = _command_payload(
        authority,
        actor_root=request.actor_root,
        session_root=request.session_root,
        credential_root=request.credential_root,
        object_root=request.object_root,
        scope_root=request.scope_root,
        intent=request.intent,
        idempotency_key=request.command_id,
        request_digest=request.request_digest,
        base_revision=request.base_revision,
        budget=request.budget,
        challenge_head=request.challenge_head,
        issued_at=request.issued_at,
        expires_at=request.expires_at,
        key_fingerprint=request.public_key_fingerprint,
    )
    try:
        signature = caller.sign(_canonical_json(payload))
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes(signature), _canonical_json(payload)
        )
    except (AttributeError, TypeError, ValueError, InvalidSignature) as exc:
        raise InvalidCell("caller request signature is invalid") from exc
    request = replace(
        request,
        signature=base64.b64encode(bytes(signature)).decode("ascii"),
    )
    if _utc_now() >= expires:
        raise InvalidCell("caller request expired before authorization")
    existing = _find_receipt(
        authority, snapshot, actor_root, session_root, command_id
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        if existing.decision == "deny":
            raise AuthorizationDenied(
                existing.root_id, existing.result_revision, replayed=True
            )
        if existing.policy_proof_root is None:
            raise InvalidCell("accepted receipt has no authoritative graph proof")
        return request, None

    allowed = _matching_policy_proofs(
        authority,
        snapshot,
        actor_root=actor_root,
        session_root=session_root,
        intent=intent,
        scope_root=scope_root,
        object_root=object_root,
        budget=budget,
    )
    if len(allowed) != 1:
        denial = _commit_with_receipt(
            authority,
            snapshot,
            resource_create=(),
            resource_replace=(),
            authenticated=request,
            result_root=object_root,
            policy_proof=None,
            decision="deny",
        )
        raise AuthorizationDenied(denial.receipt_root, denial.revision, replayed=False)
    return request, allowed[0]


def _build_receipt(
    authority: UnifiedAuthority,
    *,
    receipt_root: str,
    command_root: str,
    head_root: str,
    result_revision: int,
    result_root: str,
    decision: str,
    accepted_at: str,
) -> tuple[str, tuple[Cell, ...]]:
    cells: list[Cell] = []
    members: list[tuple[str, str]] = [
        (authority.role("result"), result_root),
        (authority.role("command"), command_root),
        (authority.role("head"), head_root),
    ]
    values = {
        "result-revision": result_revision,
        "decision": decision,
        "accepted-at": accepted_at,
    }
    for role_name, value in values.items():
        value_root, value_cell = _build_scalar_leaf(value)
        cells.append(value_cell)
        members.append((authority.role(role_name), value_root))
    cells.extend(_typed_relation_cells(
        receipt_root,
        authority.role("conforms-to"),
        authority.shape("receipt"),
        members,
    ))
    return receipt_root, tuple(cells)


def _definition_spec(
    name: str,
    version: str,
    lifecycle: str,
    defaults: Mapping[str, object] | None,
    parameters: Mapping[str, object] | None,
    interfaces: Mapping[str, object] | None,
    rules: Mapping[str, object] | None,
    presentation: Mapping[str, object] | None,
    courts: Mapping[str, object] | None,
    provenance: Mapping[str, object] | None,
    evidence_roots: Iterable[str] = (),
) -> dict[str, object]:
    if not name.strip() or not version.strip() or lifecycle not in LIFECYCLE_NAMES:
        raise InvalidCell("definition metadata is invalid")
    evidence = tuple(sorted(set(str(root) for root in evidence_roots)))
    if any(not _is_opaque_id(root) for root in evidence):
        raise InvalidCell("definition evidence identity is invalid")
    return {
        "name": name.strip(),
        "version": version.strip(),
        "lifecycle": lifecycle,
        "defaults": _normalized_mapping(defaults),
        "parameters": _normalized_mapping(parameters),
        "interfaces": _normalized_mapping(interfaces),
        "rules": _normalized_mapping(rules),
        "presentation": _normalized_mapping(presentation),
        "courts": _normalized_mapping(courts),
        "provenance": _normalized_mapping(provenance),
        "evidence": evidence,
    }


def _build_definition_revision(
    authority: UnifiedAuthority,
    spec: Mapping[str, object],
    *,
    previous_revision_root: str | None = None,
) -> tuple[str, str, tuple[Cell, ...]]:
    revision_root = _new_id()
    cells: list[Cell] = []
    members: list[tuple[str, str]] = []
    for role_name, value in (
        ("label", spec["name"]),
        ("version", spec["version"]),
        ("content-digest", _digest(spec)),
    ):
        value_root, value_cells = _build_value(
            authority.roles,
            authority.codecs[CODEC_NAME],
            value,
            shape_root=authority.shape("value"),
        )
        cells.extend(value_cells)
        members.append((authority.role(role_name), value_root))
    members.append((authority.role("lifecycle"), authority.state(str(spec["lifecycle"]))))
    if previous_revision_root is not None:
        members.append((authority.role("previous-revision"), previous_revision_root))
    members.extend(
        (authority.role("evidence"), evidence_root)
        for evidence_root in spec["evidence"]  # type: ignore[union-attr]
    )
    for contract_name in CONTRACT_NAMES:
        contract_root, contract_cells = _build_contract(
            authority, spec[contract_name]  # type: ignore[arg-type]
        )
        cells.extend(contract_cells)
        members.append((authority.role(contract_name), contract_root))
    cells.extend(_typed_relation_cells(
        revision_root,
        authority.role("conforms-to"),
        authority.shape("definition-revision"),
        members,
    ))
    return revision_root, _digest(spec), tuple(cells)


def _commit_with_receipt(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    *,
    resource_create: tuple[Cell, ...],
    resource_replace: tuple[Cell, ...],
    authenticated: _AuthenticatedRequest,
    result_root: str,
    policy_proof: LogicProof | None,
    decision: str = "allow",
) -> CommandResult:
    if (decision == "allow") != (policy_proof is not None):
        raise InvalidCell("receipt decision and graph policy proof disagree")
    if decision not in {"allow", "deny"}:
        raise InvalidCell("receipt decision is invalid")
    try:
        expires = datetime.fromisoformat(
            authenticated.expires_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise InvalidCell("authenticated request expiry is invalid") from exc
    accepted = _utc_now()
    if expires.tzinfo is None or accepted >= expires:
        raise InvalidCell("authenticated request expired before commit")
    accepted_at = accepted.isoformat(timespec="microseconds").replace("+00:00", "Z")
    result_revision = snapshot.revision + 1
    head_root = _new_id()
    receipt_root = _new_id()
    policy_proof_root: str | None = None
    policy_proof_cells: tuple[Cell, ...] = ()
    if policy_proof is not None:
        policy_proof_root, policy_proof_cells = _build_logic_proof(
            authority,
            policy_proof,
            base_revision=snapshot.revision,
        )
    command_root, command_cells = _build_command(
        authority,
        authenticated,
        policy_proof_root=policy_proof_root,
        receipt_root=receipt_root,
    )
    built_receipt_root, receipt_cells = _build_receipt(
        authority,
        receipt_root=receipt_root,
        command_root=command_root,
        head_root=head_root,
        result_revision=result_revision,
        result_root=result_root,
        decision=decision,
        accepted_at=accepted_at,
    )
    if built_receipt_root != receipt_root:
        raise InvalidCell("receipt identity allocation is inconsistent")
    history_patch = _append_relation_member(
        snapshot,
        authority.manifest.history_root,
        authority.role("receipt"),
        receipt_root,
    )
    revision = _commit_signed_change(
        authority,
        snapshot,
        create=(
            *resource_create,
            *policy_proof_cells,
            *command_cells,
            *receipt_cells,
            *history_patch.create,
        ),
        replace_cells=(*resource_replace, *history_patch.replace),
        head_root=head_root,
    )
    return CommandResult(
        result_root,
        revision,
        False,
        len(resource_create),
        len(policy_proof_cells) + len(command_cells) + len(receipt_cells) + len(history_patch.create),
        receipt_root,
    )


def _labelled_composition_cells(
    authority: UnifiedAuthority,
    root_id: str,
    label: str,
    members: Iterable[tuple[str, str]],
) -> tuple[Cell, ...]:
    label_root, label_cells = _build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        label,
        shape_root=authority.shape("value"),
    )
    return (
        *label_cells,
        *_typed_relation_cells(
            root_id,
            authority.role("conforms-to"),
            authority.shape("composition"),
            ((authority.role("label"), label_root), *tuple(members)),
        ),
    )


def enroll_session(
    authority: UnifiedAuthority,
    label: str,
    public_key: bytes,
    *,
    session_container_root: str,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Admit one graph session whose private signing key remains external."""
    normalized_label = str(label).strip()
    try:
        key_bytes = bytes(public_key)
        Ed25519PublicKey.from_public_bytes(key_bytes)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("session enrollment public key is invalid") from exc
    if not normalized_label or len(normalized_label) > 256:
        raise InvalidCell("session enrollment label is invalid")
    encoded_key = base64.b64encode(key_bytes).decode("ascii")
    fingerprint = _caller_key_fingerprint(key_bytes)
    request_digest = _digest({
        "intent": "enroll-session",
        "label": normalized_label,
        "public_key": encoded_key,
        "session_container": session_container_root,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="enroll-session",
        request_digest=request_digest,
        object_root=authority.manifest.constitution_root,
        scope_root=authority.manifest.application_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    _validate_composition_scope(authority, snapshot, session_container_root)

    session_root = _new_id()
    credential_root = _new_id()
    key_root, key_cells = _build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        encoded_key,
        shape_root=authority.shape("value"),
    )
    algorithm_root, algorithm_cells = _build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        "ed25519",
        shape_root=authority.shape("value"),
    )
    fingerprint_root, fingerprint_cells = _build_value(
        authority.roles,
        authority.codecs[CODEC_NAME],
        fingerprint,
        shape_root=authority.shape("value"),
    )
    credential_cells = _labelled_composition_cells(
        authority,
        credential_root,
        normalized_label + " credential",
        (
            (authority.role("actor"), authenticated.actor_root),
            (authority.role("session"), session_root),
            (authority.role("key"), key_root),
            (authority.role("algorithm"), algorithm_root),
            (authority.role("key-fingerprint"), fingerprint_root),
            (authority.role("lifecycle"), authority.state("published")),
        ),
    )
    session_cells = _labelled_composition_cells(
        authority,
        session_root,
        normalized_label,
        (
            (authority.role("actor"), authenticated.actor_root),
            (authority.role("credential"), credential_root),
            (authority.role("lifecycle"), authority.state("published")),
        ),
    )
    constitution_patch = _append_relation_members(
        snapshot,
        authority.manifest.constitution_root,
        (
            (authority.role("session"), session_root),
            (authority.role("credential"), credential_root),
        ),
    )
    container_patch = _append_relation_member(
        snapshot,
        session_container_root,
        authority.role("composition"),
        session_root,
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *key_cells,
            *algorithm_cells,
            *fingerprint_cells,
            *credential_cells,
            *session_cells,
            *constitution_patch.create,
            *container_patch.create,
        ),
        resource_replace=(
            *constitution_patch.replace,
            *container_patch.replace,
        ),
        authenticated=authenticated,
        result_root=session_root,
        policy_proof=policy_proof,
    )


def revoke_session(
    authority: UnifiedAuthority,
    session_root: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Revoke a graph session credential without deleting its history."""
    request_digest = _digest({
        "intent": "revoke-session",
        "session": session_root,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="revoke-session",
        request_digest=request_digest,
        object_root=session_root,
        scope_root=authority.manifest.application_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    session = validate_composition(authority, snapshot, session_root)
    if session.protocol_root != authority.shape("composition"):
        raise InvalidCell("session revocation target has the wrong protocol")
    if (
        _single_member(snapshot, session_root, authority.role("actor"))
        != authenticated.actor_root
    ):
        raise InvalidCell("session revocation actor is invalid")
    credential_root = _single_member(
        snapshot, session_root, authority.role("credential")
    )
    lifecycle_members = tuple(
        member
        for member in read_relation(snapshot, credential_root, budget=COMMAND_BUDGET)
        if member.role_id == authority.role("lifecycle")
    )
    if (
        len(lifecycle_members) != 1
        or lifecycle_members[0].participant_id != authority.state("published")
    ):
        raise InvalidCell("session credential is already revoked")
    incidence = snapshot.cells[lifecycle_members[0].incidence_id]
    replacement = Cell(
        incidence.id,
        incidence.link0,
        authority.state("archived"),
        incidence.atom,
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(),
        resource_replace=(replacement,),
        authenticated=authenticated,
        result_root=session_root,
        policy_proof=policy_proof,
    )


def published_definition_named(
    authority: UnifiedAuthority,
    name: str,
    *,
    caller: CallerCommandCapability,
) -> str | None:
    """The root of the one PUBLISHED catalogue definition called ``name``.

    An installer that re-runs its exact commands at every boot only to find
    the receipts it left re-projects each command at its original revision
    -- on the founder's graph, 16 s and 37 s at every start for definitions
    that were published weeks ago. The catalogue the audited head holds
    already answers the question. None when the name is absent or held by
    more than one published definition, so the caller falls back to its
    exact replay and nothing is guessed.
    """
    snapshot = authority.store.snapshot()
    found: list[str] = []
    for member in read_relation(
        snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
    ):
        if member.role_id != authority.role("definition"):
            continue
        try:
            definition = read_definition(
                authority, member.participant_id, caller=caller
            )
        except InvalidCell:
            continue
        if definition.name == name and definition.lifecycle == "published":
            found.append(definition.root_id)
    if len(found) != 1:
        return None
    return found[0]


def declare_definition(
    authority: UnifiedAuthority,
    name: str,
    defaults: Mapping[str, object] | None = None,
    *,
    caller: CallerCommandCapability,
    command_id: str,
    version: str = "1",
    lifecycle: str = "wip",
    parameters: Mapping[str, object] | None = None,
    interfaces: Mapping[str, object] | None = None,
    rules: Mapping[str, object] | None = None,
    presentation: Mapping[str, object] | None = None,
    courts: Mapping[str, object] | None = None,
    provenance: Mapping[str, object] | None = None,
) -> CommandResult:
    """Declare one stable assembly identity and one immutable exact revision."""
    if lifecycle != "wip":
        raise InvalidCell("ordinary definition declaration must start in WIP")
    spec = _definition_spec(
        name,
        version,
        lifecycle,
        defaults,
        parameters,
        interfaces,
        rules,
        presentation,
        courts,
        provenance,
    )
    request_digest = _digest({"intent": "declare-definition", "spec": spec})
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="declare-definition",
        request_digest=request_digest,
        object_root=authority.manifest.catalogue_root,
        scope_root=authority.manifest.catalogue_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )

    definition_root = _new_id()
    revision_root, _, revision_cells = _build_definition_revision(authority, spec)
    definition_cells = _typed_relation_cells(
        definition_root,
        authority.role("conforms-to"),
        authority.shape("definition"),
        ((authority.role("current-revision"), revision_root),),
    )
    catalogue_patch = _append_relation_member(
        snapshot,
        authority.manifest.catalogue_root,
        authority.role("definition"),
        definition_root,
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(
            *revision_cells,
            *definition_cells,
            *catalogue_patch.create,
        ),
        resource_replace=catalogue_patch.replace,
        authenticated=authenticated,
        result_root=definition_root,
        policy_proof=policy_proof,
    )


PANEL_AUDIENCE = "any"
DEFAULT_SCOPE_PANELS = (("Properties", "properties"),)


def _scope_applicability(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    revision_root: str,
) -> tuple[str, str, tuple[RelationMember, ...]] | None:
    """Find the scope applicability a definition revision rests on.

    A definition cannot be asked which scope holds it, because relations only
    walk forwards. The import puts that answer in the revision's evidence
    instead, so a reviser reads its own evidence rather than searching the
    graph for something pointing back at it.
    """
    for member in read_relation(snapshot, revision_root, budget=COMMAND_BUDGET):
        if member.role_id != authority.role("evidence"):
            continue
        try:
            carried = read_relation(
                snapshot, member.participant_id, budget=COMMAND_BUDGET
            )
        except (InvalidCell, MatchBudgetExceeded):
            continue
        conforms = [
            each.participant_id
            for each in carried
            if each.role_id == authority.role("conforms-to")
        ]
        scopes = [
            each.participant_id
            for each in carried
            if each.role_id == authority.role("scope")
        ]
        if conforms == [authority.shape("relation")] and scopes:
            return member.participant_id, tuple(scopes), carried
    return None


def _declared_panel_labels(presentation: object) -> tuple[str, ...]:
    if not isinstance(presentation, Mapping):
        return ()
    declared = presentation.get("panels")
    if not isinstance(declared, (list, tuple)):
        return ()
    labels = tuple(str(label) for label in declared)
    if len(set(labels)) != len(labels):
        raise InvalidCell("presentation declares one panel label twice")
    return labels


def _panel_declared_by(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    panel_root: str,
) -> str | None:
    try:
        members = read_relation(snapshot, panel_root, budget=COMMAND_BUDGET)
    except (InvalidCell, MatchBudgetExceeded):
        return None
    declaring = [
        member.participant_id
        for member in members
        if member.role_id == authority.role("definition")
    ]
    return declaring[0] if len(declaring) == 1 else None


def _build_scope_panels(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    definition_root: str,
    revision_root: str,
    labels: tuple[str, ...],
) -> tuple[tuple[Cell, ...], tuple[Cell, ...]]:
    """Give every declared panel a root in the scope it applies to.

    A panel is something the graph holds, not a string a projector reads back
    out of a contract: it has an identity, the definition that declared it,
    and membership in the scope's one applicability relation. Revising the
    presentation contract replaces exactly the panels this definition
    contributed there, so a definition that declares none leaves none.

    The carriers are already-released shapes with an open role, so this adds
    no protocol and runs on a graph bootstrapped before it existed. A graph
    whose revisions carry no applicability -- one bootstrapped before the
    import seeded it and not yet migrated -- is left untouched rather than
    guessed at: install_scope_panels is the loud path for that state.
    """
    found = _scope_applicability(authority, snapshot, revision_root)
    if found is None:
        return (), ()
    applicability_root, _scope_root, current = found
    stale = tuple(
        member.incidence_id
        for member in current
        if member.role_id == authority.role("object")
        and _panel_declared_by(authority, snapshot, member.participant_id)
        == definition_root
    )
    codec_root = authority.codecs[CODEC_NAME]
    create: list[Cell] = []
    additions: list[tuple[str, str]] = []
    for label in labels:
        label_root, label_cells = _build_value(
            authority.roles,
            codec_root,
            label,
            shape_root=authority.shape("value"),
        )
        # A presentation contract declares panels by name. That released
        # shape carries labels and nothing else, and what such a panel
        # shows is the definition's own fields -- so the panel is written
        # saying so. Reading it back is then the same for every panel,
        # and no projector has to decide what an unstated tab presents.
        presenter_root, presenter_cells = _build_value(
            authority.roles,
            codec_root,
            "properties",
            shape_root=authority.shape("value"),
        )
        panel_root = _new_id()
        create.extend(label_cells)
        create.extend(presenter_cells)
        create.extend(_typed_relation_cells(
            panel_root,
            authority.role("conforms-to"),
            authority.shape("composition"),
            (
                (authority.role("label"), label_root),
                (authority.role("presentation"), presenter_root),
                (authority.role("definition"), definition_root),
            ),
        ))
        additions.append((authority.role("object"), panel_root))
    replace: list[Cell] = []
    staged = snapshot
    if stale:
        removal = prepare_remove_relation_members(
            staged, applicability_root, stale, budget=COMMAND_BUDGET
        )
        replace.extend(removal.replace)
        staged = overlay_read_snapshot(staged, replace=removal.replace)
    if additions:
        append = prepare_append_relation_members(
            staged, applicability_root, additions, budget=COMMAND_BUDGET
        )
        create.extend(append.create)
        replace.extend(append.replace)
    # Retiring then appending can touch one chain cell twice. A cell the
    # graph does not hold yet must stay a creation whatever touched it after.
    created: dict[str, Cell] = {cell.id: cell for cell in create}
    replaced: dict[str, Cell] = {}
    for cell in replace:
        if cell.id in created:
            created[cell.id] = cell
        else:
            replaced[cell.id] = cell
    return tuple(created.values()), tuple(replaced.values())


VIEW_DEFAULT_VIEWPORT = {"x": 0.0, "y": 0.0, "zoom": 1.0}


def _plain_json_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise InvalidCell("%s must be a mapping" % label)
    try:
        return json.loads(_canonical_json(dict(value)).decode("utf-8"))
    except InvalidCell:
        raise InvalidCell("%s is not plain data" % label) from None


def _composition_placement(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    interface_root: str,
    composition_root_id: str,
) -> tuple[str, tuple[RelationMember, ...]] | None:
    """Find the one placement relation for a composition inside its scope.

    A composition is a released shape whose reader refuses undeclared
    members -- and so is the scope that holds it, which is a composition
    too. Neither can carry the placement. Interface is the released
    open-role carrier for interface state, the same place a view session
    keeps its viewport, so placements register there and are found by
    walking its members forward rather than by searching the graph for
    whatever happens to point at a composition.
    """
    for member in read_relation(snapshot, interface_root, budget=COMMAND_BUDGET):
        if member.role_id != authority.role("object"):
            continue
        try:
            carried = read_relation(
                snapshot, member.participant_id, budget=COMMAND_BUDGET
            )
        except (InvalidCell, MatchBudgetExceeded):
            continue
        conforms = [
            each.participant_id for each in carried
            if each.role_id == authority.role("conforms-to")
        ]
        if conforms != [authority.shape("relation")]:
            continue
        subjects = [
            each.participant_id for each in carried
            if each.role_id == authority.role("composition")
        ]
        if subjects == [composition_root_id]:
            return member.participant_id, carried
    return None


# One placement index per immutable snapshot. Interface accumulates a
# placement for every node ever placed, and walking all of them on every
# canvas read is what a projection spends its time on once a real graph
# is laid out. The entry HOLDS the mapping it keys on: an id is stable
# while its object lives, not unique across time, and a cache that kept
# only the integer would answer for a snapshot that no longer exists.
_PLACEMENT_INDEX_CACHE: dict[
    tuple[int, int, str],
    tuple[Mapping[str, Cell], dict[str, str]],
] = {}


def _placement_index(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    interface_root: str,
) -> dict[str, str]:
    """Map each placed composition to the contract holding its position."""
    key = (id(snapshot.cells), snapshot.revision, interface_root)
    cached = _PLACEMENT_INDEX_CACHE.get(key)
    if cached is not None:
        held, index = cached
        if held is snapshot.cells:
            return index
    index: dict[str, str] = {}
    for member in read_relation(snapshot, interface_root, budget=COMMAND_BUDGET):
        if member.role_id != authority.role("object"):
            continue
        try:
            carried = read_relation(
                snapshot, member.participant_id, budget=COMMAND_BUDGET
            )
        except (InvalidCell, MatchBudgetExceeded):
            continue
        conforms = [
            each.participant_id for each in carried
            if each.role_id == authority.role("conforms-to")
        ]
        if conforms != [authority.shape("relation")]:
            continue
        placed = [
            each.participant_id for each in carried
            if each.role_id == authority.role("composition")
        ]
        presentations = [
            each.participant_id for each in carried
            if each.role_id == authority.role("presentation")
        ]
        if len(placed) == 1 and len(presentations) == 1:
            index[placed[0]] = presentations[0]
    if len(_PLACEMENT_INDEX_CACHE) >= 8:
        _PLACEMENT_INDEX_CACHE.pop(next(iter(_PLACEMENT_INDEX_CACHE)))
    _PLACEMENT_INDEX_CACHE[key] = (snapshot.cells, index)
    return index


def read_composition_placements(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    interface_root: str,
    wanted: Iterable[str] | None = None,
) -> dict[str, dict[str, object]]:
    """The placements Interface holds for the compositions asked about.

    Interface accumulates one placement per node ever placed, across
    every scope, while a canvas shows one scope at a time. Decoding all
    of them to draw fifteen nodes is what turned a canvas read into
    seventeen seconds; the position is only decoded for a node the
    caller actually asked about.
    """
    index = _placement_index(authority, snapshot, interface_root)
    subjects = index.keys() if wanted is None else (
        root for root in wanted if root in index
    )
    return {
        root: _property_values(authority, snapshot, index[root])
        for root in subjects
    }


def group_compositions(
    authority: UnifiedAuthority,
    scope_root: str,
    member_roots: Iterable[str],
    *,
    label: str,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Fold selected scope members into one new openable composition.

    The group is an ordinary composition -- the same shape every Grand Map
    domain has -- holding the selected roots as its members; the scope
    stops holding them directly and holds the group. One signed commit:
    the members' incidences move, nothing is deleted, and ungroup reverses
    it with the same machinery.
    """
    members = tuple(dict.fromkeys(
        str(root) for root in member_roots if str(root).strip()
    ))
    if len(members) < 2:
        raise InvalidCell("a group needs at least two members")
    if type(label) is not str or not label.strip():
        raise InvalidCell("a group needs a label")
    request_digest = _digest({
        "intent": "group-compositions",
        "scope": scope_root,
        "members": members,
        "label": label,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="group-compositions",
        request_digest=request_digest,
        object_root=scope_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root, existing.result_revision, True, 0, 0,
            existing.root_id,
        )
    held = {
        member.participant_id: member.incidence_id
        for member in read_relation(snapshot, scope_root, budget=COMMAND_BUDGET)
        if member.role_id == authority.role("composition")
    }
    missing = [root for root in members if root not in held]
    if missing:
        raise InvalidCell("group members must all be members of this scope")
    group_root = _new_id()
    cells = list(_labelled_composition_cells(
        authority,
        group_root,
        label.strip(),
        tuple((authority.role("composition"), root) for root in members),
    ))
    removal = prepare_remove_relation_members(
        snapshot,
        scope_root,
        tuple(held[root] for root in members),
        budget=COMMAND_BUDGET,
    )
    staged = overlay_read_snapshot(snapshot, replace=removal.replace)
    staged = Snapshot(snapshot.revision, staged.cells)
    scope_patch = _append_relation_member(
        staged,
        scope_root,
        authority.role("composition"),
        group_root,
    )
    # The removal and the append can touch the same chain cell (the tail
    # being relinked twice). The append was computed on the staged
    # snapshot, so its value already carries the removal's change: for an
    # overlapping id the append's cell is the true final state.
    merged_replace: dict[str, Cell] = {
        cell.id: cell for cell in removal.replace
    }
    for cell in scope_patch.replace:
        merged_replace[cell.id] = cell
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(*cells, *scope_patch.create),
        resource_replace=tuple(merged_replace.values()),
        authenticated=authenticated,
        result_root=group_root,
        policy_proof=policy_proof,
    )


def add_composition_member(
    authority: UnifiedAuthority,
    scope_root: str,
    composition_root_id: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Hold an existing composition as a member of a scope.

    The inverse of remove_composition_member, and the second half of
    ungroup: the composition already exists with its own history; the
    scope's relation chain gains one incidence, signed and receipted.
    """
    request_digest = _digest({
        "intent": "add-composition-member",
        "scope": scope_root,
        "composition": composition_root_id,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="add-composition-member",
        request_digest=request_digest,
        object_root=composition_root_id,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            composition_root_id, existing.result_revision, True, 0, 0,
            existing.root_id,
        )
    already = any(
        member.role_id == authority.role("composition")
        and member.participant_id == composition_root_id
        for member in read_relation(snapshot, scope_root, budget=COMMAND_BUDGET)
    )
    if already:
        raise InvalidCell("the composition is already a member of this scope")
    patch = _append_relation_member(
        snapshot,
        scope_root,
        authority.role("composition"),
        composition_root_id,
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(patch.create),
        resource_replace=tuple(patch.replace),
        authenticated=authenticated,
        result_root=composition_root_id,
        policy_proof=policy_proof,
    )


def ungroup_composition(
    authority: UnifiedAuthority,
    scope_root: str,
    group_root: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Dissolve one grouped composition back into its scope.

    A sequence of the same small signed commands that built it: each
    member leaves the group and joins the scope, then the scope stops
    holding the group. Every step is receipted and idempotent under a
    command id derived from this one, so a retry resumes where it
    stopped; nothing is deleted.
    """
    snapshot = authority.store.snapshot()
    group = validate_composition(authority, snapshot, group_root)
    if group.protocol_root != authority.shape("composition"):
        raise InvalidCell("only a composition can be ungrouped")
    member_roots = tuple(
        member.participant_id
        for member in group.members
        if member.role_id == authority.role("composition")
    )
    in_scope = any(
        member.role_id == authority.role("composition")
        and member.participant_id == group_root
        for member in read_relation(snapshot, scope_root, budget=COMMAND_BUDGET)
    )
    if not in_scope:
        raise InvalidCell("the group is not a member of this scope")
    if not member_roots:
        raise InvalidCell("the group holds no members to release")

    def step_id(step: str) -> str:
        return str(uuid.uuid5(_UNGROUP_NAMESPACE, command_id + ":" + step))

    for root in member_roots:
        # Adopt before release: policy proves an act on a root that is
        # REACHABLE within the claimed scope, and a root released first
        # belongs nowhere for a moment -- the adopt was denied exactly
        # there. Held by both for one revision, then the group lets go.
        try:
            add_composition_member(
                authority, scope_root, root,
                caller=caller, command_id=step_id("adopt:" + root),
            )
        except InvalidCell as error:
            if "already a member" not in str(error):
                raise
        try:
            remove_composition_member(
                authority, group_root, root,
                caller=caller, command_id=step_id("release:" + root),
            )
        except InvalidCell as error:
            if "not a member" not in str(error):
                raise
    return remove_composition_member(
        authority, scope_root, group_root,
        caller=caller, command_id=step_id("dissolve"),
    )


_UNGROUP_NAMESPACE = uuid.UUID("7f1cf7e7-40cb-49a5-a8b6-6f2ab77a9f2a")


def remove_composition_member(
    authority: UnifiedAuthority,
    scope_root: str,
    composition_root_id: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Take one composition off the canvas of its scope.

    The graph could place a card and never take one back: no command
    detached a scope member, so every test placement stayed on the
    founder's map for good. History is kept -- the member's incidence is
    unlinked from the scope's relation chain (the kernel's own
    prepare_remove_relation_members), the composition and its revisions
    remain reachable from their own receipts, and a later audit still
    replays the revision that added it. Same signed, receipted, policy-
    proven path as placing.
    """
    request_digest = _digest({
        "intent": "remove-composition-member",
        "scope": scope_root,
        "composition": composition_root_id,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="remove-composition-member",
        request_digest=request_digest,
        object_root=composition_root_id,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            composition_root_id, existing.result_revision, True, 0, 0,
            existing.root_id,
        )
    incidences = tuple(
        member.incidence_id
        for member in read_relation(snapshot, scope_root, budget=COMMAND_BUDGET)
        if member.role_id == authority.role("composition")
        and member.participant_id == composition_root_id
    )
    if not incidences:
        raise InvalidCell("composition is not a member of this scope")
    patch = prepare_remove_relation_members(
        snapshot, scope_root, incidences, budget=COMMAND_BUDGET
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(),
        resource_replace=tuple(patch.replace),
        authenticated=authenticated,
        result_root=composition_root_id,
        policy_proof=policy_proof,
    )


def place_composition(
    authority: UnifiedAuthority,
    scope_root: str,
    composition_root_id: str,
    position: Mapping[str, object],
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Record where a composition sits on the canvas of its scope.

    A canvas cannot draw what has no place, and every composition node
    carried none: the client computed NaN bounds and the whole layout
    collapsed while every court stayed green. The position is a graph
    fact from here on -- carried as the same property contract a view
    session uses for its viewport, revised by the same signed path, and
    read back rather than recomputed, so moving a node is an ordinary
    revision and an unplaced node stays honestly unplaced.
    """
    plain = _plain_json_mapping(position, "composition position")
    request_digest = _digest({
        "intent": "place-composition",
        "scope": scope_root,
        "composition": composition_root_id,
        "position": plain,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="place-composition",
        request_digest=request_digest,
        object_root=composition_root_id,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            composition_root_id, existing.result_revision, True, 0, 0,
            existing.root_id,
        )
    position_root, position_cells = _build_contract(authority, plain)
    create: list[Cell] = list(position_cells)
    replace: list[Cell] = []
    interface_root = composition_root(authority, "Interface", caller=caller)
    found = _composition_placement(
        authority, snapshot, interface_root, composition_root_id
    )
    if found is None:
        placement_root = _new_id()
        create.extend(_typed_relation_cells(
            placement_root,
            authority.role("conforms-to"),
            authority.shape("relation"),
            (
                (authority.role("composition"), composition_root_id),
                (authority.role("presentation"), position_root),
            ),
        ))
        registration = _append_relation_member(
            snapshot,
            interface_root,
            authority.role("object"),
            placement_root,
        )
        create.extend(registration.create)
        replace.extend(registration.replace)
    else:
        placement_root, carried = found
        stale = tuple(
            each.incidence_id for each in carried
            if each.role_id == authority.role("presentation")
        )
        staged = snapshot
        if stale:
            removal = prepare_remove_relation_members(
                staged, placement_root, stale, budget=COMMAND_BUDGET
            )
            replace.extend(removal.replace)
            staged = overlay_read_snapshot(staged, replace=removal.replace)
        append = prepare_append_relation_members(
            staged,
            placement_root,
            ((authority.role("presentation"), position_root),),
            budget=COMMAND_BUDGET,
        )
        create.extend(append.create)
        replace.extend(append.replace)
        # Removing the old position and appending the new one can touch the
        # same incidence twice. A cell cannot be created and replaced in one
        # patch, so the later version of each wins and only cells that
        # already exist stay in the replace half.
        merged: dict[str, Cell] = {cell.id: cell for cell in create}
        rest: dict[str, Cell] = {}
        for cell in replace:
            if cell.id in merged:
                merged[cell.id] = cell
            else:
                rest[cell.id] = cell
        create = list(merged.values())
        replace = list(rest.values())
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(create),
        resource_replace=tuple(replace),
        authenticated=authenticated,
        result_root=composition_root_id,
        policy_proof=policy_proof,
    )


def _view_session_state(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    interface_root: str,
    view_root: str,
) -> tuple[str, tuple[RelationMember, ...]] | None:
    """Find the one graph-held state relation for a view, walking forward.

    The browser-session composition is strict -- its reader refuses an
    undeclared field -- and the view root is the agent session, which is not
    ours to extend. The Interface composition is the released open-role
    carrier for interface state, so each view's state relation registers
    there under the released session role -- the view IS an agent session --
    and is found by walking members rather than by searching the graph.
    """
    for member in read_relation(snapshot, interface_root, budget=COMMAND_BUDGET):
        if member.role_id != authority.role("session"):
            continue
        try:
            carried = read_relation(
                snapshot, member.participant_id, budget=COMMAND_BUDGET
            )
        except (InvalidCell, MatchBudgetExceeded):
            continue
        views = [
            each.participant_id
            for each in carried
            if each.role_id == authority.role("session")
        ]
        if views == [view_root]:
            return member.participant_id, carried
    return None


def read_view_session_state(
    authority: UnifiedAuthority,
    view_root: str,
    *,
    caller: CallerCommandCapability,
    at_revision: int | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Read a view's viewport and design tokens, defaulting when unrecorded.

    Absence of the state is a graph fact, not an error: a view that never
    moved sits at the origin with no token overrides. The defaults are named
    once here rather than invented per reader.
    """
    if at_revision is None:
        snapshot = authority.store.snapshot()
    else:
        snapshot = authority.store.at(at_revision)
    interface_root = composition_root(authority, "Interface", caller=caller)
    found = _view_session_state(
        authority, snapshot, interface_root, view_root
    )
    viewport: dict[str, object] = dict(VIEW_DEFAULT_VIEWPORT)
    tokens: dict[str, object] = {}
    if found is not None:
        _state_root, carried = found
        for each in carried:
            if each.role_id == authority.role("presentation"):
                viewport = dict(_property_values(
                    authority, snapshot, each.participant_id
                ))
            elif each.role_id == authority.role("defaults"):
                tokens = dict(_property_values(
                    authority, snapshot, each.participant_id
                ))
    return viewport, tokens


def revise_view_session_viewport(
    authority: UnifiedAuthority,
    view_root: str,
    *,
    viewport: Mapping[str, object],
    design_tokens: Mapping[str, object],
    session_root: str,
    caller: CallerCommandCapability,
    command_id: str,
    expected_revision: int | None = None,
) -> CommandResult:
    """Mutate one view's viewport and design tokens for an issued session.

    The view is the agent session's working view, shared by every browser
    session that agent holds -- a second tab seeing the pan is correct, not a
    leak. The boundary is the browser session: the caller names which issued
    session is acting, and an unknown, foreign or revoked session is refused
    before anything is staged, so the denial is fail-closed by construction
    rather than by cleanup.
    """
    plain_viewport = _plain_json_mapping(viewport, "viewport")
    plain_tokens = _plain_json_mapping(design_tokens, "design tokens")
    if type(session_root) is not str or not session_root:
        raise InvalidCell("browser session root is invalid")
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision < 0
    ):
        raise InvalidCell("view session revision base is invalid")
    interface_root = composition_root(authority, "Interface", caller=caller)
    request: dict[str, object] = {
        "intent": "revise-view-session-viewport",
        "view": view_root,
        "session": session_root,
        "viewport": plain_viewport,
        "design-tokens": plain_tokens,
    }
    if expected_revision is not None:
        request["expected_revision"] = expected_revision
    request_digest = _digest(request)
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="revise-view-session-viewport",
        request_digest=request_digest,
        # The graph policy admits an object within its scope. The view root
        # belongs to no released composition, so the command is anchored on
        # the Interface composition it writes into; the view is bound by the
        # request digest and checked against the issued browser session.
        object_root=interface_root,
        scope_root=interface_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    if expected_revision is not None and snapshot.revision != expected_revision:
        raise InvalidCell("view session revision base is stale")
    # The named browser session must exist, be active, and hold THIS view.
    # The import is deferred because the browser authority module composes
    # over this one; the dependency at call time runs the other way.
    from .clean_browser_authority import open_clean_browser_authority
    from .cell_browser_sessions import read_browser_session
    browser = open_clean_browser_authority(authority, caller=caller)
    session = read_browser_session(snapshot, browser.protocol, session_root)
    if session.state_root != browser.protocol.states["active"]:
        raise InvalidCell("browser session is not active")
    if session.view_root != view_root:
        raise InvalidCell("browser session does not hold this view")
    # Compound data is compositions, not encoded blobs: the state carries
    # its viewport and tokens as the same property contracts definitions use.
    viewport_root, viewport_cells = _build_contract(authority, plain_viewport)
    tokens_root, tokens_cells = _build_contract(authority, plain_tokens)
    create: list[Cell] = [*viewport_cells, *tokens_cells]
    replace: list[Cell] = []
    found = _view_session_state(
        authority, snapshot, interface_root, view_root
    )
    if found is None:
        state_root = _new_id()
        create.extend(_typed_relation_cells(
            state_root,
            authority.role("conforms-to"),
            authority.shape("relation"),
            (
                (authority.role("session"), view_root),
                (authority.role("presentation"), viewport_root),
                (authority.role("defaults"), tokens_root),
            ),
        ))
        registration = _append_relation_member(
            snapshot,
            interface_root,
            authority.role("session"),
            state_root,
        )
        create.extend(registration.create)
        replace.extend(registration.replace)
    else:
        state_root, carried = found
        stale = tuple(
            each.incidence_id
            for each in carried
            if each.role_id in (
                authority.role("presentation"),
                authority.role("defaults"),
            )
        )
        staged = snapshot
        if stale:
            removal = prepare_remove_relation_members(
                staged, state_root, stale, budget=COMMAND_BUDGET
            )
            replace.extend(removal.replace)
            staged = overlay_read_snapshot(staged, replace=removal.replace)
        append = prepare_append_relation_members(
            staged,
            state_root,
            (
                (authority.role("presentation"), viewport_root),
                (authority.role("defaults"), tokens_root),
            ),
            budget=COMMAND_BUDGET,
        )
        create.extend(append.create)
        replace.extend(append.replace)
        merged: dict[str, Cell] = {cell.id: cell for cell in create}
        rest: dict[str, Cell] = {}
        for cell in replace:
            if cell.id in merged:
                merged[cell.id] = cell
            else:
                rest[cell.id] = cell
        create = list(merged.values())
        replace = list(rest.values())
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(create),
        resource_replace=tuple(replace),
        authenticated=authenticated,
        result_root=view_root,
        policy_proof=policy_proof,
    )


def install_scope_panels(
    authority: UnifiedAuthority,
    scope_root: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
    audience: str = PANEL_AUDIENCE,
    panels: tuple[str, ...] = DEFAULT_SCOPE_PANELS,
    definition_roots: tuple[str, ...] | None = None,
) -> CommandResult:
    """Give an existing scope the panel applicability newer imports seed.

    The importer runs once, when a generation is created, so a graph
    bootstrapped before the importer seeded panel applicability will never
    have it -- and nothing says so, because absence does not raise. The
    inspector simply projects no panels, forever, on exactly the graphs that
    matter. This is the loud path for that quiet gap: an ordinary signed
    command a caller runs against a live graph, producing the same reachable
    state the importer now seeds.

    The caller names the scope explicitly because a definition cannot be
    asked which scope holds it -- relations only walk forwards -- while a
    caller, holding the scope it has open, can.

    A revision's content digest seals its evidence, so the applicability
    cannot be appended to the revisions that exist: each definition gets a
    NEW revision, identical but for resting on the applicability, with the
    old one as its predecessor. History stays honest -- the graph records
    that the feature arrived, rather than pretending it was always there.
    """
    if not panels:
        raise InvalidCell("scope panels must be named")
    for entry in panels:
        label, presenter = (
            entry if isinstance(entry, tuple) else (entry, "")
        )
        if type(label) is not str or not label.strip():
            raise InvalidCell("scope panels must be named")
        if isinstance(entry, tuple) and (
            type(presenter) is not str or not presenter.strip()
        ):
            raise InvalidCell("a scope panel names no presenter")
    request_digest = _digest({
        "intent": "install-scope-panels",
        "scope": scope_root,
        "audience": audience,
        "panels": list(panels),
        "definitions": sorted(definition_roots or ()),
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="install-scope-panels",
        request_digest=request_digest,
        object_root=scope_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    _validate_composition_scope(authority, snapshot, scope_root)
    # A caller may name the definitions. The panels a scope shows are read
    # from the definitions of the nodes standing in it, and those are not
    # always the definitions the scope lists as members -- an operation
    # placed from the catalogue is one such node.
    if definition_roots is None:
        definition_roots = tuple(dict.fromkeys(
            member.participant_id
            for member in read_relation(
                snapshot, scope_root, budget=COMMAND_BUDGET
            )
            if member.role_id == authority.role("definition")
        ))
    else:
        definition_roots = tuple(dict.fromkeys(definition_roots))
    if not definition_roots:
        raise InvalidCell("scope holds no definitions to give panels to")
    projections = {
        definition_root: read_definition(
            authority, definition_root, caller=caller
        )
        for definition_root in definition_roots
    }
    pending = tuple(
        definition_root
        for definition_root, projection in projections.items()
        if not any(
            found is not None and scope_root in found[1]
            for found in (_scope_applicability(
                authority, snapshot, projection.revision_root
            ),)
        )
    )
    if not pending:
        # The applicability is installed, but its panels may predate the
        # rule that a tab names what it presents. Such a panel is no
        # longer offered at all, so repairing it here is the difference
        # between a scope with tabs and a scope with none. The caller
        # states the mapping; nothing is guessed from the label.
        declared = {
            label: presenter
            for label, presenter in (
                entry if isinstance(entry, tuple) else (entry, "")
                for entry in panels
            )
            if presenter
        }
        repair: list[Cell] = []
        repaired: list[Cell] = []
        for definition_root, projection in projections.items():
            found = _scope_applicability(
                authority, snapshot, projection.revision_root
            )
            if found is None:
                continue
            for member in read_relation(
                snapshot, found[0], budget=COMMAND_BUDGET
            ):
                if member.role_id != authority.role("object"):
                    continue
                panel_root = member.participant_id
                members = read_relation(
                    snapshot, panel_root, budget=COMMAND_BUDGET
                )
                held = [
                    each for each in members
                    if each.role_id == authority.role("presentation")
                ]
                labels = [
                    _decode_data_value(authority, snapshot, each.participant_id)
                    for each in members
                    if each.role_id == authority.role("label")
                ]
                presenter = declared.get(str(labels[0])) if labels else None
                if not presenter:
                    continue
                if held:
                    # A panel that already names a presenter is repaired
                    # only when the caller states a different one. The
                    # tab is then repointed rather than given a second
                    # declaration, because two answers is worse than none.
                    current_presenter = _decode_data_value(
                        authority, snapshot, held[0].participant_id
                    )
                    if str(current_presenter) == presenter:
                        continue
                    moved_root, moved_cells = _build_value(
                        authority.roles,
                        authority.codecs[CODEC_NAME],
                        presenter,
                        shape_root=authority.shape("value"),
                    )
                    repair.extend(moved_cells)
                    incidence = snapshot.cells[held[0].incidence_id]
                    repaired.append(Cell(
                        incidence.id,
                        incidence.link0,
                        moved_root,
                        incidence.atom,
                    ))
                    continue
                presenter_root, presenter_cells = _build_value(
                    authority.roles,
                    authority.codecs[CODEC_NAME],
                    presenter,
                    shape_root=authority.shape("value"),
                )
                repair.extend(presenter_cells)
                widened = _append_relation_member(
                    snapshot,
                    panel_root,
                    authority.role("presentation"),
                    presenter_root,
                )
                repair.extend(widened.create)
                repaired.extend(widened.replace)
            break
        if repair or repaired:
            return _commit_with_receipt(
                authority,
                snapshot,
                resource_create=tuple(repair),
                resource_replace=tuple(repaired),
                authenticated=authenticated,
                result_root=scope_root,
                policy_proof=policy_proof,
            )
        # The feature is fully installed. Repeating the command must not
        # stack a second applicability relation onto every revision.
        return CommandResult(
            scope_root,
            snapshot.revision,
            True,
            0,
            0,
            "",
        )
    # One applicability relation per graph feature, naming every scope it
    # applies in -- the shape the importer seeds. Definitions already resting
    # on one keep it: the missing scope is APPENDED to that relation, which
    # touches no revision. Only definitions carrying none get a new revision
    # resting on the relation, minting it if this run is the first.
    # The rehearsal against a copy of the live graph is what forced this:
    # a per-scope mint left every definition pointing at whichever relation
    # sorted first in its evidence, and 15 of 17 scope pairs uncovered.
    shared_root: str | None = None
    shared_scopes: tuple[str, ...] = ()
    for projection in projections.values():
        found = _scope_applicability(
            authority, snapshot, projection.revision_root
        )
        if found is not None:
            shared_root, shared_scopes, _members = found
            break
    create: list[Cell] = []
    replace: list[Cell] = []
    if shared_root is None:
        audience_root, audience_cells = _build_value(
            authority.roles,
            authority.codecs[CODEC_NAME],
            audience,
            shape_root=authority.shape("value"),
        )
        applicability_root = _new_id()
        create.extend(audience_cells)
        # The tabs themselves are graph compositions carrying their label,
        # and the applicability names them as its objects. Minting the
        # relation without them produced an applicability no reader could
        # turn into a panel: the repair ran, reported success, and the
        # inspector stayed empty.
        panel_members: list[tuple[str, str]] = [
            (authority.role("scope"), scope_root),
            (authority.role("audience"), audience_root),
        ]
        for entry in panels:
            # A panel may name what it presents. A tab that does not is a
            # tab whose content the projector would have to decide for it,
            # and deciding for the graph is how every panel ended up
            # showing the same thing.
            label, presenter = (
                entry if isinstance(entry, tuple) else (entry, entry.lower())
            )
            label_root, label_cells = _build_value(
                authority.roles,
                authority.codecs[CODEC_NAME],
                label,
                shape_root=authority.shape("value"),
            )
            presenter_root, presenter_cells = _build_value(
                authority.roles,
                authority.codecs[CODEC_NAME],
                presenter,
                shape_root=authority.shape("value"),
            )
            panel_root = _new_id()
            create.extend(label_cells)
            create.extend(presenter_cells)
            create.extend(_typed_relation_cells(
                panel_root,
                authority.role("conforms-to"),
                authority.shape("composition"),
                (
                    (authority.role("label"), label_root),
                    (authority.role("presentation"), presenter_root),
                    (authority.role("definition"), definition_roots[0]),
                ),
            ))
            panel_members.append((authority.role("object"), panel_root))
        create.extend(_typed_relation_cells(
            applicability_root,
            authority.role("conforms-to"),
            authority.shape("relation"),
            tuple(panel_members),
        ))
    else:
        applicability_root = shared_root
        if scope_root not in shared_scopes:
            widened = _append_relation_member(
                snapshot,
                applicability_root,
                authority.role("scope"),
                scope_root,
            )
            create.extend(widened.create)
            replace.extend(widened.replace)
    for definition_root in pending:
        projection = projections[definition_root]
        if applicability_root in projection.evidence_roots:
            # Already resting on the shared relation; widening it above is
            # the whole change for this definition.
            continue
        spec = _definition_spec(
            projection.name,
            projection.version,
            projection.lifecycle,
            *(dict(projection.contracts[name]) for name in CONTRACT_NAMES),
            (*projection.evidence_roots, applicability_root),
        )
        new_revision, _, revision_cells = _build_definition_revision(
            authority,
            spec,
            previous_revision_root=projection.revision_root,
        )
        create.extend(revision_cells)
        current_members = tuple(
            member
            for member in read_relation(
                snapshot, definition_root, budget=COMMAND_BUDGET
            )
            if member.role_id == authority.role("current-revision")
        )
        if len(current_members) != 1:
            raise InvalidCell("definition current revision binding is invalid")
        incidence = snapshot.cells[current_members[0].incidence_id]
        replace.append(Cell(
            incidence.id,
            incidence.link0,
            new_revision,
            incidence.atom,
        ))
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(create),
        resource_replace=tuple(replace),
        authenticated=authenticated,
        result_root=scope_root,
        policy_proof=policy_proof,
    )


def revise_definition(
    authority: UnifiedAuthority,
    definition_root: str,
    name: str,
    defaults: Mapping[str, object] | None = None,
    *,
    caller: CallerCommandCapability,
    command_id: str,
    version: str,
    lifecycle: str = "wip",
    parameters: Mapping[str, object] | None = None,
    interfaces: Mapping[str, object] | None = None,
    rules: Mapping[str, object] | None = None,
    presentation: Mapping[str, object] | None = None,
    courts: Mapping[str, object] | None = None,
    provenance: Mapping[str, object] | None = None,
) -> CommandResult:
    """Create a WIP revision without changing definition identity."""
    if lifecycle != "wip":
        raise InvalidCell("ordinary definition revision must start in WIP")
    spec = _definition_spec(
        name,
        version,
        lifecycle,
        defaults,
        parameters,
        interfaces,
        rules,
        presentation,
        courts,
        provenance,
    )
    request_digest = _digest({
        "intent": "revise-definition",
        "definition": definition_root,
        "spec": spec,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="revise-definition",
        request_digest=request_digest,
        object_root=definition_root,
        scope_root=authority.manifest.catalogue_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    if definition_root not in snapshot.cells:
        raise InvalidCell("definition is missing")
    current_revision = _definition_revision_root(
        authority, snapshot, definition_root
    )
    # Evidence is what a revision rests on, not something the reviser
    # restates. A caller revising a contract does not re-supply the source a
    # definition was imported from, so building the new revision from the
    # caller's spec alone silently drops it and the definition loses its
    # provenance at the first revision. The request digest deliberately stays
    # the caller's intent, so replaying one command id still compares equal.
    carried_evidence = tuple(
        member.participant_id
        for member in read_relation(
            snapshot, current_revision, budget=COMMAND_BUDGET
        )
        if member.role_id == authority.role("evidence")
    )
    new_revision, _, revision_cells = _build_definition_revision(
        authority,
        _definition_spec(
            name,
            version,
            lifecycle,
            defaults,
            parameters,
            interfaces,
            rules,
            presentation,
            courts,
            provenance,
            carried_evidence,
        ),
        previous_revision_root=current_revision,
    )
    current_members = tuple(
        member
        for member in read_relation(snapshot, definition_root, budget=100_000)
        if member.role_id == authority.role("current-revision")
    )
    if len(current_members) != 1:
        raise InvalidCell("definition current revision binding is invalid")
    incidence = snapshot.cells[current_members[0].incidence_id]
    replacement = Cell(
        incidence.id,
        incidence.link0,
        new_revision,
        incidence.atom,
    )
    panel_create, panel_replace = _build_scope_panels(
        authority,
        snapshot,
        definition_root,
        current_revision,
        _declared_panel_labels(spec["presentation"]),
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(*revision_cells, *panel_create),
        resource_replace=(replacement, *panel_replace),
        authenticated=authenticated,
        result_root=definition_root,
        policy_proof=policy_proof,
    )


def promote_definition(
    authority: UnifiedAuthority,
    definition_root: str,
    *,
    target_lifecycle: str,
    version: str,
    evidence_roots: Iterable[str],
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Create an immutable lifecycle revision backed by exact graph receipts."""
    snapshot = authority.store.snapshot()
    evidence = tuple(sorted(set(str(root) for root in evidence_roots)))
    request_digest = _digest({
        "intent": "promote-definition",
        "definition": definition_root,
        "target_lifecycle": target_lifecycle,
        "version": version,
        "evidence": evidence,
    })
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="promote-definition",
        request_digest=request_digest,
        object_root=definition_root,
        scope_root=authority.manifest.catalogue_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )

    current = read_definition(authority, definition_root, caller=caller)
    transitions = {
        "wip": "shared",
        "shared": "published",
        "published": "archived",
    }
    if transitions.get(current.lifecycle) != target_lifecycle:
        raise InvalidCell("definition lifecycle transition is not admitted")
    if not evidence:
        raise InvalidCell("definition promotion requires exact graph evidence")
    for evidence_root in evidence:
        if evidence_root not in snapshot.cells:
            raise InvalidCell("definition promotion evidence is missing")
        receipt = _receipt_projection(authority, snapshot, evidence_root)
        if receipt.result_root != definition_root:
            raise InvalidCell("definition promotion evidence targets another root")

    spec = _definition_spec(
        current.name,
        version,
        target_lifecycle,
        current.contracts["defaults"],
        current.contracts["parameters"],
        current.contracts["interfaces"],
        current.contracts["rules"],
        current.contracts["presentation"],
        current.contracts["courts"],
        current.contracts["provenance"],
        evidence,
    )

    new_revision, _, revision_cells = _build_definition_revision(
        authority, spec, previous_revision_root=current.revision_root
    )
    current_members = tuple(
        member
        for member in read_relation(snapshot, definition_root, budget=COMMAND_BUDGET)
        if member.role_id == authority.role("current-revision")
    )
    if len(current_members) != 1:
        raise InvalidCell("definition current revision binding is invalid")
    incidence = snapshot.cells[current_members[0].incidence_id]
    replacement = Cell(
        incidence.id,
        incidence.link0,
        new_revision,
        incidence.atom,
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=revision_cells,
        resource_replace=(replacement,),
        authenticated=authenticated,
        result_root=definition_root,
        policy_proof=policy_proof,
    )


def _validated_parameter_metadata(
    parameter_name: str,
    metadata: object,
    value: object,
) -> tuple[object, object]:
    if not isinstance(metadata, Mapping):
        raise InvalidCell("declared parameter metadata is not structured")
    expected = metadata.get("type", "any")
    admitted_types = {
        "any": object,
        "text": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "map": Mapping,
        "list": (list, tuple),
    }
    if type(expected) is not str or expected not in admitted_types:
        raise InvalidCell("declared parameter type is not admitted")
    expected_type = admitted_types[expected]
    if expected != "any":
        if expected == "number":
            valid_type = type(value) in {int, float}
        elif expected == "integer":
            valid_type = type(value) is int
        elif expected == "boolean":
            valid_type = type(value) is bool
        else:
            valid_type = isinstance(value, expected_type)
        if not valid_type:
            raise InvalidCell(
                "parameter %s violates its declared type" % parameter_name
            )
    options = metadata.get("options")
    if options is not None:
        if not isinstance(options, (list, tuple)) or value not in options:
            raise InvalidCell(
                "parameter %s violates its declared options" % parameter_name
            )
    minimum = metadata.get("minimum")
    maximum = metadata.get("maximum")
    if minimum is not None and (
        type(value) not in {int, float}
        or type(minimum) not in {int, float}
        or value < minimum
    ):
        raise InvalidCell(
            "parameter %s violates its declared minimum" % parameter_name
        )
    if maximum is not None and (
        type(value) not in {int, float}
        or type(maximum) not in {int, float}
        or value > maximum
    ):
        raise InvalidCell(
            "parameter %s violates its declared maximum" % parameter_name
        )
    minimum_length = metadata.get("minimum_length")
    maximum_length = metadata.get("maximum_length")
    if minimum_length is not None and (
        type(minimum_length) is not int
        or minimum_length < 0
        or not isinstance(value, (str, list, tuple, Mapping))
        or len(value) < minimum_length
    ):
        raise InvalidCell(
            "parameter %s violates its declared minimum length" % parameter_name
        )
    if maximum_length is not None and (
        type(maximum_length) is not int
        or maximum_length < 0
        or not isinstance(value, (str, list, tuple, Mapping))
        or len(value) > maximum_length
    ):
        raise InvalidCell(
            "parameter %s violates its declared maximum length" % parameter_name
        )
    editor = metadata.get("editor", {})
    constraints = {
        str(key): metadata[key]
        for key in sorted(metadata, key=str)
        if key != "editor"
    }
    return constraints, editor


def instantiate_definition(
    authority: UnifiedAuthority,
    definition_root: str,
    overrides: Mapping[str, object],
    *,
    scope_root: str,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    """Create one sparse instance; released definition content remains shared."""
    normalized = _normalized_mapping(overrides)
    request_digest = _digest({
        "intent": "instantiate-definition",
        "definition": definition_root,
        "overrides": normalized,
        "scope": scope_root,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="instantiate-definition",
        request_digest=request_digest,
        object_root=definition_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    if definition_root not in snapshot.cells or scope_root not in snapshot.cells:
        raise InvalidCell("definition or scope is missing")
    _validate_composition_scope(authority, snapshot, scope_root)
    catalogue_members = read_relation(
        snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
    )
    if not any(
        member.role_id == authority.role("definition")
        and member.participant_id == definition_root
        for member in catalogue_members
    ):
        raise InvalidCell("definition is not admitted by the graph catalogue")
    definition_projection = read_definition(
        authority, definition_root, caller=caller
    )
    if definition_projection.lifecycle != "published":
        raise InvalidCell("only a published definition revision may be instantiated")
    mutable_names = set(definition_projection.contracts["parameters"])
    undeclared = set(normalized) - mutable_names
    if undeclared:
        raise InvalidCell("instance override targets an undeclared mutable parameter")
    definition_revision = _definition_revision_root(
        authority, snapshot, definition_root
    )
    instance_root = _new_id()
    cells: list[Cell] = []
    members: list[tuple[str, str]] = [
        (authority.role("definition"), definition_root),
        (authority.role("definition-revision"), definition_revision),
    ]
    for key, value in normalized.items():
        constraints, editor = _validated_parameter_metadata(
            key,
            definition_projection.contracts["parameters"][key],
            value,
        )
        property_root, property_cells = _build_property(
            authority,
            key,
            value,
            owner_root=instance_root,
            constraints_value=constraints,
            editor_value=editor,
        )
        cells.extend(property_cells)
        members.append((authority.role("override"), property_root))
    cells.extend(_typed_relation_cells(
        instance_root,
        authority.role("conforms-to"),
        authority.shape("instance"),
        members,
    ))
    scope_patch = _append_relation_member(
        snapshot,
        scope_root,
        authority.role("composition"),
        instance_root,
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(*cells, *scope_patch.create),
        resource_replace=scope_patch.replace,
        authenticated=authenticated,
        result_root=instance_root,
        policy_proof=policy_proof,
    )


def _named_instance_connections(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    instance_root: str,
) -> Mapping[str, str]:
    connections: dict[str, str] = {}
    for member in read_relation(snapshot, instance_root, budget=COMMAND_BUDGET):
        if member.role_id != authority.role("relation"):
            continue
        relation = _project_relation_node(
            authority, snapshot, member.participant_id
        )
        connection = relation.properties.get("connection")
        if connection is None:
            continue
        if type(connection) is not str or not connection.strip():
            raise InvalidCell("instance connection name is invalid")
        name = connection.strip()
        participants = dict(relation.participants)
        if (
            participants.get("source") != instance_root
            or type(participants.get("target")) is not str
            or len(relation.participants) != 2
        ):
            raise InvalidCell("named instance connection has invalid participants")
        if name in connections:
            raise InvalidCell("instance connection name is duplicated")
        connections[name] = participants["target"]
    return MappingProxyType(dict(sorted(connections.items())))


def _transition_rule(
    rules: Mapping[str, object],
    current_state: object,
    target_state: object,
) -> Mapping[str, object] | None:
    state_parameter = rules.get("state_parameter")
    transitions = rules.get("transitions")
    if state_parameter is None and transitions is None:
        return None
    if type(state_parameter) is not str or not state_parameter:
        raise InvalidCell("definition transition state parameter is invalid")
    if not isinstance(transitions, Mapping):
        raise InvalidCell("definition transitions are not structured")
    selected = transitions.get(str(target_state))
    if not isinstance(selected, Mapping):
        raise InvalidCell("instance state transition is not declared")
    admitted_from = selected.get("from")
    if (
        not isinstance(admitted_from, (list, tuple))
        or not admitted_from
        or any(type(value) is not str for value in admitted_from)
        or current_state not in admitted_from
    ):
        raise InvalidCell("instance state transition source is not admitted")
    return selected


def _validate_transition_connections(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    instance_root: str,
    rule: Mapping[str, object],
    *,
    caller_session_root: str,
) -> None:
    connections = _named_instance_connections(
        authority, snapshot, instance_root
    )
    required = rule.get("required_connections", ())
    if (
        not isinstance(required, (list, tuple))
        or any(type(value) is not str or not value for value in required)
    ):
        raise InvalidCell("transition required connections are invalid")
    missing = set(required) - set(connections)
    if missing:
        raise InvalidCell("instance transition is missing a required connection")
    caller_connection = rule.get("caller_matches_connection")
    if caller_connection is not None:
        if (
            type(caller_connection) is not str
            or not caller_connection
            or caller_connection not in connections
        ):
            raise InvalidCell("transition caller connection is invalid")
        if connections[caller_connection] != caller_session_root:
            raise InvalidCell(
                "instance transition requires the connected caller session"
            )
    distinct = rule.get("distinct_targets", ())
    if not isinstance(distinct, (list, tuple)):
        raise InvalidCell("transition distinct targets are invalid")
    for pair in distinct:
        if (
            not isinstance(pair, (list, tuple))
            or len(pair) != 2
            or any(type(value) is not str or not value for value in pair)
            or any(value not in connections for value in pair)
        ):
            raise InvalidCell("transition distinct target pair is invalid")
        if connections[pair[0]] == connections[pair[1]]:
            raise InvalidCell("instance transition requires independent participants")
    target_values = rule.get("target_values", {})
    if not isinstance(target_values, Mapping):
        raise InvalidCell("transition target values are invalid")
    for connection_name, expected_values in target_values.items():
        if (
            type(connection_name) is not str
            or connection_name not in connections
            or not isinstance(expected_values, Mapping)
        ):
            raise InvalidCell("transition target value requirement is invalid")
        target = _project_instance(
            authority, snapshot, connections[connection_name]
        )
        values = target["values"]
        if not isinstance(values, Mapping) or any(
            values.get(key) != expected
            for key, expected in expected_values.items()
        ):
            raise InvalidCell("instance transition target evidence is not satisfied")


def revise_instance(
    authority: UnifiedAuthority,
    instance_root: str,
    changes: Mapping[str, object],
    *,
    scope_root: str,
    caller: CallerCommandCapability,
    command_id: str,
    expected_revision: int | None = None,
) -> CommandResult:
    """Revise sparse overrides while preserving one stable instance identity."""
    normalized = _normalized_mapping(changes)
    if not normalized:
        raise InvalidCell("instance revision has no changes")
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision < 0
    ):
        raise InvalidCell("instance revision base is invalid")
    request = {
        "intent": "revise-instance",
        "instance": instance_root,
        "changes": normalized,
        "scope": scope_root,
    }
    if expected_revision is not None:
        request["expected_revision"] = expected_revision
    request_digest = _digest(request)
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="revise-instance",
        request_digest=request_digest,
        object_root=instance_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    if expected_revision is not None and snapshot.revision != expected_revision:
        raise InvalidCell("instance revision base is stale")
    _validate_composition_scope(authority, snapshot, scope_root)
    instance = validate_composition(authority, snapshot, instance_root)
    if instance.protocol_root != authority.shape("instance"):
        raise InvalidCell("instance revision target has the wrong protocol")
    definition_root = _single_member(
        snapshot, instance_root, authority.role("definition")
    )
    definition_revision = _single_member(
        snapshot, instance_root, authority.role("definition-revision")
    )
    definition = read_definition(authority, definition_root, caller=caller)
    if definition.revision_root != definition_revision:
        raise InvalidCell("instance definition revision is no longer current")
    mutable = definition.contracts["parameters"]
    if set(normalized) - set(mutable):
        raise InvalidCell("instance revision targets an undeclared parameter")
    current = _project_instance(authority, snapshot, instance_root)
    current_values = current["values"]
    if not isinstance(current_values, Mapping):
        raise InvalidCell("instance current values are invalid")
    rules = definition.contracts["rules"]
    if not isinstance(rules, Mapping):
        raise InvalidCell("instance definition rules are invalid")
    state_parameter = rules.get("state_parameter")
    if state_parameter in normalized:
        rule = _transition_rule(
            rules,
            current_values.get(state_parameter),
            normalized[state_parameter],
        )
        if rule is not None:
            _validate_transition_connections(
                authority,
                snapshot,
                instance_root,
                rule,
                caller_session_root=authenticated.session_root,
            )

    retained_members: list[tuple[str, str]] = []
    superseded: dict[str, str] = {}
    cells: list[Cell] = []
    for member in instance.members:
        if member.role_id == authority.role("conforms-to"):
            continue
        if member.role_id != authority.role("override"):
            retained_members.append((member.role_id, member.participant_id))
            continue
        property_root = member.participant_id
        name_root = _single_member(
            snapshot, property_root, authority.role("name")
        )
        name = _decode_scalar_leaf(snapshot, name_root)
        if type(name) is not str:
            raise InvalidCell("instance override name is invalid")
        if name not in normalized:
            retained_members.append((member.role_id, property_root))
        else:
            # The property this revision replaces, so the new one can name it.
            superseded[name] = property_root
    for key, value in normalized.items():
        constraints, editor = _validated_parameter_metadata(
            key, mutable[key], value
        )
        property_root, property_cells = _build_property(
            authority,
            key,
            value,
            owner_root=instance_root,
            constraints_value=constraints,
            editor_value=editor,
            predecessor_root=superseded.get(key),
        )
        cells.extend(property_cells)
        retained_members.append((authority.role("override"), property_root))
    rebuilt = _typed_relation_cells(
        instance_root,
        authority.role("conforms-to"),
        authority.shape("instance"),
        retained_members,
    )
    replacement = next(cell for cell in rebuilt if cell.id == instance_root)
    cells.extend(cell for cell in rebuilt if cell.id != instance_root)
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=tuple(cells),
        resource_replace=(replacement,),
        authenticated=authenticated,
        result_root=instance_root,
        policy_proof=policy_proof,
    )


def create_relation_node(
    authority: UnifiedAuthority,
    participants: Iterable[tuple[str, str]],
    *,
    scope_root: str,
    caller: CallerCommandCapability,
    command_id: str,
    properties: Mapping[str, object] | None = None,
) -> CommandResult:
    """Create an explicit editable relation node between two or more roots."""
    normalized_participants = tuple(
        (str(role_name), str(participant_root))
        for role_name, participant_root in participants
    )
    normalized_properties = _normalized_mapping(properties)
    if len(normalized_participants) < 2:
        raise InvalidCell("an explicit relation requires at least two participants")
    request_digest = _digest({
        "intent": "create-relation",
        "participants": normalized_participants,
        "properties": normalized_properties,
        "scope": scope_root,
    })
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="create-relation",
        request_digest=request_digest,
        object_root=scope_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    if scope_root not in snapshot.cells:
        raise InvalidCell("relation scope is missing")
    _validate_composition_scope(authority, snapshot, scope_root)

    members: list[tuple[str, str]] = []
    for role_name, participant_root in normalized_participants:
        if role_name not in authority.roles:
            raise InvalidCell("relation participant role is not declared")
        if participant_root not in snapshot.cells:
            raise InvalidCell("relation participant is missing")
        members.append((authority.role(role_name), participant_root))
    relation_root = _new_id()
    cells: list[Cell] = []
    for key, value in normalized_properties.items():
        property_root, property_cells = _build_property(
            authority, key, value, owner_root=relation_root
        )
        cells.extend(property_cells)
        members.append((authority.role("property"), property_root))
    cells.extend(_typed_relation_cells(
        relation_root,
        authority.role("conforms-to"),
        authority.shape("relation"),
        members,
    ))
    scope_patch = _append_relation_member(
        snapshot,
        scope_root,
        authority.role("relation"),
        relation_root,
    )
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=(*cells, *scope_patch.create),
        resource_replace=scope_patch.replace,
        authenticated=authenticated,
        result_root=relation_root,
        policy_proof=policy_proof,
    )


def _project_relation_node(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    relation_root: str,
) -> ExplicitRelationProjection:
    relation = validate_composition(authority, snapshot, relation_root)
    if relation.protocol_root != authority.shape("relation"):
        raise InvalidCell("explicit relation has the wrong structural protocol")
    participants: list[tuple[str, str]] = []
    properties = _property_values(authority, snapshot, relation_root)
    roles_by_id = {root: name for name, root in authority.roles.items()}
    for member in read_relation(snapshot, relation_root, budget=100_000):
        if member.role_id in {
            authority.role("property"),
            authority.role("conforms-to"),
            authority.role("open-role"),
        }:
            continue
        role_name = roles_by_id.get(member.role_id)
        if role_name is None:
            raise InvalidCell("relation participant role is outside the protocol")
        participants.append((role_name, member.participant_id))
    if len(participants) < 2:
        raise InvalidCell("explicit relation has fewer than two participants")
    return ExplicitRelationProjection(
        relation_root,
        tuple(participants),
        MappingProxyType(dict(sorted(properties.items()))),
    )


def read_relation_node(
    authority: UnifiedAuthority,
    relation_root: str,
    *,
    scope_root: str,
    caller: CallerCommandCapability,
) -> ExplicitRelationProjection:
    snapshot = authority.store.snapshot()
    _authorize_semantic_read(
        authority,
        snapshot,
        caller,
        object_root=relation_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    return _project_relation_node(authority, snapshot, relation_root)


def _normalized_relation_revision_members(
    members: Iterable[Mapping[str, object]],
) -> tuple[RelationRevisionMember, ...]:
    normalized: list[RelationRevisionMember] = []
    for item in members:
        if not isinstance(item, Mapping):
            raise InvalidCell("relation revision member is invalid")
        incidence_id = item.get("incidence_id")
        role_root = item.get("role_root")
        participant_root = item.get("participant_root")
        if incidence_id is not None and (
            type(incidence_id) is not str or not _is_opaque_id(incidence_id)
        ):
            raise InvalidCell("relation revision member is invalid")
        if not all(
            type(value) is str and _is_opaque_id(value)
            for value in (role_root, participant_root)
        ):
            raise InvalidCell("relation revision member is invalid")
        normalized.append(
            RelationRevisionMember(
                incidence_id=incidence_id,
                role_root=role_root,
                participant_root=participant_root,
            )
        )
    if not normalized:
        raise InvalidCell("relation revision has no members")
    return tuple(normalized)


def revise_relation_node(
    authority: UnifiedAuthority,
    relation_root: str,
    members: Iterable[Mapping[str, object]],
    *,
    scope_root: str,
    caller: CallerCommandCapability,
    command_id: str,
    expected_revision: int | None = None,
) -> CommandResult:
    """Revise one existing relation to an exact desired member set.

    A member carrying an incidence_id keeps that incidence, so an edge
    that survives a revision keeps its identity instead of being deleted
    and recreated under a new one; a member without an incidence_id is
    new and gets a fresh incidence; an existing member the caller omits
    is removed. The relation root does not change, so anything pointing
    at this relation keeps pointing at it. Order is taken from the caller
    rather than sorted here: the sequence a reader sees is the sequence
    the command asked for.
    """
    normalized = _normalized_relation_revision_members(members)
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision < 0
    ):
        raise InvalidCell("relation revision base is invalid")
    request: dict[str, object] = {
        "intent": "revise-relation",
        "relation": relation_root,
        "members": tuple(
            {
                "incidence_id": member.incidence_id,
                "role_root": member.role_root,
                "participant_root": member.participant_root,
            }
            for member in normalized
        ),
        "scope": scope_root,
    }
    if expected_revision is not None:
        request["expected_revision"] = expected_revision
    request_digest = _digest(request)
    snapshot = authority.store.snapshot()
    authenticated, policy_proof = _validate_command_participants(
        authority,
        snapshot,
        caller,
        command_id,
        intent="revise-relation",
        request_digest=request_digest,
        object_root=relation_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    existing = _find_receipt(
        authority,
        snapshot,
        authenticated.actor_root,
        authenticated.session_root,
        command_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise InvalidCell("idempotency key was reused with another request")
        return CommandResult(
            existing.result_root,
            existing.result_revision,
            True,
            0,
            0,
            existing.root_id,
        )
    if expected_revision is not None and snapshot.revision != expected_revision:
        raise InvalidCell("relation revision base is stale")
    if relation_root not in snapshot.cells:
        raise InvalidCell("relation revision target is missing")
    _validate_composition_scope(authority, snapshot, scope_root)
    current_members = read_relation(snapshot, relation_root, budget=COMMAND_BUDGET)
    current_ids = tuple(member.incidence_id for member in current_members)
    required_roots = {relation_root}
    required_roots.update(member.role_root for member in normalized)
    required_roots.update(member.participant_root for member in normalized)
    if any(_root not in snapshot.cells for _root in required_roots):
        raise InvalidCell("relation revision member root is missing")
    current_by_incidence = {
        member.incidence_id: member for member in current_members
    }
    current_role_counts: dict[str, int] = {}
    for member in current_members:
        current_role_counts[member.role_id] = current_role_counts.get(member.role_id, 0) + 1
    try:
        typed_relation = validate_composition(authority, snapshot, relation_root)
    except InvalidCell:
        typed_relation = None
    allowed_roles: set[str] = set(current_role_counts)
    required_roles: set[str] = set()
    optional_roles: set[str] = set()
    repeated_roles: set[str] = set()
    open_roles = False
    if (
        typed_relation is not None
        and typed_relation.protocol_root == authority.shape("relation")
    ):
        shape_members = read_relation(
            snapshot, typed_relation.protocol_root, budget=COMMAND_BUDGET
        )
        required_roles = {
            member.participant_id
            for member in shape_members
            if member.role_id == authority.role("required-role")
        }
        optional_roles = {
            member.participant_id
            for member in shape_members
            if member.role_id == authority.role("optional-role")
        }
        repeated_roles = {
            member.participant_id
            for member in shape_members
            if member.role_id == authority.role("repeated-role")
        }
        open_roles = any(
            member.role_id == authority.role("open-role")
            for member in shape_members
        )
        allowed_roles = required_roles | optional_roles | repeated_roles
    retained_ids: list[str] = []
    final_members: list[RelationRevisionMember] = []
    for member in normalized:
        if member.incidence_id is not None:
            if member.incidence_id not in current_by_incidence:
                raise InvalidCell(
                    "relation revision member incidence is outside the relation"
                )
            if member.incidence_id in retained_ids:
                raise InvalidCell("relation revision incidence is duplicated")
            retained_ids.append(member.incidence_id)
        if not open_roles and member.role_root not in allowed_roles:
            raise InvalidCell("relation participant role is outside the protocol")
        final_members.append(member)
    removed_ids = tuple(
        incidence_id for incidence_id in current_ids if incidence_id not in retained_ids
    )
    role_counts: dict[str, int] = {}
    for member in final_members:
        role_counts[member.role_root] = role_counts.get(member.role_root, 0) + 1
    if typed_relation is not None and typed_relation.protocol_root == authority.shape("relation"):
        if any(role_counts.get(role, 0) != 1 for role in required_roles):
            raise InvalidCell("relation revision is missing a required role")
        if any(role_counts.get(role, 0) > 1 for role in optional_roles):
            raise InvalidCell("relation revision repeats an optional role")
        if (
            final_members[0].role_root != authority.role("conforms-to")
            or final_members[0].participant_root != authority.shape("relation")
            or final_members[0].incidence_id is None
            or final_members[0].incidence_id != current_members[0].incidence_id
        ):
            raise InvalidCell(
                "typed relation revision must preserve its structural protocol member"
            )
    elif role_counts != current_role_counts:
        raise InvalidCell(
            "plain relation revision must preserve its role cardinality"
        )
    staged = snapshot
    if removed_ids:
        removal_patch = prepare_remove_relation_members(
            staged,
            relation_root,
            removed_ids,
            budget=COMMAND_BUDGET,
        )
        staged = overlay_read_snapshot(staged, replace=removal_patch.replace)
    else:
        removal_patch = None
    additions = tuple(
        (member.role_root, member.participant_root)
        for member in final_members
        if member.incidence_id is None
    )
    if additions:
        append_patch = prepare_append_relation_members(
            staged,
            relation_root,
            additions,
            budget=COMMAND_BUDGET,
        )
        staged = overlay_read_snapshot(
            staged,
            create=append_patch.create,
            replace=append_patch.replace,
        )
    else:
        append_patch = None
    added_ids = iter(append_patch.incidence_ids if append_patch is not None else ())
    assigned_members: list[RelationRevisionMember] = []
    for member in final_members:
        assigned_members.append(
            RelationRevisionMember(
                incidence_id=member.incidence_id or next(added_ids),
                role_root=member.role_root,
                participant_root=member.participant_root,
            )
        )
    incidence_replacements: list[Cell] = []
    for member in assigned_members:
        if member.incidence_id in current_by_incidence:
            current = current_by_incidence[member.incidence_id]
            if (
                current.role_id != member.role_root
                or current.participant_id != member.participant_root
            ):
                incidence_replacements.append(
                    Cell(
                        member.incidence_id,
                        member.role_root,
                        member.participant_root,
                        b"",
                    )
                )
    if incidence_replacements:
        staged = overlay_read_snapshot(staged, replace=incidence_replacements)
    requested_ids = tuple(member.incidence_id for member in assigned_members)
    reorder_replacements = prepare_reorder_relation_members(
        staged,
        relation_root,
        requested_ids,
        budget=COMMAND_BUDGET,
    )
    if reorder_replacements:
        staged = overlay_read_snapshot(staged, replace=reorder_replacements)
    create_ids = {
        cell.id for cell in append_patch.create
    } if append_patch is not None else set()
    replace_ids: dict[str, None] = {}
    for cells in (
        () if removal_patch is None else removal_patch.replace,
        () if append_patch is None else append_patch.replace,
        tuple(incidence_replacements),
        tuple(reorder_replacements),
    ):
        for cell in cells:
            replace_ids[cell.id] = None
    resource_create = tuple(
        staged.cells[cell_id] for cell_id in sorted(create_ids)
    )
    resource_replace = tuple(
        staged.cells[cell_id]
        for cell_id in replace_ids
        if cell_id in snapshot.cells
        if staged.cells[cell_id] != snapshot.cells[cell_id]
    )
    if not resource_create and not resource_replace:
        raise InvalidCell("relation revision has no changes")
    return _commit_with_receipt(
        authority,
        snapshot,
        resource_create=resource_create,
        resource_replace=resource_replace,
        authenticated=authenticated,
        result_root=relation_root,
        policy_proof=policy_proof,
    )


def _project_instance(
    authority: UnifiedAuthority,
    snapshot: Snapshot,
    instance_root: str,
) -> Mapping[str, object]:
    instance = validate_composition(authority, snapshot, instance_root)
    if instance.protocol_root != authority.shape("instance"):
        raise InvalidCell("instance has the wrong structural protocol")
    definition_root = _single_member(
        snapshot, instance_root, authority.role("definition")
    )
    definition = validate_composition(authority, snapshot, definition_root)
    if definition.protocol_root != authority.shape("definition"):
        raise InvalidCell("instance definition has the wrong structural protocol")
    revision_root = _single_member(
        snapshot, instance_root, authority.role("definition-revision")
    )
    revision = validate_composition(authority, snapshot, revision_root)
    if revision.protocol_root != authority.shape("definition-revision"):
        raise InvalidCell("instance definition revision has the wrong protocol")
    default_root = _single_member(
        snapshot, revision_root, authority.role("defaults")
    )
    values = _property_values(authority, snapshot, default_root)
    values.update(_property_values(authority, snapshot, instance_root))
    return MappingProxyType({
        "root": instance_root,
        "definition": definition_root,
        "definition_revision": revision_root,
        "values": MappingProxyType(dict(sorted(values.items()))),
    })


def read_instance(
    authority: UnifiedAuthority,
    instance_root: str,
    *,
    scope_root: str,
    caller: CallerCommandCapability,
) -> Mapping[str, object]:
    snapshot = authority.store.snapshot()
    _authorize_semantic_read(
        authority,
        snapshot,
        caller,
        object_root=instance_root,
        scope_root=scope_root,
        budget=COMMAND_BUDGET,
    )
    return _project_instance(authority, snapshot, instance_root)


def read_contained_scope(
    authority: UnifiedAuthority,
    container_root: str,
    *,
    scope_root: str,
    caller: CallerCommandCapability,
    at_revision: int | None = None,
    max_depth: int = 32,
    budget: int = COMMAND_BUDGET,
) -> ContainedScopeProjection:
    """Read one authorized composition subtree from one accepted revision."""
    if max_depth < 0 or budget < 1:
        raise InvalidCell("contained scope bounds are invalid")
    current = authority.store.snapshot()
    _authorize_semantic_read(
        authority,
        current,
        caller,
        object_root=container_root,
        scope_root=scope_root,
        budget=budget,
    )
    snapshot = (
        current if at_revision is None else authority.store.at(at_revision)
    )
    if snapshot.revision != current.revision:
        _verify_exact_snapshot_head(authority, snapshot)
    instances: dict[str, Mapping[str, object]] = {}
    relations: dict[str, ExplicitRelationProjection] = {}
    visited: set[str] = set()
    remaining = budget
    pending: list[tuple[str, int, frozenset[str]]] = [
        (container_root, 0, frozenset())
    ]
    while pending:
        current, depth, ancestors = pending.pop()
        if current in ancestors:
            raise InvalidCell("contained scope composition contains a cycle")
        if current in visited:
            continue
        visited.add(current)
        projection = validate_composition(
            authority, snapshot, current, budget=max(1, remaining)
        )
        if projection.protocol_root == authority.shape("instance"):
            instances[current] = _project_instance(authority, snapshot, current)
        next_ancestors = ancestors | {current}
        for member in projection.members:
            if member.role_id == authority.role("relation"):
                if member.participant_id in relations:
                    raise InvalidCell("contained scope relation is duplicated")
                relations[member.participant_id] = _project_relation_node(
                    authority, snapshot, member.participant_id
                )
                remaining -= 1
            elif member.role_id == authority.role("composition"):
                if depth >= max_depth:
                    raise InvalidCell("contained scope exceeded its depth bound")
                pending.append((
                    member.participant_id,
                    depth + 1,
                    next_ancestors,
                ))
                remaining -= 1
            if remaining < 0:
                raise InvalidCell("contained scope exceeded its budget")
    return ContainedScopeProjection(
        container_root,
        snapshot.revision,
        MappingProxyType(dict(sorted(instances.items()))),
        MappingProxyType(dict(sorted(relations.items()))),
    )


# A level read is pure over (what it read, container, scope, caller).
# Entries are dropped by commit-touched roots, not by revision: a focus
# commit touches attention cells and leaves the level's entries alive,
# which is the difference between a 0.15s click and a 1.2s one. Keyed
# by caller so authorization is never shared; refusals raise before
# anything is stored.
_SCOPE_LEVEL_MEMOS: "WeakKeyDictionary" = WeakKeyDictionary()


def read_scope_level(
    authority: UnifiedAuthority,
    container_root: str,
    *,
    scope_root: str,
    caller: CallerCommandCapability,
    at_revision: int | None = None,
    budget: int = COMMAND_BUDGET,
) -> ScopeLevelProjection:
    """Read only the direct children and relations of one authorized scope."""
    # Revision-keyed, not touched-keyed: a level read walks relations
    # this function cannot enumerate, and a memo whose read set is a
    # guess serves a scope that no longer holds what it shows -- a
    # placed node reported "not a member" the moment it landed. One
    # revision, one answer; a commit ends every entry.
    revision = authority.store.revision
    entry = _SCOPE_LEVEL_MEMOS.get(authority.store)
    if entry is None or entry[0] != revision:
        entry = (revision, {})
        _SCOPE_LEVEL_MEMOS[authority.store] = entry
    normalized_at = (
        None if at_revision == revision else at_revision
    )
    memo_key = (
        container_root, scope_root, caller.actor_root, normalized_at
    )
    held = entry[1].get(memo_key)
    if held is not None:
        return held
    projection = _read_scope_level_uncached(
        authority, container_root, scope_root=scope_root, caller=caller,
        at_revision=at_revision, budget=budget,
    )
    entry[1][memo_key] = projection
    return projection


def _read_scope_level_uncached(
    authority: UnifiedAuthority,
    container_root: str,
    *,
    scope_root: str,
    caller: CallerCommandCapability,
    at_revision: int | None = None,
    budget: int = COMMAND_BUDGET,
) -> ScopeLevelProjection:
    if budget < 1:
        raise InvalidCell("scope level budget is invalid")
    current = authority.store.snapshot()
    _authorize_semantic_read(
        authority,
        current,
        caller,
        object_root=container_root,
        scope_root=scope_root,
        budget=budget,
    )
    snapshot = current if at_revision is None else authority.store.at(at_revision)
    if snapshot.revision != current.revision:
        _verify_exact_snapshot_head(authority, snapshot)
    container = validate_composition(authority, snapshot, container_root, budget=budget)
    if container.protocol_root not in {
        authority.shape("composition"),
        authority.shape("instance"),
    }:
        raise InvalidCell("scope level root is not an openable composition")

    composition_roots: list[str] = []
    composition_labels: dict[str, str | None] = {}
    instances: dict[str, Mapping[str, object]] = {}
    relations: dict[str, ExplicitRelationProjection] = {}
    remaining = budget
    for member in container.members:
        if member.role_id == authority.role("composition"):
            child_root = member.participant_id
            if child_root in composition_labels:
                raise InvalidCell("scope level composition is duplicated")
            child = validate_composition(
                authority,
                snapshot,
                child_root,
                budget=max(1, remaining),
            )
            child_label = _optional_label(authority, snapshot, child_root)
            if child.protocol_root not in {
                authority.shape("composition"),
                authority.shape("instance"),
            }:
                # Protocol, policy, catalogue, and history roots also anchor the
                # application graph. They are available through deeper lenses,
                # but are not children of the direct-manipulation scope level.
                continue
            composition_roots.append(child_root)
            composition_labels[child_root] = child_label
            if child.protocol_root == authority.shape("instance"):
                instances[child_root] = _project_instance(
                    authority, snapshot, child_root
                )
                for child_member in child.members:
                    if child_member.role_id != authority.role("relation"):
                        continue
                    relation_root = child_member.participant_id
                    if relation_root in relations:
                        raise InvalidCell("scope level relation is duplicated")
                    relations[relation_root] = _project_relation_node(
                        authority, snapshot, relation_root
                    )
                    remaining -= 1
            remaining -= 1
        elif member.role_id == authority.role("relation"):
            relation_root = member.participant_id
            if relation_root in relations:
                raise InvalidCell("scope level relation is duplicated")
            relations[relation_root] = _project_relation_node(
                authority, snapshot, relation_root
            )
            remaining -= 1
        if remaining < 0:
            raise InvalidCell("scope level exceeded its budget")
    return ScopeLevelProjection(
        container_root,
        snapshot.revision,
        _optional_label(authority, snapshot, container_root),
        tuple(composition_roots),
        MappingProxyType(dict(sorted(composition_labels.items()))),
        MappingProxyType(dict(sorted(instances.items()))),
        MappingProxyType(dict(sorted(relations.items()))),
    )


def _remembered_reachability(store, revision, root_id, required):
    """A revision-bound note that these roots were already proven here.

    Proving nine roots reachable walked half a million cells on every
    open. The answer cannot change while the revision does not, so it
    is kept beside the graph as an accelerator: deleting it costs one
    slow open and changes no meaning (SPEC 3.1.6).
    """
    accelerators = getattr(store, "_accelerators", None)
    if accelerators is None:
        return None
    try:
        connection = accelerators()
        connection.execute(
            "CREATE TABLE IF NOT EXISTS reachability_proofs ("
            "revision INTEGER NOT NULL, root TEXT NOT NULL, "
            "required TEXT NOT NULL, PRIMARY KEY (root, required))"
        )
        return connection
    except Exception:  # noqa: BLE001 - an accelerator may never refuse a read
        return None


def roots_are_reachable(
    snapshot: Snapshot,
    root_id: str,
    required: frozenset[str] | set[str],
    *,
    store=None,
) -> bool:
    """Whether every required root sits in the region under one root.

    Opening the authority asked for the WHOLE reachable region and then
    tested nine roots against it, so every start walked the entire graph --
    three hundred thousand cells and minutes of it -- to answer a question
    about nine. The walk stops as soon as all nine are found, which on a
    real graph is immediately, and still walks everything when one is
    genuinely absent because that is the only way to prove absence.
    """
    if root_id not in snapshot.cells:
        raise InvalidCell("root is missing")
    outstanding = set(required)
    outstanding.discard(root_id)
    if not outstanding:
        return True
    wanted = ",".join(sorted(outstanding))
    remembered = _remembered_reachability(
        store, snapshot.revision, root_id, wanted
    )
    if remembered is not None:
        row = remembered.execute(
            "SELECT revision FROM reachability_proofs "
            "WHERE root = ? AND required = ?",
            (root_id, wanted),
        ).fetchone()
        if row is not None and int(row[0]) == int(snapshot.revision):
            return True
    pending = [root_id]
    found: set[str] = set()
    # A lazily read head answers one row per query; asking it for the
    # whole frontier at once turns half a million round trips into a
    # few hundred statements.
    warm = getattr(snapshot.cells, "prefetch", None)
    while pending:
        if warm is not None and len(pending) > 1:
            warm([
                key for key in pending
                if key != NULL_CELL_ID and key not in found
            ])
        frontier, pending = pending, []
        for current in frontier:
            if current == NULL_CELL_ID or current in found:
                continue
            cell = snapshot.cells.get(current)
            if cell is None:
                raise InvalidCell("graph contains a dangling link")
            found.add(current)
            outstanding.discard(current)
            if not outstanding:
                if remembered is not None:
                    try:
                        remembered.execute(
                            "INSERT OR REPLACE INTO reachability_proofs "
                            "(revision, root, required) VALUES (?, ?, ?)",
                            (int(snapshot.revision), root_id, wanted),
                        )
                        remembered.commit()
                    except Exception:  # noqa: BLE001
                        pass
                return True
            pending.append(cell.link0)
            pending.append(cell.link1)
    return False


def reachable_roots(snapshot: Snapshot, root_id: str) -> frozenset[str]:
    """Return the exact region reachable through raw physical links."""
    if root_id not in snapshot.cells:
        raise InvalidCell("root is missing")
    pending = [root_id]
    found: set[str] = set()
    while pending:
        current = pending.pop()
        if current == NULL_CELL_ID or current in found:
            continue
        cell = snapshot.cells.get(current)
        if cell is None:
            raise InvalidCell("graph contains a dangling link")
        found.add(current)
        pending.extend((cell.link0, cell.link1))
    return frozenset(found)


def relation_members(snapshot: Snapshot, root_id: str) -> tuple[RelationMember, ...]:
    return read_relation(snapshot, root_id, budget=100_000)




# ---------------------------------------------------------------------
# Authority seam.
#
# These operations are shared by the modules that build on this authority
# (requirement import, browser authority, scope interactions, visual
# authority, attention, scope state). They were reached through their
# private names, which left no declared contract between the authority and
# its consumers: any rename here broke them silently, and each new consumer
# copied the same reach. That is the growth path that produced the 46k-line
# legacy application module.
#
# The public names below are the supported seam. The private names remain
# for use inside this module.
# ---------------------------------------------------------------------
commit_with_receipt = _commit_with_receipt
find_receipt = _find_receipt
validate_command_participants = _validate_command_participants
digest = _digest
new_id = _new_id
typed_relation_cells = _typed_relation_cells
build_value = _build_value
append_relation_member = _append_relation_member
append_relation_members = _append_relation_members
decode_value = _decode_value
relation_cells = _relation_cells
build_definition_revision = _build_definition_revision
build_property = _build_property
definition_spec = _definition_spec
property_identities = _property_identities


__all__ = [
    "commit_with_receipt",
    "find_receipt",
    "validate_command_participants",
    "digest",
    "new_id",
    "typed_relation_cells",
    "build_contract",
    "build_value",
    "append_relation_member",
    "append_relation_members",
    "decode_value",
    "relation_cells",
    "build_definition_revision",
    "build_property",
    "definition_spec",
    "property_identities",
    "audit_authority_history",
    "BootstrapManifest",
    "CallerCommandCapability",
    "CommandResult",
    "ContainedScopeProjection",
    "DefinitionProjection",
    "ExplicitRelationProjection",
    "ScopeLevelProjection",
    "UnifiedAuthority",
    "composition_root",
    "create_relation_node",
    "create_unified_authority",
    "declare_definition",
    "enroll_session",
    "instantiate_definition",
    "open_unified_authority",
    "promote_definition",
    "reachable_roots",
    "read_definition",
    "read_instance",
    "read_contained_scope",
    "read_scope_level",
    "read_relation_node",
    "relation_members",
    "revoke_session",
    "revise_relation_node",
    "revise_instance",
    "revise_definition",
    "sign_bootstrap_manifest",
    "validate_composition",
    "verify_exact_authority_head",
]
