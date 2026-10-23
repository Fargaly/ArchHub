"""Six networks, one custody and founder approval path; physical HTTP is fake."""
from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nodelang import commit_intent, model_router, social_approval, social_custody
from nodelang import existing_workshop_social_execution as social
from nodelang import social_connectors as connectors
from nodelang.social_http_host import SocialHttpHost
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.universal_cell import InvalidCell
from nodelang.universal_application import (
    begin_universal_runtime_agent_session, create_universal_governed_work,
    claim_universal_governed_work, issue_universal_baboom_connector_execution_grant,
)
from tests_replica.test_social_approval_graph import world, _decide, _authorize
from tests_replica import test_social_approval_graph as approval_graph


@pytest.fixture
def social3_world(request, tmp_path, monkeypatch):
    # Only the six end-to-end courts need the application graph. Payload and
    # custody courts remain pure and do not build another application world.
    yield from approval_graph.social_world.__wrapped__(request, tmp_path, monkeypatch)


CASES = [
    ("instagram.reply", "meta", "123", {"comment_id": "456", "message": "Thank you"}, {"id": "789"}),
    ("facebook.page_post", "meta", "123", {"message": "Open house"}, {"id": "123_789"}),
    ("linkedin.post", "linkedin", "urn:li:person:member", {"text": "Open house"}, {}),
    ("whatsapp.message", "whatsapp", "123", {"to": "201001234567", "text": "Reply"},
     {"messages": [{"id": "wamid.fake"}]}),
    ("x.post", "x", "123", {"text": "Open house"}, {"data": {"id": "789"}}),
    ("tiktok.video_post", "tiktok", "open.id", {"video_url": "https://media.example/video.mp4",
        "title": "Open house", "privacy_level": "SELF_ONLY"},
     {"data": {"publish_id": "publish-789"}, "error": {"code": "ok"}}),
]


def _prepare(case):
    from tests_replica.test_workshop_execution_gate import TARGET, _container, _founder_post
    operation, provider, account_id, arguments, _answer = case
    w, name = world(), uuid4().hex
    inputs = {"operation": operation, "account_id": account_id,
              "vault_entry": "social-" + provider + "-founder", "arguments": arguments}
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="six-network draft"):
        session, _ = begin_universal_runtime_agent_session(w.store, w.registry,
            session_root="app:agent-session:runtime:social3-" + name, runtime="baboom-execution",
            external_session_fingerprint=hashlib.sha256(name.encode()).hexdigest(),
            catalog_entry_root="app:agent-body-catalog:entry:baboom-execution", authentication_context=w.context)
        work, _, _ = create_universal_governed_work(w.store, w.registry, title="Social3 " + operation,
            description="One approval-required provider effect", x=400.0, y=400.0,
            external_key="court:social3:" + name,
            structured_references={"inputs": inputs, "cde-container": _container("court:social3:" + name)},
            compact_references=True, select_created=False, authentication_context=w.context)
        claim_universal_governed_work(w.store, w.registry, agent_session_root=session.root_id,
                                     work_root=work, authentication_context=w.context)
    _founder_post(w.server, "plan", [work], [], "social3-plan-" + name)
    _founder_post(w.server, "research", [work], [], "social3-research-" + name, capture=TARGET)
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="prepare six-network draft"):
        prepared = social.prepare_social_work(w.server, work_root=work, session_root=session.root_id,
                                             context=w.context, note="")
    return prepared, inputs


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_each_network_requires_shared_approval_then_dispatches_once(case, monkeypatch, social3_world):
    w = world()
    entries, dispatched = {}, []
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    request, inputs = _prepare(case)
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="fake callback enrollment"):
        social_custody.enroll_social_account(w.server,
            {"vault_entry": inputs["vault_entry"], "provider": case[1], "account_id": case[2],
             "token": "fake-custody-bearer", "display_name": "@founder"}, require_admission=lambda: None, verified=True)
    with pytest.raises((AuthorizationDenied, InvalidCell), match="not granted|denied|approv"):
        _authorize(request)
    assert dispatched == []
    item = next(row for row in social_approval.pending(w.server, w.binding)
                if row["delegation"] == request["delegation"])
    assert item["account_binding"] == "provider-verified"
    decision = _decide(w.server, w.binding, {"delegation": item["delegation"],
        "input_digest": item["input_digest"], "decision": "approve"})
    assert decision["decision"] == "approved"
    assert _authorize(request).root_id == request["delegation"]

    class FakeConnection:
        def __init__(self, host, *args, **kwargs):
            assert host == connectors.PROVIDER_ORIGINS[case[1]]
            self.sock = SimpleNamespace(settimeout=lambda seconds: None)
        def connect(self):
            pass
        def request(self, method, target, *, body, headers):
            assert method == "POST" and headers["authorization"] == "Bearer fake-custody-bearer"
            dispatched.append((target, body))
        def getresponse(self):
            payload = [json.dumps(case[4]).encode(), b""]
            return SimpleNamespace(status=201 if case[1] == "linkedin" else 200,
                read1=lambda size: payload.pop(0),
                getheaders=lambda: [("x-restli-id", "urn:li:share:789")] if case[1] == "linkedin" else [])
        def close(self):
            pass

    monkeypatch.setattr("nodelang.social_http_host.http.client.HTTPSConnection", FakeConnection)
    w.server.social_execution_host = SocialHttpHost(social_custody.social_credential)
    w.server.social_account_binding_verifier = social_custody.social_account_binding_verifier
    monkeypatch.setattr(w.server, "_resolve_universal_machine_agent_session", lambda request: request["worker"])
    capability, grant = "fake-social3-" + uuid4().hex, "app:baboom-connector-grant:" + uuid4().hex
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="approved grant"):
        _, expires, _ = issue_universal_baboom_connector_execution_grant(w.store, w.registry,
            agent_session_root=request["worker"], delegation_root=request["delegation"], grant_id=grant,
            token_digest=hashlib.sha256(capability.encode()).hexdigest(), expires_at=time.time() + 60,
            authentication_context=w.context)
    w.server._connector_execution_capabilities[capability] = {"grant": grant,
        "delegation": request["delegation"], "session": request["worker"], "expires_at": expires}
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="approved fake dispatch"):
        result = social.execute_social_work(w.server, request, {"grant": grant, "capability": capability},
                                            False, w.context)
    assert result["outcome"] == "succeeded", result
    assert len(dispatched) == 1
    assert capability not in w.server._connector_execution_capabilities
    assert "fake-custody-bearer" not in json.dumps(result)
    if case[1] == "tiktok":
        assert result["result"]["publish_state"] == "processing"


