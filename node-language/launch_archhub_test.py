"""ArchHub TEST launcher -- one double-click, the windowed desktop app.

Boots the universal cell application on a PERSISTENT store under
%LOCALAPPDATA%/ArchHub-Test (your live graph is never touched) and opens
it in its own application window. Close the window to stop ArchHub TEST.
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


# pythonw has no console and stdout is the log file above, so a boot that
# refuses -- Qt missing, WebEngine refusing the GPU, a port held -- was a
# window that never opened and a colleague with nothing to send. The log
# keeps the full traceback; the colleague gets its last line and where the
# log is, in a box he can read.
def _tell_the_person(kind, value, tb):
    traceback.print_exception(kind, value, tb)
    try:
        import ctypes
        last = ''.join(traceback.format_exception_only(kind, value)).strip().splitlines()[-1]
        message = 'ArchHub could not open.' + chr(10) + chr(10) + last[:300]
        message += chr(10) + chr(10) + 'The full log is at:' + chr(10) + str(_log_path)
        message += chr(10) + chr(10) + 'Send that file to Ahmed.'
        ctypes.windll.user32.MessageBoxW(0, message, 'ArchHub', 0x10)
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
    # Say so in the log: a second launch that exits without a word
    # leaves an orphan header and reads as a crash.
    print("  another ArchHub is already running on this machine; this launch exits", flush=True)
    sys.exit(0)

# listdir membership: Path.exists() returns False on a Windows sharing
# violation (a dying prior instance still holds the handle), which would
# mislabel a warm store as a first boot.
first_boot = state_path.name not in os.listdir(state_dir)
if first_boot:
    for stale in state_dir.glob(state_path.name + "*"):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass

if not first_boot:
    # Rolling backups, like Revit's: a silent copy at every launch,
    # last TWO kept -- insurance, not a museum.
    import shutil
    backups = state_dir / "backups"
    backups.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        shutil.copy2(state_path, backups / ("%s.%s" % (state_path.name, stamp)))
        aged = sorted(backups.glob(state_path.name + ".*"))
        for old_copy in aged[:-2]:
            old_copy.unlink(missing_ok=True)
    except OSError:
        pass

print("ArchHub TEST")
print("  graph store :", state_path)
print("  first boot  :", first_boot, "(first boot builds the graph, ~1-2 min)")
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

started = time.perf_counter()

def _boot():
    return ApplicationServer(
        universal_state_path=state_path,
        pipeline_effect_engines=PIPELINE_ENGINES,
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=machine_key_provider,
    ).start()

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
    # SELF-HEALING BOOT. A desktop that refuses to open over local state
    # it could rebuild is a locked door, not a security posture. The
    # suspect universe is QUARANTINED -- never destroyed -- and a fresh
    # one is born; the refusal is printed, not swallowed.
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
if boot_refusal is not None and any(
    mark in str(boot_refusal)
    for mark in ("disk I/O error", "database is locked", "already owned", "unable to open",
                 "held by another live process", "owner fence could not be taken")
):
    print("  could not open the saved graph: %s"
          % str(boot_refusal).splitlines()[-1][:160], flush=True)
    print("  the graph is kept in place; this is a transient, not corruption."
          " Close every ArchHub process and launch again.", flush=True)
    raise boot_refusal
if boot_refusal is not None:
    print("  could not open the saved graph: %s"
          % str(boot_refusal).splitlines()[-1][:160])
    set_aside = state_dir / ("set-aside-%s" % time.strftime("%Y%m%d-%H%M%S"))
    set_aside.mkdir(parents=True, exist_ok=True)
    for stale in state_dir.glob(state_path.name + "*"):
        try:
            stale.rename(set_aside / stale.name)
        except OSError:
            pass
    print("  old data kept in %s -- starting a fresh graph ..." % set_aside.name)
    server = _boot()
print(f"  booted in {time.perf_counter()-started:.0f}s", flush=True)
print("  URL:", server.bootstrap_url, flush=True)


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
        _active_runtime.write_bytes(descriptor_path.read_bytes())
        print("  runtime    : announced as the machine's active universal "
              "runtime", flush=True)
    except OSError as _refusal:
        _previous_active = None
        print("  runtime    : could not announce (%s)" % _refusal, flush=True)

# The founder's first canvas: the wall pipeline plus the brain and BABOOM
# nodes, seeded idempotently and run once so every card opens carrying a
# real answer instead of a blank.
try:
    from nodelang.universal_pipeline import (
        run_universal_pipeline,
        seed_wall_pipeline,
    )
    # Seeding reads the canvas, then writes to it; a commit landing in
    # between makes the write's expected revision stale. That is ordinary
    # optimistic concurrency, and its answer is to re-read and try again
    # -- the seed is idempotent, so a retry adds nothing twice. Without
    # this a FRESH INSTALL opened with an empty canvas.
    for attempt in range(4):
        try:
            seed_wall_pipeline(
                server.universal_store, server.universal_registry
            )
            break
        except Exception as clash:
            if attempt == 3:
                raise
            time.sleep(0.4)
    outcome = run_universal_pipeline(
        server.universal_store,
        server.universal_registry,
        effect_engines=PIPELINE_ENGINES,
    )
    print("  pipeline   : %d node(s) ran" % outcome["ran"], flush=True)
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
app.setApplicationName("ArchHub TEST")
app.setOrganizationName("ArchHub")

profile_root = state_dir / "web-profile"
profile_root.mkdir(parents=True, exist_ok=True)
profile = QWebEngineProfile.defaultProfile()
profile.setPersistentStoragePath(str(profile_root))
profile.setCachePath(str(profile_root / "cache"))

window = QMainWindow()
window.setWindowTitle("ArchHub TEST")
# The brand icon, and a distinct AppUserModelID so the taskbar shows
# ArchHub rather than grouping under python's default.
import ctypes
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ArchHub.Test")
from PyQt6.QtGui import QIcon
# The installer ships archhub.ico beside this file; the 12.PRODUCTION tree
# exists only on the founder workstation, so it is the fallback, not the
# first look -- a colleague window carried the default python icon.
_icon_candidates = (
    Path(__file__).resolve().parent / "archhub.ico",
    Path(__file__).resolve().parents[1]
    / "12.PRODUCTION" / "app" / "assets" / "archhub.ico",
)
_icon_path = next((c for c in _icon_candidates if c.is_file()), _icon_candidates[0])
if _icon_path.is_file():
    app.setWindowIcon(QIcon(str(_icon_path)))
    window.setWindowIcon(QIcon(str(_icon_path)))
window.resize(1480, 920)
window.setMinimumSize(960, 640)
view = QWebEngineView(window)
window.setCentralWidget(view)
# The bootstrap lands on / to mint the session cookie, then the window
# lives on the studio face.
_booted = {"done": False}
def _to_studio(ok):
    if ok and not _booted["done"]:
        _booted["done"] = True
        view.load(QUrl(server.public_url + "/studio"))
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
# A window that opens BEHIND the founder's other windows reads as "the
# app didn't open". Every launch lands on top, once.
window.raise_()
window.activateWindow()

# BABOOM: the ambient companion, attached through the SAME signed
# agent-session path any governed agent uses. A failure to attach is
# printed honestly and never fakes a companion.
baboom_host = None
try:
    from nodelang.baboom_attach import attach_baboom_companion
    from nodelang.application_machine_transport import MachineTransportError
    # The runtime pipe comes up a beat after the HTTP server on a busy
    # machine. One attempt printed "universal runtime did not respond" and
    # left the founder with no companion for the whole session; a short
    # retry is what every client of a just-started service does.
    _attach_error = None
    for _attempt in range(6):
        try:
            # A retry is the same launcher, not a second process: connect()
            # binds the session identity before start() can time out, so a
            # retry under the same id is refused as "already bound". Each
            # attempt therefore carries its own id; the abandoned binding
            # expires on its own lease.
            baboom_host, baboom_window = attach_baboom_companion(
                server,
                state_dir=state_dir,
                descriptor_path=descriptor_path,
                key_provider=machine_key_provider,
                external_session_id=(
                    "founder-desktop-baboom" if _attempt == 0
                    else "founder-desktop-baboom:retry-%d" % _attempt
                ),
            )
            break
        except Exception as exc:
            text = str(exc)
            if "did not respond" not in text and "already bound" not in text:
                raise
            _attach_error = exc
            time.sleep(2.5)
    else:
        raise _attach_error
    baboom_window.show()
    # show() only makes the widget exist; projection is what makes BABOOM
    # actually draw itself and follow the graph.
    baboom_window.start_projection()
    # Say honestly whether the companion has anything to draw: a host
    # with no snapshot, or a screen too crowded for a clear placement,
    # hides itself -- and a silent hide reads as "BABOOM is broken".
    from PyQt6.QtCore import QTimer as _QTimer

    def _report_companion():
        snapshot = getattr(baboom_host, "latest_snapshot", None)
        if snapshot is None:
            print("  BABOOM     : attached, waiting for its first snapshot",
                  flush=True)
            return
        visible = baboom_window.isVisible()
        rect = baboom_window.geometry()
        print("  BABOOM     : drawing=%s at %dx%d+%d+%d" % (
            visible, rect.width(), rect.height(), rect.x(), rect.y()),
            flush=True)
    _QTimer.singleShot(6000, _report_companion)
    print("  BABOOM     : attached (signed agent session)", flush=True)
except Exception as refusal:
    print("  BABOOM     : not attached -- %s" % refusal, flush=True)

try:
    code = app.exec()
except BaseException:
    traceback.print_exc()
    code = 1
finally:
    if baboom_host is not None:
        try:
            baboom_host.stop()
        except Exception:
            pass
    # Leaving a descriptor behind that points at a dead pipe is what
    # made every brain write fail; put back whatever was there before.
    try:
        if _previous_active is None:
            _active_runtime.unlink(missing_ok=True)
        else:
            _active_runtime.write_bytes(_previous_active)
    except OSError:
        pass
    server.close()
raise SystemExit(code)
