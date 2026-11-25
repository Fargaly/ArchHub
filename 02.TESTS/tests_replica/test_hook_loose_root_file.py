"""Founder 2026-11-25: nothing forced agents to keep governed roots clean, and rules must be Settings he edits and
controls, with their configuration. ArchHub's one hook (every vendor) applies STD FOLDERS-02 as configured."""
import json

from nodelang import hook_decision as hd


def _governed(tmp_path):
    root = tmp_path / "12.WEBSITE"
    root.mkdir()
    (root / "README.md").write_text("x", encoding="utf-8")
    (root / "REGISTER.md").write_text("x", encoding="utf-8")
    return root


def _env(tmp_path):
    return {"ARCHHUB_STATE_DIR": str(tmp_path / "state"), "ARCHHUB_TEST_STATE_DIR": str(tmp_path / "state"),
            "APPDATA": str(tmp_path), "TMP": str(tmp_path)}


def _write(path, vendor="codex", env=None):
    return hd.decide({"session_id": "s-loose", "tool_name": "Write",
                      "tool_input": {"file_path": str(path), "content": "scratch"}}, vendor, environment=env)


def _set(env, rules):
    path = hd._settings_dir(env) / "permissions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return hd.write_permissions({"rules": rules}, env, path)


def test_a_new_loose_file_at_a_governed_root_is_refused_for_every_vendor(tmp_path):
    root, env = _governed(tmp_path), _env(tmp_path)
    for vendor in ("claude-code", "codex", "cursor", "gemini"):
        decision = _write(root / "_check_line842.py", vendor, env)
        assert decision["verdict"] == "refuse" and "loose-root-file" in decision["rules"], vendor
        assert any("STD FOLDERS-02" in note and str(root / "_WIP") in note for note in decision["notes"])


def test_wip_results_and_existing_files_are_allowed(tmp_path):
    root, env = _governed(tmp_path), _env(tmp_path)
    (root / "_WIP").mkdir()
    assert "loose-root-file" not in _write(root / "_WIP" / "draft.py", env=env)["rules"]
    assert "loose-root-file" not in _write(root / "archhub-ahf-rep-web-001-2026-11-25.pdf", env=env)["rules"]
    assert "loose-root-file" not in _write(root / "README.md", env=env)["rules"]


def test_the_rule_is_configured_in_settings_switch_violation_agents_and_parameters(tmp_path):
    root, env = _governed(tmp_path), _env(tmp_path)
    default = hd.checked_permissions({})["rules"]["loose-root-file"]
    assert default["state"] == "On" and default["onViolation"] == "Refuse" and default["appliesTo"] == "All agents"
    # an extra allowed root file is a parameter he edits
    _set(env, {"loose-root-file": {"params": {"rootFiles": "README.md, REGISTER.md, NOTICE.md"}}})
    assert "loose-root-file" not in _write(root / "NOTICE.md", env=env)["rules"]
    # Note instead of Refuse: the call runs, the note still names the rule
    _set(env, {"loose-root-file": {"onViolation": "Note"}})
    noted = _write(root / "notes.txt", env=env)
    assert "loose-root-file" not in noted["rules"] and any("STD FOLDERS-02" in n for n in noted["notes"])
    held = hd.read_permissions(env)["rules"]["loose-root-file"]
    assert held["params"]["rootFiles"].endswith("NOTICE.md"), "a partial edit keeps the earlier parameter"
    # only some agents
    _set(env, {"loose-root-file": {"onViolation": "Refuse", "appliesTo": "codex"}})
    assert "loose-root-file" in _write(root / "notes.txt", "codex", env)["rules"]
    assert "loose-root-file" not in _write(root / "notes.txt", "cursor", env)["rules"]
    # Off
    _set(env, {"loose-root-file": "Off"})
    assert "loose-root-file" not in _write(root / "notes.txt", "codex", env)["rules"]
    stored = json.loads((hd._settings_dir(env) / "permissions.json").read_text(encoding="utf-8"))
    assert stored["rules"]["loose-root-file"]["state"] == "Off"


def test_a_bad_rule_setting_is_refused_with_a_reason(tmp_path):
    env = _env(tmp_path)
    for bad in ({"nope": "On"}, {"loose-root-file": {"state": "Maybe"}}, {"loose-root-file": {"onViolation": "Explode"}},
                {"loose-root-file": {"params": {"unknown": "x"}}}):
        try:
            _set(env, bad)
        except ValueError as refused:
            assert str(refused)
        else:
            raise AssertionError(bad)
