"""BABOOM's "interrupt" act reaches a Claude Code session through Session Link.

2026-10-01: the coordination host's interrupt_agent only records a message the
agent reads on its next turn. Claude Code takes a peer frame with priority
"now" as a request for immediate interruption, and Session Link sends exactly
that (session_link/interrupt.mjs). Session Link reports the frame as sent and
unconfirmed: nothing acknowledges the receiver's abort, so BABOOM reports an
interruption *request*, never "interrupted". Codex Desktop exposes no
interrupt to other apps: BABOOM says so and sends nothing.

Review 2026-10-01 (Ping, b8a95aea REJECT): an unconfirmed send was reported as
kind "agent-interrupted"; status was ignored, an empty id and a foreign target
passed. These courts feed the real interrupt.mjs result shapes and drive the
real BABOOM execute route. No live session, bridge or coordination host is
touched: the Session Link process and the coordination link are recorded fakes,
plus one real node run of the real ask.mjs against an empty temp HOME.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import types
from pathlib import Path

import pytest

import nodelang.baboom_agent_link as link
import nodelang.baboom_session_interrupt as bsi
from nodelang import application_server as server_module
from nodelang.universal_cell import InvalidCell

ROOT = Path(__file__).resolve().parents[1]
EXECUTE = "/api/universal/baboom-command-execute"
SESSION = "c4c4c4c4-0000-4000-8000-000000000004"
MESSAGE = "11111111-2222-4333-8444-555555555555"
NOTE = "Interrupt sent with priority now; the receiving session decides under its own permission and hold rules"


def answer(**changes):
    """interrupt.mjs's result, exactly as sendStop()/interrupt() build it."""
    shape = {"target": SESSION, "messageId": MESSAGE, "priority": "now", "status": "sent_unconfirmed", "note": NOTE}
    shape.update(changes)
    return shape


class Recorder:
    def __init__(self, *, returncode=0, stdout=None, stderr="", raises=None):
        self.calls = []
        self.returncode, self.stderr, self.raises = returncode, stderr, raises
        self.stdout = json.dumps(answer(), indent=2) if stdout is None else stdout

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


@pytest.fixture
def env(tmp_path):
    node = tmp_path / "node.exe"
    node.write_bytes(b"")
    return {"SESSION_LINK_NODE": str(node), "LOCALAPPDATA": str(tmp_path / "local")}


# -- 1. the helper: exact result shapes -------------------------------------

def test_a_sent_unconfirmed_answer_is_an_interruption_request_with_its_exact_evidence(env):
    run = Recorder()
    done = bsi.route_interrupt({"target": "claude:" + SESSION, "reason": "wrong file"}, environment=env, runner=run)
    assert len(run.calls) == 1
    argv, kwargs = run.calls[0]
    assert argv[0] == env["SESSION_LINK_NODE"]
    assert Path(argv[1]) == ROOT / "nodelang" / "session_link" / "ask.mjs"
    assert argv[2:] == ["interrupt", "--app", "claude", "--session", SESSION, "--reason", "wrong file"]
    assert kwargs["env"]["SESSION_LINK_STATE_DIR"] == str(Path(env["LOCALAPPDATA"]) / "ArchHub-Test" / "session-link")
    assert done["kind"] == "agent-interrupt-requested"
    assert done["data"]["interrupt"] == answer()            # status, id, target preserved exactly
    assert done["data"]["confirmed"] is False
    summary = done["summary"].casefold()
    assert "requested" in summary and "not confirmed" in summary and SESSION in done["summary"]
    assert "interrupted" not in summary
    run2 = Recorder()
    bsi.route_interrupt({"target": "claude:" + SESSION, "reason": ""}, environment=env, runner=run2)
    assert run2.calls[0][0][-1] == "the founder asked you to stop"


@pytest.mark.parametrize("status", ["held", "refused", "rejected", "denied", "expired", "dropped"])
def test_a_held_or_refused_answer_is_reported_as_not_delivered(env, status):
    run = Recorder(stdout=json.dumps(answer(status=status)))
    done = bsi.route_interrupt({"target": "claude:" + SESSION}, environment=env, runner=run)
    assert done["kind"] == "agent-interrupt-not-delivered"
    assert done["data"]["interrupt"]["status"] == status and done["data"]["confirmed"] is False
    assert status in done["summary"] and "did not interrupt" in done["summary"]


@pytest.mark.parametrize("bad", [
    answer(messageId=""),
    answer(messageId="x"),
    answer(messageId=None),
    answer(target="d5d5d5d5-0000-4000-8000-000000000005"),
    answer(target=None),
    answer(priority="next"),
    answer(status="interrupted"),
    answer(status=None),
    {"priority": "now", "messageId": MESSAGE, "status": "refused"},
])
def test_an_answer_that_does_not_match_this_request_never_claims_anything(env, bad):
    run = Recorder(stdout=json.dumps(bad))
    with pytest.raises(InvalidCell, match="does not match this request.*may or may not have been sent"):
        bsi.route_interrupt({"target": "claude:" + SESSION}, environment=env, runner=run)


