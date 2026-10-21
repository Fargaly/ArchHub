const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const auth = {subject:'owner-a', session:'view-a'};

const socketRects = {
  out: {left:316, top:174, right:328, bottom:186, width:12, height:12},
  in: {left:420, top:174, right:432, bottom:186, width:12, height:12},
  bad: {left:420, top:193, right:432, bottom:205, width:12, height:12},
};

function canvas(wires = [], revision = 1) {
  return {
    ok:true, application_root:'app-a', revision,
    authorization:auth, scope:{current:'scope-a', current_label:'Scope A', trail:[{root:'scope-a', label:'Scope A'}]},
    selected:null, selection:[], selected_title:'Scope A',
    nodes:[
      {id:'src', label:'Source', engine:'engine:noop', x:100, y:100, status:'', params:[], ports:[
        {id:'out', name:'out', side:'source', type:'number', mode:'connection', connectable:true,
          connect_control:'ctl-out', connect_event_fact_input:'choice',
          connect_choices:[{id:'in', owner:'dst', label:'Target / in'}]},
      ]},
      {id:'dst', label:'Target', engine:'engine:noop', x:420, y:100, status:'', params:[], ports:[
        {id:'in', name:'in', side:'target', type:'number', mode:'connection', connectable:true},
        {id:'bad', name:'bad', side:'target', type:'text', mode:'connection', connectable:true},
      ]},
    ],
    wires, catalog:[], workshops:[],
    interaction_projection:{revision, lifecycle:'wip', bindings:[{
      control:'ctl-out', interaction:'ix-out', event:'ev-out',
      acknowledgement_mode:'receipt-v1', projection_mode:'topology-delta-v1',
      event_facts:[{input:'choice', value_kind:'number', minimum:0, maximum:0}],
    }]},
    workshop_scope:{graph_id:'app-a', root:'scope-a', revision, workshops:[]},
  };
}

function projectStudioCanvas(value) {
  const nodes = (value.nodes || []).map(node => {
    const ins = [], outs = [];
    for (const port of (node.ports || [])) {
      const item = {...port, label:port.name || '', t:port.type || port.value_type || 'any'};
      if (port.side === 'target') ins.push(item);
      else if (port.side === 'source') outs.push(item);
    }
    return {
      id:node.id, cat:'logic', title:node.label || node.id, sub:node.engine || 'Graph node',
      engine:node.engine, x:node.x, y:node.y, w:210, h:120, ins, outs,
      params:[], messages:[], live:true, ports:{ins:ins.map(x => ({id:x.id, t:x.t})), outs:outs.map(x => ({id:x.id, t:x.t}))},
      status:node.status || '',
    };
  });
  const nodeIndex = new Map(nodes.map(node => [node.id, node]));
  const wires = (value.wires || []).map(wire => {
    const sourcePort = nodeIndex.get(wire.source)?.outs.find(port => port.id === wire.source_interface);
    return {...wire, id:String(wire.id || ''), from:[wire.source, wire.source_interface],
      to:[wire.target, wire.target_interface], t:sourcePort?.t || ''};
  });
  return {nodes, wires};
}

