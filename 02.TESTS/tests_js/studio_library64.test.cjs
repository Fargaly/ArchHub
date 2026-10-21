const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const studio = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'), 'utf8');
const registry = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/node-registry.jsx'), 'utf8');
const libraryEngines = fs.readFileSync(path.join(root, '01.APP/nodelang/library_engines.py'), 'utf8');
const renderScript = fs.readFileSync(path.join(root, '03.TOOLS/tools/render_library64_after.mjs'), 'utf8');
const servedLibrary = JSON.parse(execFileSync(process.env.PYTHON || 'python', [
  '-c',
  'import json; from nodelang.library_engines import library_catalogue; print(json.dumps(library_catalogue()))',
], {cwd: root, encoding: 'utf8'}));
const servedItems = servedLibrary.flatMap(group => (group.items || []).filter(item => item.hidden !== true).map(item => ({...item, sourceCat: group.cat})));

const slice = (from, to) => {
  const start = studio.indexOf(from);
  const end = studio.indexOf(to, start);
  assert.ok(start > 0 && end > start, from + ' slice exists');
  return studio.slice(start, end);
};

const librarySurface = slice('// ─── Library panel — primary drag source ───', '// ─── Skills panel');
const modalSurface = slice('const NodeLibrary = ({ onClose, addNodeFromLibrary', '// ──────────────────────── NODE RAIL');
const evalLibraryHelpers = () => {
  const start = studio.indexOf('const LIBRARY_FAMILIES =');
  const end = studio.indexOf('const LibraryTile =', start);
  assert.ok(start > 0 && end > start, 'library helpers slice exists');
  const module = {exports: {}};
  const visibility = slice('const visibleLibraryGroups = ', 'const withHistoryLibrary = ');
  vm.runInNewContext(visibility + '\n' + studio.slice(start, end) + '\nmodule.exports = { libraryDisplayGroups, libraryPortSummary, librarySource, libraryTotal };', {
    module,
    window: {},
    Set,
    Object,
    String,
    Array,
  });
  return module.exports;
};

