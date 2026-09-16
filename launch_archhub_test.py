"""ArchHub desktop launcher, with persistent state for this Windows user.

The existing application uses %LOCALAPPDATA%/ArchHub-Test for historical
compatibility. That directory contains live user data. Explicit isolated runs
select ARCHHUB_TEST_STATE_DIR and keep the machine's active runtime unchanged.
Closing the window leaves ArchHub in its tray; Quit closes the application.
"""
import faulthandler
import os, sys, time, traceback
from pathlib import Path

# This machine's documented QtWebEngine failure: GPU compositing
# collapses the render process and takes the whole window down with no
# Python traceback. Software rendering is the fix that held.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault("QT_OPENGL", "software")

sys.path.insert(0, str(Path(__file__).parent))

# pythonw has no console: stdout/stderr vanish and a crash is invisible.
# Everything this launcher says goes to a file the founder can open.
_log_dir = Path(
    os.environ.get("ARCHHUB_TEST_STATE_DIR")
    or (Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test")
)
_log_dir.mkdir(parents=True, exist_ok=True)
_log_path = _log_dir / "launcher.log"
_log = open(_log_path, "a", encoding="utf-8", buffering=1)
sys.stdout = _log
sys.stderr = _log


def _require_complete_local_update(app_dir):
    # The existing local updater writes this reservation before replacing the
    # launcher, then publishes the remaining files while launch/store fences
    # are held. Keep it on any interrupted update until rollback or completion.
    if (app_dir / 'local-update.pending.json').exists():
        print('ArchHub update is incomplete. Resume its recorded update or rollback before opening.', flush=True)
        raise SystemExit(2)


_require_complete_local_update(Path(__file__).resolve().parent)


# pythonw has no console and stdout is the log file above, so a boot that
# refuses -- Qt missing, WebEngine refusing the GPU, a port held -- was a
# window that never opened and a colleague with nothing to send. The log
# keeps the full traceback; the colleague gets its last line and where the
# log is, in a box he can read.
def _message_box(message):
    """The only window a person without a console ever sees.

    Every refusal on the boot path goes through here. A launch that ends
    without one is a double-click that did nothing, and the colleague is left
    with nothing to read and nothing to send.
    """
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, 'ArchHub', 0x10)
        return True
    except Exception:
        return False


def _tell_the_person(kind, value, tb):
    traceback.print_exception(kind, value, tb)
    try:
        last = ''.join(traceback.format_exception_only(kind, value)).strip().splitlines()[-1]
        message = 'ArchHub could not open.' + chr(10) + chr(10) + last[:300]
        message += chr(10) + chr(10) + 'The full log is at:' + chr(10) + str(_log_path)
        message += chr(10) + chr(10) + 'Share that log when requesting support.'
        _message_box(message)
    except Exception:
        pass
sys.excepthook = _tell_the_person
print("=== launch", time.strftime("%Y-%m-%d %H:%M:%S"), "===")
faulthandler.enable(file=_log)

state_dir = Path(
    os.environ.get("ARCHHUB_TEST_STATE_DIR")
    or (Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test")
)
state_dir.mkdir(parents=True, exist_ok=True)
state_path = state_dir / "archhub-test.universal.sqlite3"

def _force_foreground(handle) -> bool:
    """Make Windows actually bring our window forward.

    Qt's showNormal/raise_/activateWindow are the whole story on other
    desktops. On Windows a process that does not own the foreground cannot
    take it: SetForegroundWindow is refused and the taskbar button flashes
    instead. The founder clicked the tray icon and nothing happened
    (2026-09-06). The documented way round it is to attach our input queue to
    the foreground window's thread for the moment of the call, which is what
    every app that restores from a tray does.
    """
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
                _force_foreground(handle)
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
        + "If ArchHub is not already open, wait a few seconds and open it "
          "again. If it still refuses, set the environment variable "
          "ARCHHUB_TEST_LOCK_PORT to a free port number (%d, for example) "
          "and open ArchHub again." % (port + 1)
    )
    return ("port %d is held and no ArchHub window answered; the person was told "
            "about ARCHHUB_TEST_LOCK_PORT" % port)


