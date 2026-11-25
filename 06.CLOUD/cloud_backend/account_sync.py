"""Account sync (D-051): the one per-account store that follows an ArchHub account to every PC.

Per account, under the replica volume: ``<REPLICAS_ROOT>/<user_id>/account_sync/``
holds ``manifest.sqlite3`` (one head per logical path, a monotonic sequence)
and content-addressed blobs. Whole-file last-writer-wins: a write whose
``base_sha256`` is not the current head still wins, and the answer names the
displaced head (``conflict_sha256``) so the device keeps a visible copy.

Namespaces are logical-path prefixes. ``connections/<entry>.json`` holds a
social/connector grant record; it is the one namespace allowed to carry a
credential, so its blobs are Fernet ciphertext under a random key the cloud
makes at first use (account_sync.key on the data volume, owner-only) and every other namespace refuses
secret-like content at ingress. A connection's refresh token stays in
``connection_refresh/`` beside the store and is never served.
Not yet here (D-051 parts owned by their builders): the Workshop JSONL log routes.
"""
from __future__ import annotations

import base64
import contextlib
import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.request  # also loads urllib.parse and urllib.error
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException, Query

import brain_replica
import db

router = APIRouter()
_LOG = logging.getLogger(__name__)
_PATH = re.compile(r"[a-z][a-z0-9_-]{0,31}/[A-Za-z0-9][A-Za-z0-9 ._()-]{0,159}")
_SHA = re.compile(r"[0-9a-f]{64}")
_ENTRY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_USER = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DEVICE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_MAX_BYTES = 8 * 1024 * 1024
_CONNECTIONS = "connections/"
_CONNECTION_FIELDS = {"format", "provider", "account_id", "token", "account_binding", "display_name"}
_REFRESHABLE = frozenset({"x", "tiktok", "linkedin"})
_STORED_AT_CONSUME = frozenset({"linkedin", "whatsapp", "x", "tiktok"})  # Meta pages are chosen on the desktop
_refresher = None  # tests replace the provider refresh call
_LOCK_WAIT = 10   # seconds a manifest write waits for another writer
_PROVIDER_WAIT = 20   # seconds a provider token refresh may take


class SyncKeyUnavailable(RuntimeError):
    pass


# ------------------------------------------------------------------ storage --

def _root(user_id: str) -> Path:
    if not _USER.fullmatch(user_id or ""):
        raise HTTPException(status_code=400, detail="account_sync_invalid_account")
    root = Path(brain_replica.DEFAULT_REPLICAS_ROOT) / user_id / "account_sync"
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "manifest.sqlite3").exists():
        with _manifest(root) as con:
            _ensure(con)
    return root


