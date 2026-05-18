"""Outlook connector — classic Outlook over COM, wrapped in the uniform
connector contract (`connectors.base`).

This module does NOT re-implement any COM logic. Every operation is a
thin adapter over a working function in `connectors.outlook_runner`
(which already inits/uninits the COM apartment per call via its
`com_thread()` context manager). The connector's only jobs are:

  * declare the operation set the canvas / workflow registry sees
  * map each op to a runner function and a `ParamSpec` list
  * normalise the runner's heterogeneous return shapes into `OpResult`
  * give an honest `probe()` — "can we COM-dispatch + reach Outlook"

Mechanism = "com": there is no localhost listener. The runner runs in
ArchHub's own process and COM-dispatches to the user's Outlook.

Safety: `create_draft` and `mark_read` are flagged `destructive`.
`create_draft` only ever *creates / opens* a draft — it never sends.
The runner's `draft_reply()` has its own send opt-in gate; we never
pass `send=True` from here.
"""
from __future__ import annotations

from typing import Any

try:  # package-relative first (app/ on sys.path)
    from connectors.base import (
        Connector, ConnectorOp, ParamSpec, OpResult, register,
    )
    from connectors import outlook_runner as _runner
except Exception:  # pragma: no cover - fallback when imported flat
    from base import (  # type: ignore
        Connector, ConnectorOp, ParamSpec, OpResult, register,
    )
    import outlook_runner as _runner  # type: ignore


_BRAND = "#0078D4"  # Outlook blue — see HOST_NODE_UI_GRAMMAR §2.1


# ── op implementations ───────────────────────────────────────────────
# Each returns either a bare value (base.ConnectorOp.run wraps it) or an
# OpResult. We return OpResult directly where we want a custom preview.

def _list_inbox(limit: int = 20, unread_only: bool = False) -> OpResult:
    rows = _runner.list_inbox(limit=int(limit or 20),
                              unread_only=bool(unread_only))
    rows = list(rows or [])
    unread = sum(1 for r in rows if r.get("unread"))
    return OpResult(
        ok=True, value=rows,
        value_preview=f"{len(rows)} email{'s' if len(rows) != 1 else ''}"
                      f" · {unread} unread",
    )


def _read_email(entry_id: str = "") -> OpResult:
    eid = (entry_id or "").strip()
    if not eid:
        return OpResult.fail("entry_id is required")
    # read_thread() returns the full body of the target message + thread.
    data = _runner.read_thread(eid)
    if not isinstance(data, dict):
        return OpResult.fail("Outlook returned an unexpected shape")
    target = data.get("target") or {}
    subject = target.get("subject") or "(no subject)"
    thread_n = len(data.get("thread") or [])
    return OpResult(
        ok=True, value=data,
        value_preview=f"{subject[:60]} · thread of {thread_n}",
    )


def _list_calendar(days: int = 14, limit: int = 50) -> OpResult:
    """Upcoming calendar appointments. The runner has no named calendar
    reader, so we drive its COM escape hatch (`execute_python`) — still
    no new COM internals, just a script run inside the runner's context.
    """
    n_days = int(days or 14)
    n_limit = int(limit or 50)
    code = (
        "import datetime\n"
        "cal = ns.GetDefaultFolder(9)  # olFolderCalendar\n"
        "items = cal.Items\n"
        "items.IncludeRecurrences = True\n"
        "items.Sort('[Start]')\n"
        "now = datetime.datetime.now()\n"
        f"end = now + datetime.timedelta(days={n_days})\n"
        "fmt = '%m/%d/%Y %H:%M %p'\n"
        "restr = items.Restrict(\n"
        "    \"[Start] >= '\" + now.strftime(fmt) + \"' AND \"\n"
        "    \"[Start] <= '\" + end.strftime(fmt) + \"'\")\n"
        "out = []\n"
        f"for ap in restr:\n"
        f"    if len(out) >= {n_limit}:\n"
        "        break\n"
        "    try:\n"
        "        out.append({\n"
        "            'subject': str(getattr(ap, 'Subject', '') or ''),\n"
        "            'start': str(getattr(ap, 'Start', '') or ''),\n"
        "            'end': str(getattr(ap, 'End', '') or ''),\n"
        "            'location': str(getattr(ap, 'Location', '') or ''),\n"
        "            'organizer': str(getattr(ap, 'Organizer', '') or ''),\n"
        "            'all_day': bool(getattr(ap, 'AllDayEvent', False)),\n"
        "            'entry_id': str(getattr(ap, 'EntryID', '') or ''),\n"
        "        })\n"
        "    except Exception:\n"
        "        continue\n"
        "result = out\n"
    )
    res = _runner.execute_python(code=code)
    return _from_execute(res, "appointment")


