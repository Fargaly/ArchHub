"""Tests for `resolver_registry.ResolverRegistry`.

The registry is the references-only secrets backbone (BRAIN-FIRST +
ANTI-LIE mandates). These tests do NOT exercise the real 1Password CLI
or real Windows Credential Manager — that's manual verification on the
deployed box. We DO verify:
  * imports cleanly
  * env://, file://, inline: resolvers work in-process
  * unknown prefixes return {"error": ...} rather than raising
  * alias roundtrip is references-only (refuses raw values)
  * `secrets_store.load_api_key` still works via the legacy path when
    the registry has no alias for the provider
  * `provider_meta` reflects the source on every load
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# ---------------------------------------------------------------------------
# 1. import smoke
# ---------------------------------------------------------------------------
def test_resolver_registry_imports():
    from resolver_registry import (
        ResolverRegistry,
        OnePasswordResolver,
        WindowsCredentialManagerResolver,
        EnvVarResolver,
        FileResolver,
        InlineResolver,
    )
    reg = ResolverRegistry()
    status = reg.resolver_status()
    assert {"1password", "wcm", "env", "file", "inline"} <= set(status.keys())


# ---------------------------------------------------------------------------
# 2. env resolver
# ---------------------------------------------------------------------------
def test_envvar_resolver(monkeypatch):
    from resolver_registry import ResolverRegistry
    monkeypatch.setenv("ARCHHUB_TEST_KEY", "sk-abcd1234")
    reg = ResolverRegistry()
    out = reg.resolve("env://ARCHHUB_TEST_KEY")
    assert out["value"] == "sk-abcd1234"
    assert out["resolver"] == "env"
    assert out["last4"] == "...1234"


def test_envvar_resolver_missing(monkeypatch):
    from resolver_registry import ResolverRegistry
    monkeypatch.delenv("ARCHHUB_TEST_MISSING", raising=False)
    reg = ResolverRegistry()
    out = reg.resolve("env://ARCHHUB_TEST_MISSING")
    assert "error" in out
    assert "env" in out["error"]


# ---------------------------------------------------------------------------
# 3. unknown prefix → error, never raise
# ---------------------------------------------------------------------------
def test_unknown_prefix_returns_error():
    from resolver_registry import ResolverRegistry
    reg = ResolverRegistry()
    out = reg.resolve("vault://something/key")
    assert "error" in out
    out = reg.resolve("")
    assert "error" in out


# ---------------------------------------------------------------------------
# 4. inline resolver emits the deprecation warning AND returns the value
# ---------------------------------------------------------------------------
def test_inline_resolver_with_warning(capsys):
    from resolver_registry import ResolverRegistry
    reg = ResolverRegistry()
    out = reg.resolve("inline:abcd-secret-xyz")
    assert out["value"] == "abcd-secret-xyz"
    assert out["resolver"] == "inline"
    captured = capsys.readouterr()
    assert "deprecated" in captured.err.lower()


# ---------------------------------------------------------------------------
# 5. file resolver — reads + warns
# ---------------------------------------------------------------------------
def test_file_resolver_with_warning(tmp_path, capsys):
    from resolver_registry import ResolverRegistry
    secret_file = tmp_path / "k.txt"
    secret_file.write_text("file-secret-9999\n", encoding="utf-8")
    reg = ResolverRegistry()
    out = reg.resolve(f"file://{secret_file}")
    assert out["value"] == "file-secret-9999"
    assert out["resolver"] == "file"
    captured = capsys.readouterr()
    assert "not recommended" in captured.err.lower()


# ---------------------------------------------------------------------------
# 6. alias roundtrip — references only, raw values rejected
# ---------------------------------------------------------------------------
def test_register_alias_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # Re-import so module-level APP_DIR picks up the override.
    if "resolver_registry" in sys.modules:
        del sys.modules["resolver_registry"]
    from resolver_registry import ResolverRegistry
    reg = ResolverRegistry()
    monkeypatch.setenv("ARCHHUB_ALIAS_TEST", "alias-value-7777")

    reg.register_alias("anthropic-test", "env://ARCHHUB_ALIAS_TEST")
    assert reg.get_alias("anthropic-test") == "env://ARCHHUB_ALIAS_TEST"

    aliases_file = tmp_path / "ArchHub" / "secrets" / "aliases.json"
    assert aliases_file.exists()
    data = json.loads(aliases_file.read_text(encoding="utf-8"))
    assert data == {"anthropic-test": "env://ARCHHUB_ALIAS_TEST"}

    out = reg.resolve_alias("anthropic-test")
    assert out["value"] == "alias-value-7777"
    assert out["resolver"] == "env"

    # Raw value masquerading as a reference must be refused.
    with pytest.raises(ValueError):
        reg.register_alias("openai", "sk-rawvalue-not-a-ref")


# ---------------------------------------------------------------------------
# 7. secrets_store.load_api_key still works via legacy path
# ---------------------------------------------------------------------------
def test_legacy_load_api_key_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # Force reloads so module-level APP_DIR picks up the override.
    for mod in ("secrets_store", "resolver_registry"):
        if mod in sys.modules:
            del sys.modules[mod]
    import secrets_store

    # Stub out the developer's real OS keyring so this test is hermetic.
    # Otherwise the host machine's stored ANTHROPIC key leaks in.
    monkeypatch.setattr(secrets_store, "_try_keyring", lambda: None)

    # No alias registered → registry returns error → keyring stubbed →
    # falls through to env-var fallback.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-legacy-1111")
    v = secrets_store.load_api_key("anthropic")
    assert v == "sk-env-legacy-1111"
    assert secrets_store.provider_meta["source"] == "env"
    assert secrets_store.provider_meta["last4"] == "...1111"


def test_load_api_key_via_alias_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for mod in ("secrets_store", "resolver_registry"):
        if mod in sys.modules:
            del sys.modules[mod]
    import secrets_store
    from resolver_registry import ResolverRegistry

    monkeypatch.setenv("ARCHHUB_VIA_ALIAS", "via-alias-2222")
    ResolverRegistry().register_alias("anthropic", "env://ARCHHUB_VIA_ALIAS")

    v = secrets_store.load_api_key("anthropic")
    assert v == "via-alias-2222"
    assert secrets_store.provider_meta["source"] == "alias"
    assert secrets_store.provider_meta["resolver"] == "env"
    assert secrets_store.provider_meta["last4"] == "...2222"


def test_resolver_status_shape():
    from resolver_registry import ResolverRegistry
    status = ResolverRegistry().resolver_status()
    for name, info in status.items():
        assert "prefix" in info and "available" in info
        assert isinstance(info["available"], bool)
