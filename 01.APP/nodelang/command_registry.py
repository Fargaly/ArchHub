"""One command catalogue; adapters keep execution and parameters with their owners."""
from __future__ import annotations

from functools import lru_cache


CONTEXTS = ('node', 'wire', 'group', 'session', 'project', 'run', 'step', 'library-card',
            'library-category', 'agent', 'settings-row', 'rail-item', 'header', 'docs-article',
            'automation', 'canvas', 'socket', 'frame', 'selection', 'message', 'tray',
            'navigation', 'palette', 'host', 'workshop')

# Missing classifications fail closed: an unclassified tool is never read-only.
READ_TOOLS = frozenset(('read', 'task.list', 'hosts.status', 'hosts_state',
    'canvas.list_open', 'canvas.open', 'canvas.read', 'library.search', 'native.hook_stop',
    'revit_ping', 'revit_info', 'acad_ping', 'acad_info', 'max_ping', 'max_info',
    'blender_ping', 'rhino_ping', 'office_read', 'outlook_inbox', 'notion_search', 'dropbox_list'))


def describe_agent_tools(tools):
    """The registered callables are bindings, not a second hand-maintained tool catalogue."""
    from .host_brokers import BROKER_ACTIONS
    from .native_host_tools import HOST_TOOLS
    specs = {row['id']: row for row in BROKER_ACTIONS}
    hosts = {row['id']: row for row in HOST_TOOLS}
    rows = []
    for index, tool in enumerate(tools):
        spec = specs.get(tool.name, {})
        read_only = tool.name in READ_TOOLS or spec.get('kind') == 'read'
        context = ('node' if tool.name.startswith('canvas.') else 'library-card' if tool.name == 'library.search'
                   else 'session' if tool.name.startswith('task.') else 'host' if tool.name in hosts or tool.name == 'hosts.status'
                   else 'agent' if tool.name.startswith('native.') else 'project' if tool.name.startswith('social.') else 'workshop')
        effect = not read_only and (context == 'host' or tool.name in ('canvas.run', 'social.work_execute'))
        operation = 'search' if tool.name in ('library.search', 'notion_search') else 'read' if read_only else 'delete' if tool.name in ('canvas.remove', 'task.archive') else 'write'
        rows.append({'id': 'agent.' + tool.name, 'label': (tool.description or tool.name).split('\n')[0],
            'group': 'host' if context == 'host' else 'ai' if context == 'agent' else 'office',
            'contexts': [context, *(['run', 'step', 'automation'] if tool.name == 'canvas.run' else [])],
            'action': {'tool': tool.name, **({'node': hosts[tool.name]['id'], 'engine': hosts[tool.name]['engine']} if tool.name in hosts else {})},
            'agent_callable': True,
            'read_only': read_only, 'effect': effect, 'approve': effect, 'operation': operation,
            'enabled_when': {}, 'order': index})
    return rows


@lru_cache(maxsize=1)
def agent_commands():
    from .native_agent_mcp import build_server
    server = build_server(_registry_catalogue=True)
    return describe_agent_tools(server._tool_manager.list_tools())


def commands_for_context(context, selection=None):
    selection = selection or {}
    if context not in CONTEXTS:
        raise ValueError('Unknown command context: ' + str(context))
    rows = []
    for command in (*STUDIO_COMMANDS, *agent_commands()):
        if context not in command['contexts'] or selection.get('readOnly') and not command['read_only']:
            continue
        rule = command['enabled_when']
        disabled = rule.get('fact') and selection.get(rule['fact']) is False
        rows.append({**command, 'enabled': not disabled,
                     'disabled_reason': rule.get('reason', '') if disabled else ''})
    return sorted(rows, key=lambda row: row['order'])


def payload():
    from .library_engines import LIBRARY_PRESENTATION
    return {'ok': True, 'contexts': list(CONTEXTS),
            'palette_order': ['Agents', 'Workflows', 'Hosts', 'Settings', 'Chats', 'Pages', 'Add node'],
            'groups': list(dict.fromkeys(category for category, _rows in LIBRARY_PRESENTATION)),
            'commands': [*STUDIO_COMMANDS, *agent_commands()]}


