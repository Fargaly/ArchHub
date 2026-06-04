"""brainwrap — one launcher that wires ANY agent client into the brain.

Two roles, one tool:

1. Universal HOOK ADAPTER (subcommands `context` / `stop` / `health`).
   The installer points a vendor's hooks here when the vendor's hook
   runner spawns an *executable* over stdio (Cursor) rather than calling
   MCP tools directly. It translates the vendor's stdio contract to/from
   the brain daemon's MCP JSON-RPC and degrades to the bundled policy when
   the daemon is down.

2. Universal LAUNCHER (subcommand `launch`, or a bare `-- <cli> [args]`).
   Wraps a vendor CLI that has NO hook surface at all (Codex, Gemini,
   aider, a bare shell). Around that process it runs the full brain
   lifecycle from the OUTSIDE — connect, inject, diligence — so even a
   hookless CLI gets the same treatment Claude Code gets natively:

     (1) CONNECT   probe brain.health; if down, START the daemon the SAME
                   way personal_brain.service does (reused, not guessed).
     (2) ANNOUNCE  brain.wiring_announce with cwd + git remote (scope hint).
     (3) INJECT    brain.context → prepend the <brain_context> block to the
                   vendor's --context-file, or pipe it on the child's stdin.
     (4) EXEC      run the vendor CLI (argv after `--`); its exit code is
                   preserved verbatim.
     (5) DILIGENCE on exit, build the SAME evidence the Stop gate sends
                   (anti_laziness_gate.extract_signals) and POST it to
                   brain.enforce_diligence; then brain.skill_mint the trace.
                   The verdict is PRINTED, never enforced — this is a
                   post-hoc wrapper, not a Stop hook, so it MUST NOT
                   hard-block the vendor's exit.

Subcommands
-----------
    brainwrap context  [--vendor cursor|generic]
        Pre-prompt inject. Reads the vendor's prompt payload on stdin, calls
        brain.context, and emits the vendor's expected response carrying the
        brain's injection block. NEVER blocks a prompt (continue=true always).

    brainwrap stop     [--vendor cursor|generic]
        Stop-gate. Reads the vendor's stop payload on stdin and runs the same
        anti-laziness diligence check the Claude Code Stop hook runs
        (brain.enforce_diligence, bundled policy fallback). On a "block"
        verdict it emits the vendor's continue/followup signal so the agent
        is told to keep working.

    brainwrap health
        Probe the daemon; exit 0 if reachable.

    brainwrap launch [opts] -- <cli> [args…]   (also the default with `--`)
        Full connect+inject+diligence lifecycle around a hookless vendor CLI.

Design rules honoured: pure stdlib (urllib / json / subprocess), no new
deps; reuse not reimplement (the gate owns transport + SSE parsing +
transcript→evidence extraction; personal_brain.service owns the daemon-start
command); fail-OPEN on every brain error so a broken wrapper never bricks a
user's prompt, traps their agent, or stops their CLI from running.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

DAEMON_URL = os.environ.get("BRAIN_DAEMON_URL", "http://127.0.0.1:8473/mcp")
_TIMEOUT = 6
# Port the daemon listens on (parsed from DAEMON_URL → 8473 by default).
try:
    DAEMON_PORT = int(DAEMON_URL.rsplit(":", 1)[1].split("/", 1)[0])
except Exception:
    DAEMON_PORT = 8473

# Make the bundled brain package importable for the offline fallback, the
# same way anti_laziness_gate.py does.
_REPO = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
_BRAIN_SRC = _REPO / "personal-brain-mcp" / "src"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if _BRAIN_SRC.exists() and str(_BRAIN_SRC) not in sys.path:
    sys.path.insert(0, str(_BRAIN_SRC))


# ───────────────────────── daemon transport ────────────────────────────


def _parse_sse(raw: bytes) -> dict:
    """Pull the structuredContent / JSON text out of an MCP SSE response."""
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


def call_tool(name: str, arguments: dict[str, Any],
              *, timeout: Optional[float] = None) -> Optional[dict]:
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode("utf-8")
    req = urllib.request.Request(
        DAEMON_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as r:
            return _parse_sse(r.read())
    except Exception:
        return None


# ───────────────────────── context (pre-prompt) ─────────────────────────


def _read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {"prompt": str(obj)}
    except Exception:
        # not JSON → treat the whole blob as the prompt text
        return {"prompt": raw}


def _injection_from_context(ctx: Optional[dict]) -> str:
    if not ctx:
        return ""
    # brain.context returns a pre-formatted injection block; tolerate a few
    # shapes so this keeps working if the field is renamed.
    for key in ("injection", "injection_block", "system_prompt_injection"):
        v = ctx.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def cmd_context(vendor: str) -> int:
    payload = _read_stdin_json()
    prompt = payload.get("prompt") or payload.get("user_message") or ""
    ctx = call_tool("brain.context", {
        "prompt": prompt,
        "cwd": os.getcwd(),
        "owner_user": os.environ.get("BRAIN_OWNER_USER"),
    })
    injection = _injection_from_context(ctx)

    if vendor == "cursor":
        # Cursor merges user_message into the outgoing prompt context.
        out = {"continue": True}
        if injection:
            out["user_message"] = injection
        sys.stdout.write(json.dumps(out))
    else:
        # generic: print the injection block for the agent/wrapper to prepend.
        if injection:
            sys.stdout.write(injection)
    return 0


# ───────────────────────── stop (diligence gate) ────────────────────────


def _diligence_verdict(payload: dict) -> tuple[dict, dict]:
    """Run the same evidence→verdict path the Claude Code Stop hook uses.

    Reuses tools/anti_laziness_gate.py (transcript parsing + brain call +
    bundled-policy fallback) so every vendor is held to ONE bar.

    Returns (verdict, evidence). The evidence dict (the SAME signals the gate
    extracts — last_message, touched_files, session_signals, file_contents) is
    handed back so the caller can flush it to the brain as the turn's memory
    WITHOUT re-parsing the transcript. Either may be {} (fail-open).
    """
    try:
        import anti_laziness_gate as gate  # tools/ already on sys.path
    except Exception:
        # gate not importable → fail-open
        return {}, {}

    transcript = (payload.get("transcript_path")
                  or payload.get("transcript") or "")
    cwd = payload.get("cwd") or os.getcwd()
    events = gate._read_jsonl(transcript) if transcript else []
    if not events:
        return {}, {}
    ev = gate.extract_signals(events)
    if not ev.get("last_message"):
        return {}, ev
    ev["file_contents"] = gate.read_file_contents(ev["touched_files"], cwd)
    verdict = gate.call_brain(ev) or gate.evaluate_local(ev)
    return (verdict or {}), ev


# ── per-turn brain flush (closes the brain-LEARNING gap for all vendors) ──


def _memory_record(evidence: dict, *, vendor: str, blocked: bool,
                   reason: str) -> Optional[dict]:
    """Compress the turn's evidence into ONE brain.write ADD op.

    Matches the brain.write contract exactly (server.brain_write(ops) →
    WriteOp.model_validate per op → apply_write): a list of WriteOps, each
    `{"op": "add", "fragment": Fragment}`. The Fragment carries the required
    id / kind / text / owner_user / provenance(contributing_agent,
    contributing_user) — the same shape community.py builds — so the daemon
    validates and stores it without any new contract.

    Returns None when there's nothing worth remembering (no final message),
    so an empty / no-signal turn doesn't write a hollow fragment.
    """
    last_message = (evidence.get("last_message") or "").strip()
    if not last_message:
        return None

    touched = list(evidence.get("touched_files") or [])
    sig = evidence.get("session_signals") or {}
    # The proof flags that actually fired this turn (compact, human-readable).
    did = [name for flag, name in (
        ("ran_tests", "tests"), ("ran_curl", "curl"),
        ("wrote_files", "wrote-files"), ("ran_build", "build"),
        ("started_server", "server"), ("took_screenshot", "screenshot"),
    ) if sig.get(flag)]

    owner = os.environ.get("BRAIN_OWNER_USER") or "unknown"
    agent = f"brainwrap:{vendor}"

    # Stable, content-derived id (sha256 of the salient form) — mirrors the
    # "sha256 of canonical form" id convention the brain uses elsewhere, so a
    # re-flush of the identical turn upserts instead of duplicating.
    import hashlib
    basis = f"{agent}|{owner}|{last_message}|{'|'.join(touched)}|{'|'.join(did)}"
    frag_id = "turn-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    # Human-readable memory text: what the turn concluded + the proof it left.
    summary = last_message if len(last_message) <= 600 else last_message[:600] + "…"
    proof = (", ".join(did)) if did else "no proof signals"
    verdict_tag = "diligence=BLOCK" if blocked else "diligence=ok"
    text = (f"[{agent}] {summary}\n"
            f"(proof: {proof}; files: {len(touched)}; {verdict_tag})")

    fragment: dict[str, Any] = {
        "id": frag_id,
        "kind": "fact",
        "text": text,
        "owner_user": owner,
        "provenance": {
            "contributing_agent": agent,
            "contributing_user": owner,
            "accessed_resources": touched[:50],
        },
        # Non-schema breadcrumbs the brain keeps in `extra` for later recall.
        "extra": {
            "vendor": vendor,
            "session_signals": sig,
            "diligence_verdict": "block" if blocked else "allow",
            "diligence_reason": (reason or "")[:400] if blocked else "",
            "touched_files": touched[:50],
        },
    }
    return {"op": "add", "fragment": fragment}


def flush_turn_memory(evidence: dict, *, vendor: str, blocked: bool,
                      reason: str) -> Optional[dict]:
    """POST the turn's salient memory to brain.write ONCE (per-turn flush).

    This is the foreign-vendor analogue of Claude Code's per-tool
    PostToolUse→brain.write hook: Codex/Gemini/Cursor connect to the brain but
    never teach it, so on the single stop hook that fires for ALL of them we
    write the turn's memory here. Reuses the existing call_tool envelope (same
    SSE/JSON-RPC shape as every other brain call) and the brain.write contract
    (ops list). FAIL-OPEN on every error so a broken/absent brain prints a note
    and the wrapped CLI's stop contract is untouched. Returns the brain.write
    result dict, or None when skipped/unreachable.
    """
    try:
        op = _memory_record(evidence, vendor=vendor, blocked=blocked,
                            reason=reason)
        if op is None:
            return None
        res = call_tool("brain.write", {"ops": [op]})
        if not isinstance(res, dict):
            print("[brainwrap] brain flush: brain unreachable - turn memory "
                  "not written (fail-open)", file=sys.stderr)
            return None
        applied = res.get("ops_applied")
        print(f"[brainwrap] brain flush: wrote turn memory "
              f"(ops_applied={applied})", file=sys.stderr)
        return res
    except Exception as ex:
        # Never let a flush bug break the stop hook.
        print(f"[brainwrap] brain flush: skipped ({type(ex).__name__}: {ex}) "
              "- fail-open", file=sys.stderr)
        return None


def cmd_stop(vendor: str) -> int:
    payload = _read_stdin_json()
    verdict, evidence = _diligence_verdict(payload)
    blocked = bool(verdict) and verdict.get("verdict") == "block"
    reason = (verdict or {}).get("reason") or "Work incomplete — keep going."

    # PER-TURN BRAIN FLUSH (the brain-LEARNING gap closer). Claude Code writes
    # the brain per-tool via its PostToolUse→brain.write hook; hookless/foreign
    # vendors (Codex/Gemini/Cursor) have no such per-tool write, so here — on
    # the ONE stop hook that fires for every vendor — we flush the turn's
    # salient memory ONCE, AFTER the diligence verdict, reusing the evidence
    # the gate already extracted. Fail-OPEN: a dead/erroring brain prints and
    # continues; it must never change the stop contract below.
    flush_turn_memory(evidence, vendor=vendor, blocked=blocked, reason=reason)

    if vendor == "cursor":
        # Cursor: continue=false + followup_message loops the agent back.
        if blocked:
            sys.stdout.write(json.dumps(
                {"continue": False, "followup_message": reason}))
        else:
            sys.stdout.write(json.dumps({"continue": True}))
    else:
        # generic: mirror Claude Code's block contract on stdout.
        if blocked:
            sys.stdout.write(json.dumps(
                {"decision": "block", "reason": reason}))
    return 0


# ───────────────────────── health ──────────────────────────────────────


def probe_health(*, timeout: float = 4.0) -> Optional[dict]:
    """Return the brain.health payload (a dict with ok=True) or None if the
    daemon is down / unhealthy."""
    res = call_tool("brain.health", {}, timeout=timeout)
    if isinstance(res, dict) and res.get("ok"):
        return res
    return None


def cmd_health() -> int:
    res = probe_health()
    if res:
        sys.stdout.write("brain: ok\n")
        return 0
    sys.stdout.write("brain: unreachable\n")
    return 1


# ═══════════════════════════════════════════════════════════════════════
#  LAUNCHER  —  connect + inject + exec + diligence around a hookless CLI
# ═══════════════════════════════════════════════════════════════════════


# ── 1. connect: health probe + (if down) start the daemon ───────────────


def daemon_start_command() -> list[str]:
    """The exact argv used to launch the brain daemon.

    REUSED from personal_brain.service._brain_command() — the same logic the
    autostart service + installer use. service returns either the installed
    `personal-brain` entry script or a `"<python>" -m personal_brain.server`
    fallback string; the install paths then run it as `<brain> --http <port>`
    (see service._windows_install / _linux_install / _macos_install). We
    resolve that to an argv and append `--http <port>` — no new/guessed
    command, the identical invocation the service registers for autostart.
    """
    try:
        from personal_brain.service import _brain_command as _svc_brain_command
        brain = _svc_brain_command()
    except Exception:
        # Final fallback, identical in spirit to service.py's own fallback.
        exe = shutil.which("personal-brain")
        brain = exe if exe else f'"{sys.executable}" -m personal_brain.server'

    full = f'{brain} --http {DAEMON_PORT}'
    import shlex
    if os.name == "nt":
        # posix=False keeps Windows backslashes intact and still honours the
        # double-quotes service.py wraps the interpreter path in.
        argv = shlex.split(full, posix=False)
        argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a
                for a in argv]
    else:
        argv = shlex.split(full, posix=True)
    return argv


def ensure_daemon(*, wait_s: float = 12.0, log: bool = True,
                  auto_start: bool = True) -> tuple[bool, str]:
    """Make sure the brain daemon is reachable. If down and auto_start, start
    it the way personal_brain.service does, then poll brain.health until it
    answers.

    Returns (ok, note). Never raises — a dead brain degrades the session to
    "no context / no diligence"; it does NOT stop the vendor CLI.
    """
    h = probe_health()
    if h is not None:
        return True, f"brain up (db={h.get('db_path', '?')})"
    if not auto_start:
        return False, "brain down (auto-start disabled)"

    cmd = daemon_start_command()
    if log:
        print(f"[brainwrap] brain down — starting daemon: {' '.join(cmd)}",
              file=sys.stderr, flush=True)

    try:
        env = dict(os.environ)
        # PYTHONPATH=src so `-m personal_brain.server` imports even when the
        # package isn't pip-installed (matches the BRAIN-FIRST "bring brain
        # up" recipe: `PYTHONPATH=src python -m personal_brain.server`).
        if _BRAIN_SRC.exists():
            prev = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(_BRAIN_SRC) + (
                os.pathsep + prev if prev else "")
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": (None if log else subprocess.DEVNULL),
            "cwd": str(_BRAIN_SRC) if _BRAIN_SRC.exists() else None,
            "env": env,
        }
        if os.name == "nt":
            # Detach + no console so the daemon outlives this wrapper and
            # serves future sessions (same intent as the service install).
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **kwargs)
    except Exception as ex:
        return False, f"could not launch daemon: {type(ex).__name__}: {ex}"

    deadline = time.time() + wait_s
    while time.time() < deadline:
        if probe_health(timeout=2.0) is not None:
            return True, "daemon started + healthy"
        time.sleep(0.5)
    return False, f"daemon did not answer health within {wait_s:.0f}s"


# ── 2. wiring announce ──────────────────────────────────────────────────


def _git_remote(cwd: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd, capture_output=True, text=True, timeout=4,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _device_id() -> str:
    import platform
    return (os.environ.get("BRAIN_DEVICE_ID")
            or platform.node()
            or "unknown-device")


def announce_wiring(cwd: str, vendor: str) -> Optional[dict]:
    """Tell the brain what's wired here. Registers the vendor CLI as a `cli`
    wiring entry and passes cwd + git remote so the brain can infer the scope
    (USER / PROJECT / FIRM) for this session's context retrievals.

    Matches server.brain_wiring_announce: device_id (required), entries
    (list of WiringEntry dicts), cwd, git_remote.
    """
    dev = _device_id()
    entry = {
        "name": vendor,
        "kind": "cli",
        "device_id": dev,
        "capabilities": ["brainwrap"],
        "status": "active",
    }
    return call_tool("brain.wiring_announce", {
        "device_id": dev,
        "entries": [entry],
        "cwd": cwd,
        "git_remote": _git_remote(cwd),
    })


# ── 3. context inject ───────────────────────────────────────────────────


def fetch_context(prompt: str, cwd: str) -> Optional[str]:
    """Call brain.context; return its pre-formatted <brain_context> injection
    block, or None when empty / unreachable."""
    ctx = call_tool("brain.context", {
        "prompt": prompt,
        "cwd": cwd,
        "owner_user": os.environ.get("BRAIN_OWNER_USER"),
    })
    inj = _injection_from_context(ctx)
    return inj or None


_CTX_START = "<!-- brainwrap:context:start -->"
_CTX_END = "<!-- brainwrap:context:end -->"


def inject_context(injection: str, *, context_file: Optional[str],
                   cwd: str) -> str:
    """PREPEND the brain context to the vendor's context file (never
    clobber), or write a sidecar when no context file was named. Returns a
    human note. Re-runs refresh the brainwrap block instead of stacking
    duplicates (bounded by the start/end markers)."""
    block = injection.rstrip() + "\n"
    wrapped = f"{_CTX_START}\n{block}{_CTX_END}\n"

    if context_file:
        path = Path(context_file)
        if not path.is_absolute():
            path = Path(cwd) / context_file
        existing = ""
        try:
            if path.exists():
                existing = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            existing = ""
        # Drop any prior brainwrap block so re-runs refresh, not stack.
        if _CTX_START in existing and _CTX_END in existing:
            pre = existing.split(_CTX_START, 1)[0]
            post = existing.split(_CTX_END, 1)[1]
            existing = (pre.rstrip("\n") + "\n" + post.lstrip("\n")).strip("\n")
            existing = existing + ("\n" if existing else "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(wrapped + ("\n" + existing if existing else ""),
                            encoding="utf-8")
            return f"context prepended to {path}"
        except Exception as ex:
            return f"context fetched but write failed: {ex}"

    # No context file → sidecar the user/vendor can pick up.
    side = Path(cwd) / ".brainwrap_context.md"
    try:
        side.write_text(wrapped, encoding="utf-8")
        return f"context written to {side} (no --context-file given)"
    except Exception as ex:
        return f"context fetched but no sink: {ex}"


# ── 4. exec the vendor CLI (exit code preserved) ────────────────────────


def run_vendor(argv: list[str], *, cwd: str,
               stdin_prefix: Optional[str] = None) -> int:
    """Exec the vendor command, preserving its exit code exactly.

    When `stdin_prefix` is given (the brain context, used only when there is
    no --context-file sink and the vendor reads stdin), feed it ahead of the
    child's input. Otherwise inherit our streams so the CLI is interactive.
    """
    if not argv:
        print("[brainwrap] no vendor command after `--`", file=sys.stderr)
        return 2

    exe = shutil.which(argv[0]) or argv[0]
    full = [exe] + argv[1:]

    if stdin_prefix:
        try:
            proc = subprocess.Popen(full, cwd=cwd, stdin=subprocess.PIPE)
            try:
                proc.stdin.write(stdin_prefix.encode("utf-8"))
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            return proc.wait()
        except FileNotFoundError:
            print(f"[brainwrap] vendor not found: {argv[0]}", file=sys.stderr)
            return 127
        except KeyboardInterrupt:
            return 130

    try:
        return subprocess.call(full, cwd=cwd)
    except FileNotFoundError:
        print(f"[brainwrap] vendor not found: {argv[0]}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130


# ── 5. diligence (post-hoc, advisory) + skill mint ──────────────────────


def _default_transcript(cwd: str) -> Optional[str]:
    """Best-effort transcript location when --transcript wasn't given."""
    candidate = Path(cwd) / ".brainwrap_transcript.jsonl"
    return str(candidate) if candidate.exists() else None


