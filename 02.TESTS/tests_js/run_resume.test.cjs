'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const requireInstalled = createRequire(path.join(process.env.ARCHHUB_NODE_MODULES, 'playwright', 'package.json'));
const {chromium} = requireInstalled('playwright');

(async () => {
  const config = JSON.parse(fs.readFileSync(0, 'utf8'));
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH;
  const shell = fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name))
    .sort((a,b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = fs.readdirSync(cache).filter(name => /^chromium-\d+$/.test(name))
    .sort((a,b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const browser = await chromium.launch({headless:true,
    executablePath:path.join(cache,shell || full,shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe')});
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => console.error(error));
    page.on('console', message => {if(message.type()==='error')console.error(message.text());});
    await page.route('**/*', route => new URL(route.request().url()).origin === new URL(config.url).origin ? route.continue() : route.abort());
    await page.goto(config.url);
    await page.waitForFunction(() => window.ArchHubAPI);
    await page.evaluate(async file => {await window.ArchHubAPI.ready;await window.ArchHubAPI.openSession(file);}, config.path);
    const paused = await page.evaluate(() => window.ArchHubAPI.runNode());
    assert.equal(paused.results.two.status,'Waiting for approval');
    assert.equal((await page.evaluate(() => window.ArchHubAPI.runNode())).approvalId,paused.approvalId);
    await page.evaluate(id => window.ArchHubAPI.approve(id),paused.approvalId);
    assert.equal((await page.evaluate(() => window.ArchHubAPI.runNode())).results.three.output.result,1);
    await page.reload();
    await page.waitForFunction(() => window.ArchHubAPI);
    await page.evaluate(() => window.ArchHubAPI.ready);
    assert.equal((await page.evaluate(() => window.ArchHubAPI.runNode())).results.three.output.result,1);
    await page.evaluate(() => window.ArchHubAPI.setNodeParam('three','task','browser tail'));
    assert.equal((await page.evaluate(() => window.ArchHubAPI.runNode())).results.three.output.result,2);
    const fresh = await page.evaluate(() => window.ArchHubAPI.runNode(undefined,true));
    assert.equal(fresh.results.one.output.result,2);
    assert.equal(fresh.results.two.status,'Waiting for approval');
    await page.evaluate(id => window.ArchHubAPI.approve(id),fresh.approvalId);
    assert.equal((await page.evaluate(() => window.ArchHubAPI.runNode())).results.three.output.result,3);
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Canvas',exact:true}).click();
    await page.evaluate(file=>window.ArchHubAPI.openSession(file),config.recovery_path);
    const uncertain=page.locator('.react-flow__node[data-id="uncertain"]');
    await uncertain.click();
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='uncertain').status),'Unconfirmed');
    await page.getByRole('button',{name:'More canvas actions',exact:true}).click();
    await page.getByRole('menuitem',{name:'Run this step again',exact:true}).waitFor();
    await page.getByRole('menuitem',{name:'Check result',exact:true}).click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='uncertain')?.status==='Done');
    console.log('RUNRESUME browser: pause, same approval, resume, reload, cached Run, selective rerun, Run all again PASS');
    console.log('RUNRESUME browser: Unconfirmed state, explicit recovery menu, real file Check result PASS');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error);process.exitCode=1;});
