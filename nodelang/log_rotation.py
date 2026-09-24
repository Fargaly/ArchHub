"""Size-capped logs: a cap per file and a fixed number of older copies.

launcher.log, baboom-geometry.log and brain.log were append-only for the life
of the install (6.9 MB of geometry lines on the founder machine, 2026-09-24).
Each is now at most ``max_bytes`` with ``keep`` older copies beside it, so the
total a log can occupy is bounded by (keep + 1) * max_bytes plus one line.
"""
import os
from pathlib import Path
import threading
import time


LAUNCHER_LOG_BYTES = 2 * 1024 * 1024
GEOMETRY_LOG_BYTES = 512 * 1024
LOG_KEEP = 3


def rotate(path, max_bytes, keep):
    """Move path aside when it reached max_bytes, then shift path.1..path.keep.

    The current log is renamed FIRST (to path.rotating). If that rename fails
    (another process holds it open) nothing changes and False is returned: no
    older copy is touched. Only after it succeeded are the copies shifted and
    the oldest dropped. A rotation interrupted after its first rename is
    finished by the next call before anything else moves.
    """
    path = Path(path)
    if type(max_bytes) is not int or max_bytes < 1 or type(keep) is not int or not 1 <= keep <= 20:
        raise ValueError("log rotation limits are invalid")
    pending = path.with_name(path.name + ".rotating")
    if not pending.exists():
        try:
            if path.stat().st_size < max_bytes:
                return False
        except FileNotFoundError:
            return False
        try:
            os.replace(path, pending)
        except OSError:
            return False
    try:
        oldest = path.with_name("%s.%d" % (path.name, keep))
        if oldest.exists():
            oldest.unlink()
        for index in range(keep - 1, 0, -1):
            source = path.with_name("%s.%d" % (path.name, index))
            if source.exists():
                os.replace(source, path.with_name("%s.%d" % (path.name, index + 1)))
        os.replace(pending, path.with_name(path.name + ".1"))
    except OSError:
        # The live log already moved aside; its bytes are in path.rotating and
        # the next call completes this shift before rotating again.
        pass
    return True


class LogRotator:
    """rotate() with a backoff: after a refused rotation, wait before retrying."""

    def __init__(self, path, max_bytes, keep, *, backoff_seconds=60.0, clock=time.monotonic):
        self.path, self.max_bytes, self.keep = Path(path), max_bytes, keep
        self.backoff_seconds, self._clock, self._next = backoff_seconds, clock, 0.0

    def __call__(self):
        now = self._clock()
        if now < self._next:
            return False
        rotated = rotate(self.path, self.max_bytes, self.keep)
        try:
            refused = not rotated and self.path.stat().st_size >= self.max_bytes
        except OSError:
            refused = False
        self._next = now + self.backoff_seconds if refused else 0.0
        return rotated


class RotatingLog:
    """A text stream for sys.stdout/sys.stderr that rotates as it grows.

    Line buffered like the file it replaces. The size check is one integer
    comparison per write; rotation closes, shifts and reopens the file.
    """

    def __init__(self, path, *, max_bytes=LAUNCHER_LOG_BYTES, keep=LOG_KEEP, on_rotate=None):
        self._path = Path(path)
        self._max_bytes = max_bytes
        self._keep = keep
        # faulthandler writes to a file descriptor; it must follow the reopen.
        self.on_rotate = on_rotate
        self._lock = threading.RLock()
        rotate(self._path, max_bytes, keep)
        self._file = open(self._path, "a", encoding="utf-8", buffering=1)
        self._size = self._file.tell()
        self._retry_at = max_bytes

    @property
    def name(self):
        return str(self._path)

    @property
    def encoding(self):
        return self._file.encoding

    def write(self, text):
        with self._lock:
            written = self._file.write(text)
            self._size += len(text.encode("utf-8", "replace"))
            if self._size >= self._retry_at:
                self._rotate()
            return written

    def _rotate(self):
        self._file.flush()
        self._file.close()
        rotated = rotate(self._path, self._max_bytes, self._keep)
        self._file = open(self._path, "a", encoding="utf-8", buffering=1)
        self._size = self._file.tell()
        # Held open elsewhere: keep writing, try again after another cap's worth.
        self._retry_at = self._max_bytes if rotated else self._size + self._max_bytes
        if self.on_rotate is not None:
            try:
                self.on_rotate(self)
            except Exception:
                pass

    def flush(self):
        with self._lock:
            self._file.flush()

    def fileno(self):
        return self._file.fileno()

    def isatty(self):
        return False

    def writable(self):
        return True

    def close(self):
        with self._lock:
            self._file.close()


__all__ = ["GEOMETRY_LOG_BYTES", "LAUNCHER_LOG_BYTES", "LOG_KEEP", "LogRotator", "RotatingLog", "rotate"]