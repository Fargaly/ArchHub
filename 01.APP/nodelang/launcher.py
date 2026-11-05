"""ArchHub desktop launcher, with persistent state for this Windows user.

This is the sole installed Qt entry. Normal state is selected beneath
%LOCALAPPDATA%/ArchHub. Historical stores are migration inputs only.
Explicit fixture runs select ARCHHUB_TEST_STATE_DIR and never publish the
machine's active pointer. Closing keeps it in the tray by default; Quit exits.
"""
import faulthandler
import os, sys, time, traceback
from pathlib import Path

# This machine's documented QtWebEngine failure: GPU compositing
# collapses the render process and takes the whole window down with no
# Python traceback. Software rendering is the fix that held.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault("QT_OPENGL", "software")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# pythonw has no console: stdout/stderr vanish and a crash is invisible.
# Everything this launcher says goes to a file the founder can open.
_log_dir = Path(
    os.environ.get("ARCHHUB_TEST_STATE_DIR")
    or (Path(os.environ["LOCALAPPDATA"]) / "ArchHub")
)
_log_dir.mkdir(parents=True, exist_ok=True)
_log_dir = _log_dir / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_path = _log_dir / "launcher.log"
_bootstrap_log = open(_log_path, "a", encoding="utf-8", buffering=1)
_log = _bootstrap_log
sys.stdout = _log
sys.stderr = _log
_boot_deadline = None


def _launcher_parameter(key):
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    return LIBRARY_ITEM_ENGINES['tool_workshop']['params'][key]


def _launcher_seconds(key):
    return _launcher_parameter(key) / 1000


def _arm_boot_watchdog():
    if _boot_deadline is not None:
        faulthandler.dump_traceback_later(
            max(0.001, _boot_deadline - time.monotonic()), file=_log, exit=True)


def _start_boot_phase(label, *, timeout_seconds=90.0):
    global _boot_deadline
    print("  startup    : begin %s (deadline %.1fs)" % (label, timeout_seconds), flush=True)
    _boot_deadline = time.monotonic() + timeout_seconds
    _arm_boot_watchdog()


def _finish_boot_phase(label):
    global _boot_deadline
    faulthandler.cancel_dump_traceback_later()
    _boot_deadline = None
    print("  startup    : finished " + label, flush=True)


def _follow_boot_log_rotation(stream):
    faulthandler.enable(file=stream)
    # Rotation must never leave the current launcher.log empty, even if the
    # boot stops before the next ordinary print. Keep the original deadline.
    stream.write("  startup    : log continued after rotation\n")
    stream.flush()
    _arm_boot_watchdog()


# Imports and profile preflight used to run before the first logged line.
# A deadline leaves the stack in this same log; SQLite keeps its crash recovery.
_start_boot_phase("prepare desktop")
# Size-capped with three older copies (launcher.log.1..3); it grew forever.
try:
    from nodelang.log_rotation import LAUNCHER_LOG_BYTES, LOG_KEEP, RotatingLog, rotate as _rotate_log
    _log = RotatingLog(_log_path, on_rotate=_follow_boot_log_rotation)
    # brain.log has no writer in this release; an old one is capped, never grown.
    _rotate_log(_log_dir / "brain.log", LAUNCHER_LOG_BYTES, LOG_KEEP)
except Exception:
    # A half-applied update still leaves a log to read (the check below names it).
    _log = _bootstrap_log
sys.stdout = _log
sys.stderr = _log
if _log is not _bootstrap_log:
    faulthandler.cancel_dump_traceback_later()
    _bootstrap_log.close()
    _arm_boot_watchdog()
print("  startup    : prepare desktop logging ready", flush=True)


def _require_complete_local_update(app_dir):
    # The existing local updater writes this reservation before replacing the
    # launcher, then publishes the remaining files while launch/store fences
    # are held. Keep it on any interrupted update until rollback or completion.
    if (app_dir / 'local-update.pending.json').exists():
        print('ArchHub update is incomplete. Resume its recorded update or rollback before opening.', flush=True)
        raise SystemExit(2)


_require_complete_local_update(Path(__file__).resolve().parents[1])