test('LIBRARY-64 categories render from registry metadata and live catalogue groups', () => {
  for (const cat of ['host', 'input', 'trigger', 'shape', 'transform', 'document', 'logic', 'ai', 'agent', 'watch', 'check', 'output']) {
    assert.match(registry, new RegExp(`${cat}:\\s*\\{[^}]*label:`), cat + ' category is in node-registry.jsx');
  }
  assert.match(studio, /const studioCategory = name => CAT\[name\] \|\| CAT\[String\(name \|\| ''\)\.toLowerCase\(\)\]/);
  assert.match(librarySurface, /const library = libraryDisplayGroups\(librarySource\(projected\)\)/);
  assert.doesNotMatch(librarySurface, /withHistoryLibrary\(/, 'left Library panel must not add non-catalogue cards');
  assert.match(librarySurface, /const LIBRARY_CATEGORY_ORDER = \['host', 'input', 'trigger', 'shape', 'transform', 'document', 'logic', 'ai', 'agent', 'watch', 'check', 'output'\]/);
  assert.match(librarySurface, /const custom = Object\.keys\(buckets\)/);
  assert.match(librarySurface, /return \[\.\.\.known, \.\.\.custom\]/);
  assert.match(librarySurface, /const c = studioCategory\(group\.cat\)/);
  assert.match(librarySurface, /<LibraryTile cat=\{c\}/);
  assert.match(librarySurface, /background:cat\.col/);
  assert.doesNotMatch(modalSurface, /Object\.entries\(CAT\)/, 'modal categories come from live library groups, not a stale registry loop');
});

test('LIBRARY-64 p3 keeps future registry categories after the known order', () => {
  const {libraryDisplayGroups} = evalLibraryHelpers();
  const groups = libraryDisplayGroups([
    {cat:'shape', items:[{id:'known-shape', title:'Shape item'}]},
    {cat:'future_custom', items:[{id:'future-node', title:'Future node'}]},
  ]);
  assert.equal(JSON.stringify(groups.map(group => group.cat)), JSON.stringify(['shape', 'future_custom']));
  assert.equal(groups[1].items[0].id, 'future-node');
});

test('LIBRARY-64 rows show human names only and never engine ids as chrome text', () => {
  assert.match(librarySurface, /const title = libraryTitle\(it\)/);
  assert.match(librarySurface, /const sub = librarySub\(it, cat\)/);
  assert.match(librarySurface, /\{title\}<\/div>/);
  assert.match(librarySurface, /\{sub\}<\/div>/);
  assert.doesNotMatch(librarySurface, /\{it\.id\}<\/(?:span|div|button)>/);
  assert.doesNotMatch(librarySurface, /\{it\.engine\}<\/(?:span|div|button)>/);
  assert.doesNotMatch(librarySurface, /NODES\s*·\s*CLICK TO ADD/);
  assert.match(librarySurface, /libraryHumanText = value => String\(value \|\| ''\)\.replace\(\/\[_-\]\+\/g, ' '\)/);
});

test('LIBRARY-64 every row adds a node in one click and keeps drag payloads', () => {
  const item = slice('const NodeLibItem = ({ it, cat, catId, selected = false, onAdd, disabled = false }) => {', '// ─── Skills panel');
  assert.match(item, /<window\.AH_DS\.Btn type="button"/);
  assert.match(item, /onClick=\{onAdd\}/);
  assert.doesNotMatch(item, /onDoubleClick/);
  assert.match(item, /draggable=\{!disabled\}/);
  assert.match(item, /application\/x-lm-node/);
  assert.match(item, /\.\.\.it, cat: catId/);
});

test('LIBRARY-64 uses the served catalogue including NODES-NEXT10, not plate sample data', () => {
  for (const item of ['b_all_category', 'b_get_parameter', 'r_xl_range', 'text_ops', 'math_expression', 'g_rule_check']) {
    assert.ok(servedItems.some(row => row.id === item), item + ' appears in the served catalogue source');
  }
  assert.ok(servedItems.length >= 70, 'court fixture sees the current full served registry count');
  assert.equal(new Set(servedItems.map(item => item.id)).size, servedItems.length, 'every served registry node id appears exactly once');
  assert.ok(servedItems.every(item => item.ports && Array.isArray(item.ports.source) && Array.isArray(item.ports.target)), 'served cards include projected port metadata');
  assert.match(renderScript, /library_catalogue/);
  assert.match(renderScript, /Search \$\{registryCount\} nodes/);
  assert.doesNotMatch(renderScript, /const library = \[/, 'render script must not ship a short hardcoded catalogue fixture');
  for (const sample of ['Nile_Tower', 'Nile Tower', 'Omar', 'sara@firm.com', 'Clinic', '46 doors', 'L3-D001', '09:14', 'run #48']) {
    assert.doesNotMatch(studio, new RegExp(sample.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'), sample + ' is not shipped in studio-lm.jsx');
  }
});

test('LIBRARY-64 p4 opens matching categories during search and exposes real socket glyphs', () => {
  assert.match(librarySurface, /useState\(\(\) => \(\{shape:true\}\)\)/, 'only Shape is open on first render');
  assert.match(librarySurface, /const open = q \? true : !!openCats\[group\.cat\]/, 'search must mount every category with matches');
  assert.match(librarySurface, /placeholder=\{`Search \$\{libraryTotal\(groups\)\} nodes`\}/);
  assert.match(librarySurface, /const libraryPortSummary = item =>/);
  assert.match(librarySurface, /item\?\.ports/);
  assert.match(librarySurface, /data-library-port-glyphs/);
  assert.match(librarySurface, /'▷'/);
  assert.match(librarySurface, /'◇'/);
  assert.match(librarySurface, /'●'/);
  assert.match(librarySurface, /'\?'/);
  assert.doesNotMatch(librarySurface, /LIBRARY_LIST_PORTS|LIBRARY_EVENT_PORTS|endsWith\('s'\)|includes\('event'\)/);
});

test('LIBRARY-64 p3 port glyphs use declared type and cardinality metadata', () => {
  const {libraryPortSummary} = evalLibraryHelpers();
  const ports = libraryPortSummary({ports:{
    target:[
      {id:'declared_list', type:'any', cardinality:'many'},
      {id:'declared_single', type:'text', cardinality:'one'},
    ],
    source:[
      {id:'declared_trigger', type:'trigger', cardinality:'one'},
    ],
  }});
  assert.equal(JSON.stringify(ports.map(port => port.glyph)), JSON.stringify(['◇', '●', '▷']));
});

test('LIBRARY-64 p4 unknown port metadata makes no one-cardinality or shape claim', () => {
  assert.doesNotMatch(libraryEngines, /LIBRARY_ITEM_INTERFACES/, 'UI-side port table must not become a second type authority');
  const {libraryPortSummary} = evalLibraryHelpers();
  const ports = libraryPortSummary({sockets:{target:['in'], source:['out']}});
  assert.equal(JSON.stringify(ports.map(port => port.glyph)), JSON.stringify(['?', '?']));
  assert.equal(JSON.stringify(ports.map(port => port.label)), JSON.stringify(['unknown in', 'unknown out']));

  const unknownRows = servedItems.flatMap(item => ['target', 'source'].flatMap(side =>
    (item.ports?.[side] || []).map(port => ({item:item.id, side, ...port}))
  )).filter(port => port.type === 'unknown' || port.cardinality === 'unknown');
  assert.ok(unknownRows.length > 0, 'served rows preserve unknown metadata instead of inventing any/one');
  assert.ok(unknownRows.every(port => port.type === 'unknown' && port.cardinality === 'unknown'));
  assert.ok(!unknownRows.some(port => port.type === 'any' && port.cardinality === 'one'));
});

test('LIBRARY-64 p4 row ports equal the served canonical interface for every row', () => {
  const expected = JSON.parse(execFileSync(process.env.PYTHON || 'python', [
    '-c',
    [
      'import json',
      'from nodelang.library_engines import library_catalogue, library_item_ports',
      'rows=[[item["id"], item["ports"], library_item_ports(item["id"], item["engine"], item.get("title", ""))] for group in library_catalogue() for item in group.get("items", [])]',
      'print(json.dumps(rows))',
    ].join('; '),
  ], {cwd: root, encoding: 'utf8'}));
  for (const [id, served, canonical] of expected) {
    assert.deepEqual(served, canonical, id + ' ports come from canonical interface projection');
  }
});

test('LIBRARY-64 p3 tabs route to live panels and the runs badge is not hardcoded', () => {
  assert.match(librarySurface, /data-library-tab=\{route\}/);
  assert.match(librarySurface, /onSwitchPanel \? \(\) => onSwitchPanel\('chats'\)/);
  assert.match(librarySurface, /onSwitchPanel \? \(\) => onSwitchPanel\('skills'\)/);
  assert.match(librarySurface, /onSwitchPanel \? \(\) => onSwitchPanel\('runs'\)/);
  assert.match(librarySurface, /runsWaiting > 0/);
  assert.doesNotMatch(librarySurface, />3<\/span>/);
});

test('LIBRARY-64 p2 drag ghost names the node before governed addNodeFromLibrary drop', () => {
  assert.match(librarySurface, /window\.__archhubDraggingLibraryTitle = libraryTitle\(it\)/);
  assert.match(studio, /Adding \{dropTarget\.title \|\| 'node'\}/);
  assert.match(studio, /addNodeFromLibrary && addNodeFromLibrary\(payload, c\.x - 110, c\.y - 30\)/);
});

test('LIBRARY-64 chrome is Inter/sans only inside the Library surface', () => {
  assert.doesNotMatch(librarySurface, /LM\.mono|LM\.serif|marketingSerif/);
  assert.doesNotMatch(modalSurface, /LM\.mono|LM\.serif|marketingSerif/);
  assert.match(librarySurface, /fontFamily:LM\.sans/);
  assert.match(modalSurface, /fontFamily:LM\.sans/);
});


test('compatibility aliases stay outside visible library groups and counts without losing raw metadata', () => {
  const {libraryDisplayGroups, librarySource, libraryTotal} = evalLibraryHelpers();
  const canonical = {id:'w_workshop', title:'Workshop', engine:'workshop.conversation'};
  const legacy = {id:'revit.sessions', title:'Sessions compatibility', engine:'revit.sessions', hidden:true};
  const raw = [{cat:'logic', items:[canonical, legacy]}, {cat:'Legacy only', items:[{...legacy, id:'old-only'}]}];
  const visible = librarySource({library:raw});
  assert.deepEqual(JSON.parse(JSON.stringify(visible)), [{cat:'logic', items:[canonical]}]);
  assert.equal(libraryTotal(raw), 1, 'aliases do not inflate search counts');
  assert.deepEqual(JSON.parse(JSON.stringify(libraryDisplayGroups(raw).flatMap(group => group.items.map(item => item.id)))), ['w_workshop']);
  assert.equal(raw[0].items[1], legacy, 'graph-held alias metadata remains available by its exact identity');
  assert.equal(raw[0].items.length, 2, 'the API catalogue is never mutated to hide aliases');
});
