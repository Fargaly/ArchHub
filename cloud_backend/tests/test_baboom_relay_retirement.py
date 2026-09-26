"""Court that the retired BABOOM relay cannot become a cloud authority again."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_cloud_backend_does_not_serve_retired_baboom_relay_routes():
    import main

    route_paths = {
        getattr(route, "path", "")
        for route in main.app.routes
    }

    assert not any(path.startswith("/v1/baboom") for path in route_paths)

    with TestClient(main.app) as client:
        response = client.get("/v1/baboom/commands")

    assert response.status_code == 404
