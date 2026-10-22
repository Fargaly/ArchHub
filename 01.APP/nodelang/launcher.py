"""ArchHub desktop launcher, with persistent state for this Windows user.

This is the sole installed Qt entry. Normal state is selected beneath
%LOCALAPPDATA%/ArchHub. Historical stores are migration inputs only.
Explicit fixture runs select ARCHHUB_TEST_STATE_DIR and never publish the
machine's active pointer. Closing quits by default; Settings can keep it in the tray.
"""
import faulthandler
import contextlib
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
_log_path = _log_dir / "launcher.log"
_bootstrap_log = open(_log_path, "a", encoding="utf-8", buffering=1)
_log = _bootstrap_log
sys.stdout = _log
sys.stderr = _log
_boot_deadline = None
_migration_status = None


def _launcher_parameter(key):
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    value = LIBRARY_ITEM_ENGINES['tool_workshop']['params'][key]
    runtime = globals().get('server')
    store = getattr(runtime, 'universal_store', None)
    registry = getattr(runtime, 'universal_registry', None)
    if store is not None and registry is not None:
        from nodelang.universal_application import _APPLICATION_SETTING_SPECS, _workshop_board_int_param
        bounds = _APPLICATION_SETTING_SPECS[key][1]
        value = _workshop_board_int_param(store.snapshot(), registry,
            key, default=value, lower=bounds['min'], upper=bounds['max'])
    return value


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
from nodelang.persistence import application_database_path
state_path = application_database_path(state_dir)

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
    # to act on.
    print("  lock       : port %d is already held" % _lock_port, flush=True)
    _forward_launch_arguments(_lock_port, sys.argv[1:])
    print("  window     : %s"
          % _held_port_outcome(_lock_port, _front_running_archhub, _message_box),
          flush=True)
    sys.exit(0)

_instance_lock.listen(8)

import subprocess as _update_preboot_process
# Apply only a verified release armed by the preceding owner's final recovery.
# No synchronous network download belongs on the application startup path.
_staged = {}
try:
    from nodelang.quiet_update import apply_staged as _apply_staged, begin_update_boot
    _staged = begin_update_boot(state_dir, Path(__file__).resolve().parents[1])
    if _staged.get("rolled_back"):
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
        from nodelang.application_update_recovery import validate_update_ready
        from nodelang.persistence import application_content_path
        _update_content = application_content_path(state_path)
        _applied = _apply_staged(state_dir, Path(__file__).resolve().parents[1],
            before_apply=lambda: validate_update_ready(state_dir, Path(__file__).resolve().parents[1],
                state_path, _update_content))
        if _applied.get("applied") or _applied.get("rolled_back"):
            print("  update     : installed build %s; relaunching" % _applied.get("build_id"), flush=True)
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


def _saved_graph_exists(directory, database):
    """Distinguish a new installation from saved state needing recovery.

    This bounded read is a presence check, not journal integrity verification.
    It runs after the single-instance lock and never initializes a database.
    SQLite may update coordination read marks in the shared-memory file.
    """
    import sqlite3

    names = {os.path.normcase(name) for name in os.listdir(database.parent)} if database.parent.is_dir() else set()
    database_name = os.path.normcase(database.name)
    if database_name not in names:
        if any(name.startswith(database_name) for name in names):
            raise RuntimeError(
                "The saved graph database is missing but recovery files remain. "
                "All files are kept in place; restore the saved graph before opening."
            )
        # 2230 wrote the old desktop journal name. Its descriptor/backups are
        # evidence of that journal, not damage to the new filename. Validate
        # it read-only before the existing owner performs the backed-up merge.
        from nodelang.persistence import legacy_application_sources
        previous = [path for path in legacy_application_sources(directory)
                    if path.name in {"archhub-test.universal.sqlite3",
                                     "node-native-wip.json.gz.universal.sqlite3"}]
        if previous:
            return all(_saved_graph_exists(path.parent, path) for path in previous)
        if any((directory / name).exists() for name in ("runtime-descriptor.json", "backups")):
            raise RuntimeError(
                "The saved graph database is missing but recovery files remain. "
                "All files are kept in place; restore the saved graph before opening."
            )
        return False
    with database.open("rb") as source:
        if source.read(16) != b"SQLite format 3\x00":
            raise RuntimeError(
                "The existing saved graph has an unreadable database header. "
                "It is kept in place; a replacement graph will not be created."
            )
    try:
        connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=ro", uri=True, timeout=_launcher_seconds('preflight_database_ms'),
        )
        try:
            required = {"revisions", "cell_versions", "current_cells"}
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('revisions', 'cell_versions', 'current_cells')"
            )}
            if tables != required:
                raise RuntimeError("The saved graph journal is incomplete; files are kept in place.")
            if connection.execute(
                "SELECT 1 FROM current_cells WHERE cell_id = ? LIMIT 1", ("app:archhub",)
            ).fetchone() is None:
                from nodelang.persistence import selected_application_generation
                if not selected_application_generation(database):
                    raise RuntimeError("The saved application root is missing; files are kept in place.")
                return False
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise RuntimeError("The saved graph could not be read; files are kept in place.") from error
    return True


# The server reads the staged-update marker from here (BABOOM's "Restart now").
os.environ["ARCHHUB_STATE_DIR"] = str(state_dir)

# A socket lock cannot coordinate the graph and its ordinary message database.
# Their owner takes the bounded recovery snapshot after construction below.
# This does not replace the separately verified pre-update recovery copy.

print("ArchHub")
print("  graph store :", state_path)
print("  booting ...", flush=True)

from nodelang.application_server import ApplicationServer, _start_background_refresh
from nodelang.pipeline_engines import PIPELINE_ENGINES

# The runtime-pipe signing secret and descriptor live beside the store;
# they are what lets BABOOM (and any governed agent) bind a signed
# session against THIS runtime.
_pipe_secret_path = state_dir / "runtime-pipe.secret"
if not _pipe_secret_path.is_file():
    import secrets as _secrets
    _pipe_secret_path.write_bytes(_secrets.token_bytes(32))
# The brain (and every other governed client) authenticates to the pipe
# with the machine's DPAPI key at its DEFAULT path. Using a private
# secret here would make this runtime unreachable to them -- which is
# exactly why brain writes were failing.
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider

machine_key_provider = WindowsDpapiSigningKeyProvider(
    WindowsDpapiSigningKeyProvider.default_path()
)
descriptor_path = state_dir / "runtime-descriptor.json"
# The machine announcement: a signed POINTER to this runtime's own record,
# written when the transport starts. A verification run opens its own graph
# and never moves the founder's wiring onto it.
_machine_pointer = (
    None if os.environ.get("ARCHHUB_TEST_STATE_DIR")
    else Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / "active-universal-runtime.json"
)

first_boot = not _saved_graph_exists(state_dir, state_path)
print("  first boot  :", first_boot, flush=True)
started = time.perf_counter()

def _boot():
    # The boot is sampled while it runs: boot-profile.log beside launcher.log
    # says where the seconds went (the founder's boot reached 694s and nobody
    # could name what it was doing).
    from nodelang.boot_profile import profile_boot
    return profile_boot(_boot_unsampled, state_dir=state_dir, on_sample=_boot_step_seen)

def _boot_unsampled():
    global state_path, first_boot
    from nodelang.persistence import prepare_application_database, application_content_path, _MigrationProgress
    print("  migration  : checking complete application journal", flush=True)
    try:
        migration = prepare_application_database(state_dir, state_path,
            key_provider=machine_key_provider, on_progress=_migration_progress)
    finally:
        _migration_progress(None)
    state_path = application_database_path(state_dir)
    first_boot = not _saved_graph_exists(state_dir, state_path)
    print("  graph store :", state_path, flush=True)
    print("  first boot  :", first_boot, flush=True)
    print("  migration  : " + migration['state'], flush=True)
    from nodelang.desktop import create_workshop_transport, create_social_execution_arguments
    from nodelang.existing_workshop_native_host import ExistingWorkshopNativeHost
    from nodelang.model_execution_broker import (
        ApplicationOpenRouterCredentialResolver, ModelExecutionBroker,
    )
    from nodelang.project_work_execution_broker import ProjectWorkExecutionBroker
    artifact_root = state_dir / "workshop-artifacts"
    artifact_root.mkdir(exist_ok=True)
    workshop_transport = create_workshop_transport(state_dir)
    workshop_arguments = ({"session_link_transport": workshop_transport}
                          if workshop_transport is not None else {})
    workshop_arguments.update(create_social_execution_arguments())
    if workshop_transport is None:
        print("  workshop   : native transport unavailable; declare SESSION_LINK_NODE or install the bundled runtime", flush=True)
    opening = True
    import threading as _opening_threads
    opening_thread = _opening_threads.get_ident()
    open_progress = _MigrationProgress(30, _migration_progress)

    def opening_sqlite_work():
        if opening and _opening_threads.get_ident() == opening_thread:
            open_progress.advance('Opening saved graph')
        return 0

    try:
        server = ApplicationServer(
            universal_state_path=state_path,
            conversation_history_path=application_content_path(state_path),
            port=int(os.environ.get('ARCHHUB_TEST_HTTP_PORT', '0')),
            legacy_state_directory=state_dir,
            pipeline_effect_engines=PIPELINE_ENGINES,
            enable_machine_transport=True,
            enable_brain_cloud_sync=True,
            machine_descriptor_path=descriptor_path,
            machine_pointer_path=_machine_pointer,
            machine_key_provider=machine_key_provider,
            universal_journal_progress_handler=opening_sqlite_work,
            project_work_execution_broker=ProjectWorkExecutionBroker(artifact_root),
            model_execution_broker=ModelExecutionBroker(
                workspace_root=Path(__file__).resolve().parents[1],
                credential_resolver=ApplicationOpenRouterCredentialResolver(),
                timeout_seconds=_launcher_seconds('broker_start_ms'),
            ),
            **workshop_arguments,
        )
    finally:
        # A failed constructor may retain a partial store until GC; its hook
        # must become inert too. A live app must never inherit a boot watchdog.
        opening = False
        _migration_progress(None)
    connection, _lock = server.universal_store.sqlite_storage()
    with _lock:
        connection.set_progress_handler(None, 0)
    from app.secrets_store import bind_settings_owner
    bind_settings_owner(server.universal_store)
    from nodelang.desktop import bind_coordination_surface
    try:
        if bind_coordination_surface(server, state_dir) is not None:
            print('  coordination: bound application owner', flush=True)
    except Exception as refused:
        server._coordination_surface_error = type(refused).__name__
        print("  coordination: unavailable (%s: %s)" %
              (type(refused).__name__, str(refused)[:200]), flush=True)
    # Chat through a signed-in local assistant (model route local-cli/<name>)
    # runs through this same broker's host process, never a second runner.
    from nodelang import model_router as _model_router
    _model_router.bind_local_cli_broker(server.model_execution_broker)
    server._existing_workshop_native_host = ExistingWorkshopNativeHost(server,
        state_dir=state_dir, descriptor_path=descriptor_path, key_provider=machine_key_provider)
    try:
        server.enable_native_workshop_compliance()
    except Exception:
        server.close()
        raise
    return server.start()

