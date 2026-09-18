/* The status strip confirms every update once and announces a release the launcher pushes when its
   download is ready; nothing shows while up to date. Founder 2026-09-17: "you updated and I got no
   notification". His build 20260916-2130-e733a13 came by local install, newer than every public
   release; the only update surfaces were an icon in the Workspace header and Settings > About, and the
   transport stopped reading update status once idle. Real React DOM in jsdom over the real Studio
   transport, the shipped status strip source and the launcher's own push script; get, post and the
   transport timers are in memory. No application, network, provider or graph. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

const UPDATE = '/api/universal/application-update';
const INSTALLED = '20260916-2130-e733a13', NEXT = '20260917-0900-0a1b2c3', PREVIOUS = '20260916-2105-b914892';
const RESTART = 'Restart to update', CONFIRM = 'Restart now - unsent text is lost';
const status = (state, extra = {}) => ({ok:true, current_build:INSTALLED, state,
  available_build:['ready', 'restarting'].includes(state) ? NEXT : null,
  detail:state === 'idle' ? 'Up to date.' : 'Build ' + NEXT + ' is downloaded and verified. Restart to update.',
  restart_supported:true, updated_from:null, updated_to:null, ...extra});
const plain = value => JSON.parse(JSON.stringify(value));
const pause = () => new Promise(resolve => setTimeout(resolve, 2));
const never = () => new Promise(() => {});
const answer = held => typeof held === 'function' ? held() : held;

// The exact script the launcher runs in the desktop page when a download reaches ready.
function launcherPush() {
  const launcher = read('launch_archhub_test.py');
  const start = launcher.indexOf('class _UpdatePush(');
  assert.ok(start > 0, 'the launcher pushes a ready download to the Studio page');
  const call = launcher.slice(start).match(/runJavaScript\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)/);
  assert.ok(call, 'the push runs one script in the desktop page');
  const script = [...call[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(match => match[1]).join('');
  assert.doesNotMatch(script, /\\/, 'the script carries no escapes');
  return transport => vm.runInContext(script, vm.createContext({window:transport ? {ARCHHUB_EXISTING_WORKSHOP:transport} : {}}));
}

function transportFor(server) {
  const timers = new Map(), listeners = new Map(), gets = [], posts = [];
  let timerId = 0;
  const document = {hidden:false, addEventListener:(name, fn) => listeners.set(name, fn),
    removeEventListener:name => listeners.delete(name)};
  const context = vm.createContext({URLSearchParams, TextEncoder, document,
    setTimeout:(fn, ms) => { timerId += 1; timers.set(timerId, {fn, ms}); return timerId; },
    clearTimeout:id => timers.delete(id)});
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), context);
  const transport = context.ArchHubExistingWorkshop.create({
    get:async url => { gets.push(url); return server.get(url); },
    post:async (url, body) => { posts.push({url, body}); return server.post(url, body); }});
  let publishes = 0;
  transport.subscribe(() => { publishes += 1; });
  const settle = async () => { for (let i = 0; i < 8; i += 1) await pause(); };
  const fire = async ms => {
    const due = [...timers.entries()].filter(([, timer]) => timer.ms === ms);
    assert.equal(due.length, 1, 'exactly one ' + ms + ' ms transport timer is scheduled');
    timers.delete(due[0][0]);
    due[0][1].fn();
    await settle();
  };
  return {transport, timers, gets, posts, document, listeners, settle, fire, publishes:() => publishes};
}

// One top-level definition of studio-lm.jsx, up to the next top-level definition or comment.
function definition(jsx, name) {
  const start = jsx.indexOf('\nconst ' + name + ' = ');
  assert.ok(start > 0, 'studio-lm.jsx defines ' + name);
  const next = /\n(?:const |\/\/ |window\.)/g;
  next.lastIndex = start + 1;
  return jsx.slice(start, next.exec(jsx).index);
}

async function mountSource(server, source, element, props) {
  const held = transportFor(server);
  const esbuild = require('esbuild');
  const {JSDOM} = require('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/studio', runScripts:'outside-only',
    pretendToBeVisual:true});
  const win = dom.window;
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  win.eval(esbuild.transformSync(read('nodelang/studio/tokens.jsx'), {loader:'jsx', target:'es2020'}).code);
  // React captured its own timer at load; only the restart confirmation window is observed here.
  const armed = [], setTimer = win.setTimeout.bind(win);
  win.setTimeout = (fn, ms, ...rest) => { if (ms === 5000) armed.push({fn, ms}); return setTimer(fn, ms, ...rest); };
  win.ARCHHUB_EXISTING_WORKSHOP = held.transport;
  win.ARCHHUB_LIVE = {connectors:[]};
  win.eval(esbuild.transformSync('(function () {\nconst LM = window.AH;\n' + source +
    '\nwindow.__Mounted = ' + element + ';\n})();', {loader:'jsx', target:'es2020'}).code);
  win.eval('window.__root = ReactDOM.createRoot(document.getElementById("root"));' +
    'ReactDOM.flushSync(() => window.__root.render(React.createElement(window.__Mounted, ' + JSON.stringify(props) + ')));');
  await held.settle();
  const doc = win.document;
  const button = label => [...doc.querySelectorAll('button')].find(node => node.textContent === label) || null;
  return {...held, win, doc, button, armed, push:transport => launcherPush()(transport),
    notice:() => doc.querySelector('[aria-label="Application update"]'),
    click:async node => { win.ReactDOM.flushSync(() => node.click()); await held.settle(); },
    expire:async () => { win.ReactDOM.flushSync(() => armed[armed.length - 1].fn()); await held.settle(); },
    close:() => { win.ReactDOM.flushSync(() => win.__root.unmount()); dom.window.close(); }};
}

async function mountStrip(server) {
  const jsx = read('nodelang/studio/studio-lm.jsx');
  const start = jsx.indexOf('const applicationUpdateNoticeState =');
  const end = jsx.indexOf('window.StudioLM = StudioLM;');
  assert.ok(start > 0 && end > start, 'studio-lm.jsx defines the application update notice before the status strip');
  const source = jsx.slice(start, end);
  assert.match(source, /const ServerStrip = /);
  assert.match(source, /<ApplicationUpdateNotice\/>/, 'the status strip carries the notice');
  // The strip names a picked model through modelRoute and restarts through the shared confirmation.
  const shared = ['modelRoute', 'useRestartConfirmation'].filter(name => jsx.includes('\nconst ' + name + ' = '))
    .map(name => definition(jsx, name)).join('\n');
  return mountSource(server, shared + '\n' + source, 'ServerStrip',
    {session:{file:'archhub.universal'}, model:{name:'Choose a model'}, account:null});
}

// The compact update controls, from the shipped source. The Workspace header draws the design row without them
// (design studio-lm.jsx:1146-1148); Settings > About and the status strip carry release updates.
async function mountHeaderControls(server) {
  const jsx = read('nodelang/studio/studio-lm.jsx');
  const header = jsx.slice(jsx.indexOf('\nconst WsHeader = '), jsx.indexOf('\nconst WsTab = '));
  assert.match(header, /<ApplicationUpdateControls compact\/>/,
    'the Workspace header draws the compact update icons (founder, 2026-09-18)');
  assert.match(definition(jsx, 'SettingsAbout'), /<ApplicationUpdateControls\/>/, 'Settings > About carries the update controls');
  const names = ['smallBtn', 'visuallyHiddenStyle', 'StudioHeaderIcon', 'ApplicationUpdateControls'];
  if (jsx.includes('\nconst useRestartConfirmation = ')) names.unshift('useRestartConfirmation');
  return mountSource(server, names.map(name => definition(jsx, name)).join('\n'), 'ApplicationUpdateControls', {compact:true});
}

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};

test('an idle Studio holds no update timer and the launcher push reads a staged release once', async () => {
  let current = status('idle');
  const push = launcherPush();
  const held = transportFor({get:url => { assert.equal(url, UPDATE); return answer(current); },
    post:() => assert.fail('reading status never posts')});
  const unwatch = held.transport.watchApplicationUpdate();
  await held.settle();
  assert.deepEqual(held.gets, [UPDATE]);
  assert.equal(held.timers.size, 0, 'an up-to-date Studio polls nothing and a finished read leaves no timeout behind');
  const before = held.publishes();
  current = status('ready');
  assert.equal(push(held.transport), undefined);
  await held.settle();
  assert.deepEqual(held.gets, [UPDATE, UPDATE], 'one push is one read');
  assert.equal(held.transport.getSnapshot().applicationUpdate.state, 'ready');
  assert.equal(held.transport.getSnapshot().applicationUpdate.available_build, NEXT);
  assert.ok(held.publishes() > before, 'the staged release is published');
  assert.equal(held.timers.size, 0);
  assert.equal(push(null), undefined, 'before the Studio mounts the push finds nothing and throws nothing');
  current = () => { throw new Error('closing'); };
  push(held.transport);
  await held.settle();
  assert.match(held.transport.getSnapshot().applicationUpdateError, /closing/, 'a failed pushed read is reported, not thrown');
  unwatch();
  assert.equal(held.listeners.size, 0);
});

test('a status read that never answers is abandoned after 15 seconds and the next read goes out', async () => {
  let current = never;
  const held = transportFor({get:() => answer(current), post:() => assert.fail('reading status never posts')});
  const unwatch = held.transport.watchApplicationUpdate();
  await held.settle();
  assert.deepEqual(held.gets, [UPDATE]);
  assert.equal(held.transport.getSnapshot().applicationUpdatePending, 'read');
  await held.fire(15000);
  const snapshot = held.transport.getSnapshot();
  assert.equal(snapshot.applicationUpdatePending, '');
  assert.match(snapshot.applicationUpdateError, /did not answer within 15 seconds/);
  current = status('ready');
  await held.transport.refreshApplicationUpdate();
  assert.deepEqual(held.gets, [UPDATE, UPDATE], 'a hung read no longer holds back the next one');
  assert.equal(held.transport.getSnapshot().applicationUpdate.state, 'ready');
  assert.equal(held.transport.getSnapshot().applicationUpdateError, '');
  assert.equal(held.timers.size, 0);
  unwatch();
});

test('nothing is shown while up to date; a pushed ready release appears in the status strip', async () => {
  let current = status('idle');
  const strip = await mountStrip({get:() => current, post:() => assert.fail('no update action while reading')});
  try {
    assert.ok(strip.gets.length >= 1 && strip.gets.every(url => url === UPDATE));
    assert.equal(strip.notice(), null, 'up to date: no notice');
    assert.equal(strip.button(RESTART), null);
    assert.ok(strip.button('docs') && strip.button('settings'), 'the shipped status strip rendered');
    assert.equal(strip.timers.size, 0, 'the strip holds no update poll');
    current = status('ready');
    strip.push(strip.transport);
    await strip.settle();
    const notice = strip.notice();
    assert.ok(notice, 'the staged release is announced without reloading Studio');
    assert.equal(notice.getAttribute('role'), 'status');
    assert.ok(notice.textContent.includes('Update ready') && notice.textContent.includes(NEXT), notice.textContent);
    const restart = strip.button(RESTART);
    assert.ok(restart && !restart.disabled && notice.contains(restart));
    assert.equal(strip.doc.querySelector('[role="dialog"], [aria-modal="true"]'), null, 'the notice never blocks the window');
    assert.ok(strip.button('docs') && strip.button('settings'), 'the strip keeps its own controls beside the notice');
  } finally { strip.close(); }
});

test('Restart to update needs a confirming second click that warns unsent text is lost', async () => {
  let current = status('ready');
  const strip = await mountStrip({get:() => current, post:(url, body) => {
    assert.equal(url, UPDATE); assert.deepEqual(plain(body), {action:'reload'});
    current = status('restarting', {detail:'Saving your data and restarting into the update.'});
    return current;
  }});
  try {
    await strip.click(strip.button(RESTART));
    assert.deepEqual(strip.posts, [], 'one click never restarts');
    assert.equal(strip.button(RESTART), null);
    assert.ok(strip.button(CONFIRM), 'the first click asks again and names what is lost');
    assert.deepEqual(strip.armed.map(timer => timer.ms), [5000], 'the confirmation expires on its own');
    await strip.expire();
    assert.ok(strip.button(RESTART) && !strip.button(CONFIRM), 'after 5 s the button starts over');
    assert.deepEqual(strip.posts, []);
    await strip.click(strip.button(RESTART));
    await strip.click(strip.button(CONFIRM));
    assert.deepEqual(plain(strip.posts), [{url:UPDATE, body:{action:'reload'}}], 'the confirming click restarts once');
    assert.equal(strip.button(RESTART), null);
    assert.equal(strip.button(CONFIRM), null, 'no second restart request is offered');
    assert.match(strip.notice().textContent, /Restarting into build 20260917-0900-0a1b2c3/);
  } finally { strip.close(); }
});

test('a refused restart stays in the strip, names the refusal and reads status again', async () => {
  const current = status('ready');
  let refuse = true;
  const strip = await mountStrip({get:() => current, post:() => {
    if (refuse) throw new Error('Wait for the update download to finish');
    return status('restarting');
  }});
  try {
    await strip.click(strip.button(RESTART));
    await strip.click(strip.button(CONFIRM));
    const notice = strip.notice();
    assert.equal(notice.getAttribute('role'), 'alert');
    assert.ok(notice.textContent.includes('Wait for the update download to finish'), notice.textContent);
    assert.equal(strip.button(RESTART), null);
    assert.equal(strip.button(CONFIRM), null);
    const reads = strip.gets.length;
    refuse = false;
    await strip.click(strip.button('Read status'));
    assert.equal(strip.gets.length, reads + 1);
    assert.equal(strip.notice().getAttribute('role'), 'status');
    assert.ok(strip.button(RESTART), 'a verified ready status offers the restart again, unconfirmed');
  } finally { strip.close(); }
});

for (const [label, from] of [['a local install', null], ['a release update', PREVIOUS]]) {
  test('after ' + label + ' the strip confirms the running build once and Dismiss acknowledges it', async () => {
    let current = status('idle', {updated_from:from, updated_to:INSTALLED});
    const strip = await mountStrip({get:() => current, post:(url, body) => {
      assert.equal(url, UPDATE); assert.deepEqual(plain(body), {action:'acknowledge'});
      current = status('idle');
      return current;
    }});
    try {
      const notice = strip.notice();
      assert.ok(notice, 'the running build is confirmed without any release check');
      assert.equal(notice.getAttribute('role'), 'status');
      assert.ok(notice.textContent.includes('Updated to build ' + INSTALLED), notice.textContent);
      assert.equal(notice.getAttribute('title'),
        from ? 'Updated from build ' + from + ' to build ' + INSTALLED : 'Updated to build ' + INSTALLED);
      assert.equal(strip.button(RESTART), null);
      const dismiss = strip.button('Dismiss');
      assert.ok(dismiss && notice.contains(dismiss));
      assert.deepEqual(strip.posts, [], 'reading the confirmation acknowledges nothing');
      await strip.click(dismiss);
      assert.deepEqual(plain(strip.posts), [{url:UPDATE, body:{action:'acknowledge'}}]);
      assert.equal(strip.notice(), null, 'dismissed: the confirmation is gone');
      await assert.rejects(strip.transport.applicationUpdateAction('acknowledge'), /No update confirmation is waiting/);
      assert.equal(strip.posts.length, 1);
    } finally { strip.close(); }
  });
}

test('a first status read that answers after 15 seconds still confirms the update and the late answer applies', async () => {
  const late = deferred();
  const strip = await mountStrip({get:() => late.promise, post:(url, body) => {
    assert.equal(url, UPDATE); assert.deepEqual(plain(body), {action:'acknowledge'});
    return status('idle');
  }});
  try {
    assert.deepEqual(strip.gets, [UPDATE]);
    await strip.fire(15000);
    const waiting = strip.notice();
    assert.ok(waiting, 'a read that did not answer is shown, never an empty strip');
    assert.equal(waiting.getAttribute('role'), 'alert');
    assert.match(waiting.textContent, /did not answer within 15 seconds/);
    assert.ok(strip.button('Read status') && waiting.contains(strip.button('Read status')));
    late.resolve(status('idle', {updated_from:PREVIOUS, updated_to:INSTALLED}));
    await strip.settle();
    const snapshot = strip.transport.getSnapshot();
    assert.equal(snapshot.applicationUpdate?.updated_to, INSTALLED, 'the late verified answer is applied');
    assert.equal(snapshot.applicationUpdateError, '', 'and it clears the abandoned read');
    const notice = strip.notice();
    assert.equal(notice.getAttribute('role'), 'status');
    assert.ok(notice.textContent.includes('Updated to build ' + INSTALLED), notice.textContent);
    assert.deepEqual(strip.gets, [UPDATE], 'the late answer needed no second read');
    assert.equal(strip.timers.size, 0);
    await strip.click(strip.button('Dismiss'));
    assert.deepEqual(plain(strip.posts), [{url:UPDATE, body:{action:'acknowledge'}}]);
    assert.equal(strip.notice(), null, 'acknowledged: the confirmation is gone');
  } finally { strip.close(); }
});

test('a late answer never overrides a newer read, and a failed first read keeps the confirmation for Read status', async () => {
  const late = deferred();
  let current = () => late.promise;
  const held = transportFor({get:() => answer(current), post:() => assert.fail('reading status never posts')});
  const unwatch = held.transport.watchApplicationUpdate();
  await held.settle();
  await held.fire(15000);
  current = status('idle');
  await held.transport.refreshApplicationUpdate();
  late.resolve(status('ready'));
  await held.settle();
  assert.equal(held.transport.getSnapshot().applicationUpdate.state, 'idle', 'the newer read owns the status');
  unwatch();

  let refuse = true;
  const strip = await mountStrip({get:() => {
    if (refuse) throw new Error('Update status could not be read (connection reset).');
    return status('idle', {updated_to:INSTALLED});
  }, post:() => assert.fail('no update action while reading')});
  try {
    const notice = strip.notice();
    assert.ok(notice, 'a failed first read is shown in the strip');
    assert.equal(notice.getAttribute('role'), 'alert');
    assert.match(notice.textContent, /could not be read/);
    assert.equal(strip.button('Dismiss'), null);
    refuse = false;
    await strip.click(strip.button('Read status'));
    assert.ok(strip.notice().textContent.includes('Updated to build ' + INSTALLED), strip.notice().textContent);
    assert.ok(strip.button('Dismiss'), 'the confirmation waits until it is acknowledged');
  } finally { strip.close(); }
});

test('the compact update restart needs the same confirming second click as the strip; the Workspace header draws none', async () => {
  let current = status('ready');
  const header = await mountHeaderControls({get:() => current, post:(url, body) => {
    assert.equal(url, UPDATE); assert.deepEqual(plain(body), {action:'reload'});
    current = status('restarting');
    return current;
  }});
  try {
    const reload = () => header.doc.querySelector('button[aria-label="Update and reload"]');
    const confirm = () => header.doc.querySelector('button[aria-label="' + CONFIRM + '"]');
    assert.ok(reload() && !reload().disabled, 'a ready release offers the compact restart');
    await header.click(reload());
    assert.deepEqual(header.posts, [], 'one click on the header never restarts');
    assert.ok(confirm() && !reload(), 'the first click asks again and names what is lost');
    assert.equal(confirm().getAttribute('title'), CONFIRM);
    assert.deepEqual(header.armed.map(timer => timer.ms), [5000], 'the confirmation expires on its own');
    await header.expire();
    assert.ok(reload() && !confirm(), 'after 5 s the header button starts over');
    assert.deepEqual(header.posts, []);
    await header.click(reload());
    await header.click(confirm());
    assert.deepEqual(plain(header.posts), [{url:UPDATE, body:{action:'reload'}}], 'the confirming click restarts once');
    const jsx = read('nodelang/studio/studio-lm.jsx');
    assert.equal(jsx.split('const useRestartConfirmation = ').length, 2, 'one restart confirmation, defined once');
    for (const name of ['ApplicationUpdateNotice', 'ApplicationUpdateControls']) {
      assert.match(definition(jsx, name), /useRestartConfirmation\(/, name + ' confirms through the shared hook');
    }
  } finally { header.close(); }
});