# ONE app. A second double-click fronts nothing and starts nothing --
# the socket is the cheapest cross-process mutex Windows respects.
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
        time.sleep(0.5)
else:
    # Say so in the log AND on the screen: a launch that exits without a word
    # leaves an orphan header, reads as a crash, and gives the person nothing
    # to act on.
    print("  lock       : port %d is already held" % _lock_port, flush=True)
    print("  window     : %s"
          % _held_port_outcome(_lock_port, _front_running_archhub, _message_box),
          flush=True)
    sys.exit(0)

_require_complete_local_update(Path(__file__).resolve().parent)

def _saved_graph_exists(directory, database):
    """Distinguish a new installation from saved state needing recovery.

    This bounded read is a presence check, not journal integrity verification.
    It runs after the single-instance lock and never initializes a database.
    SQLite may update coordination read marks in the shared-memory file.
    """
    import sqlite3

    names = {os.path.normcase(name) for name in os.listdir(directory)}
    database_name = os.path.normcase(database.name)
    if database_name not in names:
        if any(name.startswith(database_name) for name in names) or any(
            name in names for name in ("runtime-descriptor.json", "backups")
        ):
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
            database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1,
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
                raise RuntimeError("The saved application root is missing; files are kept in place.")
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

print("ArchHub TEST")
print("  graph store :", state_path)
print("  booting ...", flush=True)

from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
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

