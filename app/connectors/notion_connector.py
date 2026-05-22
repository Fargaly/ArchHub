"""Notion connector — drives the Notion REST API v1.

Implements the uniform `connectors.base.Connector` contract. Notion is
where many architecture practices keep their project wikis, issue
trackers and client logs. ArchHub lets the agent read and (carefully)
write that record from the canvas.

Mechanism: REST. Base URL `https://api.notion.com/v1`. Every request
carries the `Notion-Version` header — the API is version-pinned.

Auth model
----------
  Notion uses an internal integration token (starts `ntn_` / `secret_`).
  The user creates an integration at notion.so/my-integrations, shares
  the relevant pages/databases with it, and pastes the token. We send
  it as a bearer token. A rejected token returns HTTP 401.

Settings keys read (via secrets_store):
  notion  — load_api_key('notion') : the integration token

Operations
----------
  READ    notion.search          — search pages + databases
          notion.list_databases  — databases the integration can see
          notion.query_database  — rows of a database (id + filter)
          notion.get_page        — one page's properties
  ACTION  notion.create_page     — new page (destructive)
          notion.update_page     — patch page properties (destructive)
          notion.append_blocks   — append child blocks (destructive)

Every operation returns an `OpResult`; nothing raises to the caller.
Pagination uses Notion's `start_cursor` / `has_more` cursor model.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
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
API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_TIMEOUT_SECONDS = 30
SECRET_KEY = "notion"
MAX_PAGES = 10          # pagination safety cap (×100 rows = 1000)


# ---------------------------------------------------------------------------
def _load_token() -> Optional[str]:
    """Pull the saved Notion integration token, or None if missing."""
    try:
        from secrets_store import load_api_key
        v = load_api_key(SECRET_KEY)
        return v or None
    except Exception:
        return None


def _token_hint() -> str:
    return ("Notion token not set. Open Settings -> Sign-ins -> Notion and "
            "paste an internal integration token from "
            "notion.so/my-integrations. Remember to share the pages or "
            "databases with that integration.")


# ---------------------------------------------------------------------------
def _request(method: str, path: str, *,
             token: str,
             query: Optional[dict] = None,
             body: Optional[dict] = None,
             timeout: int = DEFAULT_TIMEOUT_SECONDS,
             _retry: bool = True) -> dict:
    """Run one Notion REST call.

    Returns:
      {"_ok": True, "data": {...}}            — success (always a dict)
      {"_err": "...", "http_status": int?}    — failure (soft)

    A 429 gets one retry honouring the Retry-After header.
    """
    url = API_BASE.rstrip("/") + "/" + path.lstrip("/")
    if query:
        q = {k: v for k, v in query.items() if v is not None and v != ""}
        if q:
            url = url + "?" + urllib.parse.urlencode(q, doseq=True)
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        if ex.code == 429 and _retry:
            time.sleep(_retry_after(ex))
            return _request(method, path, token=token, query=query,
                            body=body, timeout=timeout, _retry=False)
        try:
            payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        return {"_err": _classify_http(ex.code, payload),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Notion: {ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}

    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        return {"_err": "Notion returned a non-JSON response."}
    if not isinstance(parsed, dict):
        return {"_err": "Notion returned an unexpected response shape."}
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
    """Translate an HTTP status into an actionable message — uses
    Notion's own `message` field from the error body when present."""
    api_msg = ""
    try:
        d = json.loads(payload) if payload else {}
        if isinstance(d, dict):
            api_msg = str(d.get("message") or "")
    except Exception:
        api_msg = (payload or "")[:200]
    if code == 401:
        return ("Notion token rejected (401). Open Settings -> Sign-ins "
                "-> Notion and paste a fresh integration token.")
    if code == 403:
        return ("Notion denied access (403) — the integration is valid "
                "but the page or database has not been shared with it. "
                "Open the page in Notion -> ... -> Connections -> add "
                "your integration.")
    if code == 404:
        return (f"Notion object not found (404). Either the id is wrong "
                f"or it is not shared with the integration. {api_msg}"
                ).strip()
    if code == 400:
        return f"Notion rejected the request (400). {api_msg}".strip()
    if code == 409:
        return f"Notion conflict (409) — retry. {api_msg}".strip()
    if code == 429:
        return "Notion rate limit hit (429). Wait a moment and retry."
    if code >= 500:
        return f"Notion server error ({code}). Retry shortly."
    return f"Notion HTTP {code}: {api_msg}".strip()


