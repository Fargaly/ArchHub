import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
// Same installed-cache discovery as the existing rail doors court; pytest isolates LOCALAPPDATA.
const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
const executablePath = process.env.ARCHHUB_BROWSER_EXECUTABLE || (process.platform === 'win32' && shell ? path.join(cache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe') : undefined);
const {chromium} = await import('playwright');
const browser = await chromium.launch({executablePath, headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 960}});
  await page.goto(input.url);
  await page.waitForFunction(() => window.ArchHubAPI?.ready);
  await page.evaluate(() => window.ArchHubAPI.ready);
  const exported = await page.evaluate(() => window.ArchHubAPI.exportData('Recipe'));
  assert.equal(exported.name, 'Facade study.archhub');
  assert.equal(JSON.parse(exported.content).format, 'archhub');
  assert.equal(JSON.parse(exported.content).title, 'Facade study');
  await page.getByRole('button', {name: 'Library', exact: true}).click();
  const shelf = page.getByRole('complementary', {name: 'Library shelf'});
  await shelf.getByRole('button', {name: 'Sessions', exact: true}).click();
  assert.equal(await shelf.getByRole('button', {name: 'Skills', exact: true}).count(), 0);
  assert.equal(await shelf.getByRole('button', {name: 'Workflows', exact: true}).count(), 0);
  await shelf.getByRole('button', {name: 'Facade study', exact: true}).click();
  await page.waitForFunction(expected => window.ArchHubAPI.getSessionPath() === expected, input.path);
  assert.equal(await page.evaluate(() => window.ArchHubAPI.getSessionDocument().title), 'Facade study');
  const started = await page.evaluate(() => window.ArchHubAPI.startTemplate('skill:' + window.ArchHubAPI.getSessionDocument().id));
  assert.equal(started.ok, true);
  assert.equal(await page.evaluate(() => window.ArchHubAPI.getSessionPath()), input.path);
  const saved = await page.evaluate(async () => {
    const saving = window.ArchHubAPI.saveSessionAs();
    await new Promise(resolve => setTimeout(resolve, 200));
    window.ArchHubAPI.setSessionViewport({x: 5, y: 7, zoom: 1});
    const result = await saving;
    await window.ArchHubAPI.saveSession();
    return result;
  });
  assert.equal(saved.path, input.saveAs);
  assert.equal(await page.evaluate(() => window.ArchHubAPI.getSessionDocument().title), 'Shared study');
  assert.equal(await page.evaluate(() => window.ArchHubAPI.getGraph().name), 'Shared study');
  console.log('APPTIDY rendered Library open, Run, Save As and .archhub export PASS');
} finally {
  await browser.close();
}
