"""Every agent's Work lands in the Workshop, and landing it is cheap.

The founder asked whether the Workshop is working, mandatory, and the place
all his agents work one project together. It was written from exactly ONE
place -- him typing into it -- so nothing an agent did ever appeared there.
And appending read every entry, which cost 4.253s on his 16,919-entry
Workshop, so putting agent traffic through it would have made the app crawl
(2026-09-07).

These courts hold both halves, and the limit that keeps the first honest:
the record is an account, never the authority -- a Work claim must not fail
because its Workshop line could not be written.
"""
from __future__ import annotations

import inspect
import types

import pytest

from nodelang import cell_deliberation as deliberation
from nodelang import universal_application as app_module


def test_every_work_event_is_said_in_the_workshop():
    body = inspect.getsource(app_module.transition_universal_governed_work)
    assert "record_workshop_work_event(" in body, (
        "a transition nobody can see is not coordination"
    )
    said = app_module._WORK_EVENT_SAID
    assert said == {
        "claim": "claimed", "release": "released", "block": "blocked",
        "resume": "resumed", "submit": "submitted",
    }
    # Exactly the events the transition admits, so none is left unsaid.
    assert "{'claim', 'release', 'block', 'resume', 'submit'}" in body or (
        set(said) == {"claim", "release", "block", "resume", "submit"}
    )


def _committed_claim(monkeypatch, append):
    """One committed claim receipt, seen through the recorder's own reads."""
    from nodelang import cell_state_machine, conversation_content
    receipt = types.SimpleNamespace(
        actor_root="session:1", context_roots=("work:1",), event_root="event:claim",
        from_state_root="state:open", to_state_root="state:claimed", timestamp_root="at",
    )
    monkeypatch.setattr(cell_state_machine, "_read_transition_event",
                        lambda snapshot, protocol, root: receipt if root == "history:1" else None)
    monkeypatch.setattr(app_module, "_require_workshop_message_source", lambda *a: None)
    monkeypatch.setattr(app_module, "_require_application_authorization", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "read_instance_state_machine",
                        lambda *a: types.SimpleNamespace(transition_roots=("transition:1",)))
    monkeypatch.setattr(app_module, "read_transition", lambda *a: types.SimpleNamespace(
        event_root="event:claim", from_state_root="state:open", to_state_root="state:claimed"))
    monkeypatch.setattr(app_module, "_text",
                        lambda snapshot, root: {"event:claim": "claim", "at": "0"}[root])
    monkeypatch.setattr(app_module, "append_universal_workshop_entry", append)
    monkeypatch.setattr(conversation_content, "workshop_message_identity",
                        lambda entry: {"root": entry.root_id})
    revoked = []
    registry = types.SimpleNamespace(
        standard_library=types.SimpleNamespace(state_machine_protocol=object()),
        assembly_protocol=object(),
        workshop_category_roots={"note": "category:note"},
        authorization=types.SimpleNamespace(broker=types.SimpleNamespace(
            resolve=lambda context: types.SimpleNamespace(tenant_root="t", assurance_root="a"),
            mint_authenticated_context=lambda *a, **k: "context:actor",
            revoke=revoked.append,
        )),
    )
    said = app_module.record_workshop_work_event(
        types.SimpleNamespace(snapshot=lambda: types.SimpleNamespace(revision=7)), registry,
        agent_session_root="session:1", work_root="work:1", history_root="history:1",
        authentication_context="context:caller",
    )
    return said, revoked


def test_the_line_names_the_work_by_reference_not_a_mutable_title(monkeypatch):
    """A retry must write the same line, so the line holds references only.

    Each authorized view resolves the actor and Work labels itself; a title
    that changes between a claim and its retry would split one event in two.
    """
    written = {}

    def append(store, registry, **kw):
        written.update(kw)
        return types.SimpleNamespace(root_id="entry:1")

    said, revoked = _committed_claim(monkeypatch, append)
    assert said == "entry:1"
    assert written["content"] == "Claimed Work work:1."
    assert written["actor_root"] == "session:1"
    assert written["reference_roots"] == ("work:1", "history:1")
    assert written["idempotency_key"] == "work-event:history:1"
    assert written["created_at"] == "1970-01-01T00:00:00Z"
    assert written["authentication_context"] == "context:actor"
    assert written["source_authentication_context"] == "context:caller"
    assert written["expected_revision"] == 7
    assert revoked == ["context:actor"], "the minted actor context never outlives the line"


