"""Procore connector — drives Procore's REST API via stdlib HTTP.

Architecture mirrors `outlook_runner`: stateless module-level functions,
no localhost listener, no broker. Each call resolves the user's saved
access token + active company / project context from `secrets_store`
and hits api.procore.com directly.

Procore is the dominant SaaS for construction project management —
RFIs, submittals, change orders, daily logs, drawings. Architects in
the field need their AI to read and (carefully) write to the project
record without copy-pasting between web and chat.

Auth model
----------
  Procore exposes OAuth2 (Authorization Code or Client Credentials)
  but for desktop tooling the simplest path is a long-lived Personal
  Access Token / DCS token the user generates in the Procore admin
  UI. We treat it as a bearer token; the runner does not currently
  refresh it. When 401 comes back the surface error tells the user
  to re-paste in Settings.

Settings keys read:
  procore_access_token  — secrets_store.load_api_key('procore_access_token')
  procore_company_id    — load_setting('procore_company_id')
  procore_project_id    — load_setting('procore_project_id')

Active project / company can be overridden per call via the
`project_id` / `company_id` kwargs so a "@token" mention in chat
can target a different project than the saved default.

Endpoints
---------
  Production:  https://api.procore.com/rest/v1.0
  Sandbox:     https://sandbox.procore.com/rest/v1.0

Pick base by reading `load_setting('procore_sandbox')` — falsey →
production. The handler is read-mostly; the one write surface
(create_rfi) defaults to the "ask" policy in ai_behaviour so the
model can't silently file an RFI against a live project.

Return shape (consistent with other runners):
  list endpoints   → {"status": "ok", "items": [...]}
  get endpoints    → {"status": "ok", "<entity>": {...}}
  create endpoints → {"status": "ok", "<entity>": {...}, "id": N}
  errors           → {"status": "error", "error": "...", "http_status": int?}
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


# ---------------------------------------------------------------------------
PROD_BASE    = "https://api.procore.com/rest/v1.0"
SANDBOX_BASE = "https://sandbox.procore.com/rest/v1.0"
DEFAULT_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
def _load_token() -> Optional[str]:
    """Pull the saved Procore bearer token, or None if missing."""
    try:
        from secrets_store import load_api_key
        v = load_api_key("procore_access_token")
        return v or None
    except Exception:
        return None


def _load_company_id(override: Optional[int] = None) -> Optional[int]:
    if override is not None:
        try:
            return int(override)
        except Exception:
            return None
    try:
        from secrets_store import load_setting
        v = load_setting("procore_company_id")
        return int(v) if v else None
    except Exception:
        return None


def _load_project_id(override: Optional[int] = None) -> Optional[int]:
    if override is not None:
        try:
            return int(override)
        except Exception:
            return None
    try:
        from secrets_store import load_setting
        v = load_setting("procore_project_id")
        return int(v) if v else None
    except Exception:
        return None


def _base_url() -> str:
    try:
        from secrets_store import load_setting
        if load_setting("procore_sandbox"):
            return SANDBOX_BASE
    except Exception:
        pass
    return PROD_BASE


def _missing_token_error() -> dict:
    return {
        "status": "error",
        "error": (
            "Procore access token not set. Open Settings → Sign-ins → "
            "Procore and paste a Personal Access Token from "
            "developers.procore.com."
        ),
    }


def _missing_project_error() -> dict:
    return {
        "status": "error",
        "error": (
            "No active Procore project. Set procore_project_id in "
            "Settings → Sign-ins → Procore, or pass project_id explicitly."
        ),
    }


# ---------------------------------------------------------------------------
def _request(method: str, path: str, *,
             token: str,
             company_id: Optional[int] = None,
             query: Optional[dict] = None,
             body: Optional[dict] = None,
             timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Run one Procore REST call. Returns either the parsed JSON
    response on success (always wrapped — list endpoints return a list
    so we wrap as {"items": [...]}; dict endpoints return as-is) or a
    {"status": "error", ...} envelope on failure.

    Procore requires the company id in a header (`Procore-Company-Id`)
    on most endpoints; we always send it when known so callers don't
    have to remember.
    """
    url = _base_url().rstrip("/") + "/" + path.lstrip("/")
    if query:
        q = {k: v for k, v in query.items() if v is not None and v != ""}
        if q:
            url = url + "?" + urllib.parse.urlencode(q, doseq=True)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if company_id is not None:
        headers["Procore-Company-Id"] = str(company_id)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                   method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = raw
        if isinstance(parsed, list):
            return {"_ok": True, "items": parsed}
        if isinstance(parsed, dict):
            return {"_ok": True, "data": parsed}
        return {"_ok": True, "data": parsed}
    except urllib.error.HTTPError as ex:
        # Try to surface the API's error message.
        try:
            payload = ex.read().decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        msg = _classify_http(ex.code, payload)
        return {"status": "error",
                "error": msg,
                "http_status": int(ex.code)}
    except urllib.error.URLError as ex:
        return {"status": "error",
                "error": f"Network error reaching Procore: {ex.reason}"}
    except Exception as ex:
        return {"status": "error",
                "error": f"{type(ex).__name__}: {ex}"}