def _release_own_fence(refusal) -> None:
    """A failed _boot() can leave this process holding the store fence twice over:
    the .owner.lock file AND an in-memory path set. Both must go or every retry
    fails on ourselves."""
    if "already owned by this same process" not in str(refusal):
        return
    try:
        from nodelang.universal_cell import InterprocessOwnerFence as _Fence
        key = os.path.normcase(os.path.realpath(os.path.abspath(str(state_path))))
        with _Fence._process_guard:
            _Fence._process_paths.discard(key)
    except Exception as error:
        print("  recovery   : could not release this process's store fence: %s" % error, flush=True)
    for stale in state_dir.glob(state_path.name + ".owner.lock"):
        try:
            stale.unlink(missing_ok=True)
        except OSError as error:
            print("  recovery   : could not remove own store lock %s: %s" % (stale, error), flush=True)


def _is_transient_owner_conflict(refusal):
    try:
        from nodelang.universal_cell import DatabaseOwnerConflict
    except ImportError as error:
        print("  recovery   : owner-conflict type unavailable: %s" % error, flush=True)
        return False
    cursor = refusal
    while cursor is not None:
        if isinstance(cursor, DatabaseOwnerConflict):
            return True
        cursor = getattr(cursor, "__cause__", None) or getattr(cursor, "__context__", None)
    return False


def _mark_runtime_refused(refusal) -> None:
    """If this failed process announced itself active, replace that with failed."""
    try:
        from datetime import datetime, timezone
        from nodelang.application_machine_transport import (
            RuntimeDescriptor,
            _atomic_json,
            _canonical,
            _owner_record_path,
            _read_descriptor,
        )
        record_path = _owner_record_path(descriptor_path, machine_key_provider)
        descriptor = _read_descriptor(descriptor_path, machine_key_provider)
        if descriptor.status != "active" or descriptor.process_id != os.getpid():
            return
        unsigned = RuntimeDescriptor(
            descriptor.runtime_id,
            "failed",
            descriptor.pipe,
            descriptor.process_id,
            descriptor.started_at,
            datetime.now(timezone.utc).isoformat(),
            descriptor.application_root,
            descriptor.agent_session_root,
            descriptor.workshop_root,
            descriptor.work_registry_root,
            descriptor.database,
            descriptor.key_id,
            descriptor.key_version,
            "",
            descriptor.format_version,
            descriptor.owner_generation,
            descriptor.process_created_at,
        )
        signature = machine_key_provider.sign(
            unsigned.key_id,
            unsigned.key_version,
            _canonical(unsigned.unsigned()),
        )
        failed = RuntimeDescriptor(
            unsigned.runtime_id,
            unsigned.status,
            unsigned.pipe,
            unsigned.process_id,
            unsigned.started_at,
            unsigned.stopped_at,
            unsigned.application_root,
            unsigned.agent_session_root,
            unsigned.workshop_root,
            unsigned.work_registry_root,
            unsigned.database,
            unsigned.key_id,
            unsigned.key_version,
            signature,
            unsigned.format_version,
            unsigned.owner_generation,
            unsigned.process_created_at,
        )
        _atomic_json(record_path, failed.document())
        print("  runtime    : marked failed before boot refusal notice (%s)"
              % type(refusal).__name__, flush=True)
    except Exception as descriptor_refusal:
        print("  runtime    : refusal descriptor not changed (%s)"
              % type(descriptor_refusal).__name__, flush=True)


def _exit_process(code):
    raise SystemExit(code)


def _refusal_quit_requested(quit_event):
    if quit_event is not None and quit_event.is_set():
        return True
    try:
        marker = state_dir / "quit-request"
        if marker.is_file():
            try:
                marker.unlink()
            except OSError as error:
                print("  quit       : could not remove quit request: %s" % error, flush=True)
            if quit_event is not None:
                quit_event.set()
            print("  quit       : asked during boot refusal; leaving cleanly", flush=True)
            return True
    except OSError as error:
        print("  quit       : could not inspect quit request: %s" % error, flush=True)
    return False


def _refuse_boot_without_living(refusal, *, quit_event=None, notice_seconds=45.0):
    import threading
    import time as _refusal_time
    if quit_event is None:
        quit_event = threading.Event()
    _mark_runtime_refused(refusal)
    notice = _message_box(
        _boot_refusal_message(type(refusal), refusal),
        blocking=False,
        timeout_ms=int(max(1.0, notice_seconds) * 1000),
        quit_event=quit_event,
    )
    if not hasattr(notice, "is_set"):
        _exit_process(1)
        return
    deadline = _refusal_time.monotonic() + max(0.0, float(notice_seconds))
    while _refusal_time.monotonic() < deadline:
        if _refusal_quit_requested(quit_event):
            break
        if hasattr(notice, "is_set") and notice.is_set():
            break
        _refusal_time.sleep(_launcher_seconds('refusal_poll_ms'))
    _exit_process(1)

def _hide_in_tray_if_enabled(widget):
    """Only an explicit graph setting and a live tray can keep the app open."""
    tray = getattr(widget, "_tray", None)
    owner = globals().get("server")
    if (getattr(widget, "quitting", False) or owner is None
            or tray is None or not tray.isVisible()):
        return False
    try:
        from nodelang.universal_application import read_universal_keep_running_in_tray
        enabled = read_universal_keep_running_in_tray(
            owner.universal_store.snapshot(), owner.universal_registry)
    except Exception as refusal:
        print("  tray       : setting unreadable (%s); window close quits" % type(refusal).__name__, flush=True)
        return False
    if not enabled:
        return False
    widget.hide()
    print("  tray       : window hidden (Keep running in tray is on; Quit ArchHub is in the menu)", flush=True)
    return True


