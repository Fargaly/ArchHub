"""ArchHub Marketplace client — browse, install, uninstall signed packs.

The desktop counterpart to `cloud_backend/marketplace.py`. Handles the
network round-trips against the cloud backend, re-verifies the Ed25519
signature on the downloaded zip before touching the filesystem, and
unzips approved packs into
`%APPDATA%/ArchHub/marketplace_skills/<pack_id>/` so the skill loader
picks them up automatically.

Security model
--------------
The backend already verified the signature on upload — but the wire
between cloud and desktop is just TLS. A compromised proxy or DNS could
swap the bytes; that's why we re-verify locally using the pubkey the
backend echoes back in the `X-Pack-Pubkey` header. The pubkey itself
isn't yet pinned (Phase 2: trust list per-author), so this guards
against transit tampering, not against a malicious uploader.

Public API
----------
    list_packs(query=None, category=None, cursor=None) -> dict
    install_pack(pack_id: str) -> dict
    uninstall_pack(pack_id: str) -> dict
    list_installed() -> list[dict]
    upload_pack(zip_path, signature_path, pubkey_path, manifest_path) -> dict
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional

import cloud_client


# Override at test time by monkeypatching this module attribute.
INSTALL_ROOT_ENV = "ARCHHUB_MARKETPLACE_DIR"


def install_root() -> Path:
    """Where downloaded packs are unzipped. Honors an env override for
    tests; otherwise lands under %APPDATA% on Windows and ~/.archhub on
    POSIX so the local skill loader can find them."""
    override = os.environ.get(INSTALL_ROOT_ENV)
    if override:
        base = Path(override)
    else:
        # APPDATA = Roaming on Windows; fall back gracefully elsewhere.
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "ArchHub" / "marketplace_skills"
        else:
            base = Path.home() / ".archhub" / "marketplace_skills"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# HTTP — wraps cloud_client._request so auth headers are attached. We
# can't reach the private helper directly, so we replicate the small
# surface we need (Authorization header + JSON body) here. urllib is
# imported lazily so test monkeypatching is easier.
# ---------------------------------------------------------------------------
def _http_request(method: str, path: str, *,
                  body: Optional[dict] = None,
                  raw_body: Optional[bytes] = None,
                  raw_content_type: Optional[str] = None,
                  expect_bytes: bool = False,
                  auth: bool = True,
                  timeout: float = 30.0) -> dict:
    import urllib.error
    import urllib.request

    url = f"{cloud_client.base_url()}{path}"
    headers: dict[str, str] = {"User-Agent": "ArchHub-desktop/1.0"}
    if not expect_bytes:
        headers["Accept"] = "application/json"
    if auth:
        token = cloud_client.current_token()
        if not token:
            return {"status": "error", "error": "not_signed_in"}
        headers["Authorization"] = f"Bearer {token}"

    data: Optional[bytes] = None
    if raw_body is not None:
        data = raw_body
        if raw_content_type:
            headers["Content-Type"] = raw_content_type
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            resp_headers = {k: v for k, v in resp.getheaders()}
            if expect_bytes:
                return {"status": "ok",
                        "bytes": raw,
                        "headers": resp_headers,
                        "http_status": resp.status}
            text = raw.decode("utf-8", errors="replace")
            try:
                payload = json.loads(text) if text else {}
            except Exception:
                payload = {"raw": text}
            return {"status": "ok", "json": payload,
                    "headers": resp_headers,
                    "http_status": resp.status}
    except urllib.error.HTTPError as e:
        try:
            err_text = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_text) if err_text else {}
        except Exception:
            err_json = {}
        return {"status": "error", "error": f"http_{e.code}",
                "json": err_json}
    except urllib.error.URLError as e:
        return {"status": "error", "error": "unreachable",
                "detail": str(e.reason)}
    except Exception as e:
        return {"status": "error", "error": type(e).__name__,
                "detail": str(e)}


# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------
def list_packs(query: Optional[str] = None,
               category: Optional[str] = None,
               cursor: Optional[str] = None,
               verified_only: bool = True,
               limit: int = 20) -> dict:
    """Fetch the marketplace listing from the cloud backend. Returns the
    parsed response on success or {"status": "error", ...} on failure."""
    params: list[str] = []
    if query:
        params.append(f"query={_q(query)}")
    if category:
        params.append(f"category={_q(category)}")
    if cursor:
        params.append(f"cursor={_q(cursor)}")
    params.append(f"verified_only={'true' if verified_only else 'false'}")
    params.append(f"limit={int(limit)}")
    qs = "&".join(params)
    r = _http_request("GET", f"/marketplace/packs?{qs}", auth=False)
    if r["status"] != "ok":
        return r
    return r.get("json") or {"packs": [], "next_cursor": None}


def _q(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s), safe="")


def get_pack(pack_id: str) -> dict:
    r = _http_request("GET", f"/marketplace/packs/{pack_id}", auth=False)
    if r["status"] != "ok":
        return r
    return r.get("json") or {}


# ---------------------------------------------------------------------------
# Install — download + re-verify + unzip
# ---------------------------------------------------------------------------
def _verify_local(zip_bytes: bytes, signature_b64: str,
                  pubkey_b64: str) -> tuple[bool, str]:
    """Mirror the backend verification — same Ed25519 over raw zip bytes."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except Exception as ex:
        return False, f"crypto_unavailable:{ex}"
    try:
        sig = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError):
        return False, "signature_not_base64"
    try:
        pub = base64.b64decode(pubkey_b64, validate=True)
    except (binascii.Error, ValueError):
        return False, "pubkey_not_base64"
    try:
        pk = Ed25519PublicKey.from_public_bytes(pub)
    except Exception:
        return False, "pubkey_invalid"
    try:
        pk.verify(sig, zip_bytes)
    except InvalidSignature:
        return False, "signature_mismatch"
    return True, "ok"


