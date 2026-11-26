// Menus stay anchored to the object. Dialogs are reserved for a decision/form.
(() => {
  // One owner for a node's Rerun and Fork (registry ids menu.rerun / menu.fork): the node menu and the Properties pane
  // call these same actions. Rerun is Run again (F10): again=true does not reuse cached step results.
  const NODE_COMMANDS = {'menu.rerun': n => api.runNode(n.id, true), 'menu.fork': n => api.forkNode(n.id)};
  (window.UI = window.UI || {}).nodeCommand = (id, n) => NODE_COMMANDS[id](n);
  window.UI.productLabel = window.UI.productLabel || (label => label);
  // COMMANDREGISTRY: both menu and palette use this bounded, data-only reader.
  const contextNames = {'Node menu':'node','Embed menu':'embed','Group menu':'group','Wire menu':'wire',
    'Port menu':'socket','Selection menu':'selection','Canvas menu':'canvas','Task tab menu':'session',
    'Open tasks':'session','Canvas attachments':'session','Task message menu':'message','Tray':'tray','App menu':'navigation'};
  function commandsForContext(registry, context, selection = {}, bindings = {}) {
    return registry.filter(command => command.contexts.includes(context) && bindings[command.id]
      && (!selection.readOnly || command.read_only)).flatMap(command => [].concat(bindings[command.id]).map(binding => {
      const rule = command.enabled_when;
      const disabled = binding.disabled || (rule?.fact && selection[rule.fact] === false ? rule.reason : false);
      return {...command, ...binding, label: binding.label || command.label, disabled,
        disabledReason: typeof disabled === 'string' ? disabled : disabled ? rule?.reason || 'This action is unavailable for the current selection.' : ''};
    })).sort((a,b) => (a.order || 0) - (b.order || 0));
  }
  function commandGroups(kind, groups) {
    const registry = window.ArchHubCommandRegistry.commands;
    return groups.map(rows => {
      const bindings = {};
      rows.forEach((row,index) => (bindings[row.id] ||= []).push({...row,order:index}));
      return commandsForContext(registry,contextNames[kind] || kind,{},bindings).map(row => {
        const tuple = [row.label,row.icon,(window.UI.shortcutFor?.(row.id)??row.shortcut),row.action,row.danger,row.disabledReason || row.disabled];
        tuple.command = row;
        return tuple;
      });
    }).filter(rows => rows.length > 0);
  }
  window.UI.commandsForContext = commandsForContext;
  window.UI.commandGroups = commandGroups;
  window.UI.commandContextNames = contextNames;
  function paletteCommands(s,u,api,{query='',mode='All',context=null,actionState=null}={}) {
    let contextual = [];
    if(context){
      contextual = (contextCommandGroups({...context,nodeId:context.id,close:u.close},s,u,actionState,context.more,
        more=>u.show('Search',{commandContext:{...context,more}})) || []).flat().map(row=>row.command)
        .filter(row=>(mode==='All'||row.group===mode)&&row.label.toLowerCase().includes(query.toLowerCase()));
      if (mode !== 'Workflows' && (mode !== 'All' || !query.trim())) return contextual;
    }
    const workflows = [...(s.templates || []).filter(t => !t.path).map(t => ({
      label: t.title,
      commandId: 'palette.template',
      action: async () => {
        const opened = await u.act(() => api.openTemplateGraph(t.id));
        if (opened && !opened.cancelled) await u.go('canvas');
      }
    })), ...(s.graphs || []).map(g => ({
      label: g.name || g.title || g.id,
      commandId: 'palette.graph',
      action: async () => {
        const opened = await u.act(() => api.selectGraph(g.id));
        if (!opened || opened.cancelled) return;
        if (g.path) await u.go('canvas', g.path);
        else await u.go('canvas');
      }
    }))];
    // A card the catalogue marks not available (no engine, or coming soon) cannot be added, so it is not offered here;
    // an agent session is a conversation record, not a skill, so it is not offered as a node either.
    const agentSessions = (s.templates || []).filter(t => t.kind === 'agent-session').map(t => t.id);
    const bindings = context ? workflows : [...workflows, ...s.catalogue.filter(c => !c.unavailable && !agentSessions.includes(c.id)).map(c => ({
        label: c.name,
        commandId: 'palette.add_node',
        action: async () => {
          await u.act(() => api.addNode(c.name));
          u.go('canvas');
        }
      })), ...s.tasks.map(t => ({
        label: t.title,
        commandId: 'palette.task',
        action: () => u.openTaskFile(t.id)
      })), ...(s.liveAgents || []).map(a => ({
        label: a.name + (a.task ? ' · ' + a.task : ''),
        commandId: 'palette.live_agent',
        action: () => u.go('workshop')
      })), ...(s.agents || []).filter(p => !(s.liveAgents || []).some(a => a.app === p.runtime)).map(p => ({
        label: p.name + ' · not joined',
        commandId: 'palette.agent',
        action: () => u.go('workshop')
      })), ...(s.hosts || []).map(h => ({
        label: h.name + (h.state ? ' · ' + ({absent: 'Not installed', unavailable: 'Not available', 'prerequisites-ready': 'Ready to connect', 'needs-sign-in': 'Needs sign-in', installed: 'Installed', connected: 'Connected', listening: 'Connected'}[h.state] || h.state) : ''),
        commandId: 'palette.host',
        action: () => u.go('connections')
      })), ...(s.pages || []).map(page => ({
        label: page,
        commandId: 'palette.setting',
        action: () => u.openSystem(page)
      })), ...Object.entries(window.ArchHubRouteNames).map(([r, label]) => ({
        label,
        commandId: 'page.' + r,
        action: () => u.go(r)
      })), {
        commandId: 'palette.mcp_tools',
        action: () => window.executeAction('projects.ds_library.MCPTools.10', {u})
      }, {
        commandId: 'palette.share_session',
        action: () => window.executeAction('projects.ds_library.ExportRecipe.8', {u})
      }];
    const registry=window.ArchHubCommandRegistry;
    const held={};
    for(const binding of bindings)(held[binding.commandId] ||= []).push(binding);
    const rows = commandsForContext(registry.commands,'palette',{},held).map(row=>({...row,group:row.paletteGroup || 'Pages'}))
      .filter(row=>(mode==='All'||row.group===mode)&&row.label.toLowerCase().includes(query.toLowerCase()))
      .sort((a,b)=>registry.palette_order.indexOf(a.group)-registry.palette_order.indexOf(b.group));
    return contextual.concat(rows);
  }
  window.UI.paletteCommands = paletteCommands;
  function declaredCommandGroups(selection,s,u,actionState) {
    const registry=window.ArchHubCommandRegistry, bindings={}, seen=new Set();
    const add=row=>{
      const key=row.id+'\0'+row.label;
      if(seen.has(key))return;
      seen.add(key);(bindings[row.id] ||= []).push(row);
    };
    for(const kind of Object.keys(contextNames))for(const more of [false,true]){
      const groups=contextCommandGroups({...selection,kind},s,u,actionState,more) || [];
      groups.flat().forEach(row=>add(row.command));
    }
    paletteCommands({catalogue:[],templates:[],tasks:[],...s},u,api).forEach(add);
    const groups=new Map();
    for(const row of commandsForContext(registry.commands,selection.kind,{},bindings)){
      if(!groups.has(row.group))groups.set(row.group,[]);
      groups.get(row.group).push(row);
    }
    return commandGroups(selection.kind,[...groups.values()]);
  }
  // COMMANDREGISTRY end
  const {
      api,
      useData,
      useApp
    } = window.UI,
    Icon = window.AHIcon;

  function threadIsShown(u) {
    if (!u || typeof u !== 'object') return false;
    const face = ('canvasFace' in u && typeof u.canvasFace === 'string' && u.canvasFace)
      || ('taskFace' in u && typeof u.taskFace === 'string' && u.taskFace) || '';
    return ['split', 'workshop', 'thread'].includes(face) || ('threadOpen' in u && u.threadOpen === true);
  }
  function setThreadFace(u, nextFace) {
    if (u && typeof u === 'object' && 'setCanvasFace' in u && typeof u.setCanvasFace === 'function') {
      u.setCanvasFace(nextFace);
      if ('setTaskFace' in u && typeof u.setTaskFace === 'function') u.setTaskFace(nextFace);
      return;
    }
    u.setTaskFace(nextFace);
  }
  function traceConnectedIds(graph, startId, direction) {
    const visited = new Set([startId]), queue = [startId], nodes = graph?.nodes || [], wires = graph?.wires || [];
    while (queue.length) {
      const current = queue.shift();
      for (const wire of wires) {
        const next = direction === 'back' ? (wire.to === current ? wire.from : null) : (wire.from === current ? wire.to : null);
        if (next && !visited.has(next) && nodes.some(row => row.id === next && !(row.fixed && row.type !== 'thing.session'))) {
          visited.add(next);
          queue.push(next);
        }
      }
    }
    return [...visited];
  }
  function groupMemberSteps(graph, rootGroup) {
    const seen = new Set(), out = [], nodes = graph?.nodes || [];
    const visit = groupNode => {
      for (const id of groupNode?.children || []) {
        if (seen.has(id)) continue;
        seen.add(id);
        const child = nodes.find(row => row.id === id);
        if (!child) continue;
        if (child.children?.length) visit(child);
        else if (!child.fixed) out.push(child);
      }
    };
    visit(rootGroup);
    return out;
  }
  function distributeSelectedNodes(graph, editable, apiOwner) {
    if (apiOwner && 'distributeNodes' in apiOwner && typeof apiOwner.distributeNodes === 'function') {
      return apiOwner.distributeNodes(editable);
    }
    const nodes = editable.map(id => (graph?.nodes || []).find(row => row.id === id)).filter(Boolean);
    if (nodes.length < 2) throw Error('Select at least 2 editable nodes to distribute evenly.');
    const xs = nodes.map(row => row.x ?? row.position?.x ?? 0), ys = nodes.map(row => row.y ?? row.position?.y ?? 0);
    const horizontal = (Math.max(...xs) - Math.min(...xs)) >= (Math.max(...ys) - Math.min(...ys));
    const sorted = [...nodes].sort((a, b) => horizontal
      ? ((a.x ?? a.position?.x ?? 0) - (b.x ?? b.position?.x ?? 0))
      : ((a.y ?? a.position?.y ?? 0) - (b.y ?? b.position?.y ?? 0)));
    const start = horizontal ? (sorted[0].x ?? sorted[0].position?.x ?? 0) : (sorted[0].y ?? sorted[0].position?.y ?? 0);
    const end = horizontal ? (sorted.at(-1).x ?? sorted.at(-1).position?.x ?? 0) : (sorted.at(-1).y ?? sorted.at(-1).position?.y ?? 0);
    const step = (end - start) / (sorted.length - 1);
    const positions = Object.fromEntries(sorted.map((row, idx) => [row.id, {
      x: horizontal ? Math.round(start + step * idx) : (row.x ?? row.position?.x ?? 0),
      y: horizontal ? (row.y ?? row.position?.y ?? 0) : Math.round(start + step * idx)
    }]));
    return apiOwner.moveNodes(positions);
  }
  function arrangeGroupNodes(graph, groupNode, apiOwner) {
    if (apiOwner && 'arrangeGroup' in apiOwner && typeof apiOwner.arrangeGroup === 'function') {
      return apiOwner.arrangeGroup(groupNode.id);
    }
    const members = groupMemberSteps(graph, groupNode);
    if (members.length < 2) return apiOwner.arrangeGraph();
    const ids = new Set(members.map(m => m.id));
    const x0 = Math.min(...members.map(m => m.x ?? m.position?.x ?? 0));
    const y0 = Math.min(...members.map(m => m.y ?? m.position?.y ?? 0));
    const rank = new Map();
    const depth = (id, trail = new Set()) => {
      if (rank.has(id)) return rank.get(id);
      if (trail.has(id)) return 0;
      const nextTrail = new Set(trail);
      nextTrail.add(id);
      const preds = (graph?.wires || []).filter(w => w.to === id && ids.has(w.from)).map(w => depth(w.from, nextTrail) + 1);
      const value = preds.length ? Math.max(...preds) : 0;
      rank.set(id, value);
      return value;
    };
    members.forEach(m => depth(m.id));
    const rows = {};
    const sorted = [...members].sort((a, b) => (rank.get(a.id) - rank.get(b.id)) || ((a.y ?? a.position?.y ?? 0) - (b.y ?? b.position?.y ?? 0)));
    const positions = {};
    for (const member of sorted) {
      const col = rank.get(member.id) || 0;
      const row = rows[col] || 0;
      rows[col] = row + 1;
      positions[member.id] = {x: Math.round((x0 + col * 320) / 8) * 8, y: Math.round((y0 + row * 220) / 8) * 8};
    }
    return apiOwner.moveNodes(positions);
  }

  function contextCommandGroups({
    kind,
    nodeId,
    message,
    taskId,
    port,
    paramKey,
    open,
    selected = [],
    wireId,
    canvas,
    group,
    remove,
    close,
    anchor
  }, s, u, actionState, more = false, setMore = () => {}) {
    if(!contextNames[kind] && window.ArchHubCommandRegistry.contexts.includes(kind))
      return declaredCommandGroups({kind,nodeId,message,taskId,port,paramKey,open,selected,wireId,canvas,group,remove,close,anchor},s,u,actionState);
    const nodes = s.graph?.nodes || [], wires = s.graph?.wires || [], tasks = s.tasks || [];
    const n = nodes.find(row => row.id === nodeId);
    const run = async (fn) => {
      const result = await actionState.run(fn);
      if (result?.approvalId) u.show('Approve', {
        id: result.approvalId
      });else if (result !== null) close();
    };
    const bind = (id, action, label = null, disabled = false) => ({id, action, label, disabled});
    const command = id => () => run(() => window.UI.nodeCommand(id, n));
    let groups = [];
    if (kind === 'Open tasks') {
      groups = [tasks.filter(row => row.status !== 'ARCHIVED' && !(u.canvasTabs?.tabs || []).some(tab => tab.id === row.id)).map(row =>
        bind('menu.item', () => run(() => u.openTaskFile(row.id)), row.title, false))];
    } else if (kind === 'Canvas attachments') {
      groups = [[bind('menu.file', () => {close();u.pickFile();}, null, false),
        bind('menu.meeting.notes', () => u.show('Attach meeting notes'), null, false)]];
    } else if (kind === 'Task message menu' && message) {
      const task = tasks.find(row=>row.id===taskId), pinned = task?.pinnedMessages?.includes(message.id);
      const referencedNode = nodes.find(row=>row.title && String(message.text).includes(row.title));
      groups = [
        [bind('menu.copy.text', () => run(async () => {await navigator.clipboard.writeText(String(message.text));return {ok:true};}), null, false),
          bind('menu.reply', () => {close();open?.();}, null, false)],
        [bind('menu.show.on.canvas', () => run(async () => {if(!referencedNode)throw Error('This message names no node on this canvas.');u.setSelectedNodeId(referencedNode.id);return {ok:true};}), null, referencedNode ? false : 'This message names no node on this canvas.'),
          bind('menu.make.a.task.from.this', () => run(async () => {if(!taskId)throw Error('This message has no originating task.');const made=await api.createTask(String(message.text).slice(0,2000),'','','',taskId);if(made.taskId)await u.openTaskFile(made.taskId);return made;}), null, false),
          bind('menu.unpin', () => run(() => api.pinTaskMessage(taskId,message.id,!pinned)), pinned ? 'Unpin' : 'Pin to the task', false)]
      ];
    } else if (kind === 'Task tab menu') {
      const tab = (u.canvasTabs?.tabs || []).find(row => row.id === nodeId);
      groups = [[bind('menu.keep.open', () => run(() => u.keepTaskTab(nodeId)), null, tab?.kept),
        bind('menu.open.beside', () => run(() => u.openTaskBeside(nodeId)), null, nodeId===u.task),
        bind('menu.rename', () => u.show('Rename task', {id: nodeId, text: tasks.find(row => row.id === nodeId)?.title || ''}), null, false),
        bind('menu.show.on.home', () => run(async () => {await api.setTaskSession(nodeId,{homePinned:true});u.setTask(nodeId);u.go('home');return {ok:true};}), null, false)],
        [bind('menu.close.tab', () => run(() => u.closeTaskTab(nodeId)), null, false),
        bind('menu.close.other.tabs', () => run(async () => {for (const row of [...(u.canvasTabs?.tabs || [])]) if(row.id !== nodeId) await u.closeTaskTab(row.id);}), null, (u.canvasTabs?.tabs || []).length<2)]];
    } else if (kind === 'Wire menu') {
      const wire=wires.find(w=>w.id===wireId);
      if(!wire)return null;
      const connectedNodes = () => {
        const seen = new Set([wire.from, wire.to].filter(Boolean)), queue = [...seen];
        while (queue.length) {
          const cur = queue.pop();
          for (const w of wires) {
            for (const [a, b] of [[w.from, w.to], [w.to, w.from]]) {
              if (a === cur && b && !seen.has(b) && nodes.some(row => row.id === b)) {
                seen.add(b);
                queue.push(b);
              }
            }
          }
        }
        return [...seen];
      };
      groups=[
        [bind('menu.wire.source', ()=>{close();canvas?.select?.([wire.from]);u.setSelectedNodeId(wire.from);}, null, false),
          bind('menu.wire.target', ()=>{close();canvas?.select?.([wire.to]);u.setSelectedNodeId(wire.to);}, null, false),
          bind('menu.wire.connected', ()=>{const ids=connectedNodes();close();canvas?.select?.(ids);if(ids.length===1)u.setSelectedNodeId(ids[0]);}, null, false)],
        [bind('menu.add.rule', ()=>u.show('Wire rule',{id:wire.id,text:wire.rule||''}), wire.rule ? 'Edit rule' : 'Add rule', false),
          bind('menu.enable', ()=>run(()=>api.setWireEnabled(wire.id,wire.enabled===false)), wire.enabled===false?'Enable':'Disable', false),
          bind('menu.insert.convert', ()=>run(()=>api.insertConvertOnWire(wire.id)), null, false),
          bind('menu.insert.node.here', ()=>u.show('Add node',{wireId:wire.id,point:canvas?.point}), null, false),
          bind('menu.show.in.inspector', ()=>{close();canvas?.inspectWire?.(wire.id);}, null, false)],
        [bind('menu.delete', ()=>run(()=>api.deleteWire(wire.id)), null, false)]
      ];
    } else if (kind === 'Port menu' && n) {
      const param = !n.bind && n.parameterSchema?.find(p =>
        p.editable && p.key !== 'engine' && (paramKey === p.key || port === 'param:' + p.key));
      groups = [['Visible', 'Faint', 'Hidden'].map(v => bind('menu.item.21', () => actionState.run(() => api.setPortVisibility(n.id, port, v)), v + ' wires', false))];
      const connected=wires.filter(w=>w.from===n.id&&w.fromPort===port||w.to===n.id&&w.toPort===port);
      groups.unshift([bind('menu.disconnect', ()=>run(()=>api.deleteSelection([],connected.map(w=>w.id))), null, !connected.length),bind('menu.show.compatible.nodes', ()=>u.show('Compatible nodes',{endpoint:{id:n.id,side:(n.outputs || []).some(p=>p.id===port)?'out':'in',port}}), null, false)]);
      if (param && api.promoteParam) groups.unshift([bind('menu.return.to.inline.parameter', () =>
        run(() => param.promoted ? api.demoteParam(n.id, param.key) : api.promoteParam(n.id, param.key)), param.promoted ? 'Return to inline parameter' : 'Expose as node', false)]);
    } else if ((kind === 'Embed menu' || (kind === 'Node menu' && Boolean(n?.params?.session_file))) && n) {
      const embedPath = n.params?.session_file || '';
      groups = [
        [bind('menu.open', () => { close(); if (open) open(); else u.act(() => api.enterSession(n.id)); }, null, false),
          bind('menu.embed.run', () => run(() => api.runNode(n.id, true)), null, false),
          bind('menu.embed.update', () => run(async () => {
            if ('updateEmbeddedSession' in api && typeof api.updateEmbeddedSession === 'function') return api.updateEmbeddedSession(n.id);
            await api.refreshLibraryPorts();
            return api.refreshProjects();
          }), null, false),
          bind('menu.embed.tab', () => run(async () => {
            const samePath = 'sameSessionPath' in api && typeof api.sameSessionPath === 'function'
              ? (a, b) => api.sameSessionPath(a, b)
              : (a, b) => Boolean(a && b && String(a).replaceAll('\\', '/').toLowerCase() === String(b).replaceAll('\\', '/').toLowerCase());
            const linked = tasks.find(t => (n.params?.task && t.id === n.params.task) || (embedPath && samePath(t.sessionPath, embedPath)));
            if (linked) return u.openTaskFile(linked.id, 'canvas');
            if (embedPath) return u.openSavedSession(embedPath);
            return api.enterSession(n.id);
          }), null, false)],
        [bind('menu.rename.25', () => u.show('Rename node', {id: n.id, text: n.title}), null, false),
          bind('menu.colour', () => u.show('Node colour', {id: n.id}), null, false)],
        [bind('menu.embed.detach', () => run(() => api.detachSession(n.id)), null, false),
          bind('menu.delete.50', () => u.confirm('Delete ' + n.title + '?', () => api.deleteNode(n.id)), null, n.fixed ? 'Pinned nodes stay on this task.' : false)]
      ];
    } else if ((kind === 'Node menu' || kind === 'Group menu') && n) {
      const isGroupNode = n.children?.length > 0 && !n.fixed, frame = !!n.frameMembers;
      if (frame) {
        groups = [[bind('menu.rename.25', ()=>u.show('Rename node',{id:n.id,text:n.title}), null, false),bind('menu.colour', ()=>u.show('Node colour',{id:n.id}), null, false),bind('menu.select.contents', ()=>{canvas?.select?.(n.frameMembers);close();}, null, false),bind('menu.remove.frame.keep.nodes', ()=>run(()=>api.ungroupNode(n.id)), null, false)]];
      } else if (isGroupNode) {
        const members = groupMemberSteps(s.graph, n);
        const targetIds = members.length ? members.map(m => m.id) : (n.children || []);
        const allFrozen = members.length ? members.every(m => m.frozen) : !!n.frozen;
        const allBypassed = members.length ? members.every(m => m.bypassed) : !!n.bypassed;
        groups = [
          [bind('menu.open', ()=>{close();open?.();}, null, false),
            bind('menu.expand', ()=>run(()=>api.setGroupCollapsed(n.id,!n.collapsed)), n.collapsed?'Expand':'Collapse', false)],
          [bind('menu.group.freeze', ()=>run(async()=>{for(const id of targetIds)await api.setNodeFlags(id,{frozen:!allFrozen});return {ok:true};}), allFrozen?'Unfreeze the group':'Freeze the group', false),
            bind('menu.group.bypass', ()=>run(async()=>{for(const id of targetIds)await api.setNodeFlags(id,{bypassed:!allBypassed});return {ok:true};}), allBypassed?'Stop bypassing the group':'Bypass the group', false),
            bind('menu.group.arrange', ()=>run(()=>arrangeGroupNodes(s.graph, n, api)), null, false)],
          [bind('menu.rename.25', ()=>u.show('Rename node',{id:n.id,text:n.title}), null, false),
            bind('menu.colour', ()=>u.show('Node colour',{id:n.id}), null, false),
            bind('menu.select.contents.31', ()=>{canvas?.select?.(n.children);close();}, null, false)],
          [bind('menu.save.as.skill', ()=>u.show('Save node type',{id:n.id,skill:true}), null, false),
            bind('menu.save.as.node.type', ()=>u.show('Save node type',{id:n.id}), null, false)],
          [bind('menu.ungroup', ()=>run(()=>api.ungroupNode(n.id)), null, false),
            bind('menu.delete.group.and.nodes', ()=>u.confirm('Delete '+n.title+' and its nodes?',()=>api.deleteGroup(n.id)), null, false)]
        ];
      } else {
        const approvals = s.approvals || [];
        const sessionFile = approvals.length && 'getSessionPath' in api && typeof api.getSessionPath === 'function' ? api.getSessionPath() : (s.sessionFile || '');
        const pendingApproval = approvals.find(card => card.status === 'pending' && (
          (card.nodeId === n.id && (!sessionFile || !card.path || card.path === sessionFile)) ||
          card.canvasNodes?.some(ref => ref.nodeId === n.id && (!sessionFile || !ref.path || ref.path === sessionFile))
        ));
        const approvalId = pendingApproval?.id || n.approvalId || '';
        const hasApproval = Boolean(approvalId || /approval|waiting for approval|held/i.test(String(n.status || '')));
        const isOpenable = Boolean(n.openable || n.params?.targetGraph || n.kind === 'Workflow link');
        const isNote = n.type === 'note' || n.kind === 'note' || n.kind === 'Note';
        const hasLiveDisconnect = Boolean(
          n.title === 'Remote tunnel' || n.type === 'thing.tunnel' || n.type === 'network.tunnel' ||
          n.liveAgent || (n.connected && n.connected.length) ||
          (n.members || []).some(m => m && (m.live || m.agent || m.session)) ||
          (n.type === 'thing.workshop' && (s.liveAgents || []).length > 0)
        );
        const needsApprove = n.approvalRequired === true || n.runnable === 'approve' || (n.pure === false && !['Done', 'Solved', 'done', 'Complete'].includes(n.status));
        const alreadyRan = ['Done', 'Solved', 'done', 'Complete'].includes(n.status) || (n.output != null && n.output !== '' && (!Array.isArray(n.output) || n.output.length > 0));
        const runLabel = needsApprove ? 'Ask to run (needs Approve)' : alreadyRan ? 'Rerun' : 'Run this step';
        groups = [
          ...(hasApproval ? [[
            bind('menu.node.review', () => { if (approvalId) u.show('Approve', {id: approvalId}); else { close(); u.setSelectedNodeId(n.id); } }, null, false),
            bind('menu.node.approve', () => run(() => api.approve(approvalId || n.id)), null, false),
            bind('menu.node.reject', () => run(() => api.decline(approvalId || n.id)), null, false)
          ]] : []),
          [
            ...(isOpenable ? [bind('menu.open', () => { close(); if (open) open(); else u.show('Node', {id: n.id}); }, null, false)] : []),
            bind('menu.properties', ()=>{close();u.setSelectedNodeId(n.id);}, null, false),
            ...((!n.fixed && !isNote) || n.type === 'thing.session' ? [bind('menu.add.parameter', ()=>u.show('Add parameter',{id:n.id}), null, false)] : []),
            ...(!isNote ? [
              bind('menu.show.output', ()=>u.show('Node output',{id:n.id}), null, false),
              bind('menu.ask.the.agent', ()=>{close();u.setSelectedNodeId(n.id);setThreadFace(u,'split');}, null, false)
            ] : [])
          ],
          ...(hasLiveDisconnect ? [[
            bind('menu.disconnect.everyone', () => run(async () => {
              if (n.params && Object.hasOwn(n.params, 'armed')) await api.setNodeParam(n.id, 'armed', false);
              if ((n.members || []).length && 'detachMember' in api && typeof api.detachMember === 'function') {
                for (const m of n.members) await api.detachMember(n.id, m);
                return {ok: true};
              }
              return api.stopEverything();
            }), null, false)
          ]] : []),
          ...(!isNote ? [[
            bind('menu.rerun', command('menu.rerun'), runLabel, false),
            bind('menu.run.to.here', ()=>run(()=>api.runToHere(n.id)), null, false),
            bind('menu.unfreeze', ()=>run(()=>api.setNodeFlags(n.id,{frozen:!n.frozen})), n.frozen?'Unfreeze':'Freeze', false),
            bind('menu.unbypass', ()=>run(()=>api.setNodeFlags(n.id,{bypassed:!n.bypassed})), n.bypassed?'Stop bypassing':'Bypass', false)
          ]] : []),
          [bind('menu.duplicate', ()=>run(()=>api.duplicateNodes([n.id])), null, false),
            bind('menu.copy', ()=>run(()=>api.copyNodes([n.id])), null, false),
            bind('menu.cut', ()=>run(()=>api.cutNodes([n.id])), null, false)],
          [bind('menu.rename.25', ()=>u.show('Rename node',{id:n.id,text:n.title}), null, false),
            ...(isNote ? [bind('menu.edit.note', ()=>u.show('Note',{id:n.id,text:n.params?.text ?? n.text ?? ''}), null, false)] : []),
            bind('menu.group', ()=>run(()=>canvas?.group?.()), null, selected.length<1)],
          [bind('menu.more', ()=>setMore(true), null, false)],
          [bind('menu.delete.50', ()=>u.confirm('Delete '+n.title+'?',()=>api.deleteNode(n.id)), null, n.fixed?'Pinned nodes stay on this task.':false)]
        ];
      }
    } else if (kind === 'Selection menu') {
      const editable=selected.filter(id=>!nodes.find(row=>row.id===id)?.fixed);
      groups=[[bind('menu.item.51', ()=>run(()=>api.runSelection(editable)), 'Run '+editable.length+' steps', false),bind('menu.ask.the.agent.52', ()=>{close();setThreadFace(u,'split');}, null, false)],
        [bind('menu.group', ()=>run(()=>canvas?.group?.()), null, false),bind('menu.save.as.skill.53', ()=>u.show('Save node type',{ids:editable,skill:true}), null, false)],
        [bind('menu.align.left', ()=>run(()=>api.alignNodes(editable,'x')), null, false),bind('menu.align.top', ()=>run(()=>api.alignNodes(editable,'y')), null, false),
          bind('menu.distribute.evenly', ()=>run(()=>distributeSelectedNodes(s.graph, editable, api)), null, editable.length < 2 ? 'Select at least 2 editable nodes.' : false)],
        [bind('menu.duplicate.56', ()=>run(()=>api.duplicateNodes(editable)), null, false),bind('menu.copy.57', ()=>run(()=>api.copyNodes(editable)), null, false),bind('menu.cut.58', ()=>run(()=>api.cutNodes(editable)), null, false)],
        [bind('menu.item.59', ()=>u.confirm('Delete '+editable.length+' nodes?',()=>api.deleteSelection(editable)), 'Delete '+editable.length+' nodes', false)]];
    } else if (kind === 'Canvas menu') {
      const undoName = String(s.graph?.undoLabel || s.undoLabel || s.graph?.lastAction || s.lastAction || '').trim();
      const redoName = String(s.graph?.redoLabel || s.redoLabel || s.graph?.nextAction || s.nextAction || '').trim();
      const threadShown = threadIsShown(u);
      groups=[
        [bind('menu.add.node.here', ()=>u.show('Add node',{point:canvas?.point}), null, false),
          bind('menu.paste.here', ()=>run(()=>api.pasteNodes(canvas?.point)), null, !api.hasCopiedNodes()?'Copy nodes first.':false),
          bind('menu.add.note', ()=>u.show('Note',{point:canvas?.point}), null, false)],
        [bind('menu.find.a.node', ()=>u.show('Find node'), null, false),
          bind('menu.select.all', ()=>{canvas?.selectAll?.();close();}, null, false),
          bind('menu.arrange', ()=>run(api.arrangeGraph), null, false),
          bind('menu.fit', ()=>{canvas?.fit?.();close();}, null, false)],
        [bind('menu.undo', ()=>run(api.undo), undoName ? 'Undo ' + undoName : null, false),
          bind('menu.redo', ()=>run(api.redo), redoName ? 'Redo ' + redoName : null, false)],
        [bind('menu.ask.the.agent.52', ()=>{close();setThreadFace(u,'split');}, null, false),
          bind('menu.show.the.thread', ()=>{close();setThreadFace(u, threadShown ? 'canvas' : 'split');}, threadShown ? 'Hide the thread' : null, false)]
      ];
    } else if (kind === 'Tray') {
      const openThread = () => {
        close();
        const activeId = (u && typeof u === 'object' && 'task' in u && u.task) || u?.canvasTabs?.active || tasks.find(t => t.status !== 'ARCHIVED')?.id;
        if (activeId && u && typeof u === 'object' && 'openTaskFile' in u && typeof u.openTaskFile === 'function') u.openTaskFile(activeId, 'split');
        else u.go('workshop');
      };
      groups = [
        ...(s.update?.available ? [[bind('menu.tray.install.update', () => run(() => api.installUpdate()), null, false)]] : []),
        [bind('menu.open.archhub', () => {
            close();
            if (typeof window !== 'undefined' && typeof window.ARCHHUB_WINDOW_ACTION === 'function') void api.windowAction('open');
            u.go('home');
          }, 'Open Home', false),
          bind('menu.tray.feedback', () => { close(); u.show('Send feedback'); }, null, false),
          bind('menu.tray.thread', openThread, null, false),
          bind('menu.tray.check.updates', () => run(() => api.checkForUpdates()), null, false),
          bind('menu.tray.receipts', () => { close(); u.show('App health'); }, null, false),
          bind('menu.baboom', () => { close(); u.go('baboom'); }, null, false),
          bind('menu.stop.everything', () => run(api.stopEverything), null, false)],
        [bind('menu.hide', () => run(() => api.windowAction('hide')), null, false),
          bind('menu.quit', () => run(() => api.windowAction('quit')), 'Quit ArchHub', false)]
      ];
    } else {
      const names = Object.fromEntries(window.ArchHubCommandRegistry.commands.filter(c => c.menuPage).sort((a,b)=>a.menu_order-b.menu_order).map(c => [c.action.route, c.label]));
      groups = [[...Object.keys(names).map(route => bind('page.' + route, () => u.go(route))), bind('menu.tray.receipts', () => u.show('App health'), null, false), bind('menu.tray.feedback', () => u.show('Send feedback'), null, false)], [bind('menu.settings', () => u.go('settings/Account'), null, false)]];
    }
    if(more&&kind==='Node menu'&&n&&!n.params?.session_file){
      groups=[
        [bind('menu.back', ()=>setMore(false), null, false)],
        [bind('menu.colour', ()=>u.show('Node colour',{id:n.id}), null, false),
          bind('menu.save.as.skill', ()=>u.show('Save node type',{id:n.id,skill:true}), null, false),
          bind('menu.save.as.node.type', ()=>u.show('Save node type',{id:n.id}), null, false)],
        [bind('menu.unpin.output', ()=>run(()=>api.setNodeFlags(n.id,{pinned:!n.pinned})), n.pinned?'Unpin output':'Pin output', false),
          bind('menu.fork', command('menu.fork'), 'Fork from here', false),
          bind('menu.repeat.this', ()=>{close();u.schedule(n.id);}, null, false)],
        [bind('menu.trace.back', ()=>{const ids=traceConnectedIds(s.graph,n.id,'back');close();if(ids.length>1)canvas?.select?.(ids);u.trace(n.id,'back');}, null, false),
          bind('menu.trace.forward', ()=>{const ids=traceConnectedIds(s.graph,n.id,'forward');close();if(ids.length>1)canvas?.select?.(ids);u.trace(n.id,'forward');}, null, false)]
      ];
    }
    if (n?.agentWork?.runnable === false || n?.agentWork?.role === 'session') {
      groups = groups.map(grp => grp.filter(row => !['menu.rerun', 'menu.run.to.here', 'menu.repeat.this'].includes(row.id)));
    }
    groups = window.UI.commandGroups(kind, groups);
    return groups;
  }
  window.UI.contextCommandGroups = contextCommandGroups;

  // Existing local menus get first refusal. Resolve the rest from the clicked surface.
  window.UI.openSurfaceMenu = (event, s, u) => {
    const target = event.target;
    if (event.defaultPrevented || u.modal || !target.closest ||
        target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],a[href]')) return false;
    const choice = (id, action, label = null, disabled = false) => ({id, action: () => {u.close();return action();}, label, disabled});
    const click = (id, button, label = null) => button && choice(id, () => button.click(), label, button.disabled);
    const search = (surface, selector) => {
      const input = surface.querySelector(selector);
      return input && choice('menu.surface.search', () => input.focus());
    };
    let surface, owner, context, label, rawGroups;
    const dedicated = target.closest('[data-screen="library"],[data-screen^="settings/"],[data-screen="docs"],[data-screen="workshop"]');
    const workshopDock = target.closest('[data-dock-workshop]');
    if (!dedicated && !workshopDock && (surface = target.closest('[data-home-page]'))) {
      const flowNode = target.closest('.react-flow__node');
      const session = target.closest('[data-home-task],[data-home-session-path]') ||
        flowNode?.querySelector('[data-home-task],[data-home-session-path]');
      const project = target.closest('[data-project]') || flowNode?.querySelector('[data-project]');
      const id = session?.dataset.homeTask;
      const path = session?.dataset.homeSessionPath;
      if (id || path) {
        owner = session;
        context = 'session';
        label = 'Home session menu';
        const tasks = s.tasks || [];
        const task = tasks.find(row => row.id === id);
        const open = (face = 'canvas') => id ? u.openTaskFile(id, face) : u.openSavedSession(path);
        const onDocument = (openTarget, matches, action) => u.act(async () => {
          const opened = await openTarget();
          if (opened && !opened.cancelled && matches()) return action();
          return {cancelled:true};
        });
        const onCard = action => onDocument(open, () => id
          ? api.getSessionDocument()?.properties?.taskContext?.task === id : api.sameSessionPath(api.getSessionPath(),path), action);
        const source = path || task?.sessionPath;
        const destinations = tasks.filter(t => !t.direct && t.id !== id && t.status !== 'ARCHIVED' && (!source || !api.sameSessionPath(t.sessionPath,source)));
        const sessionTask = task && !task.direct;
        const moveTargets = sessionTask ? destinations.filter(t => t.sessionPath && t.project === task.project) : [];
        const submenu = (subLabel, subGroups) => u.show('Surface menu', {anchor:{x:event.clientX,y:event.clientY},
          restoreFocus:session, surface:{label: subLabel, groups: commandGroups('session', subGroups)}});
        const move = (dest, asSubtask) => u.act(async () => {
          const result = await api.joinLegacyChild(id,dest.id,asSubtask);
          u.setToast({text:task.title+' moved.',label:'Undo',open:()=>u.act(()=>api.restoreLegacyChild(id))});
          return result;
        });
        const moveTo = asSubtask => submenu(asSubtask ? 'Move as subtask' : 'Move task',[moveTargets.map(t =>
          choice('menu.home.move',()=>move(t,asSubtask),asSubtask ? 'Move under '+t.title : 'Move to '+t.title))]);
        const addTo = () => submenu('Add to another task',[
          destinations.map(t => choice('menu.home.add', () => onDocument(() => u.openTaskFile(t.id,'canvas'),
            () => api.sameSessionPath(api.getSessionPath(),t.sessionPath) && !api.sameSessionPath(api.getSessionPath(),source),
            () => api.insertSession(source)), 'Add to '+t.title)),
          ...(moveTargets.length ? [[choice('menu.home.move',()=>moveTo(false),'Move task…'),
            choice('menu.home.move',()=>moveTo(true),'Move as subtask…')]] : [])
        ]);
        const isStep = node => !node.fixed && !node.type?.startsWith('trigger.') && node.type !== 'thing.session' && !['fixed-agent','fixed-workshop','fixed-you','start'].includes(node.id);
        const emptyWorkflow = Array.isArray(task?.workflow) && !task.workflow.some(isStep);
        rawGroups = [
          [choice('menu.item', () => open()),
            task && choice('menu.home.thread', () => open('split')),
            choice('menu.home.run', () => onCard(async () => {
              const result = await api.runNode();
              if (result?.approvalId) u.show('Approve', {id: result.approvalId});
            }))],
          [sessionTask && choice('menu.home.watch', () => u.show('Invite to watch', {path: source, title: task?.title}), null,
              !s.watch?.capability ? (s.watch?.reason || 'Read-only watcher invitations are unavailable.') : !source && 'Save this session first.'),
            sessionTask && choice('menu.home.automate', () => onCard(async () => {
              const result = await api.addAutomation({trigger:'schedule',armed:false});
              if (!result?.cancelled && api.getSessionDocument()?.properties?.taskContext?.task === id) u.setHomeInspector({id,tab:'Automate'});
            })),
            sessionTask && choice('menu.home.settings', () => onCard(() => u.setHomeInspector({id,tab:'Task'})))],
          [choice('menu.home.add', addTo, null, !source ? 'Save this session first.' : !destinations.length && 'There is no other task to add it to.'),
            task && choice('menu.rename', () => u.show('Rename task', {id, text: task.title})),
            choice('menu.home.duplicate', () => u.act(async () => {
              const created = await api.duplicateHomeTask(id, source);
              return u.openTaskFile(created.taskId, 'canvas');
            }), null, emptyWorkflow && 'It has no steps to copy yet.'),
            task && choice('menu.home.keep', () => u.act(() => api.setTaskSession(id,{homePinned:!task.homePinned})),
              task.homePinned ? 'Stop keeping at the top' : 'Keep at the top')],
          [task && choice('menu.home.archive', () => u.confirm('Archive ' + task.title + '? Its file stays on disk.', () => u.act(async () => {
              const result = await api.archiveTask(id);
              if (result?.ok === false) throw Error(result.error);
              if ((u.canvasTabs?.tabs || []).some(tab => tab.id === id)) await u.closeTaskTab(id);
              if (result?.revision) u.setToast({text:task.title + ' archived.', label:'Undo',
                open:() => u.act(() => api.restoreArchivedTask(id, result.revision))});
              return result;
            }))),
            task && choice('menu.home.delete', () => u.show('Delete task', {id, title:task.title, revision:task.revision}))]
        ];
      } else if (project && surface.contains(project)) {
        owner = project;
        context = 'project';
        label = 'Home project menu';
        const projectName = project.dataset.project || project.querySelector('[data-design="group.title"]')?.textContent?.trim() || 'project';
        const toggle = project.querySelector('button[data-design="group.collapse"],button[aria-label^="Expand "],button[aria-label^="Collapse "]');
        const isCollapsed = project.dataset.design === 'group.node' || /^Expand\b/i.test(toggle?.getAttribute('aria-label') || toggle?.textContent?.trim() || '');
        const openProject = () => u.act(async () => {
          const ws = (s.workspaces || []).find(w => w.id === projectName || w.name === projectName || (w.register?.number && (w.register.number + ' · ' + w.name) === projectName));
          if (ws && api && 'selectWorkspace' in api && typeof api.selectWorkspace === 'function') await api.selectWorkspace(ws.id);
          const firstTask = (s.tasks || []).find(t => t.status !== 'ARCHIVED' && (t.project === projectName || (ws && t.workspace === ws.id)));
          if (firstTask) return u.openTaskFile(firstTask.id, 'canvas');
          if (ws?.canvas) return u.openSavedSession(ws.canvas);
          return u.go('canvas');
        });
        rawGroups = [[
          choice('menu.project.open', openProject, 'Open ' + projectName),
          toggle && click('menu.project.toggle', toggle, isCollapsed ? 'Expand' : 'Collapse'),
          choice('menu.project.settings', () => u.openSystem('Projects'), 'Settings for ' + projectName)
        ]];
      } else {
        return false;
      }
    } else if ((surface = target.closest('[data-screen="library"]'))) {
      const card = target.closest('[data-design="library.row"]');
      const category = target.closest('[data-library-category]');
      owner = card || category || surface;
      context = card ? 'library-card' : category ? 'library-category' : 'library';
      label = 'Library menu';
      const toggle = category?.querySelector('button.shelf-category');
      rawGroups = [[card ? click('menu.library.add', card.matches('button') ? card : null, card.getAttribute('aria-label')) :
        category ? click('menu.library.toggle', toggle, toggle?.getAttribute('aria-expanded') === 'true' ? 'Collapse category' : 'Expand category') :
        search(surface, '[data-design="library.search"]')]];
    } else if ((surface = target.closest('[data-screen^="settings/"]'))) {
      const row = target.closest('[data-setting]');
      const control = row?.querySelector('input:not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled)');
      owner = row || surface;
      context = row ? 'settings-row' : 'settings';
      label = 'Settings menu';
      rawGroups = [[row ? control && choice('menu.settings.focus', () => control.focus()) : search(surface, 'input[aria-label="Search settings"]')]];
    } else if ((surface = target.closest('[data-screen="docs"]'))) {
      const topic = target.closest('.docs-toc button');
      const article = target.closest('.docs-article article');
      owner = topic || article || surface;
      context = topic || article ? 'docs-article' : 'docs';
      label = 'Documentation menu';
      rawGroups = [[topic ? click('menu.docs.open', topic, 'Open topic') :
        article ? click('menu.docs.open', article.querySelector('.docs-open button')) :
        search(surface, 'input[aria-label="Search docs"]')]];
    } else if (workshopDock) {
      const card = target.closest('[data-ws-approval],[data-ws-failed],[data-ws-working],[data-ws-thread]');
      if (!card) return false;
      owner = card;
      context = 'workshop';
      label = 'Workshop menu';
      const buttons = [...card.querySelectorAll('button')];
      const show = card.matches('button') ? card : buttons.find(button => ['Show','Hide'].includes(button.textContent.trim())) ||
        card.querySelector('button.wsl');
      rawGroups = [[click('menu.workshop.inspect', show, show?.closest('.wsca') ? show.textContent.trim() : 'Open'),
        click('menu.workshop.raw', card.querySelector('button.wsraw'))]];
    } else if ((surface = target.closest('[data-screen="workshop"]'))) {
      const message = target.closest('.ws-msg');
      owner = message || surface;
      context = message ? 'message' : 'workshop';
      label = 'Workshop menu';
      const buttons = [...(message?.querySelectorAll('.ws-msg-foot button') || [])];
      const inspect = buttons.find(button => button.hasAttribute('aria-expanded'));
      rawGroups = [message ? [click('menu.reply', buttons.find(button => button.textContent.trim() === 'Reply')),
        click('menu.workshop.inspect', inspect, inspect?.textContent.trim())] :
        [search(surface, 'input[aria-label="Search work"]')]];
    }
    const cleaned = (rawGroups || []).map(grp => grp.filter(Boolean)).filter(grp => grp.length > 0);
    if (!cleaned.length) return false;
    const groups = commandGroups(context, cleaned);
    if (!groups.some(grp => grp.length)) return false;
    event.preventDefault();
    const focus = target.closest('button:not(:disabled),summary,[tabindex]') ||
      owner.querySelector('button:not(:disabled),input:not(:disabled),[tabindex]');
    u.show('Surface menu', {surface: {label, groups}, anchor: {x: event.clientX, y: event.clientY}, restoreFocus: focus});
    return true;
  };

  window.UI.keyboardContextMenu = event => {
    if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return false;
    const target = event.target;
    if (!target.getBoundingClientRect) return false;
    const box = target.getBoundingClientRect();
    if (target.dispatchEvent(new window.MouseEvent('contextmenu', {bubbles: true, cancelable: true,
      clientX: Math.round(box.left + box.width / 2), clientY: Math.round(box.top + box.height / 2), button: 2}))) return false;
    event.preventDefault();
    return true;
  };
  function ContextMenu({
    kind,
    nodeId,
    message,
    taskId,
    port,
    paramKey,
    open,
    selected = [],
    wireId,
    canvas,
    group,
    remove,
    close,
    anchor,
    surface
  }) {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction();
    const menuRef = React.useRef(null);
    const [more,setMore]=React.useState(false);
    React.useLayoutEffect(()=>{(menuRef.current?.querySelector('button:not(:disabled)') || menuRef.current)?.focus({preventScroll:true});},[kind,nodeId,message?.id,wireId,more,surface]);
    const groups = surface?.groups || contextCommandGroups({kind,nodeId,message,taskId,port,paramKey,open,selected,wireId,canvas,group,remove,close,anchor},s,u,actionState,more,setMore);
    React.useLayoutEffect(() => {
      const menu = menuRef.current;
      if (!menu) return;
      const place = () => {
        const box = menu.getBoundingClientRect();
        menu.style.left = Math.max(8, Math.min(anchor?.x ?? 100, window.innerWidth - box.width - 8)) + 'px';
        menu.style.top = Math.max(8, Math.min(anchor?.y ?? 58, window.innerHeight - box.height - 8)) + 'px';
      };
      place();
      window.addEventListener('resize', place);
      return () => window.removeEventListener('resize', place);
    }, [anchor, groups?.flat().length, more]);
    if (!groups) return null;
    function handleContextmenusjsx1(action, event) {
      return action(event);
    }
    const ACTIONS = {
      "context-menus.1": "handleContextmenusjsx1"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleContextmenusjsx1
      })(id, ...args);
    }
    return <><div className="context-dismiss" onMouseDown={close} /><section ref={menuRef} className="context-menu" tabIndex={-1} data-design={kind === 'Open tasks' ? 'tab.picker' : undefined} role="menu" aria-label={surface?.label || kind} onKeyDown={(e) => {
        const buttons = [...e.currentTarget.querySelectorAll('button:not(:disabled)')];
        if (buttons.length && ['ArrowDown','ArrowUp','Home','End'].includes(e.key)) {
          e.preventDefault();
          const at = buttons.indexOf(document.activeElement);
          const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length - 1 :
            e.key === 'ArrowDown' ? (at + 1) % buttons.length : (at <= 0 ? buttons.length - 1 : at - 1);
          buttons[next].focus();
        }
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
      }}><window.UI.ActionStatus action={actionState} />{groups.map((rows, i) => <div className="context-group" key={i}>{rows.map(([label, icon, key, action, danger, disabled]) => <button role={surface ? 'menuitem' : undefined} data-design={'menu.' + label.toLowerCase().replace(/\W+/g,'-')} key={label} disabled={!!disabled} title={typeof disabled === 'string' ? disabled : undefined} className={danger ? 'danger' : ''} onClick={(event) => dispatch("context-menus.1", action, event)}><Icon name={icon} size={15} /><span>{window.UI.productLabel(label,s.settings)}</span><kbd>{key}</kbd></button>)}</div>)}</section></>;
  }
  window.UI.ContextMenu = ContextMenu;
})();
