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
            title, work = args.get('task') or 'Declared step', args.get('request_id') or ''
            # Only a proven repeat continues a step: the same declared work (request id and task text) while that
            # step is still the active, unfinished one. A finished task or another task with the same label is new.
            if not (current and work and current.get('work') == work and current['title'] == title
                    and current.get('state') != 'done'):
                current = {'key': call['id'], 'title': title, 'work': work, 'calls': []}
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
    projected, before = [], copy.deepcopy(document)
    groups = steps(transcript)
    for group in groups:
        calls = group['calls']
        mapped, chosen, kind, engine, params, item = _projection(calls)
        identity = 'work-' + sha256((session_node['id'] + '\0' + group['key']).encode()).hexdigest()[:24]
        existing = next((n for n in document['nodes'] if n['id'] == identity), None)
        metadata = {'role': 'step', 'owner': session_node['id'], 'runtime': runtime, 'native': native,
                    'calls': [c['id'] for c in calls], 'kind': kind, 'tool': calls[mapped.index(chosen)]['tool'] if calls else 'detail not available',
                    'runnable': engine != 'note' and len(params) == len(chosen[2]), 'state': group.get('state', 'working')}
        if declaration.get('task_id'):
            metadata['task'] = declaration['task_id']
        if existing is None:
            from .canvas_documents import free_spot
            node = {'id': identity, 'type': engine, 'title': redact(str(group['title'])), 'params': params,
                    'paramDefs': _definitions(params), 'position': free_spot(document, 464, 380),
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
    _merge_repeats(document, before, session_node['id'], projected, transcript)
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


def _projection(calls):
    """The node an agent step projects to: its dominant tool mapping, with secrets removed."""
    mapped = [mapping(c) for c in calls]
    dominant = Counter((m[0], m[1], m[3]) for m in mapped).most_common(1)
    chosen = next(m for m in mapped if (m[0], m[1], m[3]) == dominant[0][0]) if dominant else ('step', 'note', {}, '')
    kind, engine, params, item = chosen
    params = redact(params)
    # Secret-bearing parameters are never persisted, including under benign container keys.
    params = {k: v for k, v in params.items() if '[redacted]' not in json.dumps(v)}
    if params != chosen[2]:
        engine, item = 'note', ''
    return mapped, chosen, kind, engine, params, item


# What the projection itself writes on a step node; any other key is something he set (icon, colour, label, ...).
_PROJECTED_KEYS = frozenset({'id', 'type', 'title', 'params', 'paramDefs', 'position', 'agentWork', 'approvalRequired',
                             'item', 'ports', 'result'})


def _customised(node, engine, params, item):
    """True when he changed anything the projection did not make, or moved it: keep that copy."""
    from .canvas_documents import THING_ENGINES
    from .library_engines import library_item_ports
    if set(node) - _PROJECTED_KEYS or node.get('approvalRequired') is not True or node.get('item', '') != item:
        return True
    if node.get('paramDefs') != _definitions(params):
        return True
    spec = THING_ENGINES.get(engine)
    if node.get('ports') != ({'source': spec['out'], 'target': spec['in']} if spec else library_item_ports(item, engine)):
        return True
    # Before this change the projection placed steps on a 320 x 400 grid from (464, 380); anywhere else he moved it.
    position = node.get('position') or {}
    x, y = position.get('x'), position.get('y')
    return not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and (x - 464) % 320 == 0
                and 464 <= x <= 464 + 3 * 320 and (y - 380) % 400 == 0 and y >= 380)


def _remapped(wire, target):
    new = copy.deepcopy(wire)
    for side in ('from', 'to'):
        new[side]['node'] = target.get(new[side]['node'], new[side]['node'])
    return new


def _signature(wire):
    return json.dumps({k: v for k, v in wire.items() if k != 'id'}, sort_keys=True)


def _memberships(document, identity):
    node = next((n for n in document['nodes'] if n['id'] == identity), {})
    return ({('group', g.get('id')) for g in document.get('groups', []) if identity in g.get('nodes', [])}
            | {('node', n['id']) for n in document['nodes'] if identity in n.get('children', [])}
            | ({('parent', node['parent'])} if node.get('parent') else set()))