def _classify_http(code: int, payload: str) -> str:
    """Translate HTTP status codes into a hint the user can act on."""
    payload_short = (payload or "")[:200]
    if code == 401:
        return ("Procore token rejected (401). Open Settings → Sign-ins → "
                "Procore and paste a fresh Personal Access Token.")
    if code == 403:
        return ("Procore denied access (403) — the token is valid but "
                "lacks permission for this project / company. Check "
                "project membership in Procore.")
    if code == 404:
        return f"Not found in Procore (404). {payload_short}".strip()
    if code == 422:
        return f"Procore rejected the request (422 validation). {payload_short}".strip()
    if code == 429:
        return "Procore rate limit hit (429). Wait a minute and retry."
    if code >= 500:
        return f"Procore server error ({code}). Retry shortly."
    return f"Procore HTTP {code}: {payload_short}".strip()


# ---------------------------------------------------------------------------
def is_reachable() -> bool:
    """Cheap True/False — pings the /me endpoint. Used by status bar."""
    token = _load_token()
    if not token:
        return False
    r = _request("GET", "me", token=token,
                  company_id=_load_company_id(), timeout=10)
    return bool(r.get("_ok"))


def info(project_id: Optional[int] = None,
         company_id: Optional[int] = None) -> dict:
    """Snapshot for Reality Check: company name, active project name,
    project id, user's role."""
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id(company_id)
    pid = _load_project_id(project_id)

    me = _request("GET", "me", token=token, company_id=cid)
    if not me.get("_ok"):
        return me  # already error-envelope
    user = me.get("data") or {}

    company_name = ""
    project_name = ""
    role = ""
    if cid:
        comp = _request("GET", "companies",
                          token=token, company_id=cid)
        if comp.get("_ok"):
            for c in (comp.get("items") or []):
                if int(c.get("id", -1)) == int(cid):
                    company_name = str(c.get("name") or "")
                    break
    if pid:
        proj = _request("GET", f"projects/{int(pid)}",
                          token=token, company_id=cid)
        if proj.get("_ok"):
            d = proj.get("data") or {}
            project_name = str(d.get("name") or "")
            # Procore returns project_number etc. but role lives elsewhere.
    return {
        "status": "ok",
        "user_id":      user.get("id"),
        "user_login":   user.get("login") or user.get("email") or "",
        "user_name":    user.get("name") or "",
        "company_id":   cid,
        "company_name": company_name,
        "project_id":   pid,
        "project_name": project_name,
        "role":         role,
    }


# ---------------------------------------------------------------------------
def list_projects(company_id: Optional[int] = None,
                   limit: int = 50) -> dict:
    """List projects the user has access to in a company."""
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id(company_id)
    if not cid:
        return {"status": "error",
                "error": "No procore_company_id set. Pass company_id explicitly or save one in Settings."}
    r = _request("GET", "projects",
                  token=token, company_id=cid,
                  query={"company_id": cid,
                         "per_page": int(limit or 50)})
    if not r.get("_ok"):
        return r
    items = []
    for p in (r.get("items") or [])[: int(limit or 50)]:
        items.append({
            "id":             p.get("id"),
            "name":           p.get("name"),
            "project_number": p.get("project_number"),
            "active":         p.get("active"),
            "address":        p.get("address"),
        })
    return {"status": "ok", "items": items}


