"""No idle turn end: open Work holds the turn even when the Work authority is unreachable.

The authority answers only while the session holds its lease; an idle session
loses it. The Stop host records each verdict it really observed, and the hook
uses that record once per turn when the authority cannot be reached.
"""
import io
import json

from nodelang import native_stop_hook as hook

SESSION = '2b338572-c520-4ec7-a9e8-a155198adb68'
OPEN = {'decision': 'block', 'reason': 'Work W-12 is open: submit its evidence.'}
T0 = 1_790_000_000.0


def _fingerprint():
    return hook._fingerprint('claude', SESSION)


def _payload(active=False):
    return {'session_id': SESSION, 'transcript_path': '', 'stop_hook_active': active}


def _main(tmp_path, monkeypatch, payload, verdict):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(hook.sys, 'argv', ['native_stop_hook'])
    monkeypatch.setattr(hook.sys, 'stdin', type('In', (), {'buffer': io.BytesIO(json.dumps(payload).encode())})())
    monkeypatch.setattr(hook, 'query_stop', lambda payload, vendor: verdict)
    out = io.StringIO()
    monkeypatch.setattr(hook.sys, 'stdout', out)
    assert hook.main() == 0
    return json.loads(out.getvalue())


def test_the_host_records_what_the_authority_really_said(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    host = hook.NativeStopHost.__new__(hook.NativeStopHost)
    host.fingerprint, host.last_gate = _fingerprint(), None
    request = {'request_id': 'a' * 32, 'fingerprint': host.fingerprint, 'operation': 'stop',
               'stop_hook_active': False}
    for observed, recorded in ((OPEN, OPEN), ({}, {})):
        host._observe = lambda observed=observed: dict(observed)
        host._handle(request)
        record = json.loads(hook._verdict_path(host.fingerprint).read_text(encoding='utf-8'))
        assert record['verdict'] == recorded
    host._observe = lambda: dict(hook.UNAVAILABLE)
    host._handle(request)
    record = json.loads(hook._verdict_path(host.fingerprint).read_text(encoding='utf-8'))
    assert record['verdict'] == {}, 'an unreachable authority never overwrites what it last said'


def test_open_work_holds_the_turn_when_the_authority_is_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    hook._remember_verdict(_fingerprint(), OPEN)
    result = _main(tmp_path, monkeypatch, _payload(), hook._ending_turn(hook.UNAVAILABLE))
    assert result['decision'] == 'block'
    assert 'Work W-12 is open' in result['reason'] and 'native_owner_rebind' in result['reason']


def test_the_second_stop_of_a_turn_is_never_held(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    hook._remember_verdict(_fingerprint(), OPEN)
    result = _main(tmp_path, monkeypatch, _payload(active=True), hook._ending_turn(hook.UNAVAILABLE))
    assert result.get('decision') != 'block'


def test_no_open_work_or_an_old_record_lets_the_turn_end(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    hook._remember_verdict(_fingerprint(), {})
    assert _main(tmp_path, monkeypatch, _payload(), hook._ending_turn(hook.UNAVAILABLE)).get('decision') != 'block'
    hook._remember_verdict(_fingerprint(), OPEN, now=T0)
    assert hook.no_idle_decision(_payload(), 'claude-code', now=T0 + hook.NO_IDLE_WINDOW_SECONDS + 1) is None


def test_a_reachable_authority_answers_for_itself(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    hook._remember_verdict(_fingerprint(), OPEN)
    assert _main(tmp_path, monkeypatch, _payload(), {}) == {}


def test_codex_and_gemini_turn_ends_are_held_the_same_way(tmp_path, monkeypatch):
    """Codex Stop and Gemini AfterAgent share the Claude wire; unknown runtimes stay refused."""
    import pytest
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    thread = '019a7f3e-5c1d-7a2b-9e44-0d6c8b1f2a3e'
    for vendor, runtime in (('codex', 'codex'), ('gemini', 'gemini'), ('antigravity', 'gemini')):
        assert hook.canonical_runtime(vendor) == runtime
        hook._remember_verdict(hook._fingerprint(runtime, thread), OPEN)
        held = hook.no_idle_decision({'session_id': thread, 'stop_hook_active': False}, vendor)
        assert held['decision'] == 'block' and set(held) == {'decision', 'reason'}
    with pytest.raises(ValueError):
        hook.canonical_runtime('some-other-agent')
