"""SETTINGS5 / F32: Settings › Agents is one named row per agent app with live state."""
from __future__ import annotations

import types


def test_agent_apps_roster_labels_match_book_and_f32():
    from nodelang.agent_runtime_registry import AGENT_APPS
    assert AGENT_APPS == (
        ('claude', 'Claude Code'),
        ('codex', 'Codex'),
        ('opencode', 'OpenCode'),
        ('gemini', 'Gemini CLI'),
        ('goose', 'BABOOM'),
        ('antigravity', 'Antigravity'),
    )


def test_list_agents_always_returns_one_row_per_agent_app(monkeypatch):
    from nodelang import nograph_server as server

    monkeypatch.setattr(server, '_declarations', lambda: [])
    monkeypatch.setattr(server, '_SERVER', types.SimpleNamespace(
        _live_agents=types.SimpleNamespace(get=lambda: {'processes': [], 'complete': True})))
    rows = server._list_agents()
    assert [row['id'] for row in rows] == ['claude', 'codex', 'opencode', 'gemini', 'goose', 'antigravity']
    assert [row['name'] for row in rows] == [
        'Claude Code', 'Codex', 'OpenCode', 'Gemini CLI', 'BABOOM', 'Antigravity']
    assert all(row['presence'] == 'stopped' for row in rows)
    assert all(row['status_text'] == 'Not running' for row in rows)
    assert all(row['task'] == 'Connect' for row in rows)
    assert all(row['evidence'] == 'roster' for row in rows)
    joined = ' '.join(row['status_text'] + ' ' + row['task'] + ' ' + row['name'] for row in rows)
    assert 'Runtime-' not in joined
    assert 'No live presence' not in joined


def test_list_agents_merges_live_process_into_roster_row(monkeypatch):
    from nodelang import nograph_server as server

    monkeypatch.setattr(server, '_declarations', lambda: [
        {'root': 'root-claude', 'runtime': 'claude', 'app': 'claude', 'status': 'working',
         'task': 'Repair settings', 'request_id': 'req-1', 'current': True}])
    monkeypatch.setattr(server, '_SERVER', types.SimpleNamespace(
        _live_agents=types.SimpleNamespace(get=lambda: {
            'processes': [{'runtime': 'claude', 'pid': 1}], 'complete': True})))
    rows = {row['id']: row for row in server._list_agents()}
    assert rows['claude']['presence'] == 'working'
    assert rows['claude']['status_text'] == 'Working'
    assert rows['claude']['task'] == 'Repair settings'
    assert rows['claude']['evidence'] == 'process'
    assert rows['claude']['session_count'] == 1
    assert rows['codex']['presence'] == 'stopped'
    assert rows['codex']['task'] == 'Connect'


def test_agents_canvas_does_not_invent_sessions_for_idle_roster(tmp_path, monkeypatch):
    from nodelang import nograph_server as server
    from nodelang.workshop_mailbox import application_history

    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(name, str(directory))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(server, '_list_agents', lambda: [
        {'id': 'claude', 'runtime': 'claude', 'name': 'Claude Code', 'presence': 'stopped',
         'evidence': 'roster'},
        {'id': 'codex', 'runtime': 'codex', 'name': 'Codex', 'presence': 'idle',
         'evidence': 'process', 'session_count': 1}])
    with application_history(database=tmp_path / 'messages.sqlite3') as history:
        monkeypatch.setattr(
            'nodelang.workshop_mailbox.profile_database',
            lambda: __import__('pathlib').Path(history._db.execute('PRAGMA database_list').fetchone()[2]))
        graph = server.r_agents_canvas(None, None)
    vendors = [row['vendor'] for row in graph['sessions']]
    assert 'claude' not in vendors
    assert vendors.count('codex') == 1
