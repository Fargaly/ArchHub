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
    ("mcp", "mcp"),
) + ((("pywin32", "pythoncom"), ("pywin32", "win32com.client"))
     if sys.platform == "win32" else ())


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



# This setup evidence is deliberately separate from runtime broker probes:
# no listener, COM attachment, host process or assistant session is opened.
_HOST_SETUP_NAMES = {
    "revit": "Revit", "autocad": "AutoCAD", "max": "3ds Max",
    "rhino": "Rhino", "blender": "Blender", "excel": "Excel",
    "word": "Word", "powerpoint": "PowerPoint", "outlook": "Classic Outlook",
}
_HOST_SETUP_EXES = dict(zip(_HOST_SETUP_NAMES, (
    "Revit.exe", "acad.exe", "3dsmax.exe", "Rhino.exe", "blender.exe",
    "EXCEL.EXE", "WINWORD.EXE", "POWERPNT.EXE", "OUTLOOK.EXE",
)))


def _setup_app_paths(exe: str) -> list[Path]:
    """Read only the named executable's Windows App Paths registrations."""
    if sys.platform != "win32":
        return []
    import winreg
    paths = []
    key = "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + exe
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                    value, kind = winreg.QueryValueEx(handle, "")
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str):
                    paths.append(Path(os.path.expandvars(value.strip().strip('"'))))
            except OSError:
                continue
    return paths


def _setup_children(directory: Path, limit: int = 32) -> list[Path]:
    """Bounded single-directory inventory; never descend into host projects."""
    try:
        with os.scandir(directory) as entries:
            paths = []
            for index, entry in enumerate(entries):
                if index == limit:
                    break
                paths.append(Path(entry.path))
            return paths
    except OSError:
        return []


def _setup_host_installations() -> dict[str, list[str]]:
    """Executable file evidence only; custom or unregistered installs may be missed."""
    found = {host: set() for host in _HOST_SETUP_NAMES}
    bases = {Path(value) for key in ("ProgramFiles", "ProgramFiles(x86)")
             if (value := os.environ.get(key))}
    for host, exe in _HOST_SETUP_EXES.items():
        candidates = _setup_app_paths(exe)
        for base in bases:
            if host in ("revit", "autocad", "max"):
                candidates.extend(base / "Autodesk" / f"{_HOST_SETUP_NAMES[host]} {year}" / exe
                                  for year in range(2018, 2036))
            elif host == "rhino":
                candidates.extend(base / f"Rhino {version}" / "System" / exe
                                  for version in range(5, 11))
            elif host == "blender":
                candidates.extend(path / exe for path in _setup_children(base / "Blender Foundation"))
            else:
                candidates.extend((base / "Microsoft Office" / "root" / "Office16" / exe,
                                   base / "Microsoft Office" / "Office16" / exe))
        for path in candidates:
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            if host in ("revit", "autocad", "max"):
                match = re.search(r"(?:Revit|AutoCAD|3ds Max) (20\d{2})(?:[\\/]|$)", str(path), re.I)
            elif host in ("rhino", "blender"):
                match = re.search(r"(?:Rhino|Blender) (\d+(?:\.\d+)*)(?:[\\/]|$)", str(path), re.I)
            else:
                match = None
            found[host].add(match.group(1) if match else "version-unchecked")
    return {host: sorted(versions) for host, versions in found.items()}


