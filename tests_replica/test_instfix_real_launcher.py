"""Actual source launcher, hidden desktop, isolated profile, fake model only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]

INJECTION = '''
import json, os, sys, time
from pathlib import Path
from types import SimpleNamespace
from nodelang import application_server, pipeline_engines, goose_runtime
from nodelang import baboom_native_runtime, cloud_signin, cloud_session
from app import secrets_store
secrets_store._try_keyring = lambda: None  # Isolated DPAPI file, never the user's vault.
state = Path(os.environ['ARCHHUB_TEST_STATE_DIR'])
calls = []
def fake_model(prompt, context, model, **kwargs):
    calls.append(prompt)
    if kwargs.get('before_dispatch'): kwargs['before_dispatch']()
    return 'INSTFIX actual launcher answered.'
original_init = application_server.ApplicationServer.__init__
def initialize(self, *args, **kwargs):
    kwargs.update(enable_brain_cloud_sync=False, enable_machine_projection_prewarm=False, live_watch=False)
    original_init(self, *args, **kwargs)
    self.goose_brain = SimpleNamespace(ask=fake_model)
    self._read_agent_model = lambda: 'openrouter/free'
    self._brain_state = lambda: {'ok': True, 'facts': 0}
    self._host_rows = lambda: []
application_server.ApplicationServer.__init__ = initialize
pipeline_engines.brain_recall = lambda *args: ({'out': ''}, 'court')
goose_runtime.start_goose_for_baboom = lambda *args, **kwargs: None
cloud_session._cloud_get = lambda *args, **kwargs: (200, {'email': 'person@example.test', 'founder': False})
record = cloud_session.cloud_session_path()
if not record.is_file():
    cloud_signin.write_cloud_session(record, {'email': 'person@example.test', 'token': 'court-only-token',
        'expires_at': int(time.time()) + 90 * 86400})
original_projection = baboom_native_runtime.create_baboom_native_projection
def projection(*args, **kwargs):
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    window = original_projection(*args, **kwargs)
    result = {'label': 'CANDIDATE SOURCE LAUNCHER; isolated profile; fake model/brain/hosts; Goose process off'}
    def save():
        (state / 'instfix-launcher.json').write_text(json.dumps(result), encoding='utf-8')
    def close_main():
        import ctypes
        main = sys.modules['__main__']
        result['signed_in'] = cloud_signin.sign_in_state()['signed_in']
        result['same_icon'] = (QApplication.instance().windowIcon().cacheKey() == main.window.windowIcon().cacheKey())
        main.window.showMinimized()
        main._tray_open()
        def check_open():
            result['tray_open_focused'] = main.window.isVisible() and not main.window.isMinimized()
            result['close_sent_at'] = time.time()
            save()
            ctypes.windll.user32.PostMessageW(int(main.window.winId()), 0x0010, 0, 0)
        QTimer.singleShot(500, check_open)
    def check_answer():
        elapsed = time.monotonic() - result['ask_started']
        if window._busy and elapsed < 20:
            QTimer.singleShot(20, check_answer)
            return
        result.update(answered='INSTFIX actual launcher answered.' in window._report.text(),
            ask_seconds=elapsed, fake_model_calls=len(calls))
        window.grab().save(str(state / 'instfix-launcher-answer.png'))
        QTimer.singleShot(100, close_main)
    def ask():
        window._open_interaction()
        window._input.setText('Can you answer my question about this project?')
        result['ask_started'] = time.monotonic()
        QTest.keyClick(window._input, Qt.Key.Key_Return)
        QTimer.singleShot(20, check_answer)
    QTimer.singleShot(1000, ask)
    return window
baboom_native_runtime.create_baboom_native_projection = projection
'''


@pytest.mark.skipif(sys.platform != "win32", reason="Windows real launcher court")
def test_actual_launcher_answers_restarts_signed_in_and_x_leaves_no_process(tmp_path):
    from tools.real_app_check.real_app_check import HiddenDesktop, RunJob, free_port, isolated_env
    profile = tmp_path / "profile"
    for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "state", "claude-config"):
        (profile / name).mkdir(parents=True)
    injection = tmp_path / "injection"
    injection.mkdir()
    (injection / "sitecustomize.py").write_text(INJECTION, encoding="utf-8")
    environment = isolated_env(dict(os.environ), profile, cdp_port=free_port(), lock_port=free_port())
    environment.update(PYTHONPATH=str(injection) + os.pathsep + str(ROOT),
        ARCHHUB_GRAND_MAP_PATH=str(ROOT / "nodelang/data/public_runtime_map.json"))
    environment.pop("QT_QPA_PLATFORM", None)
    job = RunJob()
    desktop = HiddenDesktop(job)
    verdicts = []
    try:
        for restart in range(2):
            result_path = profile / "state/instfix-launcher.json"
            result_path.unlink(missing_ok=True)
            process = desktop.spawn(subprocess.list2cmdline([sys.executable, "-B", str(ROOT / "launch_archhub_test.py")]),
                env=environment, cwd=str(ROOT))
            try:
                deadline = time.monotonic() + 150
                while not result_path.is_file() and time.monotonic() < deadline:
                    if desktop.k32.WaitForSingleObject(process.hProcess, 100) == 0:
                        break
                    time.sleep(0.1)
                log = (profile / "state/launcher.log").read_text(encoding="utf-8", errors="replace")
                assert result_path.is_file(), log[-3000:]
                result = json.loads(result_path.read_text(encoding="utf-8"))
                assert result["answered"] and result["ask_seconds"] <= 20, result
                assert result["fake_model_calls"] == 1 and result["signed_in"] and result["same_icon"], result
                assert result["tray_open_focused"], result
                assert desktop.k32.WaitForSingleObject(process.hProcess, 10000) == 0, "X did not exit within 10 seconds"
                deadline = time.monotonic() + 10
                while job.pids() and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert job.pids() == [], "X left an owned ArchHub/Qt process"
                result.update(restart=restart, processes_after_x=job.pids())
                verdicts.append(result)
            finally:
                desktop.k32.CloseHandle(process.hProcess)
                desktop.k32.CloseHandle(process.hThread)
        evidence = ROOT / "evidence"
        (evidence / "instfix-real-launcher-receipt.txt").write_text(json.dumps(verdicts, indent=2), encoding="utf-8")
        shutil.copy2(profile / "state/instfix-launcher-answer.png", evidence / "instfix-real-launcher.png")
        print("ACTUAL SOURCE LAUNCHER: 2 starts signed in; BABOOM asks <=20 s; X process trees empty 2/2")
    finally:
        job.close()
        desktop.close()