# pythonw has no console and stdout is the log file above, so a boot that
# refuses -- Qt missing, WebEngine refusing the GPU, a port held -- was a
# window that never opened and a colleague with nothing to send. The log
# keeps the full traceback; the colleague gets its last line and where the
# log is, in a box he can read.
def _message_box(message, *, blocking=True, timeout_ms=45000, quit_event=None):
    """The only window a person without a console ever sees.

    Every refusal on the boot path goes through here. A launch that ends
    without one is a double-click that did nothing, and the colleague is left
    with nothing to read and nothing to send.
    """
    def _show():
        try:
            import ctypes
            user32 = ctypes.windll.user32
            timeout_box = getattr(user32, "MessageBoxTimeoutW", None)
            if timeout_box is not None:
                timeout_box(0, message, 'ArchHub', 0x10, 0, int(timeout_ms))
            else:
                user32.MessageBoxW(0, message, 'ArchHub', 0x10)
            return True
        except Exception:
            return False

    if not blocking:
        import threading
        done = threading.Event()

        def _run():
            try:
                _show()
            finally:
                done.set()

        threading.Thread(target=_run, name="archhub-refusal-message", daemon=True).start()
        return done
    try:
        return _show()
    except Exception:
        return False


def _boot_refusal_message(kind, value):
    import traceback as _traceback
    last = ''.join(_traceback.format_exception_only(kind, value)).strip().splitlines()[-1]
    message = 'ArchHub could not open.' + chr(10) + chr(10) + last[:300]
    message += chr(10) + chr(10) + 'The full log is at:' + chr(10) + str(_log_path)
    message += chr(10) + chr(10) + 'Share that log when requesting support.'
    return message


def _qt_event_loop_running():
    probe = globals().get("_qt_app_event_loop_active")
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False
    try:
        from PyQt6.QtCore import QAbstractEventDispatcher, QCoreApplication
        if QCoreApplication.instance() is None:
            return False
        return QAbstractEventDispatcher.instance() is not None
    except Exception:
        return False


def _tell_the_person(kind, value, tb):
    traceback.print_exception(kind, value, tb)
    try:
        delivered = _message_box(
            _boot_refusal_message(kind, value),
            blocking=not _qt_event_loop_running(),
        )
        if delivered is False:
            print("  startup    : boot refusal notice was not displayed; see %s" % _log_path, flush=True)
    except Exception as error:
        print("  startup    : could not display boot refusal: %s" % error, flush=True)
sys.excepthook = _tell_the_person
print("=== launch", time.strftime("%Y-%m-%d %H:%M:%S"), "===")
faulthandler.enable(file=_log)

def _windows_desktop_name():
    """Read this thread's desktop; do not switch or close its borrowed handle."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    handle = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    name = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    if not user32.GetUserObjectInformationW(
            handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not name.value:
        raise RuntimeError("Windows desktop identity is unavailable")
    return name.value


def _require_desktop_state_custody(selected_state, normal_state):
    """Automation desktops may open isolated state, never normal user custody."""
    if os.name != "nt":
        return
    desktop = _windows_desktop_name()
    if desktop.casefold() == "default":
        return
    selected, normal = Path(selected_state).resolve(), Path(normal_state).resolve()
    if (selected == normal or selected.is_relative_to(normal)
            or normal.is_relative_to(selected)):
        raise RuntimeError(
            "ArchHub refused normal user state on an isolated Windows desktop. "
            "Open ArchHub from the Windows Start menu on your normal desktop. "
            "Automation requires a separate ARCHHUB_TEST_STATE_DIR outside user state.")


state_dir = Path(
    os.environ.get("ARCHHUB_TEST_STATE_DIR")
    or (Path(os.environ["LOCALAPPDATA"]) / "ArchHub")
)
try:
    _require_desktop_state_custody(
        state_dir, Path(os.environ["LOCALAPPDATA"]) / "ArchHub")
except Exception as refusal:
    print("  desktop    : launch refused: %s" % refusal, flush=True)
    raise SystemExit(4)
state_dir.mkdir(parents=True, exist_ok=True)

def idle_or_away() -> bool:
    """Use BABOOM's input-age reader; unknown presence never permits focus theft."""
    import math
    try:
        from nodelang.baboom_native_companion import desktop_input_idle_seconds
        age = desktop_input_idle_seconds()
        return math.isfinite(age) and age >= 2.0
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        return False


