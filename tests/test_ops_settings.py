"""Remaining Settings commands exercise their owners, never a source-text gate."""
import pytest

from nodelang.settings_owner import SettingsOwner
from nodelang.universal_cell import CellStore
from tests.test_wire_settings_owner import Cloud


def owner(store=None):
    return SettingsOwner(store or CellStore(), cloud=Cloud(), dependencies=object(),
                         workspace_roots=lambda: [{'id': 'root', 'canvas': 'graph', 'privacy': 'private'}])


def test_workspace_policy_scope_and_graph_membership_persist_and_validate():
    current = owner()
    assert current.dispatch('setWorkspaceRules', ['root', {'privacy': 'Secret', 'rules': 'Keep drawings private', 'shareLearning': False}])['workspacePolicies']['root']['privacy'] == 'Secret'
    assert current.dispatch('setSettingsScope', ['Workspace', 'root'])['settingsScope'] == 'Workspace'
    assert current.dispatch('setGraphWorkspaces', ['graph', ['root']])['workspaceIds'] == ['root']
    restored = owner(current.store)
    assert restored.readOperations('graph')['workspaceIds'] == ['root']
    assert restored.readOperations('graph')['workspacePolicies']['root']['rules'] == 'Keep drawings private'
    revision = current.store.revision
    for args in [['missing', {'rules': 'x'}], ['root', {'privacy': 'Public'}], ['root', {'shareLearning': 'yes'}]]:
        with pytest.raises(ValueError):
            current.dispatch('setWorkspaceRules', args)
    assert current.store.revision == revision
    with pytest.raises(ValueError, match='workspace'):
        current.setSettingsScope('Workspace', '')


def test_scope_and_device_refusals_do_not_publish_or_write():
    current = owner()
    with pytest.raises(ValueError, match='device'):
        current.selectDevice('missing')
    with pytest.raises(ValueError, match='recovery'):
        current.backUpNow()
    with pytest.raises(ValueError, match='backup'):
        current.rollBack('../outside')
    with pytest.raises(ValueError, match='Permission Request'):
        current.grantAccess('missing')


def test_policy_is_account_scoped_and_user_scope_is_persistent():
    current = owner()
    current.setWorkspaceRules('root', {'rules': 'Account one'})
    current.setSettingsScope('User')
    assert current.readOperations()['settingsScope'] == 'User'
    current.cloud.mail = 'other@example.test'
    assert current.readOperations()['workspacePolicies'] == {}


def test_workshop_context_reuses_verified_identity_and_the_saved_workspace_policy(monkeypatch):
    import nodelang.cloud_session as sessions
    current = owner()
    current.setGraphWorkspaces('graph', ['root'])
    current.setWorkspaceRules('root', {'rules': 'Keep drawings private', 'shareLearning': False})
    monkeypatch.setattr(sessions, 'signed_in_cloud_account', lambda: 'one@example.test')
    assert current.executionContext('graph')['workspaces'][0]['rules'] == 'Keep drawings private'
    assert current.executionContext('other')['workspaces'] == []
    monkeypatch.setattr(sessions, 'signed_in_cloud_account', lambda: None)
    assert current.executionContext('graph')['workspaces'] == []


def test_recovery_budget_is_a_typed_wireable_workshop_parameter():
    from nodelang.pipeline_engines import tool_settings
    from nodelang.library_engines import ENGINE_SOCKETS
    assert 'recovery_timeout_seconds' in ENGINE_SOCKETS['tool.workshop']['target']
    assert tool_settings({'tool': 'workshop'}, {'recovery_timeout_seconds': 45})[0]['out']['recovery_timeout_seconds'] == 45
    with pytest.raises(ValueError):
        tool_settings({'tool': 'workshop'}, {'recovery_timeout_seconds': 0})


def test_permission_decision_uses_the_real_graph_machine_and_rejects_replay():
    from pathlib import Path
    from types import SimpleNamespace
    from nodelang import universal_application as app
    store, registry = app.build_universal_application(Path(__file__).resolve().parents[1] / 'nodelang/data/public_runtime_map.json')
    context = registry.authorization.session.context()
    initial = app.project_universal_canvas(store, registry, authentication_context=context)
    definition = next(row['id'] for row in initial['catalog'] if row['name'] == 'Permission Request')
    permission, _ = app.instantiate_universal_definition(store, registry, definition, x=420, y=180,
                                                         authentication_context=context)
    fields = {'requester': registry.authorization.subject_root, 'action': 'file.read',
              'object': 'workspace', 'parameters': '{}', 'reason': 'Fixture read permission',
              'expires-at': '2100-01-01T00:00:00Z'}
    for name, value in fields.items():
        projection = app.project_universal_canvas(store, registry, authentication_context=context)
        interface = next(row['id'] for row in projection['selected_assembly']['interfaces'] if row['name'] == name)
        app.edit_universal_interface_value(store, registry, permission, interface, value, authentication_context=context)
    current = SettingsOwner(store, runtime=SimpleNamespace(universal_registry=registry),
                            authentication_context=context, dependencies=object())
    assert current.grantAccess(permission)['revision'] == store.revision
    approved = app.project_universal_canvas(store, registry, authentication_context=context)['selected_assembly']
    assert approved['operational']['current_state_label'] == 'APPROVED'
    before = store.revision
    with pytest.raises(ValueError):
        current.grantAccess(permission)
    assert store.revision == before