def test_the_record_is_an_account_not_the_authority(monkeypatch):
    """A claim must not fail because its Workshop line could not be written."""
    def explode(*a, **k):
        raise RuntimeError("the Workshop is unreachable")

    said, revoked = _committed_claim(monkeypatch, explode)
    assert said is None
    assert revoked == ["context:actor"]


def test_appending_no_longer_reads_the_whole_workshop():
    """One entry cost 4.253s because it read all 16,919 of them."""
    body = inspect.getsource(deliberation.prepare_deliberation_entry)
    assert "list_deliberation_entries(" not in body, (
        "an append must not read the whole space"
    )
    assert "_derived_entry_root(" in body
    assert "len(space.entry_roots) + 1" in body, (
        "the next sequence comes from the count, not from reading entries"
    )


def test_an_idempotency_key_names_its_own_entry():
    """A retry is then one point read, not a scan."""
    first = deliberation._derived_entry_root("app:workshop", "key-a")
    again = deliberation._derived_entry_root("app:workshop", "key-a")
    other = deliberation._derived_entry_root("app:workshop", "key-b")
    elsewhere = deliberation._derived_entry_root("app:other", "key-a")
    assert first == again, "the same key must name the same entry"
    assert first != other and first != elsewhere
    assert first.startswith("app:workshop:entry:")


def test_a_legacy_entry_is_still_matched_by_its_key():
    """Entries written before this carry a random root; a retry still finds them.

    The lookup reads each entry's own key, not its root, and reads every
    entry, not a tail -- with and without the per-store index.
    """
    from tests_replica.test_cell_deliberation import _append, _system
    store, protocol, authorization, identities, context, _space = _system()
    first = _append(store, protocol, authorization, identities, context,
                    idempotency_key="old:first")
    for index in range(3):
        _append(store, protocol, authorization, identities, context,
                idempotency_key="later:%d" % index)
    snapshot = store.snapshot()
    space = deliberation.read_deliberation_space(snapshot, protocol, "test:workshop")
    for lookup_store in (None, store, store):
        assert deliberation._lookup_deliberation_key(
            snapshot, protocol, space, "old:first", lookup_store) == first.root_id
        assert deliberation._lookup_deliberation_key(
            snapshot, protocol, space, "never:written", lookup_store) is None
    # The one fact no behaviour shows: prepare asks this lookup.
    assert "_lookup_deliberation_key(" in inspect.getsource(deliberation.prepare_deliberation_entry)


def test_a_claim_and_a_release_are_not_the_two_events_he_cannot_see():
    """An evidence-free transition returns early -- and that is every claim.

    transition_universal_governed_work has two exits. The evidence-free
    branch, which carries every CLAIM and every RELEASE, returned before it
    ever reached the Workshop record, so the two events that say who picked
    a piece of work up and who put it down were the exact two the founder
    could not see (audit, 2026-09-07).
    """
    body = inspect.getsource(app_module.transition_universal_governed_work)
    early = body.index("if not transition.required_evidence_type_roots:")
    tail = body.index("if additional_create:")
    branch = body[early:tail]
    assert "record_workshop_work_event(" in branch, (
        "the evidence-free branch must say it in the Workshop before it returns"
    )
    said = branch.index("record_workshop_work_event(")
    returned = branch.index("return history_root, revision")
    assert said < returned, "recorded before the return, not after it"
    assert body.count("record_workshop_work_event(") == 2, (
        "both exits of the transition must reach the Workshop"
    )


def test_a_claim_that_cannot_be_said_in_the_workshop_is_not_a_claim():
    """The Workshop is the room, not a log nobody must write to.

    The founder asked for months whether the Workshop is working and
    MANDATORY. The one enforcement site armed only when the Work already
    carried a Workshop assignment, so work created without one bypassed the
    room entirely (audit, 2026-09-07).
    """
    body = inspect.getsource(app_module.transition_universal_governed_work)
    early = body.index("if not transition.required_evidence_type_roots:")
    branch = body[early:body.index("if additional_create:")]
    assert 'if event == "claim" and said is None:' in branch
    assert "AuthorizationDenied(" in branch
    assert "claimed in the Workshop or not at all" in branch


def test_letting_go_of_work_is_never_gated():
    """A silent room must not trap work inside an agent."""
    body = inspect.getsource(app_module.transition_universal_governed_work)
    early = body.index("if not transition.required_evidence_type_roots:")
    branch = body[early:body.index("if additional_create:")]
    gate = branch.index('if event == "claim" and said is None:')
    condition = branch[gate:gate + 200]
    for freed in ("release", "block", "resume", "submit"):
        assert freed not in condition, (
            "%s must stay possible whatever the Workshop does" % freed
        )
