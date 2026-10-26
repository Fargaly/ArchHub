/* Disposable Studio projection and transport over the existing signed authority. */
(function (global) {
  'use strict';
  const executeCapability = 'app:device-capability:execute';
  const fail = message => { throw new Error(message); };
  const text = value => typeof value === 'string' && value.length > 0;
  const revision = value => Number.isSafeInteger(value) && value >= 0;
  // Both Studio boot paths use this one admitted remove-member command. A
  // collapsed member belongs to the group's projection, not canvas.nodes.
  async function removeMember({canvas, post, uuid, member, from_group, position = null, receipt = false}) {
    const group = canvas?.nodes?.find(row => row.id === from_group);
    if (!text(member) || !text(from_group) || !group ||
        !(group.members || []).some(row => row.id === member)) {
      fail('This member is no longer in the displayed group. Refresh the canvas.');
    }
    if (position && (!Number.isFinite(position.x) || !Number.isFinite(position.y))) {
      fail('The canvas position is invalid.');
    }
    const matches = (canvas.interaction_projection?.bindings || [])
      .filter(row => row.control === 'app:control:canvas:remove-member');
    if (matches.length !== 1 || !text(matches[0].interaction) || !text(matches[0].event) ||
        (receipt && matches[0].acknowledgement_mode !== 'receipt-v1')) {
      fail('Remove member has no current graph interaction. Refresh the canvas.');
    }
    const held = matches[0];
    const result = await post('/api/universal/interaction', {
      interaction:held.interaction, control:held.control, event:held.event,
      expected_scope:canvas.scope?.current || canvas.root, revision:canvas.revision, command_id:uuid(),
      ...(receipt ? {projection_mode:'receipt-v1'} : {}),
      membership:{member, from_group, to_group:'', ...(position ? {position} : {})},
    });
    if (!result || result.ok === false) fail(result?.error || 'The graph refused to remove this member.');
    const committed = receipt ? result.committed_revision : result.revision;
    if (!revision(committed) || committed <= canvas.revision) fail('The member removal needs reconciliation. Refresh the canvas.');
    if (!receipt) confirmMemberRemoved(canvas, result, member, from_group);
    return result;
  }
  function confirmMemberRemoved(before, after, member, from_group) {
    const oldGroup = before.nodes.find(row => row.id === from_group);
    const newGroup = after.nodes?.find(row => row.id === from_group);
    const oldCount = Number.isSafeInteger(oldGroup?.member_count) ? oldGroup.member_count : oldGroup?.members?.length;
    const remaining = (oldGroup?.members || []).filter(row => row.id !== member);
    const detached = after.nodes?.find(row => row.id === member);
    if (!detached || detached.group === from_group ||
        (newGroup && ((newGroup.members || []).some(row => row.id === member) ||
          newGroup.member_count !== oldCount - 1 || newGroup.members?.length !== oldCount - 1 ||
          remaining.some(row => !newGroup.members.some(saved => saved.id === row.id)))) ||
        (!newGroup && oldCount > 1)) {
      fail('The removed member is not visible in the refreshed graph. Refresh the canvas before trying again.');
    }
    return after;
  }
  // The clean canvas sends a wire's properties as an object ({connection, reason,
  // relation_kind}); labelled rows are still read as before. Both render.
  const wireParameters = properties => Array.isArray(properties)
    ? properties.map(row => ({k: row.label, v: row.value, rel: row.relation}))
    : properties && typeof properties === 'object'
      ? Object.entries(properties).map(([label, value]) =>
        ({k: label, v: typeof value === 'string' ? value : JSON.stringify(value)}))
      : [];
  const sessionSettingsFor = canvas => ({
      id: canvas.root,
      name: canvas.scope?.current_label || 'Workspace',
      model: canvas.configuration?.composer_model?.value ||
        canvas.configuration?.default_model?.route || canvas.configuration?.default_model || '',
      relay_mode: canvas.configuration?.relay_mode || canvas.configuration?.cloud_relay?.mode || 'local',
    });
  const sessionParamRows = settings => [
    {k:'name', v:settings.name, rel:'session-setting', editable:false, owner:settings.id, source:settings},
    {k:'model', get v() { return settings.model; }, set v(value) { settings.model = String(value || ''); },
      rel:'session-setting', editable:true, owner:settings.id, source:settings},
    {k:'relay mode', v:settings.relay_mode, rel:'session-setting', editable:false, owner:settings.id, source:settings},
  ];

  const interactionDeltaMode='interaction-delta-v1', topologyDeltaMode='topology-delta-v1';
  const interactionDeltaFields=[
    'action_history','topology_targets','workshop_scope',
    'revision','selected','selection','selected_title','focus','obligations',
    'authorization','catalog','scope','authoring','inspector','properties',
    'selected_relation',
    'selected_interface','selected_interfaces','viewport',
    'selected_definition','selected_assembly','physical',
    'interaction_projection','toolbar_descriptor','canvas_heading_descriptor',
    'canvas_signature',
  ];
  function mergeProjectionDelta(result,baseProjection) {
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
    const retained=new Set(['catalog','authorization',...(result.retained_fields||[])]);
    interactionDeltaFields.forEach(field => {
      if (retained.has(field) && !(field in result)) return;
      merged[field]=result[field];
    });
    if (result.interaction_projection && !('bindings' in result.interaction_projection)) {
      merged.interaction_projection={...baseProjection.interaction_projection,...result.interaction_projection};
    }
    if ('selected_relation_revision' in result) {
      if (!Number.isSafeInteger(result.selected_relation_revision) || !baseProjection.selected_relation)
        throw new Error('Selected relation revision is invalid');
      merged.selected_relation={...baseProjection.selected_relation,observed_revision:result.selected_relation_revision};
    }
    const historyPatch=result.action_history?.transactions_patch;
    if (historyPatch) {
      const held=baseProjection.action_history?.transactions;
      if (!Array.isArray(held) || held.length!==historyPatch.base_count ||
          !Number.isSafeInteger(historyPatch.remove) || historyPatch.remove<0 || historyPatch.remove>held.length ||
          !Array.isArray(historyPatch.prepend)) throw new Error('History patch does not cover the held history');
      const transactions=[...historyPatch.prepend,...held.slice(historyPatch.remove)];
      if (transactions.length!==historyPatch.count || transactions.some(row=>!text(row?.root)) || new Set(transactions.map(row=>row.root)).size!==transactions.length)
        throw new Error('History patch identities are invalid');
      merged.action_history={...result.action_history,transactions};
      delete merged.action_history.transactions_patch;
    }
    // The product canvas lens: a boolean and a count, sent only when they
    // change, so an absent field keeps the held value.
    ['selection_hidden','hidden_work_count'].forEach(field => {
      if (field in result) merged[field]=result[field];
    });
    merged.configuration={
      ...baseProjection.configuration,
      ...result.configuration_state,
      design_system:{
        ...baseProjection.configuration.design_system,
        control_catalog:result.control_state,
      },
    };
    // A positioned splice of the entries that changed, instead of the whole
    // 176KB catalogue, for the same reason the node patch stopped shipping
    // whole nodes: a change is not a reason to resend everything.
    if (Array.isArray(result.catalog_items)) {
      const held=baseProjection.catalog;
      if (!Array.isArray(held)
          || held.length !== Number(result.catalog_count)) {
        throw new Error('Catalogue patch does not cover the held catalogue');
      }
      const next=[...held];
      result.catalog_items.forEach(entry => {
        const index=Number(entry.index);
        if (!Number.isInteger(index) || index < 0 || index >= next.length) {
          throw new Error('Catalogue patch names an absent entry');
        }
        next[index]=entry.item;
      });
      merged.catalog=next;
    }
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
        const stateNodes=patch.state_nodes || [];
        const stateWires=patch.state_wires || [];
        if (!Array.isArray(stateNodes) || !Array.isArray(stateWires)) {
          throw new Error('Topology patch state channel is invalid');
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
        // A port's context is one boolean buried in a ten-kilobyte
        // descriptor. The server sends it as state; rebuild the descriptor
        // around it rather than making the server re-ship the node.
        stateNodes.forEach(state => {
          const held=nodes.get(state.id);
          if (!held) throw new Error('Topology state names an absent node');
          const next={...held,selected:state.selected,x:state.x,y:state.y};
          if (Array.isArray(state.port_context) && Array.isArray(held.ports)) {
            if (state.port_context.length !== held.ports.length) {
              throw new Error('Topology port context does not cover the ports');
            }
            next.ports=held.ports.map((port,index) => {
              const context=state.port_context[index];
              const descriptor=port.descriptor;
              if (!Array.isArray(descriptor) || !descriptor.length) return port;
              const head=descriptor[0];
              const attributes={...(head.attributes||{}),
                'data-context':context};
              return {...port,descriptor:[
                {...head,attributes},...descriptor.slice(1),
              ]};
            });
          }
          nodes.set(state.id,next);
        });
        stateWires.forEach(state => {
          const key=`${state.id}:${state.segment}`;
          const held=wires.get(key);
          if (!held) throw new Error('Topology state names an absent wire');
          wires.set(key,{...held,
            selected:state.selected,context:state.context});
        });
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
    // The state channel carries port context as a boolean per port; folding
    // it in as a bare field would leave a `port_context` key on the node and
    // the descriptor still stale. Rebuild the descriptor from it instead.
    const applyNodeState=(node,state) => {
      if (!state) return node;
      const {port_context:context,...plain}=state;
      const next={...node,...plain};
      if (Array.isArray(context) && Array.isArray(node.ports)
          && context.length === node.ports.length) {
        next.ports=node.ports.map((port,index) => {
          const descriptor=port.descriptor;
          if (!Array.isArray(descriptor) || !descriptor.length) return port;
          const head=descriptor[0];
          const attributes={...(head.attributes||{}),
            'data-context':context[index]};
          return {...port,descriptor:[
            {...head,attributes},...descriptor.slice(1),
          ]};
        });
      }
      return next;
    };
    merged.nodes=nodeStates.size || nodePatches.size
      ? baseProjection.nodes.map(node => (
          nodeStates.has(node.id) || nodePatches.has(node.id)
            ? applyNodeState(
                {...node,...nodePatches.get(node.id)},
                nodeStates.get(node.id))
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
      const baseNodes = canvas.nodes.map(node => {
        const ports = (node.ports || []).map(port => ({
          id: port.id, label: port.name, t: port.value_type || '',
          name: port.name, connectable: port.connectable === true,
          side: port.side, multiple: port.multiple,
        }));
        const parameters = (node.properties || []).map(row => ({
          k: row.label, v: row.value, rel: row.relation,
          label: row.display_label || row.label, value_root: row.value_root, cell_id:row.cell_id, setting: row.setting,
          owner: row.owner || node.id, editable: row.editable,
          type: row.editor || 'text', constraints: row.constraints || {},
          min: row.constraints?.minimum ?? row.constraints?.min, max: row.constraints?.maximum ?? row.constraints?.max,
          step: row.constraints?.step,
          opts: row.constraints?.options,
        }));
        return {
          id: node.id, definition_revision_root: node.definition_revision_root,
          cat: node.category || 'Definitions', title: node.label,
          sub: node.summary || node.assembly || '', assembly: node.assembly || '', kind: node.kind || node.assembly || '', x: node.x, y: node.y,
          subtitle: node.subtitle || '', actions: node.actions || [],
          liveState: node.state && typeof node.state === 'object' ? node.state : null,
          w: 220, h: Math.max(110, 54 + ports.length * 20), live: true,
          color: node.resolved_color || node.color, status: node.status || '',
          result: node.result || '', mutates: node.mutates === true,
          conversation_root: node.conversation_root || null, has_conversation: node.has_conversation === true,
          ins: ports.filter(port => port.side === 'target'),
          outs: ports.filter(port => port.side === 'source'),
          params: parameters.filter(row => row.k !== 'status'),
          openable: node.openable === true, composition: node.composition === true, memberCount: Number.isSafeInteger(node.member_count) ? node.member_count : null,
          members: Array.isArray(node.members) ? node.members.map(member => typeof member === 'string' ? {id:member, title:member} : member).filter(Boolean) : [],
          group: typeof node.group === 'string' ? node.group : '', pinned: node.pinned === true,
          ...(typeof node.application === 'boolean' ? {application: node.application} : {}),
        };
      });
      const nodeIds = new Set(baseNodes.map(node => node.id));
      const wires = (canvas.wires || []).filter(wire =>
        nodeIds.has(wire.source) && nodeIds.has(wire.target)).map(wire => ({
          id: wire.id, from: [wire.source, wire.source_interface],
          to: [wire.target, wire.target_interface],
          label: wire.label || wire.properties?.connection || wire.properties?.reason || '',
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
      const sessionSettings = sessionSettingsFor(canvas);
      const sessionNode = {
        id: sessionSettings.id, cat:'session', title:sessionSettings.name,
        sub:'Session container', assembly:'session', kind:'session',
        x:Number.isFinite(canvas.session_x) ? canvas.session_x : -280,
        y:Number.isFinite(canvas.session_y) ? canvas.session_y : -180,
        w:260, h:150, live:true, color:'#7dd3fc', status:'idle',
        result:canvas.projection === 'home' ? 'Open graph' : baseNodes.length + ' nodes', ins:[], outs:[], params:sessionParamRows(sessionSettings),
        openable:true, composition:false, memberCount:baseNodes.length,
        contains:[...new Set([...workshops.map(row => row.root), ...baseNodes.map(row => row.id)])],
        session_settings:sessionSettings,
      };
      const nodes = [sessionNode, ...baseNodes];
      if (pageTarget && !workshops.some(row => row.root === pageTarget.root)) {
        pageEpoch += 1; pageTarget = null; workshop = null;
      }
      if (workshop && (workshop.scope_root !== canvas.root ||
          !workshops.some(row => row.root === workshop.root))) workshop = null;
      const sessions = [{id:sessionSettings.id, title:sessionSettings.name, state:'idle',
        file:'Revision ' + canvas.revision, last:canvas.projection === 'home' ? 'Open graph' : baseNodes.length + ' nodes',
        model:sessionSettings.model, relay_mode:sessionSettings.relay_mode, settings:sessionSettings,
        node:sessionNode.id, contains:sessionNode.contains}];
      snapshot = {canvas, graph: {nodes, wires}, library: [...groups.values()], workshops, workshop, sessions,
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
      const epoch = scopeEpoch;
      pending += 1;
      project();
      const work = tail.then(async () => {
        if (epoch !== scopeEpoch || (scope && canvas?.root !== scope)) fail('The scope changed while this action was waiting.');
        const result = await action();
        if (epoch !== scopeEpoch) fail('The scope changed while this action was in flight.');
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
      const current={...found[0], expected_scope: canvas.root, revision: canvas.revision, command_id: uuid()};
      return current;
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
      clear() { canvas=null;snapshot=null;identity=null;workshop=null;pageTarget=null;wantedFocus=undefined;scopeEpoch++; },
      getSnapshot: () => snapshot,
      subscribe(notify) { listeners.add(notify); return () => listeners.delete(notify); },
      refreshWorkshop: root => readWorkshop(root, pageTarget?.root === root ? pageTarget.before : null),
      openWorkshop: root => readWorkshop(root, pageTarget?.root === root ? pageTarget.before : null, true),
      async loadOlderWorkshop(root) {
        if (workshop?.root !== root || workshop.error || workshop.storage !== 'conversation-content' ||
            !text(workshop.next_before)) fail('No older Workshop page is available.');
        return readWorkshop(root, workshop.next_before);
      },
      showLatestWorkshop: root => readWorkshop(root, null),
      adopt: (result, options) => enqueue(() => Promise.resolve(result), options),
      transact: action => enqueue(action),
      load: ({home = false, navigation = false, conditional = false} = {}) => enqueue(async () => {
        const result = await get('/api/universal/canvas' + (home ? '?screen=home' :
          conditional && canvas ? '?since_revision=' + canvas.revision : ''));
        if (result?.unchanged === true) {
          if (result.revision !== canvas?.revision || result.scope !== canvas.root || result.graph_id !== identity) {
            fail('The graph freshness response belongs to another scope.');
          }
          return canvas;
        }
        return result;
      }, {navigation}),
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
      select(root, roots = null) {
        const intent = ++focusIntent;
        const clearing = root === null && Array.isArray(roots) && roots.length === 0;
        const held = [...new Set((Array.isArray(roots) ? roots : [root]).filter(text))];
        if (!clearing && canvas?.selected === root && held.length === 1 && pending === 0 &&
            (!Array.isArray(canvas.selection) || (canvas.selection.length === 1 && canvas.selection[0] === root))) {
          wantedFocus = root;
          project();
          return Promise.resolve(canvas);
        }
        // Clearing the selected roots leaves the graph-held primary intact.
        wantedFocus = clearing ? undefined : root;
        project();
        return enqueue(async () => {
          if (clearing) {
            const result = await post('/api/universal/gesture', {expected_scope:canvas.root, roots:[], focus:null});
            if (!Array.isArray(result?.selection) || result.selection.length !== 0) {
              fail('The empty canvas selection needs reconciliation. Refresh the canvas.');
            }
            return result;
          }
          if (!canvas.nodes.some(row => row.id === root) && !(canvas.wires || []).some(row => row.id === root)) fail('This selection is no longer in the current scope.');
          if (held.some(heldRoot => !canvas.nodes.some(row => row.id === heldRoot) && !(canvas.wires || []).some(row => row.id === heldRoot))) fail('This selection is no longer in the current scope.');
          return post('/api/universal/focus', {expected_scope: canvas.root, scope_root: canvas.root,
            selected_roots: held.length ? held : [root], primary_root: root, revision: canvas.revision, command_id: uuid()});
        }).catch(reason => {
          if (intent === focusIntent) { wantedFocus = canvas.selected; project(); }
          throw reason;
        });
      },
      setProperty(root, label, value) {
        if (root === canvas.root && ['name', 'model', 'relay mode'].includes(label)) {
          if (label !== 'model') fail('This session setting is owned elsewhere and is read-only here.');
          const saveModel = global.ARCHHUB_AGENT_SELECT;
          const next = String(value || '');
          return enqueue(async () => {
            if (typeof saveModel === 'function') {
              const saved = await saveModel(next);
              if (saved !== next) fail('The model selection could not be confirmed. Refresh before editing again.');
            } else {
              const setting = canvas.configuration?.composer_model;
              if (!setting || setting.available !== true || !text(setting.control) || !text(setting.event_fact_input)) {
                fail('This connection cannot save a model selection.');
              }
              await post('/api/universal/interaction', {...binding(setting.control),
                event_facts:[{input:setting.event_fact_input, value:next}]});
            }
            return get('/api/universal/canvas');
          });
        }
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
            ...(!global.ARCHHUB_AUTHORITY ? {projection_mode:'interaction-delta-v1'} : {}),
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
          const output=endpoint(source, sourcePort, 'source'), input=endpoint(target, targetPort, 'target');
          const port=node(source).ports.find(row=>row.id===sourcePort);
          if (port.connect_control && port.connect_control !== 'direct:connect') {
            const choice=(port.connect_choices||canvas.topology_targets||[]).findIndex(row=>row.owner===target&&row.id===targetPort);
            if(choice<0 || !text(port.connect_event_fact_input))fail('Choose compatible sockets in the current graph.');
            return post('/api/universal/interaction', {...binding(port.connect_control),
              projection_mode:'topology-delta-v1',
              event_facts:[{input:port.connect_event_fact_input,value:choice}]});
          }
          return post('/api/universal/connect', {expected_scope: canvas.root, source, target,
            source_interface: output, target_interface: input});
        });
      },
      moveMember(member, from_group, to_group, position = null) {
        return enqueue(async () => {
          if (from_group && !to_group) {
            const before = canvas;
            const receipt = (canvas.interaction_projection?.bindings || []).some(row =>
              row.control === 'app:control:canvas:remove-member' && row.acknowledgement_mode === 'receipt-v1');
            const result = await removeMember({canvas:before, post, uuid, member, from_group, position, receipt});
            if (!receipt) return result;
            const latest = await get('/api/universal/canvas');
            if (!revision(latest?.revision) || latest.revision < result.committed_revision) {
              fail('The member change is not visible in the refreshed graph.');
            }
            return confirmMemberRemoved(before, latest, member, from_group);
          }
          node(member);
          if (from_group) node(from_group);
          if (to_group) node(to_group);
          const result = await post('/api/universal/gesture', {expected_scope: canvas.root,
            membership: {member, from_group:from_group || '', to_group:to_group || '',
              ...(position ? {position} : {})}});
          return result;
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
          return post('/api/universal/gesture', {expected_scope: canvas.root,
            roots: held, focus: held[0], command_id: uuid()});
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
      redo() { return enqueue(() => post('/api/universal/gesture', {expected_scope: canvas.root, redo: true})); },
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
      const probe = await rawFetch('/api/universal/boot', {headers: headers()});
      if (!probe.ok) session = null;
    }
    if (session) global.__archhubSession = session;
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
    await api.load({home:true});
    global.ARCHHUB_STUDIO_AUTHORITY = api;
    global.__archhubSession = session;
    // A held session the server refuses (403) is replaced once by a fresh sign-in.
    global.__archhubRenewSession = () => {
      try { global.sessionStorage.removeItem('archhub.studio.session'); } catch (_) {}
      return signIn();
    };
    global.ARCHHUB_GET_CANVAS = () => api.load();
    // Reuse the Studio's existing on-open library hook. Home does not load it.
    let libraryFlight = null;
    global.AH_LOAD_LIBRARY = (refresh = false) => {
      if (libraryFlight) return libraryFlight;
      if (global.AH_LIBRARY_LOADED && !refresh) return Promise.resolve(api.getSnapshot().library);
      global.AH_LIBRARY_LOADING = true;
      global.AH_LIBRARY_ERROR = '';
      libraryFlight = api.load().then(() => {
        global.AH_LIBRARY_LOADED = true;
        return api.getSnapshot().library;
      }).catch(error => {
        global.AH_LIBRARY_ERROR = error?.message || 'The node library is unavailable.';
        throw error;
      }).finally(() => {
        libraryFlight = null;
        global.AH_LIBRARY_LOADING = false;
        global.dispatchEvent?.(new Event('archhub:library-refresh'));
      });
      return libraryFlight;
    };
    global.ARCHHUB_NODE_CREATE = spec => api.create(spec);
    global.ARCHHUB_SET_NODE_PROP = async (root, label, value) => {
      const result = await api.setProperty(root, label, value);
      if (typeof global.__archhubRefreshCanvasInPlace === 'function') await global.__archhubRefreshCanvasInPlace();
      else await api.load();
      return result;
    };
    let running = null;
    global.ARCHHUB_RUN = () => {
      if (running) return Promise.reject(new Error('A run is already in progress.'));
      running = Promise.resolve().then(async () => {
        if (typeof global.pmFlushParameters === 'function') await global.pmFlushParameters();
        const result = await api.run();
        global.ARCHHUB_LAST_RUN = result;
        try { global.dispatchEvent(new Event('archhub-last-run')); } catch (_) {}
        return result;
      }).finally(() => { running = null; });
      return running;
    };
    global.ARCHHUB_RETRACT = root => api.remove(root);
    global.ARCHHUB_AGENT = async (prompt, model, options) => {
      const node = options && typeof options === 'object' && !Array.isArray(options) ? options.node : options;
      const graph = options && typeof options === 'object' && !Array.isArray(options) ? options.graph : undefined;
      const graphId = options && typeof options === 'object' && !Array.isArray(options) ? options.graph_id : undefined;
      const generation = options && typeof options === 'object' && !Array.isArray(options) ? options.generation : undefined;
      const requestId = options && typeof options === 'object' && !Array.isArray(options) ? options.request_id : undefined;
      const result = await request('/api/universal/agent', {prompt, model,
        expected_scope:api.getSnapshot()?.canvas?.root,
        ...(generation !== undefined ? {generation} : {}),
        ...(((typeof node === 'string' && node.trim()) || graph === true) && typeof requestId === 'string' && requestId.trim() ? {request_id:requestId} : {}),
        ...(graph === true ? {graph:true} : {}),
        ...(graph === true && typeof graphId === 'string' && graphId.trim() ? {graph_id:graphId} : {}),
        ...(typeof node === 'string' && node.trim() ? {node} : {})});
      return {...(result && typeof result === 'object' ? result : {}), answer:(result && result.answer) || 'done'};
    };
    const state = api.getSnapshot();
    global.ARCHHUB_LIVE = {graph: state.graph, library: state.library, hosts: [], connectors: [], memory: [], skills: [],
      // Session tabs and the session node share the same settings object from the projection.
      sessions: state.sessions || [{id: state.canvas.root, title: state.canvas.scope?.current_label || 'Workspace',
        file: 'Revision ' + state.canvas.revision, last: state.graph.nodes.length + ' nodes', state: 'idle'}]};
    return api;
  }
  global.ArchHubStudioAuthority = {create, boot, removeMember, confirmMemberRemoved, mergeProjectionDelta, requireUniqueProjectionIdentities};
})(typeof window === 'undefined' ? globalThis : window);
