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
import gzip
import inspect
import io
import json
import os
import re
from pathlib import Path
import shutil
import socket
import threading
import stat
import subprocess
import sys
import tarfile
import time
from uuid import uuid4


class QualificationRefused(RuntimeError):
    pass


class _FreeProviderFailure(QualificationRefused):
    pass


_FREE_FALLBACKS = ("openrouter/thinkingmachines/inkling:free",
                   "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free")


def _free_failure_reason(detail):
    detail = detail.lower()
    if "free usage limit reached" in detail:
        return "free quota exhausted"
    if re.search(r"\b429\b|rate.limit|too many requests", detail):
        return "rate limited"
    if "403" in detail and "only available on agentic harnesses" in detail:
        return "harness-only provider refusal"
    return None


def _check_turn_errors(output, *, timed_out=False):
    errors, attempted, unfinished = [], [], False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "tool_use":
            part = event.get("part", {})
            attempted.append(part.get("tool"))
            state = part.get("state", {})
            unfinished = unfinished or state.get("status") in {"pending", "running"}
            if state.get("status") == "error" and not (
                "native_work_task_detach" in part.get("tool", "") and
                "No Work task surface is attached" in str(state.get("error", "")) and
                "ArchHub OpenCode governance" not in str(state.get("error", ""))):
                raise QualificationRefused("OpenCode tool failed; provider fallback cannot hide a tool failure")
        if event.get("type") == "error":
            errors.append(event.get("error", {}))
    if timed_out and unfinished:
        raise QualificationRefused("OpenCode tool timed out without completed proof; no provider fallback")
    reasons = [_free_failure_reason(str(error)) for error in errors]
    if any(reason is None for reason in reasons):
        raise QualificationRefused("OpenCode returned an unclassified error; no provider fallback")
    if reasons:
        raise _FreeProviderFailure(reasons[0])
    return attempted


def _require_free_model(model):
    if not re.fullmatch(r"(?:opencode/[A-Za-z0-9_.-]+-free|openrouter/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:free)", model):
        raise QualificationRefused("Qualification requires an explicitly free OpenCode or OpenRouter model")
    if model not in _RELEASE_FREE_MODELS:
        raise QualificationRefused("Qualification model is not in the release free-model allow-list; add the id to _RELEASE_FREE_MODELS deliberately after review")


def _free_stream_models(streams, model):
    models = sorted({provider + "/" + identity for provider, identity in re.findall(
        r"message=stream providerID=(\S+) modelID=(\S+)", streams)})
    if model not in models:
        raise QualificationRefused("Selected free model has no isolated server stream evidence")
    for identity in models:
        _require_free_model(identity)
    return models


def source_digest(root):
    source = Path(root) / "01.APP" if Path(root, "01.APP").is_dir() else Path(root)
    paths = [Path(__file__).resolve(), Path(__file__).with_name("agentlink_dependencies.cjs").resolve(),
             *Path(source, "nodelang").rglob("*.py"),
             *Path(source, "nodelang/session_link").rglob("*.mjs")]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def require_checks(checks):
    for name in ("exchange", "overlap", "opencode", "connector"):
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
            # A tool result may carry several JSON blocks joined into one string (the read
            # page, then the pending injected messages); decode every block, not only the first.
            decoder, index = json.JSONDecoder(), 0
            while index < len(value):
                while index < len(value) and value[index].isspace():
                    index += 1
                if index >= len(value):
                    return
                try:
                    block, index = decoder.raw_decode(value, index)
                except ValueError:
                    return
                collect(block)
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


def _run(command, *, env, cwd, timeout=150, quota_log=None, quota_model=None):
    from nodelang.session_link_transport import _OwnedProcessJob
    process = None
    job = None
    offset = quota_log.stat().st_size if quota_log is not None and quota_log.is_file() else 0
    def provider_failure():
        if quota_log is None or not quota_log.is_file():
            return None
        with quota_log.open("rb") as stream:
            stream.seek(offset)
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        provider, identity = quota_model.split("/", 1)
        reasons = []
        for line in lines:
            if all(token in line for token in ('message="stream error"', "providerID=" + provider + " ",
                                               "modelID=" + identity + " ", "small=false ")):
                reasons.append(_free_failure_reason(line))
        if any(reason is None for reason in reasons):
            if process.returncode:
                raise QualificationRefused("Provider returned nonzero exit " + str(process.returncode))
            raise QualificationRefused("OpenCode returned an unclassified server error; no provider fallback")
        return reasons[0] if reasons else None
    def check_failure(output, *, timed_out=False):
        transient = None
        if quota_model is not None:
            try:
                _check_turn_errors(output, timed_out=timed_out)
            except _FreeProviderFailure as exc:
                transient = exc
        reason = provider_failure()
        if transient is not None:
            raise transient
        if reason:
            raise _FreeProviderFailure(reason)
    try:
        process = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        job = _OwnedProcessJob(process)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(1, remaining) if quota_log is not None else remaining)
                check_failure(stdout)
                break
            except subprocess.TimeoutExpired as exc:
                raw = exc.stdout or b""
                partial = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                check_failure(partial,
                              timed_out=time.monotonic() >= deadline)
                if time.monotonic() >= deadline:
                    raise
    except (subprocess.TimeoutExpired, _FreeProviderFailure) as exc:
        # Windows communicate(timeout) withholds partial stdout until its reader reaches EOF.
        if job is not None:
            job.close()
            job = None
        if process is not None and process.poll() is None:
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=min(1, timeout))
        except subprocess.TimeoutExpired as unsettled:
            raise QualificationRefused("Timed out child output could not be settled; no provider fallback") from unsettled
        _log_tools(stdout)
        check_failure(stdout, timed_out=isinstance(exc, subprocess.TimeoutExpired))
        if isinstance(exc, _FreeProviderFailure):
            raise
        if quota_model is not None:
            raise _FreeProviderFailure("provider timeout") from exc
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