@contextlib.contextmanager
def _manifest(root: Path):
    """One manifest transaction: committed on success, always closed."""
    con = sqlite3.connect(root / "manifest.sqlite3", timeout=_LOCK_WAIT)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def _ensure(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS items (logical_path TEXT PRIMARY KEY, sha256 TEXT NOT NULL,"
                " size INTEGER NOT NULL, updated_at INTEGER NOT NULL, device_id TEXT NOT NULL,"
                " deleted INTEGER NOT NULL, seq INTEGER NOT NULL)")
    return con


_KEY_CACHE: Fernet | None = None
_KEY_LOCK = threading.Lock()


def _key_path() -> Path:
    # On the data volume beside the replicas tree, never inside a user's folder.
    return Path(brain_replica.DEFAULT_REPLICAS_ROOT).parent / "account_sync.key"


def _fernet() -> Fernet:
    """The connections key: random, made by the cloud at first use, kept owner-only on the data volume.

    Never derived from or wrapped with an OAuth or other configured secret, never in env, logs or answers.
    If the volume loses it, a new key is made and every older connection reads as "needs reconnect"
    (Fernet authenticates, so nothing is ever decrypted wrong); a PC still holding it re-uploads it.
    """
    global _KEY_CACHE
    with _KEY_LOCK:
        if _KEY_CACHE is not None:
            return _KEY_CACHE
        path = _key_path()
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                handle = None  # another worker made it first: read theirs
            if handle is not None:
                with os.fdopen(handle, "wb") as out:
                    out.write(Fernet.generate_key())
                    out.flush()
                    os.fsync(out.fileno())
        try:
            _KEY_CACHE = Fernet(path.read_bytes().strip())
        except (OSError, ValueError) as exc:
            raise SyncKeyUnavailable("account sync key unreadable") from exc
        return _KEY_CACHE


class NeedsReconnect(SyncKeyUnavailable):
    """A stored connection this cloud's key cannot open (key lost with the volume)."""


def _blob_path(root: Path, sha: str) -> Path:
    return root / "blobs" / sha[:2] / sha


def _write_blob(root: Path, logical_path: str, sha: str, content: bytes) -> None:
    path = _blob_path(root, sha)
    if path.exists() and not logical_path.startswith(_CONNECTIONS):
        return  # a connection blob is rewritten: one sealed under a lost key must heal on re-upload
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _fernet().encrypt(content) if logical_path.startswith(_CONNECTIONS) else gzip.compress(content)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _read_blob(root: Path, logical_path: str, sha: str) -> bytes | None:
    path = _blob_path(root, sha)
    if not path.is_file():
        return None
    data = path.read_bytes()
    if logical_path.startswith(_CONNECTIONS):
        try:
            return _fernet().decrypt(data)
        except InvalidToken as exc:
            raise NeedsReconnect("connection needs reconnect: its account key was lost") from exc
    try:
        return gzip.decompress(data)
    except (OSError, EOFError) as exc:
        raise SyncKeyUnavailable("account sync item unreadable") from exc


def canonical(record: dict) -> bytes:
    """The one byte form of a JSON item, shared with the desktop so hashes agree."""
    return json.dumps(record, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("ascii")


def _check(logical_path: str, content: bytes) -> None:
    if not _PATH.fullmatch(logical_path or "") or ".." in logical_path:
        raise HTTPException(status_code=400, detail="account_sync_invalid_path")
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="account_sync_item_too_large")
    if logical_path.startswith(_CONNECTIONS):
        try:
            record = json.loads(content)
        except ValueError:
            raise HTTPException(status_code=400, detail="account_sync_invalid_connection") from None
        fields = set(record) if isinstance(record, dict) else set()
        if (not {"format", "provider", "account_id", "token"} <= fields <= _CONNECTION_FIELDS
                or any(type(record[key]) is not str or not record[key] for key in fields)):
            raise HTTPException(status_code=400, detail="account_sync_invalid_connection")
        return
    text = content.decode("utf-8", "ignore")
    if any(prefix in text for prefix in brain_replica._SECRET_LIKE_PREFIXES):
        raise HTTPException(status_code=400, detail="account_sync_refuses_credentials")


def write_item(user_id: str, logical_path: str, content: bytes | None, *, base_sha256: str = "",
               device_id: str = "cloud") -> dict:
    """Advance one head (None content = tombstone). Last writer wins; a displaced head is named."""
    root = _root(user_id)
    if content is not None:
        _check(logical_path, content)
    elif not _PATH.fullmatch(logical_path or "") or ".." in logical_path:
        raise HTTPException(status_code=400, detail="account_sync_invalid_path")
    sha = hashlib.sha256(content).hexdigest() if content is not None else ""
    if content is not None:
        _write_blob(root, logical_path, sha, content)
    with _manifest(root) as con:
        con.execute("BEGIN IMMEDIATE")
        head = con.execute("SELECT sha256, deleted FROM items WHERE logical_path = ?", (logical_path,)).fetchone()
        seq = (con.execute("SELECT COALESCE(MAX(seq), 0) FROM items").fetchone()[0]) + 1
        con.execute("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(logical_path) DO UPDATE SET"
                    " sha256 = excluded.sha256, size = excluded.size, updated_at = excluded.updated_at,"
                    " device_id = excluded.device_id, deleted = excluded.deleted, seq = excluded.seq",
                    (logical_path, sha, len(content or b""), int(time.time()), device_id,
                     int(content is None), seq))
    answer = {"ok": True, "logical_path": logical_path, "sha256": sha, "server_seq": seq}
    displaced = head["sha256"] if head and not head["deleted"] else ""
    if displaced and displaced not in (base_sha256, sha):
        answer["conflict_sha256"] = displaced
    return answer


def read_item(user_id: str, logical_path: str) -> tuple[str, bytes] | None:
    root = _root(user_id)
    with _manifest(root) as con:
        head = con.execute("SELECT sha256, deleted FROM items WHERE logical_path = ?", (logical_path,)).fetchone()
    if not head or head["deleted"]:
        return None
    content = _read_blob(root, logical_path, head["sha256"])
    return (head["sha256"], content) if content is not None else None


# -------------------------------------------------------------- connections --

def _refresh_file(user_id: str, entry: str) -> Path:
    if not _ENTRY.fullmatch(entry or "") or ".." in entry:
        raise HTTPException(status_code=400, detail="account_sync_invalid_connection")
    return _root(user_id) / "connection_refresh" / (entry + ".fernet")


def _keep_refresh(user_id: str, entry: str, refresh: dict | None) -> None:
    path = _refresh_file(user_id, entry)
    if not refresh:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_fernet().encrypt(canonical(refresh)))


