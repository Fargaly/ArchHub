"""Courts for the brain's governance layer: classes, ceilings, gates, consent.

Each court names the clause of ``ArchHub Brain Model.html`` / ``brain-model.jsx``
/ ADGR-0003, or the review finding, it holds the code to. The store is the
session-bound graph memory from sprint 1; everything here is Cells.
"""
from __future__ import annotations

import itertools
import re

import pytest

from nodelang import cell_brain_governance as gov
from nodelang.cell_brain_governance import (
    ADDED_CLEAR_COLUMNS,
    CLEAR_COLUMNS,
    CONSENT_ROOT,
    DATA_CLASSES,
    GRANT,
    REVOKE,
    SEALED_COLUMNS,
    STRATA,
    appoint_reviewer,
    bootstrap_governance,
    classification,
    classify,
    consent_history,
    effective_ceiling,
    lake_key_for,
    may_release,
    record_consent,
)
from nodelang.cell_brain_memory import forget, remember
from nodelang.cell_session_state import open_session
from nodelang.cell_users_seats import accept_invite, create_firm, invite
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, Conflict, InvalidCell

FOUNDER = "app:users:founder"          # the person whose memory this is
COLLEAGUE = "app:users:colleague"
FIRM_ADMIN = "app:users:habib-admin"    # owner of the firm
OPERATOR = "app:users:platform-operator"
REVIEWER = "app:users:founder-reviewer"
FIRM = "app:firms:habib"
S_FOUNDER = "app:sessions:founder"
S_COLLEAGUE = "app:sessions:colleague"
S_OPERATOR = "app:sessions:operator"
S_ADMIN = "app:sessions:habib-admin"
S_REVIEWER = "app:sessions:founder-reviewer"
INVITE_TOKEN = "invite-" + "0123456789abcdef"

DESIGN_CEILINGS = {
    "Client names & contacts": "firm",
    "Contract values & invoices": "firm",
    "Site addresses & coordinates": "firm",
    "Security details": "sealed",
    "Legal & dispute correspondence": "sealed",
    "Staff salaries & team notes": "personal",
    "NDA-covered drawings": "firm",
    "Approvals & authority records": "firm",
    "Your own personal files": "personal",
    "Behaviour patterns": "community",
    "Published skills": "community",
}

REPLICA_FRAGMENTS_DDL = """
CREATE TABLE fragments (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, subject TEXT,
    predicate TEXT, object TEXT, scope TEXT NOT NULL DEFAULT 'user',
    visibility TEXT NOT NULL DEFAULT 'private', owner_user TEXT NOT NULL,
    project_id TEXT, firm_id TEXT, confidence TEXT NOT NULL DEFAULT 'extracted',
    provenance_json TEXT NOT NULL DEFAULT '{}', valid_from TEXT, valid_until TEXT,
    extra_json TEXT, hlc TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


def _store():
    store = CellStore()
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("utf-8"))
        for root in (FOUNDER, COLLEAGUE, FIRM_ADMIN, OPERATOR, REVIEWER)))
    for session, owner in ((S_FOUNDER, FOUNDER), (S_COLLEAGUE, COLLEAGUE),
                           (S_OPERATOR, OPERATOR), (S_ADMIN, FIRM_ADMIN),
                           (S_REVIEWER, REVIEWER)):
        open_session(store, session_root=session, owner_root=owner)
    create_firm(store, firm_root=FIRM, owner_root=FIRM_ADMIN, seats=5)
    invite(store, firm_root=FIRM, email="founder@example.com", token=INVITE_TOKEN,
           inviter_root=FIRM_ADMIN)
    accept_invite(store, firm_root=FIRM, email="founder@example.com", token=INVITE_TOKEN,
                  member_root=FOUNDER)
    bootstrap_governance(store, operator_root=OPERATOR)
    appoint_reviewer(store, session_root=S_OPERATOR, reviewer_root=REVIEWER)
    return store


def _memory(store, fragment_id="fact-client", text="Habib & Partners is the client",
            session=S_FOUNDER, clock=10):
    remember(store, session_root=session, fragment_id=fragment_id, text=text, kind="fact",
             origin="desktop", clock=clock)
    return fragment_id


def _classify(store, fragment_id, data_class, stratum="instances", clock=20,
              session=S_FOUNDER):
    return classify(store, session_root=session, fragment_id=fragment_id,
                    data_class=data_class, stratum=stratum, origin="desktop", clock=clock)


_DECIDER = {"p2f": FOUNDER, "f2c": FIRM_ADMIN, "f2c-review": REVIEWER}
_SESSION_OF = {FOUNDER: S_FOUNDER, COLLEAGUE: S_COLLEAGUE, FIRM_ADMIN: S_ADMIN,
               REVIEWER: S_REVIEWER}


def _consent(store, fragment_id, gate, decision=GRANT, clock=30, session=None,
             decider=None, reason="shared with the office for Tower A"):
    """Each decision is recorded from the decider's OWN session."""
    decider = decider or _DECIDER[gate]
    return record_consent(store, session_root=session or _SESSION_OF[decider],
                          memory_owner_root=FOUNDER, fragment_id=fragment_id,
                          gate=gate, decision=decision, firm_root=FIRM,
                          reason=reason, clock=clock)


