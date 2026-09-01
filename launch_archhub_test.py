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
_log_dir = Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test"
_log_dir.mkdir(parents=True, exist_ok=True)
_log = open(_log_dir / "launcher.log", "a", encoding="utf-8", buffering=1)
sys.stdout = _log
sys.stderr = _log
print("=== launch", time.strftime("%Y-%m-%d %H:%M:%S"), "===")
faulthandler.enable(file=_log)

state_dir = Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test"
state_dir.mkdir(parents=True, exist_ok=True)
state_path = state_dir / "archhub-test.universal.sqlite3"

# ONE app. A second double-click fronts nothing and starts nothing --
# the socket is the cheapest cross-process mutex Windows respects.
import socket as _socket
_lock_port = int(os.environ.get("ARCHHUB_TEST_LOCK_PORT", "48611"))
_instance_lock = _socket.socket()
_instance_lock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
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

try:
    server = _boot()
except Exception as refusal:
    # SELF-HEALING BOOT. A desktop that refuses to open over local state
    # it could rebuild is a locked door, not a security posture. The
    # suspect universe is QUARANTINED -- never destroyed -- and a fresh
    # one is born; the refusal is printed, not swallowed.
    print("  could not open the saved graph: %s"
          % str(refusal).splitlines()[-1][:160])
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

# Announce THIS runtime as the machine's active universal runtime, so
# the brain, BABOOM and any governed agent reach the founder's live
# graph instead of a dead descriptor from a previous life.
_active_runtime = (
    Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / "active-universal-runtime.json"
)
try:
    _active_runtime.parent.mkdir(parents=True, exist_ok=True)
    _previous_active = (
        _active_runtime.read_bytes() if _active_runtime.is_file() else None
    )
    _active_runtime.write_bytes(descriptor_path.read_bytes())
    print("  runtime    : announced as the machine's active universal runtime",
          flush=True)
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
    seed_wall_pipeline(server.universal_store, server.universal_registry)
    outcome = run_universal_pipeline(
        server.universal_store,
        server.universal_registry,
        effect_engines=PIPELINE_ENGINES,
    )
    print("  pipeline   : %d node(s) ran" % outcome["ran"], flush=True)
except Exception as refusal:
    print("  pipeline   : not seeded -- %s" % refusal, flush=True)

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
_icon_path = (
    Path(__file__).resolve().parents[1]
    / "12.PRODUCTION" / "app" / "assets" / "archhub.ico"
)
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

# BABOOM: the ambient companion, attached through the SAME signed
# agent-session path any governed agent uses. A failure to attach is
# printed honestly and never fakes a companion.
baboom_host = None
try:
    from nodelang.baboom_attach import attach_baboom_companion
    baboom_host, baboom_window = attach_baboom_companion(
        server,
        state_dir=state_dir,
        descriptor_path=descriptor_path,
        key_provider=machine_key_provider,
    )
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