def test_a_refused_silent_or_missing_transport_never_claims_anything(env):
    refused = Recorder(returncode=1, stdout="", stderr="Claude Code session went offline; nothing sent\n")
    with pytest.raises(InvalidCell, match="Session Link refused the interrupt: Claude Code session went offline; nothing sent"):
        bsi.route_interrupt({"target": "claude:" + SESSION}, environment=env, runner=refused)
    silent = Recorder(raises=subprocess.TimeoutExpired(["node"], 20))
    with pytest.raises(InvalidCell, match="may or may not have been sent"):
        bsi.route_interrupt({"target": "claude:" + SESSION}, environment=env, runner=silent)
    garbage = Recorder(stdout="not json")
    with pytest.raises(InvalidCell, match="does not match this request"):
        bsi.route_interrupt({"target": "claude:" + SESSION}, environment=env, runner=garbage)
    missing = {"SESSION_LINK_NODE": str(Path(env["SESSION_LINK_NODE"]).with_name("absent.exe")),
               "LOCALAPPDATA": env["LOCALAPPDATA"]}
    none = Recorder()
    with pytest.raises(InvalidCell, match="Node runtime is unavailable; nothing was sent"):
        bsi.route_interrupt({"target": "claude:" + SESSION}, environment=missing, runner=none)
    assert none.calls == []


@pytest.mark.parametrize("spec,row", [
    ({"target": "codex"}, None),
    ({"target": "codex:01a07b65-f0c4-7040-a218-d703384679a0", "reason": "stop"}, None),
    ({"target": "CODEX"}, None),
    ({"target": "app:agent-session:runtime:" + "a" * 32}, {"provider": "codex", "runtime": "codex"}),
])
def test_a_codex_agent_is_refused_plainly_and_nothing_is_sent(env, spec, row):
    run = Recorder()
    with pytest.raises(InvalidCell) as refused:
        bsi.route_interrupt(spec, row=row, environment=env, runner=run)
    assert str(refused.value) == bsi.CODEX_REFUSAL
    assert "Codex agents can't be interrupted" in bsi.CODEX_REFUSAL and "Nothing was sent" in bsi.CODEX_REFUSAL
    assert run.calls == []


@pytest.mark.parametrize("spec,row", [
    ({"target": "claude"}, None),
    ({"target": "claude:"}, None),
    ({"target": "claude:my-build-session"}, None),       # a title is not an exact session id
    ({"target": "app:agent-session:runtime:" + "b" * 32}, {"provider": "claude", "runtime": "claude"}),
])
def test_a_claude_agent_without_its_exact_session_id_is_refused_unsent(env, spec, row):
    run = Recorder()
    with pytest.raises(InvalidCell, match="Name the Claude Code session"):
        bsi.route_interrupt(spec, row=row, environment=env, runner=run)
    assert run.calls == []


def test_other_agents_stay_on_the_coordination_path(env):
    run = Recorder()
    assert bsi.route_interrupt({"target": "gemini"}, environment=env, runner=run) is None
    assert bsi.route_interrupt({"target": "x"}, row={"provider": "opencode"}, environment=env, runner=run) is None
    assert run.calls == []