# Apply only a verified release armed by the preceding owner's final recovery.
# No synchronous network download belongs on the application startup path.
_staged = {}
try:
    from nodelang.quiet_update import apply_staged as _apply_staged, staged_update
    _staged = staged_update(state_dir, Path(__file__).resolve().parent)
    if _staged.get("status") == "applying":
        print("  update     : previous installation is unresolved; recovery and installer retained. Startup refused.", flush=True)
        raise SystemExit(1)
    if _staged.get("staged") and _staged.get("status") == "staged":
        from nodelang.application_update_recovery import validate_update_ready
        _update_content = Path(str(state_path) + ".conversations.sqlite3")
        _applied = _apply_staged(state_dir, Path(__file__).resolve().parent,
            before_apply=lambda: validate_update_ready(state_dir, Path(__file__).resolve().parent,
                state_path, _update_content if _update_content.is_file() else None))
        if _applied.get("applied"):
            print("  update     : installed build %s; relaunching" % _applied.get("build_id"), flush=True)
            import subprocess as _sp
            try:
                _instance_lock.close()
                _sp.Popen(["wscript.exe", str(Path(__file__).resolve().parent / "ArchHub.vbs")], close_fds=True, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
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

first_boot = not _saved_graph_exists(state_dir, state_path)
print("  first boot  :", first_boot, flush=True)
started = time.perf_counter()

def _boot():
    # The boot is sampled while it runs: boot-profile.log beside launcher.log
    # says where the seconds went (the founder's boot reached 694s and nobody
    # could name what it was doing).
    from nodelang.boot_profile import profile_boot
    return profile_boot(_boot_unsampled, state_dir=state_dir)

def _boot_unsampled():
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
    server = ApplicationServer(
        universal_state_path=state_path,
        pipeline_effect_engines=PIPELINE_ENGINES,
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=machine_key_provider,
        project_work_execution_broker=ProjectWorkExecutionBroker(artifact_root),
        model_execution_broker=ModelExecutionBroker(
            workspace_root=Path(__file__).resolve().parent,
            credential_resolver=ApplicationOpenRouterCredentialResolver(),
            timeout_seconds=60.0,
        ),
        **workshop_arguments,
    )
    try:
        recovery = server.conversation_content.backup_recovery(state_dir / "backups",
            authentication_context=server.universal_registry.authorization.session.context(),
            timeout_seconds=2.0)
        print("  backup     : checked post-construction recovery saved: " + recovery.name, flush=True)
    except Exception as refusal:
        print("  backup     : not completed (%s); existing backups retained" % type(refusal).__name__, flush=True)
        if isinstance(refusal, TimeoutError):
            print("  backup     : startup recovery exceeded its 2-second budget; no new recovery was published", flush=True)
        sqlite_code = getattr(refusal, "sqlite_errorcode", None)
        if type(sqlite_code) is int:
            print("  backup     : SQLite error code %d; recovery remains incomplete" % sqlite_code, flush=True)
        for note in getattr(refusal, "__notes__", ()):
            print("  backup     : " + note, flush=True)
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
    except Exception:
        pass
    for stale in state_dir.glob(state_path.name + ".owner.lock"):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass

boot_refusal = None
try:
    server = _boot()
except Exception as refusal:
    boot_refusal = refusal
    # A lock held by a dying predecessor clears on its own; retrying once
    # costs a second and saves the founder's whole graph from being set
    # aside for a transient.
    import gc

    gc.collect()
    # A failed first attempt can leave OUR OWN owner fence behind; the
    # conflict then names this very process. Releasing our own lock is
    # honest -- it is nobody else's.
    _release_own_fence(refusal)
    # A transient (a predecessor still closing its WAL, a lock not yet
    # released, an I/O hiccup) is retried for a while; it is never a
    # reason to set the founder's graph aside -- a fresh graph on the
    # same disk would fail the same way, and the founder would open
    # an empty canvas over 300 MB of his own work.
    for _open_attempt in range(6):
        time.sleep(1.5)
        try:
            server = _boot()
            print("  recovered  : the saved graph opened on attempt %d"
                  % (_open_attempt + 2), flush=True)
            boot_refusal = None
            break
        except Exception as again:
            boot_refusal = again
            # Each failed attempt can leave OUR OWN fence behind; without
            # clearing it every later attempt fails on ourselves.
            _release_own_fence(again)
# A startup failure never selects a replacement graph. Recovery of damaged
# state is a separate operation; its files and original refusal stay visible.
if boot_refusal is not None:
    print("  could not open the saved graph: %s"
          % str(boot_refusal).splitlines()[-1][:160], flush=True)
    print("  the saved graph is KEPT IN PLACE. No replacement graph was created.", flush=True)
    raise boot_refusal
print(f"  booted in {time.perf_counter()-started:.0f}s", flush=True)

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
    cloud = (
        Path(os.environ["APPDATA"]) / "ArchHub" / "brain" / "cloud.json"
    )
    if not cloud.is_file():
        return "no cloud session on this machine"
    held = json.loads(cloud.read_text(encoding="utf-8"))
    token = held.get("token")
    base = held.get("cloud_base_url") or "https://archhub-cloud.fly.dev"
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
    with urllib.request.urlopen(request, timeout=25) as answer:
        return json.loads(answer.read().decode("utf-8"))


try:
    print("  cloud map  :", _publish_map_to_cloud(), flush=True)
except Exception as _refusal:
    print("  cloud map  : not published (%s)" % str(_refusal)[:90], flush=True)

# Announce THIS runtime as the machine's active universal runtime, so
# the brain, BABOOM and any governed agent reach the founder's live
# graph instead of a dead descriptor from a previous life.
_active_runtime = (
    Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / "active-universal-runtime.json"
)
_previous_active = None
_announced_active = None
if os.environ.get("ARCHHUB_TEST_STATE_DIR"):
    # A verification run opens its OWN graph in its own state directory.
    # Announcing it would point the brain, BABOOM and every governed
    # agent on this machine at a throwaway database -- checking the
    # application must never move the founder's wiring onto it.
    print("  runtime    : not announced (verification run keeps the "
          "machine binding)", flush=True)
else:
    try:
        _active_runtime.parent.mkdir(parents=True, exist_ok=True)
        _previous_active = (
            _active_runtime.read_bytes() if _active_runtime.is_file() else None
        )
        _announcement = descriptor_path.read_bytes()
        _active_runtime.write_bytes(_announcement)
        _announced_active = _announcement
        print("  runtime    : announced as the machine's active universal "
              "runtime", flush=True)
    except OSError as _refusal:
        _previous_active = None
        print("  runtime    : could not announce (%s)" % _refusal, flush=True)

def _initialize_startup_pipeline(owner, *, first_boot):
    """Seed a new graph only; opening an application never invokes its effects."""
    if not first_boot:
        return None
    from nodelang.universal_pipeline import seed_wall_pipeline
    authority = owner.universal_registry.authorization
    # The owner already serves requests. Use its ordinary mutation admission,
    # minting the existing process context before taking the mutation lock.
    for attempt in range(10):
        try:
            context = authority.session.context(minimum_validity_seconds=5)
            with owner.mutation_lock, authority.broker.live_context(context):
                return seed_wall_pipeline(owner.universal_store, owner.universal_registry,
                    authentication_context=context)
        except Exception as clash:
            # Only idempotent graph seeding may retry a revision conflict.
            # An engine invocation cannot safely be repeated on that evidence.
            if "expected revision" not in str(clash) or attempt == 9:
                raise
            time.sleep(0.25 * (attempt + 1))


# first_boot comes from the validated saved-graph check, not a UI marker.
# Existing graphs retain their nodes, parameters and previous results. Repair
# seeding and execution remain available through their admitted application routes.
try:
    _initialize_startup_pipeline(server, first_boot=first_boot)
    print("  pipeline   : %s; execution awaits an admitted Run" % (
        "initial seed checked" if first_boot else "saved graph retained"), flush=True)
except Exception as refusal:
    # A refusal nobody can locate is a refusal nobody can fix: name the
    # exact call that raised, not only its message.
    where = traceback.format_exc().strip().splitlines()
    spot = [line.strip() for line in where if "line " in line][-1:] or [""]
    print("  pipeline   : not seeded -- %s (%s)" % (refusal, spot[0]),
          flush=True)

if os.environ.get("ARCHHUB_TEST_NO_OPEN"):
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    raise SystemExit(0)

from PyQt6.QtCore import QUrl
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

class _ArchHubWindow(QMainWindow):
    """Closing the window hides it: ArchHub keeps running in the background
    (the brain, BABOOM, the agents) exactly like Chrome or Claude Desktop, and
    the tray icon brings it back or quits it for real."""
    quitting = False

    def closeEvent(self, event):
        if self.quitting or getattr(self, "_tray", None) is None:
            return super().closeEvent(event)
        event.ignore()
        self.hide()
        try:
            self._tray.showMessage("ArchHub keeps running", "Open it again from the tray icon; Quit is there too.")
        except Exception:
            pass


window = _ArchHubWindow()
window.setWindowTitle("ArchHub")
# The brand icon, and a distinct AppUserModelID so the taskbar shows
# ArchHub rather than grouping under python's default.
import ctypes
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ArchHub.Test")
from PyQt6.QtGui import QIcon
# Source and installer use the same owned asset beside this launcher.
_icon_path = Path(__file__).resolve().parent / "archhub.ico"
if _icon_path.is_file():
    app.setWindowIcon(QIcon(str(_icon_path)))
    window.setWindowIcon(QIcon(str(_icon_path)))
window.resize(1480, 920)
window.setMinimumSize(960, 640)
view = QWebEngineView(window)
window.setCentralWidget(view)
from nodelang.studio_downloads import install_studio_downloads


def _download_status(status):
    window.statusBar().showMessage(status["detail"])


_studio_downloads = install_studio_downloads(
    view.page().profile(), view.page(), server.public_url,
    parent=window, on_status=_download_status)
app.aboutToQuit.connect(_studio_downloads.close)
# The bootstrap lands on / to mint the session cookie, then the window
# lives on the studio face.
_booted = {"done": False}
_update_boot = {"pending": _staged.get("status") == "awaiting_boot", "checks": 0}


def _acknowledge_update_surface():
    """Acknowledge after the saved graph and Studio have actually mounted."""
    if not _update_boot["pending"] or _update_boot["checks"] >= 60:
        return
    _update_boot["checks"] += 1

    def observed(ready):
        if ready:
            _update_boot["pending"] = False
            def confirm():
                from nodelang.quiet_update import confirm_applied
                result = confirm_applied(state_dir, Path(__file__).resolve().parent)
                print("  update     : %s" % result.get("reason"), flush=True)
            import threading as _ack_threading
            _ack_threading.Thread(target=confirm, name="archhub-update-boot-ack", daemon=True).start()
        else:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, _acknowledge_update_surface)

    view.page().runJavaScript(
        "Boolean(window.ARCHHUB_LIVE && window.ARCHHUB_LIVE.graph && "
        "document.getElementById('root')?.children.length)", observed)


