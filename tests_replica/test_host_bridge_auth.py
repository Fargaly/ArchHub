"""Court: every host exec bridge runs code only for a fresh request signed with this install's secret.

Real HTTP, real bridge source files, real Windows Credential Locker reads,
and the app's one authenticated client (nodelang/host_bridge_auth.py). The
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
import time
import types
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodelang import host_bridge_auth as auth  # noqa: E402
from nodelang.clean_revit_adapter import _call as _REAL_REVIT_CALL  # noqa: E402 - before conftest's guard

USER = "archhub-host-bridge"
SIGNATURE_HEADERS = (auth.TIME_HEADER, auth.NONCE_HEADER, auth.SIGNATURE_HEADER)
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

class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


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


def _load(name: str, monkeypatch):
    _fake_hosts(monkeypatch)
    spec = importlib.util.spec_from_file_location("court_bridge_" + name, BRIDGES[name])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Per bridge: handler class, identity route, exec route.
_ROUTES = {
    "rhino": ("_ArchHubRequestHandler", "/ping", "/execute"),
    "blender": ("_ArchHubHandler", "/ping", "/execute"),
    "max": ("_Handler", "/max-mcp/ping", "/max-mcp/exec"),
}


def _serve(name, module):
    handler = _ROUTES[name][0]
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

    def close():
        stop.set()
        server.shutdown()
        server.server_close()
    return server.server_address[1], close


@pytest.fixture(params=sorted(BRIDGES))
def bridge(request, monkeypatch, credential):
    name = request.param
    module = _load(name, monkeypatch)
    if name == "rhino":
        module.sc = types.SimpleNamespace(doc=None)
    # The shipped reader, pointed at the court's own credential service. A
    # bridge without the check has no reader; the courts below then show what
    # it does for an unsigned caller instead of failing in setup.
    if hasattr(module, "bridge_secret"):
        monkeypatch.setattr(module, "bridge_secret",
                            functools.partial(module.bridge_secret, service=credential.service))
    port, close = _serve(name, module)
    _handler, ping, execute = _ROUTES[name]
    try:
        yield types.SimpleNamespace(name=name, module=module, base="http://127.0.0.1:%d" % port,
                                    ping=ping, execute=execute, credential=credential)
    finally:
        close()


def _raw(url, *, data=None, headers=None, method=None):
    """A plain HTTP exchange, as any local process could make it."""
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"))
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    def parsed(raw):
        # http.sys answers some refusals itself with an HTML page (e.g. a bad Host).
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {"raw": raw.decode("utf-8", "replace")}
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), parsed(response.read())
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), parsed(refused.read())


def _code(marker: Path) -> bytes:
    return json.dumps({"code": "open(%r, 'a').write('ran')\nresult = 42" % str(marker)}).encode("utf-8")


def _signed(url, body: bytes, secret: str, **kwargs):
    headers = {"Content-Type": "application/json"}
    headers.update(auth.signed_headers("POST", url, body, secret=secret, **kwargs))
    return headers


def test_an_unsigned_post_is_refused_and_runs_nothing(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    status, _h, answer = _raw(bridge.base + bridge.execute, data=_code(marker),
                              headers={"Content-Type": "application/json"})
    assert status == 401, (bridge.name, status, answer)
    assert answer["error"] == "caller is not authenticated"
    assert not marker.exists(), "%s ran code for an unsigned caller" % bridge.name


def test_the_signed_caller_runs_its_code_once(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    url, body = bridge.base + bridge.execute, _code(marker)
    headers = _signed(url, body, bridge.credential.secret)
    status, _h, answer = _raw(url, data=body, headers=headers)
    assert status == 200, answer
    assert answer.get("result") == 42 and marker.read_text() == "ran"
    # The same signed request again is a replay: refused, nothing runs twice.
    status, _h, answer = _raw(url, data=body, headers=headers)
    assert status == 401 and answer["error"] == "signature was already used"
    assert marker.read_text() == "ran"


def test_a_signature_by_another_key_is_refused(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    url, body = bridge.base + bridge.execute, _code(marker)
    status, _h, _a = _raw(url, data=body, headers=_signed(url, body, "k" * 43))
    assert status == 401 and not marker.exists()


def test_a_signature_does_not_carry_over_to_another_body(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    url = bridge.base + bridge.execute
    headers = _signed(url, json.dumps({"code": "result = 1"}).encode(), bridge.credential.secret)
    status, _h, _a = _raw(url, data=_code(marker), headers=headers)
    assert status == 401 and not marker.exists()


def test_a_stale_signature_is_refused(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    url, body = bridge.base + bridge.execute, _code(marker)
    headers = _signed(url, body, bridge.credential.secret, now=time.time() - 3 * auth.SKEW_SECONDS)
    status, _h, answer = _raw(url, data=body, headers=headers)
    assert status == 401 and answer["error"] == "signature time is outside the allowed window"
    assert not marker.exists()


def test_a_browser_request_is_refused_even_when_signed(bridge, tmp_path):
    marker = tmp_path / "ran.txt"
    url, body = bridge.base + bridge.execute, _code(marker)
    headers = dict(_signed(url, body, bridge.credential.secret), Origin="https://evil.example")
    status, response_headers, _a = _raw(url, data=body, headers=headers)
    assert status == 403 and not marker.exists()
    assert not any(key.lower().startswith("access-control-") for key in response_headers)


def test_a_preflight_gets_no_cors_grant(bridge):
    status, headers, _a = _raw(bridge.base + bridge.execute, method="OPTIONS",
                               headers={"Origin": "https://evil.example",
                                        "Access-Control-Request-Method": "POST"})
    assert status == 403
    assert not any(key.lower().startswith("access-control-") for key in headers)


def test_a_non_loopback_host_name_is_refused_even_when_signed(bridge, tmp_path):
    """DNS rebinding: a page's own host name reaching 127.0.0.1 is not served."""
    marker = tmp_path / "ran.txt"
    url, body = bridge.base + bridge.execute, _code(marker)
    headers = dict(_signed(url, body, bridge.credential.secret), Host="evil.example:80")
    status, _h, answer = _raw(url, data=body, headers=headers)
    assert status == 403 and "loopback" in answer["error"] and not marker.exists()
    assert _raw(bridge.base + bridge.ping, headers={"Host": "evil.example"})[0] == 403


