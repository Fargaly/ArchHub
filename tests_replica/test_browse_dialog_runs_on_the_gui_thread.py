"""Settings -> Workspaces Browse: the folder dialog opens from an HTTP worker thread.

On 2026-10-01 the founder pressed Browse on build c292296: "Choose the folder in
the Windows dialog..." and no dialog, ever. The picker started a QTimer on the
HTTP worker thread, which has no event loop, so the dialog call never ran and
the request waited ten minutes. These courts run the real Qt event loop
(offscreen) and call from a plain worker thread, as the HTTP server does.
"""
import os
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtCore import QThread, QTimer  # noqa: E402

from nodelang.gui_thread import GuiThreadAsker  # noqa: E402

LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _from_worker(app, fn):
    """Run fn on a plain thread while the Qt loop spins; return its outcome."""
    outcome = {}

    def worker():
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc
        finally:
            QTimer.singleShot(0, app.quit)  # harmless if it never fires
            app.exit_requested = True

    app.exit_requested = False
    thread = threading.Thread(target=worker)
    thread.start()
    guard = QTimer()
    guard.timeout.connect(lambda: app.quit() if app.exit_requested or not thread.is_alive() else None)
    guard.start(20)
    QTimer.singleShot(10000, app.quit)
    app.exec()
    guard.stop()
    thread.join(5)
    return outcome


def test_a_call_from_a_worker_thread_runs_on_the_gui_thread(app):
    asker = GuiThreadAsker(app)
    gui = QThread.currentThread()
    outcome = _from_worker(app, lambda: asker(lambda: QThread.currentThread() is gui, 5))
    assert outcome == {"value": True}


def test_the_answer_comes_back_and_an_error_reaches_the_caller(app):
    asker = GuiThreadAsker(app)
    assert _from_worker(app, lambda: asker(lambda: "C:\\Clients\\Project", 5)) == {
        "value": "C:\\Clients\\Project"}

    def boom():
        raise RuntimeError("dialog failed")

    outcome = _from_worker(app, lambda: asker(boom, 5))
    assert isinstance(outcome.get("error"), RuntimeError)


def test_the_old_qtimer_route_never_runs_from_a_worker_thread(app):
    """Pins the cause: a QTimer started on a worker thread does not fire."""
    fired = threading.Event()
    _from_worker(app, lambda: (QTimer.singleShot(0, fired.set), fired.wait(1))[1])
    assert not fired.is_set()


def test_the_launcher_pickers_cross_to_the_gui_thread():
    source = LAUNCHER.read_text(encoding="utf-8")
    start = source.index("def _pick_file(")
    end = source.index("server.native_folder_picker = _pick_folder")
    pickers = source[start:end]
    assert "QTimer.singleShot" not in pickers
    assert "_ask_on_gui_thread(" in pickers
    assert "GuiThreadAsker(app)" in source
