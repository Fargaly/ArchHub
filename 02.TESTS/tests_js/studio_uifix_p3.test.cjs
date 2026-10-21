const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const {settingsNavigator} = require('./settings_navigation_helpers.cjs');

// Reuse the mounted real Studio and its admitted System owner, without registering
// the existing file's courts. Only the service boundary and component export differ.
const filename = path.join(__dirname, 'studio_first_screen_default_model.test.cjs');
const harness = new Module(filename, module);
harness.filename = filename;
harness.paths = module.paths;
const source = fs.readFileSync(filename, 'utf8');
const harnessSource = source.slice(0, source.indexOf('\nconst modelIndicators'))
  .replace('selectionTransport = null}', 'selectionTransport = null, toolPayload = null}')
  .replace('win.fetch = url => {', `win.fetch = url => {
    if (String(url) === '/tools' && toolPayload) return Promise.resolve({ok:true, json:async () => toolPayload()});
    if (String(url) === '/waiting') return Promise.resolve({ok:true, json:async () => ({ok:true, items:[]})});`)
  .replace("win.eval(read('01.APP/nodelang/studio/compiled/' + file.output));",
    "win.eval(read('01.APP/nodelang/studio/compiled/' + file.output).replace(/window\\.StudioLM\\s*=\\s*StudioLM;/, 'window.StudioLM=StudioLM;window.__UIFIX_ToolCard=ToolCard;')); ");
harness._compile(harnessSource + '\nmodule.exports={mountStudio};', filename);
const {mountStudio} = harness.exports;
const settle = async ui => { for (let i = 0; i < 10; i++) await new Promise(resolve => ui.win.setTimeout(resolve, 0)); };
const clickRail = async (ui, label) => {
  const button = ui.doc.querySelector(`[data-app-rail] [aria-label="${label}"]`);
  assert.ok(button, label + ' visible rail destination');
  ui.flush(() => button.click());
  await settle(ui);
};
const navigator = ui => settingsNavigator({doc:ui.doc, flush:ui.flush, settle:() => settle(ui)});
const namedButton = (root, label) => [...root.querySelectorAll('button')].find(node => node.textContent.trim() === label);

// SX/F1 courts the actual System mode, rather than the separate Settings graph wall.
test('UIFIX p3 SX: Settings System labelled control opens admitted System mode and header Home returns Home', async () => {
  const ui = await mountStudio({home:true, systemView:true});
  try {
    await clickRail(ui, 'Settings');
    assert.ok(namedButton(ui.doc.querySelector('[data-settings54-shell]'), 'System graph'), 'Pass 2 top-bar System graph entry remains');
    const nav = navigator(ui);
    await nav.tab('Account');
    const systemEntry = [...ui.doc.querySelectorAll('[data-settings54-capability-nav] button')].find(node => node.textContent.trim() === 'System');
    assert.ok(systemEntry, 'System section is visible even while Account is selected');
    ui.flush(() => systemEntry.click());
    await settle(ui);
    const panel = ui.doc.querySelector('[data-settings54-capability="System"]');
    assert.ok(panel, 'Settings System owner mounts');
    const open = namedButton(panel, 'Open the System graph');
    assert.ok(open, 'System section owns a visible labelled Open the System graph control');
    assert.equal(open.disabled, false, 'admitted owner enables its control');
    ui.flush(() => open.click());
    await ui.settle(() => ui.doc.querySelector('[data-system-header]'), 'actual System mode header mounts');
    const home = ui.doc.querySelector('[data-system-header] button[aria-label="Home"]');
    assert.ok(home, 'System header exposes labelled Home');
    assert.equal(home.textContent.trim(), 'Home');
    ui.flush(() => home.click());
    await ui.settle(() => ui.doc.querySelector('[data-home-page]'), 'header Home lands on Home');
    assert.equal(ui.doc.querySelector('[data-system-header]'), null);
    assert.equal(ui.doc.querySelector('[data-ws-tab][aria-current="true"]'), null);
  } finally {ui.close();}
});

