"""Filesystem-only profile checks; no CLI, model, graph or credential access."""
import json
from pathlib import Path
import pytest

from nodelang.native_workshop_profile import (
    NativeProfileRefused, SERVER_NAME, TASK_SOURCE_FILES, prepare_claude_workshop_profile,
)

SESSION = "477c5160-73cd-4a0e-8eac-2b506368b06c"


@pytest.mark.parametrize('key',['SESSION_LINK_REQUIRED_CONNECTIONS','Session_Link_Required_Connections'])
def test_fresh_profile_does_not_inherit_existing_session_recovery_links(tmp_path,key):
    values=inputs(tmp_path)
    values['environment'][key]='a'*16
    original=dict(values['environment'])
    profile=prepare_claude_workshop_profile(**values)
    try:
        server=json.loads((profile.cwd/'mcp.json').read_bytes())['mcpServers'][SERVER_NAME]
        assert 'SESSION_LINK_REQUIRED_CONNECTIONS' not in {name.upper() for name in profile.environment}
        assert 'SESSION_LINK_REQUIRED_CONNECTIONS' not in {name.upper() for name in server['env']}
        assert '--expected-actor' not in server['args']
        assert values['environment']==original
        assert server['env']['CLAUDE_CODE_SESSION_ID']==SESSION
    finally:
        profile.cleanup(process_exited=True)


def inputs(tmp_path):
    installed = tmp_path / "installed"
    (installed / "nodelang").mkdir(parents=True)
    for filename in TASK_SOURCE_FILES:
        (installed / 'nodelang' / filename).write_text('# fixture source\n')
    state = tmp_path / "state"
    state.mkdir()
    python = tmp_path / "python.exe"
    native = tmp_path / "claude.exe"
    python.write_bytes(b"fixture only")
    native.write_bytes(b"fixture only")
    return dict(install_root=installed, state_root=state, python_executable=python,
                native_executable=native, external_session_id=SESSION,
                work_root="assembly-instance:fixture-work", model="fixture-model",
                tool_names=("native.work_current", "native.work_claim"),
                permission_sources=(),
                environment={"PATH": "fixture-path", "CODEX_THREAD_ID": "parent-task",
                             "CLAUDE_CODE_SESSION_ID": "unrelated-parent"})


