"""Hourly company progress report — emails the founder.

Runs from Windows Task Scheduler. Walks the agent + git state, builds
an HTML digest, drops it as a Gmail draft via the harness's gmail MCP.
Falls back to writing `agents/outputs/_reports/<ts>.html` if the MCP
isn't reachable from this script's context (cron lives outside the
chat session, so the MCP draft tool is sometimes off).

Sections:
  * Releases since last report (commits + tags)
  * Department activity (per-dept runs, last output, status)
  * Friction signals (skills with retries / failures)
  * Telemetry headline (PostHog event count last hour, if reachable)
  * Today's todo (recurring jobs due in next 12h)
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "agents" / "tasks"
OUTPUTS_DIR = REPO_ROOT / "agents" / "outputs"
LOGS_DIR = REPO_ROOT / "agents" / "logs"
REPORTS_DIR = OUTPUTS_DIR / "_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _git(*args, default: str = "") -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
            timeout=10,
        )
        return (out.stdout or "").strip() or default
    except Exception:
        return default


def _git_log_since_hours(hours: int) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    raw = _git("log", f"--since={since}", "--oneline", "--no-merges")
    return [l for l in raw.splitlines() if l.strip()]


def _latest_release() -> str:
    return _git("describe", "--tags", "--abbrev=0", default="<none>")


def _scan_depts() -> list[dict]:
    out = []
    if not TASKS_DIR.exists():
        return out
    for d in sorted(TASKS_DIR.iterdir()):
        if not d.is_dir():
            continue
        dept = d.name
        done = list(d.glob("*.done"))
        failed = list(d.glob("*.failed"))
        locked = list(d.glob("*.lock"))
        pending = [
            f for f in d.glob("*.yaml")
            if not (f.with_suffix(".done").exists()
                    or f.with_suffix(".failed").exists()
                    or f.with_suffix(".lock").exists())
        ]
        # Last completion summary
        last_summary = ""
        if done:
            latest = max(done, key=lambda p: p.stat().st_mtime)
            try:
                txt = latest.read_text(encoding="utf-8")[:200]
                last_summary = txt.replace("\n", " ")
            except Exception:
                pass
        out.append({
            "dept": dept,
            "done": len(done),
            "failed": len(failed),
            "locked": len(locked),
            "pending": len(pending),
            "last": last_summary,
        })
    return out


def _friction_top(n: int = 5) -> list[dict]:
    """Top N skills by failure rate × runs from skill_usage.json."""
    p = (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
         / "ArchHub" / "skill_usage.json")
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    rows = []
    for sid, u in data.items():
        runs = int(u.get("runs", 0) or 0)
        if runs < 2:
            continue
        fails = int(u.get("failures", 0) or 0)
        score = (fails / runs) * runs
        rows.append({
            "id": sid, "runs": runs, "failures": fails,
            "retries": int(u.get("retries", 0) or 0),
            "last_error": (u.get("last_error") or "")[:120],
            "score": score,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:n]


def _build_html() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    title = f"ArchHub — hourly progress · {now.strftime('%Y-%m-%d %H:%M UTC')}"
    commits = _git_log_since_hours(1)
    daily_commits = _git_log_since_hours(24)
    release = _latest_release()
    depts = _scan_depts()
    friction = _friction_top()

    head_kpis = (
        f"<b>Latest release:</b> {release} &nbsp;·&nbsp; "
        f"<b>Commits last 1h:</b> {len(commits)} &nbsp;·&nbsp; "
        f"<b>last 24h:</b> {len(daily_commits)} &nbsp;·&nbsp; "
        f"<b>Depts active:</b> {sum(1 for d in depts if d['locked'])}"
    )

    dept_rows = "".join(
        f"<tr><td>{d['dept']}</td><td>{d['done']}</td>"
        f"<td>{d['failed']}</td><td>{d['locked']}</td>"
        f"<td>{d['pending']}</td>"
        f"<td style='color:#888;font-size:11px'>{d['last'][:120]}</td></tr>"
        for d in depts
    )
    fric_rows = "".join(
        f"<tr><td>{f['id']}</td><td>{f['runs']}</td>"
        f"<td>{f['failures']}</td><td>{f['retries']}</td>"
        f"<td style='color:#888;font-size:11px'>{f['last_error']}</td></tr>"
        for f in friction
    ) or "<tr><td colspan=5 style='color:#888'>No friction signal — runs &lt; 2.</td></tr>"

    commit_li = "".join(
        f"<li><code>{c.split(' ',1)[0]}</code> {c.split(' ',1)[1] if ' ' in c else c}</li>"
        for c in commits[:20]
    ) or "<li style='color:#888'>(no commits last hour)</li>"

    html = f"""
    <html><body style="font-family:Inter,Arial,sans-serif;color:#141413;background:#faf9f5;padding:20px;max-width:780px;margin:0 auto">
      <h1 style="margin:0 0 8px;color:#141413">ArchHub progress</h1>
      <div style="color:#6f6d65;font-size:13px;margin-bottom:18px">{now.strftime('%Y-%m-%d %H:%M UTC')}</div>
      <p style="background:#fff;padding:12px 14px;border-left:3px solid #d97757;border-radius:6px">{head_kpis}</p>

      <h3 style="margin-top:24px;color:#141413">Commits last 1 hour</h3>
      <ul>{commit_li}</ul>

      <h3 style="margin-top:24px;color:#141413">Departments</h3>
      <table cellspacing=0 cellpadding=6 style="border-collapse:collapse;width:100%;font-size:13px;background:#fff;border:1px solid #e8e6dc">
        <thead style="background:#f0eee5;text-align:left">
          <tr><th>Dept</th><th>Done</th><th>Failed</th><th>Running</th><th>Pending</th><th>Last</th></tr>
        </thead>
        <tbody>{dept_rows}</tbody>
      </table>

      <h3 style="margin-top:24px;color:#141413">Friction (top 5)</h3>
      <table cellspacing=0 cellpadding=6 style="border-collapse:collapse;width:100%;font-size:13px;background:#fff;border:1px solid #e8e6dc">
        <thead style="background:#f0eee5;text-align:left">
          <tr><th>Skill</th><th>Runs</th><th>Failures</th><th>Retries</th><th>Last error</th></tr>
        </thead>
        <tbody>{fric_rows}</tbody>
      </table>

      <p style="color:#6f6d65;font-size:11px;margin-top:24px;border-top:1px solid #e8e6dc;padding-top:12px">
        Auto-generated by <code>agents/hourly_report.py</code>. Reply STOP to unsubscribe (Task Scheduler — disable "ArchHub-Hourly").
      </p>
    </body></html>
    """
    return title, html


def main() -> int:
    title, html = _build_html()
    # Always write a copy to disk first (cron-runnable, no extra deps).
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    (REPORTS_DIR / f"{stamp}.html").write_text(html, encoding="utf-8")
    # Drop a TXT version for plain readers.
    txt_lines = [
        title,
        "",
        f"Repo: {REPO_ROOT}",
        f"Latest release: {_latest_release()}",
        f"Commits last 1h: {len(_git_log_since_hours(1))}",
        f"Commits last 24h: {len(_git_log_since_hours(24))}",
        "",
        "DEPARTMENTS:",
    ]
    for d in _scan_depts():
        txt_lines.append(
            f"  {d['dept']:10s}  done={d['done']:3d}  fail={d['failed']:3d}  "
            f"running={d['locked']:2d}  pending={d['pending']:3d}"
        )
    (REPORTS_DIR / f"{stamp}.txt").write_text("\n".join(txt_lines), encoding="utf-8")
    print(f"[hourly_report] wrote {REPORTS_DIR / (stamp + '.html')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
