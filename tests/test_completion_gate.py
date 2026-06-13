"""Tests for THE DRIVE (tools/completion_gate.py) - AgDR-0054.

Proves the gate: allows on all-green, BLOCKS on red-under-cap (re-enters the
agent), ESCALATES (not block) on needs-human or cap-hit (no silent quit, no
infinite grind), and that the real gate runners catch deferral markers.

Runs under pytest AND standalone: `python tests/test_completion_gate.py`.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import completion_gate as cg  # noqa: E402


def _g(name, kind="file_exists", arg="", arg2="", mr=True):
    return cg.Gate(name=name, kind=kind, arg=arg, arg2=arg2, machine_resolvable=mr)


def test_all_green_allows():
    v = cg.evaluate([_g("a"), _g("b")], iterations=0, runner=lambda g: True)
    assert v.action == "allow"


def test_red_under_cap_blocks_and_lists_only_red():
    v = cg.evaluate([_g("a"), _g("b")], iterations=0, cap=5,
                    runner=lambda g: g.name != "b")
    assert v.action == "block"
    assert v.red == ["b"]
    assert "b" in v.reason


def test_needs_human_escalates_not_blocks():
    v = cg.evaluate([_g("human", mr=False)], iterations=0, runner=lambda g: False)
    assert v.action == "escalate"
    assert "human" in v.reason


def test_cap_hit_escalates_no_infinite_grind():
    v = cg.evaluate([_g("a")], iterations=99, cap=3, runner=lambda g: False)
    assert v.action == "escalate"


def test_real_grep_clean_catches_deferral_marker():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "x.py").write_text("ok\n# TODO(later) finish this\n", encoding="utf-8")
        g = _g("no-defer", kind="grep_clean", arg=r"TODO\(later\)", arg2="x.py")
        assert cg.run_gate(g, root) is False  # marker present -> RED


def test_real_grep_clean_passes_when_clean():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "x.py").write_text("all done\n", encoding="utf-8")
        g = _g("no-defer", kind="grep_clean", arg=r"TODO\(later\)", arg2="x.py")
        assert cg.run_gate(g, root) is True


def test_real_file_exists():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "present").write_text("x", encoding="utf-8")
        assert cg.run_gate(_g("f", kind="file_exists", arg="present"), root) is True
        assert cg.run_gate(_g("f", kind="file_exists", arg="absent"), root) is False


def test_manual_gate_is_never_green():
    assert cg.run_gate(_g("m", kind="manual", mr=False), Path(".")) is False


def test_partial_parent_stays_red_one_child_red_blocks():
    # "no partial": if any child gate is red, the whole is not allowed.
    children = [_g("c1"), _g("c2"), _g("c3")]
    v = cg.evaluate(children, iterations=0, cap=9, runner=lambda g: g.name != "c3")
    assert v.action == "block" and v.red == ["c3"]


def test_load_tolerates_bom_and_parses():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "led.json"
        p.write_text(
            '﻿{"gates":[{"name":"x","kind":"manual","machine_resolvable":false}],'
            '"iterations":2}',
            encoding="utf-8",
        )
        gates, iters, cap = cg._load(p)
        assert gates[0].name == "x" and iters == 2


def test_scan_deferral_flags_bare_later():
    assert "later" in cg.scan_deferral("I'll wire the rest later")


def test_scan_deferral_flags_todo_and_partial():
    found = cg.scan_deferral("partial pass for now; TODO finish")
    assert "todo" in found and ("partial" in found or "for now" in found)


def test_scan_deferral_clean_when_done():
    assert cg.scan_deferral("All gates green; nothing outstanding.") == []


def test_scan_deferral_exempts_justified_hold():
    assert cg.scan_deferral("S5 rollout safety-gated: after red-team") == []


def _run_standalone() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
