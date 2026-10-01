"""Courts: a saved Workshop conversation is reachable from its Conversations row on a fresh graph.

The catalog names the canvas path to the Workshop Workbench, read from the graph (the map domain
that holds the Workbench as a member, then the Workbench). Walking that path with ordinary scope
transitions admits the saved room; before it, the room is refused. The Studio walks the same path
with the canvas's own open interactions (studio.html ARCHHUB_SCOPE_OPEN, which must send the
lease's acknowledgement mode). Review evidence only; the real-app run is the acceptance.
"""
import json
import shutil
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from nodelang import application_server as server_module
from nodelang import universal_application as app
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.workshop_conversation_catalog import create_workshop_conversation, workshop_workbench_path
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance


@pytest.fixture
def owner(tmp_path, monkeypatch):
    from nodelang.conversation_content import prepare_empty_content_binding
    from nodelang.conversation_history import ConversationHistoryStore
    original = server_module.QuietThreadingHTTPServer
    monkeypatch.setattr(server_module, "QuietThreadingHTTPServer",
        lambda address, handler: original(address, handler, bind_and_activate=False))
    (tmp_path / "universal").mkdir()
    server = server_module.ApplicationServer(universal_workspace_root=tmp_path / "universal",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False)
    try:
        registry, store = server.universal_registry, server.universal_store
        path = tmp_path / "reach-history.sqlite3"
        server.conversation_content._path = path
        adopted = prepare_empty_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        with ConversationHistoryStore(path, instance_id=adopted.binding.instance_id) as history:
            history.ensure_conversation(registry.workshop_root)
            history.initialize_retention()
        store.commit(adopted.expected_revision, create=adopted.create, replace=adopted.replace)
        yield server
    finally:
        server.close()


def _canvas(server, browser):
    return app.project_universal_canvas(server.universal_store, server.universal_registry,
                                        authentication_context=browser.context)


def test_the_path_is_read_from_the_graph_and_every_step_is_openable(owner):
    registry = owner.universal_registry
    browser = owner._resolve_browser_session(owner.browser_session_token)
    path = workshop_workbench_path(owner.universal_store.snapshot(), registry)
    assert path == [registry.map.domains["brain"], registry.workshop_workbench_root]
    canvas = _canvas(owner, browser)
    assert canvas["scope"]["current"] == registry.canvas_root
    for step in path:
        assert any(node["id"] == step and node.get("openable") for node in canvas["nodes"]), step
        app.set_universal_scope(owner.universal_store, registry, step, authentication_context=browser.context)
        canvas = _canvas(owner, browser)
        assert canvas["scope"]["current"] == step


def test_a_saved_room_is_refused_at_the_root_and_admitted_on_the_path(owner):
    from nodelang.existing_workshop_conversation import _admit
    registry, store = owner.universal_registry, owner.universal_store
    browser = owner._resolve_browser_session(owner.browser_session_token)
    room = create_workshop_conversation(owner, authentication_context=browser.context,
        expected_revision=store.revision, title="Saved room", participant_roots=[browser.subject_root],
        idempotency_key="reach-saved-room")["root"]
    with pytest.raises(AuthorizationDenied):
        _admit(owner, browser, room, registry.canvas_root, allow_child=True)
    for step in workshop_workbench_path(store.snapshot(), registry):
        app.set_universal_scope(store, registry, step, authentication_context=browser.context)
    snapshot, space = _admit(owner, browser, room, registry.workshop_workbench_root, allow_child=True)
    assert space.title == "Saved room"


def test_no_path_is_named_when_no_domain_holds_the_workbench(owner):
    from types import SimpleNamespace
    registry = owner.universal_registry
    without_holder = SimpleNamespace(
        map=SimpleNamespace(domains={name: root for name, root in registry.map.domains.items() if name != "brain"}),
        roles=registry.roles, workshop_workbench_root=registry.workshop_workbench_root)
    assert workshop_workbench_path(owner.universal_store.snapshot(), without_holder) == []


# Real HTTP through the REAL page code. Each entrypoint the Conversations row can take runs as the page
# runs it, in node, against a live server: the desktop walk (studio.html ARCHHUB_SCOPE_OPEN) against the
# desktop ApplicationServer, and the signed authority (studio-authority.js open) against the clean server.

STUDIO = Path(app.__file__).resolve().parent / "studio"

