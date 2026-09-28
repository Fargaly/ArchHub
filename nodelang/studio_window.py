"""The desktop window holds one page: the Studio.

The audit (2026-09-28) found the native Back / Reload menu on a right-click and a
history that still carried the bootstrap document at ``/``: Back, Alt+Left or the
mouse's Back button left the Studio for that document. The window now offers no
native context menu, and once the Studio has loaded its history is emptied, so
there is nothing behind it to go back to.
"""
from __future__ import annotations


def lock_studio_navigation(view) -> None:
    """No native Back / Forward / Reload menu on the Studio window."""
    from PyQt6.QtCore import Qt

    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)


def forget_pages_behind_studio(view) -> None:
    """Drop every history entry, so Back has nowhere to go from the Studio."""
    view.history().clear()
