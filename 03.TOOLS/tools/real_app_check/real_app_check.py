"""Real-app acceptance check: the INSTALLED ArchHub desktop app, driven on a hidden Windows desktop.

The founder's binding order: no ArchHub task is accepted without real-app evidence, meaning the
installed build, isolated, on a hidden desktop, with one screenshot per step (what was asked, what the
real window did). Every agent uses this one tool.

    python -B tools/real_app_check/real_app_check.py --scenario tools/real_app_check/scenarios/smoke.mjs \
        --out <new evidence dir> [--app <installed dir>] [--overlay <candidate dir>] [--input <json file>]

Guarantees:
  * A hidden desktop with a run-unique name (CreateDesktopW). The report proves the app's window is on
    it and belongs to this run's own processes. Native dialogs open there; pywinauto drives them there.
  * Isolated profile: APPDATA, LOCALAPPDATA, USERPROFILE (with its shell folders), HOME, TEMP,
    CLAUDE_CONFIG_DIR and ARCHHUB_TEST_STATE_DIR point into the run folder; agent/session variables
    are dropped; own lock and CDP ports; no bytecode; the launch directory is the run folder. The
    report proves the app wrote its state there.
  * The installed tree is never modified: its code is hashed before and after the run. With --overlay,
    only files under the code allowlist are laid over a copy of that code (contained, no links), and
    every report row says "CANDIDATE OVERLAY". Overlay Studio .jsx sources are compiled with this
    repository's packaging/compile_studio.cjs.
  * One Windows Job object (kill on close) owns the app, the probe and every winapp helper; every wait
    is bounded; the job is terminated in `finally` on every exit path.
  * No signing-key read: NoGraph uses plain workspace settings; the disposable run never opens CNG.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from ctypes import wintypes as w
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if REPO.name == "03.TOOLS":
    REPO = REPO.parent
DEFAULT_WINAPP = shutil.which("winapp") or ""
# The installed tree's code; never its data (the installed folder also holds the founder's state).
CODE_ENTRIES = ("nodelang", "app", "runtime", "governed-bin", "workflows", "library", "custom_nodes",
                "ui_widgets", "skills", "VERSION", "BUILD_ID",
                "BUILD_METADATA.json", "version.json", "archhub.ico", "HOST_ARTIFACTS.json", "LICENSE",
                "requirements.txt")
# An overlay may only replace or add files under these code roots.
OVERLAY_ROOTS = ("nodelang", "app", "runtime", "workflows", "library", "custom_nodes", "ui_widgets",
                 "skills")
DROPPED_ENV = ("CLAUDE", "ARCHHUB", "WORKSHOP", "CODEX", "ANTHROPIC", "PYTHON")
OVERLAY_LABEL = "CANDIDATE OVERLAY"
INSTALLED_LABEL = "INSTALLED BUILD"


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def isolated_env(base: dict, root: Path, *, cdp_port: int | None = None, lock_port: int | None = None) -> dict:
    """The app's whole environment: base minus agent/session variables, every profile path in root."""
    env = {key: value for key, value in base.items() if not key.upper().startswith(DROPPED_ENV)}
    for key in ("ARCHHUB_PROFILE_GUARD_LOG", "ARCHHUB_PROFILE_GUARD_ROOTS",
                "ARCHHUB_COURT_SOURCE", "ARCHHUB_OLD_GRAPH_SOURCE"):
        if key in base:
            env[key] = base[key]
    env.setdefault("ARCHHUB_PROFILE_GUARD_LOG", str(root / "PROFILE-WRITES.jsonl"))
    for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP"):
        env[name] = str(root / name)
    env.update(HOME=env["USERPROFILE"], TMP=env["TEMP"], CLAUDE_CONFIG_DIR=str(root / "claude-config"),
               ARCHHUB_TEST_STATE_DIR=str(root / "state"), ARCHHUB_VERIFY_NO_GPU="1",
               PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    if cdp_port is not None:
        env["QTWEBENGINE_REMOTE_DEBUGGING"] = "127.0.0.1:%d" % cdp_port
    if lock_port is not None:
        env["ARCHHUB_TEST_LOCK_PORT"] = str(lock_port)
    for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "ARCHHUB_TEST_STATE_DIR"):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    return env


