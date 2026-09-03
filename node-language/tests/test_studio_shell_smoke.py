"""StudioShell construction smoke test.

The Studio shell builds every nav page eagerly in `__init__` (so nav
switches are instant). A typo in any page-builder method — most
recently a palette key that didn't exist (`T["textMuted"]` instead of
`T["inkMuted"]`) — crashes the WHOLE shell at startup. `app/main.py`
catches the exception and falls back to the bare ChatWindow, which
renders an empty center pane and looks (to the founder) like the app
is broken.

This file pins the construction path so the next palette-key typo,
QSS-formatter typo, or missing-method bug surfaces in CI instead of
in boot.log.

Coverage is intentionally minimal — no event-loop, no paint, no
signal/slot dispatch. The point is: does `StudioShell(...)` build
without raising?
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the whole session — offscreen platform
    plugin so the test runs headless on CI."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    return app


@pytest.fixture
def mock_chat_window(qapp):
    """A bare QMainWindow stand-in for ChatWindow.

    StudioShell wraps `chat_widget.centralWidget()` as the Chat page.
    We hand it a real QMainWindow so the centralWidget call works
    without needing the entire ChatWindow init chain.
    """
    from PyQt6.QtWidgets import QMainWindow, QWidget
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    return win


@pytest.fixture
def mock_router():
    r = MagicMock()
    r.configured_providers.return_value = []
    r.blocked_providers.return_value = {}
    return r


@pytest.fixture
def mock_manager():
    m = MagicMock()
    m.entries = []
    return m


@pytest.fixture
def mock_tools():
    return MagicMock()


class TestStudioShellBuilds:
    def test_constructs_without_exception(
        self, qapp, mock_chat_window, mock_router, mock_manager, mock_tools
    ):
        """Catches palette-key typos, missing QSS keys, undefined
        method names, and any other import/build error in the page
        builders.
        """
        from studio_shell import StudioShell
        shell = StudioShell(chat_widget=mock_chat_window,
                             router=mock_router, manager=mock_manager,
                             tools=mock_tools)
        assert shell is not None

    def test_all_nav_pages_built(
        self, qapp, mock_chat_window, mock_router, mock_manager, mock_tools
    ):
        """Each nav id must have a corresponding page widget in the
        QStackedWidget so _set_page() never lands on `None`."""
        from studio_shell import StudioShell, NAV_ITEMS_ALL
        shell = StudioShell(chat_widget=mock_chat_window,
                             router=mock_router, manager=mock_manager,
                             tools=mock_tools)
        for nav_id, _, _ in NAV_ITEMS_ALL:
            assert nav_id in shell.pages, f"page missing for nav id {nav_id!r}"

    def test_memory_page_in_nav(
        self, qapp, mock_chat_window, mock_router, mock_manager, mock_tools
    ):
        """v1.3.3 added Memory at slot 4. Pin its presence so a future
        nav refactor doesn't silently drop it."""
        from studio_shell import StudioShell, NAV_ITEMS
        nav_ids = {nav_id for nav_id, _, _ in NAV_ITEMS}
        assert "memory" in nav_ids
        shell = StudioShell(chat_widget=mock_chat_window,
                             router=mock_router, manager=mock_manager,
                             tools=mock_tools)
        assert "memory" in shell.pages

    def test_set_page_to_memory_does_not_raise(
        self, qapp, mock_chat_window, mock_router, mock_manager, mock_tools
    ):
        """Memory page entry triggers _refresh_memory_stats which
        reaches into cloud_client. Confirm it handles the unreachable
        case gracefully (no exception bubble)."""
        from studio_shell import StudioShell
        shell = StudioShell(chat_widget=mock_chat_window,
                             router=mock_router, manager=mock_manager,
                             tools=mock_tools)
        shell._set_page("memory")


class TestPaletteKeys:
    """Every T[...] subscript in studio_shell must resolve at construction
    time. Yesterday `T['textMuted']` crashed the shell; the fix shipped
    in two passes (single-quote then double-quote variants). This test
    parses every f-string subscript on T and confirms each key exists
    in the current palette.
    """
    def test_no_bad_palette_keys(self, qapp):
        import re
        from pathlib import Path
        import design_tokens

        # Strip Python comments so the regex doesn't pick up the
        # literal `T['key']` that lives in a docstring/comment as a
        # placeholder for "any palette key".
        raw = (APP_ROOT / "studio_shell.py").read_text(encoding="utf-8")
        src_lines = []
        for line in raw.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            # Cut inline `# ...` comments. Heuristic: split on " #"
            # so we don't slice URLs or hex literals.
            if " #" in line:
                line = line.split(" #", 1)[0]
            src_lines.append(line)
        src = "\n".join(src_lines)

        keys = set(re.findall(r"""T\[\s*['"]([^'"]+)['"]\s*\]""", src))
        keys |= set(re.findall(
            r"""T\.get\(\s*['"]([^'"]+)['"]""", src))
        # The palette is a _LivePalette proxy over current_palette() —
        # we check both light and dark dicts since either can be active.
        light = design_tokens.COLOR
        dark = design_tokens.COLOR_DARK
        missing = []
        for k in keys:
            if k not in light or k not in dark:
                missing.append(k)
        assert not missing, (
            f"studio_shell.py references palette keys missing from "
            f"design_tokens.py: {sorted(missing)}"
        )
