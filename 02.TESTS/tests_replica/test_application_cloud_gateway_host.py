"""Courts for serving the remote gateway from the sole Universal owner."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application
from nodelang.universal_cell import CellStore


def _provider() -> MemorySigningKeyProvider:
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"o" * 32)
    provider.add_key("archhub.local.universal-cloud-dpop-nonce", b"n" * 32)
    return provider


def test_application_owner_builds_the_graph_cloud_gateway_without_a_copy(tmp_path):
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(), key_provider=provider
    )
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        cloud_host="127.0.0.1",
        cloud_port=9443,
    ).start()
    try:
        gateway = server.build_universal_cloud_gateway(
            resource_origin="https://gateway.archhub.test",
            nonce_key_provider=provider,
        )
        routes = {
            getattr(route, "path", "")
            for route in gateway.app.routes
        }
        descriptor = TestClient(gateway.app).get(
            "/api/universal/remote-runtime"
        )

        assert gateway.resource_origin == "https://gateway.archhub.test"
        assert len(gateway.runtime_id) == 64
        assert "/api/universal/work-handoff" in routes
        assert "/api/universal/baboom-capabilities" in routes
        assert descriptor.status_code == 401
        assert descriptor.headers["WWW-Authenticate"].startswith("DPoP")

        certificate = tmp_path / "certificate.pem"
        private_key = tmp_path / "private-key.pem"
        certificate.write_text("court certificate", encoding="ascii")
        private_key.write_text("court private key", encoding="ascii")
        _tls_gateway, tls_server = server.build_universal_cloud_tls_server(
            resource_origin="https://gateway.archhub.test",
            certificate_file=certificate,
            private_key_file=private_key,
            nonce_key_provider=provider,
        )

        assert tls_server.started is False
        assert tls_server.config.host == "127.0.0.1"
        assert tls_server.config.port == 9443
    finally:
        server.close()


def test_invalid_cloud_listener_never_claims_a_graph_runtime_owner(tmp_path):
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(), key_provider=provider
    )
    revision_before = store.revision

    with pytest.raises(
        ValueError,
        match="cloud gateway requires a bare HTTPS resource origin",
    ):
        ApplicationServer(
            universal_store=store,
            universal_registry=registry,
            cloud_host="127.0.0.1",
            cloud_port=9443,
            enable_universal_cloud_gateway=True,
            cloud_resource_origin="http://gateway.archhub.test",
            cloud_tls_certificate_file=tmp_path / "certificate.pem",
            cloud_tls_private_key_file=tmp_path / "private-key.pem",
            cloud_nonce_key_provider=provider,
        )

    assert store.revision == revision_before
