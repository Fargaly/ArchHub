"""AgDR-0034 — maintenance audit detector tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import maintenance_audit as ma  # noqa: E402


def _audit_for(tmp_path, monkeypatch, py: str = "", jsx: str = ""):
    """Point the audit at a throwaway app/ tree."""
    app = tmp_path / "app"
    (app / "web_ui").mkdir(parents=True)
    if py:
        (app / "mod.py").write_text(py, encoding="utf-8")
    if jsx:
        (app / "web_ui" / "studio-lm.jsx").write_text(jsx, encoding="utf-8")
    monkeypatch.setattr(ma, "REPO", tmp_path)
    monkeypatch.setattr(ma, "APP", app)
    return ma.run_audit()


# ─── Python detectors ───────────────────────────────────────────────


def test_detects_bare_except(tmp_path, monkeypatch):
    audit = _audit_for(tmp_path, monkeypatch,
                       py="def f():\n    try:\n        x()\n    except:\n        pass\n")
    classes = {f.cls for f in audit.findings}
    assert "bare-except" in classes


def test_bare_except_not_cleared_by_marker(tmp_path, monkeypatch):
    """A truly bare `except:` (catches KeyboardInterrupt / SystemExit) is
    never a legitimate fail-soft — the marker must NOT clear the HIGH
    bare-except finding."""
    py = ("def f():\n"
          "    try:\n"
          "        x()\n"
          "    except:  # audit: deliberate-fail-soft\n"
          "        pass\n")
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert any(f.cls == "bare-except" for f in audit.findings)


def test_detects_except_pass(tmp_path, monkeypatch):
    """An undocumented one-line `except Exception: pass` is a silent
    swallow and must flag MEDIUM."""
    py = ("def f():\n"
          "    try:\n"
          "        self.sig.emit()\n"
          "    except Exception: pass\n")
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert any(f.cls == "except-pass" for f in audit.findings)


def test_except_pass_cleared_by_trailing_marker(tmp_path, monkeypatch):
    """The `# audit: deliberate-fail-soft` marker TRAILING the except line
    certifies a documented fail-soft — mirrors the success-mask marker
    convention — and clears the except-pass finding."""
    py = ("def f():\n"
          "    try:\n"
          "        self.sig.emit()\n"
          "    except Exception: pass  # audit: deliberate-fail-soft — "
          "fire-and-forget UI nudge\n")
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert not any(f.cls == "except-pass" for f in audit.findings)


def test_except_pass_cleared_by_marker_on_line_above(tmp_path, monkeypatch):
    """The marker on the comment line directly ABOVE the except also
    certifies the swallow (the natural spot for a one-line rationale)."""
    py = ("def f():\n"
          "    try:\n"
          "        self.sig.emit()\n"
          "    # audit: deliberate-fail-soft — fire-and-forget UI nudge\n"
          "    except Exception: pass\n")
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert not any(f.cls == "except-pass" for f in audit.findings)


def test_except_pass_marker_does_not_blanket_disable(tmp_path, monkeypatch):
    """Regression guard: the marker clears only the swallow it documents.
    A second, undocumented `except Exception: pass` in the same file still
    flags — the marker is not a global off-switch."""
    py = ("def good():\n"
          "    try:\n"
          "        self.sig.emit()\n"
          "    except Exception: pass  # audit: deliberate-fail-soft — nudge\n"
          "def bad():\n"
          "    try:\n"
          "        do_real_work()\n"
          "    except Exception: pass\n")
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    eps = [f for f in audit.findings if f.cls == "except-pass"]
    assert len(eps) == 1, "only the undocumented bad() swallow should flag"
    assert eps[0].line == 8


def test_detects_blocking_in_pyqtslot(tmp_path, monkeypatch):
    py = (
        "from PyQt6.QtCore import pyqtSlot\n"
        "class B:\n"
        "    @pyqtSlot(result=str)\n"
        "    def slow(self):\n"
        "        import urllib.request\n"
        "        return urllib.request.urlopen('http://x').read()\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert any(f.cls == "blocking-in-pyqtslot" for f in audit.findings)


def test_blocking_in_slot_clears_when_threaded(tmp_path, monkeypatch):
    py = (
        "from PyQt6.QtCore import pyqtSlot\n"
        "class B:\n"
        "    @pyqtSlot(result=str)\n"
        "    def ok(self):\n"
        "        import threading\n"
        "        threading.Thread(target=lambda: None).start()\n"
        "        return 'queued'\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert not any(f.cls == "blocking-in-pyqtslot" for f in audit.findings)


def test_detects_blocking_in_timer_callback(tmp_path, monkeypatch):
    """A method wired to QTimer.timeout that does blocking I/O (directly or
    one helper-hop down) freezes the Qt GUI thread on every tick — the
    host-pill idle-stall class. The detector must catch it."""
    py = (
        "from PyQt6.QtCore import QTimer\n"
        "class W:\n"
        "    def _build(self):\n"
        "        t = QTimer(self)\n"
        "        t.timeout.connect(self._refresh_host_pills)\n"
        "    def _refresh_host_pills(self):\n"
        "        for fam in self._fams:\n"
        "            self._probe_host_status(fam, None)\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert any(f.cls == "blocking-in-timer-callback" for f in audit.findings)


def test_detects_blocking_in_singleshot_callback(tmp_path, monkeypatch):
    py = (
        "from PyQt6.QtCore import QTimer\n"
        "class W:\n"
        "    def _build(self):\n"
        "        QTimer.singleShot(0, self._poll)\n"
        "    def _poll(self):\n"
        "        import urllib.request\n"
        "        urllib.request.urlopen('http://x')\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert any(f.cls == "blocking-in-timer-callback" for f in audit.findings)


def test_blocking_in_timer_callback_clears_when_off_thread(tmp_path, monkeypatch):
    """The fix pattern — fan the probe onto a QThread and repaint via a
    signal — clears the finding."""
    py = (
        "from PyQt6.QtCore import QTimer, QThread\n"
        "class W:\n"
        "    def _build(self):\n"
        "        t = QTimer(self)\n"
        "        t.timeout.connect(self._refresh_host_pills)\n"
        "    def _refresh_host_pills(self):\n"
        "        thread = QThread(self)\n"
        "        thread.start()\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert not any(f.cls == "blocking-in-timer-callback" for f in audit.findings)


def test_unwired_method_with_blocking_io_not_flagged_as_timer(tmp_path, monkeypatch):
    """Only QTimer-wired callbacks are timer-scanned; an ordinary helper
    that blocks is not a timer-callback finding (it would be caught by the
    slot detector only if it is a @pyqtSlot)."""
    py = (
        "class W:\n"
        "    def _helper(self):\n"
        "        import urllib.request\n"
        "        urllib.request.urlopen('http://x')\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert not any(f.cls == "blocking-in-timer-callback" for f in audit.findings)


def test_detects_success_mask(tmp_path, monkeypatch):
    py = (
        "def f():\n"
        "    try:\n"
        "        return risky()\n"
        "    except Exception:\n"
        "        return {\"status\": \"ok\", \"raw\": 1}\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert any(f.cls == "success-mask" for f in audit.findings)


def test_success_mask_cleared_by_deliberate_fail_soft_marker(tmp_path,
                                                             monkeypatch):
    """A documented degraded path that self-labels (e.g. `stub: True`)
    and carries the `# audit: deliberate-fail-soft` marker is NOT a
    masked failure — the scanner must clear it. Mirrors the off-thread
    marker convention the blocking scanners use."""
    py = (
        "def f():\n"
        "    try:\n"
        "        from router import R\n"
        "    except Exception:\n"
        "        # audit: deliberate-fail-soft — router absent; stub is\n"
        "        # self-labelled, not a claimed real success.\n"
        "        return {\"status\": \"ok\", \"stub\": True}\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    assert not any(f.cls == "success-mask" for f in audit.findings)


def test_success_mask_marker_does_not_blanket_disable(tmp_path, monkeypatch):
    """Regression guard: the marker clears only the except block it sits
    in. A SECOND, unmarked except in the same file that masks a failure
    is still caught — the allowlist must not become a global off-switch."""
    py = (
        "def good():\n"
        "    try:\n"
        "        from router import R\n"
        "    except Exception:\n"
        "        # audit: deliberate-fail-soft — documented stub.\n"
        "        return {\"status\": \"ok\", \"stub\": True}\n"
        "def bad():\n"
        "    try:\n"
        "        return risky()\n"
        "    except Exception:\n"
        "        return {\"status\": \"ok\", \"raw\": 1}\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, py=py)
    masks = [f for f in audit.findings if f.cls == "success-mask"]
    assert len(masks) == 1, "only the unmarked bad() except should flag"
    assert masks[0].line == 11  # the bare ok-return in bad()


def test_detects_todo_markers(tmp_path, monkeypatch):
    audit = _audit_for(tmp_path, monkeypatch,
                       py="# TODO: wire this up\nx = 1\n")
    assert any(f.cls == "todo-marker" for f in audit.findings)


# ─── JSX detectors ──────────────────────────────────────────────────


def test_detects_listener_leak(tmp_path, monkeypatch):
    jsx = (
        "const C = () => {\n"
        "  React.useEffect(() => {\n"
        "    const onKey = (e) => {};\n"
        "    document.addEventListener('keydown', onKey);\n"
        "    return () => {};\n"   # no removeEventListener
        "  }, []);\n"
        "};\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, jsx=jsx)
    assert any(f.cls == "listener-leak" for f in audit.findings)


def test_listener_leak_clears_when_removed(tmp_path, monkeypatch):
    jsx = (
        "const C = () => {\n"
        "  React.useEffect(() => {\n"
        "    const onKey = (e) => {};\n"
        "    document.addEventListener('keydown', onKey);\n"
        "    return () => document.removeEventListener('keydown', onKey);\n"
        "  }, []);\n"
        "};\n"
    )
    audit = _audit_for(tmp_path, monkeypatch, jsx=jsx)
    assert not any(f.cls == "listener-leak" for f in audit.findings)


def test_detects_bridge_sync_misuse(tmp_path, monkeypatch):
    jsx = "const data = bridgeJson('get_sessions');\nif (Array.isArray(data)) {}\n"
    audit = _audit_for(tmp_path, monkeypatch, jsx=jsx)
    assert any(f.cls == "bridge-sync-misuse" for f in audit.findings)


# ─── report + summary shape ─────────────────────────────────────────


def test_report_and_summary_render():
    audit = ma.Audit()
    audit.findings.append(
        ma.Finding("HIGH", "bare-except", "app/x.py", 3, "test"))
    report = ma.render_report(audit)
    assert "maintenance audit" in report.lower()
    assert "bare-except" in report


def test_audit_runs_on_real_repo_clean_exit(capsys):
    """The audit must run against the real repo + exit 0 with a
    parseable JSON summary on the last line."""
    rc = ma.main([])
    assert rc == 0
    out = capsys.readouterr().out
    last = [l for l in out.splitlines() if l.startswith("AUDIT_SUMMARY_JSON ")]
    assert last, "no AUDIT_SUMMARY_JSON line"
    summary = json.loads(last[-1].replace("AUDIT_SUMMARY_JSON ", ""))
    for k in ("critical", "high", "medium", "info", "total"):
        assert k in summary


# ─── workflow + AgDR exist ──────────────────────────────────────────


def test_daily_audit_workflow_exists():
    p = REPO / ".github" / "workflows" / "daily-audit.yml"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "cron:" in text
    assert "maintenance_audit.py" in text
    assert "workflow_dispatch" in text


def test_agdr_0034_exists():
    p = REPO / "docs" / "agdr" / "AgDR-0034-daily-maintenance-audit-bot.md"
    assert p.exists()
    assert "status: executed" in p.read_text(encoding="utf-8")