def _merge_repeats(document, before, owner, projected, transcript):
    """Older files hold one node per re-declare of the same work. A copy merges into its surviving step only when
    it is a proven, untouched repeat: same owner and task, its calls now inside the survivor, its type and
    parameters exactly what the projection made (no hand edits), and its wires and groups move without conflict.
    Its hand-drawn wires (with their conditions) and group membership move onto the survivor. Anything else stays."""
    by_call = {c['id']: c for c in transcript.get('calls', [])}
    survivors = {n['id']: (n, {c['id'] for c in calls}) for n, calls in projected}
    merged = {}
    for copy_node in list(document['nodes']):
        work = copy_node.get('agentWork') or {}
        if copy_node['id'] in survivors or work.get('role') != 'step' or work.get('owner') != owner:
            continue
        mine = set(work.get('calls') or [])
        match = [(n, ids) for n, ids in survivors.values()
                 if n['title'] == copy_node['title'] and mine and mine <= ids and work.get('task')
                 and n['agentWork'].get('task') == work.get('task') and n['id'] != copy_node['id']]
        if len(match) != 1 or not all(i in by_call for i in mine):
            continue                                   # no proof, or two candidates: leave it intact
        survivor = match[0][0]
        _mapped, _chosen, _kind, engine, params, item = _projection([by_call[i] for i in sorted(mine, key=list(by_call).index)])
        if copy_node['type'] != engine or copy_node.get('params') != params or _customised(copy_node, engine, params, item):
            continue                                   # he edited or styled this copy: it is his, keep it
        theirs, ours = _memberships(document, copy_node['id']), _memberships(document, survivor['id'])
        if theirs and ours and theirs != ours:
            continue                                   # in a different group than the survivor: ambiguous
        merged[copy_node['id']] = (copy_node, survivor, theirs - ours)
    # The whole copy -> survivor mapping is decided first; every original wire is then remapped once, both ends,
    # from the original wire list. A wire between two copies, a self-loop, or two different wires landing on one
    # input keep the copies involved (repeat until the mapping is stable).
    hand_wires = [w for w in document['wires'] if not w.get('agentOwner')]
    while True:
        target = {cid: entry[1]['id'] for cid, entry in merged.items()}
        drop, landing = set(), {}
        for wire in hand_wires:
            ends = [wire['from']['node'], wire['to']['node']]
            copies = [end for end in ends if end in target]
            new = _remapped(wire, target)
            if len(copies) == 2 or new['from']['node'] == new['to']['node']:
                drop.update(copies)
                continue
            landing.setdefault((new['to']['node'], new['to']['socket']), {}).setdefault(_signature(new), set()).update(copies)
        for kinds in landing.values():
            if len(kinds) > 1:                         # one input takes one wire
                for owners in kinds.values():
                    drop.update(owners)
        if not drop:
            break
        merged = {cid: entry for cid, entry in merged.items() if cid not in drop}
    if not merged:
        return
    from .session_files import checkpoint_document
    # The checkpoint is the file as it was before this projection touched it.
    snapshot = copy.deepcopy(before)
    checkpoint_document(snapshot, 'Before merging repeated steps')
    document.setdefault('properties', {}).setdefault('checkpoints', []).append(snapshot['properties']['checkpoints'][-1])
    target = {cid: entry[1]['id'] for cid, entry in merged.items()}
    wires, seen = [], set()
    for wire in document['wires']:
        new = wire if wire.get('agentOwner') else _remapped(wire, target)
        if not wire.get('agentOwner'):
            key = (new['to']['node'], new['to']['socket'], _signature(new))
            if key in seen:
                continue                               # the same wire arriving twice lands once
            seen.add(key)
        wires.append(new)
    document['wires'] = wires
    gone = set(merged)
    for _copy, survivor, joins in merged.values():
        for kind, ref in joins:
            if kind == 'parent':
                survivor['parent'] = ref
            for group in document.get('groups', []) if kind == 'group' else []:
                if group.get('id') == ref and survivor['id'] not in group['nodes']:
                    group['nodes'].append(survivor['id'])
            for row in document['nodes'] if kind == 'node' else []:
                if row['id'] == ref and survivor['id'] not in row['children']:
                    row['children'].append(survivor['id'])
    document['nodes'] = [n for n in document['nodes'] if n['id'] not in gone]
    for group in document.get('groups', []):
        group['nodes'] = [i for i in group.get('nodes', []) if i not in gone]
    for row in document['nodes']:
        if 'children' in row:
            row['children'] = [i for i in row['children'] if i not in gone]


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


def request_approval(node, params, feeds, *, continuation=None):
    """Use the existing one-shot Ask owner and Approve card, with an exact immutable input."""
    from .hook_decision import _remember, ask_reviews
    clean = copy.deepcopy(node)
    clean['params'] = params
    clean.pop('result', None)
    payload = {'node': clean, 'feeds': feeds}
    if continuation:
        payload['continuation'] = copy.deepcopy(continuation)
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    event = {'tool': 'canvas.run', 'input': payload, 'vendor': 'archhub', 'session': 'canvas'}
    identity = _remember(event, 'write', 'canvas', digest, 'Run ' + node.get('title', node['type']), __import__('os').environ)
    if not identity:
        raise ValueError('The approval could not be saved.')
    return next(card for card in ask_reviews() if card['id'] == identity)


def decline_canvas(payload):
    from . import canvas_documents
    continuation = payload.get('continuation')
    if not continuation:
        return
    def change(document):
        node = next((row for row in document['nodes'] if row['id']==payload['node']['id']), None)
        from .session_files import approval_current, persist_run
        if not node or not approval_current(document, continuation, node['id']):
            return []
        # Keep the saved status understood by existing approval readers.
        node['result'] = {'status': 'Declined', 'display': 'Rejected', 'output': {}, 'error': 'Rejected by you.'}
        for row in document['nodes']:
            if row['id'] != node['id'] and row.get('result', {}).get('status') == 'Waiting':
                row['result'] = {'status': 'Blocked', 'output': {}, 'error': 'Canvas approval was rejected.'}
        document['properties']['canvasRun']['state'] = 'Ended'
        persist_run(document, continuation['path'])
        return []
    canvas_documents.edit(continuation['path'], 'You', 'reject Canvas Run', change, solve_changed=False)
    if continuation.get('parent'):
        parent = continuation['parent']
        decline_canvas({'node': parent['node'], 'continuation': parent})


