"""Court: every host exec bridge refuses callers without this install's secret.

Real HTTP, real bridge source files, real Windows Credential Locker reads. The
Python bridges (Rhino, Blender, 3ds Max) are loaded from the files the
installer ships, with only their host modules (bpy, Rhino, pymxs) replaced;
the .NET guard the Revit and AutoCAD add-ins link (BridgeAuth.cs) runs in a
harness behind a real HttpListener. The credential used is a throw-away
generic credential under a unique service name, deleted afterwards: the real
"ArchHub" entries of the person running the court are never read or written.
"""
from __future__ import annotations

import ctypes
import functools
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import types
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from http.server import HTTPServer, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodelang.clean_revit_adapter import _call as _REAL_REVIT_CALL  # noqa: E402 - before conftest's guard

HEADER = "X-ArchHub-Bridge-Token"
USER = "archhub-host-bridge"
BRIDGES = {
    "rhino": ROOT / "bridges" / "rhino" / "archhub_mcp.py",
    "blender": ROOT / "bridges" / "blender" / "archhub_mcp" / "__init__.py",
    "max": ROOT / "bridges" / "sources" / "max_mcp" / "max_mcp_startup.py",
}

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the bridges read the Windows Credential Locker")


# ------------------------------------------------ a keyring-shaped credential --

class _Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def _cred_write(target: str, user: str, secret: str) -> None:
    """What keyring's WinVaultKeyring writes: generic credential, UTF-16LE blob."""
    blob = secret.encode("utf-16-le")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _Credential(Type=1, TargetName=target, CredentialBlobSize=len(blob),
                       CredentialBlob=buffer, Persist=2, UserName=user)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredWriteW.argtypes = (ctypes.POINTER(_Credential), wintypes.DWORD)
    if not advapi.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), "CredWriteW failed")


def _cred_delete(target: str) -> None:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
    advapi.CredDeleteW(target, 1, 0)


@pytest.fixture
def credential():
    """A unique service holding a bridge secret, laid out as keyring lays it out."""
    service = "ArchHubCourt-" + uuid.uuid4().hex
    secret = uuid.uuid4().hex + uuid.uuid4().hex
    _cred_write(service, USER, secret)
    try:
        yield types.SimpleNamespace(service=service, secret=secret)
    finally:
        _cred_delete(service)
        _cred_delete(USER + "@" + service)


# ------------------------------------------------------- the shipped bridges --

def _fake_hosts(monkeypatch):
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(
        timers=types.SimpleNamespace(register=lambda fn, first_interval=0: fn()),
        version_string="court")
    bpy.context = types.SimpleNamespace(scene=None)
    bpy.data = types.SimpleNamespace(filepath="")
    monkeypatch.setitem(sys.modules, "bpy", bpy)

    class _Timer:
        def __init__(self, *a, **k):
            self.timeout = types.SimpleNamespace(connect=lambda fn: None)

        def setInterval(self, *_):
            pass

        def start(self):
            pass

        @staticmethod
        def singleShot(*_):
            pass

    qtcore = types.ModuleType("PySide2.QtCore")
    qtcore.QTimer = _Timer
    qtwidgets = types.ModuleType("PySide2.QtWidgets")
    qtwidgets.QApplication = types.SimpleNamespace(instance=lambda: None)
    pyside = types.ModuleType("PySide2")
    pyside.QtCore, pyside.QtWidgets = qtcore, qtwidgets
    for name, module in (("PySide2", pyside), ("PySide2.QtCore", qtcore), ("PySide2.QtWidgets", qtwidgets)):
        monkeypatch.setitem(sys.modules, name, module)
    pymxs = types.ModuleType("pymxs")
    pymxs.runtime = types.SimpleNamespace(execute=lambda script: eval(script, {}),  # noqa: S307 - court host
                                         UndoOn=lambda: _NullContext())
    monkeypatch.setitem(sys.modules, "pymxs", pymxs)
    monkeypatch.setenv("ARCHHUB_MAXMCP_AUTOSTART", "0")


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _load(name: str, monkeypatch):
    _fake_hosts(monkeypatch)
    spec = importlib.util.spec_from_file_location("court_bridge_" + name, BRIDGES[name])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Per bridge: handler class, identity route, exec route, body that runs `code`.
