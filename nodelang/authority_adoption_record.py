"""Graph-held adoption evidence for later atomic publication and recovery.

Reading a record does not authenticate it. The opener must verify source
authorization, the successor signed head and exact selected roots before use.
No mutation, activation or manifest generation occurs here.
"""
from dataclasses import asdict, dataclass, fields
import hashlib
import math
import uuid

from .authority_adoption import AuthorityAdoptionAuthorization
from .cell_protocols import compose_relation_cells, read_relation, _relation_chain_ids
from .universal_cell import Cell, InvalidCell, NULL_CELL_ID


REFERENCES = frozenset(("application_root", "owner_root", "tenant_root",
    "identity_protocol_root", "authorization_protocol_root", "policy_root"))
INTEGERS = frozenset(("version", "source_revision", "key_version", "successor_authority_key_version"))
FLOATS = frozenset(("issued_at", "expires_at"))


@dataclass(frozen=True, slots=True)
class AdoptionRecord:
    root: str
    authorization: AuthorityAdoptionAuthorization
    read_roots: tuple[str, ...]
    digest: str


def _validate_statement(statement):
    if type(statement) is not AuthorityAdoptionAuthorization or statement.version != 2 or not statement.signature:
        raise InvalidCell("adoption record requires a signed v2 statement")
    if any(type(getattr(statement, name)) is not int or getattr(statement, name) < 1
            for name in INTEGERS):
        raise InvalidCell("adoption record integer domain is invalid")
    if any(type(getattr(statement, name)) is not float or not math.isfinite(getattr(statement, name))
            for name in FLOATS):
        raise InvalidCell("adoption record timestamp domain is invalid")
    if not 0 < statement.expires_at - statement.issued_at <= 300:
        raise InvalidCell("adoption record lifetime is invalid")


def prepare_adoption_record(snapshot, statement):
    """Prepare immutable evidence Cells; references retain existing identities."""
    _validate_statement(statement)
    if statement.source_revision != snapshot.revision:
        raise InvalidCell("adoption record requires a signed current v2 statement")
    cells, pairs = [], []
    for name, value in asdict(statement).items():
        role = str(uuid.uuid4())
        cells.append(Cell(role, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")))
        if name in REFERENCES:
            if type(value) is not str or value == NULL_CELL_ID or value not in snapshot.cells:
                raise InvalidCell("adoption record source reference is missing")
            target = value
        else:
            if name in INTEGERS:
                if type(value) is not int:
                    raise InvalidCell("adoption record integer is invalid")
                payload = str(value).encode("ascii")
            elif name in FLOATS:
                if type(value) is not float:
                    raise InvalidCell("adoption record timestamp is invalid")
                payload = value.hex().encode("ascii")
            else:
                if type(value) is not str:
                    raise InvalidCell("adoption record scalar is invalid")
                payload = value.encode("utf-8")
            if not payload or len(payload) > 1024:
                raise InvalidCell("adoption record scalar exceeds its bound")
            target = str(uuid.uuid4())
            cells.append(Cell(target, NULL_CELL_ID, NULL_CELL_ID, payload))
        pairs.append((role, target))
    built = compose_relation_cells(pairs, relation_id=str(uuid.uuid4()))
    return built.build.root_id, (*cells, *built.cells)


def read_adoption_record(snapshot, root):
    expected = {field.name for field in fields(AuthorityAdoptionAuthorization)}
    members = read_relation(snapshot, root, budget=64, retain_projection=False)
    if len(members) != len(expected):
        raise InvalidCell("adoption record fields are incomplete")
    values = {}
    read_ids = set(_relation_chain_ids(snapshot, root, budget=64))
    record_ids = set(read_ids)
    for member in members:
        role = snapshot.cells[member.role_id]
        if role.link0 != NULL_CELL_ID or role.link1 != NULL_CELL_ID or len(role.atom) > 80:
            raise InvalidCell("adoption record role is malformed")
        try:
            name = role.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell("adoption record role is invalid") from exc
        if name not in expected or name in values:
            raise InvalidCell("adoption record field is unknown or duplicated")
        read_ids.update((role.id, member.incidence_id, member.participant_id))
        record_ids.update((role.id, member.incidence_id))
        if name in REFERENCES:
            if member.participant_id == NULL_CELL_ID or member.participant_id not in snapshot.cells:
                raise InvalidCell("adoption record source reference is missing")
            values[name] = member.participant_id
            continue
        cell = snapshot.cells[member.participant_id]
        record_ids.add(cell.id)
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID or not 0 < len(cell.atom) <= 1024:
            raise InvalidCell("adoption record scalar is malformed")
        try:
            text = cell.atom.decode("utf-8")
            value = int(text) if name in INTEGERS else float.fromhex(text) if name in FLOATS else text
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidCell("adoption record scalar is invalid") from exc
        canonical = str(value) if name in INTEGERS else value.hex() if name in FLOATS else value
        if canonical != text:
            raise InvalidCell("adoption record scalar is not canonical")
        values[name] = value
    statement = AuthorityAdoptionAuthorization(**values)
    _validate_statement(statement)
    digest = hashlib.sha256(b"ArchHub/adoption-record/v2\0")
    # Source references may evolve after adoption. The signed ticket binds
    # their historical snapshot; the record digest binds reference identities.
    for identity in sorted(record_ids):
        cell = snapshot.cells[identity]
        for value in (cell.id.encode(), cell.link0.encode(), cell.link1.encode(), cell.atom):
            digest.update(len(value).to_bytes(8, "big") + value)
    return AdoptionRecord(root, statement, tuple(sorted(read_ids)), digest.hexdigest())
