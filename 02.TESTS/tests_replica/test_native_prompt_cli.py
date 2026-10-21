"""Prompt CLI courts: retained owner only, no installed app or credential vault."""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace as NS

import pytest

from nodelang import native_agent_hooks as hook
from nodelang import native_stop_hook as stop


SESSION = "12345678-1234-4234-9234-123456789abc"
ACTOR = "app:agent-session:runtime:" + "a" * 32


class Client:
    agent_session_root = ACTOR
    _pinned_runtime_descriptor = NS(application_root="application", workshop_root="workshop")

    def __init__(self):
        self.receipts = []

    def current_work_assignment(self):
        return {"agent_session": ACTOR, "work": None, "revision": 3, "projection": "assignment"}

    def request(self, method, path, body, **kwargs):
        assert (method, path) == ("POST", "/api/universal/deliberation")
        self.receipts.append(body)
        return {"ok": True, "space": body["space"], "category_root": body["category"],
                "root": "app:compliance-event:" + "b" * 64, "payload_root": "app:compliance-event:" + "b" * 64,
                "sequence": 1, "revision": 3}


class Control:
    def __init__(self):
        self.client = Client()

    @contextmanager
    def bound_client(self):
        yield self.client

    def call(self, method, values, **kwargs):
        assert method == "read_messages"
        return {"ok": True, "application": "application", "space": "workshop", "agent_session": ACTOR,
                "storage": "conversation-content", "revision": 3, "has_older": False, "entries": []}


@pytest.mark.parametrize("vendor", ["codex", "claude-code"])
def test_stdin_context_and_completed_receipt_use_the_existing_client(monkeypatch, vendor):
    control = Control()
    fingerprint = stop._fingerprint(stop.canonical_runtime(vendor), SESSION)
    def query(payload, **kwargs):
        assert kwargs["vendor"] == vendor
        return hook.complete_prompt(control, fingerprint=fingerprint,
                                    external_session_fingerprint=hashlib.sha256(SESSION.encode()).hexdigest(),
                                    prompt_sha256=hashlib.sha256(payload["prompt"].encode()).hexdigest())
    monkeypatch.setattr(hook, "query_prompt", query)
    monkeypatch.setattr(hook.sys, "stdin", NS(buffer=io.BytesIO(json.dumps({
        "hook_event_name": "UserPromptSubmit", "session_id": SESSION, "prompt": "real prompt"}).encode())))
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(hook.sys, "stdout", stdout)
    monkeypatch.setattr(hook.sys, "stderr", stderr)
    assert hook.main(["user-prompt-submit", "--vendor", vendor]) == 0
    output = json.loads(stdout.getvalue())
    assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "app:agent-session:runtime:" in output["hookSpecificOutput"]["additionalContext"]
    receipt, = control.client.receipts
    assert receipt["payload"] == {"operation": "native.hook_user_prompt_submit", "status": "Completed",
        "session_fingerprint": fingerprint,
        "external_session_fingerprint": hashlib.sha256(SESSION.encode()).hexdigest(), "prompt_sha256": hashlib.sha256(b"real prompt").hexdigest()}
    assert "real prompt" not in json.dumps(receipt)
    assert stderr.getvalue() == ""


