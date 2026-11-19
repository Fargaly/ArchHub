"""The desktop window holds one page: the Studio.

The audit (2026-09-28) found the native Back / Reload menu on a right-click and a
history that still carried the bootstrap document at ``/``: Back, Alt+Left or the
mouse's Back button left the Studio for that document. The window now offers no
native context menu, and once the Studio has loaded its history is emptied, so
there is nothing behind it to go back to.

A link the Studio opens in a new window (billing checkout, an MCP connection page)
goes to the founder's own Chrome (R149: "open it in my browser"). Without a handler
QtWebEngine drops ``window.open`` silently, so those buttons did nothing.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import webbrowser
from urllib.parse import urlsplit


def _chrome_path() -> str | None:
    """Installed Chrome from the Windows App Paths key, or None."""
    missing = False
    try:
        import winreg
    except ImportError:
        missing = True
    if missing:
        return None
    key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value = winreg.QueryValue(key, None)
        except OSError:
            continue
        candidate = (value or '').strip('"')
        if candidate and Path(candidate).is_file():  # a stale key (Chrome removed) falls through to the next hive
            return candidate
    return None


def open_outside(url: str, *, chrome_path=_chrome_path, launch=subprocess.Popen, fallback=webbrowser.open) -> bool:
    """Open a web address in his Chrome, else his default browser. Refuses non-web or credential URLs."""
    parts = urlsplit(url or '')
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
        return False
    chrome = chrome_path()
    if chrome:
        try:
            launch([chrome, parts.geturl()], close_fds=True)
            return True
        except OSError:
            return bool(fallback(parts.geturl()))
    return bool(fallback(parts.geturl()))


def lock_studio_navigation(view) -> None:
    """No native Back / Forward / Reload menu; new-window links open in his browser."""
    from PyQt6.QtCore import Qt

    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    # The request is left unaccepted, so no second Qt window opens.
    view.page().newWindowRequested.connect(lambda request: open_outside(request.requestedUrl().toString()))


def forget_pages_behind_studio(view) -> None:
    """Drop every history entry, so Back has nowhere to go from the Studio."""
    view.history().clear()
