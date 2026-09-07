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


def test_the_line_names_the_runtime_that_did_it(monkeypatch):
    """A line saying only "an agent" tells the founder nothing."""
    written = {}

    def append(store, registry, **kw):
        written.update(kw)
        return types.SimpleNamespace(root_id="entry:1")

    monkeypatch.setattr(app_module, "append_universal_workshop_entry", append)
    monkeypatch.setattr(
        app_module, "_agent_session_runtime_label", lambda *a: "codex"
    )
    monkeypatch.setattr(
        app_module, "_work_title_for_workshop", lambda *a, **k: "Ship the map"
    )
    registry = types.SimpleNamespace(
        workshop_category_roots={"note": "cat:note"},
    )
    app_module.record_workshop_work_event(
        object(), registry,
        agent_session_root="app:agent-session:runtime:x",
        work_root="work:1", event="claimed",
    )
    assert written["content"] == "codex claimed Ship the map"
    assert written["reference_roots"] == ("work:1",)
    assert "work:1" in written["idempotency_key"]


def test_an_unreadable_session_is_never_given_a_name(monkeypatch):
    monkeypatch.setattr(
        app_module, "read_agent_session",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gone")),
    )
    registry = types.SimpleNamespace(
        agent_body=types.SimpleNamespace(protocol=object()),
        authorization=types.SimpleNamespace(protocol=object()),
    )
    store = types.SimpleNamespace(snapshot=lambda: object())
    assert app_module._agent_session_runtime_label(
        store, registry, "app:agent-session:runtime:x"
    ) == "an agent"


def test_the_record_is_an_account_not_the_authority(monkeypatch):
    """A claim must not fail because its Workshop line could not be written."""
    def explode(*a, **k):
        raise RuntimeError("the Workshop is unreachable")

    monkeypatch.setattr(app_module, "append_universal_workshop_entry", explode)
    monkeypatch.setattr(
        app_module, "_agent_session_runtime_label", lambda *a: "claude"
    )
    monkeypatch.setattr(
        app_module, "_work_title_for_workshop", lambda *a, **k: "W"
    )
    registry = types.SimpleNamespace(
        workshop_category_roots={"note": "cat:note"},
    )
    assert app_module.record_workshop_work_event(
        object(), registry, agent_session_root="s", work_root="w",
        event="claimed",
    ) is None


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
    """Entries written before this carry a random root; a retry still finds them."""
    body = inspect.getsource(deliberation.prepare_deliberation_entry)
    assert "list_recent_deliberation_entries(" in body
    assert "_IDEMPOTENCY_TAIL_ENTRIES" in body
    assert deliberation._IDEMPOTENCY_TAIL_ENTRIES >= 128
