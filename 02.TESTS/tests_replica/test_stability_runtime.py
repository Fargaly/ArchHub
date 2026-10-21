from __future__ import annotations

import os

import pytest

from nodelang.stability_runtime import (
    BrokerLatencyBaselines,
    backoff_delays,
    rotate_root_logs,
    root_cause_line,
)


def test_broker_retry_backoff_has_exponential_jitter():
    draws = iter([0.0, 0.5, 1.0, 0.25])
    delays = backoff_delays(
        4,
        base=0.5,
        factor=2.0,
        cap=3.0,
        jitter=0.2,
        random_fn=lambda: next(draws),
    )

    assert delays == pytest.approx([0.4, 1.0, 2.4, 2.7])
    assert all(delay > 0 for delay in delays)


def test_per_broker_baseline_flags_deviation_not_global_latency():
    baselines = BrokerLatencyBaselines(
        alpha=0.5,
        deviation_factor=3.0,
        min_deviation_ms=100.0,
    )

    assert not baselines.record("coordination", 50.0).flagged
    assert not baselines.record("model", 900.0).flagged
    assert not baselines.record("coordination", 80.0).flagged
    flagged = baselines.record(
        "coordination",
        600.0,
        root_cause_line="broker.py:41 in call",
    )

    assert flagged.flagged
    assert flagged.baseline_ms == pytest.approx(65.0)
    assert flagged.root_cause_line == "broker.py:41 in call"
    assert not baselines.record("model", 950.0).flagged


def test_runtime_log_rotation_keeps_last_n(tmp_path):
    root = tmp_path / "ArchHub"
    root.mkdir()
    (root / "boot-timing.log").write_text("current\n", encoding="utf-8", newline="")
    (root / "boot-timing.log.1").write_text("one\n", encoding="utf-8", newline="")
    (root / "boot-timing.log.2").write_text("two\n", encoding="utf-8", newline="")

    rotate_root_logs(root, keep=2, names=("boot-timing.log",))

    assert not (root / "boot-timing.log").exists()
    assert (root / "boot-timing.log.1").read_text(encoding="utf-8") == "current\n"
    assert (root / "boot-timing.log.2").read_text(encoding="utf-8") == "one\n"
    assert not (root / "boot-timing.log.3").exists()


def test_root_cause_line_names_source_line():
    try:
        raise RuntimeError("clear failure")
    except RuntimeError as exc:
        line = root_cause_line(exc)

    assert os.path.basename(__file__) in line
    assert "RuntimeError: clear failure" in line
