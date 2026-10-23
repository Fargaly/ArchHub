"""Real application/pipe courts for uncertain attachments across owner death."""
import logging
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil
import pytest

from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
from nodelang.native_agent_mcp import _OwnedWorkshopClient
from nodelang.native_agent_session import NativeAgentSession
from tests_replica.test_native_inbox_recovery import KEY, World, _start, _work_note


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("REATTACH-TEMPLATE")
    _start(root).close()
    return root


@pytest.fixture
def world(template, tmp_path):
    made = World(template, tmp_path / "APP")
    try:
        yield made
    finally:
        made.close()


def lose_reply(monkeypatch):
    original = UniversalRuntimeClient._accept_agent_session_result
    lost = []

    def accept(client, result, expected_agent_session=None):
        if not lost:
            lost.append(dict(result))
            raise MachineTransportError("court: owner died before attachment reply")
        return original(client, result, expected_agent_session)

    monkeypatch.setattr(UniversalRuntimeClient, "_accept_agent_session_result", accept)
    return lost


def retired(monkeypatch, owner):
    # All fixture servers run in this process: substitute only old process death.
    monkeypatch.setattr(owner, "_require_retired_owner_process", lambda descriptor: None)


@pytest.mark.parametrize("runtime,field", [("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_THREAD_ID")])
def test_uncertain_initial_attach_uses_new_owner_once(world, monkeypatch, caplog, runtime, field):
    calls = []

    class Counted(UniversalRuntimeClient):
        def bind_agent_session(self, **kwargs):
            calls.append((self._pinned_runtime_descriptor.runtime_id, kwargs))
            return super().bind_agent_session(**kwargs)

    owner = NativeAgentSession(environment={field: "court-reattach"},
        descriptor_path=world.root / "runtime.json", key_provider=KEY, client_factory=Counted)
    lost = lose_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="owner died"):
        owner.connect()
    old_client, old_descriptor = owner._client, owner._descriptor
    assert owner.owner_status()["state"] == "uncertain"
    with pytest.raises(MachineTransportError, match="no automatic enrollment retry"):
        owner.connect()
    assert len(calls) == 1
    world.restart()
    retired(monkeypatch, owner)
    caplog.set_level(logging.INFO, logger="nodelang.native_agent_session")
    client = owner.connect()
    assert client is not old_client and owner._descriptor.runtime_id != old_descriptor.runtime_id
    assert client.agent_session_root == lost[0]["agent_session"]
    assert owner.connect() is client and len(calls) == 2
    assert [row[0] for row in calls] == [old_descriptor.runtime_id, owner._descriptor.runtime_id]
    assert len([r for r in caplog.records if "reattach" in r.getMessage().lower()]) == 1
    control = _OwnedWorkshopClient(owner, client)
    result = _work_note(control, client.agent_session_root, "fresh request only", "reattach-fresh")
    assert result["message_id"] and len(calls) == 2


def test_failed_continuation_recovers_on_third_owner_without_replaying_tool(world, monkeypatch, caplog):
    owner, control = world.owner("court-reattach-existing")
    actor = owner._session_root
    world.restart()
    lose_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="owner died"):
        _work_note(control, actor, "must never run", "reattach-old")
    assert owner.owner_status()["rebind_pending"] is True
    world.restart()
    retired(monkeypatch, owner)
    caplog.set_level(logging.INFO, logger="nodelang.native_agent_session")
    with monkeypatch.context() as patch:
        patch.setattr(owner, "_continue_after_owner_change", lambda: None)
        with pytest.raises(MachineTransportError, match="binding changed"):
            owner.connect()
    assert not [r for r in caplog.records if "reattach" in r.getMessage().lower()]
    assert _work_note(control, actor, "fresh independent call", "reattach-new")["message_id"]
    assert owner._session_root == actor and owner.generation == 2
    messages = control.call("read_messages", {"limit": 20})["entries"]
    summaries = [entry["summary"] for entry in messages]
    assert "must never run" not in summaries and summaries.count("fresh independent call") == 1
    assert world.bind_calls == [("court-reattach-existing", None),
        ("court-reattach-existing", actor), ("court-reattach-existing", actor)]