def _force_foreground(handle, *, explicit_activation=False) -> bool:
    """Reserve Windows' forced-focus workaround for an idle, requested restore."""
    if not explicit_activation:
        return False
    if idle_or_away():
        try:
            import ctypes as _ct
            user32 = _ct.windll.user32
            kernel32 = _ct.windll.kernel32
            handle = int(handle)
            if not handle:
                return False
            SW_RESTORE = 9
            if user32.IsIconic(handle):
                user32.ShowWindow(handle, SW_RESTORE)
            user32.ShowWindow(handle, SW_RESTORE)
            ours = kernel32.GetCurrentThreadId()
            front = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            attached = bool(front and front != ours
                            and user32.AttachThreadInput(front, ours, True))
            try:
                user32.BringWindowToTop(handle)
                user32.SetForegroundWindow(handle)
                user32.SetActiveWindow(handle)
            finally:
                if attached:
                    user32.AttachThreadInput(front, ours, False)
            return bool(user32.IsWindowVisible(handle))
        except Exception:
            return False
    return False


def _front_running_archhub():
    """Bring an ArchHub window already on this desktop to the front.

    Launching ArchHub while it lives in the tray must SHOW it (Chrome,
    Claude Desktop): the founder double-clicked the icon and saw nothing
    (2026-09-04, the studio window sat hidden behind close-to-tray).
    True means a window of ours was found and raised.
    """
    try:
        import ctypes as _ct
        _u = _ct.windll.user32
        _shown = []

        def _each(handle, _lparam):
            length = _u.GetWindowTextLengthW(handle)
            title = _ct.create_unicode_buffer(length + 1)
            _u.GetWindowTextW(handle, title, length + 1)
            klass = _ct.create_unicode_buffer(256)
            _u.GetClassNameW(handle, klass, 256)
            if title.value == "ArchHub" and "QWindowIcon" in klass.value:
                # Same Windows foreground rule as the tray click: without the
                # input-queue attach the call is refused and the button blinks.
                _force_foreground(handle, explicit_activation=True)
                _shown.append(handle)
            return True

        _u.EnumWindows(_ct.WINFUNCTYPE(_ct.c_bool, _ct.c_void_p, _ct.c_void_p)(_each), 0)
        return bool(_shown)
    except Exception:
        return False


def _held_port_outcome(port, front_running_archhub, tell_the_person):
    """Answer a held lock port with words, never with a silent exit.

    A colleague double-clicked ArchHub on a machine where the port was
    already taken -- a copy left running under another account, a stale
    process, any program that happened to sit on it -- and got nothing at
    all: no window, no message, every single time. Two different situations
    hide behind one refusal to bind, and each needs its own answer.
    """
    if front_running_archhub():
        return "another ArchHub is already running; brought its window to the front"
    tell_the_person(
        "ArchHub is already open, or port %d on this machine is being used by "
        "another program." % port
        + chr(10) + chr(10)
        + "Nothing was found to bring to the front, so ArchHub stopped here "
          "rather than fight the other copy for the same graph."
        + chr(10) + chr(10)
        + "Open the existing ArchHub from its tray icon. If its window and "
          "tray are missing, the background instance needs recovery before "
          "another launch. Do not change the lock port or start another copy "
          "against the same user data."
    )
    return ("port %d is held and no ArchHub window answered; the person was told "
            "to recover the existing instance without changing its lock port" % port)


def _verified_launch_owner(port):
    """Refuse argv delivery unless the listener is this user's exact launcher."""
    import psutil
    from nodelang.application_machine_transport import _observe_machine_process, _desktop_launch_is_admitted
    try:
        current = psutil.Process()
        for connection in psutil.net_connections(kind='tcp'):
            if (connection.status != psutil.CONN_LISTEN or not connection.pid
                    or connection.laddr != ('127.0.0.1', port)):
                continue
            owner = psutil.Process(connection.pid)
            if owner.username() != current.username():
                return None
            observed = _observe_machine_process(connection.pid)
            if observed is not None and _desktop_launch_is_admitted(observed,
                    product_root=Path(__file__).resolve().parents[1]):
                return owner
    except (psutil.Error, OSError, ValueError) as error:
        print("  startup    : could not inspect existing owner: %s" % error, flush=True)
        return None
    return None


def _lock_takeover_decision(owner_admitted, owner_running, answers, age_seconds, listener_present):
    """One launcher. A dead or silent holder is replaced; a live answering one stays.

    A foreign program on the lock port is left alone. A launcher that has not
    had time to open its server is left alone so a slow boot is not killed.
    """
    if owner_admitted and owner_running and answers:
        return "leave"
    if owner_admitted and owner_running and age_seconds < 45:
        return "leave"
    if owner_admitted and owner_running:
        return "stop"
    if not listener_present:
        return "bind"
    return "leave"