# The window stands before the graph opens and shows the boot's own progress
# page ("phase k of n"); the graph opens off the Qt thread so the window keeps
# painting. A launch used to show nothing at all until the boot had finished.
_boot_surface = None
if not os.environ.get("ARCHHUB_TEST_NO_OPEN"):
    from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer, QUrl, QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    app.setApplicationName("ArchHub")
    app.setOrganizationName("ArchHub")

    profile_root = state_dir / "web-profile"
    profile_root.mkdir(parents=True, exist_ok=True)
    profile = QWebEngineProfile.defaultProfile()
    profile.setPersistentStoragePath(str(profile_root))
    profile.setCachePath(str(profile_root / "cache"))
    _window_quit_started = {"value": False}

    def _quit_from_window(widget=None):
        if _window_quit_started["value"]:
            return
        _window_quit_started["value"] = True
        import threading as _quit_threading
        import time as _quit_time
        update = getattr(globals().get("server"), "application_update", None)
        try:
            applying_update = update is not None and update.apply_on_quit()
        except Exception as refusal:
            print("  update     : quit policy unreadable (%s)" % type(refusal).__name__, flush=True)
            applying_update = False
        if not applying_update:
            duration = _launcher_seconds('quit_watchdog_ms')
            _quit_threading.Thread(
                target=lambda: (_quit_time.sleep(duration), os._exit(0)), daemon=True
            ).start()
        # A ready update uses the existing bounded recovery/installer timeouts;
        # a three-second hard exit could abandon a live installer mid-write.
        try:
            app.closeAllWindows()
            for top in app.topLevelWidgets():
                top.deleteLater()
        except Exception:
            if widget is not None:
                try:
                    widget.close()
                    widget.deleteLater()
                except Exception as error:
                    print("  shutdown   : could not close fallback window: %s" % error, flush=True)
        QTimer.singleShot(0, app.quit)

    class _WindowsCloseFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            if sys.platform != "win32" or event_type not in (
                b"windows_generic_MSG", b"windows_dispatcher_MSG",
                "windows_generic_MSG", "windows_dispatcher_MSG",
            ):
                return False, 0
            import ctypes as _close_ctypes
            from ctypes import wintypes as _close_wintypes

            class _MSG(_close_ctypes.Structure):
                _fields_ = [
                    ("hwnd", _close_wintypes.HWND), ("message", _close_wintypes.UINT),
                    ("wParam", _close_wintypes.WPARAM), ("lParam", _close_wintypes.LPARAM),
                    ("time", _close_wintypes.DWORD), ("pt", _close_wintypes.POINT),
                ]

            msg = _MSG.from_address(int(message))
            if msg.message != 0x0010:
                return False, 0
            _close_ctypes.windll.user32.GetAncestor.restype = _close_wintypes.HWND
            _close_ctypes.windll.user32.GetAncestor.argtypes = [
                _close_wintypes.HWND, _close_wintypes.UINT,
            ]
            root = _close_ctypes.windll.user32.GetAncestor(msg.hwnd, 2) or msg.hwnd
            length = _close_ctypes.windll.user32.GetWindowTextLengthW(root)
            title = _close_ctypes.create_unicode_buffer(length + 1)
            _close_ctypes.windll.user32.GetWindowTextW(root, title, length + 1)
            if title.value.startswith("ArchHub"):
                if not _hide_in_tray_if_enabled(window):
                    _quit_from_window(window)
                return True, 0
            return False, 0

    class _ArchHubWindow(QMainWindow):
        """Closing any ArchHub top-level window quits the desktop process."""
        quitting = False

        def closeEvent(self, event):
            if _hide_in_tray_if_enabled(self):
                event.ignore()
                return
            self.quitting = True
            event.accept()
            _quit_from_window(self)


    window = _ArchHubWindow()
    class _LaunchSignal(QObject):
        requested = pyqtSignal(list)
    _launch_signal = _LaunchSignal(app)
    app.setProperty('archhubLaunchArguments', sys.argv[1:])
    def _resume_from_launch(arguments):
        app.setProperty('archhubLaunchArguments', arguments)
        window.showNormal()
        window.raise_()
        window.activateWindow()
    _launch_signal.requested.connect(_resume_from_launch)
    import threading as _instance_threading
    _instance_threading.Thread(target=_serve_launch_requests,
        args=(_instance_lock, _launch_signal.requested.emit),
        name='ArchHub launch activation', daemon=True).start()
    # The instance fence stays held through final recovery and update apply.
    _native_close_filter = _WindowsCloseFilter()
    app.installNativeEventFilter(_native_close_filter)
    app._archhub_native_close_filter = _native_close_filter
    window.setWindowTitle("ArchHub")
    # The brand icon, and a distinct AppUserModelID so the taskbar shows
    # ArchHub rather than grouping under python's default.
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ArchHub")
    from PyQt6.QtGui import QIcon
    # Source and installer use the same owned asset beside this launcher.
    _icon_path = Path(__file__).resolve().parents[1] / "archhub.ico"
    if _icon_path.is_file():
        _brand_icon = QIcon(str(_icon_path))
        app.setWindowIcon(_brand_icon)
        window.setWindowIcon(_brand_icon)
    window.resize(1480, 920)
    window.setMinimumSize(960, 640)
    view = QWebEngineView(window)
    window.setCentralWidget(view)
    from nodelang.studio_window import forget_pages_behind_studio, lock_studio_navigation
    # One page lives in this window: no native Back/Reload menu, and nothing behind the Studio.
    lock_studio_navigation(view)
    from PyQt6.QtGui import QColor
    from nodelang.application import THEME as _BOOT_THEME
    from nodelang.clean_boot_surface import (
        BOOT_PHASES, boot_step_label, load_expected_phases, save_phase_durations,
    )
    from nodelang.desktop import create_boot_surface
    # The dark page colour before the first paint: never a white or blank window.
    view.page().setBackgroundColor(QColor(_BOOT_THEME["bg"]))
    _boot_probe = _socket.socket()
    _boot_probe.bind(("127.0.0.1", 0))
    _boot_port = _boot_probe.getsockname()[1]
    _boot_probe.close()
    # The last start's phase seconds let the bar move within a long phase.
    _boot_surface = create_boot_surface(
        "127.0.0.1", _boot_port, expected=load_expected_phases(state_dir)).start()
    view.load(QUrl("http://127.0.0.1:%d/" % _boot_port))
    window.show()


def _off_the_qt_thread(work):
    """Run ``work`` on a worker thread while the window keeps painting."""
    if _boot_surface is None:
        return work()
    import threading as _boot_threading
    from PyQt6.QtCore import QEventLoop, QTimer
    outcome, done = {}, _boot_threading.Event()

    def run():
        try:
            outcome["value"] = work()
        except BaseException as failure:
            outcome["error"] = failure
        finally:
            done.set()

    _boot_threading.Thread(target=run, name="archhub-open-graph", daemon=True).start()
    loop, poll = QEventLoop(), QTimer()
    poll.setInterval(50)
    poll.timeout.connect(lambda: loop.quit() if done.is_set() else None)
    poll.start()
    loop.exec()
    poll.stop()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _boot_step_seen(stack):
    """The boot sampler's stack, as the boot page's live step (sampler thread)."""
    if _boot_surface is not None:
        _boot_surface.progress.detail(boot_step_label(stack))


def _migration_progress(status):
    """Renew the boot watchdog only when migration reports completed work."""
    global _boot_deadline, _migration_status
    _migration_status = status
    # A blocked syscall still gets the watchdog's traceback. Ordinary stalls
    # are refused by the migration checker with a source-preserving message.
    _boot_deadline = time.monotonic() + (status['stall_seconds'] + 5 if status else 90)
    _arm_boot_watchdog()
    if _boot_surface is not None:
        _boot_surface.progress.migration(status)


def _boot_phase(index, finished=False):
    from nodelang.clean_boot_surface import BOOT_PHASES
    label = BOOT_PHASES[index]
    (_finish_boot_phase if finished else _start_boot_phase)(label)
    if _boot_surface is not None:
        (_boot_surface.progress.finish if finished else _boot_surface.progress.begin)(label)


def _open_saved_graph(*, max_wait_seconds=45.0, sleep_seconds=1.0):
    server, boot_refusal = None, None
    try:
        server = _boot()
    except Exception as refusal:
        import traceback
        traceback.print_exc()
        boot_refusal = refusal
        import gc

        gc.collect()
        # A failed first attempt can leave OUR OWN owner fence behind; the
        # conflict then names this very process. Releasing our own lock is
        # honest -- it is nobody else's.
        _release_own_fence(refusal)
        # A predecessor can still be releasing the graph OS owner fence after
        # an update relaunch. Wait for that exact condition; never force-take
        # the lock and never create a replacement graph.
        if not _is_transient_owner_conflict(refusal):
            return server, boot_refusal
        started_wait = time.monotonic()
        _open_attempt = 1
        while time.monotonic() - started_wait < max_wait_seconds:
            delay = min(float(sleep_seconds), max_wait_seconds - (time.monotonic() - started_wait))
            if delay <= 0:
                break
            print("  owner lock still held; retrying saved graph open attempt %d in %.1fs (%s)"
                  % (_open_attempt + 1, delay, str(boot_refusal).splitlines()[-1][:160]),
                  flush=True)
            time.sleep(delay)
            try:
                server = _boot()
                print("  recovered  : the saved graph opened on attempt %d"
                      % (_open_attempt + 1), flush=True)
                boot_refusal = None
                break
            except Exception as again:
                boot_refusal = again
                # Each failed attempt can leave OUR OWN fence behind; without
                # clearing it every later attempt fails on ourselves.
                _release_own_fence(again)
                if not _is_transient_owner_conflict(again):
                    break
                _open_attempt += 1
    return server, boot_refusal


def _open_saved_graph_with_recovery():
    """Keep a failed desktop boot on its existing splash until the user chooses."""
    global _boot_deadline
    opened, refusal = _open_saved_graph()
    while refusal is not None and _boot_surface is not None:
        # Waiting for the user is not stalled migration work. The next attempt
        # arms the watchdog again through its normal completed-work callbacks.
        _boot_deadline = None
        faulthandler.cancel_dump_traceback_later()
        _boot_surface.progress.fail(str(refusal))
        if _boot_surface.progress.wait_for_action() == "keep":
            _exit_process(0)
        _boot_deadline = time.monotonic() + 90
        _arm_boot_watchdog()
        opened, refusal = _open_saved_graph()
    return opened, refusal


_finish_boot_phase("prepare desktop")
_boot_phase(0)
server, boot_refusal = _off_the_qt_thread(_open_saved_graph_with_recovery)
_boot_phase(0, finished=True)
# A startup failure never selects a replacement graph. Recovery of damaged
# state is a separate operation; its files and original refusal stay visible.
if boot_refusal is not None:
    print("  could not open the saved graph: %s"
          % str(boot_refusal).splitlines()[-1][:160], flush=True)
    print("  the saved graph is KEPT IN PLACE. No replacement graph was created.", flush=True)
    _refuse_boot_without_living(boot_refusal)
print(f"  booted in {time.perf_counter()-started:.0f}s", flush=True)


def _tray_quit():
    window.quitting = True
    app.quit()


if not os.environ.get("ARCHHUB_TEST_NO_OPEN"):
    from nodelang.window_commands import bind_window_commands
    _window_commands = bind_window_commands(view, window, _tray_quit, server.public_url)
_boot_phase(1)

# Brain and Workshop belong to the application owner opened above.
# Do not start, poll, replace or kill a separate legacy Brain on a fixed port.
print("  URL:", server.public_url, flush=True)


def _publish_map_to_cloud():
    """Push this graph's projection to the founder's 24/7 cloud cockpit.

    The cockpit is the map and the map is the graph -- so the cloud
    surface shows what the founder's application actually holds, and
    keeps showing the last known state when the desktop is closed.
    """
    import json
    import urllib.request

    # The website promises nothing leaves this machine. The upload runs
    # only when this machine holds an explicit consent record; deleting
    # that file closes the path again.
    from nodelang.cloud_publish_consent import cloud_publish_allowed
    if not cloud_publish_allowed(state_dir):
        return "off (no consent recorded; nothing left this machine)"
    from nodelang.cloud_session import cloud_session_path
    cloud = cloud_session_path()
    if not cloud.is_file():
        return "no cloud session on this machine"
    from nodelang.cloud_signin import read_cloud_session
    held = read_cloud_session(cloud)
    token = held.get("token")
    from nodelang.cloud_relay import pinned_cloud_base
    base = pinned_cloud_base(held.get("cloud_base_url"))
    if not token:
        return "cloud session carries no token"
    from nodelang.universal_pipeline import project_atlas_map

    script = project_atlas_map(
        server.universal_store, server.universal_registry
    )
    body = script.split("window.ATLAS_MAP = ", 1)[1]
    body = body.rsplit("; window.ATLAS_LIVE", 1)[0].encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + "/founder/map-state", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_launcher_seconds('account_http_ms')) as answer:
        return json.loads(answer.read().decode("utf-8"))


