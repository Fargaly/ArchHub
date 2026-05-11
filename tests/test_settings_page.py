"""Settings page (v0.41) — sectioned chrome assembly.

Verifies the page structure without painting:
  * SettingsPage instantiates with no router and reports 3 sections
  * Each section button is checkable and exclusive
  * _select() flips the QStackedWidget index
  * Section ids round-trip to the right widget
  * About section renders version/build kv pairs
  * Diagnostics section enumerates connector families
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


@pytest.fixture
def page(qapp):
    from settings_page import SettingsPage
    return SettingsPage(router=None)


class TestSettingsPage:
    def test_three_sections_present(self, page):
        from settings_page import _SECTIONS
        assert len(_SECTIONS) == 3
        ids = {sid for sid, _ in _SECTIONS}
        assert ids == {"providers", "about", "diagnostics"}

    def test_default_selection_is_providers(self, page):
        assert page.stack.currentIndex() == 0
        assert page._buttons["providers"].isChecked()
        for sid in ("about", "diagnostics"):
            assert not page._buttons[sid].isChecked()

    def test_select_about_flips_stack(self, page):
        page._select("about")
        assert page.stack.currentIndex() == 1
        assert page._buttons["about"].isChecked()
        assert not page._buttons["providers"].isChecked()

    def test_select_diagnostics_flips_stack(self, page):
        page._select("diagnostics")
        assert page.stack.currentIndex() == 2
        assert page._buttons["diagnostics"].isChecked()

    def test_select_unknown_section_is_noop(self, page):
        idx_before = page.stack.currentIndex()
        page._select("does_not_exist")
        assert page.stack.currentIndex() == idx_before

    def test_about_section_has_app_card(self, page):
        page._select("about")
        about = page.stack.currentWidget()
        # Walk the children for kv labels — confirms _kv_card built rows.
        from PyQt6.QtWidgets import QLabel
        labels = about.findChildren(QLabel)
        texts = [lab.text() for lab in labels]
        assert any("ArchHub" in t for t in texts)
        # The version field renders the literal string "Python" as a
        # kv key — guards against accidental section deletion.
        assert any("Python" == t for t in texts)

    def test_diagnostics_section_has_connector_rows(self, page):
        page._select("diagnostics")
        diag = page.stack.currentWidget()
        from PyQt6.QtWidgets import QLabel
        labels = [lab.text() for lab in diag.findChildren(QLabel)]
        # At least one of the connector family titles should appear.
        assert any(fam in labels
                    for fam in ("Revit", "Acad", "Max", "Blender", "Outlook"))


class TestVersionReaders:
    def test_read_version_safe_when_file_missing(self):
        from settings_page import _read_version
        # Either returns a string or None; never raises.
        v = _read_version()
        assert v is None or isinstance(v, str)

    def test_read_git_sha_safe(self):
        from settings_page import _read_git_sha
        # Same — best-effort, returns None or 8-char prefix.
        sha = _read_git_sha()
        assert sha is None or (isinstance(sha, str) and len(sha) <= 40)
