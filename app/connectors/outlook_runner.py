"""Outlook connector — drives classic Outlook via COM (pywin32).

Architecture differs from the other connectors: there's no localhost
HTTP listener (no DLL is loaded into Outlook). The runner runs IN
ArchHub's own Python process, COM-dispatching to the user's
already-running Outlook. So `is_active` = "we can dispatch + Outlook
is reachable", not "a listener responded".

Read-only slice first. Send tools come later behind an explicit
'allow send' setting — never auto-send without user clicking
Send in the Outlook draft window.

Limitations:
  * Classic Outlook only. New Outlook (UWP) doesn't expose COM.
  * Outlook must be open (or at least its profile loadable). If
    closed, COM Dispatch will START Outlook for the user — fine
    for our use-case but we surface that in the smoke probe.
  * Multi-account: uses the DEFAULT MAPI namespace inbox. Future
    work: account picker.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


_OL_FOLDER_INBOX = 6
_OL_FOLDER_DRAFTS = 16
_OL_FOLDER_SENT = 5
_OL_BODY_HTML = 2
_OL_REPLY = 0


def _client():
    """Lazy-import + dispatch. Raises a clean RuntimeError if pywin32
    isn't available so callers can surface a single message.

    CRITICAL: every caller thread MUST have called
    pythoncom.CoInitialize() before this. The com_thread() context
    manager below handles that — always use it from worker threads.
    """
    try:
        import win32com.client as w
    except ImportError as ex:
        raise RuntimeError(
            "pywin32 not installed. Run: pip install pywin32"
        ) from ex
    try:
        return w.Dispatch("Outlook.Application")
    except Exception as ex:
        raise RuntimeError(
            f"Could not connect to Outlook (classic). Open Outlook and try again. ({ex})"
        ) from ex


import contextlib

@contextlib.contextmanager
def com_thread():
    """Context manager that inits + uninits COM apartment for the
    current thread. Wrapping every public-API call in this prevents
    Qt6Core 0xc0000409 fast-fails when these run on background
    threads pumped by Qt."""
    inited = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        inited = True
    except Exception:
        pass
    try:
        yield
    finally:
        if inited:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _ns():
    return _client().GetNamespace("MAPI")


def _safe(s: Any, n: int = 0) -> str:
    s = "" if s is None else str(s)
    return s if not n else s[:n]


def _serialize_item(m, *, include_body: bool = False) -> dict:
    """Convert an Outlook MailItem to a JSON-safe dict."""
    received = getattr(m, "ReceivedTime", None)
    received_iso = ""
    try:
        if received is not None:
            received_iso = received.isoformat()
    except Exception:
        received_iso = str(received) if received else ""
    out = {
        "entry_id": _safe(getattr(m, "EntryID", "")),
        "subject":  _safe(m.Subject, 240),
        "sender":   _safe(getattr(m, "SenderName", ""), 120),
        "sender_email": _safe(getattr(m, "SenderEmailAddress", ""), 200),
        "received": received_iso,
        "unread":   bool(getattr(m, "UnRead", False)),
        "size":     int(getattr(m, "Size", 0) or 0),
        "has_attachments": bool(getattr(m, "Attachments", None)
                                and m.Attachments.Count > 0),
        "attachment_count": int(getattr(m, "Attachments", None)
                                and m.Attachments.Count or 0),
    }
    if include_body:
        out["body_text"] = _safe(getattr(m, "Body", ""))[:20_000]
        out["body_html"] = _safe(getattr(m, "HTMLBody", ""))[:50_000]
    return out


# ---------------------------------------------------------------------------
def is_reachable() -> bool:
    """Cheap True/False — used by Reality Check + status bar."""
    with com_thread():
        try:
            ns = _ns()
            inbox = ns.GetDefaultFolder(_OL_FOLDER_INBOX)
            _ = inbox.Items.Count
            return True
        except Exception:
            return False


def info() -> dict:
    """Lightweight snapshot for Reality Check."""
    with com_thread():
        return _info_inner()


def _info_inner() -> dict:
    try:
        ns = _ns()
        inbox = ns.GetDefaultFolder(_OL_FOLDER_INBOX)
        drafts = ns.GetDefaultFolder(_OL_FOLDER_DRAFTS)
        return {
            "status": "ok",
            "inbox_total":   int(inbox.Items.Count),
            "inbox_unread":  int(inbox.UnReadItemCount),
            "drafts_count":  int(drafts.Items.Count),
            "default_account_email": _safe(
                getattr(getattr(ns, "Accounts", None) and ns.Accounts.Item(1), "SmtpAddress", "") if ns.Accounts.Count else ""),
        }
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:200]}


def list_inbox(*, limit: int = 20, unread_only: bool = False) -> list[dict]:
    """Return the most recent N inbox items, newest first."""
    with com_thread():
        return _list_inbox_inner(limit=limit, unread_only=unread_only)


def _list_inbox_inner(*, limit: int, unread_only: bool) -> list[dict]:
    ns = _ns()
    items = ns.GetDefaultFolder(_OL_FOLDER_INBOX).Items
    items.Sort("[ReceivedTime]", True)         # descending
    if unread_only:
        items = items.Restrict("[UnRead] = True")
    out: list[dict] = []
    for i in range(min(int(limit), items.Count)):
        try:
            out.append(_serialize_item(items.Item(i + 1)))
        except Exception:
            continue
    return out


def search(query: str = "", *, sender: str = "",
           subject_contains: str = "", days: int = 0,
           limit: int = 30) -> list[dict]:
    """Search inbox using DASL filter syntax. All args optional; empty
    args mean 'no filter on that field'.

    `query` is matched against subject + body. `sender` against From
    name OR email. `days` restricts to last N days (0 = no limit).
    """
    with com_thread():
        return _search_inner(query=query, sender=sender,
                              subject_contains=subject_contains,
                              days=days, limit=limit)


def _search_inner(*, query: str, sender: str, subject_contains: str,
                  days: int, limit: int) -> list[dict]:
    ns = _ns()
    items = ns.GetDefaultFolder(_OL_FOLDER_INBOX).Items
    items.Sort("[ReceivedTime]", True)

    parts: list[str] = []
    if query:
        # Search both subject and body (DASL ci_phrasematch).
        q = query.replace("'", "''")
        parts.append(
            f"(\"urn:schemas:httpmail:subject\" ci_phrasematch '{q}' "
            f"OR \"urn:schemas:httpmail:textdescription\" ci_phrasematch '{q}')"
        )
    if subject_contains:
        s = subject_contains.replace("'", "''")
        parts.append(f"\"urn:schemas:httpmail:subject\" ci_phrasematch '{s}'")
    if sender:
        s = sender.replace("'", "''")
        parts.append(
            f"(\"urn:schemas:httpmail:fromname\" ci_phrasematch '{s}' "
            f"OR \"urn:schemas:httpmail:fromemail\" ci_phrasematch '{s}')"
        )
    if days and days > 0:
        # ReceivedTime > today minus N days. DASL date format is
        # 'yyyy-mm-dd hh:mm'.
        from datetime import datetime as _dt, timedelta as _td
        cutoff = (_dt.now() - _td(days=int(days))).strftime("%m/%d/%Y %H:%M %p")
        parts.append(f"\"urn:schemas:httpmail:datereceived\" >= '{cutoff}'")
    if parts:
        items = items.Restrict("@SQL=" + " AND ".join(parts))

    out: list[dict] = []
    for i in range(min(int(limit), items.Count)):
        try:
            out.append(_serialize_item(items.Item(i + 1)))
        except Exception:
            continue
    return out


def read_thread(entry_id: str) -> dict:
    """Return the full thread containing the message identified by
    entry_id. Includes body + ConversationIndex chain when available."""
    with com_thread():
        return _read_thread_inner(entry_id)


def _read_thread_inner(entry_id: str) -> dict:
    ns = _ns()
    target = ns.GetItemFromID(entry_id)
    target_dict = _serialize_item(target, include_body=True)
    out = {"target": target_dict, "thread": []}
    convo = getattr(target, "GetConversation", None)
    if convo is None:
        return out
    try:
        c = target.GetConversation()
        if c is None:
            return out
        # Conversation.GetRootItems returns a SimpleItems collection.
        roots = c.GetRootItems()
        for i in range(min(20, roots.Count)):
            root = roots.Item(i + 1)
            out["thread"].append(_serialize_item(root))
            children = c.GetChildren(root)
            for j in range(min(40, children.Count)):
                out["thread"].append(_serialize_item(children.Item(j + 1)))
    except Exception:
        pass
    return out


def draft_reply(entry_id: str, body: str = "", *,
                reply_all: bool = False, send: bool = False) -> dict:
    """Create a reply draft (NEVER sent unless `send=True` and the
    user has opted in to send-from-ArchHub via Settings).

    Default behaviour: opens the draft in Outlook so the user can
    review + click Send themselves. Returns the draft's EntryID."""
    with com_thread():
        return _draft_reply_inner(entry_id, body, reply_all=reply_all, send=send)


