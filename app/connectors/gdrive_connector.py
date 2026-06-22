"""Google Drive connector — drives the Google Drive REST API v3.

Implements the uniform `connectors.base.Connector` contract. AEC teams
increasingly keep references, deliverables and shared drawing sets on
Google Drive / Shared Drives; ArchHub lets the agent list, fetch and
(carefully) write those files from the canvas — the same shape the
Dropbox connector gives Dropbox.

Mechanism: REST. Google Drive v3 splits across two hosts:
  * metadata / RPC endpoints — https://www.googleapis.com/drive/v3
    (JSON in, JSON out: files.list, files.get, files.create folder)
  * upload endpoint          — https://www.googleapis.com/upload/drive/v3
    (multipart: JSON metadata part + raw bytes part)

Auth model
----------
  Google Drive uses OAuth2 access tokens (Bearer). The user generates one
  via the Google OAuth Playground / their own OAuth client with the
  `drive` scope and pastes it. We send it as a bearer token. We do not
  refresh; a 401 means the token expired and must be re-pasted. This
  mirrors the dropbox_connector token model exactly (ONE-SYSTEM): no new
  secrets path, no parallel auth engine — `secrets_store.load_api_key`.

Settings keys read (via secrets_store):
  gdrive  — load_api_key('gdrive') : the OAuth2 access token

Operations
----------
  READ    gdrive.list_files     — entries (files/folders) matching a query
          gdrive.get_metadata   — metadata for one file/folder by id
          gdrive.download       — fetch file bytes (base64, capped)
  ACTION  gdrive.create_folder  — create a folder (destructive)
          gdrive.upload         — upload a file (destructive, multipart)

Every operation returns an `OpResult`; nothing raises to the caller.
When no token is present every op returns an honest failure (and probe()
returns status 'unauthorized') — never fabricated data. This is the
excel_connector / dropbox_connector honest-status pattern.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional

from connectors.base import (
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
    register,
)

# ---------------------------------------------------------------------------
API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
DEFAULT_TIMEOUT_SECONDS = 60       # content transfers can be slow
SECRET_KEY = "gdrive"
MAX_PAGES = 20                     # files.list pagination cap
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024   # 25 MB guard for download op
FOLDER_MIME = "application/vnd.google-apps.folder"
# Fields requested for a listed/queried entry — keep tight + readable.
_FILE_FIELDS = "id,name,mimeType,size,modifiedTime,parents,webViewLink"


# ---------------------------------------------------------------------------
def _load_token() -> Optional[str]:
    """Pull the saved Google Drive OAuth2 access token, or None if missing."""
    try:
        from secrets_store import load_api_key
        v = load_api_key(SECRET_KEY)
        return v or None
    except Exception:
        return None


def _token_hint() -> str:
    return ("Google Drive token not set. Open Settings -> Sign-ins -> "
            "Google Drive and paste an OAuth2 access token with the "
            "'drive' scope (e.g. from the Google OAuth Playground or your "
            "own OAuth client).")


# ---------------------------------------------------------------------------
def _request(url: str, *, token: str, method: str = "GET",
             body: Optional[bytes] = None,
             headers: Optional[dict] = None,
             timeout: int = DEFAULT_TIMEOUT_SECONDS,
             raw_response: bool = False,
             _retry: bool = True) -> dict:
    """Run one Google Drive HTTP call.

    Returns:
      json call: {"_ok": True, "data": {...}}
      raw call:  {"_ok": True, "content": bytes, "ctype": str}
      failure:   {"_err": "...", "http_status": int?}
    A 429 / 5xx gets one retry with backoff.
    """
    hdrs = {"Authorization": f"Bearer {token}"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            ctype = resp.headers.get("Content-Type", "") if resp.headers \
                else ""
    except urllib.error.HTTPError as ex:
        if ex.code in (429, 500, 502, 503) and _retry:
            time.sleep(_retry_after(ex))
            return _request(url, token=token, method=method, body=body,
                            headers=headers, timeout=timeout,
                            raw_response=raw_response, _retry=False)
        try:
            err_payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            err_payload = ""
        return {"_err": _classify_http(ex.code, err_payload),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Google Drive: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}

    if raw_response:
        return {"_ok": True, "content": payload, "ctype": ctype}

    raw = payload.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        return {"_err": "Google Drive returned a non-JSON response."}
    if not isinstance(parsed, dict):
        return {"_err": "Google Drive returned an unexpected response shape."}
    return {"_ok": True, "data": parsed}


def _retry_after(ex: urllib.error.HTTPError) -> float:
    try:
        hdr = ex.headers.get("Retry-After") if ex.headers else None
        if hdr:
            return min(float(hdr), 30.0)
    except Exception:
        pass
    return 2.0


def _classify_http(code: int, payload: str) -> str:
    """Translate an HTTP status into an actionable message. Google API
    error bodies carry {"error": {"message": ...}}."""
    summary = ""
    try:
        d = json.loads(payload) if payload else {}
        if isinstance(d, dict):
            err = d.get("error")
            if isinstance(err, dict):
                summary = str(err.get("message") or "")
            elif isinstance(err, str):
                summary = err
    except Exception:
        summary = (payload or "")[:200]
    if code == 401:
        return ("Google Drive token rejected (401). Open Settings -> "
                "Sign-ins -> Google Drive and paste a fresh OAuth2 access "
                "token with the 'drive' scope.")
    if code == 403:
        return (f"Google Drive denied access (403) — the token lacks the "
                f"required scope or quota was exceeded. {summary}").strip()
    if code == 404:
        return f"Google Drive: not found (404). {summary}".strip()
    if code == 429:
        return "Google Drive rate limit hit (429). Wait a moment and retry."
    if code >= 500:
        return f"Google Drive server error ({code}). Retry shortly."
    return f"Google Drive HTTP {code}: {summary}".strip()


def _simplify_entry(e: dict) -> dict:
    """Reduce a Drive file resource to a flat, readable dict."""
    mime = e.get("mimeType")
    is_folder = mime == FOLDER_MIME
    size = e.get("size")
    try:
        size = int(size) if size is not None else None
    except Exception:
        pass
    return {
        "type": "folder" if is_folder else "file",
        "name": e.get("name"),
        "id": e.get("id"),
        "mime_type": mime,
        "size": None if is_folder else size,
        "modified": e.get("modifiedTime"),
        "parents": e.get("parents") or [],
        "web_view_link": e.get("webViewLink"),
    }


# ---------------------------------------------------------------------------
# Operation implementations.
# ---------------------------------------------------------------------------
def _op_list_files(query: str = "", parent: str = "",
                   limit: int = 200, **_: Any) -> OpResult:
    """List Drive files/folders. Optional `query` is a Drive `q` filter
    (e.g. "name contains 'plan'"); `parent` scopes to a folder id."""
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        cap = max(1, min(int(limit or 200), 1000))
    except Exception:
        cap = 200

    clauses = ["trashed = false"]
    q = str(query or "").strip()
    if q:
        clauses.append(f"({q})")
    par = str(parent or "").strip()
    if par:
        clauses.append(f"'{par}' in parents")
    q_full = " and ".join(clauses)

    entries: list[dict] = []
    page_token = ""
    pages = 0
    while pages < MAX_PAGES and len(entries) < cap:
        params = {
            "q": q_full,
            "pageSize": str(min(cap - len(entries), 1000)),
            "fields": f"nextPageToken,files({_FILE_FIELDS})",
            "spaces": "drive",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        url = f"{API_BASE}/files?" + urllib.parse.urlencode(params)
        r = _request(url, token=token)
        if "_err" in r:
            if entries:
                break        # return what we have rather than discard all
            return OpResult.fail(r["_err"])
        data = r.get("data") or {}
        entries.extend(data.get("files") or [])
        page_token = data.get("nextPageToken") or ""
        pages += 1
        if not page_token:
            break

    items = [_simplify_entry(e) for e in entries[:cap]]
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} entr"
                                  f"{'y' if len(items) == 1 else 'ies'}")


def _op_get_metadata(file_id: str = "", **_: Any) -> OpResult:
    """Fetch metadata for one Drive file or folder by id."""
    fid = str(file_id or "").strip()
    if not fid:
        return OpResult.fail("file_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    params = {"fields": _FILE_FIELDS, "supportsAllDrives": "true"}
    url = (f"{API_BASE}/files/{urllib.parse.quote(fid)}?"
           + urllib.parse.urlencode(params))
    r = _request(url, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    out = _simplify_entry(r.get("data") or {})
    return OpResult(ok=True, value=out,
                    value_preview=f"{out.get('type')}: {out.get('name')}")


def _op_download(file_id: str = "", **_: Any) -> OpResult:
    """Download a Drive file's content. kind="read" — bytes are
    base64-encoded and capped at 25 MB for inline transfer."""
    fid = str(file_id or "").strip()
    if not fid:
        return OpResult.fail("file_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    # First fetch metadata so we can name the file + reject Google-native
    # docs (which have no direct bytes — they need an export, not download).
    meta_params = {"fields": "id,name,mimeType,size",
                   "supportsAllDrives": "true"}
    murl = (f"{API_BASE}/files/{urllib.parse.quote(fid)}?"
            + urllib.parse.urlencode(meta_params))
    mr = _request(murl, token=token)
    if "_err" in mr:
        return OpResult.fail(mr["_err"])
    meta = mr.get("data") or {}
    mime = meta.get("mimeType") or ""
    if mime.startswith("application/vnd.google-apps"):
        return OpResult.fail(
            f"'{meta.get('name')}' is a Google-native document "
            f"({mime}) — it has no direct bytes to download. Use Drive's "
            f"export for these file types.")

    params = {"alt": "media", "supportsAllDrives": "true"}
    url = (f"{API_BASE}/files/{urllib.parse.quote(fid)}?"
           + urllib.parse.urlencode(params))
    r = _request(url, token=token, raw_response=True)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    content = r.get("content") or b""
    size = len(content)
    if size > MAX_DOWNLOAD_BYTES:
        return OpResult.fail(
            f"File is {size} bytes — over the {MAX_DOWNLOAD_BYTES}-byte "
            f"download cap for inline transfer. Use the Google Drive "
            f"desktop client for files this large.")
    out = {
        "id": fid,
        "name": meta.get("name"),
        "mime_type": mime,
        "size": size,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    return OpResult(ok=True, value=out,
                    value_preview=f"{out.get('name')} ({size} bytes)")


def _op_create_folder(name: str = "", parent: str = "",
                      **_: Any) -> OpResult:
    """Create a folder in Drive. DESTRUCTIVE — writes to Drive."""
    nm = str(name or "").strip()
    if not nm:
        return OpResult.fail("name is required (the folder name).")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    metadata: dict[str, Any] = {"name": nm, "mimeType": FOLDER_MIME}
    par = str(parent or "").strip()
    if par:
        metadata["parents"] = [par]
    params = {"fields": _FILE_FIELDS, "supportsAllDrives": "true"}
    url = f"{API_BASE}/files?" + urllib.parse.urlencode(params)
    body = json.dumps(metadata).encode("utf-8")
    r = _request(url, token=token, method="POST", body=body,
                 headers={"Content-Type": "application/json"})
    if "_err" in r:
        return OpResult.fail(r["_err"])
    out = _simplify_entry(r.get("data") or {})
    return OpResult(ok=True, value=out,
                    value_preview=f"created folder {out.get('name')}")


def _op_upload(name: str = "", parent: str = "", content_base64: str = "",
               text: str = "", mime_type: str = "",
               **_: Any) -> OpResult:
    """Upload a file to Drive. DESTRUCTIVE — writes to Drive.

    Provide `content_base64` (base64-encoded bytes) or `text` (a UTF-8
    string). Uses Drive's multipart upload: one JSON metadata part + one
    raw-bytes part in a single request.
    """
    nm = str(name or "").strip()
    if not nm:
        return OpResult.fail("name is required (the destination file name).")
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

    ctype = str(mime_type or "").strip() or "application/octet-stream"
    metadata: dict[str, Any] = {"name": nm}
    par = str(parent or "").strip()
    if par:
        metadata["parents"] = [par]

    # Build a multipart/related body by hand (stdlib only — ONE-SYSTEM,
    # no new HTTP dependency).
    boundary = f"archhub-{uuid.uuid4().hex}"
    meta_json = json.dumps(metadata).encode("utf-8")
    parts = (
        b"--" + boundary.encode() + b"\r\n"
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        + meta_json + b"\r\n"
        + b"--" + boundary.encode() + b"\r\n"
        + f"Content-Type: {ctype}\r\n\r\n".encode()
        + payload + b"\r\n"
        + b"--" + boundary.encode() + b"--\r\n"
    )
    params = {"uploadType": "multipart", "fields": _FILE_FIELDS,
              "supportsAllDrives": "true"}
    url = f"{UPLOAD_BASE}/files?" + urllib.parse.urlencode(params)
    r = _request(
        url, token=token, method="POST", body=parts,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    if "_err" in r:
        return OpResult.fail(r["_err"])
    out = _simplify_entry(r.get("data") or {})
    return OpResult(ok=True, value=out,
                    value_preview=f"uploaded {out.get('name')} "
                                  f"({out.get('size')} bytes)")


# ---------------------------------------------------------------------------
class GDriveConnector(Connector):
    """Google Drive REST API v3 connector."""

    host = "gdrive"
    display_name = "Google Drive"
    mechanism = "rest"

    # -- status -------------------------------------------------------
    def probe(self) -> dict:
        """Honest status (the excel/dropbox pattern):
          no token                  -> unauthorized
          token + about.get ok      -> live
          401                       -> unauthorized
          network / other error     -> missing
        """
        token = _load_token()
        if not token:
            return {"status": "unauthorized", "note": _token_hint(),
                    "detail": {}}
        # Cheap real auth check — about.get with the user field.
        url = f"{API_BASE}/about?" + urllib.parse.urlencode(
            {"fields": "user,storageQuota"})
        r = _request(url, token=token, timeout=12)
        if "_err" in r:
            status = "unauthorized" if r.get("http_status") == 401 \
                else "missing"
            return {"status": status, "note": r["_err"], "detail": {}}
        data = r.get("data") or {}
        user = data.get("user") or {}
        name = (user.get("displayName") or user.get("emailAddress")
                or "account")
        return {
            "status": "live",
            "note": f"Signed in as {name}",
            "detail": {"name": name,
                       "email": user.get("emailAddress")},
        }

    # -- operations ---------------------------------------------------
    def build_ops(self) -> list:
        return [
            ConnectorOp(
                op_id="gdrive.list_files",
                host="gdrive", kind="read",
                label="List files",
                description="List Google Drive files and folders, "
                            "optionally filtered by a query or parent "
                            "folder.",
                inputs=[
                    ParamSpec(id="query", label="Query", type="text",
                              default="",
                              help="Drive search filter, e.g. "
                                   "\"name contains 'plan'\". Blank lists "
                                   "everything."),
                    ParamSpec(id="parent", label="Parent folder id",
                              type="text", default="",
                              help="Scope to a folder id ('root' for My "
                                   "Drive root)."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=200,
                              help="Max entries to return (1-1000)."),
                ],
                output_type="list",
                fn=_op_list_files,
            ),
            ConnectorOp(
                op_id="gdrive.get_metadata",
                host="gdrive", kind="read",
                label="Get metadata",
                description="Fetch metadata for one Google Drive file or "
                            "folder by id.",
                inputs=[
                    ParamSpec(id="file_id", label="File id", type="text",
                              required=True,
                              help="The Drive file or folder id."),
                ],
                output_type="dict",
                fn=_op_get_metadata,
            ),
            ConnectorOp(
                op_id="gdrive.download",
                host="gdrive", kind="read",
                label="Download file",
                description="Download a Google Drive file's content "
                            "(base64-encoded, capped at 25 MB).",
                inputs=[
                    ParamSpec(id="file_id", label="File id", type="text",
                              required=True,
                              help="The Drive file id to download."),
                ],
                output_type="dict",
                fn=_op_download,
            ),
            ConnectorOp(
                op_id="gdrive.create_folder",
                host="gdrive", kind="action",
                label="Create folder",
                description="Create a folder in Google Drive. Writes to "
                            "Drive.",
                inputs=[
                    ParamSpec(id="name", label="Folder name", type="text",
                              required=True,
                              help="The new folder's name."),
                    ParamSpec(id="parent", label="Parent folder id",
                              type="text", default="",
                              help="Parent folder id ('root' for My Drive "
                                   "root). Blank = root."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_create_folder,
            ),
            ConnectorOp(
                op_id="gdrive.upload",
                host="gdrive", kind="action",
                label="Upload file",
                description="Upload a file to Google Drive. Writes to "
                            "Drive.",
                inputs=[
                    ParamSpec(id="name", label="File name", type="text",
                              required=True,
                              help="Destination file name, e.g. notes.txt."),
                    ParamSpec(id="parent", label="Parent folder id",
                              type="text", default="",
                              help="Parent folder id ('root' for My Drive "
                                   "root). Blank = root."),
                    ParamSpec(id="text", label="Text content", type="text",
                              default="",
                              help="UTF-8 text to write."),
                    ParamSpec(id="content_base64",
                              label="Binary content (base64)",
                              type="text", default="",
                              help="Base64-encoded bytes (overrides "
                                   "`text`)."),
                    ParamSpec(id="mime_type", label="MIME type",
                              type="text", default="",
                              help="Content MIME type. Defaults to "
                                   "application/octet-stream."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_upload,
            ),
        ]


# ── register at import time ─────────────────────────────────────────
register(GDriveConnector())
