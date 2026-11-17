"""CHATPICKER (F389): every composer the built app has (Home, and the one Canvas composer that the Workshop panel's
cards bring into a thread's context) offers "Start Claude Code" from the server's one answer. Choosing it starts one
chat with Read, Glob and Grep only; the thread then keeps talking to that same chat; a chat that ended says so and
starts nothing; a refused start on Home leaves nothing behind.

The compiled Studio on an isolated profile; claude on PATH is a FAKE (test_chat_acp.FAKE_CLAUDE behind an npm-style
.cmd shim). No real agent, no live app state.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from test_task_session_roundtrip import _isolate, _Studio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests_replica'))
from test_chat_acp import FAKE_CLAUDE  # noqa: E402

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _fake_claude(monkeypatch, folder, log):
    from nodelang import acp_client
    folder.mkdir()
    (folder / 'fake_claude.py').write_text(FAKE_CLAUDE, encoding='utf-8')
    (folder / 'claude.cmd').write_text('@ECHO off\r\nSETLOCAL\r\n"%_prog%"  "%dp0%\\fake_claude.py" %*\r\n', encoding='utf-8')
    monkeypatch.setitem(acp_client._INTERPRETERS, '.py', sys.executable)
    monkeypatch.setattr(acp_client, 'CHAT_ACTIONS', False)          # as the release ships
    monkeypatch.setenv('FAKE_AGENT_LOG', str(log))
    monkeypatch.setenv('PATH', str(folder) + os.pathsep + os.environ.get('PATH', ''))


def _lines(log):
    return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []


def test_every_composer_starts_claude_code_and_the_thread_keeps_that_chat(tmp_path, monkeypatch):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=_NO_WINDOW).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import acp_client, workshop_live, workshop_tasks
    from nodelang.nograph_server import NoGraphServer
    from nodelang.workshop_mailbox import application_history
    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    monkeypatch.setattr(workshop_live, 'live_agents', lambda with_status=False: [])   # no joined Claude session
    log = tmp_path / 'argv.log'
    _fake_claude(monkeypatch, tmp_path / 'bin', log)
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)

    def browser(phase):
        result = subprocess.run(  # on a timeout, TimeoutExpired.stdout carries how far the page got

            ['node', '02.TESTS/tests_js/chat_picker_live.cjs'],
            input=json.dumps({'phase': phase, 'url': server.public_url, 'cookie': server._cookie_token,
                              'browserCache': browser_cache, 'shots': os.environ.get('ARCHHUB_CHATPICKER_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=300,
            creationflags=_NO_WINDOW)
        print(result.stdout)
        assert result.returncode == 0, phase + '\n' + result.stdout + result.stderr

    try:
        # A Workshop thread an agent is working on: the dock's Workshop panel shows it under Working now.
        working = client.workshop('createTask', 'Model view audit')['taskId']
        with application_history() as history:
            workshop_tasks.claim(history, working, 'dock-test-agent', 'Drawing coordinator', lease_seconds=3600)
        # 1. A refused start on Home: Claude's first lines list a tool that acts.
        monkeypatch.setenv('FAKE_CLAUDE_INIT', json.dumps({'mcp_servers': [], 'tools': ['Read', 'Glob', 'Grep', 'Write']}))
        browser('refuse')
        monkeypatch.delenv('FAKE_CLAUDE_INIT')
        assert not acp_client._SESSIONS
        assert all(row['status'] == 'ARCHIVED' for row in client.workshop('listTasks') if row['title'] == 'how many sheets?')
        # 2. Start from Home, three messages to the same chat; the menus at 1009 and 1440; Start from the Workshop card.
        browser('chat')
        starts = [line for line in _lines(log) if isinstance(line, list)]
        assert len(starts) == 3, starts          # the refused one, the Home chat, the Workshop thread's chat
        assert all(words[words.index('--tools') + 1] == 'Read,Glob,Grep' for words in starts)
        assert len(acp_client._SESSIONS) == 2
        with application_history() as history:   # three answers of the one Home chat landed in its own thread
            rows = [row for row in workshop_tasks.column(history) if row['title'] == 'how many sheets?' and row['status'] != 'ARCHIVED']
        assert len(rows) == 1
        said = [m['text'] for m in rows[0]['agentLog'] + rows[0]['fileMessages']]
        assert sum('There are 12 sheets.' in text for text in said) == 3, said
        # 3. The Home chat's process ends; the next message in that thread says so and starts nothing.
        home_key = next(key for key in acp_client._SESSIONS if key[1] != working)
        acp_client._SESSIONS[home_key].transport.process.kill()
        acp_client._SESSIONS[home_key].transport.process.wait(10)
        browser('ended')
        assert len([line for line in _lines(log) if isinstance(line, list)]) == 3   # nothing was started
        assert client.workshop('listApprovals') == []                              # the approval store stays empty
    finally:
        acp_client.close_all()
        client.close()
        server.close()
