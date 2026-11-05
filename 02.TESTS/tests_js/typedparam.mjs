import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import path from 'node:path';
const config = JSON.parse(readFileSync(0, 'utf8'));
const require = createRequire(path.join(process.env.ARCHHUB_NODE_MODULES, 'playwright/package.json'));
const {chromium} = require('playwright');
const browser = await chromium.launch({headless: true, channel: 'chromium'});
try {
  const page = await browser.newPage();
  await page.route('**/*', route => new URL(route.request().url()).origin === new URL(config.url).origin ? route.continue() : route.abort());
  await page.goto(config.url);
  await page.waitForFunction(() => window.ArchHubAPI);
  await page.evaluate(() => window.ArchHubAPI.ready);
  await page.evaluate(file => window.ArchHubAPI.openSession(file), config.path);
  for (const entry of config.cases) {
    const result = await page.evaluate(async ({kind, socket}) => {
      const api = window.ArchHubAPI, a = kind+'-a', b = kind+'-b';
      const target = api.getSnapshot().graph.nodes.find(n => n.id === b);
      const inputs = target.inputs.filter(p => p.id === 'value' || p.id === 'param:value');
      const widget = target.parameterSchema.find(p => p.key === 'value');
      await api.connectSockets({from:a, fromPort:'value', to:b, toPort:'value'});
      await api.solveNow();
      const output = api.getSessionDocument().nodes.find(n => n.id === b).result.output.value;
      let mismatch = 'any';
      if (socket !== 'any') {
        const wrong = socket === 'string' ? 'number-a' : 'text-a';
        try { await api.connectSockets({from:wrong, fromPort:'value', to:b, toPort:'value'}); mismatch = 'accepted'; }
        catch (error) { mismatch = error.message; }
      }
      return {inputs, widget, output, mismatch};
    }, entry);
    assert.equal(result.inputs.length, 2);
    assert.ok(result.inputs.every(p => p.type === entry.socket), JSON.stringify(result));
    assert.equal(result.widget.dataType, entry.kind);
    const editor = {bool:'boolean',integer:'number',number:'number',date:'date',color:'color',list:'json',json:'json',object:'json'}[entry.kind] || 'text';
    assert.equal(result.widget.type, editor);
    assert.deepEqual(result.output, entry.value);
    if (entry.socket !== 'any') assert.match(result.mismatch, /Wrong type/);
    console.log(`TYPEDPARAM compiled Studio: ${entry.kind} sockets=${entry.socket} widget=${editor} chain=pass mismatch=pass`);
  }
} finally { await browser.close(); }
