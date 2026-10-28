"""BABOOM's companion window runs on the existing BaboomNativeHost, fed by the app instead of the graph."""
import pytest


@pytest.fixture
def brain(monkeypatch):
    from nodelang import baboom_nograph

    class Brain:
        asked = []

        def ask(self, prompt, context, model, turn_seconds):
            self.asked.append(prompt)
            return {'text': '{"answer": "Revit is connected.", "actions": []}', 'steps': [{'tool': 'hosts_state', 'status': 'ok'}]}

    monkeypatch.setitem(baboom_nograph._STATE, 'brain', Brain())
    monkeypatch.setattr(baboom_nograph, 'own_session', lambda state_dir=None: 'session-baboom')
    return Brain


def test_companion_host_connects_and_projects_a_live_quiet_frame(brain, monkeypatch):
    from nodelang import baboom_nograph
    monkeypatch.setattr('nodelang.baboom_native_companion.foreground_application_windows', lambda: None)
    host = baboom_nograph.companion_host()
    snapshot = host.latest_snapshot
    assert host.connection_state == 'live' and snapshot.directive['motion'] == 'idle'
    assert snapshot.context['brain'] == {'ok': True, 'facts': 1} and snapshot.report is None
    assert host.poll().revision == snapshot.revision + 1


def test_companion_ask_and_act_reach_the_goose_brain(brain, monkeypatch):
    from nodelang import baboom_nograph
    from nodelang.baboom_native_companion import compact_baboom_response_report
    monkeypatch.setattr('nodelang.baboom_native_companion.foreground_application_windows', lambda: None)
    host = baboom_nograph.companion_host()
    answer = host.respond_input('which programs are connected?')
    assert compact_baboom_response_report(answer['response']) == 'Revit is connected.'
    assert host.execute_input('check Revit')['summary'] == 'Revit is connected.'
    assert brain.asked[-2:] == ['which programs are connected?', 'check Revit']
    assert baboom_nograph._STATE['turns'] == 0


def test_without_the_brain_the_orb_is_down_and_asks_fail_with_the_reason(monkeypatch):
    from nodelang import baboom_nograph
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', None)
    monkeypatch.setitem(baboom_nograph._STATE, 'error', 'BABOOM is turned off in Settings.')
    transport = baboom_nograph.NoGraphTransport()
    assert transport.baboom_native_frame()['context']['brain']['ok'] is False
    with pytest.raises(RuntimeError, match='turned off'):
        transport.respond_baboom_command(utterance='hi')
