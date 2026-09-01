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
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.pipeline_engines import PIPELINE_ENGINES

# The runtime-pipe signing secret and descriptor live beside the store;
# they are what lets BABOOM (and any governed agent) bind a signed
# session against THIS runtime.
_pipe_secret_path = state_dir / "runtime-pipe.secret"
if not _pipe_secret_path.is_file():
    import secrets as _secrets
    _pipe_secret_path.write_bytes(_secrets.token_bytes(32))
machine_key_provider = MemorySigningKeyProvider(
    "archhub.local.universal-runtime-pipe",
    _pipe_secret_path.read_bytes(),
)
descriptor_path = state_dir / "runtime-descriptor.json"

started = time.perf_counter()
server = ApplicationServer(
    universal_state_path=state_path,
    pipeline_effect_engines=PIPELINE_ENGINES,
    enable_machine_transport=True,
    machine_descriptor_path=descriptor_path,
    machine_key_provider=machine_key_provider,
).start()
print(f"  booted in {time.perf_counter()-started:.0f}s", flush=True)
print("  URL:", server.bootstrap_url, flush=True)

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
    server.close()
raise SystemExit(code)
