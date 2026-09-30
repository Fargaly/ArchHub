"""Social approval on the real graph, through the real HTTP routes, and never by a machine session.

No mocked graph reader: a real application graph, a real prepared social Work and
its real connector delegation. pending() finds it through the delegation registry
(never by walking every cell) and answers an unchanged revision from its last walk;
decide() grants or revokes that exact request only for the founder; the machine
approve route refuses a social delegation outright; the HTTP routes refuse a missing
session, a missing CSRF token and a non-founder subject; a machine session cannot
reach /social-approve at all. No provider, credential or network is used.
"""
from __future__ import annotations

import hashlib
import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from nodelang import existing_workshop_social_execution as social
from nodelang import commit_intent, model_router, social_approval, social_custody
from nodelang import social_linkedin_signin as signin
from nodelang.cell_adapters import UserConsentBroker, read_permission
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_connector_execution import read_connector_delegation
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    approve_universal_baboom_connector_execution, begin_universal_runtime_agent_session,
    build_universal_application, claim_universal_governed_work, create_universal_governed_work,
)
from nodelang.universal_cell import InvalidCell
from tests_replica.test_settings_terminal_routes import call, server  # noqa: F401  (fixture)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


_CURRENT = {}


def world():
    return _CURRENT["world"]


@pytest.fixture(autouse=True)
def social_world(request, tmp_path, monkeypatch):
    """A real in-memory application server (the execution-gate court's own), its founder
    runtime session, and nothing mocked. Tests that need only HTTP skip it."""
    social_approval._PENDING_CACHE.update(key=None, items=())
    if "server" in request.fixturenames:
        yield
        return
    from tests_replica.test_workshop_execution_gate import _serve
    served, _descriptor, _provider = _serve("in-memory", tmp_path, monkeypatch)
    store, registry = served.universal_store, served.universal_registry
    context = registry.authorization.session.context()
    founder_id = uuid4().hex
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="founder runtime"):
        founder, _ = begin_universal_runtime_agent_session(store, registry,
            session_root="app:agent-session:runtime:social-approval-founder-" + founder_id, runtime="*",
            external_session_fingerprint=_digest(founder_id.encode()),
            catalog_entry_root="app:agent-body-catalog:entry:founder-runtime", authentication_context=context)
    binding = SimpleNamespace(subject_root=registry.authorization.subject_root, context=context)
    _CURRENT["world"] = SimpleNamespace(store=store, registry=registry, context=context, founder=founder,
                                        server=served, binding=binding)
    try:
        yield
    finally:
        _CURRENT.pop("world", None)
        served.close()


def prepared(name, text="Open house on Friday"):
    """A real prepared social Work: planned and researched in the Workshop by the founder,
    claimed by a BABOOM execution session; its delegation is requested, not yet approved."""
    from tests_replica.test_workshop_execution_gate import TARGET, _container, _founder_post
    w = world()
    inputs = {"operation": "linkedin.post", "account_id": "urn:li:person:782bbtaQ",
              "vault_entry": "social-linkedin-founder", "arguments": {"text": text}}
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="social Work"):
        session, _ = begin_universal_runtime_agent_session(w.store, w.registry,
            session_root="app:agent-session:runtime:social-approval-" + name, runtime="baboom-execution",
            external_session_fingerprint=_digest(name.encode()),
            catalog_entry_root="app:agent-body-catalog:entry:baboom-execution", authentication_context=w.context)
        work, _, _ = create_universal_governed_work(w.store, w.registry, title="Social " + name,
            description="One founder-requested social effect", x=400.0, y=400.0,
            external_key="court:social-approval:" + name,
            structured_references={"inputs": inputs, "cde-container": _container("court:social-approval:" + name)},
            compact_references=True, select_created=False, authentication_context=w.context)
        claim_universal_governed_work(w.store, w.registry, agent_session_root=session.root_id,
                                      work_root=work, authentication_context=w.context)
    _founder_post(w.server, "plan", [work], [], "social-plan-" + name)
    _founder_post(w.server, "research", [work], [], "social-research-" + name, capture=TARGET)
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="prepare social"):
        return social.prepare_social_work(w.server, work_root=work, session_root=session.root_id,
                                          context=w.context, note="")


def _decide(server, binding, body):
    """decide() as the browser route calls it: inside the user's declared action."""
    with commit_intent.declare(commit_intent.USER_ACTION, actor=binding.subject_root, reason="founder decision"):
        return social_approval.decide(server, binding, body)