def release(payload):
    from .session_files import _dispatch_node, new_document, validate
    from .enforce import guard_effect
    node, feeds = payload['node'], payload['feeds']
    continuation = payload.get('continuation')
    if continuation:
        from . import canvas_documents
        from .session_files import read_document, run_document, skill_result, approval_current, persist_run
        from .hook_decision import _RELEASING
        from .host_exec import UnconfirmedHostRun
        def inputs(document):
            return {'id': document['id'], 'title': document['title'],
                    'nodes': [{key: value for key, value in row.items() if key not in ('result', 'position')}
                              for row in document['nodes']],
                    'wires': document['wires'], 'groups': document['groups'], 'notes': document['notes'],
                    'taskContext': document.get('properties', {}).get('taskContext')}
        outcome = {}
        def resume(document):
            if not approval_current(document, continuation, node['id']) or inputs(document) != inputs(continuation.get('source') or continuation['document']):
                raise ValueError('The canvas changed after this approval. Run its current values again.')
            execution = copy.deepcopy(continuation['document'])
            released = payload.get('released')
            error = payload.get('error')
            unconfirmed = payload.get('unconfirmed', False)
            if released is None:
                try:
                    output, display = _dispatch_node(execution, node, node['type'], node['params'], feeds,
                                                     invoke=guard_effect, stopped=None, depth=continuation.get('depth', 0),
                                                     continuation={**continuation, 'document': execution, 'source': document})
                except UnconfirmedHostRun as failure:
                    output, display, error = {}, str(failure), str(failure)
                    unconfirmed = True
                except Exception as failure:
                    output, display, error = {}, str(failure), str(failure)
            else:
                output, display = released
            completed = dict(continuation['completed'])
            each = continuation.get('each')
            waiting = isinstance(output, dict) and output.get('approvalId')
            status = 'Unconfirmed' if unconfirmed else 'Error' if error else 'Waiting for approval' if waiting else 'Done'
            if each and not (waiting or unconfirmed):
                from .stem_graph_evaluation import each_fault
                each = {node['id']: {'rows': each['rows'] + [(output, display, error or each_fault(output, display))], 'remaining': each['remaining']}}
            else:
                completed[node['id']] = {'status': status, 'output': output, 'display': display,
                                         **({'error': error} if error else {})}
            attempt = execution['properties']['canvasRun'].get('attempts', {}).get(node['id'])
            if attempt and unconfirmed:
                attempt.pop('outcome', None)
            elif attempt:
                attempt['outcome'] = {'status': status, 'output': output, 'display': display}
                next(row for row in execution['nodes'] if row['id'] == node['id'])['result'] = copy.deepcopy(attempt['outcome'])
                persist_run(execution, continuation['path'], document)
            token = _RELEASING.set(False)
            try:
                result = run_document(execution, invoke=guard_effect, roots=continuation['roots'], path=continuation['path'],
                                      depth=continuation.get('depth', 0), _resume=completed, _each=each,
                                      _source=document, _parent=continuation.get('parent'))
            finally:
                _RELEASING.reset(token)
            for row in document['nodes']:
                if row['id'] in result['results']:
                    row['result'] = result['results'][row['id']]
            if result.get('run'):
                document.setdefault('properties', {})['canvasRun'] = result['run']
            outcome.update(result)
            return list(result['results'])
        parent = continuation.get('parent')
        ancestor = parent
        while ancestor:
            if not approval_current(read_document(ancestor['path']), ancestor, ancestor['node']['id']):
                raise ValueError('The calling canvas changed after this approval. Run its current values again.')
            ancestor = ancestor.get('parent')
        document, _ = canvas_documents.edit(continuation['path'], 'You', 'approve and resume Canvas Run', resume, solve_changed=False)
        if parent and not outcome.get('approvalId'):
            error = '; '.join(row.get('error', '') for row in outcome['results'].values() if row.get('error'))
            produced = skill_result(outcome) if outcome['succeeded'] else ({}, error)
            return release({'node': parent['node'], 'feeds': {}, 'continuation': parent, 'released': produced, 'error': error,
                            'unconfirmed': outcome.get('run', {}).get('state') == 'Unconfirmed'})
        return {**outcome, 'path': continuation['path']}
    document = new_document('Approved step')
    document['nodes'] = [node]
    validate(document)
    if node.get('agentWork', {}).get('runnable') is False:
        raise ValueError('Shell and edit steps require the escape hatch.')
    output, display = _dispatch_node(document, node, node['type'], node['params'], feeds,
                                     invoke=guard_effect, stopped=None, depth=0)
    return {'output': output, 'display': display}
