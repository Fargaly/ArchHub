"""Registered workspace folders from the NOGRAPH Settings owner."""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath
from .user_paths import state_directory

class WorkspaceRootRefused(ValueError):
    pass

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROOT_PATH_PREFIX = 'workspace-roots/'

def built_in_path() -> str:
    """The built-in governed tree: the same folder the application resolves as
    its workspace root (workspace_root.workspace_root_for_map over the selected
    map). A running application passes its own resolved root as built_in, so
    admission and the view always use that instance's tree; this is only the
    fallback for callers without one. Never a hardcoded machine path."""
    from .map_import import resolve_map_path
    from .workspace_root import workspace_root_for_map
    return str(PureWindowsPath(workspace_root_for_map(resolve_map_path())))

def folder_identity(path):
    """(volume serial, file index) exactly as the hooks read it."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume_serial", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.POINTER(Info))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(path), 0x80, 0x7, None, 3, 0x02000000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        return None
    try:
        info = Info()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            return None
        return (info.volume_serial, (info.index_high << 32) | info.index_low)
    finally:
        kernel.CloseHandle(handle)

def _local_folder_path(text) -> bool:
    if type(text) is not str or not text or len(text) > 1024 or "\x00" in text:
        return False
    path = PureWindowsPath(text)
    drive = path.drive
    return (len(drive) == 2 and drive[1] == ":" and path.is_absolute()
            and len(path.parts) > 1 and ":" not in path.name
            and not text.startswith(chr(92) * 2)
            and not any(part != part.rstrip(" .") for part in path.parts[1:]))

def root_id_from_name(name, path, roots):
    """A valid, unused root id derived from what the user typed (or the folder name).

    Founder 2026-10-12: typing "BBC4" for E:\\01.PERSONAL\\BBC4 must register, not refuse.
    """
    raw = name if type(name) is str and name.strip() else PureWindowsPath(str(path or "")).name
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower()).strip("-")[:63].strip("-")
    if not slug:
        slug = "workspace"
    if slug == "archhub":
        slug = "archhub-workspace"
    used = {root.get("root_id") for root in roots or []}
    candidate, n = slug, 2
    while candidate in used:
        suffix = "-%d" % n
        candidate = slug[:63 - len(suffix)].strip("-") + suffix
        n += 1
    return candidate

def canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")

def registry_dir():
    home = os.environ.get('USERPROFILE') or str(Path.home())
    return state_directory() / 'workspace-registry' if 'ARCHHUB_TEST_STATE_DIR' in os.environ else Path(home) / '.archhub'


def default_snapshot_path():
    return registry_dir() / 'workspace-roots.json'


def read_registered_roots(verifier=None, *, snapshot_path=None, pin_path=None,
                          last_good_path=None, registry_state=None):
    from .nograph_server import JsonFile
    rows = JsonFile(state_directory() / 'settings/workspaces.json', {'roots': []}).read()['roots']
    return {row['root_id']: {'privacy': 'private', **row} for row in rows}, None


def root_bound_registration(path, *, runtime=None, **kwargs):
    parts = str(path).split('/')
    if (len(parts) < 3 or parts[0] != 'workspace-roots' or not _ID.fullmatch(parts[1])
            or any(part in ('', '.', '..') for part in parts[2:])):
        raise ValueError('workspace-root write path is invalid')
    roots, _pin = read_registered_roots()
    entry = roots.get(parts[1])
    if entry is None:
        raise ValueError('This workspace is not registered in Settings.')
    base = Path(entry['path'])
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        raise ValueError('Registered workspace is unavailable or redirected.')
    if entry.get('identity') and list(folder_identity(base) or ()) != entry['identity']:
        raise ValueError('Registered workspace folder identity changed.')
    if runtime and 'writers' in entry and runtime not in entry['writers']:
        raise ValueError('This agent is not enabled for the registered workspace.')
    return 'workspace-root:' + parts[1], hashlib.sha256(canonical(entry)).hexdigest(), entry


def root_bound_admission(path, **kwargs):
    container, digest, _entry = root_bound_registration(path, **kwargs)
    return container, digest
