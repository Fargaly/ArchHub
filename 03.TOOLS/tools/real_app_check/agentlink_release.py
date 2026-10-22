"""Mandatory real-client Workshop qualification; no installed profile mutation.

The qualification owns one disposable profile. Only provider credentials are
read into child environment memory; credentials never enter fixture files or
the evidence. A successful provider answer is insufficient: persisted mailbox
receipts and independent filesystem readback must agree.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import inspect
import json
import os
import re
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import time
from uuid import uuid4


class QualificationRefused(RuntimeError):
    pass


def source_digest(root):
    source = Path(root) / "01.APP" if Path(root, "01.APP").is_dir() else Path(root)
    paths = [Path(__file__).resolve(), *Path(source, "nodelang").rglob("*.py"),
             *Path(source, "nodelang/session_link").rglob("*.mjs")]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def require_checks(checks):
    for name in ("exchange", "overlap", "opencode"):
        if checks.get(name) is not True:
            raise QualificationRefused("AGENTLINK release refused: " + name + " has no real-process proof")


def tool_receipts(output):
    """Only completed tool results qualify; prompts and final prose never do."""
    rows, names = [], {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "tool_use":
            part = event.get("part", {})
            if part.get("state", {}).get("status") == "completed":
                rows.append((part.get("tool", ""), part["state"].get("output")))
        if event.get("type") == "goose_acp":
            update = event.get("params", {}).get("update", {})
            identity = ((update.get("_meta") or {}).get("goose") or {}).get("toolCall")
            call = update.get("toolCallId")
            if isinstance(identity, dict):
                names[call] = identity.get("toolName", "")
            if update.get("status") == "completed" and "content" in update:
                rows.append((names.get(call, ""), update["content"]))
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                names[block.get("id")] = block.get("name", "")
            if block.get("type") == "tool_result" and not block.get("is_error"):
                rows.append((names.get(block.get("tool_use_id"), ""), block.get("content")))
    return rows


def read_messages(output):
    messages = []
    def collect(value):
        if isinstance(value, str):
            try:
                collect(json.loads(value))
            except ValueError:
                return
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            if isinstance(value.get("messages"), list):
                messages.extend(value["messages"])
            for key in ("content", "structuredContent", "text"):
                if key in value:
                    collect(value[key])
    for tool, result in tool_receipts(output):
        if tool.endswith(("_read", "__read")):
            collect(result)
    return messages


def write_sequence(output):
    names = [name for name, _ in tool_receipts(output) if name in {"write", "read", "glob", "list"}]
    return len(names) >= 4 and names[:3] == ["write", "read", "write"] and names[3] in {"glob", "list"}


def _run(command, *, env, cwd, timeout=150):
    from nodelang.session_link_transport import _OwnedProcessJob
    process = None
    job = None
    try:
        process = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        job = _OwnedProcessJob(process)
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or b""
        _log_tools(raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw)
        raise QualificationRefused("Provider did not complete its isolated turn: TimeoutExpired") from exc
    except OSError as exc:
        raise QualificationRefused("Provider did not complete its isolated turn: " + type(exc).__name__) from exc
    finally:
        if job is not None:
            job.close()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
    if process.returncode:
        from nodelang.model_router import redact_user_visible
        detail = redact_user_visible((stdout or stderr)[-2000:])
        detail = re.sub(r"(?:eyJ|sk-|sk_)[A-Za-z0-9_.-]{12,}", "[redacted]", detail)
        print("PROVIDER ERROR", detail[:1600], flush=True)
        raise QualificationRefused("Provider returned nonzero exit " + str(process.returncode))
    return stdout


def _log_tools(output):
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "tool_use":
            part = event.get("part", {})
            state = part.get("state", {})
            print("OPENCODE TOOL", part.get("tool"), state.get("status"),
                  str(state.get("error", ""))[:1200], flush=True)


def _executable(candidate, fallback):
    path = Path(candidate) if candidate else Path(fallback)
    if not path.is_file():
        raise QualificationRefused("Required real provider executable unavailable: " + path.name)
    return str(path.resolve())


def isolated_environment(profile):
    env = {key:value for key,value in os.environ.items() if not key.startswith(
        ("ARCHHUB_", "CODEX_", "CLAUDE", "OPENCODE_", "SESSION_LINK_", "GEMINI_", "GOOSE_"))}
    for name in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP",
                 "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        env[name] = str(profile)
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               ARCHHUB_TEST_STATE_DIR=str(profile), ARCHHUB_NATIVE_MCP_LAUNCHER="1")
    return env


def _prepare_opencode_dependencies(opencode, *, env, cwd, version_timeout=15, install_timeout=90):
    version = _run([opencode, "--version"], env=env, cwd=cwd, timeout=version_timeout).strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise QualificationRefused("OpenCode did not report an exact dependency version")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm", path=env.get("PATH"))
    if not npm:
        raise QualificationRefused("npm unavailable for isolated OpenCode dependency preparation")
    config = Path(env["OPENCODE_CONFIG_DIR"])
    config.mkdir(parents=True, exist_ok=True)
    (config / "package.json").write_text(json.dumps({"dependencies":{"@opencode-ai/plugin":version}}), encoding="utf-8")
    # OpenCode awaits its unbounded background installer before loading plugins.
    _run([npm, "install", "--ignore-scripts", "--no-audit", "--no-fund",
          "--fetch-retries=0", "--fetch-timeout=30000"], env=env, cwd=config, timeout=install_timeout)


def _claude_auth(env, original_home):
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
        return
    path = Path(original_home, ".claude/.credentials.json")
    if path.is_file():
        token = json.loads(path.read_text(encoding="utf-8")).get("claudeAiOauth", {}).get("accessToken")
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
            return
    if os.environ.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
        return
    raise QualificationRefused("Claude account authentication unavailable to isolated child")


_GOOSE_MODEL = "dots-studio/dots-3-note-preview:free"


def _goose_turn(executable, prompt, *, env, cwd):
    from nodelang.goose_adapter import AcpTransport, workshop_mcp_server
    from nodelang.session_link_transport import _OwnedProcessJob
    process = subprocess.Popen([executable, "acp"], env=env, cwd=cwd, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    job = _OwnedProcessJob(process)
    transport = AcpTransport(process)
    updates = []
    deadline = time.monotonic() + 180
    try:
        transport.request("initialize", {"protocolVersion":1,
            "clientInfo":{"name":"ArchHub release qualification","version":"1"},
            "clientCapabilities":{"fs":{"readTextFile":False,"writeTextFile":False},"terminal":False}}, deadline=deadline)
        recipe = {"version":"1.0.0","title":"Workshop release qualification",
            "description":"Disposable agent message proof", "instructions":"Use only the Workshop MCP tools.",
            "settings":{"goose_provider":"openrouter","goose_model":_GOOSE_MODEL}}
        encoded = base64.urlsafe_b64encode(json.dumps(recipe).encode()).decode().rstrip("=")
        created = transport.request("session/new", {"cwd":str(cwd),
            "mcpServers":[workshop_mcp_server()], "_meta":{"recipeDeeplink":encoded}}, deadline=deadline)
        session = created.get("sessionId")
        if not session:
            raise QualificationRefused("Actual Goose did not create a native ACP session")
        result = transport.request("session/prompt", {"sessionId":session,
            "prompt":[{"type":"text","text":prompt}]}, deadline=deadline,
            update=lambda value:updates.append({"type":"goose_acp","params":value}))
        if result.get("stopReason") != "end_turn":
            raise QualificationRefused("Actual Goose did not complete its native turn")
        return "\n".join(json.dumps(row) for row in updates), session, process.pid
    finally:
        transport.close()
        job.close()


@contextmanager
def _environment(env):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)



def qualify(profile, *, opencode=None, claude=None, native_gate=None,
            model="opencode/mimo-v2.6-flash-free", peer="goose", goose=None, inject_failure=None,
            stop_wait=10, connect_wait=1, startup_wait=30, poll_interval=0.1, initial_turn_timeout=300):
    root = Path(__file__).resolve().parents[2]
    if root.name == "03.TOOLS":
        root = root.parent
    source = root / "01.APP" if (root / "01.APP").is_dir() else root
    profile = Path(profile).resolve()
    if profile.exists():
        raise QualificationRefused("Qualification profile must be fresh; no stale receipt reuse")
    if not model.startswith("opencode/") or not model.endswith("-free"):
        raise QualificationRefused("Qualification requires an explicitly free OpenCode model")
    original_home = os.environ.get("USERPROFILE", str(Path.home()))
    original_appdata = os.environ.get("APPDATA", "")
    oc = _executable(opencode, Path(original_appdata, "npm/node_modules/opencode-ai/bin/opencode.exe"))
    cc = (_executable(claude, Path(original_home, ".local/bin/claude.exe")) if peer == "claude" else
          _executable(goose, Path(os.environ.get("LOCALAPPDATA", ""), "ArchHub/runtime/goose/goose.exe")))
    gate = Path(native_gate or Path(original_home,
        "00.ARCHUB/00.GOVERNANCE/03.AGENT-HOOKS/opencode_native_gate.py")).resolve()
    if not gate.is_file():
        raise QualificationRefused("Trusted native permission gate unavailable; qualification cannot omit it")
    env = isolated_environment(profile)
    env["PYTHONPATH"] = str(source)
    env["CLAUDE_CONFIG_DIR"] = str(profile / "claude")
    if peer == "claude":
        _claude_auth(env, original_home)
    else:
        from nodelang.model_router import discover_key
        env["OPENROUTER_API_KEY"], _ = discover_key("openrouter")
        env.update(GOOSE_PATH_ROOT=str(profile/"goose"), GOOSE_PROVIDER="openrouter",
            GOOSE_MODEL=_GOOSE_MODEL, GOOSE_MODE="approve",
            OPENROUTER_PARAMETERS=json.dumps({"max_tokens":4096}))
        env["GOOSE_TELEMETRY_ENABLED"]=str(False).lower()
    profile.mkdir(parents=True)
    fixture = profile / "workspace"
    fixture.mkdir()
    nonce = uuid4().hex
    mcp = {"type":"local", "enabled":True,
           "command":[sys.executable, "-m", "nodelang.native_agent_mcp"],
           "environment":{"PYTHONPATH":str(source), "PYTHONUTF8":"1"}}
    loader = profile / "governance.mjs"
    gate_receipts=profile/'native-receipts.jsonl'
    loader.write_text("import fs from 'node:fs';\nimport {createOpenCodeGovernance,createNativeGateRunner} from " +
        json.dumps((source / "nodelang/session_link/opencode-governance.mjs").as_uri()) + ";\n" +
        "const native=createNativeGateRunner("+json.dumps(sys.executable)+","+json.dumps([str(gate)])+");\n"+
        "const runner=async event=>{const result=await native(event);fs.appendFileSync("+json.dumps(str(gate_receipts))+
        ",JSON.stringify({call:event.tool_use_id,tool:event.tool_name,phase:event.hook_event_name,status:event.tool_response?.status,allow:result.allow})+'\\n');return result;};\n"+
        "runner.close=native.close;runner.idle=native.idle;runner.reconcile=native.reconcile;\n"+
        "export const ArchHub = createOpenCodeGovernance({gateRunner:runner"+
        ",trustedDirectories:" + json.dumps([str(profile / 'rules')]) + "});\n", encoding="utf-8")
    env["OPENCODE_CONFIG_DIR"] = str(profile / "opencode")
    # OpenCode fetches ripgrep 15.1.0 from GitHub into the fresh profile on the
    # first glob; build 26 lost that download and every glob refused. Reuse the
    # copy OpenCode already cached for this account instead of the network.
    cached_rg = Path(original_home, ".cache/opencode/bin/rg.exe")
    if cached_rg.is_file():
        (profile / "opencode/bin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached_rg, profile / "opencode/bin/rg.exe")
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"plugin":[loader.as_uri()],
        "mcp":{"archhub_agent_coordination":mcp}, "share":"disabled", "autoupdate":False})
    from nodelang.application_server import ApplicationServer
    from nodelang.persistence import application_database_path
    from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    app = server = server_job = None
    checks = {name:False for name in ("exchange", "overlap", "opencode")}
    evidence = {"schema":"archhub-agentlink-qualification/v1", "nonce":nonce,
        "source_sha256":source_digest(root), "profile":str(profile), "checks":checks,
        "opencode_executable_sha256":hashlib.sha256(Path(oc).read_bytes()).hexdigest(),
        "peer":peer, "peer_executable_sha256":hashlib.sha256(Path(cc).read_bytes()).hexdigest()}
    try:
        with _environment(env):
            local = profile / "ArchHub"
            # Disposable source fixture: the trusted native gate checks that
            # its Python owner is resident under this profile's ArchHub root.
            # Stage product source only, never installed/user configuration.
            shutil.copytree(source / "nodelang", local / "nodelang",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "compiled", "node_modules"))
            shutil.copytree(source / "app", local / "app",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            keys = WindowsDpapiSigningKeyProvider(local / "keys/authority-signing-v1.dpapi.json")
            keys.current("archhub.local.universal-runtime-pipe")
            app = ApplicationServer(enable_machine_transport=True, machine_key_provider=keys,
                machine_descriptor_path=local / "active-universal-runtime.json",
                universal_workspace_root=fixture, universal_state_path=application_database_path(profile),
                enable_universal_cloud_gateway=False, enable_brain_cloud_sync=False,
                enable_machine_projection_prewarm=False, live_watch=False).start()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            address = "http://127.0.0.1:" + str(port)
            _prepare_opencode_dependencies(oc, env=env, cwd=fixture)
            server = subprocess.Popen([oc, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                cwd=fixture, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            from nodelang.session_link_transport import _OwnedProcessJob
            server_job = _OwnedProcessJob(server)
            deadline = time.monotonic() + startup_wait
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=connect_wait):
                        break
                except OSError:
                    if server.poll() is not None:
                        raise QualificationRefused("Isolated OpenCode server exited")
                    time.sleep(poll_interval)
            else:
                raise QualificationRefused("Isolated OpenCode server did not start")
            first = fixture / "a.txt"
            second = fixture / "b.txt"
            outside = profile / 'rules' / 'agent.txt'
            outside.parent.mkdir()
            outside.write_text('AGENTLINK-OUTSIDE '+nonce,encoding='utf-8')
            request = ("Release qualification on disposable files. Use the archhub_agent_coordination MCP tools. "
                "Call declare(task='Release OpenCode write proof',paths=[" + json.dumps(str(first)) +
                "],status='working',request_id='AGENTLINK-RELEASE'). Then use actual tools in this order: "
                "write a.txt with exact bytes '" + nonce + "'; read a.txt; write b.txt with exact bytes '" + nonce +
                "'; FOURTH use the glob tool with pattern='*' and path="+json.dumps(str(fixture))+
                ". Do not use bash, powershell or any shell for listing. Next read the rule file outside cwd at "+json.dumps(str(outside))+
                ". Then deliberately call native.work_task_detach on the MCP server with no attached Work; it must return 'No Work task surface is attached'. "
                "After that failed MCP call, read a.txt and write recovered.txt with exact bytes '"+nonce+
                "'. Continue even if the MCP tool fails. Then send(to='"+peer.title()+"',text='AGENTLINK-REQUEST " + nonce +
                "'). Keep declaration working for the paired reader. Do not use a shell to fake MCP calls. Stop.")
            output = _run([oc, "run", "--attach", address, "--format", "json", "-m", model, request],
                          env=env, cwd=fixture, timeout=initial_turn_timeout)
            events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            _log_tools(output)
            session = next((row.get("sessionID") for row in events if row.get("sessionID")), None)
            if not session:
                raise QualificationRefused("OpenCode returned no actual session identity")
            page = app.shared_agent_mail("read", {"since":0, "include_archived":True})
            requests = [row for row in page["messages"] if row["content"].endswith("AGENTLINK-REQUEST " + nonce)]
            if len(requests) != 1:
                raise QualificationRefused("OpenCode did not publish its nonce through MCP")
            note = requests[0]
            components={'ordered_write_read_write_list':write_sequence(output),
                'first_exact_bytes':first.is_file() and first.read_bytes()==nonce.encode(),
                'second_exact_bytes':second.is_file() and second.read_bytes()==nonce.encode()}
            parts=[row.get('part',{}) for row in events if row.get('type')=='tool_use']
            def tool_path(part):
                value=part.get('state',{}).get('input',{}).get('filePath')
                if not isinstance(value,str) or not value:
                    return None
                path=Path(value)
                return (path if path.is_absolute() else fixture/path).resolve()
            outside_reads=[part for part in parts if part.get('tool')=='read' and
                tool_path(part)==outside.resolve() and
                'AGENTLINK-OUTSIDE '+nonce in str(part.get('state',{}).get('output',''))]
            failures=[i for i,part in enumerate(parts) if 'native_work_task_detach' in part.get('tool','') and
                part.get('state',{}).get('status')=='error' and
                'No Work task surface is attached' in str(part.get('state',{}).get('error','')) and
                'ArchHub OpenCode governance' not in str(part.get('state',{}).get('error',''))]
            receipts=[json.loads(line) for line in gate_receipts.read_text(encoding='utf-8').splitlines()]
            failure_ids={parts[i].get('callID') for i in failures}
            settled_failure=any(row.get('call') in failure_ids and row.get('phase')=='PostToolUse' and
                row.get('status')=='failed' and row.get('allow') is True and any(
                    pre.get('call')==row['call'] and pre.get('phase')=='PreToolUse' and pre.get('allow') is True
                    for pre in receipts) for row in receipts)
            recovery=fixture/'recovered.txt'
            recovery_after=bool(failures) and settled_failure and any(part.get('tool')=='read' and
                part.get('state',{}).get('status')=='completed' and
                tool_path(part)==first.resolve()
                for part in parts[failures[0]+1:]) and any(part.get('tool')=='write' and
                part.get('state',{}).get('status')=='completed' and 'recovered.txt' in str(part)
                for part in parts[failures[0]+1:]) and recovery.is_file() and recovery.read_bytes()==nonce.encode()
            components.update(outside_cwd_read=bool(outside_reads),actual_mcp_handler_error=bool(failures),
                paired_failed_native_receipt=settled_failure,read_write_after_failure=recovery_after)
            checks['opencode'] = all(components.values())
            evidence.update(outside_cwd_read=bool(outside_reads),failed_mcp_then_write=recovery_after,
                failed_mcp_native_receipt=settled_failure,opencode_components=components,
                native_gate_sha256=hashlib.sha256(gate.read_bytes()).hexdigest())
            if not checks["opencode"]:
                raise QualificationRefused("Real OpenCode missing proof: "+', '.join(key for key,value in components.items() if not value))
            tools = [row.get("part", {}).get("tool") for row in events if row.get("type") == "tool_use"]
            evidence.update(opencode_session=session, opencode_server_pid=server.pid,
                request_message=note["id"], opencode_tools=tools)
            cc_mcp = json.dumps({"mcpServers":{"archhub_agent_coordination":{
                "command":sys.executable, "args":["-m", "nodelang.native_agent_mcp"],
                "env":{"PYTHONPATH":str(source), "PYTHONUTF8":"1"}}}})
            prompt = ("Use only the Workshop MCP declare/read/send tools. Declare task='Release peer reply proof', "
                "paths=[" + json.dumps(str(first)) + "],status='working',request_id='AGENTLINK-RELEASE'. "
                "Read since=0. Find request message " + note["id"] + " with nonce " + nonce +
                ". Read the overlap notice that references both your declaration and OpenCode's. "
                "Send(to='OpenCode',reply_to='" + note["id"] + "',text='AGENTLINK-REPLY " + nonce +
                "'). Finish with the exact overlap message id. Do not mark your declaration done yet.")
            if peer == "claude":
                answer = _run([cc, "-p", prompt, "--output-format", "stream-json", "--verbose",
                    "--strict-mcp-config", "--mcp-config", cc_mcp, "--permission-mode", "acceptEdits",
                    "--allowedTools", "mcp__archhub_agent_coordination__declare,mcp__archhub_agent_coordination__read,mcp__archhub_agent_coordination__send"], env=env, cwd=fixture)
            else:
                answer, peer_session, peer_pid = _goose_turn(cc, prompt, env=env, cwd=fixture)
                evidence.update(peer_session=peer_session, peer_pid=peer_pid,
                    peer_provider="openrouter", peer_model=_GOOSE_MODEL)
            page = app.shared_agent_mail("read", {"since":0, "include_archived":True})
            replies = [row for row in page["messages"] if row["reply_to"] == note["id"]
                       and row["content"].endswith("AGENTLINK-REPLY " + nonce)]
            notices = [row for row in page["messages"] if row["author"] == "Workshop coordination"
                       and "Your work overlaps at" in row["content"]]
            reply = replies[0] if len(replies) == 1 else None
            notice = notices[0] if len(notices) == 1 else None
            if reply is None or notice is None:
                raise QualificationRefused("Real " + peer.title() + " turn did not return the paired reply and overlap")
            final_prompt = ("Use Workshop read(since=0). Read message " + reply["id"] +
                " with AGENTLINK-REPLY " + nonce + " and overlap " + notice["id"] +
                ". Send(to='"+peer.title()+"',reply_to='" + reply["id"] + "',text='AGENTLINK-ACK " + nonce +
                "'). Finish with that exact overlap message id. Do not write any files.")
            final = _run([oc, "run", "--attach", address, "--session", session,
                "--format", "json", "-m", model, final_prompt], env=env, cwd=fixture)
            settled = app.shared_agent_mail("read", {"since":reply["sequence"], "include_archived":True})
            acknowledgements = [row for row in settled["messages"] if row["reply_to"] == reply["id"]
                and row["content"].endswith("AGENTLINK-ACK " + nonce)]
            claude_read, opencode_read = read_messages(answer), read_messages(final)
            checks["exchange"] = (bool(acknowledgements) and note["author"] != reply["author"]
                and any(row.get("id") == note["id"] for row in claude_read)
                and any(row.get("id") == reply["id"] for row in opencode_read))
            checks["overlap"] = len(notice["refs"]) == 2 and all(any(
                row.get("id") == notice["id"] and row.get("refs") == notice["refs"]
                for row in rows) for rows in (claude_read, opencode_read))
            evidence.update(reply_message=reply["id"], overlap_message=notice["id"],
                acknowledgement=acknowledgements[0]["id"] if acknowledgements else None,
                declarations=[{key:row[key] for key in ("session", "app", "pid", "created_at", "process_lineage")}
                              for row in page["declarations"]],
                fixture_sha256=hashlib.sha256(first.read_bytes()).hexdigest())
            if source_digest(root) != evidence["source_sha256"]:
                raise QualificationRefused("Candidate source changed during qualification; rerun the final artifact")
            if inject_failure:
                checks[inject_failure] = False
            require_checks(checks)
            evidence["status"] = "isolated-pass"
            return evidence
    finally:
        if server_job is not None:
            server_job.close()
        if server is not None:
            if server.poll() is None:
                server.terminate()
            server.wait(timeout=stop_wait)
        if app is not None:
            app.close()
        # This exact newly-created directory belongs solely to this invocation.
        # Parent and root guards prevent a command-line profile from deleting data.
        if profile.is_dir() and profile.name.startswith("agentlink-qualification-"):
            _remove_qualification_profile(profile)


def _remove_qualification_profile(profile):
    """Remove this invocation's disposable profile, including Git read-only packs."""
    def clear_readonly(function, path, error):
        if not isinstance(error, PermissionError):
            raise error
        os.chmod(path, stat.S_IWRITE)
        function(path)
    shutil.rmtree(profile, onexc=clear_readonly)


def main(argv=None):
    parser = argparse.ArgumentParser()
    defaults=inspect.signature(qualify).parameters
    parser.add_argument("--profile-parent", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--opencode")
    parser.add_argument("--claude")
    parser.add_argument("--goose")
    parser.add_argument("--peer", choices=("goose", "claude"), default=defaults['peer'].default)
    parser.add_argument("--native-gate")
    parser.add_argument("--model", default=defaults['model'].default)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"status":"running"}) + "\n", encoding="utf-8")
    profile = Path(args.profile_parent).resolve() / ("agentlink-qualification-" + uuid4().hex)
    try:
        receipt = qualify(profile, opencode=args.opencode, claude=args.claude,
                          native_gate=args.native_gate, model=args.model, peer=args.peer, goose=args.goose)
    except (QualificationRefused, OSError, ValueError, KeyError) as exc:
        output.write_text(json.dumps({"status":"refused", "error":str(exc)}) + "\n", encoding="utf-8")
        print("AGENTLINK RELEASE REFUSED: " + str(exc))
        return 1
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("AGENTLINK RELEASE PASS: exchange, overlap, OpenCode write/read/write/list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
