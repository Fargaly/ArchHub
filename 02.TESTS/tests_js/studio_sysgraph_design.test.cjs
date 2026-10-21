const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const studio = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'), 'utf8');
const library = fs.readFileSync(path.join(root, '01.APP/nodelang/library_engines.py'), 'utf8');
const pipeline = fs.readFileSync(path.join(root, '01.APP/nodelang/pipeline_engines.py'), 'utf8');

const slice = (startNeedle, endNeedle) => {
  const start = studio.indexOf(startNeedle);
  const end = studio.indexOf(endNeedle, start + startNeedle.length);
  assert.ok(start >= 0, startNeedle + ' exists');
  assert.ok(end > start, endNeedle + ' follows ' + startNeedle);
  return studio.slice(start, end);
};

test('S1: Settings opens as the DSYS-065 System graph with real system cards and wires', () => {
  const settings = slice('const Settings =', 'const SystemMiniGraph =');
  for (const banned of ['SETTINGS54_' + 'NODE', 'SETTINGS54_' + 'SYSTEM_GRAPH', 'SETTINGS54_' + 'SYSTEM_WIRES']) {
    assert.equal(studio.includes(banned), false);
  }
  assert.match(studio, /settings54SystemNodes = graph => \(graph\?\.nodes \|\| \[\]\)\.filter\(node => node\?\.application === true\)/);
  assert.match(studio, /settings54SystemWires = \(graph, nodes\) =>/);
  assert.match(settings, /data-settings54-shell/);
  assert.match(settings, /data-settings54-graph/);
  assert.match(studio, /data-settings54-node-card/);
  assert.match(studio, /data-settings54-node-id/);
  assert.match(settings, /data-settings54-wire/);
  assert.match(settings, /pmPersistValue/);
  assert.match(settings, /moveMany\(changed, revision, before, 'arrange'\)|moveTopologyNodes\(changed, revision, before, 'arrange'\)/);
  assert.doesNotMatch(settings, /Add node/);
  assert.doesNotMatch(settings, /data-settings-compat-tabs/);
});

test('S1: System is not injected as a Studio session tab or Hub button', () => {
  assert.doesNotMatch(studio, /systemNodeSession\(/, 'no synthetic System session row helper remains');
  const header = slice('const WsHeader =', 'const WsTab =');
  const tabLoop = header.slice(header.indexOf('openTabs.map'), header.indexOf('New session after the tabs'));
  assert.doesNotMatch(tabLoop, /System|system:/, 'System is not rendered by the Studio session tab loop');
  assert.doesNotMatch(header, /workshopModeSegments|WorkshopConversationMenu/);
  const hub = slice('const SettingsHub =', 'const SHead =');
  assert.doesNotMatch(hub, /System graph|openToolGraphFromHub\('system'\)/);
});

test('S2: opened System graph uses Settings breadcrumb and arrange toast contract', () => {
  const header = slice('const WsHeader =', 'const WsTab =');
  assert.match(header, /Settings/);
  assert.match(header, /System/);
  assert.match(header, /ArchHub application/);
  const arrange = slice('const canvasArrangePositions =', 'const CANVAS_LAYOUT_COALESCE_MS');
  assert.match(arrange, /bary/i);
  assert.match(studio, /Arranged .* nodes .* layers .* 0 overlaps .* 0 clipped .* crossings .* Undo/);
  assert.match(studio, /pinned .* in place|kept .* pinned/i);
});

test('S3/S4: group cards expose boundary sockets and normal node actions, with no frame UI', () => {
  const nodeCard = slice('const NodeRenderer =', 'const MemoNodeRenderer =');
  assert.match(nodeCard, /member_count|memberCount/);
  assert.match(nodeCard, /boundary/i);
  assert.match(nodeCard, /Open/);
  const rail = studio.slice(studio.indexOf('const NodeRail ='));
  assert.match(rail, /Interface/);
  assert.match(rail, /Exposed parameters/);
  assert.match(rail, /Ungroup/);
  assert.match(rail, /Rename/);
  assert.doesNotMatch(studio, /group-frame|data-group-frame|GroupFrame/);
});

test('S3/S4: selection bar offers grouping, selected arrange, and connected selection', () => {
  assert.match(studio, /Group \{?selectedIds\.length\}? nodes|Group .* nodes/);
  assert.match(studio, /Ctrl\+G/);
  assert.match(studio, /Arrange selected/);
  assert.match(studio, /Select connected/);
});

test('S5: one current rail replaces the retired rail; tool engines stay off the handoff catalogue', () => {
  const rail = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/shared-data.jsx'), 'utf8').slice(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/shared-data.jsx'), 'utf8').indexOf('window.ARCHHUB_APP_RAIL ='));
  for (const name of ['Home', 'Chats', 'Workshop', 'Canvas', 'Library', 'Docs', 'Settings', 'Account']) assert.match(rail, new RegExp(name));
  assert.match(studio, /Chats:\s*onChats/, 'the current rail opens the existing Chats route');
  for (const name of ['Skills', 'Search', 'Documentation', 'Brain', 'BABOOM', 'Connectors', 'Cloud']) assert.doesNotMatch(rail, new RegExp(name));
  assert.match(library, /\(\("tool\.",\), "tools"\)/, 'System tool engines retain their Tools category while the handoff catalogue uses canonical rows');
  for (const id of ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']) {
    assert.match(library, new RegExp('"tool_' + id + '"'));
    assert.match(pipeline, new RegExp('"tool\\.' + id + '"'));
  }
});

test('S6: Settings BABOOM and the BABOOM node share one parameter source and Settings opens the node', () => {
  const settings = slice('const SettingsBaboom =', 'const SettingsCloudStatus =');
  assert.match(studio, /settings54NodeGroup\(selectedNode\) !== 'permissions'/);
  assert.match(studio, /settings54ParamKey\(row\)/);
  assert.match(studio, /pmPersistValue\(node, key, value\)/);
  assert.match(settings, /Open as node/);
  assert.match(settings, /onOpenToolGraph\?\.\('baboom'\)|openToolGraphFromSettings\('baboom'\)/);
  assert.doesNotMatch(settings, /baboomMaxSpeaks|Speech budget|Speaks at most/, 'no unenforced speech-budget surface');
  assert.match(library, /"tool_baboom": \{"engine": "tool\.baboom"/);
  assert.match(library, /"start_with_archhub": True/);
  assert.doesNotMatch(library, /["']speech_budget_per_hour["']:/, "dead speech budget is absent from the catalogue");
});

test('S7: System graph states cover loading, empty scope, error, and refused action', () => {
  assert.match(studio, /Reading the application graph/);
  assert.match(studio, /This group has no nodes yet/);
  assert.match(studio, /The application graph could not be read/);
  assert.match(studio, /Arrange kept \{pinnedCount\} pinned/);
  assert.match(studio, /Read again/);
  assert.match(studio, /Back to Settings/);
});
