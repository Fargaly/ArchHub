"""Execute the real launcher callbacks and served JavaScript, without Qt/app."""
from pathlib import Path
import io
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from nodelang import clean_boot_surface, persistence
from tests_replica.test_launcher_boot_refusal import FakeClock, _launcher_names


def _launcher(monkeypatch):
    clock, alarms = FakeClock(), []
    monkeypatch.setattr(clean_boot_surface, "time", clock)
    progress = clean_boot_surface.BootProgress()
    namespace = _launcher_names(
        "_arm_boot_watchdog", "_start_boot_phase", "_migration_progress", "_boot_step_seen",
        time=clock, _boot_deadline=None, _migration_status=None, _log=io.StringIO(),
        faulthandler=SimpleNamespace(dump_traceback_later=lambda seconds, **kwargs:
            alarms.append((clock.now + seconds, kwargs))),
        _boot_surface=SimpleNamespace(progress=progress), boot_step_label=lambda _stack: "sampler detail")
    return clock, alarms, progress, namespace


def test_progressing_migration_outlives_original_ninety_second_watchdog(monkeypatch):
    clock, alarms, progress, launcher = _launcher(monkeypatch)
    monkeypatch.setattr(persistence, "time", clock)
    launcher["_start_boot_phase"]("open authority")
    assert alarms[-1][0] == 90
    lease = persistence._MigrationProgress(30, launcher["_migration_progress"])
    for index in range(1, 7):
        clock.now = index * 20.0
        assert clock.now < alarms[-1][0], "progressing work must beat its active deadline"
        lease.advance("Copying journal pages", index, 10)
    assert clock.now > 90
    assert alarms[-1][0] == 155
    assert alarms[-1][1]["exit"] is True
    status = progress.payload()["migration"]
    assert status["label"] == "Updating your data (60%)"
    assert status["percent"] == 60


def test_sampler_and_inactivity_cannot_renew_migration_watchdog(monkeypatch):
    clock, alarms, progress, launcher = _launcher(monkeypatch)
    monkeypatch.setattr(persistence, "time", clock)
    lease = persistence._MigrationProgress(30, launcher["_migration_progress"])
    lease.advance("Copying journal pages", 42, 100)
    status, deadline, armed = progress.payload()["migration"], launcher["_boot_deadline"], len(alarms)
    for elapsed in (10, 20, 29):
        clock.now = elapsed
        launcher["_boot_step_seen"](["a real sampler stack"])
        lease()
        assert progress.payload()["migration"] == status
        assert launcher["_boot_deadline"] == deadline
        assert len(alarms) == armed
    clock.now = 30
    with pytest.raises(TimeoutError, match="no progress"):
        lease()
    assert len(alarms) == armed
    clock.now = deadline + 1
    assert clock.now > alarms[-1][0], "a blocked migration's watchdog must remain armed"


def test_served_progress_view_renders_migration_over_sampler_detail():
    node = shutil.which("node")
    if node is None:
        candidate = Path("C:/Program Files/nodejs/node.exe")
        node = str(candidate) if candidate.is_file() else None
    if node is None:
        pytest.skip("node unavailable for served JavaScript behavior court")
    page = clean_boot_surface.PAGE
    start = page.index("function progressView(state){")
    end = page.index("// The port changes hands", start)
    script = page[start:end] + "\nconst assert=require('node:assert/strict');\n"
    state = {"elapsed": 150, "detail": "sampler should not replace migration",
             "phases": [], "migration": {
                 "label": "Updating your data (42%)", "stage": "Copying journal pages",
                 "percent": 42, "completed": 42, "total": 100, "stall_seconds": 30}}
    script += "const state=" + json.dumps(state) + ";\n"
    script += """
let view=progressView(state);
assert.equal(view.text,'Updating your data (42%)');
assert.equal(view.detail,' — Copying journal pages');
assert.equal(view.fraction,0.42);
assert.equal(view.determinate,true);
state.migration={...state.migration,percent:0,label:'Updating your data (0%)'};
assert.equal(progressView(state).fraction,0);
state.migration={...state.migration,percent:null,label:'Updating your data'};
assert.equal(progressView(state).determinate,false);
state.migration=null;
assert.equal(progressView(state).text,'opening the graph');
console.log('migration progressView behavior PASS');
"""
    completed = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "migration progressView behavior PASS"
