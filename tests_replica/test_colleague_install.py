"""Courts for the colleague-install seam: a co-worker double-clicks the installer.

Each court guards one way the hand-off went wrong on a clean machine: the
setup installed a dependency list that could not boot the app (rpds-py,
fastapi and uvicorn were missing) so the window never opened; the first-run
marker was written before the setup exit code was read, so one failed run
bricked the icon for good; and every shortcut ran a bare pythonw from
ArchHub.bat, which fails wherever Python was installed without Add-to-PATH.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import colleague_setup  # noqa: E402

DESKTOP_BOOT_MODULES = (
    "nodelang.universal_application",
    "nodelang.application_server",
    "nodelang.universal_pipeline",
    "nodelang.pipeline_engines",
    "nodelang.baboom_attach",
    "nodelang.baboom_native_runtime",
    "nodelang.cell_accounts",
    "nodelang.universal_cell",
)

# Pulled in transitively by a listed package; not the colleague to name.
TRANSITIVE = {
    "anyio", "pydantic", "pydantic_core", "starlette", "httpcore", "certifi",
    "h11", "idna", "sniffio", "typing_extensions", "annotated_types",
    "cffi", "pycparser", "click", "colorama", "exceptiongroup", "annotated_doc",
    "typing_inspection", "multipart", "python_multipart", "email_validator",
    # uvicorn[standard] extras: imported by uvicorn only when present, never required.
    "ujson", "watchfiles", "websockets", "httptools", "uvloop", "dotenv", "yaml",
}


@pytest.fixture
def isolated_user_state(tmp_path, monkeypatch):
    """No court that reaches main() may write into the person's own ArchHub-Test.

    main() offers Claude Code registration and records the answer in the
    launcher's state root; without this, a court that calls main() for real
    overwrites the live assistant-integration.json on the machine running the
    suite and still passes. Requested, never autouse: the boot-import court
    below imports nodelang.map_import, which binds its authority path from
    LOCALAPPDATA at import time.
    """
    state = tmp_path / "user-state"
    local = tmp_path / "localappdata"
    local.mkdir()
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return state


def _forbid_registration(monkeypatch, why):
    """Guard both process seams main() can reach: setup's own pip/venv runs,
    and the run= seam of register_claude_code, which binds run=subprocess.run
    at def time (client_mcp_installation.py:203-204) so no patched
    subprocess.run ever reaches it."""
    from nodelang import client_mcp_installation as installation

    def forbidden(*args, **kwargs):
        raise AssertionError(why)
    real = installation.register_claude_code

    def registration(*args, **kwargs):
        return real(*args, **dict(kwargs, run=forbidden))
    monkeypatch.setattr(colleague_setup.subprocess, "run", forbidden)
    monkeypatch.setattr(installation, "register_claude_code", registration)


def test_setup_list_covers_every_third_party_module_the_desktop_boot_reaches():
    """Measured, not guessed: import the boot, read sys.modules, compare."""
    stdlib = set(sys.stdlib_module_names) | {"nodelang", "_distutils_hack", "__future__"}
    before = set(sys.modules)
    for name in DESKTOP_BOOT_MODULES:
        importlib.import_module(name)
    reached = {
        name.split(".")[0]
        for name in set(sys.modules) - before
        if not name.startswith("_") and name.split(".")[0] not in stdlib
    }
    probes = {probe.split(".")[0] for _pip, probe in colleague_setup.PACKAGES}
    missing = sorted(reached - probes - TRANSITIVE)
    assert not missing, (
        "the desktop boot imports %s but colleague_setup.PACKAGES does not install "
        "them; a first launch on a clean machine would die on import" % missing
    )


def test_first_run_marker_is_written_only_after_setup_succeeds():
    bat = (ROOT / "installer" / "ArchHub.bat").read_text(encoding="utf-8")
    ready_at = bat.index(":launch")
    guard_at = bat.index("if not \"%ARCHHUB_SETUP_RC%\"==\"0\"")
    assert guard_at < ready_at, "the ready marker must follow the exit-code check"
    assert "pause" in bat[guard_at:ready_at], "a failed setup must leave its window open"
    assert re.search(r"^\s*start \"\" pythonw", bat, re.M) is None, (
        "ArchHub.bat must not launch a bare pythonw; ArchHub.vbs resolves the interpreter"
    )


def test_every_shortcut_opens_the_vbs_that_resolves_pythonw():
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert "#define AppExe \"ArchHub.vbs\"" in iss
    vbs = (ROOT / "installer" / "ArchHub.vbs").read_text(encoding="utf-8")
    assert "pythoncore" in vbs, "the launcher must find the installed interpreter itself"
    assert "launch_archhub_test.py" in vbs


def test_setup_no_longer_writes_a_second_desktop_shortcut():
    source = (ROOT / "colleague_setup.py").read_text(encoding="utf-8")
    assert "desktop.write_text" not in source


def test_installer_preserves_the_current_setup_receipt_schema(tmp_path):
    # A same-build reinstall must not force another network-dependent pip run.
    (tmp_path / "BUILD_ID").write_text("candidate-reinstall", encoding="ascii")
    (tmp_path / "requirements.txt").write_text("httpx>=0.28,<1\n", encoding="ascii")
    identity = colleague_setup.readiness_identity(tmp_path)
    colleague_setup._write_ready(tmp_path, identity)
    installer = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    expected = re.search(r"Trim\(String\(ReadyIdentity\)\)\s*<>\s*'([^']+)'", installer).group(1)
    build, digest = identity.split(":")
    expected = expected.replace("{#BuildId}", build).replace("{#RequirementsSha256}", digest)
    assert (tmp_path / ".archhub-ready").read_text(encoding="ascii").strip() == expected


def test_window_icon_is_the_one_the_installer_ships():
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "Path(__file__).resolve().parent / \"archhub.ico\"" in launcher
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert "archhub.ico" in iss


def test_no_surface_runs_a_bare_named_interpreter():
    """A bare 'py'/'python'/'pythonw' resolves from the user-writable install (or
    setup) folder first; a planted binary would run as the person."""
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert "Exec('py'" not in iss and "Exec('python'" not in iss
    assert "function FindPython(): String;" in iss and "Exec(Py," in iss
    assert "DisableDirPage=yes" in iss
    vbs = (ROOT / "installer" / "ArchHub.vbs").read_text(encoding="utf-8")
    assert 'py = "pythonw"' not in vbs
    assert 'Function FindPython(kind)' in vbs
    bat = (ROOT / "installer" / "ArchHub.bat").read_text(encoding="utf-8")
    assert "py -3 colleague_setup.py" not in bat and "\npython colleague_setup.py" not in bat
    assert '"%ARCHHUB_PY%" -E -s colleague_setup.py' in bat


def test_setup_exit_code_is_read_outside_any_block_and_deps_are_pinned():
    bat = (ROOT / "installer" / "ArchHub.bat").read_text(encoding="utf-8")
    # `%errorlevel%` inside a parenthesised block expands at parse time (always 0).
    read = bat.index('set "ARCHHUB_SETUP_RC=%errorlevel%"')
    assert bat.rfind("(", 0, read) < bat.rfind(")", 0, read) or bat.rfind("(", 0, read) == -1
    assert bat.index(':launch') > bat.index('if not "%ARCHHUB_SETUP_RC%"=="0"')
    setup = (ROOT / "colleague_setup.py").read_text(encoding="utf-8")
    assert '"-r", str(pinned)' in setup and '"--user", *missing' not in setup


def _private_environment(tmp_path, monkeypatch):
    owned = tmp_path / ".venv"
    (owned / "Scripts").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (owned / "Scripts" / name).write_text("")
    (owned / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    (tmp_path / "BUILD_ID").write_text("test-build")
    (tmp_path / "requirements.txt").write_text("example==1")
    monkeypatch.setattr(sys, "executable", str(owned / "Scripts/python.exe"))
    monkeypatch.setattr(sys, "prefix", str(owned))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "bootstrap"))
    monkeypatch.setattr(colleague_setup.site, "ENABLE_USER_SITE", False)
    return owned


def test_readiness_requires_private_interpreter_and_current_build(tmp_path, monkeypatch):
    _private_environment(tmp_path, monkeypatch)
    colleague_setup._write_ready(tmp_path, colleague_setup.readiness_identity(tmp_path))
    assert colleague_setup.ready_for_build(tmp_path)
    (tmp_path / "BUILD_ID").write_text("upgrade")
    assert not colleague_setup.ready_for_build(tmp_path)
    colleague_setup._write_ready(tmp_path, colleague_setup.readiness_identity(tmp_path))
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    assert not colleague_setup.ready_for_build(tmp_path)


def test_bootstrap_creation_failure_propagates_without_ready(tmp_path, monkeypatch):
    from types import SimpleNamespace
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=17)
    monkeypatch.setattr(colleague_setup.subprocess, "run", run)
    assert colleague_setup.prepare_environment(tmp_path) == 17
    assert calls[0][0][1:5] == ["-E", "-s", "-m", "venv"]
    assert not (tmp_path / ".archhub-ready").exists()


def test_broken_environment_is_not_recreated(tmp_path, monkeypatch):
    import pytest
    (tmp_path / ".venv").mkdir()
    def forbidden(*args, **kwargs):
        raise AssertionError("must not create or run damaged environment")
    monkeypatch.setattr(colleague_setup.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="damaged"):
        colleague_setup.prepare_environment(tmp_path)
    assert colleague_setup.prepare_environment(tmp_path / "absent", check_only=True) == 1


def test_reparse_path_refused_before_execution(tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace
    original = Path.lstat
    def redirected(path, *args, **kwargs):
        if path == tmp_path / ".venv":
            return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", redirected)
    with pytest.raises(ValueError, match="redirected"):
        colleague_setup.prepare_environment(tmp_path)


def test_environment_drops_inherited_python_paths(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    monkeypatch.setenv("PYTHONHOME", "untrusted")
    env = colleague_setup.clean_environment()
    assert "PYTHONPATH" not in env and "PYTHONHOME" not in env
    assert env["PYTHONNOUSERSITE"] == "1"


def test_pip_failure_removes_marker_and_stays_failed(tmp_path, monkeypatch, isolated_user_state):
    from types import SimpleNamespace
    _private_environment(tmp_path, monkeypatch)
    (tmp_path / "launch_archhub_test.py").write_text("")
    monkeypatch.setattr(colleague_setup, "__file__", str(tmp_path / "colleague_setup.py"))
    colleague_setup._write_ready(tmp_path, colleague_setup.readiness_identity(tmp_path))
    monkeypatch.setattr(colleague_setup, "_has", lambda module: False)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=19)
    monkeypatch.setattr(colleague_setup.subprocess, "run", run)
    assert colleague_setup.main() == 19
    assert not (tmp_path / ".archhub-ready").exists()
    assert "--isolated" in calls[0] and "--user" not in calls[0]


def test_ready_environment_does_not_reinstall(tmp_path, monkeypatch, isolated_user_state):
    _private_environment(tmp_path, monkeypatch)
    (tmp_path / "launch_archhub_test.py").write_text("")
    monkeypatch.setattr(colleague_setup, "__file__", str(tmp_path / "colleague_setup.py"))
    colleague_setup._write_ready(tmp_path, colleague_setup.readiness_identity(tmp_path))
    monkeypatch.setattr(colleague_setup, "_has", lambda module: True)
    def forbidden(*args, **kwargs):
        raise AssertionError("ready environment must not reinstall")
    monkeypatch.setattr(colleague_setup.subprocess, "run", forbidden)
    assert colleague_setup.main() == 0


def test_upgrade_reapplies_constraints_and_records_new_build(
        tmp_path, monkeypatch, isolated_user_state):
    from types import SimpleNamespace
    _private_environment(tmp_path, monkeypatch)
    (tmp_path / "launch_archhub_test.py").write_text("")
    monkeypatch.setattr(colleague_setup, "__file__", str(tmp_path / "colleague_setup.py"))
    colleague_setup._write_ready(tmp_path, colleague_setup.readiness_identity(tmp_path))
    (tmp_path / "BUILD_ID").write_text("new-build")
    monkeypatch.setattr(colleague_setup, "_has", lambda module: True)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(colleague_setup.subprocess, "run", run)
    assert colleague_setup.main() == 0
    assert len(calls) == 1 and "-r" in calls[0]
    assert colleague_setup.ready_for_build(tmp_path)


def test_invalid_reexecuted_interpreter_cannot_loop(tmp_path, monkeypatch):
    import pytest
    _private_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.setattr(sys, "argv", ["colleague_setup.py", "--owned-environment", "--check-ready"])
    with pytest.raises(ValueError, match="identity mismatch"):
        colleague_setup.prepare_environment(tmp_path, check_only=True)


def test_assistant_integration_cannot_block_a_ready_build():
    """The registration offer follows the ready marker and swallows its own failure."""
    import ast
    tree = ast.parse((ROOT / "colleague_setup.py").read_text(encoding="utf-8"))
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    source = ast.unparse(main)
    assert source.index("_write_ready(root, identity)") < source.index(
        "_assistant_integration(Path(os.path.abspath(__file__)).parent, identity)")
    guard = next(node for node in ast.walk(main) if isinstance(node, ast.Try)
                 and any("_assistant_integration" in ast.unparse(stmt) for stmt in node.body))
    assert [ast.unparse(handler.type) for handler in guard.handlers] == ["Exception"]
    assert not any(isinstance(inner, ast.Return)
                   for handler in guard.handlers for inner in ast.walk(handler))


def test_assistant_receipt_uses_the_launcher_state_root():
    """One state location: setup derives it exactly as the installed launcher does."""
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    setup = (ROOT / "colleague_setup.py").read_text(encoding="utf-8")
    for part in ('os.environ.get("ARCHHUB_TEST_STATE_DIR")',
                 'Path(os.environ["LOCALAPPDATA"]) / "ArchHub-Test"'):
        assert part in launcher and part in setup


def test_reexecuted_setup_keeps_the_path_the_shortcut_opened(tmp_path, monkeypatch):
    """prepare_environment() re-executes this file inside the owned interpreter
    and must pass it as opened, never root / "colleague_setup.py": root is
    resolved, and resolving collapses a junction at or above the install, so
    the child could never refuse a redirected registration."""
    import os
    from types import SimpleNamespace
    owned = tmp_path / ".venv"
    (owned / "Scripts").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (owned / "Scripts" / name).write_text("")
    (owned / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    opened = tmp_path / "ArchHub-link" / "colleague_setup.py"
    monkeypatch.setattr(colleague_setup, "__file__", str(opened))
    monkeypatch.setattr(sys, "argv", ["colleague_setup.py"])
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(colleague_setup.subprocess, "run", run)
    assert colleague_setup.prepare_environment(tmp_path) == 0
    assert calls == [[str(owned / "Scripts/python.exe"), "-E", "-s",
                      os.path.abspath(str(opened)), "--owned-environment"]]
    assert calls[0][3] != str(tmp_path / "colleague_setup.py")


def test_main_records_the_consent_receipt_only_inside_this_court(
        tmp_path, monkeypatch, isolated_user_state):
    """main() derives one state root and it must be this court's: without the
    fixture, the receipt lands in the person's own ArchHub-Test."""
    import json
    _private_environment(tmp_path, monkeypatch)
    (tmp_path / "launch_archhub_test.py").write_text("")
    monkeypatch.setattr(colleague_setup, "__file__", str(tmp_path / "colleague_setup.py"))
    colleague_setup._write_ready(tmp_path, colleague_setup.readiness_identity(tmp_path))
    monkeypatch.setattr(colleague_setup, "_has", lambda module: True)
    _forbid_registration(monkeypatch, "a ready environment must not reinstall or register")
    seen = []
    real_state_root = colleague_setup._launcher_state_root
    def watched():
        seen.append(Path(real_state_root()))
        return seen[-1]
    monkeypatch.setattr(colleague_setup, "_launcher_state_root", watched)
    assert colleague_setup.main() == 0
    assert seen, "main() no longer derives the launcher state root"
    assert all(tmp_path in path.parents for path in seen), (
        "setup state root escaped this court: %s" % seen)
    receipt = isolated_user_state / "assistant-integration.json"
    assert receipt.is_file(), "the receipt must land in this court's state root"
    assert json.loads(receipt.read_text(encoding="utf-8"))["choice"] == "not_asked"


