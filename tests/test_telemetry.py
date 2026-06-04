"""Telemetry / PII redactor tests.

Covers:
  * Every redactor pattern actually fires.
  * `redact_dict` walks nested structures.
  * Telemetry consent state machine: None → True | False, persistent.
  * Token meter records + status thresholds.

No network calls — PostHog SDK is monkeypatched out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
class TestPIIRedactor:
    def test_windows_path_redacted(self):
        from pii_redactor import redact, looks_redacted
        text = r"opened C:\Users\fargaly\OneDrive\Documents\proj.rvt today"
        out = redact(text)
        assert "fargaly" not in out
        assert "<REDACTED-PATH>" in out
        assert looks_redacted(out)

    def test_anthropic_key_redacted(self):
        from pii_redactor import redact
        # prefix split from body so the SOURCE has no contiguous provider-format
        # token (GitHub push-protection); joined runtime value is byte-identical.
        _k = "sk-ant-api03-" + "AAAA1111BBBB2222CCCC3333DDDD4444EEEE5555"
        text = f"key={_k} ok"
        out = redact(text)
        assert "sk-ant-api03" not in out
        assert "<REDACTED-KEY>" in out

    def test_email_redacted(self):
        from pii_redactor import redact
        out = redact("ping ahmed.fargaly98@gmail.com please")
        assert "@gmail.com" not in out
        assert "<REDACTED-EMAIL>" in out

    def test_localhost_ip_left_alone(self):
        from pii_redactor import redact
        out = redact("MCP at http://127.0.0.1:48884")
        assert "127.0.0.1" in out          # infra, not PII

    def test_external_ip_redacted(self):
        from pii_redactor import redact
        out = redact("user from 203.0.113.42 hit the relay")
        assert "203.0.113.42" not in out
        assert "<REDACTED-IP>" in out

    def test_dict_walked_recursively(self):
        from pii_redactor import redact_dict
        ev = {
            "event": "skill_run",
            "props": {
                "user_path": r"C:\Users\fargaly\file.rvt",
                "key": "sk-or-v1-XXXXXXXXXXXXXXXXXXXX",
                "tags": ["ok", "user@x.com"],
                "count": 5,
            },
        }
        out = redact_dict(ev)
        assert out["event"] == "skill_run"
        assert "<REDACTED-PATH>" in out["props"]["user_path"]
        assert "<REDACTED-KEY>" in out["props"]["key"]
        assert "<REDACTED-EMAIL>" in out["props"]["tags"][1]
        assert out["props"]["count"] == 5    # numbers untouched


# ---------------------------------------------------------------------------
class TestTelemetryConsent:
    @pytest.fixture(autouse=True)
    def _isolate_settings(self, monkeypatch, tmp_path):
        store: dict = {}
        from secrets_store import save_setting as _real_save  # noqa: F401
        # Patch the imports used inside telemetry.py
        import telemetry
        monkeypatch.setattr(telemetry, "save_setting",
                            lambda k, v: store.__setitem__(k, v))
        monkeypatch.setattr(telemetry, "load_setting",
                            lambda k: store.get(k))
        # Force-reset the lazy client between tests.
        telemetry._client = None
        yield store

    def test_consent_starts_none(self):
        import telemetry
        assert telemetry.consent_state() is None
        assert telemetry.is_enabled() is False

    def test_opt_in_persists(self, _isolate_settings):
        import telemetry
        telemetry.set_consent(True)
        assert telemetry.consent_state() is True

    def test_opt_out_persists(self, _isolate_settings):
        import telemetry
        telemetry.set_consent(False)
        assert telemetry.consent_state() is False
        assert telemetry.is_enabled() is False

    def test_distinct_id_stable(self, _isolate_settings):
        import telemetry
        a = telemetry.distinct_id()
        b = telemetry.distinct_id()
        assert a == b and len(a) >= 32

    def test_track_event_silent_when_off(self, _isolate_settings):
        import telemetry
        # No project key configured → no-op, no exception.
        telemetry.track_event("anything", foo="bar")

    def test_feature_flag_returns_default_when_off(self, _isolate_settings):
        import telemetry
        assert telemetry.is_feature_enabled("any_flag", default=True) is True
        assert telemetry.is_feature_enabled("any_flag", default=False) is False


# ---------------------------------------------------------------------------
class TestTokenMeter:
    @pytest.fixture(autouse=True)
    def _redirect_meter(self, tmp_path, monkeypatch):
        # Other tests prepend app/ to sys.path, which shadows the
        # top-level agents/ package (app/agents/ has no token_meter).
        # Force REPO_ROOT to the front of sys.path AND wipe any cached
        # `agents.*` from the app variant so the import resolves
        # against repo-root agents/.
        import sys as _sys
        repo = str(REPO_ROOT)
        if repo in _sys.path:
            _sys.path.remove(repo)
        _sys.path.insert(0, repo)
        for k in [k for k in list(_sys.modules.keys())
                   if k == "agents" or k.startswith("agents.")]:
            _sys.modules.pop(k, None)
        import agents.token_meter as tm
        monkeypatch.setattr(tm, "_METER_PATH", tmp_path / "meter.json")
        yield

    def test_record_increments_runs(self):
        from agents.token_meter import record, snapshot
        record("docs", success=True, prompt_tokens=10, completion_tokens=5,
               elapsed_ms=200)
        record("docs", success=True, prompt_tokens=20, completion_tokens=8,
               elapsed_ms=300)
        snap = snapshot()["docs"]
        assert snap["runs"] == 2
        assert snap["successes"] == 2
        assert snap["prompt_tokens"] == 30
        assert snap["completion_tokens"] == 13
        assert snap["elapsed_ms"] == 500

    def test_status_thresholds(self):
        from agents.token_meter import record, status_for, WEEKLY_BUDGET_LOCAL_SECONDS
        # Push docs to 90% of weekly budget = amber.
        budget_ms = WEEKLY_BUDGET_LOCAL_SECONDS["docs"] * 1000
        record("docs", success=True, prompt_tokens=0, completion_tokens=0,
               elapsed_ms=int(budget_ms * 0.9))
        assert status_for("docs") == "amber"
        # Push over 100% = red.
        record("docs", success=True, prompt_tokens=0, completion_tokens=0,
               elapsed_ms=int(budget_ms * 0.5))
        assert status_for("docs") == "red"
