const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const sources = ['tokens.jsx','ds/index.jsx','design-canvas.jsx','shared-data.jsx','studio-suite.jsx','param-types.jsx','studio-params.jsx','studio-mobile.jsx','studio-account.jsx','node-registry.jsx','brain-model.jsx','workshop-board.jsx','studio-workshop.jsx','studio-lm.jsx'];
const seedText = read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1],m[2]]));
let scripts;
function applicationScripts() {
  if (scripts) return scripts;
  const manifestPath = path.join(root,'01.APP/nodelang/studio/compiled/manifest.json');
  if (fs.existsSync(manifestPath) && !process.env.SYSNODES_RED_BASE && process.env.ARCHHUB_STUDIO_SOURCE_COURT !== '1') {
    const manifest = JSON.parse(fs.readFileSync(manifestPath));
    scripts = sources.map(source => {
      const entry = manifest.files.find(row => row.source === source);
      const hash = createHash('sha256').update(read('01.APP/nodelang/studio/'+source)).digest('hex');
      assert.equal(entry?.source_sha256,hash,'frozen Studio compiler input: '+source);
      return read('01.APP/nodelang/studio/compiled/'+entry.output);
    });
  } else {
    scripts = sources.map(source => require('esbuild').transformSync(process.env.SYSNODES_RED_BASE ? execFileSync('git',['show',process.env.SYSNODES_RED_BASE+':01.APP/nodelang/studio/'+source],{cwd:root,encoding:'utf8',maxBuffer:4*1024*1024}) : read('01.APP/nodelang/studio/'+source),{loader:'jsx'}).code);
  }
  scripts[sources.indexOf('studio-lm.jsx')]=scripts[sources.indexOf('studio-lm.jsx')].replace(/window\.StudioLM\s*=\s*StudioLM;/, 'window.SystemSettingsNav=SystemSettingsNav;window.SystemGraphStates=SystemGraphStates;window.NodeCanvas=NodeCanvas;window.NodeRail=NodeRail;window.Settings=Settings;window.ScopeComposer=ScopeComposer;window.StudioLM = StudioLM;');
  return scripts;
}
function projectionFixture() {
  const full = path.join(root,'05.EVIDENCE/sysnodes-projection.json');
  if (fs.existsSync(full)) return JSON.parse(fs.readFileSync(full));
  return {canvas:{graph_id:'app',application_root:'app',root:'app',revision:7,authorization:{system_view:true}},graph:{nodes:[
    {id:'sys_ui',application:true,live:true,title:'UI & Design System',group:'Appearance',cat:'display',x:20,y:40,w:280,
      outs:[{id:'theme',label:'Theme',t:'view'}],params:[
        {k:'accent',label:'Accent',v:seed.accent || '#df9a65',type:'color',value_root:'cell-accent',editable:true},
        {k:'density',label:'Density',v:'comfortable',type:'select',options:['comfortable','compact'],value_root:'cell-density',editable:true},
      ]},
    {id:'sys_workshop',application:true,live:true,title:'Workshop',group:'AI',cat:'logic',x:380,y:40,w:280,
      ins:[{id:'theme',label:'Theme',t:'view'}],params:[{k:'stale_claim_seconds',label:'Stale claim',v:120,type:'number',value_root:'cell-stale',editable:true}]},
    {id:'sys_brain',application:true,live:true,title:'Brain',group:'AI',cat:'data',x:380,y:320,w:280,
      params:[{k:'facts',label:'Facts',v:4,editable:false}],actions:[{id:'open',label:'Open Brain',kind:'open-node',root:'sys_brain'}]},
  ],wires:[{id:'relation-theme',label:'Theme tokens',relation:'Theme tokens',from:['sys_ui','theme'],to:['sys_workshop','theme']}]}};
}
function normalProjectionMapperSource(){
  const html=read('01.APP/nodelang/studio/studio.html');
  return html.slice(html.indexOf('    const PARAM_SPECS = {'),html.indexOf('    const canvas = await jget('))+
    html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
}
async function mountSystem({projection=projectionFixture(),settings=true}={}) {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>',{url:'http://127.0.0.1:53983/',runScripts:'outside-only',pretendToBeVisual:true});
  const win = dom.window, doc = win.document, listeners = new Set();
  if(Array.isArray(projection.nodes)) {
    if(projection.graph_id){
      win.eval(read('01.APP/nodelang/studio/studio-authority.js'));
      const mapper=win.ArchHubStudioAuthority.create({get:async()=>projection,post:async()=>projection,uuid:()=> 'court-id'});
      await mapper.load();projection=mapper.getSnapshot();
    }else{
      win.eval(normalProjectionMapperSource());win.__rawCanvas=projection;
      const graph=win.eval('projectStudioCanvas(window.__rawCanvas)');projection={canvas:projection,graph};
    }
  }
  const calls = {writes:[],opens:[],provider:[],propertyRoutes:[]};
  win.fetch = async url => ({ok:true,json:async()=>String(url).includes('/models')?{models:[]}: {ok:true}});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false,addEventListener(){},removeEventListener(){}});
  let settingsState={configuration:{theme:{...seed},binding_mode:'personal-wip',state:'WIP',history:[],personal_wip_heads:['head-a']},pending:false,error:''};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:()=>({canvas:projection.canvas,applicationUpdate:{state:'idle',current_build:'court'},theme:settingsState}),
    subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},readProviders:async()=>[],watchApplicationUpdate:()=>()=>{},
    readCloudPublishConsent:async()=>({allowed:false,account:''}),listSocialApprovals:async()=>[],listLocalSocialAccounts:async()=>[],
    readSettingsPermissionRows:async()=>[],
  };
  const snapshot = () => ({...projection,pending:false,error:''});
  const authority = win.ARCHHUB_STUDIO_AUTHORITY = {
    getSnapshot:snapshot,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},moveMany:async()=>({ok:true}),
    open:async id=>{calls.opens.push(id);return {ok:true,...projection}},
  };
  const persistOwnerProperty = async(id,key,value)=>{
    calls.writes.push({id,key,value});
    const row=projection.graph.nodes.find(n=>n.id===id)?.params?.find(p=>p.k===key);
    if(!row) throw new Error('no real setting '+id+':'+key);
    row.v=value; projection.canvas.revision++;
    projection.graph={...projection.graph,nodes:projection.graph.nodes.map(n=>n.id===id?{...n,params:n.params.map(p=>({...p}))}:n)};
    if(key==='accent') { win.ARCHHUB_THEME.accent=value;settingsState={...settingsState,configuration:{...settingsState.configuration,theme:{...settingsState.configuration.theme,accent:value}}};win.ArchHubTheme.apply(settingsState.configuration.theme); }
    listeners.forEach(fn=>fn());return {ok:true};
  };
  win.ARCHHUB_SET_NODE_PROP = persistOwnerProperty;
  win.ARCHHUB_SET_PROP = async(relation,value)=>{
    calls.propertyRoutes.push({relation,value});
    const node=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.rel===relation));
    const row=node?.params.find(p=>p.rel===relation);
    assert.ok(row,'set-property resolves the projected owner relation');
    return persistOwnerProperty(node.id,row.k,row.type==='number'?Number(value):value);
  };
  win.ARCHHUB_EXISTING_WORKSHOP.previewThemeToken=async(key,value)=>{
    const n=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.k===key || p.setting?.kind==='theme'&&p.setting.key===key));
    const p=n?.params.find(p=>p.k===key || p.setting?.key===key);if(!p)throw Error('no theme owner '+key);
    return win.ARCHHUB_SET_NODE_PROP(n.id,p.k,value);
  };
  win.ARCHHUB_EXISTING_WORKSHOP.setBaboomStartup=async value=>{
    const n=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.setting?.kind==='baboom'));
    return win.ARCHHUB_SET_NODE_PROP(n.id,n.params.find(p=>p.setting?.kind==='baboom').k,value);
  };
  win.ARCHHUB_EXISTING_WORKSHOP.setComposerModel=async(route,generation)=>{
    const n=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.setting?.kind==='composer-model'));
    if(n)await win.ARCHHUB_SET_NODE_PROP(n.id,n.params.find(p=>p.setting?.kind==='composer-model').k,route);
    if(generation)for(const [key,value]of Object.entries(generation)){
      const node=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.setting?.kind==='generation'&&p.setting.key===key));
      if(node)await win.ARCHHUB_SET_NODE_PROP(node.id,node.params.find(p=>p.setting?.kind==='generation'&&p.setting.key===key).k,value);
    }
    return{ok:true,model_defaults:generation};
  };
  win.ARCHHUB_MODEL_DEFAULTS_SAVE=async generation=>win.ARCHHUB_EXISTING_WORKSHOP.setComposerModel('openrouter/fake/court',generation);
  win.ARCHHUB_MODS=async command=>{
    const kind=command.action==='enable'?'mod-enabled':'mod-param';
    const node=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.setting?.kind===kind&&p.setting.mod_id===command.id&&(kind==='mod-enabled'||p.setting.key===command.param)));
    const row=node?.params.find(p=>p.setting?.kind===kind&&p.setting.mod_id===command.id&&(kind==='mod-enabled'||p.setting.key===command.param));
    assert.ok(row,'existing mod owner cell');return win.ARCHHUB_SET_NODE_PROP(node.id,row.k,kind==='mod-enabled'?command.enabled:command.value);
  };
  win.ARCHHUB_EXISTING_WORKSHOP.setCloudPublishConsent=async allowed=>{
    const node=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.setting?.kind==='cloud-consent'));
    const row=node.params.find(p=>p.setting?.kind==='cloud-consent');return win.ARCHHUB_SET_NODE_PROP(node.id,row.k,allowed);
  };
  win.fetch=async(url,options)=>{
    if(String(url).includes('/agent'))calls.provider.push({url:String(url),options});
    if(String(url).includes('/host-enabled')){const command=JSON.parse(options.body);
      const node=projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.setting?.kind==='host-enabled'&&p.setting.host_id===command.host_id));
      const row=node.params.find(p=>p.setting?.kind==='host-enabled'&&p.setting.host_id===command.host_id);
      await win.ARCHHUB_SET_NODE_PROP(node.id,row.k,command.enabled);
    }
    return{ok:true,json:async()=>({ok:true,models:[]})};
  };
  authority.load=async()=>{listeners.forEach(fn=>fn());return projection.canvas};
  win.ARCHHUB_AGENT_CHAT = async(...args)=>{calls.provider.push(args);return {ok:true,text:'unexpected provider'}};
  win.ARCHHUB_AGENT = win.ARCHHUB_AGENT_CHAT;
  win.ARCHHUB_LIVE={sessions:[],currentGraph:null,hosts:[],connectors:[],graph:projection.graph,memory:[],skills:[]};
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  // Execute classic scripts as the production script loader does. Strict eval
  // would hide global bindings and mask a window-export recursion regression.
  applicationScripts().forEach(code=>new vm.Script(code).runInContext(dom.getInternalVMContext()));
  const flush=action=>win.ReactDOM.flushSync(action);
  win.__courtProjection=projection;
  win.eval(`window.__studioRoot=ReactDOM.createRoot(document.getElementById("root"));
    window.__courtRender=(mode='graph',selected=null)=>ReactDOM.flushSync(()=>window.__studioRoot.render(
      mode==='settings'?React.createElement(Settings,{onClose:()=>window.__courtRender(),onOpenToolGraph:async()=>{window.__courtRender();return {ok:true}},initialTab:'theme',account:null,setAccount:()=>{}}):
      React.createElement('div',{style:{height:900,width:1400,position:'relative'}},
        React.createElement(NodeCanvas,{focusId:selected,setFocusId:id=>window.__courtRender('graph',id),setLibraryOpen:()=>{},system:true}),
        React.createElement(NodeRail,{node:window.__courtProjection.graph.nodes.find(n=>n.id===selected)||null,graph:window.__courtProjection.graph,canvas:window.__courtProjection.canvas,scope:'app',setPickerOpen:()=>{}}))));
    window.__courtRender('graph');`);
  const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>win.setTimeout(r,0));};
  await settle();
  if(settings) await settle();
  const close=()=>{flush(()=>win.__studioRoot.unmount());win.close();};
  const change=async(control,value,event='change')=>{assert.ok(control,'editable control exists');flush(()=>{
    const proto=control.tagName==='TEXTAREA'?win.HTMLTextAreaElement.prototype:control.tagName==='SELECT'?win.HTMLSelectElement.prototype:win.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto,'value').set.call(control,String(value));control.dispatchEvent(new win.Event(event,{bubbles:true}));});await settle();};
  const select=async id=>{
    if(!doc.querySelector('[data-node-id]')){win.__courtRender('graph');await settle();}
    const card=doc.querySelector('[data-node-id="'+id+'"]');assert.ok(card,'selectable real node '+id);
    flush(()=>card.querySelector('[data-node-card-title]').click());await settle();
    assert.equal(doc.querySelector('[data-node-id="'+id+'"]').getAttribute('data-focused'),'true','node selection reaches Properties');
  };
  return {win,doc,calls,projection,authority,flush,settle,change,close,select};
}