def test_the_identity_route_answers_without_a_signature(bridge):
    status, _h, answer = _raw(bridge.base + bridge.ping)
    assert status == 200
    assert not any(isinstance(v, str) and ("\\" in v or "/Users/" in v) for v in answer.values())


def test_with_no_secret_provisioned_the_bridge_fails_closed(bridge, tmp_path):
    _cred_delete(bridge.credential.service)
    marker = tmp_path / "ran.txt"
    url, body = bridge.base + bridge.execute, _code(marker)
    status, _h, answer = _raw(url, data=body, headers=_signed(url, body, bridge.credential.secret))
    assert status == 503 and "not provisioned" in answer["error"] and not marker.exists()


def test_the_reader_follows_keyring_when_the_entry_moved_to_its_compound_name(monkeypatch, credential):
    """keyring moves an older entry to user@service when another user saves under the service."""
    module = _load("rhino", monkeypatch)
    _cred_delete(credential.service)
    _cred_write(credential.service, "some-other-provider", "not-the-bridge-secret-" + "y" * 20)
    _cred_write(USER + "@" + credential.service, USER, credential.secret)
    assert module.bridge_secret(service=credential.service) == credential.secret


# ------------------------------------------------- the app's side of the call --

def _rhino_bridge(monkeypatch, credential):
    module = _load("rhino", monkeypatch)
    module.sc = types.SimpleNamespace(doc=None)
    monkeypatch.setattr(module, "bridge_secret",
                        functools.partial(module.bridge_secret, service=credential.service))
    return _serve("rhino", module)


def test_the_app_engine_signs_and_its_call_works(monkeypatch, credential, tmp_path):
    from nodelang import host_brokers
    port, close = _rhino_bridge(monkeypatch, credential)
    try:
        monkeypatch.setattr(host_brokers, "RHINO_URL", "http://127.0.0.1:%d" % port)
        monkeypatch.setattr(host_brokers, "_port_open", lambda port, timeout=0.15: True)
        marker = tmp_path / "ran.txt"
        code = "open(%r, 'a').write('ran')\nresult = 42" % str(marker)
        monkeypatch.setattr(auth, "ensure_secret", lambda: credential.secret)
        out, said = host_brokers.rhino_exec({"code": code}, {})
        assert said == "ran in Rhino" and out["out"]["result"] == 42 and marker.read_text() == "ran"
        # A store that cannot answer: unsigned, refused, and said -- not hidden.
        monkeypatch.setattr(auth, "ensure_secret", lambda: (_ for _ in ()).throw(OSError("store")))
        out, said = host_brokers.rhino_exec({"code": code}, {})
        assert out["ok"] is False and "HTTP 401" in said and marker.read_text() == "ran"
    finally:
        close()