def apply_agent_registry(server, *, read_only=False):
    """Offer and dispatch only admitted bindings, ordered search/read/write/delete."""
    from mcp.types import ToolAnnotations
    tools = server._tool_manager._tools
    rows = describe_agent_tools(list(tools.values()))
    order = {'search': 0, 'read': 1, 'write': 2, 'delete': 3}
    selected = sorted((row for row in rows if not read_only or row['read_only']),
                      key=lambda row: (order[row['operation']], row['order']))
    kept = {}
    for row in selected:
        tool = tools[row['action']['tool']]
        tool.annotations = ToolAnnotations(title=row['label'], readOnlyHint=row['read_only'],
            destructiveHint=not row['read_only'])
        kept[tool.name] = tool
    server._tool_manager._tools = kept
    _guard_agent_effects(server, {row['action']['tool']: row for row in selected})


def _guard_agent_effects(server, commands):
    """Hold exact arguments in the existing Approve owner before calling the original tool."""
    from .native_host_tools import HOST_TOOLS, _allow_effect
    from mcp.server.fastmcp.exceptions import ToolError
    specs = {row['id']: row for row in HOST_TOOLS}
    manager = server._tool_manager
    original = manager.call_tool

    async def call_tool(name, arguments, context=None, convert_result=False):
        command = commands.get(name)
        spec = specs.get(name)
        if name not in manager._tools or not command or not command['effect'] or not spec:
            return await original(name, arguments, context=context, convert_result=convert_result)
        try:
            tool = manager.get_tool(name)
            params = tool.fn_metadata.arg_model.model_validate(arguments).model_dump()
            host = spec.get('effect_host') or spec['engine'].split('.')[0]
            if host in ('revit', 'acad', 'max', 'rhino', 'blender'):
                _allow_effect(host)
            from hashlib import sha256
            import json
            import os
            from .hook_decision import _remember
            from .session_files import new_document, validate
            node = {'id': 'command:' + name, 'type': spec['engine'], 'title': spec['title'],
                    'params': params, 'position': {'x': 0, 'y': 0}, 'approvalRequired': True}
            document = new_document(spec['title'])
            document['nodes'] = [node]
            validate(document)
            event = {'tool': name, 'input': {'connector': 'archhub.commands', 'arguments': params},
                     'vendor': 'archhub', 'session': 'commands'}
            digest = sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            identity = _remember(event, 'write', 'command', digest, 'Run ' + spec['title'], os.environ)
            if not identity:
                raise ValueError('The approval could not be saved.')
            answer = {'ok': True, 'status': 'Waiting for approval', 'approvalId': identity}
            return tool.fn_metadata.convert_result(answer) if convert_result else answer
        except Exception as error:
            raise ToolError('Error executing tool %s: %s' % (name, error)) from error

    manager.call_tool = call_tool


def approved_action_list():
    return [{'name': row['action']['tool'], 'title': row['label']} for row in agent_commands()
            if row['effect'] and 'host' in row['contexts']]


def invoke_approved(name, arguments):
    """The normal one-shot approval release calls the original validated callable."""
    from .hook_decision import _RELEASING
    if not _RELEASING.get(False):
        raise ValueError('Approve this action first.')
    from .native_agent_mcp import build_server
    server = build_server(_registry_catalogue=True)
    tool = server._tool_manager.get_tool(name)
    commands = describe_agent_tools([tool]) if tool else []
    if not commands or not commands[0]['effect'] or 'host' not in commands[0]['contexts']:
        raise ValueError('Unknown held host command: ' + str(name))
    params = tool.fn_metadata.arg_model.model_validate(arguments).model_dump()
    return tool.fn(**params)


