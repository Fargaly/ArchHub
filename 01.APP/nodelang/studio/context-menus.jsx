// Menus stay anchored to the object. Dialogs are reserved for a decision/form.
(() => {
  // COMMANDREGISTRY: both menu and palette use this bounded, data-only reader.
  const contextNames = {'Node menu':'node','Group menu':'group','Wire menu':'wire',
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
        const tuple = [row.label,row.icon,row.shortcut,row.action,row.danger,row.disabledReason || row.disabled];
        tuple.command = row;
        return tuple;
      });
    });
  }
  window.UI.commandsForContext = commandsForContext;
  window.UI.commandGroups = commandGroups;
  window.UI.commandContextNames = contextNames;
  function paletteCommands(s,u,api,{query='',mode='All',context=null,actionState=null}={}) {
    if(context){
      return (contextCommandGroups({...context,nodeId:context.id,close:u.close},s,u,actionState,context.more,
        more=>u.show('Search',{commandContext:{...context,more}})) || []).flat().map(row=>row.command)
        .filter(row=>(mode==='All'||row.group===mode)&&row.label.toLowerCase().includes(query.toLowerCase()));
    }
    const bindings = [...s.catalogue.map(c => ({
        label: c.name,
        commandId: 'palette.add_node',
        action: async () => {
          await u.act(() => api.addNode(c.name));
          u.go('canvas');
        }
      })), ...s.templates.map(t => ({
        label: t.title,
        commandId: 'palette.template',
        action: () => u.show('Skill', {
          id: t.id
        })
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
      })), ...(s.graphs || []).map(g => ({
        label: g.name || g.title || g.id,
        commandId: 'palette.graph',
        action: async () => {
          await u.act(() => api.selectGraph(g.id));
          u.go('canvas');
        }
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
      }))];
    const registry=window.ArchHubCommandRegistry;
    const held={};
    for(const binding of bindings)(held[binding.commandId] ||= []).push(binding);
    return commandsForContext(registry.commands,'palette',{},held).map(row=>({...row,group:row.paletteGroup || 'Pages'}))
      .filter(row=>(mode==='All'||row.group===mode)&&row.label.toLowerCase().includes(query.toLowerCase()))
      .sort((a,b)=>registry.palette_order.indexOf(a.group)-registry.palette_order.indexOf(b.group));
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
    const n = s.graph.nodes.find(n => n.id === nodeId);
    const run = async (fn) => {
      const result = await actionState.run(fn);
      if (result?.approvalId) u.show('Approve', {
        id: result.approvalId
      });else if (result !== null) close();
    };
    const bind = (id, action, label = null, disabled = false) => ({id, action, label, disabled});
    let groups = [];
    if (kind === 'Open tasks') {
      groups = [s.tasks.filter(row => row.status !== 'ARCHIVED' && !u.canvasTabs.tabs.some(tab => tab.id === row.id)).map(row =>
        bind('menu.item', () => run(() => u.openTaskFile(row.id)), row.title, false))];
    } else if (kind === 'Canvas attachments') {
      groups = [[bind('menu.file', () => {close();u.pickFile();}, null, false),
        bind('menu.meeting.notes', () => u.show('Attach meeting notes'), null, false)]];
    } else if (kind === 'Task message menu' && message) {
      const task = s.tasks.find(row=>row.id===taskId), pinned = task?.pinnedMessages?.includes(message.id);
      const referencedNode = s.graph.nodes.find(row=>row.title && String(message.text).includes(row.title));
      groups = [[bind('menu.copy.text', () => run(async () => {await navigator.clipboard.writeText(String(message.text));return {ok:true};}), null, false),
        bind('menu.reply', () => {close();open?.();}, null, false),
        bind('menu.show.on.canvas', () => run(async () => {if(!referencedNode)throw Error('This message names no node on this canvas.');u.setSelectedNodeId(referencedNode.id);return {ok:true};}), null, referencedNode ? false : 'This message names no node on this canvas.'),
        bind('menu.make.a.task.from.this', () => run(async () => {const made=await api.createTask(String(message.text).slice(0,2000));if(made.taskId)await u.openTaskFile(made.taskId);return made;}), null, false),
        bind('menu.unpin', () => run(() => api.pinTaskMessage(taskId,message.id,!pinned)), pinned ? 'Unpin' : 'Pin to the task', false)]];
    } else if (kind === 'Task tab menu') {
      const tab = u.canvasTabs.tabs.find(row => row.id === nodeId);
      groups = [[bind('menu.keep.open', () => run(() => u.keepTaskTab(nodeId)), null, tab?.kept),
        bind('menu.open.beside', () => run(() => u.openTaskBeside(nodeId)), null, nodeId===u.task),
        bind('menu.rename', () => u.show('Rename task', {id: nodeId, text: s.tasks.find(row => row.id === nodeId)?.title || ''}), null, false),
        bind('menu.show.on.home', () => run(async () => {await api.setTaskSession(nodeId,{homePinned:true});u.setTask(nodeId);u.go('home');return {ok:true};}), null, false)],
        [bind('menu.close.tab', () => run(() => u.closeTaskTab(nodeId)), null, false),
        bind('menu.close.other.tabs', () => run(async () => {for (const row of [...u.canvasTabs.tabs]) if(row.id !== nodeId) await u.closeTaskTab(row.id);}), null, u.canvasTabs.tabs.length<2)]];
    } else if (kind === 'Wire menu') {
      const wire=s.graph.wires.find(w=>w.id===wireId);
      if(!wire)return null;
      groups=[[bind('menu.add.rule', ()=>u.show('Wire rule',{id:wire.id,text:wire.rule||''}), null, false),
        bind('menu.enable', ()=>run(()=>api.setWireEnabled(wire.id,wire.enabled===false)), wire.enabled===false?'Enable':'Disable', false),
        bind('menu.insert.convert', ()=>run(()=>api.insertConvertOnWire(wire.id)), null, false),
        bind('menu.insert.node.here', ()=>u.show('Add node',{wireId:wire.id,point:canvas?.point}), null, false),
        bind('menu.show.in.inspector', ()=>{close();canvas?.inspectWire?.(wire.id);}, null, false)],
        [bind('menu.delete', ()=>run(()=>api.deleteWire(wire.id)), null, false)]];
    } else if (kind === 'Port menu' && n) {
      const param = !n.bind && n.parameterSchema?.find(p =>
        p.editable && p.key !== 'engine' && (paramKey === p.key || port === 'param:' + p.key));
      groups = [['Visible', 'Faint', 'Hidden'].map(v => bind('menu.item.21', () => actionState.run(() => api.setPortVisibility(n.id, port, v)), v + ' wires', false))];
      const connected=s.graph.wires.filter(w=>w.from===n.id&&w.fromPort===port||w.to===n.id&&w.toPort===port);
      groups.unshift([bind('menu.disconnect', ()=>run(()=>api.deleteSelection([],connected.map(w=>w.id))), null, !connected.length),bind('menu.show.compatible.nodes', ()=>u.show('Compatible nodes',{endpoint:{id:n.id,side:n.outputs.some(p=>p.id===port)?'out':'in',port}}), null, false)]);
      if (param && api.promoteParam) groups.unshift([bind('menu.return.to.inline.parameter', () =>
        run(() => param.promoted ? api.demoteParam(n.id, param.key) : api.promoteParam(n.id, param.key)), param.promoted ? 'Return to inline parameter' : 'Expose as node', false)]);
    } else if ((kind === 'Node menu' || kind === 'Group menu') && n) {
      const group=n.children?.length>0&&!n.fixed,frame=!!n.frameMembers;
      if(frame)groups=[[bind('menu.rename.25', ()=>u.show('Rename node',{id:n.id,text:n.title}), null, false),bind('menu.colour', ()=>u.show('Node colour',{id:n.id}), null, false),bind('menu.select.contents', ()=>{canvas?.select?.(n.frameMembers);close();}, null, false),bind('menu.remove.frame.keep.nodes', ()=>run(()=>api.ungroupNode(n.id)), null, false)]];
      else if(group)groups=[[bind('menu.open', ()=>{close();open?.();}, null, false),
        bind('menu.expand', ()=>run(()=>api.setGroupCollapsed(n.id,!n.collapsed)), n.collapsed?'Expand':'Collapse', false),
        bind('menu.rename.25', ()=>u.show('Rename node',{id:n.id,text:n.title}), null, false),bind('menu.colour', ()=>u.show('Node colour',{id:n.id}), null, false),
        bind('menu.select.contents.31', ()=>{canvas?.select?.(n.children);close();}, null, false)],
        [bind('menu.save.as.skill', ()=>u.show('Save node type',{id:n.id,skill:true}), null, false),bind('menu.save.as.node.type', ()=>u.show('Save node type',{id:n.id}), null, false)],
        [bind('menu.ungroup', ()=>run(()=>api.ungroupNode(n.id)), null, false),bind('menu.delete.group.and.nodes', ()=>u.confirm('Delete '+n.title+' and its nodes?',()=>api.deleteGroup(n.id)), null, false)]];
      else groups=[[bind('menu.properties', ()=>{close();u.setSelectedNodeId(n.id);}, null, false),
        ...(!n.fixed||n.type==='thing.session'?[bind('menu.add.parameter', ()=>u.show('Add parameter',{id:n.id}), null, false)]:[]),
        bind('menu.show.output', ()=>u.show('Node output',{id:n.id}), null, false),bind('menu.ask.the.agent', ()=>{close();u.setSelectedNodeId(n.id);u.setTaskFace('split');}, null, false)],
        [bind('menu.rerun', ()=>run(()=>api.runNode(n.id)), null, false),bind('menu.run.to.here', ()=>run(()=>api.runToHere(n.id)), null, false),
        bind('menu.unfreeze', ()=>run(()=>api.setNodeFlags(n.id,{frozen:!n.frozen})), n.frozen?'Unfreeze':'Freeze', false),
        bind('menu.unbypass', ()=>run(()=>api.setNodeFlags(n.id,{bypassed:!n.bypassed})), n.bypassed?'Unbypass':'Bypass', false)],
        [bind('menu.duplicate', ()=>run(()=>api.duplicateNodes([n.id])), null, false),bind('menu.copy', ()=>run(()=>api.copyNodes([n.id])), null, false),bind('menu.cut', ()=>run(()=>api.cutNodes([n.id])), null, false),
        bind('menu.rename.25', ()=>u.show('Rename node',{id:n.id,text:n.title}), null, false),bind('menu.colour', ()=>u.show('Node colour',{id:n.id}), null, false)],
        [bind('menu.group', ()=>run(()=>canvas?.group?.()), null, selected.length<1),
        ...(n.type==='script.python'?[bind('menu.save.as.node.type', ()=>u.show('Save node type',{id:n.id}), null, false)]:[]),
        bind('menu.more', ()=>setMore(true), null, false)],
        [bind('menu.delete.50', ()=>u.confirm('Delete '+n.title+'?',()=>api.deleteNode(n.id)), null, n.fixed?'Pinned nodes stay on this task.':false)]];
    } else if (kind === 'Selection menu') {
      const editable=selected.filter(id=>!s.graph.nodes.find(n=>n.id===id)?.fixed);
      groups=[[bind('menu.item.51', ()=>run(()=>api.runSelection(editable)), 'Run '+editable.length+' steps', false),bind('menu.ask.the.agent.52', ()=>{close();u.setTaskFace('split');}, null, false)],
        [bind('menu.group', ()=>run(()=>canvas?.group?.()), null, false),bind('menu.save.as.skill.53', ()=>u.show('Save node type',{ids:editable,skill:true}), null, false)],
        [bind('menu.align.left', ()=>run(()=>api.alignNodes(editable,'x')), null, false),bind('menu.align.top', ()=>run(()=>api.alignNodes(editable,'y')), null, false)],
        [bind('menu.duplicate.56', ()=>run(()=>api.duplicateNodes(editable)), null, false),bind('menu.copy.57', ()=>run(()=>api.copyNodes(editable)), null, false),bind('menu.cut.58', ()=>run(()=>api.cutNodes(editable)), null, false)],
        [bind('menu.item.59', ()=>u.confirm('Delete '+editable.length+' nodes?',()=>api.deleteSelection(editable)), 'Delete '+editable.length+' nodes', false)]];
    } else if (kind === 'Canvas menu') groups=[[bind('menu.add.node.here', ()=>u.show('Add node',{point:canvas?.point}), null, false),bind('menu.paste.here', ()=>run(()=>api.pasteNodes(canvas?.point)), null, !api.hasCopiedNodes()?'Copy nodes first.':false),bind('menu.add.note', ()=>u.show('Note',{point:canvas?.point}), null, false),bind('menu.find.a.node', ()=>u.show('Find node'), null, false)],
      [bind('menu.select.all', ()=>{canvas?.selectAll?.();close();}, null, false),bind('menu.arrange', ()=>run(api.arrangeGraph), null, false),bind('menu.fit', ()=>{canvas?.fit?.();close();}, null, false)],
      [bind('menu.undo', ()=>run(api.undo), null, false),bind('menu.redo', ()=>run(api.redo), null, false)],
      [bind('menu.ask.the.agent.52', ()=>{close();u.setTaskFace('split');}, null, false),bind('menu.show.the.thread', ()=>{close();u.setTaskFace('split');}, null, false)]];
    else if (kind === 'Tray') groups = [[bind('menu.open.archhub', () => run(() => api.windowAction('open')), null, false), bind('menu.baboom', () => {
      close();
      u.go('baboom');
    }, null, false), bind('menu.stop.everything', () => run(api.stopEverything), null, false)], [bind('menu.hide', () => run(() => api.windowAction('hide')), null, false), bind('menu.quit', () => run(() => api.windowAction('quit')), null, false)]];else {
      const names = Object.fromEntries(window.ArchHubCommandRegistry.commands.filter(c => c.menuPage).sort((a,b)=>a.menu_order-b.menu_order).map(c => [c.action.route, c.label]));
      groups = [Object.keys(names).map(route => bind('page.' + route, () => u.go(route))), [bind('menu.settings', () => u.go('settings/Account'), null, false)]];
    }
    if(more&&kind==='Node menu'&&n)groups=[[bind('menu.back', ()=>setMore(false), null, false)],[bind('menu.unpin.output', ()=>run(()=>api.setNodeFlags(n.id,{pinned:!n.pinned})), n.pinned?'Unpin output':'Pin output', false),bind('menu.fork', ()=>run(()=>api.forkNode(n.id)), null, false),bind('menu.repeat.this', ()=>{close();u.schedule(n.id);}, null, false)],[bind('menu.trace.back', ()=>{close();u.trace(n.id,'back');}, null, false),bind('menu.trace.forward', ()=>{close();u.trace(n.id,'forward');}, null, false)]];
    if (n?.agentWork?.runnable === false || n?.agentWork?.role === 'session') groups = groups.map(group=>group.filter(row=>!['Rerun','Run to here','Repeat this'].includes(row.label || window.ArchHubCommandRegistry.commands.find(c=>c.id===row.id)?.label)));
    groups = window.UI.commandGroups(kind, groups);
    return groups;
  }
  window.UI.contextCommandGroups = contextCommandGroups;
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
    anchor
  }) {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction();
    const menuRef = React.useRef(null);
    const [more,setMore]=React.useState(false);
    React.useLayoutEffect(()=>{menuRef.current?.querySelector('button:not(:disabled)')?.focus({preventScroll:true});},[kind,nodeId,message?.id,more]);
    const groups = contextCommandGroups({kind,nodeId,message,taskId,port,paramKey,open,selected,wireId,canvas,group,remove,close,anchor},s,u,actionState,more,setMore);
    if (!groups) return null;
    const left = Math.max(8, Math.min(anchor?.x || 100, window.innerWidth - 266)),
      top = Math.max(8, Math.min(anchor?.y || 58, window.innerHeight - 520));
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
    return <><div className="context-dismiss" onMouseDown={close} /><section ref={menuRef} className="context-menu" data-design={kind === 'Open tasks' ? 'tab.picker' : undefined} role="menu" aria-label={kind} style={{
        left,
        top
      }} onKeyDown={(e) => {
        const buttons = [...e.currentTarget.querySelectorAll('button:not(:disabled)')];
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          const at = buttons.indexOf(document.activeElement);
          buttons[(at + (e.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length]?.focus();
        }
        if (e.key === 'Escape') { e.stopPropagation(); close(); }
      }}><window.UI.ActionStatus action={actionState} />{groups.map((rows, i) => <div className="context-group" key={i}>{rows.map(([label, icon, key, action, danger, disabled]) => <button data-design={'menu.' + label.toLowerCase().replace(/\W+/g,'-')} key={label} disabled={!!disabled} title={typeof disabled === 'string' ? disabled : undefined} className={danger ? 'danger' : ''} onClick={(event) => dispatch("context-menus.1", action, event)}><Icon name={icon} size={15} /><span>{label}</span><kbd>{key}</kbd></button>)}</div>)}</section></>;
  }
  window.UI.ContextMenu = ContextMenu;
})();
