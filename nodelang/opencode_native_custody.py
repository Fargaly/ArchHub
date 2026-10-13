"""Observe the real installed OpenCode parent of a native gate worker.

The trusted plugin exports the actual hook session ID to its direct child.
Process ancestry verifies host custody; authenticated read verifies the session
exists in that host/workspace. This is not isolation from a malicious OS user.
"""
from dataclasses import dataclass
from pathlib import Path
import base64
import json
import os
import urllib.parse
import urllib.request


@dataclass(frozen=True)
class Process:
    pid: int
    created: float
    parent: int
    executable: str
    cwd: str
    session_id: str


def observe(pid):
    import psutil
    p = psutil.Process(pid)
    created = p.create_time()
    result = Process(pid, created, p.ppid(), str(Path(p.exe()).resolve()),
                     str(Path(p.cwd()).resolve()), p.environ().get("OPENCODE_SESSION_ID", ""))
    if psutil.Process(pid).create_time() != created:
        raise RuntimeError("OpenCode process changed during custody read")
    return result


def verify_session(parent, session_id, directory):
    import psutil
    p = psutil.Process(parent.pid)
    env = p.environ()
    password = env.get("OPENCODE_SERVER_PASSWORD")
    username = env.get("OPENCODE_SERVER_USERNAME", "opencode")
    if not password:
        raise RuntimeError("OpenCode authenticated native session read unavailable")
    token = base64.b64encode((username + ":" + password).encode()).decode()
    ports = sorted({c.laddr.port for c in p.net_connections(kind="tcp")
                    if c.status == "LISTEN" and c.laddr.ip == "127.0.0.1"})
    if len(ports) != 1:
        raise RuntimeError("OpenCode native API owner is ambiguous")
    url = "http://127.0.0.1:%d/session/%s?directory=%s" % (
        ports[0], urllib.parse.quote(session_id, safe=""), urllib.parse.quote(directory, safe=""))
    # Credentials remain in memory, never argv, diagnostics or persisted frames.
    request = urllib.request.Request(url, headers={"Authorization": "Basic " + token})
    try:
        # Never follow redirects carrying a native owner's authentication.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=5) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("session read exceeds bound")
        value = json.loads(raw)
        if value.get("id") != session_id or os.path.normcase(str(Path(value.get("directory", "")).resolve())) != os.path.normcase(directory):
            raise ValueError("session workspace mismatch")
    except Exception:
        raise RuntimeError("OpenCode native session custody could not be verified") from None


def trusted_parent_executables(env):
    return [str(path) for path in _trusted_parent_executable_paths(env)]


def is_trusted_parent_executable(executable, env):
    try:
        observed = Path(executable).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    trusted = {_normal_path(path) for path in _trusted_parent_executable_paths(env)}
    return _normal_path(observed) in trusted


def _trusted_parent_executable_paths(env):
    trusted = []
    cli = resolve_installed_cli(env)
    if cli:
        trusted.append(cli)
    trusted.extend(_trusted_local_program_executables(env))
    return trusted


def resolve_installed_cli(env):
    prefix = _npm_global_prefix(env)
    if not prefix:
        return None
    candidate = prefix / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    try:
        root = prefix.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        package = candidate.parent.parent / "package.json"
        if (_path_stays_inside(resolved, root)
                and candidate.parent.name.lower() == "bin"
                and candidate.parent.parent.name.lower() == "opencode-ai"
                and candidate.parent.parent.parent.name.lower() == "node_modules"
                and resolved.name.lower() == "opencode.exe"
                and json.loads(package.read_text(encoding="utf-8")).get("name") == "opencode-ai"):
            return resolved
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        pass
    return None


_TRUSTED_LOCAL_PROGRAM_ROOT_NAMES = ("@opencode-aidesktop",)


def _trusted_local_program_executables(env):
    localappdata = env.get("LOCALAPPDATA", "")
    if not localappdata:
        return []
    programs = Path(localappdata) / "Programs"
    try:
        resolved_programs = programs.resolve(strict=True)
    except (OSError, RuntimeError):
        return []
    trusted = []
    seen = set()
    for root_name in _TRUSTED_LOCAL_PROGRAM_ROOT_NAMES:
        root = programs / root_name
        try:
            resolved_root = root.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not _path_stays_inside(resolved_root, resolved_programs):
            continue
        for name in ("OpenCode.exe", "opencode.exe"):
            candidate = root / name
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            key = _normal_path(resolved)
            if key not in seen and _path_stays_inside(resolved, resolved_root):
                trusted.append(resolved)
                seen.add(key)
    return trusted


def _npm_global_prefix(env):
    for config in _npm_config_files(env):
        prefix = _npm_prefix_from_config(config)
        if prefix:
            return prefix
    appdata = env.get("APPDATA", "")
    return Path(appdata) / "npm" if appdata else None


def _npm_config_files(env):
    files = []
    userprofile = env.get("USERPROFILE", "")
    appdata = env.get("APPDATA", "")
    if userprofile:
        files.append(Path(userprofile) / ".npmrc")
    if appdata:
        files.append(Path(appdata) / "npm" / "etc" / "npmrc")
    return files


def _npm_prefix_from_config(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")) or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip().lower() == "prefix" and value.strip():
            return Path(value.strip().strip('"'))
    return None


def _normal_path(path):
    return os.path.normcase(os.path.normpath(str(path)))


def _path_stays_inside(path, root):
    value = _normal_path(path)
    prefix = _normal_path(root).rstrip("\\/")
    return value == prefix or value.startswith(prefix + os.sep)


class OpenCodeProcessCustody:
    def __init__(self, session_id, *, environment=None, process_reader=observe, session_reader=verify_session):
        env = os.environ if environment is None else environment
        self._read = process_reader
        self._session = session_id
        self._self = process_reader(os.getpid())
        self._parent = process_reader(self._self.parent)
        if (not env.get("LOCALAPPDATA") or self._self.session_id != session_id
                or not is_trusted_parent_executable(self._parent.executable, env)):
            raise RuntimeError("OpenCode native worker requires its observed installed parent")
        session_reader(self._parent, session_id, self._self.cwd)
        self.check()

    def check(self):
        if self._read(self._self.pid) != self._self or self._read(self._parent.pid) != self._parent:
            raise RuntimeError("OpenCode native process custody changed")
