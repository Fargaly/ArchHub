"""Node-native UI projection and generic interaction interpreter.

UI hierarchy, data binding, actions, attributes, and styles cross node
boundaries only through relation nodes. HTML is a disposable projection.
"""
from __future__ import annotations

import html
import json

from .core import relation_sources, relation_targets
from .laws_relation import set_relation_parameter


SAFE_TAGS = frozenset({
    'div', 'span', 'button', 'input', 'label', 'section', 'header', 'aside',
    'main', 'nav', 'a', 'article', 'svg', 'defs', 'marker', 'line', 'path',
    'strong', 'small', 'h1', 'h2', 'p',
})
VOID_TAGS = frozenset({'input'})


def _relation_property(store, relation, name, default=None):
    pid = relation['params'].get(name)
    return store.pull(pid) if pid in store.nodes else default


def _matching_relations(store, node_id, *, source_port=None, target_port=None):
    node = store.nodes[node_id]
    found = []
    for rid in node['relations']:
        relation = store.nodes.get(rid)
        if not relation or relation['kind'] != 'wire':
            continue
        sources = relation_sources(store.nodes, relation)
        targets = relation_targets(store.nodes, relation)
        source_hit = any(endpoint['node_id'] == node_id and
                         (source_port is None or endpoint.get('port_id') == source_port)
                         for endpoint in sources)
        target_hit = any(endpoint['node_id'] == node_id and
                         (target_port is None or endpoint.get('port_id') == target_port)
                         for endpoint in targets)
        if (source_port is not None and not source_hit) or (target_port is not None and not target_hit):
            continue
        found.append((relation, sources, targets))
    return found


def connect_ui_child(store, parent_id, child_id, order=0, actor=None):
    relation = store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': parent_id,
         'port_id': 'children', 'cardinality': 'many'},
        {'role': 'target', 'direction': 'in', 'node_id': child_id,
         'port_id': 'parent', 'cardinality': 'one'},
    ], title='UI child', actor=actor)
    set_relation_parameter(store, relation, 'order', int(order), actor=actor)
    return relation


def connect_ui_binding(store, source_id, ui_id, port='text', *, suffix='',
                       value_format='', actor=None):
    relation = store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': source_id,
         'port_id': 'value', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': ui_id,
         'port_id': str(port), 'cardinality': 'one'},
    ], title='UI binding', actor=actor)
    if suffix:
        set_relation_parameter(store, relation, 'suffix', suffix, actor=actor)
    if value_format:
        set_relation_parameter(store, relation, 'format', value_format, actor=actor)
    return relation


def connect_ui_action(store, ui_id, action_id, actor=None, event='activate'):
    if event not in ('activate', 'double_activate'):
        raise ValueError('unsupported UI action event %r' % event)
    return store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': ui_id,
         'port_id': event, 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': action_id,
         'port_id': 'execute', 'cardinality': 'one'},
    ], title='UI action', actor=actor)


def connect_ui_download(store, source_id, ui_id, actor=None):
    """Expose a node/session through a UI download port via a relation node."""
    return store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': source_id,
         'port_id': 'export', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': ui_id,
         'port_id': 'download', 'cardinality': 'one'},
    ], title='UI download', actor=actor)


def _format_value(value, value_format):
    if value_format == 'percent' and isinstance(value, (int, float)):
        return '%.1f%%' % value
    if isinstance(value, float):
        return ('%.3f' % value).rstrip('0').rstrip('.')
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(',', ':'))
    return str(value)


def _ui_bindings(store, node_id):
    bindings = []
    for relation, sources, targets in _matching_relations(store, node_id):
        target = next((endpoint for endpoint in targets if endpoint['node_id'] == node_id), None)
        if not target or target.get('port_id') == 'parent':
            continue
        port_id = target.get('port_id')
        projection_port = (
            port_id in {'text', 'value', 'download'}
            or bool(port_id and port_id.startswith(('value.', 'attr.', 'style.', 'view.')))
        )
        # A UI node can participate in operational/domain relations too. Only
        # presentation ports are renderer bindings; unrelated ports remain
        # authoritative graph relations without being stringified into HTML.
        if not projection_port:
            continue
        for source in sources:
            raw_value = (source['node_id'] if port_id == 'download'
                         else store.pull(source['node_id']))
            if port_id and port_id.startswith('value.'):
                key = port_id.split('.', 1)[1]
                raw_value = raw_value.get(key, '') if isinstance(raw_value, dict) else ''
            value = raw_value
            value = _format_value(value, _relation_property(store, relation, 'format', ''))
            value += str(_relation_property(store, relation, 'suffix', '') or '')
            bindings.append((port_id, value, source['node_id'], relation['id']))
    return bindings


def _ui_children(store, node_id):
    children = []
    for relation, sources, targets in _matching_relations(store, node_id, source_port='children'):
        if not any(endpoint['node_id'] == node_id for endpoint in sources):
            continue
        for target in targets:
            if target.get('port_id') == 'parent':
                children.append((_relation_property(store, relation, 'order', 0),
                                 relation['id'], target['node_id']))
    children.sort(key=lambda item: (item[0], item[1]))
    return [child_id for _order, _rid, child_id in children]


def _has_action(store, node_id, event='activate'):
    return any(any(endpoint['node_id'] == node_id for endpoint in sources)
               for _relation, sources, _targets
               in _matching_relations(store, node_id, source_port=event))


def project_ui(store, ui_root, _seen=None):
    node = store.nodes[ui_root]
    if node['kind'] != 'ui':
        raise ValueError('UI projection target %s is kind %r' % (ui_root, node['kind']))
    seen = set() if _seen is None else _seen
    if ui_root in seen:
        raise ValueError('UI relation cycle at %s' % ui_root)
    seen.add(ui_root)
    params = node['params']
    tag = str(store.pull(params['tag']))
    if tag not in SAFE_TAGS:
        raise ValueError('unsafe UI tag %r' % tag)
    cls = str(store.pull(params['cls'])) if 'cls' in params else ''
    attrs = dict(store.pull(params['attrs'])) if 'attrs' in params else {}
    styles = dict(store.pull(params['style'])) if 'style' in params else {}
    text_parts = [str(store.pull(params['text']))] if 'text' in params else []
    editable_source = None
    for port, value, source_id, _relation_id in _ui_bindings(store, ui_root):
        if port == 'text':
            text_parts.append(value)
        elif port == 'value' or port.startswith('value.'):
            attrs['value'] = value
            editable_source = source_id
            attrs['data-edit-port'] = port
        elif port.startswith('attr.'):
            attrs[port[5:]] = value
        elif port.startswith('style.'):
            styles[port[6:]] = value
        elif port == 'download':
            attrs['data-download'] = value
        elif port.startswith('view.'):
            attrs['data-' + port[5:].replace('_', '-')] = value
    if cls:
        attrs['class'] = cls
    attrs['data-node'] = ui_root
    if _has_action(store, ui_root):
        attrs['data-action'] = 'true'
    if _has_action(store, ui_root, 'double_activate'):
        attrs['data-double-action'] = 'true'
    if editable_source is not None:
        attrs['data-edit'] = 'true'
        if attrs.get('type') == 'checkbox':
            if str(attrs.get('value')).lower() in ('1', 'true', 'yes', 'on'):
                attrs['checked'] = 'checked'
            attrs.pop('value', None)
    if styles:
        attrs['style'] = ';'.join('%s:%s' % (name.replace('_', '-'), value)
                                  for name, value in styles.items())
    attr_bits = []
    for name, value in attrs.items():
        safe_name = ''.join(ch for ch in str(name) if ch.isalnum() or ch in '-_:')
        if safe_name:
            attr_bits.append('%s="%s"' % (safe_name,
                                           html.escape(str(value), quote=True)))
    opening = '<%s %s>' % (tag, ' '.join(attr_bits))
    if tag in VOID_TAGS:
        seen.remove(ui_root)
        return opening
    children = ''.join(project_ui(store, child, seen) for child in _ui_children(store, ui_root))
    content = ''.join(html.escape(part) for part in text_parts) + children
    seen.remove(ui_root)
    return '%s%s</%s>' % (opening, content, tag)


def activate_ui(store, ui_id, actor='user', command_handler=None, transaction=None,
                event='activate'):
    if event not in ('activate', 'double_activate'):
        raise ValueError('unsupported UI action event %r' % event)
    actions = []
    for _relation, sources, targets in _matching_relations(store, ui_id, source_port=event):
        if not any(endpoint['node_id'] == ui_id for endpoint in sources):
            continue
        actions.extend(endpoint['node_id'] for endpoint in targets
                       if endpoint.get('port_id') == 'execute')
    if len(actions) != 1:
        raise ValueError('UI node %s must resolve to exactly one action' % ui_id)
    payload = store.pull(actions[0])
    operations = payload if isinstance(payload, list) else [payload]
    if not operations or any(not isinstance(operation, dict)
                             or operation.get('op') not in {
                                 'set', 'freeze', 'unfreeze', 'sample', 'command'}
                             for operation in operations):
        raise ValueError('UI action %s does not contain allowed graph operations' % actions[0])
    touched = []
    for raw in operations:
        operation = dict(raw)
        operation['actor'] = actor
        if transaction is not None:
            operation['transaction'] = transaction
        if operation['op'] == 'command':
            if command_handler is None:
                raise ValueError('UI command has no injected host capability handler')
            store.apply_op(operation)
            touched.append(command_handler(operation))
        else:
            touched.append(store.apply_op(operation))
    return touched[0] if len(touched) == 1 else touched


def edit_ui_binding(store, ui_id, raw_value, port='value', actor='user',
                    transaction=None):
    sources = []
    for _relation, relation_sources_, targets in _matching_relations(store, ui_id, target_port=port):
        if any(endpoint['node_id'] == ui_id and endpoint.get('port_id') == port
               for endpoint in targets):
            sources.extend(endpoint['node_id'] for endpoint in relation_sources_)
    if len(sources) != 1 or store.nodes[sources[0]]['kind'] != 'param':
        raise ValueError('editable UI node %s must bind to one parameter node' % ui_id)
    floor = store.nodes[sources[0]]['body'].get('floor', {})
    if floor.get('op') != 'value':
        raise ValueError('editable binding source %s is not a value parameter' % sources[0])
    current = store.pull(sources[0])
    path = ['body', 'floor', 'value']
    if port.startswith('value.'):
        key = port.split('.', 1)[1]
        if not isinstance(current, dict) or key not in current:
            raise ValueError('structured binding %s has no field %r' % (sources[0], key))
        current = current[key]
        path.append(key)
    value = raw_value
    if isinstance(current, bool):
        value = str(raw_value).lower() in ('1', 'true', 'yes', 'on')
    elif isinstance(current, (dict, list)):
        try:
            value = json.loads(str(raw_value))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError('structured UI binding requires JSON') from exc
        if not isinstance(value, type(current)):
            raise ValueError('structured UI binding must preserve its value type')
    elif isinstance(current, int) and not isinstance(current, bool):
        value = int(raw_value)
    elif isinstance(current, float):
        value = float(raw_value)
    store.edit(sources[0], path, value, actor=actor, transaction=transaction)
    return sources[0]


