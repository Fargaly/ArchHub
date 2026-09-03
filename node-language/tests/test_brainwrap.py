"""Focused tests for the vendor-agnostic brain launcher (tools/brainwrap.py).

Covers the three contract guarantees the launcher must hold:

  1. Daemon-DOWN path is graceful (fail-OPEN): a dead brain degrades the
     session to "no context / no diligence" but NEVER raises and NEVER stops
     the vendor CLI from running.
  2. brain.health / brain.context calls are well-formed: correct MCP
     JSON-RPC envelope, correct tool names + argument shapes (matching the
     personal_brain.server tool signatures), correct Accept header, and the
     SSE reply is parsed via the SAME path the Stop gate uses.
  3. The wrapped vendor process's exit code is preserved verbatim.

We mock at two seams only:
  * urllib.request.urlopen  → exercises the REAL call_tool + _parse_sse +
    SSE byte assembly (no transport stubbing above that line).
  * subprocess (Popen / call) → so daemon-start + vendor-exec don't spawn
    real processes.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# tools/ on path so `import brainwrap` works (brainwrap also self-inserts it).
TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import brainwrap  # noqa: E402


# ───────────────────────── helpers ─────────────────────────────────────


def _sse_bytes(result: dict) -> bytes:
    """Encode a tool result the way the FastMCP HTTP transport does: an SSE
    `data:` line carrying a JSON-RPC response whose result.structuredContent
    is the tool's return dict. _parse_sse must decode exactly this."""
    envelope = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"structuredContent": result},
    }
    return f"event: message\ndata: {json.dumps(envelope)}\n\n".encode("utf-8")


