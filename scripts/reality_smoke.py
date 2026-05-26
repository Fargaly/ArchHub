#!/usr/bin/env python3
"""ArchHub reality smoke test — probe the deployed system and report.

This is the founder's "is production alive RIGHT NOW?" check. Unlike the
mocked unit tests, every probe in here hits a real surface:

  * cloud_backend on Fly.io (archhub-cloud.fly.dev)
  * agents 24/7 daemon on Fly.io (archhub-agents.fly.dev)
  * Stripe live API (with --stripe-check)
  * GitHub Actions, releases, open PRs
  * local desktop artifacts (boot.log, ai_runner.list_providers)
  * external LLM APIs (with --llm-check)

Outputs a colour-coded checklist. Each line is one of:

  [OK]   fully passes
  [FAIL] failed — reason printed
  [SKIP] check disabled or prerequisite missing

Exit code 0 if every non-skipped check is OK; 1 otherwise.

Designed to run in CI / on Fly — no PyQt6 import, stdlib HTTP only.

Usage:
    python scripts/reality_smoke.py
    python scripts/reality_smoke.py --json
    python scripts/reality_smoke.py --quiet --retry 3
    python scripts/reality_smoke.py --stripe-check --llm-check
    python scripts/reality_smoke.py --cloud-url https://cloud.archhub.io
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_CLOUD_URL  = "https://archhub-cloud.fly.dev"
DEFAULT_AGENTS_URL = "https://archhub-agents.fly.dev"
HTTP_TIMEOUT       = 10        # seconds
RETRY_SLEEP        = 2         # seconds between retries
HEARTBEAT_MAX_AGE  = 5 * 60    # 5 min, per spec
BOOT_LOG_MAX_AGE   = 24 * 3600 # 24h, per spec
USER_AGENT         = "archhub-reality-smoke/1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
STATUS_OK   = "ok"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"


@dataclasses.dataclass
class CheckResult:
    name: str            # short label, e.g. "cloud.healthz"
    category: str        # group header, e.g. "Cloud backend"
    status: str          # ok | fail | skip
    detail: str = ""     # short message describing why
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Stdlib HTTP helpers
# ---------------------------------------------------------------------------
class HttpResp:
    __slots__ = ("status", "body", "headers")

    def __init__(self, status: int, body: bytes, headers: dict):
        self.status = status
        self.body = body
        self.headers = headers

    @property
    def text(self) -> str:
        try:
            return self.body.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def json(self) -> Optional[dict | list]:
        try:
            return json.loads(self.text)
        except Exception:
            return None


def http_request(
    url: str,
    *,
    method: str = "GET",
    data: Optional[bytes] = None,
    headers: Optional[dict] = None,
    timeout: float = HTTP_TIMEOUT,
) -> HttpResp:
    """Stdlib HTTP. Returns HttpResp even for 4xx/5xx (non-2xx don't raise).

    Raises only for network errors / DNS failures / timeouts. The caller
    decides what HTTP statuses mean OK vs FAIL — sometimes a 400 is
    proof a route exists (e.g. the Stripe webhook signature check).
    """
    req = urllib.request.Request(url, method=method, data=data)
    req.add_header("User-Agent", USER_AGENT)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HttpResp(resp.status, resp.read(), dict(resp.headers))
    except urllib.error.HTTPError as ex:
        # 4xx / 5xx — still useful, return the response body if any.
        try:
            body = ex.read()
        except Exception:
            body = b""
        return HttpResp(ex.code, body, dict(ex.headers or {}))


# ---------------------------------------------------------------------------
# Check decorator + dispatcher
# ---------------------------------------------------------------------------
CheckFn = Callable[[argparse.Namespace], CheckResult]


def _run_check(fn: CheckFn, args: argparse.Namespace) -> CheckResult:
    start = time.monotonic()
    last: Optional[CheckResult] = None
    attempts = max(1, int(args.retry))
    for i in range(attempts):
        try:
            res = fn(args)
        except Exception as ex:        # check itself crashed
            res = CheckResult(
                name=getattr(fn, "_check_name", fn.__name__),
                category=getattr(fn, "_check_category", "Unknown"),
                status=STATUS_FAIL,
                detail=f"{type(ex).__name__}: {ex}",
            )
        last = res
        if res.status != STATUS_FAIL:
            break
        if i < attempts - 1:
            time.sleep(RETRY_SLEEP)
    assert last is not None
    last.duration_ms = int((time.monotonic() - start) * 1000)
    return last


def check(name: str, category: str):
    """Decorator stamping name/category onto the function."""
    def deco(fn: CheckFn) -> CheckFn:
        fn._check_name = name           # type: ignore[attr-defined]
        fn._check_category = category   # type: ignore[attr-defined]
        return fn
    return deco


# ---------------------------------------------------------------------------
# CLOUD BACKEND checks
# ---------------------------------------------------------------------------
@check("cloud.healthz", "Cloud backend")
def check_cloud_healthz(args: argparse.Namespace) -> CheckResult:
    """GET /healthz → 200 + status ok. Accepts both {"status":"ok"} and
    the current shape {"ok": true, "ts": ...}."""
    url = f"{args.cloud_url.rstrip('/')}/healthz"
    r = http_request(url)
    if r.status != 200:
        return CheckResult("cloud.healthz", "Cloud backend",
                           STATUS_FAIL, f"HTTP {r.status}")
    js = r.json() or {}
    if isinstance(js, dict) and (
        js.get("status") == "ok" or js.get("ok") is True
    ):
        return CheckResult("cloud.healthz", "Cloud backend", STATUS_OK,
                           f"HTTP 200 · {json.dumps(js)[:80]}")
    return CheckResult("cloud.healthz", "Cloud backend", STATUS_FAIL,
                       f"unexpected body: {r.text[:120]}")


@check("cloud.billing_plans", "Cloud backend")
def check_cloud_billing_plans(args: argparse.Namespace) -> CheckResult:
    """GET /v1/billing/plans → returns 3 tiers."""
    url = f"{args.cloud_url.rstrip('/')}/v1/billing/plans"
    r = http_request(url)
    if r.status == 404:
        return CheckResult("cloud.billing_plans", "Cloud backend",
                           STATUS_FAIL, "route not registered (404)")
    if r.status != 200:
        return CheckResult("cloud.billing_plans", "Cloud backend",
                           STATUS_FAIL, f"HTTP {r.status}")
    js = r.json()
    tiers: list = []
    if isinstance(js, list):
        tiers = js
    elif isinstance(js, dict):
        tiers = js.get("plans") or js.get("tiers") or list(js.values())
    if len(tiers) >= 3:
        return CheckResult("cloud.billing_plans", "Cloud backend",
                           STATUS_OK, f"{len(tiers)} tiers")
    return CheckResult("cloud.billing_plans", "Cloud backend",
                       STATUS_FAIL,
                       f"expected ≥3 tiers, got {len(tiers)}")


@check("cloud.register", "Cloud backend")
def check_cloud_register(args: argparse.Namespace) -> CheckResult:
    """POST /v1/auth/register with throwaway +smoketest email → 202."""
    url = f"{args.cloud_url.rstrip('/')}/v1/auth/register"
    # Salt the email so repeated runs don't reuse the same DB row.
    salt = str(int(time.time()))
    body = json.dumps({
        "email": f"reality+smoketest{salt}@archhub.io",
        # code_challenge must be 20-200 chars per the pydantic model.
        "code_challenge": "smoketest_pkce_challenge_" + salt,
        "redirect": "",
    }).encode("utf-8")
    r = http_request(url, method="POST", data=body,
                     headers={"Content-Type": "application/json"})
    if r.status == 202:
        return CheckResult("cloud.register", "Cloud backend", STATUS_OK,
                           "magic-link issued (202)")
    # 502 email_send_failed means the route works but Resend isn't
    # configured. Surface clearly — still a deployment problem.
    if r.status == 502:
        return CheckResult("cloud.register", "Cloud backend",
                           STATUS_FAIL,
                           "route reachable but email send failed "
                           "(check RESEND_API_KEY)")
    return CheckResult("cloud.register", "Cloud backend", STATUS_FAIL,
                       f"HTTP {r.status}: {r.text[:120]}")


@check("cloud.stripe_webhook_route", "Cloud backend")
def check_cloud_stripe_webhook_route(args: argparse.Namespace) -> CheckResult:
    """POST empty body to /v1/webhooks/stripe → expect 400 bad_signature
    (proves the route exists + signature verification is wired)."""
    url = f"{args.cloud_url.rstrip('/')}/v1/webhooks/stripe"
    r = http_request(url, method="POST", data=b"",
                     headers={"Content-Type": "application/json"})
    if r.status == 400:
        # Match either {"detail": {"error":"bad_signature..."}} or string
        text = r.text.lower()
        if "signature" in text or "stripe" in text:
            return CheckResult("cloud.stripe_webhook_route",
                               "Cloud backend", STATUS_OK,
                               "400 bad_signature as expected")
        return CheckResult("cloud.stripe_webhook_route",
                           "Cloud backend", STATUS_OK,
                           f"400 ({r.text[:80]})")
    if r.status == 404:
        return CheckResult("cloud.stripe_webhook_route",
                           "Cloud backend", STATUS_FAIL,
                           "route not registered (404)")
    return CheckResult("cloud.stripe_webhook_route", "Cloud backend",
                       STATUS_FAIL,
                       f"unexpected HTTP {r.status}: {r.text[:120]}")


# ---------------------------------------------------------------------------
# AGENTS 24/7 checks
# ---------------------------------------------------------------------------
@check("agents.healthz", "Agents 24/7")
def check_agents_healthz(args: argparse.Namespace) -> CheckResult:
    """GET /healthz → 200 + last_heartbeat within 5 min."""
    url = f"{args.agents_url.rstrip('/')}/healthz"
    r = http_request(url)
    if r.status != 200:
        return CheckResult("agents.healthz", "Agents 24/7", STATUS_FAIL,
                           f"HTTP {r.status}")
    js = r.json() or {}
    if not isinstance(js, dict):
        return CheckResult("agents.healthz", "Agents 24/7", STATUS_FAIL,
                           f"unexpected body: {r.text[:120]}")
    age = js.get("age_seconds")
    if age is None:
        return CheckResult("agents.healthz", "Agents 24/7", STATUS_FAIL,
                           "no heartbeat written yet")
    if int(age) > HEARTBEAT_MAX_AGE:
        mins = int(age) // 60
        return CheckResult("agents.healthz", "Agents 24/7", STATUS_FAIL,
                           f"heartbeat stale ({mins} min old)")
    return CheckResult("agents.healthz", "Agents 24/7", STATUS_OK,
                       f"heartbeat {age}s old")


@check("agents.status", "Agents 24/7")
def check_agents_status(args: argparse.Namespace) -> CheckResult:
    """GET /status → returns dept list + non-zero completed-today."""
    url = f"{args.agents_url.rstrip('/')}/status"
    r = http_request(url)
    if r.status != 200:
        return CheckResult("agents.status", "Agents 24/7", STATUS_FAIL,
                           f"HTTP {r.status}")
    js = r.json()
    if not isinstance(js, dict):
        return CheckResult("agents.status", "Agents 24/7", STATUS_FAIL,
                           f"unexpected body: {r.text[:120]}")
    depts = js.get("departments") or []
    completed = js.get("completed_today")
    if not depts:
        return CheckResult("agents.status", "Agents 24/7", STATUS_FAIL,
                           "department list empty")
    if not completed or int(completed) <= 0:
        return CheckResult("agents.status", "Agents 24/7", STATUS_FAIL,
                           f"completed_today={completed} "
                           f"(expected non-zero)")
    return CheckResult("agents.status", "Agents 24/7", STATUS_OK,
                       f"{len(depts)} depts · {completed} done today")


# ---------------------------------------------------------------------------
# STRIPE check
# ---------------------------------------------------------------------------
def _read_stripe_secret_key() -> Optional[str]:
    """Pull the Stripe secret key from env, .env, or cloud_backend/config.

    Searches in priority order:
      1. STRIPE_SECRET_KEY env var
      2. cloud_backend/.env (KEY=VALUE lines)
    Never reads from production secrets — only what the local dev box has.
    """
    v = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if v:
        return v
    env_file = REPO_ROOT / "cloud_backend" / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.startswith("STRIPE_SECRET_KEY"):
                    _, _, rhs = line.partition("=")
                    rhs = rhs.strip().strip('"').strip("'")
                    if rhs:
                        return rhs
        except OSError:
            pass
    return None


def _read_stripe_publishable_key() -> Optional[str]:
    """For the env-sanity check. Optional; never required."""
    v = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()
    if v:
        return v
    env_file = REPO_ROOT / "cloud_backend" / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.startswith("STRIPE_PUBLISHABLE_KEY"):
                    _, _, rhs = line.partition("=")
                    rhs = rhs.strip().strip('"').strip("'")
                    if rhs:
                        return rhs
        except OSError:
            pass
    return None


@check("stripe.products", "Stripe")
def check_stripe_products(args: argparse.Namespace) -> CheckResult:
    """Hit api.stripe.com/v1/products with the secret key, count active
    products. Requires --stripe-check + STRIPE_SECRET_KEY set."""
    if not args.stripe_check:
        return CheckResult("stripe.products", "Stripe", STATUS_SKIP,
                           "pass --stripe-check to enable")
    key = _read_stripe_secret_key()
    if not key:
        return CheckResult("stripe.products", "Stripe", STATUS_SKIP,
                           "no STRIPE_SECRET_KEY in env or "
                           "cloud_backend/.env")
    url = "https://api.stripe.com/v1/products?active=true&limit=10"
    r = http_request(url, headers={"Authorization": f"Bearer {key}"})
    if r.status == 401:
        return CheckResult("stripe.products", "Stripe", STATUS_FAIL,
                           "Stripe rejected the key (401)")
    if r.status != 200:
        return CheckResult("stripe.products", "Stripe", STATUS_FAIL,
                           f"HTTP {r.status}: {r.text[:120]}")
    js = r.json() or {}
    data = js.get("data") if isinstance(js, dict) else None
    if not data:
        return CheckResult("stripe.products", "Stripe", STATUS_FAIL,
                           "no active products")
    n = len(data)
    if n < 3:
        return CheckResult("stripe.products", "Stripe", STATUS_FAIL,
                           f"{n} active products (expected ≥3 for "
                           f"Solo/Studio/Firm)")
    return CheckResult("stripe.products", "Stripe", STATUS_OK,
                       f"{n} active products")


# ---------------------------------------------------------------------------
# GITHUB checks
# ---------------------------------------------------------------------------
def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _gh_json(*args: str) -> Optional[list | dict]:
    """Run `gh ... --json ...` and return parsed JSON, or None on error."""
    if not _gh_available():
        return None
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired,
            json.JSONDecodeError):
        return None


def _github_repo() -> str:
    return os.environ.get("ARCHHUB_GH_REPO", "Fargaly/ArchHub")


def _github_api_json(path: str) -> Optional[list | dict]:
    """Fetch public GitHub API JSON.

    Used as a fallback when the GitHub CLI is missing or unauthenticated.
    Public repositories should not require local `gh auth login` just to
    answer release/CI smoke checks.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{_github_repo()}/{path.lstrip('/')}"
    try:
        resp = http_request(url, headers=headers, timeout=15)
    except Exception:
        return None
    if resp.status != 200:
        return None
    return resp.json()


@check("github.ci_latest", "GitHub")
def check_github_ci(args: argparse.Namespace) -> CheckResult:
    """Latest CI run on main: green? Falls back gracefully if gh is missing."""
    data = None
    if _gh_available():
        data = _gh_json(
            "run", "list", "--workflow=test.yml", "--branch=main",
            "--limit=1", "--json", "conclusion,status,headSha,createdAt",
        )
    if not data:
        api = _github_api_json("actions/runs?per_page=1")
        runs = api.get("workflow_runs") if isinstance(api, dict) else None
        if isinstance(runs, list):
            data = [{
                "conclusion": r.get("conclusion"),
                "status": r.get("status"),
                "headSha": r.get("head_sha"),
                "createdAt": r.get("created_at"),
            } for r in runs]
    if not data:
        return CheckResult("github.ci_latest", "GitHub", STATUS_SKIP,
                           "GitHub returned no data (auth / no runs?)")
    if not isinstance(data, list) or not data:
        return CheckResult("github.ci_latest", "GitHub", STATUS_FAIL,
                           "no CI runs found")
    run = data[0]
    conc = run.get("conclusion")
    stat = run.get("status")
    if conc == "success":
        return CheckResult("github.ci_latest", "GitHub", STATUS_OK,
                           f"green ({run.get('headSha','')[:7]})")
    if stat in ("in_progress", "queued") and not conc:
        return CheckResult("github.ci_latest", "GitHub", STATUS_OK,
                           f"in progress ({run.get('headSha','')[:7]})")
    return CheckResult("github.ci_latest", "GitHub", STATUS_FAIL,
                       f"latest CI conclusion={conc} status={stat}")


@check("github.release_matches_version", "GitHub")
def check_github_release(args: argparse.Namespace) -> CheckResult:
    """Latest release tag matches VERSION file?"""
    version_file = REPO_ROOT / "VERSION"
    if not version_file.exists():
        return CheckResult("github.release_matches_version", "GitHub",
                           STATUS_FAIL, "VERSION file missing")
    local_v = version_file.read_text(encoding="utf-8").strip().lstrip("vV")
    data = _gh_json("release", "view", "--json", "tagName")
    if not data:
        data = _github_api_json("releases/latest")
    if not data or not isinstance(data, dict):
        return CheckResult("github.release_matches_version", "GitHub",
                           STATUS_FAIL, "no published release found")
    tag = (data.get("tagName") or data.get("tag_name") or "").lstrip("vV")
    if tag == local_v:
        return CheckResult("github.release_matches_version", "GitHub",
                           STATUS_OK,
                           f"v{local_v} matches latest release")
    return CheckResult("github.release_matches_version", "GitHub",
                       STATUS_FAIL,
                       f"VERSION={local_v} but latest tag={tag or '(none)'}")


@check("github.open_prs", "GitHub")
def check_github_open_prs(args: argparse.Namespace) -> CheckResult:
    """Open PR count + how many failing CI."""
    if not _gh_available():
        return CheckResult("github.open_prs", "GitHub", STATUS_SKIP,
                           "gh CLI not installed")
    data = _gh_json("pr", "list", "--state=open", "--limit=50",
                    "--json", "number,statusCheckRollup")
    if data is None:
        return CheckResult("github.open_prs", "GitHub", STATUS_SKIP,
                           "gh returned no data (auth?)")
    if not isinstance(data, list):
        return CheckResult("github.open_prs", "GitHub", STATUS_FAIL,
                           "unexpected gh output shape")
    total = len(data)
    failing = 0
    for pr in data:
        checks = pr.get("statusCheckRollup") or []
        # Each check is {state, status, conclusion, ...}; conclusion=FAILURE
        # indicates failing CI.
        for c in checks:
            concl = (c.get("conclusion") or "").upper()
            if concl in ("FAILURE", "TIMED_OUT", "CANCELLED"):
                failing += 1
                break
    detail = f"{total} open · {failing} with failing CI"
    # This is informational only — not a hard failure unless every open
    # PR has failing CI (then the queue is jammed).
    if total > 0 and failing == total:
        return CheckResult("github.open_prs", "GitHub", STATUS_FAIL,
                           detail + " (queue jammed)")
    return CheckResult("github.open_prs", "GitHub", STATUS_OK, detail)


# ---------------------------------------------------------------------------
# LOCAL DESKTOP checks
# ---------------------------------------------------------------------------
def _resolve_boot_log() -> "Path | None":
    """AgDR-0047 §B1 fallback chain. Writer (app/main.py) emits to
    %LOCALAPPDATA%/ArchHub/logs/boot.log; reader also tolerates the
    legacy REPO_ROOT/boot.log so a fresh install + tests that
    monkey-patch REPO_ROOT both work. Pick the candidate with the
    most recent mtime among those that exist.
    """
    import os as _os
    candidates = [
        Path(_os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "ArchHub" / "logs" / "boot.log",
        REPO_ROOT / "boot.log",
    ]
    existing = [c for c in candidates if c.exists()]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


@check("local.boot_log", "Local desktop")
def check_local_boot_log(args: argparse.Namespace) -> CheckResult:
    """boot.log exists + last entry within 24h?"""
    boot = _resolve_boot_log()
    if boot is None:
        return CheckResult("local.boot_log", "Local desktop",
                           STATUS_FAIL, "boot.log not found")
    try:
        mtime = boot.stat().st_mtime
    except OSError as ex:
        return CheckResult("local.boot_log", "Local desktop",
                           STATUS_FAIL, f"stat failed: {ex}")
    age = time.time() - mtime
    age_h = age / 3600
    if age > BOOT_LOG_MAX_AGE:
        return CheckResult("local.boot_log", "Local desktop",
                           STATUS_FAIL,
                           f"last write {age_h:.1f}h ago "
                           f"(threshold 24h)")
    return CheckResult("local.boot_log", "Local desktop", STATUS_OK,
                       f"last write {age_h:.1f}h ago")


@check("local.startup_self_test_importable", "Local desktop")
def check_local_startup_self_test(args: argparse.Namespace) -> CheckResult:
    """app/main.py _startup_self_test callable (smoke-import only)?

    We DO NOT execute it — running it inside a PyQt6-free context would
    try to load brokers that require a desktop. We just confirm the
    symbol exists by parsing the file. Importing app.main pulls PyQt6.
    """
    main_py = REPO_ROOT / "app" / "main.py"
    if not main_py.exists():
        return CheckResult("local.startup_self_test_importable",
                           "Local desktop", STATUS_FAIL,
                           "app/main.py not found")
    try:
        source = main_py.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        return CheckResult("local.startup_self_test_importable",
                           "Local desktop", STATUS_FAIL,
                           f"read failed: {ex}")
    if "def _startup_self_test" not in source:
        return CheckResult("local.startup_self_test_importable",
                           "Local desktop", STATUS_FAIL,
                           "_startup_self_test function missing")
    return CheckResult("local.startup_self_test_importable",
                       "Local desktop", STATUS_OK,
                       "symbol present in app/main.py")


@check("local.ai_runner_providers", "Local desktop")
def check_local_ai_runner(args: argparse.Namespace) -> CheckResult:
    """app/connectors/ai_runner.list_providers() returns 4 entries?

    Loads ai_runner via importlib (no PyQt6 in the import path). The
    function returns {"status":"ok", "providers": {...}}; we want 4
    keys: openai, google, lmstudio, antigravity.
    """
    mod_path = REPO_ROOT / "app" / "connectors" / "ai_runner.py"
    if not mod_path.exists():
        return CheckResult("local.ai_runner_providers", "Local desktop",
                           STATUS_FAIL,
                           "app/connectors/ai_runner.py not found")
    # Add app/ to sys.path so `from secrets_store import …` resolves.
    app_dir = str(REPO_ROOT / "app")
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        spec = importlib.util.spec_from_file_location(
            "_reality_ai_runner", mod_path,
        )
        if spec is None or spec.loader is None:
            return CheckResult("local.ai_runner_providers",
                               "Local desktop", STATUS_FAIL,
                               "spec_from_file_location returned None")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.list_providers()
    except Exception as ex:
        return CheckResult("local.ai_runner_providers", "Local desktop",
                           STATUS_FAIL,
                           f"{type(ex).__name__}: {ex}")
    finally:
        # Best-effort cleanup of the loaded stub module so the next
        # check sees a fresh import surface.
        sys.modules.pop("_reality_ai_runner", None)
    providers = result.get("providers") if isinstance(result, dict) else None
    if not isinstance(providers, dict):
        return CheckResult("local.ai_runner_providers", "Local desktop",
                           STATUS_FAIL,
                           "list_providers() shape unexpected")
    n = len(providers)
    if n != 4:
        return CheckResult("local.ai_runner_providers", "Local desktop",
                           STATUS_FAIL,
                           f"{n} providers (expected 4): "
                           f"{sorted(providers)}")
    return CheckResult("local.ai_runner_providers", "Local desktop",
                       STATUS_OK,
                       f"4 providers: {sorted(providers)}")


# ---------------------------------------------------------------------------
# EXTERNAL LLM checks (opt-in)
# ---------------------------------------------------------------------------
@check("llm.anthropic", "External LLMs")
def check_llm_anthropic(args: argparse.Namespace) -> CheckResult:
    """Tiny request to Anthropic /v1/messages with max_tokens=1."""
    if not args.llm_check:
        return CheckResult("llm.anthropic", "External LLMs", STATUS_SKIP,
                           "pass --llm-check to enable")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return CheckResult("llm.anthropic", "External LLMs", STATUS_SKIP,
                           "no ANTHROPIC_API_KEY env var")
    body = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode("utf-8")
    r = http_request(
        "https://api.anthropic.com/v1/messages",
        method="POST", data=body, timeout=15,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    if r.status == 200:
        return CheckResult("llm.anthropic", "External LLMs", STATUS_OK,
                           "1-token request returned 200")
    return CheckResult("llm.anthropic", "External LLMs", STATUS_FAIL,
                       f"HTTP {r.status}: {r.text[:120]}")


@check("llm.openai", "External LLMs")
def check_llm_openai(args: argparse.Namespace) -> CheckResult:
    """Tiny request to OpenAI /v1/chat/completions."""
    if not args.llm_check:
        return CheckResult("llm.openai", "External LLMs", STATUS_SKIP,
                           "pass --llm-check to enable")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return CheckResult("llm.openai", "External LLMs", STATUS_SKIP,
                           "no OPENAI_API_KEY env var")
    body = json.dumps({
        "model": "gpt-4o-mini",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode("utf-8")
    r = http_request(
        "https://api.openai.com/v1/chat/completions",
        method="POST", data=body, timeout=15,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    if r.status == 200:
        return CheckResult("llm.openai", "External LLMs", STATUS_OK,
                           "1-token request returned 200")
    return CheckResult("llm.openai", "External LLMs", STATUS_FAIL,
                       f"HTTP {r.status}: {r.text[:120]}")


@check("llm.google", "External LLMs")
def check_llm_google(args: argparse.Namespace) -> CheckResult:
    """Tiny request to Google Generative Language API."""
    if not args.llm_check:
        return CheckResult("llm.google", "External LLMs", STATUS_SKIP,
                           "pass --llm-check to enable")
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        return CheckResult("llm.google", "External LLMs", STATUS_SKIP,
                           "no GOOGLE_API_KEY env var")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.5-flash:generateContent?key={key}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": "hi"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }).encode("utf-8")
    r = http_request(
        url, method="POST", data=body, timeout=15,
        headers={"Content-Type": "application/json"},
    )
    if r.status == 200:
        return CheckResult("llm.google", "External LLMs", STATUS_OK,
                           "1-token request returned 200")
    return CheckResult("llm.google", "External LLMs", STATUS_FAIL,
                       f"HTTP {r.status}: {r.text[:120]}")


# ---------------------------------------------------------------------------
# Registry — order = print order
# ---------------------------------------------------------------------------
CHECKS: list[CheckFn] = [
    check_cloud_healthz,
    check_cloud_billing_plans,
    check_cloud_register,
    check_cloud_stripe_webhook_route,

    check_agents_healthz,
    check_agents_status,

    check_stripe_products,

    check_github_ci,
    check_github_release,
    check_github_open_prs,

    check_local_boot_log,
    check_local_startup_self_test,
    check_local_ai_runner,

    check_llm_anthropic,
    check_llm_openai,
    check_llm_google,
]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
_ANSI = {
    "ok":    "\033[92m",   # green
    "fail":  "\033[91m",   # red
    "skip":  "\033[90m",   # grey
    "head":  "\033[96m",   # cyan
    "reset": "\033[0m",
}


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def _colorize(status: str, label: str) -> str:
    if not _supports_color():
        return label
    return f"{_ANSI.get(status, '')}{label}{_ANSI['reset']}"


def _format_line(r: CheckResult) -> str:
    tag = {
        STATUS_OK:   "[OK]  ",
        STATUS_FAIL: "[FAIL]",
        STATUS_SKIP: "[SKIP]",
    }[r.status]
    tag_c = _colorize(r.status, tag)
    detail = f" — {r.detail}" if r.detail else ""
    return f"  {tag_c}  {r.name:<38} {detail}"


def _redact(value: Optional[str]) -> str:
    """Replace any secret-like value with <set>/<unset> per spec."""
    return "<set>" if value else "<unset>"


def emit_human(results: list[CheckResult], args: argparse.Namespace) -> None:
    """Print the per-category checklist + summary."""
    categories: dict[str, list[CheckResult]] = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    if not args.quiet:
        head = _colorize("head", "ArchHub reality smoke")
        print(f"\n{head}")
        print(f"  cloud:  {args.cloud_url}")
        print(f"  agents: {args.agents_url}")
        print(f"  flags:  stripe={args.stripe_check} "
              f"llm={args.llm_check} retry={args.retry}")
        print("")

    for cat, items in categories.items():
        # quiet mode: skip whole category if everything is OK/SKIP
        if args.quiet and not any(r.status == STATUS_FAIL for r in items):
            continue
        if not args.quiet:
            print(f"  {_colorize('head', cat)}")
        for r in items:
            if args.quiet and r.status != STATUS_FAIL:
                continue
            print(_format_line(r))
        if not args.quiet:
            print("")

    green   = sum(1 for r in results if r.status == STATUS_OK)
    failed  = sum(1 for r in results if r.status == STATUS_FAIL)
    skipped = sum(1 for r in results if r.status == STATUS_SKIP)
    total   = green + failed   # "non-skipped checks"
    summary = (f"Reality check: {green}/{total} green · "
               f"{failed} failed · {skipped} skipped")
    color = STATUS_OK if failed == 0 else STATUS_FAIL
    print(_colorize(color, summary))


def emit_json(results: list[CheckResult], args: argparse.Namespace) -> None:
    """JSON shape: stable for machine consumers. NEVER prints secret values."""
    green   = sum(1 for r in results if r.status == STATUS_OK)
    failed  = sum(1 for r in results if r.status == STATUS_FAIL)
    skipped = sum(1 for r in results if r.status == STATUS_SKIP)
    payload = {
        "schema": "archhub.reality_smoke/1",
        "generated_at": datetime.now(timezone.utc)
                                .isoformat(timespec="seconds"),
        "cloud_url":  args.cloud_url,
        "agents_url": args.agents_url,
        "flags": {
            "stripe_check": args.stripe_check,
            "llm_check":    args.llm_check,
            "retry":        args.retry,
        },
        "env": {
            # Booleans only — never the values themselves.
            "STRIPE_PUBLISHABLE_KEY": _redact(_read_stripe_publishable_key()),
            "STRIPE_SECRET_KEY":      _redact(_read_stripe_secret_key()),
            "ANTHROPIC_API_KEY":      _redact(os.environ.get("ANTHROPIC_API_KEY")),
            "OPENAI_API_KEY":         _redact(os.environ.get("OPENAI_API_KEY")),
            "GOOGLE_API_KEY":         _redact(os.environ.get("GOOGLE_API_KEY")),
        },
        "summary": {
            "total_non_skipped": green + failed,
            "green":             green,
            "failed":            failed,
            "skipped":           skipped,
            "exit_code":         0 if failed == 0 else 1,
        },
        "checks": [r.to_dict() for r in results],
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="reality_smoke",
        description="ArchHub end-to-end reality smoke test.",
    )
    p.add_argument("--cloud-url",  default=DEFAULT_CLOUD_URL,
                   help=f"Cloud backend base URL (default {DEFAULT_CLOUD_URL})")
    p.add_argument("--agents-url", default=DEFAULT_AGENTS_URL,
                   help=f"Agents 24/7 base URL (default {DEFAULT_AGENTS_URL})")
    p.add_argument("--stripe-check", action="store_true",
                   help="Exercise live Stripe API (uses STRIPE_SECRET_KEY)")
    p.add_argument("--llm-check", action="store_true",
                   help="Exercise live LLM APIs (Anthropic/OpenAI/Google) — costs cents")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of human text")
    p.add_argument("--quiet", action="store_true",
                   help="Only print failures + summary")
    p.add_argument("--retry", type=int, default=1,
                   help="Retry each check N times with 2s sleep (default 1)")
    return p.parse_args(argv)


def run_all(args: argparse.Namespace) -> list[CheckResult]:
    return [_run_check(fn, args) for fn in CHECKS]


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    results = run_all(args)
    if args.json:
        emit_json(results, args)
    else:
        emit_human(results, args)
    failed = sum(1 for r in results if r.status == STATUS_FAIL)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