_ROUTES = {
    "rhino": ("_ArchHubRequestHandler", "/ping", "/execute", lambda code: {"code": code}),
    "blender": ("_ArchHubHandler", "/ping", "/execute", lambda code: {"code": code}),
    "max": ("_Handler", "/max-mcp/ping", "/max-mcp/exec", lambda code: {"code": code}),
}


@pytest.fixture(params=sorted(BRIDGES))
def bridge(request, monkeypatch, credential):
    name = request.param
    module = _load(name, monkeypatch)
    if name == "rhino":
        module.sc = types.SimpleNamespace(doc=None)
    # The shipped reader, pointed at the court's own credential service. A
    # bridge without the check has no reader; the courts below then show what
    # it does for an unauthenticated caller instead of failing in setup.
    if hasattr(module, "bridge_secret"):
        monkeypatch.setattr(module, "bridge_secret",
                            functools.partial(module.bridge_secret, service=credential.service))
    handler, ping, execute, body = _ROUTES[name]
    server = (ThreadingHTTPServer if name == "max" else HTTPServer)(("127.0.0.1", 0), getattr(module, handler))
    stop = threading.Event()
    threads = [threading.Thread(target=server.serve_forever, daemon=True)]
    if name == "max":
        def drain():
            while not stop.is_set():
                module._drain_queue()
                stop.wait(0.02)
        threads.append(threading.Thread(target=drain, daemon=True))
    for thread in threads:
        thread.start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        yield types.SimpleNamespace(name=name, module=module, base=base, ping=ping,
                                    execute=execute, body=body, credential=credential)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


def _request(url, *, body=None, headers=None, method=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), json.loads(refused.read() or b"{}")


def _marker_code(path: Path) -> str:
    return "open(%r, 'w').write('ran')\nresult = 42" % str(path)


