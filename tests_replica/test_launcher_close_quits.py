import os
import subprocess
import sys
import textwrap
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WM_CLOSE = 0x0010


def test_launcher_tray_wiring_keeps_main_window_close_as_quit():
    source = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "keeps running in the background" not in source
    assert "Closing any ArchHub top-level window quits" in source
    assert "app.setQuitOnLastWindowClosed(True)" in source


def _visible_archhub_windows_for_pid(pid):
    user32 = ctypes.windll.user32
    handles = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def collect(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if title.value.startswith("ArchHub"):
            handles.append((hwnd, title.value))
        return True

    user32.EnumWindows(collect, 0)
    return handles


def _process_ids_by_name(name):
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return set()

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    found = set()
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name.lower():
                found.add(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def _kill_process(pid):
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x0001, False, pid)
    if handle:
        try:
            kernel32.TerminateProcess(handle, 0)
        finally:
            kernel32.CloseHandle(handle)


def _job_kill_on_close(process_handle):
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x00002000
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(job)
        return None
    if not kernel32.AssignProcessToJobObject(job, process_handle):
        kernel32.CloseHandle(job)
        return None
    return job


def _kill_descendants_of(pid):
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    children = []
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32ParentProcessID == pid:
                children.append(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    for child in children:
        _kill_descendants_of(child)
        _kill_process(child)


def test_launcher_real_shell_wm_close_exits_subprocess_within_10s(tmp_path):
    if sys.platform != "win32":
        pytest.skip("real WM_CLOSE court is Windows-only")
    pytest.importorskip("PyQt6")
    existing_webengine = _process_ids_by_name("QtWebEngineProcess.exe")
    script = textwrap.dedent(
        """
        import os
        import sys
        from pathlib import Path
        from nodelang import desktop

        class FakeRuntime:
            schema_version = 1

            def start(self):
                return self

            def document_url_for(self, _schema):
                page = Path(os.environ["ARCHHUB_TEST_STATE_DIR"]) / "fake-studio.html"
                page.write_text("<!doctype html><title>ArchHub fake</title><main>fake gateway</main>", encoding="utf-8")
                return page.as_uri()

            def close(self):
                pass

        desktop.DesktopRuntime = FakeRuntime
        desktop.runtime_lock_path = lambda: Path(os.environ["ARCHHUB_TEST_STATE_DIR"]) / "desktop.lock"
        raise SystemExit(desktop.main())
        """
    )
    env = {
        **os.environ,
        "ARCHHUB_TEST_STATE_DIR": str(tmp_path),
        "LOCALAPPDATA": str(tmp_path),
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --single-process --no-sandbox",
        "QT_OPENGL": "software",
    }
    proc = subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, env=env)
    job = _job_kill_on_close(int(proc._handle))
    windows = []
    try:
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                windows = _visible_archhub_windows_for_pid(proc.pid)
                if windows:
                    break
                if proc.poll() is not None:
                    raise AssertionError("real shell exited before an ArchHub HWND appeared")
                time.sleep(0.1)
            assert windows, "real shell did not expose a visible ArchHub HWND"
            started = time.monotonic()
            for hwnd, _title in windows:
                ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            titles = ", ".join(title for _, title in windows) if windows else "none"
            raise AssertionError("WM_CLOSE left the launcher subprocess alive after 10s; hwnd titles: " + titles)
        elapsed = time.monotonic() - started
        assert code == 0
        assert elapsed <= 10.0
    finally:
        _kill_descendants_of(proc.pid)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if job:
            ctypes.windll.kernel32.CloseHandle(job)
        _kill_descendants_of(proc.pid)
        for pid in _process_ids_by_name("QtWebEngineProcess.exe") - existing_webengine:
            _kill_process(pid)
