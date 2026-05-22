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
    assert "status: approved" in p.read_text(encoding="utf-8")
