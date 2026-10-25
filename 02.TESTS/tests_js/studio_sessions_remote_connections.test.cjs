const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..', '..');



test('real Studio transport posts one-click remote MCP client installs and opens the returned client page', () => {
  const source = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-existing-workshop.js'), 'utf8');
  assert.match(source, /async installMcpClient\(provider\)/);
  assert.match(source, /post\('\/api\/universal\/mcp-client-install', \{provider:String\(provider \|\| ''\)\}\)/);
  assert.match(source, /global\.open\(result\.open_url, '_blank', 'noopener,noreferrer'\)/);
});