def _release(store, fragment_id, lake, session=S_FOUNDER):
    return may_release(store.snapshot(), session_root=session, fragment_id=fragment_id,
                       to_lake=lake, firm_root=FIRM)


def _ceiling(store, fragment_id):
    return classification(store.snapshot(), session_root=S_FOUNDER,
                          fragment_id=fragment_id).ceiling


def _to_community(store, fid, clock=30):
    _consent(store, fid, "p2f", clock=clock)
    _consent(store, fid, "f2c", clock=clock + 1)
    _consent(store, fid, "f2c-review", clock=clock + 2)


# --- design clauses -----------------------------------------------------------

def test_every_design_class_carries_exactly_its_design_ceiling():
    assert {c.name: c.ceiling for c in DATA_CLASSES.values()} == DESIGN_CEILINGS


def test_the_policy_cannot_be_changed_by_an_importer():
    with pytest.raises(TypeError):
        STRATA["instances"] = "community"
    with pytest.raises(TypeError):
        DATA_CLASSES["security-details"] = None
    with pytest.raises(TypeError):
        gov.GATES["f2c"] = None


def test_an_unclassified_fact_has_no_release_path_at_all():
    store = _store()
    fid = _memory(store)
    assert _ceiling(store, fid) == "sealed"
    assert not any(_release(store, fid, lake).allowed
                   for lake in ("personal", "firm", "community"))
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        _consent(store, fid, "p2f")
    assert store.snapshot().revision == settled
    assert lake_key_for(effective_ceiling(None, None)) == "personal"


@pytest.mark.parametrize("data_class", ("security-details", "legal-correspondence"))
def test_a_sealed_class_has_no_button_that_releases_it(data_class):
    store = _store()
    fid = _memory(store)
    _classify(store, fid, data_class)
    settled = store.snapshot().revision
    for gate in ("p2f", "f2c", "f2c-review"):
        with pytest.raises(InvalidCell):
            _consent(store, fid, gate)
    assert store.snapshot().revision == settled


def test_a_class_cannot_rise_above_its_ceiling_even_with_consent():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts")
    _consent(store, fid, "p2f")
    assert _release(store, fid, "firm").allowed
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        _consent(store, fid, "f2c", clock=31)
    assert store.snapshot().revision == settled
    assert not _release(store, fid, "community").allowed


def test_an_instance_never_passes_the_firm_whatever_its_class():
    store = _store()
    fid = _memory(store, "fact-pattern", "people rename layers before importing")
    _classify(store, fid, "behaviour-patterns", stratum="instances")
    assert _ceiling(store, fid) == "firm"
    with pytest.raises(InvalidCell):
        _consent(store, fid, "f2c")
    _classify(store, fid, "behaviour-patterns", stratum="relations", clock=40)
    _to_community(store, fid, clock=41)
    assert _release(store, fid, "community").allowed


def test_leaving_the_personal_lake_needs_a_recorded_grant_and_a_revoke_closes_it():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts")
    assert _release(store, fid, "personal").allowed
    assert "closed" in _release(store, fid, "firm").reason
    _consent(store, fid, "p2f", clock=30)
    assert _release(store, fid, "firm").allowed
    _consent(store, fid, "p2f", decision=REVOKE, clock=35, reason="client asked")
    revoked = _release(store, fid, "firm")
    assert not revoked.allowed and "revoked" in revoked.reason


