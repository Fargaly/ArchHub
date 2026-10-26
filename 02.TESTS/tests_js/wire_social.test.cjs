// Behavioral source-component checks using the shipped Babel and Node only.
// No browser-layout or installed-app result is claimed.
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {setImmediate}=require('node:timers');
const {TextEncoder}=require('node:util');
const {structuredClone,AbortSignal,Uint8Array}=globalThis;
const root=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
const Babel={};vm.runInNewContext(read('vendor/babel.js'),{exports:Babel,module:{exports:Babel}});
const compile=source=>Babel.transform(source,{presets:['react'],sourceMaps:false}).code;
const plain=value=>JSON.parse(JSON.stringify(value));
async function fixture(component,overrides={}){
 let data={graph:{id:'fixture-graph',name:''},profile:{firm:''},providers:[],people:[],brain:[],connections:[],
  social:{office:{name:'',headline:'',bio:'',website:''},inbox:[],drafts:[],groups:[],research:[],tutorials:[],digest:{enabled:false,time:'',summary:''}},
  meeting:{title:'',actions:[],calendarId:'',status:'',transcript:[],consent:false},meetingCalendar:[],
  presentation:{slides:[]},prototype:{name:'',threshold:'',samples:0,baseline:0,linkedModel:false}};
 const calls=[],slots=[],effects=[];let cursor=0,tree;
 const api={ready:Promise.resolve(),getSnapshot:()=>data,subscribe:()=>()=>{},refreshSocialState:async()=>data,refreshSocialMemory:async()=>[],
  addSlide:async()=>{calls.push('addSlide');const row={id:'created-slide',title:'',body:'',layout:'Title'};data={...data,presentation:{slides:[row]}};return row;},
  refreshModelRoster:async()=>{calls.push('refreshModelRoster');return [];},triageSocialInbox:async()=>{calls.push('triageSocialInbox');return {conversations:0};},
  readContentSource:async input=>{calls.push(plain(input));throw Error('The source refused the request. Check its URL and retry.');},...overrides};
 const u={go:screen=>calls.push(['go',screen]),show:(...args)=>calls.push(['show',...args]),setTask:id=>calls.push(['task',id]),setToast:()=>{},download:name=>calls.push(['download',name]),confirm:(_,callback)=>callback()};
 const React={createElement:(type,props,...children)=>({type,props:{...props,children}}),createContext:()=>({}),useContext:()=>u,
  useSyncExternalStore:(_,get)=>get(),useState:initial=>{const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},
  useRef:initial=>{const i=cursor++;return slots[i]||(slots[i]={current:initial});},
  useEffect:(callback,deps)=>{const i=cursor++,prior=slots[i];if(!prior||deps.some((v,j)=>v!==prior[j])){slots[i]=deps;effects.push(callback);}}};
 const w={ArchHubAPI:api,AH:{accent:'#dd7755',inkSoft:'#888888',line:'#333333',userAv:'#555555',ok:'#00aa00',warn:'#ffaa00'},AHIcon:()=>null};
 w.AH_DS={Btn:({children,...props})=>React.createElement('button',props,...children),Card:({children,...props})=>React.createElement('div',props,...children),Avatar:()=>null,Toggle:props=>React.createElement('input',props)};
 const context=vm.createContext({window:w,React,console,setInterval,clearInterval,document:{hidden:false}});
 React.forwardRef=render=>render;
 const components=w.AH_DS;vm.runInContext(compile(read('ds/index.jsx')),context);w.AH_DS=components;
 vm.runInContext(compile(read('ui.jsx')),context,{filename:'ui.jsx'});
 w.UI.Composer=()=>null;w.UI.TranscriptProvenance=()=>null;
 for(const file of ['social.jsx','research-surfaces.jsx','meetings.jsx','ds_colleagues.jsx'])vm.runInContext(compile(read(file)),context,{filename:file});
 w.UI.Composer=()=>null;w.UI.TranscriptProvenance=()=>null;
 const expand=node=>{if(node==null||typeof node!=='object')return node;if(Array.isArray(node))return node.map(expand);if(typeof node.type==='function')return expand(node.type(node.props));return {...node,props:{...node.props,children:(node.props.children||[]).map(expand)}};};
 const render=()=>{cursor=0;tree=expand(w.UI[component]());};
 const settle=async()=>{for(let i=0;i<4;i++){render();while(effects.length)effects.shift()();await new Promise(resolve=>setImmediate(resolve));}render();};
 const all=()=>{const found=[];function walk(n){if(Array.isArray(n))n.forEach(walk);else if(n&&typeof n==='object'){found.push(n);walk(n.props.children);}}walk(tree);return found;};
 const text=node=>node==null||typeof node==='boolean'?'':Array.isArray(node)?node.map(text).join(''):typeof node==='object'?text(node.props.children):String(node);
 const button=label=>all().find(n=>n.type==='button'&&(n.props['aria-label']===label||text(n).trim()===label));
 const click=async label=>{const control=button(label);assert.ok(control,'button '+label);assert.ok(!control.props.disabled,'enabled '+label);await control.props.onClick({});await settle();};
 await settle();return {api,calls,button,click,settle,all,text:()=>text(tree),input:label=>all().find(n=>n.props['aria-label']===label)};
}

