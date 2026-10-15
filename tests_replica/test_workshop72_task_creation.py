"""PASS3 plain task uses existing admitted Work/room stores; no sockets or live agents."""
import pytest
from tests_replica.test_native_contact import owner
from nodelang import commit_intent, universal_application as app
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.universal_cell import InvalidCell
from nodelang.workshop_work_creation import create_browser_workshop_work
from nodelang.existing_workshop_conversation import send_browser_workshop


def test_plain_task_creation_reconciles_same_work_and_binds_only_same_room_messages(owner, tmp_path):
    browser = owner._resolve_browser_session(owner.browser_session_token)
    registry, store = owner.universal_registry, owner.universal_store
    room, scope = registry.workshop_root, registry.workshop_workbench_root
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="Workshop plain task"):
        from nodelang.conversation_content import prepare_empty_content_binding
        from nodelang.conversation_history import ConversationHistoryStore
        owner.conversation_content._path = tmp_path / 'task-history.sqlite3'
        adopted = prepare_empty_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=room)
        with ConversationHistoryStore(owner.conversation_content._path, instance_id=adopted.binding.instance_id) as history:
            history.ensure_conversation(room)
            history.initialize_retention()
        store.commit(adopted.expected_revision, create=adopted.create, replace=adopted.replace)
        app.set_universal_scope(store, registry, registry.map.domains["brain"], authentication_context=browser.context)
        app.set_universal_scope(store, registry, scope, authentication_context=browser.context)
        request = {"workshop_root":room, "workshop_scope":scope, "revision":store.revision,
                   "title":"Inspect selected objects", "description":"Read the current selection.",
                   "external_key":"workshop:task:123", "projection":False}
        first = create_browser_workshop_work(owner, browser, request, browser_guard=lambda:None)
        second = create_browser_workshop_work(owner, browser, {**request, "revision":store.revision}, browser_guard=lambda:None)
        assert first["created_root"] == second["created_root"]
        assert first["existing"] is False and second["existing"] is True
        message = {"root":room, "scope":scope, "category":"note", "text":"Read the current selection.",
                   "refs":[first["created_root"]], "evidence":[], "recipients":[browser.subject_root],
                   "reply_to":None, "created_at":None, "idempotency_key":"plain-task-message"}
        result = send_browser_workshop(owner, browser, message, browser_guard=lambda:None)
        repeated = send_browser_workshop(owner, browser, message, browser_guard=lambda:None)
        assert result["root"] == repeated["root"]
        with pytest.raises(AuthorizationDenied, match="exact Workshop"):
            send_browser_workshop(owner, browser, {**message, "refs":[registry.application_root]}, browser_guard=lambda:None)
        with pytest.raises(InvalidCell, match="exact recipient"):
            send_browser_workshop(owner, browser, {**message, "recipients":[]}, browser_guard=lambda:None)
        with pytest.raises(InvalidCell, match="values are invalid"):
            send_browser_workshop(owner, browser, {**message, "refs":[first["created_root"], first["created_root"]]}, browser_guard=lambda:None)