def _lifecycle(delegation_root):
    w = world()
    snapshot = w.store.snapshot()
    delegation = read_connector_delegation(snapshot, w.registry.baboom_connector_execution_protocol,
                                           w.registry.adapter_protocol, delegation_root)
    state = read_permission(snapshot, w.registry.adapter_protocol, delegation.permission_root).lifecycle_root
    return {root: name for name, root in w.registry.adapter_protocol.states.items()}[state]


# -- the real graph ----------------------------------------------------------------
def test_pending_lists_the_real_prepared_post_with_its_exact_digest():
    w = world()
    request = prepared("listed", "Open house on Friday")
    items = social_approval.pending(w.server, w.binding)
    assert [item["delegation"] for item in items] == [request["delegation"]]
    item = items[0]
    assert item["operation"] == "linkedin.post" and item["account_id"] == "urn:li:person:782bbtaQ"
    assert "Open house on Friday" in item["review_text"] and len(item["input_digest"]) == 64


def test_the_founder_approves_the_exact_post_once_and_a_changed_digest_is_refused():
    w = world()
    request = prepared("approved")
    item = social_approval.pending(w.server, w.binding)[0]
    with pytest.raises(AuthorizationDenied):
        _decide(w.server, w.binding, {"delegation": item["delegation"], "input_digest": "0" * 64,
                                                     "decision": "approve"})
    assert _lifecycle(request["delegation"]) == "requested"
    answer = _decide(w.server, w.binding, {"delegation": item["delegation"],
                                                          "input_digest": item["input_digest"], "decision": "approve"})
    assert answer["decision"] == "approved" and _lifecycle(request["delegation"]) == "granted"
    assert social_approval.pending(w.server, w.binding) == [], "an approved post is no longer waiting"


def test_deny_revokes_the_request_so_it_can_never_be_granted():
    w = world()
    request = prepared("denied")
    item = social_approval.pending(w.server, w.binding)[0]
    answer = _decide(w.server, w.binding, {"delegation": item["delegation"],
                                                          "input_digest": item["input_digest"], "decision": "deny"})
    assert answer["decision"] == "denied" and _lifecycle(request["delegation"]) == "revoked"
    with pytest.raises(InvalidCell):
        _decide(w.server, w.binding, {"delegation": item["delegation"],
                                                     "input_digest": item["input_digest"], "decision": "approve"})


def test_a_subject_other_than_the_founder_neither_lists_nor_decides():
    w = world()
    prepared("other-subject")
    stranger = SimpleNamespace(subject_root=w.registry.agent_body.session.root_id, context=w.context)
    with pytest.raises(AuthorizationDenied):
        social_approval.pending(w.server, stranger)
    item = social_approval.pending(w.server, w.binding)[0]
    with pytest.raises(AuthorizationDenied):
        _decide(w.server, stranger, {"delegation": item["delegation"],
                                                    "input_digest": item["input_digest"], "decision": "approve"})


def test_the_machine_approve_route_never_approves_a_social_post():
    """Item 7: an agent session holding the founder runtime cannot approve a social
    delegation over the machine route; only the founder's browser gesture can."""
    w = world()
    request = prepared("machine")
    with pytest.raises(AuthorizationDenied, match="founder's browser"),             commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="machine approve"):
        approve_universal_baboom_connector_execution(w.store, w.registry, founder_agent_session_root=w.founder.root_id,
            delegation_root=request["delegation"], consent_broker=UserConsentBroker(), authentication_context=w.context)
    assert _lifecycle(request["delegation"]) == "requested"


class _NoWalk(dict):
    """A cell map that refuses to be walked: only keyed reads are allowed."""

    def __iter__(self):
        raise AssertionError("pending() walked every cell of the graph")

    def keys(self):
        raise AssertionError("pending() walked every cell of the graph")

    def items(self):
        raise AssertionError("pending() walked every cell of the graph")


def test_pending_reads_the_delegation_registry_not_every_cell_and_caches_a_revision(monkeypatch):
    import nodelang.cell_protocols as protocols
    w = world()
    request = prepared("indexed")
    real = w.store.snapshot()
    guarded = SimpleNamespace(revision=real.revision, cells=_NoWalk(real.cells), read_scope=real.read_scope)
    store = SimpleNamespace(snapshot=lambda: guarded, revision=real.revision)
    server_ = SimpleNamespace(universal_store=store, universal_registry=w.registry)
    walks = []
    original = protocols.read_relation
    monkeypatch.setattr(protocols, "read_relation", lambda *a, **k: walks.append(a[1]) or original(*a, **k))
    first = social_approval.pending(server_, w.binding)
    assert [item["delegation"] for item in first] == [request["delegation"]]
    registry_walks = len(walks)
    assert social_approval.pending(server_, w.binding) == first
    assert len(walks) == registry_walks, "an unchanged revision is answered without walking again"


