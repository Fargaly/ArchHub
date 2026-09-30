"""Courts: the founder assigns Workshop Work to an agent already running in it.

Design workshop-assign-design.html (sha256 67caa887...), founder decisions 1-5.
A real ApplicationServer (the execution-gate court's own, with the machine pipe),
real agents bound over that pipe, the founder's real browser session over HTTP.
Nothing launches or enrols a session, and no provider or network is used.

- Without the founder's browser binding (no session, or no CSRF): 403 and no
  assignment; with it, the assignment exists.
- An agent whose connection lease has lapsed is refused at commit, even though
  a page drawn earlier showed it verified.
- Only an agent attached to this Workshop can be assigned; one active assignee.
- The same external_key in the same Workshop returns the existing Work.
- Assigning grants nothing: no claim, no write permit.
- assignment_id is idempotent; a completed Work refuses an assignment.
"""
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang import commit_intent
from nodelang.application_machine_transport import MachineTransportError
from nodelang.universal_application import (_read_workshop_assignment, _workshop_assignment_roots,
                                            set_universal_scope)
from tests_replica.test_workshop_execution_gate import TARGET, _agent, _container, _permit, _serve

ROUTE = "/api/universal/workshop-work-assign"


@pytest.fixture
def served(tmp_path, monkeypatch):
    server, descriptor, provider = _serve("content-store", tmp_path, monkeypatch)
    binding = server._resolve_browser_session(server.browser_session_token)
    with server.mutation_lock, commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="scope"):
        set_universal_scope(server.universal_store, server.universal_registry, authentication_context=binding.context)
    try:
        yield server, descriptor, provider
    finally:
        server.close()


def _http(server, path, body=None, *, cookie=True, csrf=True):
    headers = {"Content-Type": "application/json", "Origin": server.url}
    if cookie:
        headers["Cookie"] = "ArchHub-Session=" + server.browser_session_token
    if csrf:
        headers["X-ArchHub-CSRF"] = server.browser_csrf_token
    call = Request(server.url + path, method="GET" if body is None else "POST", headers=headers,
                   data=None if body is None else json.dumps(body).encode("utf-8"))
    try:
        with urlopen(call, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def _scope(server):
    status, canvas = _http(server, "/api/universal/canvas")
    assert status == 200, canvas
    return canvas["workshop_scope"]["root"]


def _running_agent(server, descriptor, provider, name):
    """A real agent bound over the pipe (binding attaches it to the Workshop), seen on
    an authenticated request, so its connection lease is live."""
    client, session = _agent(descriptor, provider, name)
    client.request("GET", "/api/universal/work")           # an authenticated request: a live lease
    assert session in _participants(server)
    return client, session


def _work(server, key, *, title="Assign court", container=False):
    body = {"title": title, "description": "Assign court Work", "workshop_root": server.universal_registry.workshop_root,
            "workshop_scope": _scope(server), "revision": server.universal_store.revision, "external_key": key,
            "projection": False}
    if container:
        body["structured_references"] = {"cde-container": _container(key)}
    status, created = _http(server, "/api/universal/work", body)
    assert status == 200, created
    return created


def _assign(server, work, session, assignment, **kwargs):
    return _http(server, ROUTE, {"workshop_root": server.universal_registry.workshop_root,
        "workshop_scope": _scope(server), "revision": server.universal_store.revision,
        "work": work, "agent_session": session, "assignment_id": assignment}, **kwargs)


def _participants(server):
    from nodelang.cell_deliberation import read_deliberation_space
    registry = server.universal_registry
    return read_deliberation_space(server.universal_store.snapshot(), registry.deliberation_protocol,
                                   registry.workshop_root).participant_roots


def _assignments(server, work):
    snapshot, registry = server.universal_store.snapshot(), server.universal_registry
    return [held for held in (_read_workshop_assignment(snapshot, registry, root)
                              for root in _workshop_assignment_roots(snapshot, registry))
            if held.work_root == work]


def test_only_the_founders_browser_binding_assigns(served):
    server, descriptor, provider = served
    work = _work(server, "court:binding:1")["created_root"]
    _client, session = _running_agent(server, descriptor, provider, "assign-binding")
    assert _assign(server, work, session, "app:workshop-assignment:court-binding-a", cookie=False)[0] == 403
    assert _assign(server, work, session, "app:workshop-assignment:court-binding-a", csrf=False)[0] == 403
    assert "app:workshop-assignment:court-binding-a" not in server.universal_store.snapshot().cells
    assert _assignments(server, work) == []
    status, answer = _assign(server, work, session, "app:workshop-assignment:court-binding-a")
    assert status == 200, answer
    assert [held.agent_session_root for held in _assignments(server, work)] == [session]


def test_an_agent_whose_lease_lapsed_is_refused_at_commit(served):
    server, descriptor, provider = served
    work = _work(server, "court:lease:1")["created_root"]
    _live, live = _running_agent(server, descriptor, provider, "assign-lease-live")
    _stale, stale = _running_agent(server, descriptor, provider, "assign-lease-stale")
    # The page drew both as verified; the stale one's lease then lapsed.
    with server._machine_agent_observation_lock:
        server._machine_agent_observations[stale] = time.time() - 3600
    status, refused = _assign(server, work, stale, "app:workshop-assignment:court-lease-stale")
    assert status == 403 and "live verified connection" in refused.get("error", ""), refused
    # Refused before the commit, so the reply is a refusal OF THIS id: the browser may
    # clear its retry only on a refusal that names the exact assignment it sent.
    assert refused.get("refused") is True and refused.get("assignment") == "app:workshop-assignment:court-lease-stale"
    assert refused.get("reconciled_absent") is True, "the id was read absent under the commit lock"
    assert _assignments(server, work) == []
    assert _assign(server, work, live, "app:workshop-assignment:court-lease-live")[0] == 200


def test_only_an_attached_agent_and_only_one_active_assignee(served):
    server, descriptor, provider = served
    work = _work(server, "court:attached:1")["created_root"]
    # A runtime Agent Session in the graph that is not a participant of this Workshop
    # (binding over the pipe attaches one; this one never was).
    from uuid import uuid4
    from nodelang.universal_application import begin_universal_runtime_agent_session
    binding = server._resolve_browser_session(server.browser_session_token)
    with server.mutation_lock, commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="outside session"):
        outside_session, _ = begin_universal_runtime_agent_session(server.universal_store, server.universal_registry,
            session_root="app:agent-session:runtime:assign-outside-" + uuid4().hex, runtime="baboom-execution",
            external_session_fingerprint=uuid4().hex + uuid4().hex,
            catalog_entry_root="app:agent-body-catalog:entry:baboom-execution", authentication_context=binding.context)
    outside = outside_session.root_id
    assert outside not in [row for row in _participants(server)]
    status, refused = _assign(server, work, outside, "app:workshop-assignment:court-outside")
    assert status == 403 and "attached to this Workshop" in refused.get("error", ""), refused
    _a, first = _running_agent(server, descriptor, provider, "assign-first")
    _b, second = _running_agent(server, descriptor, provider, "assign-second")
    assert _assign(server, work, first, "app:workshop-assignment:court-first")[0] == 200
    status, refused = _assign(server, work, second, "app:workshop-assignment:court-second")
    assert status == 400 and "active assignee" in refused.get("error", ""), refused
    assert [held.agent_session_root for held in _assignments(server, work)] == [first]


