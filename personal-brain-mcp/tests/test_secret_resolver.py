"""Brain #32 · secret_resolver tests.

The resolver turns an ``op://vault/item/field`` reference into a value via
(in order) the 1Password CLI, Windows Credential Manager, then an
``OP_<VAULT>_<ITEM>_<FIELD>`` env-var fallback. Plain (non-op) strings
pass through unchanged.

These tests NEVER invoke the real ``op`` CLI — ``shutil.which`` is
monkeypatched to None so the subprocess branch is skipped, and keyring is
monkeypatched off so resolution falls through to the env fallback / None
deterministically regardless of the developer's machine.
"""
from __future__ import annotations

import personal_brain.secret_resolver as sr
import pytest
from personal_brain.secret_resolver import parse_op_ref, resolve_secret


def _no_external(monkeypatch):
    """Disable the op CLI (which→None) and keyring (import→raise) so the
    only live paths are env-fallback + None."""
    monkeypatch.setattr(sr.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        sr, "_try_keyring", lambda *_a, **_k: None
    )


# ── parse_op_ref ──────────────────────────────────────────────────


def test_parse_op_ref_valid_returns_triple():
    assert parse_op_ref("op://vault/item/field") == ("vault", "item", "field")


def test_parse_op_ref_plain_string_returns_none():
    assert parse_op_ref("plaintext-key") is None
    assert parse_op_ref("") is None


def test_parse_op_ref_malformed_returns_none():
    # Fewer than 3 segments after the scheme is not a usable reference.
    assert parse_op_ref("op://vault/item") is None
    assert parse_op_ref("op://vault") is None


# ── resolve_secret ────────────────────────────────────────────────


def test_resolve_secret_plain_passthrough(monkeypatch):
    _no_external(monkeypatch)
    assert resolve_secret("plaintext") == "plaintext"


def test_resolve_secret_env_fallback(monkeypatch):
    """op ref with the matching env var set and no `op` binary → env value."""
    _no_external(monkeypatch)
    monkeypatch.setenv("OP_V_I_F", "value-from-env")
    assert resolve_secret("op://V/I/F") == "value-from-env"


def test_resolve_secret_unresolvable_returns_none(monkeypatch):
    """op ref with nothing available (no CLI, no keyring, no env) → None."""
    _no_external(monkeypatch)
    monkeypatch.delenv("OP_V_I_F", raising=False)
    assert resolve_secret("op://V/I/F") is None


def test_resolve_secret_falsy_returns_none(monkeypatch):
    _no_external(monkeypatch)
    assert resolve_secret("") is None


def test_resolve_secret_env_name_normalises_dash(monkeypatch):
    """`-` in any segment maps to `_` in the env-var name."""
    _no_external(monkeypatch)
    monkeypatch.setenv("OP_MY_VAULT_R2_KEY_ACCESS_KEY", "AKIA-NORM")
    assert resolve_secret("op://my-vault/r2-key/access-key") == "AKIA-NORM"


# -- ensure_secret ----------------------------------------------------------


def test_ensure_secret_creates_once_and_never_returns_the_value(monkeypatch):
    """Provisioning is idempotent and exposes metadata, never key material."""
    ref = "op://archhub/roma-verify/signing_key"
    stored = {}
    writes = []

    monkeypatch.setattr(sr, "_try_op_cli", lambda _ref: None)
    monkeypatch.delenv("OP_ARCHHUB_ROMA_VERIFY_SIGNING_KEY", raising=False)
    monkeypatch.setattr(
        sr, "_try_keyring",
        lambda vault, item, field: stored.get((vault, item, field)),
    )

    def fake_store(vault, item, field, value):
        writes.append((vault, item, field))
        stored[(vault, item, field)] = value
        return True

    monkeypatch.setattr(sr, "_store_keyring", fake_store)

    first = sr.ensure_secret(ref)
    secret = stored[("archhub", "roma-verify", "signing_key")]
    second = sr.ensure_secret(ref)

    assert first == {
        "ok": True,
        "created": True,
        "ref": ref,
        "backend": "os_keyring",
    }
    assert second == {
        "ok": True,
        "created": False,
        "ref": ref,
        "backend": "existing",
    }
    assert writes == [("archhub", "roma-verify", "signing_key")]
    assert len(secret) >= 48
    assert secret not in repr(first)
    assert secret not in repr(second)


def test_ensure_secret_rejects_non_op_and_malformed_refs(monkeypatch):
    monkeypatch.setattr(
        sr, "_store_keyring",
        lambda *_args: pytest.fail("invalid references must never be stored"),
    )

    for ref in ("plaintext", "", "op://vault/item", "op://vault/item/field/extra"):
        result = sr.ensure_secret(ref)
        assert result["ok"] is False
        assert result["created"] is False
        assert result["ref"] == ref
        assert result["backend"] == "none"


def test_ensure_secret_fails_closed_when_os_keyring_is_unavailable(monkeypatch):
    ref = "op://archhub/roma-verify/signing_key"
    generated = "GENERATED-KEY-MUST-NEVER-LEAK"

    monkeypatch.setattr(sr, "_try_op_cli", lambda _ref: None)
    monkeypatch.setattr(sr, "_try_keyring", lambda *_args: None)
    monkeypatch.setattr(sr, "_store_keyring", lambda *_args: False)
    monkeypatch.setattr(sr.secrets, "token_urlsafe", lambda _n: generated)
    monkeypatch.delenv("OP_ARCHHUB_ROMA_VERIFY_SIGNING_KEY", raising=False)

    result = sr.ensure_secret(ref)

    assert result["ok"] is False
    assert result["created"] is False
    assert result["backend"] == "none"
    assert generated not in repr(result)
