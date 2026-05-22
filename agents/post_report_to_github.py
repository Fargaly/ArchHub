"""Post one status report as a comment on a GitHub issue.

Used as the no-email-provider fallback: the user gets emails for free
via GitHub's notification system (issue comment → author + watchers
auto-emailed). No Resend / Brevo / SMTP signup required.

Usage:
    python -m agents.post_report_to_github --issue 20
    python -m agents.post_report_to_github --issue 20 --owner Fargaly --repo ArchHub
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Make the import path agents-aware whether we're run as a module or a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _format_markdown(report: dict) -> str:
    lines: list[str] = []
    subj = report.get("subject", "[ArchHub] status")
    lines.append(f"### {subj}")
    lines.append("")
    lines.append(f"**Generated:** {report.get('ts', '?')}  ")
    lines.append(f"**Report ID:** `{report.get('id', '?')}`")
    lines.append("")

    # Agents
    ag = report.get("agents", {}) or {}
    lines.append("#### Agents")
    lines.append(f"- Pending tasks: **{ag.get('pending_total', '?')}**")
    by_dept = ag.get("pending_by_dept") or {}
    if by_dept:
        lines.append("- By department:")
        for d, n in sorted(by_dept.items()):
            if n:
                lines.append(f"  - {d}: {n}")
    lines.append("")

    # Roadmap
    rm = report.get("roadmap", {}) or {}
    lines.append("#### Roadmap")
    lines.append(f"- Next 7 days pending: **{rm.get('pending_next_7d', 0)}**")
    lines.append(f"- Shipped last 24h: **{rm.get('shipped_24h', 0)}**")
    lines.append("")

    # Infrastructure
    inf = report.get("infrastructure", {}) or {}
    if inf:
        lines.append("#### Infrastructure")
        for k, v in inf.items():
            if isinstance(v, dict):
                if "reachable" in v:
                    status = "GREEN" if v.get("reachable") else "RED"
                    url = v.get("url") or ""
                    lines.append(f"- {k}: **{status}** {url}".rstrip())
                elif "available" in v:
                    status = "GREEN" if v.get("available") else "RED"
                    lines.append(f"- {k}: **{status}**")
        lines.append("")

    # Cost
    cost = report.get("cost", {}) or {}
    if cost and not (len(cost) == 1 and cost.get("error")):
        lines.append("#### Cost")
        for k, v in cost.items():
            if k == "error":
                continue
            lines.append(f"- {k}: {v}")
        lines.append("")

    # Errors (boot log tail)
    er = report.get("errors", {}) or {}
    tail = er.get("boot_log_tail") or []
    if tail:
        lines.append("#### Errors (boot.log tail)")
        lines.append("```")
        for line in tail[-5:]:
            lines.append(str(line)[:200])
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append(
        f"<sub>Posted by agents/cloud_runner.py · {report.get('id', '?')}</sub>"
    )
    return "\n".join(lines)


def post(*, issue: int, owner: str = "Fargaly",
        repo: str = "ArchHub") -> dict:
    """Generate a fresh report + post it as a comment on the issue.

    Returns {ok, status, body}. Requires `gh` CLI authed with `repo` scope.
    """
    from agents import status_report
    report = status_report.generate_report()
    body = _format_markdown(report)
    # Write to a temp file to avoid shell-quoting issues.
    tmp = REPO_ROOT / "agents" / "state" / "_last_report.md"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(body, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["gh", "issue", "comment", str(issue),
             "--repo", f"{owner}/{repo}",
             "--body-file", str(tmp)],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return {"ok": False, "status": 0,
                "body": "gh CLI not on PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": 0, "body": "gh timeout"}
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "status": proc.returncode,
        "body": (proc.stdout or proc.stderr or "").strip(),
        "subject": report.get("subject", ""),
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", type=int, required=True,
                     help="GitHub issue number to comment on")
    ap.add_argument("--owner", default="Fargaly")
    ap.add_argument("--repo", default="ArchHub")
    ns = ap.parse_args(argv)
    res = post(issue=ns.issue, owner=ns.owner, repo=ns.repo)
    print(json.dumps(res, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