def _stop_opencode_turn(command, deadline):
    if "--attach" not in command:
        return
    address = command[command.index("--attach") + 1]
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+", address):
        raise QualificationRefused("Free fallback requires the isolated loopback server")
    def request(path, method="GET"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QualificationRefused("Free model turn deadline exhausted during cancellation")
        try:
            # The existing owned child runner bounds the entire HTTP response, including slow bodies.
            program = ("import sys,urllib.request\n"
                "opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
                "with opener.open(urllib.request.Request(sys.argv[1],method=sys.argv[2]),timeout=5) as response: raw=response.read(65537)\n"
                "if len(raw)>65536: raise ValueError('Cancellation response exceeds budget')\n"
                "print(raw.decode('utf-8'))\n")
            value = json.loads(_run([sys.executable, "-I", "-c", program, address + path, method],
                                    env=None, cwd=None, timeout=min(5, remaining)))
            if method == "GET" and (not isinstance(value, dict) or any(
                    not isinstance(status, dict) or status.get("type") not in {"idle", "busy", "retry"}
                    for status in value.values())):
                raise QualificationRefused("Isolated OpenCode cancellation status is invalid")
            return value
        except (OSError, ValueError, QualificationRefused) as exc:
            raise QualificationRefused("Isolated OpenCode cancellation could not be verified") from exc
    # The attached server belongs only to this qualification; stop its old turns before retrying.
    for session, status in request("/session/status").items():
        if status.get("type") != "idle":
            if not re.fullmatch(r"ses_[A-Za-z0-9]+", session):
                raise QualificationRefused("Isolated OpenCode returned an invalid session identity")
            if request("/session/" + session + "/abort", "POST") is not True:
                raise QualificationRefused("Isolated OpenCode did not confirm turn cancellation")
    if any(status.get("type") != "idle" for status in request("/session/status").values()):
        raise QualificationRefused("Isolated OpenCode turn still running; no overlapping retry")


def _free_turn(models, attempt, *, env, timeout, cancel=lambda _: None, nonce=None):
    from nodelang.model_router import discover_key, ModelRouteRefused
    deadline = time.monotonic() + timeout
    models = list(dict.fromkeys(models))
    for identity in models:
        _require_free_model(identity)
    routes = []
    try:
        for index, selected in enumerate(models):
            if time.monotonic() >= deadline:
                raise QualificationRefused("Free model turn deadline exhausted")
            if selected.startswith("openrouter/"):
                if not env.get("OPENROUTER_API_KEY"):
                    try:
                        env["OPENROUTER_API_KEY"], _ = discover_key("openrouter")
                    except ModelRouteRefused as exc:
                        raise QualificationRefused("Free OpenRouter authentication unavailable to isolated child") from exc
                if not env["OPENROUTER_API_KEY"]:
                    raise QualificationRefused("Free OpenRouter authentication unavailable to isolated child")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise QualificationRefused("Free model turn deadline exhausted")
            if index == 0 and timeout >= 120 and remaining < 120:
                raise QualificationRefused("Free model deadline cannot preserve the first 120 seconds")
            budget = remaining / (len(models) - index)
            if index == 0 and timeout >= 120:
                budget = min(remaining, max(120, budget))
            route = {"model":selected, "timeout":budget, "reason":"started"}
            if nonce is not None:
                route["nonce"] = nonce if index == 0 else uuid4().hex
            routes.append(route)
            print("FREE ROUTE: " + selected, flush=True)
            try:
                output = attempt(selected, time.monotonic() + budget, route)
            except _FreeProviderFailure as exc:
                route["reason"] = str(exc)
                print("FREE ROUTE REFUSED: " + selected + ": " + route["reason"], flush=True)
                if index + 1 < len(models):
                    cancel(deadline)
                continue
            if time.monotonic() > deadline:
                raise QualificationRefused("Free model turn deadline exhausted")
            route["reason"] = "completed"
            return output, selected, routes
        raise QualificationRefused("All explicitly free model routes refused")
    except QualificationRefused as exc:
        if routes and routes[-1]["reason"] == "started":
            routes[-1]["reason"] = "qualification refused"
        exc.routes = routes
        raise


def _opencode_turn(command, *, model, env, cwd, timeout, quota_log, nonce=None, proof_factory=None,
                   declaration_page=None):
    def attempt(selected, deadline, route):
        verify = proof_factory() if proof_factory is not None else None
        invocation = list(command)
        invocation[invocation.index("-m") + 1] = selected
        if nonce is not None:
            invocation[-1] = invocation[-1].replace(nonce, route["nonce"])
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QualificationRefused("Free model turn deadline exhausted before process start")
        output = _run(invocation, env=env, cwd=cwd, timeout=remaining,
            quota_log=quota_log, quota_model=selected)
        attempted = _check_turn_errors(output)
        if not output.strip():
            raise _FreeProviderFailure("empty provider output")
        if verify is not None:
            if not any(tool.endswith(("_send", "__send")) for tool in attempted):
                raise _FreeProviderFailure("model did not attempt paired acknowledgement")
            verify(output)
        elif not write_sequence(output):
            filesystem = [tool for tool in attempted if tool in {"write", "read", "glob", "list"}]
            if (len(filesystem) >= 4 and filesystem[:3] == ["write", "read", "write"] and
                    filesystem[3] in {"glob", "list"}):
                raise QualificationRefused("Attempted ordered tools lack completed proof; no provider fallback")
            raise _FreeProviderFailure("model did not attempt ordered tool sequence")
        if declaration_page is not None:
            events = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
            sessions = {row['sessionID'] for row in events if row.get('sessionID')}
            if len(sessions) != 1:
                raise QualificationRefused("OpenCode returned no unique actual session identity")
            session = sessions.pop()
            page = declaration_page()
            declaration, _ = _request_proof(page, session, route['nonce'], output=output)
            route['declaration'] = declaration['root']
        return output
    return _free_turn((model, *_FREE_FALLBACKS), attempt, env=env, timeout=timeout,
        cancel=lambda deadline:_stop_opencode_turn(command, deadline), nonce=nonce)


def _request_proof(page, session, nonce, *, output=None):
    declarations = [row for row in page["declarations"]
                    if row.get("native_session_id") == session and row.get("app") == "opencode"]
    if output is not None:
        identities = set()
        for tool, result in tool_receipts(output):
            if tool != "archhub_agent_coordination_declare":
                continue
            try:
                receipt = json.loads(result)
                declared = receipt["declaration"]
                identity = (declared["root"], receipt["sender_key"])
                if declared["session"] != identity[1] or declared["app"] != "opencode":
                    raise ValueError("Declaration sender differs")
                identities.add(identity)
            except (ValueError, TypeError, KeyError) as exc:
                raise QualificationRefused("OpenCode has no unique authenticated declaration") from exc
        if len(identities) != 1:
            raise QualificationRefused("OpenCode has no unique authenticated declaration")
        root, sender = identities.pop()
        # OpenCode can omit native metadata and re-declare the same connector root.
        declarations = [row for row in page["declarations"] if row.get("root") == root
            and row.get("session") == sender and row.get("app") == "opencode"
            and row.get("native_session_id") in (None, session)]
    if len(declarations) != 1:
        raise QualificationRefused("OpenCode has no unique authenticated declaration")
    declaration = declarations[0]
    author = declaration["agent"] + " [" + declaration["session"] + "]"
    requests = [row for row in page["messages"] if row["author"] == author and
                row["content"].endswith("AGENTLINK-REQUEST " + nonce)]
    if len(requests) != 1:
        raise QualificationRefused("OpenCode did not publish its nonce through MCP")
    return declaration, requests[0]


def _overlap_proof(page, declaration, reply, peer):
    peers = [row for row in page["declarations"] if row.get("app") == peer and
             reply["author"] == row["agent"] + " [" + row["session"] + "]"]
    if len(peers) != 1:
        raise QualificationRefused("Reply has no unique authenticated peer declaration")
    refs = {declaration["root"], peers[0]["root"]}
    notices = [row for row in page["messages"] if row["author"] == "Workshop coordination" and
               "Your work overlaps at" in row["content"] and len(row["refs"]) == 2 and set(row["refs"]) == refs]
    if len(notices) != 1:
        raise QualificationRefused("Real " + peer.title() + " turn did not return the paired reply and overlap")
    return notices[0]


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


def _new_paired_message(messages, *, seen, author, reply_to, marker):
    paired = [row for row in messages if row["id"] not in seen and row["author"] == author and
              row["reply_to"] == reply_to and row["content"].endswith(marker)]
    if len(paired) != 1:
        raise QualificationRefused("Selected route lacks a unique fresh paired message")
    return paired[0]


def _require_paired_read(output, read_id, notice):
    rows = read_messages(output)
    if not (any(row.get("id") == read_id for row in rows) and any(
            row.get("id") == notice["id"] and row.get("refs") == notice["refs"] for row in rows)):
        raise QualificationRefused("Selected route lacks completed paired read proof; no provider fallback")


def _executable(candidate, fallback):
    path = Path(candidate) if candidate else Path(fallback)
    if not path.is_file():
        raise QualificationRefused("Required real provider executable unavailable: " + path.name)
    return str(path.resolve())


def isolated_environment(profile):
    from tools.real_app_check.real_app_check import isolated_env
    env = isolated_env({key:value for key,value in os.environ.items() if not key.startswith(
        ("CODEX_", "CLAUDE", "OPENCODE_", "SESSION_LINK_", "GEMINI_", "GOOSE_"))}, Path(profile))
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        env[name] = str(profile)
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               ARCHHUB_TEST_STATE_DIR=str(profile), ARCHHUB_NATIVE_MCP_LAUNCHER="1")
    return env