def _paginate(path: str, *, token: str,
              body: Optional[dict] = None,
              query: Optional[dict] = None,
              method: str = "POST") -> dict:
    """Walk Notion's cursor pagination, accumulating `results`.

    Returns {"_ok": True, "results": [...]} or {"_err": "..."}.
    Capped at MAX_PAGES pages so a runaway database can't hang the
    canvas.
    """
    out: list = []
    cursor: Optional[str] = None
    for _ in range(MAX_PAGES):
        if method.upper() == "POST":
            page_body = dict(body or {})
            page_body["page_size"] = 100
            if cursor:
                page_body["start_cursor"] = cursor
            r = _request("POST", path, token=token, body=page_body)
        else:
            page_query = dict(query or {})
            page_query["page_size"] = 100
            if cursor:
                page_query["start_cursor"] = cursor
            r = _request("GET", path, token=token, query=page_query)
        if "_err" in r:
            # If we already gathered some results, return them rather
            # than throwing the whole call away.
            if out:
                return {"_ok": True, "results": out, "_partial": r["_err"]}
            return r
        data = r.get("data") or {}
        out.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return {"_ok": True, "results": out}


# ---------------------------------------------------------------------------
# Property / title helpers — Notion's property model is deeply nested.
# ---------------------------------------------------------------------------
def _plain_text(rich: Any) -> str:
    """Flatten a Notion rich_text / title array to plain text."""
    if not isinstance(rich, list):
        return ""
    parts = []
    for seg in rich:
        if isinstance(seg, dict):
            parts.append(str(seg.get("plain_text")
                              or (seg.get("text") or {}).get("content")
                              or ""))
    return "".join(parts)


def _object_title(obj: dict) -> str:
    """Best-effort title for a page or database object."""
    if not isinstance(obj, dict):
        return ""
    # Database objects carry a top-level `title` array.
    if obj.get("object") == "database":
        return _plain_text(obj.get("title")) or "(untitled database)"
    # Pages carry the title inside `properties` under a title-typed prop.
    props = obj.get("properties") or {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            t = _plain_text(prop.get("title"))
            if t:
                return t
    return "(untitled)"


def _simplify_property(prop: dict) -> Any:
    """Reduce one Notion property value to a plain Python scalar/list."""
    if not isinstance(prop, dict):
        return None
    ptype = prop.get("type")
    val = prop.get(ptype) if ptype else None
    if ptype in ("title", "rich_text"):
        return _plain_text(val)
    if ptype in ("number", "checkbox", "url", "email", "phone_number"):
        return val
    if ptype == "select":
        return (val or {}).get("name") if isinstance(val, dict) else None
    if ptype == "status":
        return (val or {}).get("name") if isinstance(val, dict) else None
    if ptype == "multi_select":
        return [o.get("name") for o in (val or [])
                if isinstance(o, dict)]
    if ptype == "date":
        if isinstance(val, dict):
            return {"start": val.get("start"), "end": val.get("end")}
        return None
    if ptype == "people":
        return [p.get("name") or p.get("id") for p in (val or [])
                if isinstance(p, dict)]
    if ptype in ("created_time", "last_edited_time"):
        return val
    if ptype == "formula":
        if isinstance(val, dict):
            return val.get(val.get("type"))
        return None
    if ptype in ("files", "relation"):
        return [f.get("name") or f.get("id") for f in (val or [])
                if isinstance(f, dict)]
    return val


def _simplify_page(page: dict) -> dict:
    """Reduce a Notion page object to a flat, readable dict."""
    props = page.get("properties") or {}
    simple = {k: _simplify_property(v) for k, v in props.items()}
    return {
        "id": page.get("id"),
        "title": _object_title(page),
        "url": page.get("url"),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "archived": page.get("archived"),
        "properties": simple,
    }


# ---------------------------------------------------------------------------
# Operation implementations.
# ---------------------------------------------------------------------------
def _op_search(query: str = "", filter_type: str = "",
               limit: int = 25, **_: Any) -> OpResult:
    """Search pages and databases the integration can access."""
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        lim = max(1, min(int(limit or 25), 100))
    except Exception:
        lim = 25
    body: dict = {}
    if query and str(query).strip():
        body["query"] = str(query).strip()
    ft = str(filter_type or "").strip().lower()
    if ft in ("page", "database"):
        body["filter"] = {"property": "object", "value": ft}
    r = _request("POST", "search", token=token, body=body)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    results = (r.get("data") or {}).get("results") or []
    items = []
    for obj in results[:lim]:
        items.append({
            "id": obj.get("id"),
            "object": obj.get("object"),
            "title": _object_title(obj),
            "url": obj.get("url"),
            "last_edited_time": obj.get("last_edited_time"),
        })
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} result"
                                  f"{'s' if len(items) != 1 else ''}")


