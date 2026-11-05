"""One launcher. A dead lock holder is taken over; a live answering one stays.

A process that is not this product's launcher is never stopped, so a held
bridge in Revit or AutoCAD is not a reason to close that host.
"""
import ast
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "01.APP" / "nodelang" / "launcher.py"


def _functions():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {"Path": Path, "time": time, "os": __import__("os"), "sys": sys, "__file__": str(LAUNCHER)}
    exec(compile(ast.Module(body=defs, type_ignores=[]), str(LAUNCHER), "exec"), namespace)
    return namespace


def test_a_live_answering_launcher_is_left_and_a_silent_one_is_stopped():
    decision = _functions()["_lock_takeover_decision"]
    assert decision(True, True, True, 3600, True) == "leave"
    assert decision(True, True, False, 10, True) == "leave"
    assert decision(True, True, False, 120, True) == "stop"
    assert decision(False, False, False, 0, False) == "bind"
    assert decision(False, False, False, 0, True) == "leave"


def test_a_foreign_holder_stays_and_a_dead_holder_lets_the_new_launch_bind():
    functions = _functions()
    release = functions["_release_unanswering_holder"]
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import socket,sys,time\n"
         "s=socket.socket()\n"
         "s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)\n"
         "s.bind(('127.0.0.1', int(sys.argv[1])))\n"
         "s.listen(1)\n"
         "time.sleep(30)\n",
         str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                watch = socket.socket()
                watch.bind(("127.0.0.1", port))
                watch.close()
            except OSError:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the foreign holder never bound the lock port")
        assert release(port, Path(".")) is False
        assert holder.poll() is None
    finally:
        holder.kill()
        holder.wait(timeout=5)
    assert release(port, Path(".")) is True
    taken = socket.socket()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        taken.bind(("127.0.0.1", port))
        taken.listen(1)
    finally:
        taken.close()


def _pyqt6_package():
    """The base prefix ships a PyQt6 namespace without QtCore. The bindings are in the user site."""
    version = "Python%d%d" % sys.version_info[:2]
    candidates = [Path(sys.base_prefix) / "Lib" / "site-packages" / "PyQt6"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Python" / version / "site-packages" / "PyQt6")
    try:
        import ctypes
        name = ctypes.create_unicode_buffer(256)
        size = ctypes.c_uint(256)
        if ctypes.windll.advapi32.GetUserNameW(name, ctypes.byref(size)):
            candidates.append(Path(r"C:\Users") / name.value / "AppData" / "Roaming" / "Python" / version / "site-packages" / "PyQt6")
    except OSError:
        pass
    for candidate in candidates:
        if (candidate / "QtCore.pyd").is_file():
            return candidate
    raise AssertionError("PyQt6.QtCore is not installed for this interpreter: " + ", ".join(map(str, candidates)))


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _matching_pids(root, script):
    import psutil
    needle_root = str(root).casefold()
    needle_script = script.casefold()
    found = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            text = " ".join(process.info.get("cmdline") or [])
        except (psutil.Error, OSError):
            continue
        folded = text.casefold()
        if needle_root in folded and needle_script in folded:
            found.append(process.info["pid"])
    return found


def _alive(pid):
    import psutil
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.Error, OSError):
        return False


def _kill_pids(pids):
    import psutil
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except (psutil.Error, OSError):
            continue
    deadline = time.time() + 5
    while time.time() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)


