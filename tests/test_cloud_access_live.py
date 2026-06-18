"""Live ArchHub Cloud access smoke test.

This intentionally hits the deployed public cloud endpoint. The CLOUD-ACCESS
lane needs one real endpoint assertion so a green local suite cannot hide a
dead Fly deployment.
"""
from __future__ import annotations

import json
import os
import urllib.request


def test_archhub_cloud_healthz_live_endpoint_returns_sane_response():
    base_url = os.environ.get(
        "ARCHHUB_CLOUD_BASE_URL", "https://archhub-cloud.fly.dev"
    ).rstrip("/")
    req = urllib.request.Request(
        f"{base_url}/healthz",
        headers={
            "Accept": "application/json",
            "User-Agent": "ArchHub-tests/1.0",
        },
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=20.0) as resp:
        body = resp.read().decode("utf-8")
        status = resp.status

    payload = json.loads(body)
    assert status == 200
    assert payload.get("ok") is True
    assert isinstance(payload.get("ts"), int)