def test_the_same_key_in_the_same_workshop_returns_the_existing_work(served):
    server, _descriptor, _provider = served
    first = _work(server, "bbc4:installed-evidence:3")
    count = len(server.universal_store.snapshot().cells)
    again = _work(server, "bbc4:installed-evidence:3", title="A second try")
    assert again["existing"] is True and again["created_root"] == first["created_root"]
    assert first["existing"] is False
    other = _work(server, "bbc4:installed-evidence:4")
    assert other["existing"] is False and other["created_root"] != first["created_root"]
    assert len(server.universal_store.snapshot().cells) > count, "a different key still creates"


def test_assigning_grants_no_claim_and_no_write(served):
    server, descriptor, provider = served
    work = _work(server, "court:grants:1", container=True)["created_root"]
    client, session = _running_agent(server, descriptor, provider, "assign-grants")
    assert _assign(server, work, session, "app:workshop-assignment:court-grants")[0] == 200
    with pytest.raises(MachineTransportError):
        _permit(client, "assigned-without-claim")          # no claim, no root-bound permit


def test_assignment_id_is_idempotent_and_a_completed_work_refuses(served, tmp_path):
    server, descriptor, provider = served
    work = _work(server, "court:idempotent:1")["created_root"]
    _client, session = _running_agent(server, descriptor, provider, "assign-idempotent")
    first = _assign(server, work, session, "app:workshop-assignment:court-idem")
    again = _assign(server, work, session, "app:workshop-assignment:court-idem")
    assert first[0] == again[0] == 200 and again[1]["existing"] is True
    assert len(_assignments(server, work)) == 1
    # A completed Work: finished through the real claim, submit and court path.
    (tmp_path / "done.flag").write_text("done", encoding="utf-8")
    body = {"title": "Completed", "description": "completed court Work",
            "workshop_root": server.universal_registry.workshop_root, "workshop_scope": _scope(server),
            "revision": server.universal_store.revision, "external_key": "court:completed:1", "projection": False,
            "structured_references": {"requirements": {"gate": {"kind": "file_exists", "spec": {"path": "done.flag"}}},
                                      "cde-container": {"container_id": "court-complete", "allowed_paths": ["."]}}}
    status, done = _http(server, "/api/universal/work", body)
    assert status == 200, done
    finisher, finisher_session = _running_agent(server, descriptor, provider, "assign-finisher")
    finisher.claim_work(done["created_root"])
    finisher.request("POST", "/api/universal/work-transition", {"root": done["created_root"], "event": "submit",
        "evidence": json.dumps({"artifact": done["created_root"], "verdict": "green"})})
    assert finisher.adjudicate_work(done["created_root"])["passed"] is True
    status, refused = _assign(server, done["created_root"], session, "app:workshop-assignment:court-completed")
    assert status == 400 and "completed Work" in refused.get("error", ""), refused