NAVIGATION_ROUTES = {
    "home": "Home",
    "workshop": "Workshop",
    "canvas": "Canvas",
    "library": "Library",
    "baboom": "BABOOM",
    "colleagues": "Team",
    "watcher": "Watcher",
    "brain": "Brain",
    "system": "System graph",
    "first-run": "First run",
    "runs": "Runs",
    "receipts": "Logs & receipts",
    "automations": "Automations",
    "docs": "Docs",
    "meetings": "Meetings",
    "dependencies": "Dependencies",
    "present": "Present",
    "community": "Community",
    "model-review": "Model review",
    "interface": "Interface studio",
    "feedback": "Feedback",
    "social": "Social media",
    "xray": "X-RAY",
    "access": "Plan & access",
    "routing": "Model routing"
}

MENU_PAGES = ["meetings","dependencies","home","workshop","canvas","docs","colleagues","brain","watcher","social","xray","model-review","community","present","interface","access","routing","automations","runs","receipts","feedback","system","first-run"]


# Existing Studio actions, in their original presentation order. No parameter values live here.
STUDIO_COMMANDS = (
    {"id": "menu.item", "label": "Open session", "group": "office", "contexts": ["session"], "action": {"client": "u.openTaskFile", "binding": "menu.item"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "canvas", "shortcut": "", "danger": False, "order": 0},
    {"id": "menu.file", "label": "File", "group": "input", "contexts": ["session"], "action": {"client": "u.pickFile", "binding": "menu.file"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "folder", "shortcut": "", "danger": False, "order": 1},
    {"id": "menu.meeting.notes", "label": "Meeting notes", "group": "office", "contexts": ["session"], "action": {"client": "u.show", "binding": "menu.meeting.notes"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "docs", "shortcut": "", "danger": False, "order": 2},
    {"id": "menu.copy.text", "label": "Copy text", "group": "input", "contexts": ["message"], "action": {"client": "callback", "binding": "menu.copy.text"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "docs", "shortcut": "", "danger": False, "order": 3},
    {"id": "menu.reply", "label": "Reply", "group": "office", "contexts": ["message"], "action": {"client": "callback", "binding": "menu.reply"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "workshop", "shortcut": "", "danger": False, "order": 4},
    {"id": "menu.show.on.canvas", "label": "Show on canvas", "group": "input", "contexts": ["message"], "action": {"client": "u.setSelectedNodeId", "binding": "menu.show.on.canvas"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {"fact": "bindingEnabled", "reason": "This message names no node on this canvas."}, "icon": "canvas", "shortcut": "", "danger": False, "order": 5},
    {"id": "menu.make.a.task.from.this", "label": "Make a task from this", "group": "office", "contexts": ["message"], "action": {"client": "api.createTask, u.openTaskFile", "binding": "menu.make.a.task.from.this"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "plus", "shortcut": "", "danger": False, "order": 6},
    {"id": "menu.unpin", "label": "Unpin", "group": "office", "contexts": ["message"], "action": {"client": "api.pinTaskMessage", "binding": "menu.unpin"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "pin", "shortcut": "", "danger": False, "order": 7},
    {"id": "menu.keep.open", "label": "Keep open", "group": "office", "contexts": ["session"], "action": {"client": "u.keepTaskTab", "binding": "menu.keep.open"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {"fact": "bindingEnabled", "reason": "This tab is already kept open."}, "icon": "pin", "shortcut": "", "danger": False, "order": 8},
    {"id": "menu.open.beside", "label": "Open beside", "group": "office", "contexts": ["session"], "action": {"client": "u.openTaskBeside", "binding": "menu.open.beside"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {"fact": "bindingEnabled", "reason": "This session is already open here."}, "icon": "canvas", "shortcut": "", "danger": False, "order": 9},
    {"id": "menu.rename", "label": "Rename", "group": "input", "contexts": ["session"], "action": {"client": "u.show", "binding": "menu.rename"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "edit", "shortcut": "", "danger": False, "order": 10},
    {"id": "menu.show.on.home", "label": "Show on Home", "group": "office", "contexts": ["session"], "action": {"client": "api.setTaskSession, u.setTask, u.go", "binding": "menu.show.on.home"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "home", "shortcut": "", "danger": False, "order": 11},
    {"id": "menu.close.tab", "label": "Close tab", "group": "office", "contexts": ["session"], "action": {"client": "u.closeTaskTab", "binding": "menu.close.tab"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "close", "shortcut": "Ctrl W", "danger": False, "order": 12},
    {"id": "menu.close.other.tabs", "label": "Close other tabs", "group": "office", "contexts": ["session"], "action": {"client": "u.canvasTabs, u.closeTaskTab", "binding": "menu.close.other.tabs"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {"fact": "bindingEnabled", "reason": "There are no other tabs."}, "icon": "close", "shortcut": "", "danger": False, "order": 13},
    {"id": "menu.add.rule", "label": "Add rule", "group": "input", "contexts": ["wire"], "action": {"client": "u.show", "binding": "menu.add.rule"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "edit", "shortcut": "", "danger": False, "order": 14},
    {"id": "menu.enable", "label": "Enable", "group": "input", "contexts": ["wire"], "action": {"client": "api.setWireEnabled", "binding": "menu.enable"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "stop", "shortcut": "", "danger": False, "order": 15},
    {"id": "menu.insert.convert", "label": "Insert Convert", "group": "input", "contexts": ["wire"], "action": {"client": "api.insertConvertOnWire", "binding": "menu.insert.convert"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "link", "shortcut": "", "danger": False, "order": 16},
    {"id": "menu.insert.node.here", "label": "Insert node here", "group": "input", "contexts": ["wire"], "action": {"client": "u.show, canvas?.point", "binding": "menu.insert.node.here"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "plus", "shortcut": "", "danger": False, "order": 17},
    {"id": "menu.show.in.inspector", "label": "Show in Inspector", "group": "input", "contexts": ["wire"], "action": {"client": "canvas?.inspectWire", "binding": "menu.show.in.inspector"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "settings", "shortcut": "", "danger": False, "order": 18},
    {"id": "menu.delete", "label": "Delete", "group": "transform", "contexts": ["wire"], "action": {"client": "api.deleteWire", "binding": "menu.delete"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "delete", "enabled_when": {}, "icon": "trash", "shortcut": "Del", "danger": True, "order": 19},
    {"id": "menu.item.21", "label": "Wire visibility", "group": "input", "contexts": ["socket"], "action": {"client": "api.setPortVisibility", "binding": "menu.item.21"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "link", "shortcut": "", "danger": False, "order": 20},
    {"id": "menu.disconnect", "label": "Disconnect", "group": "transform", "contexts": ["socket"], "action": {"client": "api.deleteSelection", "binding": "menu.disconnect"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {"fact": "bindingEnabled", "reason": "This socket has no connections."}, "icon": "close", "shortcut": "", "danger": False, "order": 21},
    {"id": "menu.show.compatible.nodes", "label": "Show compatible nodes", "group": "input", "contexts": ["socket"], "action": {"client": "u.show", "binding": "menu.show.compatible.nodes"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "plus", "shortcut": "", "danger": False, "order": 22},
    {"id": "menu.return.to.inline.parameter", "label": "Return to inline parameter", "group": "input", "contexts": ["socket"], "action": {"client": "api.demoteParam, api.promoteParam", "binding": "menu.return.to.inline.parameter"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "link", "shortcut": "", "danger": False, "order": 23},
    {"id": "menu.rename.25", "label": "Rename", "group": "input", "contexts": ["node","group","frame"], "action": {"client": "u.show", "binding": "menu.rename.25"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "edit", "shortcut": "F2", "danger": False, "order": 24},
    {"id": "menu.colour", "label": "Colour", "group": "input", "contexts": ["node","group","frame"], "action": {"client": "u.show", "binding": "menu.colour"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "settings", "shortcut": "", "danger": False, "order": 25},
    {"id": "menu.select.contents", "label": "Select contents", "group": "input", "contexts": ["frame"], "action": {"client": "canvas?.select", "binding": "menu.select.contents"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "canvas", "shortcut": "", "danger": False, "order": 26},
    {"id": "menu.remove.frame.keep.nodes", "label": "Remove frame, keep nodes", "group": "transform", "contexts": ["frame"], "action": {"client": "api.ungroupNode", "binding": "menu.remove.frame.keep.nodes"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "close", "shortcut": "", "danger": False, "order": 27},
    {"id": "menu.open", "label": "Open", "group": "input", "contexts": ["group"], "action": {"client": "callback", "binding": "menu.open"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "arrow", "shortcut": "Enter", "danger": False, "order": 28},
    {"id": "menu.expand", "label": "Expand", "group": "transform", "contexts": ["group"], "action": {"client": "api.setGroupCollapsed", "binding": "menu.expand"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "group", "shortcut": "", "danger": False, "order": 29},
    {"id": "menu.select.contents.31", "label": "Select contents", "group": "input", "contexts": ["group"], "action": {"client": "canvas?.select", "binding": "menu.select.contents.31"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "canvas", "shortcut": "", "danger": False, "order": 30},
    {"id": "menu.save.as.skill", "label": "Save as skill", "group": "skill", "contexts": ["group"], "action": {"client": "u.show", "binding": "menu.save.as.skill"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "library", "shortcut": "", "danger": False, "order": 31},
    {"id": "menu.save.as.node.type", "label": "Save as node type", "group": "skill", "contexts": ["node","group"], "action": {"client": "u.show", "binding": "menu.save.as.node.type"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "library", "shortcut": "", "danger": False, "order": 32},
    {"id": "menu.ungroup", "label": "Ungroup", "group": "transform", "contexts": ["group"], "action": {"client": "api.ungroupNode", "binding": "menu.ungroup"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "group", "shortcut": "", "danger": False, "order": 33},
    {"id": "menu.delete.group.and.nodes", "label": "Delete group and nodes", "group": "transform", "contexts": ["group"], "action": {"client": "u.confirm, api.deleteGroup", "binding": "menu.delete.group.and.nodes"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "delete", "enabled_when": {}, "icon": "trash", "shortcut": "Del", "danger": True, "order": 34},
    {"id": "menu.properties", "label": "Properties", "group": "input", "contexts": ["node"], "action": {"client": "u.setSelectedNodeId", "binding": "menu.properties"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "settings", "shortcut": "", "danger": False, "order": 35},
    {"id": "menu.add.parameter", "label": "Add parameter", "group": "input", "contexts": ["node"], "action": {"client": "u.show", "binding": "menu.add.parameter"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "plus", "shortcut": "", "danger": False, "order": 36},
    {"id": "menu.show.output", "label": "Show output", "group": "output", "contexts": ["node"], "action": {"client": "u.show", "binding": "menu.show.output"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "eye", "shortcut": "", "danger": False, "order": 37},
    {"id": "menu.ask.the.agent", "label": "Ask the agent", "group": "ai", "contexts": ["node"], "action": {"client": "u.setSelectedNodeId, u.setTaskFace", "binding": "menu.ask.the.agent"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "brain", "shortcut": "", "danger": False, "order": 38},
    {"id": "menu.rerun", "label": "Rerun", "group": "trigger", "contexts": ["node"], "action": {"client": "api.runNode", "binding": "menu.rerun"}, "effect": True, "approve": True, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "refresh", "shortcut": "R", "danger": False, "order": 39},
    {"id": "menu.run.to.here", "label": "Run to here", "group": "trigger", "contexts": ["node"], "action": {"client": "api.runToHere", "binding": "menu.run.to.here"}, "effect": True, "approve": True, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "play", "shortcut": "", "danger": False, "order": 40},
    {"id": "menu.unfreeze", "label": "Unfreeze", "group": "governance", "contexts": ["node"], "action": {"client": "api.setNodeFlags", "binding": "menu.unfreeze"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "shield", "shortcut": "", "danger": False, "order": 41},
    {"id": "menu.unbypass", "label": "Unbypass", "group": "governance", "contexts": ["node"], "action": {"client": "api.setNodeFlags", "binding": "menu.unbypass"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "link", "shortcut": "", "danger": False, "order": 42},
    {"id": "menu.duplicate", "label": "Duplicate", "group": "transform", "contexts": ["node"], "action": {"client": "api.duplicateNodes", "binding": "menu.duplicate"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "canvas", "shortcut": "Ctrl D", "danger": False, "order": 43},
    {"id": "menu.copy", "label": "Copy", "group": "input", "contexts": ["node"], "action": {"client": "api.copyNodes", "binding": "menu.copy"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "docs", "shortcut": "Ctrl C", "danger": False, "order": 44},
    {"id": "menu.cut", "label": "Cut", "group": "transform", "contexts": ["node"], "action": {"client": "api.cutNodes", "binding": "menu.cut"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "edit", "shortcut": "Ctrl X", "danger": False, "order": 45},
    {"id": "menu.group", "label": "Group", "group": "input", "contexts": ["selection","node"], "action": {"client": "canvas?.group", "binding": "menu.group"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {"fact": "bindingEnabled", "reason": "Select at least two nodes."}, "icon": "group", "shortcut": "Ctrl G", "danger": False, "order": 46},
    {"id": "menu.frame", "label": "Frame", "group": "input", "contexts": ["selection","node"], "action": {"client": "canvas?.frame", "binding": "menu.frame"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {"fact": "bindingEnabled", "reason": "Select a node first."}, "icon": "canvas", "shortcut": "Ctrl Alt G", "danger": False, "order": 47},
    {"id": "menu.more", "label": "More", "group": "input", "contexts": ["node"], "action": {"client": "callback", "binding": "menu.more"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "more", "shortcut": "", "danger": False, "order": 48},
    {"id": "menu.delete.50", "label": "Delete", "group": "transform", "contexts": ["node"], "action": {"client": "u.confirm, api.deleteNode", "binding": "menu.delete.50"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "delete", "enabled_when": {"fact": "bindingEnabled", "reason": "Pinned nodes stay on this task."}, "icon": "trash", "shortcut": "Del", "danger": True, "order": 49},
    {"id": "menu.item.51", "label": "Run selected steps", "group": "trigger", "contexts": ["selection"], "action": {"client": "api.runSelection", "binding": "menu.item.51"}, "effect": True, "approve": True, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "play", "shortcut": "R", "danger": False, "order": 50},
    {"id": "menu.ask.the.agent.52", "label": "Ask the agent", "group": "ai", "contexts": ["selection","canvas"], "action": {"client": "u.setTaskFace", "binding": "menu.ask.the.agent.52"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "brain", "shortcut": "", "danger": False, "order": 51},
    {"id": "menu.save.as.skill.53", "label": "Save as skill", "group": "skill", "contexts": ["selection"], "action": {"client": "u.show", "binding": "menu.save.as.skill.53"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "library", "shortcut": "", "danger": False, "order": 52},
    {"id": "menu.align.left", "label": "Align left", "group": "transform", "contexts": ["selection"], "action": {"client": "api.alignNodes", "binding": "menu.align.left"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "arrange", "shortcut": "", "danger": False, "order": 53},
    {"id": "menu.align.top", "label": "Align top", "group": "transform", "contexts": ["selection"], "action": {"client": "api.alignNodes", "binding": "menu.align.top"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "arrange", "shortcut": "", "danger": False, "order": 54},
    {"id": "menu.duplicate.56", "label": "Duplicate", "group": "transform", "contexts": ["selection"], "action": {"client": "api.duplicateNodes", "binding": "menu.duplicate.56"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "canvas", "shortcut": "Ctrl D", "danger": False, "order": 55},
    {"id": "menu.copy.57", "label": "Copy", "group": "input", "contexts": ["selection"], "action": {"client": "api.copyNodes", "binding": "menu.copy.57"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "docs", "shortcut": "Ctrl C", "danger": False, "order": 56},
    {"id": "menu.cut.58", "label": "Cut", "group": "transform", "contexts": ["selection"], "action": {"client": "api.cutNodes", "binding": "menu.cut.58"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "edit", "shortcut": "Ctrl X", "danger": False, "order": 57},
    {"id": "menu.item.59", "label": "Delete selected nodes", "group": "transform", "contexts": ["selection"], "action": {"client": "u.confirm, api.deleteSelection", "binding": "menu.item.59"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "delete", "enabled_when": {}, "icon": "trash", "shortcut": "Del", "danger": True, "order": 58},
    {"id": "menu.add.node.here", "label": "Add node here", "group": "input", "contexts": ["canvas"], "action": {"client": "u.show, canvas?.point", "binding": "menu.add.node.here"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "plus", "shortcut": "Shift A", "danger": False, "order": 59},
    {"id": "menu.paste.here", "label": "Paste here", "group": "input", "contexts": ["canvas"], "action": {"client": "api.pasteNodes, canvas?.point", "binding": "menu.paste.here"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {"fact": "bindingEnabled", "reason": "Copy nodes first."}, "icon": "docs", "shortcut": "Ctrl V", "danger": False, "order": 60},
    {"id": "menu.add.note", "label": "Add note", "group": "note", "contexts": ["canvas"], "action": {"client": "u.show, canvas?.point", "binding": "menu.add.note"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "edit", "shortcut": "N", "danger": False, "order": 61},
    {"id": "menu.find.a.node", "label": "Find a node", "group": "input", "contexts": ["canvas"], "action": {"client": "u.show", "binding": "menu.find.a.node"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "search", "shortcut": "Ctrl F", "danger": False, "order": 62},
    {"id": "menu.select.all", "label": "Select all", "group": "input", "contexts": ["canvas"], "action": {"client": "canvas?.selectAll", "binding": "menu.select.all"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "canvas", "shortcut": "Ctrl A", "danger": False, "order": 63},
    {"id": "menu.arrange", "label": "Arrange", "group": "transform", "contexts": ["canvas"], "action": {"client": "api.arrangeGraph", "binding": "menu.arrange"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "arrange", "shortcut": "", "danger": False, "order": 64},
    {"id": "menu.fit", "label": "Fit", "group": "input", "contexts": ["canvas"], "action": {"client": "canvas?.fit", "binding": "menu.fit"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "fit", "shortcut": "", "danger": False, "order": 65},
    {"id": "menu.undo", "label": "Undo", "group": "input", "contexts": ["canvas"], "action": {"client": "api.undo", "binding": "menu.undo"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "undo", "shortcut": "Ctrl Z", "danger": False, "order": 66},
    {"id": "menu.redo", "label": "Redo", "group": "input", "contexts": ["canvas"], "action": {"client": "api.redo", "binding": "menu.redo"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "redo", "shortcut": "Ctrl Shift Z", "danger": False, "order": 67},
    {"id": "menu.show.the.thread", "label": "Show the thread", "group": "office", "contexts": ["canvas"], "action": {"client": "u.setTaskFace", "binding": "menu.show.the.thread"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "workshop", "shortcut": "Ctrl \\", "danger": False, "order": 68},
    {"id": "menu.open.archhub", "label": "Open ArchHub", "group": "host", "contexts": ["tray"], "action": {"client": "api.windowAction", "binding": "menu.open.archhub"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "home", "shortcut": "", "danger": False, "order": 69},
    {"id": "menu.baboom", "label": "BABOOM", "group": "ai", "contexts": ["tray"], "action": {"client": "u.go", "binding": "menu.baboom"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "brain", "shortcut": "F2", "danger": False, "order": 70},
    {"id": "menu.stop.everything", "label": "Stop everything", "group": "trigger", "contexts": ["tray"], "action": {"client": "api.stopEverything", "binding": "menu.stop.everything"}, "effect": True, "approve": True, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "stop", "shortcut": "", "danger": False, "order": 71},
    {"id": "menu.hide", "label": "Hide", "group": "host", "contexts": ["tray"], "action": {"client": "api.windowAction", "binding": "menu.hide"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "eye", "shortcut": "", "danger": False, "order": 72},
    {"id": "menu.quit", "label": "Quit", "group": "host", "contexts": ["tray"], "action": {"client": "api.windowAction", "binding": "menu.quit"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "delete", "enabled_when": {}, "icon": "close", "shortcut": "", "danger": True, "order": 73},
    {"id": "menu.settings", "label": "Settings", "group": "office", "contexts": ["navigation"], "action": {"client": "u.go", "binding": "menu.settings"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "settings", "shortcut": "Ctrl ,", "danger": False, "order": 74},
    {"id": "menu.back", "label": "Back", "group": "input", "contexts": ["node"], "action": {"client": "callback", "binding": "menu.back"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "back", "shortcut": "", "danger": False, "order": 75},
    {"id": "menu.unpin.output", "label": "Unpin output", "group": "governance", "contexts": ["node"], "action": {"client": "api.setNodeFlags", "binding": "menu.unpin.output"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "pin", "shortcut": "", "danger": False, "order": 76},
    {"id": "menu.fork", "label": "Fork", "group": "transform", "contexts": ["node"], "action": {"client": "api.forkNode", "binding": "menu.fork"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "canvas", "shortcut": "", "danger": False, "order": 77},
    {"id": "menu.repeat.this", "label": "Repeat this", "group": "trigger", "contexts": ["node"], "action": {"client": "u.schedule", "binding": "menu.repeat.this"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "icon": "clock", "shortcut": "", "danger": False, "order": 78},
    {"id": "menu.trace.back", "label": "Trace back", "group": "output", "contexts": ["node"], "action": {"client": "u.trace", "binding": "menu.trace.back"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "back", "shortcut": "", "danger": False, "order": 79},
    {"id": "menu.trace.forward", "label": "Trace forward", "group": "output", "contexts": ["node"], "action": {"client": "u.trace", "binding": "menu.trace.forward"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "icon": "arrow", "shortcut": "", "danger": False, "order": 80},
    *({'id': 'page.' + page, 'label': label, 'group': 'office',
       'contexts': ['navigation', 'rail-item', 'header', 'palette'], 'action': {'route': page},
       'effect': False, 'approve': False, 'agent_callable': False, 'read_only': True,
       'operation': 'read', 'enabled_when': {},
       'icon': 'home' if page == 'home' else 'workshop' if page == 'workshop' else 'docs' if page == 'docs' else 'canvas',
       'shortcut': '', 'danger': False, 'order': index, 'menuPage': page in MENU_PAGES,
       'menu_order': MENU_PAGES.index(page) if page in MENU_PAGES else -1}
      for index, (page, label) in enumerate(NAVIGATION_ROUTES.items(), start=81)),
    {"id": "palette.add_node", "label": "Add node", "group": "input", "contexts": ["palette", "library-card"], "action": {"client": "palette.add_node", "collection": "catalogue"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "paletteGroup": "Add node", "order": 106},
    {"id": "palette.template", "label": "Open workflow", "group": "skill", "contexts": ["palette", "session"], "action": {"client": "palette.template", "collection": "templates"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "paletteGroup": "Workflows", "order": 107},
    {"id": "palette.task", "label": "Open session", "group": "office", "contexts": ["palette", "session"], "action": {"client": "palette.task", "collection": "tasks"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "paletteGroup": "Chats", "order": 108},
    {"id": "palette.live_agent", "label": "Open agent", "group": "ai", "contexts": ["palette", "agent"], "action": {"client": "palette.live_agent", "collection": "liveAgents"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "paletteGroup": "Agents", "order": 109},
    {"id": "palette.agent", "label": "Open agent", "group": "ai", "contexts": ["palette", "agent"], "action": {"client": "palette.agent", "collection": "agents"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "paletteGroup": "Agents", "order": 110},
    {"id": "palette.graph", "label": "Open workflow", "group": "skill", "contexts": ["palette", "session"], "action": {"client": "palette.graph", "collection": "graphs"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "paletteGroup": "Workflows", "order": 111},
    {"id": "palette.host", "label": "Open connections", "group": "host", "contexts": ["palette", "host"], "action": {"client": "palette.host", "collection": "hosts"}, "effect": False, "approve": False, "agent_callable": False, "read_only": True, "operation": "read", "enabled_when": {}, "paletteGroup": "Hosts", "order": 112},
    {"id": "palette.setting", "label": "Expose settings", "group": "office", "contexts": ["palette", "settings-row"], "action": {"client": "palette.setting", "collection": "pages"}, "effect": False, "approve": False, "agent_callable": False, "read_only": False, "operation": "write", "enabled_when": {}, "paletteGroup": "Settings", "order": 113},
)