def list_users(project_id: Optional[int] = None,
                limit: int = 50) -> dict:
    """List users on the active project — for assignee lookups."""
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id()
    pid = _load_project_id(project_id)
    if not pid:
        return _missing_project_error()
    r = _request("GET", f"projects/{int(pid)}/users",
                  token=token, company_id=cid,
                  query={"per_page": int(limit or 50)})
    if not r.get("_ok"):
        return r
    items = []
    for u in (r.get("items") or [])[: int(limit or 50)]:
        items.append({
            "id":         u.get("id"),
            "name":       u.get("name"),
            "email":      u.get("email_address") or u.get("email"),
            "title":      u.get("job_title"),
            "company":    (u.get("vendor") or {}).get("name") if isinstance(u.get("vendor"), dict) else None,
        })
    return {"status": "ok", "items": items}


# ---------------------------------------------------------------------------
def list_rfis(project_id: Optional[int] = None,
               status: Optional[str] = None,
               limit: int = 20) -> dict:
    """Return RFIs on the active project, newest first."""
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id()
    pid = _load_project_id(project_id)
    if not pid:
        return _missing_project_error()
    q = {"project_id": pid, "per_page": int(limit or 20)}
    if status:
        q["filters[status]"] = str(status)
    r = _request("GET", "rfis", token=token, company_id=cid, query=q)
    if not r.get("_ok"):
        return r
    items = []
    for it in (r.get("items") or [])[: int(limit or 20)]:
        assignees = it.get("assignees") or []
        assignee_name = ""
        if assignees and isinstance(assignees, list):
            first = assignees[0] if isinstance(assignees[0], dict) else {}
            assignee_name = first.get("name") or first.get("login") or ""
        items.append({
            "id":         it.get("id"),
            "number":     it.get("number") or it.get("full_number"),
            "subject":    it.get("subject"),
            "status":     it.get("status"),
            "assignee":   assignee_name,
            "due_date":   it.get("due_date"),
        })
    return {"status": "ok", "items": items}


def get_rfi(rfi_id: Any = None,
             project_id: Optional[int] = None) -> dict:
    """Fetch the full body of one RFI."""
    if rfi_id is None or str(rfi_id).strip() == "":
        return {"status": "error", "error": "rfi_id is required"}
    try:
        rid = int(rfi_id)
    except Exception:
        return {"status": "error",
                "error": f"rfi_id must be an integer, got {rfi_id!r}"}
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id()
    pid = _load_project_id(project_id)
    if not pid:
        return _missing_project_error()
    r = _request("GET", f"rfis/{rid}",
                  token=token, company_id=cid,
                  query={"project_id": pid})
    if not r.get("_ok"):
        return r
    return {"status": "ok", "rfi": r.get("data") or {}}


def create_rfi(subject: str = "",
                question: str = "",
                project_id: Optional[int] = None,
                assignee_id: Optional[int] = None,
                due_date: Optional[str] = None) -> dict:
    """Create a new RFI on the active project. ESCAPE HATCH — writes
    to a live construction database. The ai_behaviour default is "ask"
    so the user confirms before submission."""
    if not subject or not str(subject).strip():
        return {"status": "error", "error": "subject is required"}
    if not question or not str(question).strip():
        return {"status": "error", "error": "question is required"}
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id()
    pid = _load_project_id(project_id)
    if not pid:
        return _missing_project_error()
    rfi: dict = {
        "subject": str(subject).strip(),
        "question": {"body": str(question)},
    }
    if assignee_id:
        try:
            rfi["assignee_ids"] = [int(assignee_id)]
        except Exception:
            pass
    if due_date:
        rfi["due_date"] = str(due_date)
    r = _request("POST", "rfis",
                  token=token, company_id=cid,
                  query={"project_id": pid},
                  body={"rfi": rfi})
    if not r.get("_ok"):
        return r
    data = r.get("data") or {}
    return {"status": "ok",
            "id": data.get("id"),
            "rfi": data}


