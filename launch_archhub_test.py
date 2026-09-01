"""ArchHub TEST launcher — one double-click, persistent test graph.

Boots the universal cell application on a PERSISTENT store under
%LOCALAPPDATA%/ArchHub-Test (your live graph is never touched), prints the
URL, and opens the browser on the authenticated bootstrap link.
Close this window to stop the server.
"""
import os, sys, time, webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from nodelang.application_server import ApplicationServer

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

started = time.perf_counter()
server = ApplicationServer(universal_state_path=state_path).start()
print(f"  booted in {time.perf_counter()-started:.0f}s", flush=True)
print()
print("  URL:", server.bootstrap_url, flush=True)
print()
print("Close this window to stop ArchHub.")
if not os.environ.get("ARCHHUB_TEST_NO_OPEN"):
    webbrowser.open(server.bootstrap_url)
try:
    while True:
        time.sleep(5)
except KeyboardInterrupt:
    pass
finally:
    server.close()