async function mountStudio() {
  const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM, VirtualConsole} = await import('jsdom');
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => { throw error; });
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only',
    pretendToBeVisual:true, virtualConsole});
  const win = dom.window;
  win.PointerEvent = class PointerEvent extends win.MouseEvent {
    constructor(type, init = {}) { super(type, init); this.pointerId = init.pointerId || 1; this.pointerType = init.pointerType || 'mouse'; }
  };
  win.HTMLElement.prototype.setPointerCapture = function() {};
  win.HTMLElement.prototype.releasePointerCapture = function() {};
  Object.defineProperty(win.HTMLElement.prototype, 'offsetWidth', {configurable:true, get() { return 220; }});
  Object.defineProperty(win.HTMLElement.prototype, 'offsetHeight', {configurable:true, get() { return 120; }});
  win.HTMLElement.prototype.getBoundingClientRect = function() {
    const label = this.getAttribute('aria-label') || '';
    const rect = label.includes('Connect output out') ? socketRects.out :
      label.includes('Connect input in') ? socketRects.in :
      label.includes('Connect input bad') ? socketRects.bad : null;
    if (rect) return rect;
    if (this.getAttribute('role') === 'region' && this.getAttribute('aria-label') === 'Workflow canvas') {
      return {left:0, top:0, right:1000, bottom:760, width:1000, height:760};
    }
    return {left:0, top:0, right:220, bottom:120, width:220, height:120};
  };
  win.document.elementFromPoint = (x, y) => [...win.document.querySelectorAll('button[aria-label^="Connect "]')].find(button => {
    const rect = button.getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }) || win.document.querySelector('[role="region"][aria-label="Workflow canvas"]');
  let current = canvas();
  const calls = {posts:[]};
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/free'})})
    : Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:[], items:[]})});
  win.ARCHHUB_THEME = {};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.eval(read('01.APP/nodelang/studio/studio-existing-workshop.js'));
  win.ARCHHUB_EXISTING_WORKSHOP = win.ArchHubExistingWorkshop.create({
    get:async () => current,
    post:async (url, body) => {
      calls.posts.push({url, body:JSON.parse(JSON.stringify(body))});
      current = canvas([{id:'wire-a', source:'src', source_interface:'out', target:'dst', target_interface:'in'}], 2);
      return {ok:true, projection_mode:'receipt-v1', base_revision:1, committed_revision:2, created_root:'wire-a'};
    },
    projectCanvas:projectStudioCanvas,
  });
  win.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(current);
  const sessions = [{id:'scope-a', title:'Scope A', state:'idle', host:'archhub', when:'saved', file:'Graph', last:'2 nodes', model:''}];
  win.ARCHHUB_LIVE = {sessions, currentGraph:'scope-a', hosts:[], connectors:[],
    graph:win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph, memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('01.APP/nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 80));
  await settle();
  const canvasTab = [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === 'Canvas');
  if (canvasTab) {
    win.ReactDOM.flushSync(() => canvasTab.click());
    await settle();
  }
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const socket = label => {
    const button = [...win.document.querySelectorAll('button[aria-label^="Connect "]')].find(node => node.getAttribute('aria-label') === label);
    assert.ok(button, 'socket exists: ' + label);
    return button;
  };
  const firePointer = (target, type, x, y) => target.dispatchEvent(new win.PointerEvent(type, {
    bubbles:true, cancelable:true, button:0, buttons:type === 'pointerup' ? 0 : 1,
    clientX:x, clientY:y, pointerId:7, pointerType:'mouse',
  }));
  const drag = async (target, endX, endY, emitClick = true) => {
    const start = target.getBoundingClientRect();
    firePointer(target, 'pointerdown', start.left + 6, start.top + 6);
    firePointer(win.document, 'pointermove', start.left + 26, start.top + 6);
    firePointer(win.document, 'pointerup', endX, endY);
    if(emitClick)target.click();
    await settle(); await settle();
  };
  const dragCancelWithEscape = async target => {
    const start = target.getBoundingClientRect();
    firePointer(target, 'pointerdown', start.left + 6, start.top + 6);
    firePointer(win.document, 'pointermove', start.left + 26, start.top + 6);
    win.document.dispatchEvent(new win.KeyboardEvent('keydown', {bubbles:true, cancelable:true, key:'Escape'}));
    target.click();
    await settle(); await settle();
  };
  const click = async target => {
    win.ReactDOM.flushSync(() => target.click());
    await settle(); await settle();
  };
  const cancelWire = async () => {
    const button = [...win.document.querySelectorAll('button')].find(node => node.getAttribute('aria-label') === 'Cancel wire');
    assert.ok(button, 'cancel wire button exists');
    win.ReactDOM.flushSync(() => button.click());
    await settle(); await settle();
  };
  return {win, calls, close, socket, drag, dragCancelWithEscape, click, cancelWire};
}

test('dragging an output socket to a compatible input creates one wire through the existing connect route', async () => {
  const studio = await mountStudio();
  try {
    await studio.drag(studio.socket('Connect output out'), 426, 180);
    assert.equal(studio.calls.posts.length, 1);
    assert.equal(studio.calls.posts[0].url, '/api/universal/interaction');
    assert.deepEqual(studio.calls.posts[0].body.event_facts, [{input:'choice', value:0}]);
  } finally { studio.close(); }
});

test('dragging an output socket to empty canvas cancels without writing', async () => {
  const studio = await mountStudio();
  try {
    await studio.drag(studio.socket('Connect output out'), 40, 40);
    assert.equal(studio.calls.posts.length, 0);
    assert.equal(studio.win.document.body.textContent.includes('Choose an input for out'), false);
  } finally { studio.close(); }
});

test('canceling a click-started output clears the ref before the next input click', async () => {
  const studio = await mountStudio();
  try {
    await studio.click(studio.socket('Connect output out'));
    await studio.cancelWire();
    await studio.click(studio.socket('Connect input in'));
    assert.equal(studio.calls.posts.length, 0);
    assert.equal(studio.win.document.body.textContent.includes('Choose an output for in'), true);
  } finally { studio.close(); }
});

test('dragging from an output after an input click-start to empty canvas writes nothing', async () => {
  const studio = await mountStudio();
  try {
    await studio.click(studio.socket('Connect input in'));
    await studio.drag(studio.socket('Connect output out'), 40, 40);
    assert.equal(studio.calls.posts.length, 0);
    assert.equal(studio.win.document.body.textContent.includes('Choose an output for in'), false);
  } finally { studio.close(); }
});

test('escape during an output drag after an input click-start writes nothing', async () => {
  const studio = await mountStudio();
  try {
    await studio.click(studio.socket('Connect input in'));
    await studio.dragCancelWithEscape(studio.socket('Connect output out'));
    assert.equal(studio.calls.posts.length, 0);
    assert.equal(studio.win.document.body.textContent.includes('Choose an output for in'), false);
  } finally { studio.close(); }
});

test('dragging an output socket to an incompatible input refuses before writing', async () => {
  const studio = await mountStudio();
  try {
    await studio.drag(studio.socket('Connect output out'), 426, 199);
    assert.equal(studio.calls.posts.length, 0);
  } finally { studio.close(); }
});

test('click-click wiring still uses the same connect route', async () => {
  const studio = await mountStudio();
  try {
    await studio.click(studio.socket('Connect output out'));
    await studio.click(studio.socket('Connect input in'));
    assert.equal(studio.calls.posts.length, 1);
    assert.equal(studio.calls.posts[0].url, '/api/universal/interaction');
    assert.deepEqual(studio.calls.posts[0].body.event_facts, [{input:'choice', value:0}]);
  } finally { studio.close(); }
});


test('keyboard wiring works on the first activation after an outside drop without a click',async()=>{
  const studio=await mountStudio();
  try{
    await studio.drag(studio.socket('Connect output out'),900,700,false);
    assert.equal(studio.calls.posts.length,0);
    const activate=async label=>{studio.socket(label).dispatchEvent(new studio.win.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));await new Promise(resolve=>studio.win.setTimeout(resolve,100));};
    await activate('Connect output out');await activate('Connect input in');
    assert.equal(studio.calls.posts.length,1);
    assert.equal(studio.calls.posts[0].url,'/api/universal/interaction');
    assert.deepEqual(studio.calls.posts[0].body.event_facts,[{input:'choice',value:0}]);
  }finally{studio.close();}
});
