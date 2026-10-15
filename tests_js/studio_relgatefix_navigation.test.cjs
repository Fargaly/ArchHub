const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {transformSync} = require('esbuild');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const source = read('nodelang/studio/studio-lm.jsx');
const shared = read('nodelang/studio/shared-data.jsx');
const part = (text, start, end) => text.slice(text.indexOf(start), text.indexOf(end, text.indexOf(start)));
// Real shell and header; a physical pointer click must hit the header, not its breadcrumb overlay.
async function mount() {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1440,height:900}});
  await page.setContent('<style>html,body,#root{margin:0;width:100%;height:100%}button{box-sizing:border-box}</style><div id="root"></div>');
  await page.addScriptTag({content:read('nodelang/studio/vendor/react.js')});
  await page.addScriptTag({content:read('nodelang/studio/vendor/react-dom.js')});
  const rail = shared.slice(shared.indexOf('window.ARCHHUB_APP_RAIL ='));
  const topProp = source.match(/      top=\{([^\n]+)\}/)[1];
  await page.addScriptTag({content:transformSync(`
    const LM={bgDeep:'#0c0c0e',bg:'#111',bgPanel:'#151515',bgHover:'#222',ink:'#eee',inkSoft:'#999',sans:'Arial',lineSoft:'#222',line:'#333',accent:'#e88',warn:'#fa0',rad:{sm:5,md:8},fs:{dataSm:{sz:11}},userAv:'#cba',onUserAv:'#111',elev:{e1:'none'}};
    window.AH=LM; const useWorkshopProjection=()=>({}); const workshopWaitingItems=()=>[];
    ${rail}
    ${part(source,'// DSYS-060 app frame parts.','const isHistoryNode =')}
    ${part(source,'const WsHeader =','const ContextMenu =') .split('const WsTab =')[0]}
    const WsTab=({s,a,onClick,onClose})=><span data-ws-tab={s.id} aria-current={a?'page':undefined}><button onClick={onClick}>{s.title}</button><button title="Close tab" onClick={onClose}>×</button></span>;
    const LM_STATE_META={idle:{}}; const ApplicationUpdateControls=()=>null;
    function Harness(){const [tabs,setTabs]=React.useState(['a']);const [active,setActive]=React.useState('a');const [screen,setScreen]=React.useState('Canvas');
      const session=screen==='Canvas'?{id:active,title:'Session'}:null;const frameCrumbs=['ArchHub',screen];
      const goHome=()=>setScreen('Home');const navigate=name=>setScreen(name);
      return <Frame rail={screen} onHome={goHome} onChats={()=>navigate('Chats')} onDocs={()=>navigate('Docs')} onAccount={()=>navigate('Account')} onPanel={()=>navigate('Library')} onWorkshop={()=>navigate('Workshop')} onCanvas={()=>navigate('Canvas')} onSettings={()=>navigate('Settings')} account={{}} top={${topProp}}>
        <main data-workspace-main="" style={{height:'100%',display:'grid',gridTemplateRows:'36px 1fr'}}>
          {session?<WsHeader session={session} openTabs={tabs} sessionRows={tabs.map(id=>({id,title:id==='a'?'First session':'New session',state:'idle'}))} setOpenId={setActive} closeTab={()=>{}} onHome={goHome} onNewSession={()=>{setTabs([...tabs,'b']);setActive('b');}}/>:<h1>{screen}</h1>}
        </main></Frame>}
    ReactDOM.flushSync(()=>ReactDOM.createRoot(document.getElementById('root')).render(<Harness/>));`,{loader:'jsx'}).code});
  return {browser,page};
}
test('RELGATEFIX G2 physical + is unobscured and opens a second active tab',async()=>{
  const {browser,page}=await mount();try{
    const plus=page.getByRole('button',{name:'New session',exact:true});
    const hit=await plus.evaluate(el=>{const r=el.getBoundingClientRect();const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return el===hit||el.contains(hit);});
    assert.equal(hit,true,'the visible + receives the founder pointer click');
    await plus.click();assert.equal(await page.locator('[data-ws-tab]').count(),2);
    assert.equal(await page.locator('[data-ws-tab="b"]').getAttribute('aria-current'),'page');
    await page.getByRole('button',{name:'First session',exact:true}).click();
    assert.equal(await page.locator('[data-ws-tab="a"]').getAttribute('aria-current'),'page');
  }finally{await browser.close();}
});
test('RELGATEFIX one rail exposes and routes Home Workshop Canvas Library Settings',async()=>{
  const {browser,page}=await mount();try{
    const labels=()=>page.locator('nav [data-rail-panel]').evaluateAll(els=>els.map(el=>el.getAttribute('data-rail-panel')));
    assert.deepEqual(await labels(),['Home','Chats','Workshop','Canvas','Library','Docs','Settings','Account']);
    for(const name of ['Home','Chats','Workshop','Canvas','Library','Docs','Settings','Account']){
      await page.locator('nav [data-rail-panel="'+name+'"]').click();
      assert.deepEqual(await labels(),['Home','Chats','Workshop','Canvas','Library','Docs','Settings','Account']);
      assert.equal(await page.locator('nav').count(),1);
      assert.equal(await page.locator('nav [data-rail-panel="'+name+'"]').getAttribute('aria-current'),'true');
    }
  }finally{await browser.close();}
});
