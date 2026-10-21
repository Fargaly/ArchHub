"""Setup-only clean close of existing SQLite files; no store or sidecar deletion.

Windows Restart Manager identifies resource holders. Only known ArchHub runtime
processes are stopped; PID creation time is checked again on the open handle.
The caller holds all closed-file leases until verified custody is complete.
"""
from contextlib import contextmanager, ExitStack, closing
import ast
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
import subprocess


class _UniqueProcess(ctypes.Structure):
    _fields_ = [('pid', wintypes.DWORD), ('started', wintypes.FILETIME)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [('process', _UniqueProcess), ('name', wintypes.WCHAR * 256),
                ('service', wintypes.WCHAR * 64), ('kind', ctypes.c_int),
                ('status', wintypes.ULONG), ('session', wintypes.DWORD),
                ('restartable', wintypes.BOOL)]


def _resource_path(path):
    value = str(path)
    if len(value) < 260:
        return value
    # Restart Manager rejects long paths even when SQLite supports them. Use
    # the existing NTFS alias for this same file, never a copy or a junction.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetShortPathNameW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetShortPathNameW(value, buffer, len(buffer))
    return buffer.value if 0 < length < 260 else value


class _Holders:
    def __init__(self, paths):
        self.paths = paths
        self.session = wintypes.DWORD()
        self.api = ctypes.WinDLL('rstrtmgr')
        self.api.RmStartSession.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR)
        self.api.RmRegisterResources.argtypes = (wintypes.DWORD, wintypes.UINT, ctypes.POINTER(wintypes.LPCWSTR),
            wintypes.UINT, ctypes.POINTER(_UniqueProcess), wintypes.UINT, ctypes.POINTER(wintypes.LPCWSTR))
        self.api.RmGetList.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
                                      ctypes.POINTER(_ProcessInfo), ctypes.POINTER(wintypes.DWORD))
        self.api.RmEndSession.argtypes = (wintypes.DWORD,)

    def __enter__(self):
        code = self.api.RmStartSession(ctypes.byref(self.session), 0, ctypes.create_unicode_buffer(33))
        if code:
            raise ctypes.WinError(code)
        resources = [_resource_path(p) for path in self.paths for p in (path, *(Path(str(path) + s) for s in ('-wal', '-shm', '-journal'))) if p.exists()]
        code = self.api.RmRegisterResources(self.session, len(resources), (wintypes.LPCWSTR * len(resources))(*resources), 0, None, 0, None)
        if code:
            self.__exit__(None, None, None)
            raise OSError('Restart Manager could not register journal resources: ' + str(ctypes.WinError(code)))
        return self

    def __exit__(self, *_):
        self.api.RmEndSession(self.session)

    def list(self):
        for _ in range(8):
            needed, count, reasons = wintypes.UINT(), wintypes.UINT(), wintypes.DWORD()
            code = self.api.RmGetList(self.session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
            if code == 0:
                return []
            if code != 234:
                raise ctypes.WinError(code)
            count.value = needed.value
            entries = (_ProcessInfo * count.value)()
            code = self.api.RmGetList(self.session, ctypes.byref(needed), ctypes.byref(count), entries, ctypes.byref(reasons))
            if code == 0:
                return [entry for entry in entries[:count.value] if entry.process.pid != os.getpid()]
            if code != 234:
                raise ctypes.WinError(code)
        raise OSError('Journal holders kept changing; saved work was kept')


def _process_commands(holders, *, timeout_seconds: float = 30):
    if not holders:
        return {}
    query = ' OR '.join('ProcessId=' + str(h.process.pid) for h in holders)
    command = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-CimInstance Win32_Process -Filter '" + query + "' -ErrorAction Stop | "
               'Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as error:
        raise OSError('Timed out identifying journal holders: ' + _holder_names(holders)) from error
    if result.returncode:
        raise OSError('Cannot identify journal holders: ' + _holder_names(holders))
    rows = json.loads(result.stdout) if result.stdout.strip() else []
    return {row['ProcessId']: row.get('CommandLine') or '' for row in (rows if isinstance(rows, list) else [rows])}


def _holder_names(holders):
    return ', '.join('%s (PID %d)' % (h.name or 'process', h.process.pid) for h in holders) or 'no live holder reported'


def _arguments(command):
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    count = ctypes.c_int()
    values = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not values:
        raise ctypes.WinError(ctypes.get_last_error())
    kernel = ctypes.WinDLL('kernel32')
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    try:
        return list(values[:count.value])
    finally:
        kernel.LocalFree(values)


def _python_role(app, arguments):
    args = list(arguments[1:])
    while args and args[0] in ('-I', '-B', '-E', '-s', '-u'):
        args.pop(0)
    modules = ('native_agent_mcp', 'clean_coordination_mcp', 'clean_coordination_service', 'desktop')
    for module in modules:
        name = 'nodelang.' + module
        if len(args) >= 2 and args[:2] == ['-m', name]:
            return 'desktop' if module == 'desktop' else 'helper'
        if len(args) >= 3 and args[0] == '-c' and Path(args[2]).resolve() == app:
            expected = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module(%r,run_name='__main__')" % name
            try:
                matches = ast.dump(ast.parse(args[1])) == ast.dump(ast.parse(expected))
            except (SyntaxError, ValueError):
                matches = False
            if matches:
                return 'desktop' if module == 'desktop' else 'helper'
    if args and Path(args[0]).resolve() in (app / 'nodelang/launcher.py', app / 'launch_archhub_test.py'):
        return 'desktop'
    return ''


@contextmanager
def _process_handle(holder):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME),) * 4)
    handle = kernel.OpenProcess(0x1000 | 0x100000 | 1, False, holder.process.pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            yield None, kernel
            return
        raise OSError('Cannot stop journal holder: ' + _holder_names([holder]))
    try:
        started, ended, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(started), ctypes.byref(ended), ctypes.byref(system), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        expected = holder.process.started
        same = (started.dwHighDateTime, started.dwLowDateTime) == (expected.dwHighDateTime, expected.dwLowDateTime)
        yield handle if same else None, kernel
    finally:
        kernel.CloseHandle(handle)


def _owned_role(profile, holder, command):
    with _process_handle(holder) as (handle, kernel):
        if handle is None:
            return ''
        kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        length, buffer = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            return ''
        executable = Path(buffer.value).resolve()
        app = profile / 'ArchHub'
        arguments = _arguments(command) if command else []
        invoked = Path(arguments[0]).resolve() if arguments else None
        launchers = {app / '.venv/Scripts/python.exe', app / '.venv/Scripts/pythonw.exe'}
        if invoked not in launchers or executable.name.lower() not in ('python.exe', 'pythonw.exe'):
            return ''
        if executable not in launchers:
            # Windows venv launchers delegate to the base interpreter. Its
            # image path differs while argv[0] remains the owned launcher.
            config = app / '.venv/pyvenv.cfg'
            if not config.is_file() or config.is_symlink() or config.stat().st_size > 16384:
                return ''
            settings = dict(line.split(' = ', 1) for line in config.read_text(encoding='utf-8').splitlines() if ' = ' in line)
            base = settings.get('home')
            if not base or executable != Path(base).resolve() / executable.name:
                return ''
    return _python_role(app, arguments)


def _stop_owned(profile, holders, report):
    commands = _process_commands(holders)
    owned = [(holder, _owned_role(profile, holder, commands.get(holder.process.pid, ''))) for holder in holders]
    desktops = [holder for holder, role in owned if role == 'desktop']
    if desktops:
        for root in (profile / 'ArchHub', profile / 'ArchHub-Test'):
            if root.is_dir():
                (root / 'quit-request').write_text('Setup clean close\n', encoding='ascii')
        report('Waiting for ArchHub clean close: ' + _holder_names(desktops))
    for holder, role in owned:
        if not role:
            continue
        with _process_handle(holder) as (handle, kernel):
            if handle is None:
                continue
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
            if kernel.WaitForSingleObject(handle, 0) == 0:
                continue
            if role == 'desktop' and kernel.WaitForSingleObject(handle, 90000) == 0:
                continue
            report('Stopping ArchHub journal holder: ' + _holder_names([holder]))
            if not kernel.TerminateProcess(handle, 0) or kernel.WaitForSingleObject(handle, 10000) != 0:
                raise OSError('Cannot stop journal holder: ' + _holder_names([holder]))


def _fold(path, report, *, timeout_seconds: float = 2):
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=timeout_seconds, isolation_level=None)) as db:
        # Normal SQLite recovery, including an abandoned rollback transaction.
        # Exclusive mode retains SQLite's lock after COMMIT until close, so an
        # arriving connection cannot write concurrently with this checkpoint.
        db.execute('PRAGMA locking_mode=EXCLUSIVE')
        db.execute('BEGIN EXCLUSIVE')
        db.execute('SELECT COUNT(*) FROM sqlite_schema').fetchone()
        db.execute('COMMIT')
        result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if result[0] != 0 or result[1] not in (0, -1) or result[2] not in (0, -1):
            raise OSError('SQLite checkpoint is busy: ' + str(path))
        check = db.execute('PRAGMA quick_check(1)').fetchone()
        if check != ('ok',):
            raise ValueError('SQLite verification failed: ' + str(path) + ': ' + str(check))
    report('Closed SQLite verified: %s checkpoint=%s quick_check=ok' % (path, result))


