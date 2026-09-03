"""Model providers: named, keyed by reference, cooled down, and metered.

The superseded router held provider keys, guessed at failures, and counted
nothing. Three separate ways to lose money or leak a key.

A provider here is admitted by name and points at a secret-vault ENTRY, never at
a key. A failure is classified rather than retried blindly, and a provider that
is rate-limited or broken is unavailable until its cooldown passes -- the graph
says so, not a timer in someone's memory. Every call is metered, so cost is a
fact and not a surprise.

Time is passed in. A clock the graph cannot see is a clock the courts cannot
test.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_brain_secrets import read_secret_reference
from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

PROVIDERS_ROOT = "app:models:providers"
PROVIDER_ROLE = PROVIDERS_ROOT + ":role:provider"
KEY_ROLE = PROVIDERS_ROOT + ":role:key-entry"
COOLDOWN_ROLE = PROVIDERS_ROOT + ":role:cooldown-until"
USAGE_ROLE = PROVIDERS_ROOT + ":role:usage"

ADMITTED_PROVIDERS: Mapping[str, str] = MappingProxyType({
    "anthropic": "Claude",
    "openai": "GPT",
    "google": "Gemini",
    "local": "A model running on this machine",
    "cli-subscription": "A signed-in CLI the operator already pays for",
})

# What a failure MEANS, so the router stops guessing.
RETRYABLE = "retryable"
RATE_LIMITED = "rate-limited"
FATAL = "fatal"

FAILURE_KINDS: Mapping[str, str] = MappingProxyType({
    "timeout": RETRYABLE,
    "connection": RETRYABLE,
    "overloaded": RATE_LIMITED,
    "rate-limit": RATE_LIMITED,
    "quota": RATE_LIMITED,
    "unauthorized": FATAL,
    "not-found": FATAL,
    "refused": FATAL,
})

COOLDOWN_SECONDS: Mapping[str, int] = MappingProxyType({
    RETRYABLE: 5,
    RATE_LIMITED: 60,
    FATAL: 3600,
})


@dataclass(frozen=True, slots=True)
class Usage:
    provider: str
    calls: int
    tokens: int


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("provider text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_providers(store):
    snapshot = store.snapshot()
    if PROVIDERS_ROOT in snapshot.cells:
        return PROVIDERS_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(PROVIDER_ROLE, "provider"),
        _terminal(KEY_ROLE, "key-entry"),
        _terminal(COOLDOWN_ROLE, "cooldown-until"),
        _terminal(USAGE_ROLE, "usage"),
        Cell(PROVIDERS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return PROVIDERS_ROOT


def _provider_root(provider):
    return "%s:provider:%s" % (PROVIDERS_ROOT, provider)


def classify_failure(kind):
    """A failure means something. Guessing is how a router loops forever."""
    if kind not in FAILURE_KINDS:
        raise InvalidCell("failure kind is not classified: %s" % kind)
    return FAILURE_KINDS[kind]


def register_provider(store, *, provider, key_entry_name):
    """Point a provider at a VAULT ENTRY. A key never reaches this graph."""
    if provider not in ADMITTED_PROVIDERS:
        raise InvalidCell("provider is not admitted: %s" % provider)
    snapshot = store.snapshot()
    # Raises if the vault does not hold it -- so a provider cannot be
    # registered against a key that was never put into custody.
    read_secret_reference(snapshot, key_entry_name)
    ensure_providers(store)
    snapshot = store.snapshot()
    root = _provider_root(provider)
    if root in snapshot.cells:
        raise InvalidCell("provider is already registered: %s" % provider)
    name_root = root + ":key-entry"
    cooldown_root = root + ":cooldown"
    calls_root = root + ":calls"
    tokens_root = root + ":tokens"
    store.commit(snapshot.revision, create=(
        _terminal(name_root, key_entry_name),
        _terminal(cooldown_root, 0),
        _terminal(calls_root, 0),
        _terminal(tokens_root, 0),
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, root, (
        (KEY_ROLE, name_root),
        (COOLDOWN_ROLE, cooldown_root),
        (USAGE_ROLE, calls_root),
        (USAGE_ROLE, tokens_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, PROVIDERS_ROOT, ((PROVIDER_ROLE, root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return root


def registered(snapshot):
    if PROVIDERS_ROOT not in snapshot.cells:
        return ()
    return tuple(sorted(
        m.participant_id.rsplit(":", 1)[-1]
        for m in read_relation(snapshot, PROVIDERS_ROOT, budget=100_000)
        if m.role_id == PROVIDER_ROLE
    ))


def _require(snapshot, provider):
    root = _provider_root(provider)
    if root not in snapshot.cells:
        raise InvalidCell("provider is not registered: %s" % provider)
    return root


def key_entry_for(snapshot, provider):
    """The vault entry, never the key."""
    return _text(snapshot, _require(snapshot, provider) + ":key-entry")


def record_failure(store, *, provider, kind, now):
    """Classify, then cool the provider down for as long as that class needs."""
    severity = classify_failure(kind)
    snapshot = store.snapshot()
    root = _require(snapshot, provider)
    until = int(now) + COOLDOWN_SECONDS[severity]
    store.commit(snapshot.revision, replace=(
        _terminal(root + ":cooldown", until),))
    return severity, until


def is_available(snapshot, provider, now):
    """Available means the graph says the cooldown has passed."""
    root = _require(snapshot, provider)
    return int(now) >= int(_text(snapshot, root + ":cooldown"))


def record_call(store, *, provider, tokens, now):
    """Meter every call. Cost you cannot see is cost you cannot control."""
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise InvalidCell("a call must report a whole number of tokens")
    snapshot = store.snapshot()
    root = _require(snapshot, provider)
    if not is_available(snapshot, provider, now):
        raise InvalidCell("provider is cooling down and must not be called")
    calls = int(_text(snapshot, root + ":calls")) + 1
    total = int(_text(snapshot, root + ":tokens")) + tokens
    store.commit(snapshot.revision, replace=(
        _terminal(root + ":calls", calls),
        _terminal(root + ":tokens", total),
    ))
    return Usage(provider, calls, total)


def usage(snapshot, provider):
    root = _require(snapshot, provider)
    return Usage(
        provider,
        int(_text(snapshot, root + ":calls")),
        int(_text(snapshot, root + ":tokens")),
    )
