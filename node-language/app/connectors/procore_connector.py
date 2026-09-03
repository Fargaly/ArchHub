"""Procore connector — the uniform `connectors.base.Connector` wrapper
around the real REST runner in `connectors.procore_runner`.

Why this file exists
--------------------
`procore_runner.py` (543 lines, stdlib HTTP against api.procore.com) was
built for the AEC workflows architects live in — RFIs, submittals, change
orders, daily logs — but it shipped WITHOUT a connector. Nothing in
`load_all_connectors()` imported it, so the runner was unreachable from
the canvas, the bridge, host_detector or the agent's tool surface. The
runner was real; the door to it was missing.

This connector is that door. It does NOT re-implement Procore — every op
delegates to a real `procore_runner` function. It only adapts the
runner's `{"status": "ok"/"error", ...}` envelope to the uniform
`OpResult` the rest of ArchHub speaks, and adds the honest `probe()` the
contract requires.

Mechanism: REST (mirrors `notion_connector` / `dropbox_connector`).

Auth model (see procore_runner docstring for the full story)
  Personal Access Token pasted in Settings -> Sign-ins -> Procore, read
  via `secrets_store.load_api_key('procore_access_token')`. Active
  company / project ids come from settings and may be overridden per call.

Operations
----------
  READ    procore.list_projects     — projects in a company
          procore.list_users        — users on the active project
          procore.list_rfis         — RFIs on the active project
          procore.get_rfi           — one RFI's full body
          procore.list_submittals   — submittals on the active project
          procore.list_change_orders— change orders (CCO/PCO)
          procore.list_daily_logs   — daily-log entries
  ACTION  procore.create_rfi        — file a new RFI (destructive)

Every operation returns an `OpResult`; nothing raises to the caller.
"""
from __future__ import annotations

from typing import Any, Optional

from connectors.base import (
    Connector,
    ConnectorOp,
    OpResult,
    ParamSpec,
    register,
)
from connectors import procore_runner


# ---------------------------------------------------------------------------
SECRET_KEY = "procore_access_token"


def _load_token() -> Optional[str]:
    """Pull the saved Procore bearer token, or None if missing.

    Delegates to the runner so there is ONE token source. Tests that need
    a no-token / token path patch `procore_runner._load_token` (the real
    gate every op call funnels through).
    """
    try:
        return procore_runner._load_token()
    except Exception:
        return None


def _token_hint() -> str:
    return ("Procore token not set. Open Settings -> Sign-ins -> Procore "
            "and paste a Personal Access Token from "
            "developers.procore.com.")


# ---------------------------------------------------------------------------
def _normalize(result: Any, *, value_key: Optional[str] = None,
               op_id: str = "") -> OpResult:
    """Adapt a runner return dict to an `OpResult`.

    The runner speaks `{"status": "ok", "items": [...]}` for lists,
    `{"status": "ok", "<entity>": {...}, "id": N}` for get/create, and
    `{"status": "error", "error": "...", "http_status": int?}` on
    failure. This funnels every shape into the uniform result.

    `value_key` names the payload key for non-list endpoints
    (e.g. "rfi"); when omitted, "items" is used if present, else the
    whole dict (minus the status flag) becomes the value.
    """
    if not isinstance(result, dict):
        # A bare value from the runner — wrap it as a success payload.
        return OpResult(ok=True, value=result, op_id=op_id)
    if result.get("status") == "error":
        return OpResult.fail(result.get("error") or "Procore error", op_id)
    # success
    if value_key is not None and value_key in result:
        val = result.get(value_key)
        return OpResult(ok=True, value=val, op_id=op_id,
                        value_preview=_preview(val))
    if "items" in result:
        items = result.get("items") or []
        n = len(items) if isinstance(items, list) else 0
        return OpResult(ok=True, value=items, op_id=op_id,
                        value_preview=f"{n} item{'s' if n != 1 else ''}")
    # Fallback — return the payload without the status flag.
    payload = {k: v for k, v in result.items() if k != "status"}
    return OpResult(ok=True, value=payload, op_id=op_id,
                    value_preview=_preview(payload))


def _preview(value: Any, limit: int = 80) -> str:
    try:
        if value is None:
            return "-"
        if isinstance(value, (list, tuple)):
            n = len(value)
            return f"{n} item{'s' if n != 1 else ''}"
        if isinstance(value, dict):
            # Prefer a human field if present.
            for k in ("subject", "title", "name", "number"):
                if value.get(k):
                    return str(value[k])[:limit]
            n = len(value)
            return f"{n} field{'s' if n != 1 else ''}"
        s = str(value)
        return s if len(s) <= limit else s[:limit] + "…"
    except Exception:
        return "?"