def qualify_connector(profile, *, source=None, stall_wait=10):
    """Real stdio connector/SDK; fixture broker and owner, never a live host/profile."""
    from tools.real_app_check.profile_guard import command
    import anyio
    import builtins
    from nodelang.clean_coordination_service import build_bound_service
    from nodelang.runtime_activity import RuntimeActivity, RuntimeClosing
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = Path(__file__).resolve().parents[2]
    if root.name == "03.TOOLS":
        root = root.parent
    source = Path(source) if source is not None else root / "01.APP" if (root / "01.APP").is_dir() else root
    profile = Path(profile).resolve()
    if profile.exists():
        raise QualificationRefused("Connector qualification profile must be fresh")
    profile.mkdir(parents=True)
    release, entered = threading.Event(), threading.Event()
    declarations = []

    class Workshop:
        mode = "hung"
        activity = RuntimeActivity()

        def begin_shutdown(self):
            self.activity.begin_shutdown()
            release.set()

        def dispatch(self, payload, **_kwargs):
            mode = self.mode
            entered.set()
            if mode == "hung":
                release.wait(timeout=stall_wait)
            if mode != "up":
                raise RuntimeClosing("Workshop fixture unavailable")
            if payload["path"].endswith("/declare"):
                declarations.append(payload["body"])
            return {"ok":True, "pending":[], "declarations":[], "sender_key":"fixture",
                "message_id":"fixture-message", "created":True, "existing":False}

    host = Workshop()
    workshop = build_bound_service(host, port=0)
    threading.Thread(target=workshop.serve_forever, daemon=True).start()
    env = isolated_environment(profile)
    env.update(ARCHHUB_COORDINATION_ENDPOINT="http://127.0.0.1:%d/coordination" % workshop.server_port,
        ARCHHUB_COORDINATION_VENDOR="claude", CLAUDE_CODE_SESSION_ID="connector-release-fixture")
    # Handlers, dispatch, lifespan and stdio stay real; only physical owners are fixtures.
    code = '''import sys,time
from contextlib import contextmanager
from types import SimpleNamespace
sys.path.insert(0,sys.argv.pop(1))
from nodelang import native_agent_mcp as native, native_host_tools as hosts
class Client:
    agent_session_root="app:agent-session:runtime:"+"a"*32
    _pinned_runtime_descriptor=SimpleNamespace(application_root="application",workshop_root="workshop",work_registry_root="registry")
    def current_claimed_work(self): return None
    def current_claimed_work_detail(self): return {"work":None}
    def current_work_assignment(self):
        return {"agent_session":self.agent_session_root,"work":None,"revision":1,"projection":"assignment"}
    def current_work_configuration(self): return {"work":None}
    def request(self,method,path,body,**kwargs):
        if method=="GET" and path=="/api/universal/hosts": return {"connectors":[],"ok":True}
        if method=="GET" and path=="/api/universal/work":
            return {"application":"application","agent_session":self.agent_session_root,"workshop":"workshop",
                "registry":"registry","revision":1,"brain_scope":"brain","total":0,"items":[]}
        if method=="POST" and path=="/api/universal/workshop":
            return native._mailbox_call("send",{"to":"fixture","text":body["text"]},native._default_context(),
                timeout_seconds=kwargs.get("response_timeout_seconds",180))
        raise RuntimeError("Fixture owner does not admit effects")
client=Client()
@contextmanager
def bound(self):
    yield client
native._WorkControl.bound_client=bound
def messages(self,method,body,**kwargs):
    if method!="read_messages": raise RuntimeError("Fixture owner admits only context reads")
    native._mailbox_call("read",{"since":0},native._default_context(),timeout_seconds=kwargs.get("timeout_seconds",35))
    return {"ok":True,"application":"application","space":"workshop","agent_session":client.agent_session_root,
        "storage":"conversation-content","revision":1,"has_older":False,"entries":[]}
native._WorkControl.call=messages
def sessions(service):
    started=time.monotonic()
    time.sleep(0.1)
    return {"ok":True,"fixture_service":service,"broker_seconds":time.monotonic()-started}
hosts._sessions=sessions
hosts._broker=lambda service,*a,**kw:sessions(service)
hosts._engine=lambda engine,**kw:sessions(engine)
native.main()
'''

    def arguments(schema):
        def value(spec):
            if "default" in spec:
                return spec["default"]
            if "enum" in spec:
                return spec["enum"][0]
            if "anyOf" in spec:
                return value(next(item for item in spec["anyOf"] if item.get("type") != "null"))
            return {"string":"fixture", "integer":0, "number":0,
                    "boolean":False, "array":[], "object":{}}.get(spec.get("type"), "fixture")
        return {name:value(schema["properties"][name]) for name in schema.get("required", [])}

    async def run_case(mode):
        host.mode = mode
        entered.clear()
        params = StdioServerParameters(command=sys.executable,
            args=command(
                [sys.executable, "-I", "-B", "-c", code, str(source)])[1:], env=env, cwd=str(profile))
        started = time.monotonic()
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                with anyio.fail_after(5):
                    await session.initialize()
                initialize_seconds = time.monotonic() - started
                if initialize_seconds > 5:
                    raise QualificationRefused("Connector initialize exceeded five seconds with Workshop " + mode)
                tools = (await session.list_tools()).tools
                receipts = []
                overrides = {"declare":{"task":"Connector court", "paths":[str(profile)], "status":"working", "request_id":"FIXREVIT"},
                    "send":{"to":"fixture", "text":"Connector court", "idempotency_key":"connector-court"}}
                container = {"container_id":"GM.nodes.cde-authority", "source_requirement":"court:connector",
                    "domain":"nodes", "tier":"T1", "suitability_status":"S0", "revision":"P01",
                    "owner":"founder", "checker":"court", "gate_kind":"pytest",
                    "gate_spec":{"path":"02.TESTS/tests/test_agentlink_release.py"}}
                grants = [{"path":"70.COMPANY/72.HANDOFFS/CONNECTOR", "scope":"descendants", "operations":["apply_patch"]}]
                overrides["native.work_propose"] = {"title":"Connector court", "description":"Fixture only", "priority":100,
                    "purpose":"general", "inputs":{}, "requirements":{}, "container":container, "write_grants":grants}
                overrides["native.work_plan_import"] = {"rows":[{"item":"CONNECTOR", "task_no":1, "title":"Connector court",
                    "done_when":"Fixture evidence", "depends_on":[], "owner":"fixture"}],
                    "container":container, "write_grants":grants}
                required_success = {"revit_ping", "revit_info", "acad_ping", "acad_info", "hosts_state", "hosts.status",
                    "max_ping", "max_info", "blender_ping", "rhino_ping", "office_read", "outlook_inbox",
                    "notion_search", "dropbox_list", "native.hook_stop", "native.hook_user_prompt_submit"}
                for tool in tools:
                    started = time.monotonic()
                    with anyio.fail_after(2):
                        answer = await session.call_tool(tool.name, overrides.get(tool.name, arguments(tool.inputSchema)))
                    elapsed = time.monotonic() - started
                    result = (answer.structuredContent or json.loads(answer.content[0].text)
                        if not answer.isError and answer.content else {})
                    work_seconds = result.get("broker_seconds", 0)
                    if elapsed > work_seconds + 1:
                        raise QualificationRefused("Connector tool " + tool.name + " waited on Workshop " + mode)
                    if tool.name in required_success and answer.isError:
                        raise QualificationRefused("Registered tool " + tool.name + " did not return its fixture owner answer")
                    if tool.name in {"declare", "send", "read"} and mode == "up" and answer.isError:
                        raise QualificationRefused("Workshop-up message tool " + tool.name + " failed")
                    if tool.name in {"native.work_propose", "native.work_plan_import", "native.work_proposals"} and mode == "up" and answer.isError:
                        raise QualificationRefused("Workshop-up proposal tool " + tool.name + " failed")
                    receipts.append({"tool":tool.name, "seconds":elapsed, "work_seconds":work_seconds,
                        "is_error":answer.isError})
                ping = next(row for row in receipts if row["tool"] == "revit_ping")
                with anyio.fail_after(5):
                    while not entered.is_set() or (mode == "up" and not declarations):
                        await anyio.sleep(delay=0.02)
                return {"workshop":mode, "initialize_seconds":initialize_seconds,
                    "host_seconds":ping["seconds"], "broker_seconds":ping["work_seconds"],
                    "tools":receipts, "registered_tools":sorted(tool.name for tool in tools)}

    try:
        cases = [anyio.run(run_case, mode) for mode in ("hung", "down", "up")]
        return {"status":"isolated-pass", "scope":"real MCP connector and SDK; fixture owner, broker and Workshop",
            "native_sha256":hashlib.sha256((source / "nodelang/native_agent_mcp.py").read_bytes()).hexdigest(),
            "cases":cases, "declarations_arrived":bool(declarations)}
    except Exception as exc:
        while isinstance(exc, builtins.BaseExceptionGroup):
            exc = exc.exceptions[0]
        raise QualificationRefused("Connector runtime court failed: " + (str(exc) or type(exc).__name__)) from exc
    finally:
        release.set()
        workshop.shutdown()
        workshop.server_close()
        shutil.rmtree(profile)