def _wait_until(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    return None


def test_real_entry_chain_opens_one_window(tmp_path):
    """The installed chain: ArchHub.vbs, then one window, one maintainer.

    The venv pythonw redirector is the parent of the interpreter and carries
    the same launcher command line. This launch must leave that parent alive
    and still open. A second launch leaves the answering one alone. A dead
    holder is replaced by a launch that opens.
    """
    if sys.platform != "win32":
        return
    import psutil
    profile = tmp_path / "profile"
    app = tmp_path / "app"
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP"):
        (profile / name).mkdir(parents=True)
    app.mkdir()
    python_home = Path(sys.base_prefix)
    link_parent = profile / "LOCALAPPDATA" / "Python"
    link_parent.mkdir(parents=True)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_parent / python_home.name), str(python_home)],
        check=True, capture_output=True)
    subprocess.run(
        [sys.executable, "-E", "-s", "-m", "venv", "--without-pip", str(app / ".venv")],
        check=True, capture_output=True, timeout=180)
    site = app / ".venv" / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    (site / "lockfix-base.pth").write_text(str(python_home / "Lib" / "site-packages") + "\n", encoding="utf-8")
    # The base prefix has a PyQt6 namespace without QtCore. The bindings with
    # QtCore.pyd live in the user site, which -s hides. A junction puts that
    # package on the venv path ahead of the empty namespace.
    pyqt_home = _pyqt6_package()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(site / "PyQt6"), str(pyqt_home)],
        check=True, capture_output=True)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(app / "nodelang"), str(ROOT / "01.APP" / "nodelang")],
        check=True, capture_output=True)
    shutil.copyfile(ROOT / "01.APP" / "colleague_setup.py", app / "colleague_setup.py")
    shutil.copyfile(ROOT / "03.TOOLS" / "installer" / "ArchHub.vbs", app / "ArchHub.vbs")
    shutil.copyfile(ROOT / "03.TOOLS" / "installer" / "ArchHub.bat", app / "ArchHub.bat")
    build = "lockfix-test"
    requirements = b"archhub-lockfix-test\n"
    (app / "BUILD_ID").write_text(build + "\n", encoding="ascii")
    (app / "requirements.txt").write_bytes(requirements)
    digest = hashlib.sha256(requirements).hexdigest()
    (app / ".archhub-ready").write_text("venv-v1:%s:%s\n" % (build, digest), encoding="ascii")
    state = profile / "LOCALAPPDATA" / "ArchHub"
    state.mkdir()
    env = os.environ.copy()
    env.update(
        USERPROFILE=str(profile / "USERPROFILE"),
        HOME=str(profile / "HOME"),
        LOCALAPPDATA=str(profile / "LOCALAPPDATA"),
        APPDATA=str(profile / "APPDATA"),
        TEMP=str(profile / "TEMP"),
        TMP=str(profile / "TEMP"),
        PYTHONNOUSERSITE="1",
        ARCHHUB_TEST_STATE_DIR=str(state),
        ARCHHUB_TEST_LOCK_PORT=str(_free_port()),
        QT_QPA_PLATFORM="offscreen",
    )
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    imports = subprocess.run(
        [str(app / ".venv" / "Scripts" / "python.exe"), "-E", "-s", "-c",
         "import psutil, PyQt6.QtCore, PyQt6.QtWidgets, PyQt6.QtWebEngineWidgets"],
        capture_output=True, text=True, timeout=120)
    assert imports.returncode == 0, imports.stderr
    ready = subprocess.run(
        [sys.executable, "-E", "-s", str(app / "colleague_setup.py"), "--check-ready"],
        cwd=app, env=env, capture_output=True, text=True, timeout=120)
    assert ready.returncode == 0, (ready.returncode, ready.stdout, ready.stderr)
    log_path = state / "launcher.log"
    launches = []

    def start():
        launches.append(subprocess.Popen(["wscript.exe", str(app / "ArchHub.vbs")], cwd=app, env=env))
        return launches[-1]

    def log_text():
        if not log_path.is_file():
            return ""
        return log_path.read_text(encoding="utf-8", errors="replace")

    def answers():
        port_file = state / "nograph-http-port"
        if not port_file.is_file():
            return False
        try:
            port = int(port_file.read_text(encoding="ascii").strip())
            with urllib.request.urlopen("http://127.0.0.1:%d/api/alive" % port, timeout=2) as response:
                return response.status == 204
        except (OSError, ValueError):
            return False

    def launcher_pids():
        return [pid for pid in _matching_pids(app, "launcher.py") if _alive(pid)]

    def maintain_pids():
        found = []
        for pid in _matching_pids(app, "quiet_update.py"):
            if not _alive(pid):
                continue
            try:
                command = " ".join(psutil.Process(pid).cmdline())
            except (psutil.Error, OSError):
                continue
            if "--maintain" in command:
                found.append(pid)
        return found

    try:
        start()
        opened = _wait_until(
            lambda: "window     : Studio opened" in log_text() and answers(),
            240)
        assert opened, log_text()[-4000:]
        first = launcher_pids()
        assert len(first) >= 2, first
        parents = []
        for pid in first:
            parent = psutil.Process(pid).ppid()
            if parent in first:
                parents.append(parent)
        assert parents, first
        assert all(_alive(pid) for pid in parents)
        assert _wait_until(lambda: len(maintain_pids()) == 1, 30), maintain_pids()
        second = start()
        second.wait(timeout=180)
        assert second.returncode == 0, log_text()[-4000:]
        assert "leaving it alone" in log_text()
        assert answers()
        assert all(_alive(pid) for pid in first)
        assert len(maintain_pids()) == 1, maintain_pids()
        _kill_pids(first)
        assert _wait_until(lambda: not launcher_pids(), 20), launcher_pids()
        before = log_text().count("window     : Studio opened")
        start()
        reopened = _wait_until(
            lambda: log_text().count("window     : Studio opened") > before and answers(),
            240)
        assert reopened, log_text()[-4000:]
        again = launcher_pids()
        assert len(again) >= 2, again
        assert len(maintain_pids()) == 1, maintain_pids()
    finally:
        for proc in launches:
            try:
                proc.kill()
            except OSError:
                pass
        _kill_pids(_matching_pids(app, "launcher.py") + _matching_pids(app, "quiet_update.py")
                   + _matching_pids(app, "ArchHub.vbs"))


