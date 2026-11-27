"""The approval file under a reader: a waiting agent and the Studio read it while Approve or Deny replaces it.

On Windows a plain read that overlaps os.replace makes the replace fail (WinError 5), and a read that fails was
taken for an empty file. Found on the chat release: "The approval could not be saved", a row stuck in `releasing`,
and a waiter that could deny a live request. Every case here holds a real reader open at the exact step.
"""
import json
import io
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("tool, expected", [("Read", 0), ("Write", 2)])
def test_hook_database_failure_blocks_effects(monkeypatch, capsys, tool, expected):
    from nodelang import hook_decision

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    payload = {"tool_name": tool, "tool_input": {"file_path": "example.txt"}}
    monkeypatch.setattr(hook_decision.sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
    monkeypatch.setattr(hook_decision, "decide", locked)
    assert hook_decision.main(["--vendor", "codex"]) == expected
    result = json.loads(capsys.readouterr().out)
    if expected:
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    else:
        assert result == {}


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'TEMP', 'TMP'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)


def _card(title='Write sheets.txt'):
    """One pending permit card, made the way a waiting agent makes it."""
    from nodelang import hook_decision
    event = {'tool': title, 'input': {'connector': 'Codex', 'input': {'path': 'sheets.txt'}}, 'vendor': 'Codex', 'session': 's1'}
    digest = hook_decision._call_digest(event, 'write', 'agent')
    hold = hook_decision._remember(event, 'write', 'agent', digest, 'Codex: ' + title, os.environ)
    assert hold
    return hold, digest


def _rows():
    from nodelang import hook_decision
    return json.loads(hook_decision._ask_path(os.environ).read_text(encoding='utf-8'))['holds']


def _hold_reader_open(seconds):
    """A reader without share-delete, as Path.read_text is while it reads; closed by a timer."""
    from nodelang import hook_decision
    reader = open(hook_decision._ask_path(os.environ), 'rb')
    threading.Timer(seconds, reader.close).start()
    return reader


@pytest.mark.parametrize('decision, status', [('approve', 'approved'), ('deny', 'declined')])
def test_a_decision_made_while_the_file_is_being_read_is_saved_once(decision, status):
    from nodelang import hook_decision
    hold, digest = _card()
    _hold_reader_open(0.4)
    assert hook_decision.ask_apply(hold, digest, decision)['status'] == status
    assert _rows()[hold]['status'] == status
    assert hook_decision._take_permit(digest, os.environ) is (decision == 'approve')   # exactly one grant, or none
    assert hook_decision._take_permit(digest, os.environ) is False


def test_an_approval_that_cannot_be_saved_stays_pending_and_the_click_can_be_repeated(monkeypatch):
    from nodelang import hook_decision
    hold, digest = _card()
    monkeypatch.setattr(hook_decision, '_STORE_TRIES', 2)
    reader = open(hook_decision._ask_path(os.environ), 'rb')                 # held for the whole first click
    try:
        with pytest.raises(ValueError, match='could not be saved'):
            hook_decision.ask_apply(hold, digest, 'approve')
    finally:
        reader.close()
    assert _rows()[hold]['status'] == 'pending'                          # not `releasing`, not closed
    assert hook_decision._take_permit(digest, os.environ) is False       # nothing was granted by the failed click
    assert hook_decision.ask_apply(hold, digest, 'approve')['status'] == 'approved'
    assert hook_decision._take_permit(digest, os.environ) is True


def test_an_action_that_ran_is_recorded_once_even_when_the_file_is_being_read_at_the_finish(monkeypatch):
    from nodelang import hook_decision
    hold, digest = _card()
    path = hook_decision._ask_path(os.environ)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['holds'][hold]['replay'] = {'kind': 'connector', 'tool': 'x', 'arguments': {}}   # an Approve that runs something
    path.write_text(json.dumps(data), encoding='utf-8')
    ran = []

    def release(replay):
        ran.append(replay['kind'])
        _hold_reader_open(0.4)                                           # a reader arrives between the action and the finish
        return {'ok': True}
    monkeypatch.setattr(hook_decision, '_release_ask', release)
    assert hook_decision.ask_apply(hold, digest, 'approve')['status'] == 'approved'
    assert ran == ['connector'] and _rows()[hold]['status'] == 'approved'
    assert hook_decision.ask_apply(hold, digest, 'approve')['status'] == 'approved' and ran == ['connector']   # never replayed


def test_a_read_that_fails_for_a_moment_is_read_again_and_never_taken_for_an_empty_file(monkeypatch):
    from nodelang import hook_decision
    hold, _digest = _card()
    path, real, failures = hook_decision._ask_path(os.environ), Path.read_text, [3]

    def busy(self, *args, **kwargs):
        if self == path and failures[0]:
            failures[0] -= 1
            raise PermissionError(13, 'Access is denied')
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', busy)
    assert hold in hook_decision._read_holds(path)['holds']              # read again, the row is there
    assert hook_decision.approval_status(os.environ, hold) == 'pending'
    failures[0] = 10 ** 6                                                # it never becomes readable
    monkeypatch.setattr(hook_decision, '_STORE_TRIES', 3)
    with pytest.raises(OSError):                                         # unknown, said as unknown: not {"holds": {}}
        hook_decision._read_holds(path)
    with pytest.raises(OSError):
        hook_decision.approval_status(os.environ, hold)
    assert hook_decision.ask_reviews() == []                             # the list (display only) shows nothing rather than fail


def test_a_file_that_does_not_exist_is_an_empty_store():
    from nodelang import hook_decision
    assert hook_decision._read_holds(hook_decision._ask_path(os.environ)) == {'revision': 0, 'holds': {}}


def test_two_writers_wait_for_each_other_instead_of_failing_at_once():
    from nodelang import hook_decision
    hold, digest = _card()
    lock = hook_decision._ask_path(os.environ).with_suffix('.lock')
    held = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)       # another writer is inside

    def leave():
        os.close(held)
        lock.unlink()
    threading.Timer(0.3, leave).start()
    began = time.monotonic()
    assert hook_decision.ask_apply(hold, digest, 'deny')['status'] == 'declined'
    assert time.monotonic() - began >= 0.25
