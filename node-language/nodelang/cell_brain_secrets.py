"""The brain's secret vault: references and custody, never the secret.

`brain_secrets` in the superseded app was a store that held values. The brain
now synchronises, projects, and is read by lenses -- so a value it holds is a
value that leaks. The graph holds only WHERE a secret lives and WHO has custody
of it. Resolution happens outside the graph, through a caller-supplied
resolver, and nothing that resolver returns is ever written back.

The refusal is deliberately loud: a value that merely LOOKS like a credential
is refused, because a vault that quietly accepts one has already failed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot

VAULT_ROOT = "app:brain:secret-vault"
VAULT_MEMBER_ROLE = VAULT_ROOT + ":role:entry"
VAULT_NAME_ROLE = VAULT_ROOT + ":role:name"
VAULT_REFERENCE_ROLE = VAULT_ROOT + ":role:reference"
VAULT_CUSTODY_ROLE = VAULT_ROOT + ":role:custody"

# A reference names a place. Anything else is a value pretending to be one.
ADMITTED_SCHEMES: tuple[str, ...] = ("op://", "dpapi://", "kms://", "keyring://")

# Custody is who can actually produce the bytes. The graph is never on this list.
ADMITTED_CUSTODY: Mapping[str, str] = MappingProxyType({
    "operator-vault": "A vault the operator unlocks, outside this process",
    "os-keystore": "The operating system's own protected store",
    "cloud-kms": "A cloud key-management service",
})

_LOOKS_LIKE_A_SECRET = re.compile(
    r"(?i)(?:^(?:sk|pk|ghp|xox[abps]|ah_live|AKIA)[-_A-Za-z0-9]{8,}$"
    r"|^bearer\s+\S+$"
    r"|\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)"
    r"\s*[:=]\s*\S+)"
)
_HIGH_ENTROPY = re.compile(r"^[A-Za-z0-9+/=_-]{40,}$")


@dataclass(frozen=True, slots=True)
class SecretEntry:
    name: str
    reference: str
    custody: str


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("vault text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def assert_not_a_secret(value: str, label: str) -> None:
    """Refuse anything that reads like the secret itself."""
    if _LOOKS_LIKE_A_SECRET.search(value) or _HIGH_ENTROPY.match(value):
        raise InvalidCell("%s looks like a credential, not a reference" % label)


def _entry_root(name: str) -> str:
    return "%s:entry:%s" % (VAULT_ROOT, name)


def ensure_vault(store: CellStore) -> str:
    snapshot = store.snapshot()
    if VAULT_ROOT in snapshot.cells:
        return VAULT_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(VAULT_MEMBER_ROLE, "entry"),
        _terminal(VAULT_NAME_ROLE, "name"),
        _terminal(VAULT_REFERENCE_ROLE, "reference"),
        _terminal(VAULT_CUSTODY_ROLE, "custody"),
        Cell(VAULT_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return VAULT_ROOT


def admit_secret(
    store: CellStore,
    *,
    name: str,
    reference: str,
    custody: str,
) -> str:
    """Record WHERE a secret lives. The value never enters the graph."""
    name = name.strip()
    reference = reference.strip()
    if not name:
        raise InvalidCell("a vault entry must be named")
    if custody not in ADMITTED_CUSTODY:
        raise InvalidCell("custody is not an admitted provider: %s" % custody)
    if not reference.startswith(ADMITTED_SCHEMES):
        raise InvalidCell(
            "reference must name a place, one of %s" % (ADMITTED_SCHEMES,)
        )
    assert_not_a_secret(reference, "vault reference")
    assert_not_a_secret(name, "vault name")

    ensure_vault(store)
    snapshot = store.snapshot()
    root = _entry_root(name)
    if root in snapshot.cells:
        raise InvalidCell("vault already holds an entry named %s" % name)
    name_root, ref_root, custody_root = (
        root + ":name", root + ":reference", root + ":custody",
    )
    store.commit(snapshot.revision, create=(
        _terminal(name_root, name),
        _terminal(ref_root, reference),
        _terminal(custody_root, custody),
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    entry_patch = prepare_append_relation_members(snapshot, root, (
        (VAULT_NAME_ROLE, name_root),
        (VAULT_REFERENCE_ROLE, ref_root),
        (VAULT_CUSTODY_ROLE, custody_root),
    ), budget=10_000)
    store.commit(
        snapshot.revision,
        create=entry_patch.create, replace=entry_patch.replace,
    )
    snapshot = store.snapshot()
    vault_patch = prepare_append_relation_members(
        snapshot, VAULT_ROOT, ((VAULT_MEMBER_ROLE, root),), budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=vault_patch.create, replace=vault_patch.replace,
    )
    return root


def read_secret_reference(snapshot: Snapshot, name: str) -> SecretEntry:
    """Where it lives and who holds it. Never the bytes."""
    root = _entry_root(name.strip())
    if root not in snapshot.cells:
        raise InvalidCell("vault holds no entry named %s" % name)
    members = read_relation(snapshot, root, budget=10_000)
    def one(role: str, label: str) -> str:
        found = [m.participant_id for m in members if m.role_id == role]
        if len(found) != 1:
            raise InvalidCell("vault entry has no single %s" % label)
        return _text(snapshot, found[0])
    return SecretEntry(
        one(VAULT_NAME_ROLE, "name"),
        one(VAULT_REFERENCE_ROLE, "reference"),
        one(VAULT_CUSTODY_ROLE, "custody"),
    )


def project_vault(snapshot: Snapshot) -> tuple[SecretEntry, ...]:
    """Everything the vault knows -- which is deliberately not much."""
    if VAULT_ROOT not in snapshot.cells:
        return ()
    entries = []
    for member in read_relation(snapshot, VAULT_ROOT, budget=100_000):
        if member.role_id != VAULT_MEMBER_ROLE:
            continue
        name = _text(snapshot, member.participant_id + ":name")
        entries.append(read_secret_reference(snapshot, name))
    return tuple(entries)


def resolve_secret(
    snapshot: Snapshot,
    name: str,
    resolver: Callable[[str, str], str],
) -> str:
    """Ask custody for the value. Nothing it returns is written back."""
    entry = read_secret_reference(snapshot, name)
    value = resolver(entry.reference, entry.custody)
    if not isinstance(value, str) or not value:
        raise InvalidCell("custody returned nothing for %s" % name)
    return value