def _op_list_databases(limit: int = 50, **_: Any) -> OpResult:
    """List databases shared with the integration (search filtered)."""
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        lim = max(1, min(int(limit or 50), 100))
    except Exception:
        lim = 50
    r = _request("POST", "search", token=token,
                 body={"filter": {"property": "object",
                                  "value": "database"}})
    if "_err" in r:
        return OpResult.fail(r["_err"])
    results = (r.get("data") or {}).get("results") or []
    items = []
    for db in results[:lim]:
        items.append({
            "id": db.get("id"),
            "title": _object_title(db),
            "url": db.get("url"),
            "last_edited_time": db.get("last_edited_time"),
            "property_names": list((db.get("properties") or {}).keys()),
        })
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} database"
                                  f"{'s' if len(items) != 1 else ''}")


def _op_query_database(database_id: str = "", filter: Any = None,
                        sorts: Any = None, **_: Any) -> OpResult:
    """Query rows of a database. `filter` and `sorts` are passed through
    to Notion's query API verbatim (a dict / list, or a JSON string)."""
    if not database_id or not str(database_id).strip():
        return OpResult.fail("database_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    body: dict = {}

    parsed_filter = _coerce_json(filter)
    if isinstance(parsed_filter, dict) and parsed_filter:
        body["filter"] = parsed_filter
    elif filter not in (None, "", {}):
        return OpResult.fail("filter must be a Notion filter object "
                             "(dict) or a JSON string of one.")

    parsed_sorts = _coerce_json(sorts)
    if isinstance(parsed_sorts, list) and parsed_sorts:
        body["sorts"] = parsed_sorts

    path = f"databases/{str(database_id).strip()}/query"
    r = _paginate(path, token=token, body=body, method="POST")
    if "_err" in r:
        return OpResult.fail(r["_err"])
    rows = [_simplify_page(p) for p in (r.get("results") or [])]
    preview = f"{len(rows)} row{'s' if len(rows) != 1 else ''}"
    if r.get("_partial"):
        preview += " (partial — " + str(r["_partial"])[:60] + ")"
    return OpResult(ok=True, value=rows, value_preview=preview)


def _op_get_page(page_id: str = "", **_: Any) -> OpResult:
    """Fetch one page's properties."""
    if not page_id or not str(page_id).strip():
        return OpResult.fail("page_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    r = _request("GET", f"pages/{str(page_id).strip()}", token=token)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    page = r.get("data") or {}
    out = _simplify_page(page)
    return OpResult(ok=True, value=out,
                    value_preview=out.get("title") or "(page)")


def _op_create_page(parent_id: str = "", parent_type: str = "database_id",
                     title: str = "", properties: Any = None,
                     **_: Any) -> OpResult:
    """Create a new page. DESTRUCTIVE — writes to Notion.

    `parent_type` is "database_id" (default) or "page_id". When the
    parent is a database, `title` lands in the database's title
    property. `properties` (a dict / JSON string) is merged in for
    additional database fields.
    """
    if not parent_id or not str(parent_id).strip():
        return OpResult.fail("parent_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    ptype = str(parent_type or "database_id").strip()
    if ptype not in ("database_id", "page_id"):
        return OpResult.fail("parent_type must be 'database_id' or "
                             "'page_id'.")
    parent = {ptype: str(parent_id).strip()}

    props: dict = {}
    extra = _coerce_json(properties)
    if isinstance(extra, dict):
        props.update(extra)
    elif properties not in (None, "", {}):
        return OpResult.fail("properties must be a dict or a JSON string "
                             "of one.")

    if title and str(title).strip():
        title_block = {"title": [{"text": {"content": str(title)}}]}
        if ptype == "page_id":
            # A page-parented page uses the reserved "title" property.
            props.setdefault("title", title_block)
        else:
            # Database-parented: find the title-typed property name, or
            # default to "Name" (Notion's default title column).
            props.setdefault("Name", title_block)

    if not props:
        return OpResult.fail("Provide a title or a properties object.")

    body = {"parent": parent, "properties": props}
    r = _request("POST", "pages", token=token, body=body)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    page = r.get("data") or {}
    out = _simplify_page(page)
    return OpResult(ok=True, value=out,
                    value_preview=f"created '{out.get('title')}'")


def _op_update_page(page_id: str = "", properties: Any = None,
                     archived: Any = None, **_: Any) -> OpResult:
    """Patch a page's properties. DESTRUCTIVE — writes to Notion."""
    if not page_id or not str(page_id).strip():
        return OpResult.fail("page_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    body: dict = {}
    props = _coerce_json(properties)
    if isinstance(props, dict) and props:
        body["properties"] = props
    elif properties not in (None, "", {}):
        return OpResult.fail("properties must be a dict or JSON string.")
    if archived is not None:
        body["archived"] = bool(archived)
    if not body:
        return OpResult.fail("Provide properties to update or an "
                             "archived flag.")
    r = _request("PATCH", f"pages/{str(page_id).strip()}",
                 token=token, body=body)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    page = r.get("data") or {}
    out = _simplify_page(page)
    return OpResult(ok=True, value=out,
                    value_preview=f"updated '{out.get('title')}'")


def _op_append_blocks(block_id: str = "", text: str = "",
                       children: Any = None, **_: Any) -> OpResult:
    """Append child blocks to a page or block. DESTRUCTIVE.

    Either pass `children` (a Notion block array, dict / JSON string) or
    `text` — a plain string appended as one paragraph block.
    """
    if not block_id or not str(block_id).strip():
        return OpResult.fail("block_id is required (a page id or "
                             "block id).")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())

    blocks = _coerce_json(children)
    if isinstance(blocks, dict):
        blocks = [blocks]
    if not isinstance(blocks, list) or not blocks:
        if text and str(text).strip():
            blocks = [{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text",
                                   "text": {"content": str(text)}}],
                },
            }]
        else:
            return OpResult.fail("Provide `text` or a `children` block "
                                 "array.")

    body = {"children": blocks}
    r = _request("PATCH", f"blocks/{str(block_id).strip()}/children",
                 token=token, body=body)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    results = (r.get("data") or {}).get("results") or []
    return OpResult(ok=True,
                    value={"appended": len(results),
                           "block_ids": [b.get("id") for b in results]},
                    value_preview=f"appended {len(results)} block"
                                  f"{'s' if len(results) != 1 else ''}")


