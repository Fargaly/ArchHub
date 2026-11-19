"""F34 / F418: Connections rows say not available yet; enrolled custody stays connected."""
from __future__ import annotations

from nodelang import social_connections


def test_missing_provider_app_is_not_available_yet(monkeypatch):
    monkeypatch.setattr(social_connections.model_router, "list_social_credentials",
                        lambda: {"items": []})
    monkeypatch.setattr(social_connections.broker, "current_status",
                        lambda provider: {"phase": "idle"})
    monkeypatch.setattr(social_connections.broker, "status",
                        lambda provider: {"state": "missing",
                                          "blocker": "LinkedIn cloud publisher app secret missing"})
    row = social_connections.connection("linkedin")
    assert row["can_connect"] is False
    assert row["state"] == "blocked"
    assert row["blocker"].startswith("not available yet")
    assert "LinkedIn cloud publisher app secret missing" in row["blocker"]


def test_enrolled_account_stays_connected_when_cloud_app_is_missing(monkeypatch):
    held = {"provider": "linkedin", "account_id": "urn:li:person:fixture",
            "vault_entry": "social-linkedin-fixture", "account_binding": "provider-verified",
            "display_name": "Fixture"}
    monkeypatch.setattr(social_connections.model_router, "list_social_credentials",
                        lambda: {"items": [held]})
    monkeypatch.setattr(social_connections.broker, "current_status",
                        lambda provider: {"phase": "idle"})
    monkeypatch.setattr(social_connections.broker, "status",
                        lambda provider: {"state": "missing",
                                          "blocker": "LinkedIn cloud publisher app secret missing"})
    row = social_connections.connection("linkedin")
    assert row["state"] == "connected"
    assert row["vault_entry"] == "social-linkedin-fixture"
    assert row["can_connect"] is False


def test_start_refuses_without_opening_browser_when_not_available(monkeypatch):
    monkeypatch.setattr(social_connections.model_router, "list_social_credentials",
                        lambda: {"items": []})
    monkeypatch.setattr(social_connections.broker, "current_status",
                        lambda provider: {"phase": "idle"})
    monkeypatch.setattr(social_connections.broker, "status",
                        lambda provider: {"state": "missing", "blocker": "developer app not created"})
    called = []
    monkeypatch.setattr(social_connections.broker, "start",
                        lambda provider: called.append(provider) or {"phase": "starting"})
    row = social_connections.start("x")
    assert called == []
    assert row["state"] == "blocked"
    assert "not available yet" in row["blocker"]