def test_setup_refuses_registration_on_a_redirected_install_root(
        tmp_path, monkeypatch, capsys, isolated_user_state):
    """The seam, not the module: main() hands registration the path the
    person's shortcut opened. Path.resolve() collapses a junction, so the
    resolved root can never carry the reparse point client_mcp_installation
    refuses; main() runs through the junction here and must be refused."""
    import json
    winapi = pytest.importorskip("_winapi")
    real_root = tmp_path / "real"
    _private_environment(real_root, monkeypatch)
    (real_root / "launch_archhub_test.py").write_text("")
    for relative in ("nodelang/native_agent_mcp.py", "runtime/node.exe"):
        target = real_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")
    linked = tmp_path / "ArchHub-link"
    try:
        winapi.CreateJunction(str(real_root), str(linked))
    except (AttributeError, OSError) as exc:
        pytest.skip("native junction unavailable here: %s" % exc)
    colleague_setup._write_ready(real_root, colleague_setup.readiness_identity(real_root))
    monkeypatch.setattr(colleague_setup, "__file__", str(linked / "colleague_setup.py"))
    monkeypatch.setattr(colleague_setup, "_has", lambda module: True)
    _forbid_registration(monkeypatch, "a refused registration must run nothing")
    assert colleague_setup.main() == 0
    assert ("path is redirected: %s" % linked) in capsys.readouterr().out
    receipt = json.loads((isolated_user_state / "assistant-integration.json")
                         .read_text(encoding="utf-8"))
    assert receipt["result"] == "install_incomplete" and receipt["choice"] == "not_asked"


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_interrupted_consent_prompt_leaves_the_offer_open(
        tmp_path, monkeypatch, interruption, isolated_user_state):
    """No answer is not a no: EOF or Ctrl+C at the offer leaves the choice
    not_asked, so the next run asks again. KeyboardInterrupt is not an
    Exception, so an escaping one ends setup after the marker is written and
    the window then says nothing was marked ready over a build that is."""
    import builtins
    import json
    from types import SimpleNamespace
    _private_environment(tmp_path, monkeypatch)
    (tmp_path / "launch_archhub_test.py").write_text("")
    for relative in ("nodelang/native_agent_mcp.py", "runtime/node.exe"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "claude.exe").write_text("")
    (home / ".claude.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(colleague_setup, "__file__", str(tmp_path / "colleague_setup.py"))
    colleague_setup._write_ready(tmp_path, colleague_setup.readiness_identity(tmp_path))
    monkeypatch.setattr(colleague_setup, "_has", lambda module: True)
    _forbid_registration(monkeypatch, "an unanswered offer must register nothing")
    def interrupted(_prompt):
        raise interruption
    monkeypatch.setattr(builtins, "input", interrupted)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    try:
        status = colleague_setup.main()
    except BaseException as exc:  # noqa: BLE001 - the escape is the defect
        raise AssertionError("consent let %s out of setup" % type(exc).__name__) from None
    assert status == 0
    assert (tmp_path / ".archhub-ready").is_file()
    receipt = json.loads((isolated_user_state / "assistant-integration.json")
                         .read_text(encoding="utf-8"))
    assert receipt["choice"] == "not_asked" and receipt["result"] == "ready_to_register"