def test_live_previous_process_still_refuses_and_retains_attempt(world, monkeypatch):
    owner = NativeAgentSession(environment={"CODEX_THREAD_ID": "court-reattach-live"},
        descriptor_path=world.root / "runtime.json", key_provider=KEY)
    lose_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="owner died"):
        owner.connect()
    held = owner._client
    world.restart()
    with pytest.raises(MachineTransportError, match="still present"):
        owner.connect()
    assert owner._client is held and owner._state == "uncertain"


def test_changed_identity_instance_and_inflight_call_never_discard_attempt(world, monkeypatch):
    environment = {"CODEX_THREAD_ID": "court-reattach-boundaries"}
    owner = NativeAgentSession(environment=environment, descriptor_path=world.root / "runtime.json",
        key_provider=KEY)
    lose_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="owner died"):
        owner.connect()
    held, old = owner._client, owner._descriptor
    world.restart()
    current = owner._read_owner()
    retired(monkeypatch, owner)
    owner._active_calls = 1
    with pytest.raises(MachineTransportError, match="no automatic enrollment retry"):
        owner.connect()
    owner._active_calls = 0
    with monkeypatch.context() as patch:
        patch.setattr(owner, "_read_owner", lambda: replace(current, application_root="foreign"))
        with pytest.raises(MachineTransportError, match="no automatic enrollment retry"):
            owner.connect()
        patch.setattr(owner, "_read_owner", lambda: replace(old, started_at=old.started_at + "-changed"))
        with pytest.raises(MachineTransportError, match="no automatic enrollment retry"):
            owner.connect()
    environment["CODEX_THREAD_ID"] = "another-agent"
    with pytest.raises(MachineTransportError, match="identity changed"):
        owner.connect()
    environment["CODEX_THREAD_ID"] = "court-reattach-boundaries"
    with pytest.raises(MachineTransportError, match="expected owner"):
        owner.connect(expected_owner=owner._owner_fingerprint(old))
    assert owner._client is held and owner._descriptor == old and owner._state == "uncertain"


def test_descriptor_publication_backoff_never_retries_an_enrollment(world, monkeypatch):
    owner = NativeAgentSession(environment={"CODEX_THREAD_ID": "court-reattach-discovery"},
        descriptor_path=world.root / "runtime.json", key_provider=KEY)
    lose_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="owner died"):
        owner.connect()
    world.restart()
    retired(monkeypatch, owner)
    read = owner._read_owner
    attempts, waits = [], []

    def publication():
        attempts.append(1)
        if len(attempts) <= 2:
            raise MachineTransportError("court: descriptor not announced yet")
        return read()

    # Replace the module binding, not time.sleep globally (the server uses it).
    import nodelang.native_agent_session as native
    from types import SimpleNamespace
    with monkeypatch.context() as patch:
        patch.setattr(owner, "_read_owner", publication)
        patch.setattr(native, "time", SimpleNamespace(sleep=waits.append, time=native.time.time))
        assert owner.connect().agent_session_root
    assert waits == [0.05, 0.1] and owner.generation == 1


def test_an_already_executed_tool_with_lost_reply_is_not_replayed(world, monkeypatch):
    owner, control = world.owner("court-reattach-executed")
    actor = owner._session_root
    request = UniversalRuntimeClient.request
    dispatched = []

    def lose(client, method, path, body=None, **kwargs):
        result = request(client, method, path, body, **kwargs)
        if path == "/api/universal/workshop" and body.get("text") == "old executed call":
            dispatched.append(body["text"])
            raise MachineTransportError("court: tool reply lost after commit")
        return result

    monkeypatch.setattr(UniversalRuntimeClient, "request", lose)
    with pytest.raises(MachineTransportError, match="tool reply lost"):
        _work_note(control, actor, "old executed call", "reattach-executed")
    world.restart()
    assert _work_note(control, actor, "next call", "reattach-next")["message_id"]
    summaries = [entry["summary"] for entry in control.call("read_messages", {"limit": 20})["entries"]]
    assert summaries.count("old executed call") == summaries.count("next call") == 1
    assert dispatched == ["old executed call"]