def _lock_listener_present(port):
    import psutil
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if (connection.status == psutil.CONN_LISTEN
                    and connection.laddr == ("127.0.0.1", port)):
                return True
    except (psutil.Error, OSError):
        return True
    return False


def _holder_answers(port, state_dir):
    """True when this user's launcher is up and its loopback server answers."""
    owner = _verified_launch_owner(port)
    if owner is None:
        return False
    try:
        if not owner.is_running():
            return False
    except Exception:
        return False
    try:
        text = (Path(state_dir) / "nograph-http-port").read_text(encoding="ascii")
        http_port = int(text.strip())
    except (OSError, ValueError):
        return False
    if not 1 <= http_port <= 65535 or http_port == port:
        return False
    import urllib.request
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/alive" % http_port,
                timeout=_launcher_seconds("account_http_ms")) as response:
            return response.status == 204
    except (OSError, ValueError):
        return False


def _launcher_family_pids(process):
    """This process, its parents, and its children.

    .venv\\Scripts\\pythonw.exe is a redirector. It stays as the parent, with the
    same command line as the interpreter that actually runs this file, and it
    puts that interpreter in a job that is destroyed when the redirector exits.
    Stopping the redirector as a second launcher stops the only launch.
    """
    import psutil
    protected = set()
    try:
        protected.add(process.pid)
    except (psutil.Error, OSError):
        return protected
    current = process
    while True:
        try:
            parent = current.parent()
        except (psutil.Error, OSError):
            break
        if parent is None or parent.pid in protected:
            break
        protected.add(parent.pid)
        current = parent
    try:
        for child in process.children(recursive=True):
            protected.add(child.pid)
    except (psutil.Error, OSError) as error:
        print("  lock       : could not list child processes: %s" % error, flush=True)
    return protected


def _lock_listener_pid(port):
    import psutil
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if (connection.status == psutil.CONN_LISTEN
                    and connection.laddr == ("127.0.0.1", port)
                    and connection.pid):
                return int(connection.pid)
    except (psutil.Error, OSError) as error:
        print("  lock       : could not read the lock listener: %s" % error, flush=True)
        return None
    return None


def _release_unanswering_holder(port, state_dir):
    """Stop our own launcher when it holds the lock and is not answering.

    Returns True when this launch should bind the port and open the window.
    Revit, AutoCAD, and any other program are never stopped. This process
    chain is never stopped either: that is the launch which must open.
    """
    import psutil
    owner = _verified_launch_owner(port)
    admitted = owner is not None
    running = False
    age = 0.0
    if owner is not None:
        try:
            running = bool(owner.is_running())
            age = max(0.0, time.time() - owner.create_time())
        except (psutil.Error, OSError, ValueError):
            running = False
    decision = _lock_takeover_decision(
        admitted, running, _holder_answers(port, state_dir) if running else False,
        age, _lock_listener_present(port))
    if decision == "bind":
        print("  lock       : no live holder on port %d; opening" % port, flush=True)
        return True
    if decision != "stop" or owner is None:
        return False
    try:
        if owner.pid in _launcher_family_pids(psutil.Process()):
            return False
    except (psutil.Error, OSError):
        return False
    print("  lock       : holder on port %d is not answering; taking over" % port, flush=True)
    try:
        owner.terminate()
        owner.wait(timeout=_launcher_seconds("worker_join_ms"))
    except psutil.TimeoutExpired:
        try:
            owner.kill()
            owner.wait(timeout=_launcher_seconds("quit_watchdog_ms"))
        except (psutil.Error, OSError):
            return False
    except (psutil.Error, OSError):
        return False
    try:
        return not owner.is_running()
    except (psutil.Error, OSError):
        return True


