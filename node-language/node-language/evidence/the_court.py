"""THE court: one judge over the running program, the way the founder uses it.

Runs nodelang/the_court.cjs (real Chromium, live owner, founder gestures)
and writes evidence/the-court-verdict.json. Every check carries the measured
number and the bar it was judged against; nothing here is a hand-maintained
status. Exit 0 iff every check passes.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VERDICT = HERE / "the-court-verdict.json"


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("node is unavailable; the court cannot sit", file=sys.stderr)
        return 2
    env = os.environ.copy()
    env.setdefault("NODE_PATH", str(ROOT / "node_modules"))
    env.setdefault("ARCHHUB_COURT_URL", "http://127.0.0.1:8475")
    env["ARCHHUB_COURT_OUT"] = str(VERDICT)
    finished = subprocess.run(
        [node, str(ROOT / "nodelang" / "the_court.cjs")],
        env=env, capture_output=True, text=True, timeout=900,
    )
    try:
        verdict = json.loads(finished.stdout)
    except ValueError:
        print(finished.stdout[-2000:], file=sys.stderr)
        print(finished.stderr[-2000:], file=sys.stderr)
        return 2
    for check in verdict.get("checks", []):
        print("%s  %-56s %s  (bar: %s)" % (
            "PASS" if check["pass"] else "FAIL",
            check["name"][:56], str(check["measured"])[:60], check["bar"][:50],
        ))
    print("THE COURT: passed=%s failed=%s" % (verdict.get("passed"), verdict.get("failed")))
    if verdict.get("error"):
        print("ERROR: " + verdict["error"][:600], file=sys.stderr)
        return 1
    return 0 if verdict.get("failed") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
