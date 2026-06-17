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
          speckle.receive         — full object tree of a version
                                    (root + dereferenced children)
  ACTION  speckle.create_object   — serialize + upload an object tree
          speckle.send            — push objects to a branch: upload the
                                    tree (or reference a hash) + commit
                                    a version (destructive)

Every operation returns an `OpResult`; nothing raises to the caller.
"""
from __future__ import annotations

import gzip
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


def _as_bool(v: Any, *, default: bool = False) -> bool:
    """Coerce a param (may arrive as a JS string) to a bool."""
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off", ""):
        return False
    return default


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
# Object API (the raw REST endpoints, separate from /graphql).
#
# Speckle stores an object *tree* content-addressed: every Base object gets a
# deterministic hash (its `id`), detached children are stored as their own
# rows, and the root carries a `__closure` table {childId: depth}. The
# GraphQL surface above lists/commits versions; uploading and downloading the
# actual object bytes goes through these endpoints:
#
#   POST <server>/objects/<projectId>          — upload a batch of objects
#                                                 (multipart, gzipped JSON
#                                                 array). Returns the ids.
#   GET  <server>/objects/<projectId>/<id>/single
#                                              — one serialized object (root)
#   POST <server>/api/getobjects/<projectId>   — bulk-fetch children by id;
#                                                 newline-delimited
#                                                 `hash\tjson` lines.
#
# These mirror specklepy's own ServerTransport. We compute every hash with
# specklepy's OWN serializer (BaseObjectSerializer) so an object ArchHub
# creates is byte-identical to one any other Speckle client would create —
# we never reimplement the hash.
# ---------------------------------------------------------------------------
class _SpeckleObjectsUnavailable(RuntimeError):
    """specklepy isn't importable — object send/receive can't serialize."""


def _serialize_object_tree(root: Any) -> tuple[str, dict[str, str]]:
    """Serialize a Speckle `Base` tree to its canonical wire form.

    Returns ``(root_id, objects)`` where ``root_id`` is specklepy's OWN
    content hash of the root and ``objects`` maps every object id (root +
    each detached descendant) to its serialized JSON string — exactly the
    set a Speckle server must receive to reconstruct the tree.

    The hash is computed by specklepy's ``BaseObjectSerializer`` driven by a
    ``MemoryTransport`` write transport; we do not reimplement it. Raises
    ``_SpeckleObjectsUnavailable`` if specklepy is absent.
    """
    try:
        from specklepy.objects.base import Base  # type: ignore
        from specklepy.serialization.base_object_serializer import (  # type: ignore
            BaseObjectSerializer,
        )
        from specklepy.transports.memory import MemoryTransport  # type: ignore
    except Exception as ex:  # pragma: no cover - import guard
        raise _SpeckleObjectsUnavailable(str(ex)) from ex

    if not isinstance(root, Base):
        raise TypeError(
            "speckle.create_object needs a specklepy Base object (or a tree "
            "of them); got " + type(root).__name__)

    # A write transport is what makes the serializer DETACH children into the
    # transport's object map (without one it inlines everything and uploads
    # nothing reusable). MemoryTransport just collects them in-process.
    mem = MemoryTransport()
    serializer = BaseObjectSerializer(write_transports=[mem])
    root_id, _root_json = serializer.write_json(root)
    # mem.objects already holds the root + every detached child, each keyed by
    # its own specklepy hash and valued by its serialized JSON string.
    objects = dict(mem.objects)
    objects.setdefault(root_id, _root_json)
    return root_id, objects


def _upload_objects(project_id: str, objects: dict[str, str], *,
                    token: str,
                    timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """POST a batch of serialized objects to ``/objects/<projectId>``.

    ``objects`` is {id: serialized_json}. We send them as one gzipped JSON
    array in a multipart ``batch-1`` part — the shape Speckle's object
    endpoint accepts (identical to specklepy's BatchSender). Returns one of:
      {"_ok": True, "uploaded": int}
      {"_err": "...", "http_status": int?}
    """
    if not objects:
        return {"_ok": True, "uploaded": 0}
    payload = "[" + ",".join(objects.values()) + "]"
    gz = gzip.compress(payload.encode("utf-8"))

    boundary = "----ArchHubSpeckle" + uuid.uuid4().hex
    pre = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="batch-1"; '
        f'filename="batch-1"\r\n'
        f"Content-Type: application/gzip\r\n\r\n"
    ).encode("utf-8")
    post = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = pre + gz + post

    url = _server_url().rstrip("/") + f"/objects/{project_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "text/plain",
    }
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as ex:
        try:
            detail = ex.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return {"_err": _classify_http(ex.code, detail),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Speckle server "
                        f"{_server_url()}: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}
    return {"_ok": True, "uploaded": len(objects)}


def _download_object(project_id: str, object_id: str, *,
                     token: str,
                     timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """GET one serialized object via ``/objects/<projectId>/<id>/single``.

    Returns {"_ok": True, "obj": dict} or {"_err": ...}.
    """
    url = (_server_url().rstrip("/")
           + f"/objects/{project_id}/{object_id}/single")
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "text/plain"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        try:
            detail = ex.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return {"_err": _classify_http(ex.code, detail),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Speckle server "
                        f"{_server_url()}: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}
    try:
        return {"_ok": True, "obj": json.loads(raw) if raw else {}}
    except Exception:
        return {"_err": "Speckle returned a non-JSON object."}


def _fetch_children_via_graphql(project_id: str, object_id: str, *,
                                token: str, limit: int = 1000,
                                depth: int = 50,
                                timeout: int = DEFAULT_TIMEOUT_SECONDS
                                ) -> dict:
    """Walk a root object's detached descendants via GraphQL `children`.

    Speckle's `object(id){ children(...) }` returns the resolved descendant
    objects (those the `__closure` references), paginated by a `cursor`. We
    page until the cursor is exhausted and return them as a flat dict
    {id: data}. Returns {"_ok": True, "children": {...}, "fetched": int} or
    {"_err": ...}.
    """
    query = """
    query($pid:String!,$oid:String!,$limit:Int!,$depth:Int!,$cursor:String){
      project(id:$pid){
        object(id:$oid){
          id totalChildrenCount
          children(limit:$limit, depth:$depth, cursor:$cursor){
            totalCount cursor
            objects{ id data }
          }
        }
      }
    }
    """
    resolved: dict[str, Any] = {}
    cursor: Optional[str] = None
    # Bounded page loop — Speckle returns at most `limit` per page; the cursor
    # advances until null. The cap (totalChildrenCount + slack) guarantees
    # termination even if a server misbehaves.
    for _ in range(10000):
        r = _graphql(query, {"pid": project_id, "oid": object_id,
                             "limit": limit, "depth": depth,
                             "cursor": cursor}, token=token, timeout=timeout)
        if "_err" in r:
            return {"_err": r["_err"]}
        project = (r.get("data") or {}).get("project") or {}
        obj = project.get("object") or {}
        coll = obj.get("children") or {}
        for child in (coll.get("objects") or []):
            cid = child.get("id")
            if cid is not None and cid not in resolved:
                resolved[cid] = child.get("data")
        cursor = coll.get("cursor")
        if not cursor:
            break
    return {"_ok": True, "children": resolved, "fetched": len(resolved)}


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
                version_id: str = "", dereference: Any = True,
                **_: Any) -> OpResult:
    """Receive the object tree of a version.

    Accepts either `object_id` (the referenced object hash) directly, or
    `version_id` — in which case we first resolve the version to its
    referenced object.

    A real Speckle model is a *tree*: the root object holds detached
    references to its descendants (its `__closure` lists them by id). When
    `dereference` is true (the default) we walk those detached children via
    GraphQL `children` so the caller gets the WHOLE tree — `value["children"]`
    maps every descendant id to its resolved data, and `value["objects"]`
    is the flat root+children map. With `dereference` false we return only
    the root object (the old shallow behaviour) for a cheap peek.
    """
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    pid = str(project_id).strip()
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    deref = _as_bool(dereference, default=True)

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
    total_children = obj.get("totalChildrenCount") or 0
    out = {
        "id": obj.get("id"),
        "speckle_type": obj.get("speckleType"),
        "total_children_count": total_children,
        "data": obj.get("data"),
    }

    # Dereference the detached descendants. A root with totalChildrenCount>0
    # has children stored as their own rows; without this walk the caller
    # only ever sees the root and the tree is truncated.
    if deref and total_children > 0:
        cr = _fetch_children_via_graphql(pid, oid, token=token)
        if "_err" in cr:
            return OpResult.fail(cr["_err"])
        children = cr.get("children") or {}
        out["children"] = children
        out["children_count"] = len(children)
        # Flat root+children map keyed by id — the full received tree.
        objects = {out["id"]: out["data"]}
        objects.update(children)
        out["objects"] = objects
        return OpResult(ok=True, value=out,
                        value_preview=f"object {str(oid)[:8]} "
                                      f"({len(children)}/{total_children} "
                                      f"children resolved)")

    return OpResult(ok=True, value=out,
                    value_preview=f"object {str(oid)[:8]} "
                                  f"({total_children} children)")


def _commit_version(pid: str, mid: str, oid: str, *, message: str,
                    source_application: str, token: str) -> dict:
    """Record a new version on a model branch pointing at an object hash.

    Returns {"_ok": True, "version": {...}} or {"_err": ...}. Shared by
    `speckle.send` (after it uploads the tree) and the version mutation.
    """
    mutation = """
    mutation($input:CreateVersionInput!){
      versionMutations{
        create(input:$input){ id message referencedObject createdAt }
      }
    }
    """
    variables = {
        "input": {
            "projectId": pid,
            "modelId": mid,
            "objectId": oid,
            "message": message or "Pushed from ArchHub",
            "sourceApplication": source_application or "ArchHub",
        }
    }
    r = _graphql(mutation, variables, token=token)
    if "_err" in r:
        return {"_err": r["_err"]}
    vm = (r.get("data") or {}).get("versionMutations") or {}
    created = vm.get("create") or {}
    if not created.get("id"):
        return {"_err": "Speckle accepted the request but returned no "
                        "version id."}
    return {"_ok": True, "version": {
        "id": created.get("id"),
        "message": created.get("message"),
        "referenced_object": created.get("referencedObject"),
        "created_at": created.get("createdAt"),
    }}


def _op_create_object(project_id: str = "", objects: Any = None,
                      **_: Any) -> OpResult:
    """Serialize a Speckle object tree and UPLOAD it to the server.

    DESTRUCTIVE — writes object bytes to the Speckle server (it does not
    create a version; pair it with `speckle.send` or pass objects straight
    to `speckle.send`). `objects` is a specklepy `Base` (the canvas root)
    or a list of them. The id we return is specklepy's OWN content hash of
    the root — the same hash any Speckle client computes — and is what
    `speckle.send` commits.

    This is the op CON-03 named: it lets the canvas push real geometry to a
    cloud Speckle server instead of only re-committing an existing hash.
    """
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    if objects is None:
        return OpResult.fail("objects is required — a Speckle Base object "
                             "(or list) to upload.")
    pid = str(project_id).strip()
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    # A list of roots is wrapped in a synthetic Base whose `@elements` holds
    # them (the Speckle convention for a multi-object commit), so we always
    # upload exactly one rooted tree.
    root = objects
    if isinstance(objects, (list, tuple)):
        try:
            from specklepy.objects.base import Base  # type: ignore
        except Exception as ex:  # pragma: no cover - import guard
            return OpResult.fail(
                "Speckle object support unavailable (specklepy not "
                f"importable): {ex}")
        wrapper = Base()
        wrapper["@elements"] = list(objects)
        root = wrapper

    try:
        root_id, serialized = _serialize_object_tree(root)
    except _SpeckleObjectsUnavailable as ex:
        return OpResult.fail(
            "Speckle object support unavailable (specklepy not "
            f"importable): {ex}")
    except TypeError as ex:
        return OpResult.fail(str(ex))
    except Exception as ex:
        return OpResult.fail(f"Could not serialize objects: "
                             f"{type(ex).__name__}: {ex}")

    up = _upload_objects(pid, serialized, token=token)
    if "_err" in up:
        return OpResult.fail(up["_err"])
    out = {
        "id": root_id,
        "object_id": root_id,
        "uploaded": up.get("uploaded", len(serialized)),
        "object_count": len(serialized),
    }
    return OpResult(ok=True, value=out,
                    value_preview=f"uploaded {len(serialized)} object"
                                  f"{'s' if len(serialized) != 1 else ''} "
                                  f"-> {root_id[:8]}")


def _op_send(project_id: str = "", model_id: str = "",
             object_id: str = "", objects: Any = None, message: str = "",
             source_application: str = "ArchHub",
             **_: Any) -> OpResult:
    """Push objects to a model branch — upload + commit a new version.

    DESTRUCTIVE — writes to the Speckle server. Two ways to call it:

      * `objects` — a specklepy `Base` (or list) of canvas geometry. We
        serialize it with specklepy's OWN hash, UPLOAD the whole object tree
        to `/objects/<projectId>`, then commit a version referencing the
        resulting root hash. This is the path the canvas "Send objects" uses
        to push real geometry (CON-03).
      * `object_id` — the hash of an object ALREADY on the server; we skip
        the upload and just commit a version referencing it (back-compat).

    The agent default policy for this op is "ask".
    """
    if not project_id or not str(project_id).strip():
        return OpResult.fail("project_id is required.")
    if not model_id or not str(model_id).strip():
        return OpResult.fail("model_id is required.")
    pid = str(project_id).strip()
    mid = str(model_id).strip()
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    uploaded = 0
    if objects is not None:
        # Serialize + upload the tree, then commit the returned root hash.
        created = _op_create_object(project_id=pid, objects=objects)
        if not created.ok:
            return created
        oid = created.value["id"]
        uploaded = created.value.get("object_count", 0)
    else:
        oid = str(object_id or "").strip()
        if not oid:
            return OpResult.fail(
                "Provide either objects (a Speckle Base/list to upload) or "
                "object_id (the hash of an object already on the server).")

    cv = _commit_version(pid, mid, oid, message=str(message or "").strip(),
                         source_application=str(source_application
                                                or "ArchHub"),
                         token=token)
    if "_err" in cv:
        return OpResult.fail(cv["_err"])
    out = dict(cv["version"])
    if objects is not None:
        out["uploaded_objects"] = uploaded
    return OpResult(ok=True, value=out,
                    value_preview=f"version {str(out.get('id'))[:8]} "
                                  f"created")


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
                description="Receive the full object tree of a Speckle "
                            "version (by version id or object hash) — the "
                            "root and all detached children resolved.",
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
                    ParamSpec(id="dereference", label="Resolve children",
                              type="bool", default=True,
                              help="Walk detached child refs and return the "
                                   "whole tree (off = root object only)."),
                ],
                output_type="dict",
                fn=_op_receive,
            ),
            ConnectorOp(
                op_id="speckle.create_object",
                host="speckle", kind="action",
                label="Upload objects",
                description="Serialize a Speckle object tree (canvas "
                            "geometry) and upload it to the server. Returns "
                            "the content hash to commit with Send.",
                inputs=[
                    ParamSpec(id="project_id", label="Project ID",
                              type="text", required=True,
                              options_source="speckle.list_projects",
                              help="The stream / project id."),
                    ParamSpec(id="objects", label="Objects", type="any",
                              required=True,
                              help="A specklepy Base object (or list) to "
                                   "serialize + upload."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_create_object,
            ),
            ConnectorOp(
                op_id="speckle.send",
                host="speckle", kind="action",
                label="Send objects",
                description="Push objects to a model branch: upload the "
                            "object tree (or reference an existing hash) and "
                            "commit a new version. Writes to the server.",
                inputs=[
                    ParamSpec(id="project_id", label="Project ID",
                              type="text", required=True,
                              options_source="speckle.list_projects",
                              help="The stream / project id."),
                    ParamSpec(id="model_id", label="Model ID",
                              type="text", required=True,
                              options_source="speckle.list_models",
                              help="The target model / branch id."),
                    ParamSpec(id="objects", label="Objects", type="any",
                              help="Canvas geometry to upload + commit (a "
                                   "specklepy Base or list). Use this OR "
                                   "object_id."),
                    ParamSpec(id="object_id", label="Object ID",
                              type="text",
                              help="The hash of a Speckle object already on "
                                   "the server (alternative to objects)."),
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
