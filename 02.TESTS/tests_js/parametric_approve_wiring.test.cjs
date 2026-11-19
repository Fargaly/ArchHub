// NOGRAPH parametric core loop (42bcfe22): HostExec, Connector, Rerun and dock Retry
// open the one Approve card when run returns approvalId (SPEC §11.5 / Book Approve card).
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const screens = fs.readFileSync(path.join(studio, 'ds_screens.jsx'), 'utf8');
const app = fs.readFileSync(path.join(studio, 'app.jsx'), 'utf8');
const dock = fs.readFileSync(path.join(studio, 'dock.jsx'), 'utf8');

function hostExecRunHandler(source) {
  const marker = 'data-host-exec=""';
  const start = source.indexOf(marker);
  assert.ok(start >= 0, 'HostExecNode present');
  const chunk = source.slice(start, start + 4500);
  const run = chunk.match(/\{runLabel\}<\/button>/);
  assert.ok(run, 'HostExec Run button present');
  const before = chunk.slice(0, run.index);
  assert.match(before, /approvalId/);
  assert.match(before, /u\.show\('Approve'/);
  assert.match(before, /api\.runNode\(n\.id\)/);
}

function connectorRunHandler(source) {
  const marker = 'data-connector-action=""';
  const start = source.indexOf(marker);
  assert.ok(start >= 0, 'ConnectorActionNode present');
  const chunk = source.slice(start, start + 4500);
  const run = chunk.match(/>Run<\/button>/);
  assert.ok(run, 'Connector Run button present');
  const before = chunk.slice(0, run.index);
  assert.match(before, /approvalId/);
  assert.match(before, /u\.show\('Approve'/);
  assert.match(before, /api\.runNode\(n\.id\)/);
}

test('HostExec Run opens Approve when approvalId returns', () => {
  hostExecRunHandler(screens);
});

test('Connector action Run opens Approve when approvalId returns', () => {
  connectorRunHandler(screens);
});

test('Node menu Rerun opens Approve when approvalId returns', () => {
  assert.match(app, /function appShellRerun60\(/);
  const start = app.indexOf('function appShellRerun60(');
  const chunk = app.slice(start, start + 700);
  assert.match(chunk, /approvalId/);
  assert.match(chunk, /u\.show\('Approve'/);
  assert.match(chunk, /api\.runNode\(n\.id\)/);
  assert.doesNotMatch(chunk, /saved\(\(\)\s*=>\s*api\.runNode/);
});

test('Workshop dock Retry opens Approve when approvalId returns', () => {
  const start = dock.indexOf('const retry =');
  assert.ok(start >= 0, 'dock retry present');
  const chunk = dock.slice(start, start + 500);
  assert.match(chunk, /api\.runNode\(row\.id\)/);
  assert.match(chunk, /approvalId/);
  assert.match(chunk, /u\.show\('Approve'/);
});

test('toolbar and agentwork Run already open Approve (baseline)', () => {
  assert.match(screens, /agentWork\?\.runnable[\s\S]{0,280}approvalId[\s\S]{0,80}u\.show\('Approve'/);
  assert.match(screens, /t\?\.approvalId[\s\S]{0,120}u\.show\('Approve'/);
});
