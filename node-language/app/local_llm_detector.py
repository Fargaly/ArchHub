"""Detect local LLM apps + CLI agents installed on this machine.

Founder demand 2026-05-15: ArchHub should auto-utilise whatever AI tools
the user already has — Claude Desktop, Codex CLI, LM Studio, Ollama,
Jan.ai, GPT4All, Cursor, LocalAI, Llamafile — without forcing the user
to copy keys around.

For each detector we return a dict:

    {
        "id": "claude_desktop",         # stable slug
        "name": "Claude Desktop",       # display label
        "kind": "app" | "cli" | "endpoint",
        "installed": bool,
        "running": bool,
        "endpoint": "http://...",       # if it exposes one
        "version": "...",               # best-effort
        "exec": str | None,             # path to binary if cli/app
        "note": str,                    # human-readable status
        "icon_color": "#hex",
    }

Probes are best-effort. None of them block more than a few hundred ms
because they're called from `get_local_llms` on the Qt main thread.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Callable

# ── small helpers ────────────────────────────────────────────────────

def _port_open(host: str, port: int, timeout: float = 0.18) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _exists(*paths: str) -> str | None:
    for p in paths:
        if not p:
            continue
        try:
            if Path(p).exists():
                return p
        except Exception:
            pass
    return None


def _run(cmd: list[str], timeout: float = 0.6) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False,
                              creationflags=(0x08000000 if sys.platform == "win32"
                                              else 0))
        return (out.stdout or out.stderr or "").strip().splitlines()[0] if (out.stdout or out.stderr) else ""
    except Exception:
        return ""


def _localappdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA")
                or Path.home() / "AppData" / "Local")


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA")
                or Path.home() / "AppData" / "Roaming")


def _programfiles() -> list[Path]:
    return [Path(os.environ.get("PROGRAMFILES") or r"C:\Program Files"),
            Path(os.environ.get("PROGRAMFILES(X86)")
                  or r"C:\Program Files (x86)")]


# ── probes ───────────────────────────────────────────────────────────

def probe_claude_desktop() -> dict:
    """Anthropic's Claude desktop app. macOS / Windows."""
    out: dict = {"id": "claude_desktop", "name": "Claude Desktop",
                  "kind": "app", "installed": False, "running": False,
                  "endpoint": "", "exec": None, "version": "",
                  "note": "not installed", "icon_color": "#cc785c"}
    candidates: list[str] = []
    if sys.platform == "win32":
        for pf in _programfiles():
            candidates += [str(pf / "Claude" / "Claude.exe")]
        candidates += [str(_localappdata() / "AnthropicClaude" / "Claude.exe"),
                        str(_localappdata() / "Programs" / "Claude" / "Claude.exe")]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Claude.app/Contents/MacOS/Claude"]
    else:
        candidates += ["/usr/bin/claude-desktop", "/snap/bin/claude-desktop"]
    p = _exists(*candidates)
    if p:
        out["installed"] = True
        out["exec"] = p
        out["note"] = "installed"
    return out


def probe_claude_cli() -> dict:
    """Anthropic's `claude` CLI (claude-code)."""
    out: dict = {"id": "claude_cli", "name": "Claude Code (CLI)",
                  "kind": "cli", "installed": False, "running": False,
                  "endpoint": "", "exec": None, "version": "",
                  "note": "not installed", "icon_color": "#cc785c"}
    p = _which("claude", "claude.cmd")
    if p:
        out["installed"] = True; out["exec"] = p
        v = _run([p, "--version"])
        out["version"] = v
        out["note"] = f"CLI {v}" if v else "CLI installed"
    return out


def probe_codex_cli() -> dict:
    """OpenAI Codex CLI (`codex` or `oai`) and the new `chatgpt` CLI."""
    out: dict = {"id": "codex_cli", "name": "Codex CLI",
                  "kind": "cli", "installed": False, "running": False,
                  "endpoint": "", "exec": None, "version": "",
                  "note": "not installed", "icon_color": "#10a37f"}
    p = _which("codex", "codex.cmd", "oai", "openai")
    if p:
        out["installed"] = True; out["exec"] = p
        v = _run([p, "--version"])
        out["version"] = v
        out["note"] = f"CLI {v}" if v else "CLI installed"
    return out


