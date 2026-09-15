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


class OpenCodeProcessCustody:
    def __init__(self, session_id, *, environment=None, process_reader=observe, session_reader=verify_session):
        env = os.environ if environment is None else environment
        self._read = process_reader
        self._session = session_id
        self._self = process_reader(os.getpid())
        self._parent = process_reader(self._self.parent)
        expected = Path(env.get("LOCALAPPDATA", "")) / "Programs" / "@opencode-aidesktop" / "OpenCode.exe"
        if (not env.get("LOCALAPPDATA") or self._self.session_id != session_id
                or os.path.normcase(self._parent.executable) != os.path.normcase(str(expected.resolve()))):
            raise RuntimeError("OpenCode native worker requires its observed installed parent")
        session_reader(self._parent, session_id, self._self.cwd)
        self.check()

    def check(self):
        if self._read(self._self.pid) != self._self or self._read(self._parent.pid) != self._parent:
            raise RuntimeError("OpenCode native process custody changed")
