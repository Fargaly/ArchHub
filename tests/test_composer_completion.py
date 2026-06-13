"""Tests for THE DRIVE wired into the composer (AgDR-0054).

Proves run_agent_step returns a `completion` verdict: BLOCKS when the
composer's own reply defers / partials its work ("later", TODO, "for now",
partial), ALLOWS when the reply is actually done. Reuses the ONE shared
no-later detector (tools/completion_gate.scan_deferral) — the composer is held
to the same bar as every other agent.

Runs under pytest AND standalone: `python tests/test_composer_completion.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# repo root = parents[1] of this tests dir; expose app + app/agents on the path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "app"))
sys.path.insert(0, str(_ROOT / "app" / "agents"))

import composer_agent  # noqa: E402

# Never probe real hosts during the test — neutralize the status summary.
composer_agent._host_status_summary = lambda *a, **k: ""  # noqa: E305


class StubRouter:
    """Minimal duck-typed LLMRouter: streams its canned text via on_chunk and
    returns an object whose `.text` is that same text. No tools fire."""

    def __init__(self, text=""):
        self.text = text

    def complete(self, history=None, model=None, on_chunk=None,
                 on_tool_invocation=None, extra_tools=None, **kw):
        if on_chunk:
            on_chunk(self.text)

        class _Resp:
            pass
        r = _Resp()
        r.text = self.text
        return r


def test_blocks_on_deferral():
    router = StubRouter(text="I'll finish the walls later")
    r = composer_agent.run_agent_step(user_msg="x", graph={}, router=router)
    assert r["completion"]["action"] == "block"
    assert "later" in r["completion"]["deferral"]


def test_allows_when_done():
    router = StubRouter(text="Done. All walls tagged.")
    r = composer_agent.run_agent_step(user_msg="x", graph={}, router=router)
    assert r["completion"]["action"] == "allow"


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
