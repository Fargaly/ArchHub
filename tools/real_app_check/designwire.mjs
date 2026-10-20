import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(path.join(process.env.DESIGNWIRE_MODULES,'package.json'));
const {chromium}=require('playwright');
const out=process.env.DESIGNWIRE_OUT;
const timeoutMs=Number(process.env.DESIGNWIRE_TIMEOUT_MS);
if(!Number.isFinite(timeoutMs)||timeoutMs<=0)throw Error('DESIGNWIRE_TIMEOUT_MS must name the run budget.');
const context=await chromium.launchPersistentContext(process.env.DESIGNWIRE_PROFILE,{executablePath:'C:/Users/fargaly/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',headless:true,viewport:{width:1496,height:959},args:['--disable-gpu','--disable-gpu-shader-disk-cache','--disable-background-networking']});
const browser=context;
const page=await context.newPage();
const report={url:new URL(process.env.DESIGNWIRE_URL).origin+'/studio',consoleErrors:[],pageErrors:[],screens:[],checks:[],requests:[]};
page.on('console',(m)=>{if(m.type()==='error')report.consoleErrors.push(m.text());});
page.on('pageerror',(e)=>report.pageErrors.push(e.message));
page.on('request',(r)=>{if(r.url().includes('/api/'))report.requests.push({method:r.method(),path:new URL(r.url()).pathname});});
page.setDefaultTimeout(timeoutMs);
async function check(name,fn){await Promise.resolve().then(fn).then(()=>report.checks.push({name,status:'PASS'}),(failure)=>report.checks.push({name,status:'FAIL',error:failure.message}));console.log(JSON.stringify(report.checks.at(-1)));}
function assert(value,why){if(!value)throw Error(why);}
async function go(label){if(await page.getByText('Could not open this view',{exact:true}).count()){await page.reload({waitUntil:'networkidle'});await page.locator('[data-screen="home"]').waitFor();}await page.getByRole('button',{name:'ArchHub menu',exact:true}).click();await page.locator('.context-menu').getByRole('button',{name:label,exact:true}).click();}
const execution=(async()=>{
 await page.goto(process.env.DESIGNWIRE_URL,{waitUntil:'networkidle'});
 await check('Built approved Home opens',async()=>{await page.locator('[data-screen="home"]').waitFor({timeout:timeoutMs});assert(await page.locator('.home-content').count()===1,'Approved Home layout missing');});
 await page.screenshot({path:path.join(out,'home.png')});
 if(report.checks.at(-1).status!=='PASS')throw Error('Boot refused: '+await page.locator('body').innerText());
 const names=['Home','Workshop','Canvas','Docs','Team','Brain','Watcher','Meetings','Dependencies','Present','Community','Model review','Interface studio','Plan & access','Model routing','Social media','X-RAY','Runs','Logs & receipts','Automations','System graph','Feedback','First run'];
 for(const name of names){
  await check('Screen '+name,async()=>{await go(name);await page.waitForTimeout(75);assert(!await page.getByText('Could not open this view',{exact:true}).count(),'Error boundary');assert(await page.locator('[data-screen]').count()>0,'No rendered screen');});
  const file=name.toLowerCase().replaceAll(/[^a-z0-9]+/g,'-')+'.png';await page.screenshot({path:path.join(out,file)});report.screens.push({name,file});
 }
 if(await page.getByText('Could not open this view',{exact:true}).count()){await page.reload({waitUntil:'networkidle'});await page.locator('[data-screen="home"]').waitFor();}
 await page.getByRole('button',{name:'Settings',exact:true}).first().click();
 const pages=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().pages);
 for(const settingName of pages){await check('Settings '+settingName,async()=>{await page.locator('.settings-side').getByRole('button',{name:settingName,exact:true}).first().click();assert(!await page.getByText('Could not open this view',{exact:true}).count(),'Error boundary');});await page.screenshot({path:path.join(out,'settings-'+settingName.toLowerCase().replaceAll(/[^a-z0-9]+/g,'-')+'.png')});}
 await check('Workspace catalogue projects its actual built-in identity',async()=>{const roots=await page.evaluate(()=>window.ArchHubAPI.listWorkspaces());assert(roots.some((r)=>r.id==='archhub'&&r.builtIn===true&&r.removable===false),'Built-in workspace identity was lost');assert(roots.every((r)=>r.id),'Undefined workspace identity');});
 await check('Native Shows as persists through actual signed owner',async()=>{
  const result=await page.evaluate(async()=>{const api=window.ArchHubAPI;const row=api.getSnapshot().settings.find((s)=>s.setting?.kind==='baboom'&&s.setting.key==='shows_as');if(!row)throw Error('Native preference owner absent');const old=row.value;const next=old==='Screen'?'Tray':'Screen';await api.setSetting(row.id,next);const saved=api.getSnapshot().settings.find((s)=>s.id===row.id)?.value;await api.setSetting(row.id,old);return {next,saved};});assert(result.next===result.saved,'Native preference readback differs');
 });
 await check('Object-position node drag persists in real backend',async()=>{const result=await page.evaluate(async()=>{const api=window.ArchHubAPI,n=api.getSnapshot().graph.nodes[0];const before={x:n.x,y:n.y};await api.moveNode(n.id,{x:n.x+20,y:n.y+15});const after=api.getSnapshot().graph.nodes.find((x)=>x.id===n.id);await api.moveNode(n.id,before);return after.x===before.x+20&&after.y===before.y+15;});assert(result,'Moved coordinates not re-read');});
 let fixtureTask;
 await check('Composer creates a real Work and re-reads it',async()=>{const beforeIds=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().tasks.map((t)=>t.id));await go('Home');await page.getByRole('textbox',{name:'Message',exact:true}).first().fill('DESIGNWIRE isolated verification');await page.getByRole('textbox',{name:'Message',exact:true}).first().press('Enter');await page.waitForFunction((ids)=>window.ArchHubAPI.getSnapshot().tasks.some((t)=>!ids.includes(t.id)),beforeIds);fixtureTask=await page.evaluate((ids)=>window.ArchHubAPI.getSnapshot().tasks.find((t)=>!ids.includes(t.id)),beforeIds);assert(fixtureTask.status!=='DONE','Invented completion');});
 await check('Task queue is stored and discarded by its real owner',async()=>{assert(fixtureTask,'No fixture Work');await page.evaluate(async (id)=>{const api=window.ArchHubAPI;const item=await api.queueTaskMessage(id,'Fixture queued context');await api.settleQueuedMessage(id,item.id,false);},fixtureTask.id);const rows=await page.evaluate(()=>window.ArchHubAPI.listTasks());assert(rows.find((t)=>t.id===fixtureTask.id).queuedMessages.length===0,'Queue discard not persisted');});
 await check('External Workshop changes appear without a local mutation',async()=>{assert(fixtureTask,'No fixture Work');const added=await page.evaluate(async (id)=>{const c=await fetch('/api/universal/canvas',{headers:{'X-ArchHub-Session':window.__archhubSession.token,'X-ArchHub-CSRF':window.__archhubSession.csrf}}).then((r)=>r.json());const ws=c.workshop_scope.workshops.find((w)=>w.is_general)||c.workshop_scope.workshops[0];const response=await fetch('/api/universal/workshop',{method:'POST',headers:{'Content-Type':'application/json','X-ArchHub-Session':window.__archhubSession.token,'X-ArchHub-CSRF':window.__archhubSession.csrf},body:JSON.stringify({action:'data-api',function:'queueTaskMessage',args:[id,'External fixture change'],root:ws.root,scope:c.scope.current,request_id:window.crypto.randomUUID()})});const result=await response.json();if(!response.ok||result.ok===false)throw Error(result.error||'External write refused');return result.result;},fixtureTask.id);await page.waitForFunction(({task,id})=>window.ArchHubAPI.getSnapshot().tasks.find((t)=>t.id===task)?.queuedMessages.some((m)=>m.id===id),{task:fixtureTask.id,id:added.id},{timeout:timeoutMs});await page.evaluate(({task,id})=>window.ArchHubAPI.settleQueuedMessage(task,id,false),{task:fixtureTask.id,id:added.id});});
 await check('Review finding resolves through the real owner',async()=>{assert(fixtureTask,'No fixture Work');const done=await page.evaluate(async (id)=>{const api=window.ArchHubAPI;await api.addTaskReview(id,'output','Fixture review');await api.resolveTaskReview(id,0,true);return (await api.listTasks()).find((t)=>t.id===id).reviews[0].resolved;},fixtureTask.id);assert(done===true,'Review not resolved');});
 await check('Real task owner',async()=>{const r=await page.evaluate(()=>window.ArchHubAPI.listTasks());assert(Array.isArray(r),'No backend task array');});
 await check('No duplicate browser sprite',async()=>assert(await page.locator('[data-baboom-sprite]').count()===0,'Second desktop sprite'));
 await check('Desktop state is returned by the native companion owner',async()=>{const r=await page.evaluate(()=>window.ArchHubAPI.getDesktopCompanion());assert(r&&typeof r==='object','Missing native companion result');});
 report.snapshot=await page.evaluate(()=>{const s=window.ArchHubAPI.getSnapshot();return {nodes:s.graph.nodes.length,catalogue:s.catalogue.length,tasks:s.tasks.length,settings:s.settings.length,apiFunctions:Object.keys(window.ArchHubAPI).filter((k)=>typeof window.ArchHubAPI[k]==='function').length};});
})().catch((failure)=>{report.fatal=failure.stack;console.log(failure.stack);}).finally(async()=>{fs.writeFileSync(path.join(out,'built-report.json'),JSON.stringify(report,null,2));await browser.close();});
await execution;
console.log(JSON.stringify({checks:report.checks.length,failures:report.checks.filter((c)=>c.status!=='PASS').length,consoleErrors:report.consoleErrors.length,pageErrors:report.pageErrors.length,fatal:report.fatal||null}));
process.exitCode=report.fatal||report.checks.some((c)=>c.status==='FAIL')||report.consoleErrors.length||report.pageErrors.length?1:0;
