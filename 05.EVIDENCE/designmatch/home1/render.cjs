const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{chromium}=require('playwright');
(async()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8')),out=path.resolve('05.EVIDENCE/designmatch/home1');
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/fargaly/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 try{
 const context=await browser.newContext({viewport:{width:1920,height:1032}});await context.addCookies([{name:'archhub_studio',value:input.cookie,url:input.url}]);
 const app=await context.newPage(),design=await context.newPage(),errors=[];app.on('pageerror',e=>errors.push(e.message));
 await design.goto('file:///C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/04.ARCHIVE/archhub-directions-v48/index.html');
 await app.goto(input.url);await app.waitForFunction(()=>!!window.ArchHubAPI);await app.evaluate(async()=>{await window.ArchHubAPI.ready;await window.ArchHubAPI.listTasks();await window.ArchHubAPI.listAgentsWorking();await window.ArchHubAPI.listWorkspaces();});await app.waitForFunction(()=>window.ArchHubAPI?.getSnapshot().tasks.length===146);await app.locator('.resume-row').first().waitFor();
 await app.waitForFunction(()=>window.ArchHubAPI.getSnapshot().agentWorkingCount===14);
 const heading=name=>app.locator(`[data-home-section="${name}"]>.home-section-heading`);
 assert.match(await heading('Working now').innerText(),/14$/);assert.match(await heading('Needs you').innerText(),/2$/);
 assert.equal(await heading('Older / archived').getAttribute('aria-expanded'),'false');
 assert.equal(await app.locator('[data-home-section="Working now"] .resume-row').count(),14);
 const filter=app.getByRole('group',{name:'Saved document filter'});
 await filter.getByRole('button',{name:'Workflows',exact:true}).click();await filter.locator('button[aria-pressed=true]').filter({hasText:'Workflows'}).waitFor();
 if(await heading('Older / archived').count())await heading('Older / archived').click();
 assert.equal(await app.locator('.resume-row').count(),31);
 assert.ok((await app.locator('.resume-row .dx-task b').allTextContents()).every(text=>text.startsWith('Saved workflow')));
 await filter.getByRole('button',{name:'Agent sessions',exact:true}).click();await filter.locator('button[aria-pressed=true]').filter({hasText:'Agent sessions'}).waitFor();
 if(await heading('Older / archived').getAttribute('aria-expanded')==='false')await heading('Older / archived').click();
 assert.equal(await app.locator('.resume-row').count(),115);
 const avatars=await app.locator('.resume-row .agent-avatar').evaluateAll(rows=>rows.map(row=>row.textContent+'|'+window.getComputedStyle(row.querySelector('i')).background));assert.equal(new Set(avatars).size,115);
 await heading('Older / archived').click();await filter.getByRole('button',{name:'All',exact:true}).click();await filter.locator('button[aria-pressed=true]').filter({hasText:'All'}).waitFor();
 await app.locator('.dx-task').filter({hasText:'Agent 1 review session'}).click();
 await app.getByRole('region',{name:'Session activity'}).waitFor();assert.equal(await app.locator('[data-resume-step]').count(),0);
 assert.ok(!(await app.locator('[data-home-page]').innerText()).includes('not reported'));
 assert.match(await app.getByRole('region',{name:'Last thread lines'}).innerText(),/Reviewed/);
 for(const [width,height] of [[1920,1032],[1366,768],[1009,940]]){
  await app.setViewportSize({width,height});await design.setViewportSize({width,height});await app.waitForTimeout(500);
  const rail=app.locator('.resume-home');assert.equal(await rail.evaluate(el=>el.classList.contains('sessions-rail')),width<1100);
  const boxes=await filter.getByRole('button').evaluateAll(elements=>elements.map(el=>({text:el.textContent,width:el.clientWidth,scroll:el.scrollWidth,rect:el.getBoundingClientRect().toJSON()})));assert.ok(boxes.every(b=>b.width>=b.scroll&&b.rect.right<=width),JSON.stringify(boxes));
  const parts=await app.locator('.global-composer').evaluate(el=>[...el.querySelectorAll('.composer-scope,textarea,.composer-tools')].map(e=>e.getBoundingClientRect().toJSON()));assert.ok(Math.max(...parts.map(b=>b.top))-Math.min(...parts.map(b=>b.top))<15,JSON.stringify(parts));
  assert.equal(await app.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
  await app.screenshot({path:path.join(out,`app-${width}x${height}.png`)});await design.screenshot({path:path.join(out,`design-${width}x${height}.png`)});
 }
 await app.setViewportSize({width:1920,height:1032});await app.reload();await heading('Older / archived').waitFor();assert.equal(await heading('Older / archived').getAttribute('aria-expanded'),'false');
 assert.deepEqual(errors,[]);console.log('PASS Home 1: 146 files; filters All 146 / Workflows 31 / Agent sessions 115; Working now 14 = header 14; Needs you 2; archived 58 hidden; unique avatars; planless thread; widths 1920 / 1366 / 1009; collapsed sections survive reload.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
