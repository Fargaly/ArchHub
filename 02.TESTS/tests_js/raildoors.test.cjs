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
const sources = ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx', 'ds_home2.jsx', 'ds_library.jsx', 'ds_workshop3.jsx', 'surfaces.jsx', 'app.jsx'].map(compiled);

test('RAILDOORS: rendered doors, geometry, task faces, fallback and automation clicks', async () => {
  // Pytest isolates LOCALAPPDATA; browser binaries remain in the OS account's cache.
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full=fs.readdirSync(cache).filter(name=>/^chromium-\d+$/.test(name)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (process.platform === 'win32' && (shell || full) ? path.join(cache, shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe') : undefined);
  const browser = await chromium.launch({headless: true, executablePath});
  try {
    for (const mode of ['selected', 'clicked', 'last', 'first', 'empty', 'refused', 'cancelled', 'repeat', 'uxflow']) {
      const page = await browser.newPage({viewport: {width: 1440, height: 900}});
      const errors = [];
      let inspectorWidth = 320;
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
      await page.goto('http://raildoors.test');
      const mount = async () => {
        await page.addStyleTag({path: path.join(studio, 'style.css')});
        await page.addStyleTag({content: 'html,body,#root{height:100%;margin:0}'});
        for (const name of ['react.js', 'react-dom.js']) await page.addScriptTag({path: path.join(studio, 'vendor', name)});
        await page.addScriptTag({content: require('./studio_xyflow.cjs').script()});
        await page.addScriptTag({path: path.join(studio, 'compiled/react-resizable-panels.js')});
        await page.evaluate(() => { window.fetch = () => new Promise(() => {}); });
        await page.addScriptTag({path: path.join(studio, 'compiled/api.js')});
        await page.evaluate(({mode, inspectorWidth}) => {
          window.fixture = window.structuredClone(window.ArchHubAPI.getSnapshot());
          const s = window.fixture;
          s.settings.push({id:'Appearance.Inspector width',value:inspectorWidth,overridden:true});
          s.tasks = mode === 'empty' ? [] : [
            {id: 'recent', title: 'Recent task', status: 'WIP', sessionPath: 'recent.archhub', messages: []},
            {id: 'selected', title: 'Selected task', status: 'WIP', sessionPath: 'selected.archhub', sessionOpen: mode === 'last', messages: []}
          ];
          s.focusedTask = ['selected', 'refused', 'cancelled', 'uxflow'].includes(mode) ? 'selected' : '';
          if (mode === 'repeat') {
            s.tasks.forEach(t => { t.title = 'Same task'; });
            s.templates = s.tasks.map(t => ({...t, chain: []}));
          }
          if (mode === 'uxflow') {
            s.liveAgents = [{agent:'codex-reviewer',handle:'design-reviewer',name:'Design reviewer',gate:'missing',breaches:2}];
            s.tasks[1].messages = [{id: 'long', who: 'Fixture agent', text: 'x'.repeat(900)}];
            s.tasks.push(...['interrupted', 'limit reached', 'LIMIT_REACHED', 'blocked'].map((rowState, i) => ({
              id: 'state-' + i, title: 'State ' + rowState, status: 'PLANNED', rowState,
              reason: 'Planned, not started', summary: 'Planned, not started', blockedBy: 'Unsupported dependency', messages: []
            })));
          }
          s.tasks.forEach(task => { task.updated_at = new Date().toISOString(); });
          s.schedules = [{id: 'trigger', title: 'Repeat recent task', path: 'recent.archhub', enabled: true, time: '09:00'}];
          window.openedTasks = [];
          window.scheduledTasks = [];
          window.ArchHubAPI = {...window.ArchHubAPI, getSnapshot: () => s, subscribe: () => () => {},
            executeAction: (id, callback) => { if (id === 'ui.select') return callback(); throw Error('Unexpected action: ' + id); },
            setActiveSurface: () => {}, supportsAction: () => true,
            readCanvasTabs: async () => ({canvasTabs:{tabs:[],active:'',split:'',collapsed:false}}),
            setCanvasTabs: async () => ({ok:true}),
            readSessionListFilters: async () => ({sessionListFilters:{home:'all',library:'all'}}),
            setSessionListFilter: async () => ({ok:true}),
            readHomeLayout: async () => ({homeLayout:{width:300,collapsed:false,resume:'',order:[],hidden:[]}}),
            setHomeLayout: async () => ({ok:true}),
            setInspectorWidth: async value => { s.settings.find(row=>row.id==='Appearance.Inspector width').value=value; return {ok:true}; },
            refreshAgentSurface: async () => null, apiRouterChat: async () => window.holdSend ? new Promise(resolve => { window.finishSend = resolve; }) : null,
            addSchedule: async (id, time) => { window.scheduledTasks.push({id, time}); return {ok: true}; },
            openTaskGraph: async id => { window.openedTasks.push(id); if (mode === 'refused') throw Error('Fixture task open refused'); return mode === 'cancelled' ? {cancelled: true} : {ok: true}; }};
        }, {mode, inspectorWidth});
        for (let i = 0; i < sources.length - 1; i++) await page.addScriptTag({content: sources[i]});
        await page.evaluate(() => {
          const blank = () => null;
          Object.assign(window.UI, {BaboomSprite: blank, ScheduleResponsibility: blank,
            Canvas: () => React.createElement('div', {'data-fixture-canvas': true}, 'Task canvas'),
            GraphProperties: ({g}) => React.createElement('div', {'data-fixture-properties':true}, g.name),
            Docs: () => {
              const u = window.UI.useApp();
              return React.createElement('div', null, ...window.fixture.tasks.map(t =>
                React.createElement('button', {key: t.id, onClick: () => u.show('Skill', {id: t.id})}, 'Repeat ' + t.id)));
            }, Settings: blank});
        });
        await page.addScriptTag({content: sources.at(-1)});
      };
      await mount();
      const nav = page.getByRole('navigation', {name: 'Main navigation'});
      await nav.waitFor();
      const filter = page.getByRole('group', {name:'Saved document filter',exact:true});
      await filter.waitFor();
      assert.deepEqual(await filter.getByRole('button').allTextContents(), ['All', 'Workflows', 'Agent sessions']);
      assert.equal(await filter.getByRole('button', {name:'All',exact:true}).getAttribute('aria-pressed'), 'true');
      const labels = ['Home', 'Canvas', 'Docs', 'Settings', 'Your account'];
      assert.deepEqual(await nav.getByRole('button').evaluateAll(buttons => buttons.map(b => b.getAttribute('aria-label'))), labels);
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
      if (mode === 'uxflow') {
        // Interrupted rows sit under the collapsed Older heading and appear when it is expanded.
        const older = page.locator('.home-section-heading').filter({hasText: 'Older'});
        assert.equal(await older.getAttribute('aria-expanded'), 'false');
        assert.equal(await page.locator('.dx-task').filter({has: page.locator('b', {hasText: 'State interrupted'})}).count(), 0);
        await older.click();
        assert.equal(await older.getAttribute('aria-expanded'), 'true');
        for (const [state, label] of [['interrupted', 'interrupted'], ['limit reached', 'limit reached'], ['LIMIT_REACHED', 'limit reached']]) {
          const row = page.locator('.dx-task').filter({has: page.locator('b', {hasText: 'State ' + state})});
          assert.match(await row.innerText(), new RegExp(label));
          assert.equal(await row.getAttribute('aria-selected'), 'false');
        }
        assert.equal(await page.locator('[data-task-row-state^="blocked"]').count(), 0);
        // The same owner renders Workshop task rows; unsupported dependency data stays hidden.
        await page.evaluate(() => {
          const node = document.createElement('div'); node.id = 'workshop-row-court'; document.body.append(node);
          window.ReactDOM.createRoot(node).render(React.createElement(window.UI.Ctx.Provider, {value: {}},
            ...window.fixture.tasks.filter(t => t.rowState).map(task => React.createElement(window.UI.Task, {key: task.id, task, select: () => {}}))));
        });
        await page.locator('#workshop-row-court [data-task-row-state="interrupted"]').waitFor();
        assert.equal(await page.locator('#workshop-row-court [data-task-row-state="limit reached"]').count(), 2);
        assert.equal(await page.locator('#workshop-row-court').getByText(/blocked by/).count(), 0);
        await page.locator('#workshop-row-court').evaluate(node => node.remove());
        console.log('PASS task reasons: Home + Workshop interrupted / limit reached; generic status retained; blocked-by hidden');
        const open = async title => {
          await nav.getByRole('button', {name: 'Home', exact: true}).click();
          if(page.viewportSize().width<1100) await page.getByRole('button',{name:'Open the list',exact:true}).click();
          await page.locator('.dx-task').filter({hasText: title}).dblclick();
          const thread = page.getByRole('button', {name: 'Thread', exact: true, includeHidden:true});
          if(await thread.getAttribute('aria-pressed') !== 'true') {
            if(await thread.isVisible()) await thread.click();
            else await page.locator('body').press('Control+Backslash');
          }
        };
        await open('Selected task');
        await page.getByRole('button', {name: 'Recipient', exact:true}).click();
        const reviewer=page.getByRole('option', {name: /Design reviewer.*Gate missing.*2 breaches/});
        assert.equal(await reviewer.isEnabled(),true);
        await reviewer.click();
        await page.getByRole('button',{name:'Recipient',exact:true}).click();
        await page.getByRole('option',{name:/BABOOM/}).click();
        assert.match(await page.getByRole('button',{name:'Recipient',exact:true}).innerText(),/BABOOM/);
        await page.setViewportSize({width:1680,height:900});
        await page.getByRole('button',{name:'Open Inspector',exact:true}).click();
        await page.waitForFunction(()=>document.getElementById('params').offsetWidth>=280);
        const separator = page.getByRole('separator', {name: 'Resize the Properties pane'});
        const params = page.locator('#params');
        await page.waitForFunction(()=>document.querySelector('[aria-label="Resize the Properties pane"]').getBoundingClientRect().width>=6);
        await page.waitForFunction(()=>Math.abs(document.getElementById('params').getBoundingClientRect().width-window.fixture.settings.find(row=>row.id==='Appearance.Inspector width').value)<.5);
        await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        const before = await params.boundingBox(), handle = await separator.boundingBox();
        assert.ok(handle.width >= 6);
        assert.equal(await separator.evaluate(el => window.getComputedStyle(el).cursor), 'col-resize');
        // CDP targets only this headless page; it never sends input to the desktop.
        const input = await page.context().newCDPSession(page);
        const point = {x: handle.x + handle.width / 2, y: handle.y + handle.height / 2};
        await input.send('Input.dispatchMouseEvent', {type: 'mouseMoved', ...point});
        await input.send('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', buttons: 1, clickCount: 1});
        await input.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: point.x - 75, y: point.y, button: 'left', buttons: 1});
        await input.send('Input.dispatchMouseEvent', {type: 'mouseReleased', x: point.x - 75, y: point.y, button: 'left', buttons: 0, clickCount: 1});
        await input.detach();
        const after = await params.boundingBox();
        assert.ok(after.width > before.width + 60, JSON.stringify({before, after}));
        await page.waitForFunction(() => window.fixture.settings.find(row=>row.id==='Appearance.Inspector width').value > 320);
        inspectorWidth = await page.evaluate(() => window.fixture.settings.find(row=>row.id==='Appearance.Inspector width').value);
        await page.reload(); await mount(); await open('Selected task');
        await page.getByRole('button',{name:'Open Inspector',exact:true}).click();
        await page.waitForFunction(()=>document.getElementById('params').offsetWidth>=280);
        await page.waitForFunction(width=>Math.abs(document.getElementById('params').getBoundingClientRect().width-width)<1,after.width);
        await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        const restored = await params.boundingBox();
        assert.ok(Math.abs(restored.width - after.width) < 1, JSON.stringify({after, restored}));
        console.log('PASS pointer resize + reload: ' + JSON.stringify({before: before.width, after: after.width, restored: restored.width}));
        for (const [width, height] of [[1440, 900], [800, 500]]) {
          await page.setViewportSize({width, height});
          await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
          const closeInspector=page.getByRole('button',{name:'Fold Inspector',exact:true});
          if(await closeInspector.isVisible()) await closeInspector.click();
          const openThread=page.getByRole('button',{name:'Open Thread',exact:true});
          if(!await page.locator('.v22g-thread').isVisible() && await openThread.isVisible()) await openThread.click();
          const token = page.locator('.dx-msg-line p').filter({hasText: 'x'.repeat(900)});
          const sizes = await token.evaluate(el => ({client: el.clientWidth, scroll: el.scrollWidth, page: document.documentElement.scrollWidth}));
          assert.ok(sizes.scroll <= sizes.client, JSON.stringify(sizes));
          assert.equal(sizes.page, Math.max(width,900), JSON.stringify(sizes));
          const details = page.getByRole('button', {name: 'Details', exact: true});
          await token.hover();
          await details.click(); assert.equal(await details.getAttribute('aria-expanded'), 'true');
          await details.click(); assert.equal(await details.getAttribute('aria-expanded'), 'false');
          await page.getByRole('button', {name: 'Reply', exact: true}).click();
          assert.equal(await page.getByRole('textbox', {name: 'Message', exact: true}).evaluate(el => el === document.activeElement), true);
          console.log('PASS message wrap + actions ' + width + 'x' + height + ': ' + JSON.stringify(sizes));
        }
        const draft = page.getByRole('textbox', {name: 'Message', exact: true});
        await draft.fill('Fixture draft A');
        await open('Recent task'); assert.equal(await draft.inputValue(), '');
        await draft.fill('Fixture draft B');
        await open('Selected task'); assert.equal(await draft.inputValue(), 'Fixture draft A');
        await page.evaluate(() => { window.holdSend = true; });
        await page.getByRole('button', {name: 'Send', exact: true}).click();
        await open('Recent task');
        assert.equal(await draft.inputValue(), 'Fixture draft B');
        await page.evaluate(() => window.finishSend(null));
        await open('Selected task');
        await page.waitForFunction(() => document.querySelector('textarea[aria-label="Message"]').value === 'Fixture draft A');
        await open('Recent task'); assert.equal(await draft.inputValue(), 'Fixture draft B');
        await open('Selected task'); assert.equal(await draft.inputValue(), 'Fixture draft A');
        assert.deepEqual(errors, []);
        console.log('PASS per-task drafts: Home + B round trips, no cross-task leak, delayed failed-request recovery after navigation; pageErrors=[]');
        await page.close(); continue;
      }
      if (mode === 'clicked') {
        await page.locator('.dx-task').filter({hasText: 'Selected task'}).dblclick();
        await page.getByRole('tab', {name:'Selected task',exact:true}).waitFor();
      }
      const boxes = [];
      for (const label of labels) boxes.push(await nav.getByRole('button', {name: label, exact: true}).boundingBox());
      boxes.forEach((box, index) => { assert.ok(box && box.height > 0); if (index) assert.ok(box.y >= boxes[index - 1].y + boxes[index - 1].height, labelAt(index)); });
      for (const face of ['Canvas', 'split']) {
        if(face==='Canvas' || ['empty','first','last','cancelled','refused'].includes(mode)) await nav.getByRole('button', {name: 'Canvas', exact: true}).click();
        else await page.getByRole('button', {name: 'Thread', exact: true}).click();
        if (['empty', 'first', 'last'].includes(mode)) {
          await page.getByRole('alert').filter({hasText: 'Pick a task on Home.'}).waitFor();
          assert.deepEqual(await page.evaluate(() => window.openedTasks), []);
          assert.equal(await nav.getByRole('button', {name: 'Home', exact: true}).getAttribute('aria-current'), 'page');
        } else if (mode === 'cancelled') {
          assert.equal(await page.evaluate(() => window.openedTasks.at(-1)), 'selected');
          assert.equal(await page.getByRole('textbox', {name: 'Task title', exact: true}).count(), 0);
          assert.equal(await nav.getByRole('button', {name: 'Home', exact: true}).getAttribute('aria-current'), 'page');
        } else if (mode === 'refused') {
          await page.getByRole('alert').filter({hasText: 'Fixture task open refused'}).waitFor();
          assert.equal(await page.locator('[data-home-face="canvas"]').count(), 0);
        } else {
          assert.deepEqual(errors, []);
          await page.locator('.dx-workspace[data-task-face="' + face.toLowerCase() + '"]').waitFor();
          await page.getByRole('tab', {name:'Selected task',exact:true}).waitFor();
          assert.equal(await page.evaluate(() => window.openedTasks.at(-1)), mode === 'first' ? 'recent' : 'selected');
          if(face==='split') await page.getByRole('region', {name:'Conversation',exact:true}).waitFor();
          assert.equal(await nav.getByRole('button', {name: 'Canvas', exact: true}).getAttribute('aria-current'), 'page');
        }
      }
      if (mode === 'selected') {
        await nav.getByRole('button', {name: 'Home', exact: true}).click();
        await page.locator('.dx-task').filter({hasText: 'Recent task'}).dblclick();
        await page.getByRole('tab', {name:'Recent task',exact:true}).waitFor();
        await nav.getByRole('button', {name: 'Canvas', exact: true}).click();
        await page.locator('.dx-workspace[data-task-face="canvas"]').waitFor();
        await nav.getByRole('button', {name: 'Home', exact: true}).click();
        await page.locator('.dx-task').filter({hasText: 'Selected task'}).dblclick();
        await page.getByRole('tab', {name:'Selected task',exact:true}).waitFor();
        await page.getByRole('region', {name:'Conversation',exact:true}).waitFor();
        await nav.getByRole('button', {name: 'Home', exact: true}).click();
        await page.locator('.dx-task').filter({hasText: 'Recent task'}).dblclick();
        await page.locator('.dx-workspace[data-task-face="canvas"]').waitFor();
        console.log('PASS per-task faces: new task Workshop; selected Workshop; recent Canvas');
        await nav.getByRole('button', {name: 'Home', exact: true}).click();
        await page.getByRole('region', {name:'Resumed session',exact:true}).waitFor();
        await page.locator('body').press('/');
        await page.getByRole('textbox', {name: 'Search everything', exact: true}).fill('Automations');
        await page.getByRole('button', {name: 'Pages', exact: true}).click();
        await page.getByRole('button', {name: 'Automations Pages', exact: true}).click();
        await page.getByRole('button', {name: 'Repeat recent task', exact: true}).click();
        await page.locator('.dx-workspace[data-task-face="canvas"]').waitFor();
        await page.getByRole('tab', {name:'Recent task',exact:true}).waitFor();
        assert.equal(await page.evaluate(() => window.openedTasks.at(-1)), 'recent');
      }
      await nav.getByRole('button', {name: 'Home', exact: true}).click();
      if(mode==='empty') await page.getByRole('heading', {name:'What do you need?',exact:true}).waitFor();
      else await page.getByRole('region', {name:'Resumed session',exact:true}).waitFor();
      assert.equal(await page.getByRole('textbox', {name: 'Task title', exact: true}).count(), 0);
      assert.deepEqual(errors, []);
      console.log('PASS rendered rail + non-overlap + task face clicks: ' + mode);
      await page.close();
    }
  } finally { await browser.close(); }
});
function labelAt(index) { return 'Rail button ' + index + ' overlaps its predecessor'; }
