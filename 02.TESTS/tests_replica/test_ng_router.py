"""Router configuration and profiling without a graph or account store."""
import json
import pytest
from nodelang import model_router as router
from nodelang.settings_owner import SettingsOwner


def test_settings_switch_reaches_next_message(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    owner = SettingsOwner(None, dependencies=object())
    owner.setRouterSettings({'default_model': 'openrouter/cohere/north-mini-code:free'})
    calls = []
    def answer(route, messages, **options):
        calls.append((route, options))
        return {'text': 'four', 'model': route, 'provider': 'OpenRouter', 'usage': {'total_tokens': 3}}
    monkeypatch.setattr(router, 'route_chat', answer)
    assert router.composer_chat({'prompt': '2+2'})['answer'] == 'four'
    owner.setRouterSettings({'default_model': 'openrouter/nvidia/nemotron-3.5-lightning:free'})
    router.composer_chat({'prompt': '2+2'})
    assert [call[0] for call in calls] == ['openrouter/cohere/north-mini-code:free', 'openrouter/nvidia/nemotron-3.5-lightning:free']
    assert all(call[1]['free_only'] for call in calls)
    rows = owner.routerSettings()['requests']
    assert len(rows) == 2 and rows[0]['agent'] == 'BABOOM'
    assert rows[0]['provider'] == 'OpenRouter' and rows[0]['tokens'] == 3


def test_settings_reject_paid_keys_and_bad_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    owner = SettingsOwner(None, dependencies=object())
    for values in ({'fallback_models': ['openai-api/gpt-4o']}, {'api_key': 'private'},
                   {'free_first': False}, {'agents': {'agent': {'unknown': 'private'}}}):
        with pytest.raises(ValueError):
            owner.setRouterSettings(values)
    assert not (tmp_path / 'ArchHub/settings/router.json').exists()
    with pytest.raises(ValueError, match='configured provider'):
        owner.setRouterSettings({'providerPreferences': {'openrouter':'ollama/llama'}})


def test_failure_is_logged_without_prompt_or_error_secret(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    def fail(*args, **kwargs):
        raise router.ModelRouteRefused('private error', reason_code='provider_rate_limited')
    monkeypatch.setattr(router, 'route_chat', fail)
    with pytest.raises(router.ModelRouteRefused):
        router.composer_chat({'prompt': 'private prompt'})
    rows = SettingsOwner(None, dependencies=object()).routerSettings()['requests']
    assert rows[0]['outcome'] == 'provider_rate_limited'
    assert 'private' not in json.dumps(rows)


@pytest.mark.parametrize('status', [400, 404, 429, 503])
def test_configured_fallback_and_real_stream_parser(monkeypatch, status):
    import io
    import urllib.error
    sent = []
    deltas = []
    def wire(request, timeout=None):
        body = json.loads(request.data)
        sent.append(body)
        if len(sent) == 1:
            raise urllib.error.HTTPError(request.full_url, status, 'refused', {}, io.BytesIO())
        return io.BytesIO(b'data: {"model":"second/answer:free","choices":[{"delta":{"content":"four"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":3,"cost":0}}\n\ndata: [DONE]\n\n')
    result = router.route_chat('openrouter/first/refuses:free', [{'role':'user','content':'2+2'}],
        free_only=True, fallback_routes=['openrouter/second/answer:free'], on_delta=deltas.append,
        opener=wire, environ={}, secrets_loader=lambda name:'fixture-value', cloud_session=None)
    assert result['text'] == 'four' and deltas == ['four']
    assert [row['model'] for row in sent] == ['first/refuses:free', 'second/answer:free']
    assert all(row['stream'] and row['provider']['max_price']['completion'] == 0 for row in sent)


def test_partial_stream_never_retries():
    import io
    sent, deltas = [], []
    def wire(request, timeout=None):
        sent.append(request)
        return io.BytesIO(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
    with pytest.raises(router.ModelRouteRefused, match='did not complete'):
        router.route_chat('openrouter/first/refuses:free', [{'role':'user','content':'2+2'}],
            free_only=True, fallback_routes=['openrouter/second/answer:free'], on_delta=deltas.append,
            opener=wire, environ={}, secrets_loader=lambda name:'fixture-value', cloud_session=None)
    assert len(sent) == 1 and deltas == ['partial']


def test_profiles_and_retention(tmp_path, monkeypatch):
    import time
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    owner = SettingsOwner(None, dependencies=object())
    profile = {'purpose': 'Review drawings', 'admins': 'Owner', 'questionsPerDay': 2,
               'autonomy': {'Read': 'Autonomous'}, 'skillIds': ['review']}
    owner.setRouterSettings({'agents': {'BABOOM': profile}})
    from nodelang.settings_owner import read_router_settings
    assert read_router_settings()['agents']['BABOOM'] == profile
    row = dict(id='old', ts=time.time()-21*86400, agent='BABOOM', model='free',
               provider='OpenRouter', tokens=1, ms=1, outcome='answered')
    router.request_profiles(row)
    assert router.request_profiles() == []


@pytest.mark.parametrize('headers,halted,closing,status', [
    ({}, False, False, 403),
    ({'X-ArchHub-Canvas-Key':'wrong'}, False, False, 403),
    ({'X-ArchHub-Canvas-Key':'fixture', 'Origin':'https://outside.test'}, False, False, 403),
    ({'X-ArchHub-Canvas-Key':'fixture', 'Sec-Fetch-Site':'cross-site'}, False, False, 403),
    ({'X-ArchHub-Canvas-Key':'fixture'}, True, False, 400),
    ({'X-ArchHub-Canvas-Key':'fixture'}, False, True, 400),
    ({'X-ArchHub-Canvas-Key':'fixture'}, False, False, 200),
])
def test_http_graph_free_boundary(monkeypatch, headers, halted, closing, status):
    import io
    from types import SimpleNamespace
    from nodelang.application_server import _router_http, _CleanAuthorityHttpServer
    from nodelang.runtime_activity import RuntimeActivity
    import nodelang.universal_application as application
    activity = RuntimeActivity()
    if closing:
        activity.begin_shutdown()
    owner = SimpleNamespace(clean_canvas_key='fixture', activity=activity)
    owner._clean_canvas_key_matches = lambda value: _CleanAuthorityHttpServer._clean_canvas_key_matches(owner, value)
    monkeypatch.setattr(application, 'is_application_halted', lambda: halted)
    calls = []
    def answer(body, **kwargs):
        calls.append(body)
        return {'ok': True, 'answer':'four'}
    monkeypatch.setattr(router, 'composer_chat', answer)
    class Handler:
        path = '/api/router/chat'
        server = SimpleNamespace(server_address=('127.0.0.1', 8123))
        wfile = io.BytesIO()
        def _body(self): return {'prompt':'2+2'}
        def _json(self, code, payload): self.status = code
        def send_response(self, code): self.status = code
        def send_header(self, *args): pass
        def end_headers(self): pass
    handler = Handler()
    handler.headers = {'Host':'127.0.0.1:8123', **headers}
    assert _router_http(owner, handler)
    assert handler.status == status
    assert bool(calls) == (status == 200)