def install_pack(pack_id: str) -> dict:
    """Download, verify, and unpack a marketplace pack.

    On success returns {"status": "ok", "path": <str>, "skill_count": N,
    "pack_id": ..., "version": ...}. On signature mismatch returns
    {"status": "error", "error": "signature mismatch — refusing to install"}.
    Idempotent: re-installing the same pack with the same version is a
    no-op."""
    root = install_root()
    target = root / _safe_id(pack_id)

    # Idempotency: if we already have a marker file with the same pack_id
    # + version we skip the download entirely. Detail is checked first to
    # save bandwidth.
    detail = get_pack(pack_id)
    if not isinstance(detail, dict) or "id" not in detail:
        if isinstance(detail, dict) and detail.get("status") == "error":
            return detail
        return {"status": "error", "error": "pack_not_found"}
    expected_version = detail.get("version") or "0.0.0"
    marker = target / ".archhub_pack.json"
    if target.exists() and marker.exists():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
            if existing.get("version") == expected_version:
                return {"status": "ok", "path": str(target),
                        "skill_count": _count_skills(target),
                        "pack_id": pack_id, "version": expected_version,
                        "idempotent": True}
        except Exception:
            # Marker corrupt — fall through and re-install.
            pass

    r = _http_request("GET", f"/marketplace/packs/{pack_id}/download",
                      auth=False, expect_bytes=True)
    if r["status"] != "ok":
        return r
    zip_bytes = r.get("bytes") or b""
    headers = r.get("headers") or {}
    # urllib lower-cases canonical headers but preserves the case the
    # server used; cover both.
    signature = (headers.get("X-Pack-Signature")
                 or headers.get("x-pack-signature") or "")
    pubkey = (headers.get("X-Pack-Pubkey")
              or headers.get("x-pack-pubkey") or "")
    if not signature or not pubkey:
        return {"status": "error",
                "error": "signature mismatch — refusing to install",
                "detail": "missing_signature_headers"}

    ok, reason = _verify_local(zip_bytes, signature, pubkey)
    if not ok:
        return {"status": "error",
                "error": "signature mismatch — refusing to install",
                "detail": reason}

    # Wipe any previous version, then unzip atomically into the target.
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Defense-in-depth: refuse zip entries that try to escape the
            # target directory via absolute paths or `..` traversal.
            for member in zf.namelist():
                if member.startswith("/") or ".." in Path(member).parts:
                    shutil.rmtree(target, ignore_errors=True)
                    return {"status": "error",
                            "error": "unsafe_zip_path",
                            "detail": member}
            zf.extractall(target)
    except zipfile.BadZipFile:
        shutil.rmtree(target, ignore_errors=True)
        return {"status": "error", "error": "bad_zip"}

    # Drop a marker file so list_installed + idempotent re-install work.
    marker_data = {
        "pack_id": pack_id,
        "version": expected_version,
        "title": detail.get("title", ""),
        "slug": detail.get("slug", ""),
        "signature": signature,
        "pubkey": pubkey,
        "manifest": detail.get("manifest", {}),
        "source": "marketplace",
    }
    marker.write_text(json.dumps(marker_data, indent=2), encoding="utf-8")

    return {"status": "ok",
            "path": str(target),
            "skill_count": _count_skills(target),
            "pack_id": pack_id,
            "version": expected_version}