import threading as _threading

_cloud_publish_stop = _threading.Event()
_cloud_publish_thread = None


def _publish_map_quietly():
    """Attempt one bounded background publication without blocking window or tray display."""
    if _cloud_publish_stop.is_set():
        return
    try:
        outcome = _publish_map_to_cloud()
        if not _cloud_publish_stop.is_set():
            print("  cloud map  :", outcome, flush=True)
    except Exception as _refusal:
        if _cloud_publish_stop.is_set():
            return
        if getattr(_refusal, "code", None) in (401, 403):
            print("  cloud map  : not published (HTTP %s): the cloud refused this request. "
                  "Check sign-in and access under Settings, Account."
                  % _refusal.code, flush=True)
        else:
            print("  cloud map  : not published (%s)" % str(_refusal)[:90], flush=True)


_cloud_publish_thread = _threading.Thread(
    target=_publish_map_quietly,
    name="archhub-cloud-map-publish",
    daemon=True,
)
_cloud_publish_thread.start()

# The machine announcement (a signed pointer) was written by the transport at
# start. It names this runtime's record, which says "stopped" after close();
# nothing is copied, kept, or restored here.
if os.environ.get("ARCHHUB_TEST_STATE_DIR"):
    print("  runtime    : not announced (verification run keeps the "
          "machine binding)", flush=True)


@contextlib.contextmanager
def _held_guard(owner, authority, context):
    with owner.mutation_lock, authority.broker.live_context(context):
        yield


def _startup_pipeline_state(owner):
    """Only this graph's unfinished first-run install may resume on reopen."""
    import json
    from nodelang.universal_cell import NULL_CELL_ID
    cell = owner.universal_store.snapshot().cells.get("app:startup:pipeline-install:v1")
    if cell is None:
        return None
    value = json.loads(cell.atom)
    if (cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID
            or value not in ({"state": "pending"}, {"state": "complete"})):
        raise ValueError("first-run pipeline install intent needs recovery")
    return value["state"]


def _record_startup_pipeline_intent(owner, *, first_boot, complete=False):
    from nodelang import commit_intent
    from nodelang.universal_cell import Cell, NULL_CELL_ID
    state = _startup_pipeline_state(owner)
    if state == "complete" or (state is None and not first_boot):
        return False
    authority = owner.universal_registry.authorization
    context = authority.session.context(minimum_validity_seconds=_launcher_parameter('session_minimum_validity_seconds'))
    with owner.mutation_lock, authority.broker.live_context(context):
        state = _startup_pipeline_state(owner)
        if state == "complete" or (state is None and not first_boot):
            return False
        if state == "pending" and not complete:
            return True
        cell = Cell("app:startup:pipeline-install:v1", NULL_CELL_ID, NULL_CELL_ID,
                    b'{"state":"complete"}' if complete else b'{"state":"pending"}')
        snapshot = owner.universal_store.snapshot()
        with commit_intent.declare(commit_intent.MIGRATION,
                actor=owner.universal_registry.application_root,
                reason="record the resumable first-run pipeline install"):
            owner.universal_store.commit(snapshot.revision,
                **({"create": (cell,)} if state is None else {"replace": (cell,)}))
        return not complete


def _initialize_startup_pipeline(owner, *, first_boot):
    """Resume an admitted new-graph install; never reseed other saved graphs."""
    if not _record_startup_pipeline_intent(owner, first_boot=first_boot):
        return None
    from nodelang import commit_intent
    from nodelang.universal_pipeline import seed_wall_pipeline
    authority = owner.universal_registry.authorization
    # The owner already serves requests. Use its ordinary mutation admission,
    # minting the existing process context before taking the mutation lock.
    # The first-run seed is the install of a new graph: it commits under the
    # admitted migration/install intent (nodelang/commit_intent.py), which the
    # commit gate otherwise refuses once construction has finished.
    for attempt in range(10):
        try:
            context = authority.session.context(minimum_validity_seconds=_launcher_parameter('session_minimum_validity_seconds'))
            with commit_intent.declare(
                    commit_intent.MIGRATION,
                    actor=owner.universal_registry.application_root,
                    reason="install the first-run pipeline seed of a new graph"):
                result = seed_wall_pipeline(owner.universal_store, owner.universal_registry,
                    authentication_context=context,
                    # Preparation reads immutable snapshots. Each seed write
                    # takes this guard independently so Home reads can answer.
                    settle_guard=lambda: _held_guard(owner, authority, context))
            _record_startup_pipeline_intent(owner, first_boot=first_boot, complete=True)
            return result
        except Exception as clash:
            # Only idempotent graph seeding may retry a revision conflict.
            # An engine invocation cannot safely be repeated on that evidence.
            if "expected revision" not in str(clash) or attempt == 9:
                raise
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError("Startup pipeline did not complete")


def _settle_canvas_content(owner):
    """Admitted migration: canvas content moves to its lens, in the background.

    Smoothness is a gate: the window opens and answers while this runs. It
    is prepared off the lock in small batches; the owner's mutation lock
    and then the live authentication context (the order every admitted
    write takes) are held only for each batch's commit, and launcher.log
    prints each hold. A graph that already holds the migration record
    commits nothing (nodelang/universal_pipeline.py settle_canvas_content).
    """
    import contextlib

    def run():
        from nodelang import commit_intent
        from nodelang.universal_pipeline import settle_canvas_content
        try:
            authority = owner.universal_registry.authorization
            context = authority.session.context(minimum_validity_seconds=_launcher_parameter('session_minimum_validity_seconds'))

            @contextlib.contextmanager
            def commit_guard():
                with owner.mutation_lock, authority.broker.live_context(context):
                    yield

            with commit_intent.declare(
                commit_intent.MIGRATION,
                actor=owner.universal_registry.application_root,
                reason="move canvas content to its lenses; tombstone the duplicate seed set",
            ):
                settle_canvas_content(owner.universal_store, owner.universal_registry,
                    authentication_context=context, guard=commit_guard,
                    # Few commits: each one invalidates the cached canvas and
                    # the next read re-projects it; the pause yields to reads.
                    batch_size=48, pause=1.0)
        except Exception as refusal:
            print("  canvas     : content not moved -- %s" % refusal, flush=True)

    _start_background_refresh(owner, run, name="canvas-content-migration")


# first_boot comes from the validated saved-graph check, not a UI marker.
# Existing graphs retain their nodes, parameters and previous results. Repair
# seeding and execution remain available through their admitted application routes.
# The Studio reads the same check (ARCHHUB_BOOT.first_run) to mount its onboarding.
server.studio_first_run = first_boot is True
# Record intent before admitting Home, so closing it before the worker starts
# cannot turn an unfinished new-graph install into an ordinary saved graph.
_off_the_qt_thread(lambda: _record_startup_pipeline_intent(server, first_boot=first_boot))


def _prepare_pipeline():
    print("  pipeline   : preparing optional canvas content", flush=True)
    try:
        _initialize_startup_pipeline(server, first_boot=first_boot)
        print("  pipeline   : %s; execution awaits an admitted Run" % (
            "initial seed checked" if first_boot else "saved graph retained"), flush=True)
        if not first_boot:
            _settle_canvas_content(server)
    except Exception as refusal:
        # A refusal nobody can locate is a refusal nobody can fix: name the
        # exact call that raised, not only its message.
        where = traceback.format_exc().strip().splitlines()
        spot = [line.strip() for line in where if "line " in line][-1:] or [""]
        print("  pipeline   : not seeded -- %s (%s)" % (refusal, spot[0]),
              flush=True)


_pipeline_start = {"started": False}


def _prepare_pipeline_after_home(held):
    """Admit optional work only after the real first screen has mounted."""
    if _pipeline_start["started"]:
        return
    from PyQt6.QtCore import QTimer

    def observed(ready):
        if _pipeline_start["started"]:
            return
        if not ready:
            QTimer.singleShot(250, lambda: _prepare_pipeline_after_home(held))
            return
        _pipeline_start["started"] = True
        _boot_phase_finish_all(held)
        _start_background_refresh(server, _prepare_pipeline, name="archhub-pipeline-after-home")

    view.page().runJavaScript("""(() => {
      const root = document.getElementById('root');
      if (!root?.children.length) return false;
      const home = [...document.querySelectorAll('[data-home-page],[data-home-tools],[data-screen="home"]')]
        .some(element => element.getBoundingClientRect().width > 0);
      const onboarding = document.querySelector('[data-studio-screen="onboarding"]');
      const explicitGraph = window.ARCHHUB_BOOT?.open_graph && window.ARCHHUB_LIVE?.graph;
      return Boolean((home && document.querySelectorAll('button').length > 5) || onboarding || explicitGraph);
    })()""", observed)

if os.environ.get("ARCHHUB_TEST_NO_OPEN"):
    _off_the_qt_thread(_prepare_pipeline)
    _boot_phase(1, finished=True)
    try:
        while True:
            time.sleep(_launcher_seconds('session_poll_ms'))
    except KeyboardInterrupt:
        print("  shutdown   : interrupted headless owner", flush=True)
    finally:
        server.close()
    raise SystemExit(0)

from nodelang.studio_downloads import install_studio_downloads


def _download_status(status):
    window.statusBar().showMessage(status["detail"])


_studio_downloads = install_studio_downloads(
    view.page().profile(), view.page(), server.public_url,
    parent=window, on_status=_download_status)
app.aboutToQuit.connect(_studio_downloads.close)
# The window goes from the boot page straight to the Studio: /studio consumes
# the one-time bootstrap and mints the session cookie itself, so the founder
# never sees the "/" universal document on the way in.
_booted = {"done": False}
_update_boot = {"pending": _staged.get("status") == "awaiting_boot", "checks": 0}


