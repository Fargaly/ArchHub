"""The Studio composer pick is one owner-held graph setting that survives a restart.

2026-09-17 the founder's header read "Choose a model / No provider selected"
and the composer "no model picked" with provider keys on the machine: a pick
only set page state, and was written to a file beside the graph only when a
Send got through. The pick is now configuration.composer_model, written
through the admitted interaction route like the BABOOM startup setting,
append-only and owner-only. The old file is read only while the graph holds
no pick. Only the provider answer is a fixture here: no network, no real key.
"""
import json
import secrets
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nodelang import agent_composer, application_server, cloud_relay, model_catalogue, model_router, pipeline_engines
from nodelang import universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application, project_universal_canvas

PICK = "openrouter/vendor/model-a"
LEGACY = "openrouter/old/model"
COMPOSER_OPERATION = "app:appearance-operation:composer-model:v1"


def test_a_fresh_graph_has_no_pick_and_writes_nothing():
    store, registry = build_universal_application(resolve_map_path())
    before = store.revision
    current = app.read_universal_composer_model(store.snapshot(), registry)
    assert current == {"value": "", "source": "default", "revision": None,
                       "actor": None, "asset": None, "binding": None}
    assert store.revision == before
    setting = project_universal_canvas(store, registry)["configuration"]["composer_model"]
    assert setting["available"] is True and setting["value"] == "" and setting["source"] == "default"
    assert setting["event_fact_input"] == "app:event-fact:submitted-value:v1"
    assert setting["control"].startswith("app:appearance-control:")


