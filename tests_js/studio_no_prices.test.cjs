/* Source text only: no DOM, no React, no network, no application, no graph writes. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const studio = path.join(__dirname, '..', 'nodelang', 'studio');
const surfaces = ['studio-account.jsx', 'studio-lm.jsx', 'studio-suite.jsx'];
const source = new Map(surfaces.map(name =>
  [name, fs.readFileSync(path.join(studio, name), 'utf8')]));
const lines = name => source.get(name).split(/\r?\n/);
const found = (name, pattern) => lines(name)
  .flatMap((text, index) => pattern.test(text) ? [`${name}:${index + 1} ${text.trim()}`] : []);

// What the app may not state on its own authority: a price, a plan table, a plan-table
// quota, a version, or a mock badge shipped as a measurement. The offer is a graph record;
// until its data path exists the app shows nothing rather than a hard-coded label.
const banned = [
  ['plan table', /AC_PLANS/],
  ['monthly price', /\$\{\s*p\.price\s*\}/],
  ['seat price', /\/seat\/mo|price="\$\d/],
  ['plan-table quota', /\b(cap|opsCap):\s*\d/],
  ['version literal', /v0\.27\.0/],
  ['model badge', /'Sonnet 4\.5'/],
  ['storage badge', /'2\.3 GB'/],
  ['unsourced offer label', /Free during beta/],
];

test('no Studio surface states a price, a plan table, a quota or a mock badge', () => {
  const rows = [];
  for (const name of surfaces) {
    for (const [what, pattern] of banned) {
      for (const row of found(name, pattern)) rows.push(`${what} — ${row}`);
    }
  }
  assert.deepEqual(rows, [], `A Studio surface still carries a hard-coded literal:\n${rows.join('\n')}`);
});

test('nothing in nodelang/studio still reaches for what was removed', () => {
  const removed = ['AC_PLANS', 'StudioPricing', 'PlanCard', 'PriceCard'];
  const files = fs.readdirSync(studio, {withFileTypes:true})
    .filter(entry => entry.isFile() && /\.(jsx|js|html)$/.test(entry.name))
    .map(entry => entry.name);
  assert.ok(files.length >= surfaces.length, 'The Studio source directory did not read.');
  const dangling = [];
  for (const name of files) {
    const text = fs.readFileSync(path.join(studio, name), 'utf8');
    for (const identifier of removed) {
      if (text.includes(identifier)) dangling.push(`${name} references ${identifier}`);
    }
  }
  assert.deepEqual(dangling, [], `Removed identifiers are still referenced - a live ReferenceError:\n${dangling.join('\n')}`);
});

test('the account holds no quota or tier of its own: the graph answers, or the meter says so', () => {
  const account = source.get('studio-account.jsx');
  assert.match(account, /usage: \{ spend: 0, cap: null, ops: 0, opsCap: null, runs: 0/,
    'AC_SEED still seeds a spend or operations cap nobody granted.');
  assert.match(account, /: 'not available'\}/, 'acMeter has no "not available" rendering for a missing cap.');
  assert.match(account, /graphTier: live\.tier/);
  assert.match(account, /\{a\.graphTier && \(/, 'The SUBSCRIPTION block is not gated on the graph tier.');
  const exported = lines('studio-account.jsx').find(line => line.startsWith('Object.assign(window,'));
  assert.ok(exported, 'studio-account.jsx no longer exports its surfaces to window.');
  assert.equal(exported.includes('AC_PLANS'), false, 'AC_PLANS is still exported to window.');
  const tab = lines('studio-lm.jsx').find(line => line.includes("['account',"));
  assert.ok(tab && /graphTier/.test(tab), `The Account tab badge is not the graph tier: ${tab}`);
});

test('the Landing survives without its price strip; the pricing dialog is gone', () => {
  const suite = source.get('studio-suite.jsx');
  assert.match(suite, /^window\.StudioLanding = StudioLanding;$/m, 'StudioLanding is no longer exported.');
  assert.doesNotMatch(suite, /Pricing strip/, 'The Landing still carries its pricing strip.');
  assert.doesNotMatch(suite, /window\.StudioPricing/, 'StudioPricing is still exported.');
});