def _acknowledge_update_surface():
    """Acknowledge after the saved graph and Studio have actually mounted."""
    if not _update_boot["pending"]:
        return
    if _update_boot["checks"] >= 60:
        _update_boot["pending"] = False
        _update_rollback_requested.set()
        return
    _update_boot["checks"] += 1

    def observed(ready):
        if ready:
            _update_boot["pending"] = False
            def confirm():
                from nodelang.quiet_update import confirm_applied
                # File restoration waits for the same final close as every update.
                result = confirm_applied(state_dir, Path(__file__).resolve().parents[1], rollback=False)
                print("  update     : %s" % result.get("reason"), flush=True)
                if not result.get("confirmed"):
                    _update_rollback_requested.set()
            import threading as _ack_threading
            _ack_threading.Thread(target=confirm, name="archhub-update-boot-ack", daemon=True).start()
        else:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, _acknowledge_update_surface)

    view.page().runJavaScript(
        "Boolean(window.ARCHHUB_LIVE && window.ARCHHUB_LIVE.graph && "
        "document.getElementById('root')?.children.length)", observed)


def _studio_entry_url():
    token = server.browser_bootstrap_token
    return server.public_url + "/studio" + ("?bootstrap=" + token if token else "")


def _to_studio(ok):
    if ok and not _booted["done"]:
        _booted["done"] = True
        if not view.url().path().startswith("/studio"):
            view.load(QUrl(server.public_url + "/studio"))
            return
    if ok and view.url().path().startswith("/studio"):
        # Every page before the Studio (the boot page) is forgotten:
        # Back, Alt+Left and the mouse's Back button cannot leave the Studio.
        forget_pages_behind_studio(view)
        _acknowledge_update_surface()
view.loadFinished.connect(_to_studio)
# The studio's Browse buttons open THIS window's native file dialog; the
# chosen path goes back over the same origin. The request arrives on an HTTP
# worker thread; the dialog must run on the Qt thread (see gui_thread).
from nodelang.gui_thread import GuiThreadAsker
_ask_on_gui_thread = GuiThreadAsker(app)
def _pick_file(title, name_filter):
    from PyQt6.QtWidgets import QFileDialog
    return _ask_on_gui_thread(lambda: QFileDialog.getOpenFileName(
        window, title, "", name_filter or "All files (*.*)")[0], 120) or ""
# Settings -> Workspaces "Browse": the same window-owned dialog, for a folder.
def _pick_folder(title):
    from PyQt6.QtWidgets import QFileDialog
    return _ask_on_gui_thread(
        lambda: QFileDialog.getExistingDirectory(window, title, ""), 600) or ""
import threading
server.native_file_picker = _pick_file
server.native_folder_picker = _pick_folder
# Settings -> Workspaces Add/Remove: the owner's Windows key prompt is shown in
# front of THIS window (the graph's owner process has no window of its own).
server.native_window_handle = int(window.winId())
# A dead render process reloads instead of leaving a dead window.
def _revive(_status, _code):
    print("  render process died -- reloading", flush=True)
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(300, lambda: view.load(
        QUrl(server.public_url + "/studio")))
view.page().renderProcessTerminated.connect(_revive)
def _boot_phase_finish_all(held):
    _finish_boot_phase(BOOT_PHASES[1])
    for label in BOOT_PHASES:
        held.progress.finish(label)
    save_phase_durations(held.progress, state_dir)


def _release_boot_surface(ok):
    """The window has left the boot page: its port is released (off the Qt thread)."""
    global _boot_surface
    held = _boot_surface
    if not ok or held is None or view.url().port() == _boot_port:
        return
    _boot_surface = None
    # This start's phase seconds become the next start's expectation.
    _prepare_pipeline_after_home(held)
    import threading as _release_threading
    _release_threading.Thread(target=held.hand_over, name="archhub-boot-release", daemon=True).start()
if _boot_surface is not None:
    view.loadFinished.connect(_release_boot_surface)
view.load(QUrl(_studio_entry_url()))
window.show()

# The tray icon: the visible sign that ArchHub is running in the background.
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

def _tray_open():
    from PyQt6.QtCore import QTimer as _QT
    window.showNormal(); window.raise_(); window.activateWindow()

    def _settle():
        # Qt alone leaves the window behind everything else on Windows. The
        # foreground dance runs after Qt has applied the state rather than
        # the same instant as showNormal(), restores once more if something
        # minimized the window meanwhile, and says where the window ended up
        # so the launcher log is the receipt (2026-09-06: a screen-capture
        # tool minimizing every window it was not allowed to see made the
        # window look minimized by us; the receipt settles that question).
        _force_foreground(window.winId(), explicit_activation=True)
        try:
            import ctypes
            user32 = ctypes.windll.user32
            handle = int(window.winId())
            if user32.IsIconic(handle):
                user32.ShowWindow(handle, 9)
            rect = (ctypes.c_long * 4)()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            print("  show       : window %dx%d at %d,%d iconic=%s" % (
                rect[2] - rect[0], rect[3] - rect[1], rect[0], rect[1],
                bool(user32.IsIconic(handle))), flush=True)
        except Exception as failed:
            print("  show       : receipt unavailable: %s" % failed, flush=True)

    _QT.singleShot(150, _settle)

import threading as _restart_threading
_update_restart_requested = _restart_threading.Event()
_update_rollback_requested = _restart_threading.Event()
_restart_after_shutdown = False
_apply_after_quit = False
from nodelang.application_update import ApplicationUpdate, restart_block_reason
from PyQt6.QtCore import (
    QObject as _UpdateObject, Qt as _UpdateQt, pyqtSignal as _update_signal, pyqtSlot as _update_slot,
)


def _report_update_check(line):
    # Every finished release check (quiet cadence, tray or Studio) leaves its decision here.
    print("  update     : %s" % line, flush=True)


class _UpdatePush(_UpdateObject):
    """Carries a download that reached ready from its worker to the desktop page."""
    ready = _update_signal()

    def __init__(self, parent, page):
        super().__init__(parent)
        self.page = page
        self.ready.connect(self.push, _UpdateQt.ConnectionType.QueuedConnection)

    @_update_slot()
    def push(self):
        # The compiled design re-reads the existing lifecycle when staging completes.
        self.page.runJavaScript(
            "window.dispatchEvent(new Event('archhub:update-ready'))")


_update_push = _UpdatePush(app, view.page())


def _update_policy():
    from nodelang.universal_application import read_universal_update_policy
    return read_universal_update_policy(server.universal_store.snapshot(), server.universal_registry)


server.application_update = ApplicationUpdate(state_dir, Path(__file__).resolve().parents[1],
    request_restart=_update_restart_requested.set, initial_stage=_staged, report=_report_update_check,
    on_ready=_update_push.ready.emit, first_boot=first_boot,
    restart_refusal=lambda: restart_block_reason(server), policy=_update_policy)
server._desktop_request_update_restart = server.application_update.reload


def _begin_update_exit():
    global _restart_after_shutdown
    _restart_after_shutdown = True
    window.quitting = True
    app.quit()

def _watch_quit_request() -> None:
    """Quit cleanly when asked from outside, so the tray icon goes with us.

    Every update this week ended with the process being killed, and Windows
    keeps a dead process's tray icon until the mouse crosses it: the founder
    clicked ArchHub in the tray and nothing opened, because that icon belonged
    to a process that was gone (14 of them in one day, 2026-09-06). A file in
    the state directory is the ask; the app quits the way the menu quits.
    """
    from PyQt6.QtCore import QTimer as _QT

    marker = state_dir / "quit-request"
    # The same file-shaped ask brings the window up: an updater, a colleague
    # script or a verification run can open ArchHub the way the tray click
    # does, on the Qt thread, without touching the window from outside
    # (an external ShowWindow leaves Qt believing the widget is hidden).
    shower = state_dir / "show-request"
    # A marker written before THIS process started was meant for the copy that
    # is already gone. Leaving it made a freshly installed build read it and
    # quit itself the moment it finished booting (2026-09-06 13:19). Clear it
    # once, at startup, before anyone watches for it.
    try:
        if marker.is_file():
            marker.unlink()
    except OSError as error:
        print("  startup    : could not clear stale quit request: %s" % error, flush=True)
    try:
        if shower.is_file():
            shower.unlink()
    except OSError as error:
        print("  startup    : could not clear stale show request: %s" % error, flush=True)

    def _look():
        if _update_rollback_requested.is_set():
            _begin_update_exit()
            return
        if _update_restart_requested.is_set():
            _update_restart_requested.clear()
            def admitted(dirty):
                reason = "Save unsaved work before restarting." if dirty else restart_block_reason(server)
                if reason:
                    server.application_update.refuse_restart(reason)
                    _update_push.ready.emit()
                else:
                    _begin_update_exit()
            view.page().runJavaScript(
                "typeof window.ARCHHUB_UPDATE_RESTART_BLOCKED !== 'function' || "
                "window.ARCHHUB_UPDATE_RESTART_BLOCKED()", admitted)
            return
        if shower.is_file():
            try:
                shower.unlink()
            except OSError as error:
                print("  show       : could not remove show request: %s" % error, flush=True)
            print("  show       : asked from outside; bringing the window up", flush=True)
            _tray_open()
        if marker.is_file():
            try:
                marker.unlink()
            except OSError as error:
                print("  quit       : could not remove quit request: %s" % error, flush=True)
            print("  quit       : asked from outside; leaving cleanly", flush=True)
            _tray_quit()

    timer = _QT(app)
    timer.setInterval(2000)
    timer.timeout.connect(_look)
    timer.start()
    app._archhub_quit_watch = timer