def run_diligence(transcript: Optional[str], cwd: str,
                  *, vendor: str, exit_code: int) -> dict[str, Any]:
    """Post-hoc diligence: build evidence the SAME way the Stop gate does and
    ask brain.enforce_diligence for a verdict. PRINTS the verdict; never
    blocks (a wrapper around someone else's process can't un-exit it). Then
    skill-mints the trace. Returns a small summary dict (used by tests).

    Reuses anti_laziness_gate.extract_signals + read_file_contents so the
    evidence shape is byte-for-byte what the real Stop gate sends.
    """
    summary: dict[str, Any] = {"ran": False, "verdict": None, "reason": ""}
    try:
        import anti_laziness_gate as gate
    except Exception:
        summary["reason"] = "gate not importable — diligence skipped (fail-open)"
        print(f"[brainwrap] diligence: {summary['reason']}", file=sys.stderr)
        return summary

    events = gate._read_jsonl(transcript) if transcript else []
    if not events:
        summary["reason"] = ("no transcript to judge (post-hoc, fail-open) "
                             "-- diligence skipped")
        print(f"[brainwrap] diligence: {summary['reason']}", file=sys.stderr)
        return summary

    ev = gate.extract_signals(events)
    if not ev.get("last_message"):
        summary["reason"] = "transcript had no final assistant message — skipped"
        print(f"[brainwrap] diligence: {summary['reason']}", file=sys.stderr)
        return summary

    ev["file_contents"] = gate.read_file_contents(ev["touched_files"], cwd)

    verdict = call_tool("brain.enforce_diligence", {
        "last_message": ev["last_message"],
        "touched_files": ev["touched_files"],
        "file_contents": ev["file_contents"],
        "session_signals": ev["session_signals"],
    })
    if not isinstance(verdict, dict) or "verdict" not in verdict:
        # Daemon unreachable / malformed → bundled local policy, exactly like
        # the gate's own fallback.
        verdict = gate.evaluate_local(ev) or {}

    if not verdict:
        summary["reason"] = ("brain unreachable + local policy unavailable "
                             "-- fail-open")
        print(f"[brainwrap] diligence: {summary['reason']}", file=sys.stderr)
        return summary

    summary["ran"] = True
    summary["verdict"] = verdict.get("verdict")
    summary["reason"] = verdict.get("reason") or ""
    violations = verdict.get("violations") or []

    mark = "OK" if summary["verdict"] != "block" else "WOULD-BLOCK"
    print(f"\n[brainwrap] diligence verdict: {mark} "
          f"({summary['verdict'] or 'unknown'})", file=sys.stderr)
    if summary["reason"]:
        print(f"[brainwrap] reason: {summary['reason']}", file=sys.stderr)
    for v in violations[:8]:
        print(f"[brainwrap]   - {v}", file=sys.stderr)
    if summary["verdict"] == "block":
        print("[brainwrap] NOTE: post-hoc wrapper — the verdict is advisory "
              "and does NOT change the vendor's exit code.", file=sys.stderr)

    # Skill-mint the trace (Stop-hook parity). Derive tool_calls from the
    # gate's session_signals so a transcript-less run still mints honestly
    # (it just won't clear the ≥2 successful-call floor, which is correct).
    try:
        sig = ev["session_signals"]
        tool_calls = [
            {"name": tool, "status": "ok"}
            for flag, tool in (
                ("ran_tests", "tests"), ("ran_curl", "curl"),
                ("wrote_files", "write"), ("ran_build", "build"),
                ("started_server", "server"),
                ("took_screenshot", "screenshot"),
            ) if sig.get(flag)
        ]
        outcome = "success" if exit_code == 0 else "failure"
        mint = call_tool("brain.skill_mint", {
            "trace": {
                "tool_calls": tool_calls,
                "user_message": ev["last_message"][:200],
                "outcome": outcome,
                "touched_files": ev["touched_files"],
            },
            "outcome": outcome,
            "contributing_agent": f"brainwrap:{vendor}",
        })
        if isinstance(mint, dict):
            summary["skill_mint"] = {
                "queued": mint.get("queued"),
                "reason": (mint.get("reason") or "")[:200],
            }
    except Exception:
        pass

    return summary