def _stop_duplicate_launchers():
    """Stop one different launcher only when it is silent.

    A live launcher that answers stays. This process, its parents, its
    children, and the process that holds the lock stay as well. After a
    takeover the caller continues and opens the window.
    """
    import psutil
    from nodelang.application_machine_transport import _observe_machine_process, _desktop_launch_is_admitted
    try:
        me = psutil.Process()
    except (psutil.Error, OSError):
        return
    protected = _launcher_family_pids(me)
    listener = _lock_listener_pid(_lock_port)
    if listener:
        protected.add(listener)
        try:
            protected.update(_launcher_family_pids(psutil.Process(listener)))
        except (psutil.Error, OSError) as error:
            print("  lock       : could not protect the lock owner's process chain: %s" % error, flush=True)
    answering = _holder_answers(_lock_port, state_dir)
    root = Path(__file__).resolve().parents[1]
    for process in psutil.process_iter(["pid"]):
        if process.pid in protected:
            continue
        try:
            if process.username() != me.username():
                continue
            observed = _observe_machine_process(process.pid)
            if observed is None or not _desktop_launch_is_admitted(observed, product_root=root):
                continue
            if answering or not process.is_running():
                continue
            age = max(0.0, time.time() - process.create_time())
            if _lock_takeover_decision(True, True, False, age, True) != "stop":
                continue
            if process.pid in protected:
                continue
            process.terminate()
            print("  lock       : stopped duplicate launcher pid %d" % process.pid, flush=True)
        except (psutil.Error, OSError, ValueError):
            continue


def _exit_while_port_is_held():
    """The port is still held. Leave an answering launcher, and say so when it is not ours."""
    if _holder_answers(_lock_port, state_dir):
        _forward_launch_arguments(_lock_port, sys.argv[1:])
        print("  lock       : live launcher on port %d is answering; leaving it alone" % _lock_port, flush=True)
        raise SystemExit(0)
    _forward_launch_arguments(_lock_port, sys.argv[1:])
    print("  window     : %s"
          % _held_port_outcome(_lock_port, _front_running_archhub, _message_box),
          flush=True)
    raise SystemExit(0)


def _forward_launch_arguments(port, arguments):
    """Deliver a second launch to the existing process without opening a store."""
    import json
    import socket
    payload = json.dumps(list(arguments), ensure_ascii=False).encode('utf-8') + b'\n'
    if len(payload) > 8192:
        return False
    owner = _verified_launch_owner(port)
    if owner is None:
        return False
    try:
        with socket.create_connection(('127.0.0.1', port), 0.5) as connection:
            verified = _verified_launch_owner(port)
            if verified != owner or not owner.is_running():
                return False
            connection.sendall(payload)
        return True
    except OSError:
        return False  # An older launcher still has the same exclusive guard.


def _serve_launch_requests(listener, on_launch):
    """Blocking, bounded IPC; only the Qt thread may activate its window."""
    import json
    import time as ipc_time
    while True:
        try:
            connection, _ = listener.accept()
        except OSError:
            return
        try:
            with connection:
                deadline = ipc_time.monotonic() + 0.5
                payload = b''
                while not payload.endswith(b'\n') and len(payload) <= 8192:
                    remaining = deadline - ipc_time.monotonic()
                    if remaining <= 0:
                        raise ValueError('launch request expired')
                    connection.settimeout(remaining)
                    chunk = connection.recv(8193 - len(payload))
                    if not chunk:
                        break
                    payload += chunk
                arguments = json.loads(payload)
                if (len(payload) > 8192 or type(arguments) is not list or len(arguments) > 128
                        or any(type(value) is not str for value in arguments)):
                    raise ValueError('invalid launch request')
                on_launch(arguments)
        except (OSError, ValueError, UnicodeError):
            continue


# ONE app. The exclusive socket also carries subsequent launches to Qt.
import socket as _socket
_lock_port = int(os.environ.get("ARCHHUB_TEST_LOCK_PORT", "48611"))
_instance_lock = _socket.socket()
# NEVER SO_REUSEADDR here: on Windows it PERMITS binding a port another
# process already holds, which silently disables the single-instance
# mutex and lets a second app fight the first for the database.
if hasattr(_socket, "SO_EXCLUSIVEADDRUSE"):
    _instance_lock.setsockopt(
        _socket.SOL_SOCKET, _socket.SO_EXCLUSIVEADDRUSE, 1
    )
for _attempt in range(12):
    try:
        _instance_lock.bind(("127.0.0.1", _lock_port))
        break
    except OSError:
        # A dying previous instance still holds the port for a moment.
        # Reopening right after closing must WORK, so wait it out rather
        # than exiting silently and leaving the founder with no window.
        time.sleep(_launcher_seconds('instance_retry_ms'))