# --- review HIGH 3: deciders are enforced from the graph ---------------------

@pytest.mark.parametrize("gate,wrong", (
    ("p2f", COLLEAGUE), ("p2f", FIRM_ADMIN),
    ("f2c", FOUNDER), ("f2c", REVIEWER),
    ("f2c-review", FOUNDER), ("f2c-review", FIRM_ADMIN),
))
def test_only_the_gates_own_decider_may_decide_it(gate, wrong):
    store = _store()
    fid = _memory(store, "fact-pattern", "people rename layers before importing")
    _classify(store, fid, "behaviour-patterns", stratum="relations")
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        _consent(store, fid, gate, decider=wrong)
    assert store.snapshot().revision == settled


def test_the_owner_cannot_release_to_the_community_alone():
    store = _store()
    fid = _memory(store, "fact-pattern", "people rename layers before importing")
    _classify(store, fid, "behaviour-patterns", stratum="relations")
    _consent(store, fid, "p2f", clock=30)
    assert not _release(store, fid, "community").allowed
    _consent(store, fid, "f2c", clock=31)
    assert not _release(store, fid, "community").allowed, "the founder review is missing"
    _consent(store, fid, "f2c-review", clock=32)
    assert _release(store, fid, "community").allowed


def test_a_gate_is_decided_by_the_session_that_holds_the_right_not_by_a_name():
    """Review round 3: the owner's session named the firm owner and the reviewer
    as deciders and released to the community alone (probes3.py P3a)."""
    store = _store()
    fid = _memory(store, "fact-pattern", "people rename layers before importing")
    _classify(store, fid, "behaviour-patterns", stratum="relations")
    record_consent(store, session_root=S_FOUNDER, fragment_id=fid, gate="p2f",
                   decision=GRANT, decider_root=FOUNDER, firm_root=FIRM,
                   reason="mine to share", clock=30)
    settled = store.snapshot().revision
    for clock, (gate, named) in enumerate(
            (("f2c", FIRM_ADMIN), ("f2c-review", REVIEWER)), start=31):
        with pytest.raises(InvalidCell):
            record_consent(store, session_root=S_FOUNDER, fragment_id=fid, gate=gate,
                           decision=GRANT, decider_root=named, firm_root=FIRM,
                           reason="typed somebody else's root", clock=clock)
    assert store.snapshot().revision == settled
    assert not _release(store, fid, "community").allowed


def test_a_revoke_is_not_undone_by_editing_the_text_back():
    """Review round 3: grant on A, edit to B, revoke, edit back to A reopened
    the gate (probes3.py P5)."""
    store = _store()
    fid = _memory(store, "fact-pattern", "people rename layers before importing")
    _classify(store, fid, "behaviour-patterns", stratum="relations")

    def decide(decision, clock, reason):
        record_consent(store, session_root=S_FOUNDER, fragment_id=fid, gate="p2f",
                       decision=decision, decider_root=FOUNDER, firm_root=FIRM,
                       reason=reason, clock=clock)

    decide(GRANT, 30, "shared with the office")
    assert _release(store, fid, "firm").allowed
    _memory(store, fid, "Habib client contact is Ahmed", clock=40)
    decide(REVOKE, 50, "no longer shared")
    _memory(store, fid, "people rename layers before importing", clock=60)
    assert not _release(store, fid, "firm").allowed
    decide(GRANT, 70, "shared again")
    assert _release(store, fid, "firm").allowed


def test_a_classification_that_was_not_written_is_never_reported():
    """Review round 3: a classify that swallowed its failed write kept every court
    green, because the failure court discards the error itself."""
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts", clock=20)
    with pytest.raises(RuntimeError):
        _classify(_FailingStore(store, 1), fid, "security-details", clock=30)
    assert classification(store.snapshot(), session_root=S_FOUNDER,
                          fragment_id=fid).data_class == "client-contacts"


