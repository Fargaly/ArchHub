"""Goose boundary courts; all providers, processes and host state are fake."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import subprocess
import sys
import time
import pytest

from nodelang.goose_adapter import GooseAdapter, GooseRefused, free_route


def test_only_free_and_local_models_are_admitted():
    assert free_route("openrouter/free") == ("openrouter", "openrouter/free")
    assert free_route("openrouter/vendor/model:free") == ("openrouter", "vendor/model:free")
    assert free_route("ollama/qwen3:8b") == ("ollama", "qwen3:8b")
    for route in ("anthropic/sonnet", "openrouter/vendor/paid", "vendor/model:free", "", "ollama/"):
        with pytest.raises(GooseRefused):
            free_route(route)


def test_ask_refuses_without_managed_runtime():
    adapter = GooseAdapter(None)
    with pytest.raises(GooseRefused, match="not available"):
        adapter.ask("hello", "", "openrouter/free")


def test_read_only_host_extension_reuses_existing_tool():
    from contextlib import contextmanager
    from nodelang.native_host_tools import register_host_tools
    calls, tools = [], {}

    class Server:
        def tool(self, *, name):
            def register(fn):
                tools[name] = fn
                return fn
            return register

    @contextmanager
    def bound_client():
        yield SimpleNamespace(request=lambda *args: calls.append(args) or {"hosts": [{"host": "Rhino"}]})

    register_host_tools(Server(), SimpleNamespace(bound_client=bound_client), read_only=True)
    assert set(tools) == {"hosts_state"}
    assert tools["hosts_state"]() == {"hosts": [{"host": "Rhino"}]}
    assert calls == [("GET", "/api/universal/hosts", {})]


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import nodelang.model_router as router
    from nodelang.goose_runtime import GooseRuntime
    monkeypatch.setattr(router, "discover_key", lambda *_: ("", "fake"))
    package = tmp_path / "runtime" / "goose"
    package.mkdir(parents=True)
    binary = package / "goose.exe"
    binary.write_bytes(b"court-only executable marker")
    (package / "manifest.json").write_text(json.dumps({"version": "1.54.0",
        "executable_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "archive_sha256": "5c39bc91c3eadc231847e21a8a469e778431084437b233a63a950fee22db6239"}))
    calls, launches = [], []
    @contextmanager
    def bound_client():
        def request(*args):
            calls.append(args)
            return {"ok": True, "hosts": [{"host": "Rhino", "document": "court-fixture.3dm"}]}
        yield SimpleNamespace(request=request)
    control = SimpleNamespace(bound_client=bound_client)
    mode = ["read"]
    def spawn(command, **kwargs):
        launches.append((command, kwargs["env"]))
        assert command == [str(binary), "acp"]
        return subprocess.Popen([sys.executable, str(Path(__file__).with_name("fixtures") / "goose_acp_fake.py"), mode[0]], **kwargs)
    runtime = GooseRuntime(app_root=tmp_path, state_dir=tmp_path / "state", control=control, process_factory=spawn)
    yield SimpleNamespace(runtime=runtime, calls=calls, launches=launches, mode=mode, root=tmp_path, control=control)
    runtime.close()


def test_fake_goose_reads_actual_mcp_tool_and_returns_host_result(packaged):
    from nodelang.native_agentic_loop import observe_steps
    packaged.runtime.start()
    progress = []
    with observe_steps(progress.append):
        result = GooseAdapter(packaged.runtime).ask("What hosts are open?", "authorised context", "openrouter/free")
    assert "court-fixture.3dm" in result["text"]
    assert result["steps"][0]["tool"] == "hosts_state"
    assert result["steps"][0]["status"] == "ok"
    assert packaged.calls == [("GET", "/api/universal/hosts", {})]
    assert len(packaged.launches) == 1
    assert [row["status"] for row in progress] == ["running", "ok"]
    assert all(set(row) == {"tool", "status", "summary"} for row in progress)
    assert all(type(v) is str and len(v) <= 4000 for row in progress for v in row.values())


def test_fresh_install_launcher_starts_goose_and_companion_then_answers_within_20s(packaged, monkeypatch):
    """Run real launcher attachment callback; fake signed host/GUI, real ACP/MCP."""
    import threading
    from nodelang import baboom_attach, baboom_native_runtime, goose_runtime
    from tests_replica.test_baboom_startup_lifecycle import launcher_names
    host = packaged.control
    host.connect = lambda: None
    host.stop = lambda **_: None
    server = SimpleNamespace()
    displayed = []
    attachment = SimpleNamespace(pending_host=None, prepared_atlas=None,
                                 ready=SimpleNamespace(emit=lambda value: displayed.append(value)))
    monkeypatch.setattr(baboom_attach, "prepare_baboom_host", lambda *_, **__: host)
    monkeypatch.setattr(baboom_native_runtime, "prepare_baboom_native_atlas", lambda: object())
    monkeypatch.setattr(goose_runtime, "GooseRuntime", lambda **_: packaged.runtime)
    ns = launcher_names("_keep_attaching", server=server, state_dir=packaged.root / "state",
        descriptor_path=packaged.root / "fake-descriptor", machine_key_provider=object(),
        _baboom_stop=threading.Event(), _baboom_attachment=attachment, _baboom_startup_choice=lambda: "on",
        Path=Path, __file__=str(Path(__file__).resolve().parents[1] / "nodelang/launcher.py"))
    began = time.monotonic()
    ns["_keep_attaching"]()
    assert displayed == [host] and attachment.prepared_atlas is not None
    assert server.goose_runtime is packaged.runtime
    result = server.goose_brain.ask("What is open?", "", "openrouter/free")
    elapsed = time.monotonic() - began
    assert elapsed < 20
    assert "court-fixture.3dm" in result["text"]
    print(f"fresh-install fake Goose + companion -> host answer: {elapsed:.3f} s < 20 s")


def test_permission_request_is_cancelled_with_zero_host_writes(packaged):
    packaged.mode[0] = "permission"
    packaged.runtime.start()
    with pytest.raises(GooseRefused, match="No action was approved"):
        GooseAdapter(packaged.runtime).ask("write", "", "openrouter/free")
    assert packaged.calls == []
    assert packaged.runtime.transport.process.poll() is None


def test_permission_cannot_spoof_safe_read_using_title(packaged):
    packaged.mode[0] = "spoof"
    packaged.runtime.start()
    with pytest.raises(GooseRefused, match="No action was approved"):
        GooseAdapter(packaged.runtime).ask("write", "", "openrouter/free")
    assert packaged.calls == []


def test_provider_error_is_visible_without_secrets_or_fallback(packaged):
    packaged.mode[0] = "error"
    packaged.runtime.start()
    with pytest.raises(GooseRefused, match="Goose could not complete") as error:
        GooseAdapter(packaged.runtime).ask("hello", "", "openrouter/free")
    assert "secret" not in str(error.value)
    assert packaged.calls == [] and len(packaged.launches) == 1
    assert packaged.runtime.transport.process.poll() is None


def test_local_ollama_route_uses_same_adapter_and_read_boundary(packaged):
    packaged.runtime.start()
    answer = GooseAdapter(packaged.runtime).ask("hosts", "", "ollama/qwen3:8b")
    assert answer["via"]["family"] == "ollama"
    assert answer["via"]["model"] == "qwen3:8b"
    assert len(packaged.calls) == 1


def test_missing_or_changed_packaged_binary_never_spawns(packaged):
    (packaged.root / "runtime/goose/goose.exe").write_bytes(b"tampered")
    with pytest.raises(GooseRefused, match="different digest"):
        packaged.runtime.start()
    assert packaged.launches == []
    assert packaged.runtime.http is None


def test_runtime_does_not_inherit_agent_identity_paid_route_or_provider_override(packaged, monkeypatch):
    for key in ("GOOSE_PROVIDER", "GOOSE_MODEL", "ANTHROPIC_API_KEY", "OPENAI_HOST", "CODEX_THREAD_ID"):
        monkeypatch.setenv(key, "unwanted")
    packaged.runtime.start()
    env = packaged.launches[0][1]
    assert env["GOOSE_MODEL"] == "openrouter/free"
    assert env["GOOSE_PROVIDER"] == "openrouter"
    assert env["GOOSE_PATH_ROOT"] == str(packaged.runtime.work_dir)
    assert not {"CODEX_THREAD_ID", "ANTHROPIC_API_KEY", "OPENAI_HOST"} & env.keys()


def test_private_mcp_requires_its_bearer_token(packaged):
    import urllib.request
    import urllib.error
    packaged.runtime.start()
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(packaged.runtime.host_extension["url"], timeout=3)
    assert error.value.code == 401
    assert packaged.calls == []


def test_timeout_closes_owned_child_without_retry(tmp_path):
    from nodelang.goose_adapter import AcpTransport
    process = subprocess.Popen([sys.executable, "-c", "import sys,time; sys.stdin.buffer.readline(); time.sleep(30)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    transport = AcpTransport(process)
    try:
        with pytest.raises(GooseRefused, match="within 20 s"):
            transport.request("initialize", {}, deadline=time.monotonic() + .05)
    finally:
        transport.close()
    assert process.poll() is not None and not transport.reader.is_alive()


def test_stopped_ask_dispatches_no_session_or_read(packaged):
    packaged.runtime.start()
    with pytest.raises(GooseRefused, match="Stopped by you"):
        GooseAdapter(packaged.runtime).ask("go", "", "openrouter/free", is_halted=lambda: True)
    assert packaged.calls == []


def test_stage_rejects_wrong_archive_hash_before_creating_output(tmp_path):
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "packaging/windows/stage_goose.py"
    spec = importlib.util.spec_from_file_location("stage_goose", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = tmp_path / "wrong.zip"
    archive.write_bytes(b"not the pinned release")
    with pytest.raises(ValueError, match="SHA-256"):
        module.stage_goose(archive, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_signed_host_read_does_not_wait_on_the_outer_ask_lock(monkeypatch):
    """The existing signed ask owns this lock while Goose asks for host state."""
    import threading
    from nodelang.application_machine_transport import UniversalRuntimeClient, MachineTransportError
    client = UniversalRuntimeClient(Path("unused"), object())
    client.agent_session_root = "session:court"
    client._agent_session_token = "court-only"
    client._agent_session_access = "full"
    client._agent_session_expires_at = time.time() + 120
    calls, replies = [], []
    monkeypatch.setattr(client, "_request_once", lambda *args, **kwargs: calls.append((args, kwargs)) or {"hosts": []})
    with client._request_lock:
        worker = threading.Thread(target=lambda: replies.append(client.read_hosts_state()), daemon=True)
        worker.start()
        worker.join(1)
        assert not worker.is_alive(), "host read deadlocked against its own parent ask"
    assert replies == [{"hosts": []}]
    assert calls == [(("GET", "/api/universal/hosts", {}), {"response_timeout_seconds": 5.0})]
    client._agent_session_access = "released"
    with pytest.raises(MachineTransportError, match="current bound session"):
        client.read_hosts_state()
    assert len(calls) == 1


def test_host_read_facade_refuses_other_routes_and_stopped_host():
    import threading
    from nodelang.baboom_native_host import BaboomNativeHost
    host = object.__new__(BaboomNativeHost)
    host._stop = threading.Event()
    host._lock = threading.Lock()
    host._connected = True
    calls = []
    host._transport = SimpleNamespace(read_hosts_state=lambda: calls.append("read") or {"hosts": []})
    with host.bound_client() as client:
        with pytest.raises(RuntimeError, match="only hosts_state"):
            client.request("POST", "/api/universal/hosts", {})
        assert client.request("GET", "/api/universal/hosts", {}) == {"hosts": []}
    assert calls == ["read"]
    host._stop.set()
    with pytest.raises(RuntimeError, match="stopped"):
        with host.bound_client():
            pass


def test_unsupported_generation_is_refused_before_dispatch(packaged):
    packaged.runtime.start()
    with pytest.raises(GooseRefused, match="default generation"):
        GooseAdapter(packaged.runtime).ask("go", "", "openrouter/free", generation={"max_tokens": 800})
    assert packaged.calls == []


def test_offline_archive_staging_preserves_libraries_and_notices(tmp_path):
    import importlib.util
    import zipfile
    path = Path(__file__).resolve().parents[1] / "packaging/windows/stage_goose.py"
    spec = importlib.util.spec_from_file_location("stage_goose", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = tmp_path / "fake.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("goose/goose.exe", b"fake-executable")
        package.writestr("goose/helper.dll", b"fake-library")
        package.writestr("goose/NOTICE", b"upstream notices")
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps({"version": "1.54.0", "url": "https://example.invalid/fake.zip",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
    staged = tmp_path / "staged"
    manifest = module.stage_goose(archive, staged, pin_path=pin)
    assert manifest["executable_sha256"] == hashlib.sha256(b"fake-executable").hexdigest()
    assert (staged / "helper.dll").read_bytes() == b"fake-library"
    assert (staged / "NOTICE").read_bytes() == b"upstream notices"