test('empty presentation keeps Add slide executable and renders the owner-created slide',async()=>{
 const h=await fixture('Present');await h.click('Add slide');assert.deepEqual(h.calls,['addSlide']);assert.ok(h.input('Slide title'));assert.doesNotMatch(h.text(),/Office 301|Meeting 302/);await h.click('Export');assert.deepEqual(h.calls.at(-1),['download','Presentation']);
});
test('Social navigation reaches the actual triage and settings handlers',async()=>{
 const h=await fixture('Social');await h.click('Inbox');await h.click('Triage inbox');assert.deepEqual(h.calls,['triageSocialInbox']);await h.click('Social connection settings');assert.deepEqual(h.calls.at(-1),['go','settings/Connections']);
});
test('source error retains the input and Retry invokes the failed owner request',async()=>{
 const h=await fixture('Social');await h.click('Read');await h.input('Content source').props.onChange({target:{value:'https://example.invalid/missing'}});await h.settle();const reads=h.all().filter(n=>n.type==='button'&&n.props.children.join('')==='Read');await reads.at(-1).props.onClick({});await h.settle();assert.match(h.text(),/Check its URL/);assert.equal(h.input('Content source').props.value,'https://example.invalid/missing');await h.click('Retry');assert.deepEqual(h.calls,[{kind:'Web',url:'https://example.invalid/missing'},{kind:'Web',url:'https://example.invalid/missing'}]);
});
test('model refresh calls the live roster adapter',async()=>{const h=await fixture('ModelAvailability');await h.click('Refresh models');assert.deepEqual(h.calls,['refreshModelRoster']);});
test('Colleagues navigation and Meetings source imports stay executable',async()=>{
 const h=await fixture('Colleagues');await h.click('Meetings');assert.deepEqual(h.calls.at(-1),['go','meetings']);let imported=false;const m=await fixture('Meetings',{importMeetingCalendar:async()=>{imported=true;return [];}});await m.click('Read calendar file');assert.ok(imported);
});

test('actual adapter sends graph operations and rejects failed writes without optimistic publication',async()=>{
 const posts=[],events=[];
 const canvas={root:'fixture-graph',nodes:[],wires:[],scope:{current:'fixture-graph'},workshop_scope:{workshops:[{root:'fixture-workshop',is_general:true}]}};
 let saved={social:{office:{name:''},drafts:[],inbox:[],groups:[],digest:{},research:[],tutorials:[]},presentation:{slides:[]},meeting:{transcript:[]}},refuse=false;
 const w={ARCHHUB_BOOT:{home_load_ms:60000,token:'fixture-session',csrf:'fixture-csrf'},structuredClone,
  addEventListener(){},dispatchEvent:e=>events.push(e),crypto:require('node:crypto').webcrypto,
  Uint8Array,setInterval(){throw Error('No background timer without subscribers');},clearInterval(){}};
 w.ArchHubStudioAuthority={create:({get})=>{let snapshot=null;return {load:async()=>{snapshot={canvas:await get('/api/universal/canvas')};return snapshot.canvas;},getSnapshot:()=>snapshot,clear:()=>{snapshot=null;},adopt:async canvas=>{snapshot={canvas};return canvas;},transact:async action=>{const canvas=await action();snapshot={canvas};return canvas;}};}};
 const fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;
  if(body)posts.push({url,body,headers:options.headers});
  let data={ok:true};
  if(url==='/api/universal/canvas')data=canvas;
  if(url==='/api/universal/social-connections')data={ok:true,items:[]};
  if(url==='/api/universal/social-surface'){
   if(refuse)return {ok:false,status:409,json:async()=>({ok:false,error:'Owner rejected this draft. Correct the account and retry.'})};
   if(body.op==='save_social_draft')saved={...saved,social:{...saved.social,drafts:[{...body.args[0],id:'saved-draft',status:'Draft'}]}};
   data={ok:true,state:structuredClone(saved),result:body.op==='save_social_draft'?saved.social.drafts[0]:structuredClone(saved)};
  }
  if(url==='/api/universal/workshop')data={ok:true,result:body.function==='sendToBaboom'?{id:'actual-work',title:'Review requested'}:[]};
  if(url==='/api/universal/graphs?screen=home')data={ok:true,graphs:[]};
  if(url==='/api/universal/workspace-roots')data={ok:true,roots:[]};
  if(url==='/api/universal/providers')data={ok:true,providers:[]};
  return {ok:true,status:200,json:async()=>data};
 };
 const context=vm.createContext({window:w,setTimeout,clearTimeout,document:{hidden:false,addEventListener(){}},fetch,TextEncoder,URLSearchParams,AbortSignal,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},sessionStorage:{getItem(){return null},setItem(){}},console});
 vm.runInContext(read('api.js'),context,{filename:'api.js'});
 const api=w.ArchHubAPI;await api.ready;await new Promise(resolve=>setImmediate(resolve));
 const draft=await api.saveSocialDraft({platform:'LinkedIn',text:'User draft'});
 assert.equal(draft.id,'saved-draft');
 const request=posts.find(p=>p.body.op==='save_social_draft');
 assert.equal(request.url,'/api/universal/social-surface');assert.equal(request.headers['X-ArchHub-CSRF'],'fixture-csrf');
 refuse=true;await assert.rejects(api.updateOfficePage({name:'Must not appear'}),/Owner rejected/);
 assert.equal(api.getSnapshot().social.office.name,'');
 refuse=false;const work=await api.proposeSocialDraft(draft.id);
 assert.equal(work.id,'actual-work');await api.proposeSocialDraft(draft.id);const reviewRequests=posts.filter(p=>p.body.function==='sendToBaboom');assert.equal(reviewRequests[0].body.request_id,reviewRequests[1].body.request_id);assert.equal(api.getSnapshot().social.drafts[0].status,'Draft');
 assert.ok(posts.some(p=>p.body.function==='sendToBaboom'&&p.body.args[0].includes('social.work_prepare')));
 const exported=await api.exportData('Presentation');assert.equal(exported.content,JSON.stringify(saved.presentation,null,2));
 return undefined;
});
