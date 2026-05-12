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


def set_categories(entry_id: str, categories: list[str], *,
                    mode: str = "set") -> dict:
    """Mutate the Outlook MAPI Categories property on a single message.

    `mode`: "set" replaces · "add" appends new categories · "remove"
    drops listed categories. Categories show up in Outlook's UI as
    coloured tags + are filterable / groupable. The classic UI lets
    the user create new categories on the fly; a raw category name we
    hand in here that doesn't yet exist on the master list will still
    save on the message and auto-register on next view.
    """
    with com_thread():
        return _set_categories_inner(entry_id, categories, mode=mode)


def _set_categories_inner(entry_id: str, categories: list[str], *,
                           mode: str) -> dict:
    ns = _ns()
    m = ns.GetItemFromID(entry_id)
    existing = [c.strip() for c in (getattr(m, "Categories", "") or "").split(",")
                if c.strip()]
    incoming = [str(c).strip() for c in (categories or []) if str(c).strip()]
    if mode == "set":
        new = incoming
    elif mode == "add":
        new = list(dict.fromkeys(existing + incoming))
    elif mode == "remove":
        drop = set(c.lower() for c in incoming)
        new = [c for c in existing if c.lower() not in drop]
    else:
        return {"status": "error", "error": f"Unknown mode: {mode}"}
    m.Categories = ",".join(new)
    m.Save()
    return {"status": "ok", "entry_id": entry_id,
            "categories": new}


def set_categories_by_filter(*, categories: list[str],
                               sender_contains: str = "",
                               subject_contains: str = "",
                               body_contains: str = "",
                               days: int = 0,
                               unread_only: bool = False,
                               limit: int = 500,
                               mode: str = "set") -> dict:
    """Bulk-apply Outlook categories to EVERY message matching a
    filter — without the LLM having to loop. Solves the local-model
    failure mode where the model calls set_categories with a
    placeholder entry_id because it didn't realise it should
    list+iterate first.

    All filter fields are optional + combine with AND. Empty filter +
    no limit override = applies to the whole inbox (use with care).

    Returns a summary: count touched, sample subjects, any errors.
    """
    if not categories:
        return {"status": "error",
                "error": "categories list empty — pass at least one tag."}
    body_q = (body_contains or "").strip()
    with com_thread():
        items = _search_inner(
            query=body_q,                # search() matches body + subject
            sender=sender_contains or "",
            subject_contains=subject_contains or "",
            days=int(days or 0),
            limit=int(limit or 500),
        )
        # Post-filter for unread_only since _search_inner doesn't have
        # the kwarg.
        if unread_only:
            items = [it for it in items if it.get("unread")]
        touched: list[dict] = []
        errors: list[dict] = []
        for it in items:
            eid = it.get("entry_id")
            if not eid:
                continue
            try:
                r = _set_categories_inner(eid, categories, mode=mode)
                if r.get("status") == "ok":
                    touched.append({
                        "entry_id": eid,
                        "subject": (it.get("subject") or "")[:80],
                        "categories": r.get("categories") or [],
                    })
                else:
                    errors.append({"entry_id": eid,
                                    "error": r.get("error")})
            except Exception as ex:
                errors.append({"entry_id": eid,
                                "error": f"{type(ex).__name__}: {ex}"})
        return {
            "status": "ok",
            "matched": len(items),
            "touched": len(touched),
            "errors": errors[:10],
            "sample": touched[:5],
            "applied_categories": categories,
            "filter": {
                "sender_contains": sender_contains,
                "subject_contains": subject_contains,
                "body_contains": body_contains,
                "days": days, "unread_only": unread_only,
            },
        }


# Outlook folder constants.
_OL_FOLDER_SENT = 5
_OL_FOLDER_DRAFTS = 16