def probe_gemini_cli() -> dict:
    """Google's Gemini CLI (`gemini` or `gcloud-gemini`)."""
    out: dict = {"id": "gemini_cli", "name": "Gemini CLI",
                  "kind": "cli", "installed": False, "running": False,
                  "endpoint": "", "exec": None, "version": "",
                  "note": "not installed", "icon_color": "#4285f4"}
    p = _which("gemini", "gemini.cmd")
    if p:
        out["installed"] = True; out["exec"] = p
        v = _run([p, "--version"])
        out["version"] = v
        out["note"] = f"CLI {v}" if v else "CLI installed"
    return out


def probe_ollama() -> dict:
    """Ollama serves at 127.0.0.1:11434 by default."""
    out: dict = {"id": "ollama", "name": "Ollama",
                  "kind": "endpoint", "installed": False, "running": False,
                  "endpoint": "http://127.0.0.1:11434", "exec": None,
                  "version": "", "note": "not running",
                  "icon_color": "#1a8a4a"}
    p = _which("ollama", "ollama.exe")
    if p:
        out["installed"] = True; out["exec"] = p
        v = _run([p, "--version"])
        out["version"] = v
    if _port_open("127.0.0.1", 11434):
        out["running"] = True
        out["note"] = "live · 11434"
    elif p:
        out["note"] = "installed · not running"
    return out


def probe_lmstudio() -> dict:
    """LM Studio's OpenAI-compatible local server (default 1234)."""
    out: dict = {"id": "lmstudio", "name": "LM Studio",
                  "kind": "endpoint", "installed": False, "running": False,
                  "endpoint": "http://127.0.0.1:1234/v1", "exec": None,
                  "version": "", "note": "not running",
                  "icon_color": "#6a72ff"}
    candidates = []
    if sys.platform == "win32":
        candidates += [str(_localappdata() / "LM Studio" / "LM Studio.exe")]
        for pf in _programfiles():
            candidates += [str(pf / "LM Studio" / "LM Studio.exe")]
    elif sys.platform == "darwin":
        candidates += ["/Applications/LM Studio.app/Contents/MacOS/LM Studio"]
    p = _exists(*candidates)
    if p:
        out["installed"] = True; out["exec"] = p
        out["note"] = "installed · server off"
    if _port_open("127.0.0.1", 1234):
        out["running"] = True
        out["note"] = "live · 1234"
    return out


def probe_jan() -> dict:
    """Jan.ai — local OpenAI-compatible server, default :1337."""
    out: dict = {"id": "jan", "name": "Jan",
                  "kind": "endpoint", "installed": False, "running": False,
                  "endpoint": "http://127.0.0.1:1337/v1", "exec": None,
                  "version": "", "note": "not running",
                  "icon_color": "#7e3aed"}
    candidates = []
    if sys.platform == "win32":
        candidates += [str(_localappdata() / "Programs" / "jan" / "Jan.exe"),
                        str(_localappdata() / "jan" / "Jan.exe")]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Jan.app/Contents/MacOS/Jan"]
    p = _exists(*candidates)
    if p:
        out["installed"] = True; out["exec"] = p
        out["note"] = "installed · server off"
    if _port_open("127.0.0.1", 1337):
        out["running"] = True
        out["note"] = "live · 1337"
    return out


def probe_gpt4all() -> dict:
    """GPT4All — local server when 'API server' is enabled (4891)."""
    out: dict = {"id": "gpt4all", "name": "GPT4All",
                  "kind": "endpoint", "installed": False, "running": False,
                  "endpoint": "http://127.0.0.1:4891/v1", "exec": None,
                  "version": "", "note": "not installed",
                  "icon_color": "#5b8def"}
    candidates = []
    if sys.platform == "win32":
        for pf in _programfiles():
            candidates += [str(pf / "GPT4All" / "bin" / "chat.exe"),
                            str(pf / "GPT4All" / "chat.exe")]
        candidates += [str(_localappdata() / "Programs" / "GPT4All" / "bin" / "chat.exe")]
    elif sys.platform == "darwin":
        candidates += ["/Applications/GPT4All.app/Contents/MacOS/GPT4All"]
    p = _exists(*candidates)
    if p:
        out["installed"] = True; out["exec"] = p
        out["note"] = "installed · server off"
    if _port_open("127.0.0.1", 4891):
        out["running"] = True
        out["note"] = "live · 4891"
    return out


