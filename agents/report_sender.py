"""Resend HTTP sender for the founder status report.

Stdlib only (urllib.request) so the agents container doesn't grow a
new dep. The cloud_backend has httpx because FastAPI needs it; the
agents image is leaner and intentionally avoids adding it back.

Env contract:
  RESEND_API_KEY               re_xxx — when unset we log to stdout +
                               agents/logs/reports.log instead of
                               actually POSTing.
  ARCHHUB_REPORT_RECIPIENT     default ahmed.fargaly98@gmail.com
  ARCHHUB_REPORT_INTERVAL_MIN  default 60 — 0 disables sending
  ARCHHUB_REPORT_DIGEST_HOURS  when set, buffer reports for N hours
                               and send a single digest at the end of
                               the window (rate-limit friendly).
  ARCHHUB_REPORT_FROM_EMAIL    default noreply@archhub.io
  ARCHHUB_REPORT_DRY_RUN       any value disables the actual HTTP POST

The send-state machine is dead simple:

  cloud_runner --> tick_send_report(report_fn) --> send(report)
                                                  --> POST Resend
                                                  --> write log line

Digest mode (ARCHHUB_REPORT_DIGEST_HOURS=N) keeps buffered reports on
disk under `state/digest_buffer.jsonl`. tick_send_report decides every
N minutes whether to flush the buffer into a single combined email
instead of sending the latest report on its own.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
RESEND_URL = "https://api.resend.com/emails"
DEFAULT_RECIPIENT = "ahmed.fargaly98@gmail.com"
DEFAULT_FROM = "noreply@archhub.io"
DEFAULT_INTERVAL_MIN = 60  # see CLOUD_DEPLOY.md re Resend 100/day cap


# State files. Use ARCHHUB_AGENTS_DATA_ROOT so /data on Fly wins when
# the persistent volume is mounted, falling back to agents/state in dev.
def _state_dir() -> Path:
    root_env = os.environ.get("ARCHHUB_AGENTS_DATA_ROOT")
    if root_env:
        d = Path(root_env) / "state"
    else:
        d = Path(__file__).resolve().parent / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logs_dir() -> Path:
    root_env = os.environ.get("ARCHHUB_AGENTS_DATA_ROOT")
    if root_env:
        d = Path(root_env) / "logs"
    else:
        d = Path(__file__).resolve().parent / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _last_report_path() -> Path:
    return _state_dir() / "last_report_at.txt"


def _digest_buffer_path() -> Path:
    return _state_dir() / "digest_buffer.jsonl"


def _digest_started_path() -> Path:
    return _state_dir() / "digest_started_at.txt"


def _reports_log_path() -> Path:
    return _logs_dir() / "reports.log"


# ---------------------------------------------------------------------------
# Public env accessors — exposed for the tests + the cloud_runner.
# ---------------------------------------------------------------------------
def interval_minutes() -> int:
    """Configured interval. Returns 0 when disabled."""
    try:
        return int(os.environ.get("ARCHHUB_REPORT_INTERVAL_MIN",
                                  str(DEFAULT_INTERVAL_MIN)))
    except ValueError:
        return DEFAULT_INTERVAL_MIN


def digest_hours() -> int:
    """Buffer N hours of reports into a single digest. 0 = off."""
    try:
        return int(os.environ.get("ARCHHUB_REPORT_DIGEST_HOURS", "0"))
    except ValueError:
        return 0


def recipient() -> str:
    return (os.environ.get("ARCHHUB_REPORT_RECIPIENT", "").strip()
            or DEFAULT_RECIPIENT)


def from_email() -> str:
    return (os.environ.get("ARCHHUB_REPORT_FROM_EMAIL", "").strip()
            or os.environ.get("FROM_EMAIL", "").strip()
            or DEFAULT_FROM)


def is_dry_run() -> bool:
    return bool(os.environ.get("ARCHHUB_REPORT_DRY_RUN"))


def is_configured() -> bool:
    """True when at least one email path is reachable (Resend OR SMTP)."""
    if is_dry_run():
        return False
    if os.environ.get("RESEND_API_KEY"):
        return True
    if _smtp_configured():
        return True
    return False


def _smtp_configured() -> bool:
    """True when all four SMTP env vars are set. Gmail app-password path:
        ARCHHUB_REPORT_SMTP_HOST=smtp.gmail.com
        ARCHHUB_REPORT_SMTP_PORT=587
        ARCHHUB_REPORT_SMTP_USER=<email>
        ARCHHUB_REPORT_SMTP_PASSWORD=<16-char app password>
    """
    return all(
        os.environ.get(k)
        for k in ("ARCHHUB_REPORT_SMTP_HOST",
                  "ARCHHUB_REPORT_SMTP_PORT",
                  "ARCHHUB_REPORT_SMTP_USER",
                  "ARCHHUB_REPORT_SMTP_PASSWORD")
    )


def _send_via_smtp(*, subject: str, html: str, text: str,
                    to_addr: str, from_addr: str) -> tuple[bool, int, str]:
    """SMTP fallback when no Resend key. Uses stdlib smtplib + STARTTLS.
    Returns (ok, status_code, body) — matches _post_resend's shape."""
    import smtplib
    from email.message import EmailMessage
    host = os.environ["ARCHHUB_REPORT_SMTP_HOST"]
    port = int(os.environ["ARCHHUB_REPORT_SMTP_PORT"])
    user = os.environ["ARCHHUB_REPORT_SMTP_USER"]
    pwd  = os.environ["ARCHHUB_REPORT_SMTP_PASSWORD"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = from_addr or user
    msg["To"]      = to_addr
    msg.set_content(text or " ")
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.ehlo()
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return True, 250, "sent via SMTP"
    except smtplib.SMTPAuthenticationError as ex:
        return False, 535, f"auth failed: {ex}"
    except Exception as ex:
        return False, 0, f"{type(ex).__name__}: {ex}"


# ---------------------------------------------------------------------------
# HTTP POST — stdlib so the agents image stays lean.
# ---------------------------------------------------------------------------
def _post_resend(*, api_key: str, payload: dict,
                  timeout: float = 10.0) -> tuple[bool, int, str]:
    """Send one POST to Resend. Returns (ok, status_code, body)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        RESEND_URL, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ok = 200 <= resp.status < 300
            return ok, int(resp.status), body
    except urllib.error.HTTPError as ex:
        body = ""
        try:
            body = ex.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return False, int(ex.code), body
    except (urllib.error.URLError, TimeoutError) as ex:
        return False, 0, f"network error: {ex}"


# ---------------------------------------------------------------------------
# Outcome log — one JSONL row per send attempt. Cheap audit trail.
# ---------------------------------------------------------------------------
def _log_outcome(*, ok: bool, status: int, subject: str,
                 mode: str, recipient_addr: str, note: str = "") -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ok": bool(ok),
        "status": int(status),
        "subject": subject,
        "mode": mode,            # "live", "stdout", "digest_flush", ...
        "recipient": recipient_addr,
        "note": note,
    }
    try:
        with _reports_log_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        # Logging must NEVER kill the daemon. Swallow.
        pass


# ---------------------------------------------------------------------------
# send() — the workhorse. Either fires the HTTP POST or logs locally.
# ---------------------------------------------------------------------------
def send(report: dict, *, recipient_addr: Optional[str] = None,
         mode: Optional[str] = None) -> dict:
    """Dispatch the report. Returns {ok, status, mode, body}.

    Never raises — the daemon must keep ticking even if Resend is down.
    """
    to = (recipient_addr or recipient()).strip()
    payload = {
        "from": from_email(),
        "to": [to],
        "subject": report.get("subject", "[ArchHub] status"),
        "html": report.get("html", ""),
        "text": report.get("text", ""),
    }

    if not is_configured():
        # Dev / unset / dry-run path: print + log, don't actually send.
        why = ("dry_run" if is_dry_run()
               else "no_email_provider_key (set RESEND_API_KEY or "
                    "ARCHHUB_REPORT_SMTP_* env vars)")
        sys_write = ("[report_sender] would send "
                     f"({why}) to={to} subject={payload['subject']!r}")
        print(sys_write, flush=True)
        _log_outcome(ok=True, status=0, subject=payload["subject"],
                     mode=mode or "stdout", recipient_addr=to, note=why)
        return {"ok": True, "status": 0,
                "mode": mode or "stdout", "body": why}

    # Provider selection: Resend first (cheapest stdlib path), SMTP
    # fallback for Gmail app-password / generic SMTP setups.
    if os.environ.get("RESEND_API_KEY"):
        api_key = os.environ["RESEND_API_KEY"]
        ok, status, body = _post_resend(api_key=api_key, payload=payload)
        used_mode = mode or "live_resend"
    else:
        ok, status, body = _send_via_smtp(
            subject=payload["subject"],
            html=payload.get("html") or "",
            text=payload.get("text") or "",
            to_addr=to,
            from_addr=from_email(),
        )
        used_mode = mode or "live_smtp"
    _log_outcome(ok=ok, status=status, subject=payload["subject"],
                 mode=used_mode, recipient_addr=to,
                 note=body[:200] if not ok else "")
    return {"ok": ok, "status": status,
            "mode": used_mode, "body": body}


# ---------------------------------------------------------------------------
# Cadence gate — read/write the last-sent timestamp file.
# ---------------------------------------------------------------------------
def _read_last_sent() -> Optional[datetime]:
    p = _last_report_path()
    if not p.exists():
        return None
    try:
        return datetime.fromisoformat(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _write_last_sent(ts: Optional[datetime] = None) -> None:
    ts = ts or datetime.now(timezone.utc)
    try:
        _last_report_path().write_text(ts.isoformat(), encoding="utf-8")
    except OSError:
        pass


def should_send_now(*, now: Optional[datetime] = None) -> bool:
    """Cadence gate. Cloud_runner calls this every loop and only fires
    when at least `ARCHHUB_REPORT_INTERVAL_MIN` minutes have elapsed."""
    interval = interval_minutes()
    if interval <= 0:
        return False        # 0 = disabled
    last = _read_last_sent()
    if last is None:
        return True
    cur = now or datetime.now(timezone.utc)
    return (cur - last) >= timedelta(minutes=interval)


# ---------------------------------------------------------------------------
# Digest mode — buffer reports on disk, flush when the window elapses.
# ---------------------------------------------------------------------------
def _append_to_digest(report: dict) -> None:
    """Persist a slim copy of the report into the buffer file."""
    slim = {
        "id": report.get("id"),
        "ts": report.get("ts"),
        "subject": report.get("subject"),
        # Keep text-only snapshots in the buffer — HTML would balloon
        # the file fast and we re-render the digest later anyway.
        "text": report.get("text"),
    }
    try:
        with _digest_buffer_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(slim, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _digest_window_started() -> Optional[datetime]:
    p = _digest_started_path()
    if not p.exists():
        return None
    try:
        return datetime.fromisoformat(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _set_digest_window_start(ts: Optional[datetime] = None) -> None:
    ts = ts or datetime.now(timezone.utc)
    try:
        _digest_started_path().write_text(ts.isoformat(), encoding="utf-8")
    except OSError:
        pass


def _load_digest_buffer() -> list[dict]:
    p = _digest_buffer_path()
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def _clear_digest_buffer() -> None:
    try:
        _digest_buffer_path().unlink(missing_ok=True)
        _digest_started_path().unlink(missing_ok=True)
    except OSError:
        pass


def _render_digest_email(reports: list[dict], window_hours: int) -> dict:
    """Combine N buffered reports into a single email payload."""
    if not reports:
        return {
            "subject": "[ArchHub] digest (empty)",
            "html": "<p>No reports buffered.</p>",
            "text": "(empty digest)",
        }
    first = reports[0]
    last = reports[-1]
    subject = (f"[ArchHub] {window_hours}h digest | "
               f"{len(reports)} reports | latest: {last.get('subject', '')}")
    # Plain text — concatenate every text snapshot with a separator.
    text_parts = [
        f"ArchHub {window_hours}-hour digest",
        f"Reports: {len(reports)} "
        f"({first.get('ts', '')} → {last.get('ts', '')})",
        "",
    ]
    for i, r in enumerate(reports, 1):
        text_parts.append(f"--- {i}/{len(reports)} · {r.get('ts', '')} ---")
        text_parts.append(r.get("text", "") or "(no text)")
        text_parts.append("")
    text = "\n".join(text_parts)
    # HTML — one collapsible-style section per report. Inline styles only.
    html_parts = [
        "<html><body style=\"font-family:'Inter',Arial,sans-serif;"
        "color:#141413;background:#faf9f5;padding:20px;max-width:820px;"
        "margin:0 auto\">",
        f"<h1 style='margin:0 0 4px;font-size:20px'>ArchHub "
        f"{window_hours}h digest</h1>",
        f"<div style='color:#6f6d65;font-size:12px;margin-bottom:14px'>"
        f"{len(reports)} reports buffered · {first.get('ts', '')}"
        f" → {last.get('ts', '')}</div>",
    ]
    for i, r in enumerate(reports, 1):
        html_parts.append(
            f"<h3 style='margin:18px 0 4px;font-size:14px'>"
            f"#{i} · {r.get('ts', '')}</h3>"
            f"<div style='color:#6f6d65;font-size:12px;margin-bottom:4px'>"
            f"{r.get('subject', '')}</div>"
            f"<pre style='background:#fff;border:1px solid #e8e6dc;"
            f"border-radius:6px;padding:10px 12px;font-size:11px;"
            f"white-space:pre-wrap;line-height:1.4'>"
            + (r.get("text") or "(no text)") +
            "</pre>"
        )
    html_parts.append("</body></html>")
    return {"subject": subject, "html": "".join(html_parts), "text": text}


# ---------------------------------------------------------------------------
# tick_send_report — what the cloud_runner calls every loop iteration.
# ---------------------------------------------------------------------------
def tick_send_report(report_fn: Callable[[], dict], *,
                      now: Optional[datetime] = None) -> dict:
    """Drive one report-send decision. Idempotent + non-raising.

    Returns:
      {"sent": bool, "mode": str, "ok": bool, "reason": str}

    Modes:
      "disabled"      — interval == 0; nothing to do
      "skipped"       — interval not yet elapsed
      "live"          — POST'd a single report to Resend
      "stdout"        — logged-only (no API key or dry run)
      "digest_buffer" — appended to buffer, no send this tick
      "digest_flush"  — flushed the buffer and sent a combined email
    """
    interval = interval_minutes()
    if interval <= 0:
        return {"sent": False, "mode": "disabled", "ok": True,
                "reason": "ARCHHUB_REPORT_INTERVAL_MIN=0"}

    if not should_send_now(now=now):
        return {"sent": False, "mode": "skipped", "ok": True,
                "reason": "interval not elapsed"}

    # Cadence gate passed — claim it immediately so a slow generator
    # call can't trigger a double-send across overlapping ticks.
    _write_last_sent(now or datetime.now(timezone.utc))

    try:
        report = report_fn()
    except Exception as ex:  # noqa: BLE001
        _log_outcome(ok=False, status=0, subject="(generator failed)",
                     mode="error", recipient_addr=recipient(),
                     note=f"{type(ex).__name__}: {ex}")
        return {"sent": False, "mode": "error", "ok": False,
                "reason": f"generator: {type(ex).__name__}: {ex}"}

    hours = digest_hours()
    if hours > 0:
        # Digest mode — buffer this report; flush only when the window
        # has fully elapsed.
        _append_to_digest(report)
        started = _digest_window_started()
        cur = now or datetime.now(timezone.utc)
        if started is None:
            _set_digest_window_start(cur)
            return {"sent": False, "mode": "digest_buffer", "ok": True,
                    "reason": f"digest window opened ({hours}h)"}
        if (cur - started) < timedelta(hours=hours):
            return {"sent": False, "mode": "digest_buffer", "ok": True,
                    "reason": (f"buffered, "
                               f"{(cur - started).total_seconds() / 60:.0f}"
                               f" of {hours * 60} min")}
        # Window elapsed — flush.
        buffered = _load_digest_buffer()
        combined = _render_digest_email(buffered, window_hours=hours)
        result = send(combined, mode="digest_flush")
        if result.get("ok"):
            _clear_digest_buffer()
        return {"sent": True, "mode": "digest_flush",
                "ok": bool(result.get("ok")),
                "reason": f"flushed {len(buffered)} buffered reports"}

    # Normal per-tick send.
    result = send(report)
    return {"sent": True, "mode": result.get("mode", "live"),
            "ok": bool(result.get("ok")),
            "reason": f"status={result.get('status')}"}
