"""The existing court write guard, shared by release entrypoints and their Python children."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

def _profile_path(path):
    target = os.path.normcase(os.path.realpath(os.fsdecode(path)))
    if target.startswith("\\\\?\\unc\\"):
        return "\\\\" + target[8:]
    return target.removeprefix("\\\\?\\")


def _real_profile_paths():
    if os.name == "nt":
        import winreg
        # Logon values are independent of the redirected process environment.
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Volatile Environment") as key:
            home = Path(winreg.QueryValueEx(key, "USERPROFILE")[0])
            local = Path(winreg.QueryValueEx(key, "LOCALAPPDATA")[0])
    else:
        import pwd
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        local = home / ".local" / "share"
    return tuple(_profile_path(path) for path in (
        home / ".archhub", local / "ArchHub" / "governance"))


def _deny_profile_write(event, args, protected, attempts):
    if event == "open":
        path, mode, flags = args
        if not (set(mode or "") & set("wax+") or (flags or 0) & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            return
        paths = (path,)
    elif event in ("os.rename", "os.link", "os.symlink"):
        paths = args[:2]
    elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime",
                   "os.truncate", "sqlite3.connect"):
        paths = args[:1]
    else:
        return
    for path in paths:
        if not isinstance(path, (str, bytes, os.PathLike)):
            continue
        target = _profile_path(path)
        if any(target == root or target.startswith(root + os.sep) for root in protected):
            attempts.append((event, target))
            raise AssertionError("court refused a write to the real profile: " + target)



_INSTALLED = False


def install(log=None, *, protected=()):
    global _INSTALLED
    if _INSTALLED:
        return
    roots = (*_real_profile_paths(), *(_profile_path(path) for path in protected),
             *json.loads(os.environ.get("ARCHHUB_PROFILE_GUARD_ROOTS", "[]")))
    receipt = Path(os.environ.get("ARCHHUB_PROFILE_GUARD_LOG") or log)
    os.environ["ARCHHUB_PROFILE_GUARD_LOG"] = str(receipt)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    def deny(event, args):
        try:
            _deny_profile_write(event, args, protected=roots, attempts=attempts)
        except AssertionError:
            with receipt.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(attempts[-1]) + "\n")
            raise
    sys.addaudithook(deny)
    _INSTALLED = True
    def finish():
        if attempts or (receipt.exists() and receipt.stat().st_size):
            print("PROFILE-WRITE-GUARD: refused protected write", file=sys.stderr, flush=True)
            sys.stdout.flush()
            os._exit(3)
    atexit.register(finish)


def command(parts):
    """Keep interpreter flags, including -I/-E, and install before any application import."""
    parts = [str(part) for part in parts]
    if Path(parts[0]).name.lower() not in ("python", "python.exe", "python3", "python3.exe"):
        return parts
    index = 1
    while index < len(parts) and parts[index] in ("-I", "-E", "-s", "-B", "-u"):
        index += 1
    if index < len(parts) and parts[index] == str(Path(__file__).resolve()):
        return parts
    if index < len(parts) and parts[index] == "-c":
        prefix = "import runpy; runpy.run_path(" + repr(str(Path(__file__).resolve())) + ")['install']();\n"
        return [*parts[:index], "-c", prefix + parts[index + 1], *parts[index + 2:]]
    return [*parts[:index], str(Path(__file__).resolve()), *parts[index:]]


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if arguments[:1] == ["--profile"]:
        profile = Path(arguments[1]).resolve()
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from real_app_check import isolated_env
        isolated = isolated_env(dict(os.environ), profile)
        os.environ.clear()
        os.environ.update(isolated)
        arguments = arguments[2:]
    install()
    target, *args = arguments
    sys.argv = [target, *args]
    if target in ("-c", "-m") and not sys.flags.safe_path:
        sys.path[0] = os.getcwd()
    if target == "-c":
        raise SystemExit(subprocess.call(command([sys.executable, "-c", *args])))
    elif target == "-m":
        sys.argv = [args[0], *args[1:]]
        runpy.run_module(args[0], run_name="__main__", alter_sys=True)
    else:
        sys.path.insert(0, str(Path(target).resolve().parent))
        runpy.run_path(target, run_name="__main__")