def _extract_opencode_dependencies(staging, config, version):
    plan = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    locked = {"": {"dependencies": {"@opencode-ai/plugin": version}}}
    remaining, entries = 128 * 1024 * 1024, 0
    for row in plan:
        manifest = row["manifest"]
        target = config / row["relative"]
        archive = staging / row["archive"]
        if not target.resolve().is_relative_to(config.resolve()) or archive.parent != staging:
            raise QualificationRefused("Cached dependency escaped its isolated profile")
        blob = archive.read_bytes()
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(blob).digest()).decode()
        if integrity != manifest["dist"]["integrity"]:
            raise QualificationRefused("Cached dependency integrity mismatch")
        with gzip.GzipFile(fileobj=io.BytesIO(blob)) as compressed:
            raw = compressed.read(remaining + 1)
        remaining -= len(raw)
        if remaining < 0:
            raise QualificationRefused("Cached dependency decompression exceeds qualification budget")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as package:
            for member in package:
                entries += 1
                relative = Path(member.name.removeprefix("package/"))
                if (entries > 20000 or not 0 <= member.size <= 16 * 1024 * 1024 or member.issparse() or
                    not member.name.startswith("package/") or "\\" in member.name or ":" in member.name or
                    relative.is_absolute() or ".." in relative.parts or not (member.isfile() or member.isdir())):
                    raise QualificationRefused("Unsafe cached dependency archive entry")
                destination = target / relative
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(member) as source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
        installed = json.loads((target / "package.json").read_text(encoding="utf-8"))
        if any(installed.get(key, {}) != manifest.get(key, {}) for key in (
            "name", "version", "dependencies", "optionalDependencies", "peerDependencies", "peerDependenciesMeta")):
            raise QualificationRefused("Cached dependency identity differs from its manifest")
        locked[Path(row["relative"]).as_posix()] = {
            "version": manifest["version"], "integrity": integrity, "dependencies": manifest.get("dependencies", {})}
    (config / "package-lock.json").write_text(json.dumps({
        "lockfileVersion": 3, "requires": True, "packages": locked}) + "\n", encoding="utf-8")


