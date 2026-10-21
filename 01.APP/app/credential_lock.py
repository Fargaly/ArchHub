"""Cross-process exclusion for one protected credential file.

A Windows named mutex keyed by the SHA-256 of the file's normalized absolute
path: no lock file, no lock on the file being replaced, and no worker or
polling. Each operation opens the mutex, waits a bounded time, and releases and
closes it in every outcome. Ownership is per thread and recursive, so nested
acquisitions by one writer are admitted while other threads and processes wait.
WAIT_ABANDONED means an earlier owner ended mid-operation: exclusive() reports
it, and writers read and validate the store afresh after acquiring, never
treating an unreadable store as empty. Non-Windows is unavailable, matching the
DPAPI boundary. Reads stay atomic file reads and take no lock.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import threading

WAIT_MILLISECONDS = 10000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_KERNEL32 = None
_KERNEL32_LOCK = threading.Lock()


class CredentialLockUnavailable(OSError):
    """The credential file lock was not acquired; nothing was changed."""


def mutex_name(path) -> str:
    """Session-local mutex name for one file: a path digest, never a secret or the path."""
    normalized = os.path.normcase(os.path.abspath(os.fspath(path)))
    return "Local\\ArchHub-credential-file-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _kernel32():
    global _KERNEL32
    with _KERNEL32_LOCK:
        if _KERNEL32 is None:
            import ctypes
            from ctypes import wintypes

            library = ctypes.WinDLL("kernel32", use_last_error=True)
            library.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            library.CreateMutexW.restype = wintypes.HANDLE
            library.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            library.WaitForSingleObject.restype = wintypes.DWORD
            library.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            library.ReleaseMutex.restype = wintypes.BOOL
            library.CloseHandle.argtypes = (wintypes.HANDLE,)
            library.CloseHandle.restype = wintypes.BOOL
            _KERNEL32 = library
        return _KERNEL32


@contextlib.contextmanager
def exclusive(path, *, wait_milliseconds=None, busy=None):
    """Hold the file's named mutex for one operation; yields True when it was abandoned.

    busy() builds the exception raised when ownership is not obtained within the
    bounded wait; the default is CredentialLockUnavailable.
    """
    def refused(reason):
        return busy() if busy is not None else CredentialLockUnavailable(reason)

    if os.name != "nt":
        raise refused("credential file locking requires Windows")
    wait = WAIT_MILLISECONDS if wait_milliseconds is None else int(wait_milliseconds)
    if not 0 <= wait <= 60000:
        raise ValueError("credential lock wait must be between 0 and 60000 milliseconds")
    kernel32 = _kernel32()
    handle = kernel32.CreateMutexW(None, False, mutex_name(path))
    if not handle:
        raise refused("credential file lock could not be opened")
    owned = False
    try:
        result = kernel32.WaitForSingleObject(handle, wait)
        if result not in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            raise refused("credential file lock is busy; nothing was changed")
        owned = True
        yield result == _WAIT_ABANDONED
    finally:
        if owned:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