def execute_python(*, code: str, timeout_seconds: int = 60) -> dict:
    """Run arbitrary Python in the Outlook COM context.

    Globals injected:
      outlook    — the Outlook.Application COM object
      ns         — MAPI Namespace (outlook.GetNamespace('MAPI'))
      inbox      — default Inbox folder
      sent       — default Sent Items folder
      drafts     — default Drafts folder
      pythoncom  — for native constants if needed
      datetime, json, re — common stdlib imports

    Return: whatever you assign to `result`. Stdout captured too.
    Errors caught — return {status: 'error', error, traceback}.

    Use this as the ESCAPE HATCH when no named tool fits. Always
    prefer named tools for common ops (list_inbox, set_categories,
    auto_categorize_by_sender) since they're faster + clearer. But
    for anything custom — 'find all emails from Q1 that mention
    Tower-A and forward to bob@', 'count messages per sender per
    week', etc. — write Python here.
    """
    if not code or not str(code).strip():
        return {"status": "error", "error": "code is empty"}
    import io
    import traceback as _tb
    import contextlib
    from datetime import datetime as _dt
    import json as _json
    import re as _re

    with com_thread():
        try:
            import pythoncom
        except Exception:
            pythoncom = None
        outlook = _client()
        ns = _ns()
        inbox = ns.GetDefaultFolder(_OL_FOLDER_INBOX)
        try:
            sent = ns.GetDefaultFolder(_OL_FOLDER_SENT)
        except Exception:
            sent = None
        try:
            drafts = ns.GetDefaultFolder(_OL_FOLDER_DRAFTS)
        except Exception:
            drafts = None

        globs = {
            "__builtins__": __builtins__,
            "outlook": outlook,
            "ns": ns,
            "inbox": inbox,
            "sent": sent,
            "drafts": drafts,
            "pythoncom": pythoncom,
            "datetime": _dt,
            "json": _json,
            "re": _re,
        }
        locs: dict = {}
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(code, "<outlook_execute_python>", "exec"),
                     globs, locs)
        except Exception as ex:
            return {
                "status": "error",
                "error": f"{type(ex).__name__}: {ex}",
                "traceback": _tb.format_exc()[-2000:],
                "stdout": buf.getvalue()[-2000:],
            }
        result = locs.get("result", None)
        # Best-effort serialise — if result isn't JSON-friendly, stringify.
        try:
            _json.dumps(result)
            serialised = result
        except Exception:
            serialised = repr(result)[:4000]
        return {
            "status": "ok",
            "result": serialised,
            "stdout": buf.getvalue()[-4000:],
        }


def list_sent_items(*, limit: int = 20,
                     days: int = 0) -> list[dict]:
    """List recent messages from the Sent Items folder. Mirror of
    list_inbox for the sent side."""
    with com_thread():
        ns = _ns()
        items = ns.GetDefaultFolder(_OL_FOLDER_SENT).Items
        items.Sort("[SentOn]", True)
        out: list[dict] = []
        from datetime import datetime, timedelta
        cutoff = None
        if days and days > 0:
            cutoff = datetime.now() - timedelta(days=int(days))
        for i, m in enumerate(items):
            if i >= int(limit or 20):
                break
            try:
                sent_on = getattr(m, "SentOn", None)
                if cutoff is not None and sent_on:
                    try:
                        ts = datetime(sent_on.year, sent_on.month,
                                       sent_on.day, sent_on.hour,
                                       sent_on.minute, sent_on.second)
                        if ts < cutoff:
                            break
                    except Exception:
                        pass
                to_emails = []
                try:
                    for r in (getattr(m, "Recipients", None) or []):
                        addr = getattr(r, "Address", "") or ""
                        if addr:
                            to_emails.append(str(addr))
                except Exception:
                    pass
                out.append({
                    "entry_id": str(getattr(m, "EntryID", "") or ""),
                    "subject": str(getattr(m, "Subject", "") or ""),
                    "to": to_emails,
                    "sent_on": str(sent_on) if sent_on else "",
                    "body_preview": (str(getattr(m, "Body", "") or "")
                                      [:200]),
                    "categories": str(getattr(m, "Categories", "") or ""),
                })
            except Exception:
                continue
        return out


def auto_categorize_by_subject_keywords(
        *, keyword_map: dict, days: int = 30,
        limit: int = 500, include_sent: bool = False) -> dict:
    """Content-based bulk categoriser. Takes a {keyword: category}
    map; for each keyword applies the category to every message
    whose subject OR body contains the keyword (case-insensitive).

    Example call:
      keyword_map = {
        'Tower-A': 'Tower-A',
        'RFI': 'RFIs',
        'invoice': 'Finance',
      }
    → Tags all messages with 'Tower-A' in subject/body as 'Tower-A',
       all with 'RFI' as 'RFIs', etc. Each message can land in
       multiple categories (mode='add').

    Pairs with auto_categorize_by_sender for content-based grouping
    when sender-domain grouping isn't right. The model picks the
    keyword_map from context — for ambiguous bulk requests just
    call auto_categorize_by_sender instead.
    """
    if not keyword_map:
        return {"status": "error",
                "error": "keyword_map empty — pass at least one entry."}
    with com_thread():
        # One full scan of inbox (+ sent if requested) up front.
        scope: list[dict] = list(_search_inner(
            query="", sender="", subject_contains="",
            days=int(days or 30), limit=int(limit or 500),
        ))
        if include_sent:
            scope.extend(list_sent_items(limit=int(limit or 500),
                                           days=days))
        applied: list[dict] = []
        errors: list[dict] = []
        for kw, cat in (keyword_map or {}).items():
            if not kw or not cat:
                continue
            kwl = str(kw).lower()
            hits = []
            for it in scope:
                subj = (it.get("subject") or "").lower()
                body = (it.get("body_preview") or
                         it.get("body") or "").lower()
                if kwl in subj or kwl in body:
                    hits.append(it)
            touched = 0
            for it in hits:
                eid = it.get("entry_id")
                if not eid:
                    continue
                try:
                    r = _set_categories_inner(eid, [str(cat)],
                                                mode="add")
                    if r.get("status") == "ok":
                        touched += 1
                except Exception as ex:
                    errors.append({
                        "keyword": kw, "entry_id": eid,
                        "error": f"{type(ex).__name__}: {ex}",
                    })
            applied.append({
                "keyword": kw, "category": cat,
                "matched": len(hits), "touched": touched,
            })
        return {
            "status": "ok",
            "scope": len(scope),
            "applied": applied,
            "errors": errors[:10],
            "summary": (
                f"Tagged {sum(a['touched'] for a in applied)} "
                f"messages across {len(applied)} keywords."
            ),
        }


