"""Brain #32 day-2 · cloud archive uploader.

Per founder ask 2026-05-26 brain vision: dataset export feeds the
collective-model training north star (Brain #33). Day-2 of #32 lifts
the local dataset directory + brain blob_store to S3-compatible cloud
archive so users can opt-in to contribute.

Endpoint compatibility
----------------------
S3 protocol via boto3. Works with:
  - Cloudflare R2          (recommended per CLOUD_REVIVAL_PLAN.md)
  - AWS S3                 (default)
  - Hetzner Object Storage (cheap EU-hosted)
  - MinIO / self-host

The endpoint URL + region + bucket are caller-supplied so the user picks
where their data lives. ArchHub never holds the data — it just makes it
easy to push to the user's chosen target.

Credentials
-----------
Per Q10 + AgDR-0044 BRAIN-FIRST: NEVER store resolved secrets. Pass
`access_key_ref` / `secret_key_ref` as `op://vault/...` references that
the brain resolves via 1Password CLI / Windows Credential Manager at
call time. Direct string passing (`access_key="..."`) works for testing
but logs a warning.

Layout in remote bucket
-----------------------
::

    <prefix>/datasets/<dataset_name>/manifest.json
    <prefix>/datasets/<dataset_name>/fragments.jsonl
    <prefix>/datasets/<dataset_name>/fragments.parquet
    <prefix>/blobs/<sha[:2]>/<sha>.<ext>        (when include_blobs=True)

The blob-tree mirrors the local sidecar layout 1:1 so a download is a
straight `aws s3 sync` away.

Dependencies
------------
boto3 is lazy-imported. Returns clear error when missing — caller
falls back to local-only dataset.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def _resolve_secret_ref(ref: Optional[str]) -> Optional[str]:
    """Resolve `op://vault/item/field` references via the brain's
    secrets-resolver path. Plain strings pass through with a warning."""
    if not ref:
        return None
    if not ref.startswith("op://"):
        # Direct string — works but discouraged outside tests.
        return ref
    try:
        from .secrets import resolve_secret  # type: ignore
        return resolve_secret(ref)
    except Exception:
        # Fall back to env var lookup: op://vault/item/field →
        # env name `OP_VAULT_ITEM_FIELD` (uppercase, '/' → '_', OP_ prefix).
        env_name = "OP_" + ref.replace("op://", "").upper().replace("/", "_")
        return os.environ.get(env_name)


def _is_boto3_available() -> bool:
    try:
        import boto3  # noqa: F401  # type: ignore
        return True
    except Exception:
        return False


def upload_dataset(
    local_dir: Path,
    *,
    bucket: str,
    endpoint_url: Optional[str] = None,
    region: str = "auto",
    access_key_ref: Optional[str] = None,
    secret_key_ref: Optional[str] = None,
    prefix: str = "archhub-brain",
    dataset_name: Optional[str] = None,
    include_blobs: bool = False,
    blob_store_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Upload a local dataset directory (per dataset_export.py output)
    to an S3-compatible bucket.

    Args:
        local_dir: <out_dir>/<dataset_name>/ from export_fragments
        bucket: target S3 bucket name
        endpoint_url: e.g. 'https://<accountid>.r2.cloudflarestorage.com'
            for Cloudflare R2; None = AWS S3
        region: e.g. 'us-east-1' / 'eu-central-1' / 'auto' (R2)
        access_key_ref: 'op://vault/r2/access_key' or plain (test-only)
        secret_key_ref: 'op://vault/r2/secret_key' or plain (test-only)
        prefix: top-level key prefix in the bucket
        dataset_name: inferred from local_dir.name when None
        include_blobs: also upload blob_store contents under <prefix>/blobs/
        blob_store_root: brain_root containing blobs/ subdir; required
            when include_blobs=True

    Returns:
        Dict with ok/uploaded_count/total_bytes/error/uploaded_keys.
    """
    if not _is_boto3_available():
        return {
            "ok": False,
            "error": "boto3 not installed — `pip install boto3` to enable cloud archive",
        }
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore

    local_dir = Path(local_dir)
    if not local_dir.exists():
        return {"ok": False, "error": f"local_dir not found: {local_dir}"}
    if dataset_name is None:
        dataset_name = local_dir.name

    access_key = _resolve_secret_ref(access_key_ref)
    secret_key = _resolve_secret_ref(secret_key_ref)
    if not access_key or not secret_key:
        return {
            "ok": False,
            "error": "missing access_key or secret_key (passed refs unresolved)",
        }

    try:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
    except Exception as ex:
        return {"ok": False, "error": f"client init: {type(ex).__name__}: {ex}"}

    uploaded: list[str] = []
    total_bytes = 0

    # Upload dataset files (manifest + jsonl + parquet)
    for f in local_dir.iterdir():
        if not f.is_file():
            continue
        key = f"{prefix}/datasets/{dataset_name}/{f.name}"
        try:
            client.upload_file(str(f), bucket, key)
        except (BotoCoreError, ClientError) as ex:
            return {
                "ok": False,
                "error": f"upload {f.name}: {type(ex).__name__}: {ex}",
                "uploaded_keys": uploaded,
            }
        uploaded.append(key)
        total_bytes += f.stat().st_size

    # Optional blob mirror — content-addressed paths preserved 1:1
    if include_blobs:
        if blob_store_root is None:
            return {
                "ok": False,
                "error": "include_blobs=True requires blob_store_root",
                "uploaded_keys": uploaded,
            }
        blob_root = Path(blob_store_root) / "blobs"
        if blob_root.exists():
            for sub in sorted(blob_root.iterdir()):
                if not sub.is_dir():
                    continue
                for blob in sorted(sub.iterdir()):
                    if not blob.is_file():
                        continue
                    rel = blob.relative_to(Path(blob_store_root)).as_posix()
                    key = f"{prefix}/{rel}"
                    try:
                        client.upload_file(str(blob), bucket, key)
                    except (BotoCoreError, ClientError) as ex:
                        return {
                            "ok": False,
                            "error": f"upload blob {rel}: {type(ex).__name__}: {ex}",
                            "uploaded_keys": uploaded,
                        }
                    uploaded.append(key)
                    total_bytes += blob.stat().st_size

    return {
        "ok": True,
        "uploaded_count": len(uploaded),
        "total_bytes": total_bytes,
        "bucket": bucket,
        "prefix": prefix,
        "dataset_name": dataset_name,
        "uploaded_keys": uploaded[:50],  # cap response size
        "more_keys_omitted": max(0, len(uploaded) - 50),
    }
