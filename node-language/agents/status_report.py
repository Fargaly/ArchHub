"""Founder status report — every-N-min ArchHub digest.

`generate_report()` returns a structured dict + a self-contained HTML
rendering (inline styles only — Gmail strips <style>/<link> tags).

The report mines the same surfaces the dashboard endpoint already
exposes — heartbeat, queue depth, last outputs — and joins them with:

  * business signals    — cloud_backend.db (users, companies, usage_log)
  * infra signals       — /healthz reachability for cloud_backend +
                          agents, GitHub Actions status (best-effort)
  * cost signals        — Anthropic spend derived from usage_log token
                          totals, projected over 30 days
  * roadmap signals     — pending vs done counts from docs/ROADMAP.md
  * error signals       — tail of boot.log + Sentry hook (stubbed when
                          SENTRY_DSN absent)

Everything is best-effort. Each signal block catches its own errors
and emits an `error` field rather than killing the report — the
daemon must NEVER crash because the report builder couldn't reach
GitHub.

Run directly to dump JSON of the latest report:
    python -m agents.status_report
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from html import escape as _esc
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Filesystem roots. The cloud_runner rebinds queue + log roots onto
# /data when the persistent volume is mounted; we mirror that here so
# the report sees the same paths the daemon writes to.
REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_ROOT_ENV = os.environ.get("ARCHHUB_AGENTS_DATA_ROOT")
if _DATA_ROOT_ENV:
    DATA_ROOT = Path(_DATA_ROOT_ENV)
else:
    DATA_ROOT = REPO_ROOT / "agents"

TASKS_DIR = DATA_ROOT / "tasks"
OUTPUTS_DIR = DATA_ROOT / "outputs"
LOGS_DIR = DATA_ROOT / "logs"
HEARTBEAT_PATH = DATA_ROOT / "heartbeat.txt"
ROADMAP_PATH = REPO_ROOT / "docs" / "ROADMAP.md"


def _boot_log_path() -> Path:
    """Resolve the boot.log path per AgDR-0047 §B1 fallback chain.

    Writer (app/main.py) emits to ``%LOCALAPPDATA%/ArchHub/logs/boot.log``.
    Reader candidates: that LOCALAPPDATA path AND ``REPO_ROOT/boot.log``
    (back-compat during migration). Pick the candidate with the most
    recent mtime among those that exist. If neither exists, return the
    LOCALAPPDATA candidate (consumers handle non-existence themselves).
    """
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "ArchHub" / "logs" / "boot.log",
        REPO_ROOT / "boot.log",
    ]
    existing = [c for c in candidates if c.exists()]
    if not existing:
        return candidates[0]
    return max(existing, key=lambda p: p.stat().st_mtime)


# Back-compat constant — kept so any external import doesn't break, but
# always evaluated lazily via the resolver. Some callers read this at
# module import, so we return the FRESHEST candidate at import time.
BOOT_LOG_PATH = _boot_log_path()


# ---------------------------------------------------------------------------
# Pricing — Anthropic public list rates as of 2026-05.
# Haiku is the workforce default; Sonnet/Opus only get used by R&D /
# QA reasoning runs. The estimate is intentionally rough — we just
# want a ballpark $/day, not a billing-grade total.
ANTHROPIC_RATES_PER_M: dict[str, tuple[float, float]] = {
    # model_id_prefix → (input_$/M_toks, output_$/M_toks)
    "claude-haiku":  (0.25, 1.25),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus":   (15.00, 75.00),
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe(fn, *args, **kwargs):
    """Run a section builder; swallow + serialise any exception."""
    try:
        return fn(*args, **kwargs)
    except Exception as ex:  # noqa: BLE001 — best-effort by design
        return {"error": f"{type(ex).__name__}: {ex}"}


# ---------------------------------------------------------------------------
# Business signals — cloud_backend SQLite
# ---------------------------------------------------------------------------
def _open_backend_db() -> Optional[sqlite3.Connection]:
    """Return a read-only connection to cloud_backend's SQLite, or None.

    We DON'T import cloud_backend.config because that module fires its
    own dotenv load and pulls in the whole billing/stripe surface. The
    DB path can come from ARCHHUB_BACKEND_DB_URL or fall back to
    cloud_backend's default ./archhub_cloud.db.
    """
    url = (os.environ.get("ARCHHUB_BACKEND_DB_URL")
           or os.environ.get("DATABASE_URL")
           or str(REPO_ROOT / "cloud_backend" / "archhub_cloud.db"))
    p = Path(url)
    if not p.exists():
        # Common alt location when running from cloud_backend/.
        alt = REPO_ROOT / "archhub_cloud.db"
        if alt.exists():
            p = alt
        else:
            return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.OperationalError:
        return None


def _section_business() -> dict:
    """Signups + paying customers + churn from the cloud_backend DB."""
    con = _open_backend_db()
    if con is None:
        return {
            "available": False,
            "reason": "backend_db_unreachable",
            "new_signups_24h": 0,
            "new_paying_24h": 0,
            "active_subs": 0,
            "mrr_delta_24h_usd": 0,
            "churn_7d": 0,
        }
    now = int(time.time())
    day = now - 86_400
    week = now - 7 * 86_400
    try:
        signups_24h = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE created_at >= ?", (day,),
        ).fetchone()["n"]
        # "paying" = user.plan != 'trial' AND period_end > now. Conservative.
        paying_24h = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE plan != 'trial'"
            " AND created_at >= ?", (day,),
        ).fetchone()["n"]
        active = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE plan != 'trial'"
            " AND (period_end IS NULL OR period_end > ?)", (now,),
        ).fetchone()["n"]
        # MRR delta = sum of plan prices for users who flipped to paid
        # in the last 24h. We use a coarse map; for accurate MRR pull
        # Stripe directly. Plan price is the *list* price, not what
        # they actually paid (no discount handling).
        rates = {"solo": 19, "studio": 79, "firm": 299}
        mrr_rows = con.execute(
            "SELECT plan, COUNT(*) AS n FROM users WHERE plan != 'trial'"
            " AND created_at >= ? GROUP BY plan", (day,),
        ).fetchall()
        mrr_delta = sum(rates.get(r["plan"], 0) * int(r["n"])
                        for r in mrr_rows)
        # Churn proxy = users whose period_end fell into the last 7d
        # and who are now back on trial. We don't track cancellations
        # in their own table yet.
        churn_7d = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE plan = 'trial'"
            " AND period_end IS NOT NULL AND period_end >= ?"
            " AND period_end <= ?", (week, now),
        ).fetchone()["n"]
        return {
            "available": True,
            "new_signups_24h": int(signups_24h),
            "new_paying_24h": int(paying_24h),
            "active_subs": int(active),
            "mrr_delta_24h_usd": int(mrr_delta),
            "churn_7d": int(churn_7d),
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Infra signals
# ---------------------------------------------------------------------------
def _http_get_json(url: str, *, timeout: float = 3.0,
                  headers: Optional[dict] = None) -> Optional[dict]:
    """Stdlib HTTP GET → JSON. Returns None on any failure (DNS, 5xx,
    parse error). Used for /healthz + GitHub Actions probes."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                return None
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _http_get_status(url: str, *, timeout: float = 3.0) -> Optional[int]:
    """Status code only — for cheap reachability probes."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as ex:
        return int(ex.code)
    except (urllib.error.URLError, TimeoutError):
        return None


def _section_infrastructure() -> dict:
    """Reachability checks for cloud_backend, agents daemon, CI, Sentry."""
    backend_url = os.environ.get("ARCHHUB_BACKEND_HEALTHZ",
                                 "http://127.0.0.1:8000/healthz")
    agents_url = os.environ.get("ARCHHUB_AGENTS_HEALTHZ",
                                "http://127.0.0.1:8080/healthz")
    backend_status = _http_get_status(backend_url, timeout=2.0)
    agents_status = _http_get_status(agents_url, timeout=2.0)

    # GitHub Actions latest run on the default branch. Skipped unless
    # both repo + token are configured.
    ci = {"available": False, "status": None}
    repo = os.environ.get("ARCHHUB_GH_REPO")  # e.g. "fargaly/ArchHub"
    if repo:
        ci_url = (f"https://api.github.com/repos/{repo}"
                  f"/actions/runs?branch=main&per_page=1")
        hdrs = {"Accept": "application/vnd.github+json"}
        gh_tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if gh_tok:
            hdrs["Authorization"] = f"Bearer {gh_tok}"
        body = _http_get_json(ci_url, timeout=4.0, headers=hdrs)
        if body and body.get("workflow_runs"):
            run = body["workflow_runs"][0]
            ci = {
                "available": True,
                "status": run.get("conclusion") or run.get("status"),
                "sha": (run.get("head_sha") or "")[:7],
                "url": run.get("html_url"),
            }

    # Sentry error rate — only if DSN-keyed API token is set. We don't
    # call Sentry directly for v1; just expose whether the wiring is
    # there for follow-up. The status section flags missing config so
    # the founder sees it and decides.
    sentry = {
        "available": bool(os.environ.get("SENTRY_API_TOKEN")),
        "error_count_1h": None,
    }
    return {
        "backend_healthz": {
            "url": backend_url,
            "status_code": backend_status,
            "reachable": backend_status is not None and backend_status < 500,
        },
        "agents_healthz": {
            "url": agents_url,
            "status_code": agents_status,
            "reachable": agents_status is not None and agents_status < 500,
        },
        "ci": ci,
        "sentry": sentry,
    }


# ---------------------------------------------------------------------------
# Agent activity — pending tasks by dept, completed today, last outputs
# ---------------------------------------------------------------------------
def _scan_pending_by_dept(tasks_root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not tasks_root.exists():
        return out
    for d in sorted(tasks_root.iterdir()):
        if not d.is_dir():
            continue
        n = 0
        for f in d.glob("*.yaml"):
            stem = f.stem
            if any((d / f"{stem}.{ext}").exists()
                   for ext in ("lock", "done", "failed")):
                continue
            n += 1
        out[d.name] = n
    return out


def _count_completed_today(tasks_root: Path) -> int:
    if not tasks_root.exists():
        return 0
    today = _now_utc().date()
    n = 0
    for d in tasks_root.iterdir():
        if not d.is_dir():
            continue
        for done in d.glob("*.done"):
            try:
                if datetime.fromtimestamp(
                    done.stat().st_mtime, tz=timezone.utc,
                ).date() == today:
                    n += 1
            except OSError:
                continue
    return n


def _last_outputs(outputs_root: Path, n: int = 5) -> list[dict]:
    if not outputs_root.exists():
        return []
    items: list[tuple[float, dict]] = []
    for dept_dir in outputs_root.iterdir():
        if not dept_dir.is_dir():
            continue
        for task_dir in dept_dir.iterdir():
            if not task_dir.is_dir():
                continue
            try:
                mtime = task_dir.stat().st_mtime
            except OSError:
                continue
            summary = ""
            md = task_dir / "completion.md"
            if md.exists():
                try:
                    summary = md.read_text(encoding="utf-8")[:200]
                except OSError:
                    summary = ""
            items.append((mtime, {
                "department": dept_dir.name,
                "task_id": task_dir.name,
                "modified": datetime.fromtimestamp(mtime, tz=timezone.utc)
                                    .isoformat(),
                "summary": summary.replace("\n", " ").strip(),
            }))
    items.sort(key=lambda x: x[0], reverse=True)
    return [it[1] for it in items[:n]]


def _section_agents() -> dict:
    pending = _scan_pending_by_dept(TASKS_DIR)
    return {
        "pending_by_dept": pending,
        "pending_total": sum(pending.values()),
        "completed_today": _count_completed_today(TASKS_DIR),
        "last_outputs": _last_outputs(OUTPUTS_DIR, n=5),
    }


# ---------------------------------------------------------------------------
# Cost — Anthropic spend from usage_log
# ---------------------------------------------------------------------------
def _rate_for(model: str) -> tuple[float, float]:
    """Map a model id to (input_rate, output_rate) per million tokens."""
    m = (model or "").lower()
    for prefix, rates in ANTHROPIC_RATES_PER_M.items():
        if prefix in m:
            return rates
    return ANTHROPIC_RATES_PER_M["claude-haiku"]  # default: cheapest


def _section_cost() -> dict:
    """Estimate Anthropic spend last 24h + 30d projection."""
    con = _open_backend_db()
    if con is None:
        return {
            "available": False,
            "reason": "backend_db_unreachable",
            "spend_24h_usd": 0.0,
            "projected_30d_usd": 0.0,
        }
    now = int(time.time())
    day = now - 86_400
    try:
        # usage_log is per-turn — group by model and sum tokens.
        rows = con.execute(
            "SELECT model, SUM(input_toks) AS itoks, SUM(output_toks) AS otoks"
            " FROM usage_log WHERE ts >= ? GROUP BY model", (day,),
        ).fetchall()
        spend_24h = 0.0
        for r in rows:
            i_rate, o_rate = _rate_for(r["model"])
            spend_24h += (int(r["itoks"] or 0) / 1_000_000) * i_rate
            spend_24h += (int(r["otoks"] or 0) / 1_000_000) * o_rate
        # Naive 30d projection — last 24h × 30. Real volume varies so
        # this is just a quick sanity check, not a billing forecast.
        return {
            "available": True,
            "spend_24h_usd": round(spend_24h, 4),
            "projected_30d_usd": round(spend_24h * 30, 2),
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Roadmap — counts of pending vs shipped items
# ---------------------------------------------------------------------------
def _section_roadmap() -> dict:
    """Walk docs/ROADMAP.md and count next-7-days + shipped-today items."""
    if not ROADMAP_PATH.exists():
        return {"available": False,
                "reason": f"{ROADMAP_PATH.relative_to(REPO_ROOT)} not found"}
    try:
        text = ROADMAP_PATH.read_text(encoding="utf-8")
    except OSError as ex:
        return {"available": False, "reason": str(ex)}
    today = _now_utc().date()
    next_week = today + timedelta(days=7)
    pending_next_week = 0
    shipped_24h = 0
    # Current autonomous-loop roadmap convention: every unchecked bullet
    # under "NEXT 7 DAYS" is reportable for the weekly window.
    import re
    in_next_7_days = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_next_7_days = stripped.lower() == "## next 7 days"
            continue
        if in_next_7_days and re.match(r"^-\s*\[\s*\]", stripped):
            pending_next_week += 1

    if pending_next_week == 0:
        # Legacy fallback: old root ROADMAP.md used "(target YYYY-MM-DD)".
        # Keep supporting that format for tests and transitional docs.
        for m in re.finditer(r"target\s+(\d{4}-\d{2}-\d{2})", text):
            try:
                d = datetime.fromisoformat(m.group(1)).date()
            except ValueError:
                continue
            if today <= d <= next_week:
                pending_next_week += 1
    # "shipped" rows live in the table — look for today's ISO date in
    # the same line as a version number.
    for line in text.splitlines():
        if today.isoformat() in line and "|" in line:
            shipped_24h += 1
    return {
        "available": True,
        "pending_next_7d": pending_next_week,
        "shipped_24h": shipped_24h,
    }


# ---------------------------------------------------------------------------
# Errors — tail of boot.log + Sentry hook (stubbed)
# ---------------------------------------------------------------------------
def _tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    try:
        # Small file (boot.log is ~kb) — read whole thing.
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [l for l in text.splitlines() if l.strip()]
    return lines[-n:]


def _section_errors() -> dict:
    boot_tail = _tail_lines(_boot_log_path(), n=5)
    # "ERR" / "Error" / "Traceback" markers — boot.log lines that look
    # interesting. Don't over-engineer; the founder reads them anyway.
    err_lines = [l for l in boot_tail
                 if "ERR" in l or "Error" in l or "Traceback" in l]
    return {
        "boot_log_tail": boot_tail,
        "boot_log_errors": err_lines,
        "sentry_events": [],  # placeholder — needs SENTRY_API_TOKEN wiring
    }


# ---------------------------------------------------------------------------
# Heartbeat — small helper duplicated from dashboard so we don't pull
# the FastAPI stack just to read 2 lines of text.
# ---------------------------------------------------------------------------
def _read_heartbeat() -> dict:
    if not HEARTBEAT_PATH.exists():
        return {"ts": None, "cycles": None, "age_seconds": None,
                "fresh": False}
    try:
        lines = HEARTBEAT_PATH.read_text(encoding="utf-8").splitlines()
        ts_str = lines[0].strip() if lines else ""
        cycles = int(lines[1].strip()) if len(lines) > 1 else 0
        ts = datetime.fromisoformat(ts_str)
        age = (_now_utc() - ts).total_seconds()
        return {"ts": ts_str, "cycles": cycles,
                "age_seconds": int(age), "fresh": age < 180}
    except (OSError, ValueError, IndexError):
        return {"ts": None, "cycles": None, "age_seconds": None,
                "fresh": False}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_report(*, cadence_minutes: Optional[int] = None) -> dict:
    """Build a structured status report + its HTML rendering.

    Returns:
        {
          "id": "...",
          "ts": "...",
          "html": "...",
          "text": "...",
          "subject": "[ArchHub] HH:MM · X paying · CI green",
          "business": {...},
          "infrastructure": {...},
          "agents": {...},
          "cost": {...},
          "roadmap": {...},
          "errors": {...},
          "meta": {...},
        }
    """
    now = _now_utc()
    report_id = f"rpt_{int(now.timestamp())}_{uuid.uuid4().hex[:6]}"

    business = _safe(_section_business)
    infrastructure = _safe(_section_infrastructure)
    agents = _safe(_section_agents)
    cost = _safe(_section_cost)
    roadmap = _safe(_section_roadmap)
    errors = _safe(_section_errors)
    heartbeat = _read_heartbeat()

    report = {
        "id": report_id,
        "ts": now.isoformat(),
        "business": business,
        "infrastructure": infrastructure,
        "agents": agents,
        "cost": cost,
        "roadmap": roadmap,
        "errors": errors,
        "meta": {
            "cadence_minutes": cadence_minutes,
            "generator": "agents.status_report",
            "data_root": str(DATA_ROOT),
            "heartbeat": heartbeat,
        },
    }
    report["subject"] = _build_subject(now, report)
    report["html"] = _render_html(report)
    report["text"] = _render_text(report)
    return report


# ---------------------------------------------------------------------------
# Subject builder — short, signal-dense, no exclamation points.
# Target: <= 60 chars when possible.
# ---------------------------------------------------------------------------
def _build_subject(now: datetime, report: dict) -> str:
    hm = now.strftime("%H:%M")
    biz = report.get("business") or {}
    paying = biz.get("new_paying_24h", 0)
    pending_rm = (report.get("roadmap") or {}).get("pending_next_7d", 0)
    ci = ((report.get("infrastructure") or {}).get("ci") or {})
    ci_status = ci.get("status") or "n/a"
    ci_label = {
        "success": "CI green",
        "failure": "CI RED",
        "completed": "CI done",
        "in_progress": "CI run",
        "n/a": "CI n/a",
    }.get(ci_status, f"CI {ci_status}")

    parts = [
        f"[ArchHub] {hm}",
        f"{paying} paying 24h",
        ci_label,
        f"{pending_rm} roadmap pending",
    ]
    subj = " | ".join(parts)
    # Trim long suffixes to keep things readable.
    if len(subj) > 78:
        subj = subj[:75] + "..."
    return subj


# ---------------------------------------------------------------------------
# HTML rendering — inline styles only. Gmail strips <style> blocks.
# ---------------------------------------------------------------------------
def _kv_table(rows: list[tuple[str, Any]]) -> str:
    body = "".join(
        f"<tr><td style='padding:4px 10px;color:#6f6d65;font-size:12px'>"
        f"{_esc(str(k))}</td>"
        f"<td style='padding:4px 10px;font-size:13px;font-family:"
        f"Menlo,Consolas,monospace'>{_esc(str(v))}</td></tr>"
        for k, v in rows
    )
    return (
        "<table cellspacing='0' cellpadding='0' style='border-collapse:"
        "collapse;width:100%;background:#fff;border:1px solid #e8e6dc;"
        "border-radius:6px;margin:6px 0'>"
        f"<tbody>{body}</tbody></table>"
    )


def _render_html(r: dict) -> str:
    now_str = r["ts"]
    biz = r.get("business") or {}
    infra = r.get("infrastructure") or {}
    ag = r.get("agents") or {}
    cost = r.get("cost") or {}
    rm = r.get("roadmap") or {}
    errs = r.get("errors") or {}
    meta = r.get("meta") or {}

    biz_rows = [
        ("New signups (24h)", biz.get("new_signups_24h", "—")),
        ("New paying customers (24h)", biz.get("new_paying_24h", "—")),
        ("Active subs", biz.get("active_subs", "—")),
        ("MRR delta (24h, USD)", f"${biz.get('mrr_delta_24h_usd', 0)}"),
        ("Churn (7d)", biz.get("churn_7d", "—")),
    ]
    if not biz.get("available", False):
        biz_rows.append(("Status", f"unavailable — {biz.get('reason', '?')}"))

    backend = (infra.get("backend_healthz") or {})
    agents_hz = (infra.get("agents_healthz") or {})
    ci = (infra.get("ci") or {})
    infra_rows = [
        ("cloud_backend /healthz",
         f"{backend.get('status_code', '—')} "
         f"({'reachable' if backend.get('reachable') else 'down'})"),
        ("agents /healthz",
         f"{agents_hz.get('status_code', '—')} "
         f"({'reachable' if agents_hz.get('reachable') else 'down'})"),
        ("CI (GitHub Actions)",
         (ci.get("status") or "n/a") + (f" @ {ci['sha']}"
                                         if ci.get("sha") else "")),
    ]

    pending_rows = ag.get("pending_by_dept") or {}
    pending_lines = "".join(
        f"<li><b>{_esc(d)}</b>: {n}</li>"
        for d, n in sorted(pending_rows.items())
    ) or "<li style='color:#888'>(no pending tasks)</li>"

    outputs = ag.get("last_outputs") or []
    output_rows = "".join(
        f"<tr><td style='padding:4px 10px;font-size:12px'>"
        f"{_esc(o['department'])}</td>"
        f"<td style='padding:4px 10px;font-size:12px'>"
        f"{_esc(o['task_id'])}</td>"
        f"<td style='padding:4px 10px;font-size:11px;color:#6f6d65'>"
        f"{_esc((o.get('summary') or '')[:120])}</td></tr>"
        for o in outputs
    ) or ("<tr><td colspan='3' style='padding:8px;color:#888'>"
          "(no outputs yet)</td></tr>")

    cost_rows = [
        ("Anthropic spend last 24h",
         f"${cost.get('spend_24h_usd', 0)}"),
        ("Projected 30d (linear)",
         f"${cost.get('projected_30d_usd', 0)}"),
    ]
    if not cost.get("available", False):
        cost_rows.append(("Status",
                          f"unavailable — {cost.get('reason', '?')}"))

    rm_rows = [
        ("Pending next 7d", rm.get("pending_next_7d", "—")),
        ("Shipped 24h", rm.get("shipped_24h", "—")),
    ]
    if not rm.get("available", False):
        rm_rows.append(("Status",
                        f"unavailable — {rm.get('reason', '?')}"))

    boot_tail = errs.get("boot_log_tail") or []
    err_lines = errs.get("boot_log_errors") or []
    boot_block = "".join(
        f"<div style='font-family:Menlo,Consolas,monospace;font-size:11px;"
        f"color:#6f6d65;padding:2px 0'>{_esc(l)}</div>"
        for l in boot_tail[-5:]
    ) or ("<div style='color:#888;font-size:12px'>"
          "(boot.log empty or unreachable)</div>")
    if err_lines:
        err_block_html = (
            "<div style='font-size:11px;color:#6f6d65;margin-top:8px;"
            "margin-bottom:4px'>marked errors</div>"
            + "".join(
                f"<div style='font-family:Menlo,Consolas,monospace;"
                f"font-size:11px;color:#c0392b;padding:2px 0'>"
                f"{_esc(l)}</div>"
                for l in err_lines[-5:]
            )
        )
    else:
        err_block_html = ""

    hb = meta.get("heartbeat") or {}
    hb_line = (f"heartbeat: {hb.get('ts') or '—'}"
               f" · cycles: {hb.get('cycles') or 0}"
               f" · age: {hb.get('age_seconds') or 0}s"
               f" · fresh: {hb.get('fresh', False)}")

    cadence = meta.get("cadence_minutes")
    cadence_line = (f"cadence: every {cadence} min"
                    if cadence else "cadence: on-demand")

    subject = _esc(r.get("subject") or "")

    return (
        "<html><body style=\"font-family:'Inter',Arial,sans-serif;"
        "color:#141413;background:#faf9f5;padding:20px;max-width:820px;"
        "margin:0 auto\">"
        "<h1 style='margin:0 0 4px;font-size:20px;color:#141413'>"
        f"ArchHub status</h1>"
        f"<div style='color:#6f6d65;font-size:12px;margin-bottom:14px'>"
        f"{_esc(now_str)} · {_esc(cadence_line)}</div>"
        f"<div style='color:#6f6d65;font-size:12px;margin-bottom:14px'>"
        f"<b>{subject}</b></div>"

        "<h3 style='margin:18px 0 4px;font-size:14px'>Business</h3>"
        f"{_kv_table(biz_rows)}"

        "<h3 style='margin:18px 0 4px;font-size:14px'>Infrastructure</h3>"
        f"{_kv_table(infra_rows)}"

        "<h3 style='margin:18px 0 4px;font-size:14px'>Agents</h3>"
        f"<div style='font-size:13px;margin-bottom:6px'>Pending tasks "
        f"({ag.get('pending_total', 0)} total) · completed today: "
        f"{ag.get('completed_today', 0)}</div>"
        f"<ul style='margin:0 0 8px 18px;padding:0;font-size:13px'>"
        f"{pending_lines}</ul>"
        "<table cellspacing='0' cellpadding='0' style='border-collapse:"
        "collapse;width:100%;background:#fff;border:1px solid #e8e6dc;"
        "border-radius:6px;margin:6px 0'>"
        "<thead style='background:#f0eee5'>"
        "<tr><th style='padding:6px 10px;text-align:left;font-size:11px;"
        "color:#6f6d65'>DEPT</th><th style='padding:6px 10px;text-align:"
        "left;font-size:11px;color:#6f6d65'>TASK</th><th style='padding:"
        "6px 10px;text-align:left;font-size:11px;color:#6f6d65'>SUMMARY"
        "</th></tr></thead>"
        f"<tbody>{output_rows}</tbody></table>"

        "<h3 style='margin:18px 0 4px;font-size:14px'>Cost</h3>"
        f"{_kv_table(cost_rows)}"

        "<h3 style='margin:18px 0 4px;font-size:14px'>Roadmap</h3>"
        f"{_kv_table(rm_rows)}"

        "<h3 style='margin:18px 0 4px;font-size:14px'>Errors</h3>"
        f"<div style='background:#fff;border:1px solid #e8e6dc;"
        f"border-radius:6px;padding:8px 12px;margin:6px 0'>"
        f"<div style='font-size:11px;color:#6f6d65;margin-bottom:4px'>"
        f"boot.log tail</div>{boot_block}{err_block_html}"
        f"</div>"

        f"<p style='color:#6f6d65;font-size:11px;margin-top:18px;"
        f"border-top:1px solid #e8e6dc;padding-top:10px'>"
        f"report id <code>{_esc(r.get('id', ''))}</code> · "
        f"{_esc(hb_line)}<br/>"
        f"Generated by <code>agents/status_report.py</code>. To mute, "
        f"<code>flyctl secrets set ARCHHUB_REPORT_INTERVAL_MIN=0</code>."
        f"</p>"
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# Plain-text fallback. Clients that strip HTML still get a usable digest.
# ---------------------------------------------------------------------------
def _render_text(r: dict) -> str:
    biz = r.get("business") or {}
    infra = r.get("infrastructure") or {}
    ag = r.get("agents") or {}
    cost = r.get("cost") or {}
    rm = r.get("roadmap") or {}
    errs = r.get("errors") or {}
    meta = r.get("meta") or {}
    hb = meta.get("heartbeat") or {}

    out = [
        f"ArchHub status · {r['ts']}",
        f"Subject: {r.get('subject', '')}",
        "",
        "BUSINESS",
        f"  signups (24h):       {biz.get('new_signups_24h', '—')}",
        f"  paying new (24h):    {biz.get('new_paying_24h', '—')}",
        f"  active subs:         {biz.get('active_subs', '—')}",
        f"  MRR delta (24h):     ${biz.get('mrr_delta_24h_usd', 0)}",
        f"  churn (7d):          {biz.get('churn_7d', '—')}",
        "",
        "INFRASTRUCTURE",
        f"  backend /healthz:    {(infra.get('backend_healthz') or {}).get('status_code', '—')}",  # noqa: E501
        f"  agents /healthz:     {(infra.get('agents_healthz') or {}).get('status_code', '—')}",  # noqa: E501
        f"  CI:                  {((infra.get('ci') or {}).get('status') or 'n/a')}",  # noqa: E501
        "",
        "AGENTS",
        f"  pending total:       {ag.get('pending_total', 0)}",
        f"  completed today:     {ag.get('completed_today', 0)}",
    ]
    pending = ag.get("pending_by_dept") or {}
    for d, n in sorted(pending.items()):
        out.append(f"    {d:12s} {n}")
    out += [
        "",
        "COST",
        f"  spend 24h:           ${cost.get('spend_24h_usd', 0)}",
        f"  projected 30d:       ${cost.get('projected_30d_usd', 0)}",
        "",
        "ROADMAP",
        f"  pending next 7d:     {rm.get('pending_next_7d', '—')}",
        f"  shipped 24h:         {rm.get('shipped_24h', '—')}",
        "",
        "ERRORS (boot.log tail)",
    ]
    for line in (errs.get("boot_log_tail") or [])[-5:]:
        out.append(f"  {line}")
    out += [
        "",
        f"heartbeat: {hb.get('ts') or '—'} · cycles {hb.get('cycles') or 0}"
        f" · age {hb.get('age_seconds') or 0}s · fresh {hb.get('fresh', False)}",  # noqa: E501
        f"report id: {r.get('id', '')}",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    """CLI: dump the latest report as JSON to stdout."""
    report = generate_report(cadence_minutes=None)
    if "--html" in argv:
        sys.stdout.write(report["html"])
    elif "--text" in argv:
        sys.stdout.write(report["text"])
    else:
        # Don't print html/text in JSON dump — they're huge and not
        # useful here. Caller can request them with --html/--text.
        slim = {k: v for k, v in report.items() if k not in ("html", "text")}
        sys.stdout.write(json.dumps(slim, indent=2, default=str))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
