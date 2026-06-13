"""Tests for the active-work ledger producer (tools/active_work.py) — AgDR-0054.

Proves the producer/consumer loop is real: register done-gates, the gate BLOCKS
while a gate is red, then ALLOWS once it's green; bump records re-entries; clear
closes the job. Runs under pytest AND standalone: `python tests/test_active_work.py`.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import active_work as aw   # noqa: E402
import completion_gate as cg   # noqa: E402


def test_register_status_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "aw.json"
        aw.register([{"name": "a", "kind": "manual", "machine_resolvable": False}],
                    scope="demo", cap=5, path=p)
        s = aw.status(p)
        assert s["scope"] == "demo" and s["cap"] == 5
        assert s["gates"][0]["name"] == "a" and s["iterations"] == 0


def test_drive_blocks_then_allows_via_ledger():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "artifact.txt"
        p = Path(d) / "aw.json"
        aw.register([{"name": "artifact", "kind": "file_exists",
                      "arg": str(target)}], path=p)
        s = aw.status(p)
        gates = [cg.Gate(**g) for g in s["gates"]]
        v = cg.evaluate(gates, s["iterations"], s["cap"],
                        runner=lambda g: cg.run_gate(g, Path(d)))
        assert v.action == "block"          # artifact missing -> refuse stop
        target.write_text("done", encoding="utf-8")
        v2 = cg.evaluate(gates, s["iterations"], s["cap"],
                         runner=lambda g: cg.run_gate(g, Path(d)))
        assert v2.action == "allow"         # artifact present -> allow stop


def test_bump_and_clear():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "aw.json"
        aw.register([], path=p)
        assert aw.bump(p) == 1
        assert aw.bump(p) == 2
        assert aw.clear(p) is True
        assert aw.status(p) is None
        assert aw.clear(p) is False         # already gone


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
