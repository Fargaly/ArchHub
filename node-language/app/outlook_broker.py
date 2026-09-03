"""Outlook broker — surface each Outlook account as a "session".

Outlook is single-process per user (COM), so the multi-session story
isn't "two Outlook windows" the way Revit's is — it's "two mail
accounts in one Outlook." The MAPI namespace's Accounts collection
gives us each account (SmtpAddress + DisplayName + StoreID), and the
broker maps each one onto a Session record so the Studio HOSTS row
can read "Outlook · 2 sess" the same way it does for Revit.

Public API mirrors revit_broker so studio_shell + connector_health can
treat them interchangeably:

    list_sessions(prune=True)    -> list[Session]
    pick_session(prefer=None)     -> Session | None
    sessions_count()              -> int
    is_any_alive()                -> bool

Each Session.healthy is True iff Outlook COM dispatch succeeded AND
the account responded to a count query.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    session_id:    str           # "outlook-<smtp>"
    family:        str           # "outlook"
    pid:           int           # Outlook host PID (0 if unknown)
    port:          int           # 0 — COM, no port
    version:       str           # Outlook major version when reachable
    doc_title:     str           # account display name
    started_at:    str           # ""
    last_heartbeat: str          # last successful probe
    smtp_address:  str = ""
    legacy:        bool = False
    healthy:       bool = False

    def url(self, path: str = "") -> str:
        # Not network-bound; kept for protocol compat with revit_broker.
        return ""


def _outlook_pid() -> int:
    """Best-effort: scan for OUTLOOK.EXE pid via tasklist."""
    try:
        import subprocess
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE",
             "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=2,
            startupinfo=si,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in (r.stdout or "").splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2 and parts[0].lower() == "outlook.exe":
                try:
                    return int(parts[1])
                except Exception:
                    pass
    except Exception:
        pass
    return 0


def list_sessions(*, prune: bool = True) -> list[Session]:
    """Enumerate accounts in the running Outlook profile."""
    out: list[Session] = []
    try:
        from connectors.outlook_runner import com_thread, _ns
    except Exception:
        return out

    pid = _outlook_pid()
    try:
        with com_thread():
            ns = _ns()
            accounts = getattr(ns, "Accounts", None)
            if accounts is None or accounts.Count == 0:
                return out
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                version = str(getattr(ns.Application, "Version", "")
                              or "")
            except Exception:
                version = ""
            for i in range(accounts.Count):
                try:
                    acc = accounts.Item(i + 1)
                    smtp = str(getattr(acc, "SmtpAddress", "") or "")
                    name = str(getattr(acc, "DisplayName", "") or smtp
                               or f"Account {i+1}")
                    out.append(Session(
                        session_id=f"outlook-{smtp or i+1}",
                        family="outlook",
                        pid=pid,
                        port=0,
                        version=version,
                        doc_title=name,
                        started_at="",
                        last_heartbeat=now_iso,
                        smtp_address=smtp,
                        healthy=True,
                    ))
                except Exception:
                    continue
    except Exception:
        return out
    return out


def pick_session(prefer: Optional[str] = None) -> Optional[Session]:
    sessions = list_sessions()
    healthy = [s for s in sessions if s.healthy]
    if not healthy:
        return None
    if prefer:
        prefer = str(prefer).strip().lower()
        for s in healthy:
            if (prefer in s.session_id.lower()
                or prefer in s.smtp_address.lower()
                or prefer in s.doc_title.lower()):
                return s
    return healthy[0]


def sessions_count() -> int:
    return sum(1 for s in list_sessions(prune=False) if s.healthy)


def is_any_alive() -> bool:
    return bool(list_sessions(prune=False))
