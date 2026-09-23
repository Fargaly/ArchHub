"""RELEASE GATE: a colleague's first-ever boot is admitted by the commit gate.

The graph commit gate (nodelang/commit_intent.py) refuses every commit that
has no closed-set intent once the application has been constructed. Two
writes of a first boot run after construction and are the install of that
machine, so each commits under the admitted migration/install intent:

* the launcher's first-run pipeline seed. Without it every seeded card is
  refused and a new colleague opens an empty canvas while the log still says
  the seed was "checked";
* the registration of this machine's BABOOM device (BABOOM starts by default).
  Without it BABOOM's attachment is refused with CommitRefused.

This court boots the REAL launcher (launch_archhub_test.py) in a separate
process against a fresh profile with no graph: its own APPDATA, LOCALAPPDATA
and state directory, a free single-instance port, offscreen Qt (no window on
any desktop).

ARCHHUB_COURT_SOURCE selects the source under test (default: this checkout).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import site
import socket
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOOT_TIMEOUT_SECONDS = 600

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="the launcher is the Windows desktop entry"
)


def _source_under_test() -> Path:
    configured = os.environ.get("ARCHHUB_COURT_SOURCE", "").strip()
    source = Path(configured).resolve() if configured else ROOT
    if not (source / "launch_archhub_test.py").is_file():
        pytest.fail("source under test has no launcher: %s" % source)
    return source


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _first_boot(tmp_path: Path, *, window: bool, until: str) -> str:
    """Boot the real launcher on a fresh profile; return its log at ``until``."""
    source = _source_under_test()
    profile = tmp_path / "profile"
    state = profile / "state"
    for folder in ("appdata", "localappdata", "temp"):
        (profile / folder).mkdir(parents=True)
    # The profile moves APPDATA; keep this interpreter's user packages (Qt).
    paths = [str(source), site.getusersitepackages()]
    environment = dict(os.environ)
    environment.update({
        "APPDATA": str(profile / "appdata"),
        "LOCALAPPDATA": str(profile / "localappdata"),
        "TEMP": str(profile / "temp"),
        "TMP": str(profile / "temp"),
        "ARCHHUB_TEST_STATE_DIR": str(state),
        "ARCHHUB_TEST_LOCK_PORT": str(_free_port()),
        "ARCHHUB_VERIFY_NO_GPU": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": os.pathsep.join(paths),
    })
    if not window:
        environment["ARCHHUB_TEST_NO_OPEN"] = "1"
    assert not (state / "archhub-test.universal.sqlite3").exists()
    process = subprocess.Popen(
        [sys.executable, str(source / "launch_archhub_test.py")],
        cwd=str(source), env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log_path = state / "launcher.log"
    text = ""
    try:
        deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            if until in text or process.poll() is not None:
                break
            time.sleep(1)
    finally:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True)
        process.wait(timeout=60)
    assert "  first boot  : True" in text, text[-3000:]
    assert re.search(r"^  booted in \d+s$", text, re.M), text[-3000:]
    return text


def test_first_run_seed_commits_under_admitted_install_intent(tmp_path):
    text = _first_boot(tmp_path, window=False, until="  pipeline   :")
    seed = re.search(
        r"^  seed       : (\d+) declared · (\d+) placed · (\d+) adopted · "
        r"(\d+) row\(s\) completed · (\d+) skipped(.*)$", text, re.M)
    assert seed, text[-3000:]
    declared, placed, _adopted, _completed, skipped = map(int, seed.groups()[:5])
    assert skipped == 0 and placed == declared > 0, seed.group(0)
    assert "pipeline   : initial seed checked" in text, text[-3000:]
    assert "graph commit refused" not in text, text[-3000:]


def test_first_boot_registers_the_baboom_device_under_install_intent(tmp_path):
    text = _first_boot(tmp_path, window=True, until="  BABOOM     :")
    baboom = re.findall(r"^  BABOOM     : .*$", text, re.M)
    assert baboom, text[-3000:]
    assert baboom[0] == "  BABOOM     : attached (signed agent session)", baboom
    assert "CommitRefused" not in text, text[-3000:]