def _to_int(v: Any) -> Optional[int]:
    """Coerce a param to int (Procore ids), or None when blank/bad."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Operation implementations — thin adapters over the real runner.
# Each guards the no-token case explicitly so a missing token returns an
# honest, actionable failure WITHOUT a network round-trip.
# ---------------------------------------------------------------------------
def _op_list_projects(company_id: Any = None, limit: int = 50,
                      **_: Any) -> OpResult:
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.list_projects(company_id=_to_int(company_id),
                                     limit=int(limit or 50))
    return _normalize(r, op_id="procore.list_projects")


def _op_list_users(project_id: Any = None, limit: int = 50,
                   **_: Any) -> OpResult:
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.list_users(project_id=_to_int(project_id),
                                  limit=int(limit or 50))
    return _normalize(r, op_id="procore.list_users")


def _op_list_rfis(project_id: Any = None, status: str = "",
                  limit: int = 20, **_: Any) -> OpResult:
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.list_rfis(project_id=_to_int(project_id),
                                 status=(status or None),
                                 limit=int(limit or 20))
    return _normalize(r, op_id="procore.list_rfis")


def _op_get_rfi(rfi_id: Any = None, project_id: Any = None,
                **_: Any) -> OpResult:
    if rfi_id is None or str(rfi_id).strip() == "":
        return OpResult.fail("rfi_id is required.")
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.get_rfi(rfi_id=rfi_id,
                               project_id=_to_int(project_id))
    return _normalize(r, value_key="rfi", op_id="procore.get_rfi")


def _op_list_submittals(project_id: Any = None, status: str = "",
                        limit: int = 20, **_: Any) -> OpResult:
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.list_submittals(project_id=_to_int(project_id),
                                       status=(status or None),
                                       limit=int(limit or 20))
    return _normalize(r, op_id="procore.list_submittals")


def _op_list_change_orders(project_id: Any = None, status: str = "",
                           limit: int = 20, **_: Any) -> OpResult:
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.list_change_orders(project_id=_to_int(project_id),
                                          status=(status or None),
                                          limit=int(limit or 20))
    return _normalize(r, op_id="procore.list_change_orders")


def _op_list_daily_logs(project_id: Any = None, log_date: str = "",
                        limit: int = 10, **_: Any) -> OpResult:
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.list_daily_logs(project_id=_to_int(project_id),
                                       log_date=(log_date or None),
                                       limit=int(limit or 10))
    return _normalize(r, op_id="procore.list_daily_logs")


def _op_create_rfi(subject: str = "", question: str = "",
                   project_id: Any = None, assignee_id: Any = None,
                   due_date: str = "", **_: Any) -> OpResult:
    """DESTRUCTIVE — files a real RFI against a live construction project.
    The ai_behaviour default policy for writes is 'ask', so the user
    confirms before this fires from the agent."""
    if not subject or not str(subject).strip():
        return OpResult.fail("subject is required.")
    if not question or not str(question).strip():
        return OpResult.fail("question is required.")
    if not _load_token():
        return OpResult.fail(_token_hint())
    r = procore_runner.create_rfi(subject=subject, question=question,
                                  project_id=_to_int(project_id),
                                  assignee_id=_to_int(assignee_id),
                                  due_date=(due_date or None))
    return _normalize(r, value_key="rfi", op_id="procore.create_rfi")


# ---------------------------------------------------------------------------
class ProcoreConnector(Connector):
    """Procore REST API connector — wraps `procore_runner`."""

    host = "procore"
    display_name = "Procore"
    mechanism = "rest"

    # -- status -------------------------------------------------------
    def probe(self) -> dict:
        """Honest status:
          no token                 -> unauthorized
          token + /me responds     -> live
          token but 401/403        -> unauthorized
          token + network/5xx/etc  -> missing

        Never raises; never hits the network when no token is set.
        """
        token = _load_token()
        if not token:
            return {"status": "unauthorized", "note": _token_hint(),
                    "detail": {}}
        # Cheap real auth check — GET /me through the runner.
        try:
            cid = procore_runner._load_company_id()
            me = procore_runner._request("GET", "me", token=token,
                                         company_id=cid, timeout=12)
        except Exception as ex:  # pragma: no cover — defensive
            return {"status": "missing",
                    "note": f"Procore probe failed: {ex}", "detail": {}}
        if me.get("_ok"):
            user = me.get("data") or {}
            name = (user.get("name") or user.get("login")
                    or user.get("email") or "user")
            return {
                "status": "live",
                "note": f"Connected as '{name}'.",
                "detail": {"user_id": user.get("id"), "name": name,
                           "company_id": cid},
            }
        # Error envelope from the runner — classify by http_status.
        code = me.get("http_status")
        note = me.get("error") or "Procore unreachable."
        if code in (401, 403):
            return {"status": "unauthorized", "note": note, "detail": {}}
        return {"status": "missing", "note": note, "detail": {}}

    # -- operations ---------------------------------------------------
    def build_ops(self) -> list:
        proj_param = ParamSpec(
            id="project_id", label="Project ID", type="text", default="",
            help="Procore project id. Blank uses the saved active "
                 "project from Settings.")
        limit20 = ParamSpec(id="limit", label="Limit", type="number",
                            default=20, help="Max rows to return.")
        status_param = ParamSpec(
            id="status", label="Status filter", type="text", default="",
            help="Optional Procore status to filter by (e.g. 'open').")
        return [
            ConnectorOp(
                op_id="procore.list_projects",
                host="procore", kind="read",
                label="List projects",
                description="List Procore projects in a company.",
                inputs=[
                    ParamSpec(id="company_id", label="Company ID",
                              type="text", default="",
                              help="Procore company id. Blank uses the "
                                   "saved company from Settings."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=50, help="Max projects to return."),
                ],
                output_type="list",
                fn=_op_list_projects,
            ),
            ConnectorOp(
                op_id="procore.list_users",
                host="procore", kind="read",
                label="List users",
                description="List users on the active Procore project "
                            "(for assignee lookups).",
                inputs=[
                    proj_param,
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=50, help="Max users to return."),
                ],
                output_type="list",
                fn=_op_list_users,
            ),
            ConnectorOp(
                op_id="procore.list_rfis",
                host="procore", kind="read",
                label="List RFIs",
                description="List RFIs on the active Procore project, "
                            "newest first.",
                inputs=[proj_param, status_param, limit20],
                output_type="list",
                fn=_op_list_rfis,
            ),
            ConnectorOp(
                op_id="procore.get_rfi",
                host="procore", kind="read",
                label="Get RFI",
                description="Fetch the full body of one Procore RFI.",
                inputs=[
                    ParamSpec(id="rfi_id", label="RFI ID", type="text",
                              required=True, help="The RFI id."),
                    proj_param,
                ],
                output_type="dict",
                fn=_op_get_rfi,
            ),
            ConnectorOp(
                op_id="procore.list_submittals",
                host="procore", kind="read",
                label="List submittals",
                description="List submittals on the active Procore "
                            "project.",
                inputs=[proj_param, status_param, limit20],
                output_type="list",
                fn=_op_list_submittals,
            ),
            ConnectorOp(
                op_id="procore.list_change_orders",
                host="procore", kind="read",
                label="List change orders",
                description="List change orders (CCOs / PCOs) on the "
                            "active Procore project.",
                inputs=[proj_param, status_param, limit20],
                output_type="list",
                fn=_op_list_change_orders,
            ),
            ConnectorOp(
                op_id="procore.list_daily_logs",
                host="procore", kind="read",
                label="List daily logs",
                description="List daily-log entries on the active Procore "
                            "project.",
                inputs=[
                    proj_param,
                    ParamSpec(id="log_date", label="Log date",
                              type="text", default="",
                              help="A specific day as YYYY-MM-DD. Blank "
                                   "returns the most recent."),
                    ParamSpec(id="limit", label="Limit", type="number",
                              default=10, help="Max log entries."),
                ],
                output_type="list",
                fn=_op_list_daily_logs,
            ),
            ConnectorOp(
                op_id="procore.create_rfi",
                host="procore", kind="action",
                label="Create RFI",
                description="File a new RFI on the active Procore project. "
                            "Writes to a live construction database.",
                inputs=[
                    ParamSpec(id="subject", label="Subject", type="text",
                              required=True, help="The RFI subject line."),
                    ParamSpec(id="question", label="Question", type="text",
                              required=True,
                              help="The RFI question body."),
                    proj_param,
                    ParamSpec(id="assignee_id", label="Assignee ID",
                              type="text", default="",
                              help="Optional Procore user id to assign."),
                    ParamSpec(id="due_date", label="Due date", type="text",
                              default="",
                              help="Optional due date as YYYY-MM-DD."),
                ],
                output_type="dict",
                destructive=True,
                fn=_op_create_rfi,
            ),
        ]


# ── register at import time ─────────────────────────────────────────
register(ProcoreConnector())