@pytest.mark.parametrize("provider,account", [("whatsapp", "123"), ("x", "123"), ("tiktok", "open.id")])
def test_new_networks_reuse_verified_custody_and_preserve_display_name(provider, account, monkeypatch):
    entries = {}
    monkeypatch.setattr(model_router, "_mutate_protected_entries", lambda put, before_replace=None, **kw: put(entries))
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    name = "social-" + provider + "-founder"
    model_router.save_social_credential({"vault_entry": name, "provider": provider, "account_id": account,
                                        "token": "fake-provider-bearer", "display_name": "@founder"}, verified=True)
    record = model_router._social_record(entries[name])
    assert record["display_name"] == "@founder"
    monkeypatch.setattr(model_router, "_application_secrets_store", lambda: SimpleNamespace(
        SECRETS_FILE="unused-fake", archive_legacy_credentials=lambda: None,
        credential_names=lambda: [], load_credential=lambda name: None))
    monkeypatch.setattr(model_router, "_credential_file_bytes", lambda path: b"")
    monkeypatch.setattr(model_router, "_protected_credential_entries", lambda store, raw: entries)
    listing = model_router.list_social_credentials()
    assert listing["items"][0]["display_name"] == "@founder"
    assert "fake-provider-bearer" not in json.dumps(listing)
    assert social_custody.social_account_binding(provider=provider, account_id=account, vault_entry=name) == "provider-verified"
    assert social_custody.social_credential(provider=provider, account_id=account, vault_entry=name) == "fake-provider-bearer"
    with pytest.raises(InvalidCell, match="another provider account"):
        social_custody.social_credential(provider=provider, account_id="other", vault_entry=name)
    assert model_router.revoke_social_credential({"vault_entry": name, "provider": provider,
                                                "account_id": account})["state"] == "removed"


def test_official_reply_payloads_and_tiktok_never_claims_published():
    x, _ = connectors.social_material_from_values({"operation": "x.reply", "account_id": "123",
        "vault_entry": "social-x-founder", "arguments": {"post_id": "789", "text": "Thank you"}})
    assert json.loads(x.body)["reply"] == {"in_reply_to_tweet_id": "789"}
    wa, _ = connectors.social_material_from_values({"operation": "whatsapp.message", "account_id": "123",
        "vault_entry": "social-whatsapp-founder", "arguments": {"to": "201001234567", "text": "Thank you", "reply_to": "wamid.fake"}})
    assert json.loads(wa.body)["context"] == {"message_id": "wamid.fake"}
    assert "tiktok.reply" not in connectors.WORK_OPERATIONS


def test_instagram_posting_stages_use_admitted_work_inputs_and_honest_async_status():
    from urllib.parse import parse_qs, urlsplit

    def material(operation, arguments):
        return connectors.social_material_from_values({"operation": "instagram." + operation,
            "account_id": "123", "vault_entry": "social-meta-ig-founder", "arguments": arguments})[0]

    create = material("container_create", {"ig_user_id": "456",
        "image_url": "https://media.example/photo.jpg", "caption": "Open house"})
    assert create.url == connectors.GRAPH_API + "/456/media"
    assert parse_qs(create.body.decode()) == {"image_url": ["https://media.example/photo.jpg"],
                                             "caption": ["Open house"]}
    answer = connectors.normalize_work_answer(create, 200, {}, b'{"id":"789"}')
    assert answer["container_id"] == "789"

    status = material("container_status", {"container_id": answer["container_id"]})
    target = urlsplit(status.url)
    assert target.path.endswith("/789")
    assert parse_qs(target.query) == {"fields": ["status_code"]}
    waiting = connectors.normalize_work_answer(status, 200, {}, b'{"status_code":"IN_PROGRESS"}')
    ready = connectors.normalize_work_answer(status, 200, {}, b'{"status_code":"FINISHED"}')
    assert waiting["status_code"] == "IN_PROGRESS" and waiting["next_step"] == "wait"
    assert ready["status_code"] == "FINISHED" and ready["next_step"] == "publish"

    publish = material("media_publish", {"ig_user_id": "456", "container_id": "789"})
    assert publish.url == connectors.GRAPH_API + "/456/media_publish"
    assert parse_qs(publish.body.decode()) == {"creation_id": ["789"]}
    assert connectors.normalize_work_answer(publish, 200, {}, b'{"id":"101112"}')["media_id"] == "101112"
    assert create.effect == publish.effect == "write" and status.effect == "read"
