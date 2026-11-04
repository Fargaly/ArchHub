import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const browser = await chromium.launch({executablePath: process.env.ARCHHUB_BROWSER_EXECUTABLE, headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 960}});
  await page.goto(input.url);
  await page.waitForFunction(() => window.ArchHubAPI?.ready);
  await page.evaluate(() => window.ArchHubAPI.ready);
  const exported = await page.evaluate(() => window.ArchHubAPI.exportData('Recipe'));
  assert.equal(exported.name, 'Facade study.archhub');
  assert.equal(JSON.parse(exported.content).format, 'archhub');
  assert.equal(JSON.parse(exported.content).title, 'Facade study');
  await page.getByRole('button', {name: 'Canvas view', exact: true}).click();
  const library = page.getByRole('toolbar', {name: 'Canvas commands'}).getByRole('button', {name: 'Library', exact: true});
  if (await library.getAttribute('aria-pressed') !== 'true') await library.click();
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