def _draft_reply_inner(entry_id: str, body: str, *,
                        reply_all: bool, send: bool) -> dict:
    ns = _ns()
    target = ns.GetItemFromID(entry_id)
    if reply_all:
        draft = target.ReplyAll()
    else:
        draft = target.Reply()
    if body:
        # Prepend our generated reply above the quoted history.
        existing = getattr(draft, "Body", "") or ""
        draft.Body = body + "\n\n" + existing
    draft.Save()
    if send:
        # Hard-blocked unless the user has flipped the opt-in. The
        # tool_engine layer enforces this; we still leave the gate
        # here as a defence in depth.
        try:
            from secrets_store import load_setting
            if not bool(load_setting("outlook_allow_send")):
                send = False
        except Exception:
            send = False
    if send:
        draft.Send()
        return {"status": "sent",
                "entry_id": _safe(getattr(draft, "EntryID", ""))}
    # Show the draft window so the user can review.
    try:
        draft.Display()
    except Exception:
        pass
    return {"status": "draft_open",
            "entry_id": _safe(getattr(draft, "EntryID", ""))}


def save_attachments(entry_id: str, *, dest_dir: str) -> dict:
    """Extract every attachment from the message into dest_dir.
    Returns the list of saved paths."""
    with com_thread():
        return _save_attachments_inner(entry_id, dest_dir=dest_dir)


def _save_attachments_inner(entry_id: str, *, dest_dir: str) -> dict:
    import os
    ns = _ns()
    m = ns.GetItemFromID(entry_id)
    os.makedirs(dest_dir, exist_ok=True)
    saved: list[str] = []
    atts = getattr(m, "Attachments", None)
    if atts is None or atts.Count == 0:
        return {"status": "ok", "saved": []}
    for i in range(atts.Count):
        a = atts.Item(i + 1)
        # Sanitize filename — Outlook can produce nested/odd paths.
        fname = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_",
                       _safe(a.FileName, 200)) or f"attachment-{i+1}"
        path = os.path.join(dest_dir, fname)
        try:
            a.SaveAsFile(path)
            saved.append(path)
        except Exception:
            continue
    return {"status": "ok", "saved": saved}