def _list_contacts(limit: int = 100) -> OpResult:
    n_limit = int(limit or 100)
    code = (
        "con = ns.GetDefaultFolder(10)  # olFolderContacts\n"
        "out = []\n"
        "for c in con.Items:\n"
        f"    if len(out) >= {n_limit}:\n"
        "        break\n"
        "    try:\n"
        "        if getattr(c, 'Class', 40) != 40:  # olContact\n"
        "            continue\n"
        "        out.append({\n"
        "            'name': str(getattr(c, 'FullName', '') or ''),\n"
        "            'email': str(getattr(c, 'Email1Address', '') or ''),\n"
        "            'company': str(getattr(c, 'CompanyName', '') or ''),\n"
        "            'job_title': str(getattr(c, 'JobTitle', '') or ''),\n"
        "            'mobile': str(getattr(c, 'MobileTelephoneNumber', '')"
        " or ''),\n"
        "            'entry_id': str(getattr(c, 'EntryID', '') or ''),\n"
        "        })\n"
        "    except Exception:\n"
        "        continue\n"
        "result = out\n"
    )
    res = _runner.execute_python(code=code)
    return _from_execute(res, "contact")


def _list_drafts(limit: int = 50) -> OpResult:
    n_limit = int(limit or 50)
    code = (
        "drafts = ns.GetDefaultFolder(16)  # olFolderDrafts\n"
        "out = []\n"
        "for m in drafts.Items:\n"
        f"    if len(out) >= {n_limit}:\n"
        "        break\n"
        "    try:\n"
        "        to = []\n"
        "        for r in (getattr(m, 'Recipients', None) or []):\n"
        "            a = getattr(r, 'Address', '') or ''\n"
        "            if a:\n"
        "                to.append(str(a))\n"
        "        out.append({\n"
        "            'entry_id': str(getattr(m, 'EntryID', '') or ''),\n"
        "            'subject': str(getattr(m, 'Subject', '') or ''),\n"
        "            'to': to,\n"
        "            'body_preview': str(getattr(m, 'Body', '') or '')"
        "[:200],\n"
        "        })\n"
        "    except Exception:\n"
        "        continue\n"
        "result = out\n"
    )
    res = _runner.execute_python(code=code)
    return _from_execute(res, "draft")


def _unread_count() -> OpResult:
    snap = _runner.info()
    if not isinstance(snap, dict) or snap.get("status") != "ok":
        err = (snap or {}).get("error", "Outlook not reachable")
        return OpResult.fail(err)
    n = int(snap.get("inbox_unread", 0) or 0)
    total = int(snap.get("inbox_total", 0) or 0)
    return OpResult(
        ok=True,
        value={"unread": n, "total": total,
               "drafts": int(snap.get("drafts_count", 0) or 0)},
        value_preview=f"{n} unread / {total} total",
    )