def _prepare_opencode_dependencies(opencode, *, env, cwd, cache=None, version_timeout=15, install_timeout=90):
    version = _run([opencode, "--version"], env=env, cwd=cwd, timeout=version_timeout).strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise QualificationRefused("OpenCode did not report an exact dependency version")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm", path=env.get("PATH"))
    if not npm:
        raise QualificationRefused("npm unavailable for isolated OpenCode dependency preparation")
    config = Path(env["OPENCODE_CONFIG_DIR"])
    config.mkdir(parents=True, exist_ok=True)
    (config / "package.json").write_text(json.dumps({"dependencies":{"@opencode-ai/plugin":version}}), encoding="utf-8")
    cache = cache or os.environ.get("npm_config_cache")
    node = shutil.which("node", path=env.get("PATH"))
    npm_root = Path(npm).resolve().parent / "node_modules/npm"
    if cache and node and (npm_root / "node_modules/cacache").is_dir():
        staging = config / "DEPENDENCIES"
        try:
            prepared = _run([node, "--max-old-space-size=256", str(Path(__file__).with_name("agentlink_dependencies.cjs")),
                str(npm_root), str(Path(cache) / "_cacache"), str(staging), version],
                env=env, cwd=cwd, timeout=install_timeout).strip()
            if prepared == "LOCAL_DEPENDENCIES_VERIFIED":
                _extract_opencode_dependencies(staging, config, version)
        except (tarfile.TarError, EOFError) as exc:
            raise QualificationRefused("Invalid cached dependency archive") from exc
        finally:
            if staging.is_dir():
                shutil.rmtree(staging)
        if prepared == "LOCAL_DEPENDENCIES_VERIFIED":
            print("OPENCODE DEPENDENCIES: exact-version local cache verified", flush=True)
            return
        if prepared != "LOCAL_DEPENDENCIES_ABSENT":
            raise QualificationRefused("Unrecognized local dependency preparation result")
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
_GOOSE_FALLBACKS = ("openrouter/thinkingmachines/inkling:free",)
_RELEASE_FREE_MODELS = frozenset((*_FREE_FALLBACKS, *_GOOSE_FALLBACKS,
    "openrouter/" + _GOOSE_MODEL, "opencode/mimo-v2.6-flash-free"))