def test_launcher_lock_is_profile_scoped_and_unknown_profiles_cannot_take_over(tmp_path):
    from nodelang.profile_instance import mutex_name, profile_identity
    first = {'LOCALAPPDATA': str(tmp_path / 'one')}
    second = {'LOCALAPPDATA': str(tmp_path / 'two')}
    assert mutex_name(first) == mutex_name(dict(first))
    assert mutex_name(first) != mutex_name(second)
    assert mutex_name(first).startswith("Local\\ArchHub-")
    state = str(tmp_path / 'shared-state')
    assert mutex_name({**first, 'ARCHHUB_TEST_STATE_DIR':state}) == mutex_name({**second, 'ARCHHUB_TEST_STATE_DIR':state})
    assert profile_identity({}) is None
    assert profile_identity(first) != profile_identity(second)


def test_launch_reclaims_the_profile_when_the_previous_instance_exits():
    from types import SimpleNamespace
    source = ast.parse((Path(__file__).resolve().parents[2] / '01.APP/nodelang/launcher.py').read_text(encoding='utf-8-sig'))
    block = next(node for node in source.body if isinstance(node, ast.If)
                 and ast.unparse(node.test) == '_profile_instance.handle is None')
    retries = []
    replacement = SimpleNamespace(handle=1)
    namespace = dict(_profile_instance=SimpleNamespace(handle=None),
        _launch_port_file=SimpleNamespace(read_text=lambda **kwargs: '12345'),
        _forward_launch_arguments=lambda *args: False, sys=SimpleNamespace(argv=['launcher.py']),
        time=SimpleNamespace(sleep=lambda seconds: retries.append(seconds)), _launcher_seconds=lambda key: 0,
        ProfileInstance=lambda: replacement, _front_running_archhub=lambda: retries.append('front'))
    exec(compile(ast.Module(body=[block], type_ignores=[]), '<launcher-owner-retry>', 'exec'), namespace)
    assert namespace['_profile_instance'] is replacement and retries == [0]


def test_another_profile_listener_is_not_an_owner_and_is_never_stopped(tmp_path, monkeypatch):
    import psutil
    from types import SimpleNamespace
    from nodelang import application_machine_transport as transport
    functions = _functions()
    calls = []
    class Process:
        pid = 123
        def username(self): return 'same-account'
        def environ(self): return {'LOCALAPPDATA': str(tmp_path / 'other-profile')}
        def terminate(self): calls.append('terminate')
        def kill(self): calls.append('kill')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'current-profile'))
    monkeypatch.setattr(psutil, 'Process', lambda *args: Process())
    monkeypatch.setattr(psutil, 'net_connections', lambda **kwargs: [
        SimpleNamespace(status=psutil.CONN_LISTEN, pid=123, laddr=('127.0.0.1', 45678))])
    monkeypatch.setattr(transport, '_observe_machine_process', lambda *args: calls.append('inspect'))
    assert functions['_verified_launch_owner'](45678) is None
    assert functions['_release_unanswering_holder'](45678, tmp_path) is False
    assert calls == []


def test_profile_mutex_excludes_updater_and_rollback_and_releases(tmp_path, monkeypatch):
    from nodelang.profile_instance import ProfileInstance
    from nodelang import quiet_update
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    state = tmp_path / 'state'
    (state / 'updates').mkdir(parents=True)
    (state / 'updates' / 'staged.json').write_text('{}', encoding='utf-8')
    calls = []
    monkeypatch.setattr(quiet_update, 'rollback_staged', lambda *args: calls.append('rollback') or {'rolled_back': True})
    first = ProfileInstance()
    second = ProfileInstance()
    try:
        assert first.handle is not None and second.handle is None
        alias = ProfileInstance({'LOCALAPPDATA':str(tmp_path / 'other-local'), 'ARCHHUB_TEST_STATE_DIR':str(state)})
        try:
            assert alias.handle is None
        finally:
            alias.close()
        assert quiet_update._desktop_running() is True
        assert not quiet_update.recover_failed_launch(state, tmp_path / 'app')['rolled_back']
        assert calls == []
        foreign = ProfileInstance({'LOCALAPPDATA': str(tmp_path / 'other')})
        try:
            assert foreign.handle is not None
        finally:
            foreign.close()
    finally:
        first.close()
        second.close()
    assert quiet_update._desktop_running() is False
    assert quiet_update.recover_failed_launch(state, tmp_path / 'app')['rolled_back']
    assert calls == ['rollback']