if(require.main===module) {
test('SYSNODES2: default Workshop Properties uses its owner relation before any value cell exists',async()=>{
  const relation='app:property:workshop-default-stale';
  const projection={canvas:{graph_id:'app',application_root:'app',root:'app',revision:7,authorization:{system_view:true}},graph:{nodes:[
    {id:'sys_workshop',application:true,live:true,title:'Workshop',group:'AI',cat:'logic',x:20,y:40,w:280,
      params:[{k:'stale_claim_after_idle_minutes',label:'Stale claim',v:30,type:'number',rel:relation,
        value_root:'not-materialized',cell_id:null,editable:true,setting:{kind:'property',key:'stale_claim_after_idle_minutes'}}]},
  ],wires:[]}};
  const s=await mountSystem({projection});try{
    s.win.ARCHHUB_SET_NODE_PROP=()=>{throw Error('application setting must use its owner route');};
    await s.select('sys_workshop');
    const input=s.doc.querySelector('aside [data-sysnode-param="stale_claim_after_idle_minutes"] input');
    await s.change(input,17,'input');
    assert.deepEqual(s.calls.propertyRoutes,[{relation,value:'17'}]);
    assert.equal(s.projection.graph.nodes[0].params[0].v,17);
    assert.equal(s.doc.querySelector('aside [role=alert]'),null);
  }finally{s.close();}
});
test('SYSNODES: editing generation preserves the canonical model route over a stale header cache',async()=>{
  const s=await mountSystem();try{
    delete s.win.ARCHHUB_MODEL_DEFAULTS_SAVE;
    let canonicalRoute='openrouter/vendor/new';
    const owner=s.win.ARCHHUB_EXISTING_WORKSHOP,readSnapshot=owner.getSnapshot;
    owner.getSnapshot=()=>{
      const held=readSnapshot();return{...held,theme:{...held.theme,configuration:{...held.theme.configuration,
        composer_model:{source:'graph',value:canonicalRoute}}}};
    };
    const writes=[];owner.setComposerModel=async(route,generation)=>{writes.push({route,generation});return{ok:true,configuration_state:{model_defaults:generation}}};
    for(const route of ['openrouter/vendor/new','']){
      canonicalRoute=route;s.win.ARCHHUB_PICKED_MODEL={name:'Old cached model',routed:'openrouter/vendor/old',route:'vendor/old'};
      await s.win.saveModelDefaults({temperature:.4,'top-p':.9,'max tokens':1024});
      assert.equal(writes.at(-1)?.route,route,'generation edit preserves actual owner route, including a deliberate clear');
      assert.equal(writes.at(-1)?.generation.temperature,.4,'generation edit still reaches existing owner');
    }
  }finally{s.close();}
});
test('SYSNODES: existing ordinary node Properties renders the original inspector without export recursion',async()=>{
  const s=await mountSystem();try{
    s.win.__ordinaryNode={id:'ordinary-court-node',live:true,cat:'logic',params:[{k:'value',label:'Value',v:'working',type:'text',rel:'ordinary-value'}]};
    const delegated=s.win.NodeInspector({node:s.win.__ordinaryNode});
    assert.notEqual(delegated.type,s.win.NodeInspector,'exported application-aware inspector must delegate, never return itself');
    const writes=[];s.win.ARCHHUB_SET_NODE_PROP=async(id,key,value)=>{writes.push({id,key,value});return{ok:true}};
    s.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(window.NodeInspector,{node:window.__ordinaryNode})));');
    await s.settle();
    assert.ok(s.doc.querySelector('[data-node-inspector]'),'ordinary node retains its real Properties editor');
    await s.change(s.doc.querySelector('[data-param-key="value"] input'),'ordinary edit','input');
    assert.deepEqual(writes.at(-1),{id:'ordinary-court-node',key:'value',value:'ordinary edit'},'ordinary editor retains its actual save path');
  }finally{s.close();}
});
test('SYSNODES: projected application cards expose actual editable typed setting cells',async()=>{
  const s=await mountSystem();try{
    for(const node of s.projection.graph.nodes.filter(n=>n.application)){
      const card=s.doc.querySelector('[data-node-id="'+node.id+'"]');assert.ok(card,node.title+' card');
      const cells=(node.params||[]).filter(p=>p.editable!==false);
      const expand=card.querySelector('button[aria-expanded="false"]');if(expand){s.flush(()=>expand.click());await s.settle();}
      if(cells.length)for(const row of cells){
        const wrapper=[...card.querySelectorAll('[data-sysnode-param]')].find(el=>el.getAttribute('data-sysnode-param')===row.k);
        const canonical=row.cell_id||row.value_root||row.rel;
        if(canonical)assert.equal(wrapper?.getAttribute('data-sysnode-cell'),canonical,node.title+': canonical cell identity');
        else {assert.ok(row.setting,node.title+': lazy owner default has a real write alias');assert.equal(wrapper?.getAttribute('data-value-root'),null,'default does not invent a materialized cell');}
        const control=wrapper?.querySelector('input,select,button,textarea');assert.ok(control,node.title+': '+row.label+' inline cell is interactive');
      }
      else {
        assert.ok([...card.querySelectorAll('button')].some(b=>!b.disabled&&/Open/.test(b.textContent)),node.title+' real owner action');
        if(Number.isInteger(node.memberCount))assert.ok(card.textContent.includes(String(node.memberCount)),node.title+' real member count is visible');
      }
    }
  }finally{s.close();}
});
test('SYSNODES: every System wire has a visible semantic label and hover meaning',async()=>{
  const s=await mountSystem();try{
    const wires=[...s.doc.querySelectorAll('[data-wire-id]')];assert.equal(wires.length,s.projection.graph.wires.length);
    for(const wire of wires){
      const relation=s.projection.graph.wires.find(w=>w.id===wire.getAttribute('data-wire-id'));
      assert.equal((wire.getAttribute('aria-label')||wire.querySelector('title')?.textContent||'').trim(),relation.label,'wire hover names actual relation');
      const source=s.projection.graph.nodes.find(n=>n.id===relation.from?.[0]);
      const target=s.projection.graph.nodes.find(n=>n.id===relation.to?.[0]);
      assert.notEqual(relation.label,source?.title+' → '+target?.title,'endpoint names do not explain what flows');
    }
    const labels=[...s.doc.querySelectorAll('[data-sysnode-wire-label]')];assert.equal(labels.length,wires.length,'one visible relation label per wire');
    for(const label of labels)assert.ok(label.textContent.trim(),'visible non-empty relation');
  }finally{s.close();}
});
test('SYSNODES: selected application Properties never show generic execution filler',async()=>{
  const s=await mountSystem();try{
    for(const node of s.projection.graph.nodes.filter(n=>n.application)){
      await s.select(node.id);
      assert.doesNotMatch(s.doc.body.textContent,/\bhalted\b|Branch \/ loop \/ switch|Scope for|Incoming r/i);
      assert.doesNotMatch(s.doc.querySelector('[data-node-id="'+node.id+'"]').textContent,/Not available yet/i,node.title+' shows its actual state/action without generic preview filler');
      const aside=s.doc.querySelector('aside');assert.ok(aside,'Properties panel');
      assert.ok(aside.querySelector('[data-sysnode-cell] input,[data-sysnode-cell] select,[data-sysnode-cell] button,button[data-sysnode-action]'),node.title+' Properties editable or real action');
    }
  }finally{s.close();}
});
test('SYSNODES: every application node accepts a Properties edit or executes its real owner action',async()=>{
  const s=await mountSystem();try{
    const ids=s.projection.graph.nodes.filter(n=>n.application).map(n=>n.id);
    for(const id of ids){
      await s.select(id);const node=s.projection.graph.nodes.find(n=>n.id===id);
      const param=(node.params||[]).find(p=>p.editable===true);
      const panel=s.doc.querySelector('aside');assert.ok(panel);
      if(!param){const action=node.actions?.[0];assert.ok(action,node.title+' owner action');
        const button=panel.querySelector('[data-sysnode-action="'+action.id+'"]');assert.ok(button&&!button.disabled);
        s.flush(()=>button.click());await s.settle();assert.equal(s.calls.opens.at(-1),action.root,node.title+' action reaches owner');continue;}
      const wrapper=[...panel.querySelectorAll('[data-sysnode-param]')].find(el=>el.getAttribute('data-sysnode-param')===param.k);
      assert.ok(wrapper,node.title+' param wrapper');const input=wrapper.querySelector('input,select,button[role=switch]');assert.ok(input&&!input.disabled);
      let expected;
      if(input.getAttribute('role')==='switch'){expected=!(param.v===true||param.v==='true'||param.v==='on');s.flush(()=>input.click());await s.settle();}
      else if(input.tagName==='SELECT'){const choice=[...input.options].find(o=>o.value!==input.value)||input.options[0];expected=choice.value;await s.change(input,expected);}
      else if(input.type==='number'){expected=Number(param.v)+1;if(input.max&&expected>Number(input.max))expected=Number(param.v)-1;await s.change(input,expected,'input');}
      else if(input.type==='color'){expected='#335577';await s.change(input,expected);}
      else{expected='openrouter/fake/court';await s.change(input,expected,'input');s.flush(()=>input.dispatchEvent(new s.win.FocusEvent('focusout',{bubbles:true})));await s.settle();}
      assert.equal(s.projection.graph.nodes.find(n=>n.id===id).params.find(p=>p.k===param.k).v,expected,node.title+' edit persists through owner writer');
      assert.equal(panel.querySelector('[role=alert]'),null,node.title+' has no write error');
    }
  }finally{s.close();}
});
test('SYSNODES: Properties and Settings edit one canonical colour cell in both directions',async()=>{
  const s=await mountSystem();try{
    const owner=s.projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.k==='accent'));
    assert.ok(owner,'real accent owner');const accent=owner.params.find(p=>p.k==='accent'),cell=accent.cell_id||accent.value_root||accent.rel;
    await s.select(owner.id);
    const control=()=>s.doc.querySelector('aside [data-sysnode-cell="'+cell+'"] input[type=color]');
    await s.change(control(),'#228844');
    assert.equal(owner.params.find(p=>p.k==='accent').v,'#228844','Properties writes owner source');
    assert.equal(s.win.AH.accent,'#228844','production theme token projection recolours live');
    assert.equal(s.doc.querySelector('[data-node-id="'+owner.id+'"]').style.outlineColor,'rgb(34, 136, 68)','selected real card repaints accent');
    s.win.__courtRender('settings');await s.settle();
    const {settingsNavigator}=require('./settings_navigation_helpers.cjs');
    const nav=settingsNavigator(s);await nav.tab('Theme');
    const landing=()=>s.doc.querySelector('[data-settings54-landing] [data-sysnode-cell="'+cell+'"] input[type=color]');
    assert.equal(landing()?.value,'#228844','Settings reads same canonical cell');
    await s.change(landing(),'#3366aa');
    assert.equal(s.projection.graph.nodes.find(n=>n.id===owner.id).params.find(p=>p.k==='accent').v,'#3366aa','Settings writes owner source');
    await s.select(owner.id);
    assert.equal(control()?.value,'#3366aa','Properties rereads same cell after Settings edit');
    const card=s.doc.querySelector('[data-node-id="'+owner.id+'"]');
    assert.equal(card.querySelector('[data-sysnode-cell="'+cell+'"] input[type=color]')?.value,'#3366aa','card rereads same cell');
  }finally{s.close();}
});
for(const decision of ['approve','reject'])test('SYSNODES: graph chat accent request '+decision+' uses shared Approve and same writer',async()=>{
  const s=await mountSystem({settings:false});try{
    const owner=s.projection.graph.nodes.find(n=>(n.params||[]).some(p=>p.k==='accent'));
    const row=owner.params.find(p=>p.k==='accent'),before=row.v;
    s.win.eval('ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(ScopeComposer,{target:{kind:"graph",id:"app",node:{id:"app",application:true}},model:null})));');
    await s.settle();
    const composer=s.doc.querySelector('[data-sysnodes-chat]') || s.doc.querySelector('textarea[placeholder*="whole graph"]');
    assert.ok(composer,'real graph chat composer');
    await s.change(composer,'@ArchHub set accent to green','input');
    const send=[...s.doc.querySelectorAll('button')].find(b=>/send/i.test((b.getAttribute('aria-label')||'')+' '+(b.getAttribute('title')||'')+' '+b.textContent));
    assert.ok(send&&!send.disabled,'local setting command can send without provider');
    s.flush(()=>send.click());await s.settle();
    const card=s.doc.querySelector('[data-approval-surface="sysnodes"]') || s.doc.querySelector('[data-approval-card]');
    assert.ok(card,'actual shared Approve card');assert.equal(row.v,before,'proposal does not write');
    const choose=[...card.querySelectorAll('button')].find(b=>decision==='approve'?/^Approve/.test(b.textContent.trim()):/Reject|Decline/.test(b.textContent));
    assert.ok(choose,'review decision button');s.flush(()=>choose.click());await s.settle();
    if(decision==='approve'){assert.equal(row.v,'#008000','approved named green reaches canonical cell');assert.equal(s.calls.writes.at(-1)?.id,owner.id);assert.equal(s.calls.writes.at(-1)?.key,'accent');}
    else{assert.equal(row.v,before,'rejected proposal unchanged');assert.equal(s.calls.writes.length,0);}
    assert.equal(s.calls.provider.length,0,'exact local setting command needs no provider');
  }finally{s.close();}
});
}
module.exports={mountSystem,projectionFixture,applicationScripts,normalProjectionMapperSource,seed,root,read};
