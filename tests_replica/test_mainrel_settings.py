"""Real Settings owner and installer preference agree after a cold reopen."""
from nodelang import commit_intent
from nodelang import universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.application_recovery_files import backup_location, installer_backup_directory
from nodelang.cell_secret_keys import MemorySigningKeyProvider

def test_visible_backup_location_edits_the_same_installer_preference(tmp_path, monkeypatch):
    profile = tmp_path / 'profile'
    profile.mkdir()
    monkeypatch.setenv('LOCALAPPDATA', str(profile))
    provider = MemorySigningKeyProvider('archhub.local.relationship-authority', b'r' * 32)
    provider.add_key('archhub.local.court-attestation', b'c' * 32)
    root = app._system_tool_canvas_root('tool_workshop')
    relation, _ = app._workshop_board_property_root(root, 'backup_location')
    destination = tmp_path / 'other-disk'
    def boot():
        return ApplicationServer(universal_state_path=profile / 'authority.sqlite3', universal_key_provider=provider,
            enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False)
    server = boot()
    try:
        store, registry = server.universal_store, server.universal_registry
        with commit_intent.declare(commit_intent.USER_ACTION, actor='app:archhub', reason='fixture changes installer backup location'):
            app.apply_universal_canvas_gesture(store, registry, roots=[root], focus_root=root)
            app.edit_universal_property(store, registry, relation, str(destination))
        nodes = app.project_universal_canvas(store, registry)['nodes']
        parameter = next(row for node in nodes if node['id'] == root for row in node['params'] if row['label'] == 'backup_location')
        assert parameter['value'] == str(destination)
        assert parameter['editor'] == 'text' and parameter['editable']
        assert backup_location(profile)['location'] == str(destination)
        assert installer_backup_directory(profile, profile / 'authority.sqlite3').is_relative_to(destination)
    finally:
        server.close()
    server = boot()
    try:
        nodes = app.project_universal_canvas(server.universal_store, server.universal_registry)['nodes']
        assert next(row['value'] for node in nodes if node['id'] == root for row in node['params'] if row['label'] == 'backup_location') == str(destination)
    finally:
        server.close()