def _to_studio(ok):
    if ok and not _booted["done"]:
        _booted["done"] = True
        view.load(QUrl(server.public_url + "/studio"))
    elif ok and view.url().path().startswith("/studio"):
        _acknowledge_update_surface()
view.loadFinished.connect(_to_studio)
# The studio's Browse buttons open THIS window's native file dialog; the
# chosen path goes back over the same origin. Runs on the Qt thread.
def _pick_file(title, name_filter):
    from PyQt6.QtWidgets import QFileDialog
    result = {}
    done = threading.Event()
    def ask():
        chosen, _ = QFileDialog.getOpenFileName(
            window, title, "", name_filter or "All files (*.*)")
        result["path"] = chosen
        done.set()
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, ask)
    done.wait(120)
    return result.get("path", "")
import threading
server.native_file_picker = _pick_file
# A dead render process reloads instead of leaving a dead window.
def _revive(_status, _code):
    print("  render process died -- reloading", flush=True)
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(300, lambda: view.load(
        QUrl(server.public_url + "/studio")))
view.page().renderProcessTerminated.connect(_revive)
view.load(QUrl(server.bootstrap_url))
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
        _force_foreground(window.winId())
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

def _tray_check_updates():
    server.application_update.check()
    _tray.showMessage("ArchHub", "Checking for updates. Download status is available inside the app.")

