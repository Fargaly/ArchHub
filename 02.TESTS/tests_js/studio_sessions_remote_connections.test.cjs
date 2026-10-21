const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = require('./studio_settings_design.test.cjs');
const root = path.resolve(__dirname, '..', '..');

test('Settings Connections has one Notion button and one Gemini button', async () => {
  const s = await base.openSettingsForCourt({connectionCalls:true});
  try {
    const panel = await s.tab('Connections');
    assert.ok(panel.textContent.includes('Notion'), 'Notion row is visible');
    assert.ok(panel.textContent.includes('Gemini'), 'Gemini row is visible');
    assert.equal(s.buttons(panel, 'Add ArchHub to Notion').length, 1);
    assert.equal(s.buttons(panel, 'Add ArchHub to Gemini').length, 1);
    assert.equal(panel.textContent.includes('https://api.archhub.io/mcp'), false, 'no URL copy text is printed');
    assert.equal(/copy|paste/i.test(panel.textContent), false, 'no copy-paste instructions are printed');
    s.flush(() => s.buttons(panel, 'Add ArchHub to Notion')[0].click());
    s.flush(() => s.buttons(panel, 'Add ArchHub to Gemini')[0].click());
    await s.settle();
    assert.deepEqual(s.calls.clientMcp, ['notion', 'gemini']);
  } finally {
    s.close();
  }
});

test('real Studio transport posts one-click remote MCP client installs and opens the returned client page', () => {
  const source = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-existing-workshop.js'), 'utf8');
  assert.match(source, /async installMcpClient\(provider\)/);
  assert.match(source, /post\('\/api\/universal\/mcp-client-install', \{provider:String\(provider \|\| ''\)\}\)/);
  assert.match(source, /global\.open\(result\.open_url, '_blank', 'noopener,noreferrer'\)/);
});
