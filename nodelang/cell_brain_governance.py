"""The brain as a governance layer: data classes, ceilings, gates and consent.

Binding design: ``ArchHub Brain Model.html`` / ``brain-model.jsx`` and
``decisions/ADGR-0003-the-brain-is-a-governance-layer.md``. The brain does not
only hold facts; it holds how each fact is classified, and the classification
decides where the fact may go.

* Three lakes, named after the shipped scopes: ``personal`` (scopes ``user`` and
  ``project``), ``firm``, ``community``.
* Four strata. Ontology, relationships and categorisation are structure and may
  travel; instances never pass the firm.
* Every data class has a ceiling: ``sealed`` (never leaves the device, no path
  exists), ``personal`` (your own devices), ``firm``, ``community``. A class
  cannot rise above its ceiling even with consent.
* Unclassified defaults to sealed, and a forgotten memory is released nowhere.
* Gates have deciders, and the decider is enforced from the graph: personal to
  firm is the owner's own call, inside a firm the owner belongs to; firm to
  community needs the firm's owner AND an appointed founder reviewer.
* The consent record is append-only Cells. A decision names the text and the
  classification it was made about, so an edit or a reclassification closes the
  gate until someone decides again. Same-clock decisions resolve to revoke.
* The key follows the ceiling, not the author.

Every call acts in a session; the owner is read from the graph, never passed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType

from . import cell_brain_ownership as ownership
from . import cell_users_seats as firms
from .cell_brain_memory import FORGOTTEN, acting_owner, entry_root, recall_by_owner
from .cell_brain_secrets import assert_no_credential_in_text, assert_not_a_secret
from .cell_brain_sync import apply_fragments, held, make_fragment
from .cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, Conflict, InvalidCell

GOVERNANCE_ROOT = "app:brain:governance"
REVIEWERS_ROOT = GOVERNANCE_ROOT + ":reviewers"
CONSENT_ROOT = "app:brain:consent"

LAKE_OF_SCOPE = MappingProxyType({"user": "personal", "project": "personal",
                                  "firm": "firm", "community": "community"})
LAKES = ("personal", "firm", "community")

SEALED, PERSONAL, FIRM, COMMUNITY = "sealed", "personal", "firm", "community"
CEILINGS = (SEALED, PERSONAL, FIRM, COMMUNITY)
_RANK = MappingProxyType({ceiling: rank for rank, ceiling in enumerate(CEILINGS)})

STRATA = MappingProxyType({
    "ontology": COMMUNITY,
    "relations": COMMUNITY,
    "category": COMMUNITY,
    "instances": FIRM,
})


@dataclass(frozen=True, slots=True)
class DataClass:
    id: str
    name: str
    ceiling: str
    leaves: str


DATA_CLASSES = MappingProxyType({c.id: c for c in (
    DataClass("client-contacts", "Client names & contacts", FIRM, "on consent"),
    DataClass("contract-values", "Contract values & invoices", FIRM, "on consent"),
    DataClass("site-locations", "Site addresses & coordinates", FIRM, "on consent"),
    DataClass("security-details", "Security details", SEALED, "no path exists"),
    DataClass("legal-correspondence", "Legal & dispute correspondence", SEALED,
              "no path exists"),
    DataClass("staff-records", "Staff salaries & team notes", PERSONAL, "no"),
    DataClass("nda-drawings", "NDA-covered drawings", FIRM, "never past firm"),
    DataClass("approvals-records", "Approvals & authority records", FIRM, "on consent"),
    DataClass("personal-files", "Your own personal files", PERSONAL,
              "your devices only"),
    DataClass("behaviour-patterns", "Behaviour patterns", COMMUNITY, "on firm opt-in"),
    DataClass("published-skills", "Published skills", COMMUNITY, "deliberate act"),
)})

# Who may decide at each gate, as a rule the graph can check.
OWNER, FIRM_OWNER, REVIEWER = "the owner", "the firm's owner", "an appointed reviewer"


@dataclass(frozen=True, slots=True)
class Gate:
    id: str
    source: str
    target: str
    decider: str
    default: str


GATES = MappingProxyType({g.id: g for g in (
    Gate("p2f", "personal", "firm", OWNER, "closed"),
    Gate("f2p", "firm", "personal", OWNER, "offered, not installed"),
    Gate("f2c", "firm", "community", FIRM_OWNER, "closed"),
    Gate("f2c-review", "firm", "community", REVIEWER, "closed"),
    Gate("c2f", "community", "firm", FIRM_OWNER, "readable"),
)})
_PATH_FROM_PERSONAL = MappingProxyType({
    PERSONAL: (), FIRM: ("p2f",), COMMUNITY: ("p2f", "f2c", "f2c-review")})

GRANT, REVOKE = "grant", "revoke"
DECISIONS = (GRANT, REVOKE)

# ── the cloud row split (ArchHub Brain Encryption Solution.html §02) ──
CLEAR_COLUMNS = (
    "id", "hlc", "scope", "visibility", "owner_user", "project_id", "firm_id",
    "kind", "confidence", "valid_from", "valid_until", "created_at", "updated_at",
)
SEALED_COLUMNS = ("text", "subject", "predicate", "object", "extra_json",
                  "provenance_json")
ADDED_CLEAR_COLUMNS = ("community_id", "key_id")

_ROLES = ("entry", "subject", "source-id", "gate", "decision", "decider", "firm",
          "basis", "reason", "clock")
_ROLE = MappingProxyType({name: "%s:role:%s" % (CONSENT_ROOT, name) for name in _ROLES})

_WRITE_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class Classification:
    data_class: str | None
    stratum: str | None
    ceiling: str


@dataclass(frozen=True, slots=True)
class Consent:
    entry_root: str
    fragment_id: str
    gate: str
    decision: str
    decider_root: str
    firm_root: str
    basis: str
    reason: str
    clock: int


@dataclass(frozen=True, slots=True)
class Release:
    allowed: bool
    reason: str


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _digest(*parts):
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _memory(snapshot, owner_root, fragment_id):
    memory = recall_by_owner(snapshot, owner_root, fragment_id)
    if memory is None:
        raise InvalidCell("the session owner holds no such memory")
    return memory


def _classification_root(memory_root):
    return "%s:classification:%s" % (GOVERNANCE_ROOT, _digest(memory_root))


# ── classification: ONE fragment, so class and stratum move together ───────

def effective_ceiling(data_class, stratum):
    """The highest lake a fact may reach. Unclassified is sealed."""
    if data_class not in DATA_CLASSES or stratum not in STRATA:
        return SEALED
    return min((DATA_CLASSES[data_class].ceiling, STRATA[stratum]),
               key=_RANK.__getitem__)


def _parse(value):
    if value is None or value.count("|") != 1:
        return None, None
    data_class, stratum = value.split("|")
    return data_class, stratum


def classify(store, *, session_root, fragment_id, data_class, stratum, origin, clock):
    """File one of the session owner's memories into a data class and stratum."""
    if data_class not in DATA_CLASSES:
        raise InvalidCell("unknown data class; unclassified stays sealed")
    if stratum not in STRATA:
        raise InvalidCell("unknown stratum")
    if isinstance(origin, str):
        assert_no_credential_in_text(origin, "classification origin")
    snapshot = store.snapshot()
    owner_root = acting_owner(snapshot, session_root)
    _memory(snapshot, owner_root, fragment_id)
    root = _classification_root(entry_root(owner_root, fragment_id))
    apply_fragments(store, (
        make_fragment(root, origin, clock, "%s|%s" % (data_class, stratum)),))
    return _classification(store.snapshot(), owner_root, fragment_id)