def test_the_real_session_link_entry_refuses_an_unknown_session_through_the_same_argv(tmp_path):
    """The argv BABOOM builds is the one ask.mjs reads: a session that is not
    live comes back as Session Link's own refusal, never as requested."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    home = tmp_path / "home"
    home.mkdir()
    env = {**{k: v for k, v in os.environ.items()
              if k not in ("CODEX_APP_TOOLS_PIPE_PATH", "CODEX_THREAD_ID", "SESSION_LINK_PRODUCT_WORKER")},
           "SESSION_LINK_NODE": node, "HOME": str(home), "USERPROFILE": str(home),
           "SESSION_LINK_STATE_DIR": str(tmp_path / "state")}
    with pytest.raises(InvalidCell, match="Session Link refused the interrupt: .*nothing sent"):
        bsi.route_interrupt({"target": "claude:" + SESSION, "reason": "court"}, environment=env)


# -- 2. the real BABOOM entry: the machine execute route ---------------------

@pytest.fixture(scope="module")
def graph():
    from nodelang.map_import import resolve_map_path
    from nodelang.universal_application import build_universal_application
    return build_universal_application(resolve_map_path())


@pytest.fixture
def entry(graph, env, monkeypatch):
    """The real machine dispatcher and executor over a real graph; the Session
    Link process and the coordination host are recorded fakes."""
    store, registry = graph
    founder = registry.agent_body.session.root_id
    state = {"caller": founder}
    fake = types.SimpleNamespace(
        universal_store=store, universal_registry=registry, universal_checkpoint_guard=None,
        mutation_lock=threading.RLock(), conversation_content=None,
        require_universal_http_route=lambda *a, **k: None,
        _resolve_universal_machine_agent_session=lambda request: state["caller"],
        _brain_state=lambda: {"ok": True, "facts": 7}, _host_rows=lambda: [],
        _staged_update=lambda: {}, _desktop_request_update_restart=lambda build: None,
    )
    for name in ("_require_founder_machine_session", "_baboom_machine_content_reader",
                 "_baboom_brain_remember", "_baboom_brain_holds", "_baboom_confirm_ledger",
                 "_restart_to_confirmed_update"):
        setattr(fake, name, types.MethodType(getattr(server_module.ApplicationServer, name), fake))
    run = Recorder()
    monkeypatch.setattr(bsi, "RUNNER", run)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SESSION_LINK_STATE_DIR", raising=False)
    coordination = []
    monkeypatch.setattr(link, "resolve_target", lambda name, agents=None: (
        coordination.append(("resolve", name)) or {"session_root": "app:agent-session:runtime:" + "c" * 32,
                                                    "provider": name, "runtime": name}))
    monkeypatch.setattr(link, "interrupt_agent", lambda root, reason: (
        coordination.append(("interrupt_agent", root, reason)) or {"message": {"root": "m"}}))

    def execute(utterance):
        request = {"method": "POST", "path": EXECUTE, "body": {"utterance": utterance},
                   "runtime_id": "0" * 32, "request_id": "1" * 32,
                   "session": {"root": "app:agent-session:runtime:" + "2" * 32}}
        return server_module.ApplicationServer._dispatch_universal_machine_route(fake, request)

    return types.SimpleNamespace(execute=execute, state=state, run=run, coordination=coordination)


def _result(answer_):
    return answer_.get("result", answer_) if isinstance(answer_, dict) else answer_


def test_a_caller_who_is_not_the_founder_is_refused_before_any_interrupt(entry):
    entry.state["caller"] = "app:agent-session:runtime:" + "9" * 32
    with pytest.raises(server_module.AuthorizationDenied):
        entry.execute("interrupt claude:%s: stop now" % SESSION)
    with pytest.raises(server_module.AuthorizationDenied):
        entry.execute("interrupt codex")
    assert entry.run.calls == [] and entry.coordination == []


def test_the_founder_interrupt_of_a_named_claude_session_is_a_request_not_a_claim(entry):
    out = json.dumps(entry.execute("interrupt claude:%s: wrong file" % SESSION))
    assert len(entry.run.calls) == 1
    assert entry.run.calls[0][0][2:] == ["interrupt", "--app", "claude", "--session", SESSION, "--reason", "wrong file"]
    assert '"agent-interrupt-requested"' in out and '"agent-interrupted"' not in out
    assert MESSAGE in out and "sent_unconfirmed" in out
    assert entry.coordination == []


def test_the_founder_interrupt_of_codex_says_so_and_sends_nothing(entry):
    with pytest.raises(InvalidCell) as refused:
        entry.execute("interrupt codex: stop the build")
    assert str(refused.value) == bsi.CODEX_REFUSAL
    assert entry.run.calls == [] and entry.coordination == []


def test_the_founder_interrupt_of_bare_claude_asks_for_the_session(entry):
    with pytest.raises(InvalidCell, match="Name the Claude Code session"):
        entry.execute("interrupt claude")
    assert entry.run.calls == [] and entry.coordination == []


def test_the_founder_interrupt_of_another_agent_keeps_the_coordination_request(entry):
    out = json.dumps(entry.execute("interrupt gemini: pause"))
    assert entry.run.calls == []
    assert ("interrupt_agent", "app:agent-session:runtime:" + "c" * 32, "pause") in entry.coordination
    assert '"agent-interrupted"' in out        # the coordination request's existing kind, unchanged


# -- 3. the words the founder sees ------------------------------------------

def test_the_howto_and_the_companion_name_a_claude_session_not_codex():
    import inspect
    import nodelang.universal_application as ua
    respond = inspect.getsource(ua.respond_universal_baboom_utterance)
    assert 'interrupt claude:<session id>' in respond and "Codex agents can't be interrupted" in respond
    assert '"interrupt codex"' not in respond
    companion = (ROOT / "nodelang" / "baboom_native_companion.py").read_text(encoding="utf-8")
    assert 'self._prefill("interrupt claude:")' in companion
    assert 'self._prefill("interrupt codex")' not in companion


def test_session_link_help_requests_rather_than_claims_the_abort():
    bridge = (ROOT / "nodelang" / "session_link" / "bridge.mjs").read_text(encoding="utf-8")
    assert "(Claude Code only; requests immediate interruption)" in bridge
    assert "aborts its running turn" not in bridge
