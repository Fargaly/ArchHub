"""First-run setup for a colleague's machine.

Nobody runs this file by hand. The colleague runs ArchHub-Setup.exe from
the firm share; it installs into LOCALAPPDATA/ArchHub and leaves a
Start-menu entry and a Desktop icon, both opening ArchHub.vbs. The FIRST
time that icon is opened, ArchHub.vbs finds no .archhub-ready marker and
hands over to ArchHub.bat, which runs this file in a window the person can
read. Setup writes a marker bound to BUILD_ID and requirements.txt only
after dependencies and imports succeed. An upgraded build invalidates the
old marker; later opens validate the private environment before launching.

The founder's laws apply to the people he hands this to: the application
must open, and anything it needs installs itself or says plainly what is
missing. Windows trust prompts depend on how the installer was obtained and
the machine's policy; a firm share alone does not guarantee their absence.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import stat
import site
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
    ("psutil", "psutil"),
    ("keyring", "keyring"),
)


def _has(module):
    try:
        __import__(module)
        return True
    except Exception:
        return False


def readiness_identity(root: Path) -> str:
    """Bind successful setup to the installed build and dependency manifest."""
    with (root / "BUILD_ID").open("r", encoding="ascii") as stream:
        raw_build_id = stream.read(257)
    if len(raw_build_id) > 256:
        raise ValueError("invalid installed build identity")
    build_id = raw_build_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", build_id):
        raise ValueError("invalid installed build identity")
    with (root / "requirements.txt").open("rb") as stream:
        requirements = stream.read(65537)
    if not requirements or len(requirements) > 65536:
        raise ValueError("invalid installed requirements manifest")
    return build_id + ":" + hashlib.sha256(requirements).hexdigest()


def ready_for_build(root: Path) -> bool:
    try:
        if not owned_interpreter(root):
            return False
        identity = readiness_identity(root)
        with (root / ".archhub-ready").open("r", encoding="ascii") as stream:
            marker = stream.read(257)
        return len(marker) <= 256 and marker.strip() == "venv-v1:" + identity
    except (OSError, UnicodeError, ValueError):
        return False


def _write_ready(root: Path, identity: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".archhub-ready-", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
            stream.write("venv-v1:" + identity + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / ".archhub-ready")
    finally:
        temporary.unlink(missing_ok=True)


def clean_environment():
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONNOUSERSITE"] = "1"
    return env


def environment_path(root: Path) -> Path:
    """Reject redirected owned paths before any child interpreter is used."""
    owned = root / ".venv"
    for path in (owned, owned / "Scripts", owned / "pyvenv.cfg",
                 owned / "Scripts/python.exe", owned / "Scripts/pythonw.exe"):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("redirected ArchHub environment")
    return owned


def owned_interpreter(root: Path) -> bool:
    owned = environment_path(root)
    config = owned / "pyvenv.cfg"
    return (config.is_file()
            and re.search(r"(?im)^include-system-site-packages\s*=\s*false\s*$",
                          config.read_text(encoding="utf-8")) is not None
            and (owned / "Scripts/python.exe").is_file()
            and (owned / "Scripts/pythonw.exe").is_file()
            and Path(sys.executable).resolve() == (owned / "Scripts/python.exe").resolve()
            and Path(sys.prefix).resolve() == owned.resolve()
            and sys.prefix != sys.base_prefix
            and site.ENABLE_USER_SITE is False)


def prepare_environment(root: Path, check_only=False):
    """Return None only inside the validated environment; otherwise child status."""
    owned = environment_path(root)
    if owned_interpreter(root):
        return None
    if Path(sys.prefix).resolve() == owned.resolve():
        raise ValueError("invalid ArchHub environment interpreter")
    if not owned.exists():
        if check_only:
            return 1
        result = subprocess.run([sys.executable, "-E", "-s", "-m", "venv", str(owned)],
                                env=clean_environment())
        if result.returncode:
            return result.returncode
    environment_path(root)
    if not all((owned / name).is_file() for name in
               ("pyvenv.cfg", "Scripts/python.exe", "Scripts/pythonw.exe")):
        raise ValueError("damaged ArchHub environment; repair is required")
    # A private flag prevents recursion if the interpreter does not identify as ours.
    if "--owned-environment" in sys.argv:
        raise ValueError("ArchHub environment identity mismatch")
    args = ["--owned-environment"] + (["--check-ready"] if check_only else [])
    return subprocess.run([str(owned / "Scripts/python.exe"), "-E", "-s",
                           str(root / "colleague_setup.py"), *args],
                          env=clean_environment()).returncode


def main():
    print("ArchHub setup")
    print("  python     :", sys.version.split()[0])
    if sys.version_info < (3, 11):
        print("  REFUSED: ArchHub needs Python 3.11 or newer.")
        print("  Install it from python.org, then run this again.")
        return 2
    root = Path(__file__).resolve().parent
    try:
        identity = readiness_identity(root)
    except (OSError, UnicodeError, ValueError):
        print("  REFUSED: the installed build or requirements manifest is missing or invalid.")
        print("  Run the ArchHub installer again.")
        return 5
    if not (root / "launch_archhub_test.py").is_file():
        print("  REFUSED: launch_archhub_test.py is not beside this file.")
        return 3
    try:
        child_status = prepare_environment(root)
        if child_status is not None:
            return child_status
    except (OSError, ValueError):
        print("  REFUSED: ArchHub's private Python environment needs repair. No shared packages were changed.")
        return 7
    missing = [name for name, probe in PACKAGES if not _has(probe)]
    if missing or not ready_for_build(root):
        (root / ".archhub-ready").unlink(missing_ok=True)
        print("  preparing  : dependencies for this installed build")
        # Apply the shipped version constraints even when old imports work.
        # Without this, an upgrade silently retained incompatible packages.
        pinned = root / "requirements.txt"
        result = subprocess.run(
            [sys.executable, "-E", "-s", "-m", "pip", "--isolated", "install",
             "-r", str(pinned)], env=clean_environment()
        )
        if result.returncode != 0:
            print("  REFUSED: the install did not finish. Nothing was faked;")
            print("  send this window's text to Ahmed.")
            return result.returncode
    else:
        print("  packages   : already present")
    # Prove the boot imports resolve NOW, in this interpreter, so a failure
    # is a sentence on this screen rather than a window that never opens.
    for _pip_name, probe in PACKAGES:
        if probe in ("cv2", "ezdxf", "numpy"):
            continue  # optional engines; the app reports them as absent
        if not _has(probe):
            print("  REFUSED: %s installed but cannot be imported." % probe)
            print("  send this window text to Ahmed.")
            return 4
    try:
        if readiness_identity(root) != identity:
            raise ValueError("installed build changed during setup")
        _write_ready(root, identity)
    except (OSError, UnicodeError, ValueError):
        print("  REFUSED: setup could not record this build as ready. Run setup again.")
        return 6
    # The installer owns the shortcuts (Start menu + Desktop, both opening
    # ArchHub.vbs). Writing a second one here put two different ArchHub
    # entries on the Desktop.
    #
    # ArchHub.bat returns success to ArchHub.vbs, which opens the application.
    # Telling the person to go and double-click something sent colleagues
    # hunting for an icon while the app was already coming up behind them.
    print("  ready. ArchHub is opening now.")
    print("  Next time, open it from the ArchHub icon on your Desktop"
          " or in the Start menu.")
    return 0


if __name__ == "__main__":
    if "--check-ready" in sys.argv[1:]:
        # Checking may use an existing environment, but never creates/repairs one.
        root = Path(__file__).resolve().parent
        try:
            if owned_interpreter(root):
                status = 0 if ready_for_build(root) else 1
            else:
                status = prepare_environment(root, check_only=True)
        except (OSError, ValueError):
            status = 1
        raise SystemExit(status)
    raise SystemExit(main())
