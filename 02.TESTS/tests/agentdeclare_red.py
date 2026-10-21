"""Execute the recorded main's real MCP server and demonstrate missing declare."""
import subprocess
namespace = {"__name__":"nodelang.agentdeclare_recorded_main", "__package__":"nodelang"}
source = subprocess.check_output(["git","show","61a7ed3712d33560ea971bc01fdb57e70e5ab5ca:01.APP/nodelang/native_agent_mcp.py"])
exec(compile(source, "recorded-main/native_agent_mcp.py", "exec"), namespace)
server = namespace["build_server"]()
assert "declare" in {tool.name for tool in server._tool_manager.list_tools()}, "recorded main exposes no declaration tool"
