"""Connections projection and actual browser routes; fake cloud/custody only."""
import json
import pytest

from nodelang import social_connections as connections
from nodelang import cloud_social_oauth as broker
from nodelang import model_router, social_custody
from tests_replica.test_settings_terminal_routes import call, server  # noqa: F401


NETWORKS = ("instagram", "facebook", "linkedin", "whatsapp", "x", "tiktok")


@pytest.fixture
def fake_connections(monkeypatch):
    accounts = []
    monkeypatch.setattr(model_router, "list_social_credentials", lambda: {"ok": True, "items": accounts})
    monkeypatch.setattr(broker, "status", lambda provider: {"state": "saved"})
    monkeypatch.setattr(broker, "current_status", lambda provider: {"phase": "idle"})
    return accounts


def test_six_networks_report_real_missing_configuration(fake_connections, monkeypatch):
    monkeypatch.setattr(broker, "status", lambda provider: {
        "state": "missing", "blocker": provider + " developer app not created"})
    rows = connections.rows()
    assert tuple(row["provider"] for row in rows) == NETWORKS
    assert all(row["state"] == "blocked" and "developer app not created" in row["blocker"] for row in rows)


@pytest.mark.parametrize("provider", NETWORKS)
def test_provider_callback_enrolls_existing_custody_and_projects_name(provider, fake_connections, monkeypatch):
    account = "urn:li:person:member" if provider == "linkedin" else "12345"
    current = {"phase": "ready", "account_id": account, "name": "founder"}
    monkeypatch.setattr(broker, "current_status", lambda _: current)
    def take(_):
        current["phase"] = "taken"
        return account, "fake-token"
    monkeypatch.setattr(broker, "take_verified", take)
    def enroll(owner, body, *, require_admission, verified):
        require_admission()
        assert verified and body.pop("token") == "fake-token"
        fake_connections.append({**body, "account_binding": "provider-verified"})
        return {"ok": True, "state": "enrolled"}
    monkeypatch.setattr(social_custody, "enroll_social_account", enroll)
    admitted = []
    row = connections.finish(object(), {"provider": provider}, require_admission=lambda: admitted.append(True))
    assert admitted and row["state"] == "connected"
    assert row["display_name"] == "founder"
    assert "token" not in str(row)
    # Simulate process restart: identity remains in existing custody metadata.
    monkeypatch.setattr(broker, "current_status", lambda _: {"phase": "idle"})
    assert connections.connection(provider)["display_name"] == "founder"


def test_browser_routes_use_same_connection_owner(server, fake_connections, monkeypatch):
    seen = []
    monkeypatch.setattr(broker, "start", lambda provider: seen.append(provider) or {"phase": "waiting"})
    assert len(call(server, "/api/universal/social-connections")["items"]) == 6
    for provider in NETWORKS:
        result = call(server, "/api/universal/social-connection", {"provider": provider, "action": "start"})
        assert result["connection"]["provider"] == provider
    assert seen == list(NETWORKS)
    call(server, "/api/universal/social-connection", {"provider": "x", "action": "start", "token": "forbidden"}, expected=400)
    call(server, "/api/universal/social-connection", {"provider": "unknown", "action": "start"}, expected=400)
    # Real route -> real enrollment -> real graph secret reference. Only physical
    # protected storage and provider callback transport are fake.
    entries, attempts = {}, {}
    def mutate(put, before_replace=None):
        if before_replace:
            before_replace()
        return put(entries)
    monkeypatch.setattr(model_router, "_mutate_protected_entries", mutate)
    monkeypatch.setattr(model_router, "protected_credential_entry", lambda name: entries[name])
    def identities():
        return {"ok": True, "items": [
            {key: value for key, value in {**json.loads(raw), "vault_entry": name}.items()
             if key not in ("token", "format")} for name, raw in entries.items()]}
    monkeypatch.setattr(model_router, "list_social_credentials", identities)
    monkeypatch.setattr(broker, "current_status", lambda provider: attempts.get(provider, {"phase": "idle"}))
    def take(provider):
        held = attempts[provider]
        assert held["phase"] == "ready"
        held["phase"] = "taken"
        return held["account_id"], "fake-callback-token"
    monkeypatch.setattr(broker, "take_verified", take)
    for provider in NETWORKS:
        attempts[provider] = {"phase": "ready", "account_id": "urn:li:person:member" if provider == "linkedin" else "12345", "name": "founder"}
        result = call(server, "/api/universal/social-connection", {"provider": provider, "action": "finish"})
        row = result["connection"]
        assert row["state"] == "connected" and row["display_name"] == "founder"
        record = json.loads(entries[row["vault_entry"]])
        assert record["token"] == "fake-callback-token" and record["account_binding"] == "provider-verified"
        assert "fake-callback-token" not in json.dumps(result)
    assert all(row["state"] == "connected" for row in call(server, "/api/universal/social-connections")["items"])
