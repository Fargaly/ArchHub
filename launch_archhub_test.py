"""ArchHub TEST launcher -- one double-click, the windowed desktop app.

Boots the universal cell application on a PERSISTENT store under
%LOCALAPPDATA%/ArchHub-Test (your live graph is never touched) and opens
it in its own application window. Close the window to stop ArchHub TEST.
"""
import os, sys, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# pythonw has no console: stdout/stderr vanish and a crash is invisible.
# Everything this launcher says goes to a file the founder can open.
_log_dir = Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test"
_log_dir.mkdir(parents=True, exist_ok=True)
_log = open(_log_dir / "launcher.log", "a", encoding="utf-8", buffering=1)
sys.stdout = _log
sys.stderr = _log
print("=== launch", time.strftime("%Y-%m-%d %H:%M:%S"), "===")

state_dir = Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test"
state_dir.mkdir(parents=True, exist_ok=True)
state_path = state_dir / "archhub-test.universal.sqlite3"

# listdir membership: Path.exists() returns False on a Windows sharing
# violation (a dying prior instance still holds the handle), which would
# mislabel a warm store as a first boot and wipe its checkpoint.
first_boot = state_path.name not in os.listdir(state_dir)
if first_boot:
    # A fresh store with a stale signed checkpoint (it lives under
    # %LOCALAPPDATA%/ArchHub/checkpoints keyed by the database path)
    # reads as "rolled back behind its checkpoint" and is rightly
    # refused. Fresh means fresh: clear the sidecars AND that checkpoint.
    import hashlib
    for stale in state_dir.glob(state_path.name + "*"):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass
    identity = hashlib.sha256(
        str(state_path.resolve()).casefold().encode("utf-8")
    ).hexdigest()
    checkpoint = (
        Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / "checkpoints"
        / (identity + ".json")
    )
    checkpoint.unlink(missing_ok=True)

print("ArchHub TEST")
print("  graph store :", state_path)
print("  first boot  :", first_boot, "(first boot builds the graph, ~1-2 min)")
print("  booting ...", flush=True)

from nodelang.application_server import ApplicationServer
from nodelang.pipeline_engines import PIPELINE_ENGINES

started = time.perf_counter()
server = ApplicationServer(
    universal_state_path=state_path,
    pipeline_effect_engines=PIPELINE_ENGINES,
).start()
print(f"  booted in {time.perf_counter()-started:.0f}s", flush=True)
print("  URL:", server.bootstrap_url, flush=True)

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
view.load(QUrl(server.bootstrap_url))
window.show()

try:
    code = app.exec()
except BaseException:
    traceback.print_exc()
    code = 1
finally:
    server.close()
raise SystemExit(code)