def _coerce_json(value: Any) -> Any:
    """Accept a dict/list as-is, or parse a JSON string into one.
    Anything else (None, blank) returns None."""
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
class NotionConnector(Connector):
    """Notion REST API connector."""

    host = "notion"
    display_name = "Notion"
    mechanism = "rest"

    # -- status -------------------------------------------------------
    def probe(self) -> dict:
        """Honest status:
          no token            -> unauthorized
          token + /users/me   -> live
          network / bad token -> missing
        """
        token = _load_token()
        if not token:
            return {"status": "unauthorized", "note": _token_hint(),
                    "detail": {}}
        # Cheap real auth check — the bot user is GET /users/me.
        r = _request("GET", "users/me", token=token, timeout=12)
        if "_err" in r:
            status = "unauthorized" if r.get("http_status") == 401 \
                else "missing"
            return {"status": status, "note": r["_err"], "detail": {}}
        me = r.get("data") or {}
        name = me.get("name") or "integration"
        bot = me.get("bot") or {}
        ws = ""
        if isinstance(bot, dict):
            ws = (bot.get("workspace_name") or "")
        note = f"Connected as '{name}'"
        if ws:
            note += f" in workspace '{ws}'"
        return {
            "status": "live",
            "note": note,
            "detail": {"bot_id": me.get("id"), "name": name,
                       "workspace": ws},
        }

    # -- operations ---------------------------------------------------
    def build_ops(self) -> list:
        return [
            ConnectorOp(
                op_id="notion.search",
                host="notion", kind="read",
                label="Search",
                description="Search pages and databases shared with the "
                            "Notion integration.",
                inputs=[
                    ParamSpec(id="query", label="Query", type="text",
                              default="",
                              help="Text to match in titles. Blank lists "
                                   "everything shared."),
                    ParamSpec(id="filter_type", label="Object type",
                              type="choice", default="",
                              options=["", "page", "database"],
                              help="Restrict to pages or databases."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=25,
                              help="Max results (1-100)."),
                ],
                output_type="list",
                fn=_op_search,
            ),
            ConnectorOp(
                op_id="notion.list_databases",
                host="notion", kind="read",
                label="List databases",
                description="List databases the integration can access.",
                inputs=[
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=50,
                              help="Max databases (1-100)."),
                ],
                output_type="list",
                fn=_op_list_databases,
            ),
            ConnectorOp(
                op_id="notion.query_database",
                host="notion", kind="read",
                label="Query database",
                description="Query rows of a Notion database with an "
                            "optional filter and sort.",
                inputs=[
                    ParamSpec(id="database_id", label="Database ID",
                              type="text", required=True,
                              options_source="notion.list_databases",
                              help="The database to query."),
                    ParamSpec(id="filter", label="Filter", type="text",
                              default="",
                              help="A Notion filter object as JSON, e.g. "
                                   '{"property":"Status","status":'
                                   '{"equals":"Done"}}.'),
                    ParamSpec(id="sorts", label="Sorts", type="text",
                              default="",
                              help="A Notion sorts array as JSON."),
                ],
                output_type="list",
                fn=_op_query_database,
            ),
            ConnectorOp(
                op_id="notion.get_page",
                host="notion", kind="read",
                label="Get page",
                description="Fetch one Notion page's properties.",
                inputs=[
                    ParamSpec(id="page_id", label="Page ID", type="text",
                              required=True,
                              help="The page id."),
                ],
                output_type="dict",
                fn=_op_get_page,
            ),
            ConnectorOp(
                op_id="notion.create_page",
                host="notion", kind="action",
                label="Create page",
                description="Create a new Notion page under a database or "
                            "page parent. Writes to Notion.",
                inputs=[
                    ParamSpec(id="parent_id", label="Parent ID",
                              type="text", required=True,
                              help="A database id or page id."),
                    ParamSpec(id="parent_type", label="Parent type",
                              type="choice", default="database_id",
                              options=["database_id", "page_id"]),
                    ParamSpec(id="title", label="Title", type="text",
                              default="",
                              help="The page title."),
                    ParamSpec(id="properties", label="Properties",
                              type="text", default="",
                              help="Extra Notion property values as JSON."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_create_page,
            ),
            ConnectorOp(
                op_id="notion.update_page",
                host="notion", kind="action",
                label="Update page",
                description="Patch a Notion page's properties (or archive "
                            "it). Writes to Notion.",
                inputs=[
                    ParamSpec(id="page_id", label="Page ID", type="text",
                              required=True),
                    ParamSpec(id="properties", label="Properties",
                              type="text", default="",
                              help="Notion property values as JSON."),
                    ParamSpec(id="archived", label="Archive", type="bool",
                              default=None,
                              help="Set true to move the page to trash."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_update_page,
            ),
            ConnectorOp(
                op_id="notion.append_blocks",
                host="notion", kind="action",
                label="Append blocks",
                description="Append content blocks to a Notion page or "
                            "block. Writes to Notion.",
                inputs=[
                    ParamSpec(id="block_id", label="Page / block ID",
                              type="text", required=True,
                              help="The page or block to append to."),
                    ParamSpec(id="text", label="Text", type="text",
                              default="",
                              help="Plain text appended as one paragraph."),
                    ParamSpec(id="children", label="Block children",
                              type="text", default="",
                              help="A Notion block array as JSON "
                                   "(overrides `text`)."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_append_blocks,
            ),
        ]


# ── register at import time ─────────────────────────────────────────
register(NotionConnector())
