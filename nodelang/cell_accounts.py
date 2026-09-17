"""Accounts and tiers: who a person is, and what the founder opened for them.

Identity is an email account -- never a machine. The founder places any
account in any tier at any time; tiers decide which features an
installed app opens. Enforcement of paid tiers belongs to the cloud
account service; this module is the graph record both sides read.

The founders are a relation, not one string: every founder account stands
in it, and the migration that fills it only ever appends. The offer is one
record -- what ArchHub is offered as, and whether a price is shown --
declared once on the founder's instance and read by every surface that
states it. Callers pass the account a cloud session proved; this module
checks that account against the founders.
"""
from __future__ import annotations

import hashlib
import json
import re

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

ACCOUNTS_ROOT = "app:users:accounts"
ACCOUNT_ROLE = ACCOUNTS_ROOT + ":role:account"
EMAIL_ROLE = ACCOUNTS_ROOT + ":role:email"
TIER_ROLE = ACCOUNTS_ROOT + ":role:tier"
FOUNDER_EMAIL_ROOT = ACCOUNTS_ROOT + ":founder-email"
FOUNDERS_ROOT = ACCOUNTS_ROOT + ":founders"
FOUNDER_ROLE = ACCOUNTS_ROOT + ":role:founder"
OFFER_ROOT = ACCOUNTS_ROOT + ":offer"

TIERS = ("free", "pro", "firm", "founder")

# Founder decision 2026-09-15: both of these accounts are the founder.
FOUNDER_EMAILS = ("ahmed.fargaly98@gmail.com", "ahmedfargale@gmail.com")

# Founder decision 2026-09-15: pricing stays hidden; ArchHub is free during beta.
BETA_OFFER = {
    "availability": "free-during-beta",
    "pricing-visible": "false",
    "public-label": "Free during beta",
}
OFFER_FIELDS = tuple(BETA_OFFER)

# The cockpit's one offer command form, and the words that state a price.
_OFFER_COMMAND = re.compile(r'\s*set\s+offer\s+([a-z][a-z-]*)\s+to\s+"(.*)"\s*', re.I | re.S)
_MONEY = re.compile(
    r"[$\u20ac\u00a3\u00a5\u20b9]"
    r"|\b(?:usd|eur|gbp|aed|sar|egp|qar|kwd|bhd|omr|dollars?|euros?|pounds?|dirhams?|riyals?)\b"
    r"|\bper\s+(?:month|year|seat|user|day)\b"
    r"|/\s*(?:mo|month|yr|year|seat|user)\b",
    re.I,
)


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


def _digest_root(prefix, email):
    return prefix + hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]


def _account_root(email):
    return _digest_root(ACCOUNTS_ROOT + ":account:", email)


def _founder_member_root(email):
    return _digest_root(FOUNDERS_ROOT + ":member:", email)


def ensure_accounts(store, *, founder_email):
    """The accounts registry, and the founders standing in it as founder.

    This runs on every sign-in, so it never declares the offer.
    """
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
    if FOUNDER_ROLE not in snapshot.cells:
        create.append(_terminal(FOUNDER_ROLE, "founder"))
    if FOUNDERS_ROOT not in snapshot.cells:
        create.append(Cell(FOUNDERS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"founders"))
    if create:
        store.commit(snapshot.revision, create=tuple(create))
    recorded = _text(store.snapshot(), FOUNDER_EMAIL_ROOT)
    _append_founders(store, (recorded, *FOUNDER_EMAILS))
    upsert_account(store, founder_email)


def _relation_founders(snapshot):
    if FOUNDERS_ROOT not in snapshot.cells:
        return ()
    return tuple(
        _text(snapshot, member.participant_id)
        for member in read_relation(snapshot, FOUNDERS_ROOT, budget=100_000)
        if member.role_id == FOUNDER_ROLE
    )


def _append_founders(store, emails):
    """Append-only migration: add missing founders, never replace a member.

    An account a founder opened before being recorded as one is lifted to
    the founder tier in the same commit.
    """
    snapshot = store.snapshot()
    present = set(_relation_founders(snapshot))
    missing = [
        email for email in dict.fromkeys(_normal(value) for value in emails)
        if email not in present
    ]
    if not missing:
        return
    create, replace, pairs = [], [], []
    for email in missing:
        member = _founder_member_root(email)
        if member not in snapshot.cells:
            create.append(_terminal(member, email))
        pairs.append((FOUNDER_ROLE, member))
        held = snapshot.cells.get(_account_root(email) + ":tier")
        if held is not None and bytes(held.atom) != b"founder":
            replace.append(Cell(held.id, held.link0, held.link1, b"founder"))
    patch = prepare_append_relation_members(
        snapshot, FOUNDERS_ROOT, tuple(pairs), budget=100_000
    )
    store.commit(
        snapshot.revision,
        create=(*create, *patch.create),
        replace=(*replace, *patch.replace),
    )


def founder_email(snapshot):
    """The founder account recorded first; kept for existing callers."""
    return _text(snapshot, FOUNDER_EMAIL_ROOT)


def founder_emails(snapshot):
    """Every founder account; empty before the registry exists."""
    held = list(_relation_founders(snapshot))
    if FOUNDER_EMAIL_ROOT in snapshot.cells:
        recorded = _text(snapshot, FOUNDER_EMAIL_ROOT)
        if recorded not in held:
            # A graph from before the founders relation holds one founder only.
            held.insert(0, recorded)
    return tuple(held)


def is_founder(snapshot, email):
    try:
        return _normal(email) in founder_emails(snapshot)
    except InvalidCell:
        return False


