"""Courts for tools/real_app_check: the parts of the real-app rig that can be checked without a window.

The rig's own acceptance is its real run (README). These pin its safety rules: isolation, the
candidate label and overlay allowlist, the installed-code digest, the folder-dialog Edit choice, the
exact signing-key read and its fail-closed verdict, the strict step verdict, the run-unique desktop and
the Job that owns every process.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "real_app_check"
windows_only = pytest.mark.skipif(os.name != "nt", reason="the rig drives Windows desktops and Job objects")


def _rig():
    spec = importlib.util.spec_from_file_location("real_app_check", TOOL / "real_app_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(script):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to load the harness guards")
    done = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


GUARDS = json.dumps((TOOL / "guards.mjs").resolve().as_uri())


# (1) The signing-key read is exact; the verdict fails closed. ------------------------------------

class _FakeNcrypt:
    def __init__(self, open_key_code):
        self.open_key_code, self.freed = open_key_code, 0

    def NCryptOpenStorageProvider(self, handle, name, flags):
        return 0

    def NCryptOpenKey(self, provider, key, name, spec, flags):
        assert flags == 0x40                       # silent: never a prompt
        return self.open_key_code

    def NCryptFreeObject(self, handle):
        self.freed += 1
        return 0


def test_only_nte_bad_keyset_reads_as_absent_and_other_errors_keep_their_code():
    rig = _rig()
    assert rig.signing_key_state("k", ncrypt=_FakeNcrypt(0x80090016)) == "absent"
    silent_context = rig.signing_key_state("k", ncrypt=_FakeNcrypt(0x80090022))   # NTE_SILENT_CONTEXT
    assert silent_context == "inaccessible:0x80090022"
    assert rig.signing_key_state("k", ncrypt=_FakeNcrypt(0x80090010)) == "inaccessible:0x80090010"


def test_the_key_verdict_fails_closed_unless_exact_and_unchanged():
    rig = _rig()
    present = "present:" + "a" * 64
    assert rig.signing_key_verdict("absent", "absent") == "PASS"
    assert rig.signing_key_verdict(present, present) == "PASS"
    for before, after in (("absent", present), (present, "present:" + "b" * 64),
                          ("inaccessible:0x80090022", "inaccessible:0x80090022"),
                          ("absent", "inaccessible:0x80090022"), ("store-unavailable:0x1", "store-unavailable:0x1"),
                          ("present", "present"), ("unsupported", "unsupported")):
        assert rig.signing_key_verdict(before, after).startswith("FAIL"), (before, after)


@windows_only
def test_the_real_key_read_is_silent_and_creates_nothing():
    rig = _rig()
    name = "ArchHub-real-app-check-court-" + uuid.uuid4().hex
    assert rig.signing_key_state(name) == "absent"
    assert rig.signing_key_state(name) == "absent"          # reading twice still created nothing


# (2) A step passes only on an explicit pass: true and only expected HTTP refusals. ----------------

def test_a_step_passes_only_on_pass_true_with_no_unexpected_http_error():
    result = _node(
        "import {stepVerdict} from %s;"
        "const cases = {undef: stepVerdict(undefined), nul: stepVerdict(null), empty: stepVerdict({}),"
        " truthy: stepVerdict({pass: 'yes'}), one: stepVerdict({pass: 1}), ok: stepVerdict({pass: true}),"
        " why: stepVerdict({pass: true, why: 'x'}), http: stepVerdict({pass: true}, ['500 /api/universal/canvas']),"
        " expected: stepVerdict({pass: true, expected_http: ['400 /api/universal/workshop']}, ['400 /api/universal/workshop']),"
        " other: stepVerdict({pass: true, expected_http: ['400 /api/universal/workshop']}, ['403 /api/universal/workshop'])};"
        "console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([k, v]) => [k, v.result]))));" % GUARDS)
    assert result == {"undef": "FAIL", "nul": "FAIL", "empty": "FAIL", "truthy": "FAIL", "one": "FAIL",
                      "ok": "PASS", "why": "FAIL", "http": "FAIL", "expected": "PASS", "other": "FAIL"}


def test_a_step_that_was_not_exercised_is_never_a_pass():
    result = _node(
        "import {stepVerdict} from %s;"
        "const cases = {skipped: stepVerdict({not_exercised: 'needs a graph owner'}, ['400 /api/universal/workspace-roots']),"
        " both: stepVerdict({pass: true, not_exercised: 'x'}), blank: stepVerdict({not_exercised: '  '}),"
        " notext: stepVerdict({not_exercised: true})};"
        "console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([k, v]) => [k, v.result]))));" % GUARDS)
    assert result == {"skipped": "NOT EXERCISED", "both": "FAIL", "blank": "FAIL", "notext": "FAIL"}


def test_the_run_passes_only_when_every_step_passed_and_no_gate_failed():
    rig = _rig()
    passed, skipped, failed = ({"asked": "a", "result": "PASS"}, {"asked": "b", "result": "NOT EXERCISED"},
                               {"asked": "c", "result": "FAIL"})
    assert rig.run_result([passed], []) == "PASS"
    assert rig.run_result([passed, skipped], []).startswith("INCOMPLETE")
    assert rig.run_result([passed, skipped, failed], []).startswith("FAIL")
    assert rig.run_result([passed], ["FAIL: the installed code changed"]).startswith("FAIL")
    assert rig.run_result([], []).startswith("FAIL")
    assert rig.run_result([{"asked": "d", "result": "maybe"}], []).startswith("FAIL")


def test_the_harness_refuses_every_signing_control():
    result = _node(
        "import {refuseSigning, SIGNING_CONTROLS} from %s;"
        "const refused = SIGNING_CONTROLS.filter(t => { try { refuseSigning(t); return false; } catch (_) { return true; } });"
        "let browse = true; try { refuseSigning('Browse…'); } catch (_) { browse = false; }"
        "console.log(JSON.stringify({controls: SIGNING_CONTROLS, refused, browse}));" % GUARDS)
    assert set(result["controls"]) == {"Add", "Remove", "Republish", "Stop governing"}
    assert result["refused"] == result["controls"] and result["browse"] is True


# (3) A run-unique desktop that is never shared; (4) one Job owns every process. -------------------

@windows_only
def test_each_run_gets_its_own_desktop_and_an_existing_name_is_refused():
    rig = _rig()
    job = rig.RunJob()
    first = second = None
    try:
        first, second = rig.HiddenDesktop(job), rig.HiddenDesktop(job)
        assert first.name != second.name and first.name.startswith("ArchHubRealAppCheck-")
        with pytest.raises(RuntimeError, match="already exists"):
            rig.HiddenDesktop(job, name=first.name)
    finally:
        for desktop in (first, second):
            if desktop is not None:
                desktop.close()
        job.close()


@windows_only
def test_closing_the_job_ends_the_whole_tree_and_a_helper_wait_is_bounded():
    rig = _rig()
    job = rig.RunJob()
    desktop = rig.HiddenDesktop(job)
    try:
        started = time.monotonic()
        desktop.run("ping -n 60 127.0.0.1", timeout=2)       # a helper that would run 60 s
        assert time.monotonic() - started < 15
        parent = desktop.spawn("cmd.exe /d /c ping -n 120 127.0.0.1")
        deadline = time.monotonic() + 10
        while len(job.pids()) < 2 and time.monotonic() < deadline:
            time.sleep(0.2)
        tree = job.pids()
        assert int(parent.pid) in tree and len(tree) >= 2     # cmd and its child ping are both in the Job
    finally:
        desktop.close()
        job.close()
    k32 = __import__("ctypes").windll.kernel32
    assert k32.WaitForSingleObject(parent.hProcess, 5000) == 0   # signalled: the process ended


# (5) The overlay is an allowlisted, contained copy; the installed code is proven untouched. --------

def _installed(tmp_path):
    installed = tmp_path / "installed"
    (installed / "nodelang" / "__pycache__").mkdir(parents=True)
    (installed / "nodelang" / "x.py").write_text("old\n", encoding="utf-8")
    (installed / "nodelang" / "__pycache__" / "x.cpython-314.pyc").write_bytes(b"cache")
    (installed / "BUILD_ID").write_text("build\n", encoding="utf-8")
    (installed / "founder-state.sqlite3").write_text("never copied\n", encoding="utf-8")
    return installed


def test_an_overlay_runs_from_a_labelled_copy_and_the_installed_code_digest_is_unchanged(tmp_path):
    rig = _rig()
    installed, overlay = _installed(tmp_path), tmp_path / "overlay"
    (overlay / "nodelang").mkdir(parents=True)
    (overlay / "nodelang" / "x.py").write_text("new\n", encoding="utf-8")
    before = rig.tree_digest(installed)
    app, label, laid = rig.stage_app(installed, overlay, tmp_path / "run")
    assert label == "CANDIDATE OVERLAY" and laid == ["nodelang/x.py"]
    assert (app / "nodelang" / "x.py").read_text(encoding="utf-8") == "new\n"
    assert not (app / "founder-state.sqlite3").exists()
    assert rig.tree_digest(installed) == before
    (installed / "nodelang" / "__pycache__" / "x.cpython-314.pyc").write_bytes(b"recompiled")
    assert rig.tree_digest(installed) == before               # bytecode caches are not code
    (installed / "nodelang" / "x.py").write_text("changed\n", encoding="utf-8")
    assert rig.tree_digest(installed) != before
    same, label, laid = rig.stage_app(installed, None, tmp_path / "unused")
    assert same == installed and label == "INSTALLED BUILD" and laid == []


@pytest.mark.parametrize("relative", ["evil.txt", "packaging/compile_studio.cjs", ".venv/Scripts/python.exe",
                                      "unified-authority/graph.sqlite3"])
def test_an_overlay_outside_the_code_allowlist_is_refused_before_any_copy(tmp_path, relative):
    rig = _rig()
    installed, overlay = _installed(tmp_path), tmp_path / "overlay"
    target = overlay / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="allowlist"):
        rig.stage_app(installed, overlay, tmp_path / "run")
    assert not (tmp_path / "run").exists()


@windows_only
def test_an_overlay_link_is_refused(tmp_path):
    rig = _rig()
    installed, overlay = _installed(tmp_path), tmp_path / "overlay"
    (overlay / "nodelang").mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("x\n", encoding="utf-8")
    try:
        (overlay / "nodelang" / "linked.py").symlink_to(outside)
    except OSError:
        pytest.skip("this account cannot create symbolic links")
    with pytest.raises(ValueError, match="link"):
        rig.stage_app(installed, overlay, tmp_path / "run")


@windows_only
def test_an_overlay_junction_is_refused(tmp_path):
    rig = _rig()
    installed, overlay = _installed(tmp_path), tmp_path / "overlay"
    (overlay / "nodelang").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "planted.py").write_text("x\n", encoding="utf-8")
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(overlay / "nodelang" / "linked"), str(outside)],
                          capture_output=True, text=True)
    assert made.returncode == 0, made.stdout + made.stderr
    with pytest.raises(ValueError, match="link"):
        rig.stage_app(installed, overlay, tmp_path / "run")
    assert not (tmp_path / "run").exists()


# Isolation and the folder-dialog Edit. ------------------------------------------------------------

def test_the_app_environment_is_isolated_and_drops_agent_variables(tmp_path):
    rig = _rig()
    base = {"PATH": "x", "APPDATA": r"C:\real", "LOCALAPPDATA": r"C:\real", "USERPROFILE": r"C:\real",
            "CLAUDE_CODE_SESSION_ID": "s", "ARCHHUB_STATE_DIR": "d", "SESSION_LINK_NODE": "n",
            "CODEX_HOME": "c", "ANTHROPIC_API_KEY": "k", "PYTHONPATH": "p"}
    env = rig.isolated_env(base, tmp_path, cdp_port=9301, lock_port=9302)
    for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME", "TEMP", "TMP", "CLAUDE_CONFIG_DIR",
                 "ARCHHUB_TEST_STATE_DIR"):
        assert Path(env[name]).is_relative_to(tmp_path), name
    assert not [key for key in env if key.startswith(("CLAUDE_CODE", "SESSION_LINK", "CODEX", "ANTHROPIC", "PYTHONPATH"))]
    assert "ARCHHUB_STATE_DIR" not in env and env["PATH"] == "x"
    assert env["QTWEBENGINE_REMOTE_DEBUGGING"] == "127.0.0.1:9301" and env["ARCHHUB_TEST_LOCK_PORT"] == "9302"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_the_folder_dialog_edit_is_chosen_by_type_not_by_its_shared_name():
    rig = _rig()
    search = {"matches": [
        {"type": "Text", "name": "Folder:", "selector": "1090"},
        {"type": "Edit", "name": "Folder:", "selector": "1152"}]}
    assert rig.pick_edit_slug(search, "Folder:") == "1152"
    assert rig.pick_edit_slug(rig.json_tail("progress...\n" + json.dumps(search)), "Folder:") == "1152"
    with pytest.raises(ValueError):
        rig.pick_edit_slug({"matches": [search["matches"][0]]}, "Folder:")
    with pytest.raises(ValueError):
        rig.pick_edit_slug({"matches": [search["matches"][1], dict(search["matches"][1], selector="9")]}, "Folder:")


# (v3) The probe must finish: DONE, exit 0, no timeout, and exactly the declared steps. ----------

_DECLARED = 'DECLARED ["one", "two"]'
_ROWS = [{"asked": "one", "result": "PASS"}, {"asked": "two", "result": "PASS"}]


def test_a_finished_probe_with_its_declared_steps_has_no_problem():
    rig = _rig()
    assert rig.probe_problems([_DECLARED, "STEP {}", "DONE []"], 0, False, _ROWS) == []


@pytest.mark.parametrize("lines, exit_code, timed_out, rows, expected", [
    ([_DECLARED, "DONE []"], None, True, _ROWS, "timed out"),
    ([_DECLARED, "DONE []"], 3, False, _ROWS, "exited with 3"),
    ([_DECLARED], 0, False, _ROWS, "never reported DONE"),
    (["DONE []"], 0, False, _ROWS, "declared no steps"),
    ([_DECLARED, "DONE []"], 0, False, _ROWS[:1], "differ from the declared"),
    ([_DECLARED, "DONE []"], 0, False, _ROWS + [{"asked": "three", "result": "PASS"}], "differ from the declared"),
])
def test_an_unfinished_or_divergent_probe_fails_the_run_even_with_pass_rows(lines, exit_code, timed_out, rows, expected):
    rig = _rig()
    problems = rig.probe_problems(lines, exit_code, timed_out, rows)
    assert any(expected in problem for problem in problems), problems
    assert rig.run_result(rows, problems).startswith("FAIL")


@windows_only
def test_a_run_that_raises_still_writes_its_report_with_the_key_and_digest(tmp_path):
    rig = _rig()
    installed, overlay = _installed(tmp_path), tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "outside-the-allowlist.txt").write_text("x\n", encoding="utf-8")
    out = tmp_path / "evidence"
    code = rig.main(["--scenario", str(TOOL / "scenarios" / "smoke.mjs"), "--out", str(out),
                     "--app", str(installed), "--overlay", str(overlay)])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert code == 1 and report["result"].startswith("FAIL: the run raised ValueError")
    assert "allowlist" in report["exception"]
    assert report["signing_key_before"] == report["signing_key_after"]
    assert report["installed_code_before"] == report["installed_code_after"]


# (v3) The run's own graph owner: planned and proven, never started by these courts. -------------

def _owner():
    spec = importlib.util.spec_from_file_location("graph_owner", TOOL / "graph_owner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan(tmp_path):
    rig, owner = _rig(), _owner()
    run = tmp_path / "run"
    for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "state"):
        (run / name).mkdir(parents=True, exist_ok=True)
    env = rig.isolated_env(dict(os.environ), run, cdp_port=rig.free_port(), lock_port=rig.free_port())
    return owner, owner.plan_graph_owner(run, env, repo=TOOL.parents[1])


def test_the_owner_gets_its_own_ports_and_never_the_live_owners(tmp_path):
    owner, plan = _plan(tmp_path)
    assert plan["coordination_port"] not in (8474, 8475) and plan["canvas_port"] not in (8474, 8475)
    assert plan["coordination_port"] != plan["canvas_port"]
    assert plan["env"]["ARCHHUB_COORDINATION_ENDPOINT"] == "http://127.0.0.1:%d/coordination" % plan["coordination_port"]
    for live in ((8474, 9000), (9000, 8475), (9001, 9001)):
        with pytest.raises(ValueError, match="own two ports"):
            owner.plan_graph_owner(tmp_path / "run", plan["env"], repo=TOOL.parents[1], ports=live)


def test_every_root_the_owner_derives_lies_in_the_run_under_the_planned_environment(tmp_path):
    owner, plan = _plan(tmp_path)
    assert owner.owner_isolation_problems(plan, sys.executable, TOOL.parents[1]) == []
    leaking = dict(plan, env=dict(plan["env"], LOCALAPPDATA=os.environ.get("LOCALAPPDATA", r"C:\outside")))
    problems = owner.owner_isolation_problems(leaking, sys.executable, TOOL.parents[1])
    assert any("resolves outside the run" in problem for problem in problems), problems
    no_endpoint = dict(plan, env={k: v for k, v in plan["env"].items() if k != "ARCHHUB_COORDINATION_ENDPOINT"})
    assert any("endpoint is not the run's own" in problem
               for problem in owner.owner_isolation_problems(no_endpoint, sys.executable, TOOL.parents[1]))


def test_the_owner_sources_are_pinned_by_their_exact_bytes(tmp_path):
    owner, plan = _plan(tmp_path)
    for source in plan["sources"].values():
        assert source["sha256"] == hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()
    assert Path(plan["sources"]["grand_map"]["path"]) == TOOL / "owner_grand_map.json"


@windows_only
def test_provisioning_lands_only_in_the_run_and_refuses_an_unpinned_source(tmp_path):
    owner, plan = _plan(tmp_path)
    run = Path(plan["run_dir"])
    bad = owner.provision_command(plan, sys.executable, TOOL.parents[1])
    bad[-1] = "0" * 64                                              # the grand map's pin no longer matches
    refused = subprocess.run(bad, env=plan["env"], capture_output=True, text=True, timeout=300)
    assert refused.returncode != 0
    assert not (Path(plan["runtime_root"]) / "CURRENT").exists()
    done = subprocess.run(owner.provision_command(plan, sys.executable, TOOL.parents[1]), env=plan["env"],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-800:]
    assert json.loads(done.stdout.strip().splitlines()[-1])["ok"] is True
    assert (Path(plan["runtime_root"]) / "CURRENT").is_file()
    keys = run / "LOCALAPPDATA" / "ArchHub" / "keys"
    assert {path.name for path in keys.iterdir()} >= {"authority-signing-v1.dpapi.json", "caller-signing-v1.dpapi.json"}


def test_the_owner_is_started_only_through_the_runs_desktop_and_job(tmp_path):
    owner, plan = _plan(tmp_path)
    calls = []

    class Desktop:
        def spawn(self, command, *, env=None, cwd=None):
            calls.append((command, env, cwd))
            return "spawned"
    assert owner.start_graph_owner(Desktop(), plan, "python.exe", tmp_path) == "spawned"
    (command, env, cwd), = calls
    assert "nodelang.clean_coordination_service" in command and "--port %d" % plan["coordination_port"] in command
    assert "--root" in command and env == plan["env"]