def _classification(snapshot, owner_root, fragment_id):
    _memory(snapshot, owner_root, fragment_id)
    found = held(snapshot, _classification_root(entry_root(owner_root, fragment_id)))
    data_class, stratum = _parse(found.value if found is not None else None)
    return Classification(data_class, stratum, effective_ceiling(data_class, stratum))


def classification(snapshot, *, session_root, fragment_id):
    return _classification(snapshot, acting_owner(snapshot, session_root), fragment_id)


def lake_key_for(ceiling):
    """Which data key seals a class. The key follows the ceiling, not the author."""
    if ceiling == COMMUNITY:
        return None
    if ceiling == FIRM:
        return FIRM
    return PERSONAL


# ── reviewers: appointed by the operator the governance root is bound to ─────

def bootstrap_governance(store, *, operator_root):
    """Bind the governance root to the platform operator, once."""
    snapshot = store.snapshot()
    if operator_root not in snapshot.cells:
        raise InvalidCell("the operator is not a root the graph holds")
    if GOVERNANCE_ROOT in snapshot.cells:
        raise InvalidCell("governance already has an operator")
    ownership.ensure_registry(store)
    snapshot = store.snapshot()
    binding = ownership.prepare_bind_owner(
        snapshot, subject_root=GOVERNANCE_ROOT, owner_root=operator_root)
    store.commit(snapshot.revision, create=(
        Cell(GOVERNANCE_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
        Cell(REVIEWERS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
        _terminal(REVIEWERS_ROOT + ":role:reviewer", "reviewer"),
    ) + binding.create, replace=binding.replace)
    return GOVERNANCE_ROOT


def appoint_reviewer(store, *, session_root, reviewer_root):
    """Only the session of the governance operator appoints a founder reviewer."""
    snapshot = store.snapshot()
    operator = acting_owner(snapshot, session_root)
    if GOVERNANCE_ROOT not in snapshot.cells:
        raise InvalidCell("governance has no operator yet")
    if ownership.read_owner(snapshot, GOVERNANCE_ROOT) != operator:
        raise InvalidCell("only the governance operator appoints reviewers")
    if reviewer_root not in snapshot.cells:
        raise InvalidCell("the reviewer is not a root the graph holds")
    if reviewer_root in reviewers(snapshot):
        return reviewer_root
    patch = prepare_append_relation_members(
        snapshot, REVIEWERS_ROOT, ((REVIEWERS_ROOT + ":role:reviewer", reviewer_root),),
        budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return reviewer_root


def reviewers(snapshot):
    if REVIEWERS_ROOT not in snapshot.cells:
        return frozenset()
    return frozenset(m.participant_id for m in read_relation(
        snapshot, REVIEWERS_ROOT, budget=10_000))


def _decider_is_legitimate(snapshot, gate, *, owner_root, decider_root, firm_root):
    """Whether this decider may decide this gate for this owner inside this firm."""
    if firm_root not in snapshot.cells:
        return False
    try:
        firm = firms.read_firm(snapshot, firm_root)
    except InvalidCell:
        return False
    if owner_root not in firm.member_roots:
        return False
    rule = GATES[gate].decider
    if rule == OWNER:
        return decider_root == owner_root
    if rule == FIRM_OWNER:
        return decider_root == firm.owner_root
    if rule == REVIEWER:
        return decider_root in reviewers(snapshot)
    return False


# ── consent record: append-only Cells, bound to what it was decided about ──

def _basis(snapshot, owner_root, fragment_id):
    """The text and the classification a decision is about, as one digest."""
    memory = _memory(snapshot, owner_root, fragment_id)
    found = _classification(snapshot, owner_root, fragment_id)
    return _digest(memory.text, str(found.data_class), str(found.stratum))


def _log_root(owner_root):
    return "%s:log:%s" % (CONSENT_ROOT, _digest(owner_root))


def _gate_root(gate):
    return "%s:gate:%s" % (CONSENT_ROOT, gate)


def _decision_root(decision):
    return "%s:decision:%s" % (CONSENT_ROOT, decision)


def _ensure_schema(store):
    snapshot = store.snapshot()
    if CONSENT_ROOT in snapshot.cells and ownership.REGISTRY_ROOT in snapshot.cells:
        return
    ownership.ensure_registry(store)
    snapshot = store.snapshot()
    if CONSENT_ROOT in snapshot.cells:
        return
    store.commit(snapshot.revision, create=(
        tuple(_terminal(role, name) for name, role in _ROLE.items())
        + tuple(_terminal(_gate_root(g), g) for g in GATES)
        + tuple(_terminal(_decision_root(d), d) for d in DECISIONS)
        + (Cell(CONSENT_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),)
    ))


def record_consent(store, *, session_root, fragment_id, gate, decision, firm_root,
                   reason, clock, memory_owner_root=None, decider_root=None):
    """Append one consent decision, made by the person the session acts for.

    The decider IS the session's owner, read from the graph; ``decider_root``
    may only repeat it. ``memory_owner_root`` names whose memory is decided
    about (default: the session's own), so a firm owner or a reviewer decides
    from their own session. Refused, with nothing written, when the decider may
    not decide this gate, or when a grant would lift the fact above its
    ceiling. Nothing already recorded is ever changed.
    """
    if gate not in GATES:
        raise InvalidCell("unknown gate")
    if decision not in DECISIONS:
        raise InvalidCell("a consent decision is grant or revoke")
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidCell("a consent decision records why")
    assert_not_a_secret(reason, "consent reason")
    assert_no_credential_in_text(reason, "consent reason")
    if not isinstance(clock, int) or isinstance(clock, bool) or clock < 0:
        raise InvalidCell("a consent clock must be a whole number")
    snapshot = store.snapshot()
    actor = acting_owner(snapshot, session_root)
    if decider_root is not None and decider_root != actor:
        raise InvalidCell("a decision is made by the session that decides, not by a name")
    decider_root = actor
    owner_root = actor if memory_owner_root is None else memory_owner_root
    if not isinstance(owner_root, str) or owner_root not in snapshot.cells:
        raise InvalidCell("the memory owner is not a root the graph holds")
    # The right to decide is checked before the memory is looked up, so a session
    # without that right learns nothing about another owner's source ids.
    if not _decider_is_legitimate(snapshot, gate, owner_root=owner_root,
                                  decider_root=decider_root, firm_root=firm_root):
        raise InvalidCell("that decider may not decide this gate")
    memory_root = entry_root(owner_root, fragment_id)
    _memory(snapshot, owner_root, fragment_id)
    if decision == GRANT:
        ceiling = _classification(snapshot, owner_root, fragment_id).ceiling
        if _RANK[ceiling] < _RANK[GATES[gate].target]:
            raise InvalidCell("consent does not lift a fact above its ceiling")
    basis = _basis(snapshot, owner_root, fragment_id)
    entry = "%s:entry:%s" % (CONSENT_ROOT, _digest(
        owner_root, fragment_id, gate, decision, decider_root, firm_root, basis,
        reason, str(clock)))
    log = _log_root(owner_root)
    conflict = None
    for _ in range(_WRITE_ATTEMPTS):
        try:
            _ensure_schema(store)
            snapshot = store.snapshot()
            if entry in snapshot.cells:
                return entry
            relation = compose_relation_cells((
                (_ROLE["subject"], memory_root),
                (_ROLE["source-id"], entry + ":source-id"),
                (_ROLE["gate"], _gate_root(gate)),
                (_ROLE["decision"], _decision_root(decision)),
                (_ROLE["decider"], decider_root),
                (_ROLE["firm"], firm_root),
                (_ROLE["basis"], entry + ":basis"),
                (_ROLE["reason"], entry + ":reason"),
                (_ROLE["clock"], entry + ":clock"),
            ), relation_id=entry)
            create = tuple(relation.cells) + (
                _terminal(entry + ":source-id", fragment_id),
                _terminal(entry + ":basis", basis),
                _terminal(entry + ":reason", reason),
                _terminal(entry + ":clock", str(clock)),
            )
            replace = ()
            if log in snapshot.cells:
                append = prepare_append_relation_members(
                    snapshot, log, ((_ROLE["entry"], entry),), budget=1_000_000)
                create += tuple(append.create)
                replace += tuple(append.replace)
            else:
                log_cells = compose_relation_cells(((_ROLE["entry"], entry),),
                                                   relation_id=log)
                binding = ownership.prepare_bind_owner(
                    snapshot, subject_root=log, owner_root=owner_root)
                registry = prepare_append_relation_members(
                    snapshot, CONSENT_ROOT, ((_ROLE["entry"], log),), budget=1_000_000)
                create += (tuple(log_cells.cells) + binding.create
                           + tuple(registry.create))
                replace += binding.replace + tuple(registry.replace)
            store.commit(snapshot.revision, create=create, replace=replace)
            return entry
        except Conflict as error:
            conflict = error
    raise conflict or Conflict("consent write kept losing to concurrent writers")


def _read_consent(snapshot, entry):
    found = {}
    for member in read_relation(snapshot, entry, budget=10_000):
        found.setdefault(member.role_id, []).append(member.participant_id)

    def one(name):
        items = found.get(_ROLE[name], ())
        if len(items) != 1:
            raise InvalidCell("a consent entry is incomplete")
        return items[0]

    def text(root):
        return bytes(snapshot.cells[root].atom).decode("utf-8")

    return Consent(
        entry,
        text(one("source-id")),
        one("gate")[len(_gate_root("")):],
        one("decision")[len(_decision_root("")):],
        one("decider"),
        one("firm"),
        text(one("basis")),
        text(one("reason")),
        int(text(one("clock"))),
    )


def _history(snapshot, owner_root, fragment_id=None):
    log = _log_root(owner_root)
    if log not in snapshot.cells:
        return ()
    if ownership.read_owner(snapshot, log) != owner_root:
        raise InvalidCell("this consent record belongs to another owner")
    entries = tuple(
        _read_consent(snapshot, member.participant_id)
        for member in read_relation(snapshot, log, budget=1_000_000)
        if member.role_id == _ROLE["entry"])
    return entries if fragment_id is None else tuple(
        e for e in entries if e.fragment_id == fragment_id)


def consent_history(snapshot, *, session_root, fragment_id=None):
    """Every consent decision the session owner recorded, in the order recorded."""
    return _history(snapshot, acting_owner(snapshot, session_root), fragment_id)


def _standing(snapshot, owner_root, fragment_id, gate, firm_root):
    """The standing decision for one gate on the CURRENT text and classification.

    Latest clock wins; at the same clock a revoke wins, then the entry digest
    decides, so every replica reaches the same answer and a tie fails closed. A
    grant about an older text or classification does not stand; a revoke stands
    whatever it was about, so editing the text back cannot revive an older
    grant over a newer revoke. A decision whose decider has since lost the right
    to decide does not stand either.
    """
    basis = _basis(snapshot, owner_root, fragment_id)
    best = None
    for consent in _history(snapshot, owner_root, fragment_id):
        if consent.gate != gate or consent.firm_root != firm_root:
            continue
        if consent.basis != basis and consent.decision == GRANT:
            continue
        if not _decider_is_legitimate(snapshot, gate, owner_root=owner_root,
                                      decider_root=consent.decider_root,
                                      firm_root=firm_root):
            continue
        key = (consent.clock, consent.decision == REVOKE, consent.entry_root)
        if best is None or key > best[0]:
            best = (key, consent.decision)
    return best[1] if best else None


def current_decision(snapshot, *, session_root, fragment_id, gate, firm_root):
    return _standing(snapshot, acting_owner(snapshot, session_root), fragment_id,
                     gate, firm_root)


def may_release(snapshot, *, session_root, fragment_id, to_lake, firm_root=None):
    """Whether one of the session owner's memories may reach a lake, and why."""
    if to_lake not in LAKES:
        raise InvalidCell("unknown lake")
    owner_root = acting_owner(snapshot, session_root)
    memory = _memory(snapshot, owner_root, fragment_id)
    if memory.state == FORGOTTEN:
        return Release(False, "a forgotten memory is released nowhere")
    found = _classification(snapshot, owner_root, fragment_id)
    if found.ceiling == SEALED:
        why = "unclassified" if found.data_class is None else "sealed class"
        return Release(False, "%s: no release path exists" % why)
    if _RANK[found.ceiling] < _RANK[to_lake]:
        return Release(False, "ceiling %s is below the %s lake" % (found.ceiling, to_lake))
    for gate in _PATH_FROM_PERSONAL[to_lake]:
        decision = _standing(snapshot, owner_root, fragment_id, gate, firm_root)
        if decision != GRANT:
            return Release(False, "gate %s is %s" % (
                gate, "revoked" if decision == REVOKE else GATES[gate].default))
    return Release(True, "within ceiling %s and consented" % found.ceiling)