class _FakeResp:
    """Minimal context-manager stand-in for urlopen()'s return."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Capturing:
    """urlopen replacement that records every Request and replies with a
    routed SSE payload keyed by the tool name in the request body."""

    def __init__(self, routes: dict[str, dict]):
        self.routes = routes
        self.calls: list[dict] = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        name = body["params"]["name"]
        self.calls.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": {k.lower(): v for k, v in req.header_items()},
            "body": body,
            "timeout": timeout,
        })
        result = self.routes.get(name, {"ok": True})
        return _FakeResp(_sse_bytes(result))

    def by_name(self, name: str) -> dict:
        for c in self.calls:
            if c["body"]["params"]["name"] == name:
                return c
        raise AssertionError(f"no call to {name}; saw "
                             f"{[c['body']['params']['name'] for c in self.calls]}")

    def names(self) -> list[str]:
        return [c["body"]["params"]["name"] for c in self.calls]


# ═══════════════════ 1. well-formed health / context ════════════════════


class TestCallShapes:
    def test_health_envelope_is_well_formed(self):
        cap = _Capturing({"brain.health": {"ok": True, "db_path": "/x/brain.db"}})
        with patch.object(brainwrap.urllib.request, "urlopen", cap):
            res = brainwrap.probe_health()
        assert res is not None and res["ok"] is True

        call = cap.by_name("brain.health")
        # POST to the daemon /mcp endpoint.
        assert call["method"] == "POST"
        assert call["url"] == brainwrap.DAEMON_URL
        # JSON-RPC 2.0 tools/call envelope.
        b = call["body"]
        assert b["jsonrpc"] == "2.0"
        assert b["method"] == "tools/call"
        assert b["params"]["name"] == "brain.health"
        assert b["params"]["arguments"] == {}
        # Must advertise it accepts the SSE stream the daemon returns.
        assert "text/event-stream" in call["headers"]["accept"]
        assert call["headers"]["content-type"] == "application/json"

    def test_context_call_matches_server_signature(self):
        # server.brain_context(prompt, owner_user?, cwd?, ...) — we send
        # prompt + cwd + owner_user, and read back the `injection` field.
        inj = "<brain_context>\n## Relevant facts\n- be diligent\n</brain_context>"
        cap = _Capturing({"brain.context": {"injection": inj, "skills": [],
                                            "facts": []}})
        with patch.object(brainwrap.urllib.request, "urlopen", cap):
            got = brainwrap.fetch_context("fix the wire bug", "/repo/x")

        assert got == inj  # injection block extracted from the SSE result
        args = cap.by_name("brain.context")["body"]["params"]["arguments"]
        assert args["prompt"] == "fix the wire bug"
        assert args["cwd"] == "/repo/x"
        assert "owner_user" in args  # present (may be None) — server tolerates

    def test_wiring_announce_matches_server_signature(self):
        cap = _Capturing({"brain.wiring_announce": {"registered": 1,
                                                    "skipped": 0}})
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             patch.object(brainwrap, "_git_remote",
                          return_value="git@github.com:archhub/x.git"):
            brainwrap.announce_wiring("/repo/x", "codex")

        args = cap.by_name("brain.wiring_announce")["body"]["params"]["arguments"]
        # device_id is required by the server tool.
        assert args["device_id"]
        assert args["cwd"] == "/repo/x"
        assert args["git_remote"] == "git@github.com:archhub/x.git"
        # entries is a list of WiringEntry-shaped dicts with the required
        # `name`, `kind`, `device_id` fields.
        assert isinstance(args["entries"], list) and args["entries"]
        e = args["entries"][0]
        assert e["name"] == "codex"
        assert e["kind"] == "cli"
        assert e["device_id"] == args["device_id"]

    def test_parse_sse_reads_structured_content(self):
        # The launcher must decode the same SSE shape the gate does.
        raw = _sse_bytes({"ok": True, "verdict": "allow"})
        assert brainwrap._parse_sse(raw) == {"ok": True, "verdict": "allow"}

    def test_parse_sse_reads_text_content_fallback(self):
        # When result carries content[].text instead of structuredContent.
        env = {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": json.dumps({"ok": True})}]}}
        raw = f"data: {json.dumps(env)}\n\n".encode("utf-8")
        assert brainwrap._parse_sse(raw) == {"ok": True}


# ═══════════════════ 2. daemon-down graceful (fail-open) ═════════════════


def _boom(*a, **k):
    raise ConnectionRefusedError("daemon down")


class TestDaemonDownGraceful:
    def test_probe_health_returns_none_when_refused(self):
        with patch.object(brainwrap.urllib.request, "urlopen", _boom):
            assert brainwrap.probe_health() is None  # no raise

    def test_ensure_daemon_no_autostart_is_graceful(self):
        with patch.object(brainwrap.urllib.request, "urlopen", _boom):
            ok, note = brainwrap.ensure_daemon(auto_start=False)
        assert ok is False
        assert "down" in note.lower()

    def test_fetch_context_none_when_down(self):
        with patch.object(brainwrap.urllib.request, "urlopen", _boom):
            assert brainwrap.fetch_context("p", "/c") is None  # no raise

    def test_run_diligence_fail_open_when_down(self, tmp_path):
        # A real transcript exists, but the daemon is down AND the local
        # policy is patched unavailable → must fail-open (ran=False), no raise.
        tj = tmp_path / "t.jsonl"
        tj.write_text(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "all done"}]},
        }) + "\n", encoding="utf-8")

        import anti_laziness_gate as gate
        with patch.object(brainwrap.urllib.request, "urlopen", _boom), \
             patch.object(gate, "evaluate_local", return_value={}):
            summary = brainwrap.run_diligence(str(tj), str(tmp_path),
                                              vendor="codex", exit_code=0)
        assert summary["ran"] is False
        assert summary["verdict"] is None

    def test_run_diligence_no_transcript_is_noop(self, tmp_path):
        # No transcript path → nothing to judge → graceful no-op.
        with patch.object(brainwrap.urllib.request, "urlopen", _boom):
            summary = brainwrap.run_diligence(None, str(tmp_path),
                                              vendor="codex", exit_code=0)
        assert summary["ran"] is False

    def test_launch_runs_vendor_even_when_brain_down(self, tmp_path):
        # End-to-end: brain unreachable, auto-start disabled. The vendor CLI
        # must STILL run and its exit code propagate. Diligence skipped.
        opts = _launch_opts(cwd=str(tmp_path), skip_daemon_start=True)
        with patch.object(brainwrap.urllib.request, "urlopen", _boom), \
             patch.object(brainwrap.subprocess, "call",
                          return_value=0) as call_mock:
            code = brainwrap.cmd_launch(opts, ["echo", "hi"])
        assert code == 0
        assert call_mock.called  # vendor was executed despite dead brain


# ═══════════════════ 3. daemon-start command reuse ══════════════════════


class TestDaemonStartCommand:
    def test_start_command_reuses_service_and_targets_port(self):
        # daemon_start_command must reuse personal_brain.service._brain_command
        # and append `--http <DAEMON_PORT>` — the exact invocation the service
        # registers for autostart.
        from personal_brain import service as svc
        with patch.object(svc, "_brain_command",
                          return_value='"C:\\Py\\python.exe" -m personal_brain.server'):
            argv = brainwrap.daemon_start_command()
        assert "-m" in argv and "personal_brain.server" in argv
        assert "--http" in argv
        assert str(brainwrap.DAEMON_PORT) in argv
        # The quoted interpreter path is unwrapped into a clean token.
        assert any(tok.endswith("python.exe") for tok in argv)

    def test_ensure_daemon_starts_then_polls_health(self):
        # Down on first probe → Popen the daemon → healthy on next probe.
        probes = [None, {"ok": True, "db_path": "/x"}]

        def fake_probe(*a, **k):
            return probes.pop(0) if probes else {"ok": True}

        with patch.object(brainwrap, "probe_health", side_effect=fake_probe), \
             patch.object(brainwrap.subprocess, "Popen") as popen, \
             patch.object(brainwrap, "daemon_start_command",
                          return_value=["python", "-m", "personal_brain.server",
                                        "--http", "8473"]):
            ok, note = brainwrap.ensure_daemon(wait_s=5.0, log=False)
        assert ok is True
        assert popen.called  # we actually launched the daemon


# ═══════════════════ 4. exit-code preservation ══════════════════════════


class TestExitCodePreserved:
    @pytest.mark.parametrize("rc", [0, 1, 2, 42, 137])
    def test_run_vendor_passes_through_exit_code(self, rc, tmp_path):
        with patch.object(brainwrap.subprocess, "call",
                          return_value=rc) as call_mock:
            got = brainwrap.run_vendor(["mytool", "--flag"], cwd=str(tmp_path))
        assert got == rc
        # Executed with cwd preserved and argv intact.
        args, kwargs = call_mock.call_args
        assert kwargs["cwd"] == str(tmp_path)
        assert args[0][-2:] == ["mytool", "--flag"] or args[0][1:] == ["--flag"]

    def test_run_vendor_missing_binary_returns_127(self, tmp_path):
        with patch.object(brainwrap.subprocess, "call",
                          side_effect=FileNotFoundError):
            got = brainwrap.run_vendor(["does-not-exist"], cwd=str(tmp_path))
        assert got == 127

    @pytest.mark.parametrize("rc", [0, 3, 99])
    def test_cmd_launch_returns_vendor_code(self, rc, tmp_path):
        # Brain healthy; full lifecycle; the vendor's code must come back out.
        cap = _Capturing({
            "brain.health": {"ok": True, "db_path": "/x"},
            "brain.context": {"injection": ""},
            "brain.wiring_announce": {"registered": 0},
        })
        opts = _launch_opts(cwd=str(tmp_path))
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             patch.object(brainwrap.subprocess, "call", return_value=rc), \
             patch.object(brainwrap, "_git_remote", return_value=None), \
             patch.object(brainwrap, "run_diligence", return_value={}):
            code = brainwrap.cmd_launch(opts, ["vendor", "do"])
        assert code == rc

    def test_stdin_prefix_path_preserves_code(self, tmp_path):
        # When context is piped on stdin, run_vendor uses Popen; the wait()
        # return code must propagate.
        proc = MagicMock()
        proc.stdin = io.BytesIO()
        proc.wait.return_value = 7
        with patch.object(brainwrap.subprocess, "Popen", return_value=proc):
            got = brainwrap.run_vendor(["v"], cwd=str(tmp_path),
                                       stdin_prefix="ctx\n")
        assert got == 7
        proc.wait.assert_called_once()


# ═══════════════════ 5. diligence parity + advisory ═════════════════════


class TestDiligenceAdvisory:
    def _transcript(self, tmp_path) -> str:
        tj = tmp_path / "t.jsonl"
        tj.write_text(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text",
                                     "text": "shipped the fix"}]},
        }) + "\n", encoding="utf-8")
        return str(tj)

    def test_enforce_diligence_call_is_well_formed(self, tmp_path):
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": [],
                                        "reason": "ok"},
            "brain.skill_mint": {"queued": False, "reason": "n/a"},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap):
            summary = brainwrap.run_diligence(self._transcript(tmp_path),
                                              str(tmp_path), vendor="codex",
                                              exit_code=0)
        assert summary["ran"] is True
        assert summary["verdict"] == "allow"
        # The diligence payload carries the same evidence keys the Stop gate
        # sends (built by anti_laziness_gate.extract_signals).
        args = cap.by_name("brain.enforce_diligence")["body"]["params"]["arguments"]
        for key in ("last_message", "touched_files", "file_contents",
                    "session_signals"):
            assert key in args
        assert args["last_message"] == "shipped the fix"

    def test_block_verdict_is_advisory_not_enforced(self, tmp_path):
        # Even on a BLOCK verdict, run_diligence reports it but does not raise
        # or otherwise change control flow — it is post-hoc + advisory.
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "block",
                                        "violations": ["no tests run"],
                                        "reason": "do the work"},
            "brain.skill_mint": {"queued": False},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap):
            summary = brainwrap.run_diligence(self._transcript(tmp_path),
                                              str(tmp_path), vendor="codex",
                                              exit_code=0)
        assert summary["verdict"] == "block"
        assert summary["ran"] is True  # ran, reported, did not throw

    def test_cmd_launch_with_block_still_returns_vendor_code(self, tmp_path):
        # The whole point: a block verdict must NOT override the vendor's
        # successful (0) exit. Wrapper is post-hoc, never a hard gate.
        self._transcript(tmp_path)  # creates .brainwrap_transcript? no — pass explicit
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.health": {"ok": True, "db_path": "/x"},
            "brain.context": {"injection": ""},
            "brain.wiring_announce": {"registered": 0},
            "brain.enforce_diligence": {"verdict": "block",
                                        "violations": ["lazy"],
                                        "reason": "keep going"},
            "brain.skill_mint": {"queued": False},
        })
        opts = _launch_opts(cwd=str(tmp_path), transcript=tj)
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             patch.object(brainwrap.subprocess, "call", return_value=0), \
             patch.object(brainwrap, "_git_remote", return_value=None):
            code = brainwrap.cmd_launch(opts, ["vendor", "do"])
        assert code == 0  # vendor's success preserved despite block verdict
        assert "brain.enforce_diligence" in cap.names()


# ═══════════════════ 6. backward-compat: hook subcommands ════════════════


class TestHookSubcommandsStillWork:
    """The installer wires `brainwrap context|stop --vendor cursor` into
    Cursor hooks. Extending the file with `launch` must not break them."""

    def test_health_subcommand(self, capsys):
        cap = _Capturing({"brain.health": {"ok": True}})
        with patch.object(brainwrap.urllib.request, "urlopen", cap):
            rc = brainwrap.main(["health"])
        assert rc == 0
        assert "ok" in capsys.readouterr().out

    def test_context_subcommand_cursor_shape(self, capsys):
        cap = _Capturing({"brain.context": {"injection": "CTX"}})
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             patch.object(brainwrap.sys, "stdin",
                          io.StringIO(json.dumps({"prompt": "hi"}))):
            rc = brainwrap.main(["context", "--vendor", "cursor"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["continue"] is True
        assert out["user_message"] == "CTX"

    def test_bare_double_dash_routes_to_launch(self, tmp_path):
        # `brainwrap -- echo hi` (no subcommand) must default to launch.
        cap = _Capturing({
            "brain.health": {"ok": True, "db_path": "/x"},
            "brain.context": {"injection": ""},
            "brain.wiring_announce": {"registered": 0},
        })
        argv = ["--cwd", str(tmp_path), "--skip-daemon-start",
                "--", "echo", "hi"]
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             patch.object(brainwrap.subprocess, "call", return_value=0) as cm, \
             patch.object(brainwrap, "run_diligence", return_value={}):
            rc = brainwrap.main(argv)
        assert rc == 0
        assert cm.called


# ═══════════════════ 7. per-turn brain flush (learning gap) ══════════════


class TestStopFlushesBrainMemory:
    """The brain-LEARNING gap closer: Claude Code writes the brain per-tool
    (PostToolUse→brain.write); foreign vendors (Codex/Gemini/Cursor) have no
    per-tool write, so cmd_stop flushes the turn's salient memory to brain.write
    ONCE — AFTER the diligence verdict — reusing the gate's extracted evidence.

    Contract guarantees pinned here:
      A. cmd_stop calls brain.write with a WELL-FORMED record (validates against
         the REAL server WriteOp model — no invented contract) after the verdict.
      B. The flush is FAIL-OPEN: a dead brain (or any flush error) never raises
         and never changes the vendor's stop contract on stdout.
      C. The stop verdict is still emitted (block/continue) regardless of flush.
      D. An empty/no-final-message turn writes NOTHING (no hollow fragment).
    """

    def _stdin(self, payload: dict):
        return patch.object(brainwrap.sys, "stdin",
                            io.StringIO(json.dumps(payload)))

    def _transcript(self, tmp_path, text="shipped the fix and ran the tests",
                    with_test_cmd=True) -> str:
        """A minimal Claude-Code-shaped JSONL: one tool_use (a pytest bash call,
        so a proof signal fires) + a final assistant text block."""
        tj = tmp_path / "t.jsonl"
        lines = []
        if with_test_cmd:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "python -m pytest -q"}}]},
            }))
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]},
        }))
        tj.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(tj)

    # ── A. well-formed brain.write after the verdict ────────────────────────
    def test_stop_writes_well_formed_brain_record(self, tmp_path, capsys):
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": [],
                                        "reason": "ok"},
            "brain.write": {"ops_applied": 1, "fragments_added": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        # brain.write was called exactly once (per-turn flush, not per-tool).
        assert cap.names().count("brain.write") == 1
        args = cap.by_name("brain.write")["body"]["params"]["arguments"]
        assert "ops" in args and isinstance(args["ops"], list) and args["ops"]
        op = args["ops"][0]
        assert op["op"] == "add"
        frag = op["fragment"]
        # carries the turn's salient memory: final message + proof + files.
        assert "shipped the fix" in frag["text"]
        assert frag["provenance"]["contributing_agent"] == "brainwrap:generic"
        # The record validates against the REAL server contract (no invented
        # shape): WriteOp.model_validate must accept it unchanged.
        from personal_brain.models import WriteOp
        wo = WriteOp.model_validate(op)
        assert wo.op.value == "add"
        assert wo.fragment.kind.value == "fact"

    def test_flush_fires_after_verdict_not_before(self, tmp_path):
        # Ordering matters: the diligence verdict is computed first, then the
        # flush — so the memory record can carry the verdict tag. Assert
        # brain.enforce_diligence precedes brain.write in the call sequence.
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            brainwrap.cmd_stop("generic")
        names = cap.names()
        assert names.index("brain.enforce_diligence") < names.index("brain.write")

    def test_block_verdict_recorded_in_memory(self, tmp_path):
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "block",
                                        "violations": ["no tests"],
                                        "reason": "do the work"},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            brainwrap.cmd_stop("generic")
        frag = cap.by_name("brain.write")["body"]["params"]["arguments"]["ops"][0]["fragment"]
        assert frag["extra"]["diligence_verdict"] == "block"
        assert "do the work" in frag["extra"]["diligence_reason"]

    # ── B. fail-open when brain is down ─────────────────────────────────────
    def test_flush_fail_open_when_brain_down(self, tmp_path):
        # brain.write transport refused → no raise, cmd_stop still returns 0.
        # (enforce_diligence also fails; the local policy fallback is patched
        # out so the whole stop path runs with a dead brain.)
        tj = self._transcript(tmp_path)
        import anti_laziness_gate as gate
        with patch.object(brainwrap.urllib.request, "urlopen", _boom), \
             patch.object(gate, "evaluate_local", return_value={}), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0  # fail-open: dead brain never bricks the stop hook

    def test_flush_fail_open_on_internal_error(self, tmp_path, capsys):
        # If the record builder itself throws, flush swallows it (fail-open)
        # and the stop contract is untouched.
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             patch.object(brainwrap, "_memory_record",
                          side_effect=RuntimeError("boom")), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        assert "fail-open" in capsys.readouterr().err

    # ── C. stop verdict still emitted regardless of the flush ───────────────
    def test_cursor_block_contract_preserved_with_flush(self, tmp_path, capsys):
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "block",
                                        "violations": ["lazy"],
                                        "reason": "keep going"},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("cursor")
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        # Cursor block contract: continue=false + followup loops the agent back —
        # unchanged by the new flush.
        assert out["continue"] is False
        assert out["followup_message"] == "keep going"
        assert "brain.write" in cap.names()  # flush still happened

    def test_generic_allow_writes_no_stdout_but_still_flushes(self, tmp_path,
                                                              capsys):
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        # generic + allow → no block JSON on stdout (Claude's allow contract).
        assert capsys.readouterr().out == ""
        # …but the brain still learned this turn.
        assert "brain.write" in cap.names()

    # ── D. empty turn writes nothing ────────────────────────────────────────
    def test_no_transcript_writes_nothing(self, tmp_path):
        cap = _Capturing({"brain.write": {"ops_applied": 1}})
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"cwd": str(tmp_path)}):  # no transcript_path
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        assert "brain.write" not in cap.names()  # nothing salient → no flush

    def test_empty_final_message_writes_nothing(self, tmp_path):
        # Transcript exists but the final assistant turn has no text → the gate
        # yields no last_message → no hollow fragment is written.
        tj = tmp_path / "empty.jsonl"
        tj.write_text(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash",
                 "input": {"command": "ls"}}]},
        }) + "\n", encoding="utf-8")
        cap = _Capturing({"brain.write": {"ops_applied": 1}})
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": str(tj), "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        assert "brain.write" not in cap.names()

    def test_memory_record_none_on_empty(self):
        assert brainwrap._memory_record(
            {"last_message": ""}, vendor="codex", blocked=False, reason="") is None

    def test_flush_via_main_stop_subcommand(self, tmp_path):
        # End-to-end through main(["stop"]) — the entry the installer wires into
        # every vendor's stop/after-agent hook — flushes the brain once.
        tj = self._transcript(tmp_path)
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.main(["stop", "--vendor", "generic"])
        assert rc == 0
        assert cap.names().count("brain.write") == 1


# ═══════════════ 8. THE DRIVE wired into brainwrap (court defect #5) ══════


class TestDrivePrePromptInject:
    """The pre-prompt DRIVE for foreign vendors: in ADDITION to RECALL
    (brain.context), brainwrap's `context` hook injects the <assigned_leaf>
    block the brain hands this runtime (brain.work_assigned_block, claimed
    atomically). Without it the brain drives Claude Code but not Codex/Gemini/
    Cursor — the headline court defect #5 for the foreign-vendor hook path."""

    def _stdin(self, payload: dict):
        return patch.object(brainwrap.sys, "stdin",
                            io.StringIO(json.dumps(payload)))

    def test_context_hook_calls_work_assigned_block_with_runtime(self):
        """cmd_context fires brain.work_assigned_block (the DRIVE) with the
        vendor as the runtime, alongside brain.context (the RECALL)."""
        cap = _Capturing({
            "brain.context": {"injection": "RECALL"},
            "brain.work_assigned_block": {
                "ok": True,
                "block": "<assigned_leaf>\nwork: do X\n</assigned_leaf>"},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"prompt": "hi"}):
            rc = brainwrap.main(["context", "--vendor", "generic"])
        assert rc == 0
        # BOTH the recall and the drive tool were called.
        assert "brain.context" in cap.names()
        assert "brain.work_assigned_block" in cap.names()
        args = cap.by_name("brain.work_assigned_block")["body"]["params"]["arguments"]
        assert args["runtime"] == "generic"   # the vendor drives as this runtime

    def test_generic_context_emits_recall_plus_drive_block(self, capsys):
        cap = _Capturing({
            "brain.context": {"injection": "RECALL-BLOCK"},
            "brain.work_assigned_block": {
                "ok": True, "block": "<assigned_leaf>\nwork: ship it\n</assigned_leaf>"},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"prompt": "do the thing"}):
            brainwrap.main(["context", "--vendor", "generic"])
        out = capsys.readouterr().out
        assert "RECALL-BLOCK" in out          # recall present
        assert "<assigned_leaf>" in out       # DRIVE present
        assert "ship it" in out

    def test_cursor_context_merges_recall_and_drive_into_user_message(self, capsys):
        cap = _Capturing({
            "brain.context": {"injection": "RECALL"},
            "brain.work_assigned_block": {
                "ok": True, "block": "<assigned_leaf>\nwork: A\n</assigned_leaf>"},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"prompt": "x"}):
            brainwrap.main(["context", "--vendor", "cursor"])
        out = json.loads(capsys.readouterr().out)
        assert out["continue"] is True
        assert "RECALL" in out["user_message"]
        assert "<assigned_leaf>" in out["user_message"]

    def test_drive_dry_frontier_emits_recall_only(self, capsys):
        # Daemon answers but the frontier is dry (no block) → only recall shows;
        # the turn is never blocked by an idle drive.
        cap = _Capturing({
            "brain.context": {"injection": "RECALL"},
            "brain.work_assigned_block": {"ok": True, "block": ""},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"prompt": "x"}):
            brainwrap.main(["context", "--vendor", "generic"])
        out = capsys.readouterr().out
        assert "RECALL" in out
        assert "<assigned_leaf>" not in out

    def test_drive_fit_passed_from_env(self, monkeypatch):
        monkeypatch.setenv("BRAIN_RUNTIME_FIT", "revit, python")
        cap = _Capturing({
            "brain.context": {"injection": ""},
            "brain.work_assigned_block": {"ok": True, "block": ""},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"prompt": "x"}):
            brainwrap.main(["context", "--vendor", "generic"])
        args = cap.by_name("brain.work_assigned_block")["body"]["params"]["arguments"]
        assert args["fit"] == ["revit", "python"]