_DESKTOP_WALK = r"""
const [url, token, html, pathJson] = process.argv.slice(1);
const fs = await import('node:fs');
const source = fs.readFileSync(html, 'utf8');
const start = source.indexOf('window.ARCHHUB_SCOPE_OPEN = async targets');
const end = source.indexOf('window.ARCHHUB_HISTORY', start);
if (start < 0 || end < 0) throw new Error('ARCHHUB_SCOPE_OPEN is not in studio.html');
const H = () => ({'Content-Type': 'application/json', 'X-ArchHub-Session': token});
const sent = [];
const answer = async r => { const d = await r.json(); if (!r.ok || d.ok === false) { const e = new Error(d.error || 'refused'); e.status = r.status; throw e; } return d; };
const jget = async p => answer(await fetch(url + p, {headers: H()}));
const jpost = async (p, b) => { sent.push({path: p, keys: Object.keys(b || {}).sort(), projection_mode: (b || {}).projection_mode ?? null}); return answer(await fetch(url + p, {method: 'POST', headers: H(), body: JSON.stringify(b || {})})); };
const window = {};
new Function('window', 'jget', 'jpost', source.slice(start, end))(window, jget, jpost);
try {
  const projection = await window.ARCHHUB_SCOPE_OPEN(JSON.parse(pathJson));
  console.log(JSON.stringify({ok: true, current: projection.scope.current, sent}));
} catch (error) { console.log(JSON.stringify({ok: false, error: String(error.message), status: error.status ?? null, sent})); }
"""

_SIGNED_OPEN = r"""
const [url, key, authorityJs, target] = process.argv.slice(1);
const {createRequire} = await import('node:module');
createRequire(import.meta.url)(authorityJs);
const signIn = await fetch(url + '/api/universal/session', {method: 'POST', body: '{}',
  headers: {'Content-Type': 'application/json', 'X-ArchHub-Sign-In': '1', 'X-ArchHub-Canvas-Key': key}});
const session = await signIn.json();
if (!signIn.ok) throw new Error('sign-in refused: ' + JSON.stringify(session));
const headers = () => ({'Content-Type': 'application/json', 'X-ArchHub-Session': session.token, 'X-ArchHub-CSRF': session.csrf});
const sent = [];
const request = async (p, body) => {
  if (body !== undefined) sent.push({path: p, keys: Object.keys(body).sort(), projection_mode: body.projection_mode ?? null});
  const r = await fetch(url + p, {method: body === undefined ? 'GET' : 'POST', headers: headers(), ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const d = await r.json();
  if (!r.ok || d.ok === false) throw new Error(d.error || 'refused');
  return d;
};
const api = globalThis.ArchHubStudioAuthority.create({get: p => request(p), post: (p, b) => request(p, b)});
await api.load();
try {
  const result = await api.open(target);
  console.log(JSON.stringify({ok: true, current: result.scope.current, sent}));
} catch (error) { console.log(JSON.stringify({ok: false, error: String(error.message), sent})); }
"""


