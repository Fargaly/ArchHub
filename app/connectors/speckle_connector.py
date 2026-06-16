"""Speckle connector — drives a Speckle server's GraphQL API.

Implements the uniform `connectors.base.Connector` contract. Speckle is
the open-source data hub for AEC — streams (projects) hold branches
(models) which hold commits (versions), each commit referencing an
object tree. ArchHub architects receive Speckle objects onto the canvas
and push results back without leaving the workspace.

Mechanism: REST (GraphQL-over-HTTP). All traffic is POST to
`<server>/graphql` with a JSON `{query, variables}` body.

Auth model
----------
  Speckle uses a Personal Access Token (PAT) the user generates at
  `<server>/profile` → Developer Settings. We send it as a bearer
  token. There is no refresh; a rejected token (the GraphQL response
  carries a `FORBIDDEN` / `UNAUTHENTICATED` error, or HTTP 401) tells
  the user to re-paste in Settings.

Settings keys read (via secrets_store):
  speckle            — load_api_key('speckle')        : the PAT
  speckle_server     — load_setting('speckle_server') : server URL,
                       defaults to https://app.speckle.systems

Operations
----------
  READ    speckle.list_projects   — streams the user can see
          speckle.list_models     — branches of a stream
          speckle.list_versions   — commits on a branch
          speckle.receive         — objects of a version
  ACTION  speckle.create_object   — upload an object tree, get its hash
          speckle.send            — upload+commit an object tree, or
                                    commit an existing hash (destructive)

Every operation returns an `OpResult`; nothing raises to the caller.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
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
DEFAULT_SERVER = "https://app.speckle.systems"
DEFAULT_TIMEOUT_SECONDS = 30
SECRET_KEY = "speckle"


# ---------------------------------------------------------------------------
def _load_token() -> Optional[str]:
    """Pull the saved Speckle Personal Access Token, or None if missing."""
    try:
        from secrets_store import load_api_key
        v = load_api_key(SECRET_KEY)
        return v or None
    except Exception:
        return None


def _server_url() -> str:
    """The Speckle server base URL — saved setting or the public default."""
    try:
        from secrets_store import load_setting
        v = load_setting("speckle_server")
        if v and str(v).strip():
            return str(v).strip().rstrip("/")
    except Exception:
        pass
    return DEFAULT_SERVER


def _token_hint() -> str:
    return ("Speckle token not set. Open Settings -> Sign-ins -> Speckle "
            "and paste a Personal Access Token from your server profile "
            "(Developer Settings).")


# ---------------------------------------------------------------------------
def _graphql(query: str, variables: Optional[dict] = None, *,
             token: str,
             timeout: int = DEFAULT_TIMEOUT_SECONDS,
             _retry: bool = True) -> dict:
    """Run one GraphQL request against the configured Speckle server.

    Returns one of:
      {"_ok": True, "data": {...}}              — success
      {"_err": "...", "http_status": int?}      — failure (soft)

    GraphQL is unusual: an HTTP 200 can still carry an `errors` array.
    We surface those as `_err`. A 429 gets one retry with backoff.
    """
    url = _server_url().rstrip("/") + "/graphql"
    body = json.dumps({"query": query,
                       "variables": variables or {}}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        if ex.code == 429 and _retry:
            time.sleep(_retry_after(ex))
            return _graphql(query, variables, token=token,
                            timeout=timeout, _retry=False)
        try:
            payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        return {"_err": _classify_http(ex.code, payload),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Speckle server "
                        f"{_server_url()}: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}

    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        return {"_err": "Speckle returned a non-JSON response."}

    errors = parsed.get("errors")
    if errors:
        msg = _classify_graphql_errors(errors)
        return {"_err": msg}
    return {"_ok": True, "data": parsed.get("data") or {}}


def _retry_after(ex: urllib.error.HTTPError) -> float:
    """Seconds to wait before a 429 retry — honours Retry-After if sent."""
    try:
        hdr = ex.headers.get("Retry-After") if ex.headers else None
        if hdr:
            return min(float(hdr), 30.0)
    except Exception:
        pass
    return 2.0


def _classify_http(code: int, payload: str) -> str:
    """Translate an HTTP status code into something the user can act on."""
    short = (payload or "")[:200]
    if code == 401:
        return ("Speckle token rejected (401). Open Settings -> Sign-ins "
                "-> Speckle and paste a fresh Personal Access Token.")
    if code == 403:
        return ("Speckle denied access (403) — the token is valid but "
                "lacks scope for this resource.")
    if code == 404:
        return (f"Speckle endpoint not found (404) — check the server URL "
                f"in Settings. {short}").strip()
    if code == 429:
        return "Speckle rate limit hit (429). Wait a moment and retry."
    if code >= 500:
        return f"Speckle server error ({code}). Retry shortly."
    return f"Speckle HTTP {code}: {short}".strip()


def _classify_graphql_errors(errors: list) -> str:
    """Turn a GraphQL `errors` array into a single user-facing string."""
    msgs: list[str] = []
    auth = False
    for e in errors or []:
        if not isinstance(e, dict):
            continue
        m = str(e.get("message") or "").strip()
        code = ""
        ext = e.get("extensions")
        if isinstance(ext, dict):
            code = str(ext.get("code") or "")
        if code in ("UNAUTHENTICATED", "FORBIDDEN") or \
                "unauthorized" in m.lower() or "forbidden" in m.lower():
            auth = True
        if m:
            msgs.append(m)
    joined = "; ".join(msgs) if msgs else "unknown GraphQL error"
    if auth:
        return (f"Speckle rejected the request ({joined}). The token may "
                f"be expired or lack scope — re-paste it in Settings -> "
                f"Sign-ins -> Speckle.")
    return f"Speckle GraphQL error: {joined}"


# ---------------------------------------------------------------------------
# Object creation — the upload path `_op_send` was missing.
#
# Speckle is content-addressed: an object's id IS the SHA-256 of its
# canonical JSON, truncated to 32 hex chars (this matches specklepy's
# `serialization.base_object_serializer.hash_obj`). A commit
# (`speckle.send`) only references an object hash that already lives on
# the server — so before today `speckle.send` could ONLY re-point at an
# object somebody else uploaded; there was no way to push a fresh object
# tree from ArchHub. `_create_objects` closes that: it computes each
# object's content id and uploads the batch to the REST object endpoint
# `POST <server>/objects/<projectId>` (gzipped multipart, exactly as
# specklepy's ServerTransport does), returning the ROOT object's hash
# that a subsequent commit references.
# ---------------------------------------------------------------------------
def _speckle_object_id(obj: dict) -> str:
    """Content-addressed Speckle id: sha256(canonical-json)[:32].

    Mirrors specklepy `hash_obj` so an object ArchHub creates carries the
    SAME id the Speckle server (and every other Speckle client) would
    compute for it — that is what makes the object tree content-addressed
    and the commit reference stable.
    """
    canonical = json.dumps(obj, separators=(",", ":"), sort_keys=True,
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _normalize_objects(objects: Any) -> list[dict]:
    """Coerce a user-supplied object payload into a list of object dicts.

    Accepts a single object dict, a list of object dicts, or a JSON
    string of either. Raises ValueError on anything else so the op can
    surface an honest error instead of uploading garbage.
    """
    if objects is None:
        raise ValueError("no objects provided")
    if isinstance(objects, str):
        s = objects.strip()
        if not s:
            raise ValueError("objects is an empty string")
        objects = json.loads(s)
    if isinstance(objects, dict):
        objects = [objects]
    if not isinstance(objects, list) or not objects:
        raise ValueError("objects must be a non-empty object or list of "
                         "objects")
    out: list[dict] = []
    for o in objects:
        if not isinstance(o, dict):
            raise ValueError("every object must be a JSON object (dict)")
        out.append(o)
    return out


def _stamp_ids(objects: list[dict]) -> list[dict]:
    """Return copies of `objects`, each carrying its content-addressed id.

    The FIRST object is treated as the root. Any object that already
    carries a non-empty `id` keeps it (the caller may have pre-hashed a
    sub-tree); the rest are hashed here. Returns new dicts — the caller's
    payload is never mutated.
    """
    stamped: list[dict] = []
    for o in objects:
        copy = dict(o)
        existing = str(copy.get("id") or "").strip()
        if not existing:
            # Hash over the object MINUS any falsy id placeholder so the
            # id is a pure function of content.
            body = {k: v for k, v in copy.items() if k != "id"}
            copy["id"] = _speckle_object_id(body)
        stamped.append(copy)
    return stamped


def _multipart_gzip_body(objects: list[dict]) -> tuple[bytes, str]:
    """Build the multipart/form-data body Speckle's object API expects.

    The batch is serialised as a JSON array, gzip-compressed, and sent as
    a single file part — byte-for-byte the shape specklepy's
    ServerTransport uses (`files={"batch-1": (..., gzip)}`). Returns
    (body_bytes, content_type_header_value).
    """
    payload = json.dumps(objects, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    gz = gzip.compress(payload)
    boundary = "----ArchHubSpeckle" + uuid.uuid4().hex
    pre = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="batch-1"; '
        f'filename="batch-1"\r\n'
        f"Content-Type: application/gzip\r\n\r\n"
    ).encode("utf-8")
    post = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = pre + gz + post
    return body, f"multipart/form-data; boundary={boundary}"


def _create_objects(project_id: str, objects: list[dict], *,
                    token: str,
                    timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Upload an object batch to `POST <server>/objects/<projectId>`.

    Returns one of:
      {"_ok": True, "root_id": "<hash>", "count": int}   — success
      {"_err": "...", "http_status": int?}               — failure (soft)

    This is the REAL object-creation path. The root id returned is what a
    commit (`speckle.send`) references. Never raises to the caller.
    """
    if not objects:
        return {"_err": "no objects to upload"}
    body, content_type = _multipart_gzip_body(objects)
    url = _server_url().rstrip("/") + "/objects/" + str(project_id).strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type,
        "Accept": "text/plain",
    }
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read()
            status = int(getattr(resp, "status", 0) or resp.getcode() or 0)
    except urllib.error.HTTPError as ex:
        try:
            payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        return {"_err": _classify_http(ex.code, payload),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Speckle server "
                        f"{_server_url()}: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}
    if status and status >= 400:
        return {"_err": f"Speckle object upload failed (HTTP {status}).",
                "http_status": status}
    # The server stores the batch; the root object's id is the first
    # object's content hash (objects are sent root-first).
    return {"_ok": True, "root_id": objects[0].get("id"),
            "count": len(objects)}


def _op_create_object(project_id: str = "", objects: Any = None,
                      **_: Any) -> OpResult:
    """Create (upload) a Speckle object tree on the server.

    Accepts a single object dict, a list of objects, or a JSON string of
    either (first = root). Computes each object's content-addressed id,
    uploads the batch to `POST <server>/objects/<projectId>`, and returns
    the ROOT object hash — the id a commit (`speckle.send`) references.

    DESTRUCTIVE — writes object data to the Speckle server.
    """
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        normalized = _normalize_objects(objects)
    except ValueError as ex:
        return OpResult.fail(f"Invalid objects payload: {ex}")
    except json.JSONDecodeError as ex:
        return OpResult.fail(f"objects is not valid JSON: {ex}")
    stamped = _stamp_ids(normalized)
    r = _create_objects(str(project_id).strip(), stamped, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    root_id = r.get("root_id")
    if not root_id:
        return OpResult.fail("Speckle accepted the upload but no root "
                             "object id was produced.")
    out = {
        "object_id": root_id,
        "root_id": root_id,
        "count": r.get("count"),
    }
    return OpResult(ok=True, value=out,
                    value_preview=f"object {str(root_id)[:8]} created "
                                  f"({r.get('count')} uploaded)")


# ---------------------------------------------------------------------------
# Operation implementations. Each returns an OpResult.
# ---------------------------------------------------------------------------
def _op_list_projects(limit: int = 25, **_: Any) -> OpResult:
    """List streams (projects) visible to the authenticated user."""
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        lim = max(1, min(int(limit or 25), 100))
    except Exception:
        lim = 25
    query = """
    query($limit:Int!){
      activeUser{
        projects(limit:$limit){
          totalCount
          items{ id name description visibility updatedAt
                 models(limit:1){ totalCount } }
        }
      }
    }
    """
    r = _graphql(query, {"limit": lim}, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    user = (r.get("data") or {}).get("activeUser") or {}
    projects = (user.get("projects") or {})
    items = []
    for p in (projects.get("items") or []):
        models = p.get("models") or {}
        items.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "description": p.get("description") or "",
            "visibility": p.get("visibility"),
            "updated_at": p.get("updatedAt"),
            "model_count": models.get("totalCount"),
        })
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} project"
                                  f"{'s' if len(items) != 1 else ''}")