def _create_draft(to: str = "", subject: str = "", body: str = "",
                   reply_to_entry_id: str = "") -> OpResult:
    """Create (and display) a draft. NEVER sends.

    Two modes:
      * `reply_to_entry_id` set → reply draft on that message (uses the
        runner's `draft_reply`, send hard-disabled).
      * otherwise → a fresh draft addressed to `to` with `subject`/`body`
        (uses the runner's COM escape hatch — no send).
    """
    reply_id = (reply_to_entry_id or "").strip()
    if reply_id:
        res = _runner.draft_reply(reply_id, body or "",
                                  reply_all=False, send=False)
        if not isinstance(res, dict):
            return OpResult.fail("Outlook returned an unexpected shape")
        if res.get("status") == "error":
            return OpResult.fail(res.get("error", "draft failed"))
        return OpResult(
            ok=True, value=res,
            value_preview=f"reply draft open · {res.get('entry_id', '')[:24]}",
        )

    to_addr = (to or "").strip()
    if not to_addr:
        return OpResult.fail(
            "to is required for a new draft (or pass reply_to_entry_id)")
    # Build a fresh MailItem; .Save() + .Display() — never .Send().
    code = (
        "m = outlook.CreateItem(0)  # olMailItem\n"
        f"m.To = {to_addr!r}\n"
        f"m.Subject = {str(subject or '')!r}\n"
        f"m.Body = {str(body or '')!r}\n"
        "m.Save()\n"
        "try:\n"
        "    m.Display()\n"
        "except Exception:\n"
        "    pass\n"
        "result = {'status': 'draft_open',\n"
        "          'entry_id': str(getattr(m, 'EntryID', '') or '')}\n"
    )
    res = _runner.execute_python(code=code)
    if not isinstance(res, dict) or res.get("status") != "ok":
        return OpResult.fail((res or {}).get("error", "draft failed"))
    payload = res.get("result") or {}
    eid = payload.get("entry_id", "") if isinstance(payload, dict) else ""
    return OpResult(ok=True, value=payload,
                    value_preview=f"draft open · {eid[:24]}")


def _mark_read(entry_id: str = "", read: bool = True) -> OpResult:
    eid = (entry_id or "").strip()
    if not eid:
        return OpResult.fail("entry_id is required")
    res = _runner.mark_read(eid, read=bool(read))
    if not isinstance(res, dict) or res.get("status") != "ok":
        return OpResult.fail((res or {}).get("error", "mark_read failed"))
    state = "unread" if res.get("unread") else "read"
    return OpResult(ok=True, value=res,
                    value_preview=f"marked {state}")


def _from_execute(res: Any, noun: str) -> OpResult:
    """Normalise a runner.execute_python() envelope whose `result` is a
    list of dicts into an OpResult with a count preview."""
    if not isinstance(res, dict):
        return OpResult.fail("Outlook returned an unexpected shape")
    if res.get("status") != "ok":
        return OpResult.fail(res.get("error", "Outlook script failed"))
    rows = res.get("result")
    if not isinstance(rows, list):
        rows = []
    return OpResult(
        ok=True, value=rows,
        value_preview=f"{len(rows)} {noun}{'s' if len(rows) != 1 else ''}",
    )


