const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const studio = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
const library = fs.readFileSync(path.join(root, 'nodelang/library_engines.py'), 'utf8');
const pipeline = fs.readFileSync(path.join(root, 'nodelang/pipeline_engines.py'), 'utf8');

const slice = (startNeedle, endNeedle) => {
  const start = studio.indexOf(startNeedle);
  const end = studio.indexOf(endNeedle, start + startNeedle.length);
  assert.ok(start >= 0, startNeedle + ' exists');
  assert.ok(end > start, endNeedle + ' follows ' + startNeedle);
  return studio.slice(start, end);
};

test('S1: Settings has System as the second tab, with badge, mini preview, and one graph action', () => {
  const settings = slice('const Settings =', 'const SettingsHub =');
  assert.match(settings, /\['hub',\s*'Hub'/);
  assert.match(settings, /\['system',\s*'System',\s*systemNodeBadge/);
  assert.ok(settings.indexOf("['hub',") < settings.indexOf("['system',"), 'System follows Hub');
  assert.ok(settings.indexOf("['system',") < settings.indexOf("['account',"), 'System is before Account');
  assert.match(settings, /tab === 'system'\s*&&\s*<SettingsSystem/);
  const panel = slice('const SettingsSystem =', 'const SettingsHub =');
  assert.match(panel, /data-settings-system-preview/);
  assert.match(panel, /Open the System graph/);
  assert.doesNotMatch(panel, /SettingsHub/);
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
  assert.match(studio, /pinned .* skipped|skipped .* pinned/i);
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

test('S5: rail has only Chats, Nodes, Skills, Search, Docs and Settings; tools are catalogue nodes', () => {
  const rail = slice('const IconRail =', 'const RailIcon =');
  for (const name of ['Chats', 'Nodes', 'Skills', 'Search', 'Documentation', 'Settings']) assert.match(rail, new RegExp(name));
  for (const name of ['Studio', 'Workshop', 'Brain', 'BABOOM', 'Connectors', 'Cloud']) assert.doesNotMatch(rail, new RegExp(name));
  assert.match(library, /\("tools",/);
  for (const id of ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']) {
    assert.match(library, new RegExp('"tool_' + id + '"'));
    assert.match(pipeline, new RegExp('"tool\\.' + id + '"'));
  }
});

test('S6: Settings BABOOM and the BABOOM node share one parameter source and Settings opens the node', () => {
  const settings = slice('const SettingsBaboom =', 'const SettingsCloudStatus =');
  assert.match(settings, /parameters of the BABOOM node|same binding/i);
  assert.match(settings, /Open as node/);
  assert.match(settings, /onOpenToolGraph\?\.\('baboom'\)|openToolGraphFromSettings\('baboom'\)/);
  assert.match(settings, /baboomMaxSpeaks\(personal\)/);
  assert.match(library, /"tool_baboom": \{"engine": "tool\.baboom"/);
  assert.match(library, /"start_with_archhub": True/);
  assert.match(library, /"speech_budget_per_hour": 2/);
});

test('S7: System graph states cover loading, empty scope, error, and refused action', () => {
  assert.match(studio, /Reading the application graph/);
  assert.match(studio, /This group has no nodes yet/);
  assert.match(studio, /The application graph could not be read/);
  assert.match(studio, /Arranged did not move .* cards/);
  assert.match(studio, /Read again/);
  assert.match(studio, /Back to Settings/);
});