def test_a_work_outside_this_workshop_is_refused(served):
    server, descriptor, provider = served
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="unscoped Work"):
        elsewhere = server.dispatch_universal_machine_route({"method": "POST", "path": "/api/universal/work",
            "body": {"title": "Not in the Workshop", "priority": 1, "x": 900, "y": 900}})["created_root"]
    inside = _work(server, "court:scope:1")["created_root"]
    _client, session = _running_agent(server, descriptor, provider, "assign-scope")
    status, refused = _assign(server, elsewhere, session, "app:workshop-assignment:court-elsewhere")
    assert status == 400 and "not in this Workshop" in refused.get("error", ""), refused
    assert _assignments(server, elsewhere) == []
    assert _assign(server, inside, session, "app:workshop-assignment:court-inside")[0] == 200


@pytest.mark.parametrize("change", ["revoked", "rebound"])
def test_a_binding_revoked_or_replaced_after_capture_is_refused_at_commit(served, monkeypatch, change):
    """The pipe's binding is captured before the lock; between that and the commit it is
    revoked (dropped) or replaced (re-bound). The commit re-reads it and refuses."""
    from nodelang import workshop_work_creation as creation
    server, descriptor, provider = served
    work = _work(server, "court:revoked:" + change)["created_root"]
    _client, session = _running_agent(server, descriptor, provider, "assign-" + change)
    real = creation.live_agent_binding
    calls = []

    def capture_then_change(owner, root):
        answer = real(owner, root)
        if not calls:
            calls.append(root)
            with owner._machine_agent_session_lock:
                if change == "revoked":
                    owner._machine_agent_sessions.pop(root, None)
                else:
                    owner._machine_agent_sessions[root] = dict(owner._machine_agent_sessions[root])
        return answer
    monkeypatch.setattr(creation, "live_agent_binding", capture_then_change)
    status, refused = _assign(server, work, session, "app:workshop-assignment:court-" + change)
    assert status == 403 and "changed or was revoked" in refused.get("error", ""), refused
    assert _assignments(server, work) == []


def test_the_workshop_read_projects_its_assignments(served):
    server, descriptor, provider = served
    work = _work(server, "court:projection:1")["created_root"]
    _client, session = _running_agent(server, descriptor, provider, "assign-projection")
    from urllib.parse import urlencode
    query = "/api/universal/workshop?" + urlencode(dict(root=server.universal_registry.workshop_root, scope=_scope(server)))
    status, before = _http(server, query)
    assert status == 200 and not any(row["work"] == work for row in before.get("assignments", [])), before.get("assignments")
    assert _assign(server, work, session, "app:workshop-assignment:court-projection")[0] == 200
    status, after = _http(server, query)
    assert status == 200
    assert {"assignment": "app:workshop-assignment:court-projection", "work": work,
            "agent_session": session} in after["assignments"]


def test_a_committed_assignment_is_reconciled_by_its_exact_id_even_after_admission_changes(served):
    """The first attempt commits and its reply is lost; then the agent's lease lapses.
    The exact-id retry must report the committed assignment, never a refusal that
    would let the browser forget an id whose effect exists."""
    server, descriptor, provider = served
    work = _work(server, "court:reconcile:1")["created_root"]
    _client, session = _running_agent(server, descriptor, provider, "assign-reconcile")
    status, first = _assign(server, work, session, "app:workshop-assignment:court-reconcile")
    assert status == 200 and first.get("existing") is False, first
    with server._machine_agent_observation_lock:
        server._machine_agent_observations[session] = time.time() - 3600   # admission would now refuse
    status, retry = _assign(server, work, session, "app:workshop-assignment:court-reconcile")
    assert status == 200 and retry.get("existing") is True and retry.get("reconciled") is True, retry
    assert retry["assignment"] == "app:workshop-assignment:court-reconcile" and retry["agent_session"] == session
    # A fresh id in the same state IS refused, and says the id was read absent.
    status, refused = _assign(server, work, session, "app:workshop-assignment:court-reconcile-2")
    assert status in (400, 403) and refused.get("refused") is True and refused.get("reconciled_absent") is True, refused


def test_an_assignment_id_that_names_another_work_is_never_reported_as_a_refusal(served):
    server, descriptor, provider = served
    first_work = _work(server, "court:reconcile:a")["created_root"]
    other_work = _work(server, "court:reconcile:b")["created_root"]
    _client, session = _running_agent(server, descriptor, provider, "assign-reconcile-other")
    assert _assign(server, first_work, session, "app:workshop-assignment:court-reconcile-other")[0] == 200
    status, body = _assign(server, other_work, session, "app:workshop-assignment:court-reconcile-other")
    assert status >= 400 and not body.get("refused"), ("a reused id is uncertain, never a refusal", body)