import threading as _restart_threading
_update_restart_requested = _restart_threading.Event()
_restart_after_shutdown = False
from nodelang.application_update import ApplicationUpdate
server.application_update = ApplicationUpdate(state_dir, Path(__file__).resolve().parent,
    request_restart=_update_restart_requested.set, initial_stage=_staged)
server._desktop_request_update_restart = server.application_update.reload


def _tray_restart_to_update():
    try:
        server.application_update.reload()
    except Exception as refusal:
        _tray.showMessage("ArchHub", str(refusal))


def _begin_update_exit():
    global _restart_after_shutdown
    _restart_after_shutdown = True
    window.quitting = True
    app.quit()

def _tray_quit():
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
    except Exception:
        pass
    try:
        if shower.is_file():
            shower.unlink()
    except Exception:
        pass

    def _look():
        if _update_restart_requested.is_set():
            _update_restart_requested.clear()
            _begin_update_exit()
            return
        if shower.is_file():
            try:
                shower.unlink()
            except Exception:
                pass
            print("  show       : asked from outside; bringing the window up", flush=True)
            _tray_open()
        if marker.is_file():
            try:
                marker.unlink()
            except Exception:
                pass
            print("  quit       : asked from outside; leaving cleanly", flush=True)
            _tray_quit()

    timer = _QT(app)
    timer.setInterval(2000)
    timer.timeout.connect(_look)
    timer.start()
    app._archhub_quit_watch = timer

def _tray_menu_about_to_show():
    _restart_action.setVisible(server.application_update.status().get("state") == "ready")