# -- HTTP ---------------------------------------------------------------------------
def _http(server, method, path, body=None, *, cookie=True, csrf=True, token=None):
    headers = {"Content-Type": "application/json", "Origin": server.url}
    if cookie:
        headers["Cookie"] = "ArchHub-Session=" + (token or server.browser_session_token)
    if csrf:
        headers["X-ArchHub-CSRF"] = server.browser_csrf_token
    request = Request(server.url + path, method=method, headers=headers,
                      data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except HTTPError as refused:
        return refused.code, json.loads(refused.read() or b"{}")


BODY = {"delegation": social_approval.DELEGATION_PREFIX + "0" * 32, "input_digest": "0" * 64, "decision": "approve"}


def test_the_approval_routes_refuse_no_session_no_csrf_and_a_non_founder(server):
    assert _http(server, "GET", "/api/universal/social-approvals")[0] == 200
    assert _http(server, "GET", "/api/universal/social-approvals", cookie=False)[0] == 403
    assert _http(server, "POST", "/api/universal/social-approve", BODY, cookie=False)[0] == 403
    assert _http(server, "POST", "/api/universal/social-approve", BODY, csrf=False)[0] == 403
    registry = server.universal_registry
    authority = registry.authorization
    stranger = authority.broker.mint_authenticated_context(registry.agent_body.session.root_id, principal_roots=(),
        tenant_root=authority.tenant_root, assurance_root=authority.assurance_root, lifetime_seconds=60)
    try:
        try:
            token, stranger_csrf = server.issue_browser_session(stranger)
        except AuthorizationDenied:
            return                      # refused before any browser session exists
        headers = {"Content-Type": "application/json", "Origin": server.url, "Cookie": "ArchHub-Session=" + token,
                   "X-ArchHub-CSRF": stranger_csrf}
        for method, path, body in (("GET", "/api/universal/social-approvals", None),
                                   ("POST", "/api/universal/social-approve", BODY)):
            request = Request(server.url + path, method=method, headers=headers,
                              data=None if body is None else json.dumps(body).encode())
            with pytest.raises(HTTPError) as refused:
                urlopen(request, timeout=60)
            assert refused.value.code == 403, (path, refused.value.code)
    finally:
        authority.broker.revoke(stranger)


def test_a_machine_session_cannot_reach_social_approve(server):
    with pytest.raises((AuthorizationDenied, InvalidCell)):
        server.dispatch_universal_machine_route({"method": "POST", "path": "/api/universal/social-approve",
                                                 "body": dict(BODY)})


def _memory_custody(monkeypatch):
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: (
        before_replace() if before_replace else None, put(entries))[1])
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    return entries


def test_the_finish_route_enrolls_the_linkedin_named_account_as_verified_in_custody(server, monkeypatch):
    entries = _memory_custody(monkeypatch)
    taken = []

    class Ready:
        active = False

        def take(self):
            if taken:
                raise signin.LinkedInNotReady("no verified LinkedIn account is waiting")
            taken.append(1)
            return "urn:li:person:782bbtaQ", "AQX-token"

    monkeypatch.setattr(signin, "_current", Ready())
    status, answer = _http(server, "POST", "/api/universal/social-linkedin-finish", {})
    assert status == 200 and answer["account_binding"] == "provider-verified", answer
    stored = json.loads(entries["social-linkedin-782bbtaQ"])
    assert stored["account_binding"] == "provider-verified" and stored["format"] == "archhub-social-credential-2"
    assert social_custody.social_account_binding(provider="linkedin", account_id="urn:li:person:782bbtaQ",
                                                 vault_entry="social-linkedin-782bbtaQ") == "provider-verified"
    assert "AQX-token" not in json.dumps(answer)
    status, again = _http(server, "POST", "/api/universal/social-linkedin-finish", {})
    assert status == 409 and again["error_code"] == "linkedin_not_ready"


