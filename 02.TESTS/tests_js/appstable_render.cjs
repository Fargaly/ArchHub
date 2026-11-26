/* Headless controlled replay of actual compiled Studio components, never the live profile. */
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

async function run(studio, output) {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  const checks = [];
  const check = (name, ok, detail) => checks.push({name,ok:!!ok,detail});
  try {
    for (const screen of ['workshop','colleagues']) {
      const page = await browser.newPage({viewport:{width:1440,height:900}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      // A localhost page is a secure context (api.js needs crypto.randomUUID); nothing is served beyond this fixture.
      await page.route('http://localhost/fixture', route => route.fulfill({contentType:'text/html',body:'<html><body><div id="root"></div></body></html>'}));
      await page.goto('http://localhost/fixture');
      await page.addStyleTag({path:path.join(studio,'style.css')});
      await page.addStyleTag({content:'#root{height:100vh;display:grid;grid-template-rows:minmax(0,1fr)}'});
      for (const source of ['vendor/react.js','vendor/react-dom.js'])
        await page.addScriptTag({path:path.join(studio,source)});
      await page.evaluate(() => {
        const tasks = [
          {id:'work:gate',title:'Deploy gate v2 to the live governance write gate',status:'PLANNED',owner:null},
          {id:'work:control',title:'Restore isolated application control for the original task',status:'WIP',owner:'codex'},
          {id:'work:roots',title:'Deploy the workspace-roots reader that never opens the key',status:'PLANNED',owner:null},
          {id:'work:design',title:"Workshop screen built to the founder's design (Board + Agents first)",status:'WIP',owner:'claude'},
        ].map(task => ({...task,messages:[],steps:[]}));
        window.fixture = {providers:[],profile:{name:'Fixture user',firm:'Fixture team'},
          graph:{id:'graph:fixture',name:'Fixture graph',nodes:[]},graphs:[],tasks,people:[],brain:[],
          meeting:{title:'Team & meetings',actions:[],actionOwners:{},actionTasks:{}},
          composerAttachments:[],workshopMessages:[],workshopMessagesMore:false};
        window.calls = [];
        window.socialRequests = [];
        window.app = {task:'work:gate',selectedNodeId:null,act:async fn => fn(),
          show:(...args) => window.calls.push(['show',...args]),go:route => window.calls.push(['go',route]),
          setTask:id => window.calls.push(['task',id])};
        window.fetch = async () => ({ok:true,status:200,json:async () => ({providers:[
          {id:'openrouter',name:'OpenRouter',state:'keyed'},
          {id:'cloud',name:'ArchHub cloud',state:'no key'},
          {id:'openai',name:'OpenAI',state:'keyed'},
          {id:'google',name:'Google',state:'no key'},
          {id:'nvidia',name:'NVIDIA NIM',state:'key invalid'},
          {id:'anthropic',name:'Anthropic',state:'no key'}]})});
        window.ARCHHUB_NATIVE_APPROVAL = {binding:'fixture',approval:{rows:[]}};
      });
      // api.js builds its canvas command queue from studio-authority.js at startup.
      await page.addScriptTag({path:path.join(studio,'studio-authority.js')});
      await page.addScriptTag({path:path.join(studio,'compiled/api.js')});
      await page.evaluate(async () => {
        await window.ArchHubAPI.ready;
        window.fixture.providers = await window.ArchHubAPI.listProviders();
        window.ArchHubAPI = {...window.ArchHubAPI,getSnapshot:() => window.fixture,subscribe:() => () => {},
          refreshSocialState:() => new Promise((resolve,reject) => {window.socialRequests.push({resolve,reject});}),
          refreshSocialMemory:async () => [],supportsAction:() => true,
          remember:async text => {window.calls.push(['remember',text]);const row={id:'fact:fixture',text,source:'Fixture input'};window.fixture.brain=[row];return row;},
          editMemory:async (id,text) => {window.calls.push(['edit',id,text]);window.fixture.brain=window.fixture.brain.map(row=>row.id===id?{...row,text}:row);return {id};},
          forgetMemory:async id => {window.calls.push(['forget',id]);window.fixture.brain=[];return {id};},
          sendToBaboom:async (text,options) => {window.calls.push(['send',text,options]);return window.fixture.tasks[0];},
          sendChatTurn:async turn => {window.calls.push(['send',turn.prompt]);return {ok:true};},listTasks:async () => []};
      });
      for (const source of ['tokens.js','ds-index.js','icons.js','ui.js','ds_workshop3.js','dock.js','ds_colleagues.js'])
        await page.addScriptTag({path:path.join(studio,'compiled',source)});
      await page.evaluate(screen => {
        const UI=window.UI;
        // The Workshop is the dock panel beside the Canvas, with the Canvas thread's composer (the page is gone).
        const workshop = () => React.createElement('div',{'data-screen':'workshop',className:'dockws',style:{display:'grid',gridTemplateColumns:'340px minmax(0,1fr)',height:'100%'}},
          React.createElement('aside',null,React.createElement(UI.DockWorkshop,{onShow:({task}) => window.calls.push(['task',task.id])})),
          React.createElement('main',null,React.createElement(UI.TaskComposer,{choices:[],to:'',setTo:() => {}})));
        window.ReactDOM.createRoot(document.getElementById('root')).render(
          React.createElement(UI.Ctx.Provider,{value:window.app},
            React.createElement(screen==='colleagues'?UI.Colleagues:workshop)));
      },screen);
      try {await page.waitForSelector('[data-screen="'+screen+'"]');}
      catch (error) {check(screen+' renders',false,[...errors,error.message]);await page.close();continue;}
      await page.screenshot({path:path.join(output,screen+'.png')});
      const layout = await page.evaluate(screen => {
        const root=document.querySelector('[data-screen="'+screen+'"]');
        const aside=root.querySelector(':scope > aside'), main=root.querySelector(':scope > main');
        const box=element => {const r=element.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};};
        return {children:root.children.length,aside:box(aside),main:box(main),
          text:root.innerText,avatars:[...root.querySelectorAll('[data-workshop-avatar]')].map(e=>e.innerText),
          overflow:root.scrollWidth>root.clientWidth};
      },screen);
      check(screen+' two-column geometry',layout.children===2&&layout.aside.x===0&&layout.main.x===340&&
        Math.abs(layout.main.y-layout.aside.y)<1&&layout.main.w>=1000&&!layout.overflow,layout);
      check(screen+' no question avatars',!layout.avatars.includes('?'),layout.avatars);
      if (screen==='colleagues') {
        check('Team no dead-owner placeholder',!layout.text.includes('Waiting for the owner'),layout.text.slice(0,180));
        check('Team connected providers available',layout.text.includes('Available')&&!layout.text.includes('Unavailable'),layout.text.slice(0,260));
        await page.evaluate(() => window.socialRequests.forEach(request => request.reject(new Error('Fixture service offline; retry.'))));
        await page.getByRole('alert').filter({hasText:'Fixture service offline'}).first().waitFor();
        check('Team action errors remain visible',await page.getByRole('button',{name:'Retry',exact:true}).count()>0,null);
        await page.getByRole('button',{name:'Retry',exact:true}).first().click();
        await page.evaluate(() => window.socialRequests.at(-1).resolve(window.fixture));
        await page.getByRole('alert').filter({hasText:'Fixture service offline'}).waitFor({state:'hidden'});
        check('Team retry recovers the existing request',await page.getByRole('alert').count()===0,null);
        await page.getByRole('button',{name:/OpenAI/}).click();
        await page.getByRole('button',{name:'Meetings',exact:true}).click();
        await page.getByRole('button',{name:'New task',exact:true}).click();
        check('Team agent/meeting/task actions',await page.evaluate(() =>
          window.calls.some(c=>c[0]==='show'&&c[1]==='Agent'&&c[2].id==='openai')&&
          window.calls.some(c=>c[0]==='go'&&c[1]==='meetings')&&window.calls.some(c=>c[1]==='New task')),null);
        await page.getByRole('button',{name:'Remember',exact:true}).click();
        await page.getByRole('textbox',{name:'Learned rule'}).fill('Preserve the existing owner');
        await page.getByRole('button',{name:'Save',exact:true}).click();
        await page.getByText('Preserve the existing owner',{exact:true}).waitFor();
        await page.getByRole('button',{name:'Edit',exact:true}).click();
        await page.getByRole('textbox',{name:'Learned rule'}).fill('Updated fixture rule');
        await page.getByRole('button',{name:'Save',exact:true}).click();
        await page.getByText('Updated fixture rule',{exact:true}).waitFor();
        await page.getByRole('button',{name:'Forget',exact:true}).click();
        await page.getByText('No learned rules.',{exact:true}).waitFor();
        check('Team memory create/edit/forget actions',await page.evaluate(() =>
          window.calls.some(c=>c[0]==='remember'&&c[1]==='Preserve the existing owner')&&
          window.calls.some(c=>c[0]==='edit'&&c[1]==='fact:fixture'&&c[2]==='Updated fixture rule')&&
          window.calls.some(c=>c[0]==='forget'&&c[1]==='fact:fixture')),null);
      } else {
        check('Workshop honest unassigned owner',!layout.text.includes('null'),layout.text.slice(-350));
        await page.getByRole('textbox',{name:'Search threads'}).fill('isolated application');
        check('Workshop search preserves saved tasks',await page.locator('[data-ws-working]').count()===1,null);
        await page.getByRole('textbox',{name:'Search threads'}).fill('');
        check('Workshop search clears back to every task',await page.locator('[data-ws-working]').count()===2,null);
        await page.getByRole('button',{name:/Restore isolated application/}).click();
        await page.getByRole('button',{name:'Board',exact:true}).click();
        await page.getByRole('button',{name:'Inbox',exact:true}).click();
        check('Workshop task/board/inbox actions',await page.evaluate(() =>
          window.calls.some(c=>c[0]==='task'&&c[1]==='work:control')&&
          window.calls.some(c=>c[1]==='Workshop board')&&window.calls.some(c=>c[1]==='Founder inbox')),null);
      }
      await page.getByRole('textbox',{name:'Message',exact:true}).fill('Fixture-only reply');
      await page.getByRole('textbox',{name:'Message',exact:true}).press('Enter');
      check(screen+' composer still sends',await page.evaluate(() => window.calls.some(c=>c[0]==='send'&&c[1]==='Fixture-only reply')),null);
      check(screen+' no browser exception',errors.length===0,errors);
      await page.close();
    }
  } finally {await browser.close();}
  fs.writeFileSync(path.join(output,'render.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify(checks.map(({name,ok})=>({name,ok})),null,2));
  if(checks.some(row=>!row.ok))process.exitCode=1;
}

if(require.main===module)run(path.resolve(process.argv[2]),path.resolve(process.argv[3])).catch(error=>{
  console.error(error);process.exitCode=1;
});
module.exports={run};
