"""Static supply-chain and Fly lifecycle courts for the cloud package."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "packaging" / "cloud" / "Dockerfile"
LOCKFILE = ROOT / "packaging" / "cloud" / "requirements.lock"
GUIDE = ROOT / "CLOUD-RUNTIME-PACKAGING.md"
RENDERER = ROOT / "infrastructure" / "render_fly_application_config.py"
PINNED_BASE = (
    "python:3.14.6-slim-bookworm@"
    "sha256:86f975aca15cf04a40b399eebede9aea"
    "7c82eae084d1f1a0a6ef6bcaae871a30"
)
REQUIRED_RUNTIME_PACKAGES = {
    "boto3",
    "cryptography",
    "fastapi",
    "httpx",
    "joserfc",
    "psycopg",
    "psycopg-binary",
}
SECRET_NAMES = {
    "ARCHHUB_UNIVERSAL_POSTGRES_DSN",
    "ARCHHUB_AWS_KMS_HMAC_KEYS",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
}


def _renderer_module():
    spec = importlib.util.spec_from_file_location(
        "render_fly_application_config",
        RENDERER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cloud_image_is_digest_pinned_minimal_non_root_and_hash_locked():
    source = DOCKERFILE.read_text(encoding="utf-8")
    meaningful = tuple(
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    assert meaningful[0] == f"FROM {PINNED_BASE}"
    assert "FROM " not in "\n".join(meaningful[1:])
    assert " latest" not in source.lower()
    assert "ADD " not in source
    assert "curl " not in source
    assert "wget " not in source
    assert "sudo" not in source
    assert (
        "COPY packaging/cloud/requirements.lock /app/requirements.lock"
        in source
    )
    assert "COPY --chown=10001:10001 nodelang /app/nodelang" in source
    assert "COPY . " not in source
    assert (
        "python -m pip install --no-cache-dir --require-hashes "
        "-r /app/requirements.lock"
    ) in source
    assert source.index("USER 10001:10001") < source.index("CMD ")
    assert (
        'CMD ["python", "-m", "nodelang.cloud_application_entrypoint"]'
        in source
    )
    assert not SECRET_NAMES.intersection(source.split())


def test_cloud_requirement_lock_is_exact_hashed_and_complete():
    source = LOCKFILE.read_text(encoding="utf-8")
    package_lines = tuple(
        line.strip()
        for line in source.splitlines()
        if line and not line[0].isspace() and not line.startswith("#")
    )
    names = set()

    assert package_lines
    assert "--hash=sha256:" in source
    for line in package_lines:
        assert "==" in line
        assert " @ " not in line
        match = re.match(r"([A-Za-z0-9_.-]+)==", line)
        assert match is not None
        names.add(match.group(1).lower())
    assert REQUIRED_RUNTIME_PACKAGES.issubset(names)


def test_fly_config_is_rendered_without_secrets_or_false_health_claims():
    module = _renderer_module()
    rendered = module.render_fly_application_config(
        app_name="archhub-universal-court",
        primary_region="bom",
    )
    parsed = tomllib.loads(rendered)

    assert parsed["app"] == "archhub-universal-court"
    assert parsed["primary_region"] == "bom"
    assert parsed["kill_signal"] == "SIGTERM"
    assert parsed["kill_timeout"] == 120
    assert parsed["build"]["dockerfile"] == "packaging/cloud/Dockerfile"
    assert "env" not in parsed
    assert "mounts" not in parsed
    assert "processes" not in parsed
    assert len(parsed["services"]) == 1
    service = parsed["services"][0]
    assert service["internal_port"] == 8482
    assert service["protocol"] == "tcp"
    assert service["auto_stop_machines"] == "off"
    assert service["auto_start_machines"] is False
    assert service["min_machines_running"] == 0
    assert service["tcp_checks"] == [
        {
            "grace_period": "30s",
            "interval": "15s",
            "timeout": "2s",
        }
    ]
    assert not any(secret in rendered for secret in SECRET_NAMES)
    assert "/health" not in rendered


@pytest.mark.parametrize(
    ("app_name", "primary_region"),
    (
        ("UPPERCASE", "bom"),
        ("-leading", "bom"),
        ("contains secret", "bom"),
        ("archhub", "DUB"),
        ("archhub", "dubai"),
        ("archhub", "d1b"),
    ),
)
def test_fly_config_rejects_ambiguous_provider_identity(
    app_name,
    primary_region,
):
    module = _renderer_module()

    with pytest.raises(ValueError):
        module.render_fly_application_config(
            app_name=app_name,
            primary_region=primary_region,
        )


def test_packaging_guide_is_authority_accurate_and_evidence_backed():
    source = GUIDE.read_text(encoding="utf-8")

    for heading in (
        "## What",
        "## Why",
        "## How",
        "## Who",
        "## When",
        "## Where",
        "## Example",
        "## Evidence",
        "## Recovery",
        "## Open release gates",
    ):
        assert heading in source
    for phrase in (
        "TCP check proves process liveness only",
        "runtime ownership fence",
        "one Machine",
        "does not deploy",
        "does not prove release eligibility",
        "Fly Managed Postgres",
        "AWS KMS",
        "DynamoDB",
        "https://fly.io/docs/reference/configuration/",
        "https://docs.docker.com/build/building/best-practices/",
        "https://docs.astral.sh/uv/pip/compile/",
    ):
        assert phrase in source
