"""Process-local request lifetime; this is not graph permission or state."""
from contextlib import contextmanager
import math
import threading


class RuntimeClosing(RuntimeError):
    pass


class RuntimeActivity:
    def __init__(self):
        self._condition = threading.Condition()
        self._active = 0
        self._closing = False

    @property
    def closing(self):
        with self._condition:
            return self._closing

    @contextmanager
    def admit(self):
        with self._condition:
            if self._closing:
                raise RuntimeClosing("runtime is shutting down; new work is refused")
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def begin_shutdown(self):
        with self._condition:
            self._closing = True
            self._condition.notify_all()

    def wait_for_idle(self, timeout_seconds=30.0):
        if (type(timeout_seconds) not in (int, float) or
                not math.isfinite(timeout_seconds) or not 0 <= timeout_seconds <= 60):
            raise ValueError("runtime drain timeout must be between zero and sixty seconds")
        with self._condition:
            if not self._closing:
                raise RuntimeError("close admission before draining requests")
            return self._condition.wait_for(lambda: self._active == 0, timeout_seconds)
