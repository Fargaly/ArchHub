const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function mountStudio(options = {}) {
  const sources=['tokens.jsx','ds/index.jsx','design-canvas.jsx','shared-data.jsx','studio-suite.jsx','param-types.jsx','studio-params.jsx','studio-mobile.jsx','studio-account.jsx','node-registry.jsx','brain-model.jsx','workshop-board.jsx','studio-workshop.jsx','studio-lm.jsx'];
  const sourceMode=process.env.HOME3_SOURCE==='1';
  const manifest = sourceMode ? {files:sources.map(source=>({source}))} : JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'))).digest('hex');
  if(!sourceMode) assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const graphCreates = [];
  const fileClicks = [];
  const agentCalls = [];
  const ownerCalls = [];
  const listeners=new Set();
  const waitingItems = options.waiting || [];
  const events=[];
  const accountCalls = [];
  const toolRows = options.tools || [
      {id:'studio', label:'Studio', state:'running', state_word:'RUNNING',
        description:'Canvas, chats and graph sessions.', stat_line:'3 sessions · 0 running.',
        off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio → Brain · Connectors · Workshop'},
      {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING',
        description:'Projects, tasks and governed work.', stat_line:'1 projects · 1 tasks · 1 blocked.',
        off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop → Studio · Connectors · Brain'},
      {id:'brain', label:'Brain', state:'off', state_word:'OFF',
        description:'Memory, facts and local classification.', stat_line:'1 facts · 1 stay on this machine.',
        off_sentence:'Switched off. Nothing is remembered or recalled.', wire_summary:'Brain → Studio · Workshop · Cloud',
        empty_title:'Brain is off', empty_line:'What ArchHub remembers. Everything else keeps running.'},
      {id:'baboom', label:'BABOOM', state:'running', state_word:'RUNNING',
        description:'Desktop companion and approved execution.', stat_line:'Attached signed runtime · 1 runtime session.',
        off_sentence:'Switched off. No companion on the desktop.', wire_summary:'BABOOM ← Studio · Workshop'},
      {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING',
        description:'Host bridges and Speckle access.', stat_line:'1/1 hosts connected · Speckle connected.',
        off_sentence:'Switched off. No reads or writes to your programs.', wire_summary:'Connectors → Studio · Workshop · Speckle'},
      {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING',
        description:'Devices, grants and cloud agents.', stat_line:'Not signed in.',
        off_sentence:'Switched off. Works on this machine only.', wire_summary:'Cloud ← Brain · Workshop'},
    ];
  win.fetch = (url,init) => String(url).startsWith('/api/universal/home-templates') ? Promise.resolve({ok:true,json:async()=>({ok:true,templates:options.templates||[]})})
    : String(url).startsWith('/api/universal/') && options.request ? options.request(url,init)
    : String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/thinkingmachines/inkling:free'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:toolRows})})
    : String(url) === '/waiting' && waitingItems.length
    ? new Promise(() => {})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_GRAPH_CREATE = async title => {
    graphCreates.push(title);
    throw new Error('fixture stops after ARCHHUB_GRAPH_CREATE');
  };
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[{id:'tool-a', title:'Tool node', cat:'ai', x:40, y:40, w:220, h:120, params:[], outs:[]}],
    wires:[{id:'wire-a', from:['tool-a','out'], to:['tool-a','in']}]};
  if(options.nativeWork)graph.nodes.push({id:options.nativeWork.work,title:'Approve wall opening',status:'awaiting_approval',params:[]});
  let snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization},
    workshops:[{root:'room-a', label:'General Workshop', is_general:true}],
    workshop:{root:'room-a',graph_id:'graph-a',scope_root:'scope-a',messages:[],participants:[],workflows:[]},
    nativeWork:options.nativeWork || {state:'awaiting_approval', work:'Layer choice', review_text:'Pick a layer', approved:false},
    theme:{configuration:{baboom_startup:{value:'on', source:'graph', available:true, revision:12}}, pending:false, error:''},
    applicationUpdate:{state:'idle', current_build:'20261009-w7'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const owner = {
    readHomeTemplates:async()=>({ok:true,templates:options.templates||[]}),
    refreshHomeWorkshops:async()=>{},
    refreshTopologyCanvas:async()=>snapshot.topology,
    refreshWorkshop:async()=>snapshot.workshop,
    startHomeTemplate:async id=>{ownerCalls.push(['startHomeTemplate',id]);return {ok:true,root:'group-new',children:['a','b']};},
    ...options.owner,
    getSnapshot:() => snapshot,
    subscribe:callback => {listeners.add(callback);return ()=>listeners.delete(callback);},
    watchApplicationUpdate:() => () => {},
    setBaboomStartup:async value => { ownerCalls.push(['setBaboomStartup', value]); snapshot.theme.configuration.baboom_startup.value = value; },
    approveNativeWork:async (root, inputDigest) => { ownerCalls.push(['approveNativeWork', root, inputDigest]); return {ok:true}; },
    nativeWorkAction:async (root, action, work) => { ownerCalls.push(['nativeWorkAction', root, action, work]); return {ok:true}; },
    decideSocialApproval:async body => { ownerCalls.push(['decideSocialApproval', body]); return {ok:true}; },
  };
  Object.assign(snapshot,options.snapshot||{});
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner, {get:(target, key) => key in target || typeof key !== 'string' ||
    key === 'then' ? target[key] : () => new Promise(() => {})});
  win.ARCHHUB_AGENT = async text => { agentCalls.push(text); return 'ok'; };
  win.ARCHHUB_TOOL_HUB = {ok:true, tools:toolRows, waiting:waitingItems};
  win.ARCHHUB_LIVE = {sessions:[
      {id:'graph-a', title:'Mine', state:'idle', file:'mine.graph', owner:'mine'},
      {id:'graph-b', title:'Scheduled', state:'scheduled', file:'daily.graph'},
      {id:'graph-c', title:'Workflow', state:'workflow', file:'run.graph'},
    ], currentGraph:'graph-a',
    hosts:options.hosts || [{id:'r25', name:'Revit 2025', state:'connected', file:'Tower.rvt'}],
    connectors:[{id:'revit', drive:true}], graph, memory:[{id:'m1', text:'Remember this', src:'test'}], skills:[]};
  if (options.loadHosts) win.ARCHHUB_LOAD_HOSTS = options.loadHosts;
  Object.defineProperty(win.HTMLInputElement.prototype, 'click', {
    configurable:true,
    value:function click() { if (this.type === 'file') fileClicks.push(this.getAttribute('aria-label') || 'file'); },
  });
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') {
      let code = sourceMode ? require('esbuild').transformSync(read('01.APP/nodelang/studio/'+file.source),{loader:'jsx'}).code : read('01.APP/nodelang/studio/compiled/' + file.output);
      if(file.source==='studio-lm.jsx') code=code.replace(/window\.StudioLM\s*=\s*StudioLM\s*;/,'window.StudioLM=StudioLM; window.__HOME3={Home,Frame};');
      if (options.exposeInspector && file.source === 'studio-lm.jsx') {
        assert.ok(code.includes('window.StudioLM=StudioLM;'), 'actual compiled Studio export exists');
        code = code.replace('window.StudioLM=StudioLM;', 'window.__InferenceInspector=InferenceInspector;window.StudioLM=StudioLM;');
      }
      win.eval(code);
    }
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const home = [...win.document.querySelectorAll('button')].find(node => node.title === 'All sessions');
  if (home) win.ReactDOM.flushSync(() => home.click());
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const button = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 60));
  const setAccount = rec => accountCalls.push(['setAccount', rec]);
  const onSignOut = () => accountCalls.push(['onSignOut']);
  return {win, doc:win.document, update:mutate=>{mutate(snapshot);snapshot={...snapshot};listeners.forEach(fn=>fn());},button, graphCreates, fileClicks, agentCalls, ownerCalls, accountCalls, setAccount, onSignOut, settle, close};
}


module.exports={mountStudio,root,read};
