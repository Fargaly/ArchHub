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
    await page.addInitScript(() => {
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
    await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().homeLayout?.inner?.params === 30);
    assert.equal(await page.evaluate(() => localStorage.getItem('archhub.home.layout.v1')),null);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => [...document.fonts].some(face => face.family === 'Inter' && face.status === 'loaded')),true);
    assert.equal(await page.evaluate(() => window.devicePixelRatio),1);
    const out = path.resolve('05.EVIDENCE/designbuild',input.board);
    fs.mkdirSync(out,{recursive:true});
    const reference = 'C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/35.02-APP-DESIGN/01.WIP/penpot-home-r1964-native.png';
    fs.copyFileSync(reference,path.join(out,'penpot-r1964.png'));
    await page.screenshot({path:path.join(out,'studio.png')});
    const pair = await context.newPage();
    await pair.setViewportSize({width:2732,height:768});
    await pair.setContent('<body style="margin:0;display:flex">'+['penpot-r1964.png','studio.png'].map(name => '<img width="1366" height="768" src="data:image/png;base64,'+fs.readFileSync(path.join(out,name)).toString('base64')+'">').join(''));
    await pair.screenshot({path:path.join(out,'comparison.png')});
    await pair.close();
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
    for(const [label,value] of [['Scope','Review the current issue'],['Rules','Review every sheet before export'],['References','Current drawing index']]) {
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
    await preview.getByText('Review the current issue',{exact:true}).waitFor();
    assert.equal(await page.evaluate(() => window.ArchHubAPI.getSnapshot().homeLayout.inner.params),30);
    assert.deepEqual(errors,[]);
    console.log('PASS Home: real owner edits saved, page closed/reopened, geometry and computed plan checked');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
