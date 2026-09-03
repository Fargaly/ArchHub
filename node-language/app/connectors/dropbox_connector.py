"""Dropbox connector — drives the Dropbox HTTP API v2.

Implements the uniform `connectors.base.Connector` contract. Many
practices keep their drawing sets, references and deliverables on
Dropbox; ArchHub lets the agent list, fetch and (carefully) write
those files from the canvas.

Mechanism: REST. Dropbox v2 splits across two hosts:
  * RPC endpoints   — https://api.dropboxapi.com/2  (JSON in, JSON out)
  * content endpoints — https://content.dropboxapi.com/2  (file bytes;
    parameters travel in the `Dropbox-API-Arg` header)

Auth model
----------
  Dropbox uses OAuth2 access tokens. The user generates one in the
  Dropbox App Console (scoped app -> Generate access token) and pastes
  it. We send it as a bearer token. We do not refresh; a 401 means the
  token expired and must be re-pasted.

Settings keys read (via secrets_store):
  dropbox  — load_api_key('dropbox') : the OAuth2 access token

Operations
----------
  READ    dropbox.list_folder        — entries under a path
          dropbox.get_metadata       — metadata of one file/folder
          dropbox.list_revisions     — revision history of a file
          dropbox.download           — fetch file bytes (kind="read")
  ACTION  dropbox.upload             — write a file (destructive)
          dropbox.create_shared_link — create a share link (destructive)

Every operation returns an `OpResult`; nothing raises to the caller.
list_folder walks Dropbox's `has_more` / `cursor` pagination.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from connectors.base import (
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
    register,
)

# ---------------------------------------------------------------------------
RPC_BASE = "https://api.dropboxapi.com/2"
CONTENT_BASE = "https://content.dropboxapi.com/2"
DEFAULT_TIMEOUT_SECONDS = 60       # content transfers can be slow
SECRET_KEY = "dropbox"
MAX_PAGES = 20                     # list_folder pagination cap
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024   # 25 MB guard for download op


# ---------------------------------------------------------------------------
def _load_token() -> Optional[str]:
    """Pull the saved Dropbox OAuth2 access token, or None if missing."""
    try:
        from secrets_store import load_api_key
        v = load_api_key(SECRET_KEY)
        return v or None
    except Exception:
        return None


def _token_hint() -> str:
    return ("Dropbox token not set. Open Settings -> Sign-ins -> Dropbox "
            "and paste an OAuth2 access token from the Dropbox App "
            "Console (your app -> Generate access token).")


def _norm_path(path: Any) -> str:
    """Normalise a Dropbox path. Dropbox wants '' for the root and a
    leading slash otherwise; it rejects a literal '/'."""
    p = str(path or "").strip()
    if p in ("", "/"):
        return ""
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or ""


# ---------------------------------------------------------------------------
def _rpc(path: str, body: dict, *, token: str,
         timeout: int = DEFAULT_TIMEOUT_SECONDS,
         _retry: bool = True) -> dict:
    """Run one Dropbox RPC call (JSON in, JSON out).

    Returns {"_ok": True, "data": {...}} or {"_err": "...",
    "http_status": int?}. A 429 gets one retry with backoff.
    """
    url = RPC_BASE.rstrip("/") + "/" + path.lstrip("/")
    # Dropbox RPC requires a JSON body; some endpoints take `null`.
    data = json.dumps(body if body is not None else None).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        if ex.code == 429 and _retry:
            time.sleep(_retry_after(ex))
            return _rpc(path, body, token=token, timeout=timeout,
                        _retry=False)
        try:
            payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        return {"_err": _classify_http(ex.code, payload),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Dropbox: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}

    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        return {"_err": "Dropbox returned a non-JSON response."}
    if not isinstance(parsed, dict):
        return {"_err": "Dropbox returned an unexpected response shape."}
    return {"_ok": True, "data": parsed}


def _content_request(path: str, api_arg: dict, *, token: str,
                     upload_bytes: Optional[bytes] = None,
                     timeout: int = DEFAULT_TIMEOUT_SECONDS,
                     _retry: bool = True) -> dict:
    """Run one Dropbox content-endpoint call.

    Parameters travel JSON-encoded in the `Dropbox-API-Arg` header. For
    a download `upload_bytes` is None and the body is the file. For an
    upload `upload_bytes` carries the file content.

    Returns:
      download: {"_ok": True, "content": bytes, "meta": {...}}
      upload:   {"_ok": True, "data": {...}}
      failure:  {"_err": "...", "http_status": int?}
    """
    url = CONTENT_BASE.rstrip("/") + "/" + path.lstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Dropbox-API-Arg": json.dumps(api_arg),
        # Content endpoints require this exact content type.
        "Content-Type": "application/octet-stream",
    }
    req = urllib.request.Request(url, data=upload_bytes or b"",
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            meta_hdr = resp.headers.get("Dropbox-API-Result") \
                if resp.headers else None
    except urllib.error.HTTPError as ex:
        if ex.code == 429 and _retry:
            time.sleep(_retry_after(ex))
            return _content_request(path, api_arg, token=token,
                                    upload_bytes=upload_bytes,
                                    timeout=timeout, _retry=False)
        try:
            payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        return {"_err": _classify_http(ex.code, payload),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Dropbox: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}

    if upload_bytes is not None:
        # Upload — the response body is JSON metadata.
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {"_err": "Dropbox upload returned a non-JSON response."}
        return {"_ok": True, "data": parsed}
    # Download — body is the file; metadata is in the result header.
    meta = {}
    if meta_hdr:
        try:
            meta = json.loads(meta_hdr)
        except Exception:
            meta = {}
    return {"_ok": True, "content": raw, "meta": meta}


def _retry_after(ex: urllib.error.HTTPError) -> float:
    try:
        hdr = ex.headers.get("Retry-After") if ex.headers else None
        if hdr:
            return min(float(hdr), 30.0)
    except Exception:
        pass
    return 2.0


def _classify_http(code: int, payload: str) -> str:
    """Translate an HTTP status into an actionable message. Dropbox
    error bodies carry an `error_summary` string."""
    summary = ""
    try:
        d = json.loads(payload) if payload else {}
        if isinstance(d, dict):
            summary = str(d.get("error_summary") or "")
    except Exception:
        summary = (payload or "")[:200]
    if code == 401:
        return ("Dropbox token rejected (401). Open Settings -> Sign-ins "
                "-> Dropbox and paste a fresh OAuth2 access token.")
    if code == 403:
        return (f"Dropbox denied access (403) — the token lacks the "
                f"required scope. {summary}").strip()
    if code == 409:
        # 409 is Dropbox's catch-all endpoint error (path not found,
        # conflict, etc.) — the summary tells the user what happened.
        return f"Dropbox could not complete the request. {summary}".strip()
    if code == 429:
        return "Dropbox rate limit hit (429). Wait a moment and retry."
    if code >= 500:
        return f"Dropbox server error ({code}). Retry shortly."
    return f"Dropbox HTTP {code}: {summary}".strip()


def _simplify_entry(e: dict) -> dict:
    """Reduce a Dropbox metadata entry to a flat, readable dict."""
    tag = e.get(".tag")
    return {
        "type": tag,
        "name": e.get("name"),
        "path": e.get("path_display") or e.get("path_lower"),
        "id": e.get("id"),
        "size": e.get("size") if tag == "file" else None,
        "modified": e.get("server_modified") if tag == "file" else None,
        "rev": e.get("rev") if tag == "file" else None,
        "content_hash": e.get("content_hash") if tag == "file" else None,
    }


# ---------------------------------------------------------------------------
# Operation implementations.
# ---------------------------------------------------------------------------
def _op_list_folder(path: str = "", recursive: bool = False,
                     limit: int = 200, **_: Any) -> OpResult:
    """List entries under a Dropbox folder path."""
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        cap = max(1, min(int(limit or 200), 2000))
    except Exception:
        cap = 200
    body = {
        "path": _norm_path(path),
        "recursive": bool(recursive),
        "include_deleted": False,
        "include_media_info": False,
        "limit": min(cap, 1000),
    }
    r = _rpc("files/list_folder", body, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    data = r.get("data") or {}
    entries = list(data.get("entries") or [])
    pages = 1
    # Walk has_more pagination via list_folder/continue.
    while data.get("has_more") and pages < MAX_PAGES \
            and len(entries) < cap:
        cursor = data.get("cursor")
        if not cursor:
            break
        nr = _rpc("files/list_folder/continue", {"cursor": cursor},
                  token=token)
        if "_err" in nr:
            # Return what we have rather than discarding the whole call.
            break
        data = nr.get("data") or {}
        entries.extend(data.get("entries") or [])
        pages += 1
    items = [_simplify_entry(e) for e in entries[:cap]]
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} entr"
                                  f"{'y' if len(items) == 1 else 'ies'}")


def _op_get_metadata(path: str = "", **_: Any) -> OpResult:
    """Fetch metadata for one Dropbox file or folder."""
    p = _norm_path(path)
    if not p:
        return OpResult.fail("path is required (the Dropbox root has no "
                             "metadata — give a file or folder path).")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    body = {"path": p, "include_deleted": False,
            "include_media_info": False}
    r = _rpc("files/get_metadata", body, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    out = _simplify_entry(r.get("data") or {})
    return OpResult(ok=True, value=out,
                    value_preview=f"{out.get('type')}: {out.get('name')}")


def _op_list_revisions(path: str = "", limit: int = 10,
                        **_: Any) -> OpResult:
    """List the revision history of a Dropbox file."""
    p = _norm_path(path)
    if not p:
        return OpResult.fail("path is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        lim = max(1, min(int(limit or 10), 100))
    except Exception:
        lim = 10
    body = {"path": p, "mode": "path", "limit": lim}
    r = _rpc("files/list_revisions", body, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    data = r.get("data") or {}
    revs = []
    for e in (data.get("entries") or [])[:lim]:
        revs.append({
            "rev": e.get("rev"),
            "name": e.get("name"),
            "size": e.get("size"),
            "modified": e.get("server_modified"),
            "content_hash": e.get("content_hash"),
        })
    return OpResult(ok=True,
                    value={"is_deleted": data.get("is_deleted"),
                           "revisions": revs},
                    value_preview=f"{len(revs)} revision"
                                  f"{'s' if len(revs) != 1 else ''}")


def _op_download(path: str = "", **_: Any) -> OpResult:
    """Download a Dropbox file. kind="read" — but the payload can be
    large, so the bytes are base64-encoded and capped."""
    p = _norm_path(path)
    if not p:
        return OpResult.fail("path is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    r = _content_request("files/download", {"path": p}, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    content = r.get("content") or b""
    meta = r.get("meta") or {}
    size = len(content)
    if size > MAX_DOWNLOAD_BYTES:
        return OpResult.fail(
            f"File is {size} bytes — over the {MAX_DOWNLOAD_BYTES}-byte "
            f"download cap for inline transfer. Use the Dropbox desktop "
            f"client for files this large.")
    out = {
        "path": meta.get("path_display") or p,
        "name": meta.get("name"),
        "size": meta.get("size", size),
        "rev": meta.get("rev"),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    return OpResult(ok=True, value=out,
                    value_preview=f"{out.get('name')} ({size} bytes)")


def _op_upload(path: str = "", content_base64: str = "",
               text: str = "", mode: str = "add",
               **_: Any) -> OpResult:
    """Upload a file to Dropbox. DESTRUCTIVE — writes to Dropbox.

    Provide `content_base64` (base64-encoded bytes) or `text` (a UTF-8
    string). `mode` is "add" (default — never overwrite, autorename on
    conflict) or "overwrite".
    """
    p = _norm_path(path)
    if not p:
        return OpResult.fail("path is required (the destination file "
                             "path, e.g. /Project/notes.txt).")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    payload: Optional[bytes] = None
    if content_base64 and str(content_base64).strip():
        try:
            payload = base64.b64decode(str(content_base64), validate=True)
        except Exception:
            return OpResult.fail("content_base64 is not valid base64.")
    elif text is not None and str(text) != "":
        payload = str(text).encode("utf-8")
    else:
        return OpResult.fail("Provide content_base64 or text to upload.")

    wmode = str(mode or "add").strip().lower()
    if wmode not in ("add", "overwrite"):
        return OpResult.fail("mode must be 'add' or 'overwrite'.")

    api_arg = {
        "path": p,
        "mode": wmode,
        "autorename": wmode == "add",
        "mute": True,
    }
    r = _content_request("files/upload", api_arg, token=token,
                         upload_bytes=payload)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    out = _simplify_entry(r.get("data") or {})
    return OpResult(ok=True, value=out,
                    value_preview=f"uploaded {out.get('name')} "
                                  f"({out.get('size')} bytes)")


def _op_create_shared_link(path: str = "", **_: Any) -> OpResult:
    """Create a shared link for a Dropbox file/folder. DESTRUCTIVE —
    creates a publicly resolvable URL."""
    p = _norm_path(path)
    if not p:
        return OpResult.fail("path is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    body = {"path": p, "settings": {"audience": "public",
                                    "access": "viewer"}}
    r = _rpc("sharing/create_shared_link_with_settings", body, token=token)
    if "_err" in r:
        # A link may already exist (409 shared_link_already_exists);
        # fall back to listing the existing link.
        if r.get("http_status") == 409:
            lr = _rpc("sharing/list_shared_links",
                      {"path": p, "direct_only": True}, token=token)
            if "_ok" in lr:
                links = (lr.get("data") or {}).get("links") or []
                if links:
                    link = links[0]
                    return OpResult(
                        ok=True,
                        value={"url": link.get("url"),
                               "name": link.get("name"),
                               "path": link.get("path_lower") or p,
                               "existing": True},
                        value_preview="existing link returned")
        return OpResult.fail(r["_err"])
    data = r.get("data") or {}
    out = {
        "url": data.get("url"),
        "name": data.get("name"),
        "path": data.get("path_lower") or p,
        "visibility": ((data.get("link_permissions") or {})
                       .get("resolved_visibility") or {}).get(".tag"),
        "existing": False,
    }
    return OpResult(ok=True, value=out,
                    value_preview=f"link: {out.get('url')}")


# ---------------------------------------------------------------------------
class DropboxConnector(Connector):
    """Dropbox HTTP API v2 connector."""

    host = "dropbox"
    display_name = "Dropbox"
    mechanism = "rest"

    # -- status -------------------------------------------------------
    def probe(self) -> dict:
        """Honest status:
          no token                        -> unauthorized
          token + get_current_account ok  -> live
          network / bad token             -> missing
        """
        token = _load_token()
        if not token:
            return {"status": "unauthorized", "note": _token_hint(),
                    "detail": {}}
        # Cheap real auth check — users/get_current_account.
        r = _rpc("users/get_current_account", None, token=token,
                 timeout=12)
        if "_err" in r:
            status = "unauthorized" if r.get("http_status") == 401 \
                else "missing"
            return {"status": status, "note": r["_err"], "detail": {}}
        acct = r.get("data") or {}
        name = ((acct.get("name") or {}).get("display_name")
                or acct.get("email") or "account")
        return {
            "status": "live",
            "note": f"Signed in as {name}",
            "detail": {"account_id": acct.get("account_id"),
                       "name": name,
                       "email": acct.get("email")},
        }

    # -- operations ---------------------------------------------------
    def build_ops(self) -> list:
        return [
            ConnectorOp(
                op_id="dropbox.list_folder",
                host="dropbox", kind="read",
                label="List folder",
                description="List files and folders under a Dropbox path.",
                inputs=[
                    ParamSpec(id="path", label="Path", type="text",
                              default="",
                              help="Folder path, e.g. /Projects. Blank "
                                   "lists the account root."),
                    ParamSpec(id="recursive", label="Recursive",
                              type="bool", default=False,
                              help="Descend into sub-folders."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=200,
                              help="Max entries to return (1-2000)."),
                ],
                output_type="list",
                fn=_op_list_folder,
            ),
            ConnectorOp(
                op_id="dropbox.get_metadata",
                host="dropbox", kind="read",
                label="Get metadata",
                description="Fetch metadata for one Dropbox file or "
                            "folder.",
                inputs=[
                    ParamSpec(id="path", label="Path", type="text",
                              required=True,
                              help="The file or folder path."),
                ],
                output_type="dict",
                fn=_op_get_metadata,
            ),
            ConnectorOp(
                op_id="dropbox.list_revisions",
                host="dropbox", kind="read",
                label="List revisions",
                description="List the revision history of a Dropbox file.",
                inputs=[
                    ParamSpec(id="path", label="Path", type="text",
                              required=True,
                              help="The file path."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=10,
                              help="Max revisions (1-100)."),
                ],
                output_type="dict",
                fn=_op_list_revisions,
            ),
            ConnectorOp(
                op_id="dropbox.download",
                host="dropbox", kind="read",
                label="Download file",
                description="Download a Dropbox file's content "
                            "(base64-encoded, capped at 25 MB).",
                inputs=[
                    ParamSpec(id="path", label="Path", type="text",
                              required=True,
                              help="The file path to download."),
                ],
                output_type="dict",
                fn=_op_download,
            ),
            ConnectorOp(
                op_id="dropbox.upload",
                host="dropbox", kind="action",
                label="Upload file",
                description="Upload a file to Dropbox. Writes to Dropbox.",
                inputs=[
                    ParamSpec(id="path", label="Path", type="text",
                              required=True,
                              help="Destination path, e.g. /Project/"
                                   "notes.txt."),
                    ParamSpec(id="text", label="Text content", type="text",
                              default="",
                              help="UTF-8 text to write."),
                    ParamSpec(id="content_base64",
                              label="Binary content (base64)",
                              type="text", default="",
                              help="Base64-encoded bytes (overrides "
                                   "`text`)."),
                    ParamSpec(id="mode", label="Write mode", type="choice",
                              default="add",
                              options=["add", "overwrite"],
                              help="'add' autorenames on conflict; "
                                   "'overwrite' replaces."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_upload,
            ),
            ConnectorOp(
                op_id="dropbox.create_shared_link",
                host="dropbox", kind="action",
                label="Create shared link",
                description="Create a public shared link for a Dropbox "
                            "file or folder.",
                inputs=[
                    ParamSpec(id="path", label="Path", type="text",
                              required=True,
                              help="The file or folder to share."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_create_shared_link,
            ),
        ]


# ── register at import time ─────────────────────────────────────────
register(DropboxConnector())
