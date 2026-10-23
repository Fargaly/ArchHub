"""The boot writes where its seconds went. 694s with no account is not allowed."""
from __future__ import annotations

import time
import builtins
import os
import subprocess
import sys
import ast
from builtins import InterruptedError
from types import SimpleNamespace
from pathlib import Path

from nodelang.boot_profile import profile_boot

ROOT = Path(__file__).resolve().parents[2]


def _busy(n=6):
    end = time.perf_counter() + 0.6
    while time.perf_counter() < end:
        sum(range(10_000))
    return "booted"


def test_the_sampler_names_the_function_that_ate_the_time(tmp_path):
    assert profile_boot(_busy, state_dir=tmp_path, interval=0.05) == "booted"
    text = (tmp_path / "boot-profile.log").read_text(encoding="utf-8")
    assert "samples every 0.05s" in text
    assert "test_boot_is_measured.py:_busy" in text
    head = text.split("--- leaf")[1]
    assert "_busy" in head, head


def test_the_launcher_boots_through_the_sampler():
    src = (ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8")
    assert "profile_boot(_boot_unsampled, state_dir=state_dir" in src
    assert src.index("def _boot():") < src.index("def _boot_unsampled():")


def test_launcher_writes_before_its_first_product_import(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    source = (ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8")
    prefix = source[:source.index("\ndef _require_complete_local_update")]
    original_import = builtins.__import__
    seen = []

    def product_import(name, *args, **kwargs):
        if name.startswith("nodelang"):
            path = tmp_path / "launcher.log"
            seen.append(path.read_text(encoding="utf-8") if path.exists() else "")
            raise ImportError("court blocks product import")
        return original_import(name, *args, **kwargs)

    namespace = {"__file__": str(ROOT / "01.APP/nodelang/launcher.py")}
    stdout, stderr = sys.stdout, sys.stderr
    monkeypatch.setattr(builtins, "__import__", product_import)
    try:
        exec(compile(prefix, "nodelang/launcher.py", "exec"), namespace)
    finally:
        sys.stdout, sys.stderr = stdout, stderr
        if namespace.get("_log"):
            namespace["_log"].close()
        __import__("faulthandler").cancel_dump_traceback_later()
    assert seen and all("prepare desktop" in text for text in seen), seen


def test_stalled_boot_phase_writes_its_stack_and_exits_bounded(tmp_path):
    source = (ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8")
    prefix = source[:source.index("\ndef _require_complete_local_update")]
    script = '__file__ = ' + repr(str(ROOT / "01.APP/nodelang/launcher.py")) + '\n' + prefix + '\n_start_boot_phase("stalled court", timeout_seconds=0.1)\ntime.sleep(10)\n'
    env = dict(os.environ, ARCHHUB_TEST_STATE_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, "-B", "-c", script], env=env,
                            capture_output=True, timeout=5, text=True)
    log = (tmp_path / "launcher.log").read_text(encoding="utf-8")
    assert result.returncode == 1 and "stalled court" in log and "Timeout" in log, log


def test_optional_pipeline_waits_for_visible_home_and_starts_once(monkeypatch):
    tree = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8"))
    definitions = [node for node in tree.body if getattr(node, "name", None) == "_prepare_pipeline_after_home"]
    assert definitions, "optional pipeline has no first-paint admission"
    callbacks, scheduled, started, finished = [], [], [], []
    page = SimpleNamespace(runJavaScript=lambda expression, callback: callbacks.append(callback))
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", SimpleNamespace(QTimer=SimpleNamespace(
        singleShot=lambda delay, callback: scheduled.append(callback))))
    namespace = {"view": SimpleNamespace(page=lambda: page), "_pipeline_start": {"started": False},
                 "server": object(), "_prepare_pipeline": lambda: None,
                 "_start_background_refresh": lambda owner, work, **kwargs: started.append(work),
                 "_boot_phase_finish_all": lambda held: finished.append(held)}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "nodelang/launcher.py", "exec"), namespace)
    work = namespace["_prepare_pipeline_after_home"]
    work("surface")
    assert not started
    callbacks.pop()(False)
    assert scheduled and not started
    scheduled.pop()()
    callbacks.pop()(True)
    work("surface")
    assert len(started) == 1 and finished == ["surface"]