def probe_localai() -> dict:
    """LocalAI — drop-in OpenAI server, default :8080."""
    out: dict = {"id": "localai", "name": "LocalAI",
                  "kind": "endpoint", "installed": False, "running": False,
                  "endpoint": "http://127.0.0.1:8080/v1", "exec": None,
                  "version": "", "note": "not running",
                  "icon_color": "#f97316"}
    p = _which("local-ai", "localai")
    if p:
        out["installed"] = True; out["exec"] = p
    if _port_open("127.0.0.1", 8080):
        out["running"] = True
        out["note"] = "live · 8080"
    elif p:
        out["note"] = "installed · not running"
    return out


def probe_llamafile() -> dict:
    """A llamafile binary serving on default :8080. Heuristic — port-only."""
    out: dict = {"id": "llamafile", "name": "Llamafile",
                  "kind": "endpoint", "installed": False, "running": False,
                  "endpoint": "http://127.0.0.1:8080/v1", "exec": None,
                  "version": "", "note": "not running",
                  "icon_color": "#facc15"}
    p = _which("llamafile")
    if p:
        out["installed"] = True; out["exec"] = p
    # Don't auto-flip running on :8080 — that collides with LocalAI.
    # Only flag if we have the binary AND the port responds.
    if p and _port_open("127.0.0.1", 8080):
        out["running"] = True
        out["note"] = "live · 8080"
    elif p:
        out["note"] = "installed · not running"
    return out


def probe_cursor() -> dict:
    """Cursor — IDE with bundled AI. We can't borrow its key, but we can
    surface its presence so the user knows ArchHub recognises it.
    """
    out: dict = {"id": "cursor", "name": "Cursor",
                  "kind": "app", "installed": False, "running": False,
                  "endpoint": "", "exec": None, "version": "",
                  "note": "not installed", "icon_color": "#0a0a0a"}
    candidates = []
    if sys.platform == "win32":
        candidates += [str(_localappdata() / "Programs" / "cursor" / "Cursor.exe"),
                        str(_localappdata() / "cursor" / "Cursor.exe")]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Cursor.app/Contents/MacOS/Cursor"]
    p = _exists(*candidates)
    if p:
        out["installed"] = True; out["exec"] = p
        out["note"] = "installed"
    return out


def probe_open_webui() -> dict:
    """Open WebUI (was Ollama WebUI) often on :8080 or :3000."""
    out: dict = {"id": "open_webui", "name": "Open WebUI",
                  "kind": "endpoint", "installed": False, "running": False,
                  "endpoint": "http://127.0.0.1:3000", "exec": None,
                  "version": "", "note": "not running",
                  "icon_color": "#22c55e"}
    if _port_open("127.0.0.1", 3000):
        out["running"] = True
        out["installed"] = True
        out["note"] = "live · 3000"
    return out


# ── orchestration ────────────────────────────────────────────────────

PROBERS: dict[str, Callable[[], dict]] = {
    "claude_desktop": probe_claude_desktop,
    "claude_cli":     probe_claude_cli,
    "codex_cli":      probe_codex_cli,
    "gemini_cli":     probe_gemini_cli,
    "ollama":         probe_ollama,
    "lmstudio":       probe_lmstudio,
    "jan":            probe_jan,
    "gpt4all":        probe_gpt4all,
    "localai":        probe_localai,
    "llamafile":      probe_llamafile,
    "cursor":         probe_cursor,
    "open_webui":     probe_open_webui,
}


def detect_all_local_llms() -> list[dict]:
    """Probe every known local-LLM stack. Returns list of result dicts.

    Each dict has the schema documented at the top of this module.
    Wrapped in try/except so a single broken probe doesn't kill the
    whole detection run.
    """
    out: list[dict] = []
    for slug, fn in PROBERS.items():
        try:
            row = fn()
        except Exception as ex:
            row = {"id": slug, "name": slug, "kind": "?",
                    "installed": False, "running": False, "endpoint": "",
                    "exec": None, "version": "",
                    "note": f"probe failed: {ex}", "icon_color": "#888"}
        out.append(row)
    return out
