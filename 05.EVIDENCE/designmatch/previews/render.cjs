const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{chromium}=require('playwright');
const sizes=[[1920,1032],[1366,768],[1009,940]],designUrl='file:///C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/04.ARCHIVE/archhub-directions-v48/index.html';
(async()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8')),out=path.resolve('05.EVIDENCE/designmatch/previews');
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/fargaly/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1920,height:1032}});await context.addCookies([{name:'archhub_studio',value:input.cookie,url:input.url}]);
  const app=await context.newPage(),design=await context.newPage(),errors=[];app.on('pageerror',e=>errors.push(e.message));
  await design.goto(designUrl);
  const home=async()=>{await app.goto(input.url);await app.waitForFunction(()=>!!window.ArchHubAPI);await app.evaluate(async()=>{await window.ArchHubAPI.ready;await window.ArchHubAPI.listTasks();});await app.locator('.resume-row').first().waitFor();};
  const shots=async name=>{for(const [width,height] of sizes){await app.setViewportSize({width,height});await design.setViewportSize({width,height});await app.waitForTimeout(700);await app.screenshot({path:path.join(out,name+'-app-'+width+'x'+height+'.png')});await design.screenshot({path:path.join(out,name+'-design-'+width+'x'+height+'.png')});}await app.setViewportSize({width:1920,height:1032});};
  await home();
  await app.locator('.dx-task').filter({hasText:'Details library'}).first().click();
  await app.locator('[data-resume-step="demo-0"] .resume-made table').waitFor();
  assert.equal(await app.locator('[data-resume-step][data-made]').count(),4);
  assert.equal(await app.locator('[data-resume-step="demo-1"] .resume-made img').count(),1);
  assert.match(await app.locator('[data-resume-step="demo-2"] .resume-made').innerText(),/DET-03-001\.dwg[\s\S]*84 KB/);
  assert.equal(await app.locator('[data-resume-step="demo-4"] .resume-made').count(),0);
  assert.equal(await app.locator('[data-resume-step="demo-4"]').getByRole('button',{name:/^Approve/}).count(),1);
  const empty=await app.locator('.resume-made').evaluateAll(rows=>rows.filter(row=>!row.innerText.trim()&&!row.querySelector('img')).length);assert.equal(empty,0);
  // A1: the label stays inside the one Send button.
  const send=await app.locator('.global-composer [data-design="composer.send"]').evaluate(el=>({text:el.innerText.trim(),fits:el.scrollWidth<=el.clientWidth,icon:!!el.querySelector('svg')}));assert.deepEqual(send,{text:'Send',fits:true,icon:true});
  // A2: no number over the initials.
  assert.equal(await app.locator('.resume-row .agent-avatar>small').evaluateAll(rows=>rows.filter(row=>row.offsetParent!==null).length),0);
  // A3: a long name wraps to two lines and is not cut.
  const long=await app.locator('.resume-row .dx-task b').filter({hasText:'Check every detail'}).evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);const lines=new Set([...range.getClientRects()].map(rect=>Math.round(rect.top))).size,style=window.getComputedStyle(el);return {lines,shown:Math.round(el.clientHeight/parseFloat(style.lineHeight)),width:el.clientWidth};});assert.equal(long.lines,2,JSON.stringify(long));assert.equal(long.shown,2,JSON.stringify(long));
  await shots('home');
  // C: a planned session shows its steps as nodes; the pill and the Inspector read the same count.
  const openCanvas=async(id,title)=>{await home();await app.evaluate(id=>window.ArchHubAPI.openTaskGraph(id),id);await app.locator('.dx-task').filter({hasText:title}).first().dblclick();await app.locator('[data-design="session.node"]').waitFor();await app.locator('[data-design="session.node"]>.node-header').click();await app.getByRole('tab',{name:'This task',exact:true}).click();};
  await openCanvas(input.planned,'Check every detail');
  await app.locator('[data-graph-node="plan-1"]').waitFor();assert.equal(await app.locator('[data-graph-node="plan-2"]').count(),1);
  const pill=await app.locator('[data-design="canvas.title"] span').innerText(),line=await app.locator('.v48-progress-line').innerText();
  assert.match(pill,/^0 of 2 steps/);assert.match(line,/^0 of 2 steps done, now Read details index/);
  await app.screenshot({path:path.join(out,'canvas-planned-app-1920x1032.png')});
  await openCanvas(input.task,'Details library');
  await app.locator('[data-graph-node="demo-0"] .v48-step-preview table').waitFor();
  const pill2=await app.locator('[data-design="canvas.title"] span').innerText(),line2=await app.locator('.v48-progress-line').innerText();
  assert.equal(pill2.match(/^\d+ of \d+/)[0],line2.match(/^\d+ of \d+/)[0]);
  assert.ok(await app.locator('.v48-made img').count()>=1);
  await design.locator('.app-rail [data-go=canvas]').click();
  await shots('canvas');
  assert.deepEqual(errors,[]);console.log('PASS previews: Home cards 4 made + 1 held; Send fits; no avatar number; two-line name; planned canvas "'+pill+'" = Inspector "'+line+'"; details canvas "'+pill2+'" = "'+line2+'"');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
