"""Security closure, batch C: quota hold, CORS, secrets, Gemini key, Speckle creds."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_company_creation_holds_the_trial_quota_unconditionally():
    src = _read("cloud_backend/companies.py")
    assert "    if checkout_url:\n        db.set_company_message_limit(" not in src
    hold = src.index('db.set_company_message_limit(\n        company["id"], config.PLAN_QUOTAS["trial"]')
    assert src.rfind("checkout_url = billing.create_company_checkout(", 0, hold) != -1


def test_cors_dev_origins_never_ship_in_production():
    src = _read("cloud_backend/main.py")
    assert 'allow_origins=_cors_origins(),' in src
    assert "if _HIDE_API_DOCS:\n        return list(_PROD_ORIGINS)" in src
    assert '_PROD_ORIGINS = ["https://archhub.io"]' in src


def test_inline_raw_secret_cannot_be_registered_as_an_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import importlib
    import resolver_registry as rr
    importlib.reload(rr)
    reg = rr.ResolverRegistry() if hasattr(rr, "ResolverRegistry") else rr.registry()
    with pytest.raises(ValueError, match="cannot be registered"):
        reg.register_alias("anthropic", "inline:sk-live-secret")


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is the Windows user key store")
def test_secrets_file_is_dpapi_protected_and_never_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import importlib
    import secrets_store as ss
    importlib.reload(ss)
    ss._write_file({"anthropic": "sk-test-123"})
    raw = ss.SECRETS_FILE.read_bytes()
    assert raw.startswith(b"ARCHHUB-DPAPI-1:")
    assert b"sk-test-123" not in raw
    assert ss._read_file() == {"anthropic": "sk-test-123"}


def test_gemini_key_travels_as_a_header_nowhere_in_a_url():
    for rel in ("app/llm_providers/google_client.py", "app/connectors/ai_runner.py", "app/settings_dialog.py"):
        src = _read(rel)
        assert "?key=" not in src, rel
        assert "x-goog-api-key" in src, rel


def test_speckle_compose_carries_no_fixed_credentials():
    src = _read("app/speckle_server.py")
    for literal in ("POSTGRES_PASSWORD: speckle\n", "speckle1234", "archhub-local-dev-secret-replace-in-prod"):
        assert literal not in src, literal
    assert "${SPECKLE_PG_PASSWORD}" in src and "${SPECKLE_SESSION_SECRET}" in src
    assert "env=_local_secrets_env(compose_path.parent)" in src
