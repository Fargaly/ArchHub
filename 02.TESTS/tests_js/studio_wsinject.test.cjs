const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {transformSync}=require('esbuild');

test('Workshop renders each real projected delivery state alongside its message',()=>{
  const window={UI:{A:{},D:{},Av:()=>null,TurnUsage:()=>null,AnswerWidget:()=>null,AnswerSources:()=>null},
    ArchHubAPI:{executeAction:()=>{},getSnapshot:()=>({providers:[]})}};
  const context=vm.createContext({window,React});
  vm.runInContext(transformSync(fs.readFileSync(path.join(__dirname,
    '../../01.APP/nodelang/studio/ds_workshop3.jsx'),'utf8'),{loader:'jsx'}).code,context);
  const html=renderToStaticMarkup(React.createElement(window.UI.Messages,{task:{messages:[
    {id:'m1',who:'You',text:'To Codex',state:'pending'},
    {id:'m2',who:'You',text:'To Cursor',state:'delivered'},
    {id:'m3',who:'You',text:'To Claude',state:'answered'}]}}));
  for(const state of ['pending','delivered','answered']) {
    assert.match(html,new RegExp('data-delivery-state="'+state+'"'));
    assert.match(html,new RegExp(state,'i'));
  }
  assert.match(html,/role="status"/);
});

test('Workshop discards an older page that arrives after a graph or account switch',async()=>{
  const {JSDOM}=require('jsdom');
  const dom=new JSDOM('<div id="root"></div>',{url:'http://127.0.0.1/'});
  const oldWindow=globalThis.window,oldDocument=globalThis.document;
  globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  const {createRoot}=require('react-dom/client');
  let data={tasks:[],providers:[],profile:{email:'a@example.test'},graph:{id:'A',name:'A'},
    workshopMessages:[{id:'a',who:'You',text:'Current A'}],workshopMessagesMore:true,workshopMessagesBefore:2};
  let finish;
  const pending=new Promise(resolve=>{finish=resolve;});
  const button=props=>React.createElement('button',{onClick:props.onClick},props.children);
  const wrapper=tag=>props=>React.createElement(tag,{},props.children);
  const window={UI:{A:{lineSoft:'#222'},D:{},useData:()=>data,useApp:()=>({}),Av:()=>null,Btn:button,
    Card:wrapper('div'),Chip:wrapper('span'),Composer:()=>null,Empty:wrapper('p'),
    TurnUsage:()=>null,AnswerWidget:()=>null,AnswerSources:()=>null},
    ArchHubAPI:{executeAction:name=>name==='listWorkshopMessages'?pending:undefined,getSnapshot:()=>({providers:[]}),listWorkshopMessages:()=>pending}};
  vm.runInContext(transformSync(fs.readFileSync(path.join(__dirname,
    '../../01.APP/nodelang/studio/ds_workshop3.jsx'),'utf8'),{loader:'jsx'}).code,vm.createContext({window,React}));
  const root=createRoot(dom.window.document.getElementById('root'));
  try{
    await React.act(async()=>root.render(React.createElement(window.UI.Workshop)));
    await React.act(async()=>[...dom.window.document.querySelectorAll('button')].find(el=>el.textContent==='Older messages').click());
    data={...data,profile:{email:'b@example.test'},graph:{id:'B',name:'B'},workshopMessagesMore:false,
      workshopMessages:[{id:'b',who:'You',text:'Current B'}]};
    await React.act(async()=>root.render(React.createElement(window.UI.Workshop)));
    await React.act(async()=>{finish({messages:[{id:'old-a',who:'You',text:'Private old A'}],next_before:1,more:false});await pending;});
    assert.match(dom.window.document.body.textContent,/Current B/);
    assert.doesNotMatch(dom.window.document.body.textContent,/Private old A|Current A/);
  }finally{
    await React.act(async()=>root.unmount());dom.window.close();globalThis.window=oldWindow;globalThis.document=oldDocument;
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  }
});

test('Workshop room renders real mailbox projection even with no Work tasks',async()=>{
  const page=process.env.WSINJECT_UI_DATA?JSON.parse(fs.readFileSync(process.env.WSINJECT_UI_DATA,'utf8')):
    {messages:[{id:'pending',who:'Claude',text:'To Codex',state:'pending'},
      {id:'delivered',who:'Codex',text:'To Cursor',state:'delivered'},
      {id:'answered',who:'Cursor',text:'To Claude',state:'answered'}]};
  const data={tasks:[],providers:[],profile:{},graph:{name:'Fixture Workshop'},workshopMessages:page.messages};
  const wrapper=tag=>props=>React.createElement(tag,{},props.children);
  const window={UI:{A:{lineSoft:'#2a2a31'},D:{},useData:()=>data,useApp:()=>({}),
    Av:()=>null,Btn:wrapper('button'),Card:wrapper('div'),Chip:wrapper('span'),Composer:()=>null,
    Empty:wrapper('p'),TurnUsage:()=>null,AnswerWidget:()=>null,AnswerSources:()=>null},
    ArchHubAPI:{executeAction:()=>{},getSnapshot:()=>({providers:[]})}};
  vm.runInContext(transformSync(fs.readFileSync(path.join(__dirname,
    '../../01.APP/nodelang/studio/ds_workshop3.jsx'),'utf8'),{loader:'jsx'}).code,vm.createContext({window,React}));
  const html=renderToStaticMarkup(React.createElement(window.UI.Workshop));
  assert.match(html,/Workshop room/);
  for(const row of page.messages){assert.ok(html.includes(row.text.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')));}
  for(const state of ['pending','delivered','answered'])assert.match(html,new RegExp('data-delivery-state="'+state+'"'));
  if(process.env.WSINJECT_SCREENSHOT){
    const {chromium}=require('playwright');
    const browser=await chromium.launch({headless:true,...(process.env.WSINJECT_CHROME?{executablePath:process.env.WSINJECT_CHROME}:{})});
    try{
      const screen=await browser.newPage({viewport:{width:1280,height:1000}});
      await screen.setContent('<html><body style="margin:0;background:#0c0c0f;color:#eee;font-family:Arial">'+html+'</body></html>');
      await screen.screenshot({path:process.env.WSINJECT_SCREENSHOT,fullPage:true});
    }finally{await browser.close();}
  }
});
