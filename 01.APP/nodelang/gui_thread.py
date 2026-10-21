"""Run one call on the Qt thread from any other thread and wait for its answer.

The Studio's Browse requests arrive on HTTP worker threads, but a Qt dialog
must run on the Qt thread. A QTimer started on a worker thread never fires
(the worker has no event loop), so Browse once waited ten minutes and no
dialog ever opened. The call crosses over as a queued signal instead, the
same way the tray notifier does.
"""
import threading

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class _Carrier(QObject):
    run = pyqtSignal(object)


class GuiThreadAsker:
    """asker(call, timeout) -> call()'s result, run on the Qt thread of `parent`.

    A call made on the Qt thread itself runs directly. If the call raises, the
    same exception is raised to the caller. None comes back on a timeout.
    """

    def __init__(self, parent):
        self._carrier = _Carrier(parent)
        self._carrier.run.connect(lambda job: job())

    def __call__(self, call, timeout):
        if QThread.currentThread() is self._carrier.thread():
            return call()
        result = {}
        done = threading.Event()

        def job():
            try:
                result["value"] = call()
            except BaseException as exc:  # noqa: BLE001 - re-raised to the caller
                result["error"] = exc
            finally:
                done.set()

        self._carrier.run.emit(job)
        if not done.wait(timeout):
            return None
        if "error" in result:
            raise result["error"]
        return result.get("value")
