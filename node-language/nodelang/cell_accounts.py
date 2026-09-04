"""Accounts and tiers: who a person is, and what the founder opened for them.

Identity is an email account -- never a machine. The founder places any
account in any tier at any time; tiers decide which features an
installed app opens. Enforcement of paid tiers belongs to the cloud
account service; this module is the graph record both sides read.
"""
from __future__ import annotations

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

ACCOUNTS_ROOT = "app:users:accounts"
ACCOUNT_ROLE = ACCOUNTS_ROOT + ":role:account"
EMAIL_ROLE = ACCOUNTS_ROOT + ":role:email"
TIER_ROLE = ACCOUNTS_ROOT + ":role:tier"
FOUNDER_EMAIL_ROOT = ACCOUNTS_ROOT + ":founder-email"

TIERS = ("free", "pro", "firm", "founder")


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("account text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def _normal(email):
    email = str(email or "").strip().casefold()
    if "@" not in email or len(email) > 254:
        raise InvalidCell("account email is invalid")
    return email


def _account_root(email):
    import hashlib
    return ACCOUNTS_ROOT + ":account:" + hashlib.sha256(
        email.encode("utf-8")
    ).hexdigest()[:24]


def ensure_accounts(store, *, founder_email):
    """The accounts registry, and the founder standing in it as founder."""
    snapshot = store.snapshot()
    create = []
    if ACCOUNTS_ROOT not in snapshot.cells:
        create.extend((
            _terminal(ACCOUNT_ROLE, "account"),
            _terminal(EMAIL_ROLE, "email"),
            _terminal(TIER_ROLE, "tier"),
            Cell(ACCOUNTS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"accounts"),
        ))
    if FOUNDER_EMAIL_ROOT not in snapshot.cells:
        create.append(_terminal(FOUNDER_EMAIL_ROOT, _normal(founder_email)))
    if create:
        store.commit(snapshot.revision, create=tuple(create))
    upsert_account(store, founder_email)


def founder_email(snapshot):
    return _text(snapshot, FOUNDER_EMAIL_ROOT)


def upsert_account(store, email):
    """Find or create the account; returns (root, email, tier)."""
    email = _normal(email)
    snapshot = store.snapshot()
    root = _account_root(email)
    if root in snapshot.cells:
        return root, email, _text(snapshot, root + ":tier")
    tier = "founder" if email == founder_email(snapshot) else "free"
    create = (
        _terminal(root + ":email", email),
        _terminal(root + ":tier", tier),
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"account"),
    )
    patch = prepare_append_relation_members(
        snapshot, ACCOUNTS_ROOT, ((ACCOUNT_ROLE, root),), budget=100_000
    )
    store.commit(
        snapshot.revision,
        create=(*create, *patch.create),
        replace=patch.replace,
    )
    return root, email, tier


def read_accounts(snapshot):
    # A registry nobody has opened yet holds nobody, which is an ANSWER,
    # not a failure. Reading before the first sign-in must not refuse.
    if ACCOUNTS_ROOT not in snapshot.cells:
        return []
    out = []
    for member in read_relation(snapshot, ACCOUNTS_ROOT, budget=100_000):
        if member.role_id != ACCOUNT_ROLE:
            continue
        root = member.participant_id
        out.append({
            "email": _text(snapshot, root + ":email"),
            "tier": _text(snapshot, root + ":tier"),
        })
    return sorted(out, key=lambda item: item["email"])


def set_tier(store, email, tier):
    """The founder moves an account to any tier, any time."""
    email = _normal(email)
    if tier not in TIERS:
        raise InvalidCell("unknown tier %r" % tier)
    snapshot = store.snapshot()
    if email == founder_email(snapshot):
        raise InvalidCell("the founder account cannot be re-tiered")
    if tier == "founder":
        # There is one founder, declared at bootstrap; the tier cannot be
        # handed to a second account through the tier dial.
        raise InvalidCell("the founder tier is not assignable")
    root = _account_root(email)
    if root not in snapshot.cells:
        raise InvalidCell("no account for %s" % email)
    held = snapshot.cells[root + ":tier"]
    store.commit(snapshot.revision, replace=(Cell(
        held.id, held.link0, held.link1, tier.encode("utf-8")
    ),))
    return tier


__all__ = [
    "ACCOUNTS_ROOT", "TIERS", "ensure_accounts", "founder_email",
    "read_accounts", "set_tier", "upsert_account",
]
