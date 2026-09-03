"""Background loop that posts a status report comment every N minutes.

Stdlib-only daemon. Used when no email provider is configured — relies
on GitHub's notification system to deliver each comment to the issue
subscribers' email inbox.

Stop with Ctrl-C or kill the process. Writes a heartbeat file so the
caller can tell it's alive.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.post_report_to_github import post  # noqa: E402


STATE_DIR = REPO_ROOT / "agents" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
HEARTBEAT = STATE_DIR / "github_report_loop_heartbeat.txt"
LOG = STATE_DIR / "github_report_loop.log"


_stop = False


def _sigterm(_signum, _frame):
    global _stop
    _stop = True


def _log(line: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{ts}  {line}\n")
    print(f"{ts}  {line}", flush=True)


def run(*, issue: int, interval_minutes: int,
        owner: str = "Fargaly", repo: str = "ArchHub") -> int:
    """Forever loop. Returns when SIGTERM/SIGINT received."""
    signal.signal(signal.SIGINT, _sigterm)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _sigterm)
        except (ValueError, OSError):
            pass

    interval_seconds = max(60, int(interval_minutes) * 60)
    _log(f"start · issue={issue} interval={interval_minutes}min · "
         f"GH_TOKEN={'set' if os.environ.get('GH_TOKEN') else 'unset'}")

    cycles = 0
    while not _stop:
        try:
            res = post(issue=issue, owner=owner, repo=repo)
            if res.get("ok"):
                _log(f"posted ok · cycle={cycles} · "
                     f"subject={res.get('subject', '')!r} · "
                     f"url={res.get('body', '')}")
            else:
                _log(f"post failed · cycle={cycles} · "
                     f"status={res.get('status')} · "
                     f"body={(res.get('body') or '')[:200]}")
        except Exception as ex:
            _log(f"loop exception · {type(ex).__name__}: {ex}")

        cycles += 1
        # Heartbeat — used by /healthz when running inside cloud_runner.
        try:
            HEARTBEAT.write_text(
                f"{datetime.now(timezone.utc).isoformat()}\n{cycles}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

        # Sleep with short polls so SIGTERM is responsive.
        slept = 0
        while slept < interval_seconds and not _stop:
            time.sleep(2)
            slept += 2

    _log(f"stop · cycles={cycles}")
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", type=int,
                     default=int(os.environ.get("ARCHHUB_REPORT_GH_ISSUE", "20")))
    ap.add_argument("--interval", type=int,
                     default=int(os.environ.get("ARCHHUB_REPORT_INTERVAL_MIN", "10")))
    ap.add_argument("--owner", default="Fargaly")
    ap.add_argument("--repo",  default="ArchHub")
    ns = ap.parse_args(argv)
    return run(issue=ns.issue, interval_minutes=ns.interval,
                owner=ns.owner, repo=ns.repo)


if __name__ == "__main__":
    raise SystemExit(main())