def test_failure_is_nonblocking_and_logs_without_disclosing_prompt(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("private prompt and capability must not be logged")
    monkeypatch.setattr(hook, "query_prompt", unavailable)
    monkeypatch.setattr(hook.sys, "stdin", NS(buffer=io.BytesIO(b'{"session_id":"s","prompt":"private"}')))
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(hook.sys, "stdout", stdout)
    monkeypatch.setattr(hook.sys, "stderr", stderr)
    assert hook.main(["user-prompt-submit", "--vendor", "codex"]) == 0
    assert json.loads(stdout.getvalue()) == {}
    assert "RuntimeError" in stderr.getvalue() and "private" not in stderr.getvalue()


@pytest.mark.parametrize("payload", [[], {}, {"session_id": SESSION, "prompt": 3},
    {"session_id": SESSION, "prompt": "x", "hook_event_name": "Stop"}])
def test_wrong_event_never_reaches_the_owner(monkeypatch, payload):
    monkeypatch.setattr(stop, "owner_write_request", lambda *a, **k: pytest.fail("owner contacted"))
    with pytest.raises(ValueError):
        hook.query_prompt(payload, vendor="codex", environment={})


@pytest.mark.parametrize("vendor,key", [("codex", "CODEX_THREAD_ID"), ("claude-code", "CLAUDE_SESSION_ID")])
def test_payload_environment_fingerprint_mismatch_is_refused(monkeypatch, vendor, key):
    monkeypatch.setattr(stop, "owner_write_request", lambda *a, **k: pytest.fail("owner contacted"))
    with pytest.raises(ValueError):
        hook.query_prompt({"session_id": SESSION, "prompt": "x"}, vendor=vendor, environment={key: "other"})


def test_receipt_refusal_never_returns_completed_context():
    control = Control()
    def refused(*args, **kwargs):
        raise RuntimeError("receipt refused")
    control.client.request = refused
    with pytest.raises(RuntimeError, match="receipt refused"):
        hook.complete_prompt(control, fingerprint="c" * 64,
                             external_session_fingerprint="e" * 64, prompt_sha256="d" * 64)


@pytest.mark.skipif(os.name != "nt", reason="Windows secured owner pipe")
@pytest.mark.parametrize("vendor", ["codex", "claude-code"])
def test_real_secured_owner_ipc_records_receipt_without_another_client(monkeypatch, vendor):
    control = Control()
    owner = NS(_identity=NS(runtime=vendor, external_session_id=SESSION))
    @contextmanager
    def bound():
        yield control.client
    owner.bound_client = bound
    status = {"state": "bound", "agent_session": ACTOR, "pinned": {"instance_digest": "instance"}}
    owner.owner_status = lambda: dict(status)
    values = {}
    vault = NS(get_password=lambda s, k: values.get(k),
               set_password=lambda s, k, v: values.__setitem__(k, v),
               delete_password=lambda s, k: values.pop(k, None))
    from nodelang import native_agent_mcp
    monkeypatch.setattr(native_agent_mcp, "_OwnedWorkshopClient", lambda o, c: control)
    host = stop.NativeStopHost(owner, vault=vault).start()
    try:
        result = hook.query_prompt({"session_id": SESSION, "prompt": "actual stdin event"},
                                   vendor=vendor, vault=vault, environment={})
        assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert len(control.client.receipts) == 1
        assert control.client.receipts[0]["payload"]["session_fingerprint"] == host.fingerprint
        status["pinned"] = {"instance_digest": "replacement"}
        with pytest.raises(stop.OwnerWriteDenied):
            hook.query_prompt({"session_id": SESSION, "prompt": "second"},
                              vendor=vendor, vault=vault, environment={})
        assert len(control.client.receipts) == 1
    finally:
        assert host.close()


@pytest.mark.parametrize("mode", ["module", "direct"])
@pytest.mark.parametrize("raw", ["not JSON", "[]", "x" * 65537], ids=["malformed", "array", "oversized"])
def test_actual_entrypoints_fail_open_from_stdin(mode, raw):
    root = Path(__file__).resolve().parents[2]
    entry = ["-m", "nodelang.native_agent_hooks"] if mode == "module" else [str(root / "01.APP/nodelang/native_agent_hooks.py")]
    result = subprocess.run([sys.executable, *entry, "user-prompt-submit", "--vendor", "codex"],
                            input=raw, text=True, capture_output=True, cwd=root, timeout=20)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
    assert "prompt continues" in result.stderr


def test_timed_out_connection_cannot_dispatch_later(monkeypatch):
    connected, release = threading.Event(), threading.Event()
    sent = []
    connection = NS(close=lambda: None, send_bytes=sent.append)
    def connect(*args, **kwargs):
        connected.set()
        release.wait(2)
        return connection
    monkeypatch.setattr(stop, "Client", connect)
    monkeypatch.setattr(stop, "_server_pid", lambda c: 42)
    monkeypatch.setattr(stop, "_live_record", lambda *a: {"pid": 42, "endpoint": "fake", "key": "a" * 64})
    try:
        with pytest.raises(TimeoutError):
            hook.query_prompt({"session_id": SESSION, "prompt": "x"}, vendor="codex",
                              environment={}, vault=object(), timeout=0.05)
        assert connected.is_set()
    finally:
        release.set()
    for thread in threading.enumerate():
        if thread.name == "native-prompt-query":
            thread.join(2)
    assert sent == []


@pytest.mark.parametrize("argv", [[], ["user-prompt-submit", "--vendor", "wrong"], ["unknown"]])
def test_bad_cli_arguments_cannot_block_a_prompt(monkeypatch, argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(hook.sys, "stdout", stdout)
    monkeypatch.setattr(hook.sys, "stderr", stderr)
    assert hook.main(argv) == 0
    assert json.loads(stdout.getvalue()) == {}


def test_safe_owner_refusal_reason_reaches_stderr(monkeypatch):
    def refused(*args, **kwargs):
        raise stop.OwnerWriteDenied("receipt refused")
    monkeypatch.setattr(hook, "query_prompt", refused)
    monkeypatch.setattr(hook.sys, "stdin", NS(buffer=io.BytesIO(b'{}')))
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(hook.sys, "stdout", stdout)
    monkeypatch.setattr(hook.sys, "stderr", stderr)
    assert hook.main(["user-prompt-submit", "--vendor", "codex"]) == 0
    assert json.loads(stdout.getvalue()) == {}
    assert "receipt refused" in stderr.getvalue()


def test_query_discards_a_blocking_owner_output(monkeypatch):
    monkeypatch.setattr(stop, "owner_write_request", lambda *a, **k: {"decision": "block", "reason": "malicious"})
    with pytest.raises(hook.MachineTransportError, match="output is invalid"):
        hook.query_prompt({"session_id": SESSION, "prompt": "x"}, vendor="codex", environment={})


def test_config_patch_adds_one_command_and_preserves_every_existing_hook(tmp_path):
    root = Path(__file__).resolve().parents[2]
    original = (root / "inputs/codex-hooks.json").read_bytes()
    target = tmp_path / ".codex/hooks.json"
    target.parent.mkdir()
    target.write_bytes(original)
    patch = str(root / "inputs/codex-hooks.patch")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "apply", "--check", patch], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "apply", patch], cwd=tmp_path, check=True, capture_output=True)
    before, after = json.loads(original), json.loads(target.read_bytes())
    commands = after["hooks"]["UserPromptSubmit"][0]["hooks"]
    added = commands.pop()
    assert after == before
    assert added["type"] == "command" and added["timeout"] == 20
    assert "native_agent_hooks.py" in added["command"]
    assert "user-prompt-submit --vendor codex" in added["command"]
