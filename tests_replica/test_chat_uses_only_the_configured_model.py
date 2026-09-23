"""Court (fix 2): with no saved pick, Chat sends only with the model the founder configured.

Founder report 2026-09-23: Chat could not send; the header read "Choose a model".
Coordination review: no model may ever be chosen for him and nothing falls back to a
paid model. With no pick, a Send uses settings default_model only when it names a
concrete routable model he configured; otherwise it is refused and the Studio asks him
to choose (studio_default_model.test.cjs). A stored provider key never selects a model.
An explicit pick or an explicit clear still wins (test_composer_model_is_graph_held).
Only the provider answer and the settings/key store are fixtures: no network, no real key.
"""
import json
import secrets
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nodelang import agent_composer, cloud_relay, model_catalogue, model_router, pipeline_engines
from nodelang import universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider

# conftest keeps courts off the machine's real settings; this court restores the real
# default route and gives it a fixture settings and key store instead.
_REAL_DEFAULT = getattr(model_router, "default_composer_route", None)


def _start(tmp_path, monkeypatch, *, setting, stored):
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ARCHHUB_CLOUD_TOKEN", raising=False)
    if _REAL_DEFAULT is not None:
        monkeypatch.setattr(model_router, "default_composer_route", _REAL_DEFAULT)
    monkeypatch.setattr(agent_composer, "_DEFAULT_MODEL", "")
    monkeypatch.setattr(cloud_relay, "load_cloud_session", lambda _: None)
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, "no recall"))
    monkeypatch.setattr(model_catalogue, "live_model_groups", lambda session=None, **kw: {
        "ok": True, "live": True, "count": 0, "source_errors": {}, "groups": []})
    store = SimpleNamespace(SECRETS_FILE=str(tmp_path / "absent" / "secrets.dat"),
        load_setting=lambda name: setting if name == "default_model" else None,
        load_api_key=lambda name: stored.get(name, ""))
    monkeypatch.setattr(model_router, "_application_secrets_store", lambda: store)
    calls = []

    def provider(request, timeout):
        calls.append(json.loads(request.data)["model"])
        content = json.dumps({"actions": [], "answer": "fixture answer"})
        return BytesIO(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode())

    def routed(*args, **kwargs):
        return model_router.route_chat(*args, **kwargs, opener=provider, environ={},
            secrets_loader=lambda name: stored.get(name, ""), cloud_session=None)
    monkeypatch.setattr(agent_composer, "route_chat", routed)
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    server = ApplicationServer(universal_state_path=tmp_path / "composer.sqlite3", universal_key_provider=keys,
        universal_workspace_root=tmp_path, enable_machine_transport=False,
        enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
        live_watch=False).start()
    return server, calls


def _request(server, path, body=None):
    call = Request(server.url + path, headers={"Content-Type": "application/json", "Origin": server.url,
        "Cookie": "ArchHub-Session=" + server.browser_session_token,
        "X-ArchHub-Session": server.browser_session_token, "X-ArchHub-CSRF": server.browser_csrf_token},
        data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(call, timeout=120) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_the_configured_concrete_default_model_is_used_when_nothing_is_picked(tmp_path, monkeypatch):
    server, calls = _start(tmp_path, monkeypatch, setting="openrouter/vendor/default-model",
                           stored={"openrouter": "fixture-key"})
    try:
        status, models = _request(server, "/api/universal/models")
        assert status == 200, models
        assert models["selected_route"] == "", "nothing was picked"
        assert models.get("default_route") == "openrouter/vendor/default-model", models
        status, answer = _request(server, "/api/universal/agent", {"prompt": "hello", "model": ""})
        assert status == 200 and answer.get("answer") == "fixture answer", answer
        assert calls == ["vendor/default-model"], calls
    finally:
        server.close()


def test_no_model_is_ever_chosen_for_him_even_with_a_stored_key(tmp_path, monkeypatch):
    for index, setting in enumerate(("auto", "", "not-a-route")):
        server, calls = _start(tmp_path / str(index), monkeypatch, setting=setting,
                               stored={"openrouter": "fixture-key"})
        try:
            status, models = _request(server, "/api/universal/models")
            assert status == 200 and not models.get("default_route") and models["selected_route"] == "", models
            status, answer = _request(server, "/api/universal/agent", {"prompt": "hello", "model": ""})
            assert answer.get("ok") is False and "No model" in answer.get("error", ""), (setting, answer)
            assert calls == [], "no provider was asked for setting %r: %r" % (setting, calls)
        finally:
            server.close()