def upsert_account(store, email):
    """Find or create the account; returns (root, email, tier)."""
    email = _normal(email)
    snapshot = store.snapshot()
    root = _account_root(email)
    if root in snapshot.cells:
        return root, email, _text(snapshot, root + ":tier")
    tier = "founder" if is_founder(snapshot, email) else "free"
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
    if is_founder(snapshot, email):
        raise InvalidCell("the founder account cannot be re-tiered")
    if tier == "founder":
        # The founders are recorded in their relation; the tier cannot be
        # handed to another account through the tier dial.
        raise InvalidCell("the founder tier is not assignable")
    root = _account_root(email)
    if root not in snapshot.cells:
        raise InvalidCell("no account for %s" % email)
    held = snapshot.cells[root + ":tier"]
    store.commit(snapshot.revision, replace=(Cell(
        held.id, held.link0, held.link1, tier.encode("utf-8")
    ),))
    return tier


def _offer_field_root(field):
    return OFFER_ROOT + ":" + field


def _offer_value(field, value):
    if field not in OFFER_FIELDS:
        raise InvalidCell("unknown offer field %r" % field)
    value = str(value)
    if field == "availability":
        if len(value) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise InvalidCell("offer availability must be a short lowercase slug")
    elif field == "pricing-visible":
        if value not in ("true", "false"):
            raise InvalidCell("offer pricing visibility must be true or false")
    else:
        value = value.strip()
        if not value or len(value) > 80 or any(ord(ch) < 32 for ch in value):
            raise InvalidCell("offer public label must be 1-80 printable characters")
        if _MONEY.search(value):
            raise InvalidCell("offer public label must not state a price; pricing is hidden")
    return value


def declare_offer(store, *, founder_account, offer=None):
    """Declare the offer once, from a founder account; an existing offer stays."""
    snapshot = store.snapshot()
    if not is_founder(snapshot, founder_account):
        raise InvalidCell("only a founder account can declare the offer")
    if OFFER_ROOT in snapshot.cells:
        return read_offer(snapshot)
    fields = dict(BETA_OFFER if offer is None else offer)
    if set(fields) != set(OFFER_FIELDS):
        raise InvalidCell("the offer needs exactly: " + ", ".join(OFFER_FIELDS))
    create = tuple(
        _terminal(_offer_field_root(field), _offer_value(field, fields[field]))
        for field in OFFER_FIELDS
    ) + (Cell(OFFER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"offer"),)
    store.commit(snapshot.revision, create=create)
    return read_offer(store.snapshot())


def read_offer(snapshot):
    """The declared offer, or None: an undeclared offer is shown as absent."""
    if OFFER_ROOT not in snapshot.cells:
        return None
    return {field: _text(snapshot, _offer_field_root(field)) for field in OFFER_FIELDS}


def set_offer_field(store, field, value, *, founder_account):
    """A founder account changes one offer field."""
    snapshot = store.snapshot()
    if not is_founder(snapshot, founder_account):
        raise InvalidCell("only a founder account can change the offer")
    if OFFER_ROOT not in snapshot.cells:
        raise InvalidCell("the offer has not been declared")
    value = _offer_value(field, value)
    held = snapshot.cells[_offer_field_root(field)]
    if bytes(held.atom) != value.encode("utf-8"):
        store.commit(snapshot.revision, replace=(Cell(
            held.id, held.link0, held.link1, value.encode("utf-8")
        ),))
    return read_offer(store.snapshot())


def published_offer(snapshot):
    """The offer in the one form every published surface reads, or None."""
    offer = read_offer(snapshot)
    if offer is None:
        return None
    canonical = json.dumps(offer, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "revision": snapshot.revision,
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "availability": offer["availability"],
        "pricing_visible": offer["pricing-visible"] == "true",
        "public_label": offer["public-label"],
    }


def parse_offer_command(utterance):
    """The (field, value) of a cockpit offer command, or None for any other words.

    Words that start like an offer command but do not follow its one form are
    refused, so a typo is never passed on to BABOOM as some other request.
    """
    if not isinstance(utterance, str) or not re.match(r"\s*set\s+offer\b", utterance, re.I):
        return None
    match = _OFFER_COMMAND.fullmatch(utterance)
    if match is None:
        raise InvalidCell('an offer command reads: set offer <field> to "<value>"')
    return match.group(1).lower(), match.group(2)


def apply_offer_command(store, utterance, *, founder_account, execute):
    """Answer a cockpit offer command from the one offer record.

    Returns None for words that are not an offer command. Otherwise the account
    must be a founder. Unconfirmed words only preview; a confirmed change is one
    new revision of the record, and an undeclared offer is declared first.
    """
    parsed = parse_offer_command(utterance)
    if parsed is None:
        return None
    field, value = parsed
    snapshot = store.snapshot()
    if not is_founder(snapshot, founder_account):
        raise InvalidCell("only a founder account can change the offer")
    value = _offer_value(field, value)
    if not execute:
        return {
            "kind": "offer-preview",
            "summary": "Confirm to set the offer %s to %s." % (field, json.dumps(value)),
            "data": {"field": field, "value": value},
        }
    if OFFER_ROOT not in snapshot.cells:
        declare_offer(store, founder_account=founder_account)
    offer = set_offer_field(store, field, value, founder_account=founder_account)
    return {
        "kind": "offer-updated",
        "summary": "The offer %s is now %s." % (field, json.dumps(offer[field])),
        "data": {"field": field, "value": offer[field]},
    }
__all__ = [
    "ACCOUNTS_ROOT", "BETA_OFFER", "FOUNDER_EMAILS", "FOUNDERS_ROOT", "OFFER_FIELDS",
    "OFFER_ROOT", "TIERS", "apply_offer_command", "declare_offer", "ensure_accounts", "founder_email",
    "founder_emails", "is_founder", "parse_offer_command", "published_offer", "read_accounts", "read_offer",
    "set_offer_field", "set_tier", "upsert_account",
]