def _held_refresh(user_id: str, entry: str) -> dict:
    path = _refresh_file(user_id, entry)
    try:
        return json.loads(_fernet().decrypt(path.read_bytes())) if path.is_file() else {}
    except (InvalidToken, ValueError):
        return {}


def keep_connection(user_id: str, provider: str, account_id: str, name: str, grant: dict) -> None:
    """Consume time: the provider grant joins the account (best effort; the desktop also uploads)."""
    if provider not in _STORED_AT_CONSUME:
        return
    entry = "social-" + provider + "-" + account_id.rsplit(":", 1)[-1]
    if not _ENTRY.fullmatch(entry) or ".." in entry:
        return
    record = {"format": "archhub-social-credential-2", "provider": provider, "account_id": account_id,
              "token": grant["access_token"], "account_binding": "provider-verified",
              "display_name": str(name or account_id)[:256]}
    try:
        write_item(user_id, _CONNECTIONS + entry + ".json", canonical(record))
        _keep_refresh(user_id, entry, {
            "token": record["token"], "refresh_token": str(grant["refresh_token"]),
            "expires_at": int(time.time()) + int(grant.get("expires_in") or 0)} if grant.get("refresh_token") else None)
    except (SyncKeyUnavailable, HTTPException, ValueError, OSError) as exc:
        _LOG.warning("connection not kept on the account: %s", type(exc).__name__)


def _refresh(provider: str, refresh_token: str) -> dict:
    import social_oauth  # the broker owns provider app credentials and token URLs
    client_id, secret, _redirect = social_oauth._client_values(provider)
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    if provider == "x":
        form["client_id"] = client_id
        headers["Authorization"] = "Basic " + base64.b64encode((client_id + ":" + secret).encode()).decode()
    else:
        form.update({"client_key" if provider == "tiktok" else "client_id": client_id, "client_secret": secret})
    request = urllib.request.Request(social_oauth._TOKEN[provider], data=urllib.parse.urlencode(form).encode("ascii"),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=_PROVIDER_WAIT) as response:
        return json.loads(response.read(65536))


def connection_record(user_id: str, entry: str) -> dict | None:
    """The account's current record for one connection, refreshed server-side when due."""
    held = read_item(user_id, _CONNECTIONS + entry + ".json")
    if held is None:
        return None
    record = json.loads(held[1])
    refresh = _held_refresh(user_id, entry)
    if (not refresh or refresh.get("token") != record["token"] or not refresh.get("expires_at")
            or refresh["expires_at"] - 120 > time.time()):
        return record  # no refresh material for this token (or not due): the record is current
    if record["provider"] not in _REFRESHABLE:
        raise HTTPException(status_code=409, detail="connection_expired_reconnect")
    try:
        answer = (_refresher or _refresh)(record["provider"], refresh["refresh_token"])
        token = answer["access_token"]
        if type(token) is not str or not token:
            raise ValueError
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=409, detail="connection_expired_reconnect") from None
    record = {**record, "token": token}
    write_item(user_id, _CONNECTIONS + entry + ".json", canonical(record), base_sha256=held[0])
    _keep_refresh(user_id, entry, {"token": token,
                                   "refresh_token": str(answer.get("refresh_token") or refresh["refresh_token"]),
                                   "expires_at": int(time.time()) + int(answer.get("expires_in") or 0)}
                  if answer.get("expires_in") else None)
    return record


# ------------------------------------------------------------------- routes --

