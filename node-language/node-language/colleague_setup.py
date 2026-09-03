"""One-file setup for a colleague's machine.

The founder's laws apply to the people he hands this to: the
application must open, and anything it needs installs itself or says
plainly what is missing. Copied from the firm share, the package
carries no mark-of-the-web, so Windows raises no SmartScreen warning.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGES = (
    ("PyQt6", "PyQt6"),
    ("PyQt6-WebEngine", "PyQt6.QtWebEngineWidgets"),
    ("cryptography", "cryptography"),
    ("httpx", "httpx"),
    ("joserfc", "joserfc"),
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
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", *missing]
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
    windowless = sys.executable.replace("python.exe", "pythonw.exe")
    desktop = Path(os.path.expanduser("~")) / "Desktop" / "ArchHub.bat"
    desktop.write_text(
        chr(13).join([
            "@echo off",
            'cd /d "%s"' % root,
            'start "" "%s" launch_archhub_test.py' % windowless,
            "",
        ]).replace(chr(13), chr(13) + chr(10)),
        encoding="utf-8",
    )
    print("  shortcut   :", desktop)
    print("  ready. Double-click ArchHub on your Desktop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
