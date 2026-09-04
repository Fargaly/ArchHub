"""brainwrap — one launcher that wires ANY agent client into the brain.

Two roles, one tool:

1. Universal HOOK ADAPTER (`session-start` / `context` / `stop` / `health`).
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
                   vendor's --context-file or native interactive prompt flag.
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

    brainwrap session-start [--vendor claude-code|generic]
        Session registration. Reads the lifecycle payload on stdin and
        announces the already-running session to Brain. It never launches,
        stops, or supervises the vendor process.

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
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DAEMON_URL = os.environ.get("BRAIN_DAEMON_URL", "http://127.0.0.1:8473/mcp")
_TIMEOUT = 6
GOVERNANCE_BLOCK_EXIT = 78
_GOVERNED_ENV_KEYS = (
    "ARCHHUB_GOVERNED_SESSION",
    "ARCHHUB_REQUIRE_ACTIVE_CDE",
    "BRAIN_COMPLIANCE_EVENT_APPEND",
    "BRAIN_BROKER_EVENT_APPEND",
    "BRAIN_DAEMON_URL",
    "ARCHHUB_ACTIVE_CDE_STATE",
    "ARCHHUB_AGENT_RUNTIME",
    "ARCHHUB_EXTERNAL_SESSION_ID",
    "ARCHHUB_SESSION_CWD",
)
# Port the daemon listens on (parsed from DAEMON_URL → 8473 by default).
try:
    DAEMON_PORT = int(DAEMON_URL.rsplit(":", 1)[1].split("/", 1)[0])
except Exception:
    DAEMON_PORT = 8473

# Make the bundled brain package importable for the daemon command path, the
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


def _external_session_id(payload: dict) -> str:
    return str(
        payload.get("session_id")
        or payload.get("conversationId")
        or payload.get("conversation_id")
        or os.environ.get("ARCHHUB_EXTERNAL_SESSION_ID")
        or ""
    ).strip()


def _payload_cwd(payload: dict) -> str:
    cwd = str(payload.get("cwd") or "").strip()
    if cwd:
        return cwd
    paths = payload.get("workspacePaths")
    if isinstance(paths, list):
        for path in paths:
            if isinstance(path, str) and path.strip():
                return path
    return os.getcwd()


def ensure_universal_agent_session(payload: dict, *, vendor: str) -> Optional[dict]:
    """Idempotently bind the vendor session to its Cell Agent Session."""
    session_id = _external_session_id(payload)
    if not session_id:
        return None
    return call_tool("brain.hook_session_start", {
        "session_id": session_id,
        "cwd": str(payload.get("cwd") or os.getcwd()),
        "vendor": vendor,
        "source": payload.get("source") or "brainwrap",
    })


def _active_cde_state_path(
    *, session_id: str = "", runtime: str = ""
) -> Path:
    raw = os.environ.get("ARCHHUB_ACTIVE_CDE_STATE", "").strip()
    if raw:
        return Path(raw)
    base = os.environ.get("LOCALAPPDATA")
    root = (Path(base) / "ArchHub") if base else (Path.home() / ".archhub")
    identity = (
        session_id.strip()
        or os.environ.get("ARCHHUB_EXTERNAL_SESSION_ID", "").strip()
    )
    runtime_name = (
        runtime.strip()
        or os.environ.get("ARCHHUB_AGENT_RUNTIME", "").strip()
    ).lower()
    if identity:
        digest = hashlib.sha256(
            runtime_name.encode("utf-8")
            + b"\x00"
            + identity.encode("utf-8")
        ).hexdigest()
        return root / "active_cde" / (digest + ".json")
    if runtime_name:
        safe = "".join(
            character if character.isalnum() else "_"
            for character in runtime_name
        ).strip("_")
        if safe:
            return root / ("active_cde_%s.json" % safe)
    return root / "active_cde_container.json"


def _cde_container_from_leaf(leaf: Optional[dict]) -> Optional[dict]:
    if not isinstance(leaf, dict):
        return None
    for key in ("cde_container", "metadata"):
        value = leaf.get(key)
        if isinstance(value, dict) and value.get("container_id"):
            return value
    gate_spec = leaf.get("gate_spec")
    if isinstance(gate_spec, dict):
        value = gate_spec.get("cde_container")
        if isinstance(value, dict) and value.get("container_id"):
            return value
    return None


def _write_active_cde_state(
    leaf: Optional[dict], *, runtime: str, session_id: str = ""
) -> None:
    container = _cde_container_from_leaf(leaf)
    path = _active_cde_state_path(session_id=session_id, runtime=runtime)
    if not container:
        return
    payload = {
        "schema": "archhub-active-cde/v1",
        "runtime": runtime,
        "session_id": session_id,
        "leaf_id": leaf.get("leaf_id", "") if isinstance(leaf, dict) else "",
        "title": leaf.get("title", "") if isinstance(leaf, dict) else "",
        "cwd": os.getcwd(),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "container": container,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[brainwrap] active CDE state not written (fail-open): {exc!r}",
              file=sys.stderr)


def _clear_active_cde_state(*, runtime: str = "", session_id: str = "") -> None:
    path = _active_cde_state_path(session_id=session_id, runtime=runtime)
    try:
        if path.exists():
            path.unlink()
    except Exception as exc:  # noqa: BLE001
        print(f"[brainwrap] active CDE state not cleared (fail-open): {exc!r}",
              file=sys.stderr)


def _clear_expired_active_cde_state(
    *, runtime: str, session_id: str, now: Optional[datetime] = None
) -> bool:
    """Delete only an expired or malformed time-bounded state projection."""
    path = _active_cde_state_path(session_id=session_id, runtime=runtime)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        container = payload.get("container") if isinstance(payload, dict) else None
        expiry_text = container.get("expires_at") if isinstance(container, dict) else None
        if not expiry_text:
            return False
        expiry = datetime.fromisoformat(str(expiry_text).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("CDE expiry must be timezone-aware")
        observed = now or datetime.now(timezone.utc)
        if observed.astimezone(timezone.utc) < expiry.astimezone(timezone.utc):
            return False
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        pass
    _clear_active_cde_state(runtime=runtime, session_id=session_id)
    return True


def fetch_drive_block(*, runtime: str, session_id: str = "") -> str:
    """THE DRIVE (pre-prompt). Ask the brain for this runtime's next leaf, CLAIM
    it, and return the ready-to-prepend <assigned_leaf> block.

    Historical migration note (removed from this path):
      1. DAEMON — POST brain.work_assigned_block (the daemon's single store +
         the BEGIN IMMEDIATE critical section serialise the claim across every
         client). Preferred so two runtimes never grab the same leaf.
      2. IN-PROCESS fallback — if the daemon is down but the package imports,
         claim through the SAME on-disk brain.db via client_hook.

    Current behavior returns "" on error, an empty frontier, a missing session,
    or a non-Universal response. It never claims from a local Brain database.
    """
    if not session_id.strip():
        return ""
    _clear_expired_active_cde_state(runtime=runtime, session_id=session_id)
    owner = os.environ.get("BRAIN_OWNER_USER")
    fit = _drive_fit()
    # 1) daemon — the cross-process-safe path.
    res = call_tool("brain.work_assigned_block", {
        "runtime": runtime,
        "session_id": session_id,
        "fit": fit,
        "owner_user": owner,
        "wrap": True,
        "write": True,
    })
    if (
        isinstance(res, dict)
        and res.get("ok")
        and res.get("universal") is True
        and isinstance(res.get("agent_session"), str)
        and res["agent_session"].strip()
    ):
        block = res.get("block")
        if isinstance(block, str) and block:
            _write_active_cde_state(
                res.get("leaf"), runtime=runtime, session_id=session_id
            )
            return block
    return ""


def _drive_fit() -> Optional[list[str]]:
    """Capability tags this runtime advertises to the drive (so a specialised
    leaf is never handed to a runtime that can't do it). Read from
    BRAIN_RUNTIME_FIT (comma-separated) when set; else None (matches only
    no-requirement leaves)."""
    raw = os.environ.get("BRAIN_RUNTIME_FIT", "").strip()
    if not raw:
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


def cmd_context(vendor: str) -> int:
    payload = _read_stdin_json()
    ensure_universal_agent_session(payload, vendor=vendor)
    prompt = payload.get("prompt") or payload.get("user_message") or ""
    ctx = call_tool("brain.context", {
        "prompt": prompt,
        "cwd": _payload_cwd(payload),
        "owner_user": os.environ.get("BRAIN_OWNER_USER"),
    })
    injection = _injection_from_context(ctx)

    # THE DRIVE: in ADDITION to RECALL (brain.context), inject the next unit of
    # work the brain hands this runtime (<assigned_leaf>, claimed atomically).
    # This is what wires the foreign-vendor pre-prompt into the brain-driver —
    # without it the brain drives Claude Code but not Codex/Gemini/Cursor.
    drive = fetch_drive_block(
        runtime=vendor, session_id=_external_session_id(payload)
    )
    combined = "\n".join(b for b in (injection, drive) if b).strip()

    if vendor == "cursor":
        # Cursor merges user_message into the outgoing prompt context.
        out = {"continue": True}
        if combined:
            out["user_message"] = combined
        sys.stdout.write(json.dumps(out))
    else:
        # generic: print recall + drive for the agent/wrapper to prepend.
        if combined:
            sys.stdout.write(combined)
    return 0


def cmd_session_start(vendor: str) -> int:
    """Register a live vendor session without taking ownership of its process.

    Claude's SessionStart event can run before an MCP client context exists, so
    an mcp_tool hook is skipped even though its settings schema is valid.  The
    command adapter uses the same daemon transport and wrapper tool instead.
    It is deliberately side-effect-only: printing nothing keeps Claude's
    startup context free of transport/audit JSON.
    """
    payload = _read_stdin_json()
    cwd = _payload_cwd(payload)
    session_id = _external_session_id(payload) or None
    call_tool("brain.hook_session_start", {
        "session_id": session_id,
        "cwd": cwd,
        "vendor": vendor,
        "source": payload.get("source"),
    })
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
                  or payload.get("transcriptPath")
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


def _completion_gate_verdict(
    cwd: Optional[str] = None,
    *,
    runtime: str = "",
    session_id: str = "",
) -> tuple[bool, str]:
    """Evaluate only graph-owned Work for the exact vendor session.

    The graph declares the gate, receives the submit evidence, and runs its
    independent court. Without a Universal Agent Session there is no stop-gate
    decision and no read from the legacy Brain ledger.
    """
    if session_id:
        state = call_tool("brain.universal_work_status", {
            "session_id": session_id,
            "vendor": runtime,
        })
        if not isinstance(state, dict):
            # The founder's app restarting orphans every enrolled Agent
            # Session. That is the runtime's lifecycle, not the agent's
            # fault: re-enroll against the new runtime once and retry,
            # instead of denying the stop and demanding a human ritual.
            call_tool("brain.hook_session_start", {
                "session_id": session_id,
                "vendor": runtime,
                "cwd": cwd or str(Path.cwd()),
            })
            state = call_tool("brain.universal_work_status", {
                "session_id": session_id,
                "vendor": runtime,
            })
        if not isinstance(state, dict):
            return True, "Universal work authority is unavailable; stop denied."
        session_root = state.get("agent_session")
        owned = [
            item for item in (state.get("items") or [])
            if item.get("claimant_session") == session_root
            and str(
                (item.get("operational") or {}).get("current_state_label", "")
            ).casefold() == "claimed"
        ]
        if len(owned) > 1:
            return True, (
                "Agent Session owns multiple active work nodes; governance "
                "repair is required before stop."
            )
        if not owned:
            return False, ""
        item = owned[0]
        requirement = (item.get("resolved") or {}).get("requirements") or {}
        gate = requirement.get("gate") if isinstance(requirement, dict) else {}
        gate = gate if isinstance(gate, dict) else {}
        gate_kind = str(gate.get("kind") or "manual")
        gate_spec = gate.get("spec") or {}
        try:
            import completion_gate as cg
            import brain_ledger as bl
            gate_value = cg._gate_from_dict({
                "name": (
                    (item.get("interfaces") or {}).get("title") or {}
                ).get("value", item.get("root", "work")),
                "kind": bl._GATE_KIND_MAP.get(gate_kind, "manual"),
                "arg": bl._gate_arg_from_spec(gate_kind, gate_spec),
                "arg2": (
                    ",".join(gate_spec.get("paths", []))
                    if gate_kind == "grep_clean" else ""
                ),
                "machine_resolvable": gate_kind not in ("manual", "cdp"),
            })
            history = (item.get("operational") or {}).get("history") or []
            root = Path(cwd) if cwd else Path.cwd()
            verdict = cg.evaluate(
                [gate_value],
                len(history),
                cg.CAP_DEFAULT,
                runner=lambda value: cg.run_gate(value, root),
            )
        except Exception as exc:
            return True, (
                "Universal work court could not execute: "
                f"{type(exc).__name__}: {exc}"
            )
        if verdict.action != "allow":
            prefix = "ESCALATE -> founder: " if verdict.action == "escalate" else ""
            return True, prefix + verdict.reason + " [universal-cell]"
        evidence = json.dumps({
            "court": "brainwrap-stop",
            "gate_kind": gate_kind,
            "gate_spec": gate_spec,
            "verdict": "green",
        }, separators=(",", ":"))
        submitted = call_tool("brain.universal_work_transition", {
            "session_id": session_id,
            "vendor": runtime,
            "work_root": item.get("root"),
            "event": "submit",
            "evidence": evidence,
        })
        if not isinstance(submitted, dict):
            return True, "Green work could not be submitted to graph review."
        adjudicated = call_tool("brain.universal_work_court", {
            "session_id": session_id,
            "vendor": runtime,
            "work_root": item.get("root"),
        })
        if not isinstance(adjudicated, dict):
            return True, "Independent work court is unavailable; stop denied."
        if not adjudicated.get("passed"):
            return True, (
                "NOT DONE: the independent work court returned the work after "
                "rerunning its graph-declared gate. [universal-cell]"
            )
        counts = (adjudicated.get("status") or {}).get("counts") or {}
        if int(counts.get("complete", 0)) < 1:
            return True, "Independent court did not complete the work node."
        return False, ""

    # Legacy ledger state is not Work authority without a graph Agent Session.
    return False, ""


def cmd_stop(vendor: str) -> int:
    payload = _read_stdin_json()
    ensure_universal_agent_session(payload, vendor=vendor)
    verdict, evidence = _diligence_verdict(payload)
    blocked = bool(verdict) and verdict.get("verdict") == "block"
    reason = (verdict or {}).get("reason") or "Work incomplete — keep going."

    # THE DRIVE's Stop gate checks only graph Work owned by this exact Agent
    # Session. Its graph-declared gate takes precedence over the advisory
    # diligence result and never consults a legacy ledger.
    drive_blocked, drive_reason = _completion_gate_verdict(
        cwd=_payload_cwd(payload),
        runtime=vendor,
        session_id=_external_session_id(payload),
    )
    if drive_blocked:
        blocked = True
        reason = drive_reason or reason

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
    elif vendor == "antigravity":
        if blocked:
            sys.stdout.write(json.dumps(
                {"decision": "continue", "reason": reason}))
        else:
            sys.stdout.write(json.dumps({"decision": ""}))
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
    """PREPEND Brain context to an explicitly named vendor context file.

    Without an explicit sink, persistence is forbidden: ``cmd_launch`` may
    still use a vendor-supported interactive prompt flag, but a launcher must
    never create an instruction sidecar inside the governed workspace.
    Re-runs refresh the bounded block instead of stacking duplicates.
    """
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

    # No explicit file means no persistent sink. cmd_launch may use a vendor
    # native context flag while preserving the terminal's standard streams.
    return "context ready for vendor adapter (no workspace file written)"


# ── 4. exec the vendor CLI (exit code preserved) ────────────────────────


def _runtime_context_file(injection: str) -> Path:
    """Write one bounded private launch artifact outside the workspace."""
    root = Path(
        os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    ) / "ArchHub" / "runtime-context"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw_path = tempfile.mkstemp(
        prefix="brainwrap-",
        suffix=".md",
        dir=root,
    )
    path = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(injection.encode("utf-8"))
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise


def _vendor_context_argv(
    argv: list[str], context_path: Path
) -> Optional[list[str]]:
    """Return a vendor-supported interactive context invocation.

    Full-screen CLIs must inherit the console. Piping a context prefix through
    stdin turns their TTY into a closed pipe and leaves the apparent session
    frozen. Only documented native channels are admitted here.
    """
    if not argv:
        return list(argv)
    name = Path(argv[0]).stem.casefold()
    if name in {"claude", "claude-code"}:
        return [
            argv[0],
            "--append-system-prompt-file",
            str(context_path),
            *argv[1:],
        ]
    if name == "gemini":
        prompt = (
            "Apply the startup governance context from @%s as session "
            "instructions, then continue interactively without summarizing it."
            % context_path
        )
        return [argv[0], "--prompt-interactive", prompt, *argv[1:]]
    if name == "codex" and len(argv) == 1:
        prompt = (
            "Apply the startup governance context at %s as session "
            "instructions, then continue interactively." % context_path
        )
        return [argv[0], prompt]
    return None


def run_vendor(argv: list[str], *, cwd: str,
               context_injection: Optional[str] = None) -> int:
    """Exec the vendor command, preserving its exit code exactly.

    Brain context is carried only through a native interactive vendor option.
    Standard input, output, and error always remain inherited from the terminal.
    """
    if not argv:
        print("[brainwrap] no vendor command after `--`", file=sys.stderr)
        return 2

    requested = argv[0]
    requested_path = Path(requested)
    if requested_path.suffix.casefold() == ".ps1":
        cmd_peer = requested_path.with_suffix(".cmd")
        if cmd_peer.is_file():
            requested = str(cmd_peer)
    exe = shutil.which(requested) or requested
    full = [exe] + argv[1:]

    context_path: Optional[Path] = None
    try:
        if context_injection:
            context_path = _runtime_context_file(context_injection)
            contextualized = _vendor_context_argv(full, context_path)
            if contextualized is None:
                print(
                    "[brainwrap] vendor has no admitted interactive context "
                    f"adapter: {Path(full[0]).name}",
                    file=sys.stderr,
                )
                return GOVERNANCE_BLOCK_EXIT
            full = contextualized
        return subprocess.call(full, cwd=cwd)
    except FileNotFoundError:
        print(f"[brainwrap] vendor not found: {argv[0]}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130
    finally:
        if context_path is not None:
            context_path.unlink(missing_ok=True)


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


def _coverage_client_for_vendor(vendor: str) -> Optional[str]:
    stem = Path(vendor or "").name.lower()
    if stem.endswith(".exe"):
        stem = stem[:-4]
    if "claude" in stem:
        return "claude-code"
    if "cursor" in stem:
        return "cursor"
    if "codex" in stem:
        return "codex"
    if "gemini" in stem:
        return "gemini-cli"
    if "antigravity" in stem:
        return "antigravity"
    return None


def governed_session_env(
    *, cwd: str, vendor: str, session_id: str
) -> dict[str, str]:
    env = {
        "ARCHHUB_GOVERNED_SESSION": "1",
        "ARCHHUB_WORKSHOP_AUTHORITY_REQUIRED": "1",
        "ARCHHUB_REQUIRE_ACTIVE_CDE": "1",
        "BRAIN_COMPLIANCE_EVENT_APPEND": "1",
        "BRAIN_BROKER_EVENT_APPEND": "1",
        "BRAIN_DAEMON_URL": os.environ.get("BRAIN_DAEMON_URL", DAEMON_URL),
        "ARCHHUB_ACTIVE_CDE_STATE": str(_active_cde_state_path(
            session_id=session_id, runtime=vendor
        )),
        "ARCHHUB_AGENT_RUNTIME": vendor or "unknown",
        "ARCHHUB_EXTERNAL_SESSION_ID": session_id,
        "ARCHHUB_SESSION_CWD": cwd,
    }
    return env


def _push_env(values: dict[str, str]) -> dict[str, Optional[str]]:
    old = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        os.environ[key] = value
    return old


def _restore_env(old: dict[str, Optional[str]]) -> None:
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _status_from_hook_audit(res: Optional[dict]) -> str:
    if not isinstance(res, dict) or not res.get("ok"):
        return "unknown"
    report = res.get("report") if isinstance(res.get("report"), dict) else res
    status = str(report.get("status") or res.get("status") or "").lower()
    if status:
        return status
    summary = report.get("summary") if isinstance(report, dict) else {}
    if isinstance(summary, dict) and int(summary.get("red") or 0) > 0:
        return "red"
    return "unknown"


def _status_from_compliance_report(res: Optional[dict]) -> str:
    if not isinstance(res, dict) or not res.get("ok"):
        return "unknown"
    overall = str(res.get("overall") or "").lower()
    if overall:
        return overall
    hook = res.get("hook_coverage") if isinstance(res.get("hook_coverage"), dict) else {}
    status = str(hook.get("status") or "").lower()
    if status:
        return status
    return "unknown"


def _workshop_authority_probe(*, vendor: str, client: Optional[str]) -> dict[str, Any]:
    """Prove the Brain workshop is reachable before a governed child starts.

    The workshop is the shared authority for coordination. Hook/compliance green
    without the room means the session can still drift silently, so strict
    governed launch treats a missing room as a hard preflight failure.
    """
    agent = f"brainwrap:{client or Path(vendor or 'unknown').name or 'unknown'}"
    res = call_tool("brain.room_read", {
        "agent": agent,
        "limit": 1,
        "mark": True,
    }, timeout=5.0)
    if isinstance(res, dict) and res.get("ok"):
        return {
            "ok": True,
            "agent": agent,
            "result": res,
            "status": "green",
            "channel": "brain.room_read",
        }

    context = call_tool("brain.context", {
        "prompt": "workshop authority preflight probe",
        "cwd": os.environ.get("ARCHHUB_SESSION_CWD") or os.getcwd(),
    }, timeout=8.0)
    injection = ""
    if isinstance(context, dict):
        injection = str(context.get("injection") or "")
    ok = "<meeting_room>" in injection and "</meeting_room>" in injection
    return {
        "ok": ok,
        "agent": agent,
        "result": res,
        "context_probe": {
            "ok": bool(isinstance(context, dict)),
            "has_meeting_room": ok,
        },
        "status": "green" if ok else "red",
        "channel": "brain.context" if ok else "",
    }


def governed_preflight(*, vendor: str) -> tuple[bool, str, dict[str, Any]]:
    owner = os.environ.get("BRAIN_OWNER_USER")
    client = _coverage_client_for_vendor(vendor)
    audit_args: dict[str, Any] = {"owner_user": owner}
    if client:
        audit_args["only"] = [client]
    audit = call_tool(
        "brain.hook_coverage_audit_cell_first",
        audit_args,
        timeout=8.0,
    )
    audit_status = _status_from_hook_audit(audit)

    comp = call_tool("brain.compliance_report",
                     {"owner_user": owner}, timeout=5.0)
    comp_status = _status_from_compliance_report(comp)
    workshop = _workshop_authority_probe(vendor=vendor, client=client)

    details = {
        "hook_coverage": audit,
        "hook_coverage_status": audit_status,
        "compliance_report": comp,
        "compliance_status": comp_status,
        "workshop_authority": workshop,
        "workshop_authority_status": workshop["status"],
        "client": client,
    }
    if audit_status != "green":
        return False, f"hook coverage {audit_status}", details
    if comp_status != "green":
        return False, f"compliance report {comp_status}", details
    if not workshop["ok"]:
        return False, "workshop authority unreachable", details
    return True, "governance green", details


def cmd_launch(opts: argparse.Namespace, vendor_argv: list[str]) -> int:
    """Full lifecycle around a hookless vendor CLI. Returns the vendor's
    exit code (preserved verbatim)."""
    cwd = opts.cwd or os.getcwd()
    vendor = vendor_argv[0] if vendor_argv else "(none)"
    prompt = opts.prompt or " ".join(vendor_argv[1:]) or vendor
    governed = bool(getattr(opts, "governed", False)
                    or getattr(opts, "governed_strict", False))
    governed_strict = bool(getattr(opts, "governed_strict", False))
    external_session_id = (
        os.environ.get("ARCHHUB_EXTERNAL_SESSION_ID", "").strip()
        or secrets.token_hex(16)
    )
    if governed:
        _push_env(governed_session_env(
            cwd=cwd, vendor=vendor, session_id=external_session_id
        ))

    # 1. CONNECT — health + (if down) start the daemon the service way.
    ok, note = ensure_daemon(auto_start=not opts.skip_daemon_start)
    print(f"[brainwrap] connect: {note}", file=sys.stderr)
    if governed_strict and not ok:
        print("[brainwrap] governance: blocked (brain unreachable)",
              file=sys.stderr)
        return GOVERNANCE_BLOCK_EXIT

    context_injection: Optional[str] = None
    if ok:
        if governed:
            green, reason, _details = governed_preflight(vendor=vendor)
            print(f"[brainwrap] governance: {reason}", file=sys.stderr)
            if governed_strict and not green:
                return GOVERNANCE_BLOCK_EXIT
        # 2. ANNOUNCE wiring (scope hint for context retrieval).
        announce_wiring(cwd, vendor)
        ensure_universal_agent_session(
            {
                "session_id": external_session_id,
                "cwd": cwd,
                "source": "brainwrap-launch",
            },
            vendor=vendor,
        )
        # 3. INJECT context.
        injection = fetch_context(prompt, cwd)
        if injection:
            inote = inject_context(injection, context_file=opts.context_file,
                                   cwd=cwd)
            print(f"[brainwrap] inject: {inote}", file=sys.stderr)
            if not opts.context_file:
                probe_path = Path("brainwrap-context.md")
                if _vendor_context_argv(vendor_argv, probe_path) is not None:
                    context_injection = injection.rstrip()
                else:
                    print(
                        "[brainwrap] inject: no admitted interactive context "
                        "adapter; pass --context-file",
                        file=sys.stderr,
                    )
                    if governed_strict:
                        print("[brainwrap] governance: blocked (context was not "
                              "delivered)", file=sys.stderr)
                        return GOVERNANCE_BLOCK_EXIT
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
    code = run_vendor(
        vendor_argv,
        cwd=cwd,
        context_injection=context_injection,
    )

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
    p.add_argument("--governed", action="store_true",
                   help="Stamp the child process as a governed ArchHub "
                        "session and run Brain governance preflight.")
    p.add_argument("--governed-strict", action="store_true",
                   help="Like --governed, but fail closed when Brain, hook "
                        "coverage, or compliance report are not green.")


def main(argv: Optional[list[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    wrapper_args, vendor_argv = _split_argv(raw)

    parser = argparse.ArgumentParser(
        prog="brainwrap",
        description="Universal brain adapter + launcher for any agent client.",
    )
    sub = parser.add_subparsers(dest="cmd")
    for name in ("session-start", "context", "stop"):
        sp = sub.add_parser(name)
        sp.add_argument("--vendor", default="generic",
                        choices=["claude-code", "codex", "cursor",
                                 "gemini-cli", "antigravity", "generic"])
    sub.add_parser("health")
    _add_launch_opts(sub.add_parser("launch"))

    # A bare `brainwrap -- <cli>` (no subcommand) defaults to `launch`.
    if vendor_argv and (not wrapper_args
                        or wrapper_args[0] not in
                        ("session-start", "context", "stop", "health",
                         "launch")):
        wrapper_args = ["launch"] + wrapper_args

    args = parser.parse_args(wrapper_args)

    if args.cmd == "launch":
        # launch is allowed to fail-open at the lifecycle level but must
        # still return the vendor's real exit code — so it is NOT wrapped in
        # the blanket fail-open below.
        return cmd_launch(args, vendor_argv)

    try:
        if args.cmd == "session-start":
            return cmd_session_start(args.vendor)
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
