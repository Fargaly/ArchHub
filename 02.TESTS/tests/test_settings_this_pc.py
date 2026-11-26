"""Settings > This PC rows: each one has an owner value that changes real behaviour."""
import json
import os
import zipfile

import pytest


def _settings(tmp_path):
    from nodelang.nograph_server import JsonFile
    return JsonFile(tmp_path / 'settings.json', {})


@pytest.mark.parametrize('identity,value', [
    ('Appearance.Theme set', 'Blueprint'), ('Appearance.Density', 'Compact'), ('Appearance.UI scale', 120),
    ('Appearance.Snap to grid', True), ('Appearance.Wires', 'On hover'), ('Appearance.Wire width', 3),
    ('Appearance.Panel colour', '#112233'), ('Appearance.Event socket colour', '#00aaff')])
def test_look_rows_save_in_the_settings_owner_and_read_back(tmp_path, identity, value):
    from nodelang.settings_owner import appearance_settings
    settings = _settings(tmp_path)
    rows = appearance_settings('setAppearance', [identity, value], settings)['appearanceSettings']
    row = next(r for r in rows if r['id'] == identity)
    assert row['value'] == value and row['overridden'] is True
    assert json.loads((tmp_path / 'settings.json').read_text(encoding='utf-8'))[row['storageKey']] == value


@pytest.mark.parametrize('identity,value', [
    ('Appearance.Theme set', 'Neon'), ('Appearance.UI scale', 200), ('Appearance.Wire width', 0),
    ('Appearance.Snap to grid', 'yes'), ('Appearance.Text colour', 'red')])
def test_look_rows_refuse_values_outside_their_limits(tmp_path, identity, value):
    from nodelang.nograph_server import Refused
    from nodelang.settings_owner import appearance_settings
    with pytest.raises(Refused):
        appearance_settings('setAppearance', [identity, value], _settings(tmp_path))


def test_every_look_row_is_also_a_setting_node():
    from nodelang.canvas_documents import thing_items
    ids = {row['setting']['id'] for row in thing_items() if row.get('setting')}
    assert {'Appearance.Theme set', 'Appearance.Snap to grid', 'Appearance.Wires', 'Appearance.UI scale'} <= ids


def test_install_when_i_quit_never_installs_while_the_window_is_open(tmp_path):
    from nodelang.application_update import ApplicationUpdate, default_update_policy, save_application_setting
    save_application_setting('update_install_when_idle', False, tmp_path)
    assert default_update_policy(tmp_path)['install_when_idle'] is False
    update = ApplicationUpdate.__new__(ApplicationUpdate)
    update._policy = lambda: default_update_policy(tmp_path)
    update._auto_allowed, update.reload = (lambda: True), (lambda: None)
    assert update.install_if_safe(user_idle=True) is False
    assert update.install_if_safe(closing=True) is True
    save_application_setting('update_install_when_idle', True, tmp_path)
    assert update.install_if_safe(user_idle=True) is True


def test_back_up_now_writes_to_the_chosen_folder(tmp_path, monkeypatch):
    from nodelang import session_files
    from nodelang.settings_owner import maintenance_settings
    state, sessions, target = tmp_path / 'appstate', tmp_path / 'sessions', tmp_path / 'backups'
    for folder in (state / 'settings', sessions, target):
        folder.mkdir(parents=True)
    (sessions / 'one.archhub').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(session_files, 'sessions_directory', lambda: sessions)
    settings = _settings(tmp_path)
    with pytest.raises(ValueError):
        maintenance_settings('setMaintenance', ['backupDir', str(tmp_path / 'missing')], settings, state)
    with pytest.raises(ValueError):
        maintenance_settings('setMaintenance', ['backupTo', 'Mars'], settings, state)
    maintenance_settings('setMaintenance', ['backupDir', str(target)], settings, state)
    held = maintenance_settings('backUpNow', [], settings, state)['maintenance']
    assert held['lastBackup']['path'].startswith(str(target))
    with zipfile.ZipFile(held['lastBackup']['path']) as archive:
        assert any(name.endswith('one.archhub') for name in archive.namelist())