# ── connector ────────────────────────────────────────────────────────
class OutlookConnector(Connector):
    """Classic Outlook, driven over COM via `outlook_runner`."""

    host = "outlook"
    display_name = "Outlook"
    mechanism = "com"

    def probe(self) -> dict:
        """Honest reachability. `is_reachable()` opens the default MAPI
        inbox through COM — True only if Outlook is dispatchable and the
        profile loads. We never *force-launch* Outlook here; if pywin32
        or COM is missing, `is_reachable()` swallows it and returns
        False, which we report as `missing`.
        """
        try:
            reachable = bool(_runner.is_reachable())
        except Exception as ex:  # defence in depth — runner is best-effort
            return {"status": "missing",
                    "note": f"Outlook COM probe failed: {ex}",
                    "detail": {}}
        if not reachable:
            return {"status": "missing",
                    "note": "Outlook (classic) not reachable — open "
                            "Outlook, or pywin32 is missing.",
                    "detail": {}}
        detail: dict = {}
        try:
            snap = _runner.info()
            if isinstance(snap, dict) and snap.get("status") == "ok":
                detail = {
                    "inbox_total": snap.get("inbox_total"),
                    "inbox_unread": snap.get("inbox_unread"),
                    "drafts_count": snap.get("drafts_count"),
                    "account": snap.get("default_account_email"),
                }
        except Exception:
            pass
        note = "Outlook reachable over COM"
        if detail.get("inbox_unread") is not None:
            note = (f"Outlook reachable · {detail['inbox_unread']} unread "
                    f"/ {detail.get('inbox_total', '?')} inbox")
        return {"status": "live", "note": note, "detail": detail}

    def build_ops(self) -> list:
        return [
            # ── READ ────────────────────────────────────────────────
            ConnectorOp(
                op_id="outlook.list_inbox", host="outlook", kind="read",
                label="List inbox",
                description="Most recent inbox messages, newest first.",
                inputs=[
                    ParamSpec("limit", "Limit", "number", default=20,
                              help="Max messages to return (10-500)."),
                    ParamSpec("unread_only", "Unread only", "bool",
                              default=False,
                              help="Restrict to unread messages."),
                ],
                output_type="email",
                fn=_list_inbox,
            ),
            ConnectorOp(
                op_id="outlook.read_email", host="outlook", kind="read",
                label="Read email",
                description="Full body + conversation thread for one "
                            "message, by EntryID.",
                inputs=[
                    ParamSpec("entry_id", "Entry ID", "text",
                              required=True,
                              help="Outlook EntryID of the message."),
                ],
                output_type="email",
                fn=_read_email,
            ),
            ConnectorOp(
                op_id="outlook.list_calendar", host="outlook",
                kind="read", label="List calendar",
                description="Upcoming calendar appointments in a window "
                            "of N days.",
                inputs=[
                    ParamSpec("days", "Days ahead", "number", default=14,
                              help="How many days forward to scan."),
                    ParamSpec("limit", "Limit", "number", default=50,
                              help="Max appointments to return."),
                ],
                output_type="calendar_event",
                fn=_list_calendar,
            ),
            ConnectorOp(
                op_id="outlook.list_contacts", host="outlook",
                kind="read", label="List contacts",
                description="Contacts from the default Contacts folder.",
                inputs=[
                    ParamSpec("limit", "Limit", "number", default=100,
                              help="Max contacts to return."),
                ],
                output_type="list",
                fn=_list_contacts,
            ),
            ConnectorOp(
                op_id="outlook.list_drafts", host="outlook",
                kind="read", label="List drafts",
                description="Messages currently in the Drafts folder.",
                inputs=[
                    ParamSpec("limit", "Limit", "number", default=50,
                              help="Max drafts to return."),
                ],
                output_type="email",
                fn=_list_drafts,
            ),
            ConnectorOp(
                op_id="outlook.unread_count", host="outlook",
                kind="read", label="Unread count",
                description="Inbox unread / total / drafts counts.",
                inputs=[],
                output_type="number",
                fn=_unread_count,
            ),
            # ── ACTION ──────────────────────────────────────────────
            ConnectorOp(
                op_id="outlook.create_draft", host="outlook",
                kind="action", label="Create draft",
                description="Create (and open) a draft message. Never "
                            "sends — the user clicks Send in Outlook. "
                            "Pass reply_to_entry_id for a reply draft.",
                inputs=[
                    ParamSpec("to", "To", "text",
                              help="Recipient address (new draft)."),
                    ParamSpec("subject", "Subject", "text",
                              help="Subject line (new draft)."),
                    ParamSpec("body", "Body", "text",
                              help="Body text."),
                    ParamSpec("reply_to_entry_id", "Reply to (Entry ID)",
                              "text",
                              help="If set, draft a reply to this "
                                   "message instead of a new mail."),
                ],
                output_type="email",
                destructive=True,
                fn=_create_draft,
            ),
            ConnectorOp(
                op_id="outlook.mark_read", host="outlook",
                kind="action", label="Mark read / unread",
                description="Toggle the read flag on a message.",
                inputs=[
                    ParamSpec("entry_id", "Entry ID", "text",
                              required=True,
                              help="Outlook EntryID of the message."),
                    ParamSpec("read", "Mark as read", "bool",
                              default=True,
                              help="True = read, False = unread."),
                ],
                output_type="email",
                destructive=True,
                fn=_mark_read,
            ),
        ]


# ── self-register ────────────────────────────────────────────────────
register(OutlookConnector())