def test_current_launcher_log_is_nonempty_after_a_rotation(tmp_path):
    from nodelang.log_rotation import RotatingLog
    tree = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if getattr(node, "name", None) == "_follow_boot_log_rotation"]
    armed = []
    namespace = {"faulthandler": SimpleNamespace(enable=lambda **kwargs: None),
                 "_arm_boot_watchdog": lambda: armed.append(True)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "nodelang/launcher.py", "exec"), namespace)
    path = tmp_path / "launcher.log"
    stream = RotatingLog(path, max_bytes=128, on_rotate=namespace["_follow_boot_log_rotation"])
    try:
        stream.write("x" * 140)
        stream.flush()
        assert path.stat().st_size > 0 and "continued" in path.read_text(encoding="utf-8")
        assert armed == [True]
    finally:
        stream.close()


def _pipeline_install_functions():
    import contextlib
    tree = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8"))
    names = {"_startup_pipeline_state", "_record_startup_pipeline_intent",
             "_initialize_startup_pipeline", "_held_guard", "_launcher_parameter", "_launcher_seconds"}
    functions = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in functions} == names, "first-run seed has no durable resume intent"
    namespace = {"contextlib": contextlib, "time": time}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "nodelang/launcher.py", "exec"), namespace)
    return namespace


def _pipeline_owner(store):
    from contextlib import nullcontext
    import threading
    authority = SimpleNamespace(session=SimpleNamespace(context=lambda **kwargs: object()),
        broker=SimpleNamespace(live_context=lambda context: nullcontext()))
    return SimpleNamespace(universal_store=store, mutation_lock=threading.RLock(),
        universal_registry=SimpleNamespace(application_root="app:archhub", authorization=authority))


def test_close_after_home_before_seed_starts_resumes_only_pending_install(tmp_path, monkeypatch):
    from nodelang.universal_cell import CellStore
    from nodelang import universal_pipeline
    functions = _pipeline_install_functions()
    path = tmp_path / "application.sqlite3"
    calls = []
    monkeypatch.setattr(universal_pipeline, "seed_wall_pipeline", lambda *args, **kwargs: calls.append("seeded"))
    with CellStore(path) as store:
        owner = _pipeline_owner(store)
        assert functions["_record_startup_pipeline_intent"](owner, first_boot=True)
        assert functions["_startup_pipeline_state"](owner) == "pending"
        # Home can now close before its background worker starts.
    with CellStore(path) as store:
        owner = _pipeline_owner(store)
        functions["_initialize_startup_pipeline"](owner, first_boot=False)
        assert functions["_startup_pipeline_state"](owner) == "complete"
        revision = store.revision
        functions["_initialize_startup_pipeline"](owner, first_boot=False)
        assert calls == ["seeded"] and store.revision == revision


def test_interrupted_multicommit_seed_resumes_after_reopen(tmp_path, monkeypatch):
    import pytest
    from nodelang.universal_cell import CellStore, Cell, NULL_CELL_ID
    from nodelang import universal_pipeline
    functions = _pipeline_install_functions()
    path = tmp_path / "application.sqlite3"
    def interrupted(store, registry, **kwargs):
        store.commit(store.revision, create=(Cell("seed:partial", NULL_CELL_ID, NULL_CELL_ID, b"preserved"),))
        raise InterruptedError("closed during first-run seed")
    monkeypatch.setattr(universal_pipeline, "seed_wall_pipeline", interrupted)
    with CellStore(path) as store:
        owner = _pipeline_owner(store)
        functions["_record_startup_pipeline_intent"](owner, first_boot=True)
        with pytest.raises(InterruptedError):
            functions["_initialize_startup_pipeline"](owner, first_boot=True)
        assert functions["_startup_pipeline_state"](owner) == "pending"
    def resumed(store, registry, **kwargs):
        assert store.read("seed:partial").atom == b"preserved"
    monkeypatch.setattr(universal_pipeline, "seed_wall_pipeline", resumed)
    with CellStore(path) as store:
        owner = _pipeline_owner(store)
        functions["_initialize_startup_pipeline"](owner, first_boot=False)
        assert functions["_startup_pipeline_state"](owner) == "complete"


def test_saved_graph_without_install_intent_is_never_seeded(tmp_path, monkeypatch):
    from nodelang.universal_cell import CellStore
    from nodelang import universal_pipeline
    functions = _pipeline_install_functions()
    monkeypatch.setattr(universal_pipeline, "seed_wall_pipeline", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("saved work reseeded")))
    with CellStore(tmp_path / "saved.sqlite3") as store:
        owner = _pipeline_owner(store)
        revision = store.revision
        functions["_initialize_startup_pipeline"](owner, first_boot=False)
        assert store.revision == revision and functions["_startup_pipeline_state"](owner) is None