def cmd_launch(opts: argparse.Namespace, vendor_argv: list[str]) -> int:
    """Full lifecycle around a hookless vendor CLI. Returns the vendor's
    exit code (preserved verbatim)."""
    cwd = opts.cwd or os.getcwd()
    vendor = vendor_argv[0] if vendor_argv else "(none)"
    prompt = opts.prompt or " ".join(vendor_argv[1:]) or vendor

    # 1. CONNECT — health + (if down) start the daemon the service way.
    ok, note = ensure_daemon(auto_start=not opts.skip_daemon_start)
    print(f"[brainwrap] connect: {note}", file=sys.stderr)

    stdin_prefix: Optional[str] = None
    if ok:
        # 2. ANNOUNCE wiring (scope hint for context retrieval).
        announce_wiring(cwd, vendor)
        # 3. INJECT context.
        injection = fetch_context(prompt, cwd)
        if injection:
            inote = inject_context(injection, context_file=opts.context_file,
                                   cwd=cwd)
            print(f"[brainwrap] inject: {inote}", file=sys.stderr)
            if (not opts.context_file) and (not opts.no_stdin_context):
                stdin_prefix = injection.rstrip() + "\n"
        else:
            print("[brainwrap] inject: no context returned (empty brain) -- "
                  "continuing", file=sys.stderr)
    else:
        print("[brainwrap] inject: skipped (brain unreachable) -- fail-open",
              file=sys.stderr)

    # 4. EXEC the vendor CLI — exit code preserved.
    if not vendor_argv:
        print("[brainwrap] nothing to run. Usage: brainwrap launch [opts] -- "
              "<cli> [args]", file=sys.stderr)
        return 2
    code = run_vendor(vendor_argv, cwd=cwd, stdin_prefix=stdin_prefix)

    # 5. DILIGENCE (post-hoc, advisory) + skill mint.
    if ok:
        transcript = opts.transcript or _default_transcript(cwd)
        run_diligence(transcript, cwd, vendor=vendor, exit_code=code)
    else:
        print("[brainwrap] diligence: skipped (brain unreachable) -- fail-open",
              file=sys.stderr)

    return code