def _op_list_models(project_id: str = "", limit: int = 25,
                     **_: Any) -> OpResult:
    """List models (branches) of a stream."""
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        lim = max(1, min(int(limit or 25), 100))
    except Exception:
        lim = 25
    query = """
    query($id:String!,$limit:Int!){
      project(id:$id){
        id name
        models(limit:$limit){
          totalCount
          items{ id name description updatedAt
                 versions(limit:1){ totalCount } }
        }
      }
    }
    """
    r = _graphql(query, {"id": str(project_id).strip(), "limit": lim},
                 token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    project = (r.get("data") or {}).get("project")
    if not project:
        return OpResult.fail(f"Speckle project '{project_id}' not found "
                             f"or not accessible.")
    models = project.get("models") or {}
    items = []
    for m in (models.get("items") or []):
        versions = m.get("versions") or {}
        items.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "description": m.get("description") or "",
            "updated_at": m.get("updatedAt"),
            "version_count": versions.get("totalCount"),
        })
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} model"
                                  f"{'s' if len(items) != 1 else ''}")


def _op_list_versions(project_id: str = "", model_id: str = "",
                       limit: int = 25, **_: Any) -> OpResult:
    """List versions (commits) on a model branch."""
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    if not model_id or not str(model_id).strip():
        return OpResult.fail("model_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        lim = max(1, min(int(limit or 25), 100))
    except Exception:
        lim = 25
    query = """
    query($pid:String!,$mid:String!,$limit:Int!){
      project(id:$pid){
        model(id:$mid){
          id name
          versions(limit:$limit){
            totalCount
            items{ id message referencedObject createdAt sourceApplication
                   authorUser{ id name } }
          }
        }
      }
    }
    """
    r = _graphql(query, {"pid": str(project_id).strip(),
                         "mid": str(model_id).strip(),
                         "limit": lim}, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    project = (r.get("data") or {}).get("project")
    if not project:
        return OpResult.fail(f"Speckle project '{project_id}' not found.")
    model = project.get("model")
    if not model:
        return OpResult.fail(f"Speckle model '{model_id}' not found in "
                             f"project '{project_id}'.")
    versions = model.get("versions") or {}
    items = []
    for v in (versions.get("items") or []):
        author = v.get("authorUser") or {}
        items.append({
            "id": v.get("id"),
            "message": v.get("message") or "",
            "referenced_object": v.get("referencedObject"),
            "created_at": v.get("createdAt"),
            "source_application": v.get("sourceApplication"),
            "author": author.get("name") if isinstance(author, dict)
            else None,
        })
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} version"
                                  f"{'s' if len(items) != 1 else ''}")