_watch_quit_request()
if QSystemTrayIcon.isSystemTrayAvailable():
    _tray = QSystemTrayIcon(app.windowIcon(), app)
    _tray.setToolTip("ArchHub - running")
    _menu = QMenu()
    _menu.addAction("Open ArchHub", _tray_open)
    _menu.addAction("Check for updates now", _tray_check_updates)
    _restart_action = _menu.addAction("Restart to install the update", _tray_restart_to_update)
    _menu.addSeparator()
    _menu.addAction("Quit ArchHub", _tray_quit)
    _menu.aboutToShow.connect(_tray_menu_about_to_show)
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
    app.setQuitOnLastWindowClosed(False)
    print("  tray       : icon shown (close hides to tray; Quit is in the menu)", flush=True)
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
        self.ready.connect(self.land, _BaboomQt.ConnectionType.QueuedConnection)

    def shutdown(self):
        """Quiesce attachment before its server or journal can be closed."""
        _baboom_stop.set()
        if self.worker is not None:
            self.worker.join(timeout=5.0)
            if self.worker.is_alive():
                raise RuntimeError("BABOOM attachment did not stop; server teardown refused")
        host = self.pending_host or baboom_host
        if host is not None:
            host.stop(timeout_seconds=1.0)
            if host.running:
                raise RuntimeError("BABOOM heartbeat did not stop; server teardown refused")

    @_baboom_slot(object)
    def land(self, host):
        global baboom_host, baboom_window
        # Shutdown and duplicate deliveries cannot create an extra companion.
        if _baboom_stop.is_set() or baboom_host is not None:
            if host is not baboom_host:
                host.stop(timeout_seconds=0.01)
            return
        companion = None
        try:
            from nodelang.baboom_native_runtime import create_baboom_native_projection
            companion = create_baboom_native_projection(
                host, position_path=state_dir / "baboom-position.json", on_stop=_stop_baboom_for_user
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
            print("  BABOOM     : attached (signed agent session)", flush=True)
        except Exception as refusal:
            host.stop(timeout_seconds=0.01)
            if companion is not None:
                companion.close()
                companion.deleteLater()
            print("  BABOOM     : projection unavailable (%s)" % type(refusal).__name__, flush=True)


_baboom_attachment = _BaboomAttachment(app)
app.aboutToQuit.connect(_baboom_stop.set)


def _keep_attaching():
    from nodelang.application_machine_transport import MachineTransportError
    from nodelang.baboom_attach import prepare_baboom_host

    host = None
    transient = {
        "universal runtime did not respond",
        "universal runtime pipe is unavailable",
        "machine request timed out",
    }
    handed_off = False
    try:
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
                retryable = isinstance(refusal, (TimeoutError, ConnectionError)) or (
                    isinstance(refusal, MachineTransportError) and str(refusal) in transient
                )
                print("  BABOOM     : %s (attempt %d, %s)" % (
                    "waiting for runtime" if retryable else "attachment refused",
                    attempt + 1, type(refusal).__name__), flush=True)
                if retryable:
                    continue
                return
            if _baboom_stop.is_set():
                return
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
            host.stop(timeout_seconds=0.01)


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
        return host.respond_input(utterance)
    from nodelang.universal_application import respond_universal_baboom_utterance
    with server.mutation_lock:
        return respond_universal_baboom_utterance(
            server.universal_store, server.universal_registry,
            utterance=utterance,
            authentication_context=server.universal_registry.authorization.session.context(),
        )


def _cockpit_execute(utterance):
    if _baboom_stop.is_set():
        raise RuntimeError("ArchHub is closing; the request was not performed")
    host = baboom_host
    if host is None:
        raise RuntimeError("BABOOM is not attached; no action was performed. Retry when it connects.")
    # Exactly the same signed method used by the companion, never a fallback
    # server mutation or a GUI-bound controller call from the relay worker.
    return host.execute_input(utterance)


def _cockpit_offer():
    # The offer the cockpit states is the one record the app holds, never a copy.
    from nodelang.cell_accounts import published_offer
    return published_offer(server.universal_store.snapshot())


cloud_relay = None
try:
    from nodelang.cloud_relay import start_cloud_relay as _start_relay
    from nodelang.universal_pipeline import project_atlas_map as _atlas
    cloud_relay = _start_relay(
        appdata=Path(os.environ["APPDATA"]), state_dir=state_dir,
        respond=_cockpit_respond, execute=_cockpit_execute,
        map_script=lambda: _atlas(server.universal_store, server.universal_registry),
        hosts=lambda: server._host_rows(),
        offer=_cockpit_offer,
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
            response_timeout_seconds=5)
        if (response.get("application") != server.universal_registry.application_root
                or response.get("session_root") != server.browser_session_root
                or response.get("one_use") is not True):
            raise RuntimeError("Desktop renewal returned another authority")
        status = "ready"
    except Exception as refusal:
        if _update_stop.is_set():
            return
        status = type(refusal).__name__
        if status == "MachineTransportError":
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


def _maintain_conversations():
    global _retention_cursor, _retention_status
    if _update_stop.is_set():
        return
    try:
        session = server.universal_registry.authorization.session
        held = []
        try:
            # Skip this cadence if process trust is busy; never wait behind a
            # session renewal while the application is trying to shut down.
            for lock in (session._lock, session.broker._lock):
                if not lock.acquire(blocking=False):
                    return
                held.append(lock)
            context = session.context(minimum_validity_seconds=5)
        finally:
            for lock in reversed(held):
                lock.release()
        result = server.conversation_content.maintain_retention(authentication_context=context,
            after_conversation_id=_retention_cursor, cancellation_event=_update_stop, timeout_seconds=2.0)
        _retention_cursor = result['next_conversation_id']
        status = result['status']
        if result['archived'] or result['purged']:
            print('  conversation storage : archived %d; removed %d expired messages' %
                (result['archived'], result['purged']), flush=True)
        elif status != _retention_status and status not in ('idle', 'not-enabled', 'deferred'):
            print('  conversation storage : %s' % status, flush=True)
    except Exception as refusal:
        status = type(refusal).__name__
        if not _update_stop.is_set() and status != _retention_status:
            print('  conversation storage : deferred (%s)' % status, flush=True)
    _retention_status = status


def _stage_update_quietly():
    # Existing update cadence stays two minutes, then thirty minutes.
    # A minute cadence for renewal stays within its five-minute lead window.
    next_renewal = time.monotonic() + 60
    next_update = time.monotonic() + 120
    while not _update_stop.is_set():
        delay = max(0.0, min(next_renewal, next_update) - time.monotonic())
        if _update_stop.wait(delay):
            return
        now = time.monotonic()
        if now >= next_renewal:
            _renew_desktop_session()
            if not _update_stop.is_set():
                _maintain_conversations()
            next_renewal = time.monotonic() + 60
        if not _update_stop.is_set() and time.monotonic() >= next_update:
            _stage_once()
            next_update = time.monotonic() + 1800

def _stage_once():
    try:
        server.application_update.check()
    except Exception as refusal:
        print("  update     : check failed -- %s" % refusal, flush=True)

import threading as _threading
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
    if cloud_relay is not None:
        cloud_relay.request_stop()
    _baboom_stop.set()
    _update_stop.set()
    if not server.application_update.close(timeout_seconds=6.0):
        print("  shutdown   : INCOMPLETE (update download still active); "
              "descriptor and graph retained for recovery", flush=True)
        return False
    _quiet_update_thread.join(timeout=6.0)
    if _quiet_update_thread.is_alive():
        print("  shutdown   : INCOMPLETE (desktop maintenance still active); "
              "descriptor and graph retained for recovery", flush=True)
        return False
    try:
        if cloud_relay is not None:
            cloud_relay.close(timeout_seconds=6.0)
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
        if _restart_after_shutdown:
            from nodelang.application_update_recovery import arm_update
            content_path = server.conversation_content._path
            recovery = server.close(recovery_directory=state_dir / "backups",
                recovery_authentication_context=server.universal_registry.authorization.session.context(),
                recovery_timeout_seconds=300.0)
            arm_update(state_dir, Path(__file__).resolve().parent, state_path,
                content_path if content_path is not None and content_path.is_file() else None, recovery)
        else:
            server.close()
    except Exception as refusal:
        print("  shutdown   : INCOMPLETE (server close: %s); active descriptor retained"
              % type(refusal).__name__, flush=True)
        return False
    # An isolated launch never owned the machine binding. Another runtime may
    # also have been selected since this launch; leave its selection untouched.
    if _announced_active is None:
        return True
    try:
        selected = _active_runtime.read_bytes()
    except FileNotFoundError:
        return True
    except OSError as refusal:
        print("  shutdown   : INCOMPLETE (descriptor read: %s)"
              % type(refusal).__name__, flush=True)
        return False
    if selected != _announced_active:
        return True
    try:
        if _previous_active is None:
            _active_runtime.unlink(missing_ok=True)
        else:
            _active_runtime.write_bytes(_previous_active)
    except OSError as refusal:
        print("  shutdown   : INCOMPLETE (descriptor restore: %s)"
              % type(refusal).__name__, flush=True)
        return False
    return True


def _complete_desktop_exit(code):
    """Relaunch only after the current owner and instance lock are released."""
    if not _finish_application_shutdown():
        return 1
    if code != 0 or not _restart_after_shutdown:
        return code
    try:
        _instance_lock.close()
        import subprocess as _sp
        _sp.Popen(["wscript.exe", str(Path(__file__).resolve().parent / "ArchHub.vbs")],
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
