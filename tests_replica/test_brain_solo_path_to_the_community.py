"""Court: the solo path to the community, and real firms keep the founder review.

ADGR-0004 as corrected in review: a solo account (a member of no firm) decides
p2f and f2c itself, and the cloud's founder review decides what members pull.
Every real firm keeps p2f + f2c + f2c-review. The solo firm is derived, never
registered, and its decisions stop standing the moment the owner joins a firm.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from nodelang import app_brain
from nodelang import cell_users_seats as firms
from nodelang.brain_store_port import FOUNDER_OWNER_ROOT
from nodelang.cell_brain_governance import (
    GRANT, bootstrap_governance, may_release, record_consent, solo_firm_root, appoint_reviewer,
)
from nodelang.cell_catalog import bootstrap_assembly_protocol
from nodelang.cell_protocols import prepare_append_relation_members
from nodelang.cell_session_state import open_session
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore

OTHER = "app:court:other-owner"
REVIEWER = "app:court:reviewer"


@pytest.fixture
def brain():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    store.commit(store.snapshot().revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"owner") for root in (FOUNDER_OWNER_ROOT, OTHER, REVIEWER)))
    app_brain.bind(store, SimpleNamespace(
        authorization=SimpleNamespace(subject_root=FOUNDER_OWNER_ROOT), assembly_protocol=protocol))
    app_brain.write([{"op": "add", "fragment": {"id": "f-skill", "kind": "practice",
                                                "text": "Dimension stairs riser-first"}}])
    yield store
    app_brain.unbind(store)


def _release(store, firm_root):
    return may_release(store.snapshot(), session_root=app_brain.SESSION_ROOT, fragment_id="f-skill",
                       to_lake="community", firm_root=firm_root)


def _join(store, firm_root, member):
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, firm_root, ((firms.MEMBER_ROLE, member),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)


def test_a_solo_account_publishes_to_the_community(brain):
    assert app_brain.publish("f-skill")["published"] is True
    assert _release(brain, solo_firm_root(FOUNDER_OWNER_ROOT)).allowed


def test_the_solo_firm_is_never_a_registered_firm(brain):
    app_brain.publish("f-skill")
    snapshot = brain.snapshot()
    assert firms.FIRMS_ROOT not in snapshot.cells or not any(
        m.participant_id == solo_firm_root(FOUNDER_OWNER_ROOT)
        for m in __import__("nodelang.cell_protocols", fromlist=["x"]).read_relation(
            snapshot, firms.FIRMS_ROOT, budget=10_000))


def test_joining_a_firm_closes_the_solo_grants_without_a_write(brain):
    app_brain.publish("f-skill")
    firms.create_firm(brain, firm_root="app:court:firm", owner_root=OTHER, seats=2)
    _join(brain, "app:court:firm", FOUNDER_OWNER_ROOT)
    assert not _release(brain, solo_firm_root(FOUNDER_OWNER_ROOT)).allowed


def test_a_firm_member_waits_for_the_firm_owner_and_the_review(brain):
    firms.create_firm(brain, firm_root="app:court:firm", owner_root=OTHER, seats=2)
    _join(brain, "app:court:firm", FOUNDER_OWNER_ROOT)
    said = app_brain.publish("f-skill")
    assert said["ok"] is True and said["published"] is False and "f2c" in said["waiting"], said


def test_a_firm_owner_still_needs_the_founder_review(brain):
    firms.create_firm(brain, firm_root="app:court:firm", owner_root=FOUNDER_OWNER_ROOT, seats=2)
    said = app_brain.publish("f-skill")
    assert said["published"] is False and "f2c-review" in said["waiting"], said
    bootstrap_governance(brain, operator_root=FOUNDER_OWNER_ROOT)
    appoint_reviewer(brain, session_root=app_brain.SESSION_ROOT, reviewer_root=REVIEWER)
    open_session(brain, session_root="app:court:reviewer-session", owner_root=REVIEWER)
    record_consent(brain, session_root="app:court:reviewer-session", memory_owner_root=FOUNDER_OWNER_ROOT,
                   fragment_id="f-skill", gate="f2c-review", decision=GRANT, firm_root="app:court:firm",
                   reason="reviewed", clock=10 ** 13)
    assert _release(brain, "app:court:firm").allowed


def test_nobody_else_can_decide_for_the_solo_firm(brain):
    brain_owner_session = app_brain.SESSION_ROOT
    open_session(brain, session_root="app:court:other-session", owner_root=OTHER)
    with pytest.raises(Exception):
        record_consent(brain, session_root="app:court:other-session", memory_owner_root=FOUNDER_OWNER_ROOT,
                       fragment_id="f-skill", gate="f2c", decision=GRANT,
                       firm_root=solo_firm_root(FOUNDER_OWNER_ROOT), reason="not mine", clock=10 ** 13)
    assert brain_owner_session