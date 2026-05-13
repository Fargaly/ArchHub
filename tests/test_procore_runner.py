"""Procore connector tests.

Covers the static surface of `app/connectors/procore_runner.py`:

  * Module imports cleanly + the base URLs / defaults are sane.
  * Every handler returns a clean {"status": "error", ...} envelope
    when no access token is configured (mocks _load_token to None).
  * Input validation: get_rfi requires rfi_id; create_rfi requires
    subject + question.
  * Tool registry: every procore_* tool is registered with the
    correct family + a handler that actually exists in the runner.
  * ai_behaviour defaults: read tools default to "allow", create_rfi
    defaults to "ask".
  * Always-on filtering: procore tools are exposed even when the
    Procore family isn't in the active set (matches `ai` / `_local`).
  * Successful response shape via a mocked urlopen — no real HTTP.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# ---------------------------------------------------------------------------
class TestModule:
    def test_module_imports(self):
        from connectors import procore_runner
        assert procore_runner.PROD_BASE.startswith("https://api.procore.com")
        assert procore_runner.SANDBOX_BASE.startswith("https://sandbox.procore.com")
        assert procore_runner.DEFAULT_TIMEOUT_SECONDS > 0

    def test_base_url_defaults_to_prod(self):
        from connectors import procore_runner
        import secrets_store
        # _base_url reads procore_sandbox via secrets_store.load_setting;
        # patching that returns the prod URL by default.
        with patch.object(secrets_store, "load_setting", return_value=None):
            assert procore_runner._base_url() == procore_runner.PROD_BASE


# ---------------------------------------------------------------------------
class TestMissingTokenEnvelope:
    """Every handler must fail soft when no access token is set."""

    def _patch_no_token(self):
        from connectors import procore_runner
        return patch.object(procore_runner, "_load_token", return_value=None)

    def test_is_reachable_returns_false(self):
        from connectors import procore_runner
        with self._patch_no_token():
            assert procore_runner.is_reachable() is False

    def test_info_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.info()
        assert r["status"] == "error"
        assert "token" in r["error"].lower()

    def test_list_rfis_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.list_rfis()
        assert r["status"] == "error"
        assert "token" in r["error"].lower()

    def test_get_rfi_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.get_rfi(rfi_id=42)
        assert r["status"] == "error"
        assert "token" in r["error"].lower()

    def test_create_rfi_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.create_rfi(subject="s", question="q")
        assert r["status"] == "error"
        assert "token" in r["error"].lower()

    def test_list_submittals_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.list_submittals()
        assert r["status"] == "error"

    def test_list_change_orders_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.list_change_orders()
        assert r["status"] == "error"

    def test_list_daily_logs_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.list_daily_logs()
        assert r["status"] == "error"

    def test_list_projects_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.list_projects()
        assert r["status"] == "error"

    def test_list_users_errors(self):
        from connectors import procore_runner
        with self._patch_no_token():
            r = procore_runner.list_users()
        assert r["status"] == "error"


# ---------------------------------------------------------------------------
class TestInputValidation:
    """Schema-level validation runs before any HTTP — so we don't need
    to mock the token / network for these."""

    def test_get_rfi_requires_rfi_id(self):
        from connectors import procore_runner
        r = procore_runner.get_rfi(rfi_id=None)
        assert r["status"] == "error"
        assert "rfi_id" in r["error"]

    def test_get_rfi_requires_integer(self):
        from connectors import procore_runner
        r = procore_runner.get_rfi(rfi_id="not-a-number")
        assert r["status"] == "error"
        assert "integer" in r["error"].lower()

    def test_create_rfi_requires_subject(self):
        from connectors import procore_runner
        r = procore_runner.create_rfi(subject="", question="some Q")
        assert r["status"] == "error"
        assert "subject" in r["error"].lower()

    def test_create_rfi_requires_question(self):
        from connectors import procore_runner
        r = procore_runner.create_rfi(subject="some S", question="")
        assert r["status"] == "error"
        assert "question" in r["error"].lower()


# ---------------------------------------------------------------------------
class TestHttpMocking:
    """End-to-end happy path with a mocked urlopen — no real network."""

    def _mock_urlopen(self, payload, status: int = 200):
        """Return a context manager that yields an object with .read()."""
        from unittest.mock import MagicMock
        body = json.dumps(payload).encode("utf-8")
        resp = MagicMock()
        resp.read.return_value = body
        cm = MagicMock()
        cm.__enter__ = lambda self_: resp
        cm.__exit__ = lambda self_, *a: False
        return cm

    def test_list_rfis_happy_path(self):
        from connectors import procore_runner
        api_items = [
            {"id": 1, "number": "RFI-001", "subject": "Wall thickness?",
             "status": "open", "due_date": "2026-06-01",
             "assignees": [{"name": "Jane Doe"}]},
            {"id": 2, "number": "RFI-002", "subject": "Door swing?",
             "status": "closed", "due_date": None,
             "assignees": []},
        ]
        with patch.object(procore_runner, "_load_token", return_value="tok"), \
             patch.object(procore_runner, "_load_company_id", return_value=11), \
             patch.object(procore_runner, "_load_project_id", return_value=22), \
             patch("urllib.request.urlopen",
                    return_value=self._mock_urlopen(api_items)):
            r = procore_runner.list_rfis(limit=10)
        assert r["status"] == "ok"
        assert len(r["items"]) == 2
        assert r["items"][0]["subject"] == "Wall thickness?"
        assert r["items"][0]["assignee"] == "Jane Doe"
        assert r["items"][1]["assignee"] == ""

    def test_get_rfi_happy_path(self):
        from connectors import procore_runner
        api_body = {"id": 99, "subject": "X", "question": {"body": "Why?"}}
        with patch.object(procore_runner, "_load_token", return_value="tok"), \
             patch.object(procore_runner, "_load_company_id", return_value=11), \
             patch.object(procore_runner, "_load_project_id", return_value=22), \
             patch("urllib.request.urlopen",
                    return_value=self._mock_urlopen(api_body)):
            r = procore_runner.get_rfi(rfi_id=99)
        assert r["status"] == "ok"
        assert r["rfi"]["id"] == 99
        assert r["rfi"]["subject"] == "X"

    def test_create_rfi_happy_path(self):
        from connectors import procore_runner
        api_body = {"id": 555, "subject": "New", "question": {"body": "Q?"}}
        with patch.object(procore_runner, "_load_token", return_value="tok"), \
             patch.object(procore_runner, "_load_company_id", return_value=11), \
             patch.object(procore_runner, "_load_project_id", return_value=22), \
             patch("urllib.request.urlopen",
                    return_value=self._mock_urlopen(api_body)):
            r = procore_runner.create_rfi(subject="New", question="Q?")
        assert r["status"] == "ok"
        assert r["id"] == 555


class TestErrorHandling:
    """HTTPError responses should be translated into the standard envelope."""

    def test_401_returns_token_rejected(self):
        from connectors import procore_runner
        import urllib.error
        err = urllib.error.HTTPError(
            url="x", code=401, msg="Unauthorized",
            hdrs=None, fp=io.BytesIO(b"unauthorized"),
        )
        with patch.object(procore_runner, "_load_token", return_value="tok"), \
             patch.object(procore_runner, "_load_company_id", return_value=11), \
             patch.object(procore_runner, "_load_project_id", return_value=22), \
             patch("urllib.request.urlopen", side_effect=err):
            r = procore_runner.list_rfis()
        assert r["status"] == "error"
        assert r["http_status"] == 401
        assert "token" in r["error"].lower()

    def test_403_returns_permission_message(self):
        from connectors import procore_runner
        import urllib.error
        err = urllib.error.HTTPError(
            url="x", code=403, msg="Forbidden",
            hdrs=None, fp=io.BytesIO(b"no access"),
        )
        with patch.object(procore_runner, "_load_token", return_value="tok"), \
             patch.object(procore_runner, "_load_company_id", return_value=11), \
             patch.object(procore_runner, "_load_project_id", return_value=22), \
             patch("urllib.request.urlopen", side_effect=err):
            r = procore_runner.list_rfis()
        assert r["status"] == "error"
        assert r["http_status"] == 403
        assert "permission" in r["error"].lower() or "denied" in r["error"].lower()

    def test_422_returns_validation_message(self):
        from connectors import procore_runner
        import urllib.error
        err = urllib.error.HTTPError(
            url="x", code=422, msg="Unprocessable",
            hdrs=None, fp=io.BytesIO(b'{"errors":["bad subject"]}'),
        )
        with patch.object(procore_runner, "_load_token", return_value="tok"), \
             patch.object(procore_runner, "_load_company_id", return_value=11), \
             patch.object(procore_runner, "_load_project_id", return_value=22), \
             patch("urllib.request.urlopen", side_effect=err):
            r = procore_runner.create_rfi(subject="x", question="y")
        assert r["status"] == "error"
        assert r["http_status"] == 422
        assert "validation" in r["error"].lower()

    def test_network_error_returns_clean_envelope(self):
        from connectors import procore_runner
        import urllib.error
        with patch.object(procore_runner, "_load_token", return_value="tok"), \
             patch.object(procore_runner, "_load_company_id", return_value=11), \
             patch.object(procore_runner, "_load_project_id", return_value=22), \
             patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("connection refused")):
            r = procore_runner.list_rfis()
        assert r["status"] == "error"
        assert "network" in r["error"].lower() or "connection" in r["error"].lower()


# ---------------------------------------------------------------------------
class TestToolRegistry:
    """Every procore_* tool must be registered with family=procore and
    a handler that resolves to a real procore_runner function."""

    EXPECTED = [
        "procore_ping",
        "procore_info",
        "procore_list_rfis",
        "procore_get_rfi",
        "procore_create_rfi",
        "procore_list_submittals",
        "procore_list_change_orders",
        "procore_list_daily_logs",
        "procore_list_projects",
        "procore_list_users",
    ]

    def test_all_procore_tools_registered(self):
        from tool_engine import TOOLS
        names = {t["name"] for t in TOOLS}
        for n in self.EXPECTED:
            assert n in names, f"Missing tool: {n}"

    def test_family_is_procore(self):
        from tool_engine import TOOLS
        for t in TOOLS:
            if t["name"].startswith("procore_"):
                assert t["family"] == "procore", \
                    f"{t['name']} has family={t['family']!r}"

    def test_endpoint_handler_exists(self):
        from tool_engine import TOOLS
        from connectors import procore_runner
        for t in TOOLS:
            if not t["name"].startswith("procore_"):
                continue
            ep = t["endpoint"]
            assert isinstance(ep, tuple) and len(ep) == 2
            family, handler = ep
            assert family == "procore"
            assert hasattr(procore_runner, handler), \
                f"{t['name']} -> procore_runner.{handler} not found"

    def test_create_rfi_has_required_fields(self):
        from tool_engine import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "procore_create_rfi")
        req = tool["input_schema"]["required"]
        assert "subject" in req
        assert "question" in req

    def test_get_rfi_requires_rfi_id_in_schema(self):
        from tool_engine import TOOLS
        tool = next(t for t in TOOLS if t["name"] == "procore_get_rfi")
        assert "rfi_id" in tool["input_schema"]["required"]


# ---------------------------------------------------------------------------
class TestAlwaysOnSchema:
    """Procore tools should be exposed to the LLM even when no procore
    connector is registered in the manager — same as `ai` / `_local`."""

    def test_procore_tools_exposed_with_empty_manager(self):
        from tool_engine import ToolEngine
        mgr = MagicMock()
        mgr.entries = []
        engine = ToolEngine(mgr)
        # Force the outlook probe to report unreachable so it doesn't
        # try to dispatch COM in the test.
        engine._outlook_reachable = False
        names = {t["name"] for t in engine.tool_schemas_for("anthropic")}
        for n in ("procore_ping", "procore_list_rfis", "procore_create_rfi"):
            assert n in names, f"procore tool {n} not in always-on schema"


# ---------------------------------------------------------------------------
class TestAiBehaviourDefaults:
    """Read tools default to 'allow'; create_rfi defaults to 'ask'."""

    def test_list_rfis_defaults_to_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("procore_list_rfis") == "allow"

    def test_get_rfi_defaults_to_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("procore_get_rfi") == "allow"

    def test_info_defaults_to_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("procore_info") == "allow"

    def test_ping_defaults_to_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("procore_ping") == "allow"

    def test_list_submittals_defaults_to_allow(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("procore_list_submittals") == "allow"

    def test_create_rfi_defaults_to_ask(self):
        from ai_behaviour import _default_policy_for
        assert _default_policy_for("procore_create_rfi") == "ask"

    def test_host_display_label(self):
        from ai_behaviour import host_display_label
        assert "Procore" in host_display_label("procore")

    def test_grouping_includes_procore_section_when_registered(self):
        from ai_behaviour import tools_grouped_by_host
        grouped = tools_grouped_by_host()
        assert "procore" in grouped, "procore section should appear in tools_grouped_by_host"
        # Confirm the create_rfi tool inside it carries the 'ask' default.
        create_entry = next(
            (t for t in grouped["procore"]
             if t["name"] == "procore_create_rfi"), None,
        )
        assert create_entry is not None
        assert create_entry["default"] == "ask"
