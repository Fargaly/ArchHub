"""Tests for scripts/reality_smoke.py.

All HTTP calls are mocked — these tests must never hit the real network.
Each check function is exercised against a fake `http_request` to verify
the green / red / skip branches.

Covers the spec's required cases:
  * All-green path
  * Cloud backend down
  * Agents heartbeat stale
  * GH CLI missing
  * LLM key missing
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Load scripts/reality_smoke.py without invoking the CLI / requiring it to
# live on PYTHONPATH. Done once per test module.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_PATH = REPO_ROOT / "scripts" / "reality_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "reality_smoke", SMOKE_PATH,
    )
    assert spec and spec.loader, "reality_smoke.py not loadable"
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclasses.dataclass can resolve the
    # owning module via sys.modules (Python 3.14 requires it).
    sys.modules["reality_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


smoke = _load_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_args(**overrides) -> argparse.Namespace:
    """Build an argparse.Namespace mirroring the CLI's defaults."""
    base = dict(
        cloud_url=smoke.DEFAULT_CLOUD_URL,
        agents_url=smoke.DEFAULT_AGENTS_URL,
        stripe_check=False,
        llm_check=False,
        json=False,
        quiet=False,
        retry=1,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def make_resp(status: int, body=None, headers: dict | None = None):
    """Return a smoke.HttpResp with `body` JSON-encoded (or raw bytes)."""
    if body is None:
        raw = b""
    elif isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = json.dumps(body).encode("utf-8")
    return smoke.HttpResp(status, raw, headers or {})


def patch_http(responses_by_url: dict):
    """Patch smoke.http_request so each URL returns its configured resp.

    `responses_by_url` may map full URLs to HttpResp, or (url_substring -> resp).
    The first substring match wins; useful when query params are appended.
    """
    def fake(url, **kwargs):
        for needle, resp in responses_by_url.items():
            if needle in url:
                return resp
        raise AssertionError(
            f"test asked smoke to hit an un-mocked URL: {url}"
        )
    return mock.patch.object(smoke, "http_request", side_effect=fake)


# ---------------------------------------------------------------------------
# Cloud backend
# ---------------------------------------------------------------------------
class TestCloudHealthz:
    def test_ok_with_status_ok_shape(self):
        with patch_http({
            "/healthz": make_resp(200, {"status": "ok"})
        }):
            r = smoke.check_cloud_healthz(make_args())
        assert r.status == "ok"

    def test_ok_with_legacy_shape(self):
        # /healthz currently returns {"ok": true, "ts": ...}
        with patch_http({
            "/healthz": make_resp(200, {"ok": True, "ts": 123})
        }):
            r = smoke.check_cloud_healthz(make_args())
        assert r.status == "ok"

    def test_fail_on_500(self):
        with patch_http({
            "/healthz": make_resp(500, "boom")
        }):
            r = smoke.check_cloud_healthz(make_args())
        assert r.status == "fail"
        assert "HTTP 500" in r.detail

    def test_fail_on_garbage_body(self):
        with patch_http({
            "/healthz": make_resp(200, "not json")
        }):
            r = smoke.check_cloud_healthz(make_args())
        assert r.status == "fail"


class TestCloudBillingPlans:
    def test_ok_with_list_shape(self):
        with patch_http({
            "/v1/billing/plans": make_resp(200, [
                {"id": "solo"}, {"id": "studio"}, {"id": "firm"},
            ]),
        }):
            r = smoke.check_cloud_billing_plans(make_args())
        assert r.status == "ok"
        assert "3" in r.detail

    def test_ok_with_plans_key(self):
        with patch_http({
            "/v1/billing/plans": make_resp(200, {"plans": [
                {"id": "solo"}, {"id": "studio"}, {"id": "firm"},
            ]}),
        }):
            r = smoke.check_cloud_billing_plans(make_args())
        assert r.status == "ok"

    def test_fail_when_route_missing(self):
        with patch_http({"/v1/billing/plans": make_resp(404)}):
            r = smoke.check_cloud_billing_plans(make_args())
        assert r.status == "fail"
        assert "404" in r.detail or "not registered" in r.detail

    def test_fail_with_too_few_tiers(self):
        with patch_http({
            "/v1/billing/plans": make_resp(200, [{"id": "solo"}]),
        }):
            r = smoke.check_cloud_billing_plans(make_args())
        assert r.status == "fail"


class TestCloudRegister:
    def test_ok_on_202(self):
        with patch_http({
            "/v1/auth/register": make_resp(202, {"status": "accepted"}),
        }):
            r = smoke.check_cloud_register(make_args())
        assert r.status == "ok"

    def test_fail_when_email_send_fails(self):
        with patch_http({
            "/v1/auth/register": make_resp(502,
                                            {"detail": "email_send_failed"}),
        }):
            r = smoke.check_cloud_register(make_args())
        assert r.status == "fail"
        assert "RESEND" in r.detail.upper() or "email" in r.detail.lower()


class TestStripeWebhookRoute:
    def test_ok_on_400_bad_signature(self):
        with patch_http({
            "/v1/webhooks/stripe": make_resp(
                400, {"detail": {"error": "bad_signature: ..."}}
            ),
        }):
            r = smoke.check_cloud_stripe_webhook_route(make_args())
        assert r.status == "ok"

    def test_fail_on_404_route_missing(self):
        with patch_http({
            "/v1/webhooks/stripe": make_resp(404, ""),
        }):
            r = smoke.check_cloud_stripe_webhook_route(make_args())
        assert r.status == "fail"
        assert "404" in r.detail or "not registered" in r.detail


# ---------------------------------------------------------------------------
# Agents 24/7
# ---------------------------------------------------------------------------
class TestAgentsHealthz:
    def test_ok_when_fresh(self):
        with patch_http({
            "/healthz": make_resp(200, {
                "status": "ok", "age_seconds": 30, "last_heartbeat": "x",
                "cycles": 12,
            }),
        }):
            r = smoke.check_agents_healthz(make_args())
        assert r.status == "ok"

    def test_fail_when_stale(self):
        # 10 min old -- past the 5 min threshold per spec.
        with patch_http({
            "/healthz": make_resp(200, {
                "status": "stale", "age_seconds": 600,
                "last_heartbeat": "x", "cycles": 12,
            }),
        }):
            r = smoke.check_agents_healthz(make_args())
        assert r.status == "fail"
        assert "stale" in r.detail.lower()

    def test_fail_when_heartbeat_never_written(self):
        with patch_http({
            "/healthz": make_resp(200, {
                "status": "stale", "age_seconds": None,
            }),
        }):
            r = smoke.check_agents_healthz(make_args())
        assert r.status == "fail"

    def test_fail_when_endpoint_down(self):
        with patch_http({
            "/healthz": make_resp(503),
        }):
            r = smoke.check_agents_healthz(make_args())
        assert r.status == "fail"


class TestAgentsStatus:
    def test_ok(self):
        with patch_http({
            "/status": make_resp(200, {
                "departments": ["finance", "ops", "marketing"],
                "completed_today": 7,
                "pending_tasks": 2,
            }),
        }):
            r = smoke.check_agents_status(make_args())
        assert r.status == "ok"

    def test_fail_empty_departments(self):
        with patch_http({
            "/status": make_resp(200, {"departments": [],
                                        "completed_today": 0}),
        }):
            r = smoke.check_agents_status(make_args())
        assert r.status == "fail"

    def test_fail_zero_completed_today(self):
        with patch_http({
            "/status": make_resp(200, {
                "departments": ["x"], "completed_today": 0,
            }),
        }):
            r = smoke.check_agents_status(make_args())
        assert r.status == "fail"


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
class TestStripeProducts:
    def test_skip_when_flag_off(self):
        r = smoke.check_stripe_products(make_args(stripe_check=False))
        assert r.status == "skip"

    def test_skip_when_no_key(self, monkeypatch):
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        with mock.patch.object(smoke, "_read_stripe_secret_key",
                                return_value=None):
            r = smoke.check_stripe_products(make_args(stripe_check=True))
        assert r.status == "skip"

    def test_ok_with_three_products(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
        with patch_http({
            "api.stripe.com": make_resp(200, {"data": [
                {"id": "prod_solo"},
                {"id": "prod_studio"},
                {"id": "prod_firm"},
            ]}),
        }):
            r = smoke.check_stripe_products(make_args(stripe_check=True))
        assert r.status == "ok"

    def test_fail_with_too_few_products(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
        with patch_http({
            "api.stripe.com": make_resp(200, {"data": [{"id": "p"}]}),
        }):
            r = smoke.check_stripe_products(make_args(stripe_check=True))
        assert r.status == "fail"

    def test_fail_on_401(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
        with patch_http({
            "api.stripe.com": make_resp(401, {"error": "bad key"}),
        }):
            r = smoke.check_stripe_products(make_args(stripe_check=True))
        assert r.status == "fail"


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
class TestGithubCI:
    def test_skip_when_gh_missing(self):
        with mock.patch.object(smoke, "_gh_available", return_value=False), \
             mock.patch.object(smoke, "_github_api_json", return_value=None):
            r = smoke.check_github_ci(make_args())
        assert r.status == "skip"
        assert "github" in r.detail.lower()

    def test_ok_when_public_api_latest_run_green(self):
        with mock.patch.object(smoke, "_gh_available", return_value=False), \
             mock.patch.object(smoke, "_github_api_json", return_value={
                 "workflow_runs": [{
                     "conclusion": "success", "status": "completed",
                     "head_sha": "abc1234567", "created_at": "now",
                 }]
             }):
            r = smoke.check_github_ci(make_args())
        assert r.status == "ok"

    def test_ok_when_latest_run_green(self):
        with mock.patch.object(smoke, "_gh_available", return_value=True), \
             mock.patch.object(smoke, "_gh_json", return_value=[{
                 "conclusion": "success", "status": "completed",
                 "headSha": "abc1234567",
             }]):
            r = smoke.check_github_ci(make_args())
        assert r.status == "ok"

    def test_fail_when_latest_run_failed(self):
        with mock.patch.object(smoke, "_gh_available", return_value=True), \
             mock.patch.object(smoke, "_gh_json", return_value=[{
                 "conclusion": "failure", "status": "completed",
                 "headSha": "abc1234",
             }]):
            r = smoke.check_github_ci(make_args())
        assert r.status == "fail"


class TestGithubRelease:
    def test_skip_when_gh_missing(self):
        with mock.patch.object(smoke, "_gh_available", return_value=False), \
             mock.patch.object(smoke, "_github_api_json", return_value=None):
            r = smoke.check_github_release(make_args())
        assert r.status == "fail"

    def test_ok_when_public_api_tag_matches_version(self):
        local_v = (REPO_ROOT / "VERSION").read_text().strip()
        with mock.patch.object(smoke, "_gh_available", return_value=False), \
             mock.patch.object(smoke, "_github_api_json",
                               return_value={"tag_name": f"v{local_v}"}):
            r = smoke.check_github_release(make_args())
        assert r.status == "ok"

    def test_ok_when_tag_matches_version(self):
        # The repo ships a VERSION file containing the current version;
        # just read it and feed the same value back as the latest release tag.
        local_v = (REPO_ROOT / "VERSION").read_text().strip()
        with mock.patch.object(smoke, "_gh_available", return_value=True), \
             mock.patch.object(smoke, "_gh_json",
                                return_value={"tagName": f"v{local_v}"}):
            r = smoke.check_github_release(make_args())
        assert r.status == "ok"

    def test_fail_when_tag_mismatches(self):
        with mock.patch.object(smoke, "_gh_available", return_value=True), \
             mock.patch.object(smoke, "_gh_json",
                                return_value={"tagName": "v0.0.1"}):
            r = smoke.check_github_release(make_args())
        assert r.status == "fail"


class TestGithubOpenPRs:
    def test_skip_when_gh_missing(self):
        with mock.patch.object(smoke, "_gh_available", return_value=False):
            r = smoke.check_github_open_prs(make_args())
        assert r.status == "skip"

    def test_ok_with_clean_queue(self):
        with mock.patch.object(smoke, "_gh_available", return_value=True), \
             mock.patch.object(smoke, "_gh_json", return_value=[
                 {"number": 1, "statusCheckRollup":
                     [{"conclusion": "SUCCESS"}]},
                 {"number": 2, "statusCheckRollup":
                     [{"conclusion": "SUCCESS"}]},
             ]):
            r = smoke.check_github_open_prs(make_args())
        assert r.status == "ok"
        assert "2 open" in r.detail
        assert "0 with failing" in r.detail

    def test_fail_when_queue_jammed(self):
        with mock.patch.object(smoke, "_gh_available", return_value=True), \
             mock.patch.object(smoke, "_gh_json", return_value=[
                 {"number": 1, "statusCheckRollup":
                     [{"conclusion": "FAILURE"}]},
                 {"number": 2, "statusCheckRollup":
                     [{"conclusion": "FAILURE"}]},
             ]):
            r = smoke.check_github_open_prs(make_args())
        assert r.status == "fail"


# ---------------------------------------------------------------------------
# Local desktop
# ---------------------------------------------------------------------------
class TestLocalBootLog:
    def test_ok_when_recent(self, tmp_path, monkeypatch):
        boot = tmp_path / "boot.log"
        boot.write_text("recent")
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
        r = smoke.check_local_boot_log(make_args())
        assert r.status == "ok"

    def test_fail_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
        r = smoke.check_local_boot_log(make_args())
        assert r.status == "fail"
        assert "not found" in r.detail

    def test_fail_when_too_old(self, tmp_path, monkeypatch):
        boot = tmp_path / "boot.log"
        boot.write_text("old")
        # Backdate beyond 24h.
        past = time.time() - (48 * 3600)
        os.utime(boot, (past, past))
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
        r = smoke.check_local_boot_log(make_args())
        assert r.status == "fail"


class TestLocalStartupSelfTest:
    def test_ok_when_symbol_present(self, tmp_path, monkeypatch):
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text(
            "def _startup_self_test():\n    pass\n", encoding="utf-8"
        )
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
        r = smoke.check_local_startup_self_test(make_args())
        assert r.status == "ok"

    def test_fail_when_symbol_missing(self, tmp_path, monkeypatch):
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text(
            "def something_else():\n    pass\n", encoding="utf-8"
        )
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
        r = smoke.check_local_startup_self_test(make_args())
        assert r.status == "fail"


@pytest.fixture(autouse=True)
def _restore_sys_state():
    """check_local_ai_runner inserts `app_dir` into sys.path. When the
    test monkeypatches REPO_ROOT to tmp_path that becomes tmp_path/app,
    which contains a stub `main.py` from other test classes. The stub
    poisons `sys.modules["main"]` for any subsequent test in the
    session that does `import main` (e.g. AUMID tests in
    test_session_history). Snapshot sys.path + sys.modules and
    restore around every test in this file.
    """
    _path = list(sys.path)
    _mods = set(sys.modules.keys())
    yield
    sys.path[:] = _path
    for k in list(sys.modules):
        if k not in _mods:
            sys.modules.pop(k, None)


class TestLocalAiRunner:
    def test_ok_when_four_providers(self, tmp_path, monkeypatch):
        # Build a fake app/connectors/ai_runner.py exposing list_providers().
        (tmp_path / "app" / "connectors").mkdir(parents=True)
        (tmp_path / "app" / "connectors" / "ai_runner.py").write_text(
            "def list_providers():\n"
            "    return {'status': 'ok', 'providers': {\n"
            "        'openai': {}, 'google': {},\n"
            "        'lmstudio': {}, 'antigravity': {},\n"
            "    }}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
        r = smoke.check_local_ai_runner(make_args())
        assert r.status == "ok"
        assert "4 providers" in r.detail

    def test_fail_when_wrong_count(self, tmp_path, monkeypatch):
        (tmp_path / "app" / "connectors").mkdir(parents=True)
        (tmp_path / "app" / "connectors" / "ai_runner.py").write_text(
            "def list_providers():\n"
            "    return {'status': 'ok', 'providers': {'openai': {}}}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
        r = smoke.check_local_ai_runner(make_args())
        assert r.status == "fail"


# ---------------------------------------------------------------------------
# LLM checks
# ---------------------------------------------------------------------------
class TestLLMAnthropic:
    def test_skip_when_flag_off(self):
        r = smoke.check_llm_anthropic(make_args(llm_check=False))
        assert r.status == "skip"

    def test_skip_when_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        r = smoke.check_llm_anthropic(make_args(llm_check=True))
        assert r.status == "skip"

    def test_ok_on_200(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        with patch_http({
            "api.anthropic.com": make_resp(200, {"id": "msg_x"}),
        }):
            r = smoke.check_llm_anthropic(make_args(llm_check=True))
        assert r.status == "ok"

    def test_fail_on_401(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-bad")
        with patch_http({
            "api.anthropic.com": make_resp(401, {"error": "bad"}),
        }):
            r = smoke.check_llm_anthropic(make_args(llm_check=True))
        assert r.status == "fail"


class TestLLMOpenAI:
    def test_skip_when_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        r = smoke.check_llm_openai(make_args(llm_check=True))
        assert r.status == "skip"

    def test_ok_on_200(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with patch_http({
            "api.openai.com": make_resp(200, {"id": "chatcmpl"}),
        }):
            r = smoke.check_llm_openai(make_args(llm_check=True))
        assert r.status == "ok"


class TestLLMGoogle:
    def test_skip_when_no_key(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        r = smoke.check_llm_google(make_args(llm_check=True))
        assert r.status == "skip"

    def test_ok_on_200(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")
        with patch_http({
            "generativelanguage.googleapis.com": make_resp(
                200, {"candidates": []},
            ),
        }):
            r = smoke.check_llm_google(make_args(llm_check=True))
        assert r.status == "ok"


# ---------------------------------------------------------------------------
# Output + summary integration
# ---------------------------------------------------------------------------
class TestJSONOutput:
    def test_secrets_never_appear_in_json(self, monkeypatch, capsys):
        # Salt the env with realistic-looking secrets and make sure none of
        # them ever appear in the JSON output. Should only see <set>/<unset>.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-LEAK-IF-PRINTED")
        monkeypatch.setenv("OPENAI_API_KEY",    "sk-LEAK-IF-PRINTED")
        monkeypatch.setenv("GOOGLE_API_KEY",    "AIza-LEAK-IF-PRINTED")
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_LEAK-IF-PRINTED")

        # Use a synthetic check list so we don't hit the network.
        fake = smoke.CheckResult("dummy", "Dummy", "ok", "all fine")
        smoke.emit_json([fake], make_args())
        out = capsys.readouterr().out
        for needle in (
            "sk-ant-LEAK", "sk-LEAK", "AIza-LEAK", "sk_live_LEAK",
        ):
            assert needle not in out, \
                f"secret value leaked into JSON output: {needle}"
        assert "<set>" in out


class TestAllGreenPath:
    """End-to-end smoke: mock every check so every category is green and the
    summary line + exit code reflect that."""
    def test_all_green(self, tmp_path, monkeypatch):
        # Fixture filesystem so the local checks pass.
        (tmp_path / "boot.log").write_text("x")
        (tmp_path / "VERSION").write_text("1.2.0\n")
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text(
            "def _startup_self_test(): pass\n", encoding="utf-8",
        )
        (tmp_path / "app" / "connectors").mkdir()
        (tmp_path / "app" / "connectors" / "ai_runner.py").write_text(
            "def list_providers():\n"
            "    return {'status': 'ok', 'providers':"
            "    {'openai': {}, 'google': {}, 'lmstudio': {},"
            "     'antigravity': {}}}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)

        responses = {
            f"{smoke.DEFAULT_CLOUD_URL}/healthz":
                make_resp(200, {"status": "ok"}),
            "/v1/billing/plans":
                make_resp(200, [{"id": "a"}, {"id": "b"}, {"id": "c"}]),
            "/v1/auth/register":
                make_resp(202, {"status": "accepted"}),
            "/v1/webhooks/stripe":
                make_resp(400, {"detail": "bad_signature"}),
            f"{smoke.DEFAULT_AGENTS_URL}/healthz":
                make_resp(200, {"status": "ok", "age_seconds": 5}),
            f"{smoke.DEFAULT_AGENTS_URL}/status":
                make_resp(200, {"departments": ["a", "b"],
                                "completed_today": 5}),
        }
        def fake_github_api(path: str):
            if path.startswith("actions/runs"):
                return {"workflow_runs": [{
                    "conclusion": "success",
                    "status": "completed",
                    "head_sha": "abc1234567",
                }]}
            if path == "releases/latest":
                return {"tag_name": "v1.2.0"}
            return None

        with mock.patch.object(smoke, "http_request",
                                side_effect=lambda url, **k:
                                    next(v for k_, v in responses.items()
                                         if k_ in url)), \
             mock.patch.object(smoke, "_gh_available", return_value=False), \
             mock.patch.object(smoke, "_github_api_json",
                               side_effect=fake_github_api):
            # gh_available=False exercises the public GitHub API fallback.
            results = smoke.run_all(make_args())
        green = [r for r in results if r.status == "ok"]
        failed = [r for r in results if r.status == "fail"]
        assert not failed, [f"{r.name}: {r.detail}" for r in failed]
        assert len(green) >= 6


class TestCloudDownPath:
    """Spec required: cloud backend down → all cloud checks fail."""
    def test_cloud_unreachable(self, monkeypatch):
        import urllib.error as ue

        def unreachable(url, **kwargs):
            raise ue.URLError("network unreachable")

        # http_request catches HTTPError but not URLError — so we
        # patch the underlying _run_check path: a check that crashes
        # gets marked FAIL with the exception detail.
        with mock.patch.object(smoke, "http_request",
                                side_effect=unreachable):
            args = make_args()
            r1 = smoke._run_check(smoke.check_cloud_healthz, args)
            r2 = smoke._run_check(smoke.check_cloud_register, args)
            r3 = smoke._run_check(smoke.check_cloud_stripe_webhook_route,
                                   args)
        assert r1.status == "fail"
        assert r2.status == "fail"
        assert r3.status == "fail"


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------
class TestCLI:
    def test_parses_default_args(self):
        args = smoke.parse_args([])
        assert args.cloud_url == smoke.DEFAULT_CLOUD_URL
        assert args.agents_url == smoke.DEFAULT_AGENTS_URL
        assert args.stripe_check is False
        assert args.llm_check is False
        assert args.json is False
        assert args.quiet is False
        assert args.retry == 1

    def test_parses_overrides(self):
        args = smoke.parse_args([
            "--cloud-url", "https://x.example",
            "--agents-url", "https://y.example",
            "--stripe-check", "--llm-check", "--json", "--quiet",
            "--retry", "3",
        ])
        assert args.cloud_url == "https://x.example"
        assert args.agents_url == "https://y.example"
        assert args.stripe_check is True
        assert args.llm_check is True
        assert args.json is True
        assert args.quiet is True
        assert args.retry == 3

    def test_exit_code_when_any_fail(self, monkeypatch, capsys):
        # Force every check to FAIL via http stubbing — main() should return 1.
        with mock.patch.object(smoke, "run_all",
                                return_value=[
                                    smoke.CheckResult(
                                        "x", "cat", "fail", "bad",
                                    )
                                ]):
            rc = smoke.main(["--json"])
        assert rc == 1

    def test_exit_code_zero_when_only_skip_or_ok(self):
        with mock.patch.object(smoke, "run_all",
                                return_value=[
                                    smoke.CheckResult(
                                        "x", "cat", "ok", "fine",
                                    ),
                                    smoke.CheckResult(
                                        "y", "cat", "skip", "later",
                                    ),
                                ]):
            rc = smoke.main(["--json"])
        assert rc == 0