def test_an_unauthenticated_post_is_refused_and_runs_nothing(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    status, _headers, answer = _request(bridge.base + bridge.execute, body=bridge.body(_marker_code(marker)))
    assert status == 401, (bridge.name, status, answer)
    assert answer["error"] == "caller is not authenticated"
    assert not marker.exists(), "%s ran code for an unauthenticated caller" % bridge.name


def test_a_wrong_secret_is_refused(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    status, _headers, _answer = _request(bridge.base + bridge.execute, body=bridge.body(_marker_code(marker)),
                                         headers={HEADER: "x" * len(bridge.credential.secret)})
    assert status == 401 and not marker.exists()


def test_a_browser_request_is_refused_even_with_the_secret(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    status, headers, _answer = _request(
        bridge.base + bridge.execute, body=bridge.body(_marker_code(marker)),
        headers={HEADER: bridge.credential.secret, "Origin": "https://evil.example"})
    assert status == 403 and not marker.exists()
    assert not any(key.lower().startswith("access-control-") for key in headers)


def test_a_preflight_gets_no_cors_grant(bridge):
    status, headers, _answer = _request(bridge.base + bridge.execute, method="OPTIONS",
                                        headers={"Origin": "https://evil.example",
                                                 "Access-Control-Request-Method": "POST"})
    assert status == 403
    assert not any(key.lower().startswith("access-control-") for key in headers)


def test_the_identity_route_answers_without_the_secret(bridge):
    status, _headers, _answer = _request(bridge.base + bridge.ping)
    assert status == 200


def test_the_authenticated_caller_runs_its_code(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    status, _headers, answer = _request(bridge.base + bridge.execute, body=bridge.body(_marker_code(marker)),
                                        headers={HEADER: bridge.credential.secret})
    assert status == 200, answer
    assert marker.read_text() == "ran"
    assert answer.get("result") == 42


def test_with_no_secret_provisioned_the_bridge_fails_closed(bridge, tmp_path):
    _cred_delete(bridge.credential.service)
    marker = tmp_path / "ran.txt"
    status, _headers, answer = _request(bridge.base + bridge.execute, body=bridge.body(_marker_code(marker)),
                                        headers={HEADER: bridge.credential.secret})
    assert status == 503 and "not provisioned" in answer["error"] and not marker.exists()


def test_the_reader_follows_keyring_when_the_entry_moved_to_its_compound_name(monkeypatch, credential):
    """keyring moves an older entry to user@service when another user saves under the service."""
    module = _load("rhino", monkeypatch)
    _cred_delete(credential.service)
    _cred_write(credential.service, "some-other-provider", "not-the-bridge-secret-" + "y" * 20)
    _cred_write(USER + "@" + credential.service, USER, credential.secret)
    assert module.bridge_secret(service=credential.service) == credential.secret


# ------------------------------------------------- the app's side of the call --

def test_the_app_engine_sends_the_secret_and_its_call_works(monkeypatch, credential, tmp_path):
    from nodelang import host_bridge_auth, host_brokers
    module = _load("rhino", monkeypatch)
    module.sc = types.SimpleNamespace(doc=None)
    monkeypatch.setattr(module, "bridge_secret",
                        functools.partial(module.bridge_secret, service=credential.service))
    server = HTTPServer(("127.0.0.1", 0), module._ArchHubRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(host_brokers, "RHINO_URL", "http://127.0.0.1:%d" % server.server_address[1])
        monkeypatch.setattr(host_brokers, "_port_open", lambda port, timeout=0.15: True)
        marker = tmp_path / "ran.txt"
        # The installed app reads the same secret from its credential store.
        monkeypatch.setattr(host_bridge_auth, "ensure_secret", lambda: credential.secret)
        out, said = host_brokers.rhino_exec({"code": _marker_code(marker)}, {})
        assert said == "ran in Rhino" and out["out"]["result"] == 42 and marker.exists()
        marker.unlink()
        # A store that cannot answer: no header, and the refusal is reported, not hidden.
        monkeypatch.setattr(host_bridge_auth, "ensure_secret", lambda: (_ for _ in ()).throw(OSError("store")))
        out, said = host_brokers.rhino_exec({"code": _marker_code(marker)}, {})
        assert out["ok"] is False and "HTTP 401" in said and not marker.exists()
    finally:
        server.shutdown()
        server.server_close()


def test_the_revit_adapter_sends_the_secret_and_reads_a_refusal_as_an_error(monkeypatch, credential):
    from nodelang import clean_revit_adapter, host_bridge_auth
    module = _load("blender", monkeypatch)
    monkeypatch.setattr(module, "bridge_secret",
                        functools.partial(module.bridge_secret, service=credential.service))
    server = HTTPServer(("127.0.0.1", 0), module._ArchHubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        # This court's own bridge on its own port, never a live host.
        monkeypatch.setattr(clean_revit_adapter, "_call", _REAL_REVIT_CALL)
        monkeypatch.setattr(host_bridge_auth, "ensure_secret", lambda: credential.secret)
        assert clean_revit_adapter._call(port, "/exec", {"code": "result = 7"})["result"] == 7
        monkeypatch.setattr(host_bridge_auth, "ensure_secret", lambda: "z" * 43)
        refused = clean_revit_adapter._call(port, "/exec", {"code": "result = 7"})
        assert refused["status"] == "error" and refused["http_status"] == 401
    finally:
        server.shutdown()
        server.server_close()


def test_the_secret_is_created_once_kept_in_the_store_and_never_sent_off_machine(monkeypatch):
    from nodelang import host_bridge_auth
    saved = {}
    store = types.SimpleNamespace(load_api_key=saved.get,
                                  save_api_key=lambda name, value: saved.__setitem__(name, value))
    monkeypatch.setattr(host_bridge_auth, "_store", lambda: store)
    first = host_bridge_auth.ensure_secret()
    assert len(first) >= 32 and saved == {"archhub-host-bridge": first}
    assert host_bridge_auth.ensure_secret() == first
    assert host_bridge_auth.bridge_headers("http://127.0.0.1:9879/execute") == {HEADER: first}
    assert host_bridge_auth.bridge_headers("https://api.notion.com/v1/search") == {}
    lying = types.SimpleNamespace(load_api_key=lambda name: None, save_api_key=lambda name, value: None)
    monkeypatch.setattr(host_bridge_auth, "_store", lambda: lying)
    with pytest.raises(host_bridge_auth.BridgeSecretUnavailable):
        host_bridge_auth.ensure_secret()


# ------------------------------------------- the .NET guard (Revit, AutoCAD) --

def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def harness_exe(tmp_path_factory):
    dotnet = shutil.which("dotnet")
    if not dotnet:
        pytest.skip("the .NET SDK is needed to build the BridgeAuth harness")
    source = tmp_path_factory.mktemp("harness-src")
    shutil.copytree(ROOT / "tests_replica" / "bridge_auth_harness", source / "tests_replica" / "bridge_auth_harness")
    (source / "bridges" / "sources" / "shared").mkdir(parents=True)
    shutil.copy2(ROOT / "bridges" / "sources" / "shared" / "BridgeAuth.cs", source / "bridges" / "sources" / "shared")
    out = tmp_path_factory.mktemp("harness-out")
    built = subprocess.run([dotnet, "build", str(source / "tests_replica" / "bridge_auth_harness"),
                            "-c", "Release", "-nologo", "-v", "q", "-o", str(out)],
                           capture_output=True, text=True, timeout=600)
    assert built.returncode == 0, built.stdout[-2000:]
    return out / "BridgeAuthHarness.exe"


def test_the_dotnet_guard_the_revit_and_autocad_add_ins_link(harness_exe, credential, tmp_path):
    port = _free_port()
    process = subprocess.Popen([str(harness_exe), str(port), credential.service, USER],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "READY"
        base = "http://localhost:%d" % port
        body = {"code": "noop"}
        assert _request(base + "/ping")[0] == 200
        assert _request(base + "/exec", body=body)[0] == 401
        assert _request(base + "/exec", body=body, headers={HEADER: "q" * 64})[0] == 401
        status, headers, _ = _request(base + "/exec", body=body,
                                      headers={HEADER: credential.secret, "Origin": "https://evil.example"})
        assert status == 403 and not any(k.lower().startswith("access-control-") for k in headers)
        assert _request(base + "/exec", method="OPTIONS", headers={"Origin": "https://evil.example"})[0] == 403
        status, _headers, answer = _request(base + "/exec", body=body, headers={HEADER: credential.secret})
        assert status == 200 and answer == {"status": "ok", "result": "ran"}
        _cred_delete(credential.service)
        assert _request(base + "/exec", body=body, headers={HEADER: credential.secret})[0] == 503
    finally:
        process.stdin.close()
        process.wait(timeout=10)


def test_every_dotnet_route_passes_the_guard_before_it_runs():
    core = (ROOT / "bridges/sources/revit_mcp_core/RevitMCPCore.cs").read_text(encoding="utf-8")
    acad = (ROOT / "bridges/sources/acad_mcp/AcadMCPApp.cs").read_text(encoding="utf-8")
    for text, handler in ((core, "private async Task HandleAsync("), (acad, "private async Task ProcessRequestAsync(")):
        body = text[text.index(handler):]
        body = body[:body.index("\n        }\n")]
        assert body.index("BridgeAuth.Refuse(") < body.index("RouteAsync("), handler
        assert "Access-Control" not in text
    for project, marker in (("revit_mcp_core/RevitMCPCore.csproj", "BridgeAuth.cs"),
                            ("acad_mcp/AcadMCP.csproj", "BridgeAuth.cs")):
        assert marker in (ROOT / "bridges/sources" / project).read_text(encoding="utf-8")


def test_the_python_bridges_carry_one_identical_guard_and_no_cors():
    blocks = set()
    for path in BRIDGES.values():
        text = path.read_text(encoding="utf-8")
        start = text.index("# --- BEGIN ArchHub bridge caller check")
        end = text.index("# --- END ArchHub bridge caller check ---")
        blocks.add(text[start:end])
        assert "Access-Control-Allow" not in text, path
    assert len(blocks) == 1
