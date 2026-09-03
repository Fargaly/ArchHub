"""Dependency-admission checks for the browser publication court."""
from __future__ import annotations

import json
import os

from nodelang.browser_publish_court import _admitted_playwright_module_path


def _write_playwright_module(root, *, valid_entry=True):
    package = root / "playwright"
    package.mkdir(parents=True)
    package.joinpath("package.json").write_text(
        json.dumps({
            "name": "playwright",
            "version": "1.61.1",
            "main": "index.js",
        }),
        encoding="utf-8",
    )
    package.joinpath("index.js").write_text(
        "module.exports = {};" if valid_entry else "",
        encoding="utf-8",
    )


def test_browser_court_accepts_only_a_complete_declared_playwright_module(
    tmp_path,
):
    corrupt = tmp_path / "corrupt"
    _write_playwright_module(corrupt, valid_entry=False)
    admitted = tmp_path / "admitted"
    _write_playwright_module(admitted)

    assert _admitted_playwright_module_path(
        os.pathsep.join((str(corrupt), str(admitted)))
    ) == str(admitted.resolve())


def test_browser_court_rejects_invalid_or_empty_module_paths(tmp_path):
    assert _admitted_playwright_module_path("") is None
    assert _admitted_playwright_module_path(str(tmp_path / "missing")) is None
