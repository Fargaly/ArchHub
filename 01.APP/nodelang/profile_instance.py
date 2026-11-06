"""One desktop per local profile; loopback ports carry IPC, never ownership."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path

# The updater's emergency loader must survive a damaged package __init__.
import importlib.util
_spec = importlib.util.spec_from_file_location('archhub_user_paths', Path(__file__).with_name('user_paths.py'))
_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_paths)


def profile_identity(environment):
    local = environment.get("LOCALAPPDATA")
    if not local and not environment.get('ARCHHUB_TEST_STATE_DIR'):
        return None
    state = str(_paths.state_directory(environment))
    return tuple(os.path.normcase(os.path.realpath(value)) for value in (local or state, state))


def mutex_name(environment):
    profile = profile_identity(environment)
    if profile is None:
        raise ValueError("LOCALAPPDATA is required for the launcher profile")
    return "Local\\ArchHub-" + hashlib.sha256(profile[1].encode()).hexdigest()


class ProfileInstance:
    def __init__(self, environment=None):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel, self.handle = kernel, None
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, False, mutex_name(os.environ if environment is None else environment))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(handle)
        else:
            self.handle = handle

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
