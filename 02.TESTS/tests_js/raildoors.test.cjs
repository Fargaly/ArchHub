// Replay the real rail, Home task faces and Automations without a live owner.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
process.stdout.write(execFileSync(process.execPath, ['--max-old-space-size=512', path.resolve(__dirname, '../../03.TOOLS/packaging/compile_studio.cjs')], {windowsHide: true}));
const compiled = name => fs.readFileSync(path.join(studio, 'compiled', name.replace(/\//g, '-').replace(/\.jsx$/, '.js')), 'utf8');
const sources = ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'ds_home2.jsx', 'surfaces.jsx', 'app.jsx'].map(compiled);

test('RAILDOORS: rendered doors, geometry, task faces, fallback and automation clicks', async () => {
  // Pytest isolates LOCALAPPDATA; browser binaries remain in the OS account's cache.
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (process.platform === 'win32' && shell ? path.join(cache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe') : undefined);
  const browser = await chromium.launch({headless: true, executablePath});
  try {
    for (const mode of ['selected', 'clicked', 'last', 'first', 'empty', 'refused', 'cancelled', 'repeat']) {
      const page = await browser.newPage({viewport: {width: 1440, height: 900}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
      await page.goto('http://raildoors.test');
      await page.addStyleTag({path: path.join(studio, 'style.css')});
      await page.addStyleTag({content: 'html,body,#root{height:100%;margin:0}'});
      for (const name of ['react.js', 'react-dom.js']) await page.addScriptTag({path: path.join(studio, 'vendor', name)});
      await page.evaluate(() => { window.fetch = () => new Promise(() => {}); });
      await page.addScriptTag({path: path.join(studio, 'compiled/api.js')});
      await page.evaluate(mode => {
        window.fixture = window.structuredClone(window.ArchHubAPI.getSnapshot());
        const s = window.fixture;
        s.tasks = mode === 'empty' ? [] : [
          {id: 'recent', title: 'Recent task', status: 'WIP', sessionPath: 'recent.archhub', messages: []},
          {id: 'selected', title: 'Selected task', status: 'WIP', sessionPath: 'selected.archhub', sessionOpen: mode === 'last', messages: []}
        ];
        s.focusedTask = ['selected', 'refused', 'cancelled'].includes(mode) ? 'selected' : '';
        if (mode === 'repeat') {
          s.tasks.forEach(t => { t.title = 'Same task'; });
          s.templates = s.tasks.map(t => ({...t, chain: []}));
        }
        s.schedules = [{id: 'trigger', title: 'Repeat recent task', path: 'recent.archhub', enabled: true, time: '09:00'}];
        window.openedTasks = [];
        window.scheduledTasks = [];
        window.ArchHubAPI = {...window.ArchHubAPI, getSnapshot: () => s, subscribe: () => () => {},
          executeAction: (id, callback) => { if (id === 'ui.select') return callback(); throw Error('Unexpected action: ' + id); },
          setActiveSurface: () => {}, supportsAction: () => true,
          refreshAgentSurface: async () => null,
          addSchedule: async (id, time) => { window.scheduledTasks.push({id, time}); return {ok: true}; },
          openTaskGraph: async id => { window.openedTasks.push(id); if (mode === 'refused') throw Error('Fixture task open refused'); return mode === 'cancelled' ? {cancelled: true} : {ok: true}; }};
      }, mode);
      for (let i = 0; i < sources.length - 1; i++) await page.addScriptTag({content: sources[i]});
      await page.evaluate(() => {
        const blank = () => null;
        Object.assign(window.UI, {BaboomSprite: blank, ScheduleResponsibility: blank,
          Canvas: () => React.createElement('div', {'data-fixture-canvas': true}, 'Task canvas'),
          Docs: () => {
            const u = window.UI.useApp();
            return React.createElement('div', null, ...window.fixture.tasks.map(t =>
              React.createElement('button', {key: t.id, onClick: () => u.show('Skill', {id: t.id})}, 'Repeat ' + t.id)));
          }, Settings: blank});
      });
      await page.addScriptTag({content: sources.at(-1)});
      const nav = page.getByRole('navigation', {name: 'Main navigation'});
      await nav.waitFor();
      const labels = ['Home', 'Workshop', 'Canvas', 'Automations', 'Docs', 'Settings'];
      assert.deepEqual(await nav.getByRole('button').evaluateAll(buttons => buttons.slice(0, 6).map(b => b.getAttribute('aria-label'))), labels);
      assert.equal(await page.locator('[data-home-face]').count(), 0, 'Home starts with the task list');
      assert.deepEqual(await page.evaluate(() => window.openedTasks), []);
      if (mode === 'repeat') {
        await nav.getByRole('button', {name: 'Docs', exact: true}).click();
        for (const id of ['recent', 'selected']) {
          await page.getByRole('button', {name: 'Repeat ' + id, exact: true}).click();
          await page.getByRole('dialog', {name: 'Skill', exact: true}).waitFor();
          await page.getByRole('button', {name: 'Run every day', exact: true}).click();
          await page.getByRole('textbox', {name: 'Schedule time', exact: true}).fill('09:17');
          await page.getByRole('button', {name: 'Add schedule', exact: true}).click();
          await page.getByRole('dialog').waitFor({state: 'hidden'});
        }
        assert.deepEqual(await page.evaluate(() => window.scheduledTasks),
          ['recent', 'selected'].map(id => ({id, time: '09:17'})));
        assert.deepEqual(errors, []);
        console.log('PASS repeat: same-named tasks keep distinct IDs through the recurrence modal');
        await page.close();
        continue;
      }
      if (mode === 'clicked') {
        await page.locator('.dx-task').filter({hasText: 'Selected task'}).dblclick();
        await page.locator('.dx-main[data-home-face="workshop"]').waitFor();
      }
      const boxes = [];
      for (const label of labels) boxes.push(await nav.getByRole('button', {name: label, exact: true}).boundingBox());
      boxes.forEach((box, index) => { assert.ok(box && box.height > 0); if (index) assert.ok(box.y >= boxes[index - 1].y + boxes[index - 1].height, labelAt(index)); });
      for (const face of ['Workshop', 'Canvas']) {
        await nav.getByRole('button', {name: face, exact: true}).click();
        if (['empty', 'first', 'last'].includes(mode)) {
          await page.getByRole('alert').filter({hasText: 'Pick a task on Home.'}).waitFor();
          assert.deepEqual(await page.evaluate(() => window.openedTasks), []);
          assert.equal(await nav.getByRole('button', {name: 'Home', exact: true}).getAttribute('aria-current'), 'page');
        } else if (mode === 'cancelled') {
          assert.equal(await page.getByRole('textbox', {name: 'Task title', exact: true}).count(), 0);
          assert.equal(await nav.getByRole('button', {name: 'Home', exact: true}).getAttribute('aria-current'), 'page');
        } else if (mode === 'refused') {
          await page.getByRole('alert').filter({hasText: 'Fixture task open refused'}).waitFor();
          assert.equal(await page.locator('[data-home-face="canvas"]').count(), 0);
        } else {
          await page.locator('.dx-main[data-home-face="' + face.toLowerCase() + '"]').waitFor();
          assert.equal(await page.getByRole('textbox', {name: 'Task title', exact: true}).inputValue(), mode === 'first' ? 'Recent task' : 'Selected task');
          assert.equal(await page.evaluate(() => window.openedTasks.at(-1)), mode === 'first' ? 'recent' : 'selected');
          assert.equal(await nav.getByRole('button', {name: face, exact: true}).getAttribute('aria-current'), 'page');
        }
      }
      if (mode === 'selected') {
        await page.getByRole('button', {name: 'Workshop view', exact: true}).click();
        await nav.getByRole('button', {name: 'Home', exact: true}).click();
        await page.locator('.dx-task').filter({hasText: 'Recent task'}).dblclick();
        await page.locator('.dx-main[data-home-face="workshop"]').waitFor();
        await nav.getByRole('button', {name: 'Canvas', exact: true}).click();
        await page.locator('.dx-main[data-home-face="canvas"]').waitFor();
        await nav.getByRole('button', {name: 'Home', exact: true}).click();
        await page.locator('.dx-task').filter({hasText: 'Selected task'}).dblclick();
        await page.locator('.dx-main[data-home-face="workshop"]').waitFor();
        await nav.getByRole('button', {name: 'Home', exact: true}).click();
        await page.locator('.dx-task').filter({hasText: 'Recent task'}).dblclick();
        await page.locator('.dx-main[data-home-face="canvas"]').waitFor();
        console.log('PASS per-task faces: new task Workshop; selected Workshop; recent Canvas');
        await nav.getByRole('button', {name: 'Automations', exact: true}).click();
        await page.getByRole('button', {name: 'Repeat recent task', exact: true}).click();
        await page.locator('.dx-main[data-home-face="canvas"]').waitFor();
        assert.equal(await page.getByRole('textbox', {name: 'Task title', exact: true}).inputValue(), 'Recent task');
        assert.equal(await page.evaluate(() => window.openedTasks.at(-1)), 'recent');
      }
      await nav.getByRole('button', {name: 'Home', exact: true}).click();
      await page.locator('.dx-home-preview').waitFor();
      assert.equal(await page.getByRole('textbox', {name: 'Task title', exact: true}).count(), 0);
      assert.deepEqual(errors, []);
      console.log('PASS rendered rail + non-overlap + task face clicks: ' + mode);
      await page.close();
    }
  } finally { await browser.close(); }
});
function labelAt(index) { return 'Rail button ' + index + ' overlaps its predecessor'; }