else:
    # Say so in the log AND on the screen: a launch that exits without a word
    # leaves an orphan header, reads as a crash, and gives the person nothing
    # to act on. A dead or silent holder is not "already running": take the
    # port and open the window. A live launcher that answers is left as the
    # one instance.
    print("  lock       : port %d is already held" % _lock_port, flush=True)
    if not _release_unanswering_holder(_lock_port, state_dir):
        _exit_while_port_is_held()
    bound = False
    for _again in range(12):
        try:
            _instance_lock.bind(("127.0.0.1", _lock_port))
            bound = True
            break
        except OSError:
            time.sleep(_launcher_seconds("instance_retry_ms"))
    if not bound:
        _exit_while_port_is_held()

_instance_lock.listen(8)
_stop_duplicate_launchers()

import subprocess as _update_preboot_process
# Apply the verified installer after the previous desktop owner has closed.
# No synchronous network download belongs on the application startup path.
_staged = {}
try:
    from nodelang.quiet_update import apply_staged as _apply_staged, begin_update_boot
    _staged = begin_update_boot(state_dir, Path(__file__).resolve().parents[1])
    if _staged.get("rolled_back"):
        print("  update     : %s" % _staged.get("reason"), flush=True)
        try:
            _instance_lock.close()
            _update_preboot_process.Popen(["wscript.exe", str(Path(__file__).resolve().parents[1] / "ArchHub.vbs")],
                close_fds=True, creationflags=getattr(_update_preboot_process, "CREATE_NO_WINDOW", 0))
        except Exception as _rollback_relaunch_refusal:
            print("  update     : restored; relaunch failed (%s). Reopen ArchHub; recovery is retained." % type(_rollback_relaunch_refusal).__name__, flush=True)
            raise SystemExit(1) from None
        raise SystemExit(0)
    if _staged.get("status") == "applying":
        print("  update     : previous installation is unresolved; recovery and installer retained. Startup refused.", flush=True)
        raise SystemExit(1)
    if _staged.get("staged") and _staged.get("status") == "staged":
        _applied = _apply_staged(state_dir, Path(__file__).resolve().parents[1])
        if _applied.get("rolled_back"):
            print("  update     : install failed: %s" % _applied.get("reason"), flush=True)
            try:
                _instance_lock.close()
                _update_preboot_process.Popen(["wscript.exe", str(Path(__file__).resolve().parents[1] / "ArchHub.vbs")], close_fds=True, creationflags=getattr(_update_preboot_process, "CREATE_NO_WINDOW", 0))
            except Exception as _relaunch_refusal:
                print("  update     : install failed; relaunch failed (%s). Reopen ArchHub." % type(_relaunch_refusal).__name__, flush=True)
                raise SystemExit(1) from None
            raise SystemExit(0)
        if _applied.get("applied"):
            print("  update     : installed build %s; relaunching" % _applied.get("build_id"), flush=True)
            from nodelang.quiet_update import append_update_log
            append_update_log(state_dir, "update: installed %s" % _applied.get("build_id"))
            try:
                _instance_lock.close()
                _update_preboot_process.Popen(["wscript.exe", str(Path(__file__).resolve().parents[1] / "ArchHub.vbs")], close_fds=True, creationflags=getattr(_update_preboot_process, "CREATE_NO_WINDOW", 0))
            except Exception as _relaunch_refusal:
                print("  update     : installed; relaunch failed (%s). Reopen ArchHub; recovery is retained." % type(_relaunch_refusal).__name__, flush=True)
                raise SystemExit(1) from None
            raise SystemExit(0)
        print("  update     : %s" % _applied.get("reason"), flush=True)
        if _applied.get("status") == "applying":
            print("  update     : installation is unresolved; saved recovery retained. Startup refused.", flush=True)
            raise SystemExit(1)
except SystemExit:
    raise
except Exception as _update_refusal:
    print("  update     : not applied -- %s" % _update_refusal, flush=True)



_require_complete_local_update(Path(__file__).resolve().parents[1])

# NOGRAPH (founder 2026-10-28): the app is files + nodes. Only the file server starts;
# the graph journal stays on disk untouched and its server is never imported.
from nodelang.nograph_launcher import run as _run_nograph
_finish_boot_phase("prepare desktop")
raise SystemExit(_run_nograph(state_dir, _instance_lock, _serve_launch_requests))
