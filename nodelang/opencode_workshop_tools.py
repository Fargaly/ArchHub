"""Native OpenCode dispatch into the retained selected-Work MCP implementation.

The caller supplies deployment-selected Work and the already bound hook owner.
This adapter never constructs an owner, selects a task from model arguments,
issues permissions, or retries an operation.
"""
import asyncio
import copy
import json

from mcp.server.fastmcp.exceptions import ToolError

from .native_agent_mcp import attach_workshop_tools
from .native_workshop_tools import WORKSHOP_TASK_TOOL_NAMES


class OpenCodeWorkshopTools:
    def __init__(self, owner, selected_work):
        self.owner = owner
        self.server = attach_workshop_tools(owner, selected_work)
        self.calls = {}

    @staticmethod
    def _arguments(value):
        if (type(value) is not dict or set(value) != {'operation', 'arguments'}
                or value['operation'] not in WORKSHOP_TASK_TOOL_NAMES
                or type(value['arguments']) is not dict):
            raise ValueError('Unsupported selected-Work operation or arguments')
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(encoded.encode('utf-8')) > 65536:
            raise ValueError('Selected-Work input exceeds 64 KiB')
        return copy.deepcopy(value)

    def dispatch(self, event):
        if (event.get('vendor') != 'opencode'
                or event.get('session_id') != self.owner._identity.external_session_id
                or event.get('tool_name') != 'archhub_work'):
            raise ValueError('Selected-Work native identity mismatch')
        call = event.get('tool_use_id')
        if type(call) is not str or not call or len(call) > 256:
            raise ValueError('Selected-Work call identity required')
        phase = event.get('hook_event_name')
        try:
            arguments = self._arguments(event.get('tool_input'))
        except (TypeError, ValueError):
            if phase == 'PreToolUse':
                # Known local refusal precedes every task effect. Do not turn
                # a misspelled tool into a quarantined native session.
                return {'decision': 'deny'}
            raise
        with self.owner.bound_client():
            if phase == 'PreToolUse':
                if call in self.calls or len(self.calls) >= 64:
                    raise ValueError('Selected-Work call already retained or capacity reached')
                self.calls[call] = {'arguments': arguments, 'state': 'admitted'}
                return {'decision': 'allow'}
            retained = self.calls.get(call)
            if retained is None or retained['arguments'] != arguments:
                raise ValueError('Selected-Work call has no matching admission')
            if (phase == 'PostToolUse' and retained['state'] == 'admitted'
                    and event.get('tool_response') == {'status': 'skipped'}):
                # Both sides prove execution never began; uncertain/completed
                # calls cannot enter this branch or be silently discarded.
                del self.calls[call]
                return {'decision': 'allow'}
            if phase == 'NativeToolExecute' and retained['state'] == 'admitted':
                # Reserve before calling. Lost output must never repeat an effect.
                retained['state'] = 'uncertain'
                try:
                    result = asyncio.run(self.server.call_tool(
                        arguments['operation'], arguments['arguments']))
                    output = {'isError': False, 'result': result}
                except ToolError as error:
                    # The existing selected-Work server retains any uncertain
                    # effect itself; its work_reconcile tool remains available.
                    output = {'isError': True, 'error': str(error)}
                encoded = json.dumps(output, allow_nan=False, ensure_ascii=False,
                    default=lambda value: value.model_dump(mode='json'))
                if len(encoded.encode('utf-8')) > 524288:
                    raise ValueError('Selected-Work output exceeds native frame budget')
                retained['state'] = 'completed'
                return {'decision': 'allow', 'tool_output': encoded}
            if phase == 'PostToolUse' and retained['state'] == 'completed':
                del self.calls[call]
                return {'decision': 'allow'}
            raise ValueError('Selected-Work execution is missing or already attempted')
