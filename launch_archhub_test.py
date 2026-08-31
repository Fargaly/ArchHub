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

first_boot = not state_path.exists()
print("ArchHub TEST")
print("  graph store :", state_path)
print("  first boot  :", first_boot, "(first boot builds the graph, ~1-2 min)")
print("  booting ...", flush=True)

started = time.perf_counter()
server = ApplicationServer(universal_state_path=state_path).start()
print(f"  booted in {time.perf_counter()-started:.0f}s")
print()
print("  URL:", server.bootstrap_url)
print()
print("Close this window to stop ArchHub.")
webbrowser.open(server.bootstrap_url)
try:
    while True:
        time.sleep(5)
except KeyboardInterrupt:
    pass
finally:
    server.close()
