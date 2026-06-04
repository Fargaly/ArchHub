"""Settings dialog — structural / contract tests for the tab list.

The `SettingsDialog.TABS` list is the contract that downstream agents
(JSX, bridge, founder muscle-memory) rely on. Tabs added or reordered
here without coordination break the UX promise. These tests pin:

  * `SettingsDialog` + `BrainTab` import cleanly.
  * `BrainTab` is a `QWidget` subclass.
  * `TABS` is exactly the 11-entry list in the documented order, with
    Brain at index 5 (between Memory and Permissions) and
    Accessibility at index 9 (between Shortcuts and About).
  * `BrainTab` exposes every public/private method that
    `studio-lm.jsx` + the dialog code expects.
  * `BrainTab.DAEMON_URL` matches the BRAIN-FIRST MANDATE port
    (8473/mcp).
  * `AccessibilityTab` imports clean + is a QWidget subclass.
  * Bonus: if agent 3's `SecretsTab` has landed, it imports.

Tests deliberately avoid Qt app boot where possible — only the
`SettingsDialog` instantiation needs a `QApplication`, so the QWidget
subclass check works at the class level.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ── Qt fixture (some platforms refuse QWidget instantiation without an
#    app) ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


# ── Import-level (no app instance needed) ─────────────────────────────
def test_settings_dialog_imports_clean():
    """SettingsDialog must be importable without dragging in heavy state."""
    from settings_dialog import SettingsDialog
    assert SettingsDialog is not None
    # Sanity: it's a class.
    assert isinstance(SettingsDialog, type)


def test_braintab_imports():
    """BrainTab is importable + is a QWidget subclass."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QWidget
    from settings_dialog import BrainTab
    assert BrainTab is not None
    assert isinstance(BrainTab, type)
    assert issubclass(BrainTab, QWidget), (
        "BrainTab must be a QWidget subclass so SettingsDialog can "
        "host it inside a QScrollArea."
    )


def test_tabs_list_order():
    """The TABS contract: 12-entry list. Secrets inserted between Providers
    and Hosts (2026-05-26 wave agent 3); Accessibility between Shortcuts and
    About (2026-05-26 wave agent E); Account APPENDED after About
    (MAKE-IT-REAL cloud sign-in agent, 2026-05-31) — appended, not inserted,
    so every prior tab keeps its documented index. Brain stays at index 5
    between Memory and Permissions; Accessibility at index 9 between
    Shortcuts and About; Account is the last tab."""
    from settings_dialog import SettingsDialog
    expected = [
        "General", "Providers", "Secrets", "Hosts", "Memory", "Brain",
        "Permissions", "Storage", "Shortcuts", "Accessibility", "About",
        "Account",
    ]
    actual = [label for label, _cls in SettingsDialog.TABS]
    assert actual == expected, (
        f"TABS order changed!\n  expected: {expected}\n  actual:   {actual}"
    )
    # Brain stays between Memory and Permissions.
    assert actual.index("Brain") == 5
    assert actual[4] == "Memory"
    assert actual[6] == "Permissions"
    # Secrets MUST come right after Providers.
    assert actual.index("Secrets") == 2
    assert actual[1] == "Providers"
    # Accessibility lands between Shortcuts and About.
    assert actual.index("Accessibility") == 9
    assert actual[8] == "Shortcuts"
    assert actual[10] == "About"
    # Account is appended as the final tab — the real cloud sign-in home.
    assert actual.index("Account") == 11
    assert actual[-1] == "Account"
    assert len(SettingsDialog.TABS) == 12


def test_tabs_list_entries_are_widget_classes():
    """Every TABS entry's second slot is a class (resolved at import).
    Guards against accidental `(label, lambda: …)` regressions."""
    from settings_dialog import SettingsDialog
    for label, cls in SettingsDialog.TABS:
        assert isinstance(label, str)
        assert isinstance(cls, type), (
            f"TABS entry {label!r} second slot is not a class: {cls!r}"
        )


def test_braintab_has_required_methods():
    """The methods studio-lm.jsx + the dialog wire-up expect to exist
    on BrainTab. Tests catch silent renames before they hit ArchHub
    boot."""
    from settings_dialog import BrainTab
    required = [
        "_mcp_call",
        "_refresh",
        "_render_firm",
        "_on_create_firm",
        "_on_join_firm",
        "_on_create_invite",
        "_on_leave_firm",
        "_on_subscribe",
        "_make_tile",
    ]
    missing = [m for m in required if not hasattr(BrainTab, m)]
    assert not missing, (
        f"BrainTab missing required methods: {missing}. "
        f"These names are wired from settings_dialog + tests."
    )
    # And — they are actually callable.
    for name in required:
        assert callable(getattr(BrainTab, name)), (
            f"BrainTab.{name} exists but is not callable."
        )


def test_braintab_daemon_url_constant():
    """BrainTab points at the canonical local brain daemon URL. Change
    this and the BRAIN-FIRST MANDATE preamble curl example also has
    to change — they MUST agree."""
    from settings_dialog import BrainTab
    assert BrainTab.DAEMON_URL == "http://127.0.0.1:8473/mcp"


def test_braintab_constructor_signature_takes_parent():
    """BrainTab(parent_dialog) — single positional arg. Other tabs
    follow the same shape so SettingsDialog can construct them
    generically inside its for-loop."""
    import inspect
    from settings_dialog import BrainTab
    sig = inspect.signature(BrainTab.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert len(params) >= 1, (
        "BrainTab.__init__ must accept at least a parent_dialog arg."
    )


def test_all_tab_classes_are_qwidgets():
    """Every tab class in TABS must be a QWidget subclass — that's the
    SettingsDialog contract for wrapping each in a QScrollArea."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QWidget
    from settings_dialog import SettingsDialog
    for label, cls in SettingsDialog.TABS:
        assert issubclass(cls, QWidget), (
            f"{label} tab class {cls.__name__} is not a QWidget subclass."
        )


# ── Bonus: agent 3's SecretsTab (importorskip pattern) ────────────────
def test_secretstab_imports_if_present():
    """If agent 3's SecretsTab has landed, it must import + be a
    QWidget subclass. If it has not landed yet, the test SKIPS so
    waves don't collide."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QWidget
    import importlib
    mod = importlib.import_module("settings_dialog")
    if not hasattr(mod, "SecretsTab"):
        pytest.skip("SecretsTab not landed yet (agent 3's work)")
    SecretsTab = getattr(mod, "SecretsTab")
    assert isinstance(SecretsTab, type)
    assert issubclass(SecretsTab, QWidget)


# ── Track E (Accessibility, 2026-05-26): AccessibilityTab must import
def test_accessibility_tab_imports():
    """AccessibilityTab is importable + is a QWidget subclass + carries
    the documented DAEMON_URL constant the same way BrainTab does."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QWidget
    from settings_dialog import AccessibilityTab
    assert AccessibilityTab is not None
    assert isinstance(AccessibilityTab, type)
    assert issubclass(AccessibilityTab, QWidget), (
        "AccessibilityTab must be a QWidget subclass so SettingsDialog "
        "can host it inside a QScrollArea."
    )
    # Same canonical brain daemon URL as BrainTab — the audit doc + the
    # BRAIN-FIRST mandate preamble all agree on 127.0.0.1:8473/mcp.
    assert AccessibilityTab.DAEMON_URL == "http://127.0.0.1:8473/mcp"
