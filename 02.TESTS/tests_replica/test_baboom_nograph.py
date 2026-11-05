"""BABOOM's companion window runs on the existing BaboomNativeHost, fed by the app instead of the graph."""
import pytest


@pytest.fixture
def brain(monkeypatch):
    from nodelang import baboom_nograph
    from nodelang import settings_owner

    configured = {'default_model': 'openrouter/free', 'agents': {}, 'providerPreferences': {},
                  'providers': {'openrouter': {'enabled': True}}}
    monkeypatch.setattr(settings_owner, 'read_router_settings', lambda: configured)

    class Brain:
        asked = []
        models = []
        stop_checks = []
        active_counts = []
        frame_counts = []
        fail = False
        settings = configured

        def ask(self, prompt, context, model, turn_seconds, is_halted=None, before_dispatch=None):
            if before_dispatch is not None:
                before_dispatch()
            self.asked.append(prompt)
            self.models.append(model)
            self.stop_checks.append(is_halted)
            self.active_counts.append(baboom_nograph._STATE['turns'])
            self.frame_counts.append(baboom_nograph.NoGraphTransport().baboom_native_frame()['context']['work'].get('active_turns'))
            if self.fail:
                raise RuntimeError('Provider did not finish')
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


def test_each_baboom_turn_uses_the_current_shared_default_and_profile(brain):
    from nodelang import baboom_nograph

    brain.settings['default_model'] = 'ollama/qwen3:8b'
    first = baboom_nograph.ask('which programs are connected?')
    assert brain.models[-1] == 'ollama/qwen3:8b'
    assert first['steps'] == [{'tool': 'hosts_state', 'status': 'ok'}]
    brain.settings['agents']['BABOOM'] = {'model': 'openrouter/qwen/qwen3-coder:free'}
    baboom_nograph.ask('check Revit')
    assert brain.models[-1] == 'openrouter/qwen/qwen3-coder:free'
    brain.settings['agents'].clear()
    brain.settings['default_model'] = 'openrouter/free'
    baboom_nograph.ask('check again')
    assert brain.models[-1] == 'openrouter/free'


def test_unsupported_baboom_route_is_not_replaced_with_a_free_model(brain, monkeypatch):
    from nodelang import baboom_nograph
    from nodelang.goose_adapter import GooseAdapter, GooseRefused

    brain.settings['default_model'] = 'local-cli/codex'
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', GooseAdapter(None))
    with pytest.raises(GooseRefused, match='needs an OpenRouter free route or a local Ollama model'):
        baboom_nograph.ask('check Revit')


def test_native_baboom_obeys_stop_everything_before_dispatch(brain, monkeypatch):
    from types import SimpleNamespace
    from nodelang import baboom_nograph, nograph_server

    monkeypatch.setattr(nograph_server, '_SERVER', SimpleNamespace(is_halted=lambda: True))
    with pytest.raises(RuntimeError, match='Stopped by you'):
        baboom_nograph.NoGraphTransport().respond_baboom_command(utterance='check Revit')
    assert brain.asked == []
    assert baboom_nograph._STATE['turns'] == 0


def test_native_baboom_uses_the_existing_agent_budget(brain, monkeypatch):
    from nodelang import agent_budget, baboom_nograph
    from nodelang.model_router import ModelRouteRefused

    monkeypatch.setattr(agent_budget, 'paused', lambda agent: agent == 'BABOOM')
    with pytest.raises(ModelRouteRefused, match='token cap'):
        baboom_nograph.ask('check Revit')
    assert brain.asked == []


def test_disabled_provider_refuses_before_goose_dispatch(brain):
    from nodelang import baboom_nograph
    from nodelang.model_router import ModelRouteRefused

    brain.settings['providers']['openrouter']['enabled'] = False
    with pytest.raises(ModelRouteRefused, match='OpenRouter is disabled in Settings'):
        baboom_nograph.ask('check Revit')
    assert brain.asked == []
    brain.settings['default_model'] = 'ollama/qwen3:8b'
    baboom_nograph.ask('check Revit locally')
    assert brain.models[-1] == 'ollama/qwen3:8b'


def test_shared_stop_signal_reaches_the_running_goose_turn(brain, monkeypatch):
    from types import SimpleNamespace
    from nodelang import baboom_nograph, nograph_server

    stopped = [False]
    monkeypatch.setattr(nograph_server, '_SERVER', SimpleNamespace(is_halted=lambda: stopped[0]))
    baboom_nograph.ask('check Revit')
    check = brain.stop_checks[-1]
    assert callable(check) and check() is False
    stopped[0] = True
    assert check() is True


def test_composer_and_native_turns_expose_actual_activity_and_return_to_idle(brain):
    from nodelang import baboom_nograph

    baboom_nograph.ask('from the composer')
    baboom_nograph.NoGraphTransport().respond_baboom_command(utterance='from the desktop')
    assert brain.active_counts == [1, 1]
    assert brain.frame_counts == [1, 1]
    assert baboom_nograph._STATE['turns'] == 0
    brain.fail = True
    with pytest.raises(RuntimeError, match='Provider did not finish'):
        baboom_nograph.ask('fails while running')
    assert baboom_nograph._STATE['turns'] == 0


def test_refused_concurrent_goose_ask_is_not_counted_as_another_active_turn(brain, monkeypatch):
    from nodelang import baboom_nograph
    from nodelang.goose_adapter import GooseAdapter, GooseRefused

    seen = []

    class HeldLock:
        def acquire(self, blocking=False):
            seen.append(baboom_nograph._STATE['turns'])
            return False

    adapter = GooseAdapter(object())
    adapter.lock = HeldLock()
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', adapter)
    monkeypatch.setitem(baboom_nograph._STATE, 'turns', 1)
    with pytest.raises(GooseRefused, match='answering another request'):
        baboom_nograph.ask('another request')
    assert seen == [1]
    assert baboom_nograph._STATE['turns'] == 1


def test_goose_is_offered_only_the_workshop_and_canvas_tools(monkeypatch, tmp_path):
    from nodelang.goose_adapter import WORKSHOP_TOOLS
    from nodelang.native_agent_mcp import build_server
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv('ARCHHUB_CONNECTOR_TOOLS', WORKSHOP_TOOLS)
    names = {tool.name for tool in build_server()._tool_manager.list_tools()}
    assert {'declare', 'send', 'read', 'canvas.read', 'library.search'} <= names
    assert all(n in ('declare', 'send', 'read', 'library.search') or n.startswith('canvas.') for n in names)
