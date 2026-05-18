"""Tests for the founder status report system.

Covers:
  * `status_report.generate_report()` returns the expected dict shape
    + non-empty HTML and text renderings.
  * `report_sender.send()` POSTs to Resend with the right body when
    RESEND_API_KEY is set (urllib.request mocked).
  * `report_sender.send()` falls back to stdout + reports.log when
    the key is missing.
  * Cadence gate respects `state/last_report_at.txt` — second call
    inside the window is a no-op.
  * Digest mode buffers reports + flushes a combined email when the
    digest window elapses.
  * Generator failures don't crash tick_send_report.

We monkey-patch `urllib.request.urlopen` (the stdlib function the
sender uses) so no live HTTP ever fires.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _force_top_level_agents() -> None:
    """Same trick as test_agents_cloud — drop any cached `agents.*`
    modules so the package resolves to repo-root/agents/ rather than
    app/agents/ (a sibling package on sys.path)."""
    sys.path.insert(0, str(REPO_ROOT))
    for mod_name in list(sys.modules):
        if mod_name == "agents" or mod_name.startswith("agents."):
            del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _isolate_agents_package(tmp_path, monkeypatch):
    """Run for every test in this file. Pins the agents data root onto
    `tmp_path` so state files don't leak between tests."""
    _force_top_level_agents()
    monkeypatch.setenv("ARCHHUB_AGENTS_DATA_ROOT", str(tmp_path / "agents"))
    # Don't probe live HTTP for healthz / CI in any test.
    monkeypatch.delenv("ARCHHUB_GH_REPO", raising=False)
    monkeypatch.setenv("ARCHHUB_BACKEND_HEALTHZ", "http://127.0.0.1:9/healthz")
    monkeypatch.setenv("ARCHHUB_AGENTS_HEALTHZ", "http://127.0.0.1:9/healthz")
    monkeypatch.delenv("ARCHHUB_REPORT_DIGEST_HOURS", raising=False)
    monkeypatch.delenv("ARCHHUB_REPORT_DRY_RUN", raising=False)
    yield


def _make_urlopen_mock(*, status: int = 202, body: str = '{"id":"x"}'):
    """Build a contextmanager-shaped mock matching urllib.request.urlopen.

    `urlopen` returns an object that's a context manager AND has
    .read() / .status. The sender calls both, so we replicate.
    """
    fake_resp = MagicMock()
    fake_resp.status = status
    fake_resp.read.return_value = body.encode("utf-8")
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=fake_resp)


