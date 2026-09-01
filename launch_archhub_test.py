"""ArchHub TEST launcher -- one double-click, the windowed desktop app.

Boots the universal cell application on a PERSISTENT store under
%LOCALAPPDATA%/ArchHub-Test (your live graph is never touched) and opens
it in its own application window. Close the window to stop ArchHub TEST.
"""
import os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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
view.load(QUrl(server.bootstrap_url))
window.show()

code = app.exec()
server.close()
raise SystemExit(code)
