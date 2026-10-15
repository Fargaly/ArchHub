"""Real governed account layout writer; no running app, hosts or provider calls."""
from dataclasses import replace

import pytest

from nodelang import commit_intent
from nodelang import universal_application as app
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.universal_cell import Cell, InvalidCell
from nodelang.workshop_presentation import perform_presentation_action, presentation_root, read_layout
from test_workshop_conversation_reach import owner  # noqa: F401


def action(owner, layout=None, binding=None, guard=lambda: None, **overrides):
    binding = binding or owner._resolve_browser_session(owner.browser_session_token)
    registry, store = owner.universal_registry, owner.universal_store
    body = dict(action='presentation-read' if layout is None else 'presentation-layout',
        root=registry.workshop_root, scope=registry.canvas_root, revision=store.revision)
    if layout is not None:
        body['layout'] = layout
    body.update(overrides)
    with commit_intent.declare(commit_intent.USER_ACTION,actor=binding.subject_root,reason='Choose Workshop layout'):
        return perform_presentation_action(owner,binding,body,browser_guard=guard)


def test_layout_uses_real_account_store_and_tracked_writer(owner):
    registry, store = owner.universal_registry, owner.universal_store
    browser = owner._resolve_browser_session(owner.browser_session_token)
    initial = store.revision
    assert action(owner)['layout'] == 1
    assert store.revision == initial  # first open has no semantic writes
    saved = action(owner,4)
    assert saved['layout'] == 4 and saved['revision'] > initial
    view = registry.view_sessions[browser.subject_root]
    read = lambda snapshot: read_layout(snapshot,registry.application_root,browser.subject_root,view.settings_root,registry.roles['member'])
    assert read(store.snapshot()) == 4
    # A fresh browser view reads the same account preference. The key contains
    # neither the view/session root nor a device label.
    fresh_token, _ = owner.issue_browser_session(browser.context)
    fresh_browser = owner._resolve_browser_session(fresh_token)
    assert action(owner,binding=fresh_browser)['layout'] == 4
    revision = store.revision
    assert action(owner,4)['revision'] == revision
    assert action(owner,2)['layout'] == 2
    assert action(owner,1)['layout'] == 1
    assert read_layout(store.snapshot(),registry.application_root,'other-account',view.settings_root,registry.roles['member']) == 1
    assert read_layout(store.snapshot(),'other-application',browser.subject_root,view.settings_root,registry.roles['member']) == 1


def test_layout_first_save_and_later_edits_use_existing_undo_redo(owner):
    registry, store = owner.universal_registry, owner.universal_store
    browser = owner._resolve_browser_session(owner.browser_session_token)
    action(owner,4)
    with commit_intent.declare(commit_intent.USER_ACTION,actor=browser.subject_root,reason='Undo Workshop layout'):
        app.undo_universal_change(store,registry,authentication_context=browser.context)
    assert action(owner)['layout'] == 1
    with commit_intent.declare(commit_intent.USER_ACTION,actor=browser.subject_root,reason='Redo Workshop layout'):
        app.redo_universal_change(store,registry,authentication_context=browser.context)
    assert action(owner)['layout'] == 4
    action(owner,2)
    with commit_intent.declare(commit_intent.USER_ACTION,actor=browser.subject_root,reason='Undo Workshop layout edit'):
        app.undo_universal_change(store,registry,authentication_context=browser.context)
    assert action(owner)['layout'] == 4


@pytest.mark.parametrize('layout',[0,3,5,True,'2',None])
def test_invalid_layout_never_writes(owner,layout):
    before = owner.universal_store.revision
    with pytest.raises(InvalidCell):
        action(owner,action='presentation-layout',layout=layout)
    assert owner.universal_store.revision == before


def test_stale_scope_revision_and_browser_refuse_before_write(owner):
    before = owner.universal_store.revision
    for overrides in ({'scope':'foreign-scope'},{'root':'foreign-room'},{'revision':before-1}):
        with pytest.raises((InvalidCell,AuthorizationDenied)):
            action(owner,2,**overrides)
        assert owner.universal_store.revision == before
    def expired():
        raise AuthorizationDenied('Browser changed')
    with pytest.raises(AuthorizationDenied,match='Browser changed'):
        action(owner,2,guard=expired)
    assert owner.universal_store.revision == before


def test_foreign_account_cell_cannot_be_read_as_own_preference(owner):
    registry, store = owner.universal_registry, owner.universal_store
    browser = owner._resolve_browser_session(owner.browser_session_token)
    root = presentation_root(registry.application_root,browser.subject_root)
    snapshot = store.snapshot()
    # An invalid binding must fail closed, even when a caller knows its id.
    cells = dict(snapshot.cells)
    cells[root] = Cell(root,registry.application_root,registry.application_root,b'{"version":1,"layout":4}')
    with pytest.raises(InvalidCell,match='foreign or invalid'):
        read_layout(replace(snapshot,cells=cells),registry.application_root,browser.subject_root,
            registry.view_sessions[browser.subject_root].settings_root,registry.roles['member'])
