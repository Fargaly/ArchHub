"""Capability readiness is independent, bounded, and non-sensitive."""
from __future__ import annotations

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_readyz_reports_independent_capabilities_without_secrets_or_paths(
    client, monkeypatch, tmp_path,
):
    import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "REPLICAS_ROOT", str(tmp_path / "replicas"))
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "secret-stripe-value")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "secret-webhook-value")
    monkeypatch.setattr(config, "RESEND_API_KEY", "secret-resend-value")
    monkeypatch.setattr(config, "FROM_EMAIL", "noreply@archhub.io")
    monkeypatch.setattr(config, "stripe_price_id",
                        lambda tier, annual=False: "configured-product")

    response = client.get("/readyz")

    assert response.status_code == 200
    report = response.json()
    assert report["format"] == "archhub-capability-readiness-v1"
    assert set(report["capabilities"]) == {
        "database", "persistent_storage", "billing", "email",
        "website_publication",
    }
    assert report["ready"] is True
    assert all(item["ok"] for item in report["capabilities"].values())
    raw = response.text
    assert "secret-" not in raw
    assert str(tmp_path) not in raw
    assert "cell_native_product_complete" not in raw
    assert "monetization_ready" not in raw


def test_readyz_is_http_green_but_capability_red_when_database_is_unavailable(
    client, monkeypatch, tmp_path,
):
    import config

    missing = tmp_path / "missing" / "cloud.db"
    monkeypatch.setattr(config, "DATABASE_URL", str(missing))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "missing")
    monkeypatch.setattr(config, "REPLICAS_ROOT", str(tmp_path / "missing" / "replicas"))

    response = client.get("/readyz")

    assert response.status_code == 200
    report = response.json()
    assert report["ready"] is False
    assert report["capabilities"]["database"] == {
        "ok": False, "reason": "query_failed", "engine": "sqlite",
    }
    assert report["capabilities"]["persistent_storage"]["ok"] is False
    assert client.get("/healthz").json()["ok"] is True


def test_readiness_report_is_capability_evidence_not_product_authority(client):
    report = client.get("/readyz").json()

    assert report["format"] == "archhub-capability-readiness-v1"
    assert set(report) == {"format", "ready", "capabilities"}
    assert "cockpit" not in report["capabilities"]
    assert "brain" not in report["capabilities"]
    assert "grand_map" not in report["capabilities"]
    assert "product_complete" not in report
