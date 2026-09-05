"""First-run setup for a colleague's machine.

Nobody runs this file by hand. The colleague runs ArchHub-Setup.exe from
the firm share; it installs into LOCALAPPDATA/ArchHub and leaves a
Start-menu entry and a Desktop icon, both opening ArchHub.vbs. The FIRST
time that icon is opened, ArchHub.vbs finds no .archhub-ready marker and
hands over to ArchHub.bat, which runs this file in a window the person can
read. When it returns zero the marker is written and ArchHub opens by
itself; every later open goes straight to the application.

The founder's laws apply to the people he hands this to: the application
must open, and anything it needs installs itself or says plainly what is
missing. Run from the firm share, the package carries no mark-of-the-web,
so Windows raises no SmartScreen warning.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# (pip name, import probe). What the DESKTOP boot reaches, measured by
# importing the launcher modules and reading sys.modules -- not a guess. A
# court holds this list against that measurement, so a dependency added to
# the app cannot ship without landing here too. Before that court, rpds-py,
# fastapi and uvicorn were missing and a first launch on a clean machine
# died on import with no window and no message.
PACKAGES = (
    ("PyQt6", "PyQt6"),
    ("PyQt6-WebEngine", "PyQt6.QtWebEngineWidgets"),
    ("cryptography", "cryptography"),
    ("httpx", "httpx"),
    ("joserfc", "joserfc"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("rpds-py", "rpds"),
    ("opencv-python-headless", "cv2"),
    ("ezdxf", "ezdxf"),
    ("numpy", "numpy"),
)


def _has(module):
    try:
        __import__(module)
        return True
    except Exception:
        return False


def main():
    print("ArchHub setup")
    print("  python     :", sys.version.split()[0])
    if sys.version_info < (3, 11):
        print("  REFUSED: ArchHub needs Python 3.11 or newer.")
        print("  Install it from python.org, then run this again.")
        return 2
    missing = [name for name, probe in PACKAGES if not _has(probe)]
    if missing:
        print("  installing :", ", ".join(missing))
        # Versions come from the shipped requirements.txt, the same pins the
        # founder machine runs; an unpinned "pip install <name>" would put
        # whatever PyPI serves today on a colleague machine.
        pinned = Path(__file__).resolve().parent / "requirements.txt"
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user",
             "-r", str(pinned)]
        )
        if result.returncode != 0:
            print("  REFUSED: the install did not finish. Nothing was faked;")
            print("  send this window's text to Ahmed.")
            return result.returncode
    else:
        print("  packages   : already present")
    root = Path(__file__).resolve().parent
    if not (root / "launch_archhub_test.py").is_file():
        print("  REFUSED: launch_archhub_test.py is not beside this file.")
        return 3
    # Prove the boot imports resolve NOW, in this interpreter, so a failure
    # is a sentence on this screen rather than a window that never opens.
    for _pip_name, probe in PACKAGES:
        if probe in ("cv2", "ezdxf", "numpy"):
            continue  # optional engines; the app reports them as absent
        if not _has(probe):
            print("  REFUSED: %s installed but cannot be imported." % probe)
            print("  send this window text to Ahmed.")
            return 4
    # The installer owns the shortcuts (Start menu + Desktop, both opening
    # ArchHub.vbs). Writing a second one here put two different ArchHub
    # entries on the Desktop.
    #
    # ArchHub.bat opens the application itself the moment this returns zero.
    # Telling the person to go and double-click something sent colleagues
    # hunting for an icon while the app was already coming up behind them.
    print("  ready. ArchHub is opening now.")
    print("  Next time, open it from the ArchHub icon on your Desktop"
          " or in the Start menu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
