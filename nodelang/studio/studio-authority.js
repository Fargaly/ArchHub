/* Disposable Studio projection and transport over the existing signed authority. */
(function (global) {
  'use strict';
  const executeCapability = 'app:device-capability:execute';
  const fail = message => { throw new Error(message); };
  const text = value => typeof value === 'string' && value.length > 0;
  const revision = value => Number.isSafeInteger(value) && value >= 0;
  // The clean canvas sends a wire's properties as an object ({connection, reason,
  // relation_kind}); labelled rows are still read as before. Both render.
  const wireParameters = properties => Array.isArray(properties)
    ? properties.map(row => ({k: row.label, v: row.value, rel: row.relation}))
    : properties && typeof properties === 'object'
      ? Object.entries(properties).map(([label, value]) =>
        ({k: label, v: typeof value === 'string' ? value : JSON.stringify(value)}))
      : [];

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
          result: node.result || '', mutates: node.mutates === true,
          conversation_root: node.conversation_root || null, has_conversation: node.has_conversation === true,
          ins: ports.filter(port => port.side === 'target'),
          outs: ports.filter(port => port.side === 'source'),
          params: parameters.filter(row => row.k !== 'status'),
          openable: node.openable === true, composition: node.composition === true, memberCount: Number.isSafeInteger(node.member_count) ? node.member_count : null,
          group: typeof node.group === 'string' ? node.group : '', pinned: node.pinned === true,
          ...(typeof node.application === 'boolean' ? {application: node.application} : {}),
        };
      });
      const nodeIds = new Set(nodes.map(node => node.id));
      const wires = (canvas.wires || []).filter(wire =>
        nodeIds.has(wire.source) && nodeIds.has(wire.target)).map(wire => ({
          id: wire.id, from: [wire.source, wire.source_interface],
          to: [wire.target, wire.target_interface],
          params: wireParameters(wire.properties),
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
      // The clean canvas names the caller's own browser session in browser_sessions
      // (clean_visual_projection.py); the Studio reads authorization.session, the
      // desktop projection's name, and waited on "Loading your workspace" forever.
      const sessions = result.authorization?.browser_sessions;
      canvas = result.authorization && !text(result.authorization.session) && Array.isArray(sessions) &&
        sessions.length === 1 && text(sessions[0]?.root)
        ? {...result, authorization: {...result.authorization, session: sessions[0].root}} : result;
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

    // open: true only when a person navigates here; polls never set it.
    async function readWorkshop(root, before = null, open = false) {
      const scope = canvas?.root, graph = identity, epoch = scopeEpoch;
      if (!snapshot?.workshops.some(row => row.root === root)) fail('This Workshop is no longer on the canvas.');
      if (!pageTarget || pageTarget.root !== root || pageTarget.before !== before) {
        pageTarget = {root, before}; pageEpoch += 1; workshop = null; project();
      }
      const pageStamp = pageEpoch;
      const current = () => scopeEpoch === epoch && canvas.root === scope && identity === graph &&
        snapshot.workshops.some(row => row.root === root) && pageStamp === pageEpoch &&
        pageTarget?.root === root && pageTarget.before === before;
      const key = JSON.stringify([epoch, pageStamp, root, before, open === true]);
      if (workshopReads.has(key)) return workshopReads.get(key);
      const previous = workshop?.root === root && !workshop.error ? workshop : null;
      const ordinary = previous?.storage === 'conversation-content';
      const operation = (async () => {
        try {
          const result = await get('/api/universal/workshop?root=' + encodeURIComponent(root) +
            '&scope=' + encodeURIComponent(scope) + (before === null ? '' : '&before=' + encodeURIComponent(before)) +
            (previous ? '&after=' + previous.revision : '') +
            (ordinary ? '&content_after=' + encodeURIComponent(previous.content_cursor) : '') +
            (open === true ? '&open=1' : ''));
          if (!current()) return null;
          if (!result || result.ok === false) fail(result?.error || 'Workshop history could not be read.');
          if (result.graph_id !== graph || result.root !== root || result.scope_root !== scope ||
              !revision(result.revision) || result.revision < canvas.revision ||
              (previous && result.revision < previous.revision)) fail('The Workshop response is stale or belongs to another scope.');
          const content = result.storage === 'conversation-content';
          if (content && (!text(result.content_cursor) || result.page_before !== before)) fail('Workshop history returned an invalid page.');
          if (result.unchanged) {
            if (!previous || (!content && result.revision !== previous.revision) || content !== ordinary ||
                (content && (result.content_cursor !== previous.content_cursor ||
                  result.page_before !== previous.page_before))) fail('Workshop history needs a full refresh.');
            // A graph write that adds no message (an assignment) moves the revision
            // while the page holds: republish the revision and what the page carries,
            // as the desktop transport does (3a6bf6ba), instead of refusing it.
            if (result.assignments !== undefined && !Array.isArray(result.assignments)) fail('Workshop assignments are invalid.');
            if (result.participants !== undefined && (!Array.isArray(result.participants) ||
                result.participants.some(row => !row || !text(row.root) || typeof row.label !== 'string' ||
                  typeof row.attached !== 'boolean'))) fail('Workshop participant status is invalid.');
            const carried = {
              ...(result.assignments !== undefined ? {assignments:result.assignments} : {}),
              ...(result.participants !== undefined ? {participants:result.participants} : {}),
            };
            if (result.revision === previous.revision && Object.keys(carried).every(name =>
                JSON.stringify(previous[name] ?? null) === JSON.stringify(carried[name]))) return previous;
            workshop = {...previous, revision:result.revision, ...carried}; project(); return workshop;
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
          // The messages feed's ACTIVITY panel: the newest tool records, bounded by the server.
          if (result.activity !== undefined && (!content || !Array.isArray(result.activity) || result.activity.length > 8 ||
              result.activity.some((row, index, rows) => !row || !text(row.root) || typeof row.body !== 'string' ||
                Array.from(row.body).length > 240 || typeof row.sender_root !== 'string' || typeof row.created_at !== 'string' ||
                !Number.isSafeInteger(row.sequence) || row.sequence < 1 ||
                (index > 0 && row.sequence <= rows[index - 1].sequence)))) fail('Workshop activity is invalid.');
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
      openWorkshop: root => readWorkshop(root, pageTarget?.root === root ? pageTarget.before : null, true),
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
      moveMany(positions, expectedRevision = canvas?.revision, expectedPositions = null, placement = null) {
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
            expected_positions:bases, projection_revision:canvas.revision,
            ...(placement === 'arrange' ? {placement:'arrange'} : {})});
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
          // One Run route for both Studios; here it carries the signed Run control.
          return post('/api/universal/run-graph', request);
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
      // Group or ungroup through the graph's own composition control (the toolbar's "Group selection"):
      // the roots become the graph selection, then the one applicable control of that operation runs.
      composition(operation, roots) {
        if (operation !== 'group' && operation !== 'ungroup') fail('Only group and ungroup are composition operations.');
        const held = [...new Set((roots || []).filter(root => typeof root === 'string' && root))];
        if (operation === 'group' && held.length < 2) fail('A group needs at least two nodes.');
        if (operation === 'ungroup' && held.length !== 1) fail('Expand one group at a time.');
        const intent = ++focusIntent;
        wantedFocus = held[0];
        project();
        return enqueue(() => {
          held.forEach(root => node(root));
          return post('/api/universal/focus', {expected_scope: canvas.root, scope_root: canvas.root,
            selected_roots: held, primary_root: held[0], revision: canvas.revision, command_id: uuid()});
        }).then(() => enqueue(() => {
          const controls = canvas.configuration?.design_system?.control_catalog?.controls || [];
          const matches = controls.filter(control => control.applicable && control.activation?.arguments?.operation === operation);
          if (matches.length !== 1) fail(operation === 'group' ? 'Group is not available for these nodes.' : 'Expand is not available for this group.');
          return post('/api/universal/interaction', binding(matches[0].owner));
        })).then(result => {
          if (intent === focusIntent) { wantedFocus = result.selected; project(); }
          return result;
        }).catch(reason => {
          if (intent === focusIntent) { wantedFocus = canvas.selected; project(); }
          throw reason;
        });
      },
      open(root) {
        const intent = ++focusIntent;
        return enqueue(() => {
          const request = binding(root);
          // A lease that names its acknowledgement mode is answered in that mode; a clean lease names
          // none and its scope route reads none, so nothing is added or defaulted for it.
          if (text(request.acknowledgement_mode)) request.projection_mode = request.acknowledgement_mode;
          return post('/api/universal/interaction', request);
        }, {navigation: true})
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
    // The probe below proves the held token only (a read needs no CSRF), so a held
    // pair without its CSRF is never kept, and a CSRF refusal later signs in again.
    if (session && !(session.token && session.csrf)) session = null;
    // Browser sessions expire (about an hour). Every Studio call that the server refuses
    // with an expired/drifted session is signed in again once and retried, instead of
    // surfacing "browser session expired or not yet valid" and leaving the app dead.
    const rawFetch = global.fetch.bind(global);
    let renewing = null;
    const sessionRefusal = /browser session|session lease|credential digest|browser-session/i;
    global.fetch = async (input, init) => {
      const response = await rawFetch(input, init);
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const given = (init && init.headers) || {};
      const headersIn = {};
      if (typeof given.forEach === 'function' && !Array.isArray(given)) given.forEach((v, k) => { headersIn[k] = v; });
      else Object.assign(headersIn, Array.isArray(given) ? Object.fromEntries(given) : given);
      const headerGet = name => { const k = Object.keys(headersIn).find(x => x.toLowerCase() === name.toLowerCase()); return k ? headersIn[k] : null; };
      const headerSet = (name, value) => { Object.keys(headersIn).filter(x => x.toLowerCase() === name.toLowerCase()).forEach(x => delete headersIn[x]); headersIn[name] = value; };
      if (response.status !== 403 || !/\/api\//.test(url) || headerGet('X-ArchHub-Sign-In')) return response;
      let text = '';
      try { text = await response.clone().text(); } catch (_) {}
      if (!sessionRefusal.test(text)) return response;
      try {
        renewing = renewing || signIn().finally(() => { renewing = null; });
        await renewing;
      } catch (_) { return response; }
      // Only reads are retried. A refused write is never replayed (it may have had an
      // effect before a later binding check failed); the session is renewed so the
      // user's next attempt succeeds.
      const method = String((init && init.method) || (typeof input !== 'string' && input && input.method) || 'GET').toUpperCase();
      if (method !== 'GET' && method !== 'HEAD') return response;
      headerSet('X-ArchHub-Session', session?.token || '');
      headerSet('X-ArchHub-CSRF', session?.csrf || '');
      const meta = global.document && global.document.querySelector('meta[name="archhub-csrf"]');
      if (meta && session?.csrf) meta.content = session.csrf;
      return rawFetch(input, {...(init || {}), headers: headersIn});
    };
    if (session) {
      const probe = await rawFetch('/api/universal/canvas', {headers: headers()});
      if (!probe.ok) session = null;
    }
    async function signIn() {
      const response = await rawFetch('/api/universal/session', {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-ArchHub-Sign-In': '1',
          'X-ArchHub-Canvas-Key': descriptor.canvas_key}, body: '{}'});
      if (!response.ok) fail('Studio sign-in was refused. Reopen the application from its launcher.');
      session = await response.json();
      try { global.sessionStorage.setItem('archhub.studio.session', JSON.stringify(session)); } catch (_) {}
      global.__archhubSession = session;
      return session;
    }
    if (!session) await signIn();
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
    // A held session the server refuses (403) is replaced once by a fresh sign-in.
    global.__archhubRenewSession = () => {
      try { global.sessionStorage.removeItem('archhub.studio.session'); } catch (_) {}
      return signIn();
    };
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
        // A state the Chats panel knows (LM_STATE_META): 'ready' is not one, and
        // opening Chats blanked the hosted Studio. A held workspace reads as saved.
        file: 'Revision ' + state.canvas.revision, last: state.graph.nodes.length + ' nodes', state: 'idle'}]};
    return api;
  }
  global.ArchHubStudioAuthority = {create, boot};
})(typeof window === 'undefined' ? globalThis : window);