def auto_categorize_by_sender(*, days: int = 30,
                                limit: int = 500,
                                min_messages: int = 2) -> dict:
    """One-shot bulk categorisation. ZERO model orchestration needed.

    Internally:
      1. Walks last `days` of inbox via _search_inner.
      2. Groups by sender domain.
      3. Derives a category name from the domain (first label,
         title-cased). 'mail.bayatyarchitects.com' → 'Bayatyarchitects'.
         'autodesk.com' → 'Autodesk'.
      4. For each domain with >= min_messages msgs, applies the
         derived category to every message from that domain via
         _set_categories_inner.
      5. Returns full summary.

    Solves the local-model orchestration failure: command-r7b /
    llama3.1 can't reliably loop list → read → set. With this tool
    they just call auto_categorize_by_sender() once. Tool engine
    does the rest.
    """
    def _domain_to_category(dom: str) -> str:
        if not dom:
            return "Uncategorised"
        head = dom.split(".")[0]
        # Drop common no-info prefixes.
        if head in ("mail", "smtp", "email", "noreply", "no-reply",
                     "info", "support"):
            parts = dom.split(".")
            if len(parts) >= 2:
                head = parts[1] if parts[0] in ("mail", "smtp",
                                                  "email") else parts[0]
        return head.replace("-", " ").replace("_", " ").title()

    with com_thread():
        items = _search_inner(query="", sender="", subject_contains="",
                                days=int(days or 30),
                                limit=int(limit or 500))
        # Group by domain.
        by_domain: dict[str, list[dict]] = {}
        for it in items:
            sender = (it.get("sender_email") or
                       it.get("sender") or "").strip().lower()
            if not sender:
                continue
            dom = sender.split("@")[-1] if "@" in sender else sender
            by_domain.setdefault(dom, []).append(it)

        applied: list[dict] = []
        skipped: list[dict] = []
        errors: list[dict] = []
        for dom, group in sorted(by_domain.items(),
                                   key=lambda kv: -len(kv[1])):
            if len(group) < min_messages:
                skipped.append({"domain": dom, "count": len(group),
                                 "reason": f"under min_messages "
                                            f"({min_messages})"})
                continue
            cat = _domain_to_category(dom)
            touched = 0
            for it in group:
                eid = it.get("entry_id")
                if not eid:
                    continue
                try:
                    r = _set_categories_inner(eid, [cat], mode="add")
                    if r.get("status") == "ok":
                        touched += 1
                except Exception as ex:
                    errors.append({"domain": dom, "entry_id": eid,
                                    "error": f"{type(ex).__name__}: "
                                              f"{ex}"})
            applied.append({"domain": dom, "category": cat,
                             "matched": len(group),
                             "touched": touched})
        return {
            "status": "ok",
            "total_messages": len(items),
            "distinct_domains": len(by_domain),
            "categorised": applied,
            "skipped": skipped,
            "errors": errors[:10],
            "summary": (
                f"Tagged {sum(a['touched'] for a in applied)} "
                f"messages across {len(applied)} categories."
            ),
        }


