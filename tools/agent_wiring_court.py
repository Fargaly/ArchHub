"""Every agent's wiring, proven under every shell.

Reads the hook commands of Claude Code, Gemini and Codex and the stdio/http
MCP servers of Claude and Codex, then:
  * runs each hook command under cmd.exe, PowerShell and Git Bash with `{}`
    on stdin (a hook must at least launch: no "not recognized", no "cannot
    find", within 60 s);
  * spawns each stdio MCP server and sends a JSON-RPC `initialize`,
    expecting a JSON response line within 25 s; GETs each http server.
Exit 0 only when every row passes. Run: python tools/agent_wiring_court.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
SHELLS = {
    "cmd": lambda c: ["cmd.exe", "/d", "/c", c],
    "powershell": lambda c: ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", c],
    "bash": lambda c: [r"C:\Program Files\Git\bin\bash.exe", "-lc", c],
}
BAD = re.compile(r"is not recognized|cannot find the path|No such file|command not found", re.I)


def _hooks_from_json(path: Path, vendor: str) -> list[tuple[str, str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups if isinstance(groups, list) else []:
            for hook in group.get("hooks", []):
                cmd = str(hook.get("command") or "").strip()
                if cmd and not cmd.startswith("pwsh"):
                    rows.append((vendor, event, cmd))
    return rows


def _mcp_servers() -> list[tuple[str, str, dict]]:
    rows = []
    claude = HOME / ".claude.json"
    if claude.exists():
        for name, spec in (json.loads(claude.read_text(encoding="utf-8")).get("mcpServers") or {}).items():
            rows.append(("claude", name, spec))
    opencode = HOME / ".config" / "opencode" / "opencode.jsonc"
    if opencode.exists():
        text = re.sub(r"^\s*//.*$", "", opencode.read_text(encoding="utf-8"), flags=re.M)
        for name, spec in (json.loads(text).get("mcp") or {}).items():
            if spec.get("enabled") is False:
                continue
            cmd = spec.get("command") or []
            rows.append(("opencode", name, {"url": spec.get("url"), "command": cmd[0] if cmd else None,
                                            "args": cmd[1:], "env": spec.get("environment") or {}}))
    codex = HOME / ".codex" / "config.toml"
    if codex.exists():
        for name, spec in (tomllib.loads(codex.read_text(encoding="utf-8")).get("mcp_servers") or {}).items():
            if spec.get("enabled") is False or (not spec.get("command") and not spec.get("url")):
                continue
            rows.append(("codex", name, spec))
    return rows


def run_hook(shell: str, cmd: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(SHELLS[shell](cmd), input="{}", capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timeout 60 s"
    except FileNotFoundError as exc:
        return False, f"shell missing: {exc}"
    text = (proc.stderr or "") + (proc.stdout or "")
    if BAD.search(text):
        return False, f"exit {proc.returncode}: {text[-160:]!r}"
    return True, f"exit {proc.returncode}"


def run_mcp(spec: dict) -> tuple[bool, str]:
    if spec.get("url"):
        try:
            with urllib.request.urlopen(urllib.request.Request(spec["url"], method="GET"), timeout=8) as resp:
                return True, f"http {resp.status}"
        except urllib.error.HTTPError as exc:
            return True, f"http {exc.code} (alive)"
        except Exception as exc:  # noqa: BLE001
            return False, f"unreachable: {exc}"
    command = str(spec.get("command"))
    resolved = command if Path(command).exists() else shutil.which(command)
    if not resolved:
        return False, f"launcher missing: {command}"
    argv = [resolved, *[str(a) for a in spec.get("args") or []]]
    for arg in argv[1:]:
        if arg.endswith(".py") and not Path(arg).exists():
            return False, f"script missing: {arg}"
    env = {**os.environ, **{k: str(v) for k, v in (spec.get("env") or {}).items()}}
    # The coordination server derives its identity from the vendor's own
    # session variable, which only the real client sets. The court stands in
    # for that client with one stable id per vendor.
    vendor = env.get("ARCHHUB_COORDINATION_VENDOR", "").lower()
    for name in {"codex": ("CODEX_THREAD_ID",), "claude": ("CLAUDE_CODE_SESSION_ID",),
                 "gemini": ("GEMINI_SESSION_ID",), "antigravity": ("ANTIGRAVITY_SESSION_ID",)}.get(vendor, ()):
        env.setdefault(name, "wiring-court-" + vendor)
    cwd = spec.get("cwd")
    if cwd and not Path(cwd).exists():
        return False, f"cwd missing: {cwd}"
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "wiring-court", "version": "0"}}})
    out = ""
    try:
        proc = subprocess.run(argv, input=init + "\n", capture_output=True, text=True, timeout=25, env=env, cwd=cwd)
        out = proc.stdout or ""
        err = (proc.stderr or "")[-200:]
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or b""
        out = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        err = "timeout"
    except (FileNotFoundError, OSError) as exc:
        return False, f"cannot launch: {exc}"
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{") and '"jsonrpc"' in line:
            return True, "initialize answered"
    return False, "no JSON-RPC answer: " + (err or out[-160:]).replace("\n", " ")


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    results = []
    hooks = (_hooks_from_json(HOME / ".claude" / "settings.json", "claude")
             + _hooks_from_json(HOME / ".gemini" / "settings.json", "gemini")
             + _hooks_from_json(HOME / ".codex" / "hooks.json", "codex"))
    for vendor, event, cmd in hooks:
        if only and vendor != only:
            continue
        for shell in SHELLS:
            ok, note = run_hook(shell, cmd)
            results.append(ok)
            print(f"{'PASS' if ok else 'FAIL'}  hook {vendor}/{event} under {shell}: {note}", flush=True)
    for vendor, name, spec in _mcp_servers():
        if only and vendor != only:
            continue
        ok, note = run_mcp(spec)
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  mcp {vendor}/{name}: {note}", flush=True)
    print(f"\n{sum(results)}/{len(results)} passed", flush=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
