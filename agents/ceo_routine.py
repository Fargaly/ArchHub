"""CEO routine — runs hourly via Task Scheduler.

What a CEO does on a 30-day sprint that I (Claude in this session)
am NOT around for: diagnose → plan → act → report. This script is
the no-LLM-tokens version of that loop, runnable from cron.

Each hourly tick:

  1. DIAGNOSE — read last-hour git log + skill_usage retries +
     dept .failed counts. Build a 'pulse' dict.
  2. PLAN — pick the next concrete move from a priority backlog
     (templates below) that hasn't been picked recently.
  3. ACT — write a YAML task into agents/tasks/<dept>/ so the
     dept daemon picks it up on its next 5-min cycle.
  4. REPORT — append to agents/outputs/_ceo/<date>.log + refresh
     the desktop status file via existing notify pipeline.

Hourly cadence. Daily summary at 07:00 UTC = 11:00 AST (the user's
TZ) is fired by a separate Task Scheduler entry that runs this
script with --daily.

Never burns Claude tokens. Reads filesystem + git. Local stable.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
CEO_OUT = REPO / "agents" / "outputs" / "_ceo"
CEO_OUT.mkdir(parents=True, exist_ok=True)
TASKS_ROOT = REPO / "agents" / "tasks"


# ---------------------------------------------------------------------------
# Priority backlog — moves the CEO would queue if no human were watching.
# Each entry: (dept, title, instructions, max_per_week).
# Skipped automatically if an identical title fired in the last
# `max_per_week` * (60*24*7 / 168) minutes. Cheap idempotency.
# ---------------------------------------------------------------------------
BACKLOG: list[dict] = [
    {
        "dept": "eng",
        "title": "Audit chat_window for unhandled exceptions in tool-use loop",
        "instructions": (
            "Read app/chat_window.py and app/llm_router.py. List every "
            "code path that could swallow an LLM exception and leave the "
            "spinner running indefinitely. For each, propose a 3-line "
            "patch: (a) catch, (b) log to archhub.log via existing "
            "logger, (c) surface error in chat bubble. Output: unified "
            "diff."
        ),
        "max_per_week": 1,
    },
    {
        "dept": "rnd",
        "title": "Compare Gemini 2.5 Flash vs Ollama qwen2.5-coder for Revit C# generation",
        "instructions": (
            "Read app/skills/production_seeds.py. Pick stage_walls "
            "and stage_openings from the sketch-to-production Skill. "
            "For each, draft 3 metrics we'd run to compare Gemini Flash "
            "vs local qwen2.5-coder:7b on real Revit C# generation: "
            "tokens-out, retry-rate, transaction-success-rate. Output: "
            "Markdown decision memo recommending which model slots into "
            "which stage."
        ),
        "max_per_week": 1,
    },
    {
        "dept": "docs",
        "title": "Daily standup brief",
        "instructions": (
            "Read DEVELOPMENT_LOG.md, VERSION, and the most recent 24h "
            "of agents/outputs/_reports/*.html. Output one Markdown "
            "page titled '# ArchHub standup — <ISO>' with: shipped "
            "(bullet list of release tags + 1-line each), in-flight "
            "(open YAML tasks), risks (failed tasks + reason), one "
            "imperative next move. Stay under 250 words."
        ),
        "max_per_week": 7,         # daily
    },
    {
        "dept": "watcher",
        "title": "AEC competitor weekly digest",
        "instructions": (
            "Read STRATEGY.md. Write a 5-bullet 'this week in AEC AI' "
            "digest covering: Hypar, TestFit, SWAPP, Cove.tool, Forma. "
            "Each bullet: one signal you'd watch + why it matters for "
            "ArchHub. Cite source urls when known. If nothing notable, "
            "say 'quiet week'."
        ),
        "max_per_week": 1,
    },
    {
        "dept": "ops",
        "title": "Cold-outreach draft pack — Reddit + email",
        "instructions": (
            "Draft 3 short Reddit posts (r/Revit, r/architecture, r/BIM) "
            "introducing ArchHub. Different angle each: (1) free Skill "
            "library replacing pyRevit add-ins, (2) Construction Doc "
            "Sprint Pack story, (3) Outlook + Revit chat integration. "
            "Each post 80-150 words, NO SALES VOICE, lead with a real "
            "user pain point. Plus 1 cold email template (180 words "
            "max) for AEC technology leads at 50-architect firms. "
            "Subject + body. Mark 'DRAFT — founder approval required'."
        ),
        "max_per_week": 1,
    },
    {
        "dept": "qa",
        "title": "Smoke-plan: cold-install of v$LATEST on a clean Windows machine",
        "instructions": (
            "Write a 12-step manual smoke-test plan for installing the "
            "latest ArchHub release on a fresh Windows 11 VM with no "
            "Python pre-installed. Each step: action, expected outcome, "
            "fail-safe if outcome differs. Cover installer download, "
            "Python detection, Revit MCP autoload, first chat reply, "
            "Reality Check green. Output Markdown checklist."
        ),
        "max_per_week": 1,
    },
]


# ---------------------------------------------------------------------------
def _git(*args, default: str = "") -> str:
    creationflags = 0
    si = None
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True,
            timeout=10, creationflags=creationflags, startupinfo=si,
        )
        return (out.stdout or "").strip() or default
    except Exception:
        return default


def _latest_tag() -> str:
    return _git("describe", "--tags", "--abbrev=0", default="v0.0.0")


def _pulse() -> dict:
    """Snapshot of where we are right now."""
    p: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "version": _latest_tag(),
        "commits_24h": len([
            l for l in _git("log", "--since=24 hours ago", "--oneline").splitlines()
            if l.strip()
        ]),
        "depts": {},
    }
    for d in TASKS_ROOT.iterdir() if TASKS_ROOT.exists() else []:
        if not d.is_dir():
            continue
        p["depts"][d.name] = {
            "done":   len(list(d.glob("*.done"))),
            "failed": len(list(d.glob("*.failed"))),
            "open":   len([f for f in d.glob("*.yaml")
                           if not (f.with_suffix(".done").exists()
                                   or f.with_suffix(".failed").exists()
                                   or f.with_suffix(".lock").exists())]),
        }
    return p


def _recent_titles(hours: int = 24 * 7) -> set[str]:
    """Titles of every task we've already filed in the last week."""
    cutoff = (datetime.now() - timedelta(hours=hours)).timestamp()
    out = set()
    if not TASKS_ROOT.exists():
        return out
    for yaml in TASKS_ROOT.rglob("*.yaml"):
        try:
            if yaml.stat().st_mtime < cutoff:
                continue
            data = json.loads(yaml.read_text(encoding="utf-8"))
            t = (data.get("title") or "").strip()
            if t:
                out.add(t)
        except Exception:
            continue
    return out