def _setup_compiler_candidates(root: Path) -> bool:
    """Find files, never execute a compiler or imply language-version validation."""
    candidates = [root / "bin" / "csc" / "csc.exe"]
    if value := os.environ.get("ARCHHUB_CSC_PATH"):
        candidates.append(Path(value))
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        if not (value := os.environ.get(key)):
            continue
        base = Path(value)
        for edition in ("BuildTools", "Community", "Professional", "Enterprise"):
            candidates.append(base / "Microsoft Visual Studio" / "2022" / edition
                              / "MSBuild" / "Current" / "Bin" / "Roslyn" / "csc.exe")
        candidates.extend(sdk / "Roslyn" / "bincore" / "csc.dll"
                          for sdk in _setup_children(base / "dotnet" / "sdk"))
    # A framework csc can exist yet support only C# 5. Its presence remains
    # unverified here; the existing runtime owner must enforce C# >= 7.3.
    if value := os.environ.get("WINDIR"):
        candidates.append(Path(value) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe")
    return any(path.is_file() for path in candidates)


def host_installation_readiness(root: Path) -> list[dict]:
    """Passive setup evidence, never permission or a claim of live execution readiness."""
    installations = _setup_host_installations()
    compiler = "candidate-unverified" if _setup_compiler_candidates(root) else "compiler-not-found"
    com_available = sys.platform == "win32" and _has("pythoncom") and _has("win32com.client")
    rows = [{"host": "Assistant MCP runtime", "version": "",
             "host_installation": "not-applicable",
             "packaged": "importable" if _has("mcp") else "dependency-missing",
             "deployment": "assistant-registration-unchecked", "compiler": "not-applicable",
             "detail": "MCP import does not establish assistant registration, a session, or graph access."}]
    scripts = {"rhino": root / "bridges/rhino/archhub_mcp.py",
               "blender": root / "bridges/blender/archhub_mcp/__init__.py",
               # installer/build_release.ps1 ships no 3ds Max script; bridges/sources is never payload.
               "max": None}
    for host, label in _HOST_SETUP_NAMES.items():
        for version in installations.get(host) or ["not-detected"]:
            row = {"host": label, "version": version,
                   "host_installation": "executable-found" if version != "not-detected" else "not-detected",
                   "packaged": "not-packaged", "deployment": "unchecked",
                   "compiler": compiler if host in ("revit", "autocad") else "not-applicable",
                   "detail": "No host was opened; authentication and host load state are unchecked."}
            if host in ("revit", "autocad"):
                names = ("RevitMCP.dll", "RevitMCPCore.dll") if host == "revit" else ("AcadMCP.dll",)
                payload = root / "bridges" / host / version
                if all((payload / name).is_file() for name in names):
                    row["packaged"] = "payload-files-present-unverified"
                    row["detail"] = "Payload files exist; release closure, matching host registration and compiler compatibility need verification. A host restart may be needed after deployment."
                else:
                    row["detail"] = "This build has no connector payload for this detected host version; installing the host alone does not install its ArchHub connector."
                if host == "revit" and re.fullmatch(r"20\d{2}", version) and os.environ.get("APPDATA"):
                    manifest = Path(os.environ["APPDATA"]) / "Autodesk/Revit/Addins" / version / "RevitMCP.addin"
                    if manifest.is_file():
                        row["deployment"] = "registration-present-unverified"
                        row["detail"] += " An existing Revit add-in registration was found; its ownership, version and load state were not verified."
            elif host in scripts:
                row["packaged"] = ("script-packaged" if scripts[host] is not None and scripts[host].is_file()
                                   else "not-packaged")
                row["deployment"] = "activation-unchecked"
                row["detail"] = ("This build does not package an ArchHub script for this host." if scripts[host] is None
                                 else "The host must explicitly load the ArchHub script; script presence does not establish activation.")
                if host == "rhino":
                    row["detail"] += " The packaged script requires Rhino 8 CPython 3."
                    if version.isdigit() and int(version) < 8:
                        row["deployment"] = "unsupported-version"
                elif host == "blender":
                    row["detail"] += " The packaged add-on declares Blender 3.6 or newer."
                    if re.fullmatch(r"\d+(?:\.\d+)*", version) and tuple(map(int, version.split("."))) < (3, 6):
                        row["deployment"] = "unsupported-version"
                elif re.fullmatch(r"20\d{2}", version) and os.environ.get("LOCALAPPDATA"):
                    startup = Path(os.environ["LOCALAPPDATA"]) / "Autodesk/3dsMax" / f"{version} - 64bit" / "ENU/scripts/startup/max_mcp_startup.py"
                    if startup.is_file():
                        row["deployment"] = "startup-script-present-unverified"
                        row["detail"] += " A per-user startup script exists; its contents and host load state are unchecked. A host restart may be needed after deployment."
            else:
                row["packaged"] = "COM-dependency-importable" if com_available else "pywin32-missing"
                row["deployment"] = "built-in-COM-adapter"
                row["detail"] = "Requires the installed Windows desktop Office application and its configured user profile; no separate listener is installed. COM access and sign-in are unchecked."
                if host == "outlook":
                    row["detail"] += " New Outlook uses the separate Microsoft Graph connector and its prerequisite/sign-in check."
            rows.append(row)
    return rows


def print_host_installation_readiness(root: Path) -> None:
    print("  external hosts: passive installation evidence; no host or assistant was opened")
    print("  Detection covers App Paths and bounded standard locations; custom installs may be missed.")
    try:
        for row in host_installation_readiness(root):
            print("  {host} {version}: host={host_installation}; payload={packaged}; deployment={deployment}; compiler={compiler}".format(**row))
            print("    " + row["detail"])
    except Exception:  # noqa: BLE001 - evidence only; the ready marker must still be written
        print("  Host installation evidence is unavailable. External connectors are not verified ready.")


def _launcher_state_root() -> Path:
    # launch_archhub_test.py owns this location; a court holds the two equal.
    return Path(os.environ.get("ARCHHUB_TEST_STATE_DIR")
                or Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test")


def _assistant_integration(root: Path, identity: str) -> None:
    """Offer Claude Code registration, record the choice, and say what is true.

    Registration adds one entry to this Windows user's Claude Code MCP list,
    and only on their yes. It does not start the server, connect a session or
    prove a host action; the window says so.
    """
    import json
    from nodelang.client_mcp_installation import readiness, register_claude_code

    state = _launcher_state_root()
    receipt_path = state / "assistant-integration.json"
    try:
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        previous = {}
    report = readiness(root, state)
    requested = [argument.split("=", 1)[1] for argument in sys.argv[1:]
                 if argument.startswith("--assistant=")]
    choice = "not_asked"
    if report["claude_code"] == "ready_to_register":
        if requested:
            choice = "accepted" if requested[-1] == "claude-code" else "declined"
        elif type(previous) is dict and previous.get("choice") == "declined":
            choice = "declined"
        elif sys.stdin is not None and sys.stdin.isatty():
            try:
                answer = input("  Connect ArchHub tools to Claude Code for this Windows user?"
                               " It adds one entry to your Claude Code MCP list and"
                               " changes nothing else. [y/N] ")
            except EOFError:
                answer = None
            if answer is not None:
                choice = "accepted" if answer.strip().lower() in ("y", "yes") else "declined"
        if choice == "accepted":
            report = register_claude_code(root, state, consent=True)
    print("  claude code:", report["claude_code"])
    if report.get("reason"):
        suffix = "" if report.get("exit_code") is None else " (exit %d)" % report["exit_code"]
        print("  reason     : %s%s" % (report["reason"], suffix))
    if report.get("project_overrides"):
        print("  override   : %d Claude Code project(s) define their own %s; the user entry"
              " does not apply in those projects, and nothing was changed there."
              % (report["project_overrides"], report["server_name"]))
    if report.get("legacy_migration_needed"):
        print("  legacy     : %s: migration needed; not an ArchHub connection; left unchanged"
              % ", ".join(report["legacy_migration_needed"]))
    print("  claude app :", report["claude_desktop"])
    if report["claude_code"] == "registered":
        print("  note       : entry registered only. Open ArchHub, then start Claude Code to"
              " use it; a project's own .mcp.json can still override it. Setup does not"
              " verify host actions.")
    elif report["claude_code"] == "registered_with_project_overrides":
        print("  note       : entry registered, but not in effect in the projects above."
              " Setup does not verify host actions.")
    elif report["claude_code"] == "ready_to_register":
        print("  later      : \"%s\" -E -s \"%s\" --assistant=claude-code"
              % (sys.executable, root / "colleague_setup.py"))
    entry = report.get("entry")
    receipt = {
        "schema": "assistant-integration-v1", "build": identity, "client": "claude-code",
        "choice": choice, "result": report["claude_code"], "server_name": report["server_name"],
        "entry_sha256": (hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":"))
                                        .encode("utf-8")).hexdigest() if entry else None),
        "exit_code": report.get("exit_code"), "project_overrides": report.get("project_overrides", 0),
        "legacy_migration_needed": list(report.get("legacy_migration_needed") or ()),
        "host_execution": "not_verified",
    }
    state.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".assistant-integration-", dir=state)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, receipt_path)
    finally:
        temporary.unlink(missing_ok=True)


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
    print_host_installation_readiness(root)
    try:
        if readiness_identity(root) != identity:
            raise ValueError("installed build changed during setup")
        _write_ready(root, identity)
    except (OSError, UnicodeError, ValueError):
        print("  REFUSED: setup could not record this build as ready. Run setup again.")
        return 6
    # Offered once the build is ready. A failure here is one line on this
    # screen, never an application that does not open.
    try:
        _assistant_integration(root, identity)
    except Exception as exc:  # noqa: BLE001 - the application must still open
        print("  assistant  : not connected (%s)" % type(exc).__name__)
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