def _canvas_watchdog_script(body):
    source = (ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8")
    prefix = source[:source.index("\ndef _require_complete_local_update")]
    phase = next(node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "_boot_phase")
    return ("__file__ = " + repr(str(ROOT / "01.APP/nodelang/launcher.py")) + "\n"
            + prefix + "\n" + ast.unparse(phase) + "\n"
            + "from PyQt6.QtCore import QCoreApplication, QTimer, Qt\n"
            + "from nodelang.clean_boot_surface import BootProgress\n"
            + "from types import SimpleNamespace\n"
            + "app = QCoreApplication([])\n"
            + "_boot_surface = SimpleNamespace(progress=BootProgress())\n"
            + body)


def test_canvas_phase_allows_120_seconds_with_responsive_qt_loop(tmp_path):
    script = _canvas_watchdog_script('''
ticks = []
timer = QTimer()
timer.setTimerType(Qt.TimerType.PreciseTimer)
timer.setInterval(100)
timer.timeout.connect(lambda: ticks.append(time.monotonic()))
timer.start()
started = time.monotonic()
_boot_phase(1)
completion = QTimer()
completion.setTimerType(Qt.TimerType.PreciseTimer)
completion.setSingleShot(True)
def finish():
    elapsed = time.monotonic() - started
    _boot_phase(1, finished=True)
    assert elapsed >= 120 and len(ticks) >= 100
    assert _boot_deadline is None
    assert _boot_surface.progress.payload()['phases'][-1]['seconds'] >= 120
    print('CANVAS_COMPLETE elapsed=%.3f ticks=%d' % (elapsed, len(ticks)), flush=True)
    app.quit()
completion.timeout.connect(finish)
completion.start(120000)
app.exec()
''')
    result = subprocess.run([sys.executable, "-B", "-c", script],
                            env=dict(os.environ, ARCHHUB_TEST_STATE_DIR=str(tmp_path)),
                            capture_output=True, timeout=140, text=True)
    log = (tmp_path / "launcher.log").read_text(encoding="utf-8")
    print(log)
    assert result.returncode == 0 and "CANVAS_COMPLETE" in log, log + result.stderr


def test_canvas_phase_hang_still_exits_with_injected_deadline(tmp_path):
    script = _canvas_watchdog_script('''
start_phase = _start_boot_phase
def _start_boot_phase(label, **kwargs):
    start_phase(label, timeout_seconds=0.2)
_boot_phase(1)
QTimer.singleShot(0, lambda: time.sleep(10))
app.exec()
''')
    result = subprocess.run([sys.executable, "-B", "-c", script],
                            env=dict(os.environ, ARCHHUB_TEST_STATE_DIR=str(tmp_path)),
                            capture_output=True, timeout=5, text=True)
    log = (tmp_path / "launcher.log").read_text(encoding="utf-8")
    print(log)
    assert result.returncode == 1 and "stand the canvas surface" in log and "Timeout" in log, log


def test_phase_deadlines_progress_and_finish_are_preserved():
    from nodelang.clean_boot_surface import BOOT_PHASES, BootProgress
    tree = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8"))
    names = {"_start_boot_phase", "_finish_boot_phase", "_arm_boot_watchdog", "_boot_phase"}
    functions = [node for node in tree.body if getattr(node, "name", None) in names]
    alarms, cancelled = [], []
    progress = BootProgress()
    namespace = {"time": SimpleNamespace(monotonic=lambda: 10), "_log": None,
                 "_boot_deadline": None, "_boot_surface": SimpleNamespace(progress=progress),
                 "faulthandler": SimpleNamespace(
                     dump_traceback_later=lambda seconds, **kwargs: alarms.append((seconds, kwargs)),
                     cancel_dump_traceback_later=lambda: cancelled.append(True))}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "nodelang/launcher.py", "exec"), namespace)
    namespace["_start_boot_phase"]("prepare desktop")
    assert alarms[-1][0] == 90
    for index, seconds in enumerate((90, 300)):
        namespace["_boot_phase"](index)
        assert alarms[-1] == (seconds, {"file": None, "exit": True})
        namespace["_boot_phase"](index, finished=True)
        assert namespace["_boot_deadline"] is None
    assert len(cancelled) == 2
    assert [phase['label'] for phase in progress.payload()['phases']] == list(BOOT_PHASES)
    assert all(phase['seconds'] is not None for phase in progress.payload()['phases'])
    namespace['_boot_surface'] = None
    namespace['_boot_phase'](1)
    assert alarms[-1][0] == 300
    namespace['_boot_phase'](1, finished=True)
    namespace['_start_boot_phase']('explicit court', timeout_seconds=0.1)
    assert abs(alarms[-1][0] - 0.1) < 0.001