def test_an_unrelated_runtime_error_is_not_reported_as_linkedin_not_ready(server, monkeypatch):
    def broken(body, before_replace=None):
        raise RuntimeError("disk went away")
    monkeypatch.setattr(model_router, "save_linkedin_app", broken)
    status, answer = _http(server, "POST", "/api/universal/social-linkedin-app",
                           {"client_id": "86abc123xyz", "client_secret": "secret-value-1"})
    assert (status, answer.get("error_code")) == (503, "credential_change_unconfirmed"), (status, answer)


def test_cancel_stops_the_waiting_sign_in_through_the_route(server, monkeypatch):
    monkeypatch.setattr(signin, "_current", None)
    status, answer = _http(server, "POST", "/api/universal/social-linkedin-signin", {"cancel": True})
    assert status == 200 and answer["phase"] == "idle", answer
    attempt = signin.LinkedInSignIn("86abc123xyz", "secret-value-1", port=0, wait_seconds=30,
                                    opener=lambda url: None)
    monkeypatch.setattr(signin, "_current", attempt.start())
    status, answer = _http(server, "POST", "/api/universal/social-linkedin-signin", {"cancel": True})
    assert status == 200 and answer["phase"] == "failed" and answer["error"] == "cancelled", answer
    assert not attempt.thread.is_alive()


# -- v2.1: the review of v2 ---------------------------------------------------------------
def _authorize(request):
    from nodelang.universal_application import authorize_universal_baboom_connector_execution
    w = world()
    return authorize_universal_baboom_connector_execution(w.store, w.registry, agent_session_root=request["worker"],
        delegation_root=request["delegation"], authentication_context=w.context)


def test_execution_is_refused_while_the_post_is_not_approved():
    request = prepared("unapproved-execute")
    with pytest.raises((AuthorizationDenied, InvalidCell), match="not granted|denied|approv"):
        _authorize(request)


def test_deny_after_approve_revokes_so_the_post_is_not_postable():
    """A second tab or a stale list: the post is approved, then Denied. Deny's promise,
    "It will not be posted", must be true."""
    w = world()
    request = prepared("deny-after-approve")
    item = social_approval.pending(w.server, w.binding)[0]
    body = {"delegation": item["delegation"], "input_digest": item["input_digest"]}
    assert _decide(w.server, w.binding, {**body, "decision": "approve"})["decision"] == "approved"
    assert _authorize(request).root_id == request["delegation"], "approved: execution is admitted"
    assert _decide(w.server, w.binding, {**body, "decision": "deny"})["decision"] == "denied"
    assert _lifecycle(request["delegation"]) == "revoked"
    with pytest.raises((AuthorizationDenied, InvalidCell), match="not granted|denied|approv"):
        _authorize(request)


def test_deny_is_refused_honestly_once_the_post_was_sent(monkeypatch):
    w = world()
    request = prepared("deny-after-send")
    item = social_approval.pending(w.server, w.binding)[0]
    body = {"delegation": item["delegation"], "input_digest": item["input_digest"]}
    _decide(w.server, w.binding, {**body, "decision": "approve"})
    monkeypatch.setattr(social_approval, "_sent", lambda snapshot, registry, root: root == request["delegation"])
    with pytest.raises(InvalidCell, match="already sent"):
        _decide(w.server, w.binding, {**body, "decision": "deny"})
    assert _lifecycle(request["delegation"]) == "granted", "nothing is claimed that is not true"


def test_the_soonest_expiring_posts_are_listed_first_even_past_the_limit(monkeypatch):
    import nodelang.cell_protocols as protocols
    w = world()
    first = prepared("soonest")                    # created first: expires first
    prepared("later")
    original = protocols.read_relation
    monkeypatch.setattr(protocols, "read_relation", lambda *a, **k: tuple(reversed(original(*a, **k))))
    monkeypatch.setattr(social_approval, "PENDING_LIMIT", 1)
    assert [item["delegation"] for item in social_approval.pending(w.server, w.binding)] == [first["delegation"]]


def test_the_card_says_whether_linkedin_confirmed_the_account(monkeypatch):
    w = world()
    prepared("binding")
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    assert social_approval.pending(w.server, w.binding)[0]["account_binding"] == "unknown"
    model_router.save_social_credential({"vault_entry": "social-linkedin-founder", "provider": "linkedin",
                                         "account_id": "urn:li:person:782bbtaQ", "token": "AQX-token"}, verified=True)
    social_approval._PENDING_CACHE.update(key=None, items=())
    item = social_approval.pending(w.server, w.binding)[0]
    assert item["account_binding"] == "provider-verified" and "AQX-token" not in json.dumps(item)