def list_distinct_senders(*, days: int = 30,
                           limit: int = 500) -> dict:
    """Walk recent inbox, return unique sender domains with counts +
    a few sample subjects per domain. Helps the LLM derive sensible
    project / category names without reading every message body."""
    with com_thread():
        items = _search_inner(query="", sender="", subject_contains="",
                                days=int(days or 30),
                                limit=int(limit or 500))
        domains: dict[str, dict] = {}
        for it in items:
            sender = (it.get("sender_email") or
                       it.get("sender") or "").strip().lower()
            if not sender:
                continue
            dom = sender.split("@")[-1] if "@" in sender else sender
            entry = domains.setdefault(dom, {
                "domain": dom, "count": 0, "samples": [],
            })
            entry["count"] += 1
            if len(entry["samples"]) < 3:
                entry["samples"].append(it.get("subject", "")[:80])
        out = sorted(domains.values(), key=lambda d: -d["count"])
        return {"status": "ok", "total_messages": len(items),
                 "distinct_domains": len(out), "domains": out[:50]}


def list_folders(*, root: str = "") -> list[dict]:
    """Walk the user's MAPI folders. `root` empty = enumerate from the
    default store root. Returns flat list of {path, name, item_count,
    folder_id}. Useful for project-folder mapping ("move emails about
    Tower-A into the Tower-A folder")."""
    with com_thread():
        return _list_folders_inner(root=root)


def _list_folders_inner(*, root: str) -> list[dict]:
    ns = _ns()
    out: list[dict] = []

    def _walk(folder, prefix: str) -> None:
        try:
            name = _safe(folder.Name, 120)
        except Exception:
            return
        path = f"{prefix}/{name}" if prefix else name
        try:
            count = int(folder.Items.Count)
        except Exception:
            count = -1
        try:
            fid = _safe(folder.EntryID, 0)
        except Exception:
            fid = ""
        out.append({"path": path, "name": name,
                    "item_count": count, "folder_id": fid})
        try:
            for child in folder.Folders:
                _walk(child, path)
        except Exception:
            return

    if root:
        try:
            target = ns.GetFolderFromID(root)
            _walk(target, "")
        except Exception:
            return out
    else:
        # Default store inbox parent walks the whole tree.
        inbox = ns.GetDefaultFolder(_OL_FOLDER_INBOX)
        try:
            store_root = inbox.Parent
            _walk(store_root, "")
        except Exception:
            _walk(inbox, "")
    return out


def create_folder(parent_id: str, name: str) -> dict:
    """Create a new mail folder under `parent_id` (a folder EntryID).
    Returns the new folder's EntryID + path."""
    with com_thread():
        return _create_folder_inner(parent_id, name)


def _create_folder_inner(parent_id: str, name: str) -> dict:
    ns = _ns()
    if parent_id:
        parent = ns.GetFolderFromID(parent_id)
    else:
        parent = ns.GetDefaultFolder(_OL_FOLDER_INBOX)
    try:
        new = parent.Folders.Add(str(name).strip())
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:200]}
    return {"status": "ok",
            "folder_id": _safe(getattr(new, "EntryID", "")),
            "name": _safe(getattr(new, "Name", "")),
            "parent_id": _safe(getattr(parent, "EntryID", ""))}


def move_to_folder(entry_id: str, folder_id: str) -> dict:
    """Move a message to a target folder by folder EntryID."""
    with com_thread():
        return _move_to_folder_inner(entry_id, folder_id)


def _move_to_folder_inner(entry_id: str, folder_id: str) -> dict:
    ns = _ns()
    msg = ns.GetItemFromID(entry_id)
    folder = ns.GetFolderFromID(folder_id)
    try:
        moved = msg.Move(folder)
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:200]}
    return {"status": "ok",
            "new_entry_id": _safe(getattr(moved, "EntryID", "")),
            "folder_id": folder_id}


def mark_read(entry_id: str, *, read: bool = True) -> dict:
    """Toggle the message's read/unread flag."""
    with com_thread():
        ns = _ns()
        m = ns.GetItemFromID(entry_id)
        m.UnRead = (not bool(read))
        m.Save()
        return {"status": "ok", "entry_id": entry_id, "unread": m.UnRead}


def flag_for_followup(entry_id: str, *, due_offset_days: int = 0,
                       reminder: bool = False) -> dict:
    """Set the standard Outlook follow-up flag on a message."""
    with com_thread():
        ns = _ns()
        m = ns.GetItemFromID(entry_id)
        m.FlagRequest = "Follow up"
        if due_offset_days > 0:
            from datetime import datetime, timedelta
            due = datetime.now() + timedelta(days=int(due_offset_days))
            try:
                m.TaskDueDate = due
                m.TaskStartDate = datetime.now()
            except Exception:
                pass
        if reminder:
            try:
                m.ReminderSet = True
            except Exception:
                pass
        m.Save()
        return {"status": "ok", "entry_id": entry_id}


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
