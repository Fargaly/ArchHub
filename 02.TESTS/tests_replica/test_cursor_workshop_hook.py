"""Cursor receives Workshop messages through its own stop hook.

The building check runs the real hook entry against a temp mailbox: one chat's
message comes back as followup_message once, another agent's message does not,
and two prompts keep the same Workshop identity.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "01.APP" / "nodelang" / "native_stop_hook.py"
ONBOARD = Path(r"C:\Users\fargaly\00.ARCHUB\00.GOVERNANCE\03.AGENT-HOOKS\agent_onboard.py")


def _env(mailbox):
    env = os.environ.copy()
    env["ARCHHUB_TEST_STATE_DIR"] = str(mailbox)
    env["PYTHONPATH"] = str(ROOT / "01.APP") + os.pathsep + env.get("PYTHONPATH", "")
    env["ARCHHUB_APP_ROOT"] = str(ROOT)
    return env


def _hook(payload, mailbox):
    done = subprocess.run([sys.executable, str(ENTRY), "--vendor", "cursor"], input=json.dumps(payload),
                          text=True, capture_output=True, cwd=str(ROOT), env=_env(mailbox), timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _cursor_rows(mailbox):
    from nodelang.workshop_mailbox import application_history
    os.environ["ARCHHUB_TEST_STATE_DIR"] = str(mailbox)
    with application_history() as history:
        return [json.loads(row[0]) for row in history._db.execute("SELECT record FROM workshop_declarations")]


def test_cursor_stop_hook_injects_the_addressed_message_once(tmp_path, monkeypatch):
    mailbox = tmp_path / "mailbox"
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(mailbox))
    monkeypatch.setattr("nodelang.workshop_mailbox._sender_may_push", lambda *args, **kwargs: False)
    conversation = "conv-cursor-hook"
    other_conversation = "conv-other-agent"
    base = {"conversation_id": conversation, "model": "grok", "cursor_version": "test",
            "workspace_roots": [str(tmp_path)], "loop_count": 0, "status": "completed"}
    first = _hook({**base, "hook_event_name": "beforeSubmitPrompt", "generation_id": "gen-1", "prompt": "one"}, mailbox)
    assert first == {"continue": True}
    identity = [row for row in _cursor_rows(mailbox) if row.get("native_session_id") == conversation]
    assert len(identity) == 1
    second = _hook({**base, "hook_event_name": "beforeSubmitPrompt", "generation_id": "gen-2", "prompt": "two"}, mailbox)
    assert second == {"continue": True}
    again = [row for row in _cursor_rows(mailbox) if row.get("native_session_id") == conversation]
    assert len(again) == 1
    assert again[0]["session"] == identity[0]["session"]
    assert again[0]["root"] == identity[0]["root"]

    from nodelang.workshop_mailbox import call
    call("declare", {"task": "other work", "paths": [str(tmp_path)], "status": "working", "request_id": "OTHER"},
         {"threadId": "other-agent-thread"})
    call("send", {"to": other_conversation, "text": "OTHER-AGENT-ONLY please reply"}, {"threadId": "sender-thread"})
    sent = call("send", {"to": conversation, "text": "CURSOR-HOOK-BODY please reply"}, {"threadId": "sender-thread"})
    assert sent["message_id"]

    delivered = _hook({**base, "hook_event_name": "stop", "generation_id": "gen-3"}, mailbox)
    text = delivered["followup_message"]
    assert "CURSOR-HOOK-BODY" in text
    assert "OTHER-AGENT-ONLY" not in text
    assert "Workshop" in text and "reply_to" in text
    assert _hook({**base, "hook_event_name": "stop", "generation_id": "gen-4"}, mailbox) == {}

    call("send", {"to": conversation, "text": "CURSOR-HOOK-LATER please reply"}, {"threadId": "sender-thread"})
    held = _hook({**base, "hook_event_name": "stop", "generation_id": "gen-5", "loop_count": 5}, mailbox)
    assert held == {}
    later = _hook({**base, "hook_event_name": "stop", "generation_id": "gen-6", "loop_count": 0}, mailbox)
    assert "CURSOR-HOOK-LATER" in later["followup_message"]
    assert "CURSOR-HOOK-BODY" not in later["followup_message"]
    assert _hook({**base, "hook_event_name": "stop", "generation_id": "gen-7"}, mailbox) == {}


def test_cursor_live_delivery_is_queued_for_the_hook(monkeypatch):
    from nodelang import workshop_mailbox
    from nodelang.workshop_live import push

    def refuse(*args, **kwargs):
        raise AssertionError("cursor delivery must not open a console or bridge")

    monkeypatch.setattr(workshop_mailbox, "_local_transport", refuse)
    assert push("cursor", "conv-1", "hello", "m1") == ("queued", "hook", "queued for next turn via hook")
    assert push("cursor", "", "hello", "m2") == ("queued", "hook", "queued for next turn via hook")


def test_agent_onboard_merges_cursor_hooks_and_keeps_guards(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHHUB_APP_ROOT", str(ROOT))
    home = tmp_path / "home"
    cursor = home / ".cursor"
    cursor.mkdir(parents=True)
    original = {"version": 1, "hooks": {
        "preToolUse": [{"command": "guard-pre"}],
        "postToolUse": [{"command": "guard-post"}],
        "stop": [{"command": "guard-stop"}]}}
    (cursor / "hooks.json").write_text(json.dumps(original), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("agent_onboard_cursorhook", ONBOARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    written = module.install_cursor_workshop_hooks(home)
    assert Path(written) == cursor / "hooks.json"
    module.install_cursor_workshop_hooks(home)
    data = json.loads((cursor / "hooks.json").read_text(encoding="utf-8"))
    assert data["hooks"]["preToolUse"] == original["hooks"]["preToolUse"]
    assert data["hooks"]["postToolUse"] == original["hooks"]["postToolUse"]
    commands = [row.get("command", "") for row in data["hooks"]["stop"]]
    assert "guard-stop" in commands
    ours = [row for row in data["hooks"]["stop"] if "native_stop_hook.py" in row.get("command", "")]
    assert len(ours) == 1
    assert "--vendor cursor" in ours[0]["command"]
    from nodelang.native_agent_hooks import CURSOR_HOOK_NODE
    assert ours[0]["loop_limit"] == CURSOR_HOOK_NODE["params"]["loop_limit"]
    before = [row for row in data["hooks"]["beforeSubmitPrompt"] if "native_stop_hook.py" in row.get("command", "")]
    assert len(before) == 1 and before[0]["command"] == ours[0]["command"]
    assert "loop_limit" not in before[0]