CLIENT_SCRIPT = """
(() => {
  const headers = {'Content-Type':'application/json'};
  const csrfToken = document.querySelector('meta[name="archhub-csrf"]')?.content;
  if (csrfToken) headers['X-ArchHub-CSRF'] = csrfToken;
  let drag = null;
  let pan = null;
  let marquee = null;
  let wireDrag = null;
  let spaceDown = false;
  let motionFrame = 0;
  let pendingMotion = null;
  let viewportCommit = 0;
  let mutationQueue = Promise.resolve();

  function claimPointer(owner, pointerId) {
    const active=window.__archhubPointerOwner;
    if (active && (active.owner !== owner || active.pointerId !== pointerId)) {
      return false;
    }
    window.__archhubPointerOwner={owner,pointerId};
    return true;
  }
  function releasePointer(owner, pointerId) {
    const active=window.__archhubPointerOwner;
    if (active?.owner === owner && active.pointerId === pointerId) {
      window.__archhubPointerOwner=null;
    }
  }
  function interactionPolicy(projection=null) {
    const policy=projection?.interaction_policy
      || window.__archhubInteractionPolicy || {};
    return {
      zoom_min:Number(policy.zoom_min ?? .25),
      zoom_max:Number(policy.zoom_max ?? 2.5),
      zoom_fit_max:Number(policy.zoom_fit_max ?? 1.25),
      zoom_toolbar_step:Number(policy.zoom_toolbar_step ?? .1),
      wheel_sensitivity:Number(policy.wheel_sensitivity ?? .0015),
      wheel_delta_cap:Number(policy.wheel_delta_cap ?? 800),
      drag_threshold_px:Number(policy.drag_threshold_px ?? 3),
      viewport_commit_debounce_ms:Number(
        policy.viewport_commit_debounce_ms ?? 140),
      gesture_suppression_ms:Number(policy.gesture_suppression_ms ?? 300),
    };
  }
  function clampZoom(value, policy=interactionPolicy()) {
    const min=Number.isFinite(policy.zoom_min) && policy.zoom_min > 0
      ? policy.zoom_min : .25;
    const max=Number.isFinite(policy.zoom_max) && policy.zoom_max >= min
      ? policy.zoom_max : 2.5;
    return Math.max(min,Math.min(max,value));
  }

  function root() { return document.querySelector('.archhub-app'); }
  function byNode(scope, id) {
    return Array.from(scope.querySelectorAll('[data-node]')).find(
      element => element.dataset.node === id) || null;
  }
  function captureView() {
    const canvas = document.querySelector('.canvas');
    const active = document.activeElement && document.activeElement.dataset
      ? document.activeElement.dataset.node : '';
    return {active, start:document.activeElement?.selectionStart,
            end:document.activeElement?.selectionEnd,
            left:canvas?.scrollLeft || 0, top:canvas?.scrollTop || 0};
  }
  function restoreView(view) {
    const canvas = document.querySelector('.canvas');
    if (canvas) { canvas.scrollLeft=view.left; canvas.scrollTop=view.top; }
    if (!view.active) return;
    const active = byNode(document, view.active);
    if (!active) return;
    active.focus({preventScroll:true});
    if (typeof active.setSelectionRange === 'function' && view.start != null) {
      active.setSelectionRange(view.start, view.end);
    }
  }
  function syncAttributes(current, next) {
    const focused = current === document.activeElement;
    for (const attribute of Array.from(current.attributes)) {
      if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
    }
    for (const attribute of Array.from(next.attributes)) {
      if (!(focused && attribute.name === 'value')) {
        current.setAttribute(attribute.name, attribute.value);
      }
    }
    if (current instanceof HTMLInputElement && !focused) {
      current.value = next.value;
      current.checked = next.checked;
    }
  }
  function reconcileProjection(markup) {
    const parsed = new DOMParser().parseFromString(markup, 'text/html');
    const currentRoot = root();
    const nextRoot = parsed.querySelector('.archhub-app');
    if (!currentRoot || !nextRoot) return;
    const view = captureView();
    const currentElements = Array.from(currentRoot.querySelectorAll('[data-node]'));
    const nextElements = Array.from(nextRoot.querySelectorAll('[data-node]'));
    const currentById = new Map(currentElements.map(
      element => [element.dataset.node, element]));
    const nextById = new Map(nextElements.map(
      element => [element.dataset.node, element]));
    const structural = currentById.size !== nextById.size ||
      Array.from(nextById.keys()).some(id => !currentById.has(id));
    if (structural) {
      currentRoot.replaceWith(nextRoot);
      restoreView(view);
      redrawCables();
      window.__archhubUniversalRefresh?.();
      return;
    }
    syncAttributes(currentRoot, nextRoot);
    for (const [id, next] of nextById) {
      const current = currentById.get(id);
      if (!current || !next || current.tagName !== next.tagName) continue;
      syncAttributes(current, next);
      if (!next.querySelector('[data-node]') && !(current instanceof HTMLInputElement)) {
        current.textContent = next.textContent;
      }
    }
    restoreView(view);
    redrawCables();
    window.__archhubUniversalRefresh?.();
  }
  async function performRequest(path, payload, reconcile=true) {
    const app = root();
    if (app) app.dataset.sync = 'working';
    payload.projection = reconcile;
    payload.transaction = payload.transaction || crypto.randomUUID();
    try {
      const response = await fetch(path, {method:'POST', headers,
        body:JSON.stringify(payload)});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'Graph mutation failed');
      if (reconcile && result.projection) reconcileProjection(result.projection);
      const current = root();
      if (current) {
        current.dataset.sync = 'settled';
        setTimeout(() => { if (root()) root().dataset.sync = ''; }, 380);
      }
      return result;
    } catch (error) {
      const current = root();
      if (current) current.dataset.sync = 'failed';
      console.error(error);
      throw error;
    }
  }
  function request(path, payload, reconcile=true) {
    const execute = () => performRequest(path, payload, reconcile);
    const result = mutationQueue.then(execute, execute);
    mutationQueue = result.catch(() => undefined);
    return result;
  }
  function actionPayload(target, transaction, event='activate') {
    const payload = {ui_id:target.dataset.node, event};
    if (transaction) payload.transaction = transaction;
    if (target.dataset.inputNode) {
      const input = byNode(document, target.dataset.inputNode);
      if (!input) throw new Error('Command input node is not rendered');
      payload.input_value = input.value;
    }
    return payload;
  }
  async function runAction(target, reconcile=true, transaction='', event='activate') {
    return request('/api/activate', actionPayload(target, transaction, event), reconcile);
  }
  async function writeBinding(target, port, value, reconcile=true, transaction='') {
    return request('/api/edit', {ui_id:target.dataset.node, port,
      value:String(value), transaction}, reconcile);
  }
  async function runBatch(operations, transaction='', reconcile=true) {
    return request('/api/batch', {operations, transaction}, reconcile);
  }
  async function runBatches(operations, transaction='', reconcile=false) {
    let result = null;
    for (let index=0; index<operations.length; index+=32) {
      result = await runBatch(operations.slice(index,index+32), transaction,
                              reconcile && index+32 >= operations.length);
    }
    return result;
  }
  function cardPoint(card, output) {
    return {x:(parseFloat(card.style.left)||0)+(output ? 204 : 0),
            y:(parseFloat(card.style.top)||0)+67};
  }
  function cablePath(a, b) {
    return 'M '+a.x+' '+a.y+' C '+(a.x+80)+' '+a.y+', '+
      (b.x-80)+' '+b.y+', '+b.x+' '+b.y;
  }
  function redrawCables() {
    document.querySelectorAll(
      '.canvas[data-pan-surface="true"]:not([data-universal="true"])'
    ).forEach(surface => {
      const zoom=parseFloat(surface.dataset.zoom)||1;
      surface.style.setProperty('--grid-size',(20*zoom)+'px');
      surface.style.setProperty('--grid-x',(parseFloat(surface.dataset.panX)||0)+'px');
      surface.style.setProperty('--grid-y',(parseFloat(surface.dataset.panY)||0)+'px');
      const cards = new Map(Array.from(
        surface.querySelectorAll('[data-graph-node]')
      ).map(card => [card.dataset.graphNode, card]));
      surface.querySelectorAll(
        '.wire-line[data-source-node][data-target-node]'
      ).forEach(path => {
        const source = cards.get(path.dataset.sourceNode);
        const target = cards.get(path.dataset.targetNode);
        if (source && target) path.setAttribute('d', cablePath(
          cardPoint(source, true), cardPoint(target, false)));
      });
    });
  }
  function scheduleMotion(callback) {
    pendingMotion = callback;
    if (motionFrame) return;
    motionFrame = requestAnimationFrame(() => {
      motionFrame = 0;
      const run = pendingMotion;
      pendingMotion = null;
      if (run) run();
    });
  }
  function flushMotion() {
    if (motionFrame) cancelAnimationFrame(motionFrame);
    motionFrame = 0;
    const run = pendingMotion;
    pendingMotion = null;
    if (run) run();
  }
  function canvasPoint(event, stage) {
    const rect = stage.getBoundingClientRect();
    const surface = stage.closest('.canvas');
    const zoom = parseFloat(surface?.dataset.zoom)||1;
    return {x:(event.clientX-rect.left)/zoom, y:(event.clientY-rect.top)/zoom};
  }
  function clearWireDrag() {
    document.querySelectorAll('.wire-target-ready').forEach(
      element => element.classList.remove('wire-target-ready'));
    wireDrag?.preview?.remove();
    wireDrag = null;
  }
  function selectedIds(surface=document.querySelector('.canvas')) {
    if (!surface) return new Set();
    try {
      const value = JSON.parse(surface.dataset.selection || '[]');
      if (Array.isArray(value)) return new Set(value.map(String));
    } catch (_) {}
    return new Set(Array.from(surface.querySelectorAll(
      '.graph-node[data-selected="True"]')).map(card => card.dataset.graphNode));
  }
  function paintSelection(surface, ids) {
    const ordered = Array.from(ids);
    surface.dataset.selection = JSON.stringify(ordered);
    surface.querySelectorAll('.graph-node[data-graph-node]').forEach(card => {
      card.dataset.selected = ids.has(card.dataset.graphNode) ? 'True' : 'False';
    });
    const value = surface.querySelector('.canvas-selection-value');
    if (value) value.textContent = ordered.length ? ordered.length+' selected' : '0 selected';
  }
  function mergeSelection(base, hits, event) {
    const result = new Set(base);
    if (event.shiftKey) {
      hits.forEach(id => result.delete(id));
      return result;
    }
    if (event.ctrlKey || event.metaKey) {
      hits.forEach(id => result.add(id));
      return result;
    }
    return new Set(hits);
  }
  function intersects(a, b) {
    return a.left <= b.right && a.right >= b.left &&
      a.top <= b.bottom && a.bottom >= b.top;
  }
  function marqueeHits(surface, box, crossing) {
    const hits = new Set();
    surface.querySelectorAll('.graph-node[data-graph-node]').forEach(card => {
      if (card.dataset.visible === 'False' || !card.getClientRects().length) return;
      const rect = card.getBoundingClientRect();
      const hit = crossing ? intersects(box, rect) :
        rect.left >= box.left && rect.right <= box.right &&
        rect.top >= box.top && rect.bottom <= box.bottom;
      if (hit) hits.add(card.dataset.graphNode);
    });
    return hits;
  }
  function setLocalFocus(nodeId) {
    document.querySelectorAll('.graph-node[data-graph-node]').forEach(card => {
      card.dataset.focused = card.dataset.graphNode === nodeId ? 'True' : 'False';
    });
    document.querySelectorAll('.wire-line[data-relation]').forEach(path => {
      path.dataset.focused = path.dataset.relation === nodeId ? 'True' : 'False';
    });
    document.querySelectorAll('.inspector-panel[data-inspected-node]').forEach(panel => {
      if (panel.closest('.inspector')?.dataset.universal === 'true') return;
      panel.dataset.visible = panel.dataset.inspectedNode === nodeId ? 'True' : 'False';
    });
  }
  function applyViewport(surface, x, y, zoom) {
    const stage = surface.querySelector('.canvas-stage');
    if (!stage) return;
    surface.dataset.panX = String(x);
    surface.dataset.panY = String(y);
    surface.dataset.zoom = String(zoom);
    stage.style.transform = 'translate('+x+'px,'+y+'px) scale('+zoom+')';
    surface.style.setProperty('--grid-size', (20*zoom)+'px');
    surface.style.setProperty('--grid-x', x+'px');
    surface.style.setProperty('--grid-y', y+'px');
  }
  function queueViewportCommit(surface) {
    clearTimeout(viewportCommit);
    const policy=interactionPolicy();
    viewportCommit = setTimeout(() => {
      if (surface.dataset.universal === 'true') {
        window.__archhubUniversalCommit?.({viewport:{
          pan_x:parseFloat(surface.dataset.panX)||0,
          pan_y:parseFloat(surface.dataset.panY)||0,
          zoom:parseFloat(surface.dataset.zoom)||1,
        }});
        return;
      }
      const transaction = crypto.randomUUID();
      runBatch([
        {kind:'edit', ui_id:surface.dataset.node, port:'view.pan_x',
         value:surface.dataset.panX},
        {kind:'edit', ui_id:surface.dataset.node, port:'view.pan_y',
         value:surface.dataset.panY},
        {kind:'edit', ui_id:surface.dataset.node, port:'view.zoom',
         value:surface.dataset.zoom},
      ], transaction, false).catch(error => console.error(error));
    }, Number.isFinite(policy.viewport_commit_debounce_ms)
      ? policy.viewport_commit_debounce_ms : 140);
  }
  function showMarquee(currentX, currentY) {
    if (!marquee) return;
    const surface = marquee.surface;
    const offsetParent = marquee.box.offsetParent;
    const containingRect = offsetParent?.getBoundingClientRect?.()
      || surface.getBoundingClientRect();
    const scrollLeft = offsetParent === surface ? surface.scrollLeft || 0
      : offsetParent?.scrollLeft || 0;
    const scrollTop = offsetParent === surface ? surface.scrollTop || 0
      : offsetParent?.scrollTop || 0;
    const left = Math.min(marquee.startX, currentX);
    const right = Math.max(marquee.startX, currentX);
    const top = Math.min(marquee.startY, currentY);
    const bottom = Math.max(marquee.startY, currentY);
    const threshold=interactionPolicy().drag_threshold_px;
    marquee.moved = marquee.moved ||
      Math.abs(currentX-marquee.startX) > threshold ||
      Math.abs(currentY-marquee.startY) > threshold;
    const crossing = currentX < marquee.startX;
    const box = marquee.box;
    box.style.display = 'block';
    box.style.left = (left-containingRect.left+scrollLeft)+'px';
    box.style.top = (top-containingRect.top+scrollTop)+'px';
    box.style.width = Math.max(1,right-left)+'px';
    box.style.height = Math.max(1,bottom-top)+'px';
    box.dataset.mode = crossing ? 'crossing' : 'window';
    const hitBox = {left,right,top,bottom};
    marquee.current = mergeSelection(
      marquee.base, marqueeHits(surface, hitBox, crossing), marquee.event);
    paintSelection(surface, marquee.current);
  }
  function hideMarquee() {
    const box = document.querySelector('.canvas .selection-box');
    if (box) {
      box.style.display = 'none';
      box.style.width = '0px';
      box.style.height = '0px';
    }
  }

  document.addEventListener('click', async event => {
    const download = event.target.closest('[data-download]');
    if (download) {
      event.preventDefault();
      location.href = '/api/export?node_id=' + encodeURIComponent(download.dataset.download);
      return;
    }
    const relation = event.target.closest('.wire-line[data-relation][data-action="true"]');
    if (relation) {
      event.preventDefault();
      event.stopPropagation();
      setLocalFocus(relation.dataset.relation);
      await runAction(relation, false);
      return;
    }
    const target = event.target.closest('[data-action="true"]');
    if (!target) return;
    if (window.__archhubDragged || Date.now() < (window.__archhubGestureUntil||0)) {
      window.__archhubDragged = false;
      event.preventDefault();
      return;
    }
    event.preventDefault();
    await runAction(target);
    if (target.dataset.navigate) location.href = target.dataset.navigate;
  });
  document.addEventListener('dblclick', async event => {
    const target = event.target.closest('[data-double-action="true"]');
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();
    await runAction(target, true, crypto.randomUUID(), 'double_activate');
  });
  document.addEventListener('change', async event => {
    const target = event.target.closest('[data-edit="true"]');
    if (!target) return;
    const value = target.type === 'checkbox' ? String(target.checked) : target.value;
    await writeBinding(target, target.dataset.editPort || 'value', value);
  });
  document.addEventListener('pointerdown', event => {
    if (event.target.closest('.canvas[data-universal="true"]')) return;
    const surface = event.target.closest('.canvas[data-pan-surface="true"]');
    const panGesture = surface && (event.button === 1 ||
      (event.button === 0 && spaceDown));
    if (panGesture && !event.target.closest('.canvas-toolbar,.composer')) {
      const stage = surface.querySelector('.canvas-stage');
      if (!stage) return;
      if (!claimPointer('pan',event.pointerId)) return;
      event.preventDefault();
      pan = {surface, stage, x:event.clientX, y:event.clientY,
             left:parseFloat(surface.dataset.panX)||0,
             top:parseFloat(surface.dataset.panY)||0,
             zoom:parseFloat(surface.dataset.zoom)||1,
             pointerId:event.pointerId};
      surface.classList.add('is-panning');
      surface.setPointerCapture?.(event.pointerId);
      return;
    }
    const output = event.target.closest('.node-port-out[data-action="true"]');
    if (output && event.button === 0) {
      const stage = output.closest('.canvas-stage');
      const layer = stage?.querySelector('.wire-layer');
      const card = output.closest('[data-graph-node]');
      if (!stage || !layer || !card) return;
      if (!claimPointer('legacy-wire',event.pointerId)) return;
      event.preventDefault();
      event.stopPropagation();
      const preview = document.createElementNS('http://www.w3.org/2000/svg','path');
      preview.setAttribute('class','wire-preview');
      layer.appendChild(preview);
      wireDrag = {output, stage, card, preview, pointerId:event.pointerId};
      const point = canvasPoint(event, stage);
      preview.setAttribute('d', cablePath(cardPoint(card, true), point));
      output.setPointerCapture?.(event.pointerId);
      return;
    }
    if (event.target.closest(
      '.wire-line[data-relation],[data-universal-rewire-incidence]')) return;
    if (event.target.closest('button,input,[data-edit="true"]')) return;
    const target = event.target.closest('[data-draggable="true"]');
    if (target && event.button === 0) {
      const canvas = target.closest('.canvas');
      if (!canvas) return;
      if (!claimPointer('node',event.pointerId)) return;
      event.preventDefault();
      const nodeId = target.dataset.graphNode;
      const base = selectedIds(canvas);
      const previousFocus=canvas.querySelector(
        '.graph-node[data-focused="True"]')?.dataset.graphNode;
      let next;
      if (event.shiftKey) {
        next = new Set(base);
        next.delete(nodeId);
      } else if (event.ctrlKey || event.metaKey) {
        next = new Set(base);
        next.add(nodeId);
      } else {
        next = base.has(nodeId) ? new Set(base) : new Set([nodeId]);
      }
      const focusId = next.has(nodeId) ? nodeId : Array.from(next).at(-1);
      paintSelection(canvas, next);
      setLocalFocus(focusId);
      const targets = next.has(nodeId)
        ? Array.from(canvas.querySelectorAll('.graph-node[data-graph-node]'))
          .filter(card => next.has(card.dataset.graphNode)) : [];
      const origins = targets.map(card => ({card,
        left:parseFloat(card.style.left)||0,
        top:parseFloat(card.style.top)||0}));
      drag = {target, canvas, nodeId, focusId, previousFocus, base,
              cardUi:target.dataset.node,
              x:event.clientX, y:event.clientY,
              zoom:parseFloat(canvas.dataset.zoom)||1, moved:false,
              selection:next, origins, pointerId:event.pointerId};
      target.setPointerCapture?.(event.pointerId);
      return;
    }
    if (!surface || event.button !== 0 ||
        event.target.closest('.canvas-toolbar,.composer')) return;
    const box = surface.querySelector('.selection-box');
    if (!box) return;
    if (!claimPointer('marquee',event.pointerId)) return;
    event.preventDefault();
    const base = selectedIds(surface);
    marquee = {surface, box, startX:event.clientX, startY:event.clientY,
                base, current:new Set(base), moved:false,
                previousFocus:surface.querySelector(
                  '.graph-node[data-focused="True"]')?.dataset.graphNode,
                event:{shiftKey:event.shiftKey, ctrlKey:event.ctrlKey,
                       metaKey:event.metaKey}, pointerId:event.pointerId};
    surface.classList.add('is-selecting');
    surface.setPointerCapture?.(event.pointerId);
  });
  document.addEventListener('pointermove', event => {
    const active=window.__archhubPointerOwner;
    if (active && active.pointerId !== event.pointerId) return;
    if (wireDrag) {
      const x=event.clientX,y=event.clientY,current=wireDrag;
      scheduleMotion(() => {
        if (wireDrag !== current) return;
        const point = canvasPoint({clientX:x,clientY:y}, current.stage);
        current.preview.setAttribute('d', cablePath(
          cardPoint(current.card, true), point));
        document.querySelectorAll('.wire-target-ready').forEach(
          element => element.classList.remove('wire-target-ready'));
        document.elementFromPoint(x,y)
          ?.closest('.node-port-in')?.classList.add('wire-target-ready');
      });
    } else if (drag) {
      const x=event.clientX,y=event.clientY,current=drag;
      scheduleMotion(() => {
        if (drag !== current) return;
        const dx=(x-current.x)/current.zoom;
        const dy=(y-current.y)/current.zoom;
        if (Math.abs(dx)+Math.abs(dy) >
            interactionPolicy().drag_threshold_px) current.moved = true;
        if (!current.moved) return;
        current.origins.forEach(origin => {
          origin.card.classList.add('is-moving');
          origin.card.style.left=(origin.left+dx)+'px';
          origin.card.style.top=(origin.top+dy)+'px';
        });
        redrawCables();
      });
    } else if (pan) {
      const x=event.clientX,y=event.clientY,current=pan;
      scheduleMotion(() => {
        if (pan !== current) return;
        applyViewport(current.surface,
          current.left+x-current.x, current.top+y-current.y, current.zoom);
      });
    } else if (marquee) {
      const x=event.clientX,y=event.clientY,current=marquee;
      scheduleMotion(() => {
        if (marquee === current) showMarquee(x,y);
      });
    }
  });
  document.addEventListener('pointerup', async event => {
    flushMotion();
    if (wireDrag) {
      if (wireDrag.pointerId !== event.pointerId) return;
      const current = wireDrag;
      const target = document.elementFromPoint(event.clientX,event.clientY)
        ?.closest('.node-port-in[data-action="true"]');
      clearWireDrag();
      current.output.releasePointerCapture?.(event.pointerId);
      releasePointer('legacy-wire',event.pointerId);
      window.__archhubGestureUntil = Date.now()+
        interactionPolicy().gesture_suppression_ms;
      if (target) {
        const transaction = crypto.randomUUID();
        await runBatch([
          {kind:'activate', ...actionPayload(current.output)},
          {kind:'activate', ...actionPayload(target)},
        ], transaction);
      }
      return;
    }
    if (drag) {
      if (drag.pointerId !== event.pointerId) return;
      const current = drag;
      drag = null;
      current.target.releasePointerCapture?.(event.pointerId);
      releasePointer('node',event.pointerId);
      current.origins.forEach(origin => origin.card.classList.remove('is-moving'));
      window.__archhubDragged = current.moved;
      window.__archhubGestureUntil = Date.now()+
        interactionPolicy().gesture_suppression_ms;
      if (current.canvas.dataset.universal === 'true') {
        const positions = {};
        if (current.moved) current.origins.forEach(origin => {
          positions[origin.card.dataset.graphNode] = {
            x:parseFloat(origin.card.style.left),
            y:parseFloat(origin.card.style.top),
          };
        });
        const payload = {
          roots:Array.from(current.selection), focus:current.focusId,
        };
        if (current.moved) payload.positions=positions;
        await window.__archhubUniversalCommit?.(payload);
        return;
      }
      const transaction = crypto.randomUUID();
      const operations = [
        {kind:'activate', ui_id:current.cardUi},
        {kind:'edit', ui_id:current.canvas.dataset.node, port:'view.selection',
         value:JSON.stringify(Array.from(current.selection))},
      ];
      if (current.moved) current.origins.forEach(origin => {
        operations.push(
          {kind:'edit', ui_id:origin.card.dataset.node, port:'style.left',
           value:String(parseFloat(origin.card.style.left))},
          {kind:'edit', ui_id:origin.card.dataset.node, port:'style.top',
           value:String(parseFloat(origin.card.style.top))});
      });
      await runBatches(operations, transaction, false);
      return;
    }
    if (marquee) {
      if (marquee.pointerId !== event.pointerId) return;
      const current = marquee;
      marquee = null;
      current.surface.releasePointerCapture?.(event.pointerId);
      releasePointer('marquee',event.pointerId);
      current.surface.classList.remove('is-selecting');
      if (!current.moved) {
        current.current = (current.event.shiftKey || current.event.ctrlKey ||
          current.event.metaKey) ? new Set(current.base) : new Set();
        paintSelection(current.surface, current.current);
      }
      hideMarquee();
      window.__archhubGestureUntil = Date.now()+
        interactionPolicy().gesture_suppression_ms;
      if (current.surface.dataset.universal === 'true') {
        const roots = Array.from(current.current);
        await window.__archhubUniversalCommit?.({
          roots, focus:roots.length ? roots[roots.length-1] : undefined,
        });
        return;
      }
      await writeBinding(current.surface, 'view.selection',
        JSON.stringify(Array.from(current.current)), false, crypto.randomUUID());
      return;
    }
    if (pan) {
      if (pan.pointerId !== event.pointerId) return;
      const current = pan;
      pan = null;
      current.surface.releasePointerCapture?.(event.pointerId);
      releasePointer('pan',event.pointerId);
      current.surface.classList.remove('is-panning');
      const x=current.left+event.clientX-current.x;
      const y=current.top+event.clientY-current.y;
      applyViewport(current.surface,x,y,current.zoom);
      if (current.surface.dataset.universal === 'true') {
        await window.__archhubUniversalCommit?.({viewport:{
          pan_x:x, pan_y:y, zoom:current.zoom,
        }});
        return;
      }
      const transaction = crypto.randomUUID();
      await runBatch([
        {kind:'edit', ui_id:current.surface.dataset.node, port:'view.pan_x',
         value:String(x)},
        {kind:'edit', ui_id:current.surface.dataset.node, port:'view.pan_y',
         value:String(y)},
      ], transaction, false);
    }
  });
  document.addEventListener('pointercancel', event => {
    flushMotion();
    if (wireDrag?.pointerId === event.pointerId) {
      const current=wireDrag;
      clearWireDrag();
      releasePointer('legacy-wire',event.pointerId);
      current.output.releasePointerCapture?.(event.pointerId);
    }
    if (drag?.pointerId === event.pointerId) {
      drag.origins.forEach(origin => {
        origin.card.style.left=origin.left+'px';
        origin.card.style.top=origin.top+'px';
        origin.card.classList.remove('is-moving');
      });
      paintSelection(drag.canvas,drag.base);
      setLocalFocus(drag.previousFocus);
      drag.target.releasePointerCapture?.(event.pointerId);
      releasePointer('node',event.pointerId);
      redrawCables();
      drag=null;
    }
    if (pan?.pointerId === event.pointerId) {
      applyViewport(pan.surface,pan.left,pan.top,pan.zoom);
      pan.surface.classList.remove('is-panning');
      pan.surface.releasePointerCapture?.(event.pointerId);
      releasePointer('pan',event.pointerId);
      pan=null;
    }
    if (marquee?.pointerId === event.pointerId) {
      paintSelection(marquee.surface,marquee.base);
      setLocalFocus(marquee.previousFocus);
      marquee.surface.classList.remove('is-selecting');
      marquee.surface.releasePointerCapture?.(event.pointerId);
      releasePointer('marquee',event.pointerId);
      marquee=null;
    }
    hideMarquee();
  });
  document.addEventListener('wheel', event => {
    const surface = event.target.closest('.canvas[data-pan-surface="true"]');
    if (!surface || surface.dataset.universal === 'true'
        || event.target.closest('.canvas-toolbar,.composer')) return;
    event.preventDefault();
    const rect = surface.getBoundingClientRect();
    const oldZoom = parseFloat(surface.dataset.zoom)||1;
    const oldX = parseFloat(surface.dataset.panX)||0;
    const oldY = parseFloat(surface.dataset.panY)||0;
    const policy=interactionPolicy();
    const rawDelta = event.deltaY * (event.deltaMode === 1 ? 16 :
      event.deltaMode === 2 ? rect.height : 1);
    const cap=Number.isFinite(policy.wheel_delta_cap)
      ? policy.wheel_delta_cap : 800;
    const delta=Math.max(-cap,Math.min(cap,rawDelta));
    const sensitivity=Number.isFinite(policy.wheel_sensitivity)
      ? policy.wheel_sensitivity : .0015;
    const zoom = clampZoom(oldZoom*Math.exp(-delta*sensitivity),policy);
    const cursorX = event.clientX-rect.left;
    const cursorY = event.clientY-rect.top;
    const worldX = (cursorX-oldX)/oldZoom;
    const worldY = (cursorY-oldY)/oldZoom;
    applyViewport(surface,cursorX-worldX*zoom,cursorY-worldY*zoom,zoom);
    queueViewportCommit(surface);
  }, {passive:false});
  document.addEventListener('keydown', async event => {
    if (document.querySelector('.canvas[data-universal="true"]')) return;
    const editing = document.activeElement?.matches?.(
      'input,textarea,select,[contenteditable="true"]');
    const focusedCard=document.activeElement?.matches?.(
      '[data-universal-root][role="button"]');
    if (event.code === 'Space' && !editing && !focusedCard) {
      spaceDown = true;
      event.preventDefault();
      return;
    }
    if (event.key === 'Escape' && !editing) {
      event.preventDefault();
      const hadGesture=Boolean(drag || pan || marquee || wireDrag ||
        window.__archhubPointerOwner?.owner === 'universal-wire');
      if (wireDrag) {
        const current=wireDrag;
        clearWireDrag();
        current.output.releasePointerCapture?.(current.pointerId);
        releasePointer('legacy-wire',current.pointerId);
      }
      if (drag) {
        drag.origins.forEach(origin => {
          origin.card.style.left=origin.left+'px';
          origin.card.style.top=origin.top+'px';
          origin.card.classList.remove('is-moving');
        });
        paintSelection(drag.canvas,drag.base);
        setLocalFocus(drag.previousFocus);
        drag.target.releasePointerCapture?.(drag.pointerId);
        releasePointer('node',drag.pointerId);
        redrawCables();
      }
      if (pan) {
        applyViewport(pan.surface,pan.left,pan.top,pan.zoom);
        pan.surface.classList.remove('is-panning');
        pan.surface.releasePointerCapture?.(pan.pointerId);
        releasePointer('pan',pan.pointerId);
      }
      if (marquee) {
        paintSelection(marquee.surface,marquee.base);
        setLocalFocus(marquee.previousFocus);
        marquee.surface.classList.remove('is-selecting');
        marquee.surface.releasePointerCapture?.(marquee.pointerId);
        releasePointer('marquee',marquee.pointerId);
      }
      hideMarquee();
      drag=null; pan=null; marquee=null; wireDrag=null;
      if (hadGesture) return;
      const canvas=document.querySelector('.canvas');
      if (canvas) {
        paintSelection(canvas,new Set());
        if (canvas.dataset.universal === 'true') {
          await window.__archhubUniversalCommit?.({roots:[]});
          return;
        }
        await writeBinding(canvas,'view.selection','[]',false,crypto.randomUUID());
      }
      return;
    }
    if (!(event.ctrlKey || event.metaKey) || event.altKey || editing) return;
    const redo = (event.shiftKey && event.key.toLowerCase() === 'z') ||
      (!event.shiftKey && event.key.toLowerCase() === 'y');
    const undo = !event.shiftKey && event.key.toLowerCase() === 'z';
    if (!undo && !redo) return;
    const universal = document.querySelector('.canvas[data-universal="true"]');
    const control = universal
      ? document.querySelector(
          `[data-universal-history="${redo ? 'redo' : 'undo'}"]`)
      : document.querySelector(redo ? '.history-redo' : '.history-undo');
    if (!control) return;
    event.preventDefault();
    if (universal) control.click();
    else await runAction(control);
  });
  document.addEventListener('keyup', event => {
    if (event.code === 'Space') spaceDown = false;
  });
  window.addEventListener('blur', () => { spaceDown = false; });
  document.querySelectorAll(
    '.canvas[data-pan-surface="true"]:not([data-universal="true"])'
  ).forEach(surface => applyViewport(surface,parseFloat(surface.dataset.panX)||0,
    parseFloat(surface.dataset.panY)||0,parseFloat(surface.dataset.zoom)||1));
  redrawCables();
})();
"""


