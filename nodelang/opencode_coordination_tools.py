"""Native OpenCode messages to other agents, through the session's own bound owner.

OpenCode starts MCP servers once per app, not per session, so a coordination MCP
mounted there has no session identity, and the native owner refuses to guess one
("actual OpenCode hook session identity is required", native_agent_session.py).
The governance plugin already keeps one direct child per actual hook sessionID
holding a verified NativeAgentSession. This adapter serves the coordination
message tools from that owner with the same admit, execute-once and receipt cycle
as selected Work. It never constructs an owner, enrolls, or chooses an identity.
"""
from .clean_coordination_mcp import build_server as build_coordination_server
from .native_agent_mcp import _OwnedWorkshopClient
from .opencode_workshop_tools import OpenCodeWorkshopTools

MESSAGE_OPERATIONS = frozenset({
    'coordination.list_agents',
    'coordination.send_message',
    'coordination.read_messages',
    'coordination.read_message',
    'coordination.acknowledge_message',
})


class OpenCodeCoordinationTools(OpenCodeWorkshopTools):
    TOOL = 'archhub_message'
    OPERATIONS = MESSAGE_OPERATIONS

    def __init__(self, owner):
        self.owner = owner
        with owner.bound_client() as client:
            self.server = build_coordination_server(client=_OwnedWorkshopClient(owner, client))
        self.calls = {}


__all__ = ['MESSAGE_OPERATIONS', 'OpenCodeCoordinationTools']