# ───────────────────────── CLI ──────────────────────────────────────────


def _split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """Everything before `--` is wrapper config; everything after is the
    vendor command."""
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def _add_launch_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--context-file", default=None,
                   help="File to PREPEND the brain context to "
                        "(e.g. the vendor's instructions/system file).")
    p.add_argument("--transcript", default=None,
                   help="Session transcript (JSONL) to run diligence on at "
                        "exit. Defaults to .brainwrap_transcript.jsonl in cwd "
                        "if present.")
    p.add_argument("--prompt", default="",
                   help="Prompt text for brain.context retrieval. Falls back "
                        "to the joined vendor args.")
    p.add_argument("--cwd", default=None,
                   help="Working directory (default: current).")
    p.add_argument("--no-stdin-context", action="store_true",
                   help="Do not pipe context on stdin even when no "
                        "--context-file sink exists.")
    p.add_argument("--skip-daemon-start", action="store_true",
                   help="Probe health but never auto-start the daemon.")


def main(argv: Optional[list[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    wrapper_args, vendor_argv = _split_argv(raw)

    parser = argparse.ArgumentParser(
        prog="brainwrap",
        description="Universal brain adapter + launcher for any agent client.",
    )
    sub = parser.add_subparsers(dest="cmd")
    for name in ("context", "stop"):
        sp = sub.add_parser(name)
        sp.add_argument("--vendor", default="generic",
                        choices=["cursor", "generic"])
    sub.add_parser("health")
    _add_launch_opts(sub.add_parser("launch"))

    # A bare `brainwrap -- <cli>` (no subcommand) defaults to `launch`.
    if vendor_argv and (not wrapper_args
                        or wrapper_args[0] not in
                        ("context", "stop", "health", "launch")):
        wrapper_args = ["launch"] + wrapper_args

    args = parser.parse_args(wrapper_args)

    if args.cmd == "launch":
        # launch is allowed to fail-open at the lifecycle level but must
        # still return the vendor's real exit code — so it is NOT wrapped in
        # the blanket fail-open below.
        return cmd_launch(args, vendor_argv)

    try:
        if args.cmd == "context":
            return cmd_context(args.vendor)
        if args.cmd == "stop":
            return cmd_stop(args.vendor)
        if args.cmd == "health":
            return cmd_health()
    except Exception:
        # fail-open: never brick the caller on our own bug
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
