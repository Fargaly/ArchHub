// R35: a record parameter is edited field by field with typed widgets; an edit saves a record, never a string.
'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const root = path.resolve(__dirname, '..', '..');
const babelContext = {}; vm.createContext(babelContext);
vm.runInContext(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/vendor/babel.js'), 'utf8'), babelContext);

function load() {
  const saved = [];
  const stub = name => props => ({type: name, props});
  const React = {createElement: (type, props, ...children) => ({type, props: {...props, children}}), useState: v => [typeof v === 'function' ? v() : v, () => {}],
    useRef: v => ({current: v}), useEffect: () => {}, useLayoutEffect: () => {}, useMemo: f => f(), useCallback: f => f, useContext: () => null,
    useSyncExternalStore: (_s, get) => get(), createContext: () => ({Provider: stub('provider')}), memo: c => c, startTransition: f => f(), Fragment: 'fragment'};
  const api = {setNodeParam: (id, key, value) => { saved.push([id, key, value]); return Promise.resolve(); }};
  const UI = {A: new Proxy({rad: {}}, {get: (t, k) => k in t ? t[k] : '#000'}), D: {Toggle: stub('toggle'), Node: stub('node')}, api,
    useData: () => ({}), useApp: () => ({}), Btn: stub('button'), Chip: stub('chip')};
  const window = {UI, AH: {rad: {}, sp: {}}, ReactFlow: {Position: {}, useUpdateNodeInternals: () => () => {}, useStore: () => ''},
    ReactResizablePanels: {Group: stub('group'), Panel: stub('panel'), Separator: stub('separator')}, AHIcon: stub('icon'),
    getComputedStyle: () => ({getPropertyValue: () => ''}), registerActions: () => {}};
  window.window = window;
  const context = vm.createContext({window, React, console, setTimeout, clearTimeout, document: {documentElement: {}, querySelector: () => null}});
  const code = babelContext.Babel.transform(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/ds_screens.jsx'), 'utf8'), {presets: ['react']}).code;
  vm.runInContext(code, context);
  return {ValueWidget: window.UI.ValueWidget, saved};
}
const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree, ...[tree.props?.children].flat(Infinity).flatMap(nodes)];
const u = {act: fn => Promise.resolve(fn())};

// Render function components (the record's fields are the same ValueWidget) so the tree is what the page draws.
const render = tree => {
  if (!tree || typeof tree !== 'object') return tree;
  if (typeof tree.type === 'function') return {...render(tree.type(tree.props)), rendered: tree.type.name, from: tree.props};
  return {...tree, props: {...tree.props, children: [tree.props?.children].flat(Infinity).map(render)}};
};
const field = (tree, name) => nodes(tree).find(n => n.props?.['data-object-field'] === name);
const plain = value => JSON.parse(JSON.stringify(value));   // records made inside the page's realm, compared by value

test('a record shows each field in the same typed widget, and a field edit saves the whole record', async () => {
  const {ValueWidget, saved} = load();
  const value = {width: 3.5, label: 'Door', fire_rated: true, finishes: ['paint'], frame: {depth: 0.1, material: 'steel'},
    note: null, mixed: [1, 'a']};
  const tree = render(ValueWidget({n: {id: 'n1', title: 'Door'}, p: {key: 'size', editable: true, type: 'text'}, value, u}));
  assert.ok(tree.props.className.includes('v48-object-widget'));
  const widget = name => nodes(field(tree, name)).find(n => n.rendered === 'ValueWidget');
  assert.equal(widget('width').type, 'input');
  assert.equal(widget('width').props.type, 'number');
  assert.equal(widget('label').props.type, 'text');
  assert.equal(widget('fire_rated').type, 'toggle');                                     // the existing yes/no widget
  assert.ok(widget('finishes').props.className.includes('v48-list-widget'));              // the existing list widget
  assert.ok(widget('frame').props.className.includes('v48-object-widget'));               // a nested record, editable
  for (const name of ['note', 'mixed']) assert.ok(nodes(field(tree, name)).some(n => n.props?.['data-kept'] === ''));
  widget('width').props.onChange({target: {value: '4.25', valueAsNumber: 4.25}});
  widget('label').props.onChange({target: {value: 'Fire door'}});
  widget('fire_rated').props.onCheckedChange(false);
  const depth = nodes(widget('frame')).find(n => n.props?.['data-object-field'] === 'depth');
  nodes(depth).find(n => n.rendered === 'ValueWidget').props.onChange({target: {value: '0.12', valueAsNumber: 0.12}});
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  assert.deepEqual(plain(saved), [
    ['n1', 'size', {...value, width: 4.25}],
    ['n1', 'size', {...value, label: 'Fire door'}],
    ['n1', 'size', {...value, fire_rated: false}],
    ['n1', 'size', {...value, frame: {depth: 0.12, material: 'steel'}}],      // note and mixed kept untouched
  ]);
});

test('lists and plain values keep their own widgets', () => {
  const {ValueWidget} = load();
  const list = ValueWidget({n: {id: 'n', title: 'N'}, p: {key: 'k', editable: true, type: 'text'}, value: ['a'], u});
  assert.ok(list.props.className.includes('v48-list-widget'));
  const number = ValueWidget({n: {id: 'n', title: 'N'}, p: {key: 'k', editable: true, type: 'number'}, value: 2, u});
  assert.equal(number.type, 'input');
});
