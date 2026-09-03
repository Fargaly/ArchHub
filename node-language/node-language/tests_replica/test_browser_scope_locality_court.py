"""Real-browser release blocker for local composition entry."""
import json
from pathlib import Path
import shutil

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.browser_scope_locality_court import BrowserScopeLocalityCourt
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import build_universal_application


ROOT = Path(__file__).resolve().parents[1]


def test_scope_entry_stays_inside_the_exact_session_projection(monkeypatch):
    node = shutil.which("node")
    modules = ROOT / "node_modules"
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if (
        not node
        or not modules.joinpath("playwright", "package.json").is_file()
        or not chrome.exists()
    ):
        pytest.skip("local real-browser court runtime is unavailable")
    monkeypatch.setenv("ARCHHUB_NODE_EXECUTABLE", node)
    monkeypatch.setenv("ARCHHUB_NODE_MODULE_PATH", str(modules))
    monkeypatch.setenv("ARCHHUB_CHROME_EXECUTABLE", str(chrome))

    store, registry = build_universal_application(resolve_map_path())
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    try:
        court = BrowserScopeLocalityCourt()
        court.configure(server.url, server.browser_session_token)
        result = court.run()
        if not result.passed:
            pytest.fail(json.dumps({
                "failed": [
                    name for name, passed in result.checks.items() if not passed
                ],
                "details": dict(result.details),
            }, indent=2))
    finally:
        server.close()