def _node(script, *args):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node runs the page's own code")
    done = subprocess.run([node, "--input-type=module", "-e", script, *map(str, args)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _http(server, path):
    request = Request(server.url + path, headers={"X-ArchHub-Session": server.browser_session_token})
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


@pytest.fixture
def served(tmp_path):
    """The desktop ApplicationServer on a real socket, with a saved conversation off the root canvas."""
    from nodelang.conversation_content import prepare_empty_content_binding
    from nodelang.conversation_history import ConversationHistoryStore
    (tmp_path / "universal").mkdir()
    server = server_module.ApplicationServer(universal_workspace_root=tmp_path / "universal",
        runtime_compliance_runner=_green_runtime_compliance,
        enable_machine_transport=False, enable_machine_projection_prewarm=False)
    try:
        registry, store = server.universal_registry, server.universal_store
        path = tmp_path / "reach-history.sqlite3"
        server.conversation_content._path = path
        adopted = prepare_empty_content_binding(store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        with ConversationHistoryStore(path, instance_id=adopted.binding.instance_id) as history:
            history.ensure_conversation(registry.workshop_root)
            history.initialize_retention()
        store.commit(adopted.expected_revision, create=adopted.create, replace=adopted.replace)
        server.start()
        browser = server._resolve_browser_session(server.browser_session_token)
        room = create_workshop_conversation(server, authentication_context=browser.context,
            expected_revision=store.revision, title="Saved room", participant_roots=[browser.subject_root],
            idempotency_key="reach-http-room")["root"]
        yield server, room
    finally:
        server.close()


def test_the_desktop_row_walks_the_catalog_path_over_http_and_selects_the_room_in_the_new_scope(served):
    server, room = served
    registry = server.universal_registry
    root, general = registry.canvas_root, registry.workshop_root
    status, catalog = _http(server, "/api/universal/workshop?root=%s&scope=%s&catalog=1"
                            % (quote(general), quote(root)))
    assert status == 200, catalog
    path = catalog["workbench_path"]
    assert path == [registry.map.domains["brain"], registry.workshop_workbench_root]
    assert room in [row["root"] for row in catalog["conversations"]]
    status, refused = _http(server, "/api/universal/workshop?root=%s&scope=%s" % (quote(room), quote(root)))
    assert status in (400, 403) and refused["ok"] is False          # not reachable from the root canvas
    walked = _node(_DESKTOP_WALK, server.url, server.browser_session_token, STUDIO / "studio.html", json.dumps(path))
    assert walked["ok"] is True and walked["current"] == registry.workshop_workbench_root, walked
    opens = [row for row in walked["sent"] if row["path"] == "/api/universal/interaction"]
    assert len(opens) == len(path) and all(row["projection_mode"] == "topology-delta-v1" for row in opens), opens
    status, selected = _http(server, "/api/universal/workshop?root=%s&scope=%s"
                             % (quote(room), quote(registry.workshop_workbench_root)))
    assert status == 200 and selected["root"] == room, selected   # the room opens in the new scope


def test_the_desktop_walk_without_the_lease_mode_is_refused_by_the_real_route(served, tmp_path):
    server, _room = served
    registry = server.universal_registry
    page = (STUDIO / "studio.html").read_text(encoding="utf-8")
    stripped = tmp_path / "studio-without-mode.html"
    mode = "projection_mode:binding.acknowledgement_mode || 'receipt-v1'"
    assert page.count(mode) == 1
    stripped.write_text(page.replace(mode, ""), encoding="utf-8")   # a trailing comma stays valid JS
    path = workshop_workbench_path(server.universal_store.snapshot(), registry)
    walked = _node(_DESKTOP_WALK, server.url, server.browser_session_token, stripped, json.dumps(path))
    assert walked["ok"] is False and "topology projection delta" in walked["error"], walked
    status, canvas = _http(server, "/api/universal/canvas")
    assert canvas["scope"]["current"] == registry.canvas_root        # nothing moved


def test_the_signed_authority_open_enters_the_scope_over_the_clean_route(tmp_path):
    from tests_replica.test_clean_server_admission import (
        _issue_clean_session, _json as clean_json, _provision_clean_runtime, _start_clean_server)
    built, provider = _provision_clean_runtime(tmp_path, root_name="reach-signed-open")
    server = _start_clean_server(built, provider, scope_root=built.grand_map.root_id)
    try:
        _issue_clean_session(built, token="reach-token", csrf="reach-csrf")
        status, canvas = clean_json(server.url, "/api/universal/canvas", token="reach-token")
        assert status == 200
        target = next(node for node in canvas["nodes"] if node["openable"])["id"]
        opened = _node(_SIGNED_OPEN, server.url, server.clean_canvas_key, STUDIO / "studio-authority.js", target)
        assert opened["ok"] is True and opened["current"] == target, opened
        (sent,) = [row for row in opened["sent"] if row["path"] == "/api/universal/interaction"]
        binding = next(row for row in canvas["interaction_projection"]["bindings"] if row["control"] == target)
        # The clean lease names no acknowledgement mode, and its scope route reads none.
        assert "acknowledgement_mode" not in binding and sent["projection_mode"] == binding.get("projection_mode")
        status, catalog = clean_json(server.url, "/api/universal/workshop?root=%s&scope=%s&catalog=1"
                                     % (quote(target), quote(target)), token="reach-token")
        assert status != 200 or "workbench_path" not in catalog   # no catalog row reaches here to walk
    finally:
        server.close()


_OPEN_MODE = r"""
const [authorityJs] = process.argv.slice(1);
const {createRequire} = await import('node:module');
createRequire(import.meta.url)(authorityJs);
const sent = [];
const lease = named => ({ok: true, graph_id: 'graph:court', root: 'scope:a', revision: 7, nodes: [], wires: [], catalog: [],
  scope: {current: 'scope:a', trail: [{root: 'scope:a'}]},
  interaction_projection: {bindings: [{control: 'scope:b', interaction: 'i', event: 'e', event_facts: [],
    ...(named ? {acknowledgement_mode: 'topology-delta-v1'} : {})}]}});
const out = {};
for (const named of [true, false]) {
  const api = globalThis.ArchHubStudioAuthority.create({get: async () => lease(named),
    post: async (p, body) => { sent.push(body); return {...lease(named), root: 'scope:b'}; }});
  await api.load();
  await api.open('scope:b');
  out[named ? 'named' : 'unnamed'] = Object.prototype.hasOwnProperty.call(sent.at(-1), 'projection_mode')
    ? sent.at(-1).projection_mode : 'absent';
}
console.log(JSON.stringify(out));
"""


def test_the_signed_open_sends_a_projection_mode_only_when_its_lease_names_one():
    assert _node(_OPEN_MODE, STUDIO / "studio-authority.js") == {"named": "topology-delta-v1", "unnamed": "absent"}