def test_a_session_without_the_right_learns_nothing_about_another_owners_ids():
    """Review round 3: the decider is checked before the memory is looked up, so
    naming another owner's memory is refused the same way whether it exists."""
    store = _store()
    fid = _memory(store, "fact-pattern", "people rename layers before importing")
    _classify(store, fid, "behaviour-patterns", stratum="relations")
    settled = store.snapshot().revision
    refusals = set()
    for probe in (fid, "fact-never-remembered"):
        with pytest.raises(InvalidCell) as refused:
            record_consent(store, session_root=S_COLLEAGUE, memory_owner_root=FOUNDER,
                           fragment_id=probe, gate="f2c", decision=GRANT, firm_root=FIRM,
                           reason="probing", clock=40)
        refusals.add(str(refused.value))
    assert len(refusals) == 1
    assert store.snapshot().revision == settled


def test_a_member_outside_the_firm_has_no_firm_gate():
    store = _store()
    fid = _memory(store, session=S_COLLEAGUE)
    _classify(store, fid, "client-contacts", session=S_COLLEAGUE)
    with pytest.raises(InvalidCell):
        record_consent(store, session_root=S_COLLEAGUE, fragment_id=fid, gate="p2f",
                       decision=GRANT, decider_root=COLLEAGUE, firm_root=FIRM,
                       reason="not a member", clock=30)


def test_only_the_governance_operator_appoints_reviewers():
    store = _store()
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        appoint_reviewer(store, session_root=S_FOUNDER, reviewer_root=FOUNDER)
    assert store.snapshot().revision == settled
    with pytest.raises(InvalidCell):
        bootstrap_governance(store, operator_root=FOUNDER)


# --- review HIGH 4: classify lands class and stratum together ----------------

class _FailingStore:
    def __init__(self, inner, fail_at):
        self.inner, self.fail_at, self.commits = inner, fail_at, 0

    def snapshot(self):
        return self.inner.snapshot()

    @property
    def revision(self):
        return self.inner.revision

    def commit(self, *args, **kwargs):
        self.commits += 1
        if self.commits == self.fail_at:
            raise RuntimeError("injected")
        return self.inner.commit(*args, **kwargs)


def test_a_failed_reclassification_leaves_the_old_or_the_new_ceiling_never_more():
    def prepared():
        store = _store()
        fid = _memory(store, "fact-pattern", "people rename layers before importing")
        _classify(store, fid, "published-skills", stratum="ontology", clock=20)
        _to_community(store, fid, clock=21)
        _classify(store, fid, "security-details", stratum="ontology", clock=30)
        return store, fid

    store, fid = prepared()
    counter = _FailingStore(store, 10 ** 9)
    _classify(counter, fid, "published-skills", stratum="instances", clock=40)
    for fail_at in range(1, counter.commits + 1):
        store, fid = prepared()
        try:
            _classify(_FailingStore(store, fail_at), fid, "published-skills",
                      stratum="instances", clock=40)
        except RuntimeError:
            pass
        assert _ceiling(store, fid) in ("sealed", "firm")
        assert not _release(store, fid, "community").allowed


def test_a_reclassification_follows_the_sync_law():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts", clock=20)
    _classify(store, fid, "security-details", clock=15)
    assert classification(store.snapshot(), session_root=S_FOUNDER,
                          fragment_id=fid).data_class == "client-contacts"
    _classify(store, fid, "security-details", clock=25)
    settled = store.snapshot().revision
    _classify(store, fid, "security-details", clock=25)
    assert store.snapshot().revision == settled
    assert _ceiling(store, fid) == "sealed"


# --- review MEDIUM: consent stands only for what it was decided about --------

def test_an_edit_or_a_reclassification_after_a_grant_closes_the_gate():
    store = _store()
    fid = _memory(store, "fact-pattern", "people rename layers before importing")
    _classify(store, fid, "behaviour-patterns", stratum="relations")
    _to_community(store, fid)
    assert _release(store, fid, "community").allowed
    _memory(store, fid, "Habib client contact Ahmed mobile 0501234567", clock=50)
    assert not _release(store, fid, "community").allowed
    assert not _release(store, fid, "firm").allowed

    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts", clock=20)
    _consent(store, fid, "p2f", clock=30)
    _classify(store, fid, "contract-values", clock=40)
    assert not _release(store, fid, "firm").allowed


def test_same_clock_decisions_resolve_the_same_closed_way_in_every_order():
    outcomes = set()
    for order in itertools.permutations((GRANT, REVOKE, GRANT)):
        store = _store()
        fid = _memory(store)
        _classify(store, fid, "client-contacts")
        for index, decision in enumerate(order):
            _consent(store, fid, "p2f", decision=decision, clock=30,
                     reason="decision %d" % index)
        outcomes.add(_release(store, fid, "firm").allowed)
    assert outcomes == {False}