def _op_receive(project_id: str = "", object_id: str = "",
                version_id: str = "", **_: Any) -> OpResult:
    """Receive the object tree of a version.

    Accepts either `object_id` (the referenced object hash) directly, or
    `version_id` — in which case we first resolve the version to its
    referenced object. Returns the root Speckle Base object as a dict.
    """
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    pid = str(project_id).strip()
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    oid = str(object_id or "").strip()
    if not oid:
        vid = str(version_id or "").strip()
        if not vid:
            return OpResult.fail("Provide either object_id or version_id.")
        # Resolve the version to its referenced object hash.
        vq = """
        query($pid:String!,$vid:String!){
          project(id:$pid){ version(id:$vid){ id referencedObject } }
        }
        """
        vr = _graphql(vq, {"pid": pid, "vid": vid}, token=token)
        if "_err" in vr:
            return OpResult.fail(vr["_err"])
        project = (vr.get("data") or {}).get("project") or {}
        version = project.get("version") or {}
        oid = str(version.get("referencedObject") or "").strip()
        if not oid:
            return OpResult.fail(f"Version '{vid}' has no referenced "
                                 f"object.")

    query = """
    query($pid:String!,$oid:String!){
      project(id:$pid){
        object(id:$oid){
          id speckleType totalChildrenCount data
        }
      }
    }
    """
    r = _graphql(query, {"pid": pid, "oid": oid}, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    project = (r.get("data") or {}).get("project")
    if not project:
        return OpResult.fail(f"Speckle project '{pid}' not found.")
    obj = project.get("object")
    if not obj:
        return OpResult.fail(f"Speckle object '{oid}' not found in "
                             f"project '{pid}'.")
    out = {
        "id": obj.get("id"),
        "speckle_type": obj.get("speckleType"),
        "total_children_count": obj.get("totalChildrenCount"),
        "data": obj.get("data"),
    }
    children = obj.get("totalChildrenCount") or 0
    return OpResult(ok=True, value=out,
                    value_preview=f"object {str(oid)[:8]} "
                                  f"({children} children)")


def _op_send(project_id: str = "", model_id: str = "",
             object_id: str = "", objects: Any = None, message: str = "",
             source_application: str = "ArchHub",
             **_: Any) -> OpResult:
    """Push to a model branch — uploads an object tree, then commits it.

    Two ways to call it:
      * `objects` — a raw object dict / list / JSON string. The object
        tree is UPLOADED to the server (content-addressed) and the
        resulting root hash is committed. THIS is the full send path
        (create object tree + commit) that used to be missing.
      * `object_id` — the hash of an object already on the server; only a
        new commit is recorded (no upload). Back-compat with the
        re-commit-only behaviour.

    If both are given, `object_id` wins (explicit hash beats re-upload).

    DESTRUCTIVE — writes to the Speckle server. The agent default policy
    for this op is "ask".
    """
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    if not model_id or not str(model_id).strip():
        return OpResult.fail("model_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    oid = str(object_id or "").strip()
    uploaded_count = 0
    did_upload = False
    if not oid:
        # No pre-existing hash — we must CREATE the object tree first.
        if objects is None:
            return OpResult.fail(
                "Provide either object_id (a hash already on the server) "
                "or objects (an object tree to upload).")
        try:
            normalized = _normalize_objects(objects)
        except ValueError as ex:
            return OpResult.fail(f"Invalid objects payload: {ex}")
        except json.JSONDecodeError as ex:
            return OpResult.fail(f"objects is not valid JSON: {ex}")
        stamped = _stamp_ids(normalized)
        cr = _create_objects(str(project_id).strip(), stamped, token=token)
        if "_err" in cr:
            return OpResult.fail(cr["_err"])
        oid = str(cr.get("root_id") or "").strip()
        if not oid:
            return OpResult.fail("Speckle accepted the object upload but "
                                 "returned no root object id.")
        uploaded_count = int(cr.get("count") or 0)
        did_upload = True

    mutation = """
    mutation($input:CreateVersionInput!){
      versionMutations{
        create(input:$input){ id message referencedObject createdAt }
      }
    }
    """
    variables = {
        "input": {
            "projectId": str(project_id).strip(),
            "modelId": str(model_id).strip(),
            "objectId": oid,
            "message": str(message or "").strip()
            or "Pushed from ArchHub",
            "sourceApplication": str(source_application or "ArchHub"),
        }
    }
    r = _graphql(mutation, variables, token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    vm = (r.get("data") or {}).get("versionMutations") or {}
    created = vm.get("create") or {}
    if not created.get("id"):
        return OpResult.fail("Speckle accepted the request but returned "
                             "no version id.")
    out = {
        "id": created.get("id"),
        "message": created.get("message"),
        "referenced_object": created.get("referencedObject"),
        "created_at": created.get("createdAt"),
        "object_id": oid,
        "uploaded": did_upload,
        "uploaded_count": uploaded_count,
    }
    preview = f"version {str(created.get('id'))[:8]} created"
    if did_upload:
        preview += f" ({uploaded_count} object" \
                   f"{'s' if uploaded_count != 1 else ''} uploaded)"
    return OpResult(ok=True, value=out, value_preview=preview)


# ---------------------------------------------------------------------------
class SpeckleConnector(Connector):
    """Speckle GraphQL connector."""

    host = "speckle"
    display_name = "Speckle"
    mechanism = "rest"

    # -- status -------------------------------------------------------
    def probe(self) -> dict:
        """Honest status:
          no token              -> unauthorized
          token + activeUser ok -> live
          network / bad token   -> missing
        """
        token = _load_token()
        if not token:
            return {
                "status": "unauthorized",
                "note": _token_hint(),
                "detail": {"server": _server_url()},
            }
        # Cheap real auth check — the `activeUser` query.
        r = _graphql("query{ activeUser{ id name email } }",
                     token=token, timeout=12)
        if "_err" in r:
            return {
                "status": "missing",
                "note": r["_err"],
                "detail": {"server": _server_url()},
            }
        user = (r.get("data") or {}).get("activeUser") or {}
        if not user.get("id"):
            return {
                "status": "unauthorized",
                "note": ("Speckle token did not resolve to a user. "
                         "Re-paste it in Settings -> Sign-ins -> Speckle."),
                "detail": {"server": _server_url()},
            }
        return {
            "status": "live",
            "note": f"Signed in as {user.get('name') or user.get('email')} "
                    f"on {_server_url()}",
            "detail": {"server": _server_url(),
                       "user_id": user.get("id"),
                       "user_name": user.get("name")},
        }

    # -- operations ---------------------------------------------------
    def build_ops(self) -> list:
        return [
            ConnectorOp(
                op_id="speckle.list_projects",
                host="speckle", kind="read",
                label="List projects",
                description="List Speckle streams (projects) the signed-in "
                            "user can access.",
                inputs=[
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=25,
                              help="Max projects to return (1-100)."),
                ],
                output_type="list",
                fn=_op_list_projects,
            ),
            ConnectorOp(
                op_id="speckle.list_models",
                host="speckle", kind="read",
                label="List models",
                description="List models (branches) of a Speckle project.",
                inputs=[
                    ParamSpec(id="project_id", label="Project ID",
                              type="text", required=True,
                              options_source="speckle.list_projects",
                              help="The stream / project id."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=25,
                              help="Max models to return (1-100)."),
                ],
                output_type="list",
                fn=_op_list_models,
            ),
            ConnectorOp(
                op_id="speckle.list_versions",
                host="speckle", kind="read",
                label="List versions",
                description="List versions (commits) on a Speckle model "
                            "branch.",
                inputs=[
                    ParamSpec(id="project_id", label="Project ID",
                              type="text", required=True,
                              options_source="speckle.list_projects",
                              help="The stream / project id."),
                    ParamSpec(id="model_id", label="Model ID",
                              type="text", required=True,
                              options_source="speckle.list_models",
                              help="The model / branch id."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=25,
                              help="Max versions to return (1-100)."),
                ],
                output_type="list",
                fn=_op_list_versions,
            ),
            ConnectorOp(
                op_id="speckle.receive",
                host="speckle", kind="read",
                label="Receive objects",
                description="Receive the object tree of a Speckle version "
                            "(by version id or object hash).",
                inputs=[
                    ParamSpec(id="project_id", label="Project ID",
                              type="text", required=True,
                              options_source="speckle.list_projects",
                              help="The stream / project id."),
                    ParamSpec(id="version_id", label="Version ID",
                              type="text",
                              help="A commit id; resolved to its object."),
                    ParamSpec(id="object_id", label="Object ID",
                              type="text",
                              help="A Speckle object hash (alternative to "
                                   "version_id)."),
                ],
                output_type="dict",
                fn=_op_receive,
            ),
            ConnectorOp(
                op_id="speckle.create_object",
                host="speckle", kind="action",
                label="Create object",
                description="Upload an object tree to the Speckle server "
                            "(content-addressed) and return its root "
                            "object hash. Writes object data to the "
                            "server.",
                inputs=[
                    ParamSpec(id="project_id", label="Project ID",
                              type="text", required=True,
                              options_source="speckle.list_projects",
                              help="The stream / project id to store the "
                                   "object under."),
                    ParamSpec(id="objects", label="Objects",
                              type="text", required=True,
                              help="An object dict, a list of objects, or "
                                   "a JSON string of either (first = "
                                   "root). Each object's id is computed "
                                   "and the batch uploaded."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_create_object,
            ),
            ConnectorOp(
                op_id="speckle.send",
                host="speckle", kind="action",
                label="Send objects",
                description="Push to a model branch: upload an object tree "
                            "(via `objects`) then commit it, OR commit an "
                            "existing object hash (via `object_id`). "
                            "Writes to the Speckle server.",
                inputs=[
                    ParamSpec(id="project_id", label="Project ID",
                              type="text", required=True,
                              options_source="speckle.list_projects",
                              help="The stream / project id."),
                    ParamSpec(id="model_id", label="Model ID",
                              type="text", required=True,
                              options_source="speckle.list_models",
                              help="The target model / branch id."),
                    ParamSpec(id="objects", label="Objects",
                              type="text",
                              help="An object tree to upload + commit (dict "
                                   "/ list / JSON string). Use this OR "
                                   "object_id."),
                    ParamSpec(id="object_id", label="Object ID",
                              type="text",
                              help="The hash of a Speckle object already on "
                                   "the server (skips upload). Use this OR "
                                   "objects."),
                    ParamSpec(id="message", label="Commit message",
                              type="text", default="",
                              help="Optional version message."),
                    ParamSpec(id="source_application",
                              label="Source application", type="text",
                              default="ArchHub"),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_send,
            ),
        ]


# ── register at import time ─────────────────────────────────────────
register(SpeckleConnector())
