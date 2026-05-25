"""Memory gate — Layer 5 of the multi-LLM enforcement model (AgDR-0044).

Layer 3 (`library_gate.py`) enforces LIBRARY-FIRST.
Layer 5 (this file) enforces MEMORY-FIRST + provenance.

Mirrors the LibraryGate pattern: stateless gate + TurnState observer +
GateDecision result. The gate runs in `llm_router._complete_once` at the
same four insertion points each turn:

  1. PRE-PROMPT  (before stream_completion at ~line 1366)
     → call brain.context, prepend injection to system_prompt
  2. PRE-EXECUTE (before ToolEngine.invoke at ~line 1430)
     → resolve op:// secret refs, validate memory-tool args
  3. POST-EXECUTE (after tool_result at ~line 1440)
     → call brain.write with Mem0-style op + provenance
  4. STOP (when final reached at ~line 1378)
     → call brain.skill_mint with the trace

Provider-agnostic by construction. Works for Anthropic, OpenAI, Gemini,
Ollama, LM Studio, Mistral, OpenRouter — every provider lands at the
same dispatch loop in the router.

Behaviour when the brain daemon is unreachable:
  - PRE-PROMPT  → no injection (router uses bare system prompt)
  - PRE-EXECUTE → secret resolution falls back to Windows Credential
                  Manager if op:// reference present
  - POST-EXECUTE → write swallowed silently (don't break the turn)
  - STOP → skill mint skipped

In short: ArchHub keeps working with or without the brain. Brain enriches;
it does not gate.

Slice 4 ships the gate + insertion-helper functions. Slice 5 wires the
real reflexion-worker pipeline; until then `brain.skill_mint` queues the
trace and returns immediately.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional


# ─────────────────────── data shapes ────────────────────────────────────


@dataclass
class MemoryTurnState:
    """Per-turn observer. Constructed fresh at the start of each
    `_complete_once` and disposed when the turn closes (Stop hook)."""

    context_injected: bool = False
    context_payload: dict[str, Any] = field(default_factory=dict)
    write_ops_emitted: int = 0
    tool_invocations: list[dict[str, Any]] = field(default_factory=list)
    secret_resolutions: list[dict[str, Any]] = field(default_factory=list)
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    started_at: float = field(default_factory=time.perf_counter)

    def trace(self) -> dict[str, Any]:
        """Compact trace snapshot for skill_mint."""
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "tool_calls": list(self.tool_invocations),
            "secret_resolutions_n": len(self.secret_resolutions),
            "wall_clock_s": time.perf_counter() - self.started_at,
        }


@dataclass
class GateDecision:
    """Result of a per-call gate check. Allow=True means proceed; False
    means the gate refused (e.g. brain unavailable + tool requires a
    secret with no fallback)."""

    allow: bool = True
    reason: str = ""
    augmentation: dict[str, Any] = field(default_factory=dict)


# ─────────────────────── transport (talks to brain MCP daemon) ──────────


class BrainClient:
    """Lightweight HTTP client to the local brain daemon.

    The brain runs by default on http://127.0.0.1:8473. Every call uses a
    short timeout (200ms) so an unreachable brain never blocks the router.
    """

    def __init__(self, base_url: Optional[str] = None, timeout_s: float = 0.2):
        import os
        self.base_url = (
            base_url
            or os.environ.get("BRAIN_HTTP_URL")
            or "http://127.0.0.1:8473"
        )
        self.timeout_s = timeout_s
        self._available: Optional[bool] = None  # tri-state; None = unknown

    def is_available(self) -> bool:
        """Quick reachability probe. Caches result for the process lifetime
        once it's True; re-probes on each call when not yet confirmed."""
        if self._available is True:
            return True
        try:
            self._call("brain.health", {}, timeout=0.15)
            self._available = True
            return True
        except Exception:
            self._available = False
            return False

    def context(
        self,
        prompt: str,
        *,
        owner_user: Optional[str] = None,
        project_id: Optional[str] = None,
        firm_id: Optional[str] = None,
        cwd: Optional[str] = None,
        k_skills: int = 5,
        k_facts: int = 8,
    ) -> Optional[dict[str, Any]]:
        try:
            return self._call("brain.context", {
                "prompt": prompt,
                "owner_user": owner_user,
                "project_id": project_id,
                "firm_id": firm_id,
                "cwd": cwd,
                "k_skills": k_skills,
                "k_facts": k_facts,
            })
        except Exception:
            return None

    def write(self, ops: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        try:
            return self._call("brain.write", {"ops": ops})
        except Exception:
            return None

    def skill_mint(
        self,
        trace: dict[str, Any],
        *,
        outcome: str = "success",
        owner_user: Optional[str] = None,
        contributing_agent: str = "unknown",
        session_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        try:
            return self._call("brain.skill_mint", {
                "trace": trace,
                "outcome": outcome,
                "owner_user": owner_user,
                "contributing_agent": contributing_agent,
                "session_id": session_id,
            })
        except Exception:
            return None

    def wiring_announce(
        self,
        device_id: str,
        *,
        entries: Optional[list[dict[str, Any]]] = None,
        secret_refs: Optional[list[dict[str, Any]]] = None,
        cwd: Optional[str] = None,
        git_remote: Optional[str] = None,
        owner_user: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        try:
            return self._call("brain.wiring_announce", {
                "device_id": device_id,
                "entries": entries or [],
                "secret_refs": secret_refs or [],
                "cwd": cwd,
                "git_remote": git_remote,
                "owner_user": owner_user,
            })
        except Exception:
            return None

    # ── transport impl ──────────────────────────────────────────────────

    def _call(
        self, tool: str, params: dict[str, Any], timeout: Optional[float] = None
    ) -> dict[str, Any]:
        """MCP tools/call over Streamable HTTP. Server runs stateless
        (set via `--stateless` / `stateless_http=True`); we send the
        Accept: text/event-stream header and parse the SSE wire shape.

        Verified live against FastMCP 3.3.1 at /mcp. Wire shape:
            POST {base_url}/mcp
            Headers: Content-Type: application/json
                     Accept: application/json, text/event-stream
            Body: {jsonrpc, id, method:"tools/call", params:{name, arguments}}
            Response: text/event-stream
                event: message
                data: {"jsonrpc":"2.0","id":N,"result":{"content":[...],
                       "structuredContent":{...}, "isError":bool}}
        """
        url = self.base_url.rstrip("/") + "/mcp"
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {"name": tool, "arguments": params or {}},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as resp:
            raw = resp.read().decode("utf-8")

        # Parse SSE — extract the JSON payload from `data:` lines. There
        # may be multiple `event: message` blocks; take the first that has
        # an `id` matching our request (or just the first data line).
        data: Optional[dict[str, Any]] = None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("jsonrpc") == "2.0":
                data = obj
                break

        # If we got JSON (non-SSE server) — fall back to plain parse.
        if data is None:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                raise RuntimeError(f"unparseable brain response: {raw[:200]}")

        if "error" in data and data["error"]:
            raise RuntimeError(data["error"])
        result = data.get("result") or {}
        # Tool results come back as {content:[{type:'text', text:...}],
        # structuredContent:{...}, isError:bool}. Prefer structuredContent.
        if isinstance(result, dict):
            if result.get("isError"):
                raise RuntimeError(result.get("content") or "tool error")
            if "structuredContent" in result and result["structuredContent"]:
                return result["structuredContent"]
            # Fallback: parse text content[0]
            content = result.get("content") or []
            if content and isinstance(content[0], dict):
                txt = content[0].get("text", "")
                try:
                    return json.loads(txt)
                except Exception:
                    return {"text": txt}
        return result


# ─────────────────────── gate (4 hook helpers) ──────────────────────────


def _default_journal_path() -> str:
    """Best-effort journal location: %APPDATA%/ArchHub/brain/journal.ndjson
    on Windows, ~/.local/share/archhub/brain/journal.ndjson elsewhere."""
    import os as _os
    from pathlib import Path as _Path
    if _os.name == "nt":
        base = _Path(_os.environ.get("APPDATA",
                                       str(_Path.home() / "AppData/Roaming")))
        return str(base / "ArchHub" / "brain" / "journal.ndjson")
    base = _Path(_os.environ.get("XDG_DATA_HOME",
                                   str(_Path.home() / ".local" / "share")))
    return str(base / "archhub" / "brain" / "journal.ndjson")


class ResilientBrainClientAdapter:
    """Lightweight resilience wrapper for BrainClient — borrows the
    full ResilientBrainClient from personal_brain.liveness when that
    package is on sys.path (it ships beside ArchHub).

    Behaviour when personal_brain.liveness is importable:
      • Circuit breaker on every call (hard-fail trips instantly)
      • Write journal at brain.write — durability before network
      • Cached last-context served when daemon is down
      • Status callbacks fire on every state transition

    Behaviour when the brain package isn't installed:
      • Falls back to the bare BrainClient (Slice 4 baseline behaviour).
    """

    def __init__(
        self,
        inner: "BrainClient",
        *,
        journal_path: Optional[str] = None,
        on_status: Optional[Any] = None,
    ):
        self.inner = inner
        # Ensure the bundled personal-brain-mcp/src is on sys.path so the
        # resilience wrapper resolves when ArchHub runs out of repo root.
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _bp = _Path(__file__).resolve().parent.parent / "personal-brain-mcp" / "src"
            if _bp.exists() and str(_bp) not in _sys.path:
                _sys.path.insert(0, str(_bp))
        except Exception:
            pass
        try:
            from personal_brain.liveness import (  # type: ignore
                BreakerConfig, ResilientBrainClient,
            )
            self._impl = ResilientBrainClient(
                inner,
                journal_path=journal_path or _default_journal_path(),
                breaker_config=BreakerConfig(
                    threshold=3, hard_fail_trip=True, reset_timeout_s=5.0,
                ),
                on_status=on_status,
            )
            self._has_resilient = True
        except Exception:
            self._impl = inner
            self._has_resilient = False

    def is_available(self) -> bool:
        # When wrapped, derive "available" from breaker state. When bare,
        # delegate to inner.
        if self._has_resilient:
            return self._impl.breaker.state != "open"
        return self.inner.is_available()

    def context(self, *args, **kwargs):
        if self._has_resilient:
            return self._impl.context(*args, **kwargs)
        return self.inner.context(*args, **kwargs)

    def write(self, ops):
        if self._has_resilient:
            return self._impl.write(ops)
        return self.inner.write(ops)

    def skill_mint(self, *args, **kwargs):
        if self._has_resilient:
            return self._impl.skill_mint(*args, **kwargs)
        return self.inner.skill_mint(*args, **kwargs)

    def wiring_announce(self, *args, **kwargs):
        if self._has_resilient:
            return self._impl.wiring_announce(*args, **kwargs)
        return self.inner.wiring_announce(*args, **kwargs)

    def replay_journal(self) -> int:
        if self._has_resilient:
            return self._impl.replay_journal()
        return 0

    def status(self) -> dict[str, Any]:
        if self._has_resilient:
            return self._impl.status()
        return {"breaker": {"state": "n/a (resilience not installed)"},
                "journal_pending": 0}


class MemoryGate:
    """Stateless. State lives on MemoryTurnState.

    Wire in `llm_router._complete_once`:

        gate = MemoryGate()
        turn_state = MemoryTurnState(session_id=..., trace_id=...)

        # 1. PRE-PROMPT
        decision = gate.pre_prompt(turn_state, user_message=..., owner_user=...)
        if decision.allow and decision.augmentation.get('injection'):
            system_prompt += "\\n\\n" + decision.augmentation['injection']

        # 2. for each tool call:
        decision = gate.pre_execute(turn_state, inv)
        if decision.allow:
            tool_result = ToolEngine.invoke(inv.tool_name, inv.arguments)
            gate.post_execute(turn_state, inv, tool_result, contributing_agent)

        # 3. STOP
        gate.stop(turn_state, outcome='success', owner_user=...,
                   contributing_agent=...)
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        *,
        resilient: bool = True,
    ):
        """`client` accepts either a bare BrainClient or a
        ResilientBrainClientAdapter. When `resilient=True` (default) and
        a bare BrainClient is provided, it is auto-wrapped with the
        adapter so circuit-breaker + journal + cached-context apply.
        """
        inner = client or BrainClient()
        if resilient and not isinstance(inner, ResilientBrainClientAdapter):
            self.client = ResilientBrainClientAdapter(inner)
        else:
            self.client = inner

    # ── 1. pre-prompt ──────────────────────────────────────────────────

    def pre_prompt(
        self,
        turn_state: MemoryTurnState,
        *,
        user_message: str,
        owner_user: Optional[str] = None,
        project_id: Optional[str] = None,
        firm_id: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> GateDecision:
        """Pull context from brain and prepare injection block.

        Returns GateDecision with `augmentation.injection` set (a markdown
        block to prepend to the system prompt). Empty injection if brain
        unavailable.
        """
        if not user_message or not user_message.strip():
            return GateDecision(allow=True, reason="empty prompt")
        if not self.client.is_available():
            return GateDecision(allow=True, reason="brain unavailable; bare prompt",
                                 augmentation={"injection": ""})
        payload = self.client.context(
            user_message,
            owner_user=owner_user,
            project_id=project_id,
            firm_id=firm_id,
            cwd=cwd,
        )
        if not payload:
            return GateDecision(allow=True, augmentation={"injection": ""})
        turn_state.context_injected = True
        turn_state.context_payload = payload
        return GateDecision(
            allow=True,
            augmentation={
                "injection": payload.get("injection", ""),
                "skills": payload.get("skills", []),
                "facts": payload.get("facts", []),
                "secret_refs": payload.get("secret_refs", []),
                "retrieval_ms": payload.get("retrieval_ms", 0.0),
            },
        )

    # ── 2. pre-execute ─────────────────────────────────────────────────

    def pre_execute(
        self,
        turn_state: MemoryTurnState,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        actor_user: Optional[str] = None,
        actor_project_id: Optional[str] = None,
        actor_firm_id: Optional[str] = None,
    ) -> GateDecision:
        """Pre-execute gate. Two responsibilities:

        1. Secret reference detection — scan args for op:// values;
           record them so PostToolUse can scrub them from traces.
        2. ACL enforcement on cross-scope memory writes — if the tool is
           `brain.write` or `brain.promote` and the target scope is
           above USER, verify the actor has write rights at that scope
           per arXiv 2505.18279 bipartite policy.
        """
        secret_refs = _collect_op_refs(arguments)
        for ref in secret_refs:
            turn_state.secret_resolutions.append({
                "ref": ref, "tool": tool_name, "ts": time.time(),
            })

        # Slice-7 ACL check on brain.write to non-USER scopes.
        # Skip when actor identity unknown (gate stays advisory).
        if actor_user and tool_name == "brain.write":
            denial = _acl_check_brain_write(
                arguments, actor_user=actor_user,
                actor_project_id=actor_project_id,
                actor_firm_id=actor_firm_id,
            )
            if denial is not None:
                return GateDecision(
                    allow=False, reason=denial,
                    augmentation={"secret_refs_to_resolve": secret_refs},
                )

        return GateDecision(
            allow=True,
            augmentation={"secret_refs_to_resolve": secret_refs},
        )

    # ── 3. post-execute ────────────────────────────────────────────────

    def post_execute(
        self,
        turn_state: MemoryTurnState,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        status: str = "ok",
        contributing_agent: str = "unknown",
        owner_user: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Write a memory op capturing what just happened.

        Slice-4 heuristic: every successful tool call emits an ADD op with
        a synthesized fact describing the action. Slice 5's reflexion
        worker upgrades this with LLM-generated semantic ops.

        Fire-and-forget. Brain unavailable → silent skip.
        """
        turn_state.tool_invocations.append({
            "name": tool_name,
            "args": _strip_secrets(arguments),
            "status": status,
            "ts": time.time(),
        })

        if not self.client.is_available():
            return
        if status != "ok":
            return

        fragment = _synthesize_fragment(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            contributing_agent=contributing_agent,
            owner_user=owner_user or "founder",
            session_id=session_id,
        )
        ops = [{"op": "add", "fragment": fragment}]
        resp = self.client.write(ops)
        if resp and resp.get("ops_applied", 0) > 0:
            turn_state.write_ops_emitted += 1

    # ── 4. stop ────────────────────────────────────────────────────────

    def stop(
        self,
        turn_state: MemoryTurnState,
        *,
        outcome: str = "success",
        contributing_agent: str = "unknown",
        owner_user: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Fire skill_mint with the full trace. Returns the SkillMintResult
        dict or None if brain unavailable."""
        if not self.client.is_available():
            return None
        return self.client.skill_mint(
            trace=turn_state.trace(),
            outcome=outcome,
            owner_user=owner_user,
            contributing_agent=contributing_agent,
            session_id=turn_state.session_id,
        )


# ─────────────────────── helpers ───────────────────────────────────────


def _acl_check_brain_write(
    arguments: dict[str, Any],
    *,
    actor_user: str,
    actor_project_id: Optional[str],
    actor_firm_id: Optional[str],
) -> Optional[str]:
    """Walk every fragment in a brain.write ops list and enforce scope
    rules:
      - USER scope: only actor's own user (owner_user must match actor)
      - PROJECT scope: actor's project_id must match fragment.project_id
      - FIRM scope: actor's firm_id must match fragment.firm_id
      - COMMUNITY / GLOBAL: deny here (must go through brain.promote)
    Returns reason string on denial, None on allow.
    """
    ops = arguments.get("ops") or []
    if not isinstance(ops, list):
        return None  # malformed; let server validate
    for op in ops:
        if not isinstance(op, dict):
            continue
        if op.get("op") not in ("add", "update"):
            continue
        frag = op.get("fragment") or {}
        if not isinstance(frag, dict):
            continue
        scope = frag.get("scope") or "user"
        if scope == "user":
            owner = frag.get("owner_user")
            if owner and owner != actor_user:
                return (
                    f"ACL deny: brain.write user-scope fragment owner="
                    f"{owner} but actor={actor_user}"
                )
        elif scope == "project":
            if frag.get("project_id") and frag["project_id"] != actor_project_id:
                return (
                    f"ACL deny: brain.write project-scope fragment "
                    f"project_id={frag['project_id']} but actor in "
                    f"project={actor_project_id}"
                )
        elif scope == "firm":
            if frag.get("firm_id") and frag["firm_id"] != actor_firm_id:
                return (
                    f"ACL deny: brain.write firm-scope fragment firm_id="
                    f"{frag['firm_id']} but actor in firm={actor_firm_id}"
                )
        elif scope in ("community", "global"):
            return (
                f"ACL deny: cannot brain.write directly to {scope} scope. "
                f"Use brain.promote with redaction instead."
            )
    return None


def _collect_op_refs(obj: Any) -> list[str]:
    """Walk arguments dict/list and collect any op:// vault:// wcm:// refs."""
    out: list[str] = []
    if isinstance(obj, str):
        if obj.startswith(("op://", "vault://", "wcm://")):
            out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_collect_op_refs(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_collect_op_refs(v))
    return out


def _strip_secrets(obj: Any) -> Any:
    """Recursively replace op:// refs with `<secret>` placeholder. Keeps
    structure, hides values. Used when writing traces so secrets never
    end up in memory."""
    if isinstance(obj, str):
        if obj.startswith(("op://", "vault://", "wcm://")):
            return "<secret>"
        # Heuristic: strip api-key-shaped strings (sk-…, ghp_…, AKIA…)
        if any(obj.startswith(p) for p in ("sk-", "ghp_", "AKIA", "ya29.")):
            return "<secret>"
        return obj
    if isinstance(obj, dict):
        return {k: _strip_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_secrets(v) for v in obj]
    return obj


def _synthesize_fragment(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    contributing_agent: str,
    owner_user: str,
    session_id: Optional[str],
) -> dict[str, Any]:
    """Synthesize a fragment from a successful tool call.

    Slice-4 heuristic: text = `tool_name(args_keys) → result_summary`.
    Slice 5 replaces with an LLM-extracted semantic fact (subject /
    predicate / object).
    """
    import hashlib

    args_clean = _strip_secrets(arguments or {})
    args_keys = ", ".join(sorted(args_clean.keys())) if isinstance(args_clean, dict) else ""

    result_summary = _summarise_result(result)
    text = f"{tool_name}({args_keys}) → {result_summary}"

    frag_id_seed = f"{tool_name}|{json.dumps(args_clean, sort_keys=True, default=str)[:200]}"
    frag_id = hashlib.sha256(frag_id_seed.encode("utf-8")).hexdigest()

    return {
        "id": frag_id,
        "kind": "fact",
        "text": text,
        "subject": tool_name,
        "predicate": "produced",
        "object": result_summary[:120],
        "scope": "user",
        "visibility": "private",
        "owner_user": owner_user,
        "confidence": "extracted",
        "provenance": {
            "contributing_agent": contributing_agent,
            "contributing_user": owner_user,
            "session_id": session_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }


def _summarise_result(result: Any) -> str:
    """Compact one-line summary of a tool result for memory text."""
    if result is None:
        return "no result"
    if isinstance(result, (str, int, float, bool)):
        return str(result)[:160]
    if isinstance(result, dict):
        if "status" in result:
            base = f"status={result['status']}"
            if "result" in result and result["result"] is not None:
                base += f"; result={str(result['result'])[:80]}"
            return base[:160]
        # generic dict — pick a few interesting keys
        keys = sorted(result.keys())[:5]
        return "dict{" + ", ".join(keys) + "}"
    if isinstance(result, list):
        return f"list[{len(result)}]"
    return type(result).__name__
