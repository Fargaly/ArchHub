"""Court: the boot page wears the brand wordmark and never sits still for minutes.

The founder's start (2026-09-30 17:55) sat on "phase 1 of 2" with the bar at 0
for 150s, under a wordmark drawn in a plain bold system sans: the page asked
for Inter, and the boot port serves nothing but the page. Now the brand faces
travel inside the page, the wordmark is the website's (cell_website.py .site-
brand / .site-brand-mark / .site-logo), the line names the restore step the
boot is in, and the fill moves toward the time the phase took last start --
below the next phase's mark until the phase really ends.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from nodelang import boot_profile, cell_website, clean_boot_surface
from nodelang.application import THEME
from nodelang.clean_boot_surface import BOOT_PHASES, PAGE, BootProgress

# Read through the module so each court fails on its own on a tree without them.
boot_step_label = lambda stack: clean_boot_surface.boot_step_label(stack)  # noqa: E731
load_expected_phases = lambda state_dir: clean_boot_surface.load_expected_phases(state_dir)  # noqa: E731
save_phase_durations = lambda progress, state_dir: clean_boot_surface.save_phase_durations(progress, state_dir)  # noqa: E731

FONTS = Path(clean_boot_surface.__file__).resolve().parent / "data" / "website" / "fonts"


def _rule(css: str, selector: str) -> str:
    found = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert found, selector
    return found.group(1)


@pytest.mark.parametrize("name, style", [
    ("instrument-serif-regular.woff2", "normal"), ("instrument-serif-italic.woff2", "italic"),
])
def test_the_brand_faces_travel_inside_the_page(name, style):
    encoded = base64.b64encode((FONTS / name).read_bytes()).decode("ascii")
    face = '@font-face{font-family:"Instrument Serif";font-style:%s;font-weight:400;font-display:block;' \
           'src:url(data:font/woff2;base64,%s) format("woff2")}' % (style, encoded)
    assert face in PAGE


def test_the_wordmark_is_the_websites():
    site_css = cell_website.WEBSITE_CSS
    site_brand = _rule(site_css, ".site-brand")
    assert "font-family:var(--serif)" in site_brand and "text-transform:uppercase" in site_brand
    assert "font-style:italic" in _rule(site_css, ".site-brand-mark")
    word = _rule(PAGE, ".site-brand-word")
    assert word.startswith('font-family:"Instrument Serif"')
    assert "text-transform:uppercase" in word and "letter-spacing:.02em" in word
    mark = _rule(PAGE, ".site-brand-mark")
    assert THEME["accent"] in mark and "font-style:italic" in mark
    markup = re.search(r'<div class="mark">(.*?)</div>', PAGE, re.S).group(1)
    assert '<span>Arch</span><span class="site-brand-mark">Hub</span>' in markup
    assert 'class="site-logo"' in markup and 'class="site-logo-eye"' in markup
    assert "font-weight:650" not in PAGE  # the synthetic bold sans is gone


def _view(states):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = re.search(r"(function progressView\(state\)\{.*?\n\})", PAGE, re.S).group(1)
    program = script + "\nprocess.stdout.write(JSON.stringify(%s.map(progressView)));" % json.dumps(states)
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_fill_rises_within_a_phase_and_stays_below_the_next_mark():
    first, second = BOOT_PHASES
    live = lambda elapsed, expected: {"phases": [{"label": first, "started": 0.0, "seconds": None}],
                                      "total": 2, "elapsed": elapsed, "expected": expected,
                                      "detail": "restoring design system graph"}
    views = _view([live(t, {first: 70}) for t in (0, 5, 30, 70, 150, 900)]
                  + [live(60, {})]
                  + [{"phases": [{"label": first, "started": 0, "seconds": 70.0},
                                 {"label": second, "started": 70, "seconds": None}],
                      "total": 2, "elapsed": 70, "expected": {first: 70}}])
    fills = [view["fraction"] for view in views[:6]]
    assert fills == sorted(fills) and len(set(fills)) == 6, fills
    assert all(fill < 0.5 for fill in fills), fills          # never the next phase's mark
    assert views[0]["estimate"] == " of about 70s"
    assert views[0]["detail"] == " — restoring design system graph"
    assert 0 < views[6]["fraction"] < 0.5 and views[6]["estimate"] == ""   # no record: still moves
    assert views[7]["fraction"] == 0.5                                    # the mark itself, only when phase 1 ended


def test_the_step_is_read_from_the_boot_stack():
    assert boot_step_label(["run", "_boot", "restore_universal_application",
                            "_ensure_design_system_graph", "read_relation"]) == "restoring design system graph"
    assert boot_step_label(["run", "restore_universal_application", "project_grand_map_cells"]) == \
        "restoring grand map cells"
    assert boot_step_label(["x", "load_head", "_load_head_in_transaction"]) == "reading the saved graph"
    assert boot_step_label(["x", "anything"]) == ""
    progress = BootProgress({BOOT_PHASES[0]: 70, "not a phase": 5})
    progress.begin(BOOT_PHASES[0])
    progress.detail("restoring grand map cells")
    payload = progress.payload()
    assert payload["detail"] == "restoring grand map cells"
    assert payload["expected"] == {BOOT_PHASES[0]: 70.0}


def test_the_sampler_hands_the_page_the_stack_outermost_first():
    seen = []
    started = threading.Event()

    def restore_universal_application():
        def _ensure_design_system_graph():
            started.set()
            time.sleep(0.6)
        _ensure_design_system_graph()

    worker = threading.Thread(target=restore_universal_application)
    worker.start()
    started.wait(5)
    sampler = boot_profile.BootSampler(worker.ident, interval=0.05, on_sample=seen.append).start()
    worker.join()
    sampler.stop()
    assert any(boot_step_label(stack) == "restoring design system graph" for stack in seen), seen[:3]


def test_this_starts_seconds_become_the_next_starts_expectation(tmp_path):
    progress = BootProgress()
    progress.begin(BOOT_PHASES[0])
    progress.finish(BOOT_PHASES[0])
    save_phase_durations(progress, tmp_path)
    assert set(load_expected_phases(tmp_path)) == {BOOT_PHASES[0]}
    fallback = tmp_path / "old"
    fallback.mkdir()
    (fallback / "boot-profile.log").write_text("=== boot 2026-09-30 15:31:06\nboot 70s, 264 samples every 0.25s\n",
                                               encoding="utf-8")
    assert load_expected_phases(fallback) == {BOOT_PHASES[0]: 70.0}
    assert load_expected_phases(tmp_path / "missing") == {}
