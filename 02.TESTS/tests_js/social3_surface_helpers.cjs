const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const providers = ['instagram','facebook','linkedin','whatsapp','x','tiktok'];
const names = ['Instagram','Facebook','LinkedIn','WhatsApp Business','X','TikTok'];
const Babel = {};
vm.runInNewContext(read('01.APP/nodelang/studio/vendor/babel.js'), {exports:Babel, module:{exports:Babel}});
const compile = source => Babel.transform(source, {presets:['react'], sourceMaps:false}).code;
const section = (source, start, end) => source.slice(source.indexOf(start), source.indexOf(end));

async function mount({rows, statuses = {}, start, node = false, nodeParams = []} = {}) {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/',runScripts:'outside-only',pretendToBeVisual:true});
  const w = dom.window;
  w.fetch = () => { throw new Error('Live endpoints forbidden'); };
  w.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  w.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  w.eval(compile(read('01.APP/nodelang/studio/tokens.jsx')));
  w.eval(compile(read('01.APP/nodelang/studio/ds/index.jsx')));
  const calls = {start:[],finish:[],cancel:[],params:[]};
  w.ARCHHUB_EXISTING_WORKSHOP = {
    listSocialConnections:async () => rows || providers.map((provider,i) => ({provider,name:names[i],state:'not_connected'})),
    startSocialConnection:async provider => {calls.start.push(provider); return start ? start(provider) : {provider,state:'connecting'};},
    socialConnectionStatus:async provider => statuses[provider] || {provider,state:'ready'},
    finishSocialConnection:async (provider,account_id) => {calls.finish.push([provider,account_id]);return {provider,state:'connected',display_name:'@founder'};},
    cancelSocialConnection:async provider => {calls.cancel.push(provider); return {provider,state:'not_connected'};},
    listSocialApprovals:async () => [],
    installMcpClient:async () => ({ok:true}),
  };
  const source = read('01.APP/nodelang/studio/studio-lm.jsx');
  const surface = section(source, 'const SocialConnectionRow =', "// The design's per-row");
  const approvals = section(source, 'const SettingsSocialApprovals =', 'const socialAccountView =');
  w.eval(compile(`const LM = window.AH; const smallBtn = primary => ({color:LM.ink,background:primary?LM.accent:LM.bgSoft,padding:'8px 14px',borderRadius:6,border:'1px solid '+LM.line,cursor:'pointer'}); ${approvals}\n${surface}\nwindow.Social3Surface = SettingsConnections;`));
  if(node) {
    w.ARCHHUB_STUDIO_AUTHORITY={};
    w.ARCHHUB_SET_NODE_PROP=async (id,key,value)=>{calls.params.push([id,key,value]);return {ok:true};};
    w.eval(compile(read('01.APP/nodelang/studio/param-types.jsx')));
    w.eval(compile(read('01.APP/nodelang/studio/studio-params.jsx')));
  }
  const nodeValue=JSON.stringify({id:'connections',application:true,title:'Connections',group:'Connections',params:nodeParams});
  w.eval(`window.__root = ReactDOM.createRoot(document.getElementById('root')); ReactDOM.flushSync(() => window.__root.render(React.createElement(${node ? 'window.ApplicationNodeParameters,{node:'+nodeValue+'}' : 'window.Social3Surface'})));`);
  const settle = async () => {for(let i=0;i<8;i++) await new Promise(resolve=>w.setTimeout(resolve,0));};
  await settle();
  const openPalette = async () => {
    const host=w.document.createElement('div');w.document.body.appendChild(host);host.id='palette';
    const commandBar=section(source,'const CommandBar =','const AppToast =');
    w.eval(compile(`(() => {const LM=window.AH; const useNodeLibrary=()=>{}, useCatalogueVersion=()=>{}, useStudioProjection=()=>null, withHistoryLibrary=x=>x, loadCatalogue=()=>{};
      const catalogueStates=new Map(), LM_LIBRARY=[], LM_SAVED_SKILLS=[], LM_SESSIONS=[];
      ${commandBar}\nwindow.__paletteRoot=ReactDOM.createRoot(document.getElementById('palette'));ReactDOM.flushSync(()=>window.__paletteRoot.render(React.createElement(CommandBar,{open:true,onClose:()=>{window.__paletteClosed=true;}})));})();`));
    await settle();
  };
  return {w,doc:w.document,calls,settle,openPalette,click:async el=>{assert.ok(el,'control exists');w.ReactDOM.flushSync(()=>el.click());await settle();},close:()=>{w.ReactDOM.flushSync(()=>{w.__root.unmount();w.__paletteRoot?.unmount();});w.close();}};
}


module.exports = {mount,providers,names};