def _goose_turn(executable, prompts, *, env, cwd, proof_factory, timeout=180):
    from nodelang.goose_adapter import AcpTransport, workshop_mcp_server, GooseRefused
    from nodelang.session_link_transport import _OwnedProcessJob
    def attempt(selected, deadline, route):
        verify = proof_factory()
        mcp = workshop_mcp_server()
        connector = next(row["value"] for row in mcp["env"] if row["name"] == "GOOSE_SESSION_ID")
        child_env = {**env, "GOOSE_MODEL":selected.removeprefix("openrouter/")}
        if time.monotonic() >= deadline:
            raise QualificationRefused("Free model turn deadline exhausted before process start")
        try:
            process = subprocess.Popen([executable, "acp"], env=child_env, cwd=cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise QualificationRefused("Goose process unavailable; no provider fallback") from exc
        job = _OwnedProcessJob(process)
        transport = AcpTransport(process)
        updates = []
        failed_tools, pending = set(), set()
        def update(value):
            updates.append({"type":"goose_acp", "params":value})
            item = value.get("update", {})
            call = item.get("toolCallId")
            if call:
                if item.get("status") in {"failed", "error"}:
                    failed_tools.add(call)
                if item.get("status") in {"pending", "in_progress"}:
                    pending.add(call)
                if item.get("status") in {"completed", "failed", "error"}:
                    pending.discard(call)
        def response_error(error):
            reason = _free_failure_reason(str(error))
            if reason and not failed_tools and not pending:
                raise _FreeProviderFailure(reason)
            raise QualificationRefused("Goose returned a tool or unclassified error; no provider fallback")
        try:
            transport.request("initialize", {"protocolVersion":1,
                "clientInfo":{"name":"ArchHub release qualification","version":"1"},
                "clientCapabilities":{"fs":{"readTextFile":False,"writeTextFile":False},"terminal":False}},
                deadline=deadline, response_error=response_error)
            recipe = {"version":"1.0.0","title":"Workshop release qualification",
                "description":"Disposable agent message proof", "instructions":"Use only the Workshop MCP tools.",
                "settings":{"goose_provider":"openrouter","goose_model":child_env["GOOSE_MODEL"]}}
            encoded = base64.urlsafe_b64encode(json.dumps(recipe).encode()).decode().rstrip("=")
            created = transport.request("session/new", {"cwd":str(cwd),
                "mcpServers":[mcp], "_meta":{"recipeDeeplink":encoded}},
                deadline=deadline, response_error=response_error)
            session = created.get("sessionId")
            if not session:
                raise QualificationRefused("Actual Goose did not create a native ACP session")
            for prompt in prompts:
                result = transport.request("session/prompt", {"sessionId":session,
                    "prompt":[{"type":"text","text":prompt}]}, deadline=deadline,
                    update=update, response_error=response_error)
                if failed_tools or pending:
                    raise QualificationRefused("Goose tool lacks completed proof; no provider fallback")
                if result.get("stopReason") != "end_turn":
                    raise QualificationRefused("Actual Goose did not complete its native turn")
            output = "\n".join(json.dumps(row) for row in updates)
            if not any(tool.endswith("__send") for tool, _ in tool_receipts(output)):
                raise _FreeProviderFailure("model did not attempt paired reply")
            verify(output, connector)
            return output, session, process.pid
        except GooseRefused as exc:
            if time.monotonic() >= deadline and not failed_tools and not pending:
                raise _FreeProviderFailure("provider timeout") from exc
            raise QualificationRefused("Goose transport refused; no provider fallback") from exc
        finally:
            transport.close()
            job.close()
    result, selected, routes = _free_turn(("openrouter/" + _GOOSE_MODEL, *_GOOSE_FALLBACKS),
        attempt, env=env, timeout=timeout)
    return *result, selected, routes


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
            stop_wait=10, connect_wait=1, startup_wait=30, poll_interval=0.1, initial_turn_timeout=300,
            final_turn_timeout=150):
    from tools.real_app_check.profile_guard import command
    root = Path(__file__).resolve().parents[2]
    if root.name == "03.TOOLS":
        root = root.parent
    source = root / "01.APP" if (root / "01.APP").is_dir() else root
    profile = Path(profile).resolve()
    if profile.exists():
        raise QualificationRefused("Qualification profile must be fresh; no stale receipt reuse")
    _require_free_model(model)
    original_home = os.environ.get("USERPROFILE", str(Path.home()))
    original_appdata = os.environ.get("APPDATA", "")
    original_cache = os.environ.get("npm_config_cache") or str(
        Path(os.environ.get("LOCALAPPDATA", original_home), "npm-cache") if os.name == "nt"
        else Path(original_home, ".npm"))
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
    from nodelang.model_router import discover_key
    # The attached CLI uses the server's environment, including on quota fallback.
    env["OPENROUTER_API_KEY"], _ = discover_key("openrouter")
    if peer == "claude":
        _claude_auth(env, original_home)
    else:
        env.update(GOOSE_PATH_ROOT=str(profile/"goose"), GOOSE_PROVIDER="openrouter",
            GOOSE_MODEL=_GOOSE_MODEL, GOOSE_MODE="approve",
            OPENROUTER_PARAMETERS=json.dumps({"max_tokens":4096}))
        env["GOOSE_TELEMETRY_ENABLED"]=str(False).lower()
    profile.mkdir(parents=True, exist_ok=True)
    fixture = profile / "workspace"
    fixture.mkdir()
    nonce = uuid4().hex
    mcp = {"type":"local", "enabled":True,
           "command":command(
               [sys.executable, "-m", "nodelang.native_agent_mcp"]),
           "environment":{"PYTHONPATH":str(source), "PYTHONUTF8":"1"}}
    loader = profile / "governance.mjs"
    gate_receipts=profile/'native-receipts.jsonl'
    loader.write_text("import fs from 'node:fs';\nimport {createOpenCodeGovernance,createNativeGateRunner} from " +
        json.dumps((source / "nodelang/session_link/opencode-governance.mjs").as_uri()) + ";\n" +
        "const native=createNativeGateRunner("+json.dumps(sys.executable)+","+json.dumps(command([sys.executable, str(gate)])[1:])+");\n"+
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
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"plugin":[loader.as_uri()], "model":model, "small_model":model,
        "mcp":{"archhub_agent_coordination":mcp}, "share":"disabled", "autoupdate":False})
    from nodelang.application_server import ApplicationServer
    from nodelang.persistence import application_database_path
    from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    app = server = server_job = coordination = None
    checks = {name:False for name in ("exchange", "overlap", "opencode", "connector")}
    evidence = {"schema":"archhub-agentlink-qualification/v1", "nonce":nonce,
        "source_sha256":source_digest(root), "profile":str(profile), "checks":checks,
        "opencode_executable_sha256":hashlib.sha256(Path(oc).read_bytes()).hexdigest(),
        "peer":peer, "peer_executable_sha256":hashlib.sha256(Path(cc).read_bytes()).hexdigest()}
    try:
        with _environment(env):
            evidence["connector"] = qualify_connector(profile / "CONNECTOR", source=source)
            checks["connector"] = True
            local = Path(env["LOCALAPPDATA"]) / "ArchHub"
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
                enable_machine_projection_prewarm=False, live_watch=False)
            app.start()
            # WSRECEIPTS: agent processes write only through the running application, so the
            # isolated application serves its own coordination surface on an ephemeral port and
            # every agent in this profile is pointed at it (never the founder's 8474).
            from nodelang.clean_coordination_host import CleanCoordinationHost
            from nodelang.clean_coordination_service import build_bound_service
            coordination = build_bound_service(CleanCoordinationHost(app), port=0)
            threading.Thread(target=coordination.serve_forever, name="AGENTLINK coordination surface",
                             daemon=True).start()
            endpoint = "http://127.0.0.1:%d/coordination" % coordination.server_address[1]
            env["ARCHHUB_COORDINATION_ENDPOINT"] = os.environ["ARCHHUB_COORDINATION_ENDPOINT"] = endpoint
            mcp["environment"]["ARCHHUB_COORDINATION_ENDPOINT"] = endpoint
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"plugin":[loader.as_uri()], "model":model, "small_model":model,
                "mcp":{"archhub_agent_coordination":mcp}, "share":"disabled", "autoupdate":False})
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            address = "http://127.0.0.1:" + str(port)
            _prepare_opencode_dependencies(oc, env=env, cwd=fixture, cache=original_cache)
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
            rule_nonce = nonce
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
            requested_model = model
            output, model, routes = _opencode_turn([oc, "run", "--attach", address, "--format", "json", "-m", model, request],
                model=model, env=env, cwd=fixture, timeout=initial_turn_timeout,
                quota_log=profile / "opencode/log/opencode.log", nonce=nonce,
                declaration_page=lambda:app.shared_agent_mail("read", {"since":0, "include_archived":True}))
            nonce = routes[-1]["nonce"]
            evidence.update(opencode_requested_model=requested_model, opencode_model=model,
                opencode_routes=routes, nonce=nonce,
                opencode_route_reason=routes[-2]["reason"] if model != requested_model else "requested free model")
            events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            _log_tools(output)
            session = next((row.get("sessionID") for row in events if row.get("sessionID")), None)
            if not session:
                raise QualificationRefused("OpenCode returned no actual session identity")
            page = app.shared_agent_mail("read", {"since":0, "include_archived":True})
            page = {**page, "declarations":[row for row in page["declarations"]
                    if row["root"] == routes[-1]["declaration"]]}
            declaration, note = _request_proof(page, session, nonce, output=output)
            if (declaration.get("native_process") or {}).get("pid") != server.pid:
                raise QualificationRefused("OpenCode declaration does not belong to the isolated server")
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
                'AGENTLINK-OUTSIDE '+rule_nonce in str(part.get('state',{}).get('output',''))]
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
                "command":sys.executable, "args":command(
                    [sys.executable, "-m", "nodelang.native_agent_mcp"])[1:],
                "env":{"PYTHONPATH":str(source), "PYTHONUTF8":"1",
                       "ARCHHUB_COORDINATION_ENDPOINT":endpoint}}}})
            # Two ordered prompts: the free Goose model read the room before it declared
            # (builds 27 and 28), so its read never held the overlap notice its own
            # declaration creates. The declaration must settle before the read starts.
            declare_prompt = ("Use only the Workshop MCP declare tool. Declare task='Release peer reply proof', "
                "paths=[" + json.dumps(str(first)) + "],status='working',request_id='AGENTLINK-RELEASE'. Then stop.")
            prompt = ("Use only the Workshop MCP read/send tools. "
                "Read since=0. Find request message " + note["id"] + " with nonce " + nonce +
                ". Read the overlap notice whose refs are your declaration and " + declaration["root"] + ". "
                "Send(to='OpenCode',reply_to='" + note["id"] + "',text='AGENTLINK-REPLY " + nonce +
                "'). Finish with the exact overlap message id. Do not mark your declaration done yet.")
            selected_peer = {}
            if peer == "claude":
                answer = _run([cc, "-p", declare_prompt + " " + prompt, "--output-format", "stream-json", "--verbose",
                    "--strict-mcp-config", "--mcp-config", cc_mcp, "--permission-mode", "acceptEdits",
                    "--allowedTools", "mcp__archhub_agent_coordination__declare,mcp__archhub_agent_coordination__read,mcp__archhub_agent_coordination__send"], env=env, cwd=fixture)
            else:
                def peer_proof():
                    boundary = app.shared_agent_mail("read", {"since":0, "include_archived":True})
                    seen = {row["id"] for row in boundary["messages"]}
                    def verify_peer(answer, connector):
                        peer_page = app.shared_agent_mail("read", {"since":0, "include_archived":True})
                        peers = [row for row in peer_page["declarations"] if row.get("native_session_id") == connector
                                 and row.get("app") == peer]
                        if len(peers) != 1:
                            raise QualificationRefused("Real Goose turn did not return the paired reply and overlap")
                        paired = _new_paired_message(peer_page["messages"], seen=seen,
                            author=peers[0]["agent"] + " [" + peers[0]["session"] + "]", reply_to=note["id"],
                            marker="AGENTLINK-REPLY " + nonce)
                        overlap = _overlap_proof(peer_page, declaration, paired, peer)
                        _require_paired_read(answer, note["id"], overlap)
                        selected_peer["reply"] = paired["id"]
                    return verify_peer
                try:
                    answer, peer_session, peer_pid, peer_model, peer_routes = _goose_turn(
                        cc, [declare_prompt, prompt], env=env, cwd=fixture, proof_factory=peer_proof)
                except QualificationRefused as exc:
                    evidence["peer_routes"] = getattr(exc, "routes", [])
                    raise
                evidence.update(peer_session=peer_session, peer_pid=peer_pid,
                    peer_provider="openrouter", peer_model=peer_model.removeprefix("openrouter/"), peer_routes=peer_routes)
            page = app.shared_agent_mail("read", {"since":0, "include_archived":True})
            replies = [row for row in page["messages"] if row["reply_to"] == note["id"]
                       and row["content"].endswith("AGENTLINK-REPLY " + nonce)
                       and (peer == "claude" or row["id"] == selected_peer["reply"])]
            reply = replies[0] if len(replies) == 1 else None
            if reply is None:
                raise QualificationRefused("Real " + peer.title() + " turn did not return the paired reply and overlap")
            notice = _overlap_proof(page, declaration, reply, peer)
            final_prompt = ("Use Workshop read(since=0). Read message " + reply["id"] +
                " with AGENTLINK-REPLY " + nonce + " and overlap " + notice["id"] +
                ". Send(to='"+peer.title()+"',reply_to='" + reply["id"] + "',text='AGENTLINK-ACK " + nonce +
                "'). Finish with that exact overlap message id. Do not write any files.")
            selected_ack = {}
            def ack_proof():
                boundary = app.shared_agent_mail("read", {"since":reply["sequence"], "include_archived":True})
                seen = {row["id"] for row in boundary["messages"]}
                def verify_ack(output):
                    ack_page = app.shared_agent_mail("read", {"since":reply["sequence"], "include_archived":True})
                    paired = _new_paired_message(ack_page["messages"], seen=seen, author=note["author"],
                        reply_to=reply["id"], marker="AGENTLINK-ACK " + nonce)
                    _require_paired_read(output, reply["id"], notice)
                    selected_ack["id"] = paired["id"]
                return verify_ack
            try:
                final, ack_model, ack_routes = _opencode_turn([oc, "run", "--attach", address, "--session", session,
                    "--format", "json", "-m", model, final_prompt], model=model, env=env, cwd=fixture,
                    timeout=final_turn_timeout, quota_log=profile / "opencode/log/opencode.log", proof_factory=ack_proof)
            except QualificationRefused as exc:
                evidence["ack_routes"] = getattr(exc, "routes", [])
                raise
            evidence.update(ack_model=ack_model, ack_routes=ack_routes)
            settled = app.shared_agent_mail("read", {"since":reply["sequence"], "include_archived":True})
            acknowledgements = [row for row in settled["messages"] if row["reply_to"] == reply["id"]
                and row["id"] == selected_ack["id"]
                and row["author"] == note["author"]
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
            streams = (profile / "opencode/log/opencode.log").read_text(encoding="utf-8")
            evidence.update(opencode_stream_models=_free_stream_models(streams, model), opencode_small_model=requested_model)
            if source_digest(root) != evidence["source_sha256"]:
                raise QualificationRefused("Candidate source changed during qualification; rerun the final artifact")
            if inject_failure:
                checks[inject_failure] = False
            require_checks(checks)
            evidence["status"] = "isolated-pass"
            return evidence
    except QualificationRefused as exc:
        evidence.setdefault("opencode_routes", getattr(exc, "routes", []))
        exc.evidence = evidence
        raise
    finally:
        if server_job is not None:
            server_job.close()
        if server is not None:
            if server.poll() is None:
                server.terminate()
            server.wait(timeout=stop_wait)
        if coordination is not None:
            coordination.shutdown()
            coordination.server_close()
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
    parser.add_argument("--connector-only", action="store_true",
                        help="Run the mandatory stdio connector court without providers or application startup")
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    from tools.real_app_check.profile_guard import install
    install(output.parent / "PROFILE-WRITES.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"status":"running"}) + "\n", encoding="utf-8")
    profile = Path(args.profile_parent).resolve() / ("agentlink-qualification-" + uuid4().hex)
    try:
        receipt = (qualify_connector(profile) if args.connector_only else
            qualify(profile, opencode=args.opencode, claude=args.claude,
                    native_gate=args.native_gate, model=args.model, peer=args.peer, goose=args.goose))
    except (QualificationRefused, OSError, ValueError, KeyError) as exc:
        output.write_text(json.dumps({**getattr(exc, "evidence", {}), "status":"refused", "error":str(exc)}, indent=2) + "\n", encoding="utf-8")
        print("AGENTLINK RELEASE REFUSED: " + str(exc))
        return 1
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("AGENTLINK RELEASE PASS: " + ("connector" if args.connector_only else
          "connector, exchange, overlap, OpenCode write/read/write/list"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
