"""Court: hot-added native tools reach Claude Code (live 717, 2026-10-01).

native.work_task_attach adds tools and sends notifications/tools/list_changed;
the launcher sends the same after every swap and revive. Claude Code registers
its list_changed handler only when the server's initialize result declares
capabilities.tools.listChanged = true (claude.exe 2.1.281:
``if(oo.capabilities?.tools?.listChanged)...onMcpToolListChanged``; MCP spec
server/tools). The real worker (FastMCP) declares false and the launcher relayed
that unchanged, so every notification was ignored and attached tools never
appeared. Real launcher over OS pipes; a worker answering initialize exactly as
FastMCP does. No application, no live service.
"""
import json
import os
import queue
import sys
import threading

from nodelang.native_mcp_launcher import Launcher

# A worker that answers initialize exactly as the real FastMCP worker does.
FASTMCP_LIKE_WORKER = r'''
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if message.get("method") == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {"experimental": {}, "prompts": {"listChanged": False},
                             "resources": {"subscribe": False, "listChanged": False},
                             "tools": {"listChanged": False}},
            "serverInfo": {"name": "ArchHub native", "version": "1"}}}) + "\n")
        sys.stdout.flush()
'''


def test_real_worker_declares_no_tool_list_changes():
    """Documents the worker: FastMCP's default initialize says listChanged false."""
    from mcp.server.fastmcp import FastMCP
    options = FastMCP('court')._mcp_server.create_initialization_options()
    assert options.capabilities.tools.listChanged is False


def test_client_is_told_the_tool_list_can_change(tmp_path):
    install = tmp_path / 'install'
    install.mkdir()
    (install / 'BUILD_ID').write_text('build-1', encoding='utf-8')
    script = tmp_path / 'worker.py'
    script.write_text(FASTMCP_LIKE_WORKER, encoding='utf-8')
    to_r, to_w = os.pipe()
    from_r, from_w = os.pipe()
    send, recv = os.fdopen(to_w, 'wb'), os.fdopen(from_r, 'rb')
    launcher = Launcher(install, client_in=os.fdopen(to_r, 'rb'), client_out=os.fdopen(from_w, 'wb'),
                        worker_argv=lambda extra: [sys.executable, str(script), *extra], check_seconds=60)
    threading.Thread(target=launcher.serve, daemon=True).start()
    inbox = queue.Queue()
    threading.Thread(target=lambda: [inbox.put(json.loads(raw)) for raw in iter(recv.readline, b'')],
                     daemon=True).start()
    try:
        send.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                               'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                          'clientInfo': {'name': 'claude-code', 'version': '2.1.281'}}}).encode() + b'\n')
        send.flush()
        answer = inbox.get(timeout=15)
        assert answer['id'] == 1
        capabilities = answer['result']['capabilities']
        assert capabilities['tools']['listChanged'] is True, (
            'initialize declares tools.listChanged=false; Claude Code ignores every '
            'notifications/tools/list_changed from this server')
        # Only the tools flag changes; the worker's other answers stay as they were.
        assert capabilities['prompts'] == {'listChanged': False}
        assert capabilities['resources'] == {'subscribe': False, 'listChanged': False}
    finally:
        send.close()
