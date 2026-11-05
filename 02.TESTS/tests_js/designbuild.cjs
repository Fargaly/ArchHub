// Native compiled Studio and the real isolated owners; no UI/API substitutions.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const shell = fs.readdirSync(input.browserCache).filter(n => /^chromium_headless_shell-\d+$/.test(n)).sort((a,b) => Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
  const full=fs.readdirSync(input.browserCache).filter(name=>/^chromium-\d+$/.test(name)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
  const executablePath=path.join(input.browserCache,shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe');
  const browser = await chromium.launch({headless:true, executablePath});
  try {
    const context = await browser.newContext({viewport:{width:1366,height:768}});
    await context.addCookies([{name:'archhub_studio',value:input.cookie,url:input.url}]);
    let page = await context.newPage();
    if(input.board === "home") await page.addInitScript(() => {
      if (!sessionStorage.getItem('designbuild-layout-seeded')) {
        localStorage.setItem('archhub.home.layout.v1',JSON.stringify({inner:{params:30,main:70}}));
        sessionStorage.setItem('designbuild-layout-seeded','1');
      }
    });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(input.url);
    let preview = page.getByRole('complementary',{name:'Selected task properties'});
    await preview.waitFor({timeout:45000});
    await page.getByRole('button',{name:/Drawing set review/}).first().click();
    await preview.getByRole('heading',{name:'Drawing set review'}).waitFor();
    if(input.board === "home") await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().homeLayout?.inner?.params === 30);
    assert.equal(await page.evaluate(() => localStorage.getItem('archhub.home.layout.v1')),null);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => [...document.fonts].some(face => face.family === 'Inter' && face.status === 'loaded')),true);
    assert.equal(await page.evaluate(() => window.devicePixelRatio),1);
    console.log('Fonts '+JSON.stringify(await page.evaluate(() => ({dpr:window.devicePixelRatio,faces:[...document.fonts].map(f=>({family:f.family,status:f.status,weight:f.weight})),title:window.getComputedStyle(document.querySelector('.dx-tasks h2')).font}))));
    const capture = async referenceName => {
    const out = path.resolve('05.EVIDENCE/designbuild',input.board);
    fs.mkdirSync(out,{recursive:true});
    const reference = 'C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/01.WIP/' + referenceName;
    const referenceFile=input.board==='home'?'penpot-r1964.png':'penpot-r1963.png';
    fs.copyFileSync(reference,path.join(out,referenceFile));
    await page.screenshot({path:path.join(out,'studio.png')});
    const pair = await context.newPage();
    await pair.setViewportSize({width:2732,height:768});
    await pair.setContent('<body style="margin:0;display:flex">'+[referenceFile,'studio.png'].map(name => '<img width="1366" height="768" src="data:image/png;base64,'+fs.readFileSync(path.join(out,name)).toString('base64')+'">').join(''));
    await pair.screenshot({path:path.join(out,'comparison.png')});
    await pair.close();
    };
    if(input.board === 'workshop') {
      await preview.getByRole('button',{name:'Open Workshop',exact:true}).click();
      await page.getByRole('heading',{name:'Thread activity',exact:true}).waitFor();
      await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().sessionDirty === false).catch(async error => {throw Error(error.message+' state='+JSON.stringify(await page.evaluate(() => {const s=window.ArchHubAPI.getSnapshot();return {dirty:s.sessionDirty,sync:s.sync,notice:s.connectionNotice,last:s.lastResult};})));});
      assert.match(await page.locator('.dx-session-meta').innerText(), /Saved$/);
      preview=page.getByRole('region',{name:'Task parameters',exact:true});
      await page.getByRole('complementary',{name:'Threads',exact:true}).waitFor();
      const geometry=await page.evaluate(() => {
        const box = selector => {const r=document.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
        return {params:box('#params'),composer:box('.dx-composer'),conversation:box('[data-dx="conversation"]')};
      });
      assert.ok(geometry.params.x > geometry.conversation.x + geometry.conversation.width);
      assert.ok(geometry.composer.height <= 100);
      await capture('penpot-workshop-r1963-native.png');
      console.log('PASS Workshop layout: '+JSON.stringify(geometry));
      const session=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id);
      await page.getByRole('button',{name:'Handoff map',exact:true}).click();
      await page.locator('[data-home-face=canvas]').first().waitFor();
      assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.id),session);
      await page.getByRole('button',{name:'Workshop view',exact:true}).click();
    } else {
      await capture('penpot-home-r1964-native.png');
    const bounds = await page.evaluate(() => {
      const box = selector => {const r=document.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
      return {rail:box('nav[aria-label="Main navigation"]'), list:box('.dx-tasks'),properties:box('.dx-home-preview'),title:box('.dx-tasks h2'),font:window.getComputedStyle(document.querySelector('.dx-tasks')).fontFamily};
    });
    console.log(JSON.stringify(bounds));
    assert.equal(bounds.rail.width,64);
    assert.equal(bounds.properties.x,962);
    assert.equal(bounds.properties.width,380);
    assert.equal(bounds.properties.y,87);
    assert.equal(await preview.getByText('Drawing set review.archhub',{exact:true}).count(),1);
    assert.equal(await page.locator('.dx-task').filter({has:page.locator('b',{hasText:'Drawing set review'})}).locator('span').first().innerText(),'Drawing coordinator');
    assert.equal(await page.getByText('Accept edits',{exact:true}).count(),0);
    assert.equal(await preview.getByText('2 of 3 steps complete',{exact:true}).count(),1);
    }
    for(const [label,value] of [['Scope','Review the current issue'],['Rules','Review every sheet before export'],['References','Current drawing index'],['Folders','Dated issue folder renamed']]) {
      const field=preview.locator('details').filter({has:page.locator('summary>span:first-child').filter({hasText:new RegExp('^'+label+'$')})});
      await field.locator('summary').click();
      await field.getByRole('textbox').fill(value);
      await field.getByRole('textbox').press('Tab');
      await page.waitForFunction(() => !document.querySelector('[role="status"]')?.textContent?.includes('Saving'));
      await field.locator('summary').click();
    }
    await page.close();
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(input.url);
    preview = page.getByRole('complementary',{name:'Selected task properties'});
    await preview.waitFor();
    await page.getByRole('button',{name:/Drawing set review/}).first().click();
    if(input.board==='workshop'){await preview.getByRole('button',{name:'Open Workshop',exact:true}).click();preview=page.getByRole('region',{name:'Task parameters',exact:true});}
    await preview.getByText('Review the current issue',{exact:true}).waitFor();
    if(input.board === 'home') assert.equal(await page.evaluate(() => window.ArchHubAPI.getSnapshot().homeLayout.inner.params),30);
    assert.deepEqual(errors,[]);
    console.log('PASS '+input.board+': real owner edits saved, page closed/reopened, geometry and computed plan checked');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
