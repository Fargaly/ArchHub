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
def _observed_runtime(peer):
    """Bounded display derivation for one immutable OS peer, not a session map."""
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
                parent = process.parent()
                if runtime or parent is None:
                    return runtime
                process = parent
    except (psutil.Error, OSError, ValueError) as exc:
        logging.getLogger(__name__).debug("Runtime label observation unavailable for peer %s: %s", peer.pid, exc)
    return None


def mailbox_label(peer, context):
    """Display only: registry host plus observed project/session, never authority."""
    from hashlib import sha256
    runtime = {"threadId": "codex", "ai.opencode/sessionID": "opencode"}.get(
        next(iter(context), "")) or _observed_runtime(peer)
    host = RUNTIMES[runtime]["label"] if runtime else "Agent"
    project = (Path(peer.cwd).name if peer.cwd else "Session")
    project = project.replace("\n", " ").replace("\r", " ").replace("[", "(").replace("]", ")")
    project = project.encode("utf-8")[:48].decode("utf-8", errors="ignore")
    # No protocol supplies a conversation title. This is a generated session
    # label; absent host metadata, project addressing can be ambiguous.
    title = ("session-" + sha256(next(iter(context.values())).encode("utf-8")).hexdigest()[:12]
        if context else "project")
    return "%s / %s / %s" % (host, project, title), runtime or "mcp"