@contextmanager
def closed_profile(profile, candidates, lease, report):
    """Fold every selected graph/companion and retain leases through backup."""
    paths = list(dict.fromkeys(p for source in candidates for p in
        (source, Path(str(source) + '.conversations.sqlite3'), Path(str(source) + '.accelerators')) if p.is_file()))
    for path in paths:
        if path.resolve() != path.absolute() or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise ValueError('Installer journal path contains a link: ' + str(path))
        for suffix in ('-wal', '-shm', '-journal'):
            side = Path(str(path) + suffix)
            if side.is_symlink() or side.is_junction():
                raise ValueError('Installer journal sidecar is a link: ' + str(side))
    if not paths:
        yield
        return
    with ExitStack() as stack:
        holders = stack.enter_context(_Holders(paths)) if os.name == 'nt' else None
        for attempt in range(3):
            if holders:
                _stop_owned(profile, holders.list(), report)
            leases = ExitStack()
            try:
                for path in paths:
                    # Probe custody before any SQLite write: an unknown live
                    # writer must not race the checkpoint on older runtimes.
                    with lease(path):
                        pass
                    _fold(path, report)
                    leases.enter_context(lease(path))
                    if any(Path(str(path) + s).exists() and Path(str(path) + s).stat().st_size for s in ('-wal', '-journal')):
                        raise OSError('Journal changed while closing: ' + str(path))
            except (OSError, sqlite3.OperationalError) as error:
                leases.close()
                live = holders.list() if holders else []
                if attempt == 2 or not live:
                    raise OSError('Cannot close SQLite journals: %s; holders: %s' % (error, _holder_names(live))) from error
                report('Retrying journal clean close: ' + _holder_names(live))
            except BaseException:
                leases.close()
                raise
            else:
                with leases:
                    yield
                return
