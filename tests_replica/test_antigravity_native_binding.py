"""Antigravity binds as the GEMINI runtime on the INSTALLED native path, and its
end-of-turn cutover is a localized, byte-preserving Stop-only replacement.

Re-scoped after 717 (2026-10-01): the clean coordination host is retired at S5, so
Antigravity binds through the installed native client (native_agent_session ->
UniversalRuntimeClient), as a distinct session under runtime gemini, driven by the
explicit env the installed hook exports -- no clean-host edit, no change to
native_agent_session. The installed hook's Stop entry is cut over, through the same
consented preview/repair path, from the clean-coordination hook to the installed
native Stop client, under Antigravity's archhub-governance/flat config shape, by an
exact argv match and a localized raw-byte edit (Ping v2).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nodelang.native_agent_session import resolve_native_agent_identity


# ---- Identity: Antigravity binds as gemini on the installed native path -------

def test_antigravity_binds_as_gemini_on_the_installed_native_path():
    antigravity = resolve_native_agent_identity({
        "ARCHHUB_AGENT_RUNTIME": "gemini",
        "ARCHHUB_EXTERNAL_SESSION_ID": "antigravity-session-xyz",
    })
    assert antigravity.runtime == "gemini"
    assert antigravity.external_session_id == "antigravity-session-xyz"
    gemini_cli = resolve_native_agent_identity({"GEMINI_SESSION_ID": "gemini-cli-session-abc"})
    assert gemini_cli.runtime == "gemini"
    assert gemini_cli.external_session_id == "gemini-cli-session-abc"
    assert (antigravity.runtime, antigravity.external_session_id) != (
        gemini_cli.runtime, gemini_cli.external_session_id)


def test_antigravity_without_a_session_id_refuses_on_the_native_path():
    with pytest.raises(ValueError):
        resolve_native_agent_identity({"ARCHHUB_AGENT_RUNTIME": "gemini"})
    with pytest.raises(ValueError):
        resolve_native_agent_identity({
            "ARCHHUB_AGENT_RUNTIME": "gemini", "ARCHHUB_EXTERNAL_SESSION_ID": ""})


# ---- The exact argv predicate, in isolation (lookalikes refused) --------------

_CLEAN_STOP = ('"C:\\Python\\python.exe" '
               '"C:/ARCHUB/10.PRODUCT/13.NODE-LANGUAGE/nodelang/clean_antigravity_hook.py" stop')


def test_argv_predicate_accepts_only_the_exact_clean_stop_command():
    from nodelang.session_link_config import _antigravity_clean_stop_argv as parse
    assert parse(_CLEAN_STOP) is not None
    lookalikes = [
        "echo clean_antigravity_hook.py stop",                       # not a python interpreter
        '"C:/py.exe" "C:/x/other_clean_antigravity_hook.py" stop',   # script-name lookalike
        '"C:/py.exe" "C:/x/clean_antigravity_hook.py" pre && echo stop',  # compound
        '"C:/py.exe" "C:/x/clean_antigravity_hook.py" stop --extra',      # extra arg
        '"C:/py.exe" "C:/x/clean_antigravity_hook.py" start',            # wrong arg
        '"C:/py.exe" "C:/x/clean_antigravity_hook.py" stop ; rm -rf x',  # trailing shell
        '"C:/py.exe" "C:/x/clean_antigravity_hook.py" stop # note',      # comment
        'clean_antigravity_hook.py stop',                               # no interpreter
        '"C:/py.exe" "C:/x/clean_antigravity_hook.py.bak" stop',        # extension lookalike
    ]
    for command in lookalikes:
        assert parse(command) is None, "accepted a lookalike: %r" % command


# ---- Cutover through the consented writer (temp HOME; DPAPI backup) -----------

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="the consented hook writer backs up with Windows DPAPI")


def _fixture_obj(stop_entries):
    return {
        "archhub-governance": {
            "PreInvocation": [
                {"command": '"C:/py.exe" "C:/ARCHUB/11.WIP/x.py"', "timeout": 10, "type": "command"},
                {"command": '"C:/py.exe" "C:/x/clean_antigravity_hook.py" pre',
                 "timeout": 10, "type": "command"}],
            "PostInvocation": [
                {"command": '"C:/py.exe" "C:/x/clean_antigravity_hook.py" post',
                 "timeout": 10, "type": "command"}],
            "PreToolUse": [
                {"matcher": ".*", "hooks": [
                    {"command": "C:/py.exe C:/x/agent_scope_gate.py --vendor antigravity",
                     "type": "command"}]}],
            "Stop": stop_entries,
        }
    }


def _install(tmp_path, monkeypatch):
    from nodelang import assistant_registration as reg
    install = tmp_path / "install"
    (install / ".venv" / "Scripts").mkdir(parents=True)
    (install / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (install / "BUILD_METADATA.json").write_text("{}", encoding="utf-8")
    (install / "nodelang").mkdir()
    (install / "nodelang" / "native_stop_hook.py").write_bytes(b"")
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(reg, "install_roots", lambda environment=None: (install, state))
    return reg, state


def _home(tmp_path, raw_bytes):
    profile = tmp_path / "home"
    (profile / ".gemini" / "config").mkdir(parents=True)
    hooks = profile / ".gemini" / "config" / "hooks.json"
    hooks.write_bytes(raw_bytes)
    return profile, hooks


def _env(profile, state, tmp_path):
    return {"USERPROFILE": str(profile), "LOCALAPPDATA": str(tmp_path / "local"),
            "ARCHHUB_TEST_STATE_DIR": str(state), "PATH": ""}


def _setup(tmp_path, monkeypatch, stop_entries, raw=None):
    reg, state = _install(tmp_path, monkeypatch)
    if raw is None:
        raw = (json.dumps(_fixture_obj(stop_entries), indent=2) + "\n").encode("utf-8")
    profile, hooks = _home(tmp_path, raw)
    return reg, _env(profile, state, tmp_path), hooks


def test_cutover_changes_exactly_the_stop_command(tmp_path, monkeypatch):
    reg, env, hooks = _setup(tmp_path, monkeypatch,
                             [{"command": _CLEAN_STOP, "timeout": 10, "type": "command"}])
    before = json.loads(hooks.read_text(encoding="utf-8"))
    preview = reg.preview_hooks("antigravity", environment=env)
    assert preview["changed"] is True and preview["events"] == ["Stop"]
    done = reg.repair_hooks("antigravity", consent=True,
                            plan_digest=preview["plan_digest"], environment=env)
    assert done["changed"] is True
    after = json.loads(hooks.read_text(encoding="utf-8"))
    stop_cmd = after["archhub-governance"]["Stop"][0]["command"]
    assert "native_stop_hook.py" in stop_cmd and "--vendor antigravity" in stop_cmd
    assert "clean_antigravity_hook.py" not in stop_cmd
    expected = json.loads(json.dumps(before))
    expected["archhub-governance"]["Stop"][0]["command"] = stop_cmd
    assert after == expected, "the cutover changed more than the one Stop command"


def test_cutover_preserves_every_byte_outside_the_one_command(tmp_path, monkeypatch):
    """Real localized byte preservation on a NON-canonically formatted file: every byte
    outside the single replaced JSON string is identical (Ping v2 option a)."""
    clean_json = json.dumps(_CLEAN_STOP)
    # Deliberately non-canonical: odd indent, trailing spaces, compact Stop, reordered keys.
    raw_text = (
        "{\n"
        '  "archhub-governance" :  {\n'
        '        "PreInvocation": [ {"type":"command","command":"keep-me","timeout":10} ],   \n'
        '    "PostInvocation":[{"command":"also-keep","timeout":10,"type":"command"}],\n'
        '"Stop":[ {  "type":"command"  ,  "command":' + clean_json + ' ,"timeout": 10 } ]\n'
        "  }\n"
        "}\n"
    )
    raw = raw_text.encode("utf-8")
    reg, env, hooks = _setup(tmp_path, monkeypatch, None, raw=raw)
    preview = reg.preview_hooks("antigravity", environment=env)
    reg.repair_hooks("antigravity", consent=True,
                     plan_digest=preview["plan_digest"], environment=env)
    after_raw = hooks.read_bytes()
    new_cmd = json.loads(after_raw.decode("utf-8"))["archhub-governance"]["Stop"][0]["command"]
    new_token = json.dumps(new_cmd).encode("utf-8")
    old_token = clean_json.encode("utf-8")
    assert raw.replace(old_token, new_token) == after_raw, (
        "bytes outside the one replaced command string were not preserved")


def test_cutover_leaves_other_clients_byte_identical(tmp_path, monkeypatch):
    reg, env, hooks = _setup(tmp_path, monkeypatch,
                             [{"command": _CLEAN_STOP, "timeout": 10, "type": "command"}])
    profile = Path(env["USERPROFILE"])
    others = {}
    for rel, body in ((".claude/settings.json", {"hooks": {"Stop": []}}),
                      (".codex/hooks.json", {"hooks": {"Stop": []}}),
                      (".gemini/settings.json", {"hooks": {"AfterAgent": []}})):
        path = profile / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        others[path] = path.read_bytes()
    preview = reg.preview_hooks("antigravity", environment=env)
    reg.repair_hooks("antigravity", consent=True,
                     plan_digest=preview["plan_digest"], environment=env)
    for path, raw in others.items():
        assert path.read_bytes() == raw, "%s must be untouched" % path


def test_cutover_refuses_a_stale_plan_digest(tmp_path, monkeypatch):
    from nodelang.session_link_config import SessionLinkConfigRefused
    reg, env, hooks = _setup(tmp_path, monkeypatch,
                             [{"command": _CLEAN_STOP, "timeout": 10, "type": "command"}])
    original = hooks.read_bytes()
    reg.preview_hooks("antigravity", environment=env)
    with pytest.raises(SessionLinkConfigRefused):
        reg.repair_hooks("antigravity", consent=True, plan_digest="0" * 64, environment=env)
    assert hooks.read_bytes() == original, "a refused repair must not touch the file"


@pytest.mark.parametrize("stop_entries", [
    [],  # absent
    [{"command": "echo clean_antigravity_hook.py stop", "timeout": 10, "type": "command"}],
    [{"command": '"C:/py.exe" "C:/x/clean_antigravity_hook.py" pre && echo stop',
      "timeout": 10, "type": "command"}],
    [{"command": _CLEAN_STOP, "timeout": 10, "type": "command"},
     {"command": _CLEAN_STOP, "timeout": 10, "type": "command"}],  # duplicate
])
def test_cutover_refuses_and_leaves_the_file_unchanged(tmp_path, monkeypatch, stop_entries):
    from nodelang.session_link_config import SessionLinkConfigRefused
    reg, env, hooks = _setup(tmp_path, monkeypatch, stop_entries)
    original = hooks.read_bytes()
    with pytest.raises(SessionLinkConfigRefused):
        reg.preview_hooks("antigravity", environment=env)
    assert hooks.read_bytes() == original, "a refused preview must not touch the file"
