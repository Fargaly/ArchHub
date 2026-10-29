"""The agent-side launcher: a stdio MCP server that is only mcp-proxy's client mode pointed at the host.

Stdlib-only; the installer copies it to %LOCALAPPDATA%\\ArchHub-Runtime next to the runtime venv that
holds mcp-proxy, so an install never replaces it. The agent starts it as an ordinary stdio server with
its own environment, so the session identity (CLAUDE_CODE_SESSION_ID, CODEX_THREAD_ID, ...) is read
here, at spawn, and sent to the host as ``X-ArchHub-Session: VAR=value``. The host then starts the
connector with that variable, so the connector sees the same identity it would have had as the agent's
own child. If the host is down for an install, a call fails with a tool error; the agent's pipe to this
process stays open, and the next call reaches the new build.

    python mcp_launcher.py <url> <token> <session env var> [<session env var> ...]
"""
from __future__ import annotations

import os
import subprocess
import sys


def build_command(argv, environ, python):
    """The mcp-proxy client-mode command line (flags per its README; native Windows unverified)."""
    url, token, *names = argv
    headers = ["--headers", "Authorization", "Bearer " + token]
    for name in names:
        if environ.get(name):
            headers += ["--headers", "X-ArchHub-Session", "%s=%s" % (name, environ[name])]
            break
    return [python, "-m", "mcp_proxy", *headers, url]


def main(argv):
    return subprocess.call(build_command(argv, os.environ, sys.executable))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
