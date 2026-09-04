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
    ready_at = bat.index("echo ready> \".archhub-ready\"")
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
    assert '"%ARCHHUB_PY%" colleague_setup.py' in bat


def test_setup_exit_code_is_read_outside_any_block_and_deps_are_pinned():
    bat = (ROOT / "installer" / "ArchHub.bat").read_text(encoding="utf-8")
    # `%errorlevel%` inside a parenthesised block expands at parse time (always 0).
    read = bat.index('set "ARCHHUB_SETUP_RC=%errorlevel%"')
    assert bat.rfind("(", 0, read) < bat.rfind(")", 0, read) or bat.rfind("(", 0, read) == -1
    assert bat.index('echo ready>') > bat.index('if not "%ARCHHUB_SETUP_RC%"=="0"')
    setup = (ROOT / "colleague_setup.py").read_text(encoding="utf-8")
    assert '"-r", str(pinned)' in setup and '"--user", *missing' not in setup
