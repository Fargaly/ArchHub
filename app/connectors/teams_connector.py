"""Microsoft Teams connector — drives the Microsoft Graph API v1.0.

Implements the uniform `connectors.base.Connector` contract. Project
coordination for many practices runs through Teams channels; ArchHub
lets the agent read those channels, messages and meetings and post
updates from the canvas.

Mechanism: REST. Base URL `https://graph.microsoft.com/v1.0`.

Auth model
----------
  Microsoft Graph uses OAuth2. Teams channel/message endpoints require
  a *delegated* token (acting as a signed-in user) — application tokens
  cannot read channel messages without protected-API approval. The user
  obtains a delegated access token (Azure AD app with delegated
  Group.Read.All / ChannelMessage.Send / Channel.ReadBasic.All scopes,
  via an OAuth2 flow) and pastes it. We send it as a bearer token and
  do not refresh; a 401 means the (typically ~1 h) token expired.

Settings keys read (via secrets_store):
  teams  — load_api_key('teams') : the delegated OAuth2 access token

Operations
----------
  READ    teams.list_teams      — teams the user joined
          teams.list_channels   — channels of a team
          teams.list_messages   — messages in a channel
          teams.list_meetings   — the user's online meetings / events
  ACTION  teams.post_message    — post a channel message (destructive)

Every operation returns an `OpResult`; nothing raises to the caller.
Pagination follows Graph's `@odata.nextLink` model.
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
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_TIMEOUT_SECONDS = 30
SECRET_KEY = "teams"
MAX_PAGES = 10        # @odata.nextLink pagination cap


# ---------------------------------------------------------------------------
def _load_token() -> Optional[str]:
    """Pull the saved Microsoft Graph delegated token, or None."""
    try:
        from secrets_store import load_api_key
        v = load_api_key(SECRET_KEY)
        return v or None
    except Exception:
        return None


def _token_hint() -> str:
    return ("Microsoft Teams token not set. Open Settings -> Sign-ins -> "
            "Teams and paste a delegated Microsoft Graph access token "
            "(Azure AD app with Group.Read.All, Channel.ReadBasic.All, "
            "ChannelMessage.Send delegated scopes).")


# ---------------------------------------------------------------------------
def _request(method: str, url_or_path: str, *,
             token: str,
             query: Optional[dict] = None,
             body: Optional[dict] = None,
             timeout: int = DEFAULT_TIMEOUT_SECONDS,
             _retry: bool = True) -> dict:
    """Run one Microsoft Graph call.

    `url_or_path` is either a path relative to GRAPH_BASE or a full URL
    (used to follow `@odata.nextLink`).

    Returns {"_ok": True, "data": {...}} or {"_err": "...",
    "http_status": int?}. A 429 gets one retry honouring Retry-After.
    """
    if url_or_path.startswith("http://") or \
            url_or_path.startswith("https://"):
        url = url_or_path
    else:
        url = GRAPH_BASE.rstrip("/") + "/" + url_or_path.lstrip("/")
    if query:
        q = {k: v for k, v in query.items() if v is not None and v != ""}
        if q:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(q, doseq=True)
    headers = {
        "Authorization": f"Bearer {token}",
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
            return _request(method, url_or_path, token=token,
                            query=query, body=body, timeout=timeout,
                            _retry=False)
        try:
            payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        return {"_err": _classify_http(ex.code, payload),
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"_err": f"Network error reaching Microsoft Graph: "
                        f"{ex.reason}"}
    except Exception as ex:
        return {"_err": f"{type(ex).__name__}: {ex}"}

    if not raw:
        # Some Graph writes return 204 No Content.
        return {"_ok": True, "data": {}}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {"_err": "Microsoft Graph returned a non-JSON response."}
    if not isinstance(parsed, dict):
        return {"_err": "Microsoft Graph returned an unexpected shape."}
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
    """Translate an HTTP status into an actionable message. Graph error
    bodies carry `{"error": {"code": ..., "message": ...}}`."""
    api_msg = ""
    try:
        d = json.loads(payload) if payload else {}
        if isinstance(d, dict):
            err = d.get("error")
            if isinstance(err, dict):
                api_msg = str(err.get("message") or "")
    except Exception:
        api_msg = (payload or "")[:200]
    if code == 401:
        return ("Microsoft Teams token rejected (401) — the delegated "
                "token has likely expired. Open Settings -> Sign-ins -> "
                "Teams and paste a fresh access token.")
    if code == 403:
        return (f"Microsoft Graph denied access (403) — the token lacks "
                f"the required delegated scope (e.g. Channel.ReadBasic."
                f"All, ChannelMessage.Send). {api_msg}").strip()
    if code == 404:
        return f"Microsoft Graph resource not found (404). {api_msg}".strip()
    if code == 400:
        return f"Microsoft Graph rejected the request (400). {api_msg}".strip()
    if code == 429:
        return ("Microsoft Graph throttled the request (429). Wait a "
                "moment and retry.")
    if code >= 500:
        return f"Microsoft Graph server error ({code}). Retry shortly."
    return f"Microsoft Graph HTTP {code}: {api_msg}".strip()


def _paginate(path: str, *, token: str,
              query: Optional[dict] = None,
              cap: int = 100) -> dict:
    """Walk Graph's @odata.nextLink pagination, accumulating `value`.

    Returns {"_ok": True, "value": [...]} or {"_err": "..."}.
    """
    out: list = []
    next_url: Optional[str] = None
    first = True
    for _ in range(MAX_PAGES):
        if first:
            r = _request("GET", path, token=token, query=query)
            first = False
        else:
            if not next_url:
                break
            r = _request("GET", next_url, token=token)
        if "_err" in r:
            if out:
                return {"_ok": True, "value": out, "_partial": r["_err"]}
            return r
        data = r.get("data") or {}
        out.extend(data.get("value") or [])
        if len(out) >= cap:
            break
        next_url = data.get("@odata.nextLink")
        if not next_url:
            break
    return {"_ok": True, "value": out}


def _extract_body_text(body: Any) -> str:
    """Pull plain text out of a Graph itemBody object."""
    if not isinstance(body, dict):
        return ""
    content = str(body.get("content") or "")
    if body.get("contentType") == "html":
        # Cheap tag strip — enough for a preview / readable value.
        import re
        text = re.sub(r"<[^>]+>", "", content)
        return text.replace("&nbsp;", " ").strip()
    return content.strip()


# ---------------------------------------------------------------------------
# Operation implementations.
# ---------------------------------------------------------------------------
def _op_list_teams(limit: int = 50, **_: Any) -> OpResult:
    """List the teams the signed-in user has joined."""
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        cap = max(1, min(int(limit or 50), 200))
    except Exception:
        cap = 50
    # /me/joinedTeams is the delegated endpoint for a user's teams.
    r = _paginate("me/joinedTeams", token=token,
                  query={"$select": "id,displayName,description"},
                  cap=cap)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    items = []
    for t in (r.get("value") or [])[:cap]:
        items.append({
            "id": t.get("id"),
            "name": t.get("displayName"),
            "description": t.get("description") or "",
        })
    preview = f"{len(items)} team{'s' if len(items) != 1 else ''}"
    if r.get("_partial"):
        preview += " (partial)"
    return OpResult(ok=True, value=items, value_preview=preview)


def _op_list_channels(team_id: str = "", limit: int = 50,
                       **_: Any) -> OpResult:
    """List the channels of a team."""
    if not team_id or not str(team_id).strip():
        return OpResult.fail("team_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        cap = max(1, min(int(limit or 50), 200))
    except Exception:
        cap = 50
    path = f"teams/{str(team_id).strip()}/channels"
    r = _paginate(path, token=token,
                  query={"$select": "id,displayName,description,"
                                    "membershipType,webUrl"},
                  cap=cap)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    items = []
    for c in (r.get("value") or [])[:cap]:
        items.append({
            "id": c.get("id"),
            "name": c.get("displayName"),
            "description": c.get("description") or "",
            "membership_type": c.get("membershipType"),
            "web_url": c.get("webUrl"),
        })
    return OpResult(ok=True, value=items,
                    value_preview=f"{len(items)} channel"
                                  f"{'s' if len(items) != 1 else ''}")


def _op_list_messages(team_id: str = "", channel_id: str = "",
                       limit: int = 20, **_: Any) -> OpResult:
    """List messages in a team channel, newest first."""
    if not team_id or not str(team_id).strip():
        return OpResult.fail("team_id is required.")
    if not channel_id or not str(channel_id).strip():
        return OpResult.fail("channel_id is required.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        cap = max(1, min(int(limit or 20), 50))
    except Exception:
        cap = 20
    path = (f"teams/{str(team_id).strip()}/channels/"
            f"{str(channel_id).strip()}/messages")
    # Graph caps channel-message $top at 50.
    r = _paginate(path, token=token, query={"$top": min(cap, 50)},
                  cap=cap)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    items = []
    for m in (r.get("value") or [])[:cap]:
        frm = m.get("from") or {}
        user = (frm.get("user") or {}) if isinstance(frm, dict) else {}
        items.append({
            "id": m.get("id"),
            "created": m.get("createdDateTime"),
            "last_modified": m.get("lastModifiedDateTime"),
            "from": user.get("displayName") if isinstance(user, dict)
            else None,
            "importance": m.get("importance"),
            "message_type": m.get("messageType"),
            "text": _extract_body_text(m.get("body")),
            "web_url": m.get("webUrl"),
        })
    preview = f"{len(items)} message{'s' if len(items) != 1 else ''}"
    if r.get("_partial"):
        preview += " (partial)"
    return OpResult(ok=True, value=items, value_preview=preview)


def _op_list_meetings(limit: int = 20, **_: Any) -> OpResult:
    """List the signed-in user's upcoming calendar events (meetings).

    Graph's onlineMeetings endpoint requires a join URL to look one up;
    the user's calendar events are the practical 'my meetings' list and
    flag which are Teams meetings via `isOnlineMeeting`.
    """
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    try:
        cap = max(1, min(int(limit or 20), 100))
    except Exception:
        cap = 20
    r = _paginate("me/events", token=token,
                  query={"$select": "id,subject,start,end,organizer,"
                                    "isOnlineMeeting,onlineMeeting,webLink",
                         "$orderby": "start/dateTime desc",
                         "$top": min(cap, 50)},
                  cap=cap)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    items = []
    for e in (r.get("value") or [])[:cap]:
        organizer = ((e.get("organizer") or {}).get("emailAddress")
                     or {}) if isinstance(e.get("organizer"), dict) else {}
        online = e.get("onlineMeeting") or {}
        items.append({
            "id": e.get("id"),
            "subject": e.get("subject"),
            "start": (e.get("start") or {}).get("dateTime"),
            "end": (e.get("end") or {}).get("dateTime"),
            "organizer": organizer.get("name") or organizer.get("address"),
            "is_online_meeting": e.get("isOnlineMeeting"),
            "join_url": online.get("joinUrl")
            if isinstance(online, dict) else None,
            "web_link": e.get("webLink"),
        })
    preview = f"{len(items)} meeting{'s' if len(items) != 1 else ''}"
    if r.get("_partial"):
        preview += " (partial)"
    return OpResult(ok=True, value=items, value_preview=preview)


def _op_post_message(team_id: str = "", channel_id: str = "",
                      text: str = "", content_type: str = "text",
                      **_: Any) -> OpResult:
    """Post a message to a team channel. DESTRUCTIVE — writes to Teams."""
    if not team_id or not str(team_id).strip():
        return OpResult.fail("team_id is required.")
    if not channel_id or not str(channel_id).strip():
        return OpResult.fail("channel_id is required.")
    if not text or not str(text).strip():
        return OpResult.fail("text is required — the message body.")
    token = _load_token()
    if not token:
        return OpResult.fail(_token_hint())
    ctype = str(content_type or "text").strip().lower()
    if ctype not in ("text", "html"):
        return OpResult.fail("content_type must be 'text' or 'html'.")
    path = (f"teams/{str(team_id).strip()}/channels/"
            f"{str(channel_id).strip()}/messages")
    body = {"body": {"contentType": ctype, "content": str(text)}}
    r = _request("POST", path, token=token, body=body)
    if "_err" in r:
        return OpResult.fail(r["_err"])
    msg = r.get("data") or {}
    out = {
        "id": msg.get("id"),
        "created": msg.get("createdDateTime"),
        "web_url": msg.get("webUrl"),
    }
    return OpResult(ok=True, value=out,
                    value_preview=f"posted message {msg.get('id') or ''}"
                    .strip())


# ---------------------------------------------------------------------------
class TeamsConnector(Connector):
    """Microsoft Teams (Graph API) connector."""

    host = "teams"
    display_name = "Microsoft Teams"
    mechanism = "rest"

    # -- status -------------------------------------------------------
    def probe(self) -> dict:
        """Honest status:
          no token        -> unauthorized
          token + /me ok  -> live
          network / bad   -> missing
        """
        token = _load_token()
        if not token:
            return {"status": "unauthorized", "note": _token_hint(),
                    "detail": {}}
        # Cheap real auth check — GET /me resolves the signed-in user.
        r = _request("GET", "me", token=token,
                     query={"$select": "id,displayName,"
                                       "userPrincipalName"},
                     timeout=12)
        if "_err" in r:
            status = "unauthorized" if r.get("http_status") == 401 \
                else "missing"
            return {"status": status, "note": r["_err"], "detail": {}}
        me = r.get("data") or {}
        name = me.get("displayName") or me.get("userPrincipalName") \
            or "user"
        return {
            "status": "live",
            "note": f"Signed in as {name}",
            "detail": {"user_id": me.get("id"),
                       "name": me.get("displayName"),
                       "upn": me.get("userPrincipalName")},
        }

    # -- operations ---------------------------------------------------
    def build_ops(self) -> list:
        return [
            ConnectorOp(
                op_id="teams.list_teams",
                host="teams", kind="read",
                label="List teams",
                description="List the teams the signed-in user has "
                            "joined.",
                inputs=[
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=50,
                              help="Max teams (1-200)."),
                ],
                output_type="list",
                fn=_op_list_teams,
            ),
            ConnectorOp(
                op_id="teams.list_channels",
                host="teams", kind="read",
                label="List channels",
                description="List the channels of a Microsoft team.",
                inputs=[
                    ParamSpec(id="team_id", label="Team ID", type="text",
                              required=True,
                              options_source="teams.list_teams",
                              help="The team id."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=50,
                              help="Max channels (1-200)."),
                ],
                output_type="list",
                fn=_op_list_channels,
            ),
            ConnectorOp(
                op_id="teams.list_messages",
                host="teams", kind="read",
                label="List messages",
                description="List messages in a Teams channel.",
                inputs=[
                    ParamSpec(id="team_id", label="Team ID", type="text",
                              required=True,
                              options_source="teams.list_teams",
                              help="The team id."),
                    ParamSpec(id="channel_id", label="Channel ID",
                              type="text", required=True,
                              options_source="teams.list_channels",
                              help="The channel id."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=20,
                              help="Max messages (1-50)."),
                ],
                output_type="list",
                fn=_op_list_messages,
            ),
            ConnectorOp(
                op_id="teams.list_meetings",
                host="teams", kind="read",
                label="List meetings",
                description="List the signed-in user's calendar events, "
                            "flagging Teams online meetings.",
                inputs=[
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=20,
                              help="Max events (1-100)."),
                ],
                output_type="list",
                fn=_op_list_meetings,
            ),
            ConnectorOp(
                op_id="teams.post_message",
                host="teams", kind="action",
                label="Post message",
                description="Post a message to a Teams channel. Writes to "
                            "Teams.",
                inputs=[
                    ParamSpec(id="team_id", label="Team ID", type="text",
                              required=True,
                              options_source="teams.list_teams",
                              help="The team id."),
                    ParamSpec(id="channel_id", label="Channel ID",
                              type="text", required=True,
                              options_source="teams.list_channels",
                              help="The channel id."),
                    ParamSpec(id="text", label="Message", type="text",
                              required=True,
                              help="The message body."),
                    ParamSpec(id="content_type", label="Content type",
                              type="choice", default="text",
                              options=["text", "html"]),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_post_message,
            ),
        ]


# ── register at import time ─────────────────────────────────────────
register(TeamsConnector())