# ---------------------------------------------------------------------------
class TestGenerateReport:
    def test_returns_expected_shape(self):
        from agents.status_report import generate_report
        r = generate_report(cadence_minutes=60)
        assert set(r.keys()) >= {
            "id", "ts", "html", "text", "subject",
            "business", "infrastructure", "agents",
            "cost", "roadmap", "errors", "meta",
        }
        assert r["id"].startswith("rpt_")
        # Timestamp parses as ISO
        datetime.fromisoformat(r["ts"])
        assert isinstance(r["html"], str) and len(r["html"]) > 100
        assert isinstance(r["text"], str) and "ArchHub status" in r["text"]
        assert r["subject"].startswith("[ArchHub]")
        # Sections are dicts (even when unavailable)
        for k in ("business", "infrastructure", "agents",
                  "cost", "roadmap", "errors", "meta"):
            assert isinstance(r[k], dict)
        # Meta carries the cadence
        assert r["meta"]["cadence_minutes"] == 60

    def test_html_is_self_contained(self):
        """No <link>/<style> tags — Gmail strips them. Inline only."""
        from agents.status_report import generate_report
        r = generate_report()
        html = r["html"].lower()
        assert "<link" not in html
        assert "<style" not in html
        # Sanity — headings rendered
        assert "<h1" in html
        assert "business" in html

    def test_subject_under_80_chars(self):
        from agents.status_report import generate_report
        r = generate_report()
        assert len(r["subject"]) <= 80

    def test_section_failure_does_not_crash(self, monkeypatch):
        """A broken section should report `error` rather than raise."""
        from agents import status_report

        def _boom():
            raise RuntimeError("boom")

        monkeypatch.setattr(status_report, "_section_business", _boom)
        r = status_report.generate_report()
        # The safe wrapper turns the exception into a dict carrying
        # the error message.
        assert "error" in r["business"]
        assert "boom" in r["business"]["error"]

    def test_text_contains_section_headers(self):
        from agents.status_report import generate_report
        r = generate_report()
        for header in ("BUSINESS", "INFRASTRUCTURE", "AGENTS",
                       "COST", "ROADMAP", "ERRORS"):
            assert header in r["text"], f"missing {header} in text body"

    def test_agents_section_counts_pending(self, tmp_path, monkeypatch):
        """Drop two .yaml files into a fake tasks dir and confirm the
        pending count surfaces in the agents section."""
        _force_top_level_agents()
        monkeypatch.setenv("ARCHHUB_AGENTS_DATA_ROOT", str(tmp_path / "ag"))
        from agents import status_report
        # Re-bind the module-level paths after the env change.
        d = tmp_path / "ag" / "tasks" / "eng"
        d.mkdir(parents=True)
        (d / "a.yaml").write_text("{}", encoding="utf-8")
        (d / "b.yaml").write_text("{}", encoding="utf-8")
        # Force the module to re-read its DATA_ROOT constants.
        status_report.DATA_ROOT = tmp_path / "ag"
        status_report.TASKS_DIR = tmp_path / "ag" / "tasks"
        status_report.OUTPUTS_DIR = tmp_path / "ag" / "outputs"
        r = status_report.generate_report()
        ag = r["agents"]
        assert ag["pending_total"] == 2
        assert ag["pending_by_dept"]["eng"] == 2

    def test_roadmap_default_source_is_docs_roadmap(self):
        from agents import status_report
        assert status_report.ROADMAP_PATH == REPO_ROOT / "docs" / "ROADMAP.md"

    def test_roadmap_counts_next_7_days_section(self, tmp_path, monkeypatch):
        from agents import status_report

        p = tmp_path / "ROADMAP.md"
        p.write_text(
            "# ArchHub roadmap\n\n"
            "## NEXT 7 DAYS\n\n"
            "- [ ] #P0 First urgent item (eng)\n"
            "- [ ] #P1 Second urgent item (docs)\n\n"
            "## NEXT 30 DAYS\n\n"
            "- [ ] #P2 Later item (ops)\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(status_report, "ROADMAP_PATH", p)

        r = status_report._section_roadmap()

        assert r["available"] is True
        assert r["pending_next_7d"] == 2


# ---------------------------------------------------------------------------
class TestSendLive:
    def test_send_posts_to_resend_when_key_set(self, monkeypatch):
        from agents import report_sender

        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("ARCHHUB_REPORT_RECIPIENT", "x@example.com")

        mock_urlopen = _make_urlopen_mock(status=202)
        monkeypatch.setattr(report_sender.urllib.request,
                            "urlopen", mock_urlopen)

        report = {
            "subject": "[ArchHub] test",
            "html": "<h1>ok</h1>",
            "text": "ok",
        }
        result = report_sender.send(report)
        assert result["ok"] is True
        assert result["status"] == 202

        # urlopen was called with a urllib.Request carrying the right
        # body + headers.
        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == report_sender.RESEND_URL
        assert req.get_header("Authorization") == "Bearer re_test_key"
        body = json.loads(req.data.decode("utf-8"))
        assert body["to"] == ["x@example.com"]
        assert body["subject"] == "[ArchHub] test"
        assert body["html"] == "<h1>ok</h1>"
        assert body["text"] == "ok"
        # `from` defaults to noreply@archhub.io unless overridden
        assert "@" in body["from"]

    def test_send_surfaces_http_error_without_raising(self, monkeypatch):
        import urllib.error
        from agents import report_sender

        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")

        def _raise_http(_req, timeout=None):
            err = urllib.error.HTTPError(
                report_sender.RESEND_URL, 429,
                "Too Many Requests", {}, BytesIO(b'{"error":"rate_limit"}'),
            )
            raise err

        monkeypatch.setattr(report_sender.urllib.request,
                            "urlopen", _raise_http)
        result = report_sender.send({"subject": "s", "html": "h", "text": "t"})
        assert result["ok"] is False
        assert result["status"] == 429

    def test_send_falls_back_to_stdout_when_key_missing(
            self, monkeypatch, capsys):
        from agents import report_sender
        monkeypatch.delenv("RESEND_API_KEY", raising=False)

        # urlopen MUST NOT be called.
        def _boom(*_a, **_kw):
            raise AssertionError("urlopen should not be called without key")

        monkeypatch.setattr(report_sender.urllib.request, "urlopen", _boom)
        result = report_sender.send({"subject": "[ArchHub] dev",
                                     "html": "<p/>", "text": "ok"})
        assert result["ok"] is True
        assert result["mode"] == "stdout"
        captured = capsys.readouterr()
        assert "would send" in captured.out
        # v1.3.1 added SMTP fallback so the unset-reason string changed
        # from "no_resend_api_key" to "no_email_provider_key".
        assert "no_email_provider_key" in captured.out

    def test_send_respects_dry_run_env(self, monkeypatch, capsys):
        from agents import report_sender
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setenv("ARCHHUB_REPORT_DRY_RUN", "1")

        def _boom(*_a, **_kw):
            raise AssertionError("dry-run must not POST")

        monkeypatch.setattr(report_sender.urllib.request, "urlopen", _boom)
        result = report_sender.send({"subject": "x", "html": "y", "text": "z"})
        assert result["ok"] is True
        assert result["mode"] == "stdout"
        assert "dry_run" in capsys.readouterr().out

    def test_send_writes_outcome_log(self, monkeypatch, tmp_path):
        from agents import report_sender
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        monkeypatch.setattr(report_sender.urllib.request,
                            "urlopen", _make_urlopen_mock(status=202))
        report_sender.send({"subject": "[ArchHub] log",
                            "html": "x", "text": "x"})
        log_path = report_sender._reports_log_path()
        assert log_path.exists()
        rows = [json.loads(l)
                for l in log_path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        assert len(rows) >= 1
        assert rows[-1]["subject"] == "[ArchHub] log"
        assert rows[-1]["ok"] is True
        assert rows[-1]["status"] == 202


# ---------------------------------------------------------------------------
class TestCadenceGate:
    def test_should_send_when_no_state(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "60")
        assert report_sender.should_send_now() is True

    def test_should_not_send_inside_window(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "60")
        # Mark a send 1 minute ago
        report_sender._write_last_sent(
            datetime.now(timezone.utc) - timedelta(minutes=1)
        )
        assert report_sender.should_send_now() is False

    def test_should_send_after_window(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "30")
        report_sender._write_last_sent(
            datetime.now(timezone.utc) - timedelta(minutes=45)
        )
        assert report_sender.should_send_now() is True

    def test_interval_zero_disables(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "0")
        assert report_sender.should_send_now() is False
        result = report_sender.tick_send_report(lambda: {})
        assert result["sent"] is False
        assert result["mode"] == "disabled"

    def test_tick_skips_inside_window(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "60")
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
        mock_urlopen = _make_urlopen_mock(status=202)
        monkeypatch.setattr(report_sender.urllib.request,
                            "urlopen", mock_urlopen)
        # First tick fires (no last_report_at exists).
        first = report_sender.tick_send_report(
            lambda: {"subject": "s", "html": "h", "text": "t"}
        )
        assert first["sent"] is True
        # Second tick — same loop iteration, must skip.
        second = report_sender.tick_send_report(
            lambda: {"subject": "s2", "html": "h2", "text": "t2"}
        )
        assert second["sent"] is False
        assert second["mode"] == "skipped"
        # And urlopen was called exactly once.
        assert mock_urlopen.call_count == 1

    def test_tick_handles_generator_exception(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "60")

        def _boom():
            raise RuntimeError("kaboom")

        result = report_sender.tick_send_report(_boom)
        assert result["sent"] is False
        assert result["ok"] is False
        assert "kaboom" in result["reason"]


# ---------------------------------------------------------------------------
class TestDigestMode:
    def test_first_tick_opens_window_and_buffers(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "10")
        monkeypatch.setenv("ARCHHUB_REPORT_DIGEST_HOURS", "1")
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")

        def _boom(*_a, **_kw):
            raise AssertionError("digest first-tick must not POST")

        monkeypatch.setattr(report_sender.urllib.request, "urlopen", _boom)
        result = report_sender.tick_send_report(
            lambda: {"id": "r1", "ts": "t1",
                     "subject": "[ArchHub] first",
                     "text": "first body", "html": "<p>first</p>"}
        )
        assert result["sent"] is False
        assert result["mode"] == "digest_buffer"
        # Buffer file now has one row.
        buf = report_sender._load_digest_buffer()
        assert len(buf) == 1
        assert buf[0]["subject"] == "[ArchHub] first"

    def test_window_elapsed_flushes_combined_email(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "10")
        monkeypatch.setenv("ARCHHUB_REPORT_DIGEST_HOURS", "1")
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")

        # Seed: window opened 2 hours ago, with 2 buffered reports.
        report_sender._set_digest_window_start(
            datetime.now(timezone.utc) - timedelta(hours=2),
        )
        report_sender._append_to_digest({
            "id": "r1", "ts": "t1",
            "subject": "[ArchHub] one",
            "text": "first text",
        })
        report_sender._append_to_digest({
            "id": "r2", "ts": "t2",
            "subject": "[ArchHub] two",
            "text": "second text",
        })

        mock_urlopen = _make_urlopen_mock(status=202)
        monkeypatch.setattr(report_sender.urllib.request,
                            "urlopen", mock_urlopen)

        # Force the cadence gate open.
        report_sender._write_last_sent(
            datetime.now(timezone.utc) - timedelta(minutes=60),
        )
        result = report_sender.tick_send_report(
            lambda: {"id": "r3", "ts": "t3",
                     "subject": "[ArchHub] three",
                     "text": "third text",
                     "html": "<p>three</p>"}
        )
        assert result["sent"] is True
        assert result["mode"] == "digest_flush"
        assert result["ok"] is True

        # One combined POST was issued.
        assert mock_urlopen.call_count == 1
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        # Subject reflects the digest, body contains every buffered ts.
        assert "digest" in body["subject"]
        assert "first text" in body["text"]
        assert "second text" in body["text"]
        # Newest report (added on this tick) appears too.
        assert "third text" in body["text"]

        # Buffer is cleared after a successful flush.
        assert report_sender._load_digest_buffer() == []

    def test_window_not_elapsed_still_buffers(self, monkeypatch):
        from agents import report_sender
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "10")
        monkeypatch.setenv("ARCHHUB_REPORT_DIGEST_HOURS", "2")
        monkeypatch.setenv("RESEND_API_KEY", "re_test_key")

        # Window opened just 5 minutes ago — not ready to flush.
        report_sender._set_digest_window_start(
            datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        report_sender._write_last_sent(
            datetime.now(timezone.utc) - timedelta(minutes=30),
        )

        def _boom(*_a, **_kw):
            raise AssertionError("digest must not flush before window")

        monkeypatch.setattr(report_sender.urllib.request, "urlopen", _boom)
        result = report_sender.tick_send_report(
            lambda: {"subject": "[ArchHub] x", "text": "x", "html": "<p/>"}
        )
        assert result["sent"] is False
        assert result["mode"] == "digest_buffer"


# ---------------------------------------------------------------------------
class TestCloudRunnerWiring:
    """Smoke test: the daemon calls report_sender.tick_send_report
    during its tick_once cycle."""

    def test_tick_once_invokes_report_sender(self, tmp_path, monkeypatch):
        _force_top_level_agents()
        monkeypatch.setenv("ARCHHUB_AGENTS_DATA_ROOT",
                           str(tmp_path / "agents"))
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "60")
        # No key → stdout mode, no HTTP attempted.
        monkeypatch.delenv("RESEND_API_KEY", raising=False)

        from agents import cloud_runner, report_sender

        hb_path = tmp_path / "agents" / "heartbeat.txt"
        daemon = cloud_runner.CloudDaemon(
            cycle_seconds=1,
            heartbeat_path=hb_path,
        )

        # Stub the scheduler so we don't run real LLM calls.
        stub_sched = MagicMock()
        stub_sched.tick.return_value = {"ts": "t", "added": 0, "ran": {}}
        daemon._scheduler = stub_sched

        # Spy on tick_send_report so we can assert it was called and
        # control its return.
        spy = MagicMock(return_value={
            "sent": True, "mode": "stdout", "ok": True, "reason": "ok",
        })
        monkeypatch.setattr(report_sender, "tick_send_report", spy)

        summary = daemon.tick_once()
        assert spy.called
        assert summary.get("report", {}).get("sent") is True

    def test_tick_once_swallows_report_exceptions(self, tmp_path, monkeypatch):
        """A report builder explosion must NOT crash the daemon."""
        _force_top_level_agents()
        monkeypatch.setenv("ARCHHUB_AGENTS_DATA_ROOT",
                           str(tmp_path / "agents"))
        monkeypatch.setenv("ARCHHUB_REPORT_INTERVAL_MIN", "60")
        from agents import cloud_runner, report_sender

        daemon = cloud_runner.CloudDaemon(
            cycle_seconds=1,
            heartbeat_path=tmp_path / "agents" / "heartbeat.txt",
        )
        stub_sched = MagicMock()
        stub_sched.tick.return_value = {"ts": "t", "added": 0, "ran": {}}
        daemon._scheduler = stub_sched

        def _explode(_fn):
            raise RuntimeError("report subsystem broken")

        monkeypatch.setattr(report_sender, "tick_send_report", _explode)
        # Must not raise.
        summary = daemon.tick_once()
        assert "report" not in summary