def test_cache_size_removes_oldest_cache_files_first(tmp_path, monkeypatch):
    from nodelang import pc_maintenance
    from nodelang.pc_maintenance import prune_cache
    monkeypatch.setattr(pc_maintenance, '_GB', 1000)  # 1 "GB" = 1000 bytes: no large files on disk
    cache = tmp_path / 'cache'
    cache.mkdir()
    old, new = cache / 'old.bin', cache / 'new.bin'
    for path in (old, new):
        path.write_bytes(b'x' * 700)
    os.utime(old, (1, 1))
    assert prune_cache(tmp_path, 1) == ['old.bin'] and new.exists()
    with pytest.raises(ValueError):
        prune_cache(tmp_path, 0)


def test_review_before_sharing_holds_a_send_that_leaves_the_account_on_the_approve_card(tmp_path):
    from nodelang.hook_decision import checked_permissions, mode_verdict
    send = {"tool": "mcp__slack__post_message", "input": {"channel": "general", "text": "hi"}, "cwd": str(tmp_path)}
    workshop = {"tool": "mcp__workshop__send", "input": {"text": "hi"}, "cwd": str(tmp_path)}
    on, off = checked_permissions({}), checked_permissions({"reviewBeforeSharing": False})
    assert on["reviewBeforeSharing"] is True  # design default: on
    assert mode_verdict(send, "send", on, {}) == ("ask", "review-before-sharing")
    assert mode_verdict(send, "send", off, {}) is None  # Accept edits, switch off: never asks
    assert mode_verdict(workshop, "send", on, {}) is None  # his own Workshop never leaves his account
    with pytest.raises(ValueError):
        checked_permissions({"reviewBeforeSharing": "yes"})


def test_read_only_workspace_refuses_agent_writes_inside_it_only_when_on(tmp_path):
    from nodelang.hook_decision import read_only_workspace
    from nodelang.settings_owner import workspace_access
    from nodelang.nograph_server import JsonFile
    state, folder = tmp_path / "state", tmp_path / "project"
    folder.mkdir()
    workspaces = JsonFile(state / "settings" / "workspaces.json", {"roots": []})
    workspaces.write({"roots": [{"root_id": "workspace:p1", "label": "project", "path": str(folder)}]})
    env = {"ARCHHUB_TEST_STATE_DIR": str(state)}
    write = {"tool": "Write", "input": {"file_path": str(folder / "a.txt")}, "cwd": str(tmp_path)}
    outside = {"tool": "Write", "input": {"file_path": str(tmp_path / "b.txt")}, "cwd": str(tmp_path)}
    assert read_only_workspace(write, "write", env) == ""  # off by default: never blocks
    assert workspace_access("setWorkspaceReadOnly", ["workspace:p1", True], workspaces) == {"readOnlyWorkspaces": ["workspace:p1"]}
    assert read_only_workspace(write, "write", env) == str(folder.resolve())
    assert read_only_workspace(write, "read", env) == ""  # reading stays open
    assert read_only_workspace(outside, "write", env) == ""
    workspace_access("setWorkspaceReadOnly", ["workspace:p1", False], workspaces)
    assert read_only_workspace(write, "write", env) == ""
    with pytest.raises(ValueError):
        workspace_access("setWorkspaceReadOnly", ["workspace:gone", True], workspaces)


def test_conversation_retention_archives_and_never_deletes(tmp_path):
    from nodelang.conversation_history import ConversationHistoryStore
    now = [1_800_000_000.0]
    with ConversationHistoryStore(tmp_path / "workshop.sqlite3", instance_id="room", retention_clock=lambda: now[0]) as history:
        history.initialize_retention()
        for room in ("old-room", "new-room"):
            history.append(room, author="Agent", content="kept text", idempotency_key=room + "-1")
            history.record_activity(room)
        now[0] += 25 * 86400
        history.record_activity("new-room")
        with pytest.raises(ValueError):
            history.archive_inactive(0)
        assert history.archive_inactive(20) == {"archived": ["old-room"]}
        old = history.retention_status("old-room")
        assert old["archived_at"] is not None and old["purged_messages"] == 0 and old["last_sequence"] == 1
        assert history.retention_status("new-room")["archived_at"] is None
        assert history.archive_inactive(20) == {"archived": []}  # already archived: nothing moves twice
