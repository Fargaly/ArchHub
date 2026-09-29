"""New Work, contacts and agent sessions land in their homes, never on the user's canvas.

Canvas-clean patch B (2026-09-29). Before it, every route created a Work without a point at
(0, 0) (29 Work cards shared one point), a contact was drawn on the top canvas at (240, 200),
and every runtime agent session was drawn on the top canvas at (1080, 180) with a projection
grant. The canvas-content migration moves what an older graph holds; without these the canvas
filled up again on the next Work, contact or agent launch.
"""
from __future__ import annotations

import itertools

from nodelang import native_contact as contact
from nodelang.canvas_placement import intersects
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    _canvas_roots,
    begin_universal_runtime_agent_session,
    build_universal_application,
    create_universal_governed_work,
    project_universal_canvas,
    read_relation,
)
import pytest

from nodelang import application_server as server_module
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance


@pytest.fixture
def owner(tmp_path, monkeypatch):
    original = server_module.QuietThreadingHTTPServer
    monkeypatch.setattr(server_module, "QuietThreadingHTTPServer",
                        lambda address, handler: original(address, handler, bind_and_activate=False))
    server = server_module.ApplicationServer(
        universal_workspace_root=tmp_path, runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False)
    try:
        yield server
    finally:
        server.close()


class Transport:
    """A discovered external session; no message is ever sent."""
    endpoint = {"app": "claude", "id": "existing-external", "title": "Existing Claude", "cwd": "fixture", "pid": 123}

    def discover(self, timeout_seconds=3, **kwargs):
        return {"status": "ok", "recipients": [self.endpoint]}

    def request(self, recipient, text, **kwargs):
        raise AssertionError("binding a contact sends nothing")

    def cancel_pending(self, **kwargs):
        return {"local_call_joined": True, "worker_stopped": True}

    def close(self):
        pass


def _members(snapshot, registry, scope):
    return {member.participant_id for member in read_relation(snapshot, scope, budget=300_000)
            if member.role_id == registry.roles["member"]}


def test_work_created_without_a_point_takes_a_free_slot_beside_the_other_work():
    store, registry = build_universal_application(resolve_map_path())
    try:
        context = registry.authorization.session.context()
        roots = [
            create_universal_governed_work(
                store, registry, title="Court Work %d" % index,
                external_key="court:free-slot-%d" % index, authentication_context=context,
            )[0]
            for index in range(3)
        ]
        from nodelang.universal_pipeline import scope_card_bounds
        bounds = scope_card_bounds(store.snapshot(), registry, registry.governed_work_registry_root)
        rects = [bounds[root] for root in roots]
        assert all(rect[:2] != (0.0, 0.0) for rect in rects), rects
        assert not [pair for pair in itertools.combinations(rects, 2) if intersects(*pair)], rects
    finally:
        store.close()


def test_a_new_contact_is_drawn_in_the_workbench_not_on_the_canvas(owner, tmp_path):
    from nodelang.conversation_content import prepare_empty_content_binding
    from nodelang.conversation_history import ConversationHistoryStore
    owner.native_recipient_relay._transport = Transport()
    browser = owner._resolve_browser_session(owner.browser_session_token)
    registry = owner.universal_registry
    owner.conversation_content._path = tmp_path / "contact-history.sqlite3"
    adopted = prepare_empty_content_binding(
        owner.universal_store.snapshot(), registry.deliberation_protocol,
        application_root=registry.application_root, space_root=registry.workshop_root)
    with ConversationHistoryStore(owner.conversation_content._path,
                                  instance_id=adopted.binding.instance_id) as history:
        history.ensure_conversation(registry.workshop_root)
        history.initialize_retention()
    owner.universal_store.commit(adopted.expected_revision, create=adopted.create, replace=adopted.replace)
    bound = contact.bind_native_contact(owner, browser, {
        "root": registry.workshop_root, "scope": registry.workshop_workbench_root, "node": None,
        "app": "claude", "session_id": Transport.endpoint["id"],
        "revision": owner.universal_store.revision,
    }, browser_guard=lambda: None)
    snapshot = owner.universal_store.snapshot()
    assert bound["contact"] not in set(_canvas_roots(snapshot, registry)[0])
    assert bound["contact"] in _members(snapshot, registry, registry.workshop_workbench_root)


def test_a_new_agent_session_is_not_drawn_on_the_users_canvas():
    store, registry = build_universal_application(resolve_map_path())
    try:
        session_root = "app:agent-session:runtime:court-not-on-the-canvas"
        begin_universal_runtime_agent_session(
            store, registry, session_root=session_root, runtime="baboom-execution",
            external_session_fingerprint="b" * 64,
            catalog_entry_root="app:agent-body-catalog:entry:baboom-execution",
            authentication_context=registry.authorization.session.context(),
        )
        snapshot = store.snapshot()
        assert session_root not in set(_canvas_roots(snapshot, registry)[0])
        assert session_root in _members(snapshot, registry, registry.application_root)
        project_universal_canvas(store, registry)  # opens: no grant names a row that is not drawn
    finally:
        store.close()