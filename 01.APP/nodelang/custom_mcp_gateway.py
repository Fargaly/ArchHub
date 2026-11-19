"""The person's own MCP servers as two agent tools (mcp_tools, mcp_call), from the one owner custom_mcp.

register_tools() is the one definition: the ArchHub agent server adds it (native_host_tools), and run as
a module it is a stdio MCP server of its own for agents whose MCP client carries no ArchHub session
(OpenCode adds it through ctx.mcp.transform). It needs no session identity and enrolls nothing; every
call still passes connector.call's decide().
"""
from __future__ import annotations


def register_tools(server):
    from .custom_mcp import agent_call, agent_tools

    @server.tool(name="mcp_tools")
    def mcp_tools(server_id: str = "") -> dict:
        """The person's own MCP servers (Settings > Connections) and, for one server_id, its live tools."""
        return agent_tools(server_id)

    @server.tool(name="mcp_call")
    def mcp_call(server_id: str, tool: str, arguments: dict | None = None) -> dict:
        """Call one tool of the person's own MCP server; sends and writes wait on the same decision as any connector."""
        return agent_call(server_id, tool, arguments)

    return server


def main():
    from mcp.server.fastmcp import FastMCP
    register_tools(FastMCP("archhub-tools")).run()


if __name__ == "__main__":
    main()