def _profile_guard():
    # Absolute sibling import also works when loaded by path or from installed Python with -I.
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_profile_guard", HERE / "profile_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_digest(root: Path, entries=CODE_ENTRIES) -> str:
    """sha256 over every source file's path and bytes under the given code entries. Bytecode caches
    are left out: the founder's own running app shares the installed tree and may write them."""
    digest = hashlib.sha256()
    for entry in entries:
        base = root / entry
        files = ([base] if base.is_file() else
                 sorted(path for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts
                        and path.suffix not in (".pyc", ".pyo")) if base.is_dir() else [])
        for path in files:
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def overlay_files(overlay: Path) -> list:
    """The overlay's files, each under an allowed code root, contained, and not a link."""
    root = overlay.resolve()
    chosen = []
    for path in sorted(overlay.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("overlay holds a link: %s" % path)
        if not path.is_file():
            continue
        relative = path.relative_to(overlay)
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or ".." in relative.parts:
            raise ValueError("overlay path escapes its folder: %s" % relative)
        if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if relative.parts[0] not in OVERLAY_ROOTS:
            raise ValueError("overlay path is outside the code allowlist: %s" % relative.as_posix())
        chosen.append(relative)
    return chosen


def stage_app(installed: Path, overlay: Path | None, run_dir: Path, *, repo: Path = REPO) -> tuple[Path, str, list]:
    """The tree to launch and its label. Without an overlay that is the installed tree itself."""
    if overlay is None:
        return installed, INSTALLED_LABEL, []
    files = overlay_files(overlay)
    app = run_dir / "app"
    app.mkdir(parents=True)
    for entry in CODE_ENTRIES:
        source = installed / entry
        if source.is_dir():
            shutil.copytree(source, app / entry, ignore=shutil.ignore_patterns("__pycache__"))
        elif source.is_file():
            shutil.copy2(source, app / entry)
    laid = []
    for relative in files:
        target = (app / relative).resolve()
        if not target.is_relative_to(app.resolve()):
            raise ValueError("overlay target escapes the copy: %s" % relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(overlay / relative, target)
        laid.append(relative.as_posix())
    if any(name.startswith("nodelang/studio/") and name.endswith(".jsx") for name in laid):
        (app / "packaging").mkdir(exist_ok=True)
        shutil.copy2((repo / "03.TOOLS/packaging" if (repo / "03.TOOLS").is_dir() else repo / "packaging") / "compile_studio.cjs", app / "packaging" / "compile_studio.cjs")
        for name in ("package.json", "package-lock.json"):
            shutil.copy2(repo / name, app / name)
        compiled = subprocess.run(["node", "packaging/compile_studio.cjs"], cwd=app, capture_output=True,
                                  text=True, timeout=600)
        if compiled.returncode != 0:
            raise SystemExit("Studio recompile refused: " + (compiled.stdout + compiled.stderr)[-600:])
        laid.append("compiled Studio: " + compiled.stdout.strip()[-200:])
    return app, OVERLAY_LABEL, laid


def json_tail(raw: str):
    """winapp prints progress before its JSON; parse from the first object or array."""
    starts = [index for index in (raw.find("{"), raw.find("[")) if index >= 0]
    if not starts:
        raise ValueError("no JSON in winapp output")
    return json.loads(raw[min(starts):])


def pick_edit_slug(search: object, label: str) -> str:
    """From `winapp ui search <label> --json`, the selector of the one Edit with that label.

    The folder dialog names both its Text label and its Edit field "Folder:"; the Edit is chosen by
    element type, and exactly one must exist."""
    rows = search
    if isinstance(search, dict):
        lists = [value for value in search.values() if isinstance(value, list)
                 and all(isinstance(item, dict) for item in value)]
        rows = lists[0] if len(lists) == 1 else []
    edits = [row for row in rows or () if isinstance(row, dict)
             and str(row.get("type") or row.get("controlType") or "").lower() in ("edit", "textbox")
             and str(row.get("name") or "") == label]
    if len(edits) != 1:
        raise ValueError("expected exactly one Edit named %r, found %d" % (label, len(edits)))
    return str(edits[0].get("slug") or edits[0].get("selector"))


def run_result(steps: list, problems: list) -> str:
    """PASS only when every step passed and no run-level gate failed. A step that was not exercised
    makes the run INCOMPLETE, never PASS; any failed step or gate makes it FAIL."""
    failed = [row["asked"] for row in steps if row.get("result") not in ("PASS", "NOT EXERCISED")]
    skipped = [row["asked"] for row in steps if row.get("result") == "NOT EXERCISED"]
    if not steps:
        problems = [*problems, "FAIL: no step ran"]
    if failed:
        problems = [*problems, "FAIL: step(s) failed: " + "; ".join(failed)]
    if problems:
        return "; ".join(problems)
    if skipped:
        return "INCOMPLETE: not exercised: " + "; ".join(skipped)
    return "PASS"


def probe_problems(lines: list, exit_code, timed_out: bool, steps: list) -> list:
    """The probe passes only when it declared its steps, ran exactly those, said DONE and exited 0.
    Anything else is a failed run, whatever the rows say."""
    problems = []
    if timed_out:
        problems.append("FAIL: the scenario probe timed out")
    if exit_code != 0:
        problems.append("FAIL: the scenario probe exited with %r" % (exit_code,))
    if not any(str(line).startswith("DONE ") for line in lines):
        problems.append("FAIL: the scenario probe never reported DONE")
    declared = None
    for line in lines:
        if str(line).startswith("DECLARED "):
            try:
                declared = json.loads(str(line)[len("DECLARED "):])
            except ValueError:
                declared = None
            break
    observed = [row.get("asked") for row in steps]
    if not isinstance(declared, list) or not declared:
        problems.append("FAIL: the scenario declared no steps")
    elif observed != declared:
        problems.append("FAIL: the steps that ran differ from the declared steps (declared %d, ran %d)"
                        % (len(declared), len(observed)))
    return problems


# --- Windows plumbing: one hidden desktop and one Job object own everything this run starts. -------

class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("r", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("t", w.LPWSTR)] + \
               [(n, w.DWORD) for n in ("x", "y", "xs", "ys", "xc", "yc", "fa", "flags")] + \
               [("show", w.WORD), ("cb2", w.WORD), ("r2", ctypes.c_void_p),
                ("i", w.HANDLE), ("o", w.HANDLE), ("e", w.HANDLE)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class RunJob:
    """A Job object with KILL_ON_JOB_CLOSE: every process this run starts belongs to it, and closing
    it ends them all. No numeric PID is ever killed."""

    def __init__(self):
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.CreateJobObjectW.restype = w.HANDLE
        self.handle = self.k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k32.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())

    def adopt(self, process_handle) -> None:
        if not self.k32.AssignProcessToJobObject(self.handle, w.HANDLE(process_handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def pids(self) -> list:
        class List(ctypes.Structure):
            _fields_ = [("assigned", w.DWORD), ("listed", w.DWORD), ("ids", ctypes.c_size_t * 4096)]
        listed = List()
        if not self.k32.QueryInformationJobObject(self.handle, 3, ctypes.byref(listed), ctypes.sizeof(listed), None):
            return []
        return [int(listed.ids[index]) for index in range(listed.listed)]

    def close(self) -> None:
        if self.handle:
            self.k32.TerminateJobObject(self.handle, 1)
            self.k32.CloseHandle(self.handle)
            self.handle = None


class JobRunner:
    """subprocess.run for the run's helper children. Each starts suspended and, before its first
    instruction, joins the run's Job and its own Job nested inside it (both verified); it keeps its handle
    and is waited on with a bound. When it ends (or passes its bound) its own Job is terminated, which
    ends every descendant it left (a python.exe redirector leaves one), and the runner waits, bounded,
    until that Job is empty. leftovers() lists every process still alive in the run's Job."""

    job_owned = True
    SETTLE_SECONDS = 15

    def __init__(self, job: RunJob):
        self.job, self.children = job, []
        self.ntdll = ctypes.WinDLL("ntdll")
        self.ntdll.NtResumeProcess.argtypes = [w.HANDLE]
        self.ntdll.NtResumeProcess.restype = ctypes.c_long

    def __call__(self, command, *, env=None, cwd=None, capture_output=True, text=True, timeout=120):
        own = RunJob()
        process = None
        try:
            process = subprocess.Popen(_profile_guard().command(command), env=env, cwd=cwd,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace",
                                       creationflags=0x00000004 | 0x08000000)
            record = {"pid": process.pid, "command": [str(part)[:80] for part in command[:3]]}
            self.children.append(record)
            self.job.adopt(int(process._handle))
            own.adopt(int(process._handle))          # nested in the run's Job
            if process.pid not in self.job.pids() or process.pid not in own.pids():
                raise RuntimeError("helper %d did not join the run's Job" % process.pid)
            if self.ntdll.NtResumeProcess(w.HANDLE(int(process._handle))) != 0:
                raise RuntimeError("helper %d could not be resumed" % process.pid)
            try:
                out, err = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._end(own, record)
                out, err = process.communicate(timeout=10)
                record.update(timed_out=True, exit_code=process.returncode)
                return subprocess.CompletedProcess(command, -1, out, (err or "") + "\ntimed out after %ds" % timeout)
            record["exit_code"] = process.returncode
            return subprocess.CompletedProcess(command, process.returncode, out, err)
        finally:
            if process is not None and self.children and self.children[-1].get("pid") == process.pid:
                self._end(own, self.children[-1])
            own.close()
            if process is not None and process.poll() is None:
                process.kill()                       # its own handle, never a PID lookup
                process.communicate(timeout=10)

    def _end(self, own: RunJob, record: dict) -> None:
        """Terminate the helper's own Job and wait, bounded, until nothing in it is still alive."""
        own.k32.TerminateJobObject(own.handle, 1)
        deadline = time.monotonic() + self.SETTLE_SECONDS
        while own.pids() and time.monotonic() < deadline:
            time.sleep(0.1)
        record["left_alive"] = own.pids()
        if record["left_alive"]:
            raise RuntimeError("helper %d left %r alive past %ds" % (record["pid"], record["left_alive"],
                                                                   self.SETTLE_SECONDS))

    def leftovers(self) -> list:
        return self.job.pids()


class HiddenDesktop:
    """A new hidden desktop with a run-unique name; processes started here draw nowhere visible."""

    def __init__(self, job: RunJob, name: str | None = None):
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.job, self.name = job, name or "ArchHubRealAppCheck-" + uuid.uuid4().hex[:12]
        self.u32.OpenDesktopW.restype = w.HANDLE
        if self.u32.OpenDesktopW(self.name, 0, False, 0x0001):
            raise RuntimeError("desktop %s already exists; refusing to share it" % self.name)
        self.u32.CreateDesktopW.restype = w.HANDLE
        self.handle = self.u32.CreateDesktopW(self.name, None, None, 0, 0x10000000, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def spawn(self, cmdline: str, *, env: dict | None = None, cwd: str | None = None) -> _ProcessInfo:
        """Start a process on this desktop, suspended, inside the run's Job, then let it run."""
        si, pi = _StartupInfo(), _ProcessInfo()
        si.cb, si.lpDesktop = ctypes.sizeof(si), self.name
        block = (ctypes.create_unicode_buffer("".join("%s=%s\0" % kv for kv in env.items()) + "\0")
                 if env is not None else None)
        flags = 0x08000000 | 0x00004000 | 0x00000004 | (0x400 if env is not None else 0)
        if not self.k32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None, None, False, flags,
                                       block, cwd, ctypes.byref(si), ctypes.byref(pi)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.job.adopt(pi.hProcess)
        except OSError:
            self.k32.TerminateProcess(pi.hProcess, 1)
            raise
        self.k32.ResumeThread(pi.hThread)
        return pi

    def run(self, cmdline: str, timeout: int = 30, *, env=None, cwd=None) -> str:
        """Run one short command ON the hidden desktop (UI Automation sees that desktop only)."""
        handle, name = tempfile.mkstemp(suffix=".txt", dir=cwd)
        os.close(handle)
        out = Path(name)
        pi = self.spawn('cmd.exe /d /c "%s > "%s" 2>&1"' % (cmdline, out), env=env, cwd=cwd)
        try:
            if self.k32.WaitForSingleObject(pi.hProcess, timeout * 1000) != 0:
                self.k32.TerminateProcess(pi.hProcess, 1)   # its own handle, never a PID lookup
            return out.read_text(encoding="utf-8", errors="replace")
        finally:
            self.k32.CloseHandle(pi.hProcess); self.k32.CloseHandle(pi.hThread)
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass

    def windows(self) -> list:
        """Visible top-level windows on THIS desktop: (owning pid, title)."""
        found = []
        callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

        def visit(hwnd, _):
            if self.u32.IsWindowVisible(hwnd):
                pid, length = w.DWORD(), self.u32.GetWindowTextLengthW(hwnd)
                self.u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                title = ctypes.create_unicode_buffer(length + 1)
                self.u32.GetWindowTextW(hwnd, title, length + 1)
                found.append((int(pid.value), title.value))
            return True
        self.u32.EnumDesktopWindows(w.HANDLE(self.handle), callback(visit), 0)
        return found

    def close(self) -> None:
        if self.handle:
            self.u32.CloseDesktop(w.HANDLE(self.handle))
            self.handle = None


def native_application(cache):
    """Keep generated COM wrappers in this run, never in the installed environment."""
    import types
    import comtypes
    cache.mkdir(parents=True, exist_ok=True)
    generated = types.ModuleType('comtypes.gen')
    generated.__path__ = [str(cache)]
    sys.modules['comtypes.gen'] = comtypes.gen = generated
    from pywinauto import Application
    return Application


def native_folder_action(request):
    """Invoke only a folder dialog owned by this rig, on this hidden desktop."""
    user = ctypes.windll.user32
    user.GetThreadDesktop.argtypes, user.GetThreadDesktop.restype = (w.DWORD,), w.HANDLE
    user.GetUserObjectInformationW.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD))
    user.GetWindowThreadProcessId.argtypes = (w.HWND, ctypes.POINTER(w.DWORD))
    user.GetWindowTextLengthW.argtypes = (w.HWND,)
    user.GetWindowTextW.argtypes = (w.HWND, w.LPWSTR, ctypes.c_int)
    desktop = user.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
    name, needed = ctypes.create_unicode_buffer(256), w.DWORD()
    if not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
        raise RuntimeError("Cannot verify the native worker desktop")
    if name.value.casefold() != request['desktop'].split('\\')[-1].casefold() or name.value.casefold() == 'default':
        raise RuntimeError("Native worker is outside the rig desktop")
    allowed = set(request['pids'])
    handles = []
    callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    def visit(handle, _):
        pid = w.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        title = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(handle) + 1)
        user.GetWindowTextW(handle, title, len(title))
        if pid.value in allowed and title.value == request['title']:
            handles.append(handle)
        return True
    user.EnumDesktopWindows.argtypes = (w.HANDLE, callback, w.LPARAM)
    user.EnumDesktopWindows(desktop, callback(visit), 0)
    if len(handles) != 1:
        raise RuntimeError("Expected one folder dialog owned by the rig")
    Application = native_application(Path(os.environ['LOCALAPPDATA']) / 'comtypes')
    dialog = Application(backend='uia').connect(handle=handles[0]).window(handle=handles[0])
    edits = dialog.descendants(control_type='Edit')
    named = [edit for edit in edits if edit.element_info.name.rstrip(':').casefold() in
             {'folder', 'folder name', 'file name'}]
    edits = named or edits
    if len(edits) != 1:
        raise RuntimeError("Folder dialog Edit is ambiguous")
    edits[0].set_edit_text(request['folder'])
    if edits[0].get_value() != request['folder']:
        raise RuntimeError("Folder field readback differs")
    dialog.child_window(auto_id='1', control_type='Button').invoke()
    dialog.wait_not('exists')
    return {'title': request['title'], 'folder': request['folder'], 'closed': True}


def pick_folder(desktop: HiddenDesktop, python: str, title: str, folder: str, evidence: Path, env) -> dict:
    request = evidence / 'native-folder-request.json'
    request.write_text(json.dumps({'title': title, 'folder': folder, 'desktop': desktop.name,
                                  'pids': desktop.job.pids()}), encoding='utf-8')
    command = subprocess.list2cmdline([python, str(HERE / 'real_app_check.py'), '--native-folder', str(request)])
    return json_tail(desktop.run(command, 30, env=env, cwd=str(evidence)))


def agent_propose(runner, python: Path, app: Path, run_dir: Path, env: dict, title: str) -> dict:
    """A run-local agent session proposes one Work through the product's own native.work_propose,
    as a Job-owned helper under the app's environment and against this run's runtime descriptor."""
    session_id = str(uuid.uuid4())
    done = runner([str(python), "-B", str(HERE / "agent_propose.py"), str(app),
                   str(run_dir / "state" / "runtime-descriptor.json"), session_id, title],
                  env=env, cwd=str(run_dir), timeout=180)
    answer = {"kind": "agent-propose", "title": title, "external_session_id": session_id,
              "exit_code": done.returncode}
    try:
        answer.update(json.loads(done.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        answer["error"] = "the agent did not propose: " + (done.stderr or done.stdout)[-600:]
    return answer


def _graph_owner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("graph_owner", HERE / "graph_owner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lines(stream, sink: queue.Queue) -> None:
    for line in stream:
        sink.put(line)
    sink.put(None)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) == 2 and arguments[0] == '--native-folder':
        request = Path(arguments[1])
        if request.stat().st_size > 65536:
            raise ValueError('Native request exceeds its bound')
        print(json.dumps(native_folder_action(json.loads(request.read_text(encoding='utf-8')))))
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--app", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "ArchHub")
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--input", type=Path, help="JSON handed to the scenario as ctx.input")
    parser.add_argument("--winapp", default=os.environ.get("ARCHHUB_WINAPP", DEFAULT_WINAPP))
    parser.add_argument("--boot-seconds", type=int, default=600)
    parser.add_argument("--probe-seconds", type=int, default=1200)
    args = parser.parse_args(argv)

    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit("evidence directory must be new or empty: %s" % out)
    out.mkdir(parents=True, exist_ok=True)
    _profile_guard().install(out / "PROFILE-WRITES.jsonl")
    installed = args.app.resolve()
    python = installed / ".venv" / "Scripts" / "python.exe"
    report = {"installed": str(installed), "signing_key_before": "not-used-nograph",
              "installed_code_before": tree_digest(installed)}
    job = desktop = probe = None
    failures, lines, timed_out, exit_code = [], [], False, None
    try:
        job = RunJob()
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=out))
        app, label, laid = stage_app(installed, args.overlay.resolve() if args.overlay else None, run_dir)
        for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "claude-config", "state"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        # Shell folders the Windows file dialogs list; without them a second error window opens.
        for name in ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"):
            (run_dir / "USERPROFILE" / name).mkdir(exist_ok=True)
        cdp = free_port()
        env = isolated_env(dict(os.environ), run_dir, cdp_port=cdp, lock_port=free_port())
        desktop = HiddenDesktop(job)
        report.update(label=label, build=(app / "BUILD_ID").read_text(encoding="utf-8").strip(), app=str(app),
                      overlay=str(args.overlay) if args.overlay else None, overlay_files=laid,
                      desktop=desktop.name, isolated_root=str(run_dir), launch_cwd=str(run_dir), cdp_port=cdp)
        # The run's NoGraph listener is admitted by profile paths, marker, endpoint and Job ownership.
        owner_module = _graph_owner()
        owner_plan = owner_module.plan_graph_owner(run_dir, env)
        owner = owner_module.launch_nograph_owner(desktop, owner_plan, str(python), app,
                                                  runner=JobRunner(job), health_seconds=args.boot_seconds)
        report["nograph_owner"] = owner
        env = owner_plan["env"]
        # launch_nograph_owner already started the Qt desktop.
        # The rig observes that same process instead of opening another app.
        report["owner_pid"] = owner["pid"]
        started = time.monotonic()
        studio_open = False
        while time.monotonic() - started < args.boot_seconds:
            try:
                pages = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % cdp, timeout=2))
                if any("/studio" in page.get("url", "") for page in pages):
                    studio_open = True
                    break
            except Exception:
                pass
            time.sleep(2)
        report["boot_seconds"] = round(time.monotonic() - started)
        report["studio_open"] = studio_open
        if not studio_open:
            raise RuntimeError("The isolated NoGraph server is ready but Studio did not open")
        ours = set(job.pids())
        report["app_windows_on_desktop"] = [title for pid, title in desktop.windows() if pid in ours and title]
        report["state_written_in_run_folder"] = sorted(path.name for path in (run_dir / "state").iterdir())[:20]
        probe = subprocess.Popen(["node", str(HERE / "harness.mjs"), str(args.scenario.resolve())], cwd=str(HERE),
                                 text=True, encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=env)
        job.adopt(int(probe._handle))
        scenario_input = json.loads(args.input.read_text(encoding="utf-8")) if args.input else None
        probe.stdin.write(json.dumps({"cdp": cdp, "out": str(out), "label": label, "input": scenario_input}) + "\n")
        probe.stdin.flush()
        natives, sink = [], queue.Queue()
        report["native"] = natives
        threading.Thread(target=_lines, args=(probe.stdout, sink), daemon=True).start()
        deadline = time.monotonic() + args.probe_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                line = sink.get(timeout=remaining)
            except queue.Empty:
                timed_out = True
                break
            if line is None:
                break
            lines.append(line.rstrip())
            if line.startswith("NATIVE "):
                request = json.loads(line[len("NATIVE "):])
                if request.get("kind") == "pick-folder":
                    answer = pick_folder(desktop, str(python), request["title"], request["folder"], out, env)
                elif request.get("kind") == "agent-propose":
                    answer = agent_propose(JobRunner(job), python, app, run_dir, env, str(request["title"])[:200])
                else:
                    answer = {"error": "unknown native request"}
                natives.append(answer)
                probe.stdin.write(json.dumps(answer) + "\n")
                probe.stdin.flush()
        if not timed_out:
            try:
                exit_code = probe.wait(timeout=30)
            except subprocess.TimeoutExpired:
                timed_out = True
    except BaseException as exc:  # noqa: BLE001 - the report records it; the run fails
        import traceback
        failures.append("FAIL: the run raised %s: %s" % (type(exc).__name__, str(exc)[:300]))
        if getattr(exc, "problems", None):
            report["graph_owner_refused"] = list(exc.problems)
        report["exception"] = traceback.format_exc()[-3000:]
    finally:
        if job is not None:
            job.close()                      # ends the app, the probe and any helper, by Job, not by PID
        if desktop is not None:
            desktop.close()
        report["probe"], report["probe_exit_code"], report["probe_timed_out"] = lines, exit_code, timed_out
        result = finalize_report(report, out, installed, failures)
    return result