const TOOL_IDS = ['studio','workshop','brain','baboom','connectors','cloud'];
const TOOL_LABELS = ['Studio','Workshop','Brain','BABOOM','Connectors','Cloud'];
const payload = () => ({ok:true, tools:TOOL_IDS.map((id, index) => ({id, label:TOOL_LABELS[index],
  state:id === 'brain' ? 'off' : id === 'cloud' ? 'starting' : 'running',
  state_word:id === 'brain' ? 'OFF' : id === 'cloud' ? 'STARTING' : 'RUNNING',
  description:'Owner description ' + id, stat_line:'Owner stat ' + id, off_sentence:'Owner stat ' + id}))});
const renderedBySharedToolCard = (ui, node) => {
  const key = Object.keys(node).find(key => key.startsWith('__reactFiber$'));
  for (let fiber = node[key]; fiber; fiber = fiber.return) if (fiber.type === ui.win.__UIFIX_ToolCard) return true;
  return false;
};
test('UIFIX p3 K: Connections Hub owns exactly six shared ToolCards with real tools response state', async () => {
  const ui = await mountStudio({home:true, toolPayload:payload});
  try {
    await clickRail(ui, 'Settings');
    await navigator(ui).tab('Hub');
    const hub = ui.doc.querySelector('[data-settings54-capability="Hub"]');
    assert.ok(hub, 'Connections > Hub owner mounts');
    await ui.settle(() => hub.querySelector('[data-tool-card="cloud"]')?.textContent.includes('STARTING'), 'tool owner response reaches Hub');
    const cards = [...hub.querySelectorAll('[data-tool-card]')];
    assert.deepEqual(cards.map(node => node.getAttribute('data-tool-card')), TOOL_IDS);
    assert.equal(ui.doc.querySelectorAll('[data-tool-card]').length, 6, 'six tools live in one mounted place');
    for (const card of cards) {
      const id = card.getAttribute('data-tool-card');
      assert.ok(renderedBySharedToolCard(ui, card), id + ' is rendered by the shared ToolCard component');
      assert.equal(card.querySelector('[data-tool-description]').textContent, 'Owner description ' + id);
      assert.equal(card.querySelector('[data-tool-stat]').textContent, id === 'connectors' ? '0/0 hosts running.' : 'Owner stat ' + id);
      assert.match(card.textContent, new RegExp(id === 'connectors' ? 'Not running' : id === 'brain' ? 'OFF' : id === 'cloud' ? 'STARTING' : 'RUNNING'));
    }
    await navigator(ui).tab('Connections');
    assert.equal(ui.doc.querySelectorAll('[data-tool-card]').length, 0, 'Connections does not duplicate the Hub cards');
    await clickRail(ui, 'Home');
    assert.equal(ui.doc.querySelectorAll('[data-tool-card]').length, 0, 'Home does not duplicate the Hub cards');
  } finally {ui.close();}
});

test('UIFIX p3 CP/y: unavailable Cockpit has no rail route and remaining conversation destinations keep their composers', async () => {
  const ui = await mountStudio({home:true});
  try {
    for (const label of ['Home','Settings','Workshop','Chats','Home']) {
      await clickRail(ui, label);
      assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length, 1, label + ' has one rail');
      assert.equal(!!ui.doc.querySelector('[data-app-rail] [aria-label="Cockpit"]'), false, label + ' has no empty Cockpit destination');
      assert.equal(!!ui.doc.querySelector('[data-tool-view="cockpit"]'), false);
      if (label === 'Home') assert.ok(ui.doc.querySelector('textarea[aria-label="Start a new session"]'), 'Home composer survives');
      if (label === 'Workshop') assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Workshop message"]').length, 1, 'Workshop composer survives');
      if (label === 'Chats') assert.ok(ui.doc.querySelector('[aria-label="Reply"], textarea[aria-label="Start a new session"]'), 'Chats retains the conversation composer');
    }
  } finally {ui.close();}
});