def _safe_id(pack_id: str) -> str:
    """Strip anything that could escape the install root."""
    bad = set('<>:"/\\|?*\0')
    safe = "".join(c for c in str(pack_id) if c not in bad and c != "..")
    return safe or "pack"


def _count_skills(target: Path) -> int:
    """Count .json / .skill files in the unzipped pack — used as the
    UI's 'N skills installed' number."""
    if not target.exists():
        return 0
    n = 0
    for p in target.rglob("*"):
        if p.name == ".archhub_pack.json":
            continue
        if p.is_file() and p.suffix.lower() in (".json", ".skill"):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Uninstall — drop the dir
# ---------------------------------------------------------------------------
def uninstall_pack(pack_id: str) -> dict:
    root = install_root()
    target = root / _safe_id(pack_id)
    if not target.exists():
        return {"status": "ok", "removed": False, "pack_id": pack_id}
    shutil.rmtree(target, ignore_errors=True)
    return {"status": "ok", "removed": True, "pack_id": pack_id}


# ---------------------------------------------------------------------------
# Installed inventory
# ---------------------------------------------------------------------------
def list_installed() -> list[dict]:
    """Scan the install dir for marker files and return one record per
    installed pack. Missing / corrupt markers are skipped silently."""
    root = install_root()
    out: list[dict] = []
    if not root.exists():
        return out
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        marker = child / ".archhub_pack.json"
        if not marker.exists():
            continue
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["path"] = str(child)
        data["skill_count"] = _count_skills(child)
        data["source"] = data.get("source", "marketplace")
        out.append(data)
    return out


# ---------------------------------------------------------------------------
# Author flow — upload a pack to the backend
# ---------------------------------------------------------------------------
def upload_pack(zip_path: str, signature_path: str, pubkey_path: str,
                manifest_path: str) -> dict:
    """Author-side helper. Reads the four artifacts off disk and POSTs
    them as multipart/form-data to /marketplace/packs."""
    z = Path(zip_path)
    s = Path(signature_path)
    k = Path(pubkey_path)
    m = Path(manifest_path)
    for p in (z, s, k, m):
        if not p.exists():
            return {"status": "error", "error": "missing_file",
                    "detail": str(p)}
    zip_bytes = z.read_bytes()
    signature = s.read_text(encoding="utf-8").strip()
    pubkey = k.read_text(encoding="utf-8").strip()
    manifest = m.read_text(encoding="utf-8").strip()
    body, content_type = _encode_multipart({
        "pack_zip": (z.name, zip_bytes, "application/zip"),
        "signature": signature,
        "pubkey": pubkey,
        "manifest": manifest,
    })
    r = _http_request("POST", "/marketplace/packs",
                      raw_body=body,
                      raw_content_type=content_type)
    if r["status"] != "ok":
        return r
    return r.get("json") or {}


def _encode_multipart(fields: dict) -> tuple[bytes, str]:
    """Hand-rolled multipart encoder so we don't need to pull in `requests`.
    Field values can be either a string or a (filename, bytes, mime) tuple."""
    import secrets
    boundary = "archhub" + secrets.token_hex(16)
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}".encode("ascii"))
        if isinstance(value, tuple):
            filename, data, mime = value
            parts.append(
                f'Content-Disposition: form-data; name="{name}";'
                f' filename="{filename}"'.encode("ascii")
            )
            parts.append(f"Content-Type: {mime}".encode("ascii"))
            parts.append(b"")
            parts.append(data)
        else:
            parts.append(
                f'Content-Disposition: form-data; name="{name}"'.encode("ascii")
            )
            parts.append(b"")
            parts.append(str(value).encode("utf-8"))
    parts.append(f"--{boundary}--".encode("ascii"))
    parts.append(b"")
    body = crlf.join(parts)
    return body, f"multipart/form-data; boundary={boundary}"