UNIVERSAL_CANVAS_SCRIPT = r"""
(() => {
  let lastProjection = null;
  let acceptedProjection = null;
  let refreshPending = null;
  let mutationTail = Promise.resolve();
  const skipUniversalMutation=Symbol('skip-universal-mutation');
  let pendingWire = null;
  let pendingRoleWire = null;
  let pendingConnectionRewire = null;
  let canvasGesture = null;
  let pendingCanvasSelectionCommit = null;
  let canvasMotionFrame = 0;
  let pendingCanvasMotion = null;
  let canvasSpaceDown = false;
  let viewportCommitTimer = 0;
  let canvasElementIndex = null;
  let wireTargetReadyElements = new Set();
  let projectionReconciliationDepth = 0;

  function element(tag, className='', text='') {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== '') node.textContent = text;
    return node;
  }
  function svgElement(tag, attrs={}) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([name,value]) => node.setAttribute(name,String(value)));
    return node;
  }
  const admittedIconTags=new Set([
    'path','circle','line','rect','polyline','polygon',
  ]);
  const admittedIconAttributes=new Set([
    'd','cx','cy','r','x','y','width','height','rx','ry',
    'x1','x2','y1','y2','points',
  ]);
  const controlCapabilities=Object.freeze({
    scope:'app:device-capability:scope',
    viewport:'app:device-capability:viewport',
    composition:'app:device-capability:composition',
    history:'app:device-capability:history',
  });
  function interactionPolicy(projection=lastProjection) {
    const policy=projection?.interaction_policy
      || window.__archhubInteractionPolicy || {};
    return {
      zoom_min:Number(policy.zoom_min ?? .25),
      zoom_max:Number(policy.zoom_max ?? 2.5),
      zoom_fit_max:Number(policy.zoom_fit_max ?? 1.25),
      zoom_toolbar_step:Number(policy.zoom_toolbar_step ?? .1),
      wheel_sensitivity:Number(policy.wheel_sensitivity ?? .0015),
      wheel_delta_cap:Number(policy.wheel_delta_cap ?? 800),
      drag_threshold_px:Number(policy.drag_threshold_px ?? 3),
      viewport_commit_debounce_ms:Number(
        policy.viewport_commit_debounce_ms ?? 140),
      gesture_suppression_ms:Number(policy.gesture_suppression_ms ?? 300),
    };
  }
  function clampZoom(value, policy=interactionPolicy()) {
    const min=Number.isFinite(policy.zoom_min) && policy.zoom_min > 0
      ? policy.zoom_min : .25;
    const max=Number.isFinite(policy.zoom_max) && policy.zoom_max >= min
      ? policy.zoom_max : 2.5;
    return Math.max(min,Math.min(max,value));
  }
  function controlPresentation(owner,projection=lastProjection) {
    return projection?.configuration?.design_system?.control_catalog?.controls
      ?.find(control => control.owner === owner) || null;
  }
  function iconPresentation(root,projection=lastProjection) {
    const icons=projection?.configuration?.design_system?.icon_catalog?.icons || {};
    return Object.values(icons).find(icon => icon.root === root) || null;
  }
  function graphIcon(iconRoot,projection=lastProjection) {
    const icon=iconPresentation(iconRoot,projection);
    if (!icon || icon.view_box !== '0 0 24 24' || !icon.primitives?.length) {
      throw new Error(`Projected icon is missing or invalid: ${iconRoot}`);
    }
    const svg=svgElement('svg',{
      viewBox:icon.view_box,width:16,height:16,fill:'none',
      stroke:'currentColor','stroke-width':2,'stroke-linecap':'round',
      'stroke-linejoin':'round','aria-hidden':'true',focusable:'false',
    });
    svg.classList.add('graph-icon');
    svg.dataset.universalIconRoot=icon.root;
    icon.primitives.forEach(primitive => {
      if (!admittedIconTags.has(primitive.tag)) {
        throw new Error(`Projected icon tag is not admitted: ${primitive.tag}`);
      }
      const shape=svgElement(primitive.tag);
      Object.entries(primitive.attributes || {}).forEach(([name,value]) => {
        if (!admittedIconAttributes.has(name)) {
          throw new Error(`Projected icon attribute is not admitted: ${name}`);
        }
        shape.setAttribute(name,String(value));
      });
      svg.append(shape);
    });
    return svg;
  }
  function applyControlPresentation(
    button,owner,{showLabel=false,projection=lastProjection}={}
  ) {
    const control=controlPresentation(owner,projection);
    if (!control) throw new Error(`Projected control is missing: ${owner}`);
    button.dataset.universalControl=owner;
    if (!control.activation?.binding || !control.activation?.capability) {
      throw new Error(`Projected control activation is missing: ${owner}`);
    }
    button.dataset.controlBinding=control.activation.binding;
    button.dataset.controlCapability=control.activation.capability;
    button.title=control.title;
    button.setAttribute('aria-label',control.title);
    button.replaceChildren(graphIcon(control.icon,projection));
    if (showLabel) {
      button.append(element('span','control-label',control.label));
    } else {
      button.classList.add('icon-only');
    }
    return button;
  }
  function zoneControls(zone,projection=lastProjection) {
    return (projection?.configuration?.design_system?.control_catalog?.controls || [])
      .filter(control => control.zone === zone && control.applicable)
      .sort((left,right) => left.order-right.order);
  }
  function projectedControlButton(control,projection=lastProjection) {
    return applyControlPresentation(
      element('button','header-action'),control.owner,{projection});
  }
  async function activateProjectedControl(button) {
    const control=controlPresentation(button.dataset.universalControl);
    if (!control || !control.applicable) {
      throw new Error('Projected control is not currently applicable');
    }
    const activation=control.activation;
    if (activation.binding !== button.dataset.controlBinding) {
      throw new Error('Projected control binding changed before activation');
    }
    const args=activation.arguments || {};
    if (activation.capability === controlCapabilities.viewport) {
      const current=lastProjection.viewport;
      const policy=interactionPolicy();
      const canvas=button.closest('.canvas');
      let next;
      if (args.operation === 'fit') {
        next=fitViewport(lastProjection,canvas);
      } else if (args.operation === 'delta') {
        const amount=Number(args.amount);
        if (!Number.isFinite(amount) || Math.abs(amount) > .5) {
          throw new Error('Viewport delta is not admitted');
        }
        next={
          pan_x:current.pan_x,pan_y:current.pan_y,
          zoom:clampZoom(current.zoom+amount,policy),
        };
      } else {
        throw new Error('Viewport capability arguments are not admitted');
      }
      await commit({viewport:next});
      if (args.operation === 'fit' && canvas) {
        canvas.scrollLeft=0;
        canvas.scrollTop=0;
      }
      return;
    }
    if (!button.dataset.universalInteraction) {
      throw new Error('Projected toolbar Interaction is missing');
    }
    await executeProjectedInteraction(button,topologyDeltaMode);
  }
  function renderStaticControls(projection) {
    // The rail draws what the graph's catalogue declares for its zone,
    // and only the controls that DO something here: Home fits the work,
    // Search focuses the library. Chrome with nothing behind it does not
    // render.
    const rail=document.querySelector('.icon-rail');
    const controls=projection.configuration?.design_system?.control_catalog
      ?.controls || [];
    if (rail && !rail.dataset.railBuilt) {
      const actions={
        'Home':() => {
          const fit=document.querySelector('[data-universal-zoom="fit"]');
          if (fit) fit.click();
        },
        'Search':() => {
          const box=document.querySelector('[data-universal-library-search]');
          if (box) { box.focus(); box.select?.(); }
        },
      };
      controls.filter(control => control.zone === 'application-rail'
          && actions[control.title]).forEach(control => {
        const button=document.createElement('button');
        button.type='button';
        button.className='rail-button';
        button.dataset.universalControl=control.owner;
        button.title=control.title;
        button.setAttribute('aria-label',control.title);
        button.addEventListener('click',actions[control.title]);
        rail.append(button);
      });
      rail.dataset.railBuilt='true';
    }
    document.querySelectorAll('.icon-rail [data-universal-control]').forEach(
      button => applyControlPresentation(
        button,button.dataset.universalControl,{showLabel:true,projection}
      ));
    document.querySelectorAll('.history-undo,.history-redo').forEach(button => {
      button.hidden=true;
      button.setAttribute('aria-hidden','true');
      button.tabIndex=-1;
    });
  }
  function socketPoint(socket, side) {
    const card=socket.closest('[data-universal-root]');
    if (!card) return {x:0,y:0};
    if (socket === card) {
      return {
        x:(parseFloat(card.style.left)||0)+(
          side === 'source' ? card.offsetWidth : 0),
        y:(parseFloat(card.style.top)||0)+card.offsetHeight/2,
      };
    }
    const output=socket.matches(
      '[data-universal-output],[data-universal-relation-incidence]');
    return {
      x:(parseFloat(card.style.left)||0)+(output ? card.offsetWidth : 0),
      y:(parseFloat(card.style.top)||0)+socket.offsetTop+socket.offsetHeight/2,
    };
  }
  function cablePath(source, target) {
    const a=socketPoint(source,'source'),b=socketPoint(target,'target');
    const x1=a.x,y1=a.y,x2=b.x,y2=b.y;
    return `M ${x1} ${y1} C ${x1+80} ${y1}, ${x2-80} ${y2}, ${x2} ${y2}`;
  }
  function invalidateCanvasElementIndex() {
    canvasElementIndex=null;
  }
  function indexCanvasNode(index,card) {
    const root=card?.dataset?.graphNode;
    if (!root) return;
    index.nodes.set(root,card);
    for (const [interfaceRoot,owner] of index.interfaceOwners) {
      if (owner === root) {
        index.interfaceOwners.delete(interfaceRoot);
        index.sockets.delete(interfaceRoot);
      }
    }
    card.querySelectorAll('[data-universal-interface]').forEach(socket => {
      const interfaceRoot=socket.dataset.universalInterface;
      if (!interfaceRoot) return;
      index.sockets.set(interfaceRoot,socket);
      index.interfaceOwners.set(interfaceRoot,root);
    });
  }
  function indexCanvasWire(index,element) {
    const relation=(
      element.dataset?.universalRelation
      || element.dataset?.universalRewireRelation
    );
    const segment=(
      element.dataset?.wireSegment
      || element.dataset?.universalRewireSegment
    );
    if (!relation || !segment) return;
    const key=relation+':'+segment;
    const members=index.wires.get(key) || [];
    if (!members.includes(element)) members.push(element);
    index.wires.set(key,members);
    if (element.dataset.uiKey) {
      index.wireElementsByUiKey.set(element.dataset.uiKey,element);
    }
    for (const root of [
      element.dataset.sourceNode,element.dataset.targetNode,
    ]) {
      if (!root) continue;
      const segments=index.nodeWireSegments.get(root) || new Set();
      segments.add(key);
      index.nodeWireSegments.set(root,segments);
    }
  }
  function wireSegmentsForNodes(canvas,roots) {
    const index=canvasElementIndexFor(canvas);
    const segments=new Set();
    if (!index) return segments;
    roots.forEach(root => {
      index.nodeWireSegments.get(root)?.forEach(segment => segments.add(segment));
    });
    return segments;
  }
  function canvasElementIndexFor(canvas) {
    if (canvasElementIndex?.canvas === canvas) return canvasElementIndex;
    const stage=canvas?.querySelector('.canvas-stage');
    const layer=stage?.querySelector('[data-ui-key="canvas:wires"]');
    if (!stage || !layer) return null;
    canvasElementIndex={
      canvas,stage,layer,nodes:new Map(),sockets:new Map(),
      interfaceOwners:new Map(),wires:new Map(),wireElementsByUiKey:new Map(),
      nodeWireSegments:new Map(),
    };
    stage.querySelectorAll(':scope > [data-graph-node]').forEach(card => {
      indexCanvasNode(canvasElementIndex,card);
    });
    Array.from(layer.children).forEach(element => {
      indexCanvasWire(canvasElementIndex,element);
    });
    return canvasElementIndex;
  }
  const interactionDeltaMode='interaction-delta-v1';
  const topologyDeltaMode='topology-delta-v1';
  const receiptMode='receipt-v1';
  const interactionDeltaFields=[
    'revision','selected','selection','selected_title','focus','obligations',
    'authorization','catalog','scope','authoring','inspector','properties',
    'selected_relation',
    'selected_interface','selected_interfaces','viewport',
    'selected_definition','selected_assembly','physical',
    'interaction_projection','toolbar_descriptor','canvas_heading_descriptor',
    'canvas_signature',
  ];
  function mergeProjectionDelta(result,baseProjection=lastProjection) {
    const mode=result?.projection_mode;
    if (mode !== interactionDeltaMode && mode !== topologyDeltaMode) return result;
    if (!baseProjection || result.base_revision !== baseProjection.revision) {
      throw new Error('Projection delta does not match the visible revision');
    }
    if (!result.control_state?.controls) {
      throw new Error('Projection delta omitted graph control state');
    }
    if (!result.configuration_state
      || typeof result.configuration_state !== 'object') {
      throw new Error('Projection delta omitted mutable configuration state');
    }
    const merged={...baseProjection};
    // The catalogue and authorization block travel only when they changed
    // (topology deltas) or never (interaction deltas): absent means "what
    // you hold still stands", not "cleared". Every other delta field is
    // authoritative as sent -- absent clears it, exactly as before.
    const heldWhenAbsent=new Set(['catalog','authorization']);
    interactionDeltaFields.forEach(field => {
      if (heldWhenAbsent.has(field) && !(field in result)) return;
      merged[field]=result[field];
    });
    merged.configuration={
      ...baseProjection.configuration,
      ...result.configuration_state,
      design_system:{
        ...baseProjection.configuration.design_system,
        control_catalog:result.control_state,
      },
    };
    merged.connection_count=Number(result.connection_count || 0);
    merged.connections=[];
    if (mode === topologyDeltaMode) {
      const patch=result.topology_patch;
      if (patch && typeof patch === 'object') {
        const fields=[
          'node_order','wire_order','remove_nodes','remove_wires',
          'upsert_nodes','upsert_wires',
        ];
        if (fields.some(field => !Array.isArray(patch[field]))) {
          throw new Error('Topology patch shape is invalid');
        }
        const nodes=new Map(baseProjection.nodes.map(node => [node.id,node]));
        const wires=new Map(baseProjection.wires.map(wire => [
          `${wire.id}:${wire.segment}`,wire,
        ]));
        patch.remove_nodes.forEach(root => nodes.delete(root));
        patch.remove_wires.forEach(root => wires.delete(root));
        patch.upsert_nodes.forEach(node => nodes.set(node.id,node));
        patch.upsert_wires.forEach(wire => wires.set(
          `${wire.id}:${wire.segment}`,wire));
        if (
          new Set(patch.node_order).size !== patch.node_order.length
          || new Set(patch.wire_order).size !== patch.wire_order.length
          || patch.node_order.length !== nodes.size
          || patch.wire_order.length !== wires.size
          || patch.node_order.some(root => !nodes.has(root))
          || patch.wire_order.some(root => !wires.has(root))
        ) {
          throw new Error('Topology patch does not exactly cover the graph');
        }
        merged.nodes=patch.node_order.map(root => nodes.get(root));
        merged.wires=patch.wire_order.map(root => wires.get(root));
        Object.defineProperty(merged,'__topologyPatch',{
          value:patch,enumerable:false,configurable:true,
        });
      } else if (
        result.topology_recovery === true
        && Array.isArray(result.nodes)
        && Array.isArray(result.wires)
      ) {
        merged.nodes=result.nodes;
        merged.wires=result.wires;
      } else {
        throw new Error('Topology delta omitted graph topology');
      }
      requireUniqueProjectionIdentities(merged);
      Object.defineProperty(merged,'__topologyValidated',{
        value:true,enumerable:false,configurable:true,
      });
      return merged;
    }
    if (
      !Number.isSafeInteger(result.node_count)
      || !Number.isSafeInteger(result.wire_count)
      || result.node_count !== baseProjection.nodes.length
      || result.wire_count !== baseProjection.wires.length
      || !Array.isArray(result.node_states)
      || !Array.isArray(result.wire_states)
      || !Array.isArray(result.node_patches || [])
      || !Array.isArray(result.wire_patches || [])
    ) {
      throw new Error('Interaction delta changed the projected topology');
    }
    const nodeStates=new Map((result.node_states || []).map(
      state => [state.id,state]));
    const wireStates=new Map((result.wire_states || []).map(
      state => [`${state.id}:${state.segment}`,state]));
    const nodePatches=new Map((result.node_patches || []).map(
      node => [node.id,node]));
    const wirePatches=new Map((result.wire_patches || []).map(
      wire => [`${wire.id}:${wire.segment}`,wire]));
    const nodeRoots=new Set(baseProjection.nodes.map(node => node.id));
    const wireRoots=new Set(baseProjection.wires.map(
      wire => `${wire.id}:${wire.segment}`));
    if (
      nodeStates.size !== (result.node_states || []).length
      || wireStates.size !== (result.wire_states || []).length
      || nodePatches.size !== (result.node_patches || []).length
      || wirePatches.size !== (result.wire_patches || []).length
      || [...nodeStates.keys()].some(root => !nodeRoots.has(root))
      || [...wireStates.keys()].some(root => !wireRoots.has(root))
      || [...nodePatches.keys()].some(root => !nodeRoots.has(root))
      || [...wirePatches.keys()].some(root => !wireRoots.has(root))
    ) {
      throw new Error('Interaction delta changed the projected topology');
    }
    merged.nodes=nodeStates.size || nodePatches.size
      ? baseProjection.nodes.map(node => (
          nodeStates.has(node.id) || nodePatches.has(node.id)
            ? {...node,...nodePatches.get(node.id),...nodeStates.get(node.id)}
            : node
        ))
      : baseProjection.nodes;
    merged.wires=wireStates.size || wirePatches.size
      ? baseProjection.wires.map(wire => {
          const key=`${wire.id}:${wire.segment}`;
          return wireStates.has(key) || wirePatches.has(key)
            ? {...wire,...wirePatches.get(key),...wireStates.get(key)}
            : wire;
        })
      : baseProjection.wires;
    Object.defineProperty(merged,'__interactionPatch',{
      value:{
        nodeStateCount:nodeStates.size,
        wireStateCount:wireStates.size,
        nodePatchCount:nodePatches.size,
        wirePatchCount:wirePatches.size,
        topologyUnchanged:nodePatches.size === 0 && wirePatches.size === 0,
      },
      enumerable:false,configurable:true,
    });
    return merged;
  }
  function redraw(segments=null) {
    const canvas=document.querySelector('.canvas');
    const index=canvasElementIndexFor(canvas);
    if (!index) return;
    const sockets=index.sockets;
    const cards=index.nodes;
    const wireMembers=segments
      ? [...segments].flatMap(segment => index.wires.get(segment) || [])
      : [...index.layer.children];
    wireMembers.forEach(element => {
      if (element.dataset.universalRelation) {
        const source=sockets.get(element.dataset.sourceInterface)
          || cards.get(element.dataset.sourceNode);
        const target=sockets.get(element.dataset.targetInterface)
          || cards.get(element.dataset.targetNode);
        if (source && target) element.setAttribute('d',cablePath(source,target));
        return;
      }
      if (!element.dataset.universalRewireIncidence) return;
      const side=element.dataset.universalRewireSide;
      const socket=sockets.get(element.dataset.universalRewireInterface)
        || cards.get(element.dataset.universalRewireNode);
      if (!socket) return;
      const point=socketPoint(socket,side);
      element.setAttribute('cx',String(point.x));
      element.setAttribute('cy',String(point.y));
    });
  }
  function markWireTargets(candidateInterfaces=null) {
    wireTargetReadyElements.forEach(
      target => target.classList.remove('wire-target-ready'));
    wireTargetReadyElements.clear();
    if (!(candidateInterfaces instanceof Set)) return;
    const canvas=document.querySelector('.canvas');
    const index=canvasElementIndexFor(canvas);
    if (!index) return;
    candidateInterfaces.forEach(interfaceRoot => {
      const target=index.sockets.get(interfaceRoot);
      if (!target?.matches('[data-universal-input]')
          || target.dataset.existingOnly === 'true') return;
      target.classList.add('wire-target-ready');
      wireTargetReadyElements.add(target);
    });
  }
  function markConnectionRewireTargets(
    side=null,currentInterface=null,candidateInterfaces=null
  ) {
    document.querySelectorAll('.canvas [data-universal-interface]')
      .forEach(port => {
        const matches=side === 'source'
          ? port.matches('[data-universal-output]')
          : side === 'target'
            ? port.matches('[data-universal-input]')
            : false;
        const eligible=matches
          && candidateInterfaces instanceof Set
          && candidateInterfaces.has(port.dataset.universalInterface)
          && port.dataset.existingOnly !== 'true'
          && port.dataset.universalInterface !== currentInterface;
        port.classList.toggle('wire-reconnect-ready',eligible);
      });
  }
  function cancelConnectionRewire() {
    if (!pendingConnectionRewire) return;
    const wire=pendingConnectionRewire; pendingConnectionRewire=null;
    wire.preview.remove();
    wire.handle.dataset.dragging='False';
    wire.handle.releasePointerCapture?.(wire.pointerId);
    markConnectionRewireTargets();
    if (window.__archhubPointerOwner?.owner === 'universal-rewire') {
      window.__archhubPointerOwner=null;
    }
  }
  async function performUniversalFetch(path,payload={}) {
    const csrfToken=document.querySelector('meta[name="archhub-csrf"]')?.content;
    const requestHeaders={'Content-Type':'application/json'};
    if (csrfToken) requestHeaders['X-ArchHub-CSRF']=csrfToken;
    // The session travels in a header from origin-scoped storage, never a
    // cookie: a cookie authenticates every request that carries it and is
    // shared with every other service on this host, port regardless.
    const sessionToken=window.__archhubSession?.token;
    if (sessionToken) requestHeaders['X-ArchHub-Session']=sessionToken;
    const response = await fetch(path, {
      method:path.endsWith('/canvas') ? 'GET' : 'POST',
      headers:requestHeaders,
      credentials:'same-origin',
      body:path.endsWith('/canvas') ? undefined : JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      const error=new Error(result.error || 'Universal graph request failed');
      error.code=typeof result.code === 'string' ? result.code : '';
      error.status=response.status;
      throw error;
    }
    return result;
  }
  async function performUniversalRequest(
    path,payload={},baseProjection=lastProjection
  ) {
    return mergeProjectionDelta(
      await performUniversalFetch(path,payload),baseProjection);
  }
  let projectionRefreshRequired=false;
  function scheduleUniversalMutation(operation) {
    const scheduled=mutationTail.then(operation,operation);
    mutationTail=scheduled.catch(() => {});
    return scheduled;
  }
  function universalMutation(path,payloadFactory) {
    return scheduleUniversalMutation(async () => {
      let baseProjection=acceptedProjection || lastProjection;
      if (projectionRefreshRequired) {
        baseProjection=await performUniversalRequest(
          '/api/universal/canvas',{},null);
        acceptedProjection=baseProjection;
        projectionRefreshRequired=false;
      }
      const payload=typeof payloadFactory === 'function'
        ? payloadFactory(baseProjection)
        : payloadFactory;
      if (payload === skipUniversalMutation) return baseProjection;
      const usesReceipt=(
        (path === '/api/universal/interaction'
          || path === '/api/universal/gesture')
        && payload?.projection_mode === receiptMode
      );
      let projection;
      let receipt=null;
      if (usesReceipt) {
        receipt=await performUniversalFetch(path,payload);
        if (
          receipt?.projection_mode !== receiptMode
          || receipt.base_revision !== baseProjection.revision
          || !Number.isSafeInteger(receipt.committed_revision)
          || receipt.committed_revision < receipt.base_revision
        ) {
          throw new Error('Committed mutation receipt is invalid');
        }
        projectionRefreshRequired=true;
        try {
          projection=await performUniversalRequest(
            '/api/universal/canvas',{},null);
        } catch (error) {
          Object.defineProperty(error,'committedReceipt',{
            value:receipt,enumerable:false,configurable:true,
          });
          throw error;
        }
        if (projection.revision < receipt.committed_revision) {
          const error=new Error(
            'Fresh graph projection predates the committed mutation');
          Object.defineProperty(error,'committedReceipt',{
            value:receipt,enumerable:false,configurable:true,
          });
          throw error;
        }
        projectionRefreshRequired=false;
      } else {
        projection=await performUniversalRequest(path,payload,baseProjection);
      }
      Object.defineProperty(projection,'__mutationBaseProjection',{
        value:baseProjection,enumerable:false,configurable:true,
      });
      if (receipt) {
        Object.defineProperty(projection,'__mutationReceipt',{
          value:receipt,enumerable:false,configurable:true,
        });
      }
      acceptedProjection=projection;
      return projection;
    });
  }
  function universalRequest(path,payload={}) {
    return path.endsWith('/canvas')
      ? performUniversalRequest(path,payload)
      : universalMutation(path,payload);
  }
  function projectedInteraction(controlRoot,projection=lastProjection) {
    const bindings=projection?.interaction_projection?.bindings;
    if (!Array.isArray(bindings)) return null;
    return bindings.find(binding => binding.control === controlRoot) || null;
  }
  function bindProjectedInteraction(control,controlRoot) {
    const binding=projectedInteraction(controlRoot);
    if (!binding) {
      // A control the graph declared no interaction for cannot act -- with
      // one honest exception: a control whose capability is served by this
      // client alone. The viewport controls commit through the gesture
      // path and never held an interaction; disabling them for that took
      // Fit and Zoom away from every canvas at once.
      const capability=controlPresentation(
        control.dataset.universalControl,lastProjection
      )?.activation?.capability;
      if (capability === controlCapabilities.viewport) return;
      control.dataset.universalInteractionMissing='true';
      control.setAttribute('aria-disabled','true');
      if ('disabled' in control) control.disabled=true;
      return;
    }
    control.dataset.universalInteraction=binding.interaction;
    control.dataset.universalInteractionControl=binding.control;
    control.dataset.universalInteractionEvent=binding.event;
    control.dataset.universalInteractionProjectionMode=(
      binding.projection_mode || interactionDeltaMode);
  }
  function collectProjectedEventFacts(control,binding,eventContext={}) {
    if (!Array.isArray(binding.event_facts)) {
      throw new Error('Projected interaction input authority is missing');
    }
    if (!binding.event_facts.length) return null;
    const form=control.closest('[data-universal-relation-form]');
    const fields=form ? [...form.querySelectorAll(
      '[data-universal-relation-form-input]')] : [];
    const scope=control.closest('[data-universal-interaction-scope]');
    if (scope) fields.push(...scope.querySelectorAll(
      '[data-universal-event-fact-input]'));
    if (control.dataset.universalEventFactInput) fields.push(control);
    const facts=[];
    for (const specification of binding.event_facts) {
      if (!specification || typeof specification.input !== 'string'
          || !specification.input) {
        throw new Error('Projected interaction input declaration is invalid');
      }
      let value;
      if (specification.source === 'submitted') {
        const matching=[...new Set(fields)].filter(field =>
          field.dataset.universalRelationFormInput === specification.input
          || field.dataset.universalEventFactInput === specification.input);
        if (matching.length !== 1) {
          throw new Error('Projected interaction input identity is ambiguous');
        }
        const field=matching[0];
        value=String(field.value || '');
        if (specification.required && !value.trim()) {
          field.focus();
          return false;
        }
        if (specification.value_kind === 'text') {
          if (
            typeof specification.maximum_bytes !== 'number'
            || specification.maximum_bytes < 0
            || new TextEncoder().encode(value).length
              > specification.maximum_bytes
          ) {
            throw new Error(
              'Projected interaction text fact is outside its bounds');
          }
        } else if (specification.value_kind !== 'root') {
          throw new Error(
            'Projected interaction submitted fact kind is not admitted');
        }
      } else {
        const placement=eventContext.placement;
        const matching=[...new Set(fields)].filter(field =>
          field.dataset.universalEventFactInput === specification.input);
        const values={
          'canvas-point-x':placement?.x,
          'canvas-point-y':placement?.y,
          'canvas-viewport-pan-x':placement?.viewport?.pan_x,
          'canvas-viewport-pan-y':placement?.viewport?.pan_y,
          'canvas-viewport-zoom':placement?.viewport?.zoom,
          'relation-participant-index':(
            eventContext.participantIndex
            ?? (matching.length === 1 ? matching[0].selectedIndex : undefined)
          ),
          'topology-candidate-index':eventContext.topologyCandidateIndex,
        };
        if (!Object.prototype.hasOwnProperty.call(
          values,specification.source)) {
          throw new Error('Projected interaction source is not admitted');
        }
        value=values[specification.source];
        if (value == null && !specification.required) continue;
        if (typeof value !== 'number' || !Number.isFinite(value)) {
          throw new Error('Projected interaction numeric fact is invalid');
        }
        if (
          typeof specification.minimum !== 'number'
          || typeof specification.maximum !== 'number'
          || value < specification.minimum
          || value > specification.maximum
        ) {
          throw new Error('Projected interaction numeric fact is outside its bounds');
        }
      }
      facts.push({input:specification.input,value});
    }
    return facts;
  }
  async function executeProjectedInteraction(
    control,projectionMode=null,eventContext={}
  ) {
    projectionMode=(
      projectionMode
      || control.dataset.universalInteractionProjectionMode
      || interactionDeltaMode);
    if (projectionMode !== interactionDeltaMode
        && projectionMode !== topologyDeltaMode) {
      throw new Error('Projected interaction mode is invalid');
    }
    const controlRoot=control.dataset.universalInteractionControl;
    let previous=lastProjection;
    const initialBinding=projectedInteraction(controlRoot);
    if (!initialBinding) {
      throw new Error('Projected interaction authority is missing');
    }
    const initialFacts=collectProjectedEventFacts(
      control,initialBinding,eventContext);
    if (initialFacts === false) return null;
    const execute=() => universalMutation(
      '/api/universal/interaction',baseProjection => {
        const authority=baseProjection?.interaction_projection;
        const binding=projectedInteraction(controlRoot,baseProjection);
        if (!authority || !Number.isSafeInteger(authority.revision) || !binding) {
          throw new Error('Projected interaction authority is missing');
        }
        const payload={
          interaction:binding.interaction,
          control:binding.control,
          event:binding.event,
          revision:authority.revision,
          projection_mode:(
            binding.acknowledgement_mode
            || authority.acknowledgement_mode
          ) === receiptMode ? receiptMode : projectionMode,
        };
        if (initialFacts !== null) payload.event_facts=initialFacts;
        // A derived placement binding declares no inputs, but the drop
        // still happened at a point. The point travels as the same
        // event-fact shape; a server that expects declared facts ignores
        // unknown sources, and the clean instantiate reads them.
        if (!payload.event_facts && eventContext.placement
            && Number.isFinite(eventContext.placement.x)) {
          payload.event_facts=[
            {source:'canvas-point-x',value:eventContext.placement.x},
            {source:'canvas-point-y',value:eventContext.placement.y},
          ];
        }
        return payload;
      });
    let projection;
    try {
      projection=await execute();
    } catch (error) {
      if (error.code !== 'projection_lease_expired') throw error;
      const refreshed=await universalMutation('/api/universal/canvas',{});
      render(refreshed);
      previous=lastProjection;
      if (!projectedInteraction(controlRoot)) {
        throw new Error('The refreshed graph no longer admits this control');
      }
      projection=await execute();
    }
    if (!projection) return null;
    previous=projection.__mutationBaseProjection || previous;
    if (projectionMode === topologyDeltaMode) {
      reconcileTopologyProjection(projection);
    } else if (!reconcileStableViewProjection(previous,projection)) {
      render(projection);
    }
    return projection;
  }
  function executeTopologyInteraction(controlRoot,candidateIndex=null) {
    if (typeof controlRoot !== 'string' || !controlRoot) {
      throw new Error('Projected topology control is missing');
    }
    const control=document.createElement('button');
    bindProjectedInteraction(control,controlRoot);
    return executeProjectedInteraction(
      control,
      topologyDeltaMode,
      candidateIndex == null ? {} : {topologyCandidateIndex:candidateIndex},
    );
  }
  function applyViewport(canvas, viewport) {
    const stage=canvas.querySelector('.canvas-stage');
    if (!stage) return;
    canvas.dataset.panX=String(viewport.pan_x);
    canvas.dataset.panY=String(viewport.pan_y);
    canvas.dataset.zoom=String(viewport.zoom);
    stage.style.transform=`translate(${viewport.pan_x}px,${viewport.pan_y}px) scale(${viewport.zoom})`;
    const grid=parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--component-canvas-grid-size')) || 20;
    canvas.style.setProperty('--grid-size',(grid*viewport.zoom)+'px');
    canvas.style.setProperty('--grid-x',viewport.pan_x+'px');
    canvas.style.setProperty('--grid-y',viewport.pan_y+'px');
  }
  function renderRelationComposer(list,definition) {
    if (definition.composer?.descriptor?.length !== 1) {
      throw new Error('Relation composer graph descriptor is missing');
    }
    const composer=renderDescriptor(definition.composer.descriptor[0]);
    composer.querySelectorAll('[data-universal-relation-control]').forEach(
      control => bindProjectedInteraction(
        control,control.dataset.universalRelationControl));
    list.append(composer);
  }

  function normalizedLibraryQuery(value) {
    return String(value || '').trim().toLocaleLowerCase().split(/\s+/)
      .filter(Boolean);
  }
  function visibleLibraryEntries(library) {
    return [...library.querySelectorAll('[data-universal-library-entry]')]
      .filter(entry => !entry.hidden);
  }
  function applyLibrarySearch(library) {
    const search=library.querySelector('[data-universal-library-search]');
    if (!search) throw new Error('Node Library search graph is missing');
    const terms=normalizedLibraryQuery(search.value);
    library.querySelectorAll('[data-universal-library-entry]').forEach(entry => {
      const searchable=String(entry.dataset.universalSearchText || '')
        .toLocaleLowerCase();
      entry.hidden=!terms.every(term => searchable.includes(term));
      delete entry.dataset.searchActive;
    });
    library.querySelectorAll('[data-universal-library-section]').forEach(
      section => {
        section.hidden=![...section.querySelectorAll(
          '[data-universal-library-entry]')].some(entry => !entry.hidden);
      });
    const count=visibleLibraryEntries(library).length;
    const countElement=library.querySelector(
      '[data-universal-library-result-count]');
    if (countElement) countElement.textContent=`${count} ${count === 1 ? 'node' : 'nodes'}`;
  }
  function moveLibrarySearchSelection(library,direction) {
    const entries=visibleLibraryEntries(library);
    if (!entries.length) return null;
    let index=entries.findIndex(entry => entry.dataset.searchActive === 'true');
    index=(index+direction+entries.length)%entries.length;
    entries.forEach(entry => { delete entry.dataset.searchActive; });
    entries[index].dataset.searchActive='true';
    entries[index].querySelector('[data-universal-definition]')?.scrollIntoView?.({
      block:'nearest',
    });
    return entries[index];
  }

  function renderLibrary(projection) {
    const library=document.querySelector('.sidebar > .library-panel');
    if (!library) return;
    const existingQuery=library.querySelector(
      '[data-universal-library-search]')?.value || '';
    if (projection.library.descriptor?.length !== 1) {
      throw new Error('Library shell graph descriptor is missing');
    }
    const desired=renderDescriptor(projection.library.descriptor[0]);
    const list=desired.querySelector('[data-universal-library-list]');
    if (!list) throw new Error('Library list graph descriptor is missing');
    if (projection.primitive.visible) {
      if (projection.primitive.descriptor?.length !== 1) {
        throw new Error('Library primitive graph descriptor is missing');
      }
      const primitive=renderDescriptor(projection.primitive.descriptor[0]);
      bindProjectedInteraction(primitive,projection.primitive.id);
      primitive.draggable=true;
      list.append(primitive);
    }
    const catalog=new Map(projection.catalog.map(item => [item.id,item]));
    projection.catalog_sections.forEach(section => {
      if (section.descriptor?.length !== 1) {
        throw new Error('Library section graph descriptor is missing');
      }
      const group=renderDescriptor(section.descriptor[0]);
      if (group.dataset.universalLibrarySection !== section.id) {
        throw new Error('Library section identity is missing');
      }
      section.definitions.forEach(definition => {
      const item=catalog.get(definition);
      if (item.descriptor?.length !== 1) {
        throw new Error('Library definition graph descriptor is missing');
      }
      const entry=renderDescriptor(item.descriptor[0]);
      if (entry.dataset.universalLibraryEntry !== item.id
          || entry.dataset.universalSearchText !== item.search_text) {
        throw new Error('Library entry metadata descriptor drifted');
      }
      const row=entry.querySelector('[data-universal-definition]');
      if (!row) {
        throw new Error('Library definition control descriptor is missing');
      }
      row.draggable=true;
      const place=entry.querySelector('[data-universal-definition-place]');
      if (!place || place.dataset.universalDefinitionPlace !== item.id) {
        throw new Error('Library place control descriptor is missing');
      }
      const placeControl=controlPresentation(
        place.dataset.universalControl,projection);
      if (
        !placeControl || !placeControl.applicable
        || place.dataset.controlBinding !== placeControl.activation?.binding
        || place.dataset.controlCapability !== placeControl.activation?.capability
        || place.dataset.controlIcon !== placeControl.icon
        || place.title !== `${placeControl.title}: ${item.name}`
        || place.getAttribute('aria-label') !== place.title
      ) {
        throw new Error('Library place control descriptor drifted');
      }
      bindProjectedInteraction(place,item.id);
      place.append(graphIcon(placeControl.icon,projection));
      group.append(entry);
      });
      list.append(group);
    });
    if (projection.selected_definition?.composer) {
      renderRelationComposer(list,projection.selected_definition);
    }
    reconcileKeyedChildren(library,desired);
    const liveSearch=library.querySelector('[data-universal-library-search]');
    if (!liveSearch) throw new Error('Node Library search control is missing');
    liveSearch.value=existingQuery;
    applyLibrarySearch(library);
  }
  function keyed(node,key) {
    node.dataset.uiKey=key;
    return node;
  }
  function reconcileKeyedNode(current,desired) {
    if (!current || current.nodeType !== desired.nodeType ||
        (current.nodeType === 1 && current.tagName !== desired.tagName)) {
      return desired;
    }
    if (current.nodeType === 3) {
      if (current.data !== desired.data) current.data=desired.data;
      return current;
    }
    const desiredNames=new Set(desired.getAttributeNames());
    current.getAttributeNames().forEach(name => {
      if (!desiredNames.has(name)) current.removeAttribute(name);
    });
    desired.getAttributeNames().forEach(name => {
      const value=desired.getAttribute(name);
      if (current.getAttribute(name) !== value) current.setAttribute(name,value);
    });
    const isEditing=current === document.activeElement &&
      /^(INPUT|TEXTAREA|SELECT)$/.test(current.tagName);
    if ('disabled' in current) {
      current.disabled=desired.disabled;
    }
    reconcileKeyedChildren(current,desired);
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(current.tagName) && !isEditing &&
        current.value !== desired.value) {
      current.value=desired.value;
    }
    if (current.tagName === 'OPTION') current.selected=desired.selected;
    return current;
  }
  function reconcileKeyedChildren(current,desired) {
    projectionReconciliationDepth+=1;
    try {
      const existingByKey=new Map();
      Array.from(current.children).forEach(child => {
        const key=child.dataset.uiKey;
        if (!key) return;
        if (existingByKey.has(key)) {
          throw new Error(`Duplicate mounted UI key: ${key}`);
        }
        existingByKey.set(key,child);
      });
      const desiredKeys=new Set();
      let cursor=current.firstChild;
      Array.from(desired.childNodes).forEach(wanted => {
        let retained=null;
        if (wanted.nodeType === 1 && wanted.dataset.uiKey) {
          const key=wanted.dataset.uiKey;
          if (desiredKeys.has(key)) {
            throw new Error(`Duplicate projected UI key: ${key}`);
          }
          desiredKeys.add(key);
          const existing=existingByKey.get(key);
          if (existing) retained=reconcileKeyedNode(existing,wanted);
        } else if (wanted.nodeType === 3 && cursor?.nodeType === 3) {
          retained=reconcileKeyedNode(cursor,wanted);
        } else if (wanted.nodeType === 1 && cursor?.nodeType === 1 &&
            !cursor.dataset.uiKey && cursor.tagName === wanted.tagName) {
          retained=reconcileKeyedNode(cursor,wanted);
        }
        const node=retained || wanted;
        if (node === cursor) {
          cursor=cursor.nextSibling;
        } else {
          current.insertBefore(node,cursor);
          cursor=node.nextSibling;
        }
      });
      while (cursor) {
        const stale=cursor;
        cursor=cursor.nextSibling;
        stale.remove();
      }
    } finally {
      projectionReconciliationDepth-=1;
    }
  }
  const descriptorTags=new Set([
    'button','details','div','input','label','option','section','select',
    'span','summary','textarea'
  ]);
  const descriptorAttributes=new Set([
    'aria-controls','aria-label','aria-labelledby','aria-pressed',
    'aria-selected','autocomplete','disabled','hidden','id','maxlength','open',
    'placeholder','role','spellcheck','step','tabindex','title','type'
  ,'draggable']);
  const descriptorBoolean=value => (
    value === true || value === 1 || value === '1'
    || value === 'true' || value === 'True'
  );
  function renderDescriptor(spec) {
    if (!spec || !descriptorTags.has(spec.tag) || !spec.key) {
      throw new Error('Rejected invalid Properties descriptor');
    }
    const node=keyed(element(
      spec.tag,spec.class || '',spec.text === undefined ? '' : String(spec.text)
    ),String(spec.key));
    Object.entries(spec.attributes || {}).forEach(([name,value]) => {
      if (name.startsWith('on') || name === 'style' || name === 'src' ||
          name === 'srcdoc' ||
          (!descriptorAttributes.has(name) && !name.startsWith('data-'))) {
        throw new Error('Rejected unsafe Properties descriptor attribute');
      }
      if (name === 'disabled') {
        node.disabled=descriptorBoolean(value);
      } else if (name === 'hidden') {
        node.hidden=descriptorBoolean(value);
      } else if (name === 'open' && node.tagName === 'DETAILS') {
        node.open=descriptorBoolean(value);
      } else if (name === 'data-selected' && node.tagName === 'OPTION') {
        node.selected=descriptorBoolean(value);
      } else if (value !== null && value !== undefined) {
        node.setAttribute(name,String(value));
      }
    });
    (spec.children || []).forEach(child => node.append(renderDescriptor(child)));
    if (spec.value !== undefined && 'value' in node) {
      node.value=String(spec.value);
    }
    return node;
  }
  function renderInspector(projection) {
    const inspector=document.querySelector('.inspector');
    if (!inspector) return;
    inspector.dataset.universal='true';
    inspector.style.overflowAnchor='none';
    const changedSelection=
      inspector.dataset.inspectedNode !== (projection.selected || '');
    inspector.dataset.inspectedNode=projection.selected || '';
    const presentation=projection.inspector.presentation;
    const shell=projection.inspector.shell_descriptor;
    if (shell?.length !== 1) {
      throw new Error('Inspector shell graph descriptor is missing');
    }
    const panel=renderDescriptor(shell[0]);
    const chrome=[];
    const header=projection.inspector.header_descriptor;
    if (!header?.length) {
      throw new Error('Inspector header graph descriptor is missing');
    }
    header.forEach(item => chrome.push(renderDescriptor(item)));
    const controls=projection.inspector.controls_descriptor;
    if (!controls?.length) {
      throw new Error('Inspector controls graph descriptor is missing');
    }
    const controlSpecs=new Map(controls.map(spec => [spec.key,spec]));
    const lensSpec=controlSpecs.get('inspector:lenses');
    const tabsSpec=controlSpecs.get('inspector:tabs');
    if (!lensSpec || !tabsSpec) {
      throw new Error('Inspector controls graph descriptor is incomplete');
    }
    const lensControl=renderDescriptor(lensSpec);
    lensControl.querySelectorAll('[data-universal-inspector-lens]').forEach(
      control => bindProjectedInteraction(
        control,control.dataset.universalInspectorLens));
    chrome.push(lensControl);
    const tabs=renderDescriptor(tabsSpec);
    tabs.querySelectorAll('[data-universal-properties-panel]').forEach(tab => {
      bindProjectedInteraction(tab,tab.dataset.universalPropertiesPanel);
    });
    chrome.push(tabs);
    presentation.panels.forEach(definition => {
      const lensPanel=[...panel.querySelectorAll(
        '[data-inspector-tabpanel]')].find(item =>
          item.dataset.inspectorTabpanel === definition.id);
      if (!lensPanel) {
        throw new Error('Inspector tab panel graph descriptor is missing');
      }
      definition.components.forEach(component => {
        if (!component.descriptor?.length) {
          throw new Error(
            `Properties presenter ${component.presenter} has no descriptor`
          );
        }
        component.descriptor.forEach(item => {
          lensPanel.append(renderDescriptor(item));
        });
      });
    });
    panel.querySelectorAll('[data-universal-control]').forEach(control => {
      bindProjectedInteraction(control,control.dataset.universalControl);
    });
    panel.prepend(...chrome);
    const descriptorDesired=element('div');
    descriptorDesired.append(panel);
    reconcileKeyedChildren(inspector,descriptorDesired);
    if (changedSelection) {
      inspector.scrollTop=0;
      requestAnimationFrame(() => { inspector.scrollTop=0; });
    }
  }
  function renderToolbar(projection) {
    const toolbar=document.querySelector('.canvas-toolbar');
    if (!toolbar) return;
    const focusedControl=toolbar.contains(document.activeElement)
      ? document.activeElement?.dataset?.universalControl : null;
    const controls=zoneControls('canvas-toolbar',projection);
    if (projection.toolbar_descriptor?.length !== 1) {
      throw new Error('Canvas toolbar graph descriptor is missing');
    }
    const surface=renderDescriptor(projection.toolbar_descriptor[0]);
    const scope=surface.querySelector('[data-universal-toolbar-scope]');
    const zoom=surface.querySelector('[data-universal-toolbar-zoom-value]');
    const selected=surface.querySelector(
      '[data-universal-toolbar-selection-value]');
    const buttons=[...surface.querySelectorAll(
      'button[data-universal-control]')];
    if (!scope || !zoom || !selected || buttons.length !== controls.length) {
      throw new Error('Canvas toolbar graph descriptor is incomplete');
    }
    buttons.forEach((button,index) => {
      const control=controls[index];
      if (
        button.dataset.universalControl !== control.owner
        || button.dataset.controlBinding !== control.activation.binding
        || button.dataset.controlCapability !== control.activation.capability
        || button.dataset.controlIcon !== control.icon
        || button.title !== control.title
        || button.getAttribute('aria-label') !== control.title
      ) {
        throw new Error('Canvas toolbar control descriptor drifted');
      }
      button.append(graphIcon(control.icon,projection));
      bindProjectedInteraction(button,button.dataset.universalControl);
    });
    surface.querySelectorAll('[data-universal-scope]').forEach(control => {
      bindProjectedInteraction(control,control.dataset.universalScope);
    });
    const desired=element('div');
    desired.append(...surface.childNodes);
    reconcileKeyedChildren(toolbar,desired);
    const toolbarButtons=[...toolbar.querySelectorAll(
      'button[data-universal-control]')];
    const focusTarget=toolbarButtons.find(
      button => button.dataset.universalControl === focusedControl
    ) || toolbarButtons[0];
    toolbarButtons.forEach(button => { button.tabIndex=button === focusTarget ? 0 : -1; });
    // The composer: the typed way to reach the same library the sidebar
    // shows. It is chrome, not graph content -- what it DOES is the
    // graph's placement interaction, unchanged -- so the surface is
    // made here rather than asking the graph to describe a text box.
    const canvasSurface=document.querySelector('.canvas');
    let composer=canvasSurface?.querySelector(':scope > .composer');
    if (canvasSurface && !composer) {
      composer=element('div','composer');
      const box=element('input','composer-input');
      box.type='text';
      box.placeholder='Type a node and press Enter';
      box.setAttribute('aria-label','Composer');
      box.autocomplete='off';
      box.spellcheck=false;
      // Arrange: the graph holds each card's position, and an import that
      // placed twenty-six domains left nine of them under another card --
      // 57 overlapping pairs, and elementFromPoint on nine of them
      // answered a DIFFERENT card, so those nine could not be clicked,
      // wired or grouped at all. This lays the scope out on a grid
      // through the SAME signed positions gesture a drag uses; nothing
      // moves unless the founder asks for it.
      const arrange=element('button','composer-arrange');
      arrange.type='button';
      arrange.textContent='Arrange';
      arrange.title='Lay out this scope so no card covers another';
      arrange.addEventListener('click',async () => {
        if (!lastProjection || !lastProjection.nodes.length) return;
        const width=projectedNodeWidth(lastProjection);
        const columnStep=width+56;
        const surface=document.querySelector('.canvas');
        const zoom=lastProjection.viewport?.zoom || 1;
        const usable=Math.max(
          columnStep*2,
          ((surface?.clientWidth || 1280)/zoom)-96,
        );
        const columns=Math.max(1,Math.floor(usable/columnStep));
        const rowStep=Math.max(...lastProjection.nodes.map(
          node => projectedNodeHeight(node,lastProjection)))+56;
        // Keep the founder's arrangement as far as it goes: cards are
        // laid out in the order they already read on screen.
        const ordered=[...lastProjection.nodes].sort((a,b) =>
          (Number(a.y)-Number(b.y)) || (Number(a.x)-Number(b.x)));
        const positions={};
        ordered.forEach((node,index) => {
          positions[node.id]={
            x:60+(index % columns)*columnStep,
            y:60+Math.floor(index/columns)*rowStep,
          };
        });
        composerHint('arranging ' + ordered.length + ' cards…');
        try {
          await commit({positions});
          composerHint('arranged ' + ordered.length + ' cards');
        } catch (error) {
          composerHint(String(error.message || error));
        }
      });
      // The stylesheet is graph-held and knows only about the input, so
      // the row that holds both is laid out here, where it is made.
      // The panel is a backdrop, not a target: three cards sat under it
      // and elementFromPoint answered DIV.composer, so a click meant for
      // a card hit empty chrome. Only the things you can actually press
      // take the pointer.
      composer.style.pointerEvents='none';
      const row=element('div','composer-row');
      row.style.pointerEvents='auto';
      row.style.display='flex';
      row.style.alignItems='center';
      row.style.gap='8px';
      box.style.flex='1';
      box.style.minWidth='0';
      arrange.style.flex='0 0 auto';
      arrange.style.height='28px';
      arrange.style.padding='0 12px';
      arrange.style.borderRadius='5px';
      arrange.style.border='1px solid var(--line)';
      arrange.style.background='var(--bg)';
      arrange.style.color='var(--ink-soft)';
      arrange.style.cursor='pointer';
      row.append(box,arrange);
      composer.append(row,element('div','composer-hint'));
      canvasSurface.append(composer);
      // Bound to the element itself: document-level listeners in this
      // page compete over keys, and the founder's Enter must not depend
      // on winning that race.
      box.addEventListener('input',() => {
        const match=composerMatch(box.value);
        composerHint(
          !box.value.trim() ? ''
          : match ? 'Enter places ' + match.name
          : 'no node called that');
      });
      box.addEventListener('keydown',async keyEvent => {
        if (keyEvent.key === 'Escape') {
          box.value=''; composerHint(''); box.blur(); return;
        }
        if (keyEvent.key !== 'Enter') return;
        keyEvent.preventDefault();
        keyEvent.stopPropagation();
        const match=composerMatch(box.value);
        if (!match) { composerHint('no node called that'); return; }
        const viewport=lastProjection?.viewport;
        const middle=viewport ? {
          x:(canvasSurface.clientWidth/2 - viewport.pan_x)/viewport.zoom,
          y:(canvasSurface.clientHeight/2 - viewport.pan_y)/viewport.zoom,
        } : null;
        const control=document.createElement('button');
        bindProjectedInteraction(control,match.id);
        composerHint('placing ' + match.name + '…');
        try {
          await executeProjectedInteraction(control,interactionDeltaMode,
            middle ? {placement:middle} : {});
          box.value='';
          composerHint('placed ' + match.name);
        } catch (error) {
          composerHint(String(error.message || error));
        }
      });
    }
    if (composer) composer.hidden=false;
    // The composer is client-made chrome and the toolbar is graph-held, so
    // nothing in the stylesheet knows they share the bottom of the canvas.
    // With twenty-six cards the toolbar grew under the composer and every
    // group/ungroup click landed in the text box instead of the button:
    // elementFromPoint on "Compose selected nodes" answered composer-input.
    // Measured, not guessed, so a toolbar that wraps still stays clear.
    if (composer && toolbar) {
      const lift=Math.ceil(toolbar.getBoundingClientRect().height)+22;
      const wanted=lift+'px';
      if (composer.style.bottom !== wanted) composer.style.bottom=wanted;
    }
  }
  function projectedNodeWidth(projection) {
    const value=projection.configuration?.design_system?.components
      ?.card?.width?.value;
    const width=parseFloat(value);
    return Number.isFinite(width) && width > 0 ? width : 220;
  }
  function canvasAuthoringExpanded(projection=lastProjection) {
    return projection?.inspector?.lenses?.some(
      lens => lens.active && lens.name === 'build') || false;
  }
  function expandedCanvasPort(port,projection=lastProjection) {
    return canvasAuthoringExpanded(projection) && Boolean(
      port.connectable
      || port.mode === 'connection' && !port.read_only
      || port.mode === 'relation-role' && port.editable
    );
  }
  function projectedNodeHeight(node,projection=lastProjection) {
    const inputs=node.ports.filter(
      port => port.side === 'target' &&
        expandedCanvasPort(port,projection)).length;
    const outputs=node.ports.filter(
      port => port.side === 'source' &&
        expandedCanvasPort(port,projection)).length;
    return Math.max(112,82+Math.max(inputs,outputs)*24);
  }
  function positionCanvasPort(
    port,button,ports,cardHeight,projection=lastProjection
  ) {
    const sameSide=ports.filter(item => item.side === port.side);
    if (expandedCanvasPort(port,projection)) {
      const expanded=sameSide.filter(item =>
        expandedCanvasPort(item,projection));
      button.style.top=(66+expanded.indexOf(port)*24)+'px';
      return;
    }
    const compact=sameSide.filter(item =>
      !expandedCanvasPort(item,projection));
    const usable=Math.max(24,cardHeight-48);
    const center=34+(compact.indexOf(port)+1)*usable/(compact.length+1);
    button.style.top=(center-12)+'px';
  }
  function projectedBounds(projection) {
    if (!projection.nodes.length) {
      return {left:0,top:0,right:1,bottom:1,width:1,height:1};
    }
    const left=Math.min(...projection.nodes.map(node => Number(node.x)));
    const top=Math.min(...projection.nodes.map(node => Number(node.y)));
    const width=projectedNodeWidth(projection);
    const right=Math.max(...projection.nodes.map(node => Number(node.x)+width));
    const bottom=Math.max(...projection.nodes.map(
      node => Number(node.y)+projectedNodeHeight(node,projection)));
    return {left,top,right,bottom,width:right-left,height:bottom-top};
  }
  function fitViewport(projection,canvas) {
    const bounds=projectedBounds(projection);
    const rect=canvas.getBoundingClientRect();
    const policy=interactionPolicy(projection);
    const padding=36;
    const usableWidth=Math.max(1,rect.width-padding*2);
    const usableHeight=Math.max(1,rect.height-padding*2);
    const fitMax=Number.isFinite(policy.zoom_fit_max)
      ? policy.zoom_fit_max : 1.25;
    const zoom=Math.max(policy.zoom_min,Math.min(fitMax,
      Math.min(usableWidth/bounds.width,usableHeight/bounds.height)));
    return {
      pan_x:padding+(usableWidth-bounds.width*zoom)/2-bounds.left*zoom,
      pan_y:padding+(usableHeight-bounds.height*zoom)/2-bounds.top*zoom,
      zoom,
    };
  }
  // A canvas that opens where no node is drawn is an empty program. The
  // stored viewport is the operator's own choice and is honoured whenever it
  // shows any of the work; when it shows none -- a pan left behind, a node
  // placed outside it -- the graph's work is what the surface opens on.
  // This corrects presentation only. Nothing is committed, so the operator's
  // held viewport survives untouched until they pan for themselves, and the
  // correction is offered once per opening rather than on every projection.
  let openedOnWork=false;
  function viewportShowsAnyNode(projection,canvas,viewport) {
    if (!projection.nodes.length) return true;
    const rect=canvas.getBoundingClientRect();
    if (!(rect.width > 0) || !(rect.height > 0)) return true;
    const width=projectedNodeWidth(projection);
    return projection.nodes.some(node => {
      const x=Number(node.x), y=Number(node.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return true;
      const height=Array.isArray(node.ports)
        ? projectedNodeHeight(node,projection) : 112;
      const left=x*viewport.zoom+viewport.pan_x;
      const top=y*viewport.zoom+viewport.pan_y;
      const right=left+width*viewport.zoom;
      const bottom=top+height*viewport.zoom;
      return right > 0 && left < rect.width
        && bottom > 0 && top < rect.height;
    });
  }
  function viewportOverWork(projection,canvas) {
    const held=projection.viewport;
    if (openedOnWork) return held;
    openedOnWork=true;
    // A presentation-only correction must be incapable of taking the
    // render down: any surprise in this projection's shape means the
    // held viewport wins, exactly as if this function did not exist.
    let fitted;
    try {
      if (viewportShowsAnyNode(projection,canvas,held)) return held;
      fitted=fitViewport(projection,canvas);
    } catch (error) {
      return held;
    }
    // The correction must ALSO become what the projection believes, or
    // the first wheel notch zooms from the stale stored viewport and
    // throws every node off-screen again (the founder's first scroll did
    // exactly that). The projection is replaced, never mutated, and the
    // fitted viewport is committed once so the stored value stops being
    // a landmine for the next open.
    if (projection === lastProjection) {
      lastProjection={...projection,viewport:fitted};
    }
    setTimeout(() => { commit({viewport:fitted}).catch(() => {}); },0);
    return fitted;
  }
  function topologyAppendPlan(previous,projection) {
    if (!previous || previous.scope.current !== projection.scope.current) {
      return null;
    }
    const nextNodes=new Map(projection.nodes.map(node => [node.id,node]));
    const nextWires=new Map(projection.wires.map(wire => [
      wire.id+':'+wire.segment,wire,
    ]));
    if (
      previous.nodes.some(node => !nextNodes.has(node.id))
      || previous.wires.some(wire =>
        !nextWires.has(wire.id+':'+wire.segment))
    ) return null;
    if (previous.wires.some(wire => (
      !sameCanvasWireStructure(
        wire,nextWires.get(wire.id+':'+wire.segment)
      )
    ))) return null;
    const addedNodes=projection.nodes.filter(node =>
      !previous.nodes.some(current => current.id === node.id));
    const previousWireKeys=new Set(previous.wires.map(
      wire => wire.id+':'+wire.segment));
    const addedWires=projection.wires.filter(wire =>
      !previousWireKeys.has(wire.id+':'+wire.segment));
    if (!addedNodes.length && !addedWires.length) return null;
    const changedWires=new Set();
    const changedNodes=new Set([
      ...addedNodes.map(node => node.id),
      ...addedWires.flatMap(
        wire => [wire.source,wire.target]).filter(Boolean),
    ]);
    if (previous.selected) changedNodes.add(previous.selected);
    if (projection.selected) changedNodes.add(projection.selected);
    previous.wires.forEach(wire => {
      const next=nextWires.get(wire.id+':'+wire.segment);
      if (wire.selected !== next.selected || wire.context !== next.context) {
        changedWires.add(wire.id+':'+wire.segment);
        if (wire.source) changedNodes.add(wire.source);
        if (wire.target) changedNodes.add(wire.target);
      }
    });
    previous.nodes.forEach(node => {
      const next=nextNodes.get(node.id);
      if (
        node.x !== next.x || node.y !== next.y
        || !sameCanvasNodeStructure(node,next)
      ) changedNodes.add(node.id);
    });
    return {addedWires,changedNodes,changedWires};
  }
  function topologyPatchAppendPlan(previous,projection,patch) {
    if (
      !previous || previous.scope.current !== projection.scope.current
      || patch.remove_nodes.length || patch.remove_wires.length
    ) return null;
    const previousNodeRoots=new Set(previous.nodes.map(node => node.id));
    const previousWireRoots=new Set(previous.wires.map(
      wire => wire.id+':'+wire.segment));
    const retainedNodeOrder=patch.node_order.filter(
      root => previousNodeRoots.has(root));
    const retainedWireOrder=patch.wire_order.filter(
      root => previousWireRoots.has(root));
    if (
      retainedNodeOrder.some(
        (root,index) => root !== previous.nodes[index]?.id)
      || retainedWireOrder.some((root,index) => root !== (
        previous.wires[index]?.id+':'+previous.wires[index]?.segment))
    ) return null;
    const addedWires=patch.upsert_wires.filter(wire =>
      !previousWireRoots.has(wire.id+':'+wire.segment));
    const changedWires=new Set(patch.upsert_wires.filter(wire =>
      previousWireRoots.has(wire.id+':'+wire.segment)
    ).map(wire => wire.id+':'+wire.segment));
    const previousNodes=new Map(previous.nodes.map(node => [node.id,node]));
    const candidateNodes=new Set(patch.upsert_nodes.map(node => node.id));
    addedWires.forEach(wire => {
      if (wire.source) candidateNodes.add(wire.source);
      if (wire.target) candidateNodes.add(wire.target);
    });
    if (previous.selected) candidateNodes.add(previous.selected);
    if (projection.selected) candidateNodes.add(projection.selected);
    const nextNodes=new Map(projection.nodes.map(node => [node.id,node]));
    const changedNodes=new Set();
    const stateNodes=new Set();
    candidateNodes.forEach(root => {
      const before=previousNodes.get(root);
      const after=nextNodes.get(root);
      if (
        before && after
        && before.x === after.x && before.y === after.y
        && sameCanvasNodeStructure(before,after)
      ) stateNodes.add(root);
      else changedNodes.add(root);
    });
    return {addedWires,changedNodes,changedWires,stateNodes};
  }
  function canvasWireElements(wire) {
    const relationAttributes={
      'data-universal-relation':wire.id,
      'data-relation':wire.id,
      'data-wire-segment':wire.segment,
      'data-wire-role':wire.role || '',
      'data-source-node':wire.source,
      'data-target-node':wire.target,
      'data-source-interface':wire.source_interface,
      'data-target-interface':wire.target_interface,
      'data-source-incidence':wire.source_incidence,
      'data-target-incidence':wire.target_incidence,
      'data-focused':wire.selected ? 'True' : 'False',
      'data-context':wire.context ? 'True' : 'False',
    };
    const hit=keyed(svgElement('path',{
      class:'wire-hit',...relationAttributes,
    }),'canvas:wire-hit:'+wire.id+':'+wire.segment);
    const path=keyed(svgElement('path',{
      class:'wire-line universal-wire',...relationAttributes,
    }),'canvas:wire:'+wire.id+':'+wire.segment);
    if (wire.directed) path.setAttribute(
      'marker-end','url(#archhub-wire-arrow)');
    path.style.stroke=wire.color;
    path.style.strokeWidth=String(wire.width);
    path.style.strokeDasharray=wire.dash;
    const handles=[];
    if (!wire.nary && wire.source_incidence && wire.target_incidence) {
      for (const side of ['source','target']) {
        const fixedSide=side === 'source' ? 'target' : 'source';
        handles.push(keyed(svgElement('circle',{
          class:'wire-endpoint wire-endpoint-'+side,
          r:6,
          'data-universal-rewire-relation':wire.id,
          'data-universal-rewire-segment':wire.segment,
          'data-universal-rewire-side':side,
          'data-universal-rewire-incidence':wire[side+'_incidence'],
          'data-universal-rewire-interface':wire[side+'_interface'],
          'data-universal-rewire-node':wire[side],
          'data-universal-rewire-fixed-interface':
            wire[fixedSide+'_interface'],
          'data-universal-rewire-fixed-node':wire[fixedSide],
          'data-focused':wire.selected ? 'True' : 'False',
        }),'canvas:wire-endpoint:'+wire.id+':'+wire.segment+':'+side));
      }
    }
    return {paths:[hit,path],handles};
  }
  function sameCanvasPortPresentation(left,right) {
    return left.id === right.id
      && left.name === right.name
      && left.side === right.side
      && left.mode === right.mode
      && left.connectable === right.connectable
      && left.read_only === right.read_only
      && left.editable === right.editable
      && JSON.stringify(left.descriptor) === JSON.stringify(right.descriptor);
  }
  function sameCanvasNodeStructure(left,right) {
    return left.id === right.id
      && left.label === right.label
      && left.color === right.color
      && left.composition === right.composition
      && left.openable === right.openable
      && left.member_count === right.member_count
      && left.connection_count === right.connection_count
      && left.ports.length === right.ports.length
      && left.ports.every(
        (port,index) => sameCanvasPortPresentation(port,right.ports[index]))
      && JSON.stringify(left.card_descriptor) === JSON.stringify(
        right.card_descriptor);
  }
  function sameCanvasNodePresentation(left,right) {
    return left.x === right.x
      && left.y === right.y
      && left.selected === right.selected
      && sameCanvasNodeStructure(left,right);
  }
  function sameCanvasWireStructure(left,right) {
    return left.id === right.id
      && left.segment === right.segment
      && left.role === right.role
      && left.source === right.source
      && left.target === right.target
      && left.source_interface === right.source_interface
      && left.target_interface === right.target_interface
      && left.source_incidence === right.source_incidence
      && left.target_incidence === right.target_incidence
      && left.color === right.color
      && left.width === right.width
      && left.dash === right.dash
      && left.directed === right.directed
      && left.nary === right.nary;
  }
  function sameCanvasWirePresentation(left,right) {
    return left.selected === right.selected
      && left.context === right.context
      && sameCanvasWireStructure(left,right);
  }
  function canvasNodeElement(item,projection) {
    if (item.card_descriptor?.length !== 1) {
      throw new Error('Canvas card graph descriptor is missing');
    }
    const card=renderDescriptor(item.card_descriptor[0]);
    card.dataset.graphNode=item.id;
    card.dataset.universalRoot=item.id;
    card.dataset.universalComposition=item.composition ? 'True' : 'False';
    card.dataset.draggable='true';
    card.dataset.universalOpenable=item.openable ? 'True' : 'False';
    card.dataset.selected=item.selected ? 'True' : 'False';
    card.dataset.focused=item.id === projection.selected ? 'True' : 'False';
    if (item.openable) bindProjectedInteraction(card,item.id);
    card.style.left=item.x+'px';
    card.style.top=item.y+'px';
    card.style.setProperty('--node-color',item.color);
    const inputCount=item.ports.filter(
      port => port.side === 'target'
        && expandedCanvasPort(port,projection)).length;
    const outputCount=item.ports.filter(
      port => port.side === 'source'
        && expandedCanvasPort(port,projection)).length;
    const cardHeight=Math.max(
      112,82+Math.max(inputCount,outputCount)*24);
    card.style.minHeight=cardHeight+'px';
    const ports=card.querySelector(
      ':scope > [data-ui-key="canvas:node:'+item.id+':ports"]');
    if (!ports) throw new Error('Canvas card ports descriptor is missing');
    [
      ...item.ports.filter(port => port.side === 'target'),
      ...item.ports.filter(port => port.side === 'source'),
    ].forEach(port => {
      if (port.descriptor?.length !== 1) {
        throw new Error('Canvas port graph descriptor is missing');
      }
      const control=renderDescriptor(port.descriptor[0]);
      if (!expandedCanvasPort(port,projection)) {
        control.classList.add('node-port-exact');
      }
      positionCanvasPort(
        port,control,item.ports,cardHeight,projection);
      ports.append(control);
    });
    return card;
  }
  function renderAppendedTopology(projection,plan,redrawSegments) {
    const canvas=document.querySelector('.canvas');
    const stage=canvas?.querySelector('.canvas-stage');
    const layer=stage?.querySelector('[data-ui-key="canvas:wires"]');
    if (!canvas || !stage || !layer) return false;
    const index=canvasElementIndexFor(canvas);
    if (!index) return false;
    canvas.dataset.universal='true';
    canvas.dataset.selection=JSON.stringify(projection.selection);
    const mountedWires=index.wireElementsByUiKey;
    plan.changedWires.forEach(key => {
      const wire=projection.wires.find(
        item => item.id+':'+item.segment === key);
      if (!wire) return;
      const parts=canvasWireElements(wire);
      [...parts.paths,...parts.handles].forEach(desired => {
        const current=mountedWires.get(desired.dataset.uiKey);
        if (current) reconcileKeyedNode(current,desired);
      });
    });
    plan.addedWires.forEach(wire => {
      const parts=canvasWireElements(wire);
      const elements=[...parts.paths,...parts.handles];
      layer.append(...elements);
      elements.forEach(element => indexCanvasWire(index,element));
    });
    const nodes=new Map(projection.nodes.map(node => [node.id,node]));
    const mountedNodes=index.nodes;
    (plan.stateNodes || new Set()).forEach(root => {
      const item=nodes.get(root);
      const current=mountedNodes.get(root);
      if (!item || !current) return;
      current.dataset.selected=item.selected ? 'True' : 'False';
      current.dataset.focused=(
        item.id === projection.selected ? 'True' : 'False'
      );
    });
    plan.changedNodes.forEach(root => {
      const item=nodes.get(root);
      if (!item) return;
      const desired=canvasNodeElement(item,projection);
      const current=mountedNodes.get(root);
      const mounted=current ? reconcileKeyedNode(current,desired) : desired;
      if (!current) stage.append(mounted);
      indexCanvasNode(index,mounted);
    });
    const heading=stage.querySelector(
      ':scope > [data-ui-key="canvas:heading"]');
    if (heading) heading.textContent=projection.scope.current_label;
    const bounds=projectedBounds(projection);
    const stageWidth=Math.max(1320,Math.ceil(bounds.right+80));
    const stageHeight=Math.max(760,Math.ceil(bounds.bottom+80));
    layer.setAttribute('viewBox','0 0 '+stageWidth+' '+stageHeight);
    layer.setAttribute('width',String(stageWidth));
    layer.setAttribute('height',String(stageHeight));
    stage.style.width=stageWidth+'px';
    stage.style.height=stageHeight+'px';
    applyViewport(canvas,viewportOverWork(projection,canvas));
    requestAnimationFrame(() => redraw(redrawSegments));
    return true;
  }
  function reconcileStableCanvasProjection(previous,projection) {
    if (!previous || previous.scope.current !== projection.scope.current) {
      return false;
    }
    const previousNodes=new Map(previous.nodes.map(node => [node.id,node]));
    const nextNodes=new Map(projection.nodes.map(node => [node.id,node]));
    const previousWires=new Map(previous.wires.map(wire => [
      wire.id+':'+wire.segment,wire,
    ]));
    const nextWires=new Map(projection.wires.map(wire => [
      wire.id+':'+wire.segment,wire,
    ]));
    if (
      previousNodes.size !== nextNodes.size
      || previousWires.size !== nextWires.size
      || [...previousNodes.keys()].some(root => !nextNodes.has(root))
      || [...previousWires.keys()].some(root => !nextWires.has(root))
    ) return false;
    const canvas=document.querySelector('.canvas');
    const stage=canvas?.querySelector('.canvas-stage');
    const layer=stage?.querySelector('[data-ui-key="canvas:wires"]');
    if (!canvas || !stage || !layer) return false;
    const changedNodes=new Set();
    const movedNodes=new Set();
    nextNodes.forEach((node,root) => {
      const current=previousNodes.get(root);
      if (!sameCanvasNodePresentation(current,node)) {
        changedNodes.add(root);
      }
      if (current.x !== node.x || current.y !== node.y) {
        movedNodes.add(root);
      }
    });
    const changedWires=new Set();
    nextWires.forEach((wire,key) => {
      const current=previousWires.get(key);
      if (!sameCanvasWirePresentation(current,wire)) {
        changedWires.add(key);
        if (wire.source) changedNodes.add(wire.source);
        if (wire.target) changedNodes.add(wire.target);
      }
    });
    const mountedNodes=new Map(Array.from(
      stage.querySelectorAll(':scope > [data-graph-node]')
    ).map(card => [card.dataset.graphNode,card]));
    for (const root of changedNodes) {
      const current=mountedNodes.get(root);
      const node=nextNodes.get(root);
      if (!current || !node) return false;
      reconcileKeyedNode(
        current,canvasNodeElement(node,projection));
    }
    const mountedWires=new Map(Array.from(layer.children).map(
      child => [child.dataset.uiKey,child]).filter(([key]) => Boolean(key)));
    for (const key of changedWires) {
      const wire=nextWires.get(key);
      const parts=canvasWireElements(wire);
      for (const desired of [...parts.paths,...parts.handles]) {
        const current=mountedWires.get(desired.dataset.uiKey);
        if (!current) return false;
        reconcileKeyedNode(current,desired);
      }
    }
    if (changedNodes.size || changedWires.size) {
      invalidateCanvasElementIndex();
      canvasElementIndexFor(canvas);
    }
    canvas.dataset.selection=JSON.stringify(projection.selection);
    const redrawSegments=new Set(projection.wires.filter(wire =>
      movedNodes.has(wire.source) || movedNodes.has(wire.target)
      || changedWires.has(wire.id+':'+wire.segment)
    ).map(wire => wire.id+':'+wire.segment));
    const bounds=projectedBounds(projection);
    const stageWidth=Math.max(1320,Math.ceil(bounds.right+80));
    const stageHeight=Math.max(760,Math.ceil(bounds.bottom+80));
    layer.setAttribute('viewBox','0 0 '+stageWidth+' '+stageHeight);
    layer.setAttribute('width',String(stageWidth));
    layer.setAttribute('height',String(stageHeight));
    stage.style.width=stageWidth+'px';
    stage.style.height=stageHeight+'px';
    applyViewport(canvas,viewportOverWork(projection,canvas));
    requestAnimationFrame(() => redraw(redrawSegments));
    return true;
  }
  function reconcileCanvasLensPresentation(previous,projection) {
    if (!previous || previous.scope.current !== projection.scope.current) {
      return false;
    }
    if (
      previous.nodes.length !== projection.nodes.length
      || previous.wires.length !== projection.wires.length
      || !previous.nodes.every(
        (node,index) => sameCanvasNodePresentation(
          node,projection.nodes[index]))
      || !previous.wires.every(
        (wire,index) => sameCanvasWirePresentation(
          wire,projection.wires[index]))
      || previous.viewport.pan_x !== projection.viewport.pan_x
      || previous.viewport.pan_y !== projection.viewport.pan_y
      || previous.viewport.zoom !== projection.viewport.zoom
    ) return false;
    const canvas=document.querySelector('.canvas');
    const stage=canvas?.querySelector('.canvas-stage');
    const layer=stage?.querySelector('[data-ui-key="canvas:wires"]');
    if (!canvas || !stage || !layer) return false;
    const index=canvasElementIndexFor(canvas);
    if (!index) return false;
    const previousNodes=new Map(previous.nodes.map(node => [node.id,node]));
    const movedInterfaces=new Set();
    for (const node of projection.nodes) {
      const card=index.nodes.get(node.id);
      if (!card) return false;
      const prior=previousNodes.get(node.id);
      const cardHeight=projectedNodeHeight(node,projection);
      const priorHeight=projectedNodeHeight(prior,previous);
      if (priorHeight !== cardHeight) card.style.minHeight=cardHeight+'px';
      for (const port of node.ports) {
        const button=index.sockets.get(port.id);
        if (!button) return false;
        const wasExpanded=expandedCanvasPort(port,previous);
        const expanded=expandedCanvasPort(port,projection);
        const exact=expanded
          ? '' : ' node-port-exact';
        const className='node-port '+(
          port.side === 'target' ? 'node-port-in' : 'node-port-out'
        )+exact;
        if (button.className !== className) button.className=className;
        if (wasExpanded !== expanded) movedInterfaces.add(port.id);
        if (wasExpanded !== expanded || priorHeight !== cardHeight) {
          positionCanvasPort(
            port,button,node.ports,cardHeight,projection);
        }
      }
    }
    canvas.dataset.selection=JSON.stringify(projection.selection);
    const bounds=projectedBounds(projection);
    const stageWidth=Math.max(1320,Math.ceil(bounds.right+80));
    const stageHeight=Math.max(760,Math.ceil(bounds.bottom+80));
    layer.setAttribute('viewBox','0 0 '+stageWidth+' '+stageHeight);
    layer.setAttribute('width',String(stageWidth));
    layer.setAttribute('height',String(stageHeight));
    stage.style.width=stageWidth+'px';
    stage.style.height=stageHeight+'px';
    const redrawSegments=new Set(projection.wires.filter(wire => (
      movedInterfaces.has(wire.source_interface)
      || movedInterfaces.has(wire.target_interface)
    )).map(wire => wire.id+':'+wire.segment));
    if (redrawSegments.size) {
      requestAnimationFrame(() => redraw(redrawSegments));
    }
    return true;
  }
  function reconcileStableViewProjection(previous,projection) {
    if (!projection.__interactionPatch?.topologyUnchanged) {
      requireUniqueProjectionIdentities(projection);
    }
    const canvasUnchanged=(
      typeof projection.canvas_signature === 'string'
      && projection.canvas_signature
      && projection.canvas_signature === previous?.canvas_signature
    );
    const propertyPatched=canvasUnchanged
      && reconcileSimplePropertyValue(previous,projection);
    if (canvasUnchanged) {
      const canvasStateUnchanged=(
        projection.__interactionPatch?.nodeStateCount === 0
        && projection.__interactionPatch?.wireStateCount === 0
        && projection.__interactionPatch?.topologyUnchanged === true
      );
      if (!canvasStateUnchanged
          && !reconcileStableCanvasProjection(previous,projection)) return false;
      lastProjection=projection;
      window.__archhubInteractionPolicy=projection?.interaction_policy || null;
      applyThemeProjection(projection);
      const previousComposer=(
        previous.selected_definition?.composer?.descriptor || null);
      const nextComposer=(
        projection.selected_definition?.composer?.descriptor || null);
      if (
        previous.primitive.visible !== projection.primitive.visible
        || previous.library.title !== projection.library.title
        || previous.selected !== projection.selected
        || JSON.stringify(previousComposer) !== JSON.stringify(nextComposer)
      ) renderLibrary(projection);
      if (!propertyPatched) renderInspector(projection);
      if (!sameProjectedRegion(
        previous.toolbar_descriptor,projection.toolbar_descriptor)) {
        renderToolbar(projection);
      }
      clearInteractionStatus();
      return true;
    }
    if (!reconcileCanvasLensPresentation(previous,projection)) return false;
    lastProjection=projection;
    window.__archhubInteractionPolicy=projection?.interaction_policy || null;
    applyThemeProjection(projection);
    const previousComposer=(
      previous.selected_definition?.composer?.descriptor || null);
    const nextComposer=(
      projection.selected_definition?.composer?.descriptor || null);
    if (
      previous.primitive.visible !== projection.primitive.visible
      || previous.library.title !== projection.library.title
      || previous.selected !== projection.selected
      || JSON.stringify(previousComposer) !== JSON.stringify(nextComposer)
    ) renderLibrary(projection);
    renderInspector(projection);
    if (
      JSON.stringify(zoneControls('canvas-toolbar',previous))
      !== JSON.stringify(zoneControls('canvas-toolbar',projection))
    ) renderToolbar(projection);
    clearInteractionStatus();
    return true;
  }
  async function navigateScope(control) {
    cancelPendingCanvasSelectionCommit();
    const scoped=await executeProjectedInteraction(
      control,topologyDeltaMode);
    if (!scoped) return null;
    const canvas=document.querySelector('.canvas');
    if (canvas) {
      canvas.scrollLeft=0;
      canvas.scrollTop=0;
    }
    return scoped;
  }
  function renderCanvas(projection,redrawSegments=null) {
    const canvas=document.querySelector('.canvas');
    const stage=canvas?.querySelector('.canvas-stage');
    if (!canvas || !stage) return;
    canvas.dataset.universal='true';
    canvas.dataset.selection=JSON.stringify(projection.selection);
    const desiredStage=element('div');
    const bounds=projectedBounds(projection);
    const stageWidth=Math.max(1320,Math.ceil(bounds.right+80));
    const stageHeight=Math.max(760,Math.ceil(bounds.bottom+80));
    const layer=keyed(svgElement('svg',{
      class:'wire-layer', viewBox:`0 0 ${stageWidth} ${stageHeight}`,
      width:stageWidth,height:stageHeight,'aria-hidden':'true'
    }),'canvas:wires');
    const defs=keyed(svgElement('defs'),'canvas:wire-definitions');
    const marker=keyed(svgElement('marker',{
      id:'archhub-wire-arrow',viewBox:'0 0 8 8',refX:7,refY:4,
      markerWidth:5,markerHeight:5,orient:'auto',markerUnits:'strokeWidth'
    }),'canvas:wire-arrow');
    marker.append(svgElement('path',{class:'wire-arrow',d:'M 0 0 L 8 4 L 0 8 z'}));
    defs.append(marker); layer.append(defs);
    const endpointHandles=[];
    projection.wires.forEach(wire => {
      const parts=canvasWireElements(wire);
      layer.append(...parts.paths);
      endpointHandles.push(...parts.handles);
    });
    layer.append(...endpointHandles);
    desiredStage.append(layer);
    if (projection.canvas_heading_descriptor?.length !== 1) {
      throw new Error('Canvas heading graph descriptor is missing');
    }
    const heading=renderDescriptor(projection.canvas_heading_descriptor[0]);
    if (heading.dataset.universalCanvasHeading !== projection.scope.current) {
      throw new Error('Canvas heading graph identity does not match scope');
    }
    desiredStage.append(heading);
    projection.nodes.forEach(item => {
      desiredStage.append(canvasNodeElement(item,projection));
    });
    reconcileKeyedChildren(stage,desiredStage);
    stage.style.width=stageWidth+'px';
    stage.style.height=stageHeight+'px';
    applyViewport(canvas,viewportOverWork(projection,canvas));
    invalidateCanvasElementIndex();
    canvasElementIndexFor(canvas);
    requestAnimationFrame(() => redraw(redrawSegments));
  }
  function requireUniqueProjectionIdentities(projection) {
    const requireUnique=(values,label) => {
      const seen=new Set();
      values.forEach(value => {
        if (typeof value !== 'string' || !value || seen.has(value)) {
          throw new Error(`Duplicate or missing projected ${label}: ${value}`);
        }
        seen.add(value);
      });
    };
    requireUnique(projection.nodes.map(node => node.id),'node identity');
    requireUnique(
      projection.catalog.map(item => item.id),'catalogue definition identity');
    requireUnique(
      projection.catalog_sections.map(section => section.id),
      'catalogue section identity');
    const catalogueDefinitions=projection.catalog.map(item => item.id);
    const sectionDefinitions=projection.catalog_sections.flatMap(
      section => section.definitions);
    if (
      sectionDefinitions.length !== catalogueDefinitions.length
      || sectionDefinitions.some(
        (definition,index) => definition !== catalogueDefinitions[index])
    ) {
      throw new Error('Catalogue sections do not exactly cover the release');
    }
    requireUnique(projection.wires.map(
      wire => `${wire.id}:${wire.segment}`),'wire segment identity');
    requireUnique(projection.nodes.flatMap(
      node => node.ports.map(port => port.id)),'interface identity');
  }
  function applyThemeProjection(projection) {
    Object.entries(projection.configuration?.theme || {}).forEach(
      ([name,value]) => document.documentElement.style.setProperty(
        `--${name.replaceAll('_','-')}`,value));
  }
  function render(projection) {
    requireUniqueProjectionIdentities(projection);
    lastProjection=projection;
    if (
      !acceptedProjection
      || Number(projection.revision) >= Number(acceptedProjection.revision)
    ) acceptedProjection=projection;
    window.__archhubInteractionPolicy=projection?.interaction_policy || null;
    applyThemeProjection(projection);
    Object.entries(projection.configuration.design_system?.tokens || {}).forEach(
      ([name,token]) => document.documentElement.style.setProperty(
        `--token-${name.replaceAll('.','-')}`,token.value));
    Object.entries(projection.configuration.design_system?.components || {}).forEach(
      ([component,bindings]) => Object.entries(bindings).forEach(
        ([property,binding]) => document.documentElement.style.setProperty(
          `--component-${component}-${property}`,binding.value)));
    renderStaticControls(projection);
    renderLibrary(projection);
    renderCanvas(projection);
    renderInspector(projection);
    renderToolbar(projection);
    clearInteractionStatus();
  }
  async function refresh() {
    if (refreshPending) return refreshPending;
    refreshPending=universalRequest('/api/universal/canvas')
      .then(render).catch(error => {
        console.error(error);
        showInteractionStatus(
          error.message || 'The projected graph was rejected.');
      }).finally(() => {refreshPending=null;});
    return refreshPending;
  }
  function sameSelection(previous,projection) {
    const before=previous?.selection || [];
    const after=projection?.selection || [];
    return before.length === after.length
      && before.every((root,index) => root === after[index])
      && previous?.selected === projection?.selected;
  }
  function sameProjectedRegion(previous,next) {
    return JSON.stringify(previous) === JSON.stringify(next);
  }
  function reconcileSimplePropertyValue(previous,projection) {
    if (!previous || previous.canvas_signature !== projection.canvas_signature
        || previous.selected !== projection.selected
        || previous.scope.current !== projection.scope.current
        || previous.inspector?.active !== projection.inspector?.active
        || !sameProjectedRegion(previous.selection,projection.selection)) {
      return false;
    }
    const before=new Map((previous.properties || []).map(
      property => [property.relation,property]));
    const changed=(projection.properties || []).filter(property => {
      const prior=before.get(property.relation);
      return prior && prior.value !== property.value;
    });
    if (before.size !== (projection.properties || []).length
        || changed.length !== 1) return false;
    const property=changed[0];
    const prior=before.get(property.relation);
    const withoutValue=item => {
      const {value,...rest}=item;
      return rest;
    };
    if (!property.editable
        || !sameProjectedRegion(withoutValue(prior),withoutValue(property))
        || (projection.properties || []).some(candidate => {
          const previousProperty=before.get(candidate.relation);
          return candidate.relation === property.relation
            ? !sameProjectedRegion(
              withoutValue(previousProperty),withoutValue(candidate))
            : !sameProjectedRegion(previousProperty,candidate);
        })) {
      return false;
    }
    const inspector=document.querySelector('.inspector');
    if (!inspector) return false;
    const fields=[...inspector.querySelectorAll('[data-universal-control]')]
      .filter(field => field.dataset.universalControl === property.control
        && 'value' in field);
    if (fields.length !== 1) return false;
    fields[0].value=String(property.value ?? '');
    return true;
  }
  function reconcileCanvasProjectionState(
    previous,projection,{deferRelations=false,redrawSegments=null}={}
  ) {
    const canvas=document.querySelector('.canvas');
    const stage=canvas?.querySelector('.canvas-stage');
    if (!canvas || !stage) return false;
    const previousNodes=new Map((previous?.nodes || []).map(
      node => [node.id,node]));
    const nextNodes=new Map(projection.nodes.map(node => [node.id,node]));
    if (
      previousNodes.size !== nextNodes.size
      || [...previousNodes.keys()].some(root => !nextNodes.has(root))
    ) return false;
    canvas.dataset.selection=JSON.stringify(projection.selection);
    const changedNodes=new Set();
    const movedNodes=new Set();
    nextNodes.forEach((node,root) => {
      const prior=previousNodes.get(root);
      if (
        prior.selected !== node.selected
        || prior.x !== node.x || prior.y !== node.y
      ) changedNodes.add(root);
      if (prior.x !== node.x || prior.y !== node.y) movedNodes.add(root);
    });
    const index=canvasElementIndexFor(canvas);
    if (!index) return false;
    const mountedNodes=index.nodes;
    for (const root of changedNodes) {
      const card=mountedNodes.get(root);
      const node=nextNodes.get(root);
      if (!card || !node) return false;
      card.dataset.selected=node.selected ? 'True' : 'False';
      card.dataset.focused=node.id === projection.selected ? 'True' : 'False';
      if (previousNodes.get(root).x !== node.x) card.style.left=node.x+'px';
      if (previousNodes.get(root).y !== node.y) card.style.top=node.y+'px';
    }
    const viewportChanged=(
      !previous
      || previous.viewport.pan_x !== projection.viewport.pan_x
      || previous.viewport.pan_y !== projection.viewport.pan_y
      || previous.viewport.zoom !== projection.viewport.zoom
    );
    if (viewportChanged) applyViewport(canvas,viewportOverWork(projection,canvas));

    const reconcileRelations=() => {
      if (lastProjection !== projection) return;
      const layer=index.layer;
      const previousWires=new Map((previous?.wires || []).map(wire => [
        wire.id+':'+wire.segment,wire,
      ]));
      const nextWires=new Map(projection.wires.map(wire => [
        wire.id+':'+wire.segment,wire,
      ]));
      if (
        previousWires.size !== nextWires.size
        || [...previousWires.keys()].some(key => !nextWires.has(key))
      ) return;
      const changedWires=new Set();
      nextWires.forEach((wire,key) => {
        const prior=previousWires.get(key);
        if (prior.selected !== wire.selected || prior.context !== wire.context) {
          changedWires.add(key);
        }
      });
      if (changedWires.size) {
        changedWires.forEach(key => {
          const wire=nextWires.get(key);
          (index.wires.get(key) || []).forEach(element => {
            element.dataset.focused=wire.selected ? 'True' : 'False';
            if (element.dataset.context !== undefined) {
              element.dataset.context=wire.context ? 'True' : 'False';
            }
          });
        });
      }
      const affectedInterfaces=new Set();
      changedWires.forEach(key => {
        const previousWire=previousWires.get(key);
        const nextWire=nextWires.get(key);
        [previousWire,nextWire].filter(Boolean).forEach(wire => {
          if (wire.source_interface) affectedInterfaces.add(wire.source_interface);
          if (wire.target_interface) affectedInterfaces.add(wire.target_interface);
        });
      });
      if (previous?.selected) affectedInterfaces.add(previous.selected);
      if (projection.selected) affectedInterfaces.add(projection.selected);
      const contextInterfaces=new Set(projection.wires.filter(
        wire => wire.context || wire.selected).flatMap(wire => [
          wire.source_interface,wire.target_interface,
        ]).filter(Boolean));
      const selectedInterface=projection.selected;
      affectedInterfaces.forEach(interfaceRoot => {
        const socket=index.sockets.get(interfaceRoot);
        if (!socket) return;
        const context=contextInterfaces.has(socket.dataset.universalInterface);
        const selected=socket.dataset.universalInterface === selectedInterface;
        if ((socket.dataset.context === 'True') !== context) {
          socket.dataset.context=context ? 'True' : 'False';
        }
        if ((socket.dataset.selected === 'True') !== selected) {
          socket.dataset.selected=selected ? 'True' : 'False';
          socket.setAttribute('aria-pressed',selected ? 'true' : 'false');
        }
      });
      if (redrawSegments === false) return;
      const segments=redrawSegments === null
        ? new Set(projection.wires.filter(wire => (
          movedNodes.has(wire.source) || movedNodes.has(wire.target)
        )).map(wire => wire.id+':'+wire.segment))
        : redrawSegments;
      if (segments.size) redraw(segments);
    };
    if (deferRelations) requestAnimationFrame(reconcileRelations);
    else reconcileRelations();
    return true;
  }
  function reconcileGestureProjection(previous,projection) {
    lastProjection=projection;
    window.__archhubInteractionPolicy=projection?.interaction_policy || null;
    const reconciled=reconcileCanvasProjectionState(previous,projection,{
      deferRelations:true,
    });
    const inspectorChanged=!sameProjectedRegion(
      previous?.inspector,projection.inspector);
    const toolbarChanged=!sameProjectedRegion(
      previous?.toolbar_descriptor,projection.toolbar_descriptor);
    const renderChrome=() => {
      if (lastProjection !== projection) return;
      if (inspectorChanged) renderInspector(projection);
      else {
        const inspector=document.querySelector('.inspector');
        if (inspector) inspector.dataset.inspectedNode=projection.selected || '';
      }
      if (toolbarChanged) renderToolbar(projection);
      clearInteractionStatus();
    };
    if (!reconciled) {
      render(projection);
      return;
    }
    if (sameSelection(previous,projection)) renderChrome();
    else requestAnimationFrame(renderChrome);
  }
  function topologyRedrawSegments(previous,projection) {
    if (!previous) return null;
    const currentNodes=new Map(previous.nodes.map(node => [node.id,node]));
    const moved=projection.nodes.some(node => {
      const current=currentNodes.get(node.id);
      return current && (current.x !== node.x || current.y !== node.y);
    });
    if (moved) return null;
    const currentWires=new Map(previous.wires.map(wire => [
      wire.id+':'+wire.segment,wire,
    ]));
    const geometry=[
      'source','target','source_interface','target_interface',
      'source_incidence','target_incidence',
    ];
    return new Set(projection.wires.filter(wire => {
      const current=currentWires.get(wire.id+':'+wire.segment);
      return !current || geometry.some(field => current[field] !== wire[field]);
    }).map(wire => wire.id+':'+wire.segment));
  }
  function topologyPatchRedrawSegments(previous,patch) {
    if (!previous || !patch) return null;
    const previousNodes=new Map(previous.nodes.map(node => [node.id,node]));
    const moved=patch.upsert_nodes.some(node => {
      const current=previousNodes.get(node.id);
      return current && (current.x !== node.x || current.y !== node.y);
    });
    if (moved) return null;
    const previousWires=new Map(previous.wires.map(wire => [
      wire.id+':'+wire.segment,wire,
    ]));
    const geometry=[
      'source','target','source_interface','target_interface',
      'source_incidence','target_incidence',
    ];
    return new Set(patch.upsert_wires.filter(wire => {
      const current=previousWires.get(wire.id+':'+wire.segment);
      return !current || geometry.some(field => current[field] !== wire[field]);
    }).map(wire => wire.id+':'+wire.segment));
  }
  function reconcileTopologyProjection(projection) {
    if (projection.__topologyValidated !== true) {
      requireUniqueProjectionIdentities(projection);
    }
    const previous=lastProjection;
    const inspectorChanged=!sameProjectedRegion(
      previous?.inspector,projection.inspector);
    const toolbarChanged=!sameProjectedRegion(
      previous?.toolbar_descriptor,projection.toolbar_descriptor);
    const redrawSegments=projection.__topologyPatch
      ? topologyPatchRedrawSegments(previous,projection.__topologyPatch)
      : topologyRedrawSegments(previous,projection);
    const appendPlan=projection.__topologyPatch
      ? topologyPatchAppendPlan(
          previous,projection,projection.__topologyPatch)
      : topologyAppendPlan(previous,projection);
        lastProjection=projection;
        window.__archhubInteractionPolicy=projection?.interaction_policy || null;
    const appended=appendPlan
      && renderAppendedTopology(projection,appendPlan,redrawSegments);
    if (!appended) renderCanvas(projection,redrawSegments);
    if (inspectorChanged) renderInspector(projection);
    else {
      const inspector=document.querySelector('.inspector');
      if (inspector) inspector.dataset.inspectedNode=projection.selected || '';
    }
    if (toolbarChanged) renderToolbar(projection);
    clearInteractionStatus();
  }
  function reconcileStableProjection(projection) {
    requireUniqueProjectionIdentities(projection);
    if (
      typeof projection.canvas_signature === 'string'
      && projection.canvas_signature
      && projection.canvas_signature === lastProjection?.canvas_signature
    ) {
      const previous=lastProjection;
      const propertyPatched=reconcileSimplePropertyValue(previous,projection);
      if (!reconcileStableCanvasProjection(previous,projection)) {
        render(projection);
        return;
      }
      lastProjection=projection;
      window.__archhubInteractionPolicy=projection?.interaction_policy || null;
      if (!propertyPatched) renderInspector(projection);
      if (!sameProjectedRegion(
        previous?.toolbar_descriptor,projection.toolbar_descriptor)) {
        renderToolbar(projection);
      }
      clearInteractionStatus();
      return;
    }
    const stable=reconcileStableCanvasProjection(lastProjection,projection);
    if (!stable) {
      render(projection);
      return;
    }
    lastProjection=projection;
    window.__archhubInteractionPolicy=projection?.interaction_policy || null;
    renderInspector(projection);
    renderToolbar(projection);
    clearInteractionStatus();
  }
  function clearInteractionStatus() {
    const target=document.querySelector('.status-message');
    if (!target) return;
    target.textContent='';
    target.dataset.tone='';
    target.dataset.visible='False';
    target.hidden=true;
  }
  function showInteractionStatus(message, tone='error') {
    const target=document.querySelector('.status-message');
    if (!target) return;
    target.textContent=message;
    target.dataset.tone=tone;
    target.dataset.visible='True';
    target.hidden=false;
  }
  function canvasGestureIsNoop(payload,projection=lastProjection) {
    if (!projection || !payload || typeof payload !== 'object') return false;
    if (payload.positions && Object.keys(payload.positions).length) return false;
    let compared=false;
    if (Array.isArray(payload.roots)) {
      compared=true;
      if (
        payload.roots.length !== projection.selection.length
        || payload.roots.some(
          (root,index) => root !== projection.selection[index])
      ) return false;
      if (
        payload.focus !== undefined
        && payload.focus !== projection.selected
      ) return false;
    }
    if (payload.viewport && typeof payload.viewport === 'object') {
      compared=true;
      if (['pan_x','pan_y','zoom'].some(
        field => Number(payload.viewport[field])
          !== Number(projection.viewport[field])
      )) return false;
    }
    return compared;
  }
  async function commit(payload) {
    // Projections are replaced, never mutated. Keep the immutable prior
    // projection for rejection rollback instead of cloning the full graph on
    // every pointer gesture.
    const previous=lastProjection || null;
    try {
      const projection=await universalMutation(
        '/api/universal/gesture',baseProjection => {
          if (canvasGestureIsNoop(payload,baseProjection)) {
            return skipUniversalMutation;
          }
          return {
            ...payload,
            projection_mode:(
              baseProjection.interaction_projection?.acknowledgement_mode
                === receiptMode
            ) ? receiptMode : interactionDeltaMode,
            projection_revision:baseProjection.revision,
          };
        });
      reconcileGestureProjection(
        projection.__mutationBaseProjection || previous,projection);
      return projection;
    } catch (error) {
      if (!error.committedReceipt && previous) render(previous);
      showInteractionStatus(
        error.committedReceipt
          ? 'The change is committed. Refreshing its graph view is required.'
          : (error.message || 'The governed action was rejected.'),
        error.committedReceipt ? 'pending' : 'error');
      return previous;
    }
  }
  window.__archhubUniversalRefresh=refresh;
  window.__archhubUniversalCommit=commit;
  window.__archhubUniversalValidateProjection=requireUniqueProjectionIdentities;

  function canvasPoint(clientX,clientY) {
    const canvas=document.querySelector('.canvas');
    const rect=canvas.getBoundingClientRect();
    const viewport=lastProjection?.viewport || {pan_x:0,pan_y:0,zoom:1};
    return {
      x:(clientX-rect.left+canvas.scrollLeft-viewport.pan_x)/viewport.zoom,
      y:(clientY-rect.top+canvas.scrollTop-viewport.pan_y)/viewport.zoom,
    };
  }

  function placementHeight(definition=null) {
    if (!canvasAuthoringExpanded(lastProjection)) return 112;
    const interfaces=Number(definition?.interfaces) || 0;
    return Math.max(112,82+interfaces*24);
  }

  function placementOverlaps(candidate,width,height,margin,node) {
    const nodeWidth=projectedNodeWidth(lastProjection);
    const nodeHeight=projectedNodeHeight(node,lastProjection);
    const left=Number(node.x),top=Number(node.y);
    return !(
      candidate.x+width+margin <= left
      || candidate.x >= left+nodeWidth+margin
      || candidate.y+height+margin <= top
      || candidate.y >= top+nodeHeight+margin
    );
  }

  function nearestAvailablePlacement(point,definition=null) {
    const canvas=document.querySelector('.canvas');
    const rect=canvas.getBoundingClientRect();
    const viewport=lastProjection?.viewport || {pan_x:0,pan_y:0,zoom:1};
    const width=projectedNodeWidth(lastProjection);
    const height=placementHeight(definition);
    const grid=parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--component-canvas-grid-size')) || 20;
    const margin=Math.max(8,grid);
    const base={x:Math.round(point.x-width/2),y:Math.round(point.y-height/2)};
    const visible={
      left:(canvas.scrollLeft-viewport.pan_x)/viewport.zoom,
      top:(canvas.scrollTop-viewport.pan_y)/viewport.zoom,
      right:(canvas.scrollLeft+rect.width-viewport.pan_x)/viewport.zoom,
      bottom:(canvas.scrollTop+rect.height-viewport.pan_y)/viewport.zoom,
    };
    const stepX=Math.ceil((width+margin)/grid)*grid;
    const stepY=Math.ceil((height+margin)/grid)*grid;
    const candidates=[];
    for (let ring=0;ring<=48;ring+=1) {
      for (let row=-ring;row<=ring;row+=1) {
        for (let column=-ring;column<=ring;column+=1) {
          if (Math.max(Math.abs(row),Math.abs(column)) !== ring) continue;
          candidates.push({
            x:base.x+column*stepX,
            y:base.y+row*stepY,
            distance:column*column+row*row,
          });
        }
      }
    }
    candidates.sort((left,right) =>
      left.distance-right.distance || right.y-left.y || right.x-left.x);
    const occupied=lastProjection?.nodes || [];
    const available=candidate => !occupied.some(node =>
      placementOverlaps(candidate,width,height,margin,node));
    const inside=candidate => (
      candidate.x >= visible.left+margin
      && candidate.y >= visible.top+margin
      && candidate.x+width <= visible.right-margin
      && candidate.y+height <= visible.bottom-margin
    );
    const nonnegative=candidate => candidate.x >= margin && candidate.y >= margin;
    const chosen=(candidates.find(candidate =>
      nonnegative(candidate) && inside(candidate) && available(candidate))
      || candidates.find(candidate => nonnegative(candidate) && available(candidate)));
    if (!chosen) throw new Error('No collision-free canvas position is available.');
    const reveal=inside(chosen) ? null : {
      pan_x:rect.width/2-(chosen.x+width/2)*viewport.zoom,
      pan_y:rect.height/2-(chosen.y+height/2)*viewport.zoom,
      zoom:viewport.zoom,
    };
    return {
      x:Math.round(chosen.x),y:Math.round(chosen.y),viewport:reveal,
    };
  }

  async function instantiateAt(control,clientX,clientY) {
    const definition=control.dataset.universalDefinitionPlace;
    if (!definition) throw new Error('Library placement identity is missing');
    const point=canvasPoint(clientX,clientY);
    const catalogueDefinition=lastProjection?.catalog.find(
      item => item.id === definition);
    const placement=nearestAvailablePlacement(point,catalogueDefinition);
    if (catalogueDefinition?.composition_contract) {
      await commit({
        roots:[],focus:definition,
        ...(placement.viewport ? {viewport:placement.viewport} : {}),
      });
      const refreshed=[...document.querySelectorAll(
        '[data-universal-definition-place]')].find(
          item => item.dataset.universalDefinitionPlace === definition);
      if (!refreshed?.dataset.universalInteraction) {
        throw new Error('Relation placement Interaction is missing');
      }
      await executeProjectedInteraction(
        refreshed,interactionDeltaMode,{placement});
      showInteractionStatus('Choose the relation participants in the Node Library.');
      return;
    }
    if (!control.dataset.universalInteraction) {
      throw new Error('Library placement Interaction is missing');
    }
    await executeProjectedInteraction(
      control,topologyDeltaMode,{placement});
    if (placement.viewport) {
      const canvas=document.querySelector('.canvas');
      canvas.scrollLeft=0; canvas.scrollTop=0;
    }
  }

  async function instantiatePrimitiveAt(control,clientX,clientY) {
    const point=canvasPoint(clientX,clientY);
    const placement=nearestAvailablePlacement(point);
    if (!control?.dataset.universalInteraction) {
      throw new Error('Primitive placement Interaction is missing');
    }
    await executeProjectedInteraction(
      control,topologyDeltaMode,{placement});
    if (placement.viewport) {
      const canvas=document.querySelector('.canvas');
      canvas.scrollLeft=0; canvas.scrollTop=0;
    }
  }

  function projectedRolePort(socket) {
    if (!lastProjection) return null;
    const owner=socket.dataset.universalRoleOwner;
    const interfaceRoot=(
      socket.dataset.universalRelationRole
      || socket.dataset.universalRoleInterface
    );
    return lastProjection.nodes.find(node => node.id === owner)?.ports.find(
      port => port.id === interfaceRoot || port.interface === interfaceRoot
    ) || null;
  }

  function markRelationCandidates(roots) {
    const allowed=new Set(roots);
    document.querySelectorAll('.canvas [data-universal-root]').forEach(card => {
      if (allowed.has(card.dataset.universalRoot)) {
        card.dataset.universalWireCandidate='true';
      } else {
        delete card.dataset.universalWireCandidate;
      }
    });
  }

  function cancelRoleWire() {
    if (!pendingRoleWire) return;
    const wire=pendingRoleWire; pendingRoleWire=null;
    wire.preview.remove();
    wire.socket.releasePointerCapture?.(wire.pointerId);
    markRelationCandidates([]);
    if (window.__archhubPointerOwner?.owner === 'universal-role-wire') {
      window.__archhubPointerOwner=null;
    }
  }

  document.addEventListener('click', async event => {
    const toolbarControl=event.target.closest(
      '.canvas-toolbar [data-control-binding]');
    if (toolbarControl && lastProjection) {
      event.preventDefault(); event.stopPropagation();
      try {
        if (toolbarControl.matches('[data-universal-scope]')) {
          await navigateScope(toolbarControl);
        } else if (toolbarControl.dataset.universalInteraction) {
          await executeProjectedInteraction(toolbarControl,topologyDeltaMode);
        } else {
          await activateProjectedControl(toolbarControl);
        }
      } catch (error) {
        showInteractionStatus(error.message || 'The governed control was rejected.');
      }
      return;
    }
    const definitionPlace=event.target.closest(
      '[data-universal-definition-place]');
    if (definitionPlace && lastProjection) {
      event.preventDefault(); event.stopPropagation();
      const canvas=document.querySelector('.canvas');
      if (!canvas) return;
      const rect=canvas.getBoundingClientRect();
      try {
        await instantiateAt(
          definitionPlace,
          rect.left+rect.width/2,
          rect.top+rect.height/2,
        );
      } catch (error) {
        showInteractionStatus(
          error.message || 'The governed placement was rejected.');
      }
      return;
    }
    const contractCreate=event.target.closest('[data-universal-contract-create]');
    if (contractCreate && lastProjection) {
      event.preventDefault(); event.stopPropagation();
      const definition=lastProjection.selected_definition;
      if (!definition?.composer?.complete ||
          definition.id !== contractCreate.dataset.universalContractCreate) return;
      if (definition.composer.x === null || definition.composer.y === null) {
        const canvas=document.querySelector('.canvas');
        const rect=canvas.getBoundingClientRect();
        const point=canvasPoint(rect.left+rect.width/2,rect.top+rect.height/2);
        const placement=nearestAvailablePlacement(point,definition);
        const place=[...document.querySelectorAll(
          '[data-universal-definition-place]')].find(
            item => item.dataset.universalDefinitionPlace === definition.id);
        if (!place?.dataset.universalInteraction) {
          throw new Error('Relation placement Interaction is missing');
        }
        await executeProjectedInteraction(
          place,interactionDeltaMode,{placement});
      }
      const refreshed=[...document.querySelectorAll(
        '[data-universal-contract-create]')].find(
          item => item.dataset.universalContractCreate === definition.id);
      if (!refreshed?.dataset.universalInteraction) {
        throw new Error('Relation creation Interaction is missing');
      }
      await executeProjectedInteraction(refreshed,topologyDeltaMode);
      return;
    }
    const projected=event.target.closest('[data-universal-interaction]');
    if (projected?.matches(
      '.canvas[data-universal="true"] [data-universal-root]'
    )) return;
    if (projected && lastProjection) {
      event.preventDefault(); event.stopPropagation();
      if (projected.matches('[data-universal-scope]')) {
        await navigateScope(projected);
      } else {
        await executeProjectedInteraction(projected);
      }
      return;
    }
    const scope=event.target.closest('[data-universal-scope]');
    if (scope && lastProjection) {
      event.preventDefault(); event.stopPropagation();
      await navigateScope(scope);
      return;
    }
    const settings=event.target.closest('.rail-settings');
    if (settings && lastProjection) {
      event.preventDefault();
      await commit({roots:[],focus:lastProjection.configuration.personal_asset});
      return;
    }
    const shareTheme=event.target.closest('[data-universal-theme-share]');
    if (shareTheme && !shareTheme.disabled && lastProjection) {
      event.preventDefault();
      const projection=await universalRequest('/api/universal/theme-share',{
        revision:shareTheme.dataset.universalThemeShare,
      });
      render(projection); return;
    }
    const publishTheme=event.target.closest('[data-universal-theme-publish]');
    if (publishTheme && !publishTheme.disabled && lastProjection) {
      event.preventDefault();
      const projection=await universalRequest('/api/universal/theme-publish',{
        revision:publishTheme.dataset.universalThemePublish,
      });
      render(projection); return;
    }
    const adapterExecution=event.target.closest('[data-universal-adapter-execute]');
    if (adapterExecution && !adapterExecution.disabled) {
      event.preventDefault();
      // A run carries its own identity. Without one the graph cannot
      // tell a retry from a second run, so this path refused every
      // press outright -- the button was drawn, wired, and answered
      // with a complaint about a field only the caller can mint.
      const projection=await universalRequest('/api/universal/execute-adapter',{
        root:adapterExecution.dataset.root,
        command_id:crypto.randomUUID(),
      });
      render(projection);
      return;
    }
    const promotion=event.target.closest('[data-universal-resource-promote]');
    if (promotion && !promotion.disabled) {
      event.preventDefault();
      const projection=await universalRequest('/api/universal/resource-promote',{
        root:promotion.dataset.root,
        target:promotion.dataset.target,
        source:promotion.dataset.source || null,
      });
      render(projection);
      return;
    }
    const saveWip=event.target.closest('[data-universal-lifecycle-save]');
    if (saveWip && !saveWip.disabled) {
      event.preventDefault();
      const input=saveWip.parentElement.querySelector(
        '[data-universal-lifecycle-content]');
      const projection=await universalRequest('/api/universal/lifecycle-wip',{
        root:saveWip.dataset.root,
        interface:saveWip.dataset.interface,
        base:saveWip.dataset.base,
        value:input?.value || '',
      });
      render(projection);
      return;
    }
    const mergeWip=event.target.closest('[data-universal-lifecycle-merge]');
    if (mergeWip && !mergeWip.disabled) {
      event.preventDefault();
      const input=mergeWip.parentElement.querySelector(
        '[data-universal-lifecycle-content]');
      const projection=await universalRequest('/api/universal/lifecycle-merge',{
        root:mergeWip.dataset.root,
        interface:mergeWip.dataset.interface,
        parents:JSON.parse(mergeWip.dataset.parents || '[]'),
        value:input?.value || '',
      });
      render(projection);
      return;
    }
    const primitive=event.target.closest('[data-universal-primitive]');
    if (primitive) {
      event.preventDefault();
      await commit({roots:[],focus:primitive.dataset.universalPrimitive});
      return;
    }
    const canvasInterface=event.target.closest(
      '.canvas [data-universal-interface]');
    if (canvasInterface) {
      event.preventDefault(); event.stopPropagation();
      await commit({
        roots:[],focus:canvasInterface.dataset.universalInterface
      });
      return;
    }
    const row=event.target.closest('[data-universal-select]');
    if (row) {
      event.preventDefault();
      await commit({roots:[row.dataset.universalSelect],focus:row.dataset.universalSelect});
      return;
    }
    const definition=event.target.closest('[data-universal-definition]');
    if (definition) {
      event.preventDefault();
      // Selecting a library row is a local act: highlight it and let the
      // + button and drag do the placing. Committing a focus for a
      // definition that is not a member of the scope was refused on every
      // click ("browser focus primary must be selected") and painted an
      // error toast over the library.
      const wasActive=definition.dataset.active === 'true';
      document.querySelectorAll('[data-universal-definition]').forEach(
        row => { delete row.dataset.active; });
      if (!wasActive) definition.dataset.active='true';
      return;
    }
    const wire=event.target.closest('[data-universal-relation]');
    if (wire) {
      event.preventDefault(); event.stopPropagation();
      await commit({roots:[],focus:wire.dataset.universalRelation});
      return;
    }
    const authority=event.target.closest('[data-authority-relationship]');
    if (authority) {
      event.preventDefault(); event.stopPropagation();
      await commit({roots:[],focus:authority.dataset.authorityRelationship});
      return;
    }
    const focus=event.target.closest('[data-universal-focus]');
    if (focus) {
      event.preventDefault(); event.stopPropagation();
      await commit({roots:[],focus:focus.dataset.universalFocus});
      return;
    }
  });
  document.addEventListener('input', event => {
    const search=event.target.closest?.('[data-universal-library-search]');
    if (!search) return;
    const library=search.closest('.library-panel');
    if (library) applyLibrarySearch(library);
  });
  document.addEventListener('keydown', async event => {
    const search=event.target.closest?.('[data-universal-library-search]');
    if (!search) return;
    const library=search.closest('.library-panel');
    if (!library) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      search.value='';
      applyLibrarySearch(library);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      moveLibrarySearchSelection(
        library,event.key === 'ArrowDown' ? 1 : -1);
      return;
    }
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const active=(
      library.querySelector('[data-universal-library-entry][data-search-active="true"]')
      || visibleLibraryEntries(library)[0]
    );
    const place=active?.querySelector('[data-universal-definition-place]');
    const canvas=document.querySelector('.canvas');
    if (!place || !canvas) return;
    const rect=canvas.getBoundingClientRect();
    try {
      await instantiateAt(
        place,rect.left+rect.width/2,rect.top+rect.height/2);
    } catch (error) {
      showInteractionStatus(
        error.message || 'The governed placement was rejected.');
    }
  });
  document.addEventListener('keydown', async event => {
    if (event.key === 'Escape' && pendingConnectionRewire) {
      cancelConnectionRewire();
      event.preventDefault();
      return;
    }
    if (event.key === 'Escape' && pendingRoleWire) {
      cancelRoleWire();
      event.preventDefault();
      return;
    }
    if (event.key === 'Escape' && pendingWire) {
      const wire=pendingWire; pendingWire=null;
      wire.preview.remove();
      markWireTargets();
      wire.output.releasePointerCapture?.(wire.pointerId);
      if (window.__archhubPointerOwner?.owner === 'universal-wire') {
        window.__archhubPointerOwner=null;
      }
      event.preventDefault();
      return;
    }
    const editing=event.target.closest?.(
      'input,textarea,select,[contenteditable="true"]');
    if (
      !editing && !event.repeat
      && (event.key === 'Delete' || event.key === 'Backspace')
      && lastProjection
    ) {
      const relation=lastProjection.selected_relation?.id;
      const detachable=relation && lastProjection.wires.find(
        wire => wire.id === relation && !wire.nary
          && typeof wire.disconnect_control === 'string');
      if (detachable) {
        event.preventDefault(); event.stopPropagation();
        try {
          await executeTopologyInteraction(
            detachable.disconnect_control);
        } catch (error) {
          showInteractionStatus(
            error.message || 'The connection could not be detached.');
        }
        return;
      }
    }
    const tab=event.target.closest?.(
      '[role="tab"][data-universal-properties-panel]');
    if (!tab) return;
    const tabs=Array.from(tab.closest('[role="tablist"]')?.querySelectorAll(
      '[role="tab"][data-universal-properties-panel]') || []);
    if (!tabs.length) return;
    const current=tabs.indexOf(tab);
    let next=current;
    if (event.key === 'ArrowRight') next=(current+1)%tabs.length;
    else if (event.key === 'ArrowLeft') next=(current-1+tabs.length)%tabs.length;
    else if (event.key === 'Home') next=0;
    else if (event.key === 'End') next=tabs.length-1;
    else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      tab.click();
      return;
    } else return;
    event.preventDefault();
    tabs[next].focus({preventScroll:true});
  });
  document.addEventListener('keydown', event => {
    const control=event.target.closest?.(
      '.canvas-toolbar button[data-universal-control]');
    if (!control) return;
    const buttons=[...control.closest('[role="toolbar"]')?.querySelectorAll(
      'button[data-universal-control]') || []];
    if (!buttons.length) return;
    const current=buttons.indexOf(control);
    let next=current;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      next=(current+1)%buttons.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      next=(current-1+buttons.length)%buttons.length;
    } else if (event.key === 'Home') {
      next=0;
    } else if (event.key === 'End') {
      next=buttons.length-1;
    } else {
      return;
    }
    event.preventDefault();
    buttons.forEach((button,index) => { button.tabIndex=index === next ? 0 : -1; });
    buttons[next].focus({preventScroll:true});
  });
  document.addEventListener('keydown', async event => {
    const card=event.target.closest?.(
      '[data-universal-root][role="button"]');
    if (!card || !lastProjection ||
        (event.key !== 'Enter' && event.key !== ' ')) return;
    if (event.target !== card) return;
    event.preventDefault();
    const root=card.dataset.universalRoot;
    if (
      event.key === 'Enter'
      && card.dataset.universalOpenable === 'True'
    ) {
      await navigateScope(card);
      return;
    }
    const roots=new Set(lastProjection.selection);
    if (event.shiftKey) roots.delete(root);
    else if (event.ctrlKey || event.metaKey) roots.add(root);
    else { roots.clear(); roots.add(root); }
    const chosen=Array.from(roots);
    const focus=roots.has(root) ? root : chosen.at(-1);
    // Selection is a view fact. Painting it locally FIRST and letting the
    // signed commit land behind the paint is the difference between a
    // click that answers now and one that waits ~0.5s for a projection
    // it already knows the shape of (SPEC 11.14 asks for 0.150s). The
    // commit still happens, still signed, and its answer still
    // reconciles -- a refusal repaints from the server, so the graph
    // remains the authority for what is selected.
    localCanvasSelection(chosen,focus);
    commit({roots:chosen,focus}).catch(() => {
      if (lastProjection) render(lastProjection);
    });
  });
  document.addEventListener('dragstart', event => {
    const primitive=event.target.closest('[data-universal-primitive]');
    if (primitive && event.dataTransfer) {
      event.dataTransfer.effectAllowed='copy';
      event.dataTransfer.setData(
        'application/x-archhub-primitive',primitive.dataset.universalPrimitive);
      return;
    }
    const definition=event.target.closest('[data-universal-definition]');
    if (!definition || !event.dataTransfer) return;
    event.dataTransfer.effectAllowed='copy';
    event.dataTransfer.setData(
      'application/x-archhub-definition',definition.dataset.universalDefinition);
  });
  document.addEventListener('dragover', event => {
    if (!event.target.closest('.canvas') || !event.dataTransfer) return;
    const types=Array.from(event.dataTransfer.types);
    if (!types.includes('application/x-archhub-definition') &&
        !types.includes('application/x-archhub-primitive')) return;
    event.preventDefault();
    event.dataTransfer.dropEffect='copy';
  });
  document.addEventListener('drop', async event => {
    const canvas=event.target.closest('.canvas');
    if (!canvas || !event.dataTransfer) return;
    const definition=event.dataTransfer.getData(
      'application/x-archhub-definition');
    const primitive=event.dataTransfer.getData(
      'application/x-archhub-primitive');
    if (!definition && !primitive) return;
    event.preventDefault();
    if (primitive) {
      const control=[...document.querySelectorAll(
        '[data-universal-primitive]')].find(
          item => item.dataset.universalPrimitive === primitive);
      if (!control) {
        throw new Error('Dragged primitive placement control is missing');
      }
      await instantiatePrimitiveAt(control,event.clientX,event.clientY);
    } else {
      const place=[...document.querySelectorAll(
        '[data-universal-definition-place]')].find(
          control => control.dataset.universalDefinitionPlace === definition);
      if (!place) {
        throw new Error('Dragged library placement control is missing');
      }
      await instantiateAt(place,event.clientX,event.clientY);
    }
  });

  document.addEventListener('pointerdown', event => {
    const socket=event.target.closest(
      '[data-universal-relation-role],[data-universal-relation-incidence]');
    if (
      !socket || socket.dataset.existingOnly === 'true'
      || event.button !== 0 || !lastProjection
    ) return;
    const port=projectedRolePort(socket);
    if (!port || port.mode === 'relation-role' && !port.editable) return;
    const items=Array.isArray(port.items) ? port.items : [];
    const incidence=socket.dataset.universalRelationIncidence || null;
    let controlRoot=null;
    if (!incidence) {
      if (port.maximum == null || items.length < Number(port.maximum)) {
        controlRoot=port.append_control;
      } else if (Number(port.maximum) === 1 && items.length === 1) {
        controlRoot=items[0].replace_control;
      } else {
        return;
      }
    } else {
      controlRoot=items.find(item => item.incidence === incidence)
        ?.replace_control;
    }
    if (typeof controlRoot !== 'string' || !projectedInteraction(controlRoot)) {
      return;
    }
    const occupied=new Set(items.map(item => item.participant));
    const participantIndexes=new Map((port.choices || [])
      .map((choice,index) => [choice.id,index])
      .filter(([root]) => !occupied.has(root)));
    if (!participantIndexes.size) return;
    const canvas=socket.closest('.canvas');
    const stage=canvas?.querySelector('.canvas-stage');
    const layer=stage?.querySelector('.wire-layer');
    if (!canvas || !stage || !layer) return;
    const active=window.__archhubPointerOwner;
    if (active && (active.owner !== 'universal-role-wire'
        || active.pointerId !== event.pointerId)) return;
    window.__archhubPointerOwner={
      owner:'universal-role-wire',pointerId:event.pointerId
    };
    event.preventDefault(); event.stopPropagation();
    const preview=svgElement('path',{
      class:'wire-line universal-wire-preview',
      'data-universal-role-preview':'true',
    });
    layer.append(preview);
    bindProjectedInteraction(socket,controlRoot);
    pendingRoleWire={
      controlRoot,participantIndexes,
      choices:new Set(participantIndexes.keys()),preview,socket,canvas,
      fromRole:!incidence,pointerId:event.pointerId,
    };
    markRelationCandidates(participantIndexes.keys());
    socket.setPointerCapture?.(event.pointerId);
  });
  document.addEventListener('pointermove', event => {
    if (!pendingRoleWire || pendingRoleWire.pointerId !== event.pointerId) return;
    const wire=pendingRoleWire;
    const pointer=canvasPoint(event.clientX,event.clientY);
    const socket=socketPoint(
      wire.socket,wire.fromRole ? 'target' : 'source');
    wire.preview.setAttribute('d',wire.fromRole
      ? `M ${pointer.x} ${pointer.y} C ${pointer.x+80} ${pointer.y}, ${socket.x-80} ${socket.y}, ${socket.x} ${socket.y}`
      : `M ${socket.x} ${socket.y} C ${socket.x+80} ${socket.y}, ${pointer.x-80} ${pointer.y}, ${pointer.x} ${pointer.y}`);
  });
  document.addEventListener('pointerup', async event => {
    if (!pendingRoleWire || pendingRoleWire.pointerId !== event.pointerId) return;
    const wire=pendingRoleWire;
    const target=document.elementFromPoint(event.clientX,event.clientY)
      ?.closest('[data-universal-root]');
    const participant=target?.dataset.universalRoot;
    cancelRoleWire();
    if (!participant || !wire.choices.has(participant)) return;
    const participantIndex=wire.participantIndexes.get(participant);
    if (!Number.isSafeInteger(participantIndex)) return;
    try {
      await executeProjectedInteraction(
        wire.socket,null,{participantIndex});
    } catch (error) {
      showInteractionStatus(
        error.message || 'The relation contract rejected this participant.');
    }
  });
  document.addEventListener('pointercancel', event => {
    if (!pendingRoleWire || pendingRoleWire.pointerId !== event.pointerId) return;
    cancelRoleWire();
  });

  document.addEventListener('pointerdown', event => {
    const output=event.target.closest('[data-universal-output]');
    if (!output || output.dataset.existingOnly === 'true' || event.button !== 0) return;
    const sourceNode=lastProjection?.nodes.find(
      node => node.id === output.dataset.universalOutput);
    const sourcePort=sourceNode?.ports.find(
      port => port.id === output.dataset.universalInterface);
    const choices=sourcePort?.connect_choices;
    if (typeof sourcePort?.connect_control !== 'string'
        || !Array.isArray(choices) || !choices.length) return;
    const direct=sourcePort.connect_control === 'direct:connect';
    const canvas=output.closest('.canvas');
    const stage=canvas?.querySelector('.canvas-stage');
    const layer=stage?.querySelector('.wire-layer');
    if (!canvas || !stage || !layer) return;
    const active=window.__archhubPointerOwner;
    if (active && (active.owner !== 'universal-wire' ||
        active.pointerId !== event.pointerId)) return;
    window.__archhubPointerOwner={owner:'universal-wire',pointerId:event.pointerId};
    event.preventDefault(); event.stopPropagation();
    const preview=svgElement('path',{class:'wire-line universal-wire-preview'});
    layer.append(preview);
    pendingWire={
      source:output.dataset.universalOutput,
      sourceInterface:sourcePort.name,
      control:sourcePort.connect_control,
      direct,
      directTargets:direct
        ? new Map(choices.map(choice => [choice.id,choice.interface]))
        : null,
      candidateIndexes:new Map(choices.map((choice,index) => [choice.id,index])),
      preview,output,canvas,pointerId:event.pointerId
    };
    markWireTargets(direct
      ? new Set(choices.map(choice => 'decl:'+choice.id+':'+choice.interface))
      : new Set(pendingWire.candidateIndexes.keys()));
    output.setPointerCapture?.(event.pointerId);
  });
  document.addEventListener('pointermove', event => {
    if (!pendingWire || !lastProjection) return;
    if (pendingWire.pointerId !== event.pointerId) return;
    const sourceCard=pendingWire.output.closest('[data-universal-root]');
    if (!sourceCard) return;
    const source=socketPoint(pendingWire.output);
    const target=canvasPoint(event.clientX,event.clientY);
    pendingWire.preview.setAttribute('d',
      `M ${source.x} ${source.y} C ${source.x+80} ${source.y}, ${target.x-80} ${target.y}, ${target.x} ${target.y}`);
  });
  document.addEventListener('pointerup', async event => {
    if (!pendingWire) return;
    if (pendingWire.pointerId !== event.pointerId) return;
    const wire=pendingWire; pendingWire=null;
    const target=document.elementFromPoint(event.clientX,event.clientY)
      ?.closest('[data-universal-input]');
    wire.preview.remove();
    wire.output.releasePointerCapture?.(event.pointerId);
    markWireTargets();
    if (window.__archhubPointerOwner?.owner === 'universal-wire' &&
        window.__archhubPointerOwner.pointerId === event.pointerId) {
      window.__archhubPointerOwner=null;
    }
    if (!target || target.dataset.universalInput === wire.source) return;
    if (wire.direct) {
      // A declared-socket wire: one explicit relation between the two
      // nodes, made by the signed connect command; the fresh projection
      // draws it like every other wire.
      const targetNode=target.dataset.universalInput;
      const targetInterface=wire.directTargets.get(targetNode)
        ?? target.dataset.interfaceLabel
        ?? target.dataset.universalInterface;
      try {
        const projection=await universalMutation(
          '/api/universal/connect',() => ({
            source:wire.source,
            source_interface:wire.sourceInterface,
            target:targetNode,
            target_interface:String(targetInterface || ''),
          }));
        if (projection) render(projection);
      } catch (error) {
        showInteractionStatus(
          error.message || 'The governed connect was rejected.');
      }
      return;
    }
    const candidateIndex=wire.candidateIndexes.get(
      target.dataset.universalInterface);
    if (!Number.isSafeInteger(candidateIndex)) return;
    try {
      await executeTopologyInteraction(
        wire.control,candidateIndex);
    } catch (error) {
      showInteractionStatus(
        error.message || 'The connection contract rejected this wire.');
    }
  });
  document.addEventListener('pointercancel', event => {
    if (!pendingWire || pendingWire.pointerId !== event.pointerId) return;
    const wire=pendingWire; pendingWire=null;
    wire.preview.remove();
    wire.output.releasePointerCapture?.(event.pointerId);
    markWireTargets();
    if (window.__archhubPointerOwner?.owner === 'universal-wire' &&
        window.__archhubPointerOwner.pointerId === event.pointerId) {
      window.__archhubPointerOwner=null;
    }
  });

  document.addEventListener('pointerdown', event => {
    const handle=event.target.closest('[data-universal-rewire-incidence]');
    if (!handle) return;
    if (
      handle.dataset.focused !== 'True'
      || event.button !== 0 || !lastProjection
    ) return;
    const incidence=handle.dataset.universalRewireIncidence;
    const currentInterface=handle.dataset.universalRewireInterface;
    const side=handle.dataset.universalRewireSide;
    const fixedInterface=handle.dataset.universalRewireFixedInterface;
    const fixedNode=handle.dataset.universalRewireFixedNode;
    if (!incidence || !currentInterface || !fixedNode) return;
    const projectedWire=lastProjection.wires.find(wire => (
      wire.id === handle.dataset.universalRewireRelation
      && String(wire.segment) === handle.dataset.universalRewireSegment
    ));
    const control=projectedWire?.[side+'_rewire_control'];
    const choices=projectedWire?.[side+'_rewire_choices'];
    if (typeof control !== 'string' || !Array.isArray(choices)) return;
    const fixedSocket=[...document.querySelectorAll(
      '.canvas [data-universal-interface]')].find(port =>
        port.dataset.universalInterface === fixedInterface)
      || [...document.querySelectorAll('.canvas [data-universal-root]')]
        .find(card => card.dataset.universalRoot === fixedNode);
    const layer=handle.closest('.wire-layer');
    if (!fixedSocket || !layer) return;
    const active=window.__archhubPointerOwner;
    if (active && (active.owner !== 'universal-rewire'
        || active.pointerId !== event.pointerId)) return;
    window.__archhubPointerOwner={
      owner:'universal-rewire',pointerId:event.pointerId
    };
    event.preventDefault(); event.stopPropagation();
    const preview=svgElement('path',{
      class:'wire-line universal-wire-preview',
      'data-universal-rewire-preview':'true',
    });
    layer.append(preview);
    pendingConnectionRewire={
      incidence,currentInterface,side,fixedSocket,preview,handle,control,
      candidateIndexes:new Map(choices.map((choice,index) => [choice.id,index])),
      pointerId:event.pointerId,
    };
    handle.dataset.dragging='True';
    markConnectionRewireTargets(
      side,currentInterface,new Set(pendingConnectionRewire.candidateIndexes.keys()));
    handle.setPointerCapture?.(event.pointerId);
  });
  document.addEventListener('pointermove', event => {
    if (
      !pendingConnectionRewire
      || pendingConnectionRewire.pointerId !== event.pointerId
    ) return;
    const wire=pendingConnectionRewire;
    const pointer=canvasPoint(event.clientX,event.clientY);
    const fixed=socketPoint(
      wire.fixedSocket,wire.side === 'source' ? 'target' : 'source');
    const source=wire.side === 'source' ? pointer : fixed;
    const target=wire.side === 'target' ? pointer : fixed;
    wire.handle.setAttribute('cx',String(pointer.x));
    wire.handle.setAttribute('cy',String(pointer.y));
    wire.preview.setAttribute('d',
      `M ${source.x} ${source.y} C ${source.x+80} ${source.y}, ${target.x-80} ${target.y}, ${target.x} ${target.y}`);
  });
  document.addEventListener('pointerup', async event => {
    if (
      !pendingConnectionRewire
      || pendingConnectionRewire.pointerId !== event.pointerId
    ) return;
    const wire=pendingConnectionRewire;
    const selector=wire.side === 'source'
      ? '[data-universal-output]' : '[data-universal-input]';
    const target=document.elementFromPoint(event.clientX,event.clientY)
      ?.closest(selector);
    const participant=target?.dataset.universalInterface;
    const candidateIndex=wire.candidateIndexes.get(participant);
    cancelConnectionRewire();
    window.__archhubGestureUntil=Date.now()+180;
    if (!participant || participant === wire.currentInterface
        || !Number.isSafeInteger(candidateIndex)) return;
    try {
      await executeTopologyInteraction(
        wire.control,candidateIndex);
    } catch (error) {
      showInteractionStatus(
        error.message || 'The connection contract rejected this endpoint.');
    }
  });
  document.addEventListener('pointercancel', event => {
    if (
      !pendingConnectionRewire
      || pendingConnectionRewire.pointerId !== event.pointerId
    ) return;
    cancelConnectionRewire();
  });
  document.addEventListener('change', async event => {
    if (projectionReconciliationDepth > 0) return;
    // A rail field edit: the input's ui-key names the property row,
    // the row names its owner and label, and the gesture path signs
    // the same revise-instance the stem runner lands answers with.
    const railInput=event.target.closest('.inspector .property-input');
    const uiKey=railInput?.dataset?.uiKey || '';
    if (railInput && uiKey.startsWith('property-input:') && lastProjection) {
      const rowKey=uiKey.slice('property-input:'.length);
      const row=(lastProjection.properties || []).find(item => (
        item.relation === rowKey));
      if (row && row.editable && row.owner && row.label) {
        const answer=await universalMutation('/api/universal/gesture',
          () => ({property:{
            owner:row.owner,label:row.label,value:railInput.value,
          }}));
        if (answer) render(answer);
        return;
      }
    }
    const contractRole=event.target.closest('[data-universal-contract-role]');
    if (contractRole && lastProjection) {
      if (!contractRole.dataset.universalInteraction) {
        throw new Error('Relation participant Interaction is missing');
      }
      await executeProjectedInteraction(
        contractRole,interactionDeltaMode,{
          participantIndex:contractRole.selectedIndex,
        });
      return;
    }
    const property=event.target.closest(
      '[data-universal-event-fact-input][data-universal-control]');
    if (property) {
      await executeProjectedInteraction(property); return;
    }
    const incidence=event.target.closest('[data-universal-incidence]');
    if (incidence) {
      const relation=lastProjection?.selected_relation;
      const endpoint=[relation?.source,relation?.target].find(item => (
        item?.incidence === incidence.dataset.universalIncidence));
      const matches=(endpoint?.rewire_choices || []).map(
        (choice,index) => ({choice,index})).filter(item => (
          item.choice.id === incidence.value));
      if (typeof endpoint?.rewire_control !== 'string' || matches.length !== 1) {
        throw new Error('Projected topology endpoint is ambiguous');
      }
      await executeTopologyInteraction(
        endpoint.rewire_control,matches[0].index);
    }
  });
  document.addEventListener('keydown', event => {
    // A key dispatched at the document itself has no element target, and
    // Element.closest on it is a crash that takes every later listener's
    // work down with it. No element under the key means none of these
    // branches apply.
    if (!(event.target instanceof Element)) return;
    // Delete takes the selected cards off the canvas. The graph keeps
    // their history; the scope simply stops holding them.
    if (
      (event.key === 'Delete' || event.key === 'Backspace')
      && !event.target.closest('input,textarea,select')
      && lastProjection?.selection?.length
    ) {
      event.preventDefault();
      const removing=[...lastProjection.selection];
      universalMutation('/api/universal/gesture',() => ({delete:removing}))
        .then(answer => { if (answer) render(answer); })
        .catch(error => showInteractionStatus(String(error.message || error)));
      return;
    }
    if (
      (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'g'
      && !event.target.closest('input,textarea,select') && lastProjection
    ) {
      event.preventDefault();
      const operation=event.shiftKey ? 'ungroup' : 'group';
      const control=zoneControls('canvas-toolbar').find(candidate =>
        candidate.activation.capability === controlCapabilities.composition
        && candidate.activation.arguments?.operation === operation);
      const action=control ? [...document.querySelectorAll(
        '.canvas-toolbar [data-control-binding]')].find(button =>
          button.dataset.controlBinding === control.activation.binding) : null;
      action?.click();
      return;
    }
    const scopedInput=event.target.closest?.(
      '[data-universal-event-fact-input]');
    const scopedAction=scopedInput?.closest(
      '[data-universal-interaction-scope]')?.querySelector(
        'button[data-universal-control]');
    if (scopedAction && event.key === 'Enter') {
      event.preventDefault();
      scopedAction.click();
      return;
    }
    const relationFormInput=event.target.closest(
      '[data-universal-relation-form-field]');
    if (relationFormInput && event.key === 'Enter') {
      event.preventDefault();
      relationFormInput.closest('[data-universal-relation-form]')?.querySelector(
        '[data-universal-relation-form-submit]')?.click();
    }
  });
  document.addEventListener('mouseover', event => {
    const card=event.target.closest('[data-universal-root]');
    if (!card || card.contains(event.relatedTarget)) return;
    document.querySelectorAll('[data-universal-relation]').forEach(wire => {
      wire.dataset.hoverContext=(
        wire.dataset.sourceNode === card.dataset.universalRoot ||
        wire.dataset.targetNode === card.dataset.universalRoot) ? 'True' : 'False';
    });
  });
  document.addEventListener('mouseout', event => {
    const card=event.target.closest('[data-universal-root]');
    if (!card || card.contains(event.relatedTarget)) return;
    document.querySelectorAll('[data-universal-relation]').forEach(wire => {
      delete wire.dataset.hoverContext;
    });
  });

  // The Cell page owns its direct-manipulation loop.  It deliberately works
  // only from projected root/interface identities and commits one graph
  // mutation when a gesture finishes; pointer feedback stays local.
  function localCanvasSelection(roots,focus) {
    const canvas=document.querySelector('.canvas');
    if (!canvas) return;
    const selected=new Set(roots);
    canvas.dataset.selection=JSON.stringify([...selected]);
    const index=canvasElementIndexFor(canvas);
    const cards=index ? [...index.nodes.values()]
      : [...canvas.querySelectorAll('[data-universal-root]')];
    cards.forEach(card => {
      const isSelected=selected.has(card.dataset.universalRoot);
      card.dataset.selected=isSelected ? 'True' : 'False';
      card.dataset.focused=(card.dataset.universalRoot === focus)
        ? 'True' : 'False';
      card.setAttribute('aria-selected',isSelected ? 'true' : 'false');
    });
  }
  function visibleCanvasSelection(canvas) {
    const allowed=new Set((lastProjection?.nodes || []).map(node => node.id));
    try {
      const roots=JSON.parse(canvas.dataset.selection || '[]');
      if (!Array.isArray(roots)) throw new Error('selection is not an array');
      return new Set(roots.filter(root => (
        typeof root === 'string' && allowed.has(root))));
    } catch (_) {
      return new Set((lastProjection?.selection || []).filter(
        root => allowed.has(root)));
    }
  }
  function selectionWithModifiers(base,roots,event) {
    const result=new Set(base);
    if (event.shiftKey) roots.forEach(root => result.delete(root));
    else if (event.ctrlKey || event.metaKey) roots.forEach(root => result.add(root));
    else return new Set(roots);
    return result;
  }
  function gestureFocus(roots,preferred) {
    return roots.has(preferred) ? preferred : [...roots].at(-1);
  }
  function scheduleCanvasMotion(callback) {
    pendingCanvasMotion=callback;
    if (canvasMotionFrame) return;
    canvasMotionFrame=requestAnimationFrame(() => {
      canvasMotionFrame=0;
      const pending=pendingCanvasMotion; pendingCanvasMotion=null;
      pending?.();
    });
  }
  function flushCanvasMotion() {
    if (canvasMotionFrame) cancelAnimationFrame(canvasMotionFrame);
    canvasMotionFrame=0;
    const pending=pendingCanvasMotion; pendingCanvasMotion=null;
    pending?.();
  }
  function hideCanvasMarquee() {
    const box=document.querySelector('.canvas .selection-box');
    if (!box) return;
    box.style.display='none';
    box.style.width='0px';
    box.style.height='0px';
  }
  function marqueeSelection(canvas,left,right,top,bottom,crossing) {
    const hits=[];
    canvas.querySelectorAll('[data-universal-root]').forEach(card => {
      const rect=card.getBoundingClientRect();
      const contained=rect.left >= left && rect.right <= right
        && rect.top >= top && rect.bottom <= bottom;
      const intersects=rect.right >= left && rect.left <= right
        && rect.bottom >= top && rect.top <= bottom;
      if ((crossing ? intersects : contained) && card.dataset.universalRoot) {
        hits.push(card.dataset.universalRoot);
      }
    });
    return hits;
  }
  function paintCanvasMarquee(gesture,clientX,clientY) {
    const {canvas,box}=gesture;
    const left=Math.min(gesture.startX,clientX);
    const right=Math.max(gesture.startX,clientX);
    const top=Math.min(gesture.startY,clientY);
    const bottom=Math.max(gesture.startY,clientY);
    const parent=box.offsetParent || canvas;
    const parentRect=parent.getBoundingClientRect();
    const scrollLeft=parent.scrollLeft || 0;
    const scrollTop=parent.scrollTop || 0;
    gesture.moved=gesture.moved
      || Math.abs(clientX-gesture.startX) > interactionPolicy().drag_threshold_px
      || Math.abs(clientY-gesture.startY) > interactionPolicy().drag_threshold_px;
    const crossing=clientX < gesture.startX;
    box.style.display='block';
    box.style.left=(left-parentRect.left+scrollLeft)+'px';
    box.style.top=(top-parentRect.top+scrollTop)+'px';
    box.style.width=Math.max(1,right-left)+'px';
    box.style.height=Math.max(1,bottom-top)+'px';
    box.dataset.mode=crossing ? 'crossing' : 'window';
    gesture.roots=selectionWithModifiers(
      gesture.base,marqueeSelection(canvas,left,right,top,bottom,crossing),
      gesture.event);
    gesture.focus=[...gesture.roots].at(-1);
    localCanvasSelection(gesture.roots,gesture.focus);
  }
  function resetCanvasGesture(gesture,{restore=false}={}) {
    if (!gesture) return;
    if (gesture.kind === 'drag' && restore) {
      gesture.origins.forEach(origin => {
        origin.card.style.left=origin.left+'px';
        origin.card.style.top=origin.top+'px';
        origin.card.classList.remove('is-moving');
      });
      const segments=wireSegmentsForNodes(
        gesture.canvas,gesture.origins.map(origin => origin.root));
      if (segments.size) requestAnimationFrame(() => redraw(segments));
    }
    if (gesture.kind === 'pan' && restore) {
      applyViewport(gesture.canvas,gesture.viewport);
    }
    if (gesture.kind === 'marquee') hideCanvasMarquee();
    if (restore && lastProjection) {
      localCanvasSelection(lastProjection.selection,lastProjection.selected);
    }
    gesture.capture?.releasePointerCapture?.(gesture.pointerId);
    if (window.__archhubPointerOwner?.owner === 'universal-canvas'
        && window.__archhubPointerOwner.pointerId === gesture.pointerId) {
      window.__archhubPointerOwner=null;
    }
  }
  function cancelPendingCanvasSelectionCommit() {
    if (!pendingCanvasSelectionCommit) return;
    clearTimeout(pendingCanvasSelectionCommit.timer);
    pendingCanvasSelectionCommit=null;
  }
  function deferOpenableCanvasSelection(payload) {
    cancelPendingCanvasSelectionCommit();
    const projection=lastProjection;
    if (!projection) return;
    const revision=projection.revision;
    const scope=projection.scope?.current;
    const delay=interactionPolicy(projection).gesture_suppression_ms;
    const pending={revision,scope,payload,timer:0};
    pending.timer=setTimeout(async () => {
      if (pendingCanvasSelectionCommit !== pending) return;
      pendingCanvasSelectionCommit=null;
      if (
        lastProjection?.revision !== revision
        || lastProjection?.scope?.current !== scope
      ) return;
      await commit(payload);
    },delay);
    pendingCanvasSelectionCommit=pending;
  }
  function startCanvasGesture(kind,event,details) {
    const active=window.__archhubPointerOwner;
    if (active && active.pointerId !== event.pointerId) return null;
    window.__archhubPointerOwner={
      owner:'universal-canvas',pointerId:event.pointerId,
    };
    const gesture={kind,pointerId:event.pointerId,...details};
    canvasGesture=gesture;
    gesture.capture?.setPointerCapture?.(event.pointerId);
    return gesture;
  }
  function isCanvasManipulationTarget(target) {
    return Boolean(target.closest(
      'button,input,select,textarea,[data-universal-interface],'
      + '[data-universal-rewire-incidence],[data-universal-relation]'));
  }
  document.addEventListener('pointerdown', event => {
    const canvas=event.target.closest('.canvas[data-universal="true"]');
    if (!canvas || !lastProjection || canvasGesture) return;
    if (isCanvasManipulationTarget(event.target)) return;
    const panRequested=event.button === 1
      || (event.button === 0 && canvasSpaceDown);
    if (panRequested) {
      event.preventDefault();
      startCanvasGesture('pan',event,{
        canvas,capture:canvas,startX:event.clientX,startY:event.clientY,
        viewport:{...lastProjection.viewport},
      });
      return;
    }
    if (event.button !== 0) return;
    const card=event.target.closest('[data-universal-root]');
    if (card) {
      const root=card.dataset.universalRoot;
      const base=visibleCanvasSelection(canvas);
      let roots;
      if (event.shiftKey || event.ctrlKey || event.metaKey) {
        roots=selectionWithModifiers(base,[root],event);
      } else {
        roots=base.has(root) ? base : new Set([root]);
      }
       const focus=gestureFocus(roots,root);
       localCanvasSelection(roots,focus);
       const modifierSelection=Boolean(
         event.shiftKey || event.ctrlKey || event.metaKey);
       const origins=[...canvas.querySelectorAll('[data-universal-root]')]
         .filter(candidate => roots.has(candidate.dataset.universalRoot))
        .map(candidate => ({
          card:candidate,
          root:candidate.dataset.universalRoot,
          left:parseFloat(candidate.style.left)||0,
          top:parseFloat(candidate.style.top)||0,
        }));
      event.preventDefault();
       startCanvasGesture('drag',event,{
         canvas,capture:card,startX:event.clientX,startY:event.clientY,
         roots,focus,origins,zoom:lastProjection.viewport.zoom,moved:false,
         modifierSelection,
       });
      return;
    }
    const box=canvas.querySelector('.selection-box');
    if (!box) return;
    event.preventDefault();
    const base=visibleCanvasSelection(canvas);
    startCanvasGesture('marquee',event,{
      canvas,capture:canvas,box,startX:event.clientX,startY:event.clientY,
      base,roots:new Set(base),
      focus:lastProjection.selected,moved:false,
      event:{shiftKey:event.shiftKey,ctrlKey:event.ctrlKey,metaKey:event.metaKey},
    });
  });
  document.addEventListener('pointermove', event => {
    const gesture=canvasGesture;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const clientX=event.clientX,clientY=event.clientY;
    scheduleCanvasMotion(() => {
      if (canvasGesture !== gesture) return;
      if (gesture.kind === 'pan') {
        gesture.nextViewport={
          pan_x:gesture.viewport.pan_x+clientX-gesture.startX,
          pan_y:gesture.viewport.pan_y+clientY-gesture.startY,
          zoom:gesture.viewport.zoom,
        };
        applyViewport(gesture.canvas,gesture.nextViewport);
        return;
      }
      if (gesture.kind === 'drag') {
        const dx=(clientX-gesture.startX)/gesture.zoom;
        const dy=(clientY-gesture.startY)/gesture.zoom;
        gesture.moved=gesture.moved
          || Math.abs(dx)+Math.abs(dy) > interactionPolicy().drag_threshold_px;
        if (!gesture.moved) return;
        gesture.origins.forEach(origin => {
          origin.card.classList.add('is-moving');
          origin.card.style.left=(origin.left+dx)+'px';
          origin.card.style.top=(origin.top+dy)+'px';
        });
        const segments=wireSegmentsForNodes(gesture.canvas,gesture.roots);
        if (segments.size) redraw(segments);
        return;
      }
      paintCanvasMarquee(gesture,clientX,clientY);
    });
  });
  document.addEventListener('pointerup', async event => {
    const gesture=canvasGesture;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    flushCanvasMotion();
    canvasGesture=null;
    try {
      if (gesture.kind === 'pan') {
        const viewport=gesture.nextViewport || gesture.viewport;
        resetCanvasGesture(gesture);
        await commit({viewport});
        return;
      }
      if (gesture.kind === 'drag') {
        const payload={roots:[...gesture.roots],focus:gesture.focus};
        if (gesture.moved) {
          payload.positions={};
          gesture.origins.forEach(origin => {
            origin.card.classList.remove('is-moving');
            payload.positions[origin.root]={
              x:parseFloat(origin.card.style.left),
              y:parseFloat(origin.card.style.top),
            };
          });
        }
         const deferSelection=(
           !gesture.moved
           && !gesture.modifierSelection
           && gesture.capture?.dataset?.universalOpenable === 'True'
         );
        resetCanvasGesture(gesture);
        if (deferSelection) {
          deferOpenableCanvasSelection(payload);
          return;
        }
        await commit(payload);
        return;
      }
      if (!gesture.moved && !gesture.event.shiftKey
          && !gesture.event.ctrlKey && !gesture.event.metaKey) {
        gesture.roots=new Set(); gesture.focus=undefined;
        localCanvasSelection(gesture.roots,gesture.focus);
      }
      hideCanvasMarquee();
      resetCanvasGesture(gesture);
      await commit({roots:[...gesture.roots],focus:gesture.focus});
    } catch (error) {
      showInteractionStatus(error.message || 'The canvas gesture was rejected.');
    }
  });
  document.addEventListener('pointercancel', event => {
    const gesture=canvasGesture;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    flushCanvasMotion(); canvasGesture=null;
    resetCanvasGesture(gesture,{restore:true});
  });
  document.addEventListener('dblclick', async event => {
    const card=event.target.closest(
      '.canvas[data-universal="true"] [data-universal-root][data-universal-openable="True"]');
    if (!card || !lastProjection) return;
    event.preventDefault(); event.stopPropagation();
    cancelPendingCanvasSelectionCommit();
    if (!card.dataset.universalInteraction) {
      showInteractionStatus('The composition scope is not available.');
      return;
    }
    try {
      await navigateScope(card);
    } catch (error) {
      showInteractionStatus(
        error.message || 'The composition scope could not be opened.');
    }
  });
  // The viewport the founder is LOOKING at, which is not the one the graph
  // has accepted yet: a commit is debounced, so five quick notches all
  // computed from the same committed zoom and overwrote each other. Zoom
  // compounds from what is on screen and settles into the graph once.
  let liveViewport=null;
  document.addEventListener('wheel', event => {
    const canvas=event.target.closest('.canvas[data-universal="true"]');
    if (!canvas || !lastProjection || event.target.closest('.canvas-toolbar')) return;
    event.preventDefault();
    const rect=canvas.getBoundingClientRect();
    const old=liveViewport || lastProjection.viewport;
    const raw=event.deltaY*(event.deltaMode === 1 ? 16
      : event.deltaMode === 2 ? rect.height : 1);
    const policy=interactionPolicy();
    const delta=Math.max(-policy.wheel_delta_cap,
      Math.min(policy.wheel_delta_cap,raw));
    const zoom=clampZoom(old.zoom*Math.exp(-delta*policy.wheel_sensitivity));
    const cursorX=event.clientX-rect.left;
    const cursorY=event.clientY-rect.top;
    const worldX=(cursorX-old.pan_x)/old.zoom;
    const worldY=(cursorY-old.pan_y)/old.zoom;
    const viewport={
      pan_x:cursorX-worldX*zoom,
      pan_y:cursorY-worldY*zoom,
      zoom,
    };
    liveViewport=viewport;
    applyViewport(canvas,viewport);
    clearTimeout(viewportCommitTimer);
    viewportCommitTimer=setTimeout(() => {
      const settled=liveViewport;
      liveViewport=null;
      if (settled) commit({viewport:settled});
    },policy.viewport_commit_debounce_ms);
  },{passive:false});
  document.addEventListener('keydown', async event => {
    const editing=event.target.closest?.('input,textarea,select,[contenteditable="true"]');
    if (event.code === 'Space' && !editing
        && !event.target.closest?.('[data-universal-root][role="button"]')) {
      canvasSpaceDown=true; event.preventDefault(); return;
    }
    if (event.key === 'Escape' && !editing) {
      if (canvasGesture) {
        const gesture=canvasGesture; canvasGesture=null;
        flushCanvasMotion(); resetCanvasGesture(gesture,{restore:true});
        event.preventDefault(); return;
      }
      if (lastProjection) {
        event.preventDefault(); await commit({roots:[]});
      }
      return;
    }
    if (!(event.ctrlKey || event.metaKey) || event.altKey || editing) return;
    const redo=(event.shiftKey && event.key.toLowerCase() === 'z')
      || (!event.shiftKey && event.key.toLowerCase() === 'y');
    const undo=!event.shiftKey && event.key.toLowerCase() === 'z';
    if (!undo && !redo) return;
    const control=document.querySelector(
      `[data-universal-history="${redo ? 'redo' : 'undo'}"]`);
    if (!control) return;
    event.preventDefault(); control.click();
  });
  document.addEventListener('keyup', event => {
    if (event.code === 'Space') canvasSpaceDown=false;
  });
  window.addEventListener('blur', () => { canvasSpaceDown=false; });
  window.addEventListener('resize',() => requestAnimationFrame(redraw));
  refresh();
  // The composer: name a node, press Enter, it lands in the middle of what
  // you are looking at. It places the SAME graph-held definition the library
  // places, through the same signed interaction -- typing is another way to
  // reach it, never a second way to create things.
  function composerMatch(query) {
    const wanted=String(query || '').trim().toLocaleLowerCase();
    if (!wanted || !lastProjection) return null;
    const items=lastProjection.catalog || [];
    return items.find(item =>
      String(item.name || '').toLocaleLowerCase() === wanted)
      || items.find(item =>
        String(item.name || '').toLocaleLowerCase().startsWith(wanted))
      || null;
  }
  function composerHint(text) {
    let hint=document.querySelector('.composer-hint');
    if (!hint) {
      const bar=document.querySelector('.canvas > .composer');
      if (!bar) return;
      hint=element('div','composer-hint');
      bar.append(hint);
    }
    if (hint) hint.textContent=text || '';
  }
  document.addEventListener('input', event => {
    if (!event.target.closest('.composer-input')) return;
    const match=composerMatch(event.target.value);
    composerHint(
      !event.target.value.trim() ? ''
      : match ? 'Enter places ' + match.name
      : 'no node called that');
  });
  // Capture phase: a canvas listener upstream stops key propagation, and
  // the composer must answer the founder's Enter regardless.
  document.addEventListener('keydown', async event => {
    const box=event.target.closest('.composer-input');
    if (!box) return;
    if (event.key === 'Escape') { box.value=''; composerHint(''); box.blur(); return; }
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const match=composerMatch(box.value);
    if (!match) { composerHint('no node called that'); return; }
    const canvas=document.querySelector('.canvas');
    const viewport=lastProjection?.viewport;
    const middle=canvas && viewport ? {
      x:(canvas.clientWidth/2 - viewport.pan_x)/viewport.zoom,
      y:(canvas.clientHeight/2 - viewport.pan_y)/viewport.zoom,
    } : null;
    const control=document.createElement('button');
    bindProjectedInteraction(control,match.id);
    try {
      await executeProjectedInteraction(control,interactionDeltaMode,
        middle ? {placement:middle} : {});
      box.value='';
      composerHint('placed ' + match.name);
    } catch (error) {
      composerHint(String(error.message || error));
    }
  }, true);
})();
"""


def project_document(store, app_id, ui_root):
    app = store.nodes[app_id]
    theme = {name[6:]: store.pull(pid) for name, pid in app['params'].items()
             if name.startswith('theme:')}
    css = store.pull(app['params']['stylesheet'])
    variables = ''.join('--%s:%s;' % (name.replace('_', '-'), value)
                        for name, value in theme.items())
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>ArchHub</title><style>:root{%s}%s</style></head><body>%s'
            '<script>%s</script></body></html>'
            % (variables, css, project_ui(store, ui_root),
               CLIENT_SCRIPT + UNIVERSAL_CANVAS_SCRIPT))
