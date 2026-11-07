"""Agent work is a projection into its existing task file; raw history stays in native logs."""
import copy
import json
import re
from collections import Counter
from hashlib import sha256
from uuid import uuid4


def redact(value):
    from .session_files import _SECRET
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if not _SECRET.search(k)
                and k.casefold() not in ('authorization', 'cookie', 'set-cookie', 'x-api-key')}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY[^-]*-----.*?(?:-----END [^-]*PRIVATE KEY[^-]*-----|$)', '[redacted]', value, flags=re.S | re.I)
        value = re.sub(r'''(?i)(bearer\s+|(?:password|secret|token|api[_-]?key|private[_-]?key|credential)["']?\s*[=:]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;"'}]+)''', r'\1[redacted]', value)
        return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{8,}|(?:sk_live_|rk-|gh[pousr]_|github_pat_|AIza|xox[bpas]-)[A-Za-z0-9_-]{10,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b', '[redacted]', value)
    return value


def _tool(call):
    return call['tool'].rsplit('__', 1)[-1].rsplit('.', 1)[-1].lower()


def mapping(call):
    """Only explicit tool identities map to engines. A command is never parsed into a read."""
    from .native_host_tools import HOST_TOOLS
    from .library_engines import LIBRARY_ITEM_ENGINES
    tool, args = _tool(call), call['input']
    args = args if isinstance(args, dict) else {}
    if tool in ('read', 'read_file'):
        return 'file read', 'thing.file', {'path': args.get('file_path') or args.get('path') or ''}, ''
    if tool in ('write', 'write_file') and 'code' not in args:
        return 'file write', 'thing.file.write', {'path': args.get('file_path') or args.get('path') or '', 'content': args.get('content', '')}, ''
    if tool in ('bash', 'shell', 'exec_command', 'execute', 'run_command', 'powershell', 'apply_patch', 'edit', 'edit_file', 'multiedit'):
        return 'shell' if tool not in ('apply_patch', 'edit', 'edit_file', 'multiedit') else 'edit', 'note', args, ''
    if tool in ('send', 'send_message', 'message') and args.get('to') and (args.get('text') or args.get('message')):
        return 'message', 'thing.agent', {'agent': args['to'], 'instructions': args.get('text') or args['message']}, ''
    item = LIBRARY_ITEM_ENGINES.get(tool) if tool.startswith(('r_', 'b_')) else None
    host = next((r for r in HOST_TOOLS if r['id'] == tool), None)
    if item or host:
        spec = item or host
        engine = spec['engine']
        # Raw host code remains an escape hatch, even when its broker exists.
        if any(k in args for k in ('code', 'script', 'command')):
            return 'shell', 'note', args, ''
        return 'broker', engine, {**spec.get('params', {}), **args}, tool if item else ''
    return ('web' if tool in ('webfetch', 'websearch', 'search_query', 'fetch', 'browse') else
            'message' if tool in ('send', 'send_message', 'message') else 'tool'), 'note', args, ''


def _definitions(params):
    definitions = []
    for key, value in params.items():
        kind = ('bool' if isinstance(value, bool) else 'integer' if isinstance(value, int) else
                'number' if isinstance(value, float) else 'list' if isinstance(value, list) else
                'object' if isinstance(value, dict) else 'folder' if 'folder' in key or key == 'cwd' else
                'file' if key in ('path', 'file', 'file_path', 'output_path') else 'text')
        definitions.append({'id': key, 'name': key.replace('_', ' ').capitalize(), 'type': kind})
    return definitions


def _texts(value):
    if isinstance(value, str):
        yield value
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return
        if isinstance(decoded, (dict, list)):
            yield from _texts(decoded)
        elif isinstance(decoded, str) and decoded != value:
            yield decoded
    elif isinstance(value, dict):
        for child in value.values():
            yield from _texts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _texts(child)


def steps(transcript):
    """Use declarations as boundaries; without them one step per actual turn."""
    groups, current = [], None
    calls = transcript.get('calls', [])
    declared = any(_tool(c) == 'declare' for c in calls)
    for call in calls:
        if _tool(call) == 'declare':
            args = call['input'] if isinstance(call['input'], dict) else {}
            current = {'key': call['id'], 'title': args.get('task') or 'Declared step', 'calls': []}
            groups.append(current)
        elif _tool(call) in ('task_complete', 'complete'):
            if current:
                current['state'] = 'done'
        else:
            if current is None or (not declared and current['key'] != call['turn']):
                current = {'key': call['turn'], 'title': 'Agent turn', 'calls': []}
                groups.append(current)
            current['calls'].append(call)
    return groups


def project(document, session_node, declaration, transcript):
    """Reconcile stable ids, preserving every edited parameter and user position."""
    runtime, native = declaration.get('runtime', ''), declaration.get('native_session_id', '')
    session_node['agentWork'] = {'role': 'session', 'runtime': runtime, 'native': native}
    session_node['params']['model'] = transcript.get('model') or declaration.get('model') or 'detail not available'
    session_node['params']['goal'] = session_node['title']
    session_node['params']['detail'] = '' if transcript.get('calls') else 'detail not available'
    from .canvas_documents import THING_ENGINES
    from .library_engines import library_item_ports
    projected = []
    for index, group in enumerate(steps(transcript)):
        calls = group['calls']
        mapped = [mapping(c) for c in calls]
        dominant = Counter((m[0], m[1], m[3]) for m in mapped).most_common(1)
        chosen = next(m for m in mapped if (m[0], m[1], m[3]) == dominant[0][0]) if dominant else ('step', 'note', {}, '')
        kind, engine, params, item = chosen
        params = redact(params)
        # Secret-bearing parameters are never persisted, including under benign container keys.
        params = {k: v for k, v in params.items() if '[redacted]' not in json.dumps(v)}
        if params != chosen[2]:
            engine, item = 'note', ''
        identity = 'work-' + sha256((session_node['id'] + '\0' + group['key']).encode()).hexdigest()[:24]
        existing = next((n for n in document['nodes'] if n['id'] == identity), None)
        metadata = {'role': 'step', 'owner': session_node['id'], 'runtime': runtime, 'native': native,
                    'calls': [c['id'] for c in calls], 'kind': kind, 'tool': calls[mapped.index(chosen)]['tool'] if calls else 'detail not available',
                    'runnable': engine != 'note' and len(params) == len(chosen[2]), 'state': group.get('state', 'working')}
        if existing is None:
            node = {'id': identity, 'type': engine, 'title': redact(str(group['title'])), 'params': params,
                    'paramDefs': _definitions(params), 'position': {'x': 464 + index % 4 * 320, 'y': 380 + index // 4 * 400},
                    'agentWork': metadata}
            node['approvalRequired'] = True
            if item:
                node['item'] = item
            spec = THING_ENGINES.get(engine)
            node['ports'] = {'source': spec['out'], 'target': spec['in']} if spec else library_item_ports(item, engine)
            document['nodes'].append(node)
        else:
            node = existing
            node['agentWork'] = metadata
        projected.append((node, calls))
    # Inferred wires explain observed data flow; they are evidence, not executable bindings.
    document['wires'] = [w for w in document['wires'] if w.get('agentOwner') != session_node['id']]
    for later, _later_calls in projected:
        for earlier, earlier_calls in projected:
            if earlier['id'] == later['id']:
                break
            for key, value in later['params'].items():
                if not isinstance(value, str) or len(value) < 4:
                    continue
                if not any(len(text) >= 4 and text in value for c in earlier_calls for text in _texts(c.get('output', ''))):
                    continue
                target = 'param:' + key
                if any(w['to'] == {'node': later['id'], 'socket': target} for w in document['wires']):
                    continue
                sources = earlier.get('ports', {}).get('source', [])
                if not sources:
                    continue
                source = 'path' if any(p['id'] == 'path' for p in sources) else sources[0]['id']
                document['wires'].append({'id': 'inferred-' + earlier['id'] + '-' + later['id'] + '-' + key,
                    'from': {'node': earlier['id'], 'socket': source}, 'to': {'node': later['id'], 'socket': target},
                    'inferred': True, 'agentOwner': session_node['id']})


def fork(document, identity):
    selected = next(n for n in document['nodes'] if n['id'] == identity)
    meta = selected.get('agentWork', {})
    owner = identity if meta.get('role') == 'session' else meta.get('owner')
    source = [n for n in document['nodes'] if owner and n.get('agentWork', {}).get('owner') == owner] if owner else [selected]
    if meta.get('role') == 'step':
        source = source[source.index(selected):]
    ids = {n['id']: str(uuid4()) for n in source}
    for original in source:
        node = copy.deepcopy(original)
        node['id'] = ids[original['id']]
        node.pop('agentWork', None)
        node.pop('result', None)
        node['position']['y'] += 480
        document['nodes'].append(node)
    # Observed dependencies stay dashed until the user explicitly connects live sockets.
    for wire in list(document['wires']):
        if wire['from']['node'] in ids and wire['to']['node'] in ids:
            cloned = copy.deepcopy(wire)
            cloned['id'] = str(uuid4())
            cloned.pop('agentOwner', None)
            for side in ('from', 'to'):
                cloned[side]['node'] = ids[wire[side]['node']]
            document['wires'].append(cloned)
    return list(ids.values())


def history(node):
    from .agent_status import read_transcript
    meta = node.get('agentWork') or {}
    transcript = read_transcript(meta.get('runtime'), meta.get('native'))
    return {**transcript, 'calls': [c for c in transcript['calls'] if c['id'] in meta.get('calls', [])]}


def request_approval(node, params, feeds):
    """Use the existing one-shot Ask owner and Approve card, with an exact immutable input."""
    from .hook_decision import _remember, ask_reviews
    clean = copy.deepcopy(node)
    clean['params'] = params
    clean.pop('result', None)
    payload = {'node': clean, 'feeds': feeds}
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    event = {'tool': 'canvas.run', 'input': payload, 'vendor': 'archhub', 'session': 'canvas'}
    identity = _remember(event, 'write', 'canvas', digest, 'Run ' + node.get('title', node['type']), __import__('os').environ)
    if not identity:
        raise ValueError('The approval could not be saved.')
    return next(card for card in ask_reviews() if card['id'] == identity)


def release(payload):
    from .session_files import _dispatch_node, new_document, validate
    from .enforce import guard_effect
    node, feeds = payload['node'], payload['feeds']
    document = new_document('Approved step')
    document['nodes'] = [node]
    validate(document)
    if node.get('agentWork', {}).get('runnable') is False:
        raise ValueError('Shell and edit steps require the escape hatch.')
    output, display = _dispatch_node(document, node, node['type'], node['params'], feeds,
                                     invoke=guard_effect, stopped=None, depth=0)
    return {'output': output, 'display': display}
