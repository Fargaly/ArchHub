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

ROOT = Path(__file__).resolve().parents[1]


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
    src = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "profile_boot(_boot_unsampled, state_dir=state_dir" in src
    assert src.index("def _boot():") < src.index("def _boot_unsampled():")


def test_launcher_writes_before_its_first_product_import(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    source = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    prefix = source[:source.index("\ndef _require_complete_local_update")]
    original_import = builtins.__import__
    seen = []

    def product_import(name, *args, **kwargs):
        if name.startswith("nodelang"):
            path = tmp_path / "launcher.log"
            seen.append(path.read_text(encoding="utf-8") if path.exists() else "")
            raise ImportError("court blocks product import")
        return original_import(name, *args, **kwargs)

    namespace = {"__file__": str(ROOT / "launch_archhub_test.py")}
    stdout, stderr = sys.stdout, sys.stderr
    monkeypatch.setattr(builtins, "__import__", product_import)
    try:
        exec(compile(prefix, "launch_archhub_test.py", "exec"), namespace)
    finally:
        sys.stdout, sys.stderr = stdout, stderr
        if namespace.get("_log"):
            namespace["_log"].close()
        __import__("faulthandler").cancel_dump_traceback_later()
    assert seen and all("prepare desktop" in text for text in seen), seen


def test_stalled_boot_phase_writes_its_stack_and_exits_bounded(tmp_path):
    source = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    prefix = source[:source.index("\ndef _require_complete_local_update")]
    script = '__file__ = ' + repr(str(ROOT / "launch_archhub_test.py")) + '\n' + prefix + '\n_start_boot_phase("stalled court", timeout_seconds=0.1)\ntime.sleep(10)\n'
    env = dict(os.environ, ARCHHUB_TEST_STATE_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, "-B", "-c", script], env=env,
                            capture_output=True, timeout=5, text=True)
    log = (tmp_path / "launcher.log").read_text(encoding="utf-8")
    assert result.returncode == 1 and "stalled court" in log and "Timeout" in log, log


def test_optional_pipeline_waits_for_visible_home_and_starts_once(monkeypatch):
    tree = ast.parse((ROOT / "launch_archhub_test.py").read_text(encoding="utf-8"))
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
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "launch_archhub_test.py", "exec"), namespace)
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
    tree = ast.parse((ROOT / "launch_archhub_test.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if getattr(node, "name", None) == "_follow_boot_log_rotation"]
    armed = []
    namespace = {"faulthandler": SimpleNamespace(enable=lambda **kwargs: None),
                 "_arm_boot_watchdog": lambda: armed.append(True)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "launch_archhub_test.py", "exec"), namespace)
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
    tree = ast.parse((ROOT / "launch_archhub_test.py").read_text(encoding="utf-8"))
    names = {"_startup_pipeline_state", "_record_startup_pipeline_intent",
             "_initialize_startup_pipeline", "_held_guard"}
    functions = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in functions} == names, "first-run seed has no durable resume intent"
    namespace = {"contextlib": contextlib, "time": time}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "launch_archhub_test.py", "exec"), namespace)
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