@contextmanager
def process_owner(root, log):
    """A real disposable owner process: no substituted death or descriptor."""
    code = ("import sys; from pathlib import Path; "
        "from tests_replica.test_native_inbox_recovery import _start; "
        "server = _start(Path(sys.argv[1])); sys.stdin.readline(); server.close()")
    with log.open("wb") as output:
        process = subprocess.Popen([sys.executable, "-u", "-c", code, str(root)],
            stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, text=True,
            cwd=Path(__file__).resolve().parents[1],
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            owner = NativeAgentSession(environment={"CODEX_THREAD_ID": "court-physical-death"},
                descriptor_path=root / "runtime.json", key_provider=KEY)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail(log.read_text(errors="replace"))
                try:
                    descriptor = owner._read_owner()
                    # Windows venv python.exe may launch the interpreter as a child.
                    family = {process.pid, *(child.pid for child in psutil.Process(process.pid).children(recursive=True))}
                    if descriptor.process_id in family:
                        break
                except (MachineTransportError, psutil.Error):
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("isolated owner did not announce within 90 seconds")
            yield owner, descriptor.process_id
        finally:
            try:
                process.communicate("\n", timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                pytest.fail("isolated owner did not close within 30 seconds")
        assert process.returncode == 0


def test_real_process_death_reattaches_without_a_death_stub(template, tmp_path, monkeypatch):
    root = tmp_path / "PROCESS"
    shutil.copytree(template, root)
    with process_owner(root, tmp_path / "OWNER.log") as (owner, first_pid):
        lost = lose_reply(monkeypatch)
        with pytest.raises(MachineTransportError, match="owner died"):
            owner.connect()
        first = owner._descriptor
        assert first.process_id == first_pid
    with process_owner(root, tmp_path / "OWNER.log") as (_replacement, second_pid):
        client = owner.connect()
        assert owner._descriptor.runtime_id != first.runtime_id
        assert owner._descriptor.process_id == second_pid
        assert client.agent_session_root == lost[0]["agent_session"]
        assert _work_note(owner, client.agent_session_root, "after physical death", "physical-new")["ok"] is True
        assert owner.connect() is client and owner.generation == 1


def test_app_down_before_client_creation_can_attach_when_app_returns(world):
    owner = NativeAgentSession(environment={"CODEX_THREAD_ID": "court-start-app-down"},
        descriptor_path=world.root / "runtime.json", key_provider=KEY)
    world.server.close()
    with pytest.raises(MachineTransportError):
        owner.connect()
    assert owner._client is None and owner._state == "unbound"
    world.restart()
    client = owner.connect()
    assert owner.connect() is client and owner.generation == 1
    assert _work_note(owner, client.agent_session_root, "after app starts", "app-up")["ok"] is True


def test_owner_disappearing_before_fresh_connect_does_not_latch_uncertainty(world, monkeypatch):
    owner = NativeAgentSession(environment={"CODEX_THREAD_ID": "court-owner-disappears"},
        descriptor_path=world.root / "runtime.json", key_provider=KEY)
    lose_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="owner died"):
        owner.connect()
    world.restart()
    retired(monkeypatch, owner)
    read = owner._read_owner
    calls = []

    def publication():
        calls.append(1)
        # Recovery discovery and retirement succeed; nested enrollment discovers downtime.
        if len(calls) == 3:
            raise MachineTransportError("court: replacement stopped before enrollment")
        return read()

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_read_owner", publication)
        with pytest.raises(MachineTransportError, match="replacement stopped"):
            owner.connect()
    assert owner._client is None and owner._state == "unbound"
    assert owner.connect().agent_session_root and owner.generation == 1
