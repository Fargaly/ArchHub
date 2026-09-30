"""Court: the installed runtime carries pytest, because the Work court needs it.

artifact_verification_court.py runs a Work's pytest gate as
``sys.executable -m pytest`` inside the installed application. The installed
environment had no pytest, so every pytest gate failed with
"No module named pytest". pytest now ships in the desktop wheelhouse, setup
import-checks it, and the release build refuses a wheelhouse without it.
"""
from pathlib import Path
import re

import colleague_setup

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_requirements_pin_pytest_and_its_dependencies():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for name in ("pytest", "iniconfig", "pluggy", "packaging", "Pygments"):
        assert re.search(r"^%s==\S+" % re.escape(name), text, re.M), name


def test_setup_import_checks_pytest_after_installing():
    assert ("pytest", "pytest") in colleague_setup.PACKAGES


def test_release_build_refuses_a_wheelhouse_without_pytest():
    build = (ROOT / "installer" / "build_release.ps1").read_text(encoding="utf-8")
    assert "must carry exactly one pytest wheel for the Work court" in build
    assert build.index("pip download") < build.index("exactly one pytest wheel")
