// Court: five consecutive Settings > This PC changes on one Studio, each answered by the Settings owner and applied.
// Real Studio page, real owner server (isolated profile, admitted fixture account), real clicks.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../..');
const python = process.env.ARCHHUB_TEST_PYTHON || process.env.PYTHON || path.join(process.env.LOCALAPPDATA, 'Python/bin/python.exe');

test('SETTINGS five consecutive This PC changes are each answered and applied', {timeout: 240000}, async t => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'five-changes-'));
  const env = {...process.env, USERPROFILE: profile, HOME: profile, LOCALAPPDATA: path.join(profile, 'local'),
    APPDATA: path.join(profile, 'roaming'), ARCHHUB_TEST_STATE_DIR: path.join(profile, 'state'),
    ARCHHUB_TEST_SECRET_STORE: 'memory', PYTHONDONTWRITEBYTECODE: '1', ARCHHUB_DISABLE_WORKSHOP_WATCH: '1',
    PYTHONPATH: path.join(root, '01.APP')};
  const server = spawn(python, ['-u', '-c', `
import json, os, sys
from pathlib import Path
from nodelang.nograph_server import NoGraphServer
from nodelang.cloud_session import _ResumeSigner
signer = _ResumeSigner(b'isolated-test-key', 'isolated', 'five-fixture', 'isolated')
class Admitted:
    def check(self, *, expected_bearer=None, bind_resume=False):
        return {'ok': True, 'admitted': True, 'state': 'admitted', 'subject': 'five-fixture', 'email': None, '_sign_resume_pointer': signer}
s = NoGraphServer(Path(os.environ['ARCHHUB_TEST_STATE_DIR']), desktop_access=Admitted())
print(json.dumps({'url': s.public_url + '/studio?bootstrap=' + s.browser_bootstrap_token}), flush=True)
s.httpd.serve_forever()
`], {env, stdio: ['ignore', 'pipe', 'pipe']});
  let browser, stderr = '';
  server.stderr.on('data', chunk => { stderr += chunk; });
  t.after(async () => {
    if (browser) await browser.close();
    if (server.exitCode === null) { server.kill(); await Promise.race([once(server, 'exit'), new Promise(r => setTimeout(r, 3000))]); }
    fs.rmSync(profile, {recursive: true, force: true});
  });
  const url = await new Promise((resolve, reject) => {
    let raw = '';
    server.stdout.on('data', chunk => { raw += chunk; const end = raw.indexOf('\n'); if (end >= 0) resolve(JSON.parse(raw.slice(0, end)).url); });
    server.once('exit', code => reject(Error('owner startup ' + code + ': ' + stderr)));
  });
  browser = await chromium.launch({headless: true, executablePath: process.env.ARCHHUB_TEST_CHROMIUM});
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.setDefaultTimeout(30000);
  await page.route('**/api/**', route => (route.request().postData() || '').includes('"function":"checkDependencies"')
    ? route.fulfill({json: {ok: true, result: {dependencies: []}}}) : route.fallback());  // a blank profile's probe
  await page.route('**/api/universal/desktop-access', route => route.fulfill({json: {ok: true, admitted: true, state: 'admitted', subject: 'five-fixture', email: 'five@example.test'}}));
  await page.goto(url);
  await page.waitForSelector('.app-window', {timeout: 60000});
  await page.evaluate(() => window.ArchHubAPI.ready);
  await page.getByRole('button', {name: /^Settings$/}).first().click();
  await page.getByText('This PC', {exact: true}).first().click();
  await page.waitForSelector('[data-design-section="Theme and colour"]');
  const changes = [['themeSet', 'Vellum', 'Appearance.Theme set'], ['density', 'Compact', 'Appearance.Density'],
    ['themeSet', 'Forge', 'Appearance.Theme set'], ['density', 'Comfortable', 'Appearance.Density'], ['wireVis', 'On hover', 'Appearance.Wires']];
  for (const [row, option, id] of changes) {
    const control = page.locator(`[data-row="${row}"]`);
    await control.scrollIntoViewIfNeeded();
    await control.getByText(option, {exact: true}).click();
    await page.waitForFunction(([id, option]) => (window.ArchHubAPI.getSnapshot().settings || []).find(r => r.id === id)?.value === option, [id, option]);
  }
  const saved = JSON.parse(fs.readFileSync(path.join(profile, 'state', 'settings', 'settings.json'), 'utf8'));
  assert.deepEqual([saved.appearanceThemeSet, saved.appearanceDensity, saved.appearanceWires], ['Forge', 'Comfortable', 'On hover']);
  assert.equal(await page.evaluate(() => document.body.classList.contains('compact')), false);
  assert.deepEqual(errors, []);
});
