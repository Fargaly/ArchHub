"""The boot writes where its seconds went. 694s with no account is not allowed."""
from __future__ import annotations

import time
from pathlib import Path

from nodelang.boot_profile import profile_boot

ROOT = Path(__file__).resolve().parents[1]


def _busy(n=6):
    end = time.perf_counter() + 0.6
    while time.perf_counter() < end:
        sum(range(10_000))
    return "booted"


def test_the_sampler_names_the_function_that_ate_the_time(tmp_path):
    assert profile_boot(_busy, state_dir=tmp_path, interval=0.05) == "booted"
    text = (tmp_path / "boot-profile.log").read_text(encoding="utf-8")
    assert "samples every 0.05s" in text
    assert "test_boot_is_measured.py:_busy" in text
    head = text.split("--- leaf")[1]
    assert "_busy" in head, head


def test_the_launcher_boots_through_the_sampler():
    src = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    assert "profile_boot(_boot_unsampled, state_dir=state_dir)" in src
    assert src.index("def _boot():") < src.index("def _boot_unsampled():")
