import fs from 'node:fs';
import path from 'node:path';

export const steps = [
  'NoGraph opens Home',
  'Settings opens with a category sidebar',
  'Home is reachable from Settings',
  'New workflow opens an editable Canvas',
  'Library places a Number node on Canvas',
  'Undo removes and Redo restores the Number node',
  'Edit, undo and redo the Number value',
  'Connect Number to Convert through their sockets',
  'Save and reopen the typed wire',
  'Expose, edit, and return a parameter while preserving its saved value',
];

export default async function ({step, js, until, clickText, cdp, rectOf, out}) {
  const fixture = path.join(out, 'typed-wire.archhub');
  const home = () => js("Boolean(document.querySelector('[data-home-page]'))");
  await step(steps[0], async () => {
    const pass = await until(home, Boolean);
    return {pass, got: {path: await js('location.pathname')}, why: pass ? '' : 'Home was not rendered'};
  });
  await step(steps[1], async () => {
    if (!await clickText('Settings')) return {pass: false, why: 'Settings control missing'};
    const got = await until(() => js(`(() => {
      const surface = document.querySelector('[data-screen^="settings"]');
      if (!surface) return null;
      const sidebar = surface.querySelector('aside, [role="navigation"], nav');
      return {screen: surface.dataset.screen, categories: sidebar?.innerText || ''};
    })()`), Boolean);
    const pass = Boolean(got?.categories.includes('Appearance') && got?.categories.includes('System'));
    return {pass, got, why: pass ? '' : 'Settings categories were not rendered in a sidebar'};
  });
  await step(steps[2], async () => {
    const clicked = await clickText('Home');
    const pass = clicked && await until(home, Boolean);
    return {pass, why: pass ? '' : 'Home did not reopen'};
  });
  await step(steps[3], async () => {
    const focused = await js(`(() => {
      const button = [...document.querySelectorAll('[data-home-page] button')].find(e => !e.disabled && e.getClientRects().length);
      button?.focus();
      return !!button && document.activeElement === button;
    })()`);
    if (!focused) return {pass: false, why: 'Home had no focusable control for Ctrl+N'};
    for (const type of ['rawKeyDown', 'keyUp']) {
      await cdp('Input.dispatchKeyEvent', {type, key: 'n', code: 'KeyN', windowsVirtualKeyCode: 78, modifiers: 2});
    }
    const got = await until(() => js(`(() => {
      const canvas = [...document.querySelectorAll('[aria-label="Workflow canvas"]')].find(e => e.getClientRects().length);
      const graph = window.ArchHubAPI?.getSnapshot().graph;
      return {canvas: Boolean(canvas), name: graph?.name || '', nodes: graph?.nodes?.length ?? null};
    })()`), value => value?.canvas && value.name === 'Untitled');
    const pass = Boolean(got?.canvas && got.name === 'Untitled' && got.nodes === 0);
    return {pass, got, why: pass ? '' : 'Ctrl+N did not show the new workflow on Canvas'};
  });
  const nodes = () => js("window.ArchHubAPI.getSnapshot().graph.nodes.map(n=>({id:n.id,title:n.title}))");
  const shortcut = async (key, code, windowsVirtualKeyCode, modifiers) => {
    for (const type of ['rawKeyDown', 'keyUp']) {
      await cdp('Input.dispatchKeyEvent', {type, key, code, windowsVirtualKeyCode, modifiers});
    }
  };
  await step(steps[4], async () => {
    if (!await clickText('Search nodes', 'input')) return {pass: false, why: 'Library search missing'};
    await cdp('Input.insertText', {text: 'Number'});
    if (!await until(() => js("Boolean(document.querySelector('[aria-label=\"Add Number\"]'))"), Boolean)
        || !await clickText('Add Number')) return {pass: false, why: 'Number node missing from the Library'};
    const got = await until(nodes, value => value.some(n => n.title === 'Number'));
    const pass = got.length === 1 && got[0].title === 'Number'
      && await until(() => js("Boolean(document.querySelector('[data-graph-node]'))"), Boolean);
    return {pass, got, why: pass ? '' : 'The Number node did not render on Canvas'};
  });
  await step(steps[5], async () => {
    const before = await nodes();
    if (before.length !== 1) return {pass: false, why: 'No single placed node to restore'};
    await js("document.activeElement.blur()");
    await shortcut('z', 'KeyZ', 90, 2);
    const undone = await until(nodes, value => value.length === 0);
    await shortcut('z', 'KeyZ', 90, 10);
    const restored = await until(nodes, value => value.length === 1 && value[0].id === before[0].id);
    const pass = undone.length === 0 && restored.length === 1 && restored[0].id === before[0].id;
    return {pass, got: {before, undone, restored}, why: pass ? '' : 'Undo and Redo did not restore the same node'};
  });
  await step(steps[6], async () => {
    const read = () => js(`(() => {
      const node = window.ArchHubAPI.getSnapshot().graph.nodes.find(n => n.title === 'Number');
      return node && {id: node.id, value: node.params.value};
    })()`);
    const before = await read();
    await until(() => js("Boolean(document.querySelector('input[aria-label=\"Number value\"]'))"), Boolean, 20, 200);
    if (!before || !await clickText('Number value', 'input')) return {pass: false, why: 'Number value input missing'};
    const value = before.value === 7 ? 8 : 7;
    await shortcut('a', 'KeyA', 65, 2);
    await cdp('Input.insertText', {text: String(value)});
    const matches = (state, expected) => state?.id === before.id && state.value === expected;
    const edited = await until(read, state => matches(state, value));
    await js("document.activeElement.blur()");
    await shortcut('z', 'KeyZ', 90, 2);
    const undone = await until(read, state => matches(state, before.value));
    await shortcut('z', 'KeyZ', 90, 10);
    const restored = await until(read, state => matches(state, value));
    const pass = matches(edited, value) && matches(undone, before.value) && matches(restored, value);
    return {pass, got: {before, edited, undone, restored}, why: pass ? '' : 'Number value history did not match'};
  });
  await step(steps[7], async () => {
    fs.writeFileSync(fixture, JSON.stringify({
      format:'archhub', version:1, id:'a9738cc8-015e-4f9d-a349-079a52fafc4b',
      title:'Typed socket acceptance', viewport:{x:0,y:0,zoom:1},
      nodes:[
        {id:'number',item:'n_number',type:'data.constant',title:'Number',params:{value:7},position:{x:80,y:160}},
        {id:'convert',item:'data.convert',type:'data.convert',title:'Convert',params:{target_type:'text'},position:{x:500,y:160}},
      ],
      wires:[], groups:[], notes:[],
    }), {flag:'wx'});
    await js(`window.ArchHubAPI.openSession(${JSON.stringify(fixture)})`);
    const placed = await until(nodes, value => value.length === 2);
    if (placed.length !== 2) return {pass:false, got:placed, why:'The two-node fixture did not open'};
    const endpoint = title => `Array.from(document.querySelectorAll('[data-port-key]')).find(e=>e.getAttribute('aria-label')?.startsWith(${JSON.stringify(title)}))`;
    const source = endpoint('Number out ');
    const target = endpoint('Convert in ');
    await until(() => rectOf(target), Boolean);
    await clickText('Overview') || await clickText('Fit');
    const a = await rectOf(source), b = await rectOf(target);
    if (!a || !b) return {pass: false, got:{source:a,target:b}, why: 'The two socket controls did not render'};
    await cdp('Input.dispatchMouseEvent', {type:'mousePressed', x:a.x, y:a.y, button:'left', buttons:1, clickCount:1});
    for (const fraction of [.2, .5, .8, 1]) {
      await cdp('Input.dispatchMouseEvent', {type:'mouseMoved', x:a.x+(b.x-a.x)*fraction, y:a.y+(b.y-a.y)*fraction, buttons:1});
    }
    await cdp('Input.dispatchMouseEvent', {type:'mouseReleased', x:b.x, y:b.y, button:'left', clickCount:1});
    const got = await until(() => js(`(() => {
      const {nodes,wires}=window.ArchHubAPI.getSnapshot().graph;
      return wires.filter(w=>nodes.find(n=>n.id===w.from)?.title==='Number'&&nodes.find(n=>n.id===w.to)?.title==='Convert');
    })()`), wires => wires.length === 1);
    const pass = got.length === 1 && await until(() => js("Boolean(document.querySelector('[data-graph-wire]'))"), Boolean);
    return {pass, got, why: pass ? '' : 'The socket drag did not produce a visible wire'};
  });
  await step(steps[8], async () => {
    const wireId = await js("window.ArchHubAPI.getSnapshot().graph.wires[0]?.id");
    if (!wireId) return {pass:false, why:'No typed wire to save'};
    await js("document.querySelector('[aria-label=\"Workflow canvas\"]').focus()");
    await shortcut('s', 'KeyS', 83, 2);
    const saved = await until(() => {
      try { return JSON.parse(fs.readFileSync(fixture, 'utf8')).wires.find(w => w.id === wireId); }
      catch (error) { if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error; return null; }
    }, Boolean);
    if (!saved) return {pass:false, why:'The wire did not reach the saved file'};
    await js("window.ArchHubAPI.newSession()");
    const cleared = await js("window.ArchHubAPI.getSnapshot().graph.wires.length===0");
    await js(`window.ArchHubAPI.openSession(${JSON.stringify(fixture)})`);
    const reopened = await until(() => js(`Boolean(document.querySelector('[data-graph-wire="'+${JSON.stringify(wireId)}+'"]'))`), Boolean);
    const pass = cleared && reopened && saved.from.node === 'number' && saved.to.node === 'convert';
    return {pass, got:{cleared,reopened,wire:saved}, why:pass ? '' : 'The saved wire did not return with its endpoints'};
  });
  await step(steps[9], async () => {
    const read = () => js(`(() => {
      const {nodes,wires}=window.ArchHubAPI.getSnapshot().graph;
      const owner=nodes.find(n=>n.id==='number');
      const binding=nodes.find(n=>n.bind?.node===owner?.id&&n.bind?.param==='value');
      return {value:owner?.params.value, binding:binding?.id,
        linked:Boolean(binding&&wires.some(w=>w.from===binding.id&&w.to===owner.id&&w.toPort==='param:value')),
        original:wires.some(w=>w.from==='number'&&w.to==='convert')};
    })()`);
    const before = await read();
    if (!await clickText('value row actions') || !await clickText('Expose as node')) {
      return {pass:false, why:'The value row could not expose its parameter'};
    }
    const exposed = await until(read, state => state.linked);
    await clickText('Overview') || await clickText('Fit');
    if (!exposed?.linked || !await clickText('Increase Value')) {
      return {pass:false, got:exposed, why:'The bound parameter or its stepper was missing'};
    }
    const edited = await until(read, state => state.linked && state.value !== before.value);
    if (!edited?.linked || edited.value === before.value) return {pass:false, got:edited, why:'The stepper did not update its owner'};
    const reopen = async check => {
      await js('window.ArchHubAPI.saveSession()');
      await js('window.ArchHubAPI.newSession()');
      await js(`window.ArchHubAPI.openSession(${JSON.stringify(fixture)})`);
      return until(read, check);
    };
    const linked = await reopen(state => state.linked && state.binding === edited.binding && state.value === edited.value);
    if (!linked?.linked || linked.binding !== edited.binding || linked.value !== edited.value) {
      return {pass:false, got:linked, why:'The linked value or its binding did not reopen'};
    }
    if (!await clickText('Value row actions') || !await clickText('Return to inline parameter')) {
      return {pass:false, why:'The value row could not return its parameter inline'};
    }
    const inline = await until(read, state => !state.binding && state.value === edited.value);
    if (inline?.binding || inline?.value !== edited.value) {
      return {pass:false, got:inline, why:'The inline value did not survive demotion'};
    }
    const restored = await reopen(state => state.original && !state.binding && state.value === edited.value);
    const pass = restored?.original && !restored.binding && restored.value === edited.value;
    return {pass, got:{before,edited,linked,inline,restored}, why:pass ? '' : 'The inline value did not reopen'};
  });
}
