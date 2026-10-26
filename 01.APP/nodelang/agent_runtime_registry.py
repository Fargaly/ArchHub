"""One definition per CLI; one registry entry adds a runtime (OpenDesign shape)."""
import logging
import os
from pathlib import Path
import time
from nodelang.agent_runtime_defs.claude import DEFINITION as CLAUDE
from nodelang.agent_runtime_defs.codex import DEFINITION as CODEX
from nodelang.agent_runtime_defs.gemini import DEFINITION as GEMINI
from nodelang.agent_runtime_defs.opencode import DEFINITION as OPENCODE

RUNTIMES = {definition["id"]: definition for definition in (CLAUDE, CODEX, GEMINI, OPENCODE)}
_runtime_process_cache = {}
# Desktop hosts and services supply presence through declarations, not helpers.
_PROCESS_ROLES = {
    'claude': (('/windowsapps/', '/anthropicclaude/', '/claude/app/', '/claude.app/'), ()),
    'codex': (('/codex.app/', '/chatgpt.app/'), ('app-server', 'exec-server', 'mcp-server')),
    'gemini': ((), ('--acp', '--experimental-acp')),
    'opencode': (('/@opencode-aidesktop/', '/opencode.app/', '/opencode-desktop/',
                  '/opencode desktop/', '/programs/opencode/'), ('serve', 'web', 'acp')),
    'goose': (('/goose.app/', '/programs/goose/'), ('mcp', 'acp')),
    'antigravity': (('/antigravity/', '/antigravity.app/', '/antigravity ide/'), ()),
}
_COMMAND_VALUE_OPTIONS = {'-c', '--config', '-p', '--profile', '-C', '--cd',
                          '-m', '--model', '--enable', '--disable', '--local-provider',
                          '-s', '--sandbox', '-a', '--ask-for-approval', '--add-dir', '-i', '--image'}


def _process_runtime(process):
    names = {Path(process.name()).stem.casefold()}
    argv = process.cmdline()
    executable = (argv[0] if argv else '').replace('\\', '/').casefold()
    arguments = argv[1:]
    if 'node' in names:
        for arg in argv[1:2]:
            parts = [part.casefold() for part in Path(arg).parts]
            if 'node_modules' in parts:
                package = parts[parts.index('node_modules') + 1:]
                for prefix, runtime in ((['@anthropic-ai','claude-code'],'claude'),
                                        (['@google','gemini-cli'],'gemini'), (['@openai','codex'],'codex'),
                                        (['opencode-ai'],'opencode')):
                    if package[:len(prefix)] == prefix:
                        names.add(runtime)
                        arguments = argv[2:]
    runtime = next((key for key, definition in RUNTIMES.items()
                 if names.intersection(definition['executables'])),
                next((key for key in ('goose','antigravity') if key in names), None))
    desktop_paths, services = _PROCESS_ROLES.get(runtime, ((), ()))
    if any(part in executable for part in desktop_paths):
        return None
    skip_value = False
    for argument in arguments:
        if skip_value:
            skip_value = False
            continue
        if argument == '--':
            break
        if argument in services or argument == '--type' or argument.startswith('--type='):
            return None
        if not argument.startswith('-'):
            break  # Later positional words belong to the session/task.
        skip_value = argument in _COMMAND_VALUE_OPTIONS
    return runtime


def observed_runtime_process(peer, *, strict=False):
    """Actual runtime ancestor and its generation, never a cached display claim."""
    try:
        import psutil
    except ImportError as exc:
        if strict:
            raise
        logging.getLogger(__name__).debug('Optional runtime label observer unavailable: %s', exc)
        return None
    try:
        process = psutil.Process(peer.pid)
        if abs(process.create_time() - peer.created_at) > 0.00001:
            return None
        for _ in range(8):
            runtime = _process_runtime(process)
            if runtime:
                # npm's native CLI child and its Node launcher are one runtime.
                try:
                    parent = process.parent()
                    if parent is not None and Path(parent.name()).stem.casefold() == 'node' and _process_runtime(parent) == runtime:
                        process = parent
                except (psutil.Error, OSError) as exc:
                    logging.getLogger(__name__).debug('Optional runtime launcher metadata unavailable: %s', exc)
                return {'runtime':runtime, 'pid':process.pid, 'created_at':process.create_time()}
            process = process.parent()
            if process is None:
                return None
    except (psutil.Error, OSError, ValueError) as exc:
        if strict and not isinstance(exc, psutil.NoSuchProcess):
            raise
        logging.getLogger(__name__).debug('Runtime label observation unavailable for peer %s: %s', peer.pid, exc)
    return None


def _runtime_process_table():
    import psutil
    if os.name == 'nt':
        from .host_brokers import _windows_process_table
        return _windows_process_table()
    return {process.pid:process.info for process in psutil.process_iter(['name','ppid'])}


def discover_runtime_processes():
    """One snapshot; fresh generations guard cached metadata, never PID alone."""
    import psutil
    global _runtime_process_cache
    deadline = time.monotonic() + .3
    table = _runtime_process_table()
    processes = {}
    cache = {}
    candidates = {}
    complete = True
    username = psutil.Process().username()
    executable_names = {name for definition in RUNTIMES.values() for name in definition['executables']} | {'node','goose','antigravity'}
    for index, (pid, info) in enumerate(table.items()):
        if index >= 8192 or time.monotonic() >= deadline:
            complete = False
            break
        if Path(info.get('name') or '').stem.casefold() not in executable_names:
            continue
        try:
            process = psutil.Process(pid)
            created = process.create_time()
            key = (pid, created, info['name'], info['ppid'])
            if key in _runtime_process_cache:
                runtime = _runtime_process_cache[key]
            else:
                runtime = _process_runtime(process) if process.username() == username else None
                if psutil.Process(pid).create_time() != created:
                    complete = False
                    continue
            cache[key] = runtime
            if runtime:
                candidates[pid] = {'runtime':runtime, 'pid':pid, 'created_at':created}
        except psutil.NoSuchProcess:
            continue  # Normal process exit during an observation.
        except (psutil.Error, OSError, ValueError):
            complete = False
    # Resolve parents only from this snapshot and the memoized classifications.
    for pid, observed in candidates.items():
        parent = candidates.get(table[pid]['ppid'])
        if (parent and parent['runtime'] == observed['runtime']
                and Path(table[parent['pid']]['name']).stem.casefold() == 'node'
                and parent['created_at'] <= observed['created_at']):
            observed = parent
        processes[(observed['runtime'], observed['pid'], observed['created_at'])] = observed
    _runtime_process_cache = cache
    return {'processes':list(processes.values()), 'complete':complete, 'observed_at':time.time()}


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