def _file_task(dept: str, title: str, instructions: str, *,
               priority: int = 50) -> Path:
    """Write a YAML task that the dispatcher will pick up next cycle."""
    d = TASKS_ROOT / dept
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:40].strip("-")
    tid = f"{dept}-{slug}-{stamp}"
    fp = d / f"{tid}.yaml"
    payload = {
        "id": tid,
        "department": dept,
        "title": title,
        "instructions": instructions,
        "priority": priority,
        "inputs": {},
    }
    fp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return fp


def _pick_move(pulse: dict, recent: set[str]) -> dict | None:
    """Pick one entry from BACKLOG that hasn't fired this week.

    Random tie-break so we don't always queue the same dept first."""
    candidates = [b for b in BACKLOG if b["title"] not in recent]
    if not candidates:
        return None
    return random.choice(candidates)


def hourly_tick() -> dict:
    pulse = _pulse()
    recent = _recent_titles(hours=24 * 7)
    move = _pick_move(pulse, recent)
    log_line = {
        "ts": pulse["ts"],
        "pulse": pulse,
        "filed": None,
    }
    if move:
        try:
            fp = _file_task(move["dept"], move["title"], move["instructions"])
            log_line["filed"] = {
                "dept": move["dept"],
                "title": move["title"],
                "path": str(fp.relative_to(REPO)),
            }
        except Exception as ex:
            log_line["filed"] = {"error": str(ex)[:200]}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (CEO_OUT / f"{today}.log").open("a", encoding="utf-8").write(
        json.dumps(log_line) + "\n"
    )
    return log_line


def daily_brief() -> str:
    """Single-page Markdown rolled up from the last 24h CEO log."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = CEO_OUT / f"{today}.log"
    pulse = _pulse()
    filed = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                if d.get("filed") and "title" in d["filed"]:
                    filed.append(d["filed"])
            except Exception:
                continue
    md = [
        f"# ArchHub — daily CEO brief ({today})",
        f"",
        f"**Latest release:** `{pulse['version']}`  ·  "
        f"**Commits last 24h:** {pulse['commits_24h']}",
        "",
        "## Department state",
    ]
    for dept, st in (pulse["depts"] or {}).items():
        md.append(f"  * **{dept}** — done {st['done']}, "
                  f"failed {st['failed']}, open {st['open']}")
    md.extend([
        "",
        "## Tasks I auto-filed last 24h",
    ])
    if not filed:
        md.append("  * (none — backlog templates exhausted for the week)")
    else:
        seen = set()
        for f in filed:
            key = (f.get("dept", ""), f.get("title", ""))
            if key in seen:
                continue
            seen.add(key)
            md.append(f"  * [{f['dept']}] {f['title']}")
    md.extend([
        "",
        "## Next 24h move (founder, in priority order)",
        "  1. Verify v" + pulse["version"].lstrip("v") + " auto-updated to your machine.",
        "  2. Run flagship Skill *Construction doc sprint pack* on a duplicated copy of BA-649. Capture audit Markdown.",
        "  3. Approve / edit any draft outreach posts under `agents/outputs/ops/`.",
        "",
        "_Generated by `agents/ceo_routine.py --daily`. Does not burn Claude tokens._",
    ])
    return "\n".join(md)


def main(argv: list[str]) -> int:
    if "--daily" in argv:
        md = daily_brief()
        out_path = CEO_OUT / f"daily-{datetime.now().strftime('%Y%m%d')}.md"
        out_path.write_text(md, encoding="utf-8")
        # Push to desktop status file via notify pipeline.
        try:
            from notify import write_desktop_status, windows_toast, discord_webhook
            html = (
                "<html><body style='font-family:Inter,Arial,sans-serif;"
                "background:#141413;color:#faf9f5;padding:24px;max-width:780px;"
                "margin:0 auto;'><pre style='white-space:pre-wrap;font-family:"
                "Lora,Georgia,serif;font-size:14px;line-height:1.55'>"
                + md.replace("<", "&lt;") +
                "</pre></body></html>"
            )
            write_desktop_status(html)
            windows_toast("ArchHub daily brief", "Open ~/Desktop/ArchHub-Status.html")
            discord_webhook("ArchHub daily brief",
                            md[:1500],
                            link=None)
        except Exception:
            pass
        # Avoid unicode print on legacy Windows consoles.
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        print(f"[ceo] daily brief -> {out_path}")
        return 0
    # default: hourly
    out = hourly_tick()
    print(json.dumps(out, indent=2)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
