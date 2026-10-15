const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const filename = path.join(__dirname, 'studio_first_screen_default_model.test.cjs');
const harness = new Module(filename, module);
harness.filename = filename;
harness.paths = module.paths;
let source = fs.readFileSync(filename, 'utf8').split('\nconst modelIndicators')[0];
source = source.replace("const canvas = {graph_id:'graph-a'", "graph.nodes = graph.nodes.filter(node => !node.application);\n  const canvas = {canvas_root:'canvas-root', application_root:'application-root', scope:{current:'child', trail:[{root:'canvas-root', label:'Canvas'}, {root:'child', label:'Child'}]}, graph_id:'graph-a'");
source = source.replace("topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}", "topology:{canvas:{canvas_root:'canvas-root', application_root:'application-root', scope:{current:'child', trail:[{root:'canvas-root', label:'Canvas'}, {root:'child', label:'Child'}]}");
source = source.replace("win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}]", "win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'Child', state:'idle', host:'archhub', file:'Graph composition'}, {id:'canvas-root', title:'Root canvas', state:'idle', host:'archhub', file:'Graph composition'}]");
source = source.replace('if (graphOpen) win.ARCHHUB_GRAPH_OPEN = graphOpen;', `win.ARCHHUB_MODS = async () => { throw new Error('not found'); };
  win.ARCHHUB_GRAPH_OPEN = async id => {
    await graphOpen(id);
    graph.nodes.push({...graph.nodes[0], id:'app-node', title:'Application node', application:true, x:320, y:60});
    snapshot.canvas = {...canvas, graph_id:'application-root', root:id};
    snapshot.topology.canvas = {...canvas, root:id, scope:{current:id}, application_root:'application-root'};
    listeners.forEach(listener => listener());
    return {ok:true, current_graph:id, graphs:[{id, title:'Root canvas', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'', model:''}], canvas:snapshot.topology.canvas};
  };`);
harness._compile(source + '\nmodule.exports={mountStudio};', filename);
const {mountStudio} = harness.exports;
const button = (doc, label) => [...doc.querySelectorAll('button')].find(node => node.textContent.trim() === label);
const settle = async ui => { for (let i=0;i<15;i++) await new Promise(resolve=>ui.win.setTimeout(resolve,0)); };
for (const entry of ['Open the System graph', 'System graph']) test('SXFIX child scope opens real System owner via ' + entry, async () => {
  const calls = [];
  const ui = await mountStudio({home:true, systemView:true, graphOpen:async id => calls.push(id)});
  try {
    ui.flush(()=>ui.doc.querySelector('[data-app-rail] [aria-label="Settings"]').click());
    await settle(ui);
    ui.flush(()=>button(ui.doc, 'System').click());
    await settle(ui);
    ui.flush(()=>button(ui.doc, entry).click());
    await settle(ui);
    assert.deepEqual(calls, ['canvas-root'], 'opens authoritative canvas root, not first child session');
    assert.ok(ui.doc.querySelector('[data-system-header] button[aria-label="Home"]'), 'labelled Home in real System header');
    assert.ok(ui.doc.querySelector('[data-node-id="app-node"]'), 'application node from returned root projection renders');
    assert.equal(ui.doc.querySelector('[data-settings54-graph]'), null, 'no alternate Settings renderer opens');
    ui.flush(()=>ui.doc.querySelector('[data-system-header] button[aria-label="Home"]').click());
    await settle(ui);
    assert.ok(ui.doc.querySelector('[data-home-page]'));
  } finally {ui.close();}
});
test('SXFIX Hub omits unavailable Mods remnant and retains six tool cards', async () => {
  const ui = await mountStudio({home:true});
  try {
    ui.flush(()=>ui.doc.querySelector('[data-app-rail] [aria-label="Settings"]').click());
    await settle(ui);
    ui.flush(()=>[...ui.doc.querySelectorAll('[data-settings54-nav] button')].find(node => node.querySelector('[data-settings54-group-title]')?.textContent === 'Connections').click());
    await settle(ui);
    ui.flush(()=>button(ui.doc, 'Hub').click());
    await settle(ui);
    const hub = ui.doc.querySelector('[data-settings54-capability="Hub"]');
    assert.ok(hub);
    assert.equal(hub.querySelectorAll('[data-tool-card]').length, 6);
    assert.doesNotMatch(hub.textContent, /not found|Reading installed mods/);
  } finally {ui.close();}
});
