/* Disposable Studio projection and transport over the existing signed authority. */
(function (global) {
  'use strict';
  const executeCapability = 'app:device-capability:execute';
  const fail = message => { throw new Error(message); };
  const text = value => typeof value === 'string' && value.length > 0;
  const revision = value => Number.isSafeInteger(value) && value >= 0;

  function create({get, post, uuid = () => global.crypto.randomUUID(), pendingStorage,
      hash = async value => Array.from(new Uint8Array(await global.crypto.subtle.digest('SHA-256',
        new TextEncoder().encode(value))), byte => byte.toString(16).padStart(2, '0')).join('')}) {
    let canvas = null, snapshot = null, tail = Promise.resolve(), pending = 0;
    let error = '', wantedFocus, identity = null, focusIntent = 0;
    let workshop = null, scopeEpoch = 0, pageEpoch = 0, pageTarget = null;
    let workshopNotice = '';
    const listeners = new Set();
    const unresolvedRuns = new Map();
    const workshopReads = new Map();

    function project() {
      if (!canvas) return;
      const nodes = canvas.nodes.map(node => {
        const ports = (node.ports || []).map(port => ({
          id: port.id, label: port.name, t: port.value_type || '',
          name: port.name, connectable: port.connectable === true,
          side: port.side, multiple: port.multiple,
        }));
        const parameters = (node.properties || []).map(row => ({
          k: row.label, v: row.value, rel: row.relation,
          owner: row.owner || node.id, editable: row.editable,
          type: row.editor || 'text', constraints: row.constraints || {},
          min: row.constraints?.minimum, max: row.constraints?.maximum,
          opts: row.constraints?.options,
        }));
        return {
          id: node.id, definition_revision_root: node.definition_revision_root,
          cat: node.category || 'Definitions', title: node.label,
          sub: node.summary || node.assembly || '', x: node.x, y: node.y,
          w: 220, h: Math.max(110, 54 + ports.length * 20), live: true,
          color: node.resolved_color || node.color, status: node.status || '',
          ins: ports.filter(port => port.side === 'target'),
          outs: ports.filter(port => port.side === 'source'),
          params: parameters.filter(row => row.k !== 'status'),
          openable: node.openable === true,
        };
      });
      const nodeIds = new Set(nodes.map(node => node.id));
      const wires = (canvas.wires || []).filter(wire =>
        nodeIds.has(wire.source) && nodeIds.has(wire.target)).map(wire => ({
          id: wire.id, from: [wire.source, wire.source_interface],
          to: [wire.target, wire.target_interface],
          params: (wire.properties || []).map(row => ({k: row.label, v: row.value, rel: row.relation})),
        }));
      const groups = new Map();
      for (const entry of canvas.catalog || []) {
        const cat = entry.category || 'Definitions';
        if (!groups.has(cat)) groups.set(cat, {cat, items: []});
        groups.get(cat).items.push({
          id: entry.id, definition: entry.id, revision_root: entry.revision_root,
          title: entry.name, sub: entry.description || '', cat,
          interface_contract: entry.interface_contract, parameters: entry.parameters,
          defaults: entry.defaults, composition_contract: entry.composition_contract,
        });
      }
      const workshops = (canvas.workshops || []).filter(row =>
        row.root === canvas.root || nodeIds.has(row.root));
      if (pageTarget && !workshops.some(row => row.root === pageTarget.root)) {
        pageEpoch += 1; pageTarget = null; workshop = null;
      }
      if (workshop && (workshop.scope_root !== canvas.root ||
          !workshops.some(row => row.root === workshop.root))) workshop = null;
      snapshot = {canvas, graph: {nodes, wires}, library: [...groups.values()], workshops, workshop,
        workshopPage:pageTarget, workshopNotice,
        selected: wantedFocus === undefined ? canvas.selected : wantedFocus,
        pending, error};
      listeners.forEach(notify => notify());
    }

    function accept(result, expectedScope, navigation = false) {
      if (!result || result.ok === false) fail(result?.error || 'The graph refused this action.');
      if (!Number.isInteger(result.revision) || !result.root || !result.graph_id || !Array.isArray(result.nodes)) {
        fail('The runtime did not return an authoritative canvas.');
      }
      if (identity && result.graph_id !== identity) fail('The response belongs to another application.');
      if (!navigation && expectedScope && result.root !== expectedScope) fail('The response belongs to another scope. Refresh before continuing.');
      if (canvas && result.revision < canvas.revision) fail('The response is older than the displayed graph.');
      identity = result.graph_id;
      if (canvas && (canvas.root !== result.root || result.revision > (workshop?.revision ?? canvas.revision))) {
        pageEpoch += 1; pageTarget = null; workshop = null;
      }
      if (canvas && canvas.root !== result.root) scopeEpoch += 1;
      canvas = result;
      project();
      return result;
    }

    function enqueue(action, {navigation = false} = {}) {
      const scope = canvas?.root;
      pending += 1;
      project();
      const work = tail.then(async () => {
        if (scope && canvas.root !== scope) fail('The scope changed while this action was waiting.');
        const result = await action();
        error = '';
        return accept(result, scope, navigation);
      }).catch(reason => {
        error = reason?.message || String(reason);
        throw reason;
      }).finally(() => { pending -= 1; project(); });
      // A refused action remains refused to its caller; it does not poison the queue.
      tail = work.catch(() => {});
      return work;
    }

    function binding(control) {
      const found = (canvas.interaction_projection?.bindings || []).filter(row => row.control === control);
      if (found.length !== 1) fail('This control has no current graph interaction. Refresh the canvas.');
      return {...found[0], expected_scope: canvas.root, revision: canvas.revision, command_id: uuid()};
    }

    function node(root) {
      return canvas.nodes.find(row => row.id === root) || fail('This node is no longer in the current scope.');
    }

    function propertyValue(row, value) {
      const type = row.constraints?.type;
      if (type === 'number' || type === 'integer' || (!type && row.editor === 'number')) {
        if (typeof value === 'string' && !value.trim()) fail('Enter a number before saving.');
        const number = typeof value === 'number' ? value : Number(value);
        if (!Number.isFinite(number) || (type === 'integer' && !Number.isInteger(number))) fail('Enter a valid ' + (type || 'number') + '.');
        return number;
      }
      if (type === 'boolean') {
        if (value === true || value === 'true') return true;
        if (value === false || value === 'false') return false;
        fail('Choose true or false.');
      }
      if ((type === 'list' || type === 'map') && typeof value === 'string') return JSON.parse(value);
      return value;
    }

    async function readWorkshop(root, before = null) {
      const scope = canvas?.root, graph = identity, epoch = scopeEpoch;
      if (!snapshot?.workshops.some(row => row.root === root)) fail('This Workshop is no longer on the canvas.');
      if (!pageTarget || pageTarget.root !== root || pageTarget.before !== before) {
        pageTarget = {root, before}; pageEpoch += 1; workshop = null; project();
      }
      const pageStamp = pageEpoch;
      const current = () => scopeEpoch === epoch && canvas.root === scope && identity === graph &&
        snapshot.workshops.some(row => row.root === root) && pageStamp === pageEpoch &&
        pageTarget?.root === root && pageTarget.before === before;
      const key = JSON.stringify([epoch, pageStamp, root, before]);
      if (workshopReads.has(key)) return workshopReads.get(key);
      const previous = workshop?.root === root && !workshop.error ? workshop : null;
      const ordinary = previous?.storage === 'conversation-content';
      const operation = (async () => {
        try {
          const result = await get('/api/universal/workshop?root=' + encodeURIComponent(root) +
            '&scope=' + encodeURIComponent(scope) + (before === null ? '' : '&before=' + encodeURIComponent(before)) +
            (previous ? '&after=' + previous.revision : '') +
            (ordinary ? '&content_after=' + encodeURIComponent(previous.content_cursor) : ''));
          if (!current()) return null;
          if (!result || result.ok === false) fail(result?.error || 'Workshop history could not be read.');
          if (result.graph_id !== graph || result.root !== root || result.scope_root !== scope ||
              !revision(result.revision) || result.revision < canvas.revision ||
              (previous && result.revision < previous.revision)) fail('The Workshop response is stale or belongs to another scope.');
          const content = result.storage === 'conversation-content';
          if (content && (!text(result.content_cursor) || result.page_before !== before)) fail('Workshop history returned an invalid page.');
          if (result.unchanged) {
            if (!previous || result.revision !== previous.revision || content !== ordinary ||
                (content && (result.content_cursor !== previous.content_cursor ||
                  result.page_before !== previous.page_before))) fail('Workshop history needs a full refresh.');
            return previous;
          }
          if (!Array.isArray(result.messages) || !Array.isArray(result.participants) ||
              result.messages.length > 100 || (!content && before !== null)) fail('Workshop history is invalid.');
          if (content && ((!text(result.next_before) && result.next_before !== null) ||
              (result.next_before !== null && result.next_before === before) ||
              typeof result.has_older !== 'boolean' || result.has_older !== (result.next_before !== null) ||
              !revision(result.total) || result.total < result.messages.length ||
              result.messages.some((row, index, rows) => !row || !text(row.root) ||
                typeof row.body !== 'string' || !Number.isSafeInteger(row.sequence) || row.sequence < 1 ||
                (index > 0 && row.sequence <= rows[index - 1].sequence)) ||
              new Set(result.messages.map(row => row.root)).size !== result.messages.length)) fail('Workshop history is invalid.');
          workshop = {...result, error:''}; project(); return workshop;
        } catch (reason) {
          if (!current()) return null;
          workshop = {root, scope_root:scope, messages:[], participants:[],
            ...(ordinary || before !== null ? {storage:'conversation-content',page_before:before} : {}),
            error:reason?.message || String(reason)};
          project(); throw reason;
        }
      })();
      workshopReads.set(key, operation);
      try { return await operation; } finally { if (workshopReads.get(key) === operation) workshopReads.delete(key); }
    }

    const api = {
      getSnapshot: () => snapshot,
      subscribe(notify) { listeners.add(notify); return () => listeners.delete(notify); },
      async workshopAction(root, action, commandId, details = {}) {
        const scope = canvas?.root, graph = identity, epoch = scopeEpoch;
        if (!snapshot?.workshops.some(row => row.root === root)) fail('This Workshop is no longer on the canvas.');
        let storage, pendingKey, records;
        if (!commandId) {
          if (!workshop?.owner || !workshop?.view || workshop.root !== root) fail('Refresh the Workshop before sending.');
          storage = pendingStorage || global.sessionStorage;
          if (!storage) fail('Session storage is required to preserve pending Workshop actions.');
          pendingKey = await hash(JSON.stringify({graph, owner:workshop.owner, view:workshop.view,
            root, action, target:details.target || '', message:details.message || '',
            execution_root:details.execution_root || ''}));
          if (scopeEpoch !== epoch || canvas.root !== scope || identity !== graph) fail('The workspace changed before sending.');
          records = JSON.parse(storage.getItem('archhub.workshop.pending.v1') || '{}');
          if (!records || Array.isArray(records) || typeof records !== 'object' ||
              Object.entries(records).some(([key, value]) => !/^[a-f0-9]{64}$/.test(key) ||
                typeof value !== 'string' || !value || value.length > 128)) fail('Pending Workshop records need recovery.');
          if (!records[pendingKey] && Object.keys(records).length >= 32) fail('Reconcile pending Workshop actions before creating more.');
          commandId = records[pendingKey] || uuid();
          records[pendingKey] = commandId;
          // Only a request digest and opaque ID persist; no message or credential.
          storage.setItem('archhub.workshop.pending.v1', JSON.stringify(records));
        }
        const result = await post('/api/universal/workshop', {...details,
          root, scope, action, command_id: commandId});
        if (result.ok === false) fail(result.error || 'The Workshop action was refused.');
        let warning = '';
        if (storage) {
          try {
            const current = JSON.parse(storage.getItem('archhub.workshop.pending.v1') || '{}');
            if (current[pendingKey] === commandId) delete current[pendingKey];
            storage.setItem('archhub.workshop.pending.v1', JSON.stringify(current));
          } catch (_) { warning = 'Action accepted. Pending request recovery could not be updated.'; }
        }
        const accepted = {...result, accepted:true, original_graph:graph, original_scope:scope, original_workshop:root, warning};
        if (scopeEpoch !== epoch || canvas.root !== scope || identity !== graph) {
          workshopNotice = 'Action accepted in the previous workspace. Open it to see the result.';
          project();
          return {...accepted, navigated:true};
        }
        workshopNotice = warning;
        // Reconcile the accepted action without waiting on an obsolete poll.
        pageEpoch += 1; pageTarget = {root, before:null}; workshop = null;
        project();
        await api.refreshWorkshop(root).catch(() => {});
        return accepted;
      },
      refreshWorkshop: root => readWorkshop(root, pageTarget?.root === root ? pageTarget.before : null),
      async loadOlderWorkshop(root) {
        if (workshop?.root !== root || workshop.error || workshop.storage !== 'conversation-content' ||
            !text(workshop.next_before)) fail('No older Workshop page is available.');
        return readWorkshop(root, workshop.next_before);
      },
      showLatestWorkshop: root => readWorkshop(root, null),
      load: () => enqueue(() => get('/api/universal/canvas')),
      create(spec) {
        const intent = ++focusIntent;
        return enqueue(() => {
          const entry = (canvas.catalog || []).find(row => row.id === spec.definition);
          if (!entry || !spec.definition_revision || entry.revision_root !== spec.definition_revision) fail('This definition changed or is no longer available. Refresh the library.');
          if (entry.composition_contract) fail('This definition requires participants in the composer before placement.');
          if (!Number.isFinite(spec.x) || !Number.isFinite(spec.y)) fail('Choose a valid canvas position.');
          return post('/api/universal/interaction', {...binding(entry.id),
            definition_revision: entry.revision_root,
            event_facts: [{source: 'canvas-point-x', value: spec.x}, {source: 'canvas-point-y', value: spec.y}],
          });
        }).then(result => {
          if (intent === focusIntent) { wantedFocus = result.selected; project(); }
          return result;
        });
      },
      select(root) {
        const intent = ++focusIntent;
        if (canvas?.selected === root && pending === 0) {
          wantedFocus = root;
          project();
          return Promise.resolve(canvas);
        }
        wantedFocus = root;
        project();
        return enqueue(() => {
          if (!canvas.nodes.some(row => row.id === root) && !(canvas.wires || []).some(row => row.id === root)) fail('This selection is no longer in the current scope.');
          return post('/api/universal/focus', {expected_scope: canvas.root, scope_root: canvas.root,
            selected_roots: [root], primary_root: root, revision: canvas.revision, command_id: uuid()});
        }).catch(reason => {
          if (intent === focusIntent) { wantedFocus = canvas.selected; project(); }
          throw reason;
        });
      },
      setProperty(root, label, value) {
        return enqueue(() => {
          const row = (node(root).properties || []).find(row => row.label === label);
          if (!row || row.editable !== true) fail('This parameter is not editable in the current scope.');
          return post('/api/universal/gesture', {expected_scope: canvas.root,
            property: {owner: root, label, value: propertyValue(row, value)}});
        });
      },
      move(root, position) {
        return enqueue(() => {
          node(root);
          if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) fail('The canvas position is invalid.');
          return post('/api/universal/gesture', {expected_scope: canvas.root,
            positions: {[root]: {x: position.x, y: position.y}}});
        });
      },
      moveMany(positions, expectedRevision = canvas?.revision, expectedPositions = null) {
        const scope = canvas?.root, graph = identity;
        const copy = Object.fromEntries(Object.entries(positions || {}).map(([root, point]) => [root, {
          x:Number.isFinite(point?.x) ? Math.trunc(point.x) : point?.x,
          y:Number.isFinite(point?.y) ? Math.trunc(point.y) : point?.y}]));
        const roots = Object.keys(copy);
        const bases = Object.fromEntries(Object.entries(expectedPositions ?? Object.fromEntries(roots.map(root => {
          const held = canvas?.nodes.find(row => row.id === root);
          return [root, {x:held?.x, y:held?.y}];
        }))).map(([root, point]) => [root, {x:point?.x, y:point?.y}]));
        return enqueue(async () => {
          if (!scope || canvas.root !== scope || identity !== graph) fail('The canvas scope changed before saving positions.');
          if (!revision(expectedRevision) || canvas.revision < expectedRevision) fail('The layout revision is invalid. Refresh the canvas.');
          if (!Object.keys(copy).length) fail('Choose nodes to arrange.');
          if (roots.length > 256 || Object.keys(bases).length !== roots.length) fail('The layout position bases are invalid.');
          for (const [root, point] of Object.entries(copy)) {
            const held = node(root), base = bases[root];
            if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) fail('The canvas position is invalid.');
            if (!Number.isFinite(base?.x) || !Number.isFinite(base?.y) || held.x !== base.x || held.y !== base.y) {
              fail('A moved node changed position. Refresh before arranging it again.');
            }
          }
          const result = await post('/api/universal/gesture', {expected_scope:scope, positions:copy,
            expected_positions:bases, projection_revision:canvas.revision});
          if (!Array.isArray(result?.nodes) || Object.entries(copy).some(([root, point]) => {
            const held = result.nodes.find(row => row.id === root);
            return !held || held.x !== point.x || held.y !== point.y;
          })) fail('The saved positions could not be confirmed. Refresh the canvas.');
          return result;
        });
      },
      connect(source, sourcePort, target, targetPort) {
        return enqueue(() => {
          const endpoint = (root, id, side) => {
            const port = (node(root).ports || []).find(row => row.id === id);
            if (!port || port.side !== side || port.connectable !== true || !port.name) fail('Choose an available output and input socket.');
            return port.name;
          };
          return post('/api/universal/connect', {expected_scope: canvas.root, source, target,
            source_interface: endpoint(source, sourcePort, 'source'),
            target_interface: endpoint(target, targetPort, 'target')});
        });
      },
      run() {
        let runKey;
        return enqueue(() => {
          if (wantedFocus && canvas.selected !== wantedFocus) fail('The selection has not been saved. Select the node again before running.');
          const controls = canvas.configuration?.design_system?.control_catalog?.controls || [];
          const matches = controls.filter(control => control.applicable && control.activation?.capability === executeCapability);
          if (matches.length !== 1) fail('Run is not available for this selection.');
          runKey = JSON.stringify([identity, canvas.root, canvas.selected]);
          const request = binding(matches[0].owner);
          const operation = node(canvas.selected).operation;
          const unresolved = unresolvedRuns.get(runKey);
          if (unresolved) {
            if (!unresolved.host) fail('The previous graph run has an unresolved result. Reconcile it before running again.');
            if (operation !== unresolved.operation) fail('The node operation changed while its previous run was unresolved. Reconcile that run first.');
            request.command_id = unresolved.command;
          } else {
            unresolvedRuns.set(runKey, {command: request.command_id, operation,
              host: typeof operation === 'string' && operation.trim().length > 0});
          }
          return post('/api/universal/interaction', request);
        }).then(result => {
          unresolvedRuns.delete(runKey);
          return result;
        }).catch(reason => {
          // A receipted failure is a known completed attempt. A transport or
          // uncertain failure retains its identity for a later reconciliation.
          if (reason?.outcome === 'failed' && reason?.receipt) unresolvedRuns.delete(runKey);
          throw reason;
        });
      },
      open(root) {
        const intent = ++focusIntent;
        return enqueue(() => post('/api/universal/interaction', binding(root)), {navigation: true})
          .then(result => {
            if (intent === focusIntent) { wantedFocus = result.selected; project(); }
            return result;
          });
      },
      undo() { return enqueue(() => post('/api/universal/gesture', {expected_scope: canvas.root, undo: true})); },
      remove(root) {
        const selected = api.select(root), intent = focusIntent;
        return selected.then(() => enqueue(() => post('/api/universal/gesture',
          {expected_scope: canvas.root, delete: [root]}))).then(result => {
            if (intent === focusIntent) { wantedFocus = result.selected; project(); }
            return result;
          });
      },
    };
    return api;
  }

  async function boot(descriptor) {
    let session = null;
    try { session = JSON.parse(global.sessionStorage.getItem('archhub.studio.session') || 'null'); } catch (_) {}
    const headers = () => ({'Content-Type': 'application/json',
      'X-ArchHub-Session': session?.token || '', 'X-ArchHub-CSRF': session?.csrf || ''});
    if (session) {
      const probe = await global.fetch('/api/universal/canvas', {headers: headers()});
      if (!probe.ok) session = null;
    }
    if (!session) {
      const response = await global.fetch('/api/universal/session', {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-ArchHub-Sign-In': '1',
          'X-ArchHub-Canvas-Key': descriptor.canvas_key}, body: '{}'});
      if (!response.ok) fail('Studio sign-in was refused. Reopen the application from its launcher.');
      session = await response.json();
      try { global.sessionStorage.setItem('archhub.studio.session', JSON.stringify(session)); } catch (_) {}
    }
    async function request(url, body) {
      const response = await global.fetch(url, {method: body === undefined ? 'GET' : 'POST',
        headers: headers(), ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const result = await response.json();
      if (!response.ok || result.ok === false) {
        const error = new Error(result.error || 'The graph refused this action.');
        if (result.outcome === 'failed' || result.outcome === 'uncertain') {
          error.outcome = result.outcome;
          error.receipt = result.receipt;
          error.effect = result.effect;
          error.revision = result.revision;
          error.replayed = result.replayed;
        }
        throw error;
      }
      return result;
    }
    const api = create({get: url => request(url), post: (url, body) => request(url, body)});
    await api.load();
    global.ARCHHUB_STUDIO_AUTHORITY = api;
    global.__archhubSession = session;
    global.ARCHHUB_GET_CANVAS = () => api.load();
    global.ARCHHUB_NODE_CREATE = spec => api.create(spec);
    global.ARCHHUB_SET_NODE_PROP = (root, label, value) => api.setProperty(root, label, value);
    let running = null;
    global.ARCHHUB_RUN = () => {
      if (running) return Promise.reject(new Error('A run is already in progress.'));
      running = Promise.resolve().then(async () => {
        if (typeof global.pmFlushParameters === 'function') await global.pmFlushParameters();
        const result = await api.run();
        global.ARCHHUB_LAST_RUN = result;
        return result;
      }).finally(() => { running = null; });
      return running;
    };
    global.ARCHHUB_RETRACT = root => api.remove(root);
    global.ARCHHUB_AGENT = async (prompt, model, node) =>
      (await request('/api/universal/agent', {prompt, model,
        expected_scope:api.getSnapshot()?.canvas?.root,
        ...(node !== undefined ? {node} : {})})).answer || 'done';
    const state = api.getSnapshot();
    global.ARCHHUB_LIVE = {graph: state.graph, library: state.library, hosts: [], connectors: [], memory: [], skills: [],
      sessions: [{id: state.canvas.root, title: state.canvas.scope?.current_label || 'Workspace',
        file: 'Revision ' + state.canvas.revision, last: state.graph.nodes.length + ' nodes', state: 'ready'}]};
    return api;
  }
  global.ArchHubStudioAuthority = {create, boot};
})(typeof window === 'undefined' ? globalThis : window);