class TestStopBrainLedgerGate:
    """THE DRIVE's Stop consumer for foreign vendors: cmd_stop ALSO asks the
    brain ledger (over the daemon) whether this runtime still has an open/red
    leaf and BLOCKS the exit if so — the half that makes the pre-prompt pull
    binding (the foreign-vendor analogue of Claude Code's Stop → completion_gate)."""

    def _stdin(self, payload: dict):
        return patch.object(brainwrap.sys, "stdin",
                            io.StringIO(json.dumps(payload)))

    def _transcript(self, tmp_path, text="all green") -> str:
        tj = tmp_path / "t.jsonl"
        tj.write_text(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]},
        }) + "\n", encoding="utf-8")
        return str(tj)

    def test_open_red_leaf_blocks_even_when_diligence_allows(self, tmp_path,
                                                             capsys):
        """Diligence says allow, but the brain ledger has a CLAIMED leaf whose
        file_exists gate is RED → cmd_stop must BLOCK (the drive wins: undone,
        gated work is the strongest keep-going signal)."""
        tj = self._transcript(tmp_path)
        ledger = {"leaves": {"L1": {
            "state": "claimed", "title": "ship X",
            "gate_kind": "file_exists",
            "gate_spec": {"path": "definitely_absent.flag"}}},
            "iterations": 0, "cap": 12}
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
            "brain.work_get": {"ok": True, "ledger": ledger},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        out = json.loads(capsys.readouterr().out or "{}")
        assert out.get("decision") == "block", (
            f"open red leaf must block the foreign-vendor stop; got {out!r}")
        assert "brain:daemon" in out.get("reason", "")

    def test_done_leaf_allows_when_diligence_allows(self, tmp_path, capsys):
        """Ledger leaf DONE + diligence allow → no block (drive dry)."""
        tj = self._transcript(tmp_path)
        ledger = {"leaves": {"L1": {
            "state": "done", "title": "ship X", "gate_kind": "file_exists",
            "gate_spec": {"path": "x"}}}, "iterations": 0, "cap": 12}
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
            "brain.work_get": {"ok": True, "ledger": ledger},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        assert capsys.readouterr().out == ""   # allow → no block JSON

    def test_satisfied_gate_allows(self, tmp_path, capsys):
        """A claimed leaf whose file_exists gate is GREEN (the file is present)
        does not block — the gate runs against the REAL artifact."""
        (tmp_path / "present.flag").write_text("ok", encoding="utf-8")
        tj = self._transcript(tmp_path)
        ledger = {"leaves": {"L1": {
            "state": "claimed", "title": "ship X", "gate_kind": "file_exists",
            "gate_spec": {"path": "present.flag"}}}, "iterations": 0, "cap": 12}
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
            "brain.work_get": {"ok": True, "ledger": ledger},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_ledger_gate_fail_open_when_daemon_down(self, tmp_path):
        """Daemon down → work_get returns None → the ledger gate fails open
        (no spurious block off an unrelated on-disk default ledger)."""
        # diligence local policy patched empty so the stop runs fully dead-brain.
        import anti_laziness_gate as gate
        tj = self._transcript(tmp_path)
        with patch.object(brainwrap.urllib.request, "urlopen", _boom), \
             patch.object(gate, "evaluate_local", return_value={}), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0   # fail-open: no raise, no spurious block

    def test_blocked_leaf_escalates(self, tmp_path, capsys):
        """A BLOCKED ledger leaf (needs the founder) surfaces as a block-with-
        escalation reason — never a silent allow."""
        tj = self._transcript(tmp_path)
        ledger = {"leaves": {"L1": {
            "state": "blocked", "title": "needs a credential",
            "gate_kind": "manual", "gate_spec": {}}}, "iterations": 0, "cap": 12}
        cap = _Capturing({
            "brain.enforce_diligence": {"verdict": "allow", "violations": []},
            "brain.work_get": {"ok": True, "ledger": ledger},
            "brain.write": {"ops_applied": 1},
        })
        with patch.object(brainwrap.urllib.request, "urlopen", cap), \
             self._stdin({"transcript_path": tj, "cwd": str(tmp_path)}):
            rc = brainwrap.cmd_stop("generic")
        assert rc == 0
        out = json.loads(capsys.readouterr().out or "{}")
        assert out.get("decision") == "block"
        assert "ESCALATE" in out.get("reason", "")


# ───────────────────────── shared opts builder ─────────────────────────


def _launch_opts(*, cwd: str, transcript=None, context_file=None,
                 prompt="", skip_daemon_start=False, no_stdin_context=True):
    """Build the argparse.Namespace cmd_launch expects (mirrors
    _add_launch_opts). no_stdin_context defaults True in tests so we don't
    accidentally take the Popen stdin path when asserting subprocess.call."""
    import argparse
    return argparse.Namespace(
        cmd="launch",
        cwd=cwd,
        transcript=transcript,
        context_file=context_file,
        prompt=prompt,
        skip_daemon_start=skip_daemon_start,
        no_stdin_context=no_stdin_context,
    )
