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

import math
import re
import unicodedata
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

# A credential can sit inside a sentence. These are searched ANYWHERE in the
# text, never anchored to its start or end.
_CREDENTIAL_IN_TEXT = (
    # personal-brain-mcp personal_cloud_sync.py _SECRET_TOKEN_RE (127-132).
    re.compile(
        r"(?<![A-Za-z0-9_\-])"
        r"(?:(?:sk-|sk_live_|sk_test_|rk_live_|rk_test_|AKIA|AIza|gh[pousr]_|xox[bpars]-)"
        r"[A-Za-z0-9_\-]{8,}"
        r"|eyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,})"
    ),
    # personal-brain-mcp redaction.py _PATTERNS, the secret rows (47-59).
    re.compile(r"\b(?:sk|ghp|gho|ghu|ghs|ghr)[_\-][A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}"),
    re.compile(r"\bya29\.[A-Za-z0-9_-]+"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bxox[bpars]-[0-9A-Za-z\-]{10,}"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{6,}"),
    # A private key block, whatever the key type.
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    # Authorization header values anywhere in the text.
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/]{12,}={0,2}"),
    # A password in a URL: scheme://user:password@host
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@"),
    # "<name>=value" / "<name>: value", where the name may carry a prefix as in
    # PGPASSWORD or DB_PASSWORD or OPENAI_API_KEY.
    re.compile(
        r"(?i)(?<![A-Za-z0-9])[A-Za-z0-9]*[_\-]?(?:api[_\- ]?key|access[_\- ]?token"
        r"|refresh[_\- ]?token|password|passwd|pwd|passphrase|secret|token)"
        r"\s*[:=]\s*\S{4,}"
    ),
    # "<name> is value": a value with a digit, or one long unbroken word, so
    # "the wifi password is on the fridge" stays a memory.
    re.compile(
        r"(?i)(?<![A-Za-z0-9])[A-Za-z0-9]*[_\-]?(?:api[_\- ]?key|access[_\- ]?token"
        r"|refresh[_\- ]?token|password|passwd|pwd|passphrase|secret|token)"
        r"\s+is\s+(?:(?=\S*\d)\S{6,}|\S{12,})"
    ),
)
# Candidate secret words: runs of the base64 alphabet. '-', '_' and '.' break a
# run, so identifiers like claude-codex-link-20260914 never form one.
_WORD = re.compile(r"[A-Za-z0-9+/=]{32,}")
_URL_TOKEN = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://\S+")
_SRI = re.compile(r"(?i)\bsha(?:256|384|512)-[A-Za-z0-9+/=]+")
# Format (zero-width) and non-spacing marks (a combining grapheme joiner) are
# invisible; so are the Hangul and Braille fillers, which are letters.
_INVISIBLE = {"Cf", "Mn"}
_FILLERS = frozenset("\u115f\u1160\u2800\u3164\uffa0")
_WORD_SEGMENT = re.compile(r"[A-Z]?[a-z]{3,}")


def _normalised(value: str) -> str:
    """Fold look-alikes and drop invisible format characters before matching."""
    folded = unicodedata.normalize("NFKC", value)
    return "".join(c for c in folded
                   if unicodedata.category(c) not in _INVISIBLE and c not in _FILLERS)


def _high_entropy_word(word: str) -> bool:
    """A random-looking key half: mixed case and digits, near-random entropy, and
    less than half of it made of word segments ([A-Z]?[a-z]{3,}).

    Measured 2026-09-17 on 5000 seeded random keys each: a lower-case-run limit
    of 4 admitted 1196 of 40-char base64 and 2337 of 32-char base62 keys; this
    rule admits 37 and 139. camelCase identifiers are mostly word segments.
    """
    classes = sum((
        any(c.islower() for c in word),
        any(c.isupper() for c in word),
        any(c.isdigit() for c in word),
    ))
    if classes < 3:
        return False
    counts = {}
    for c in word:
        counts[c] = counts.get(c, 0) + 1
    entropy = -sum(n / len(word) * math.log2(n / len(word)) for n in counts.values())
    words = sum(len(segment) for segment in _WORD_SEGMENT.findall(word))
    return entropy >= min(4.5, math.log2(len(word)) - 1.0) and words * 2 < len(word)


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


def assert_no_credential_in_text(value: str, label: str) -> None:
    """Refuse prose that carries a credential anywhere inside it.

    ``assert_not_a_secret`` judges a value that should be a reference. Memory
    text is a sentence, and a key pasted mid-sentence is still a key. A long
    word mixing lower case, upper case and digits is refused too: that is how a
    secret half of a key pair looks when no prefix names it.
    """
    if not isinstance(value, str):
        raise InvalidCell("%s must be text" % label)
    text = _normalised(value)
    for pattern in _CREDENTIAL_IN_TEXT:
        if pattern.search(text):
            raise InvalidCell("%s carries a credential" % label)
    words = _SRI.sub(" ", _URL_TOKEN.sub(" ", text))
    if any(_high_entropy_word(word) for word in _WORD.findall(words)):
        raise InvalidCell("%s carries a credential-shaped word" % label)


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
