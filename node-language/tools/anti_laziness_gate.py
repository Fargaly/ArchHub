"""Claude Code Stop-hook: the brain's anti-laziness enforcement gate.

Wired as a `command` Stop hook in ~/.claude/settings.json. On every
attempt to end a turn it:

  1. reads the session transcript (path handed in on stdin),
  2. extracts the agent's final message + evidence of real work
     (tests run, curl, build, server start, files written, screenshots),
  3. asks the brain (`brain.enforce_diligence`) whether the agent earned
     the right to stop — the brain owns the policy so every client is
     held to the same bar,
  4. if the verdict is BLOCK, prints {"decision":"block","reason":...}
     so Claude Code refuses to stop and feeds the reason back — the agent
     must DO THE WORK.

Safety:
  * Fail-OPEN on the gate's own errors (never brick a session).
  * Fail-CLOSED on detected laziness.
  * Loop-guard: after MAX_BLOCKS consecutive blocks for one session we
    allow with a warning, so a genuinely-stuck agent isn't hard-locked.

Contract refs (verified via claude-code-guide):
  stdin  = {"session_id","transcript_path","cwd","stop_hook_active",...}
  block  = exit 0 + stdout {"decision":"block","reason":"..."}
  allow  = exit 0 + no stdout
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

DAEMON_URL = "http://127.0.0.1:8473/mcp"
MAX_BLOCKS = 3          # escape hatch: stop forcing after this many
MAX_FILE_BYTES = 200_000

# Make the bundled policy importable as a fallback when the daemon is down.
_REPO = Path(__file__).resolve().parent.parent
_BRAIN_SRC = _REPO / "personal-brain-mcp" / "src"
if _BRAIN_SRC.exists() and str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))


# ───────────────────────── transcript parsing ──────────────────────────


def _read_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def _content_blocks(entry: dict) -> list[dict]:
    """Return the message.content array for an assistant/user entry,
    tolerating the couple of shapes Claude Code transcripts use."""
    msg = entry.get("message") or entry
    content = msg.get("content")
    if isinstance(content, list):
        return [c for c in content if isinstance(c, dict)]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _role(entry: dict) -> str:
    return (entry.get("message") or entry).get("role") or entry.get("type") or ""


def extract_signals(events: list[dict]) -> dict:
    """Walk the transcript → last assistant text + proof signals + files."""
    last_text_parts: list[str] = []
    touched: list[str] = []
    sig = {
        "ran_tests": False, "ran_curl": False, "wrote_files": False,
        "took_screenshot": False, "ran_build": False, "started_server": False,
    }

    # find the index of the final assistant turn
    last_assistant_idx = -1
    for i, e in enumerate(events):
        if _role(e) == "assistant":
            last_assistant_idx = i

    for i, e in enumerate(events):
        role = _role(e)
        for b in _content_blocks(e):
            btype = b.get("type")
            if btype == "tool_use":
                name = (b.get("name") or "").lower()
                inp = b.get("input") or {}
                if name in ("write", "edit", "notebookedit", "multiedit"):
                    sig["wrote_files"] = True
                    fp = inp.get("file_path") or inp.get("path")
                    if fp:
                        touched.append(str(fp))
                if "screenshot" in name:
                    sig["took_screenshot"] = True
                if name in ("bash", "powershell"):
                    cmd = (inp.get("command") or "").lower()
                    if "pytest" in cmd or "python -m pytest" in cmd or " test" in cmd:
                        sig["ran_tests"] = True
                    if "curl" in cmd:
                        sig["ran_curl"] = True
                    if "npm run build" in cmd or "astro build" in cmd or "npm run preview" in cmd:
                        sig["ran_build"] = True
                    if "uvicorn" in cmd or "http.server" in cmd or "--http" in cmd or "runserver" in cmd:
                        sig["started_server"] = True
                if name.startswith("mcp__claude_preview__preview_screenshot") or "todataurl" in name:
                    sig["took_screenshot"] = True
                if name.startswith("mcp__claude_preview__preview_start"):
                    sig["started_server"] = True
            elif btype == "text" and role == "assistant" and i == last_assistant_idx:
                last_text_parts.append(b.get("text") or "")

    return {
        "last_message": "\n".join(last_text_parts).strip(),
        "touched_files": list(dict.fromkeys(touched)),  # de-dupe, keep order
        "session_signals": sig,
    }


def read_file_contents(paths: list[str], cwd: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in paths[:50]:
        fp = Path(p)
        if not fp.is_absolute() and cwd:
            fp = Path(cwd) / p
        try:
            if fp.exists() and fp.stat().st_size <= MAX_FILE_BYTES:
                out[p] = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
    return out


# ───────────────────────── brain call ──────────────────────────────────


def _parse_sse(raw: bytes) -> dict:
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                obj = json.loads(line[5:].strip())
            except Exception:
                continue
            res = obj.get("result") or {}
            sc = res.get("structuredContent")
            if isinstance(sc, dict):
                return sc
            for c in res.get("content") or []:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except Exception:
                        pass
    return {}


def call_brain(evidence: dict) -> dict | None:
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "brain.enforce_diligence", "arguments": evidence},
    }).encode("utf-8")
    req = urllib.request.Request(
        DAEMON_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return _parse_sse(r.read())
    except Exception:
        return None


def evaluate_local(evidence: dict) -> dict:
    """Fallback when the daemon is unreachable — bundled policy."""
    try:
        from personal_brain.diligence import evaluate_diligence
        v = evaluate_diligence(
            last_message=evidence.get("last_message", ""),
            touched_files=evidence.get("touched_files"),
            file_contents=evidence.get("file_contents"),
            session_signals=evidence.get("session_signals"),
        )
        return v.to_dict()
    except Exception:
        return {}


# ───────────────────────── loop guard ──────────────────────────────────


def _guard_path(session_id: str) -> Path:
    safe = "".join(c for c in (session_id or "anon") if c.isalnum() or c in "-_")
    return Path(tempfile.gettempdir()) / f"brain_diligence_{safe}.count"


def bump_block_count(session_id: str) -> int:
    p = _guard_path(session_id)
    n = 0
    try:
        if p.exists():
            n = int(p.read_text().strip() or "0")
    except Exception:
        n = 0
    n += 1
    try:
        p.write_text(str(n))
    except Exception:
        pass
    return n


def reset_block_count(session_id: str) -> None:
    try:
        _guard_path(session_id).unlink(missing_ok=True)
    except Exception:
        pass


# ───────────────────────── main ────────────────────────────────────────


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0   # fail-open: can't read input → never brick

    transcript = payload.get("transcript_path") or ""
    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or ""

    events = _read_jsonl(transcript) if transcript else []
    if not events:
        return 0   # nothing to judge → allow

    ev = extract_signals(events)
    if not ev["last_message"]:
        return 0   # no final text → allow

    ev["file_contents"] = read_file_contents(ev["touched_files"], cwd)

    verdict = call_brain(ev) or evaluate_local(ev)
    if not verdict:
        return 0   # gate failed → fail-open

    if verdict.get("verdict") == "block":
        n = bump_block_count(session_id)
        if n > MAX_BLOCKS:
            reset_block_count(session_id)
            sys.stderr.write(
                f"[brain diligence] {n} blocks for this session — "
                f"releasing the loop guard. Threads still open; review.\n"
            )
            return 0   # escape hatch
        reason = verdict.get("reason") or "Work incomplete — keep going."
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0

    reset_block_count(session_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