# ---------------------------------------------------------------------------
def list_submittals(project_id: Optional[int] = None,
                     status: Optional[str] = None,
                     limit: int = 20) -> dict:
    """Return submittals on the active project."""
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id()
    pid = _load_project_id(project_id)
    if not pid:
        return _missing_project_error()
    q = {"project_id": pid, "per_page": int(limit or 20)}
    if status:
        q["filters[status]"] = str(status)
    r = _request("GET", "submittals",
                  token=token, company_id=cid, query=q)
    if not r.get("_ok"):
        return r
    items = []
    for it in (r.get("items") or [])[: int(limit or 20)]:
        bic = it.get("ball_in_court") or {}
        bic_name = ""
        if isinstance(bic, dict):
            bic_name = bic.get("name") or ""
        elif isinstance(bic, list) and bic:
            first = bic[0] if isinstance(bic[0], dict) else {}
            bic_name = first.get("name") or ""
        items.append({
            "id":             it.get("id"),
            "number":         it.get("number") or it.get("formatted_number"),
            "title":          it.get("title"),
            "status":         (it.get("status") or {}).get("name") if isinstance(it.get("status"), dict) else it.get("status"),
            "ball_in_court":  bic_name,
        })
    return {"status": "ok", "items": items}


# ---------------------------------------------------------------------------
def list_change_orders(project_id: Optional[int] = None,
                        status: Optional[str] = None,
                        limit: int = 20) -> dict:
    """Return change orders (CCOs / PCOs) on the active project."""
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id()
    pid = _load_project_id(project_id)
    if not pid:
        return _missing_project_error()
    q = {"project_id": pid, "per_page": int(limit or 20)}
    if status:
        q["filters[status]"] = str(status)
    # Procore exposes several change-order endpoints; the
    # "prime_contract_change_orders" surface is the most generally
    # available; fall back to a broader list if absent.
    r = _request("GET", "change_orders",
                  token=token, company_id=cid, query=q)
    if not r.get("_ok"):
        # Try the prime-contract variant — different envelope on
        # some Procore deployments.
        r2 = _request("GET", "prime_contract_change_orders",
                       token=token, company_id=cid, query=q)
        if r2.get("_ok"):
            r = r2
        else:
            return r
    items = []
    for it in (r.get("items") or [])[: int(limit or 20)]:
        items.append({
            "id":      it.get("id"),
            "number":  it.get("number") or it.get("formatted_number"),
            "title":   it.get("title") or it.get("subject"),
            "status":  it.get("status"),
            "amount":  it.get("amount"),
        })
    return {"status": "ok", "items": items}


# ---------------------------------------------------------------------------
def list_daily_logs(project_id: Optional[int] = None,
                     log_date: Optional[str] = None,
                     limit: int = 10) -> dict:
    """Return daily-log entries. `log_date` is YYYY-MM-DD; omit for
    most recent."""
    token = _load_token()
    if not token:
        return _missing_token_error()
    cid = _load_company_id()
    pid = _load_project_id(project_id)
    if not pid:
        return _missing_project_error()
    q = {"project_id": pid, "per_page": int(limit or 10)}
    if log_date:
        q["log_date"] = str(log_date)
    r = _request("GET", "daily_logs",
                  token=token, company_id=cid, query=q)
    if not r.get("_ok"):
        return r
    items = []
    for it in (r.get("items") or [])[: int(limit or 10)]:
        items.append({
            "id":         it.get("id"),
            "date":       it.get("log_date") or it.get("date"),
            "weather":    (it.get("weather") or {}).get("description")
                            if isinstance(it.get("weather"), dict) else None,
            "summary":    it.get("notes") or it.get("description"),
            "created_by": (it.get("created_by") or {}).get("name")
                            if isinstance(it.get("created_by"), dict) else None,
        })
    return {"status": "ok", "items": items}