def test_a_forgotten_memory_is_released_nowhere():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts")
    _consent(store, fid, "p2f")
    forget(store, session_root=S_FOUNDER, fragment_id=fid, origin="desktop", clock=60)
    assert not _release(store, fid, "firm").allowed
    assert not _release(store, fid, "personal").allowed


# --- the record itself --------------------------------------------------------

def test_the_consent_record_is_append_only():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts")
    first = _consent(store, fid, "p2f", clock=30)
    snapshot = store.snapshot()
    first_cells = {i: c for i, c in snapshot.cells.items() if i.startswith(first)}
    _consent(store, fid, "p2f", decision=REVOKE, clock=35, reason="client asked")
    _consent(store, fid, "p2f", clock=50, reason="client agreed in writing")
    after = store.snapshot()
    assert {i: after.cells[i] for i in first_cells} == first_cells
    history = consent_history(after, session_root=S_FOUNDER, fragment_id=fid)
    assert [(c.decision, c.clock, c.reason) for c in history] == [
        (GRANT, 30, "shared with the office for Tower A"),
        (REVOKE, 35, "client asked"),
        (GRANT, 50, "client agreed in writing"),
    ]
    assert all(c.gate == "p2f" and c.decider_root == FOUNDER and c.firm_root == FIRM
               for c in history)


def test_recording_the_same_decision_again_changes_nothing():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts")
    _consent(store, fid, "p2f")
    settled = store.snapshot().revision
    _consent(store, fid, "p2f")
    assert store.snapshot().revision == settled
    assert len(consent_history(store.snapshot(), session_root=S_FOUNDER)) == 1


def test_consent_is_held_as_cells_in_the_graph():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts")
    entry = _consent(store, fid, "p2f")
    assert entry.startswith(CONSENT_ROOT + ":entry:") and entry in store.snapshot().cells


def test_another_session_cannot_classify_consent_or_read_the_record():
    store = _store()
    fid = _memory(store)
    _classify(store, fid, "client-contacts")
    _consent(store, fid, "p2f")
    settled = store.snapshot().revision
    with pytest.raises(InvalidCell):
        _classify(store, fid, "published-skills", stratum="ontology", clock=90,
                  session=S_COLLEAGUE)
    with pytest.raises(InvalidCell):
        _consent(store, fid, "p2f", clock=91, session=S_COLLEAGUE, decider=COLLEAGUE)
    assert store.snapshot().revision == settled
    assert consent_history(store.snapshot(), session_root=S_COLLEAGUE) == ()
    with pytest.raises(InvalidCell):
        _release(store, fid, "firm", session=S_COLLEAGUE)


def test_refusals_do_not_echo_what_was_refused():
    store = _store()
    fid = _memory(store)
    token = "gh" + "p_" + "0123456789abcdefABCDEF0123456789abcd"
    with pytest.raises(InvalidCell) as refused:
        _classify(store, fid, token)
    assert token not in str(refused.value)
    _classify(store, fid, "client-contacts")
    with pytest.raises(InvalidCell) as refused:
        _consent(store, fid, "p2f", reason="ok, the token is " + token)
    assert token not in str(refused.value)


@pytest.mark.parametrize("ceiling,key", (
    ("sealed", "personal"), ("personal", "personal"), ("firm", "firm"), ("community", None),
))
def test_the_key_follows_the_ceiling_not_the_author(ceiling, key):
    assert lake_key_for(ceiling) == key


def test_every_live_replica_column_is_either_clear_or_sealed():
    columns = re.findall(r"^\s*(\w+) TEXT", REPLICA_FRAGMENTS_DDL.replace(", ", ",\n"),
                         flags=re.M)
    assert len(columns) == 19
    assert set(CLEAR_COLUMNS) | set(SEALED_COLUMNS) == set(columns)
    assert not set(CLEAR_COLUMNS) & set(SEALED_COLUMNS)
    assert (len(CLEAR_COLUMNS), len(SEALED_COLUMNS), len(ADDED_CLEAR_COLUMNS)) == (13, 6, 2)
