"""Run from app/ directory. Writes result to ../build_output.txt"""
import sys, os, subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(BASE, "payload", "sources", "revit_mcp")
OUT  = os.path.join(BASE, "payload", "revit", "2023")
LOG_PATH = os.path.join(BASE, "build_output.txt")

log = open(LOG_PATH, "w", buffering=1)

def log_line(s):
    print(s, flush=True)
    log.write(s + "\n")
    log.flush()

log_line("=== Revit 2023 Build ===")

# Step 1: Find Revit 2023
revit_dir = r"C:\Program Files\Autodesk\Revit 2023"
if not os.path.exists(os.path.join(revit_dir, "RevitAPI.dll")):
    log_line("FAILED: Revit 2023 not found at " + revit_dir)
    log.close(); sys.exit(1)
log_line("Revit found: " + revit_dir)

# Step 2: Force restore (passes TargetFramework=net48)
log_line("Running: dotnet restore --force -p:TargetFramework=net48 ...")
r1 = subprocess.run(
    ["dotnet", "restore", SRC,
     "--force",
     "-p:TargetFramework=net48",
     f"-p:RevitInstallDir={revit_dir}"],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)
for line in (r1.stdout + r1.stderr).splitlines():
    if line.strip(): log_line("  restore> " + line)
if r1.returncode != 0:
    log_line(f"FAILED: restore exit code {r1.returncode}")
    log.close(); sys.exit(1)
log_line("Restore OK")

# Step 3: Build
os.makedirs(OUT, exist_ok=True)
log_line("Running: dotnet build ...")
r2 = subprocess.run(
    ["dotnet", "build", SRC,
     "-c", "Release",
     "-p:TargetFramework=net48",
     f"-p:RevitInstallDir={revit_dir}",
     "--no-restore",
     "-o", OUT],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)
for line in (r2.stdout + r2.stderr).splitlines():
    if line.strip(): log_line("  build> " + line)

if r2.returncode == 0:
    files = os.listdir(OUT)
    log_line(f"SUCCESS: {len(files)} files in {OUT}")
    for f in files:
        log_line("  " + f)
else:
    log_line(f"FAILED: exit code {r2.returncode}")

log.close()