def test_a_squatting_listener_learns_no_secret(monkeypatch, credential, tmp_path):
    """Whatever answers on a bridge port gets one MAC bound to one body, never the key."""
    from nodelang import host_brokers
    captured = []

    class Squatter(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            captured.append((dict(self.headers), body))
            payload = b'{"status": "ok", "result": 0}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    squat = HTTPServer(("127.0.0.1", 0), Squatter)
    threading.Thread(target=squat.serve_forever, daemon=True).start()
    port, close = _rhino_bridge(monkeypatch, credential)
    try:
        monkeypatch.setattr(auth, "ensure_secret", lambda: credential.secret)
        host_brokers._bridge_call("http://127.0.0.1:%d/execute" % squat.server_address[1], {"code": "result = 1"})
        headers, _body = captured[0]
        assert credential.secret not in json.dumps(headers) and credential.secret.encode() not in _body
        # The captured signature cannot carry different code into the real bridge.
        marker = tmp_path / "ran.txt"
        status, _h, _a = _raw("http://127.0.0.1:%d/execute" % port, data=_code(marker),
                              headers={k: v for k, v in headers.items() if k.startswith("X-ArchHub")
                                       or k == "Content-Type"})
        assert status == 401 and not marker.exists()
    finally:
        close()
        squat.shutdown()
        squat.server_close()


def test_the_revit_adapter_signs_and_reads_a_refusal_as_an_error(monkeypatch, credential):
    from nodelang import clean_revit_adapter
    module = _load("blender", monkeypatch)
    monkeypatch.setattr(module, "bridge_secret",
                        functools.partial(module.bridge_secret, service=credential.service))
    port, close = _serve("blender", module)
    try:
        # This court's own bridge on its own port, never a live host.
        monkeypatch.setattr(clean_revit_adapter, "_call", _REAL_REVIT_CALL)
        monkeypatch.setattr(auth, "ensure_secret", lambda: credential.secret)
        assert clean_revit_adapter._call(port, "/exec", {"code": "result = 7"})["result"] == 7
        monkeypatch.setattr(auth, "ensure_secret", lambda: "z" * 43)
        refused = clean_revit_adapter._call(port, "/exec", {"code": "result = 7"})
        assert refused["status"] == "error" and refused["http_status"] == 401
    finally:
        close()


def test_the_host_graph_node_signs_through_the_same_client(monkeypatch, credential):
    """nodelang/core.py op 'host' (_run_host): a signed call works; a refusal is a host_error, not unreachable."""
    from nodelang import core
    # MaxMCP answers the node's POST /exec with the {"status": "ok"} shape it reads.
    module = _load("max", monkeypatch)
    monkeypatch.setattr(module, "bridge_secret",
                        functools.partial(module.bridge_secret, service=credential.service))
    port, close = _serve("max", module)
    try:
        monkeypatch.setattr(auth, "ensure_secret", lambda: credential.secret)
        assert core._run_host(port, "result = 6 * 7") == 42
        monkeypatch.setattr(auth, "ensure_secret", lambda: "w" * 43)
        refused = core._run_host(port, "result = 1")
        assert refused["http_status"] == 401 and "host_unreachable" not in refused
    finally:
        close()


def test_the_client_refuses_to_call_anything_but_loopback(monkeypatch):
    monkeypatch.setattr(auth, "ensure_secret", lambda: "s" * 43)
    with pytest.raises(ValueError):
        auth.bridge_request("https://api.notion.com/v1/search", {"query": "x"})
    headers = auth.signed_headers("POST", "http://127.0.0.1:9879/execute", b"{}", secret="s" * 43)
    assert set(headers) == set(SIGNATURE_HEADERS) and "s" * 43 not in json.dumps(headers)


def test_the_secret_is_created_once_and_kept_in_the_store(monkeypatch):
    saved = {}
    store = types.SimpleNamespace(load_api_key=saved.get,
                                  save_api_key=lambda name, value: saved.__setitem__(name, value))
    monkeypatch.setattr(auth, "_store", lambda: store)
    first = auth.ensure_secret()
    assert len(first) >= 32 and saved == {"archhub-host-bridge": first}
    assert auth.ensure_secret() == first
    lying = types.SimpleNamespace(load_api_key=lambda name: None, save_api_key=lambda name, value: None)
    monkeypatch.setattr(auth, "_store", lambda: lying)
    with pytest.raises(auth.BridgeSecretUnavailable):
        auth.ensure_secret()


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


def test_the_dotnet_guard_the_revit_and_autocad_add_ins_link(harness_exe, credential):
    port = _free_port()
    process = subprocess.Popen([str(harness_exe), str(port), credential.service, USER],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "READY"
        url = "http://localhost:%d/exec" % port
        body = b'{"code":"noop"}'
        json_type = {"Content-Type": "application/json"}
        assert _raw("http://localhost:%d/ping" % port)[0] == 200
        assert _raw(url, data=body, headers=json_type)[0] == 401
        assert _raw(url, data=body, headers=dict(json_type, **_signed(url, body, "q" * 43)))[0] == 401
        signed = dict(json_type, **_signed(url, body, credential.secret))
        status, headers, _ = _raw(url, data=body, headers=dict(signed, Origin="https://evil.example"))
        assert status == 403 and not any(k.lower().startswith("access-control-") for k in headers)
        assert _raw(url, method="OPTIONS", headers={"Origin": "https://evil.example"})[0] == 403
        stale = dict(json_type, **_signed(url, body, credential.secret, now=time.time() - 300))
        assert _raw(url, data=body, headers=stale)[0] == 401
        other_body = dict(json_type, **_signed(url, b'{"code":"other"}', credential.secret))
        assert _raw(url, data=body, headers=other_body)[0] == 401
        signed = dict(json_type, **_signed(url, body, credential.secret))
        status, _headers, answer = _raw(url, data=body, headers=signed)
        assert status == 200 and answer == {"status": "ok", "result": "ran"}
        status, _headers, answer = _raw(url, data=body, headers=signed)
        assert status == 401 and answer["error"] == "signature was already used"
        assert _raw(url, data=body, headers=dict(json_type, **_signed(url, body, credential.secret),
                                                 Host="evil.example"))[0] in (400, 403)
        _cred_delete(credential.service)
        fresh = dict(json_type, **_signed(url, body, credential.secret))
        assert _raw(url, data=body, headers=fresh)[0] == 503
    finally:
        process.stdin.close()
        process.wait(timeout=10)


def test_the_host_graph_node_reaches_a_listener_registered_on_localhost(harness_exe, credential, monkeypatch):
    """nodelang/core.py _run_host against the one prefix the Revit and AutoCAD add-ins register.

    RevitMCPCore.cs and AcadMCPApp.cs add only http://localhost:<port>/ to their
    HttpListener; http.sys answers a request whose Host is 127.0.0.1:<port> with 400
    before the add-in (or BridgeAuth) ever sees it.
    """
    from nodelang import core
    port = _free_port()
    process = subprocess.Popen([str(harness_exe), str(port), credential.service, USER],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "READY"
        monkeypatch.setattr(auth, "ensure_secret", lambda: credential.secret)
        assert core._run_host(port, "noop") == "ran"
        # The address the node used to post to never reaches the add-in.
        assert _raw("http://127.0.0.1:%d/ping" % port)[0] == 400
    finally:
        process.stdin.close()
        process.wait(timeout=10)


def test_every_dotnet_route_passes_the_guard_before_it_runs():
    core = (ROOT / "bridges/sources/revit_mcp_core/RevitMCPCore.cs").read_text(encoding="utf-8")
    acad = (ROOT / "bridges/sources/acad_mcp/AcadMCPApp.cs").read_text(encoding="utf-8")
    for text, handler in ((core, "private async Task HandleAsync("), (acad, "private async Task ProcessRequestAsync(")):
        body = text[text.index(handler):]
        body = body[:body.index("\n        }\n")]
        assert body.index("BridgeAuth.ReadBody(") < body.index("BridgeAuth.Refuse(") < body.index("RouteAsync(")
        assert "Access-Control" not in text
        # /ping names the service; it never reveals a path on this machine.
        assert "csc_path" not in text
    for project in ("revit_mcp_core/RevitMCPCore.csproj", "acad_mcp/AcadMCP.csproj"):
        assert "BridgeAuth.cs" in (ROOT / "bridges/sources" / project).read_text(encoding="utf-8")


def test_the_python_bridges_carry_one_identical_guard_and_no_cors():
    blocks = set()
    for path in BRIDGES.values():
        text = path.read_text(encoding="utf-8")
        start = text.index("# --- BEGIN ArchHub bridge caller check")
        end = text.index("# --- END ArchHub bridge caller check ---")
        blocks.add(text[start:end])
        assert "Access-Control-Allow" not in text, path
    assert len(blocks) == 1
