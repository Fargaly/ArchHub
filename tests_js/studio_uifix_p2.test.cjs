const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

// Reuse the compiled, mounted Studio harness without registering its courts twice.
const filename = path.join(__dirname, 'studio_workshop_open.test.cjs');
const harness = new Module(filename, module);
harness.filename = filename;
harness.paths = module.paths;
const source = fs.readFileSync(filename, 'utf8');
const harnessSource = source.slice(0, source.indexOf("\ntest('"))
  .replace("win.eval(read('nodelang/studio/compiled/' + file.output));",
    "win.eval(read('nodelang/studio/compiled/' + file.output).replace(/window\\.StudioLM\\s*=\\s*StudioLM;/, 'window.StudioLM=StudioLM;window.__UIFIX_NodeRenderer=NodeRenderer;')); ");
harness._compile(harnessSource + '\nmodule.exports={mountStudio};', filename);
const {mountStudio} = harness.exports;
const settle = async ui => { for (let i = 0; i < 10; i++) await new Promise(resolve => ui.win.setTimeout(resolve, 0)); };
const clickRail = async (ui, name) => {
  const button = ui.doc.querySelector(`[data-app-rail] [aria-label="${name}"]`);
  assert.ok(button, name + ' has a visible rail destination');
  ui.flush(() => button.click());
  await settle(ui);
};

test('UIFIX p2: one persistent rail exposes Chats and the union of destinations on Settings', async () => {
  const ui = await mountStudio({workshops:[{root:'room-a',label:'Workshop',is_general:true}]});
  try {
    const rail = ui.doc.querySelector('[data-app-rail]');
    const destinations = ['Home','Chats','Workshop','Canvas','Library','Docs','Cockpit','Settings'];
    for (const name of destinations) assert.ok(rail.querySelector(`[aria-label="${name}"]`), name);
    for (const name of ['Settings','Chats','Workshop','Library','Canvas','Home','Settings']) {
      await clickRail(ui, name);
      assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length, 1, name + ' has one rail');
      assert.equal(ui.doc.querySelector('[data-app-rail]'), rail, name + ' retains the rail DOM node');
      for (const destination of destinations) assert.ok(rail.querySelector(`[aria-label="${destination}"]`), destination);
    }
  } finally {ui.close();}
});

test('UIFIX p2: a never-run canvas card has no placeholder footer', async () => {
  const ui = await mountStudio();
  try {
    ui.win.eval(`ReactDOM.flushSync(() => window.__studioRoot.render(React.createElement(window.__UIFIX_NodeRenderer, {
      n:{id:'never-run',title:'Number',cat:'logic',live:true,x:0,y:0,ins:[],outs:[],params:[],result:''}
    })));`);
    const card = ui.doc.querySelector('[data-node-id="never-run"]');
    assert.ok(card, 'real NodeRenderer mounts');
    const footer = card.querySelector('[data-node-footer-status]');
    if (footer) {
      assert.doesNotMatch(footer.textContent, /Not available yet/);
      assert.match(footer.textContent, /not run yet/i);
      assert.ok([...card.querySelectorAll('button')].some(button => /run/i.test(button.textContent)), 'a never-run state has a Run action');
    }
    ui.win.eval(`ReactDOM.flushSync(() => window.__studioRoot.render(React.createElement(window.__UIFIX_NodeRenderer, {
      n:{id:'completed',title:'Number',cat:'logic',live:true,x:0,y:0,ins:[],outs:[],params:[],result:'',state:'done'}
    })));`);
    const completed = ui.doc.querySelector('[data-node-id="completed"] [data-node-footer-status]');
    assert.ok(completed, 'real state retains its footer');
    assert.match(completed.textContent, /done/);
    assert.doesNotMatch(completed.textContent, /Not available yet/);
  } finally {ui.close();}
});

test('UIFIX p2: Workshop rail opens the Workshop window when an existing graph is available', async () => {
  const ui = await mountStudio({workshops:[{root:'room-a',label:'Workshop',is_general:true}]});
  try {
    await clickRail(ui, 'Workshop');
    assert.ok(ui.doc.querySelector('[data-workshop72]'), 'Workshop v3 window mounts');
    assert.equal(ui.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), null, 'Workshop does not mount the graph canvas');
    assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Workshop message"]').length, 1);
    await clickRail(ui, 'Canvas');
    assert.ok(ui.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), 'Canvas remains separately reachable');
  } finally {ui.close();}
});

test('UIFIX p2: Settings lands on controls and opens its System graph only by its labelled button', async () => {
  const ui = await mountStudio();
  try {
    await clickRail(ui, 'Settings');
    const shell = ui.doc.querySelector('[data-settings54-shell]');
    assert.ok(shell, 'Settings page mounts');
    assert.equal(shell.parentElement.style.left, '64px', 'Settings clears the complete shared rail');
    assert.equal(shell.querySelector('[data-settings54-graph]'), null, 'Settings landing does not mount the System card wall');
    assert.ok(shell.querySelector('[data-settings54-capability]'), 'designed settings controls are visible');
    const button = [...shell.querySelectorAll('button')].find(button => /^(Open )?System graph$/i.test(button.textContent.trim()));
    assert.ok(button, 'System graph has an explicit labelled entry');
    ui.flush(() => button.click());
    await settle(ui);
    assert.ok(shell.querySelector('[data-settings54-graph]'), 'the labelled button opens the System graph');
  } finally {ui.close();}
});