def _user(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization")
    user = db.user_for_token(authorization.split(None, 1)[1].strip())
    if not user:
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization")
    return user


def _unavailable(exc: SyncKeyUnavailable) -> HTTPException:
    if isinstance(exc, NeedsReconnect):
        return HTTPException(status_code=409, detail={"error": "connection_needs_reconnect", "blocker": str(exc)})
    return HTTPException(status_code=503, detail={"error": "account_sync_unavailable", "blocker": str(exc)})


def _needs_reconnect(root: Path, logical_path: str, sha: str) -> bool:
    try:
        _read_blob(root, logical_path, sha)
    except NeedsReconnect:
        return True
    except SyncKeyUnavailable:
        return False
    return False


@router.get("/v1/account-sync/manifest")
def manifest(since: int = Query(0, ge=0), authorization: str | None = Header(None)) -> dict:
    """Heads changed after ``since``: paths and digests only, never content."""
    user = _user(authorization)
    root = _root(user["id"])
    with _manifest(root) as con:
        rows = con.execute("SELECT * FROM items WHERE seq > ? ORDER BY seq", (since,)).fetchall()
        top = con.execute("SELECT COALESCE(MAX(seq), 0) FROM items").fetchone()[0]
    items = []
    for r in rows:
        item = {"logical_path": r["logical_path"], "sha256": r["sha256"], "size": r["size"],
                "updated_at": r["updated_at"], "device_id": r["device_id"], "deleted": bool(r["deleted"])}
        if (not r["deleted"] and r["logical_path"].startswith(_CONNECTIONS)
                and _needs_reconnect(root, r["logical_path"], r["sha256"])):
            item["needs_reconnect"] = True
        items.append(item)
    return {"ok": True, "server_seq": top, "items": items}


@router.put("/v1/account-sync/item")
def put_item(body: dict, authorization: str | None = Header(None)) -> dict:
    """{logical_path, base_sha256, device_id, content_b64 (gzip) | deleted: true}."""
    user = _user(authorization)
    path, base, device = body.get("logical_path"), body.get("base_sha256") or "", body.get("device_id") or ""
    if type(path) is not str or type(base) is not str or not _DEVICE.fullmatch(str(device)):
        raise HTTPException(status_code=400, detail="account_sync_invalid_item")
    content = None
    if body.get("deleted") is not True:
        try:
            content = gzip.decompress(base64.b64decode(str(body.get("content_b64") or ""), validate=True))
        except (ValueError, OSError, EOFError):
            raise HTTPException(status_code=400, detail="account_sync_invalid_content") from None
    try:
        answer = write_item(user["id"], path, content, base_sha256=base, device_id=device)
        if content is None and path.startswith(_CONNECTIONS):
            _keep_refresh(user["id"], path[len(_CONNECTIONS):].removesuffix(".json"), None)
        return answer
    except SyncKeyUnavailable as exc:
        raise _unavailable(exc)


@router.get("/v1/account-sync/blob/{sha256}")
def blob(sha256: str, logical_path: str = Query(...), authorization: str | None = Header(None)) -> dict:
    """One immutable blob of this account as gzip base64 (a connection blob is decrypted first)."""
    user = _user(authorization)
    if not _SHA.fullmatch(sha256) or not _PATH.fullmatch(logical_path):
        raise HTTPException(status_code=400, detail="account_sync_invalid_blob")
    try:
        content = _read_blob(_root(user["id"]), logical_path, sha256)
    except SyncKeyUnavailable as exc:
        raise _unavailable(exc)
    if content is None or hashlib.sha256(content).hexdigest() != sha256:
        raise HTTPException(status_code=404, detail="account_sync_blob_missing")
    return {"ok": True, "sha256": sha256, "content_b64": base64.b64encode(gzip.compress(content)).decode("ascii")}


@router.post("/v1/account-sync/connection/{entry}")
def connection(entry: str, authorization: str | None = Header(None)) -> dict:
    """The record to make one call with. POST, so the token never sits in a URL or cache."""
    user = _user(authorization)
    if not _ENTRY.fullmatch(entry) or ".." in entry:
        raise HTTPException(status_code=400, detail="account_sync_invalid_connection")
    try:
        record = connection_record(user["id"], entry)
    except SyncKeyUnavailable as exc:
        raise _unavailable(exc)
    if record is None:
        raise HTTPException(status_code=404, detail="account_sync_connection_missing")
    return {"ok": True, "record": record}
