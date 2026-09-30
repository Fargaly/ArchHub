"""The founder approves or denies ONE exact social post; nothing else can.

The graph readers are replaced by recorders so each refusal is checked in isolation:
another provider, an expired or changed request, another user's permission, a
malformed request. Approve mints the founder's gesture and grants once; Deny revokes.
"""
import contextlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import nodelang.cell_adapters as adapters_module
import nodelang.cell_connector_execution as connector_module
import nodelang.universal_application as app
from nodelang import social_approval
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.universal_cell import InvalidCell

ROOT = social_approval.DELEGATION_PREFIX + "a" * 32
OTHER = social_approval.DELEGATION_PREFIX + "b" * 32
DIGEST = "d" * 64
STATES = {"requested": "s:requested", "granted": "s:granted", "revoked": "s:revoked"}


def _rig(monkeypatch, *, provider="prov:li", expires=None, digest=DIGEST, lifecycle="requested", user="subject:founder"):
    calls = {"grant": [], "revoke": [], "mint": []}
    delegation = SimpleNamespace(root_id=ROOT, work_root="work:1", session_root="session:agent", provider_root=provider,
                                 input_digest=DIGEST, permission_root="permission:1",
                                 expires_at=expires if expires is not None else 4e9)
    permission = SimpleNamespace(lifecycle_root=STATES[lifecycle], user_root=user)

    @contextlib.contextmanager
    def live(context):
        yield

    registry = SimpleNamespace(
        baboom_connector_provider_roots={"social-linkedin-post": "prov:li", "workshop-project": "prov:proj"},
        baboom_connector_execution_protocol=object(), adapter_protocol=SimpleNamespace(states=STATES),
        authorization=SimpleNamespace(broker=SimpleNamespace(live_context=live, resolve=lambda context: None)))
    store = SimpleNamespace(snapshot=lambda: SimpleNamespace(revision=7, cells={ROOT: None, OTHER: None}), revision=8)
    broker = SimpleNamespace(mint_from_user_gesture=lambda permission_root, subject: calls["mint"].append((permission_root, subject)) or "gesture")
    server = SimpleNamespace(universal_store=store, universal_registry=registry, mutation_lock=threading.Lock(),
                             adapter_consent_broker=broker)
    prepared = SimpleNamespace(operation="linkedin.post", account_id="urn:li:person:782bbtaQ")
    monkeypatch.setattr(social_approval, "_founder", lambda snapshot, registry, binding: SimpleNamespace(subject_root="subject:founder"))
    monkeypatch.setattr(social_approval, "_review", lambda snapshot, registry, d: (prepared, digest, "Operation: linkedin.post\n{\"text\": \"Open house\"}"))
    monkeypatch.setattr(connector_module, "read_connector_delegation", lambda *args: delegation)
    monkeypatch.setattr(connector_module, "read_connector_provider", lambda *args: SimpleNamespace(operation="linkedin.post"))
    monkeypatch.setattr(adapters_module, "read_permission", lambda *args: permission)
    monkeypatch.setattr(adapters_module, "grant_permission", lambda *args, **kw: calls["grant"].append((args, kw)))
    monkeypatch.setattr(adapters_module, "revoke_permission", lambda store, protocol, root: calls["revoke"].append(root))
    monkeypatch.setattr(app, "_require_application_authorization", lambda *args, **kw: None)
    monkeypatch.setattr(app, "_connector_execution_catalog_for_provider", lambda registry, provider: "catalog")
    monkeypatch.setattr(social_approval, "_sent", lambda snapshot, registry, root: False)
    return server, calls


def _body(decision="approve", digest=DIGEST):
    return {"delegation": ROOT, "input_digest": digest, "decision": decision}


BINDING = SimpleNamespace(subject_root="subject:founder", context="ctx")


def test_approve_mints_the_founders_gesture_and_grants_once(monkeypatch):
    server, calls = _rig(monkeypatch)
    answer = social_approval.decide(server, BINDING, _body())
    assert answer["decision"] == "approved" and answer["account_id"] == "urn:li:person:782bbtaQ"
    assert calls["mint"] == [("permission:1", "subject:founder")] and len(calls["grant"]) == 1 and calls["revoke"] == []


def test_deny_revokes_and_never_grants(monkeypatch):
    server, calls = _rig(monkeypatch)
    assert social_approval.decide(server, BINDING, _body("deny"))["decision"] == "denied"
    assert calls["revoke"] == ["permission:1"] and calls["grant"] == [] and calls["mint"] == []


@pytest.mark.parametrize("rig, body", [
    ({"provider": "prov:proj"}, _body()),
    ({"expires": 1.0}, _body()),
    ({"digest": "e" * 64}, _body()),
    ({}, _body(digest="e" * 64)),
    ({"user": "subject:someone-else"}, _body()),
])
def test_nothing_else_is_approved(monkeypatch, rig, body):
    server, calls = _rig(monkeypatch, **rig)
    with pytest.raises(AuthorizationDenied):
        social_approval.decide(server, BINDING, body)
    assert calls["grant"] == [] and calls["revoke"] == [] and calls["mint"] == []


def test_a_malformed_decision_is_refused(monkeypatch):
    server, _ = _rig(monkeypatch)
    for body in ({"delegation": ROOT, "input_digest": DIGEST, "decision": "maybe"}, {"delegation": ROOT, "decision": "approve"},
                 {"delegation": "app:other:" + "a" * 32, "input_digest": DIGEST, "decision": "approve"}):
        with pytest.raises(InvalidCell):
            social_approval.decide(server, BINDING, body)


def test_the_card_and_routes_are_wired():
    from nodelang.universal_application import _APPLICATION_HTTP_ROUTE_SPECS
    declared = {(method, path) for method, path, _ in _APPLICATION_HTTP_ROUTE_SPECS}
    assert ("GET", "/api/universal/social-approvals") in declared and ("POST", "/api/universal/social-approve") in declared
    studio = Path(social_approval.__file__).resolve().parent / "studio"
    page = (studio / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "<SettingsSocialApprovals transport={transport}/>" in page and "Approve this post" in page and ">Deny<" in page
    transport = (studio / "studio-existing-workshop.js").read_text(encoding="utf-8")
    assert "post('/api/universal/social-approve', {delegation, input_digest, decision})" in transport