def test_a_graph_from_an_older_build_takes_the_pick_across_restarts_and_a_clear_retires_the_old_file(
        tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(agent_composer, "_DEFAULT_MODEL", "")
    monkeypatch.setattr(cloud_relay, "load_cloud_session", lambda _: None)
    monkeypatch.setattr(pipeline_engines, "brain_recall", lambda params, feeds: ({"out": ""}, "no recall"))
    monkeypatch.setattr(model_catalogue, "live_model_groups", lambda session=None, **kw: {
        "ok": True, "live": True, "count": 1, "source_errors": {}, "groups": [{"name": "BYO", "items": [
            {"name": "Model A", "route": "vendor/model-a", "vendor": "vendor", "tag": "BYO"}]}]})
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    database = tmp_path / "composer.sqlite3"
    legacy = Path(str(database) + ".agent-model")
    calls = []

    def provider(request, timeout):
        calls.append(json.loads(request.data)["model"])
        content = json.dumps({"actions": [], "answer": "fixture answer"})
        return BytesIO(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode())

    def routed(*args, **kwargs):
        return model_router.route_chat(*args, **kwargs, opener=provider, environ={},
            secrets_loader=lambda name: "synthetic-fixture-key" if name == "openrouter" else "", cloud_session=None)
    monkeypatch.setattr(agent_composer, "route_chat", routed)

    def start():
        return ApplicationServer(universal_state_path=database, universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=False,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            live_watch=False).start()

    def request(server, path, body=None):
        call = Request(server.url + path, headers={"Content-Type": "application/json", "Origin": server.url,
            "Cookie": "ArchHub-Session=" + server.browser_session_token,
            "X-ArchHub-Session": server.browser_session_token,
            "X-ArchHub-CSRF": server.browser_csrf_token},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(call, timeout=120) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def pick(server, value):
        status, canvas = request(server, "/api/universal/canvas")
        assert status == 200, canvas
        setting = canvas["configuration"]["composer_model"]
        binding = next(row for row in canvas["interaction_projection"]["bindings"]
                       if row["control"] == setting["control"])
        return request(server, "/api/universal/interaction", {
            "interaction": binding["interaction"], "control": binding["control"],
            "event": binding["event"], "revision": canvas["interaction_projection"]["revision"],
            "projection_mode": "interaction-delta-v1",
            "event_facts": [{"input": setting["event_fact_input"], "value": value}]})

    def selected(server):
        status, models = request(server, "/api/universal/models")
        assert status == 200, models
        return models["selected_route"]

    def baboom_model(server):
        """The model a BABOOM open question asks: BABOOM has no picker of its own."""
        asked = []

        def composer(store, registry, prompt, *, model, **kwargs):
            asked.append(model)
            return {"actions": [], "answer": "fixture"}
        with monkeypatch.context() as scoped:
            scoped.setattr(agent_composer, "run_agent_composer", composer)
            application_server.answer_open_question(server, "hello", None, {"command": {}, "response": {}})
        return asked[0]

    def send(server):
        return request(server, "/api/universal/agent", {"prompt": "hello", "model": ""})

    # An older build: its canvas never projected a composer setting, so the
    # graph holds no composer control, interaction or binding, and a Send
    # wrote its pick to the file beside the graph.
    with monkeypatch.context() as older:
        older.setattr(app, "_project_universal_composer_model", lambda *args: None)
        server = start()
        try:
            status, canvas = request(server, "/api/universal/canvas")
            assert status == 200 and canvas["configuration"]["composer_model"] is None, canvas
        finally:
            server.close()
    legacy.write_text(LEGACY, encoding="utf-8")

    server = start()
    try:
        cells = server.universal_store.snapshot().cells
        assert COMPOSER_OPERATION not in cells, "the graph was built without the setting"
        assert not any(root.startswith("app:composer-model-binding:") for root in cells)
        assert selected(server) == LEGACY, "a pick made by an older build is still shown"
        assert baboom_model(server) == LEGACY
        # A clear while only the old file holds a pick is not unchanged.
        before = server.universal_store.revision
        status, cleared = pick(server, "")
        assert status == 200, cleared
        state = cleared["configuration_state"]["composer_model"]
        assert (state["value"], state["source"]) == ("", "graph")
        assert server.universal_store.revision > before
        assert selected(server) == "", "a clear retires the old file"
        assert baboom_model(server) == ""
        status, unpicked = send(server)
        assert unpicked.get("ok") is False and "No model" in unpicked.get("error", ""), unpicked
        status, repeated = pick(server, "")
        assert status == 400 and "already" in repeated.get("error", ""), repeated
        status, changed = pick(server, PICK)
        assert status == 200, changed
        state = changed["configuration_state"]["composer_model"]
        assert (state["value"], state["source"]) == (PICK, "graph")
        assert state["actor"] == server.universal_registry.authorization.subject_root
        assert calls == [], "a pick asks no provider"
        before = server.universal_store.revision
        status, refused = pick(server, "no-provider-route")
        assert status == 400 and "names no provider" in refused.get("error", ""), refused
        assert server.universal_store.revision == before
        status, answer = send(server)
        assert status == 200 and answer.get("answer") == "fixture answer", answer
        assert calls == ["vendor/model-a"], "Send went through the router to the graph-held pick"
        assert legacy.read_text(encoding="utf-8") == LEGACY, "the old file is read, never written"
    finally:
        server.close()

    # The same graph reopened by a new process: the graph answers, not the file.
    server = start()
    try:
        assert selected(server) == PICK
        assert baboom_model(server) == PICK
        status, canvas = request(server, "/api/universal/canvas")
        assert status == 200 and canvas["configuration"]["composer_model"]["value"] == PICK
        assert legacy.read_text(encoding="utf-8") == LEGACY
    finally:
        server.close()


def test_admitted_keyed_providers_are_listed_and_never_promise_an_unkeyed_openrouter():
    held = {"anthropic": "a-key", "google": "g-key", "nvidia": "n-key"}
    rows = model_router.provider_rows(environ={}, secrets_loader=lambda name: held.get(name, ""),
        cloud_session=None, local_probe=lambda host, port: False)
    by = {row["id"]: row for row in rows}
    assert by["openrouter"]["state"] == "no key"
    for name in ("anthropic", "google"):
        assert by[name]["state"] == "keyed, not routed", by
        assert "add an OpenRouter key" in by[name]["source"] and "reached through" not in by[name]["source"]
    assert "openai" not in by and "nvidia" not in by, "only keyed providers the graph registry admits"
    held["openrouter"] = "r-key"
    by = {row["id"]: row for row in model_router.provider_rows(environ={},
        secrets_loader=lambda name: held.get(name, ""), cloud_session=None, local_probe=lambda host, port: False)}
    assert by["openrouter"]["state"] == "keyed"
    assert "reached through OpenRouter" in by["anthropic"]["source"]
    for secret in held.values():
        assert secret not in json.dumps(rows)


def test_the_provider_listing_opens_the_secrets_store_once(monkeypatch, tmp_path):
    """GET /api/universal/providers calls provider_rows with no loader of its own."""
    opened, asked = [], []

    def load_api_key(name):
        asked.append(name)
        return {"openrouter": "r-key", "openai": "o-key"}.get(name, "")
    store = SimpleNamespace(SECRETS_FILE=str(tmp_path / "absent" / "secrets.dat"), load_api_key=load_api_key)
    monkeypatch.setattr(model_router, "_application_secrets_store", lambda: opened.append(1) or store)
    rows = model_router.provider_rows(environ={}, cloud_session=None, local_probe=lambda host, port: False)
    by = {row["id"]: row for row in rows}
    assert len(opened) == 1, "store loads per provider_rows call: %d" % len(opened)
    assert (by["openrouter"]["state"], by["openrouter"]["source"]) == ("keyed", "secrets store")
    assert by["cloud"]["state"] == "no key"
    assert by["openai"]["state"] == "keyed, not routed"
    assert "reached through OpenRouter" in by["openai"]["source"]
    assert "r-key" not in json.dumps(rows) and "o-key" not in json.dumps(rows)
    assert {"openrouter", "archhub-cloud", "openai", "anthropic", "google"} <= set(asked)
