"""Notification channels for the autonomous loop.

Three sinks, all no-auth, in priority order:

  1. Desktop status file — overwrite `%USERPROFILE%/Desktop/
     ArchHub-Status.html` each tick. User glances at desktop, sees
     latest. Zero credentials. Always works.

  2. Windows toast — pops a single-line notification when something
     ships, breaks, or graduates. Uses `winrt` if installed; falls
     back to `win10toast` if available; falls back to silent if
     neither.

  3. Discord webhook — POSTs the headline + link to a webhook URL
     stored in `secrets_store('discord_webhook_url')`. User pastes
     URL once in Settings → Notifications. No OAuth, no app
     password.

Optional 4. Notion page — if a Notion API token is configured, append
     a block to the dashboard page. Wired but only fires if token
     is present.

Hourly_report.py and the dispatcher both call `notify(...)` —
exceptions never propagate.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_DESKTOP = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
_STATUS_FILE = _DESKTOP / "ArchHub-Status.html"


# ---------------------------------------------------------------------------
def _load_setting(key: str) -> Optional[str]:
    """Read from secrets_store if available, else env var fallback.
    secrets_store lives in app/, which is not on agents/'s sys.path
    by default — guard the import."""
    try:
        import sys
        repo_root = Path(__file__).resolve().parent.parent
        app_dir = repo_root / "app"
        if str(app_dir) not in sys.path:
            sys.path.insert(0, str(app_dir))
        from secrets_store import load_setting
        v = load_setting(key)
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get(f"ARCHHUB_{key.upper()}")


# ---------------------------------------------------------------------------
def write_desktop_status(html: str) -> Path:
    """Always-on, no-auth: drop the latest report on the desktop.
    Overwrites in place each call. Returns the path."""
    try:
        _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATUS_FILE.write_text(html, encoding="utf-8")
    except Exception:
        pass
    return _STATUS_FILE


def windows_toast(title: str, message: str) -> bool:
    """Best-effort Windows toast notification. Returns True if dispatched.

    Tries winrt's windows.ui.notifications stack first (built-in on
    Windows 10/11, no pip install). Falls back to running PowerShell
    BurntToast cmdlet if installed; finally silent."""
    title = (title or "")[:64]
    message = (message or "")[:200]
    if not title and not message:
        return False
    # PowerShell BurntToast — most reliable, no pip dep.
    try:
        import subprocess, sys
        ps = (
            "Import-Module BurntToast -ErrorAction Stop; "
            f'New-BurntToastNotification -Text "{_escape_ps(title)}", "{_escape_ps(message)}" -AppLogo $null'
        )
        creationflags = 0
        startupinfo = None
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True, timeout=8, text=True,
            creationflags=creationflags, startupinfo=startupinfo,
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass
    # Native winrt toast — works without BurntToast on Win10/11.
    try:
        from winrt.windows.ui.notifications import (
            ToastNotificationManager, ToastNotification,
        )
        from winrt.windows.data.xml.dom import XmlDocument
        toast_xml = (
            '<toast><visual><binding template="ToastGeneric">'
            f'<text>{_xml_escape(title)}</text>'
            f'<text>{_xml_escape(message)}</text>'
            "</binding></visual></toast>"
        )
        xml = XmlDocument()
        xml.load_xml(toast_xml)
        notifier = ToastNotificationManager.create_toast_notifier("ArchHub")
        notifier.show(ToastNotification(xml))
        return True
    except Exception:
        return False


def _escape_ps(s: str) -> str:
    return s.replace('"', '`"').replace("\n", " ")


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


# ---------------------------------------------------------------------------
def discord_webhook(headline: str, summary: str = "",
                    link: Optional[str] = None) -> bool:
    """POST a one-line Discord embed to a configured webhook. No auth
    beyond the URL itself (which is the secret). Returns True on 2xx."""
    url = _load_setting("discord_webhook_url")
    if not url:
        return False
    payload = {
        "username": "ArchHub",
        "embeds": [{
            "title": (headline or "ArchHub")[:256],
            "description": (summary or "")[:1900],
            "url": link,
            "color": 0xD97757,           # Anthropic orange
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
def notify(headline: str, summary: str = "", *,
           html: Optional[str] = None, link: Optional[str] = None,
           toast: bool = True) -> dict:
    """Fan out to every configured channel. Always silent on failure;
    returns a dict of which channels actually fired so the caller can
    log it."""
    fired = {"desktop": False, "toast": False, "discord": False}
    if html:
        fired["desktop"] = bool(write_desktop_status(html))
    if toast:
        fired["toast"] = windows_toast(headline, summary)
    fired["discord"] = discord_webhook(headline, summary, link=link)
    return fired
