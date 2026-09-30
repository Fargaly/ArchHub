"""Court: the boot screen is drawn from THEME and says how far the boot is.

Frontend brief task 11. The page painted four hex literals of its own, spelled
the wordmark ARCHHUB, and showed an endless sliding bar however far the boot
had got, although /api/universal/boot already reported every phase.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from nodelang import clean_boot_surface
from nodelang.application import THEME
from nodelang.clean_boot_surface import BOOT_PHASES, PAGE, BootProgress

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_every_colour_on_the_page_comes_from_theme():
    colours = {value.lower() for value in HEX.findall(PAGE)}
    assert colours, "the page paints nothing"
    assert colours <= {value.lower() for value in THEME.values()}
    for key in ("bg", "ink", "ink_muted", "line", "accent"):
        assert THEME[key].lower() in colours, key


def test_the_wordmark_reads_archhub_as_on_the_website():
    mark = re.search(r'<div class="mark">(.*?)</div>', PAGE, re.S).group(1)
    assert re.sub(r"<[^>]+>", "", mark) == "ArchHub"


def test_the_phase_plan_is_the_one_the_boot_runs():
    source = Path(clean_boot_surface.__file__).with_name(
        "clean_coordination_service.py").read_text(encoding="utf-8")
    begun = tuple(dict.fromkeys(re.findall(r'_begin\("([^"]+)"\)', source)))
    assert begun == BOOT_PHASES


def test_the_boot_answer_carries_the_phase_total():
    progress = BootProgress()
    assert progress.payload()["total"] == len(BOOT_PHASES)
    progress.begin(BOOT_PHASES[0])
    assert progress.payload()["total"] == len(BOOT_PHASES)


def _view(states):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = re.search(r"(function progressView\(state\)\{.*?\n\})", PAGE, re.S)
    assert script, "the page has no progressView(state)"
    program = script.group(1) + "\nprocess.stdout.write(JSON.stringify(%s.map(progressView)));" % (
        json.dumps(states))
    done = subprocess.run([node, "-e", program], capture_output=True, text=True,
                          encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_bar_is_determinate_once_a_phase_is_known():
    first, second = BOOT_PHASES[0], BOOT_PHASES[1]
    empty = {"phases": [], "total": 2}
    one = {"phases": [{"label": first, "seconds": None}], "total": 2}
    two = {"phases": [{"label": first, "seconds": 3.0},
                      {"label": second, "seconds": None}], "total": 2}
    views = _view([empty, one, two])
    assert views[0]["determinate"] is False
    assert views[1] == {"determinate": True, "fraction": 0.0,
                        "text": "phase 1 of 2 · " + first}
    assert views[2] == {"determinate": True, "fraction": 0.5,
                        "text": "phase 2 of 2 · " + second}
