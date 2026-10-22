"""One definition per CLI; one registry entry adds a runtime (OpenDesign shape)."""
from functools import lru_cache
import logging
from pathlib import Path
from nodelang.agent_runtime_defs.claude import DEFINITION as CLAUDE
from nodelang.agent_runtime_defs.codex import DEFINITION as CODEX
from nodelang.agent_runtime_defs.gemini import DEFINITION as GEMINI
from nodelang.agent_runtime_defs.opencode import DEFINITION as OPENCODE

RUNTIMES = {definition["id"]: definition for definition in (CLAUDE, CODEX, GEMINI, OPENCODE)}


@lru_cache(maxsize=256)
def observed_runtime_process(peer):
    """Nearest actual runtime ancestor and its generation, never a display claim."""
    try:
        import psutil
    except ImportError as exc:
        logging.getLogger(__name__).debug("Optional runtime label observer unavailable: %s", exc)
        return None
    try:
        process = psutil.Process(peer.pid)
        if abs(process.create_time() - peer.created_at) <= 0.00001:
            for _ in range(8):
                names = {Path(process.name()).stem.casefold()}
                if "node" in names:
                    for arg in process.cmdline()[:2]:
                        names.add(Path(arg).stem.casefold())
                        names.update(part.casefold() for part in Path(arg).parts)
                runtime = next((key for key, definition in RUNTIMES.items()
                    if names.intersection(definition["executables"])), None)
                if runtime is None:
                    runtime = next((key for key in ("goose", "antigravity") if key in names), None)
                parent = process.parent()
                if runtime:
                    return {"runtime": runtime, "pid": process.pid, "created_at": process.create_time()}
                if parent is None:
                    return None
                process = parent
    except (psutil.Error, OSError, ValueError) as exc:
        logging.getLogger(__name__).debug("Runtime label observation unavailable for peer %s: %s", peer.pid, exc)
    return None


def _observed_runtime(peer):
    observed = observed_runtime_process(peer)
    return observed["runtime"] if observed else None


def mailbox_label(peer, context):
    """Display only: registry host plus observed project/session, never authority."""
    from hashlib import sha256
    from .agent_declarations import SESSION_KEYS
    runtime = SESSION_KEYS.get(
        next(iter(context), "")) or _observed_runtime(peer)
    connector = str(context.get("archhub/sessionID") or "").split(":", 2)
    if len(connector) == 3 and connector[0] == "mcp":
        runtime = connector[1]
    host = RUNTIMES.get(runtime, {}).get("label", {"goose":"Goose", "antigravity":"Antigravity",
        "antigravity-ide":"Antigravity", "cursor":"Cursor", "copilot":"VS Code Copilot",
        "vscode-copilot":"VS Code Copilot", "grok":"Grok Bot", "grok-bot":"Grok Bot"}.get(runtime, "Agent"))
    project = (Path(peer.cwd).name if peer.cwd else "Session")
    project = project.replace("\n", " ").replace("\r", " ").replace("[", "(").replace("]", ")")
    project = project.encode("utf-8")[:48].decode("utf-8", errors="ignore")
    # No protocol supplies a conversation title. This is a generated session
    # label; absent host metadata, project addressing can be ambiguous.
    title = ("session-" + sha256(next(iter(context.values())).encode("utf-8")).hexdigest()[:12]
        if context else "project")
    return "%s / %s / %s" % (host, project, title), runtime or "mcp"