_watch_quit_request()
if QSystemTrayIcon.isSystemTrayAvailable():
    _tray = QSystemTrayIcon(app.windowIcon(), app)
    _tray.setToolTip("ArchHub - running")
    _menu = QMenu()
    _menu.addAction("Open ArchHub", _tray_open)
    _menu.addSeparator()
    _menu.addAction("Quit ArchHub", _tray_quit)
    _tray.setContextMenu(_menu)
    _tray.activated.connect(lambda reason: _tray_open() if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
    _tray.show()
    window._tray = _tray
    # The notify card lands on this tray. Engines run on worker threads and
    # Qt widgets belong to this one, so the ask crosses over as a queued
    # signal rather than a direct call.
    from PyQt6.QtCore import QObject as _QObject, pyqtSignal as _signal
    from nodelang.library_engines import set_notify_surface

    class _Notifier(_QObject):
        asked = _signal(str, str)

    _notifier = _Notifier(app)
    _notifier.asked.connect(lambda title, message: _tray.showMessage(title, message))
    set_notify_surface(lambda title, message: _notifier.asked.emit(str(title), str(message)))
    app.setQuitOnLastWindowClosed(True)
    print("  tray       : icon shown (window close quits by default; Keep running in tray is in Settings; Quit is in the menu)", flush=True)
else:
    print("  tray       : no system tray on this desktop", flush=True)
# A window that opens BEHIND the founder's other windows reads as "the
# app didn't open". Every launch lands on top, once.
window.raise_()
window.activateWindow()

# BABOOM: one signed host, prepared off the GUI thread and projected on it.
# The relay resolves this attachment per request, including after a slow boot.
baboom_host = None
baboom_window = None
_baboom_stop = threading.Event()
_baboom_off_reason = None
def _stop_baboom_for_user():
    _baboom_stop.set()
    host = baboom_host or _baboom_attachment.pending_host
    if host is not None:
        host.request_stop()
    if baboom_window is not None and not baboom_window._stopped:
        baboom_window.stop_baboom()
    print("  BABOOM     : stopped accepting requests; in-flight operations may finish", flush=True)


if '_menu' in globals():
    _menu.addSeparator()
    _menu.addAction("Stop BABOOM for this launch", lambda: _stop_baboom_for_user())
from PyQt6.QtCore import (
    QObject as _BaboomObject, QTimer as _BaboomTimer, Qt as _BaboomQt,
    pyqtSignal as _baboom_signal, pyqtSlot as _baboom_slot,
)


class _BaboomAttachment(_BaboomObject):
    ready = _baboom_signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.worker = None
        self.pending_host = None
        self.prepared_atlas = None
        self.ready.connect(self.land, _BaboomQt.ConnectionType.QueuedConnection)

    def shutdown(self):
        """Quiesce attachment before its server or journal can be closed."""
        _baboom_stop.set()
        if self.worker is not None:
            self.worker.join(timeout=_launcher_seconds('worker_join_ms'))
            if self.worker.is_alive():
                raise RuntimeError("BABOOM attachment did not stop; server teardown refused")
        host = self.pending_host or baboom_host
        if host is not None:
            host.stop(timeout_seconds=_launcher_seconds('host_stop_ms'))
            if host.running:
                raise RuntimeError("BABOOM heartbeat did not stop; server teardown refused")

    @_baboom_slot(object)
    def land(self, host):
        global baboom_host, baboom_window
        # Shutdown and duplicate deliveries cannot create an extra companion.
        if _baboom_stop.is_set() or baboom_host is not None:
            if host is not baboom_host:
                host.stop(timeout_seconds=_launcher_seconds('host_cancel_ms'))
            return
        companion = None
        try:
            from nodelang.baboom_native_runtime import create_baboom_native_projection
            companion = create_baboom_native_projection(
                host, atlas=self.prepared_atlas,
                position_path=state_dir / "baboom-position.json", on_stop=_stop_baboom_for_user
            )
            controller = getattr(companion, "controller", None)
            try:
                if controller is not None and hasattr(controller, "watch_geometry"):
                    controller.watch_geometry(state_dir / "baboom-geometry.log")
            except Exception:
                print("  BABOOM     : geometry logging unavailable", flush=True)
            companion.show()
            companion.start_projection()
            host.start()
            baboom_window = companion
            baboom_host = host
            server.app_agents.companion = host
            print("  BABOOM     : attached (signed agent session)", flush=True)
        except Exception as refusal:
            host.stop(timeout_seconds=_launcher_seconds('host_cancel_ms'))
            if companion is not None:
                companion.close()
                companion.deleteLater()
            print("  BABOOM     : projection unavailable (%s)" % type(refusal).__name__, flush=True)


_baboom_attachment = _BaboomAttachment(app)
app.aboutToQuit.connect(_baboom_stop.set)


def _baboom_startup_choice():
    """Read the owner's BABOOM startup choice from the graph, on the attach worker.

    Returns "on", "off", or None when the launch closes during the lock wait.
    An undecodable setting raises, and the caller then does not start BABOOM.
    No session context is used, so an expired owner lease cannot hide BABOOM.
    """
    while not server.mutation_lock.acquire(timeout=_launcher_seconds('mutation_poll_ms')):
        if _baboom_stop.is_set():
            return None
    try:
        if _baboom_stop.is_set():
            return None
        from nodelang.universal_application import read_universal_baboom_startup
        return read_universal_baboom_startup(
            server.universal_store.snapshot(), server.universal_registry
        )["value"]
    finally:
        server.mutation_lock.release()


def _keep_attaching():
    global _baboom_off_reason
    from nodelang.application_machine_transport import MachineNoResponse, MachineNotSent
    from nodelang.baboom_attach import prepare_baboom_host

    host = None
    handed_off = False
    try:
        # Settings decide this launch before any key file, custody commit or
        # retry. An unreadable setting fails closed and says so.
        try:
            choice = _baboom_startup_choice()
            if choice not in (None, "on", "off"):
                raise ValueError("BABOOM startup value must be on or off")
        except Exception as refusal:
            _baboom_off_reason = "BABOOM did not start because its Settings value is unreadable; no action was performed."
            print("  BABOOM     : not started; startup setting unreadable (%s)" % type(refusal).__name__, flush=True)
            return
        if choice is None:
            return
        if choice == "off":
            _baboom_off_reason = "BABOOM is turned off in Settings; no action was performed."
            print("  BABOOM     : off (Settings); not started this launch", flush=True)
            return
        for attempt in range(40):
            if _baboom_stop.wait(0.0 if attempt == 0 else 15.0):
                return
            try:
                if host is None:
                    host = prepare_baboom_host(
                        server, state_dir=state_dir, descriptor_path=descriptor_path,
                        key_provider=machine_key_provider,
                        external_session_id="founder-desktop-baboom",
                        cancellation_event=_baboom_stop,
                    )
                    _baboom_attachment.pending_host = host
                if _baboom_stop.is_set():
                    return
                # A failed first frame retains the already signed client. A retry
                # renews that presence instead of minting another Agent Session.
                host.connect()
            except Exception as refusal:
                # Retried inside the 40 x 15 s budget: a request that never
                # left (the runtime was not reachable yet), and no answer from
                # a runtime busy at boot (2026-09-07) -- but only while no
                # enrollment has been sent, so nothing was minted. Once the
                # enrollment left, a lost answer is final (a retry would be
                # refused as "already bound"); so is any unanswered presence,
                # activity or frame request, and anything else.
                retryable = isinstance(refusal, (MachineNotSent, ConnectionRefusedError)) or (
                    isinstance(refusal, MachineNoResponse)
                    and host is not None and not host.enrollment_sent)
                print("  BABOOM     : %s (attempt %d, %s: %s)" % (
                    "waiting for runtime" if retryable else "attachment refused",
                    attempt + 1, type(refusal).__name__, str(refusal)[:200]), flush=True)
                if retryable:
                    continue
                return
            if _baboom_stop.is_set():
                return
            # The sprite atlas is decoded here, never on the GUI thread: it
            # froze the window for seconds while the Studio loaded. A failed
            # inspection leaves None and land() refuses exactly as before.
            try:
                from nodelang.goose_runtime import start_goose_for_baboom
                start_goose_for_baboom(server, host,
                    app_root=Path(__file__).resolve().parents[1], state_dir=state_dir,
                    cancellation_event=_baboom_stop)
            except Exception as refusal:
                # Keep the face available so a missing package is visible. The
                # ask boundary refuses; it never falls back to the retired loop.
                print("  BABOOM     : Goose unavailable (%s)" % type(refusal).__name__, flush=True)
            try:
                from nodelang.baboom_native_runtime import prepare_baboom_native_atlas
                _baboom_attachment.prepared_atlas = prepare_baboom_native_atlas()
            except Exception:
                _baboom_attachment.prepared_atlas = None
            # This receiver was created on the GUI thread. No Qt object is
            # constructed by this worker; an undelivered host has no heartbeat.
            try:
                _baboom_attachment.ready.emit(host)
            except RuntimeError:
                print("  BABOOM     : attachment receiver unavailable", flush=True)
                return
            handed_off = True
            return
        print("  BABOOM     : runtime remained unavailable after 40 attempts", flush=True)

    finally:
        if host is not None and not handed_off:
            host.stop(timeout_seconds=_launcher_seconds('host_cancel_ms'))


def _start_baboom_attachment():
    if not _baboom_stop.is_set() and _baboom_attachment.worker is None:
        _baboom_attachment.worker = threading.Thread(
            target=_keep_attaching, name="archhub-baboom-attach", daemon=True
        )
        _baboom_attachment.worker.start()


# Start only once the window's event loop is processing events.
_BaboomTimer.singleShot(0, _start_baboom_attachment)


def _cockpit_respond(utterance):
    if _baboom_stop.is_set():
        raise RuntimeError("ArchHub is closing; the request was not performed")
    host = baboom_host
    if host is not None:
        # The cockpit never receives a confirmation: a restart or a remember
        # is confirmed on the desktop companion only (founder decision
        # 2026-09-30). The offer is still described.
        answered = dict(host.respond_input(utterance))
        response = dict(answered.get("response") or {})
        data = dict(response.get("data") or {})
        if data.pop("confirm_utterance", None) is not None:
            data["requires"] = "confirm on the desktop"
            response["data"] = data
            answered["response"] = response
        return answered
    from nodelang.universal_application import (
        finish_universal_baboom_response, respond_universal_baboom_utterance,
    )
    with server.mutation_lock:
        answered = respond_universal_baboom_utterance(
            server.universal_store, server.universal_registry,
            utterance=utterance,
            authentication_context=server.universal_registry.authorization.session.context(),
        )
    # Slow host reads (repo status) run after the lock.
    return finish_universal_baboom_response(answered)


def _cockpit_execute(utterance):
    if _baboom_stop.is_set():
        raise RuntimeError("ArchHub is closing; the request was not performed")
    host = baboom_host
    if host is None:
        if _baboom_off_reason is not None:
            raise RuntimeError(_baboom_off_reason)
        raise RuntimeError("BABOOM is not attached; no action was performed. Retry when it connects.")
    from nodelang.universal_application import baboom_confirmation_nonce
    if baboom_confirmation_nonce(utterance) is not None:
        # Only the desktop companion confirms a restart or a remember.
        raise RuntimeError("That act is confirmed on the desktop only; no action was performed.")
    # Exactly the same signed method used by the companion, never a fallback
    # server mutation or a GUI-bound controller call from the relay worker.
    return host.execute_input(utterance)


def _cockpit_offer():
    # The offer the cockpit states is the one record the app holds, never a copy.
    from nodelang.cell_accounts import published_offer
    return published_offer(server.universal_store.snapshot())


def _cockpit_offer_command(utterance, execute):
    # The cockpit's offer control changes the one offer record, as the founder
    # the CLOUD names for this machine's session (/v1/me + its founder-only
    # route), never the email cloud.json holds: that file is editable. Any
    # other words return None and go to BABOOM exactly as before.
    from nodelang.cell_accounts import apply_offer_command, parse_offer_command
    from nodelang.cloud_session import signed_in_founder_account
    if parse_offer_command(utterance) is None:
        return None
    if _baboom_stop.is_set():
        raise RuntimeError("ArchHub is closing; the request was not performed")
    with server.mutation_lock:
        return apply_offer_command(
            server.universal_store, utterance,
            founder_account=signed_in_founder_account(), execute=execute,
        )


cloud_relay = None
try:
    from nodelang.cloud_relay import McpWorkshopAgents as _McpAgents, start_cloud_relay as _start_relay
    from nodelang.universal_pipeline import project_atlas_map as _atlas
    # Spark, Notion and any other MCP client the founder connected with Workshop
    # access: each is its own agent in this app's Workshop. If that cannot be
    # set up, the relay still starts; only Workshop steps are refused.
    try:
        _mcp_workshop_caller = _McpAgents(descriptor_path, machine_key_provider).call
    except Exception as refusal:
        _mcp_workshop_caller = None
        print("  workshop   : MCP agents unavailable (%s)" % type(refusal).__name__, flush=True)
    cloud_relay = _start_relay(
        appdata=None, state_dir=state_dir,
        respond=_cockpit_respond, execute=_cockpit_execute,
        map_script=lambda: _atlas(server.universal_store, server.universal_registry),
        hosts=lambda: server._host_rows(),
        offer=_cockpit_offer,
        offer_command=_cockpit_offer_command,
        workshop_caller=_mcp_workshop_caller,
    )
    print("  cockpit    :", "relay on (actions wait for signed BABOOM attachment)"
          if cloud_relay else "relay off (no cloud session or consent)", flush=True)
except Exception as refusal:
    print("  cockpit    : relay unavailable (%s)" % type(refusal).__name__, flush=True)

# Reuse one existing background worker for local desktop trust and updates.
# No navigation, model work or new session roots occur during renewal.
_desktop_refresh_client = None
_desktop_refresh_status = None
_retention_cursor = None
_retention_status = None
_trace_retention_cursor = None
_trace_retention_status = None
_trace_inventory_completed_at = None


def _renew_desktop_session():
    global _desktop_refresh_client, _desktop_refresh_status
    if _update_stop.is_set():
        return
    from time import monotonic as renewal_clock
    renewal_started = renewal_clock()
    response = None
    try:
        if _desktop_refresh_client is None:
            from nodelang.application_machine_transport import UniversalRuntimeClient
            client = UniversalRuntimeClient(descriptor_path, machine_key_provider,
                cancellation_event=_update_stop)
            client.pin_runtime_descriptor(server.machine_transport._descriptor("active"))
            _desktop_refresh_client = client
        response = _desktop_refresh_client.request("POST", "/api/universal/browser-handoff", {},
            response_timeout_seconds=_launcher_seconds('desktop_refresh_ms'))
        if (response.get("application") != server.universal_registry.application_root
                or response.get("session_root") != server.browser_session_root
                or response.get("one_use") is not True):
            raise RuntimeError("Desktop renewal returned another authority")
        status = "ready"
    except Exception as refusal:
        if _update_stop.is_set():
            return
        from nodelang.application_machine_transport import (
            MachineEffectOutcomeUnknown, MachineResponseError, MachineTransportError,
        )
        status = type(refusal).__name__
        # A transport failure with a fixed message (the base class or the
        # never-sent subclass) maps to its code; a server refusal or an
        # unknown outcome carries server text and keeps only its class name.
        if isinstance(refusal, MachineTransportError) and not isinstance(
                refusal, (MachineResponseError, MachineEffectOutcomeUnknown)):
            status = "MachineTransportError"
            # Only fixed transport messages may become diagnostic codes. Never
            # log a server error, response body, URL or credential-bearing text.
            code = {
                "universal runtime is not active": "not_active",
                "universal runtime owner changed; reconnect through admitted enrollment": "owner_changed",
                "machine request exceeds its size limit": "too_large",
                "universal runtime pipe is unavailable": "pipe_unavailable",
                "universal runtime response timeout is invalid": "invalid_timeout",
                "universal runtime did not respond": "no_response",
                "universal runtime response is invalid": "invalid_response",
                "universal runtime response binding failed": "binding_failed",
                "universal runtime response status is invalid": "invalid_status",
                "universal runtime result is invalid": "invalid_result",
            }.get(str(refusal), "other")
            status += "[" + code + "]"
    finally:
        if isinstance(response, dict):
            response.clear()  # Never retain or log the unused handoff URL.
    if status != _desktop_refresh_status:
        _desktop_refresh_status = status
        elapsed = "" if status == "ready" else " after %.1fs" % (renewal_clock() - renewal_started)
        print("  desktop session : %s%s" % (status, elapsed), flush=True)


def _conversation_maintenance_context():
    session = server.universal_registry.authorization.session
    held = []
    try:
        for lock in (session._lock, session.broker._lock):
            if not lock.acquire(blocking=False):
                return None
            held.append(lock)
        return session.context(minimum_validity_seconds=_launcher_parameter('session_minimum_validity_seconds'))
    finally:
        for lock in reversed(held):
            lock.release()


@contextlib.contextmanager
def _trace_background_priority():
    """Lower only this existing worker's CPU/I/O priority, never the GUI."""
    kernel, handle = None, None
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentThread.restype = ctypes.c_void_p
        kernel.SetThreadPriority.argtypes = (ctypes.c_void_p, ctypes.c_int)
        kernel.SetThreadPriority.restype = ctypes.c_int
        handle = kernel.GetCurrentThread()
        if not kernel.SetThreadPriority(handle, 0x00010000):
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if kernel is not None and not kernel.SetThreadPriority(handle, 0x00020000):
            raise OSError('could not restore conversation worker thread priority')


def _maintain_legacy_conversations():
    global _trace_retention_cursor, _trace_retention_status, _migration_status, _trace_inventory_completed_at
    import time as trace_clock
    import sqlite3 as trace_sqlite
    if _update_stop.is_set() or _trace_retention_status == 'failed':
        return False
    try:
        context = _conversation_maintenance_context()
        if context is None:
            return False
        with _trace_background_priority():
            completed = globals().get('_trace_inventory_completed_at')
            if completed is None or trace_clock.monotonic() - completed >= 3600:
                result = server.conversation_content.maintain_legacy_trace_inventory(
                    authentication_context=context, cursor=_trace_retention_cursor,
                    cancellation_event=_update_stop, timeout_seconds=_launcher_seconds('archive_step_ms'))
                if result['status'] == 'inventory-complete':
                    _trace_inventory_completed_at = trace_clock.monotonic()
            else:
                result = dict(status='inventory-complete', next_cursor=None)
            if result['status'] == 'inventory-complete':
                from nodelang.conversation_retention_maintenance import (
                    maintain_trace_families, compact_trace_journal, _user_is_active)
                from nodelang.conversation_trace_receipts import maintain_trace_receipts
                result = maintain_trace_families(server.conversation_content,
                    authentication_context=context, cancellation_event=_update_stop,
                    prepare_only=True)
                if result['status'] in ('family-ready', 'family-complete'):
                    result = maintain_trace_receipts(server.conversation_content,
                        authentication_context=context, cancellation_event=_update_stop)
                    if result['status'] == 'receipts-complete':
                        result = maintain_trace_families(server.conversation_content,
                            authentication_context=context, cancellation_event=_update_stop)
                if result['status'] == 'family-complete':
                    def idle_check():
                        if _update_stop.is_set() or _user_is_active(server):
                            raise TimeoutError('trace compaction yields to user activity')
                    def compact_progress(event):
                        progress = dict(_migration_status or {})
                        progress.update(label='Compacting archived trace space', background=True, **event)
                        if _boot_surface is not None:
                            _boot_surface.progress.migration(progress)
                    result = {**result, **compact_trace_journal(server.universal_store,
                        check=idle_check, on_progress=compact_progress)}
        _trace_retention_cursor = result['next_cursor']
        status = result['status']
        # The progress channel survives boot, but the boot watchdog must never
        # be renewed/rearmed by later archive work.
        _migration_status = dict(label='Archiving old agent traces', stage=status,
            completed=result.get('copied', 0), total=None, percent=None,
            exported=result.get('exported', 0), moved=result.get('moved', 0),
            background=True)
        if _boot_surface is not None:
            _boot_surface.progress.migration(_migration_status)
        if status != _trace_retention_status or result.get('exported'):
            print('  trace archive : %s; copied %d; exported %d; moved %d' %
                (status, result.get('copied', 0), result.get('exported', 0),
                 result.get('moved', 0)), flush=True)
        _trace_retention_status = status
        return status in ('copying', 'inventory', 'archived', 'compacting',
            'family-reset', 'family-inventory', 'family-delta', 'family-protection',
            'family-retained-dependencies', 'family-ready', 'family-archiving',
            'receipt-preparing', 'receipt-copying', 'receipt-scanning', 'receipt-reset')
    except TimeoutError:
        return False
    except Exception as refusal:
        if isinstance(refusal, trace_sqlite.OperationalError) and (
                getattr(refusal, 'sqlite_errorcode', 0) & 255) in (
                trace_sqlite.SQLITE_BUSY, trace_sqlite.SQLITE_LOCKED, trace_sqlite.SQLITE_INTERRUPT):
            return False
        _trace_retention_status = 'failed'
        _migration_status = dict(label='Agent trace archive paused', stage='failed',
            error=str(refusal), background=True, completed=None, total=None, percent=None)
        if _boot_surface is not None:
            _boot_surface.progress.migration(_migration_status)
        from nodelang.conversation_archive import archive_directory, write_status
        try:
            write_status(archive_directory(server.conversation_content._path), _migration_status,
                name='trace-maintenance-status.json')
        except (OSError, ValueError) as status_error:
            print('  trace archive : status could not be saved: %s' % status_error, flush=True)
        print('  trace archive : paused: %s' % refusal, flush=True)
        return False


def _maintain_conversations():
    global _retention_cursor, _retention_status
    if _update_stop.is_set():
        return
    try:
        context = _conversation_maintenance_context()
        if context is None:
            return
        result = server.conversation_content.maintain_retention(authentication_context=context,
            after_conversation_id=_retention_cursor, cancellation_event=_update_stop, timeout_seconds=_launcher_seconds('archive_step_ms'))
        _retention_cursor = result['next_conversation_id']
        status = result['status']
        if result['archived'] or result['purged']:
            print('  conversation storage : archived %d; removed %d expired messages' %
                (result['archived'], result['purged']), flush=True)
        elif status != _retention_status and status not in ('idle', 'not-enabled', 'deferred',
                                                             'waiting-for-idle'):
            print('  conversation storage : %s' % status, flush=True)
    except Exception as refusal:
        status = type(refusal).__name__
        if not _update_stop.is_set() and status != _retention_status:
            print('  conversation storage : deferred (%s)' % status, flush=True)
    _retention_status = status


def _stage_update_quietly():
    # First check is at startup, off the UI thread. The owner enforces the
    # catalogue interval; the existing renewal loop stays the only scheduler.
    _stage_once()
    next_renewal = time.monotonic() + 60
    next_update = time.monotonic() + 60
    next_trace = time.monotonic() + 30
    while not _update_stop.is_set():
        delay = max(0.0, min(next_renewal, next_update, next_trace) - time.monotonic())
        if _update_stop.wait(delay):
            return
        now = time.monotonic()
        if now >= next_renewal:
            from nodelang.cloud_signin import refresh_session
            try:
                refresh_session()
            except Exception as refusal:
                print("  cloud session : renewal deferred (%s)" % type(refusal).__name__, flush=True)
            _renew_desktop_session()
            if not _update_stop.is_set():
                _maintain_conversations()
            next_renewal = time.monotonic() + 60
        if not _update_stop.is_set() and time.monotonic() >= next_trace:
            pending = _maintain_legacy_conversations()
            next_trace = time.monotonic() + (0.25 if pending else 60)
        if not _update_stop.is_set() and time.monotonic() >= next_update:
            _stage_once()
            next_update = time.monotonic() + 60

def _stage_once():
    try:
        server.application_update.check_if_due()
    except Exception as refusal:
        print("  update     : check failed -- %s" % refusal, flush=True)

_update_stop = _threading.Event()
_quiet_update_thread = _threading.Thread(target=_stage_update_quietly,
    name="archhub-quiet-update", daemon=True)
_quiet_update_thread.start()


def _finish_application_shutdown():
    """Return success only after quiescence and the existing server close path.

    A blocked OS pipe handshake is not cancellable by a Python Event. If an
    owned worker cannot quiesce, exit unsuccessfully with its descriptor and
    journal retained for the normal stale-owner/crash-recovery path. Never
    restore another descriptor or close a journal under that live worker.
    """
    global _apply_after_quit
    _apply_on_quit = not _update_rollback_requested.is_set() and server.application_update.apply_on_quit()
    _apply_after_quit = _apply_on_quit
    if cloud_relay is not None:
        cloud_relay.request_stop()
    _baboom_stop.set()
    goose_runtime = getattr(server, "goose_runtime", None)
    if goose_runtime is not None:
        goose_runtime.close()
    _update_stop.set()
    _cloud_publish_stop_event = globals().get("_cloud_publish_stop")
    if _cloud_publish_stop_event is not None:
        _cloud_publish_stop_event.set()
    _cloud_pub_thread = globals().get("_cloud_publish_thread")
    if _cloud_pub_thread is not None and hasattr(_cloud_pub_thread, "join"):
        try:
            _cloud_pub_thread.join(timeout=_launcher_seconds('cloud_shutdown_ms'))
        except Exception as error:
            print("  shutdown   : could not join cloud publisher: %s" % error, flush=True)
    if not server.application_update.close(timeout_seconds=_launcher_seconds('update_shutdown_ms')):
        print("  shutdown   : INCOMPLETE (update download still active); "
              "descriptor and graph retained for recovery", flush=True)
        return False
    _quiet_update_thread.join(timeout=_launcher_seconds('update_shutdown_ms'))
    if _quiet_update_thread.is_alive():
        print("  shutdown   : INCOMPLETE (desktop maintenance still active); "
              "descriptor and graph retained for recovery", flush=True)
        return False
    try:
        if cloud_relay is not None:
            # One HTTP request may be in flight for relay.timeout; wait it out.
            cloud_relay.close(timeout_seconds=min(30.0, cloud_relay.timeout + 2.0))
    except Exception as refusal:
        print("  shutdown   : INCOMPLETE (cloud relay: %s); "
              "descriptor and graph retained for recovery" % type(refusal).__name__, flush=True)
        return False
    try:
        _baboom_attachment.shutdown()
    except Exception as refusal:
        print("  shutdown   : INCOMPLETE (%s); active descriptor and journal retained; "
              "process exit requires stale-owner recovery" % type(refusal).__name__, flush=True)
        return False
    try:
        if _restart_after_shutdown or _apply_on_quit:
            from nodelang.desktop import arm_update
            content_path = server.conversation_content._path
            # Setup owns the one pre-upgrade copy after this owner closes.
            # Keep the instance fence until its existing preboot admission.
            server.close()
            if _update_rollback_requested.is_set():
                from nodelang.quiet_update import rollback_staged
                rolled = rollback_staged(state_dir, Path(__file__).resolve().parents[1])
                if not rolled.get("rolled_back"):
                    raise ValueError(rolled.get("reason", "previous build could not be restored"))
            else:
                arm_update(state_dir, Path(__file__).resolve().parents[1], state_path,
                    content_path if content_path is not None and content_path.is_file() else None,
                    expected_build=server.application_update.confirmed_build)
        else:
            server.close()
    except Exception as refusal:
        print("  shutdown   : INCOMPLETE (server close: %s); active descriptor retained"
              % type(refusal).__name__, flush=True)
        return False
    # The machine pointer names this runtime's record, now "stopped"; a later
    # runtime's pointer replaces it. Nothing is restored or rewritten here.
    if _machine_pointer is not None:
        print("  runtime    : announcement %s" % _announcement_at_exit(_machine_pointer, server),
              flush=True)
    return True


def _announcement_at_exit(pointer, owner):
    """What the machine announcement names after this runtime closed (log only)."""
    import json
    try:
        named = json.loads(pointer.read_text(encoding="utf-8")).get("runtime_id")
    except (OSError, ValueError, AttributeError):
        return "absent or unreadable (left)"
    mine = getattr(getattr(owner, "machine_transport", None), "runtime_id", None)
    return ("names this runtime, now stopped" if named is not None and named == mine
            else "names another runtime (left)")


def _complete_desktop_exit(code):
    """Relaunch only after the current owner and instance lock are released."""
    if not _finish_application_shutdown():
        return 1
    if code == 0 and _apply_after_quit and not _restart_after_shutdown:
        from nodelang.quiet_update import apply_staged
        from nodelang.application_update_recovery import validate_update_ready
        from nodelang.persistence import application_content_path
        result = apply_staged(state_dir, Path(__file__).resolve().parents[1],
            before_apply=lambda: validate_update_ready(state_dir, Path(__file__).resolve().parents[1],
                state_path, application_content_path(state_path)))
        if not result.get("applied") and not result.get("rolled_back"):
            print("  update     : quit update refused: %s" % result.get("reason"), flush=True)
            return 1
    if code != 0 or not _restart_after_shutdown:
        return code
    try:
        _instance_lock.close()
        import subprocess as _sp
        _sp.Popen(["wscript.exe", str(Path(__file__).resolve().parents[1] / "ArchHub.vbs")],
            close_fds=True, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
    except Exception as refusal:
        print("  update     : restart failed (%s); staged update retained" % type(refusal).__name__, flush=True)
        return 1
    return code


try:
    code = app.exec()
except BaseException:
    traceback.print_exc()
    code = 1
finally:
    code = _complete_desktop_exit(code)
raise SystemExit(code)
