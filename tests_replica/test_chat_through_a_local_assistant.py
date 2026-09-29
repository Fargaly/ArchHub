"""Court: chat THROUGH a signed-in local assistant (model route local-cli/<name>).

The picker offered Claude Code, Codex, Gemini CLI and OpenCode as "installed,
not routed". A local-cli/ route now answers one free-text chat turn through the
model broker's own host process -- one engine, no HTTP -- in chat mode (no
review-JSON contract), with the assistant's tools off where it has that switch,
no session kept, and a fresh EMPTY working folder instead of the workspace.
A missing assistant, an unbound broker or an unknown name is a refusal, never a
fallback to another model. The composer's before_dispatch runs first.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodelang import model_router
from nodelang.model_execution_broker import HostProcessResult, ModelExecutionBroker


class FakeHost:
    def __init__(self, stdout=b"", ok=True):
        self.calls = []
        self.stdout, self.ok = stdout, ok

    def run_process(self, command, *, prompt, cwd, timeout_seconds):
        cwd = Path(cwd)
        self.calls.append({"command": tuple(command), "prompt": prompt.decode("utf-8"),
                           "cwd": cwd, "cwd_empty": cwd.is_dir() and not any(cwd.iterdir()),
                           "timeout": timeout_seconds})
        return HostProcessResult(self.ok, self.stdout, "" if self.ok else "provider_failed")

    def post_json(self, *args, **kwargs):
        raise AssertionError("a local-cli chat made an HTTP call")

    def get_json(self, *args, **kwargs):
        raise AssertionError("a local-cli chat made an HTTP call")


def _broker(tmp_path, host, **executables):
    return ModelExecutionBroker(workspace_root=tmp_path, host=host, timeout_seconds=120.0,
                                executables={"local-cli:" + k: v for k, v in executables.items()})


MESSAGES = [{"role": "system", "content": "You are ArchHub."},
            {"role": "user", "content": "How deep is a standard door frame?"}]


@pytest.mark.parametrize("assistant,stdout,expect_args", [
    ("claude", json.dumps({"result": "About 100 mm."}).encode(),
     ["-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
      "--permission-mode", "plan", "--strict-mcp-config", "--setting-sources", "",
      "--disable-slash-commands", "--model", "sonnet"]),
    ("codex", b"About 100 mm.\n",
     ["exec", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only",
      "--color", "never", "--disable", "shell_tool", "--disable", "unified_exec", "--disable", "hooks",
      "--disable", "plugins", "--disable", "memories", "--disable", "apps", "--disable", "browser_use",
      "--disable", "browser_use_external", "--disable", "in_app_browser", "--disable", "computer_use",
      "--disable", "multi_agent", "--disable", "image_generation", "--disable", "skill_mcp_dependency_install",
      "--disable", "tool_suggest", "--disable", "goals", "--disable", "code_mode_host",
      "--disable", "remote_plugin", "--disable", "plugin_sharing", "--disable", "workspace_dependencies",
      "-m", "sonnet", "-"]),
    ("gemini", json.dumps({"response": "About 100 mm."}).encode(),
     ["--prompt", "", "--output-format", "json", "--approval-mode", "plan",
      "--allowed-mcp-server-names", "none", "--extensions", "none", "--model", "sonnet"]),
])
def test_each_assistant_answers_one_chat_turn(tmp_path, assistant, stdout, expect_args):
    host = FakeHost(stdout)
    broker = _broker(tmp_path, host, **{assistant: "C:/tools/%s.exe" % assistant})
    said = broker.chat(assistant, "sonnet", MESSAGES, timeout_seconds=30)
    assert said == {"ok": True, "text": "About 100 mm."}
    (call,) = host.calls
    assert list(call["command"][1:]) == expect_args
    assert call["cwd_empty"] and call["cwd"] != Path(tmp_path), "the assistant must not start in the workspace"
    assert not call["cwd"].exists(), "the empty folder is removed after the turn"
    assert "You are ArchHub." in call["prompt"] and "USER: How deep" in call["prompt"]
    assert "Return ONLY one JSON object" not in call["prompt"], "chat mode, not the review format"
    assert call["timeout"] == 30


def test_an_absent_assistant_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    host = FakeHost(b"x")
    assert _broker(tmp_path, host).chat("gemini", "", MESSAGES) == {
        "ok": False, "error_code": "provider_unavailable"}
    assert host.calls == []


def test_opencode_is_never_a_chat_route(tmp_path):
    """OpenCode's permissions default to allow (edit, bash, webfetch) and no run
    flag denies them: a chat turn could act on the machine (review 2026-09-29)."""
    host = FakeHost(b"x")
    assert _broker(tmp_path, host, opencode="C:/tools/opencode.exe").chat("opencode", "", MESSAGES) == {
        "ok": False, "error_code": "provider_binding_denied"}
    assert host.calls == []
    with pytest.raises(model_router.ModelRouteRefused, match="claude, codex or gemini"):
        model_router.resolve_model_route("local-cli/opencode")


def test_route_chat_goes_through_the_bound_broker_and_never_http(tmp_path):
    host = FakeHost(json.dumps({"result": "Hello from Claude Code."}).encode())
    order = []
    model_router.bind_local_cli_broker(_broker(tmp_path, host, claude="C:/tools/claude.exe"))
    try:
        answer = model_router.route_chat(
            "local-cli/claude", MESSAGES,
            opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("HTTP was used")),
            before_dispatch=lambda: order.append("guard"), cloud_session=None)
    finally:
        model_router.bind_local_cli_broker(None)
    assert answer["ok"] is True and answer["text"] == "Hello from Claude Code."
    assert answer["family"] == "local-cli" and answer["provider"] == "Claude Code"
    assert answer["key_source"] == "not required"
    assert order == ["guard"] and len(host.calls) == 1


def test_route_chat_refuses_rather_than_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(model_router, "installed_cli_version",
                        lambda executable, **_k: model_router._CLI_VERIFIED_VERSIONS["codex"])
    model_router.bind_local_cli_broker(None)
    with pytest.raises(model_router.ModelRouteRefused, match="not available in this process"):
        model_router.route_chat("local-cli/claude", MESSAGES, cloud_session=None)
    with pytest.raises(model_router.ModelRouteRefused, match="claude, codex or gemini"):
        model_router.resolve_model_route("local-cli/notepad")
    host = FakeHost(b"", ok=False)
    model_router.bind_local_cli_broker(_broker(tmp_path, host, codex="C:/tools/codex.exe"))
    try:
        with pytest.raises(model_router.ModelRouteRefused, match="Codex did not answer"):
            model_router.route_chat("local-cli/codex", MESSAGES, cloud_session=None)
    finally:
        model_router.bind_local_cli_broker(None)


def test_the_route_is_recognised_and_garbage_still_refused():
    route = model_router.resolve_model_route("local-cli/gemini/gemini-2.5-pro")
    assert (route.family, route.url, route.provider, route.needs_key) == (
        "local-cli", "local-cli:gemini", "Gemini CLI", False)
    with pytest.raises(model_router.ModelRouteRefused):
        model_router.resolve_model_route("nowhere/model")


def test_the_picker_row_says_where_the_chat_goes():
    tested = model_router._CLI_VERIFIED_VERSIONS
    rows = model_router.provider_rows(
        environ={}, secrets_loader=lambda _n: "", cloud_session=None,
        local_probe=lambda *_a: False, cli_probe=lambda exe: "C:/tools/%s.exe" % exe,
        version_probe=lambda route: tested.get(route))
    by = {row["id"]: row for row in rows}
    assert by["claude-code"]["state"] == "installed"
    assert "local-cli/claude" in by["claude-code"]["source"]
    assert "sent to Anthropic through your subscription" in by["claude-code"]["source"]
    assert "can read files" not in by["claude-code"]["source"], "Claude Code runs with every tool off"
    assert "can read files" not in by["codex"]["source"], "Codex runs with every tool off"
    assert "it can read files on this computer" in by["gemini-cli"]["source"]
    assert "Gemini CLI: not verified on this machine" in by["gemini-cli"]["source"]
    assert "not verified" not in by["claude-code"]["source"] + by["codex"]["source"]
    assert by["opencode"]["state"] == "installed, not routed"
    assert "run commands and change files" in by["opencode"]["source"]


def test_the_application_binds_its_broker_and_the_studio_knows_the_family():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "_model_router.bind_local_cli_broker(server.model_execution_broker)" in launcher
    jsx = (root / "nodelang" / "studio" / "studio-lm.jsx").read_text(encoding="utf-8")
    assert "['local-cli/', 'local-cli']" in jsx

# Real assistants, opt-in: ARCHHUB_REAL_CLI_COURT=1 sends one "hello" turn to each
# installed assistant through the real host process (it uses the subscription).
REAL = __import__("os").environ.get("ARCHHUB_REAL_CLI_COURT") == "1"


@pytest.mark.skipif(not REAL, reason="set ARCHHUB_REAL_CLI_COURT=1 to call real assistants")
@pytest.mark.parametrize("assistant", ["claude", "codex", "gemini"])
def test_a_real_assistant_answers_hello(tmp_path, assistant):
    broker = ModelExecutionBroker(workspace_root=tmp_path, timeout_seconds=180.0)
    if not broker.local_cli_executable(assistant):
        pytest.skip("%s is not installed here" % assistant)
    said = broker.chat(assistant, "", [{"role": "user", "content": "Reply with the single word: hello"}])
    assert said.get("ok") is True, said
    assert "hello" in said["text"].lower()


@pytest.mark.skipif(not REAL, reason="set ARCHHUB_REAL_CLI_COURT=1 to call real assistants")
def test_a_real_claude_turn_starts_no_mcp_server_and_no_hook(tmp_path):
    """Plain `claude -p` starts the person's MCP servers -- ArchHub's own
    coordination server among them, which enrols a session in the graph -- and
    runs their hooks. The chat argv must start neither (read from its debug log)."""
    import subprocess
    from nodelang.model_execution_broker import local_cli_chat_command
    broker = ModelExecutionBroker(workspace_root=tmp_path, timeout_seconds=180.0)
    executable = broker.local_cli_executable("claude")
    if not executable:
        pytest.skip("claude is not installed here")
    log = tmp_path / "claude-debug.log"
    work = tmp_path / "empty"
    work.mkdir()
    subprocess.run(local_cli_chat_command("claude", executable) + ("--debug-file", str(log)),
                   input=b"Reply with the single word: hello", cwd=work, capture_output=True,
                   timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = log.read_text(encoding="utf-8", errors="replace")
    assert text, "claude wrote no debug log"
    assert 'MCP server "' not in text, "an MCP server started inside a chat turn"
    assert "Found 0 total hooks" in text


@pytest.mark.skipif(not REAL, reason="set ARCHHUB_REAL_CLI_COURT=1 to call real assistants")
@pytest.mark.parametrize("assistant", ["claude", "codex"])
def test_a_real_assistant_cannot_write_a_file(tmp_path, assistant):
    """Read-only is enforced by the assistant, not assumed: asked to create a file
    in its working folder, it leaves none there (looked at before the folder goes)."""
    broker = ModelExecutionBroker(workspace_root=tmp_path, timeout_seconds=180.0)
    if not broker.local_cli_executable(assistant):
        pytest.skip("%s is not installed here" % assistant)
    watched = []
    real_run = broker._host.run_process

    def run_and_look(command, *, prompt, cwd, timeout_seconds):
        result = real_run(command, prompt=prompt, cwd=cwd, timeout_seconds=timeout_seconds)
        watched.append(sorted(p.name for p in Path(cwd).iterdir()))
        return result
    broker._host.run_process = run_and_look
    broker.chat(assistant, "", [{"role": "user", "content":
        "Create a file named proof.txt containing the word written in the current folder, then reply done."}])
    assert watched == [[]], "the assistant wrote into its folder: %r" % watched


@pytest.mark.skipif(not REAL, reason="set ARCHHUB_REAL_CLI_COURT=1 to call real assistants")
@pytest.mark.parametrize("assistant", ["claude", "codex"])
def test_a_real_assistant_cannot_read_a_file(tmp_path, assistant):
    secret = tmp_path / "secret.txt"
    token = "ARCHHUB-" + __import__("uuid").uuid4().hex
    secret.write_text(token, encoding="utf-8")
    broker = ModelExecutionBroker(workspace_root=tmp_path, timeout_seconds=180.0)
    if not broker.local_cli_executable(assistant):
        pytest.skip("%s is not installed here" % assistant)
    said = broker.chat(assistant, "", [{"role": "user", "content":
        "Read the file %s and reply with its exact contents." % secret}])
    assert token not in str(said.get("text", "")), "the assistant read a file on this computer"


@pytest.mark.skipif(not REAL, reason="set ARCHHUB_REAL_CLI_COURT=1 to call real assistants")
def test_a_real_codex_turn_runs_no_command_at_all(tmp_path):
    """Enforcement, not obedience: with its tools off Codex emits no
    command_execution item at all (its own --json event stream)."""
    import subprocess
    from nodelang.model_execution_broker import local_cli_chat_command
    broker = ModelExecutionBroker(workspace_root=tmp_path, timeout_seconds=180.0)
    executable = broker.local_cli_executable("codex")
    if not executable:
        pytest.skip("codex is not installed here")
    command = local_cli_chat_command("codex", executable)
    work = tmp_path / "empty"
    work.mkdir()
    answer = subprocess.run(command[:2] + ("--json",) + command[2:],
                            input=b"Create proof.txt here with a shell command, then reply done.",
                            cwd=work, capture_output=True, timeout=180,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    events = answer.stdout.decode("utf-8", "replace")
    assert '"type":"turn.completed"' in events, events[-400:]
    assert '"command_execution"' not in events, "Codex ran a command in a chat turn"
    assert not any(work.iterdir())


def test_another_assistant_version_is_not_verified():
    """A new version can turn on a tool the chat argv does not switch off: until
    the real courts pass on it, the picker says so and names both versions."""
    rows = model_router.provider_rows(
        environ={}, secrets_loader=lambda _n: "", cloud_session=None,
        local_probe=lambda *_a: False, cli_probe=lambda exe: "C:/tools/%s.exe" % exe,
        version_probe=lambda route: "9.9.9")
    codex = next(row for row in rows if row["id"] == "codex")
    assert "Codex: updated; ArchHub has not verified this version yet, so chat through it is refused (tested on %s, installed 9.9.9" % (
        model_router._CLI_VERIFIED_VERSIONS["codex"]) in codex["source"]
    claude = next(row for row in rows if row["id"] == "claude-code")
    assert "Claude Code: not verified on this machine (tested on %s, installed 9.9.9)" % (
        model_router._CLI_VERIFIED_VERSIONS["claude"]) in claude["source"], "Claude is disclosed, not refused"
    unknown = model_router.provider_rows(
        environ={}, secrets_loader=lambda _n: "", cloud_session=None,
        local_probe=lambda *_a: False, cli_probe=lambda exe: "C:/tools/%s.exe" % exe,
        version_probe=lambda route: None)
    assert "installed unknown" in next(row for row in unknown if row["id"] == "claude-code")["source"]


def test_the_version_is_read_once_per_program_file(tmp_path, monkeypatch):
    import subprocess
    program = tmp_path / "codex.exe"
    program.write_bytes(b"x")
    calls = []

    class Done:
        stdout = b"codex-cli 0.144.5\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or Done())
    assert model_router.installed_cli_version(program) == "0.144.5"
    assert model_router.installed_cli_version(program) == "0.144.5"
    assert len(calls) == 1
    assert model_router.installed_cli_version(tmp_path / "missing.exe") is None


@pytest.mark.skipif(not REAL, reason="set ARCHHUB_REAL_CLI_COURT=1 to call real assistants")
@pytest.mark.parametrize("assistant", ["claude", "codex"])
def test_the_installed_version_is_the_one_the_courts_passed_on(tmp_path, assistant):
    broker = ModelExecutionBroker(workspace_root=tmp_path, timeout_seconds=60.0)
    executable = broker.local_cli_executable(assistant)
    if not executable:
        pytest.skip("%s is not installed here" % assistant)
    assert model_router.installed_cli_version(executable) == model_router._CLI_VERIFIED_VERSIONS[assistant]


def test_the_settings_rows_never_wait_on_a_version_read(tmp_path, monkeypatch):
    """Smoothness: the first read answers CHECKING at once and reads the version
    on one background thread; the next read answers from the cache."""
    import threading
    program = tmp_path / "codex.exe"
    program.write_bytes(b"x")
    started, release = threading.Event(), threading.Event()

    def slow(executable):
        started.set()
        release.wait(5)
        return "0.144.5"
    monkeypatch.setattr(model_router, "_read_version", slow)
    assert model_router.installed_cli_version(program, wait=False) == model_router.CHECKING
    assert started.wait(5)
    assert model_router.installed_cli_version(program, wait=False) == model_router.CHECKING, "one read, not two"
    release.set()
    for _ in range(100):
        if model_router.installed_cli_version(program, wait=False) == "0.144.5":
            break
        threading.Event().wait(0.02)
    assert model_router.installed_cli_version(program, wait=False) == "0.144.5"


def test_a_row_says_checking_while_the_version_is_read():
    rows = model_router.provider_rows(
        environ={}, secrets_loader=lambda _n: "", cloud_session=None,
        local_probe=lambda *_a: False, cli_probe=lambda exe: "C:/tools/%s.exe" % exe,
        version_probe=lambda route: model_router.CHECKING)
    codex = next(row for row in rows if row["id"] == "codex")
    assert "Codex: checking its version" in codex["source"]


def test_a_codex_chat_on_an_unverified_version_is_refused_before_it_runs(tmp_path, monkeypatch):
    """717, 2026-09-29: fail closed for Codex -- a new version could run commands
    in a chat turn again. The turn is refused before Codex is launched."""
    host = FakeHost(b"About 100 mm.\n")
    order = []
    monkeypatch.setattr(model_router, "installed_cli_version", lambda executable, **_k: "9.9.9")
    model_router.bind_local_cli_broker(_broker(tmp_path, host, codex="C:/tools/codex.exe"))
    try:
        with pytest.raises(model_router.ModelRouteRefused, match="Codex was updated; ArchHub has not verified this version yet") as refused:
            model_router.route_chat("local-cli/codex", MESSAGES, before_dispatch=lambda: order.append("guard"),
                                    cloud_session=None)
        assert refused.value.reason_code == "unverified_version"
        state = model_router.composer_readiness("local-cli/codex", cloud_session=None)
        assert state["state"] == "unavailable" and "Codex was updated" in state["message"]
    finally:
        model_router.bind_local_cli_broker(None)
    assert host.calls == [] and order == [], "nothing ran"


def test_a_claude_chat_on_another_version_still_answers(tmp_path, monkeypatch):
    host = FakeHost(json.dumps({"result": "About 100 mm."}).encode())
    monkeypatch.setattr(model_router, "installed_cli_version", lambda executable, **_k: "9.9.9")
    model_router.bind_local_cli_broker(_broker(tmp_path, host, claude="C:/tools/claude.exe"))
    try:
        answer = model_router.route_chat("local-cli/claude", MESSAGES, cloud_session=None)
    finally:
        model_router.bind_local_cli_broker(None)
    assert answer["text"] == "About 100 mm."
