"""Rhino connector tests — v1.1.0.

Static-surface tests for the Rhino MCP bridge. We don't spawn Rhino in
CI, so the network-facing tests stub the transport. The discovery tests
run freely on any OS and verify the search paths exist.

The "bridge down" tests are HERMETIC: they monkeypatch the transport
(``socket.create_connection`` for the TCP probe, ``urllib.request.urlopen``
for the HTTP calls) to force a connection-refused failure. That makes them
deterministic whether or not a real Rhino bridge happens to be listening on
:9879 on this machine — a developer box with Rhino auto-started would
otherwise see the probe succeed and flip these error-path assertions.
"""
from __future__ import annotations

import socket
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


class TestDiscovery:
    def test_payload_addon_path_resolves(self):
        from connectors.rhino_runner import payload_addon_path
        p = payload_addon_path()
        assert p.name == "archhub_mcp.py"
        # The bundled addon must be in payload/rhino/.
        assert "payload" in p.parts
        assert "rhino" in p.parts

    def test_payload_addon_file_exists(self):
        from connectors.rhino_runner import payload_addon_path
        assert payload_addon_path().exists(), "addon source must be in repo"

    def test_detect_version_from_path(self):
        from pathlib import Path as P
        from connectors.rhino_runner import detect_rhino_version
        assert detect_rhino_version(P(r"C:\Program Files\Rhino 8\System\Rhino.exe")) == "8"
        assert detect_rhino_version(P(r"C:\Program Files\Rhino 7\System\Rhino.exe")) == "7"
        assert detect_rhino_version(P("/somewhere/else")) is None
        assert detect_rhino_version(None) is None

    def test_scripts_folder_uses_version(self):
        from connectors.rhino_runner import rhino_scripts_folder
        p = rhino_scripts_folder("8")
        # The version is embedded in the path on every supported OS.
        assert "8" in str(p)


class TestReachability:
    def test_is_reachable_returns_false_when_port_unbound(self, monkeypatch):
        from connectors import rhino_runner
        # 9879 is the production port. On THIS box a real Rhino bridge may be
        # auto-started and listening, so we can't rely on the port being free.
        # Force the TCP connect to fail (connection-refused) so the probe
        # deterministically exercises its fail-closed path regardless.
        def _refuse(*_a, **_k):
            raise ConnectionRefusedError("forced: port unbound")
        monkeypatch.setattr(rhino_runner.socket, "create_connection", _refuse)
        assert rhino_runner.is_reachable(timeout=0.1) is False


class TestPing:
    def test_ping_returns_error_when_bridge_down(self, monkeypatch):
        from connectors import rhino_runner
        # Force the HTTP transport to fail as if no bridge is listening, so
        # this stays deterministic even when Rhino is live on :9879 here.
        # A URLError drives ping()'s "cannot reach Rhino bridge" branch.
        def _refuse(*_a, **_k):
            raise urllib.error.URLError("forced: connection refused")
        monkeypatch.setattr(rhino_runner.urllib.request, "urlopen", _refuse)
        r = rhino_runner.ping(timeout=0.2)
        assert r["status"] == "error"
        assert "rhino" in r["error"].lower() or "bridge" in r["error"].lower() \
            or "9879" in r["error"] or "connect" in r["error"].lower()


class TestExecutePython:
    def test_empty_code_returns_error(self):
        from connectors.rhino_runner import execute_python
        r = execute_python("")
        assert r["status"] == "error"
        assert "code" in r["error"].lower()

    def test_non_empty_code_when_bridge_down_errors_cleanly(self, monkeypatch):
        from connectors import rhino_runner
        # Simulate "bridge not running" by forcing the POST transport to
        # raise connection-refused, deterministic even with Rhino live here.
        def _refuse(*_a, **_k):
            raise ConnectionRefusedError("forced: bridge down")
        monkeypatch.setattr(rhino_runner.urllib.request, "urlopen", _refuse)
        r = rhino_runner.execute_python("result = 1+1", timeout_seconds=1)
        # The HTTP call fails because the bridge isn't running.
        assert r["status"] == "error"


class TestToolRegistry:
    def test_all_rhino_tools_registered(self):
        from tool_engine import TOOLS
        names = {t["name"] for t in TOOLS if t.get("family") == "rhino"}
        for required in ("rhino_ping", "rhino_info",
                          "rhino_execute_python", "rhino_screenshot"):
            assert required in names, f"missing tool: {required}"

    def test_rhino_tools_have_handlers(self):
        from tool_engine import TOOLS
        from connectors import rhino_runner
        for t in TOOLS:
            if t.get("family") != "rhino":
                continue
            handler_name = t["endpoint"][1]
            assert hasattr(rhino_runner, handler_name), \
                f"rhino_runner.{handler_name} missing for {t['name']}"


class TestAiBehaviourDefaults:
    def test_rhino_execute_python_is_ask(self):
        from ai_behaviour import _default_policy_for
        # rhinoscriptsyntax + .NET can mutate the doc — keep "ask".
        assert _default_policy_for("rhino_execute_python") == "ask"

    def test_rhino_info_and_ping_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("rhino_info") == "allow"
        assert _default_policy_for("rhino_ping") == "allow"

    def test_rhino_display_label(self):
        from ai_behaviour import host_display_label
        assert host_display_label("rhino") == "Rhino"

    def test_rhino_appears_in_grouped_output(self):
        from ai_behaviour import tools_grouped_by_host
        g = tools_grouped_by_host()
        # Rhino tools may or may not be active depending on bridge state,
        # but the family key should appear in the grouped output regardless
        # because we register them in TOOLS unconditionally.
        # Verify by collecting all names in the grouping.
        all_names = [t["name"] for tools in g.values() for t in tools]
        # If rhino family is registered we should see its tools.
        assert any("rhino_" in n for n in all_names), \
            "rhino tools should appear in tools_grouped_by_host()"