def finalize_report(report: dict, out: Path, installed: Path, failures: list) -> int:
    """Always record the code digest, every gate and report.json without opening keys."""
    for name, read in (("signing_key_after", lambda: "not-used-nograph"), ("installed_code_after", lambda: tree_digest(installed))):
        try:
            report[name] = read()
        except Exception as exc:  # noqa: BLE001 - an unreadable state is not a pass
            report[name] = "unreadable:%s" % type(exc).__name__
    steps_file = out / "steps.json"
    try:
        steps = json.loads(steps_file.read_text(encoding="utf-8")) if steps_file.exists() else []
    except ValueError:
        steps, failures = [], [*failures, "FAIL: steps.json is unreadable"]
    problems = [*failures, *[problem for problem in (
        None if report["installed_code_after"] == report.get("installed_code_before") else "FAIL: the installed code changed",
        None if report.get("app_windows_on_desktop") else "FAIL: no window of this run's app was found on its hidden desktop",
        None if report.get("state_written_in_run_folder") else "FAIL: the app wrote no state in the run folder",
    ) if problem], *probe_problems(report.get("probe", []), report.get("probe_exit_code"),
                                   report.get("probe_timed_out", True), steps)]
    report["result"] = run_result(steps, problems)
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ("probe", "exception")},
                     indent=1, ensure_ascii=False)[:4000])
    for row in steps:
        print("%s | %s | %s | %s" % (row.get("result"), row.get("asked"), row.get("did"), Path(str(row.get("shot"))).name))
    return 0 if report["result"] == "PASS" else 2 if report["result"].startswith("INCOMPLETE") else 1


if __name__ == "__main__":
    sys.exit(main())
