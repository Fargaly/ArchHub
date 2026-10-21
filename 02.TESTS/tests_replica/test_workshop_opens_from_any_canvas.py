"""Court (fix 1): the general Workshop opens from any canvas level the subject stands on.

Founder report 2026-09-23: "the Workshop does not open ... I click here and nothing opens".
His view stands on the top canvas; the Workshop card is drawn inside the Brain domain,
so the canvas-drawn Workshop list was empty and reads were refused.

Rule (SPEC.md section 6): "The same semantic root MUST be traversable, subject to
authority and the definition/instance boundaries in section 1, from every applicable
lens." The Workshop lens follows read authority on registry.workshop_root; view binding,
subject, current scope, CSRF and send validation still bind every request.

Real ApplicationServer over HTTP on a temporary graph; no host, model or network.
"""
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_application import set_universal_scope


def _call(server, path, body=None, *, csrf=True):
    headers = {"Content-Type": "application/json", "Cookie": "ArchHub-Session=" + server.browser_session_token}
    if csrf:
        headers["X-ArchHub-CSRF"] = server.browser_csrf_token
    call = Request(server.url + path, method="GET" if body is None else "POST", headers=headers,
        data=None if body is None else json.dumps(body).encode("utf-8"))
    try:
        with urlopen(call, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


@pytest.fixture(scope="module")
def top_canvas(tmp_path_factory):
    provider = MemorySigningKeyProvider("archhub.local.relationship-authority", b"w" * 32)
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    path = tmp_path_factory.mktemp("workshop-any-canvas") / "graph.sqlite3"
    server = ApplicationServer(universal_state_path=path, universal_key_provider=provider,
        enable_machine_transport=False, enable_universal_cloud_gateway=False, live_watch=False).start()
    try:
        binding = server._resolve_browser_session(server.browser_session_token)
        with server.mutation_lock:
            set_universal_scope(server.universal_store, server.universal_registry,
                authentication_context=binding.context)
        yield server
    finally:
        server.close()


def test_top_canvas_lists_reads_and_sends_the_general_workshop(top_canvas):
    server, registry = top_canvas, top_canvas.universal_registry
    status, canvas = _call(server, "/api/universal/canvas")
    assert status == 200, canvas
    scope = canvas["workshop_scope"]
    drawn = {row.get("id") for row in canvas.get("nodes", ())}
    assert registry.workshop_root not in drawn and registry.workshop_workbench_root not in drawn, \
        "the court stands where the Workshop card is not drawn"
    general = [row for row in scope["workshops"] if row["root"] == registry.workshop_root]
    assert len(general) == 1 and general[0]["is_general"] is True, scope
    assert "unavailable" not in scope, scope
    query = "/api/universal/workshop?" + urlencode(dict(root=registry.workshop_root, scope=scope["root"]))
    status, transcript = _call(server, query)
    assert status == 200, transcript
    assert transcript["root"] == registry.workshop_root and transcript["can_send"] is True
    binding = server._resolve_browser_session(server.browser_session_token)
    body = dict(root=registry.workshop_root, scope=scope["root"], category=transcript["send_category"],
        text="From the top canvas", refs=[], evidence=[], recipients=[binding.subject_root],
        reply_to=None, idempotency_key="top-canvas-note", created_at=None)
    assert _call(server, "/api/universal/workshop", body, csrf=False)[0] == 403, "CSRF still binds a send"
    status, sent = _call(server, "/api/universal/workshop", body)
    assert status == 200, sent
    stale = dict(root=registry.workshop_root, scope=registry.workshop_workbench_root)
    status, refused = _call(server, "/api/universal/workshop?" + urlencode(stale))
    assert status == 403, "a scope the view does not stand on is still refused: %r" % (refused,)


def test_without_read_authority_the_owner_says_why_and_refuses(top_canvas, monkeypatch):
    from nodelang import universal_application
    from nodelang.cell_authorization import AuthorizationDenied
    server, registry = top_canvas, top_canvas.universal_registry
    real = universal_application._require_application_authorization

    def no_workshop_read(snapshot, registry_, action_name, object_root, **kwargs):
        if action_name == "read" and object_root == registry.workshop_root:
            raise AuthorizationDenied("court: this subject may not read the Workshop")
        return real(snapshot, registry_, action_name, object_root, **kwargs)
    monkeypatch.setattr(universal_application, "_require_application_authorization", no_workshop_read)
    status, canvas = _call(server, "/api/universal/canvas")
    assert status == 200, canvas
    scope = canvas["workshop_scope"]
    assert [row for row in scope["workshops"] if row["root"] == registry.workshop_root] == []
    assert scope.get("unavailable") == "This account has no read access to the Workshop.", scope
    query = "/api/universal/workshop?" + urlencode(dict(root=registry.workshop_root, scope=scope["root"]))
    assert _call(server, query)[0] == 403
