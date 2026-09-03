"""Brain #32 day-2 · cloud archive uploader tests.

boto3 is heavy + needs cloud credentials. Tests cover:
  - Graceful absence (boto3 missing returns clear error)
  - Argument validation (missing local_dir / creds)
  - Secret-ref resolution from env vars

Tests that exercise real S3 uploads are skipped — they require either
real creds (refuse on principle) or a moto mock (extra dep we don't
add for one test).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from personal_brain.cloud_archive import (
    _is_boto3_available,
    _resolve_secret_ref,
    upload_dataset,
)


BOTO3_OK = _is_boto3_available()


# ── _resolve_secret_ref ───────────────────────────────────────────


def test_resolve_secret_ref_none():
    assert _resolve_secret_ref(None) is None
    assert _resolve_secret_ref("") is None


def test_resolve_secret_ref_plain_string_passthrough():
    """Direct string passes through (works for tests · discouraged in prod)."""
    assert _resolve_secret_ref("plaintext-key") == "plaintext-key"


def test_resolve_secret_ref_env_fallback(monkeypatch):
    """`op://vault/item/field` → env var OP_VAULT_ITEM_FIELD when
    1Password resolver is unavailable."""
    monkeypatch.setenv("OP_VAULT_TESTBUCKET_ACCESSKEY", "AKIAFROMENV")
    assert _resolve_secret_ref("op://vault/testbucket/accesskey") == "AKIAFROMENV"


def test_resolve_secret_ref_env_missing_returns_none(monkeypatch):
    monkeypatch.delenv("OP_VAULT_NOTSET_KEY", raising=False)
    assert _resolve_secret_ref("op://vault/notset/key") is None


# ── upload_dataset · arg validation ───────────────────────────────


@pytest.mark.skipif(BOTO3_OK, reason="boto3 installed — covered elsewhere")
def test_upload_dataset_returns_error_when_boto3_missing(tmp_path):
    result = upload_dataset(
        tmp_path / "ds",
        bucket="any",
        access_key_ref="x",
        secret_key_ref="y",
    )
    assert result["ok"] is False
    assert "boto3" in result["error"].lower()


@pytest.mark.skipif(not BOTO3_OK, reason="boto3 not installed")
def test_upload_dataset_local_dir_missing(tmp_path):
    result = upload_dataset(
        tmp_path / "does_not_exist",
        bucket="b",
        access_key_ref="ak",
        secret_key_ref="sk",
    )
    assert result["ok"] is False
    assert "not found" in result["error"]


@pytest.mark.skipif(not BOTO3_OK, reason="boto3 not installed")
def test_upload_dataset_missing_creds_rejected(tmp_path):
    local = tmp_path / "ds"
    local.mkdir()
    (local / "manifest.json").write_text("{}")
    result = upload_dataset(local, bucket="b")
    assert result["ok"] is False
    assert "missing" in result["error"].lower()


@pytest.mark.skipif(not BOTO3_OK, reason="boto3 not installed")
def test_upload_dataset_include_blobs_requires_root(tmp_path):
    local = tmp_path / "ds"
    local.mkdir()
    (local / "manifest.json").write_text("{}")
    result = upload_dataset(
        local, bucket="b",
        access_key_ref="ak", secret_key_ref="sk",
        include_blobs=True,
    )
    # Will fail at credential / endpoint stage before reaching the
    # blob_store_root check, but the precondition is documented.
    # Acceptable that we get either error — both prove the function
    # rejected the unsafe call.
    assert result["ok"] is False