def test_profile_uses_only_installed_mcp_and_preserves_subscription_auth(tmp_path):
    values = inputs(tmp_path)
    profile = prepare_claude_workshop_profile(**values)
    args = profile.argv
    assert "--bare" not in args and "--dangerously-skip-permissions" not in args
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--setting-sources=" in args
    assert "--no-session-persistence" not in args
    assert args[args.index("--model") + 1] == "fixture-model"
    assert "CLAUDE_CODE_SESSION_ID" not in profile.environment
    assert "CODEX_THREAD_ID" not in profile.environment
    assert profile.environment["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert profile.environment["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert "unrelated-parent" not in repr(profile)
    mcp = json.loads((profile.cwd / "mcp.json").read_bytes())
    assert set(mcp["mcpServers"]) == {"archhub_agent_coordination"}
    server = mcp["mcpServers"][SERVER_NAME]
    assert server["args"][-2:] == ["--workshop-task", values["work_root"]]
    assert server["args"][:3] == ["-I", "-B", "-c"]
    assert server["env"] == {"ARCHHUB_AGENT_RUNTIME": "claude", "ARCHHUB_EXTERNAL_SESSION_ID": SESSION,
        "CLAUDE_CODE_SESSION_ID": SESSION,
        "SESSION_LINK_STATE_DIR": str(values['state_root'] / 'session-link'),
        "SESSION_LINK_NODE": str(values['install_root'] / 'runtime' / 'node.exe')}
    assert str(values["install_root"]) in server["args"]
    profile.verify()
    assert profile.cleanup(process_exited=True) is True
    assert not profile.cwd.exists()


def test_changed_installed_task_source_refuses_launch_but_owned_cleanup_remains_available(tmp_path):
    values = inputs(tmp_path)
    profile = prepare_claude_workshop_profile(**values)
    source = values['install_root'] / 'nodelang/native_workshop_tools.py'
    source.write_text('# changed task tools\n')
    with pytest.raises(NativeProfileRefused, match='task source changed'):
        profile.verify()
    # A code update must not prevent safe deletion of unchanged owned config.
    assert profile.cleanup(process_exited=True) is True
    assert source.read_text() == '# changed task tools\n'


@pytest.mark.parametrize("override", [
    {"ANTHROPIC_API_KEY": "fixture"},
    {"ANTHROPIC_BASE_URL": "https://provider.invalid"},
    {"CLAUDE_CODE_USE_BEDROCK": "1"},
    {"anthropic_api_key": "fixture"},
    {"Claude_Code_Use_Vertex": "true"},
])
def test_subscription_profile_refuses_other_billing_before_writes(tmp_path, override):
    values = inputs(tmp_path)
    values["environment"].update(override)
    with pytest.raises(NativeProfileRefused, match="conflicts") as error:
        prepare_claude_workshop_profile(**values)
    assert "fixture-private-value" not in str(error.value)
    assert not (values["state_root"] / "native-workshop").exists()


def test_cleanup_requires_exit_and_never_removes_changed_or_foreign_files(tmp_path):
    profile = prepare_claude_workshop_profile(**inputs(tmp_path))
    with pytest.raises(NativeProfileRefused, match="Live"):
        profile.cleanup(process_exited=False)
    config = profile.cwd / "mcp.json"
    original = config.read_bytes()
    config.write_bytes(b"changed by user")
    with pytest.raises(NativeProfileRefused, match="changed"):
        profile.cleanup(process_exited=True)
    assert config.read_bytes() == b"changed by user"
    config.write_bytes(original)
    foreign = profile.cwd / "keep.txt"
    foreign.write_bytes(b"user data")
    assert profile.cleanup(process_exited=True) is False
    assert foreign.read_bytes() == b"user data"


def test_existing_session_configuration_is_not_reused(tmp_path):
    values = inputs(tmp_path)
    first = prepare_claude_workshop_profile(**values)
    before = {p: Path(p).read_bytes() for p in first.config_digests}
    with pytest.raises(NativeProfileRefused, match="already exists"):
        prepare_claude_workshop_profile(**values)
    assert {p: Path(p).read_bytes() for p in before} == before
    first.cleanup(process_exited=True)


def test_permission_restrictions_survive_without_copying_hooks_or_grants(tmp_path):
    values = inputs(tmp_path)
    settings = tmp_path / "personal-settings.json"
    settings.write_text(json.dumps({
        "permissions": {"deny": ["mcp__archhub_agent_coordination__coordination_send_message"],
                        "ask": ["mcp__archhub_agent_coordination__native_work_submit"],
                        "allow": ["Bash(*)"]},
        "hooks": {"fixture": "private command"}, "apiKeyHelper": "private helper",
    }))
    values["permission_sources"] = (settings,)
    before = settings.read_bytes()
    profile = prepare_claude_workshop_profile(**values)
    copied = json.loads((profile.cwd / "settings.json").read_bytes())
    assert copied == {"autoMemoryEnabled": False, "forceLoginMethod": "claudeai",
                      "permissions": {"deny": ["mcp__archhub_agent_coordination__coordination_send_message"],
                                      "ask": ["mcp__archhub_agent_coordination__native_work_submit"]}}
    assert SERVER_NAME == "archhub_agent_coordination"
    assert settings.read_bytes() == before
    profile.cleanup(process_exited=True)


def test_environment_duplicate_names_and_conflicting_login_are_refused(tmp_path):
    values = inputs(tmp_path)
    values["environment"]["Path"] = "ambiguous"
    with pytest.raises(NativeProfileRefused, match="ambiguous"):
        prepare_claude_workshop_profile(**values)
    values["environment"].pop("Path")
    settings = tmp_path / "settings.json"
    settings.write_text('{"forceLoginMethod":"console"}')
    values["permission_sources"] = (settings,)
    with pytest.raises(NativeProfileRefused, match="login method"):
        prepare_claude_workshop_profile(**values)
    assert not (values["state_root"] / "native-workshop").exists()


def test_identical_replacement_is_not_owned_for_cleanup(tmp_path):
    profile = prepare_claude_workshop_profile(**inputs(tmp_path))
    config = profile.cwd / "mcp.json"
    original = config.read_bytes()
    retained = profile.cwd / "original-config.json"
    config.rename(retained)
    config.write_bytes(original)
    with pytest.raises(NativeProfileRefused, match="identity changed"):
        profile.cleanup(process_exited=True)
    assert config.read_bytes() == retained.read_bytes() == original


def test_missing_required_settings_refuse_before_writes(tmp_path):
    values = inputs(tmp_path)
    values["permission_sources"] = (tmp_path / "missing-project-settings.json",)
    with pytest.raises(NativeProfileRefused, match="Required"):
        prepare_claude_workshop_profile(**values)
    assert not (values["state_root"] / "native-workshop").exists()


def test_profile_constructs_the_real_driver_input_with_explicit_limits(tmp_path):
    profile = prepare_claude_workshop_profile(**inputs(tmp_path))
    launch = profile.launch(max_input_bytes=65536, max_output_bytes=262144,
        max_event_bytes=65536, max_events=64, max_process_bytes=512*1024**2,
        startup_timeout_seconds=30, turn_timeout_seconds=60,
        lifetime_seconds=120, stop_timeout_seconds=5)
    assert launch.argv == profile.argv
    assert dict(launch.env) == dict(profile.environment)
    assert launch.external_session_id == SESSION and launch.max_events == 64
    profile.cleanup(process_exited=True)
